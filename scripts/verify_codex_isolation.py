#!/usr/bin/env python3
"""Run the signer isolation probe through the local Codex app-server sandbox."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Any, TextIO


CANARY_ENVIRONMENT = "THESIS_SIGNER_CANARY"
PERMISSION_PROFILE = "thesis-agent"


def _toml_string(value: str) -> str:
    return json.dumps(value)


def _config(repo_root: Path, codex_home: Path, signer_root: Path, socket_path: Path) -> str:
    return f'''default_permissions = "{PERMISSION_PROFILE}"

[permissions.{PERMISSION_PROFILE}]
description = "Hermes thesis agent without signer or Controller access."
extends = ":workspace"

[permissions.{PERMISSION_PROFILE}.workspace_roots]
{_toml_string(str(repo_root))} = true
{_toml_string(str(codex_home))} = true

[permissions.{PERMISSION_PROFILE}.filesystem]
{_toml_string(str(signer_root))} = "deny"

[permissions.{PERMISSION_PROFILE}.network]
enabled = false

[permissions.{PERMISSION_PROFILE}.network.unix_sockets]
{_toml_string(str(socket_path))} = "deny"

[shell_environment_policy]
inherit = "none"
ignore_default_excludes = false
set = {{ CODEX_HOME = {_toml_string(str(codex_home))} }}
'''


def _serve_canary(listener: socket.socket, stop: threading.Event) -> None:
    listener.settimeout(0.1)
    while not stop.is_set():
        try:
            connection, _ = listener.accept()
        except TimeoutError:
            continue
        except OSError:
            return
        else:
            connection.close()


def _send(stream: TextIO, method: str, request_id: int, params: dict[str, Any]) -> None:
    stream.write(json.dumps({"method": method, "id": request_id, "params": params}) + "\n")
    stream.flush()


def _response(stream: TextIO, request_id: int) -> dict[str, Any]:
    for line in stream:
        value = json.loads(line)
        if value.get("id") == request_id:
            return value
    raise RuntimeError("app-server exited before returning a response")


def _process_exit(stream: TextIO, process_handle: str) -> dict[str, Any]:
    for line in stream:
        value = json.loads(line)
        if (
            value.get("method") == "process/exited"
            and value.get("params", {}).get("processHandle") == process_handle
        ):
            return value["params"]
    raise RuntimeError("app-server exited before the escape-hatch probe completed")


def _parse_probe_result(result: dict[str, Any], source: str) -> dict[str, Any]:
    stdout = str(result.get("stdout", "")).strip()
    try:
        probe = json.loads(stdout)
    except json.JSONDecodeError as exc:
        diagnostic = str(result.get("stderr", "")).strip()[:1000]
        raise RuntimeError(
            f"{source} isolation probe did not return structured output "
            f"(exit={result.get('exitCode')}, stderr={diagnostic!r})"
        ) from exc
    return {
        "exit_code": result.get("exitCode"),
        "probe": probe,
        "verified": result.get("exitCode") == 0 and probe.get("isolated") is True,
    }


def verify(repo_root: Path, codex: str) -> dict[str, Any]:
    codex_executable = shutil.which(codex)
    if codex_executable is None:
        raise RuntimeError(f"Codex CLI not found: {codex}")
    with tempfile.TemporaryDirectory(prefix="thesis-isolation-") as temporary:
        root = Path(temporary)
        codex_home = root / "codex-home"
        signer_root = root / "signer"
        signer_path = signer_root / "envelope.canary"
        socket_path = root / "controller.sock"
        codex_home.mkdir(mode=0o700)
        signer_root.mkdir(mode=0o700)
        signer_path.write_text("public-isolation-canary", encoding="utf-8")
        signer_path.chmod(0o600)
        (codex_home / "config.toml").write_text(
            _config(
                repo_root.resolve(),
                codex_home.resolve(),
                signer_root.resolve(),
                socket_path.resolve(),
            ),
            encoding="utf-8",
        )

        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(socket_path))
        listener.listen(1)
        stop = threading.Event()
        server = threading.Thread(target=_serve_canary, args=(listener, stop), daemon=True)
        server.start()

        environment = os.environ.copy()
        environment["CODEX_HOME"] = str(codex_home)
        environment[CANARY_ENVIRONMENT] = "public-isolation-canary"
        process = subprocess.Popen(
            [
                codex_executable,
                "sandbox",
                "--permission-profile",
                PERMISSION_PROFILE,
                "--cd",
                str(repo_root),
                codex_executable,
                "app-server",
                "--stdio",
                "--strict-config",
            ],
            cwd=repo_root,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        try:
            probe_command = [
                sys.executable,
                "-m",
                "control_plane.isolation",
                "--environment-name",
                CANARY_ENVIRONMENT,
                "--signer-path",
                str(signer_path),
                "--controller-socket",
                str(socket_path),
            ]
            _send(
                process.stdin,
                "initialize",
                1,
                {
                    "clientInfo": {
                        "name": "thesis_isolation_verifier",
                        "title": "Thesis isolation verifier",
                        "version": "1",
                    },
                    "capabilities": {"experimentalApi": True},
                },
            )
            initialized = _response(process.stdout, 1)
            if "error" in initialized:
                raise RuntimeError(f"app-server initialization failed: {initialized['error']}")
            process.stdin.write(json.dumps({"method": "initialized", "params": {}}) + "\n")
            process.stdin.flush()
            _send(
                process.stdin,
                "command/exec",
                2,
                {
                    "command": probe_command,
                    "cwd": str(repo_root),
                    # The app-server itself already runs inside PERMISSION_PROFILE.
                    # Avoid unsupported nested Seatbelt application; the outer
                    # OS boundary must still contain even this broad inner mode.
                    "permissionProfile": ":danger-full-access",
                    "timeoutMs": 10000,
                    "outputBytesCap": 4096,
                },
            )
            command_response = _response(process.stdout, 2)
            if "error" in command_response:
                raise RuntimeError(f"command/exec failed: {command_response['error']}")

            escape_handle = "escape-hatch-probe"
            _send(
                process.stdin,
                "process/spawn",
                3,
                {
                    "command": probe_command,
                    "cwd": str(repo_root),
                    "processHandle": escape_handle,
                    "timeoutMs": 10000,
                    "outputBytesCap": 4096,
                },
            )
            spawn_response = _response(process.stdout, 3)
            if "error" in spawn_response:
                raise RuntimeError(f"process/spawn failed: {spawn_response['error']}")
            escape_result = _process_exit(process.stdout, escape_handle)
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            stop.set()
            listener.close()
            server.join(timeout=1)

        command_result = _parse_probe_result(command_response.get("result", {}), "command/exec")
        escape_probe = _parse_probe_result(escape_result, "process/spawn")
        return {
            "command_exec": command_result,
            "process_spawn_escape_hatch": escape_probe,
            "verified": command_result["verified"] and escape_probe["verified"],
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--codex", default="codex", help="Codex CLI executable")
    args = parser.parse_args(argv)
    result = verify(Path(__file__).resolve().parents[1], args.codex)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())

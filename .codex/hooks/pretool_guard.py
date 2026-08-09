#!/usr/bin/env python3
"""Translate Codex PreToolUse events into the repository's Claude guard schema."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


def deny(message: str) -> None:
    print(message.strip(), file=sys.stderr)
    raise SystemExit(2)


def repo_root(cwd: str) -> Path:
    try:
        value = subprocess.check_output(
            ["git", "-C", cwd, "rev-parse", "--show-toplevel"],
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
        return Path(value)
    except Exception:
        deny("BLOCKED: thesis-rca Codex guard could not resolve the repository root.")


def run_guard(root: Path, script: str, tool_input: dict[str, object]) -> None:
    payload = json.dumps({"tool_input": tool_input}, ensure_ascii=False)
    result = subprocess.run(
        [str(root / "hooks" / script)],
        input=payload,
        text=True,
        cwd=root,
        capture_output=True,
        env=os.environ.copy(),
        check=False,
    )
    if result.returncode == 2:
        deny(result.stderr or f"BLOCKED by hooks/{script}")
    if result.returncode != 0:
        deny(
            f"BLOCKED: hooks/{script} failed closed with exit code "
            f"{result.returncode}.\n{result.stderr}"
        )
    if result.stderr:
        print(result.stderr.rstrip(), file=sys.stderr)


PATCH_PATH = re.compile(r"^\*\*\* (?:Add|Update|Delete) File: (.+)$")
MOVE_PATH = re.compile(r"^\*\*\* Move to: (.+)$")


def patch_paths(patch: str, root: Path) -> list[Path]:
    found: list[Path] = []
    for line in patch.splitlines():
        match = PATCH_PATH.match(line) or MOVE_PATH.match(line)
        if not match:
            continue
        raw = match.group(1).strip()
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = root / candidate
        found.append(candidate.resolve(strict=False))
    unique: list[Path] = []
    for candidate in found:
        if candidate not in unique:
            unique.append(candidate)
    return unique


def added_patch_content(patch: str) -> str:
    return "\n".join(
        line[1:]
        for line in patch.splitlines()
        if line.startswith("+") and not line.startswith("+++")
    )


def guard_patch(event: dict[str, object], root: Path) -> None:
    tool_input = event.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        deny("BLOCKED: apply_patch input is not a JSON object.")
    patch = tool_input.get("command") or tool_input.get("patch") or ""
    if not isinstance(patch, str) or not patch.strip():
        deny("BLOCKED: apply_patch payload is empty or unsupported.")
    targets = patch_paths(patch, root)
    if not targets:
        deny("BLOCKED: no target path could be parsed from apply_patch payload.")
    additions = added_patch_content(patch)
    for target in targets:
        translated = {"file_path": str(target), "content": additions}
        run_guard(root, "claude-config-guard.sh", translated)
        run_guard(root, "data-guard.sh", translated)
        run_guard(root, "secret-scanner.sh", translated)


def guard_bash(event: dict[str, object], root: Path) -> None:
    tool_input = event.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        deny("BLOCKED: Bash input is not a JSON object.")
    command = tool_input.get("command") or tool_input.get("cmd") or ""
    if not isinstance(command, str):
        deny("BLOCKED: Bash command is not a string.")
    translated = {"command": command}
    for script in ("pr-only-guard.sh", "experiment-guard.sh", "bash-guard.sh"):
        run_guard(root, script, translated)


def guard_agent(event: dict[str, object], root: Path) -> None:
    tool_input = event.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return
    raw_agent = str(
        tool_input.get("subagent_type")
        or tool_input.get("agent_type")
        or tool_input.get("task_name")
        or ""
    )
    raw_model = str(tool_input.get("model") or "")
    agent_name = raw_agent.replace("_", "-")
    model_map = {
        "gpt-5.6-sol": "opus",
        "gpt-5.6-terra": "sonnet",
    }
    translated = {
        "subagent_type": agent_name,
        "model": model_map.get(raw_model, raw_model),
    }
    run_guard(root, "agent-model-guard.sh", translated)


def main() -> None:
    try:
        event = json.load(sys.stdin)
    except Exception as exc:
        deny(f"BLOCKED: invalid Codex hook JSON: {exc}")
    if not isinstance(event, dict):
        deny("BLOCKED: Codex hook event is not an object.")
    root = repo_root(str(event.get("cwd") or os.getcwd()))
    tool_name = str(event.get("tool_name") or "")
    if tool_name == "Bash":
        guard_bash(event, root)
    elif tool_name == "apply_patch":
        guard_patch(event, root)
    elif tool_name in {"Agent", "spawn_agent"}:
        guard_agent(event, root)


if __name__ == "__main__":
    main()

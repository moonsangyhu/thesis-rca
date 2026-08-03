"""Fail-closed probes for the Codex-to-signer isolation boundary.

The probe reports only access outcomes.  It never emits environment values or
file contents, so it is safe to use with a canary that stands in for a signer
credential.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
from dataclasses import asdict, dataclass
from pathlib import Path


_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")
OUT_OF_SANDBOX_APP_SERVER_METHODS = frozenset(
    {
        "process/spawn",
        "thread/shellCommand",
    }
)


@dataclass(frozen=True)
class IsolationResult:
    environment: str
    signer_file: str
    controller_socket: str

    @property
    def isolated(self) -> bool:
        return (
            self.environment == "absent"
            and self.signer_file == "denied"
            and self.controller_socket == "denied"
        )

    def public_dict(self) -> dict[str, object]:
        return asdict(self) | {"isolated": self.isolated}


def reject_out_of_sandbox_method(method: str) -> None:
    """Reject app-server APIs that explicitly bypass a thread sandbox."""

    if method in OUT_OF_SANDBOX_APP_SERVER_METHODS:
        raise ValueError(f"out-of-sandbox app-server method is forbidden: {method}")


def _probe_file(path: Path) -> str:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except PermissionError:
        return "denied"
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "error"
    else:
        os.close(descriptor)
        return "accessible"


def _probe_socket(path: Path) -> str:
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(1.0)
    try:
        client.connect(str(path))
    except PermissionError:
        return "denied"
    except FileNotFoundError:
        return "missing"
    except OSError:
        return "error"
    else:
        return "accessible"
    finally:
        client.close()


def probe_isolation(*, environment_name: str, signer_path: Path, socket_path: Path) -> IsolationResult:
    if not _ENV_NAME.fullmatch(environment_name):
        raise ValueError("invalid environment variable name")
    return IsolationResult(
        environment="present" if environment_name in os.environ else "absent",
        signer_file=_probe_file(signer_path),
        controller_socket=_probe_socket(socket_path),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Probe signer isolation without exposing values")
    parser.add_argument("--environment-name", required=True)
    parser.add_argument("--signer-path", required=True, type=Path)
    parser.add_argument("--controller-socket", required=True, type=Path)
    args = parser.parse_args(argv)
    result = probe_isolation(
        environment_name=args.environment_name,
        signer_path=args.signer_path,
        socket_path=args.controller_socket,
    )
    print(json.dumps(result.public_dict(), sort_keys=True, separators=(",", ":")))
    return 0 if result.isolated else 1


if __name__ == "__main__":
    raise SystemExit(main())

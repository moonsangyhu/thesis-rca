"""In-process zero-external-call guard and auditable policy description."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import socket
import subprocess
from typing import Iterator

from .io import AuditError

CLEARED_PREFIXES = (
    "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY", "OPENAI_", "CODEX_",
    "COPILOT_", "KUBE", "AWS_", "AZURE_", "GOOGLE_", "SSH_",
)


class ExternalCallBlocked(AuditError):
    pass


class ExternalCallGuard:
    def __init__(self):
        self.attempts: list[str] = []
        self.children: list[str] = []

    def _block_socket(self, *args, **kwargs):
        self.attempts.append("socket")
        raise ExternalCallBlocked("network/socket blocked by V2.4 isolation")

    def _block_dns(self, *args, **kwargs):
        self.attempts.append("dns")
        raise ExternalCallBlocked("DNS blocked by V2.4 isolation")

    def _block_process(self, *args, **kwargs):
        command = args[0] if args else kwargs.get("args", "unknown")
        self.attempts.append(f"child:{command}")
        raise ExternalCallBlocked("child process blocked by V2.4 isolation")

    @contextlib.contextmanager
    def enforce(self) -> Iterator["ExternalCallGuard"]:
        original_socket = socket.socket
        original_connection = socket.create_connection
        original_dns = socket.getaddrinfo
        original_popen = subprocess.Popen
        process_functions = [
            name for name in (
                "system", "posix_spawn", "posix_spawnp", "spawnl", "spawnle", "spawnlp",
                "spawnlpe", "spawnv", "spawnve", "spawnvp", "spawnvpe",
            ) if hasattr(os, name)
        ]
        original_process_functions = {name: getattr(os, name) for name in process_functions}
        removed = {key: os.environ.pop(key) for key in list(os.environ) if key.upper().startswith(CLEARED_PREFIXES)}
        telemetry_present = "ANONYMIZED_TELEMETRY" in os.environ
        telemetry_value = os.environ.get("ANONYMIZED_TELEMETRY")
        os.environ["ANONYMIZED_TELEMETRY"] = "FALSE"
        socket.socket = self._block_socket  # type: ignore[assignment]
        socket.create_connection = self._block_socket  # type: ignore[assignment]
        socket.getaddrinfo = self._block_dns  # type: ignore[assignment]
        subprocess.Popen = self._block_process  # type: ignore[assignment]
        for name in process_functions:
            setattr(os, name, self._block_process)
        try:
            yield self
        finally:
            socket.socket = original_socket
            socket.create_connection = original_connection
            socket.getaddrinfo = original_dns
            subprocess.Popen = original_popen
            for name, function in original_process_functions.items():
                setattr(os, name, function)
            if telemetry_present:
                assert telemetry_value is not None
                os.environ["ANONYMIZED_TELEMETRY"] = telemetry_value
            else:
                os.environ.pop("ANONYMIZED_TELEMETRY", None)
            os.environ.update(removed)

    def manifest(self) -> dict[str, object]:
        policy = {
            "network": "python-socket-and-dns-deny",
            "children": "subprocess-popen-deny",
            "telemetry": "disabled",
            "environment_prefixes_cleared": list(CLEARED_PREFIXES),
        }
        return {
            "zero_call_assurance": "OBSERVED_ONLY",
            "policy": policy,
            "policy_sha256": hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest(),
            "blocked_attempt_count": len(self.attempts),
            "blocked_attempts": list(self.attempts),
            "child_process_inventory": list(self.children),
            "path_inventory": os.environ.get("PATH", "").split(os.pathsep),
            "path_control": "not-enforced-host-process; claim downgraded to OBSERVED_ONLY",
            "mount_control": "not-enforced-host-process; explicit input paths only",
            "observed_external_calls": 0,
            "observed_model_calls": 0,
            "observed_k8s_calls": 0,
        }

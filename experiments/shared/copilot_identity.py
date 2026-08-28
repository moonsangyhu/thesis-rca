"""Read-only binding of the active GitHub account used by Copilot SDK."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime


class CopilotIdentityError(RuntimeError):
    pass


IDENTITY_PROBE_REAP_SECONDS = 5

@dataclass(frozen=True)
class CopilotAccountIdentity:
    login: str
    source: str
    observed_at: str

    def to_dict(self) -> dict:
        return asdict(self)


def _is_retryable_identity_service_failure(
    completed: subprocess.CompletedProcess[str],
) -> bool:
    """Recognize only GitHub's transient authenticated-API 503 response."""
    if completed.returncode == 0:
        return False
    combined = f"{completed.stdout}\n{completed.stderr}"
    return (
        "HTTP 503" in combined
        or "No server is currently available to service your request" in combined
    )


def _run_identity_probe(
    command: list[str], *, timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        # gh api user is one read-only CLI process, so direct timeout cleanup
        # avoids macOS fork/exec after a native runtime has initialized.
        close_fds=False,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except BaseException:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        try:
            process.communicate(timeout=IDENTITY_PROBE_REAP_SECONDS)
        except subprocess.TimeoutExpired:
            # A leaked descendant can retain stdout/stderr after the directly
            # owned gh process is gone.  Do not turn an identity preflight
            # timeout into an unbounded hang before any experiment artifact.
            for stream in (process.stdin, process.stdout, process.stderr):
                try:
                    if stream is not None:
                        stream.close()
                except OSError:
                    pass
        raise
    return subprocess.CompletedProcess(
        command, process.returncode, stdout=stdout, stderr=stderr
    )


def inspect_active_gh_account(
    *, expected_login: str, timeout_seconds: int = 30,
    timeout_retries: int = 1, now: datetime | None = None,
) -> CopilotAccountIdentity:
    """Bind the active gh user without starting a model or quota session."""
    if not isinstance(expected_login, str) or not re.fullmatch(
        r"[A-Za-z0-9-]{1,39}", expected_login
    ):
        raise ValueError("expected GitHub login is invalid")
    if (
        isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, int)
        or timeout_seconds < 1
    ):
        raise ValueError("identity timeout must be a positive integer")
    if (
        isinstance(timeout_retries, bool) or not isinstance(timeout_retries, int)
        or timeout_retries not in (0, 1)
    ):
        raise ValueError("identity timeout retries must be zero or one")
    gh = shutil.which("gh")
    if not gh:
        raise CopilotIdentityError("GitHub CLI is unavailable")
    completed = None
    for attempt in range(timeout_retries + 1):
        try:
            completed = _run_identity_probe(
                [gh, "api", "user", "--jq", ".login"],
                timeout_seconds=timeout_seconds,
            )
            if completed.returncode == 0:
                break
            if (
                _is_retryable_identity_service_failure(completed)
                and attempt < timeout_retries
            ):
                continue
            raise CopilotIdentityError("GitHub account probe failed before inference")
        except subprocess.TimeoutExpired as exc:
            if attempt == timeout_retries:
                raise CopilotIdentityError(
                    "GitHub account probe timed out before inference"
                ) from exc
        except Exception as exc:
            raise CopilotIdentityError(
                "GitHub account probe failed before inference"
            ) from exc
    if completed is None or completed.returncode != 0:
        raise CopilotIdentityError("GitHub account probe failed before inference")
    login = completed.stdout.strip()
    if login != expected_login or "\n" in login:
        raise CopilotIdentityError("active GitHub account does not match approval")
    observed = now or datetime.now().astimezone()
    if observed.tzinfo is None:
        raise ValueError("identity observation time must be timezone-aware")
    return CopilotAccountIdentity(
        login=login, source="gh-api-active-user", observed_at=observed.isoformat()
    )

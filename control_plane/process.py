"""Stable process identity helpers for PID reuse detection."""

from __future__ import annotations

import subprocess
from datetime import datetime


def process_start_time(pid: int) -> str | None:
    try:
        completed = subprocess.run(
            ["ps", "-o", "lstart=", "-p", str(pid)],
            check=False,
            capture_output=True,
            text=True,
            timeout=3,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    raw = completed.stdout.strip()
    if completed.returncode != 0 or not raw:
        return None
    try:
        parsed = datetime.strptime(" ".join(raw.split()), "%a %b %d %H:%M:%S %Y")
        return parsed.astimezone().isoformat()
    except ValueError:
        return None


def process_start_time_for_pid(pid: int) -> str:
    value = process_start_time(pid)
    if value is None:
        raise RuntimeError(f"cannot determine process start time for pid {pid}")
    return value

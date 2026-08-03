"""Append-only audit log for authenticated command envelopes."""

from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path

from .io import fsync_directory
from .protocol import CommandEnvelope
from .state import utc_now


class CommandAuditLog:
    def __init__(self, runtime_root: Path):
        self.path = Path(runtime_root) / "commands.jsonl"
        self.lock_path = Path(runtime_root) / ".commands.lock"
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    def append(self, envelope: CommandEnvelope, result: dict) -> None:
        subcommand = envelope.args.strip().split(maxsplit=1)[0] if envelope.args.strip() else ""
        record = {
            "request_id": envelope.request_id,
            "platform": envelope.platform,
            "user_id": envelope.user_id,
            "channel_id": envelope.channel_id,
            "thread_ts": envelope.thread_ts,
            "subcommand": subcommand,
            "received_at": envelope.received_at,
            "processed_at": utc_now(),
            "result_status": result.get("status", "unknown"),
            "result_reason": result.get("reason", ""),
        }
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        with self.lock_path.open("a+") as lock:
            os.chmod(self.lock_path, 0o600)
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                os.write(fd, payload.encode("utf-8"))
                os.fsync(fd)
            finally:
                os.close(fd)
        fsync_directory(self.path.parent)

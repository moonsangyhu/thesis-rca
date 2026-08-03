"""Read-only stale-lock classification used by the future Watchdog daemon."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from .global_lock import GlobalCampaignLock, LockRecord


@dataclass(frozen=True)
class WatchdogFinding:
    status: str
    reason: str
    lock: LockRecord | None


class WatchdogInspector:
    def __init__(
        self,
        runtime_root: Path,
        process_start_time: Callable[[int], str | None],
        heartbeat_timeout: timedelta = timedelta(minutes=3),
    ):
        self.runtime_root = Path(runtime_root)
        self.lock = GlobalCampaignLock(runtime_root)
        self.process_start_time = process_start_time
        self.heartbeat_timeout = heartbeat_timeout

    def inspect(self, now: datetime | None = None) -> WatchdogFinding:
        if not self.lock.path.exists():
            return WatchdogFinding("no_lock", "no active campaign lock", None)
        try:
            record = self.lock.inspect()
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return WatchdogFinding("stale_candidate", "lock metadata invalid", None)
        actual_start = self.process_start_time(record.controller_pid)
        if actual_start is None:
            return WatchdogFinding("stale_candidate", "controller process missing", record)
        if actual_start != record.process_start_time:
            return WatchdogFinding("stale_candidate", "process start time mismatch", record)
        heartbeat = self.runtime_root / "campaigns" / record.campaign_id / "heartbeat.json"
        if not heartbeat.exists():
            return WatchdogFinding("stale_candidate", "heartbeat missing", record)
        try:
            value = json.loads(heartbeat.read_text())
            observed = datetime.fromisoformat(value["observed_at"])
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            return WatchdogFinding("stale_candidate", "heartbeat invalid", record)
        if observed.tzinfo is None:
            return WatchdogFinding("stale_candidate", "heartbeat missing timezone", record)
        current = now or datetime.now(timezone.utc)
        if current - observed > self.heartbeat_timeout:
            return WatchdogFinding("stale_candidate", "heartbeat expired", record)
        return WatchdogFinding("healthy", "pid, start time, and heartbeat agree", record)

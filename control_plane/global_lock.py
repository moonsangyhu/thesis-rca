"""Atomic, owner-bound global campaign lock."""

from __future__ import annotations

import hmac
import json
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import LockHeld, LockOwnershipError
from .io import atomic_write_json, fsync_directory
from .process import process_start_time_for_pid
from .state import CampaignState, utc_now


@dataclass(frozen=True)
class LockRecord:
    campaign_id: str
    controller_pid: int
    process_start_time: str
    manifest_sha256: str
    state: CampaignState
    lease_id: str
    created_at: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "LockRecord":
        return cls(
            campaign_id=value["campaign_id"],
            controller_pid=int(value["controller_pid"]),
            process_start_time=value["process_start_time"],
            manifest_sha256=value["manifest_sha256"],
            state=CampaignState(value["state"]),
            lease_id=value["lease_id"],
            created_at=value["created_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "controller_pid": self.controller_pid,
            "process_start_time": self.process_start_time,
            "manifest_sha256": self.manifest_sha256,
            "state": self.state.value,
            "lease_id": self.lease_id,
            "created_at": self.created_at,
        }


class GlobalCampaignLock:
    def __init__(self, runtime_root: Path):
        self.path = Path(runtime_root) / "campaign.lock"

    def acquire(
        self,
        campaign_id: str,
        manifest_sha256: str,
        state: CampaignState,
        *,
        controller_pid: int | None = None,
        process_start_time: str | None = None,
    ) -> LockRecord:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        record = LockRecord(
            campaign_id=campaign_id,
            controller_pid=controller_pid or os.getpid(),
            process_start_time=process_start_time or process_start_time_for_pid(
                controller_pid or os.getpid()
            ),
            manifest_sha256=manifest_sha256,
            state=state,
            lease_id=uuid.uuid4().hex,
            created_at=utc_now(),
        )
        try:
            fd = os.open(self.path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError as exc:
            try:
                holder = self.inspect().campaign_id
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                holder = "unreadable-lock"
            raise LockHeld(holder) from exc
        try:
            payload = json.dumps(record.to_dict(), sort_keys=True, separators=(",", ":")) + "\n"
            os.write(fd, payload.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        fsync_directory(self.path.parent)
        return record

    def inspect(self) -> LockRecord:
        return LockRecord.from_dict(json.loads(self.path.read_text()))

    def update_state(self, lease_id: str, state: CampaignState) -> LockRecord:
        current = self.inspect()
        if not hmac.compare_digest(current.lease_id, lease_id):
            raise LockOwnershipError("lock lease mismatch")
        updated = LockRecord(
            campaign_id=current.campaign_id,
            controller_pid=current.controller_pid,
            process_start_time=current.process_start_time,
            manifest_sha256=current.manifest_sha256,
            state=state,
            lease_id=current.lease_id,
            created_at=current.created_at,
        )
        atomic_write_json(self.path, updated.to_dict())
        return updated

    def release(self, lease_id: str, final_state: CampaignState) -> None:
        if final_state not in {CampaignState.COMPLETE, CampaignState.SAFE_STOPPED}:
            raise LockOwnershipError("lock release requires a verified safe final state")
        current = self.inspect()
        if not hmac.compare_digest(current.lease_id, lease_id):
            raise LockOwnershipError("lock lease mismatch")
        self.path.unlink()
        fsync_directory(self.path.parent)

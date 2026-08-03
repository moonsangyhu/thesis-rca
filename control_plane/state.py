"""Campaign state machine and durable state registry."""

from __future__ import annotations

import fcntl
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .errors import CampaignExists, CampaignNotFound, InvalidTransition
from .io import atomic_write_json, fsync_directory


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CampaignState(str, Enum):
    DRAFT = "DRAFT"
    READY = "READY"
    APPROVED = "APPROVED"
    PREFLIGHT = "PREFLIGHT"
    RUNNING = "RUNNING"
    STOPPING = "STOPPING"
    RESTORING = "RESTORING"
    VERIFYING = "VERIFYING"
    COMPLETE = "COMPLETE"
    SAFE_STOPPED = "SAFE_STOPPED"
    BLOCKED = "BLOCKED"


TRANSITIONS = {
    CampaignState.DRAFT: {CampaignState.READY, CampaignState.BLOCKED},
    CampaignState.READY: {
        CampaignState.APPROVED,
        CampaignState.SAFE_STOPPED,
        CampaignState.BLOCKED,
    },
    CampaignState.APPROVED: {
        CampaignState.PREFLIGHT,
        CampaignState.SAFE_STOPPED,
        CampaignState.BLOCKED,
    },
    CampaignState.PREFLIGHT: {
        CampaignState.RUNNING,
        CampaignState.SAFE_STOPPED,
        CampaignState.BLOCKED,
    },
    CampaignState.RUNNING: {
        CampaignState.STOPPING,
        CampaignState.RESTORING,
        CampaignState.BLOCKED,
    },
    CampaignState.STOPPING: {CampaignState.RESTORING, CampaignState.BLOCKED},
    CampaignState.RESTORING: {
        CampaignState.VERIFYING,
        CampaignState.SAFE_STOPPED,
        CampaignState.BLOCKED,
    },
    CampaignState.VERIFYING: {CampaignState.COMPLETE, CampaignState.BLOCKED},
    CampaignState.COMPLETE: set(),
    CampaignState.SAFE_STOPPED: set(),
    CampaignState.BLOCKED: set(),
}


@dataclass(frozen=True)
class CampaignSnapshot:
    campaign_id: str
    state: CampaignState
    manifest_sha256: str
    source_commit: str
    sequence: int
    updated_at: str

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "CampaignSnapshot":
        return cls(
            campaign_id=value["campaign_id"],
            state=CampaignState(value["state"]),
            manifest_sha256=value["manifest_sha256"],
            source_commit=value["source_commit"],
            sequence=int(value["sequence"]),
            updated_at=value["updated_at"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "campaign_id": self.campaign_id,
            "state": self.state.value,
            "manifest_sha256": self.manifest_sha256,
            "source_commit": self.source_commit,
            "sequence": self.sequence,
            "updated_at": self.updated_at,
        }


class CampaignStore:
    def __init__(self, runtime_root: Path):
        self.runtime_root = Path(runtime_root)
        self.campaigns_root = self.runtime_root / "campaigns"

    def campaign_dir(self, campaign_id: str) -> Path:
        return self.campaigns_root / campaign_id

    def create(self, campaign_id: str, manifest_sha256: str, source_commit: str) -> CampaignSnapshot:
        directory = self.campaign_dir(campaign_id)
        try:
            directory.mkdir(parents=True, mode=0o700)
        except FileExistsError as exc:
            raise CampaignExists(campaign_id) from exc
        snapshot = CampaignSnapshot(
            campaign_id=campaign_id,
            state=CampaignState.DRAFT,
            manifest_sha256=manifest_sha256,
            source_commit=source_commit,
            sequence=0,
            updated_at=utc_now(),
        )
        self._append_event(directory, snapshot, actor="builder", reason="campaign_created")
        atomic_write_json(directory / "state.json", snapshot.to_dict())
        return snapshot

    def read(self, campaign_id: str) -> CampaignSnapshot:
        path = self.campaign_dir(campaign_id) / "state.json"
        try:
            return CampaignSnapshot.from_dict(json.loads(path.read_text()))
        except FileNotFoundError as exc:
            raise CampaignNotFound(campaign_id) from exc

    def read_manifest(self, campaign_id: str) -> dict[str, Any]:
        path = self.campaign_dir(campaign_id) / "campaign.json"
        try:
            return json.loads(path.read_text())
        except FileNotFoundError as exc:
            raise CampaignNotFound(campaign_id) from exc

    def transition(
        self,
        campaign_id: str,
        target: CampaignState,
        *,
        actor: str,
        reason: str,
        event_id: str | None = None,
    ) -> CampaignSnapshot:
        directory = self.campaign_dir(campaign_id)
        lock_path = directory / ".state.lock"
        if not directory.exists():
            raise CampaignNotFound(campaign_id)
        with lock_path.open("a+") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            current = self.read(campaign_id)
            if target not in TRANSITIONS[current.state]:
                raise InvalidTransition(f"{current.state.value} -> {target.value}")
            updated = CampaignSnapshot(
                campaign_id=current.campaign_id,
                state=target,
                manifest_sha256=current.manifest_sha256,
                source_commit=current.source_commit,
                sequence=current.sequence + 1,
                updated_at=utc_now(),
            )
            self._append_event(directory, updated, actor=actor, reason=reason, event_id=event_id)
            atomic_write_json(directory / "state.json", updated.to_dict())
            return updated

    @staticmethod
    def _append_event(
        directory: Path,
        snapshot: CampaignSnapshot,
        *,
        actor: str,
        reason: str,
        event_id: str | None = None,
    ) -> None:
        record = snapshot.to_dict() | {"actor": actor, "reason": reason}
        if event_id is not None:
            record["event_id"] = event_id
        payload = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        fd = os.open(directory / "events.jsonl", os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, payload.encode("utf-8"))
            os.fsync(fd)
        finally:
            os.close(fd)
        fsync_directory(directory)

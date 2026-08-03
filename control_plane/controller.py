"""Approval-bound campaign controller core (no Slack or cluster dependencies)."""

from __future__ import annotations

import hmac
import json
from dataclasses import dataclass
from pathlib import Path

from .errors import (
    CampaignNotFound,
    InvalidTransition,
    LockHeld,
    LockOwnershipError,
    ManifestValidationError,
)
from .events import EventStore
from .global_lock import GlobalCampaignLock
from .manifest import CampaignManifest
from .state import CampaignState, CampaignStore


@dataclass(frozen=True)
class ControlPlaneConfig:
    allowed_user_id: str
    allowed_channel_id: str

    def __post_init__(self) -> None:
        if not self.allowed_user_id or not self.allowed_channel_id:
            raise ValueError("one allowed user and channel are required")


@dataclass(frozen=True)
class ApprovalRequest:
    event_id: str
    user_id: str
    channel_id: str
    campaign_id: str
    manifest_sha256: str
    thread_ts: str


@dataclass(frozen=True)
class StopRequest:
    event_id: str
    user_id: str
    channel_id: str
    campaign_id: str
    thread_ts: str


class CampaignController:
    def __init__(self, runtime_root: Path, config: ControlPlaneConfig):
        self.runtime_root = Path(runtime_root)
        self.config = config
        self.campaigns = CampaignStore(self.runtime_root)
        self.events = EventStore(self.runtime_root)
        self.global_lock = GlobalCampaignLock(self.runtime_root)

    def register_manifest(self, value: dict) -> dict:
        manifest = CampaignManifest.parse(value)
        snapshot = self.campaigns.create(
            manifest.campaign_id,
            manifest.sha256,
            manifest.source_commit,
        )
        manifest.seal_to(self.campaigns.campaign_dir(manifest.campaign_id) / "campaign.json")
        snapshot = self.campaigns.transition(
            manifest.campaign_id,
            CampaignState.READY,
            actor="builder",
            reason="manifest_validated_and_sealed",
        )
        return snapshot.to_dict()

    def approve(self, request: ApprovalRequest) -> dict:
        result, duplicate = self.events.process_once(
            request.event_id,
            lambda: self._approve_once(request),
        )
        return result | {"duplicate": duplicate}

    def status(self, user_id: str, channel_id: str, campaign_id: str | None = None) -> dict:
        rejection = self.authorize(user_id, channel_id)
        if rejection:
            return rejection
        if campaign_id is None:
            if not self.global_lock.path.exists():
                return {"status": "ok", "active_campaign": None}
            try:
                campaign_id = self.global_lock.inspect().campaign_id
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                return {"status": "blocked", "reason": "global_lock_invalid"}
        try:
            snapshot = self.campaigns.read(campaign_id)
        except CampaignNotFound:
            return {"status": "rejected", "reason": "campaign_not_found"}
        return {
            "status": "ok",
            "campaign_id": snapshot.campaign_id,
            "state": snapshot.state.value,
            "manifest_sha256": snapshot.manifest_sha256,
            "source_commit": snapshot.source_commit,
            "sequence": snapshot.sequence,
            "updated_at": snapshot.updated_at,
        }

    def campaign_thread(self, campaign_id: str) -> str | None:
        try:
            snapshot = self.campaigns.read(campaign_id)
            manifest = CampaignManifest.parse(self.campaigns.read_manifest(campaign_id))
        except (CampaignNotFound, ManifestValidationError, json.JSONDecodeError):
            return None
        if not hmac.compare_digest(manifest.sha256, snapshot.manifest_sha256):
            return None
        return manifest.data["thread_ts"]

    def stop(self, request: StopRequest) -> dict:
        result, duplicate = self.events.process_once(
            request.event_id,
            lambda: self._stop_once(request),
        )
        return result | {"duplicate": duplicate}

    def _approve_once(self, request: ApprovalRequest) -> dict:
        rejection = self.authorize(request.user_id, request.channel_id)
        if rejection:
            return rejection
        try:
            snapshot = self.campaigns.read(request.campaign_id)
        except CampaignNotFound:
            return {"status": "rejected", "reason": "campaign_not_found"}
        if not hmac.compare_digest(request.manifest_sha256, snapshot.manifest_sha256):
            return {"status": "rejected", "reason": "manifest_sha_mismatch"}
        try:
            manifest = CampaignManifest.parse(self.campaigns.read_manifest(request.campaign_id))
        except (CampaignNotFound, ManifestValidationError, json.JSONDecodeError):
            return {"status": "rejected", "reason": "sealed_manifest_invalid"}
        if not hmac.compare_digest(manifest.sha256, snapshot.manifest_sha256):
            return {"status": "rejected", "reason": "sealed_manifest_tampered"}
        if not hmac.compare_digest(request.thread_ts, manifest.data["thread_ts"]):
            return {"status": "rejected", "reason": "thread_not_bound"}
        # Filesystem state and SQLite cannot share a transaction. If a process
        # dies after fsyncing APPROVED but before recording the event result,
        # recover the original successful outcome from the append-only journal.
        if snapshot.state is CampaignState.APPROVED and self._journal_has_event(
            request.campaign_id, request.event_id, CampaignState.APPROVED
        ):
            return {
                "status": "approved",
                "campaign_id": request.campaign_id,
                "state": snapshot.state.value,
                "manifest_sha256": snapshot.manifest_sha256,
            }
        if snapshot.state is not CampaignState.READY:
            return {"status": "rejected", "reason": f"state_{snapshot.state.value.lower()}"}
        try:
            self.global_lock.acquire(
                request.campaign_id,
                snapshot.manifest_sha256,
                CampaignState.APPROVED,
            )
        except LockHeld:
            return {"status": "rejected", "reason": "global_lock_held"}
        try:
            updated = self.campaigns.transition(
                request.campaign_id,
                CampaignState.APPROVED,
                actor="slack_command",
                reason="identity_channel_and_manifest_sha_verified",
                event_id=request.event_id,
            )
        except InvalidTransition:
            return {"status": "rejected", "reason": "state_changed"}
        return {
            "status": "approved",
            "campaign_id": request.campaign_id,
            "state": updated.state.value,
            "manifest_sha256": updated.manifest_sha256,
        }

    def _stop_once(self, request: StopRequest) -> dict:
        rejection = self.authorize(request.user_id, request.channel_id)
        if rejection:
            return rejection
        try:
            snapshot = self.campaigns.read(request.campaign_id)
            manifest = CampaignManifest.parse(self.campaigns.read_manifest(request.campaign_id))
        except (CampaignNotFound, ManifestValidationError, json.JSONDecodeError):
            return {"status": "rejected", "reason": "campaign_not_found_or_invalid"}
        if not hmac.compare_digest(manifest.sha256, snapshot.manifest_sha256):
            return {"status": "rejected", "reason": "sealed_manifest_tampered"}
        if not hmac.compare_digest(request.thread_ts, manifest.data["thread_ts"]):
            return {"status": "rejected", "reason": "thread_not_bound"}

        if snapshot.state is CampaignState.SAFE_STOPPED and self._journal_has_event(
            request.campaign_id, request.event_id, CampaignState.SAFE_STOPPED
        ):
            lock_retained = False
            try:
                lock_retained = self.global_lock.inspect().campaign_id == request.campaign_id
            except (OSError, ValueError, KeyError, json.JSONDecodeError):
                pass
            return {
                "status": "stopped_lock_retained" if lock_retained else "stopped",
                "campaign_id": request.campaign_id,
                "state": snapshot.state.value,
            }
        if snapshot.state is CampaignState.STOPPING and self._journal_has_event(
            request.campaign_id, request.event_id, CampaignState.STOPPING
        ):
            return {
                "status": "stop_requested",
                "campaign_id": request.campaign_id,
                "state": snapshot.state.value,
            }

        if snapshot.state in {CampaignState.READY, CampaignState.APPROVED, CampaignState.PREFLIGHT}:
            updated = self.campaigns.transition(
                request.campaign_id,
                CampaignState.SAFE_STOPPED,
                actor="slack_command",
                reason="user_requested_safe_stop_before_running",
                event_id=request.event_id,
            )
            lock_released = snapshot.state is CampaignState.READY
            if snapshot.state in {CampaignState.APPROVED, CampaignState.PREFLIGHT}:
                try:
                    lock = self.global_lock.inspect()
                    if lock.campaign_id == request.campaign_id:
                        self.global_lock.release(lock.lease_id, CampaignState.SAFE_STOPPED)
                        lock_released = True
                except (
                    OSError,
                    KeyError,
                    ValueError,
                    json.JSONDecodeError,
                    LockOwnershipError,
                ):
                    lock_released = False
            return {
                "status": "stopped" if lock_released else "stopped_lock_retained",
                "campaign_id": request.campaign_id,
                "state": updated.state.value,
            }
        if snapshot.state is CampaignState.RUNNING:
            updated = self.campaigns.transition(
                request.campaign_id,
                CampaignState.STOPPING,
                actor="slack_command",
                reason="user_requested_safe_stop",
                event_id=request.event_id,
            )
            return {
                "status": "stop_requested",
                "campaign_id": request.campaign_id,
                "state": updated.state.value,
            }
        if snapshot.state in {
            CampaignState.STOPPING,
            CampaignState.RESTORING,
            CampaignState.VERIFYING,
        }:
            return {
                "status": "stop_in_progress",
                "campaign_id": request.campaign_id,
                "state": snapshot.state.value,
            }
        return {
            "status": "no_op",
            "campaign_id": request.campaign_id,
            "state": snapshot.state.value,
        }

    def authorize(self, user_id: str, channel_id: str) -> dict | None:
        if not hmac.compare_digest(user_id, self.config.allowed_user_id):
            return {"status": "rejected", "reason": "user_not_allowed"}
        if not hmac.compare_digest(channel_id, self.config.allowed_channel_id):
            return {"status": "rejected", "reason": "channel_not_allowed"}
        return None

    def _journal_has_event(
        self,
        campaign_id: str,
        event_id: str,
        state: CampaignState,
    ) -> bool:
        path = self.campaigns.campaign_dir(campaign_id) / "events.jsonl"
        try:
            for line in path.read_text().splitlines():
                record = json.loads(line)
                if record.get("event_id") == event_id and record.get("state") == state.value:
                    return True
        except (FileNotFoundError, json.JSONDecodeError):
            return False
        return False

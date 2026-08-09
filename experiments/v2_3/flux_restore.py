"""Idempotent emergency restore for the V2.3 Flux app suspension guard."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path

from .live_runner import FluxAppGuard, FluxHierarchyGuard, PilotError


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def build_live_flux_guard() -> FluxHierarchyGuard:
    """Build the production root/app hierarchy guard with CAS patches."""
    from scripts.fault_inject.base import kubectl, kubectl_get_json

    def guard_for(name: str) -> FluxAppGuard:
        def load() -> dict:
            return kubectl_get_json("kustomization", name, namespace="flux-system")

        def patch_suspend(value: bool | None, resource_version: str) -> dict:
            patch = {
                "metadata": {"resourceVersion": resource_version},
                "spec": {"suspend": value},
            }
            output = kubectl(
                "patch", "kustomization", name, "--type", "merge",
                "-p", json.dumps(patch, separators=(",", ":")), "-o", "json",
                namespace="flux-system",
            )
            try:
                parsed = json.loads(output) if output else {}
            except json.JSONDecodeError as exc:
                raise PilotError("Flux patch response is not JSON") from exc
            if not isinstance(parsed, dict):
                raise PilotError("Flux patch response is not an object")
            return parsed

        return FluxAppGuard(load, patch_suspend, name=name)

    def settle(*members: tuple[FluxAppGuard, dict]) -> None:
        # A parent reconciliation already in flight may write after the CAS.
        # Ten joint observations establish quiescence before the fault patch.
        for _ in range(10):
            time.sleep(1)
            for guard, receipt in members:
                guard.verify_suspended(receipt)

    return FluxHierarchyGuard(
        guard_for("flux-system"), guard_for("app"), settle=settle
    )


def _validated_campaign_dir(path: Path) -> Path:
    allowed = (PROJECT_ROOT / "artifacts" / "v2_3_pilot").resolve()
    resolved = Path(path).resolve(strict=True)
    if (
        resolved.parent != allowed
        or re.fullmatch(r"[A-Za-z0-9_.-]{8,128}", resolved.name) is None
    ):
        raise PilotError("emergency restore path is not a V2.3 campaign directory")
    manifest_path = resolved / "campaign_manifest.json"
    events_path = resolved / "campaign_events.jsonl"
    if not manifest_path.is_file() or not events_path.is_file():
        raise PilotError("campaign manifest/events are missing")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("campaign_id") != resolved.name:
        raise PilotError("campaign directory identity mismatch")
    return resolved


def _durable_events(campaign_dir: Path) -> list[dict]:
    events: list[dict] = []
    journal = (campaign_dir / "campaign_events.jsonl").read_bytes()
    fragments = journal.split(b"\n")
    for index, fragment in enumerate(fragments):
        if index == len(fragments) - 1 and fragment == b"":
            continue
        final_incomplete_tail = index == len(fragments) - 1 and not journal.endswith(b"\n")
        try:
            event = json.loads(fragment.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            # append_event fsyncs complete records, but SIGKILL can leave only the
            # final append partially written.  Preserve the earlier durable
            # receipt while still rejecting corruption anywhere in the journal.
            if final_incomplete_tail:
                break
            raise PilotError("campaign event journal is malformed") from exc
        if not isinstance(event, dict):
            raise PilotError("campaign event is not an object")
        events.append(event)
    return events


def _sealed_receipt(events: list[dict], event_name: str, label: str) -> dict:
    receipts: list[dict] = []
    for event in events:
        if event.get("event") == event_name:
            receipt = event.get("recovery_context")
            if not isinstance(receipt, dict):
                raise PilotError(f"sealed {label} recovery receipt is malformed")
            receipts.append(receipt)
    if len(receipts) != 1:
        raise PilotError(f"campaign must contain exactly one sealed {label} receipt")
    return receipts[0]


def _optional_f7_receipt(events: list[dict]) -> dict | None:
    matching = [
        event for event in events if event.get("event") == "recovery_receipt_sealed"
    ]
    if len(matching) > 1:
        raise PilotError("campaign contains duplicate sealed F7 receipts")
    if not matching:
        if any(event.get("event") == "injection_started" for event in events):
            raise PilotError("F7 injection started without a sealed recovery receipt")
        return None
    receipt = matching[0].get("recovery_context")
    if not isinstance(receipt, dict):
        raise PilotError("sealed F7 recovery receipt is malformed")
    return receipt


def _append_event(campaign_dir: Path, event: str, **details) -> None:
    from datetime import datetime, timezone

    payload = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event": event,
        **details,
    }
    with (campaign_dir / "campaign_events.jsonl").open("a") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def restore_campaign(
    campaign_dir: Path,
    guard: object | None = None,
    recovery: object | None = None,
) -> dict:
    """Restore F7 exactly, then Flux, after a crashed pilot process."""
    resolved = _validated_campaign_dir(campaign_dir)
    events = _durable_events(resolved)
    flux_receipt = _sealed_receipt(
        events, "flux_recovery_receipt_sealed", "Flux"
    )
    active_guard = guard or build_live_flux_guard()
    if recovery is None:
        from scripts.stabilize import Recovery

        recovery = Recovery()

    recovery_error: BaseException | None = None
    recovery_result: dict = {}
    flux_error: BaseException | None = None
    flux_result: dict = {}
    try:
        injection_receipt = _optional_f7_receipt(events)
        if injection_receipt is None:
            recovery_result = {
                "action": "not-started", "health_check_passed": True,
            }
        else:
            recovery_result = recovery.recover("F7", 1, injection_receipt)
            if recovery_result.get("health_check_passed") is not True:
                raise PilotError("emergency F7 recovery did not recover exact GREEN state")
    except BaseException as exc:
        recovery_error = exc

    # Flux must be restored even when F7 recovery fails, matching the live
    # runner's independent cleanup boundaries.
    try:
        flux_result = active_guard.restore(flux_receipt)
        if (
            flux_result.get("flux_restored") is not True
            or flux_result.get("flux_exact_original") is not True
        ):
            raise PilotError("emergency Flux restore did not recover exact original state")
    except BaseException as exc:
        flux_error = exc

    if recovery_error is not None or flux_error is not None:
        _append_event(
            resolved, "flux_emergency_restore_failed",
            f7_error_type=(type(recovery_error).__name__ if recovery_error else None),
            flux_error_type=(type(flux_error).__name__ if flux_error else None),
            restore_action=flux_result.get("flux_restore_action", "unknown"),
        )
        raise PilotError("emergency F7/Flux restore did not recover exact original state")
    _append_event(
        resolved, "flux_emergency_restored",
        f7_action=recovery_result.get("action", "unknown"),
        restore_action=flux_result.get("flux_restore_action", "unknown"),
    )
    return {**recovery_result, **flux_result}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Restore V2.3 Flux guard state")
    parser.add_argument("--campaign-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    print(json.dumps(restore_campaign(args.campaign_dir), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

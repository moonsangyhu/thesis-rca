import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from experiments.v2_3.flux_restore import restore_campaign
from experiments.v2_3.live_runner import PilotError


class FakeEmergencyGuard:
    def __init__(self, result=None, calls=None):
        self.result = result or {
            "flux_restored": True,
            "flux_exact_original": True,
            "flux_restore_action": "cas-restored",
        }
        self.receipts = []
        self.calls = calls

    def restore(self, receipt):
        if self.calls is not None:
            self.calls.append("flux")
        self.receipts.append(receipt)
        return dict(self.result)


class FakeEmergencyRecovery:
    def __init__(self, result=None, error=None, calls=None):
        self.result = result or {
            "action": "restore_cpu_resources", "health_check_passed": True,
        }
        self.error = error
        self.calls = calls
        self.receipts = []

    def recover(self, fault_id, trial, receipt):
        if self.calls is not None:
            self.calls.append("f7")
        self.receipts.append((fault_id, trial, receipt))
        if self.error is not None:
            raise self.error
        return dict(self.result)


class FluxEmergencyRestoreTests(unittest.TestCase):
    def make_campaign(self, project_root: Path, campaign_id="campaign-flux-1"):
        campaign = project_root / "artifacts" / "v2_3_pilot" / campaign_id
        campaign.mkdir(parents=True)
        (campaign / "campaign_manifest.json").write_text(json.dumps({
            "campaign_id": campaign_id,
        }))
        receipt = {
            "flux_guard_schema": "v2.3-flux-app-guard-1",
            "flux_namespace": "flux-system", "flux_name": "app",
            "flux_uid": "uid-1", "flux_resource_version": "10",
            "flux_original_suspend_present": False,
            "flux_original_suspend": False,
        }
        (campaign / "campaign_events.jsonl").write_text(json.dumps({
            "event": "flux_recovery_receipt_sealed",
            "recovery_context": receipt,
        }) + "\n" + json.dumps({
            "event": "recovery_receipt_sealed",
            "recovery_context": {
                "fault_id": "F7", "trial": 1, "target_service": "frontend",
                "container_name": "server", "original_cpu_limit": "200m",
                "original_cpu_request": "100m",
            },
        }) + "\n")
        return campaign, receipt

    def test_restore_uses_single_sealed_receipt_and_fsync_event_path(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            campaign, receipt = self.make_campaign(project)
            guard = FakeEmergencyGuard()
            recovery = FakeEmergencyRecovery()
            with patch("experiments.v2_3.flux_restore.PROJECT_ROOT", project):
                result = restore_campaign(campaign, guard=guard, recovery=recovery)
            self.assertTrue(result["flux_exact_original"])
            self.assertEqual(guard.receipts, [receipt])
            self.assertEqual(recovery.receipts[0][:2], ("F7", 1))
            events = [json.loads(line) for line in
                      (campaign / "campaign_events.jsonl").read_text().splitlines()]
            self.assertEqual(events[-1]["event"], "flux_emergency_restored")

    def test_nonexact_external_state_is_preserved_and_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            campaign, _ = self.make_campaign(project)
            guard = FakeEmergencyGuard({
                "flux_restored": False,
                "flux_exact_original": False,
                "flux_restore_action": "external-change-preserved",
            })
            with patch("experiments.v2_3.flux_restore.PROJECT_ROOT", project):
                with self.assertRaisesRegex(PilotError, "exact original"):
                    restore_campaign(
                        campaign, guard=guard, recovery=FakeEmergencyRecovery()
                    )
            events = [json.loads(line) for line in
                      (campaign / "campaign_events.jsonl").read_text().splitlines()]
            self.assertEqual(events[-1]["event"], "flux_emergency_restore_failed")

    def test_missing_or_duplicate_receipt_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            campaign, _ = self.make_campaign(project)
            events = campaign / "campaign_events.jsonl"
            original = events.read_text()
            events.write_text(original + original)
            with patch("experiments.v2_3.flux_restore.PROJECT_ROOT", project):
                with self.assertRaisesRegex(PilotError, "exactly one"):
                    restore_campaign(
                        campaign, guard=FakeEmergencyGuard(),
                        recovery=FakeEmergencyRecovery(),
                    )

    def test_final_truncated_event_is_ignored_after_durable_receipt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            campaign, receipt = self.make_campaign(project)
            events = campaign / "campaign_events.jsonl"
            with events.open("ab") as handle:
                handle.write(b'{"event":"incident_failed","details":')
            guard = FakeEmergencyGuard()
            with patch("experiments.v2_3.flux_restore.PROJECT_ROOT", project):
                result = restore_campaign(
                    campaign, guard=guard, recovery=FakeEmergencyRecovery()
                )
            self.assertTrue(result["flux_exact_original"])
            self.assertEqual(guard.receipts, [receipt])

    def test_interior_malformed_event_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            campaign, _ = self.make_campaign(project)
            events = campaign / "campaign_events.jsonl"
            with events.open("ab") as handle:
                handle.write(b'{"event":bad}\n')
                handle.write(b'{"event":"incident_failed"}\n')
            with patch("experiments.v2_3.flux_restore.PROJECT_ROOT", project):
                with self.assertRaisesRegex(PilotError, "journal is malformed"):
                    restore_campaign(
                        campaign, guard=FakeEmergencyGuard(),
                        recovery=FakeEmergencyRecovery(),
                    )

    def test_final_truncated_utf8_event_is_ignored(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            campaign, _ = self.make_campaign(project)
            events = campaign / "campaign_events.jsonl"
            with events.open("ab") as handle:
                handle.write(b'{"event":"incident_failed","message":"\xed')
            with patch("experiments.v2_3.flux_restore.PROJECT_ROOT", project):
                result = restore_campaign(
                    campaign, guard=FakeEmergencyGuard(),
                    recovery=FakeEmergencyRecovery(),
                )
            self.assertTrue(result["flux_exact_original"])

    def test_f7_exact_recovery_precedes_flux_restore(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            campaign, _ = self.make_campaign(project)
            calls = []
            recovery = FakeEmergencyRecovery(calls=calls)
            guard = FakeEmergencyGuard(calls=calls)
            with patch("experiments.v2_3.flux_restore.PROJECT_ROOT", project):
                result = restore_campaign(campaign, guard=guard, recovery=recovery)
            self.assertEqual(calls, ["f7", "flux"])
            self.assertTrue(result["health_check_passed"])

    def test_flux_restore_still_runs_when_f7_recovery_fails(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            campaign, _ = self.make_campaign(project)
            calls = []
            recovery = FakeEmergencyRecovery(
                error=RuntimeError("F7 restore failed"), calls=calls
            )
            guard = FakeEmergencyGuard(calls=calls)
            with patch("experiments.v2_3.flux_restore.PROJECT_ROOT", project):
                with self.assertRaisesRegex(PilotError, "F7/Flux"):
                    restore_campaign(campaign, guard=guard, recovery=recovery)
            self.assertEqual(calls, ["f7", "flux"])

    def test_flux_only_restore_before_f7_receipt_crash_window(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            campaign, _ = self.make_campaign(project)
            events = campaign / "campaign_events.jsonl"
            records = [json.loads(line) for line in events.read_text().splitlines()]
            records = [
                record for record in records
                if record["event"] != "recovery_receipt_sealed"
            ]
            records.append({"event": "flux_suspended"})
            events.write_text("\n".join(json.dumps(record) for record in records) + "\n")
            calls = []
            recovery = FakeEmergencyRecovery(calls=calls)
            guard = FakeEmergencyGuard(calls=calls)
            with patch("experiments.v2_3.flux_restore.PROJECT_ROOT", project):
                result = restore_campaign(campaign, guard=guard, recovery=recovery)
            self.assertEqual(calls, ["flux"])
            self.assertEqual(result["action"], "not-started")

    def test_missing_f7_receipt_after_injection_start_fails_but_restores_flux(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            project = Path(temp_dir)
            campaign, _ = self.make_campaign(project)
            events = campaign / "campaign_events.jsonl"
            records = [json.loads(line) for line in events.read_text().splitlines()]
            records = [
                record for record in records
                if record["event"] != "recovery_receipt_sealed"
            ]
            records.append({"event": "injection_started"})
            events.write_text("\n".join(json.dumps(record) for record in records) + "\n")
            calls = []
            with patch("experiments.v2_3.flux_restore.PROJECT_ROOT", project):
                with self.assertRaisesRegex(PilotError, "F7/Flux"):
                    restore_campaign(
                        campaign,
                        guard=FakeEmergencyGuard(calls=calls),
                        recovery=FakeEmergencyRecovery(calls=calls),
                    )
            self.assertEqual(calls, ["flux"])


if __name__ == "__main__":
    unittest.main()

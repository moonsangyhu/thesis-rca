from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from control_plane.controller import ApprovalRequest, CampaignController, ControlPlaneConfig
from control_plane.errors import InvalidTransition, LockOwnershipError, ManifestValidationError
from control_plane.global_lock import GlobalCampaignLock
from control_plane.commands import ThesisCommandRouter
from control_plane.ipc import ControllerEndpoint, UnixControllerServer, send_command
from control_plane.isolation import probe_isolation, reject_out_of_sandbox_method
from control_plane.manifest import CampaignManifest
from control_plane.protocol import CommandEnvelope, EnvelopeSigner
from control_plane.state import CampaignState, CampaignStore, TRANSITIONS
from control_plane.watchdog import WatchdogInspector


def manifest(campaign_id: str = "v2.3-c01", fault: str = "F1") -> dict:
    return {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "source_commit": "a" * 40,
        "model": "gpt-4o-mini",
        "faults": [fault],
        "trials": [1],
        "timeout_seconds": 3600,
        "runner_profile": "v2_3",
        "restore_profile": "boutique_v1",
        "credential_profile": "lab_write_v1",
        "expected_rows": 5,
        "expected_raw_files": 5,
        "thread_ts": "1234567890.123456",
    }


def signed_envelope(
    signer: EnvelopeSigner,
    args: str,
    *,
    request_id: str = "Req-1",
    user_id: str = "U-allowed",
    channel_id: str = "C-allowed",
    thread_ts: str = "1234567890.123456",
    received_at: str | None = None,
) -> CommandEnvelope:
    return signer.sign(
        CommandEnvelope(
            version=1,
            request_id=request_id,
            platform="slack",
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            command="thesis",
            args=args,
            received_at=received_at or datetime.now(timezone.utc).isoformat(),
        )
    )


class ManifestTests(unittest.TestCase):
    def test_sha_is_canonical(self):
        first = manifest()
        second = dict(reversed(list(first.items())))
        self.assertEqual(CampaignManifest.parse(first).sha256, CampaignManifest.parse(second).sha256)

    def test_fail_closed_on_model_and_unknown_field(self):
        bad = manifest()
        bad["model"] = "gpt-5"
        with self.assertRaises(ManifestValidationError):
            CampaignManifest.parse(bad)
        bad = manifest()
        bad["command"] = "kubectl delete pod --all"
        with self.assertRaises(ManifestValidationError):
            CampaignManifest.parse(bad)


class StateMachineTests(unittest.TestCase):
    def test_normal_path_and_illegal_transition(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(Path(tmp))
            store.create("v2.3-c01", "b" * 64, "a" * 40)
            for target in (
                CampaignState.READY,
                CampaignState.APPROVED,
                CampaignState.PREFLIGHT,
                CampaignState.RUNNING,
                CampaignState.RESTORING,
                CampaignState.VERIFYING,
                CampaignState.COMPLETE,
            ):
                snapshot = store.transition("v2.3-c01", target, actor="test", reason="test")
            self.assertEqual(snapshot.state, CampaignState.COMPLETE)
            with self.assertRaises(InvalidTransition):
                store.transition("v2.3-c01", CampaignState.RUNNING, actor="test", reason="illegal")

    def test_every_declared_transition_is_executable(self):
        paths = {
            CampaignState.DRAFT: [],
            CampaignState.READY: [CampaignState.READY],
            CampaignState.APPROVED: [CampaignState.READY, CampaignState.APPROVED],
            CampaignState.PREFLIGHT: [
                CampaignState.READY, CampaignState.APPROVED, CampaignState.PREFLIGHT,
            ],
            CampaignState.RUNNING: [
                CampaignState.READY, CampaignState.APPROVED,
                CampaignState.PREFLIGHT, CampaignState.RUNNING,
            ],
            CampaignState.STOPPING: [
                CampaignState.READY, CampaignState.APPROVED, CampaignState.PREFLIGHT,
                CampaignState.RUNNING, CampaignState.STOPPING,
            ],
            CampaignState.RESTORING: [
                CampaignState.READY, CampaignState.APPROVED, CampaignState.PREFLIGHT,
                CampaignState.RUNNING, CampaignState.RESTORING,
            ],
            CampaignState.VERIFYING: [
                CampaignState.READY, CampaignState.APPROVED, CampaignState.PREFLIGHT,
                CampaignState.RUNNING, CampaignState.RESTORING, CampaignState.VERIFYING,
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            store = CampaignStore(Path(tmp))
            index = 0
            for source, targets in TRANSITIONS.items():
                for target in targets:
                    index += 1
                    campaign_id = f"transition-{index}"
                    store.create(campaign_id, "b" * 64, "a" * 40)
                    for step in paths.get(source, []):
                        store.transition(campaign_id, step, actor="test", reason="setup")
                    updated = store.transition(campaign_id, target, actor="test", reason="table")
                    self.assertEqual(updated.state, target)


class ApprovalTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.controller = CampaignController(
            self.root,
            ControlPlaneConfig(allowed_user_id="U-allowed", allowed_channel_id="C-allowed"),
        )

    def tearDown(self):
        self.tmp.cleanup()

    def request(self, campaign_id: str, sha: str, event_id: str) -> ApprovalRequest:
        return ApprovalRequest(
            event_id, "U-allowed", "C-allowed", campaign_id, sha, "1234567890.123456"
        )

    def test_duplicate_event_reuses_result_and_transitions_once(self):
        ready = self.controller.register_manifest(manifest())
        request = self.request("v2.3-c01", ready["manifest_sha256"], "Ev-1")
        first = self.controller.approve(request)
        second = self.controller.approve(request)
        self.assertEqual(first["status"], "approved")
        self.assertFalse(first["duplicate"])
        self.assertTrue(second["duplicate"])
        events = (self.root / "campaigns/v2.3-c01/events.jsonl").read_text().splitlines()
        approved = [json.loads(line) for line in events if json.loads(line)["state"] == "APPROVED"]
        self.assertEqual(len(approved), 1)
        self.assertEqual(
            (self.root / "campaigns/v2.3-c01/campaign.json").stat().st_mode & 0o777,
            0o400,
        )
        self.assertEqual((self.root / "events.sqlite3").stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / "campaign.lock").stat().st_mode & 0o777, 0o600)

    def test_identity_and_sha_are_bound(self):
        ready = self.controller.register_manifest(manifest())
        denied = self.controller.approve(
            ApprovalRequest(
                "Ev-user", "U-other", "C-allowed", "v2.3-c01",
                ready["manifest_sha256"], "1234567890.123456",
            )
        )
        self.assertEqual(denied["reason"], "user_not_allowed")
        mismatch = self.controller.approve(self.request("v2.3-c01", "0" * 64, "Ev-sha"))
        self.assertEqual(mismatch["reason"], "manifest_sha_mismatch")
        wrong_thread = self.controller.approve(
            ApprovalRequest(
                "Ev-thread", "U-allowed", "C-allowed", "v2.3-c01",
                ready["manifest_sha256"], "1234567890.999999",
            )
        )
        self.assertEqual(wrong_thread["reason"], "thread_not_bound")
        self.assertEqual(self.controller.campaigns.read("v2.3-c01").state, CampaignState.READY)

    def test_sealed_manifest_tampering_is_rejected(self):
        ready = self.controller.register_manifest(manifest())
        path = self.root / "campaigns/v2.3-c01/campaign.json"
        path.chmod(0o600)
        changed = json.loads(path.read_text())
        changed["thread_ts"] = "1234567890.999999"
        path.write_text(json.dumps(changed))
        denied = self.controller.approve(
            ApprovalRequest(
                "Ev-tampered", "U-allowed", "C-allowed", "v2.3-c01",
                ready["manifest_sha256"], "1234567890.999999",
            )
        )
        self.assertEqual(denied["reason"], "sealed_manifest_tampered")
        self.assertFalse(self.controller.global_lock.path.exists())

    def test_concurrent_approvals_have_one_global_winner(self):
        one = self.controller.register_manifest(manifest("v2.3-c01", "F1"))
        two = self.controller.register_manifest(manifest("v2.3-c02", "F2"))
        requests = [
            self.request("v2.3-c01", one["manifest_sha256"], "Ev-1"),
            self.request("v2.3-c02", two["manifest_sha256"], "Ev-2"),
        ]
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(self.controller.approve, requests))
        self.assertEqual(sum(result["status"] == "approved" for result in results), 1)
        self.assertEqual(sum(result.get("reason") == "global_lock_held" for result in results), 1)

    def test_approval_replays_from_journal_after_event_db_gap(self):
        ready = self.controller.register_manifest(manifest())
        request = self.request("v2.3-c01", ready["manifest_sha256"], "Ev-crash-gap")
        self.controller.global_lock.acquire(
            request.campaign_id,
            request.manifest_sha256,
            CampaignState.APPROVED,
        )
        self.controller.campaigns.transition(
            request.campaign_id,
            CampaignState.APPROVED,
            actor="slack_command",
            reason="simulated_crash_before_event_db_commit",
            event_id=request.event_id,
        )
        replay = self.controller.approve(request)
        self.assertEqual(replay["status"], "approved")
        self.assertFalse(replay["duplicate"])
        duplicate = self.controller.approve(request)
        self.assertTrue(duplicate["duplicate"])


class LockAndWatchdogTests(unittest.TestCase):
    def test_lock_cannot_be_released_without_safe_state_and_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            lock = GlobalCampaignLock(Path(tmp))
            record = lock.acquire("v2.3-c01", "b" * 64, CampaignState.RUNNING)
            with self.assertRaises(LockOwnershipError):
                lock.release(record.lease_id, CampaignState.BLOCKED)
            with self.assertRaises(LockOwnershipError):
                lock.release("0" * 32, CampaignState.SAFE_STOPPED)
            self.assertTrue(lock.path.exists())

    def test_watchdog_marks_start_time_mismatch_without_deleting_lock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock = GlobalCampaignLock(root)
            lock.acquire(
                "v2.3-c01",
                "b" * 64,
                CampaignState.RUNNING,
                controller_pid=42,
                process_start_time="2026-08-03T00:00:00+00:00",
            )
            finding = WatchdogInspector(root, lambda pid: "2026-08-03T00:00:01+00:00").inspect()
            self.assertEqual(finding.status, "stale_candidate")
            self.assertTrue(lock.path.exists())

    def test_watchdog_marks_invalid_lock_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root / "campaign.lock"
            path.write_text("")
            finding = WatchdogInspector(root, lambda pid: None).inspect()
            self.assertEqual(finding.status, "stale_candidate")
            self.assertEqual(finding.reason, "lock metadata invalid")
            self.assertTrue(path.exists())

    def test_watchdog_accepts_fresh_matching_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            started = "2026-08-03T00:00:00+00:00"
            lock = GlobalCampaignLock(root)
            lock.acquire(
                "v2.3-c01", "b" * 64, CampaignState.RUNNING,
                controller_pid=42, process_start_time=started,
            )
            campaign_dir = root / "campaigns/v2.3-c01"
            campaign_dir.mkdir(parents=True)
            now = datetime.now(timezone.utc)
            (campaign_dir / "heartbeat.json").write_text(json.dumps({"observed_at": now.isoformat()}))
            finding = WatchdogInspector(
                root,
                lambda pid: started,
                heartbeat_timeout=timedelta(minutes=3),
            ).inspect(now=now)
            self.assertEqual(finding.status, "healthy")


class IsolationBoundaryTests(unittest.TestCase):
    def test_probe_reports_access_without_exposing_values(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            signer_path = root / "signer.canary"
            socket_path = root / "controller.sock"
            signer_path.write_text("must-not-appear-in-output")
            listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            listener.bind(str(socket_path))
            listener.listen(1)
            name = "THESIS_TEST_SIGNER_CANARY"
            previous = os.environ.get(name)
            os.environ[name] = "must-not-appear-in-output"
            try:
                result = probe_isolation(
                    environment_name=name,
                    signer_path=signer_path,
                    socket_path=socket_path,
                )
            finally:
                listener.close()
                if previous is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = previous
            self.assertEqual(result.environment, "present")
            self.assertEqual(result.signer_file, "accessible")
            self.assertEqual(result.controller_socket, "accessible")
            self.assertFalse(result.isolated)
            self.assertNotIn("must-not-appear", json.dumps(result.public_dict()))

    def test_probe_rejects_untrusted_environment_name(self):
        with self.assertRaises(ValueError):
            probe_isolation(
                environment_name="BAD-NAME",
                signer_path=Path("unused"),
                socket_path=Path("unused"),
            )

    def test_out_of_sandbox_app_server_methods_are_rejected(self):
        for method in ("process/spawn", "thread/shellCommand"):
            with self.subTest(method=method), self.assertRaises(ValueError):
                reject_out_of_sandbox_method(method)
        reject_out_of_sandbox_method("command/exec")


class CommandProtocolTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.controller = CampaignController(
            self.root,
            ControlPlaneConfig(allowed_user_id="U-allowed", allowed_channel_id="C-allowed"),
        )
        self.signer = EnvelopeSigner(b"test-envelope-key-material-32-bytes-minimum")
        self.endpoint = ControllerEndpoint(ThesisCommandRouter(self.controller), self.signer)

    def tearDown(self):
        self.tmp.cleanup()

    def test_signed_approve_and_status_route_without_agent_loop(self):
        ready = self.controller.register_manifest(manifest())
        approved = self.endpoint.handle(
            signed_envelope(
                self.signer,
                f"approve v2.3-c01 {ready['manifest_sha256']}",
            ).to_dict()
        )
        self.assertEqual(approved["status"], "approved")
        status = self.endpoint.handle(
            signed_envelope(
                self.signer,
                "status v2.3-c01",
                request_id="Req-status",
                thread_ts="",
            ).to_dict()
        )
        self.assertEqual(status["state"], "APPROVED")
        audit = (self.root / "commands.jsonl").read_text().splitlines()
        self.assertEqual([json.loads(line)["subcommand"] for line in audit], ["approve", "status"])
        self.assertEqual((self.root / "commands.jsonl").stat().st_mode & 0o777, 0o600)

    def test_native_slash_resolves_registered_campaign_thread(self):
        ready = self.controller.register_manifest(manifest())
        approved = self.endpoint.handle(
            signed_envelope(
                self.signer,
                f"approve v2.3-c01 {ready['manifest_sha256']}",
                thread_ts="",
            ).to_dict()
        )
        self.assertEqual(approved["status"], "approved")

    def test_tampered_and_expired_envelopes_are_rejected(self):
        envelope = signed_envelope(self.signer, "status")
        tampered = envelope.to_dict()
        tampered["args"] = "approve forged deadbeef"
        self.assertEqual(
            self.endpoint.handle(tampered)["reason"],
            "invalid_envelope_signature",
        )
        expired = signed_envelope(
            self.signer,
            "status",
            request_id="Req-old",
            received_at=(datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat(),
        )
        self.assertEqual(self.endpoint.handle(expired.to_dict())["reason"], "envelope expired")

    def test_stop_before_running_releases_lock(self):
        ready = self.controller.register_manifest(manifest())
        approved = self.endpoint.handle(
            signed_envelope(
                self.signer,
                f"approve v2.3-c01 {ready['manifest_sha256']}",
                request_id="Req-approve",
            ).to_dict()
        )
        self.assertEqual(approved["status"], "approved")
        stopped = self.endpoint.handle(
            signed_envelope(
                self.signer,
                "stop v2.3-c01",
                request_id="Req-stop",
            ).to_dict()
        )
        self.assertEqual(stopped["status"], "stopped")
        self.assertEqual(stopped["state"], "SAFE_STOPPED")
        self.assertFalse(self.controller.global_lock.path.exists())

    def test_running_stop_only_requests_stopping_and_keeps_lock(self):
        ready = self.controller.register_manifest(manifest())
        self.controller.approve(
            ApprovalRequest(
                "Req-approve", "U-allowed", "C-allowed", "v2.3-c01",
                ready["manifest_sha256"], "1234567890.123456",
            )
        )
        self.controller.campaigns.transition(
            "v2.3-c01", CampaignState.PREFLIGHT, actor="test", reason="test"
        )
        self.controller.campaigns.transition(
            "v2.3-c01", CampaignState.RUNNING, actor="test", reason="test"
        )
        stopped = self.endpoint.handle(
            signed_envelope(
                self.signer,
                "stop v2.3-c01",
                request_id="Req-stop-running",
            ).to_dict()
        )
        self.assertEqual(stopped["state"], "STOPPING")
        self.assertTrue(self.controller.global_lock.path.exists())

    def test_stop_replays_from_journal_after_event_db_gap(self):
        self.controller.register_manifest(manifest())
        self.controller.campaigns.transition(
            "v2.3-c01",
            CampaignState.SAFE_STOPPED,
            actor="slack_command",
            reason="simulated_crash_before_event_db_commit",
            event_id="Req-stop-gap",
        )
        replay = self.endpoint.handle(
            signed_envelope(
                self.signer,
                "stop v2.3-c01",
                request_id="Req-stop-gap",
            ).to_dict()
        )
        self.assertEqual(replay["status"], "stopped")
        duplicate = self.endpoint.handle(
            signed_envelope(
                self.signer,
                "stop v2.3-c01",
                request_id="Req-stop-gap",
            ).to_dict()
        )
        self.assertTrue(duplicate["duplicate"])

    def test_unix_socket_round_trip_checks_peer_uid(self):
        server = UnixControllerServer(
            self.root / "controller.sock",
            self.endpoint,
            allowed_peer_uids={os.getuid()},
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            response = send_command(
                self.root / "controller.sock",
                signed_envelope(self.signer, "status", thread_ts=""),
            )
            self.assertEqual(response, {"active_campaign": None, "status": "ok"})
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        self.assertFalse((self.root / "controller.sock").exists())


if __name__ == "__main__":
    unittest.main()

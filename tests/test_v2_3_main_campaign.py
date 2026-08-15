import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from experiments.shared.copilot_identity import CopilotAccountIdentity
from experiments.v2_3.authorization import LiveAuthorization
from experiments.v2_3.main_campaign import run_authorized_main


class MainCampaignWiringTests(unittest.TestCase):
    def test_paid_main_records_startup_account_without_quota(self):
        authorization = LiveAuthorization.require_paid_overage(
            approval_id="paid-overage-20260812",
            environment={
                "THESIS_V23_PAID_OVERAGE_AUTHORIZED": "1",
                "THESIS_V23_PILOT_USER_APPROVED": "1",
            },
        )
        startup = CopilotAccountIdentity(
            login="moonsangyhu", source="gh-api-active-user",
            observed_at=datetime(2026, 8, 16, 1, tzinfo=timezone.utc).isoformat(),
        )
        backend = SimpleNamespace(
            executable="/opt/bin/copilot", sdk_sha256="a" * 64,
            runner_sha256="b" * 64, pre_call_guard=None,
            charge_observer=None,
        )
        store = MagicMock()
        runner = MagicMock()
        runner.run.return_value = {"rows": 3, "calls": 36}
        caller = SimpleNamespace(cumulative_aic=1.25)
        ground_truth = {("F1", 1): {"fault_id": "F1", "trial": 1}}

        replacements = {
            "experiments.shared.copilot_sdk.CopilotSDKBackend": MagicMock(return_value=backend),
            "experiments.shared.copilot_identity.inspect_active_gh_account": MagicMock(return_value=startup),
            "experiments.shared.copilot_quota.inspect_copilot_quota": MagicMock(side_effect=AssertionError("quota must not run")),
            "experiments.shared.csv_io.load_ground_truth": MagicMock(return_value=ground_truth),
            "experiments.shared.infra.preflight_check": MagicMock(return_value=True),
            "scripts.fault_inject.FaultInjector": MagicMock(),
            "scripts.fault_inject.base.kubectl_get_json": MagicMock(),
            "scripts.fault_inject.base.ssh_node": MagicMock(),
            "scripts.stabilize.Recovery": MagicMock(),
            "scripts.stabilize.state_validator.StateValidator": MagicMock(),
            "src.collector.SignalCollector": MagicMock(),
            "src.rag.retriever.KnowledgeRetriever": MagicMock(),
            "experiments.v2_3.engine.RCAEngineV2_3": MagicMock(),
            "experiments.v2_3.flux_restore.build_live_flux_guard": MagicMock(),
            "experiments.v2_3.injection_validator.LiveInjectionValidator": MagicMock(),
            "experiments.v2_3.ledger.CallLedger": MagicMock(),
            "experiments.v2_3.live_caller.AuthorizedTerraCaller": MagicMock(return_value=caller),
            "experiments.v2_3.live_runner.AttemptJournal": MagicMock(),
            "experiments.v2_3.live_runner.ChargedCallJournal": MagicMock(),
            "experiments.v2_3.live_runner.MainOutputStore": MagicMock(return_value=store),
            "experiments.v2_3.live_runner.PilotIncidentRunner": MagicMock(return_value=runner),
            "experiments.v2_3.live_runner.RuntimeOnlyRetriever": MagicMock(),
            "experiments.v2_3.live_runner.snapshot_tree": MagicMock(return_value="corpus"),
            "experiments.v2_3.run._local_cli_build_identity": MagicMock(
                return_value="package-and-native-sha"
            ),
            "experiments.v2_3.run._verified_git_revision": MagicMock(return_value="c" * 40),
        }
        with tempfile.TemporaryDirectory() as chroma, ExitStack() as stack:
            stack.enter_context(patch.dict("os.environ", {
                "THESIS_V23_PAID_OVERAGE_AUTHORIZED": "1",
                "THESIS_V23_PILOT_USER_APPROVED": "1",
            }, clear=False))
            stack.enter_context(patch("experiments.v2_3.main_campaign.FAULTS", ("F1",)))
            stack.enter_context(patch("experiments.v2_3.main_campaign.TRIALS", (1,)))
            stack.enter_context(patch("experiments.v2_3.main_campaign.time.sleep"))
            mocks = {name: stack.enter_context(patch(name, value)) for name, value in replacements.items()}
            summary = run_authorized_main(
                authorization, campaign_id="main-wiring-test",
                chroma_dir=Path(chroma),
            )

        self.assertEqual(summary["incidents"], 1)
        self.assertIsNone(backend.pre_call_guard)
        mocks["experiments.shared.copilot_quota.inspect_copilot_quota"].assert_not_called()
        self.assertEqual(
            mocks["experiments.shared.copilot_identity.inspect_active_gh_account"].call_count,
            1,
        )
        manifest = store.write_manifest.call_args.args[0]
        self.assertEqual(manifest["schema_version"], "v2.3-main-campaign-4")
        self.assertIsNone(manifest["billing_confirmed_at"])
        self.assertEqual(
            manifest["billing_confirmation_timestamp_status"],
            "not-recorded-in-authorization-seal",
        )
        self.assertIsNone(manifest["included_aic_balance_before"])
        self.assertEqual(manifest["server_quota"]["status"], "not-queried-paid-overage-mode")
        self.assertEqual(manifest["active_account"], startup.to_dict())
        self.assertEqual(
            manifest["cli_version_source"], "local-package-and-native-sha256"
        )
        self.assertFalse(any(
            call.args and call.args[0] == "account_identity_verified"
            for call in store.append_event.call_args_list
        ))


if __name__ == "__main__":
    unittest.main()

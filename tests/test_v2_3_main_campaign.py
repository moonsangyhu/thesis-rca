import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from experiments.v2_3.authorization import LiveAuthorization
from experiments.v2_3.main_campaign import run_authorized_main


class MainCampaignWiringTests(unittest.TestCase):
    def test_codex_subscription_main_seals_isolated_provider_provenance(self):
        authorization = LiveAuthorization.require_codex_subscription(
            approval_id="codex-subscription-20260829",
            environment={
                "THESIS_V23_CODEX_SUBSCRIPTION_AUTHORIZED": "1",
                "THESIS_V23_PILOT_USER_APPROVED": "1",
            },
        )
        backend = SimpleNamespace(
            executable="/opt/bin/codex", charge_observer=None,
        )
        store = MagicMock()
        runner = MagicMock()
        runner.run.return_value = {"rows": 3, "calls": 36}
        caller = SimpleNamespace(cumulative_aic=1.25)
        ground_truth = {("F1", 1): {"fault_id": "F1", "trial": 1}}

        replacements = {
            "experiments.shared.codex_cli.CodexCLIBackend": MagicMock(return_value=backend),
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
            "experiments.v2_3.run._probe_cli_version": MagicMock(return_value="codex-cli 0.150.1"),
            "experiments.v2_3.run._verified_git_revision": MagicMock(return_value="c" * 40),
        }
        with tempfile.TemporaryDirectory() as chroma, ExitStack() as stack:
            stack.enter_context(patch.dict("os.environ", {
                "THESIS_V23_CODEX_SUBSCRIPTION_AUTHORIZED": "1",
                "THESIS_V23_PILOT_USER_APPROVED": "1",
            }, clear=False))
            stack.enter_context(patch("experiments.v2_3.main_campaign.FAULTS", ("F1",)))
            stack.enter_context(patch("experiments.v2_3.main_campaign.TRIALS", (1,)))
            stack.enter_context(patch("experiments.v2_3.main_campaign.MAIN_INCIDENTS", (("F1", 1),)))
            stack.enter_context(patch("experiments.v2_3.main_campaign.MAIN_EXCLUDED_INCIDENTS", frozenset()))
            stack.enter_context(patch("experiments.v2_3.main_campaign.MAIN_EXPECTED_INCIDENTS", 1))
            stack.enter_context(patch("experiments.v2_3.main_campaign.MAIN_EXPECTED_ROWS", 3))
            stack.enter_context(patch("experiments.v2_3.main_campaign.MAIN_EXPECTED_CALLS", 36))
            stack.enter_context(patch("experiments.v2_3.main_campaign.time.sleep"))
            mocks = {name: stack.enter_context(patch(name, value)) for name, value in replacements.items()}
            summary = run_authorized_main(
                authorization, campaign_id="main-wiring-test",
                chroma_dir=Path(chroma),
            )

        self.assertEqual(summary["incidents"], 1)
        backend_factory = mocks["experiments.shared.codex_cli.CodexCLIBackend"]
        self.assertEqual(backend_factory.call_args.kwargs["timeout_seconds"], 300)
        manifest = store.write_manifest.call_args.args[0]
        self.assertEqual(manifest["schema_version"], "v2.3-main-campaign-7")
        self.assertEqual(manifest["codex_inference_timeout_seconds"], 300)
        self.assertIsNone(manifest["billing_confirmed_at"])
        self.assertEqual(
            manifest["billing_confirmation_timestamp_status"],
            "not-recorded-in-authorization-seal",
        )
        self.assertIsNone(manifest["included_aic_balance_before"])
        self.assertEqual(manifest["subscription_usage"]["status"], "token-count-only")
        self.assertEqual(manifest["provider"], "codex-cli-chatgpt-subscription")
        self.assertEqual(manifest["cli_version_source"], "codex-cli---version")
        self.assertFalse(any(
            call.args and call.args[0] == "account_identity_verified"
            for call in store.append_event.call_args_list
        ))
        live_validator_factory = mocks[
            "experiments.v2_3.injection_validator.LiveInjectionValidator"
        ]
        resource_loader = live_validator_factory.call_args.args[0]
        resource_loader("node", "yms-proxmox-04", "")
        self.assertEqual(
            mocks["scripts.fault_inject.base.kubectl_get_json"].call_args.kwargs[
                "timeout"
            ],
            5,
        )
        resource_loader("deployment", "frontend", "boutique")
        self.assertEqual(
            mocks["scripts.fault_inject.base.kubectl_get_json"].call_args.kwargs[
                "timeout"
            ],
            60,
        )


if __name__ == "__main__":
    unittest.main()

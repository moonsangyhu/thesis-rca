import tempfile
import unittest
import hashlib
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

from experiments.v2_3.engine import RCAEngineV2_3
from experiments.v2_3.live_runner import (
    AttemptJournal, ChargedCallJournal, F7InjectionValidator, FluxAppGuard,
    PilotError, PilotIncidentRunner, RecoveryFailure, RuntimeEvidenceRenderer,
    RuntimeOnlyRetriever,
)
from experiments.v2_3.mock import DeterministicMockCaller
from experiments.v2_3.scanner import ForbiddenLexicon
from tests.v2_3_helpers import LIVE_ENV, verified_authorization


class AuthorizedMockCaller(DeterministicMockCaller):
    def __init__(self, campaign_id, auth):
        super().__init__(campaign_id)
        self.authorization = auth


class FakeDoc:
    id = "generic-doc-1"
    content = "Compare timestamps, inspect neighboring signals, and test one reversible hypothesis."
    score = 0.8
    source = "docs/debugging/generic.md"
    filename = "generic.md"
    title = "Generic diagnostic procedure"


class FakeRetrievalBackend:
    def __init__(self):
        self.calls = []

    def query(self, **kwargs):
        self.calls.append(kwargs)
        return [FakeDoc()]


class FakeStore:
    output_dir = Path("/tmp/v2-3-unit-pilot")

    def __init__(self):
        self.writes = []
        self.events = []

    def write_incident(self, rows, raws, ledger_entries):
        self.writes.append((rows, raws, ledger_entries))

    def append_event(self, event, **details):
        self.events.append((event, details))


class FailingDiagnosticStore(FakeStore):
    def append_event(self, event, **details):
        if event == "incident_failed":
            raise OSError("simulated event journal failure")
        super().append_event(event, **details)


class FakeRecovery:
    def __init__(self, healthy=True):
        self.healthy = healthy
        self.calls = []

    def recover(self, fault_id, trial, injection_result):
        self.calls.append((fault_id, trial, injection_result))
        return {"health_check_passed": self.healthy}


class FakeFluxGuard:
    def __init__(self, suspend_error=None, restore_error=None):
        self.suspend_error = suspend_error
        self.restore_error = restore_error
        self.calls = []

    def prepare_recovery_context(self):
        self.calls.append("prepare")
        return {
            "flux_guard_schema": "v2.3-flux-app-guard-1",
            "flux_namespace": "flux-system", "flux_name": "app",
            "flux_uid": "uid-1", "flux_resource_version": "1",
            "flux_original_suspend_present": False,
            "flux_original_suspend": False,
        }

    def suspend(self, context):
        self.calls.append("suspend")
        if self.suspend_error:
            raise self.suspend_error
        return dict(context)

    def restore(self, context):
        self.calls.append("restore")
        if self.restore_error:
            raise self.restore_error
        return {
            "flux_restored": True, "flux_exact_original": True,
            "flux_suspend_present": False,
            "flux_restore_action": "cas-restored",
        }


class FakeInjector:
    def __init__(self, error=None):
        self.error = error
        self.calls = []

    def prepare_recovery_context(self, fault_id, trial):
        return {
            "fault_id": fault_id,
            "trial": trial,
            "target_service": "frontend",
            "container_name": "server",
            "original_cpu_limit": "200m",
            "original_cpu_request": "100m",
        }

    def inject(self, fault_id, trial, recovery_context=None):
        self.calls.append((fault_id, trial))
        if self.error:
            raise self.error
        return {
            **(recovery_context or {}),
            "fault_id": fault_id, "trial": trial, "target_service": "frontend",
            "action": "patch_cpu_limit", "cpu_limit": "10m", "wait_seconds": 0,
        }


class FakeCollector:
    def __init__(self, extra=None):
        self.extra = extra or {}
        self.calls = 0

    def collect_observability_only(self, window_minutes):
        self.calls += 1
        return {
            "metrics": {"latency": [1, 2, 3]},
            "logs": {"pod_logs": ["generic runtime warning"]},
            "kubectl": {"pods": [{"name": "frontend", "status": "Running"}]},
            **self.extra,
        }


GROUND_TRUTH = {
    "fault_id": "F7",
    "trial": "1",
    "fault_name": "CPUThrottle",
    "target_service": "frontend",
    "injection_method": "Set CPU limit to 10m on frontend",
    "expected_root_cause": "frontend exceeded its constrained CPU allocation",
    "affected_components": "frontend,checkoutservice",
    "primary_symptoms": "elevated request latency",
    "expected_metrics": "container_cpu_cfs_throttled_seconds_total increases",
    "expected_log_patterns": "deadline exceeded;slow request",
    "expected_recovery_action": "restore CPU resources",
}


class LiveRunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict("os.environ", LIVE_ENV, clear=False)
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def make_runner(
        self, *, injector=None, recovery=None, collector=None, journal=None,
        injection_validator=None, flux_guard=None,
    ):
        auth = verified_authorization(Path(self.temp.name))
        caller = AuthorizedMockCaller("pilot-campaign", auth)
        from experiments.v2_3.ledger import CallLedger
        engine = RCAEngineV2_3(
            caller,
            ledger=CallLedger(on_append=journal.append if journal else None),
            campaign_id="pilot-campaign",
        )
        backend = FakeRetrievalBackend()
        runner = PilotIncidentRunner(
            authorization=auth,
            engine=engine,
            injector=injector or FakeInjector(),
            recovery=recovery or FakeRecovery(),
            collector=collector or FakeCollector(),
            validator=SimpleNamespace(
                validate_and_correct=lambda **_: SimpleNamespace(status="clean")
            ),
            injection_validator=injection_validator or SimpleNamespace(
                validate=lambda *args: {"status": "verified"}
            ),
            flux_guard=flux_guard or FakeFluxGuard(),
            retriever=RuntimeOnlyRetriever(backend, corpus_version="corpus-snapshot-1"),
            store=FakeStore(),
            sleep_fn=lambda _: None,
        )
        return runner, backend

    def test_success_collects_once_commits_three_arms_and_recovers_once(self):
        runner, backend = self.make_runner()
        summary = runner.run("F7", 1, GROUND_TRUTH)
        self.assertEqual((summary["rows"], summary["calls"]), (3, 36))
        self.assertEqual(runner.collector.calls, 1)
        self.assertEqual(len(runner.store.writes), 1)
        self.assertEqual(len(runner.recovery.calls), 1)
        self.assertEqual(runner.flux_guard.calls, ["prepare", "suspend", "restore"])
        self.assertEqual(len(backend.calls), 1)
        self.assertIsNone(backend.calls[0]["fault_type"])
        rows, raws, ledger = runner.store.writes[0]
        self.assertEqual(len(rows), 3)
        self.assertEqual(len(raws), 3)
        self.assertEqual(len(ledger), 36)
        self.assertEqual(len({row["runtime_context_hash"] for row in rows}), 1)
        events = [event for event, _ in runner.store.events]
        self.assertLess(events.index("flux_suspended"), events.index("injection_started"))
        self.assertLess(events.index("flux_restored"), events.index("recovery_green"))
        self.assertLess(events.index("recovery_green"), events.index("incident_committed"))

    def test_pilot_rejects_invalidated_f7_trial_5_before_injection(self):
        runner, _ = self.make_runner()
        with self.assertRaisesRegex(PilotError, "frozen to F7 trial 1"):
            runner.run("F7", 5, GROUND_TRUTH)
        self.assertEqual(runner.injector.calls, [])

    def test_injection_exception_still_attempts_recovery(self):
        injector = FakeInjector(error=RuntimeError("partial injection"))
        recovery = FakeRecovery()
        runner, _ = self.make_runner(injector=injector, recovery=recovery)
        with self.assertRaisesRegex(RuntimeError, "partial injection"):
            runner.run("F7", 1, GROUND_TRUTH)
        self.assertEqual(len(recovery.calls), 1)
        self.assertEqual(runner.flux_guard.calls[-1], "restore")
        self.assertEqual(recovery.calls[0][2]["original_cpu_limit"], "200m")
        events = [event for event, _ in runner.store.events]
        self.assertLess(
            events.index("recovery_receipt_sealed"), events.index("injection_started")
        )

    def test_run_revalidates_authorization_before_injection(self):
        runner, _ = self.make_runner()
        with patch.dict("os.environ", {
            "THESIS_COPILOT_ZERO_OVERAGE_CONFIRMED": "0",
            "THESIS_V23_PILOT_USER_APPROVED": "0",
        }, clear=False):
            with self.assertRaisesRegex(RuntimeError, "zero-overage"):
                runner.run("F7", 1, GROUND_TRUTH)
        self.assertEqual(len(runner.injector.calls), 0)

    def test_collection_contamination_fails_and_recovers(self):
        collector = FakeCollector(extra={"gitops": {"forbidden": True}})
        recovery = FakeRecovery()
        runner, _ = self.make_runner(collector=collector, recovery=recovery)
        with self.assertRaisesRegex(PilotError, "non-runtime"):
            runner.run("F7", 1, GROUND_TRUTH)
        self.assertEqual(len(recovery.calls), 1)
        self.assertEqual(len(runner.store.writes), 0)

    def test_post_injection_failure_stops_before_collection_and_recovers(self):
        injection_validator = SimpleNamespace(
            validate=lambda *args: (_ for _ in ()).throw(
                PilotError("post-injection mismatch")
            )
        )
        runner, _ = self.make_runner(injection_validator=injection_validator)
        with self.assertRaisesRegex(PilotError, "post-injection mismatch"):
            runner.run("F7", 1, GROUND_TRUTH)
        self.assertEqual(runner.collector.calls, 0)
        self.assertEqual(len(runner.recovery.calls), 1)
        self.assertEqual(len(runner.store.writes), 0)
        self.assertIn("incident_failed", [event for event, _ in runner.store.events])

    def test_incident_failed_event_error_cannot_bypass_recovery(self):
        recovery = FakeRecovery()
        injection_validator = SimpleNamespace(
            validate=lambda *args: (_ for _ in ()).throw(
                PilotError("post-injection mismatch")
            )
        )
        runner, _ = self.make_runner(
            recovery=recovery, injection_validator=injection_validator
        )
        runner.store = FailingDiagnosticStore()

        with self.assertRaisesRegex(PilotError, "post-injection mismatch"):
            runner.run("F7", 1, GROUND_TRUTH)

        self.assertEqual(len(recovery.calls), 1)
        self.assertIn("recovery_green", [event for event, _ in runner.store.events])

    def test_recovery_not_green_invalidates_pilot(self):
        recovery = FakeRecovery(healthy=False)
        runner, _ = self.make_runner(recovery=recovery)
        with self.assertRaises(RecoveryFailure):
            runner.run("F7", 1, GROUND_TRUTH)
        self.assertEqual(len(runner.store.writes), 0)
        self.assertEqual(runner.flux_guard.calls[-1], "restore")

    def test_partial_flux_suspend_error_still_restores_original_state(self):
        flux = FakeFluxGuard(suspend_error=RuntimeError("patch timeout"))
        runner, _ = self.make_runner(flux_guard=flux)
        with self.assertRaisesRegex(RuntimeError, "patch timeout"):
            runner.run("F7", 1, GROUND_TRUTH)
        self.assertEqual(flux.calls, ["prepare", "suspend", "restore"])
        self.assertEqual(runner.injector.calls, [])

    def test_flux_guard_cannot_alter_sealed_receipt(self):
        flux = FakeFluxGuard()

        def altered(context):
            flux.calls.append("suspend")
            return {**context, "flux_resource_version": "forged"}

        flux.suspend = altered
        runner, _ = self.make_runner(flux_guard=flux)
        with self.assertRaisesRegex(PilotError, "altered"):
            runner.run("F7", 1, GROUND_TRUTH)
        self.assertEqual(flux.calls, ["prepare", "suspend", "restore"])
        self.assertEqual(runner.injector.calls, [])

    def test_flux_restore_failure_invalidates_result_after_cluster_recovery(self):
        flux = FakeFluxGuard(restore_error=RuntimeError("restore failed"))
        runner, _ = self.make_runner(flux_guard=flux)
        with self.assertRaises(RecoveryFailure):
            runner.run("F7", 1, GROUND_TRUTH)
        self.assertEqual(len(runner.recovery.calls), 1)
        self.assertEqual(len(runner.store.writes), 0)

    def test_flux_guard_restores_absent_suspend_field_exactly(self):
        state = {
            "metadata": {
                "namespace": "flux-system", "name": "app",
                "uid": "uid-1", "resourceVersion": "10",
            },
            "spec": {"interval": "10m"},
        }

        def load():
            import copy
            return copy.deepcopy(state)

        def patch_suspend(value, resource_version):
            self.assertEqual(resource_version, state["metadata"]["resourceVersion"])
            if value is None:
                state["spec"].pop("suspend", None)
            else:
                state["spec"]["suspend"] = value
            state["metadata"]["resourceVersion"] = str(
                int(state["metadata"]["resourceVersion"]) + 1
            )
            return load()

        guard = FluxAppGuard(load, patch_suspend)
        receipt = guard.prepare_recovery_context()
        guard.suspend(receipt)
        self.assertIs(state["spec"]["suspend"], True)
        restored = guard.restore(receipt)
        self.assertNotIn("suspend", state["spec"])
        self.assertTrue(restored["flux_restored"])
        self.assertTrue(restored["flux_exact_original"])

    def test_flux_guard_rejects_preexisting_suspension(self):
        resource = {
            "metadata": {
                "namespace": "flux-system", "name": "app",
                "uid": "uid-1", "resourceVersion": "10",
            },
            "spec": {"suspend": True},
        }
        guard = FluxAppGuard(lambda: resource, lambda _: None)
        with self.assertRaisesRegex(PilotError, "must be active"):
            guard.prepare_recovery_context()

    def test_flux_guard_rejects_missing_resource_version(self):
        resource = {
            "metadata": {
                "namespace": "flux-system", "name": "app", "uid": "uid-1",
            },
            "spec": {},
        }
        guard = FluxAppGuard(lambda: resource, lambda *_: {})
        with self.assertRaisesRegex(PilotError, "resourceVersion"):
            guard.prepare_recovery_context()

    def test_flux_guard_preserves_concurrent_false_field_on_cas_conflict(self):
        state = {
            "metadata": {
                "namespace": "flux-system", "name": "app",
                "uid": "uid-1", "resourceVersion": "10",
            },
            "spec": {"interval": "10m"},
        }
        patch_calls = []

        def load():
            import copy
            return copy.deepcopy(state)

        def patch_suspend(value, resource_version):
            patch_calls.append((value, resource_version))
            return load()

        guard = FluxAppGuard(load, patch_suspend)
        receipt = guard.prepare_recovery_context()
        state["metadata"]["resourceVersion"] = "11"
        state["spec"]["suspend"] = False

        with self.assertRaisesRegex(PilotError, "changed after"):
            guard.suspend(receipt)
        restored = guard.restore(receipt)

        self.assertEqual(patch_calls, [])
        self.assertIn("suspend", state["spec"])
        self.assertIs(state["spec"]["suspend"], False)
        self.assertFalse(restored["flux_restored"])
        self.assertEqual(restored["flux_restore_action"], "external-change-preserved")

    def test_f7_post_injection_validator_binds_identity_and_live_state(self):
        deployment = {
            "spec": {"template": {"spec": {"containers": [{
                "name": "server",
                "resources": {
                    "limits": {"cpu": "10m"}, "requests": {"cpu": "10m"}
                },
            }]}}}
        }
        pods = {"items": [{
            "metadata": {"labels": {"app": "frontend"}},
            "spec": {"containers": [{
                "name": "server",
                "resources": {
                    "limits": {"cpu": "10m"}, "requests": {"cpu": "10m"}
                },
            }]},
            "status": {
                "phase": "Running",
                "containerStatuses": [{"name": "server", "ready": True}],
            },
        }]}
        validator = F7InjectionValidator(lambda _: deployment, lambda: pods)
        result = FakeInjector().inject("F7", 1)
        self.assertEqual(
            validator.validate("F7", 1, GROUND_TRUTH, result)["status"], "verified"
        )
        bad = dict(result, trial=4)
        with self.assertRaisesRegex(PilotError, "trial identity"):
            validator.validate("F7", 1, GROUND_TRUTH, bad)

    def test_short_injection_value_is_forbidden(self):
        from experiments.v2_3.live_runner import build_forbidden_lexicon
        from experiments.v2_3.scanner import LeakageScanner
        lexicon = build_forbidden_lexicon(
            "F7", 1, GROUND_TRUTH, FakeInjector().inject("F7", 1)
        )
        self.assertIn("10m", lexicon.field_values)
        self.assertGreater(LeakageScanner().scan("limit=10-m", lexicon).match_count, 0)

    def test_attempt_journal_fsync_path_receives_all_calls(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = AttemptJournal(Path(temp_dir) / "attempts.jsonl")
            runner, _ = self.make_runner(journal=journal)
            runner.run("F7", 1, GROUND_TRUTH)
            lines = journal.path.read_text().splitlines()
            self.assertEqual(len(lines), 36)

    def test_charged_call_journal_preserves_incomplete_attempt(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            journal = ChargedCallJournal(Path(temp_dir) / "charged.jsonl")
            journal.append({
                "attempt_id": "attempt-1", "requested_model": "gpt-5.6-terra",
                "actual_model": None, "session_id": None, "output_tokens": None,
                "ai_credits": None, "premium_requests": None,
                "usage_metadata_complete": False,
                "started_at": "2026-08-09T00:00:00+00:00",
                "ended_at": "2026-08-09T00:00:01+00:00", "latency_ms": 1000,
                "exit_code": 1, "timed_out": False,
                "cli_executable": "/opt/bin/copilot", "temporary_cwd_id": "isolated",
                "stdout_hash": hashlib.sha256(b"").hexdigest(),
                "stderr_hash": hashlib.sha256(b"failure").hexdigest(),
            })
            self.assertEqual(len(journal.path.read_text().splitlines()), 1)

    def test_runtime_renderer_rejects_gitops(self):
        with self.assertRaises(PilotError):
            RuntimeEvidenceRenderer().render({
                "metrics": {}, "logs": {}, "kubectl": {}, "gitops": {}
            })

    def test_runtime_retrieval_masks_observed_label_but_keeps_observed_entity(self):
        backend = FakeRetrievalBackend()
        retriever = RuntimeOnlyRetriever(
            backend, corpus_version="corpus-snapshot-1", query_char_limit=4000
        )
        result = retriever.retrieve(
            "CPUThrottle frontend reports warning",
            ForbiddenLexicon(
                canonical_labels=("CPUThrottle",), entities=("frontend",)
            ),
        )
        query = backend.calls[0]["query_text"]
        self.assertNotIn("CPUThrottle", query)
        self.assertIn("frontend", query)
        self.assertGreater(
            len(result.procedure.provenance["query_removed_spans"]), 0
        )

    def test_f7_injector_captures_exact_pre_injection_cpu_resources(self):
        from scripts.fault_inject.injector import FaultInjector

        deployment = {
            "spec": {"template": {"spec": {"containers": [{
                "name": "server",
                "resources": {
                    "limits": {"cpu": "200m"},
                    "requests": {"cpu": "100m"},
                },
            }]}}}
        }
        with patch(
            "scripts.fault_inject.injector.kubectl_get_json", return_value=deployment
        ), patch("scripts.fault_inject.injector.kubectl", return_value="updated"):
            injector = FaultInjector()
            recovery_context = injector.prepare_recovery_context("F7", 1)
            result = injector._inject_f7_cpu_throttle(
                "frontend", 1, {}, recovery_context
            )
        self.assertEqual(result["container_name"], "server")
        self.assertEqual(result["original_cpu_limit"], "200m")
        self.assertEqual(result["original_cpu_request"], "100m")
        self.assertEqual(result["cpu_limit"], "10m")

    def test_f7_partial_mutation_error_keeps_pre_state_for_recovery(self):
        recovery = FakeRecovery()
        injector = FakeInjector(error=TimeoutError("applied then timed out"))
        runner, _ = self.make_runner(injector=injector, recovery=recovery)
        with self.assertRaisesRegex(TimeoutError, "applied then timed out"):
            runner.run("F7", 1, GROUND_TRUTH)
        receipt = recovery.calls[0][2]
        self.assertEqual(receipt["container_name"], "server")
        self.assertEqual(receipt["original_cpu_limit"], "200m")
        self.assertEqual(receipt["original_cpu_request"], "100m")

    def test_f7_recovery_requires_exact_desired_cpu_and_rollout_state(self):
        from scripts.stabilize.recovery import Recovery

        restored = {
            "metadata": {"generation": 21},
            "spec": {
                "replicas": 1,
                "template": {"spec": {"containers": [{
                    "name": "server",
                    "resources": {
                        "limits": {"cpu": "200m"},
                        "requests": {"cpu": "100m"},
                    },
                }]}},
            },
            "status": {
                "observedGeneration": 21,
                "updatedReplicas": 1,
                "readyReplicas": 1,
                "availableReplicas": 1,
            },
        }
        receipt = {
            "target_service": "frontend",
            "container_name": "server",
            "original_cpu_limit": "200m",
            "original_cpu_request": "100m",
        }
        with patch("scripts.stabilize.recovery.kubectl") as kubectl_mock, patch(
            "scripts.stabilize.recovery.kubectl_get_json", return_value=restored
        ):
            result = Recovery()._recover_f7(5, receipt)
        self.assertTrue(result["desired_state_verified"])
        self.assertEqual(result["cpu_limit"], "200m")
        self.assertIn("--containers=server", kubectl_mock.call_args_list[0].args)

        stale = dict(restored)
        stale["spec"] = dict(restored["spec"])
        stale["spec"]["template"] = {"spec": {"containers": [{
            "name": "server",
            "resources": {
                "limits": {"cpu": "10m"}, "requests": {"cpu": "10m"}
            },
        }]}}
        with patch("scripts.stabilize.recovery.kubectl"), patch(
            "scripts.stabilize.recovery.kubectl_get_json", return_value=stale
        ):
            with self.assertRaisesRegex(RuntimeError, "not fully restored"):
                Recovery()._recover_f7(5, receipt)

    def test_f10_recovery_does_not_use_unsupported_namespace_restart(self):
        from scripts.stabilize.recovery import Recovery

        with patch("scripts.stabilize.recovery.kubectl_delete") as delete, patch(
            "scripts.stabilize.recovery.kubectl"
        ) as kubectl_mock:
            result = Recovery()._recover_f10(2, {})
        delete.assert_called_once_with("resourcequota", "fault-quota-cpu")
        kubectl_mock.assert_not_called()
        self.assertEqual(result, {"action": "delete_quota", "trial": 2})


if __name__ == "__main__":
    unittest.main()

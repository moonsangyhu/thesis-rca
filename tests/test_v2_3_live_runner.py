import tempfile
import unittest
import hashlib
import json
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

from experiments.v2_3.engine import RCAEngineV2_3
from experiments.v2_3.live_runner import (
    F4DisruptionNotObserved,
    F4ObservationTimeout,
    AttemptJournal, ChargedCallJournal, F7InjectionValidator, FluxAppGuard,
    FluxCASConflict, FluxHierarchyGuard, PilotError, PilotIncidentRunner, RecoveryFailure,
    RuntimeEvidenceRenderer, RuntimeOnlyRetriever,
    validate_f4_t3_evidence_deadline,
    validate_injection_in_observation_window,
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
            "flux_original_spec_sha256": "a" * 64,
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


class FakeHierarchyMember:
    def __init__(self, name, calls, restore_error=None):
        self.name = name
        self.calls = calls
        self.restore_error = restore_error
        self.stable = True

    def prepare_recovery_context(self):
        self.calls.append(f"prepare-{self.name}")
        return {"name": self.name}

    def suspend(self, receipt):
        self.calls.append(f"suspend-{self.name}")
        return receipt

    def verify_suspended(self, receipt):
        self.calls.append(f"settle-{self.name}")
        if not self.stable:
            raise PilotError(f"{self.name} drift")

    def restore(self, receipt):
        self.calls.append(f"restore-{self.name}")
        if self.restore_error:
            raise self.restore_error
        return {
            "flux_restored": True, "flux_exact_original": True,
            "flux_suspend_present": False, "flux_restore_action": "cas-restored",
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
        injection_validator=None, flux_guard=None, infrastructure_flux_guard=None,
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
            infrastructure_flux_guard=infrastructure_flux_guard,
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

    def test_f5_trial_3_uses_infrastructure_flux_guard_only(self):
        app_guard = FakeFluxGuard()
        infrastructure_guard = FakeFluxGuard()
        runner, _ = self.make_runner(
            flux_guard=app_guard,
            infrastructure_flux_guard=infrastructure_guard,
        )
        runner.allowed_incidents = frozenset({("F5", 3)})
        summary = runner.run(
            "F5", 3, {**GROUND_TRUTH, "fault_id": "F5", "trial": "3"}
        )
        self.assertEqual((summary["rows"], summary["calls"]), (3, 36))
        self.assertEqual(app_guard.calls, [])
        self.assertEqual(
            infrastructure_guard.calls, ["prepare", "suspend", "restore"]
        )

    def test_f5_trial_3_without_infrastructure_guard_fails_before_mutation(self):
        runner, _ = self.make_runner()
        runner.allowed_incidents = frozenset({("F5", 3)})
        with self.assertRaisesRegex(PilotError, "infrastructure Flux guard"):
            runner.run("F5", 3, {**GROUND_TRUTH, "fault_id": "F5", "trial": "3"})
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

    def test_leakage_failure_records_safe_stage_and_still_recovers(self):
        from experiments.v2_3.scanner import LeakageDetected

        collector = FakeCollector(
            extra={"logs": {"pod_logs": ["fault_id F7"]}}
        )
        recovery = FakeRecovery()
        runner, _ = self.make_runner(collector=collector, recovery=recovery)
        with self.assertRaises(LeakageDetected):
            runner.run("F7", 1, GROUND_TRUTH)
        failures = [
            details for event, details in runner.store.events
            if event == "incident_failed"
        ]
        self.assertEqual(len(failures), 1)
        diagnostic = failures[0]["leakage_diagnostic"]
        self.assertEqual(diagnostic["stage"], "runtime_context")
        self.assertNotIn("term", diagnostic["matches"][0])
        self.assertEqual(len(recovery.calls), 1)
        self.assertEqual(runner.store.writes, [])

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

    def test_failed_observed_cas_uses_latest_durable_receipt_for_normal_restore(self):
        class ObservedFailureGuard:
            def __init__(self):
                self.restored = None

            def prepare_recovery_context(self):
                return {
                    "flux_hierarchy_schema": "v2.3-flux-hierarchy-1",
                    "root": {"flux_resource_version": "1"},
                    "app": {"flux_resource_version": "1"},
                }

            def suspend_with_receipt_observer(self, context, observer):
                for version in ("2", "3"):
                    receipt = json.loads(json.dumps(context))
                    receipt["app"]["flux_resource_version"] = version
                    observer(receipt)
                raise PilotError("retry limit")

            def restore(self, context):
                self.restored = context
                return {
                    "flux_restored": True, "flux_exact_original": True,
                    "flux_suspend_present": False,
                    "flux_restore_action": "cas-restored",
                }

        flux = ObservedFailureGuard()
        runner, _ = self.make_runner(flux_guard=flux)
        with self.assertRaisesRegex(PilotError, "retry limit"):
            runner.run("F7", 1, GROUND_TRUTH)
        self.assertEqual(flux.restored["app"]["flux_resource_version"], "3")
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

    def test_nested_flux_receipt_mutation_cannot_change_recovery_copy(self):
        class NestedMutatingGuard:
            def __init__(self):
                self.restored = None

            def prepare_recovery_context(self):
                return {
                    "flux_hierarchy_schema": "v2.3-flux-hierarchy-1",
                    "root": {"flux_resource_version": "10"},
                    "app": {"flux_resource_version": "20"},
                }

            def suspend(self, context):
                context["root"]["flux_resource_version"] = "forged"
                return context

            def restore(self, context):
                self.restored = context
                return {
                    "flux_restored": True, "flux_exact_original": True,
                    "flux_suspend_present": False,
                    "flux_restore_action": "cas-restored",
                }

        flux = NestedMutatingGuard()
        runner, _ = self.make_runner(flux_guard=flux)
        with self.assertRaisesRegex(PilotError, "altered"):
            runner.run("F7", 1, GROUND_TRUTH)
        self.assertEqual(flux.restored["root"]["flux_resource_version"], "10")
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

    def test_flux_guard_classifies_failed_patch_with_unchanged_state_as_cas_race(self):
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

        def lose_cas(_value, resource_version):
            self.assertEqual(resource_version, "10")
            state["metadata"]["resourceVersion"] = "11"
            return {}

        guard = FluxAppGuard(load, lose_cas)
        with self.assertRaisesRegex(FluxCASConflict, "resourceVersion race"):
            guard.suspend(guard.prepare_recovery_context())
        self.assertNotIn("suspend", state["spec"])

    def test_flux_guard_does_not_retry_unrelated_spec_drift(self):
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

        guard = FluxAppGuard(load, lambda *_: {})
        receipt = guard.prepare_recovery_context()
        state["metadata"]["resourceVersion"] = "11"
        state["spec"]["interval"] = "1m"
        with self.assertRaises(PilotError) as raised:
            guard.suspend(receipt)
        self.assertNotIsInstance(raised.exception, FluxCASConflict)

    def test_flux_hierarchy_suspends_root_then_app_and_restores_reverse(self):
        calls = []
        root = FakeHierarchyMember("root", calls)
        app = FakeHierarchyMember("app", calls)
        guard = FluxHierarchyGuard(root, app)
        receipt = guard.prepare_recovery_context()
        observed = []
        refreshed = guard.suspend_with_receipt_observer(receipt, observed.append)
        result = guard.restore(refreshed)
        self.assertEqual(calls, [
            "prepare-root", "prepare-app",
            "suspend-root", "settle-root", "prepare-app", "suspend-app",
            "settle-root", "settle-app", "settle-root", "settle-app",
            "restore-app", "restore-root",
        ])
        self.assertEqual(observed, [refreshed])
        self.assertTrue(result["flux_exact_original"])

    def test_flux_hierarchy_restores_root_even_when_app_restore_fails(self):
        calls = []
        root = FakeHierarchyMember("root", calls)
        app = FakeHierarchyMember("app", calls, restore_error=RuntimeError("app"))
        guard = FluxHierarchyGuard(root, app)
        receipt = guard.prepare_recovery_context()
        with self.assertRaisesRegex(PilotError, "hierarchy"):
            guard.restore(receipt)
        self.assertEqual(calls[-2:], ["restore-app", "restore-root"])

    def test_flux_hierarchy_rejects_root_drift_during_app_settle(self):
        calls = []
        root = FakeHierarchyMember("root", calls)
        app = FakeHierarchyMember("app", calls)

        def adversarial_settle(*members):
            if len(members) == 2:
                root.stable = False
            for member, receipt in members:
                member.verify_suspended(receipt)

        guard = FluxHierarchyGuard(root, app, settle=adversarial_settle)
        receipt = guard.prepare_recovery_context()
        with self.assertRaisesRegex(PilotError, "root drift"):
            guard.suspend_with_receipt_observer(receipt, lambda _: None)

    def test_flux_hierarchy_refreshes_child_receipt_after_root_settle(self):
        calls = []

        class RefreshingMember(FakeHierarchyMember):
            def __init__(self, name, calls, resource_version):
                super().__init__(name, calls)
                self.resource_version = resource_version

            def prepare_recovery_context(self):
                self.calls.append(f"prepare-{self.name}")
                return {
                    "flux_guard_schema": "v2.3-flux-app-guard-1",
                    "flux_namespace": "flux-system",
                    "flux_name": self.name,
                    "flux_uid": f"uid-{self.name}",
                    "flux_resource_version": self.resource_version,
                    "flux_original_spec_sha256": "a" * 64,
                    "flux_original_suspend_present": False,
                    "flux_original_suspend": False,
                }

            def suspend(self, receipt):
                self.calls.append(f"suspend-{self.name}-{receipt['flux_resource_version']}")
                if receipt["flux_resource_version"] != self.resource_version:
                    raise PilotError("stale receipt")
                return receipt

        root = RefreshingMember("root", calls, "10")
        app = RefreshingMember("app", calls, "20")

        def settle(*members):
            calls.extend(f"settle-{member.name}" for member, _ in members)
            if len(members) == 1:
                app.resource_version = "21"

        guard = FluxHierarchyGuard(root, app, settle=settle)
        initial = guard.prepare_recovery_context()
        observed = []
        refreshed = guard.suspend_with_receipt_observer(initial, observed.append)

        self.assertEqual(initial["app"]["flux_resource_version"], "20")
        self.assertEqual(refreshed["app"]["flux_resource_version"], "21")
        self.assertEqual(observed[0]["app"]["flux_resource_version"], "21")
        self.assertLess(
            calls.index("prepare-app", calls.index("suspend-root-10")),
            calls.index("suspend-app-21"),
        )

    def test_flux_hierarchy_reseals_and_retries_unchanged_app_cas_races(self):
        calls = []
        root = FakeHierarchyMember("root", calls)

        class RacingApp(FakeHierarchyMember):
            def __init__(self):
                super().__init__("app", calls)
                self.resource_version = 20
                self.conflicts = 2

            def prepare_recovery_context(self):
                self.calls.append("prepare-app")
                return {
                    "flux_guard_schema": "v2.3-flux-app-guard-1",
                    "flux_namespace": "flux-system", "flux_name": "app",
                    "flux_uid": "uid-app",
                    "flux_resource_version": str(self.resource_version),
                    "flux_original_spec_sha256": "a" * 64,
                    "flux_original_suspend_present": False,
                    "flux_original_suspend": False,
                }

            def suspend(self, receipt):
                self.calls.append(f"suspend-app-{receipt['flux_resource_version']}")
                if self.conflicts:
                    self.conflicts -= 1
                    self.resource_version += 1
                    raise FluxCASConflict("status writer advanced resourceVersion")
                return receipt

        app = RacingApp()
        guard = FluxHierarchyGuard(root, app, settle=lambda *_: None)
        initial = guard.prepare_recovery_context()
        observed = []
        result = guard.suspend_with_receipt_observer(initial, observed.append)

        self.assertEqual(
            [item["app"]["flux_resource_version"] for item in observed],
            ["20", "21", "22"],
        )
        self.assertEqual(result, observed[-1])

    def test_flux_hierarchy_stops_after_bounded_app_cas_conflicts(self):
        calls = []
        root = FakeHierarchyMember("root", calls)

        class AlwaysRacingApp(FakeHierarchyMember):
            def __init__(self):
                super().__init__("app", calls)
                self.resource_version = 20

            def prepare_recovery_context(self):
                return {
                    "flux_guard_schema": "v2.3-flux-app-guard-1",
                    "flux_namespace": "flux-system", "flux_name": "app",
                    "flux_uid": "uid-app",
                    "flux_resource_version": str(self.resource_version),
                    "flux_original_spec_sha256": "a" * 64,
                    "flux_original_suspend_present": False,
                    "flux_original_suspend": False,
                }

            def suspend(self, receipt):
                self.resource_version += 1
                raise FluxCASConflict("continuous race")

        app = AlwaysRacingApp()
        guard = FluxHierarchyGuard(root, app, settle=lambda *_: None)
        observed = []
        with self.assertRaisesRegex(PilotError, "retry limit"):
            guard.suspend_with_receipt_observer(
                guard.prepare_recovery_context(), observed.append
            )
        self.assertEqual(len(observed), FluxHierarchyGuard.MAX_APP_CAS_ATTEMPTS)

    def test_flux_hierarchy_rejects_suspend_without_durable_observer(self):
        guard = FluxHierarchyGuard(
            FakeHierarchyMember("root", []), FakeHierarchyMember("app", [])
        )
        with self.assertRaisesRegex(PilotError, "durable receipt observer"):
            guard.suspend(guard.prepare_recovery_context())

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

    def test_execution_envelopes_are_not_lexical_field_values(self):
        from experiments.v2_3.live_runner import build_forbidden_lexicon

        injection = {
            **FakeInjector().inject("F7", 1),
            "command": "sudo sh -c " + "very long command segment " * 300,
            "ssh_output": "transport diagnostic " * 300,
            "kubectl_output": "transport diagnostic " * 300,
            "diskfill_nonce": "a" * 32,
        }
        lexicon = build_forbidden_lexicon("F7", 1, GROUND_TRUTH, injection)
        self.assertNotIn(injection["command"], lexicon.field_values)
        self.assertNotIn(injection["ssh_output"], lexicon.field_values)
        self.assertNotIn(injection["kubectl_output"], lexicon.field_values)
        self.assertIn("a" * 32, lexicon.field_values)

    def test_production_fault_marker_is_structured_not_bare_short_id(self):
        from experiments.v2_3.live_runner import build_forbidden_lexicon
        from experiments.v2_3.scanner import LeakageScanner

        lexicon = build_forbidden_lexicon(
            "F7", 1, GROUND_TRUTH, FakeInjector().inject("F7", 1)
        )
        scanner = LeakageScanner()
        self.assertEqual(
            scanner.scan(
                "pod uid segment abcd-f7-91ef", lexicon, runtime_scope=True
            ).match_count,
            0,
        )
        for leaked in ("fault_id F7", "fault F-7", "F7_t1"):
            self.assertGreater(
                scanner.scan(leaked, lexicon, runtime_scope=True).match_count,
                0,
            )

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

    def test_f4_memory_injector_uses_absolute_bytes_and_requires_pid_receipt(self):
        from scripts.fault_inject.injector import FaultInjector

        with patch(
            "scripts.fault_inject.injector.ssh_node",
            return_value=(
                "__V23_STRESS_NG_PID__=4321\n"
                "__V23_STRESS_NG_START_TICKS__=8765\n"
                f"__V23_STRESS_NG_CMDLINE_SHA256__={'c' * 64}\n"
            ),
        ) as ssh:
            result = FaultInjector()._inject_f4_node_notready(
                "worker03", 3, {}, {
                    "stress_ng_version": "0.19.02",
                    "stress_ng_preexisting": False,
                    "stress_receipt_file": "/tmp/v23-f4t3-stress.receipt",
                    "stress_vm_workers": 2,
                }
            )
        command = ssh.call_args.args[1]
        self.assertIn("command -v stress-ng", command)
        self.assertIn("--vm 2 --vm-bytes 15G", command)
        self.assertIn("--timeout 180s", command)
        self.assertIn("--vm-keep", command)
        self.assertIn("sync -f", command)
        self.assertIn("read rpid rstart rhash", command)
        self.assertEqual(result["stress_ng_pid"], 4321)
        self.assertEqual(result["stress_ng_start_ticks"], 8765)
        self.assertEqual(result["stress_memory_bytes"], "15G")
        self.assertEqual(result["stress_vm_workers"], 2)
        self.assertEqual(result["stress_timeout_seconds"], 180)

        with patch(
            "scripts.fault_inject.injector.ssh_node",
            return_value="bash: stress-ng: command not found\n",
        ):
            with self.assertRaisesRegex(RuntimeError, "launch receipt"):
                FaultInjector()._inject_f4_node_notready(
                    "worker03", 3, {}, {
                        "stress_ng_version": "0.19.02",
                        "stress_ng_preexisting": False,
                        "stress_receipt_file": "/tmp/v23-f4t3-stress.receipt",
                        "stress_vm_workers": 2,
                    }
                )

        for bad_workers in (None, 0, 1, 3, True, 2.0, "2"):
            with self.subTest(sealed_workers=bad_workers), patch(
                "scripts.fault_inject.injector.ssh_node"
            ) as ssh:
                context = {
                    "stress_ng_version": "0.19.02",
                    "stress_ng_preexisting": False,
                    "stress_receipt_file": "/tmp/v23-f4t3-stress.receipt",
                }
                if bad_workers is not None:
                    context["stress_vm_workers"] = bad_workers
                with self.assertRaisesRegex(RuntimeError, "sealed recovery preflight"):
                    FaultInjector()._inject_f4_node_notready(
                        "worker03", 3, {}, context
                    )
                ssh.assert_not_called()

    def test_f4_inject_preserves_sealed_preflight_for_runner_recovery(self):
        from scripts.fault_inject.injector import FaultInjector

        sealed = {
            "fault_id": "F4", "trial": 3, "target_service": "worker03",
            "node": "yms-proxmox-04", "stress_ng_preexisting": False,
            "stress_receipt_file": "/tmp/v23-f4t3-stress.receipt",
            "stress_vm_workers": 2,
        }
        injector = FaultInjector()
        injector._injectors["F4"] = lambda target, trial, gt, ctx: {
            "action": "node_disruption", "node": ctx["node"],
            "stress_ng_pid": 4321,
        }
        with patch(
            "scripts.fault_inject.injector.load_trial",
            return_value={
                "target_service": "worker03", "injection_method": "memory",
                "fault_name": "NodeNotReady",
            },
        ):
            result = injector.inject("F4", 3, recovery_context=sealed)
        self.assertIs(result["stress_ng_preexisting"], False)
        self.assertEqual(result["stress_receipt_file"], sealed["stress_receipt_file"])
        self.assertEqual(result["stress_ng_pid"], 4321)
        self.assertEqual(result["wait_seconds"], 120)

        for trial in (1, 2, 4, 5):
            with patch(
                "scripts.fault_inject.injector.load_trial",
                return_value={
                    "target_service": "worker",
                    "injection_method": "node fault",
                    "fault_name": "NodeNotReady",
                },
            ):
                injector._injectors["F4"] = lambda *_args: {
                    "action": "node_disruption", "node": "worker"
                }
                other = injector.inject("F4", trial, recovery_context=sealed)
            self.assertEqual(other["wait_seconds"], 180)

    def test_f4_diskfill_preflight_launch_and_recovery_are_nodefs_bound(self):
        from scripts.fault_inject.injector import FaultInjector
        from scripts.stabilize.recovery import Recovery

        preflight = (
            "__V23_DISK_PREFLIGHT_DEVICE__=64512\n"
            "__V23_DISK_PREFLIGHT_CAPACITY__=100000\n"
            "__V23_DISK_PREFLIGHT_AVAILABLE__=70000\n"
        )
        launch = (
            "__V23_DISK_DEVICE__=64512\n"
            "__V23_DISK_WORK_INODE__=101\n"
            "__V23_DISK_CAPACITY__=100000\n"
            "__V23_DISK_PRE_AVAILABLE__=70000\n"
            "__V23_DISK_ALLOCATED_BYTES__=61000\n"
            "__V23_DISK_FILE_INODE__=102\n"
            "__V23_DISK_FILE_SIZE__=61000\n"
            "__V23_DISK_FILE_BLOCKS__=120\n"
            "__V23_DISK_POST_AVAILABLE__=9000\n"
        )
        node_green = {
            "kind": "Node",
            "metadata": {"name": "yms-proxmox-02", "uid": "node-uid-02"},
            "status": {"conditions": [
                {"type": "Ready", "status": "True"},
                {"type": "DiskPressure", "status": "False"},
            ]},
        }
        with patch(
            "scripts.fault_inject.injector.load_trial",
            return_value={
                "target_service": "worker01",
                "injection_method": "diskfill",
                "fault_name": "NodeNotReady",
            },
        ), patch(
            "scripts.fault_inject.injector.ssh_node",
            side_effect=[preflight, launch],
        ) as ssh, patch(
            "scripts.fault_inject.injector.secrets.token_hex",
            return_value="a" * 32,
        ), patch(
            "scripts.fault_inject.injector.kubectl_get_json",
            return_value=node_green,
        ):
            injector = FaultInjector()
            sealed = injector.prepare_recovery_context("F4", 4)
            result = injector.inject("F4", 4, recovery_context=sealed)
        self.assertEqual(sealed["nodefs_device"], 64512)
        self.assertEqual(sealed["nodefs_target_available_percent"], 9)
        self.assertEqual(sealed["node_uid_before"], "node-uid-02")
        self.assertEqual(result["diskfill_inode"], 102)
        self.assertEqual(result["nodefs_post_available_bytes"], 9000)
        self.assertEqual(result["wait_seconds"], 180)
        preflight_command = ssh.call_args_list[0].args[1]
        self.assertIn("stat -c %d \"$nodefs\"", preflight_command)
        self.assertNotIn("install -d", preflight_command)
        self.assertNotIn("receipt.tmp", preflight_command)
        self.assertIn(
            f"/var/tmp/v23-f4t4-{'a' * 32}/diskfill",
            ssh.call_args_list[1].args[1],
        )
        self.assertNotIn("/tmp/diskfill", ssh.call_args_list[1].args[1])
        self.assertIn("post_available * 100", ssh.call_args_list[1].args[1])
        self.assertLess(
            ssh.call_args_list[1].args[1].index("printf \"intent"),
            ssh.call_args_list[1].args[1].index("fallocate -l"),
        )
        self.assertLess(
            ssh.call_args_list[1].args[1].index("mv \"$tmp\" \"$receipt\""),
            ssh.call_args_list[1].args[1].index("fallocate -l"),
        )
        self.assertIn("read pschema pnonce", ssh.call_args_list[1].args[1])

        with patch(
            "scripts.stabilize.recovery.ssh_node",
            return_value=(
                "__V23_DISK_RECOVERY__=exact-clean\n"
                "__V23_DISK_RECOVERY_CAPACITY__=100000\n"
                "__V23_DISK_RECOVERY_AVAILABLE__=70000\n"
            ),
        ) as recovery_ssh, patch(
            "scripts.stabilize.recovery.kubectl"
        ), patch(
            "scripts.stabilize.recovery.kubectl_get_json",
            return_value=node_green,
        ), patch("scripts.stabilize.recovery.time.sleep"):
            recovered = Recovery()._recover_f4(4, result)
        self.assertTrue(recovered["diskfill_cleanup_verified"])
        recovery_command = recovery_ssh.call_args.args[1]
        self.assertIn("stat -c %i \"$work\"", recovery_command)
        self.assertIn("sealed_file_inode", recovery_command)
        self.assertIn("rmdir \"$work\"", recovery_command)
        self.assertNotIn("systemctl restart kubelet", recovery_command)
        self.assertIs(recovered["kubelet_restarted"], False)

        node_stale = {
            **node_green,
            "status": {"conditions": [
                {"type": "Ready", "status": "True"},
                {"type": "DiskPressure", "status": "True"},
            ]},
        }
        recovery_marker = (
            "__V23_DISK_RECOVERY__=already-absent\n"
            "__V23_DISK_RECOVERY_CAPACITY__=100000\n"
            "__V23_DISK_RECOVERY_AVAILABLE__=70000\n"
        )
        with patch(
            "scripts.stabilize.recovery.ssh_node",
            side_effect=[
                recovery_marker,
                "__V23_KUBELET_RESTART__=verified\n",
            ],
        ) as stale_ssh, patch(
            "scripts.stabilize.recovery.kubectl"
        ), patch(
            "scripts.stabilize.recovery.kubectl_get_json",
            side_effect=[node_stale, node_stale, node_green],
        ), patch("scripts.stabilize.recovery.time.sleep"):
            stale_recovered = Recovery()._recover_f4(4, result)
        self.assertIs(stale_recovered["kubelet_restarted"], True)
        self.assertEqual(stale_recovered["condition_check_attempts"], 2)
        self.assertEqual(stale_ssh.call_count, 2)
        self.assertIn("systemctl restart kubelet", stale_ssh.call_args_list[1].args[1])

        with patch(
            "scripts.stabilize.recovery.ssh_node",
            side_effect=[
                recovery_marker, "", recovery_marker,
                "__V23_KUBELET_RESTART__=verified\n",
            ],
        ) as retry_ssh, patch(
            "scripts.stabilize.recovery.kubectl"
        ), patch(
            "scripts.stabilize.recovery.kubectl_get_json",
            side_effect=[node_stale, node_stale, node_green],
        ), patch("scripts.stabilize.recovery.time.sleep"):
            retried = Recovery()._recover_f4(4, result)
        self.assertEqual(retried["attempts"], 2)
        self.assertIs(retried["kubelet_restarted"], True)
        self.assertEqual(retry_ssh.call_count, 4)

        node_unknown = {
            **node_green,
            "status": {"conditions": [
                {"type": "Ready", "status": "True"},
                {"type": "DiskPressure", "status": "Unknown"},
            ]},
        }
        with patch(
            "scripts.stabilize.recovery.ssh_node",
            side_effect=[
                recovery_marker,
                "__V23_KUBELET_RESTART__=verified\n",
            ],
        ) as unknown_ssh, patch(
            "scripts.stabilize.recovery.kubectl"
        ), patch(
            "scripts.stabilize.recovery.kubectl_get_json",
            side_effect=[node_unknown, node_green],
        ), patch("scripts.stabilize.recovery.time.sleep"):
            unknown_recovered = Recovery()._recover_f4(4, result)
        self.assertIs(unknown_recovered["kubelet_restarted"], True)
        self.assertEqual(unknown_ssh.call_count, 2)

        with patch(
            "scripts.stabilize.recovery.ssh_node",
            side_effect=[
                recovery_marker,
                "__V23_KUBELET_RESTART__=verified\n",
            ],
        ) as stuck_ssh, patch(
            "scripts.stabilize.recovery.kubectl"
        ), patch(
            "scripts.stabilize.recovery.kubectl_get_json",
            return_value=node_stale,
        ) as stuck_state, patch("scripts.stabilize.recovery.time.sleep"):
            with self.assertRaisesRegex(
                RuntimeError, "did not become GREEN after one kubelet restart"
            ):
                Recovery()._recover_f4(4, result)
        self.assertEqual(stuck_ssh.call_count, 2)
        self.assertEqual(stuck_state.call_count, 16)

        dirty_baseline = {
            **node_green,
            "status": {"conditions": [
                {"type": "Ready", "status": "True"},
                {"type": "DiskPressure", "status": "True"},
            ]},
        }
        with patch(
            "scripts.fault_inject.injector.kubectl_get_json",
            return_value=dirty_baseline,
        ), patch("scripts.fault_inject.injector.ssh_node") as no_ssh:
            with self.assertRaisesRegex(RuntimeError, "baseline"):
                FaultInjector().prepare_recovery_context("F4", 4)
        no_ssh.assert_not_called()

    def test_f4_diskfill_malformed_receipts_fail_before_mutation_or_cleanup(self):
        from scripts.fault_inject.injector import FaultInjector
        from scripts.stabilize.recovery import Recovery

        sealed = {
            "fault_id": "F4", "trial": 4, "target_service": "worker01",
            "node": "yms-proxmox-02", "diskfill_preexisting": False,
            "diskfill_nonce": "a" * 32,
            "diskfill_file": f"/var/tmp/v23-f4t4-{'a' * 32}/diskfill",
            "diskfill_receipt_file": f"/var/tmp/v23-f4t4-{'a' * 32}/receipt",
            "diskfill_work_dir": f"/var/tmp/v23-f4t4-{'a' * 32}",
            "nodefs_path": "/var/lib/kubelet",
            "node_uid_before": "node-uid-02",
            "node_ready_before": "True",
            "node_disk_pressure_before": "False",
            "nodefs_device": 64512, "nodefs_capacity_bytes": 100000,
            "nodefs_pre_available_bytes": 70000,
            "nodefs_target_available_percent": 9,
        }
        for field, value in (
            ("nodefs_device", True),
            ("nodefs_capacity_bytes", 0),
            ("diskfill_nonce", "z" * 32),
            ("diskfill_file", "/tmp/diskfill"),
            ("nodefs_target_available_percent", 10),
        ):
            with self.subTest(field=field), patch(
                "scripts.fault_inject.injector.ssh_node"
            ) as inject_ssh, patch(
                "scripts.stabilize.recovery.ssh_node"
            ) as recovery_ssh:
                bad = dict(sealed, **{field: value})
                with self.assertRaisesRegex(RuntimeError, "sealed recovery preflight"):
                    FaultInjector()._inject_f4_node_notready(
                        "worker01", 4, {}, bad
                    )
                with self.assertRaisesRegex(RuntimeError, "receipt is incomplete"):
                    Recovery()._recover_f4(4, bad)
                inject_ssh.assert_not_called()
                recovery_ssh.assert_not_called()

    def test_f4_diskfill_recovery_retries_and_rejects_low_available_false_green(self):
        from scripts.stabilize.recovery import Recovery

        ctx = {
            "node": "yms-proxmox-02", "diskfill_preexisting": False,
            "diskfill_nonce": "a" * 32,
            "diskfill_file": f"/var/tmp/v23-f4t4-{'a' * 32}/diskfill",
            "diskfill_receipt_file": f"/var/tmp/v23-f4t4-{'a' * 32}/receipt",
            "diskfill_work_dir": f"/var/tmp/v23-f4t4-{'a' * 32}",
            "nodefs_path": "/var/lib/kubelet",
            "node_uid_before": "node-uid-02",
            "node_ready_before": "True",
            "node_disk_pressure_before": "False",
            "nodefs_device": 64512, "nodefs_capacity_bytes": 100000,
            "nodefs_pre_available_bytes": 70000,
            "nodefs_target_available_percent": 9,
        }
        low = (
            "__V23_DISK_RECOVERY__=already-absent\n"
            "__V23_DISK_RECOVERY_CAPACITY__=100000\n"
            "__V23_DISK_RECOVERY_AVAILABLE__=9000\n"
        )
        green = (
            "__V23_DISK_RECOVERY__=already-absent\n"
            "__V23_DISK_RECOVERY_CAPACITY__=100000\n"
            "__V23_DISK_RECOVERY_AVAILABLE__=70000\n"
        )
        with patch(
            "scripts.stabilize.recovery.ssh_node",
            side_effect=[TimeoutError("ssh"), low, green],
        ) as ssh, patch("scripts.stabilize.recovery.kubectl"), patch(
            "scripts.stabilize.recovery.kubectl_get_json",
            return_value={
                "kind": "Node",
                "metadata": {
                    "name": "yms-proxmox-02", "uid": "node-uid-02"
                },
                "status": {"conditions": [
                    {"type": "Ready", "status": "True"},
                    {"type": "DiskPressure", "status": "False"},
                ]},
            },
        ), patch(
            "scripts.stabilize.recovery.time.sleep"
        ):
            result = Recovery()._recover_f4(4, ctx)
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(ssh.call_count, 3)

    def test_f4_memory_evidence_deadline_is_strict_and_trial_scoped(self):
        self.assertEqual(
            validate_f4_t3_evidence_deadline("F4", 3, 174.999),
            {"elapsed_seconds": 174.999, "deadline_seconds": 175},
        )
        self.assertIsNone(validate_f4_t3_evidence_deadline("F4", 2, 999))
        for elapsed in (175, -1, float("nan"), True):
            with self.subTest(elapsed=elapsed):
                with self.assertRaisesRegex(PilotError, "treatment deadline"):
                    validate_f4_t3_evidence_deadline("F4", 3, elapsed)

    def test_f4_memory_observation_window_latches_first_notready(self):
        clock = [0.0]
        calls = []

        def sleep(seconds):
            clock[0] += seconds

        class Validator:
            def validate(self, *_args):
                calls.append(clock[0])
                if clock[0] < 22:
                    raise F4DisruptionNotObserved(
                        "F4 node disruption was not observed"
                    )
                return {"status": "verified", "node_disrupted": True}

        result = validate_injection_in_observation_window(
            fault_id="F4",
            trial=3,
            ground_truth={"target_service": "worker03"},
            injection_result={"wait_seconds": 120},
            injection_validator=Validator(),
            injection_started_monotonic=0.0,
            sleep_fn=sleep,
            monotonic_fn=lambda: clock[0],
        )
        self.assertEqual(calls, [10, 12, 14, 16, 18, 20, 22])
        self.assertEqual(result["observation_poll_started_seconds"], 22.0)
        self.assertEqual(result["observation_latched_seconds"], 22.0)

    def test_f4_memory_observation_window_fails_at_deadline(self):
        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds

        validator = SimpleNamespace(
            validate=lambda *_: (_ for _ in ()).throw(
                F4DisruptionNotObserved("F4 node disruption was not observed")
            )
        )
        with self.assertRaisesRegex(F4DisruptionNotObserved, "not observed"):
            validate_injection_in_observation_window(
                fault_id="F4",
                trial=3,
                ground_truth={"target_service": "worker03"},
                injection_result={"wait_seconds": 120},
                injection_validator=validator,
                injection_started_monotonic=0.0,
                sleep_fn=sleep,
                monotonic_fn=lambda: clock[0],
            )
        self.assertEqual(clock[0], 120.0)

    def test_f4_memory_observation_timeout_is_bounded_and_audited(self):
        clock = [10.0]
        events = []
        attempts = [0]

        def validate(*_args):
            attempts[0] += 1
            if attempts[0] == 1:
                clock[0] = 45.0
                raise F4ObservationTimeout("F4 node observation timed out")
            return {"status": "verified", "node_disrupted": True}

        result = validate_injection_in_observation_window(
            fault_id="F4", trial=3,
            ground_truth={"target_service": "worker03"},
            injection_result={"wait_seconds": 120},
            injection_validator=SimpleNamespace(validate=validate),
            injection_started_monotonic=0.0,
            sleep_fn=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
            monotonic_fn=lambda: clock[0],
            observation_event_fn=events.append,
        )
        self.assertEqual(result["status"], "verified")
        self.assertEqual([event["outcome"] for event in events], [
            "observation-timeout", "verified",
        ])
        self.assertEqual([event["attempt"] for event in events], [1, 2])

    def test_f4_memory_observation_event_failure_aborts_retry(self):
        clock = [10.0]
        validator = SimpleNamespace(
            validate=lambda *_: (_ for _ in ()).throw(
                F4DisruptionNotObserved("not observed")
            )
        )
        with self.assertRaisesRegex(OSError, "event fsync failed"):
            validate_injection_in_observation_window(
                fault_id="F4", trial=3,
                ground_truth={"target_service": "worker03"},
                injection_result={"wait_seconds": 120},
                injection_validator=validator,
                injection_started_monotonic=0.0,
                sleep_fn=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
                monotonic_fn=lambda: clock[0],
                observation_event_fn=lambda _: (_ for _ in ()).throw(
                    OSError("event fsync failed")
                ),
            )

    def test_f4_memory_observation_window_does_not_retry_other_errors(self):
        clock = [0.0]
        calls = []
        events = []

        def sleep(seconds):
            calls.append(seconds)
            clock[0] += seconds

        validator = SimpleNamespace(
            validate=lambda *_: (_ for _ in ()).throw(
                PilotError("malformed launch receipt")
            )
        )
        with self.assertRaisesRegex(PilotError, "malformed launch receipt"):
            validate_injection_in_observation_window(
                fault_id="F4",
                trial=3,
                ground_truth={"target_service": "worker03"},
                injection_result={"wait_seconds": 120},
                injection_validator=validator,
                injection_started_monotonic=0.0,
                sleep_fn=sleep,
                monotonic_fn=lambda: clock[0],
                observation_event_fn=events.append,
            )
        self.assertEqual(calls, [10.0])
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["outcome"], "fatal-validation-error")

    def test_f4_memory_observation_invalid_result_is_not_verified(self):
        clock = [10.0]
        events = []
        with self.assertRaisesRegex(PilotError, "did not PASS"):
            validate_injection_in_observation_window(
                fault_id="F4", trial=3,
                ground_truth={"target_service": "worker03"},
                injection_result={"wait_seconds": 120},
                injection_validator=SimpleNamespace(
                    validate=lambda *_: {"status": "bad"}
                ),
                injection_started_monotonic=0.0,
                sleep_fn=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
                monotonic_fn=lambda: clock[0],
                observation_event_fn=events.append,
            )
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["outcome"], "invalid-result")

    def test_f4_memory_observation_window_rejects_late_start_and_success(self):
        for initial_elapsed in (121.0, 130.0, float("nan"), -1.0):
            with self.subTest(initial_elapsed=initial_elapsed):
                validator = SimpleNamespace(
                    validate=lambda *_: {"status": "verified"}
                )
                with self.assertRaisesRegex(PilotError, "window elapsed"):
                    validate_injection_in_observation_window(
                        fault_id="F4",
                        trial=3,
                        ground_truth={"target_service": "worker03"},
                        injection_result={"wait_seconds": 120},
                        injection_validator=validator,
                        injection_started_monotonic=0.0,
                        sleep_fn=lambda _: None,
                        monotonic_fn=lambda value=initial_elapsed: value,
                    )

        clock = [119.0]

        class SlowSuccessfulValidator:
            def validate(self, *_args):
                clock[0] = 125.0
                return {"status": "verified"}

        with self.assertRaisesRegex(PilotError, "validation exceeded"):
            validate_injection_in_observation_window(
                fault_id="F4",
                trial=3,
                ground_truth={"target_service": "worker03"},
                injection_result={"wait_seconds": 120},
                injection_validator=SlowSuccessfulValidator(),
                injection_started_monotonic=0.0,
                sleep_fn=lambda _: None,
                monotonic_fn=lambda: clock[0],
            )

    def test_f4_memory_recovery_retries_and_kills_only_sealed_pid(self):
        from scripts.stabilize.recovery import Recovery

        ctx = {
            "node": "yms-proxmox-04", "stress_ng_preexisting": False,
            "stress_receipt_file": "/tmp/v23-f4t3-stress.receipt",
            "stress_vm_workers": 2,
            "stress_ng_pid": 4321, "stress_ng_start_ticks": 8765,
        }
        with patch(
            "scripts.stabilize.recovery.ssh_node",
            side_effect=[
                "Connection timed out during banner exchange",
                "__V23_STRESS_RECOVERY__=exact-clean\n",
            ],
        ) as ssh, patch("scripts.stabilize.recovery.kubectl"), patch(
            "scripts.stabilize.recovery.time.sleep"
        ):
            result = Recovery()._recover_f4(3, ctx)
        self.assertTrue(result["stress_cleanup_verified"])
        self.assertEqual(result["attempts"], 2)
        self.assertIn('"$pid" != "4321"', ssh.call_args.args[1])
        self.assertIn("--timeout 180s", ssh.call_args.args[1])
        self.assertIn("--vm 2 --vm-bytes 15G", ssh.call_args.args[1])
        self.assertNotIn("pkill -9 stress-ng", ssh.call_args.args[1])

    def test_f4_memory_recovery_rejects_malformed_worker_receipt(self):
        from scripts.stabilize.recovery import Recovery

        for bad_workers in (None, 0, 1, 3, True, 2.0, "2"):
            with self.subTest(workers=bad_workers), patch(
                "scripts.stabilize.recovery.ssh_node"
            ) as ssh:
                ctx = {
                    "node": "yms-proxmox-04",
                    "stress_ng_preexisting": False,
                    "stress_receipt_file": "/tmp/v23-f4t3-stress.receipt",
                }
                if bad_workers is not None:
                    ctx["stress_vm_workers"] = bad_workers
                with self.assertRaisesRegex(RuntimeError, "receipt is incomplete"):
                    Recovery()._recover_f4(3, ctx)
                ssh.assert_not_called()

    def test_f4_memory_crash_recovery_uses_durable_node_receipt(self):
        from scripts.stabilize.recovery import Recovery

        ctx = {
            "node": "yms-proxmox-04", "stress_ng_preexisting": False,
            "stress_receipt_file": "/tmp/v23-f4t3-stress.receipt",
            "stress_vm_workers": 2,
        }
        with patch(
            "scripts.stabilize.recovery.ssh_node",
            return_value="__V23_STRESS_RECOVERY__=exact-clean\n",
        ) as ssh, patch("scripts.stabilize.recovery.kubectl"), patch(
            "scripts.stabilize.recovery.time.sleep"
        ):
            result = Recovery()._recover_f4(3, ctx)
        self.assertTrue(result["stress_cleanup_verified"])
        command = ssh.call_args.args[1]
        self.assertIn("read pid sealed_start sealed_hash", command)
        self.assertNotIn('[ -n "4321" ]', command)

    def test_f4_memory_missing_receipt_waits_for_process_absence(self):
        from scripts.stabilize.recovery import Recovery

        ctx = {
            "node": "yms-proxmox-04", "stress_ng_preexisting": False,
            "stress_receipt_file": "/tmp/v23-f4t3-stress.receipt",
            "stress_vm_workers": 2,
        }
        with patch(
            "scripts.stabilize.recovery.ssh_node",
            side_effect=[
                "__V23_STRESS_RECOVERY__=awaiting-unsealed\n",
                "__V23_STRESS_RECOVERY__=no-receipt-no-process\n",
            ],
        ) as ssh, patch("scripts.stabilize.recovery.kubectl"), patch(
            "scripts.stabilize.recovery.time.sleep"
        ):
            result = Recovery()._recover_f4(3, ctx)
        self.assertEqual(result["attempts"], 2)
        self.assertIn("pgrep '^stress-ng'", ssh.call_args.args[1])

    def test_f4_memory_stale_receipt_cannot_hide_new_residual_process(self):
        from scripts.stabilize.recovery import Recovery

        ctx = {
            "node": "yms-proxmox-04", "stress_ng_preexisting": False,
            "stress_receipt_file": "/tmp/v23-f4t3-stress.receipt",
            "stress_vm_workers": 2,
        }
        with patch(
            "scripts.stabilize.recovery.ssh_node",
            side_effect=[
                "__V23_STRESS_RECOVERY__=awaiting-residual\n",
                "__V23_STRESS_RECOVERY__=exact-clean\n",
            ],
        ) as ssh, patch("scripts.stabilize.recovery.kubectl"), patch(
            "scripts.stabilize.recovery.time.sleep"
        ):
            result = Recovery()._recover_f4(3, ctx)
        self.assertEqual(result["attempts"], 2)
        self.assertIn("awaiting-residual", ssh.call_args.args[1])

    def test_f4_memory_preflight_requires_version_and_no_existing_process(self):
        from scripts.fault_inject.injector import FaultInjector

        with patch(
            "scripts.fault_inject.injector.load_trial",
            return_value={"target_service": "worker03"},
        ), patch(
            "scripts.fault_inject.injector.ssh_node",
            return_value="__V23_STRESS_NG_PREFLIGHT__=0.19.02\n",
        ) as ssh:
            context = FaultInjector().prepare_recovery_context("F4", 3)
        self.assertEqual(context["stress_ng_version"], "0.19.02")
        self.assertIs(context["stress_ng_preexisting"], False)
        self.assertEqual(context["stress_vm_workers"], 2)
        self.assertEqual(
            context["stress_receipt_file"], "/tmp/v23-f4t3-stress.receipt"
        )
        preflight_command = ssh.call_args.args[1]
        self.assertIn("sudo rm -f /tmp/v23-f4t3-stress.receipt", preflight_command)
        self.assertIn("sudo sync -f /tmp", preflight_command)
        self.assertLess(
            preflight_command.index("rm -f"),
            preflight_command.index("__V23_STRESS_NG_PREFLIGHT__"),
        )

        with patch(
            "scripts.fault_inject.injector.load_trial",
            return_value={"target_service": "worker03"},
        ), patch(
            "scripts.fault_inject.injector.ssh_node", return_value=""
        ):
            with self.assertRaisesRegex(RuntimeError, "preflight"):
                FaultInjector().prepare_recovery_context("F4", 3)

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

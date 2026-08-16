import unittest

from experiments.v2_3.injection_validator import LiveInjectionValidator
from experiments.v2_3.live_runner import PilotError


class InjectionValidatorTests(unittest.TestCase):
    def test_f1_binds_receipt_to_live_memory_resources(self):
        deployment = {
            "spec": {"template": {"spec": {"containers": [{
                "name": "cartservice",
                "resources": {
                    "limits": {"memory": "32Mi"},
                    "requests": {"memory": "32Mi"},
                },
            }]}}}
        }
        validator = LiveInjectionValidator(
            lambda resource, name, namespace: deployment,
            lambda node, command: "",
        )
        result = validator.validate("F1", 1, {"target_service": "cartservice"}, {
            "fault_id": "F1", "trial": 1, "target_service": "cartservice",
            "action": "patch_memory_limit", "memory_limit": "32Mi",
        })
        self.assertEqual(result["status"], "verified")
        deployment["spec"]["template"]["spec"]["containers"][0]["resources"]["limits"]["memory"] = "128Mi"
        with self.assertRaisesRegex(PilotError, "F1"):
            validator.validate("F1", 1, {"target_service": "cartservice"}, {
                "fault_id": "F1", "trial": 1, "target_service": "cartservice",
                "action": "patch_memory_limit", "memory_limit": "32Mi",
            })

    def test_f5_provisioner_requires_pending_probe_pvc(self):
        def load(resource, name, namespace):
            if resource == "deployment":
                return {"spec": {"replicas": 0}}
            return {"status": {"phase": "Pending"}}
        validator = LiveInjectionValidator(load, lambda node, command: "")
        result = validator.validate("F5", 3, {"target_service": "loki"}, {
            "fault_id": "F5", "trial": 3, "target_service": "loki",
            "action": "scale_provisioner_to_zero", "pvc": "storage-probe-pvc",
        })
        self.assertEqual(result["pvc_phase"], "Pending")

    def test_netem_requires_independent_live_qdisc_evidence(self):
        base = {
            "fault_id": "F11", "trial": 1, "target_service": "worker01",
            "action": "netem_delay", "node": "yms-proxmox-02",
            "interface": "vmbr0",
        }
        validator = LiveInjectionValidator(
            lambda resource, name, namespace: {},
            lambda node, command: "qdisc netem 8001: root refcnt 2 limit 1000 delay 500ms",
        )
        self.assertTrue(validator.validate(
            "F11", 1, {"target_service": "worker01"}, base
        )["status"] == "verified")
        validator = LiveInjectionValidator(
            lambda resource, name, namespace: {},
            lambda node, command: "qdisc fq_codel 0: root",
        )
        with self.assertRaisesRegex(PilotError, "delay"):
            validator.validate("F11", 1, {"target_service": "worker01"}, base)

    def test_f4_memory_pressure_requires_bound_launch_receipt(self):
        node = {
            "status": {"conditions": [
                {"type": "Ready", "status": "Unknown"},
                {"type": "MemoryPressure", "status": "Unknown"},
            ]}
        }
        validator = LiveInjectionValidator(
            lambda resource, name, namespace: node,
            lambda node, command: "Connection timed out during banner exchange",
        )
        receipt = {
            "fault_id": "F4", "trial": 3, "target_service": "worker03",
            "action": "node_disruption", "node": "yms-proxmox-04",
            "stress_ng_pid": 1234, "stress_ng_start_ticks": 5678,
            "stress_ng_cmdline_sha256": "a" * 64,
            "stress_memory_bytes": "13G", "stress_timeout_seconds": 180,
            "wait_seconds": 60,
        }
        self.assertTrue(validator.validate(
            "F4", 3, {"target_service": "worker03"}, receipt
        )["node_disrupted"])
        del receipt["stress_ng_pid"]
        with self.assertRaisesRegex(PilotError, "launch receipt"):
            validator.validate("F4", 3, {"target_service": "worker03"}, receipt)

    def test_f4_memory_pressure_binds_exact_wait_and_requires_notready(self):
        receipt = {
            "fault_id": "F4", "trial": 3, "target_service": "worker03",
            "action": "node_disruption", "node": "yms-proxmox-04",
            "stress_ng_pid": 1234, "stress_ng_start_ticks": 5678,
            "stress_ng_cmdline_sha256": "a" * 64,
            "stress_memory_bytes": "13G", "stress_timeout_seconds": 180,
            "wait_seconds": 60,
        }
        ready_under_pressure = {"status": {"conditions": [
            {"type": "Ready", "status": "True"},
            {"type": "MemoryPressure", "status": "True"},
        ]}}
        validator = LiveInjectionValidator(
            lambda *_: ready_under_pressure,
            lambda *_: "__V23_STRESS_NG_IDENTITY__=live",
        )
        with self.assertRaisesRegex(PilotError, "node disruption"):
            validator.validate("F4", 3, {"target_service": "worker03"}, receipt)

        not_ready = {"status": {"conditions": [
            {"type": "Ready", "status": "Unknown"},
            {"type": "MemoryPressure", "status": "Unknown"},
        ]}}
        validator = LiveInjectionValidator(
            lambda *_: not_ready,
            lambda *_: "__V23_STRESS_NG_IDENTITY__=live",
        )
        for bad_wait in (None, 0, 180, True, "60", 60.0):
            with self.subTest(wait=bad_wait):
                mutated = dict(receipt)
                if bad_wait is None:
                    mutated.pop("wait_seconds")
                else:
                    mutated["wait_seconds"] = bad_wait
                with self.assertRaisesRegex(PilotError, "amount"):
                    validator.validate(
                        "F4", 3, {"target_service": "worker03"}, mutated
                    )
        for bad_timeout in (True, 180.0, "180"):
            with self.subTest(timeout=bad_timeout):
                mutated = dict(receipt, stress_timeout_seconds=bad_timeout)
                with self.assertRaisesRegex(PilotError, "amount"):
                    validator.validate(
                        "F4", 3, {"target_service": "worker03"}, mutated
                    )

    def test_f4_memory_pressure_rejects_unbound_process_probe(self):
        node = {"status": {"conditions": [{"type": "Ready", "status": "Unknown"}]}}
        validator = LiveInjectionValidator(
            lambda resource, name, namespace: node,
            lambda node, command: "",
        )
        with self.assertRaisesRegex(PilotError, "process identity"):
            validator.validate("F4", 3, {"target_service": "worker03"}, {
                "fault_id": "F4", "trial": 3, "target_service": "worker03",
                "action": "node_disruption", "node": "yms-proxmox-04",
                "stress_ng_pid": 999999, "stress_ng_start_ticks": 1,
                "stress_ng_cmdline_sha256": "b" * 64,
                "stress_memory_bytes": "13G", "stress_timeout_seconds": 180,
                "wait_seconds": 60,
            })


if __name__ == "__main__":
    unittest.main()

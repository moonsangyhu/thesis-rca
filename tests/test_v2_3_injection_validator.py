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


if __name__ == "__main__":
    unittest.main()

import unittest
import subprocess

from experiments.v2_3.injection_validator import LiveInjectionValidator
from experiments.v2_3.live_runner import (
    F4DisruptionNotObserved, F4ObservationTimeout, PilotError,
)


def node_state(ready: str, memory: str = "False") -> dict:
    return {
        "kind": "Node",
        "metadata": {"name": "yms-proxmox-04", "uid": "node-uid-04"},
        "status": {"conditions": [
            {"type": "Ready", "status": ready},
            {"type": "MemoryPressure", "status": memory},
        ]},
    }


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
        node = node_state("Unknown", "Unknown")
        validator = LiveInjectionValidator(
            lambda resource, name, namespace: node,
            lambda node, command: "Connection timed out during banner exchange",
        )
        receipt = {
            "fault_id": "F4", "trial": 3, "target_service": "worker03",
            "action": "node_disruption", "node": "yms-proxmox-04",
            "stress_ng_pid": 1234, "stress_ng_start_ticks": 5678,
            "stress_ng_cmdline_sha256": "a" * 64,
            "stress_memory_bytes": "15G", "stress_vm_workers": 2,
            "stress_timeout_seconds": 180,
            "wait_seconds": 120,
        }
        self.assertTrue(validator.validate(
            "F4", 3, {"target_service": "worker03"}, receipt
        )["node_disrupted"])
        del receipt["stress_ng_pid"]
        with self.assertRaisesRegex(PilotError, "launch receipt"):
            validator.validate("F4", 3, {"target_service": "worker03"}, receipt)

    def test_f4_memory_pressure_binds_exact_wait_and_pressure_threshold(self):
        receipt = {
            "fault_id": "F4", "trial": 3, "target_service": "worker03",
            "action": "node_disruption", "node": "yms-proxmox-04",
            "stress_ng_pid": 1234, "stress_ng_start_ticks": 5678,
            "stress_ng_cmdline_sha256": "a" * 64,
            "stress_memory_bytes": "15G", "stress_vm_workers": 2,
            "stress_timeout_seconds": 180,
            "wait_seconds": 120,
        }
        ready_under_pressure = node_state("True", "False")
        validator = LiveInjectionValidator(
            lambda *_: ready_under_pressure,
            lambda *_: (
                "__V23_STRESS_NG_IDENTITY__=live\n"
                "__V23_MEM_AVAILABLE_BYTES__=1500000000"
            ),
        )
        verified = validator.validate(
            "F4", 3, {"target_service": "worker03"}, receipt
        )
        self.assertEqual(verified["treatment_basis"], "memavailable-threshold")
        self.assertEqual(verified["mem_available_bytes"], 1500000000)
        self.assertIs(verified["node_disrupted"], False)
        self.assertIs(verified["treatment_verified"], True)
        self.assertIs(verified["stress_identity_verified"], True)

        validator = LiveInjectionValidator(
            lambda *_: ready_under_pressure,
            lambda *_: (
                "__V23_STRESS_NG_IDENTITY__=live\n"
                "__V23_MEM_AVAILABLE_BYTES__=3000000000"
            ),
        )
        with self.assertRaises(F4DisruptionNotObserved):
            validator.validate("F4", 3, {"target_service": "worker03"}, receipt)

        for value, passes in ((2147483648, True), (2147483649, False)):
            with self.subTest(mem_available=value):
                validator = LiveInjectionValidator(
                    lambda *_: ready_under_pressure,
                    lambda *_args, current=value: (
                        "__V23_STRESS_NG_IDENTITY__=live\n"
                        f"__V23_MEM_AVAILABLE_BYTES__={current}"
                    ),
                )
                if passes:
                    self.assertTrue(validator.validate(
                        "F4", 3, {"target_service": "worker03"}, receipt
                    )["treatment_verified"])
                else:
                    with self.assertRaises(F4DisruptionNotObserved):
                        validator.validate(
                            "F4", 3, {"target_service": "worker03"}, receipt
                        )

        for malformed in (
            "__V23_STRESS_NG_IDENTITY__=live",
            "__V23_STRESS_NG_IDENTITY__=live\n__V23_MEM_AVAILABLE_BYTES__=-1",
            "__V23_STRESS_NG_IDENTITY__=live\n__V23_MEM_AVAILABLE_BYTES__=x",
            "__V23_STRESS_NG_IDENTITY__=live\n"
            "__V23_MEM_AVAILABLE_BYTES__=1\n__V23_MEM_AVAILABLE_BYTES__=2",
        ):
            with self.subTest(probe=malformed):
                validator = LiveInjectionValidator(
                    lambda *_: ready_under_pressure,
                    lambda *_args, value=malformed: value,
                )
                with self.assertRaisesRegex(PilotError, "availability probe"):
                    validator.validate(
                        "F4", 3, {"target_service": "worker03"}, receipt
                    )

        validator = LiveInjectionValidator(
            lambda *_: ready_under_pressure,
            lambda *_: (
                "__V23_STRESS_NG_IDENTITY__=live\n"
                "__V23_STRESS_NG_IDENTITY__=live\n"
                "__V23_MEM_AVAILABLE_BYTES__=1500000000"
            ),
        )
        with self.assertRaisesRegex(PilotError, "process identity"):
            validator.validate("F4", 3, {"target_service": "worker03"}, receipt)

        validator = LiveInjectionValidator(
            lambda *_: ready_under_pressure,
            lambda *_: (_ for _ in ()).throw(TimeoutError("ssh timeout")),
        )
        with self.assertRaises(F4ObservationTimeout):
            validator.validate("F4", 3, {"target_service": "worker03"}, receipt)

        commands = []
        validator = LiveInjectionValidator(
            lambda *_: ready_under_pressure,
            lambda _node, command: commands.append(command) or subprocess.run(
                ["sh", "-c", command], capture_output=True, text=True,
                check=False,
            ).stdout,
        )
        with self.assertRaisesRegex(PilotError, "process identity"):
            validator.validate(
                "F4", 3, {"target_service": "worker03"},
                {**receipt, "stress_ng_pid": 999999},
            )
        self.assertTrue(commands[0].startswith("set -eu;"))

        not_ready = node_state("Unknown", "False")
        validator = LiveInjectionValidator(
            lambda *_: not_ready,
            lambda *_: (_ for _ in ()).throw(TimeoutError("ssh timeout")),
        )
        unreachable = validator.validate(
            "F4", 3, {"target_service": "worker03"}, receipt
        )
        self.assertIs(unreachable["node_disrupted"], True)
        self.assertIs(unreachable["stress_identity_verified"], False)
        self.assertIs(unreachable["memory_pressure_verified"], False)
        self.assertEqual(
            unreachable["stress_identity_basis"],
            "sealed-launch-plus-node-notready",
        )

        not_ready = node_state("Unknown", "Unknown")
        validator = LiveInjectionValidator(
            lambda *_: not_ready,
            lambda *_: (
                "__V23_STRESS_NG_IDENTITY__=live\n"
                "__V23_MEM_AVAILABLE_BYTES__=1500000000"
            ),
        )
        for bad_wait in (None, 0, 60, 180, True, "120", 120.0):
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
        for bad_workers in (None, 0, 1, 3, True, 2.0, "2"):
            with self.subTest(workers=bad_workers):
                mutated = dict(receipt)
                if bad_workers is None:
                    mutated.pop("stress_vm_workers")
                else:
                    mutated["stress_vm_workers"] = bad_workers
                with self.assertRaisesRegex(PilotError, "amount"):
                    validator.validate(
                        "F4", 3, {"target_service": "worker03"}, mutated
                    )

    def test_f4_memory_pressure_rejects_unbound_process_probe(self):
        node = node_state("Unknown", "Unknown")
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
                "stress_memory_bytes": "15G", "stress_vm_workers": 2,
                "stress_timeout_seconds": 180,
                "wait_seconds": 120,
            })

    def test_f4_rejects_empty_wrong_or_ambiguous_node_observation(self):
        receipt = {
            "fault_id": "F4", "trial": 3, "target_service": "worker03",
            "action": "node_disruption", "node": "yms-proxmox-04",
            "stress_ng_pid": 1234, "stress_ng_start_ticks": 5678,
            "stress_ng_cmdline_sha256": "a" * 64,
            "stress_memory_bytes": "15G", "stress_vm_workers": 2,
            "stress_timeout_seconds": 180, "wait_seconds": 120,
        }
        malformed = [
            {},
            {**node_state("Unknown"), "kind": "Pod"},
            {**node_state("Unknown"), "metadata": {
                "name": "other-node", "uid": "node-uid-04"
            }},
            {**node_state("Unknown"), "metadata": {
                "name": "yms-proxmox-04", "uid": ""
            }},
            {**node_state("Unknown"), "status": {"conditions": []}},
            {**node_state("Unknown"), "status": {"conditions": [
                {"type": "Ready", "status": "Unknown"},
                {"type": "Ready", "status": "False"},
            ]}},
            {**node_state("Unknown"), "status": {"conditions": [
                {"type": "Ready", "status": "Maybe"},
            ]}},
        ]
        for observed in malformed:
            with self.subTest(observed=observed):
                validator = LiveInjectionValidator(
                    lambda *_args, value=observed: value,
                    lambda *_: "connection timed out",
                )
                with self.assertRaisesRegex(PilotError, "schema"):
                    validator.validate(
                        "F4", 3, {"target_service": "worker03"}, receipt
                    )

    def test_f4_diskfill_requires_exact_nodefs_receipt_and_live_threshold(self):
        observed = {
            "kind": "Node",
            "metadata": {"name": "yms-proxmox-02", "uid": "node-uid-02"},
            "status": {"conditions": [
                {"type": "Ready", "status": "True"},
                {"type": "DiskPressure", "status": "False"},
            ]},
        }
        receipt = {
            "fault_id": "F4", "trial": 4, "target_service": "worker01",
            "action": "node_disruption", "node": "yms-proxmox-02",
            "diskfill_preexisting": False,
            "diskfill_nonce": "a" * 32,
            "diskfill_file": f"/var/tmp/v23-f4t4-{'a' * 32}/diskfill",
            "diskfill_receipt_file": f"/var/tmp/v23-f4t4-{'a' * 32}/receipt",
            "diskfill_work_dir": f"/var/tmp/v23-f4t4-{'a' * 32}",
            "nodefs_path": "/var/lib/kubelet",
            "node_uid_before": "node-uid-02",
            "node_ready_before": "True",
            "node_disk_pressure_before": "False",
            "nodefs_device": 64512, "diskfill_work_inode": 101,
            "nodefs_capacity_bytes": 100_000,
            "nodefs_pre_available_bytes": 80_000,
            "nodefs_injection_available_bytes": 70_000,
            "diskfill_allocated_bytes": 61_000,
            "diskfill_inode": 102, "diskfill_size_bytes": 61_000,
            "diskfill_allocated_blocks": 120,
            "nodefs_post_available_bytes": 9_000,
            "nodefs_target_available_percent": 9,
            "wait_seconds": 180,
        }
        live = (
            "__V23_DISK_LIVE_DEVICE__=64512\n"
            "__V23_DISK_LIVE_WORK_INODE__=101\n"
            "__V23_DISK_LIVE_FILE_INODE__=102\n"
            "__V23_DISK_LIVE_FILE_SIZE__=61000\n"
            "__V23_DISK_LIVE_FILE_BLOCKS__=120\n"
            "__V23_NODEFS_LIVE_CAPACITY__=100000\n"
            "__V23_NODEFS_INJECTION_AVAILABLE__=70000\n"
            "__V23_DISK_LIVE_ALLOCATION__=61000\n"
            "__V23_NODEFS_POST_AVAILABLE__=9000\n"
            "__V23_NODEFS_LIVE_AVAILABLE__=9000\n"
        )
        disk_probe_commands = []
        validator = LiveInjectionValidator(
            lambda *_: observed,
            lambda _node, command: disk_probe_commands.append(command) or live,
        )
        verified = validator.validate(
            "F4", 4, {"target_service": "worker01"}, receipt
        )
        self.assertEqual(len(disk_probe_commands), 1)
        self.assertTrue(disk_probe_commands[0].startswith("sudo sh -c "))
        self.assertIn("set -eu", disk_probe_commands[0])
        self.assertIs(verified["node_disrupted"], False)
        self.assertIs(verified["disk_pressure_observed"], False)
        self.assertIs(verified["nodefs_injection_threshold_verified"], True)
        self.assertIs(verified["nodefs_live_threshold_verified"], True)
        self.assertEqual(verified["nodefs_injection_post_available_bytes"], 9000)
        self.assertEqual(verified["nodefs_injection_allocation_bytes"], 61000)
        self.assertEqual(verified["treatment_basis"], "nodefs-available-threshold")

        replaced_node = {
            **observed,
            "metadata": {"name": "yms-proxmox-02", "uid": "replacement-uid"},
        }
        validator = LiveInjectionValidator(
            lambda *_: replaced_node, lambda *_: live
        )
        with self.assertRaisesRegex(PilotError, "schema"):
            validator.validate(
                "F4", 4, {"target_service": "worker01"}, receipt
            )

        for name, bad in (
            ("node", "wrong-node"),
            ("diskfill_file", "/tmp/diskfill"),
            ("diskfill_nonce", "z" * 32),
            ("nodefs_device", True),
            ("diskfill_inode", 999),
            ("node_uid_before", "wrong-uid"),
            ("node_ready_before", "False"),
            ("node_disk_pressure_before", "True"),
            ("nodefs_pre_available_bytes", "80000"),
            ("nodefs_pre_available_bytes", 9_999),
            ("nodefs_injection_available_bytes", 70_001),
            ("diskfill_allocated_bytes", 60_999),
            ("diskfill_allocated_blocks", 119),
            ("nodefs_post_available_bytes", 9_001),
            ("nodefs_target_available_percent", 10),
            ("wait_seconds", 0),
            ("wait_seconds", 180.0),
        ):
            with self.subTest(field=name):
                mutated = dict(receipt, **{name: bad})
                with self.assertRaises(PilotError):
                    validator.validate(
                        "F4", 4, {"target_service": "worker01"}, mutated
                    )

        above_threshold = live.replace(
            "__V23_NODEFS_LIVE_AVAILABLE__=9000",
            "__V23_NODEFS_LIVE_AVAILABLE__=10000",
        )
        validator = LiveInjectionValidator(
            lambda *_: observed, lambda *_: above_threshold
        )
        with self.assertRaisesRegex(PilotError, "threshold"):
            validator.validate(
                "F4", 4, {"target_service": "worker01"}, receipt
            )

        disk_pressure = dict(observed)
        disk_pressure["status"] = {"conditions": [
            {"type": "Ready", "status": "True"},
            {"type": "DiskPressure", "status": "True"},
        ]}
        validator = LiveInjectionValidator(
            lambda *_: disk_pressure, lambda *_: above_threshold
        )
        verified = validator.validate(
            "F4", 4, {"target_service": "worker01"}, receipt
        )
        self.assertEqual(verified["treatment_basis"], "diskpressure-condition")
        self.assertIs(verified["disk_pressure_observed"], True)
        self.assertIs(verified["nodefs_injection_threshold_verified"], True)
        self.assertIs(verified["nodefs_live_threshold_verified"], False)
        self.assertEqual(verified["diskfill_nonce"], "a" * 32)

        below_floor = live.replace(
            "__V23_NODEFS_LIVE_AVAILABLE__=9000",
            "__V23_NODEFS_LIVE_AVAILABLE__=7999",
        )
        validator = LiveInjectionValidator(
            lambda *_: observed, lambda *_: below_floor
        )
        with self.assertRaisesRegex(PilotError, "threshold"):
            validator.validate(
                "F4", 4, {"target_service": "worker01"}, receipt
            )

        missing_disk = dict(observed)
        missing_disk["status"] = {"conditions": [
            {"type": "Ready", "status": "True"},
        ]}
        validator = LiveInjectionValidator(lambda *_: missing_disk, lambda *_: live)
        with self.assertRaisesRegex(PilotError, "schema"):
            validator.validate(
                "F4", 4, {"target_service": "worker01"}, receipt
            )

        unknown_disk = dict(observed)
        unknown_disk["status"] = {"conditions": [
            {"type": "Ready", "status": "True"},
            {"type": "DiskPressure", "status": "Unknown"},
        ]}
        validator = LiveInjectionValidator(
            lambda *_: unknown_disk, lambda *_: live
        )
        with self.assertRaisesRegex(PilotError, "schema"):
            validator.validate(
                "F4", 4, {"target_service": "worker01"}, receipt
            )

        not_ready = dict(observed)
        not_ready["status"] = {"conditions": [
            {"type": "Ready", "status": "False"},
            {"type": "DiskPressure", "status": "False"},
        ]}
        validator = LiveInjectionValidator(lambda *_: not_ready, lambda *_: live)
        verified = validator.validate(
            "F4", 4, {"target_service": "worker01"}, receipt
        )
        self.assertEqual(verified["treatment_basis"], "node-notready")
        self.assertIs(verified["node_disrupted"], True)
        self.assertEqual(verified["disk_pressure_status"], "False")

        duplicate_disk = dict(observed)
        duplicate_disk["status"] = {"conditions": [
            {"type": "Ready", "status": "True"},
            {"type": "DiskPressure", "status": "False"},
            {"type": "DiskPressure", "status": "False"},
        ]}
        validator = LiveInjectionValidator(
            lambda *_: duplicate_disk, lambda *_: live
        )
        with self.assertRaisesRegex(PilotError, "schema"):
            validator.validate(
                "F4", 4, {"target_service": "worker01"}, receipt
            )

    def test_f4_named_node_timeout_has_dedicated_retry_class(self):
        validator = LiveInjectionValidator(
            lambda *_: (_ for _ in ()).throw(
                subprocess.TimeoutExpired(["kubectl"], 5)
            ),
            lambda *_: "",
        )
        receipt = {
            "fault_id": "F4", "trial": 3, "target_service": "worker03",
            "action": "node_disruption", "node": "yms-proxmox-04",
            "stress_ng_pid": 1234, "stress_ng_start_ticks": 5678,
            "stress_ng_cmdline_sha256": "a" * 64,
            "stress_memory_bytes": "15G", "stress_vm_workers": 2,
            "stress_timeout_seconds": 180, "wait_seconds": 120,
        }
        with self.assertRaises(F4ObservationTimeout):
            validator.validate("F4", 3, {"target_service": "worker03"}, receipt)

    def test_f4_memory_rejects_wrong_node_before_load_or_ssh(self):
        calls = []
        validator = LiveInjectionValidator(
            lambda *_: calls.append("load") or node_state("Unknown"),
            lambda *_: calls.append("ssh") or "Connection timed out",
        )
        base = {
            "fault_id": "F4", "trial": 3, "target_service": "worker03",
            "action": "node_disruption",
            "stress_ng_pid": 1234, "stress_ng_start_ticks": 5678,
            "stress_ng_cmdline_sha256": "a" * 64,
            "stress_memory_bytes": "15G", "stress_vm_workers": 2,
            "stress_timeout_seconds": 180, "wait_seconds": 120,
        }
        for bad_node in (None, "", "wrong-node", 123):
            with self.subTest(node=bad_node):
                with self.assertRaisesRegex(PilotError, "node identity"):
                    validator.validate(
                        "F4", 3, {"target_service": "worker03"},
                        {**base, "node": bad_node},
                    )
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()

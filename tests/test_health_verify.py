import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts.stabilize import health_verify
from scripts.stabilize import recovery


class HealthVerifyTests(unittest.TestCase):
    def test_disk_usage_ignores_unrelated_ssh_stderr_after_exact_marker(self):
        commands = []

        def probe(_node, command, timeout):
            commands.append((command, timeout))
            return (
                "__V23_DISK_USAGE_PCT__=20\n"
                "bash: warning: setlocale: LC_ALL: cannot change locale "
                "(ko_KR.UTF-8)\n"
            )

        with patch.object(health_verify, "ssh_node", side_effect=probe):
            self.assertEqual(health_verify._check_disk_usage(), [])
        self.assertEqual(len(commands), len(health_verify.WORKER_NODES))
        self.assertTrue(all("LC_ALL=C df -P /" in item[0] for item in commands))
        self.assertTrue(all("__V23_DISK_USAGE_PCT__=" in item[0] for item in commands))

    def test_disk_usage_rejects_missing_duplicate_or_invalid_markers(self):
        malformed = (
            "20%\n",
            "__V23_DISK_USAGE_PCT__=20\n__V23_DISK_USAGE_PCT__=20\n",
            "__V23_DISK_USAGE_PCT__=20%\n",
            "__V23_DISK_USAGE_PCT__=101\n",
        )
        for output in malformed:
            with self.subTest(output=output), patch.object(
                health_verify, "ssh_node", return_value=output
            ), patch.object(
                health_verify, "_nodefs_usage_from_kubelet", side_effect=ValueError("unavailable")
            ):
                issues = health_verify._check_disk_usage()
                self.assertEqual(len(issues), len(health_verify.WORKER_NODES))
                self.assertTrue(all("marker is malformed" in item for item in issues))

    def test_disk_usage_uses_fresh_kubelet_nodefs_summary_after_ssh_timeout(self):
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        def kubelet_summary(*args, **_kwargs):
            node_name = args[2].split("/")[4]
            return __import__("json").dumps(
                {
                    "node": {
                        "nodeName": node_name,
                        "fs": {
                            "capacityBytes": 1000,
                            "availableBytes": 800,
                            "time": now,
                        },
                    }
                }
            )

        with patch.object(health_verify, "ssh_node", side_effect=TimeoutError("ssh")), patch.object(
            health_verify, "kubectl", side_effect=kubelet_summary
        ) as kubectl:
            self.assertEqual(health_verify._check_disk_usage(), [])

        self.assertEqual(kubectl.call_count, len(health_verify.WORKER_NODES))
        self.assertTrue(all("/proxy/stats/summary" in call.args[2] for call in kubectl.call_args_list))

    def test_kubelet_nodefs_rejects_stale_summary(self):
        summary = {
            "node": {
                "nodeName": "yms-proxmox-02",
                "fs": {
                    "capacityBytes": 1000,
                    "availableBytes": 800,
                    "time": "2020-01-01T00:00:00Z",
                },
            }
        }
        with patch.object(health_verify, "kubectl", return_value=__import__("json").dumps(summary)):
            with self.assertRaisesRegex(ValueError, "stale"):
                health_verify._nodefs_usage_from_kubelet("yms-proxmox-02")

    def test_disk_usage_preserves_threshold_gate(self):
        with patch.object(
            health_verify,
            "ssh_node",
            return_value="__V23_DISK_USAGE_PCT__=80\n",
        ):
            issues = health_verify._check_disk_usage()
        self.assertEqual(len(issues), len(health_verify.WORKER_NODES))
        self.assertTrue(all("disk=80%" in item for item in issues))


class RecoveryManifestTests(unittest.TestCase):
    def test_full_reset_uses_manifest_from_the_checked_out_revision(self):
        expected = (
            Path(recovery.__file__).resolve().parents[2]
            / "k8s" / "app" / "online-boutique.yaml"
        )
        self.assertEqual(Path(recovery.ORIGINAL_MANIFEST), expected)
        self.assertTrue(expected.is_file())
        self.assertNotIn("/tmp/thesis-rca-work", recovery.ORIGINAL_MANIFEST)

        with patch.object(recovery, "kubectl", return_value="applied") as apply, patch.object(
            recovery, "kubectl_delete"
        ) as delete, patch.object(recovery, "kubectl_get_json", return_value={"items": []}):
            result = recovery.Recovery()._full_reset()
        self.assertEqual(result, {"action": "full_reset", "output": "applied"})
        self.assertEqual(
            [call.args for call in delete.call_args_list],
            [("networkpolicy", name) for name in recovery.F6_POLICY_NAMES.values()],
        )
        apply.assert_called_once_with(
            "apply", "-f", str(expected), namespace=recovery.NAMESPACE
        )

    def test_full_reset_removes_only_exact_f2_command_residual(self):
        deployments = {"items": [{
            "metadata": {"name": "shippingservice"},
            "spec": {"template": {"spec": {"containers": [
                {"name": "server", "command": ["/bin/sh", "-c", "exit 1"]},
                {"name": "sidecar", "command": ["/bin/sh", "-c", "keep"]},
            ]}}},
        }]}
        with patch.object(recovery, "kubectl", return_value="applied"), patch.object(
            recovery, "kubectl_delete"
        ), patch.object(recovery, "kubectl_get_json", return_value=deployments), patch.object(
            recovery, "kubectl_patch", return_value="patched"
        ) as patcher:
            recovery.Recovery()._full_reset()
        patcher.assert_called_once_with(
            "deployment", "shippingservice",
            [{"op": "remove", "path": "/spec/template/spec/containers/0/command"}],
            patch_type="json",
        )

    def test_f8_t4_recovery_restores_sealed_probe_without_rollout_undo(self):
        deployment = {"spec": {"template": {"spec": {"containers": [
            {"name": "server", "readinessProbe": {"httpGet": {"path": "/nonexistent"}}},
        ]}}}}
        original_probe = {"grpc": {"port": 50051}, "periodSeconds": 5}
        with patch.object(recovery, "kubectl_get_json", return_value=deployment), patch.object(
            recovery, "kubectl_patch", return_value="patched"
        ) as patcher, patch.object(recovery, "kubectl", return_value="rolled out") as kubectl:
            result = recovery.Recovery()._recover_f8(4, {
                "target_service": "shippingservice",
                "container_name": "server",
                "original_readiness_probe": original_probe,
            })
        self.assertEqual(result, {"action": "restore_service", "trial": 4})
        patcher.assert_called_once_with(
            "deployment", "shippingservice",
            [{
                "op": "replace",
                "path": "/spec/template/spec/containers/0/readinessProbe",
                "value": original_probe,
            }],
            patch_type="json",
        )
        self.assertNotIn("undo", " ".join(str(call.args) for call in kubectl.call_args_list))


if __name__ == "__main__":
    unittest.main()

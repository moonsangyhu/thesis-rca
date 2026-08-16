import unittest
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
            ):
                issues = health_verify._check_disk_usage()
                self.assertEqual(len(issues), len(health_verify.WORKER_NODES))
                self.assertTrue(all("marker is malformed" in item for item in issues))

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

        with patch.object(recovery, "kubectl", return_value="applied") as apply:
            result = recovery.Recovery()._full_reset()
        self.assertEqual(result, {"action": "full_reset", "output": "applied"})
        apply.assert_called_once_with(
            "apply", "-f", str(expected), namespace=recovery.NAMESPACE
        )


if __name__ == "__main__":
    unittest.main()

"""Regression coverage for kubectl execution after local ML initialization."""
import subprocess
import unittest
from unittest.mock import patch


class KubectlPosixSpawnTests(unittest.TestCase):
    def test_fault_inject_kubectl_uses_absolute_executable_and_keeps_fds(self):
        from scripts.fault_inject import base

        completed = subprocess.CompletedProcess(["kubectl"], 0, "{}", "")
        with patch("scripts.fault_inject.base.shutil.which", return_value="/usr/local/bin/kubectl"), \
                patch("scripts.fault_inject.base.subprocess.run", return_value=completed) as run:
            base.kubectl("get", "pods")

        self.assertEqual(run.call_args.args[0][0], "/usr/local/bin/kubectl")
        self.assertFalse(run.call_args.kwargs["close_fds"])

    def test_state_validator_uses_absolute_executable_and_keeps_fds(self):
        from scripts.stabilize import state_validator

        completed = subprocess.CompletedProcess(["kubectl"], 0, '{"items": []}', "")
        with patch("scripts.stabilize.state_validator.shutil.which", return_value="/usr/local/bin/kubectl"), \
                patch("scripts.stabilize.state_validator.subprocess.run", return_value=completed) as run:
            self.assertEqual(state_validator._kubectl_json("get", "pods"), {"items": []})

        self.assertEqual(run.call_args.args[0][0], "/usr/local/bin/kubectl")
        self.assertFalse(run.call_args.kwargs["close_fds"])

    def test_collectors_use_absolute_executable_and_keep_fds(self):
        from src.collector import gitops, kubectl

        completed = subprocess.CompletedProcess(["kubectl"], 0, "", "")
        with patch("src.collector.kubectl.shutil.which", return_value="/usr/local/bin/kubectl"), \
                patch("src.collector.kubectl.subprocess.run", return_value=completed) as run:
            kubectl._run(["get", "pods"])
        self.assertEqual(run.call_args.args[0][0], "/usr/local/bin/kubectl")
        self.assertFalse(run.call_args.kwargs["close_fds"])

        with patch("src.collector.gitops.subprocess.run", return_value=completed) as run:
            gitops._run(["/usr/local/bin/kubectl", "get", "kustomization"])
        self.assertFalse(run.call_args.kwargs["close_fds"])

    def test_git_revision_uses_absolute_git_and_keeps_fds(self):
        from pathlib import Path
        from experiments.v2_3.run import _verified_git_revision

        completed = [
            subprocess.CompletedProcess(["git"], 0, "a" * 40 + "\n", ""),
            subprocess.CompletedProcess(["git"], 0, "", ""),
        ]
        with patch("experiments.v2_3.run.shutil.which", return_value="/usr/bin/git"), \
                patch("experiments.v2_3.run.subprocess.run", side_effect=completed) as run:
            self.assertEqual(_verified_git_revision(Path("/repo")), "a" * 40)

        self.assertEqual(run.call_args_list[0].args[0][0], "/usr/bin/git")
        self.assertEqual(run.call_args_list[1].args[0][0], "/usr/bin/git")
        self.assertTrue(all(not call.kwargs["close_fds"] for call in run.call_args_list))

if __name__ == "__main__":
    unittest.main()

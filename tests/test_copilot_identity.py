import subprocess
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from experiments.shared.copilot_identity import (
    CopilotIdentityError, _run_identity_probe, inspect_active_gh_account,
)


class CopilotIdentityTests(unittest.TestCase):
    @patch("experiments.shared.copilot_identity.shutil.which", return_value="/usr/bin/gh")
    @patch("experiments.shared.copilot_identity._run_identity_probe")
    def test_exact_active_account_passes(self, probe, _which):
        probe.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout="researcher\n", stderr=""
        )
        identity = inspect_active_gh_account(
            expected_login="researcher",
            now=datetime(2026, 8, 16, tzinfo=timezone.utc),
        )
        self.assertEqual(identity.login, "researcher")
        self.assertEqual(identity.source, "gh-api-active-user")
        self.assertEqual(probe.call_args.args[0][1:], ["api", "user", "--jq", ".login"])

    @patch("experiments.shared.copilot_identity.shutil.which", return_value="/usr/bin/gh")
    @patch("experiments.shared.copilot_identity._run_identity_probe")
    def test_timeout_retries_once_and_second_fails(self, probe, _which):
        probe.side_effect = subprocess.TimeoutExpired(cmd=["gh"], timeout=30)
        with self.assertRaisesRegex(CopilotIdentityError, "timed out"):
            inspect_active_gh_account(expected_login="researcher")
        self.assertEqual(probe.call_count, 2)

    @patch("experiments.shared.copilot_identity.shutil.which", return_value="/usr/bin/gh")
    @patch("experiments.shared.copilot_identity._run_identity_probe")
    def test_mismatch_and_process_failure_fail_closed_without_retry(self, probe, _which):
        for outcome in (
            subprocess.CompletedProcess(args=[], returncode=0, stdout="other\n", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="x"),
            OSError("boom"),
        ):
            probe.reset_mock()
            probe.side_effect = None
            if isinstance(outcome, BaseException):
                probe.side_effect = outcome
            else:
                probe.return_value = outcome
            with self.subTest(outcome=outcome), self.assertRaises(CopilotIdentityError):
                inspect_active_gh_account(expected_login="researcher")
            self.assertEqual(probe.call_count, 1)

    @patch("experiments.shared.copilot_identity.os.killpg")
    @patch("experiments.shared.copilot_identity.subprocess.Popen")
    def test_timeout_and_interruption_kill_process_group(self, popen, killpg):
        for exc in (
            subprocess.TimeoutExpired(cmd=["gh"], timeout=3), KeyboardInterrupt(),
        ):
            process = popen.return_value
            process.pid = 4444
            process.communicate.side_effect = (exc, ("", ""))
            with self.subTest(exc=type(exc).__name__), self.assertRaises(type(exc)):
                _run_identity_probe(["gh"], timeout_seconds=3)
            killpg.assert_called_with(4444, 9)
            process.communicate.reset_mock()

    def test_invalid_contract_is_rejected(self):
        for kwargs in (
            {"expected_login": ""},
            {"expected_login": "researcher", "timeout_seconds": True},
            {"expected_login": "researcher", "timeout_retries": 2},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                inspect_active_gh_account(**kwargs)


if __name__ == "__main__":
    unittest.main()

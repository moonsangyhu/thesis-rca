import subprocess
import unittest
from unittest.mock import patch

from experiments.shared.infra import _run_kubectl_check, preflight_check


class InfraCheckTests(unittest.TestCase):
    @patch("experiments.shared.infra.os.killpg")
    @patch("experiments.shared.infra.subprocess.Popen")
    def test_timeout_kills_group_then_retries_once(self, popen, killpg):
        first = unittest.mock.Mock(pid=1101)
        first.communicate.side_effect = (
            subprocess.TimeoutExpired(cmd=["kubectl"], timeout=30),
            ("", ""),
        )
        second = unittest.mock.Mock(pid=1102, returncode=0)
        second.communicate.return_value = ("node Ready\n", "")
        popen.side_effect = (first, second)

        result = _run_kubectl_check(["kubectl", "get", "nodes"])

        self.assertEqual(result.returncode, 0)
        self.assertEqual(popen.call_count, 2)
        killpg.assert_called_once_with(1101, 9)
        self.assertTrue(popen.call_args_list[0].kwargs["start_new_session"])

    @patch("experiments.shared.infra.os.killpg")
    @patch("experiments.shared.infra.subprocess.Popen")
    def test_second_timeout_returns_failure(self, popen, killpg):
        processes = []
        for pid in (1201, 1202):
            process = unittest.mock.Mock(pid=pid)
            process.communicate.side_effect = (
                subprocess.TimeoutExpired(cmd=["kubectl"], timeout=30),
                ("", ""),
            )
            processes.append(process)
        popen.side_effect = processes

        self.assertIsNone(_run_kubectl_check(["kubectl", "get", "nodes"]))
        self.assertEqual(killpg.call_count, 2)

    @patch("experiments.shared.infra.os.killpg")
    @patch("experiments.shared.infra.subprocess.Popen")
    def test_interruption_kills_group_and_propagates(self, popen, killpg):
        process = popen.return_value
        process.pid = 1301
        process.communicate.side_effect = (KeyboardInterrupt(), ("", ""))
        with self.assertRaises(KeyboardInterrupt):
            _run_kubectl_check(["kubectl", "get", "nodes"])
        killpg.assert_called_once_with(1301, 9)

    @patch("experiments.shared.infra._check_port", return_value=True)
    @patch("experiments.shared.infra._run_kubectl_check")
    def test_preflight_fails_closed_without_raising_on_probe_failure(
        self, run_check, _port
    ):
        run_check.side_effect = (None, subprocess.CompletedProcess(
            args=[], returncode=0, stdout="pod Running\n" * 12, stderr=""
        ))
        self.assertFalse(preflight_check())

    def test_invalid_timeout_contract_is_rejected(self):
        for kwargs in (
            {"timeout_seconds": True}, {"timeout_seconds": 0},
            {"timeout_retries": True}, {"timeout_retries": -1},
            {"timeout_retries": 2},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                _run_kubectl_check(
                    ["kubectl", "get", "nodes"], **kwargs
                )


if __name__ == "__main__":
    unittest.main()

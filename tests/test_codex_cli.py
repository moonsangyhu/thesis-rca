import json
import tempfile
import unittest
from datetime import datetime, timezone
from subprocess import CompletedProcess
from unittest.mock import patch

from experiments.shared.codex_cli import CodexCLIBackend
from experiments.shared.copilot_cli import CopilotCLIError


def events(*, message='{"ok":true}', tokens=9):
    return "\n".join(json.dumps(row) for row in (
        {"type": "thread.started", "thread_id": "thread-1"},
        {"type": "turn.started"},
        {"type": "item.completed", "item": {"type": "agent_message", "text": message}},
        {"type": "turn.completed", "usage": {"output_tokens": tokens}},
    )) + "\n"


class CodexCLIBackendTests(unittest.TestCase):
    def backend(self, observer=None):
        return CodexCLIBackend(
            model="gpt-5.6-terra", executable="codex", subscription_authorized=True,
            charge_observer=observer,
        )

    @patch("experiments.shared.codex_cli.shutil.which", return_value="/opt/bin/codex")
    @patch("experiments.shared.codex_cli.subprocess.run")
    def test_success_seals_token_usage_and_empty_readonly_command(self, run, _which):
        run.return_value = CompletedProcess([], 0, events(), "")
        receipts = []
        response = self.backend(receipts.append).call("user", "system", 128)
        self.assertEqual(response.text, '{"ok":true}')
        self.assertEqual(response.model, "gpt-5.6-terra")
        self.assertEqual(response.ai_credits, 0.0)
        self.assertEqual(response.output_tokens, 9)
        command = run.call_args.args[0]
        self.assertIn("--ephemeral", command)
        self.assertIn("--sandbox", command)
        self.assertIn("read-only", command)
        self.assertIn("--skip-git-repo-check", command)
        self.assertTrue(receipts[0]["usage_metadata_complete"])
        self.assertEqual(receipts[0]["actual_model"], "gpt-5.6-terra")
        self.assertEqual(receipts[0]["ai_credits"], 0.0)

    @patch("experiments.shared.codex_cli.shutil.which", return_value="/opt/bin/codex")
    @patch("experiments.shared.codex_cli.subprocess.run")
    def test_rejects_any_non_message_item(self, run, _which):
        polluted = events().replace(
            '"agent_message"', '"command_execution"', 1,
        )
        run.return_value = CompletedProcess([], 0, polluted, "")
        with self.assertRaisesRegex(CopilotCLIError, "invalid isolated response"):
            self.backend().call("user", "system", 128)

    @patch("experiments.shared.codex_cli.shutil.which", return_value="/opt/bin/codex")
    @patch("experiments.shared.codex_cli.subprocess.run")
    def test_nonzero_exit_keeps_usage_incomplete(self, run, _which):
        run.return_value = CompletedProcess([], 1, "", "provider failure")
        receipts = []
        with self.assertRaises(CopilotCLIError):
            self.backend(receipts.append).call("user", "system", 128)
        self.assertFalse(receipts[0]["usage_metadata_complete"])
        self.assertIsNone(receipts[0]["actual_model"])


if __name__ == "__main__":
    unittest.main()

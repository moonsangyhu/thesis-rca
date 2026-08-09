import json
import subprocess
import unittest
from unittest.mock import patch

from experiments.shared.copilot_cli import CopilotCLIBackend, CopilotCLIError
from experiments.shared.llm_client import BaseLLMClient


def event(event_type, data=None, **extra):
    payload = {"type": event_type, **extra}
    if data is not None:
        payload["data"] = data
    return json.dumps(payload)


class CopilotCLIBackendTest(unittest.TestCase):
    @patch("experiments.shared.copilot_cli.shutil.which", return_value="/opt/bin/copilot")
    @patch("experiments.shared.copilot_cli.subprocess.run")
    def test_call_pins_model_and_disables_tools(self, run, _which):
        run.return_value = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="\n".join(
                [
                    event(
                        "assistant.message",
                        {
                            "content": '{"ready":true}',
                            "model": "gpt-5.6-terra",
                            "outputTokens": 7,
                        },
                    ),
                    event(
                        "session.usage_checkpoint",
                        {
                            "totalNanoAiu": 966_900_000,
                            "totalPremiumRequests": 1,
                        },
                    ),
                    event(
                        "result",
                        sessionId="session-1",
                        usage={"premiumRequests": 1},
                    ),
                ]
            ),
            stderr="",
        )
        receipts = []
        backend = CopilotCLIBackend(
            zero_overage_confirmed=True, charge_observer=receipts.append
        )

        response = backend.call("diagnose", "return JSON", 512)

        self.assertEqual(response.text, '{"ready":true}')
        self.assertEqual(response.model, "gpt-5.6-terra")
        self.assertEqual(response.session_id, "session-1")
        self.assertEqual(response.output_tokens, 7)
        self.assertEqual(response.ai_credits, 0.9669)
        self.assertEqual(response.premium_requests, 1.0)
        command = run.call_args.args[0]
        self.assertIn("--available-tools=none", command)
        self.assertIn("--disable-builtin-mcps", command)
        self.assertNotIn("--allow-all-tools", command)
        self.assertEqual(command[command.index("--max-ai-credits") + 1], "10.0")
        self.assertEqual(command[command.index("--model") + 1], "gpt-5.6-terra")
        self.assertIn("<SYSTEM_INSTRUCTIONS>", command[command.index("-p") + 1])
        self.assertTrue(response.started_at)
        self.assertTrue(response.ended_at)
        self.assertEqual(response.cli_executable, "/opt/bin/copilot")
        self.assertTrue(response.temporary_cwd_id.startswith("thesis-copilot-inference-"))
        self.assertEqual(len(receipts), 1)
        self.assertTrue(receipts[0]["usage_metadata_complete"])
        self.assertEqual(receipts[0]["ai_credits"], 0.9669)

    @patch("experiments.shared.copilot_cli.shutil.which", return_value="/opt/bin/copilot")
    def test_model_drift_fails_closed(self, _which):
        backend = CopilotCLIBackend()
        output = "\n".join(
            [
                event(
                    "assistant.message",
                    {"content": "ok", "model": "other-model", "outputTokens": 1},
                ),
                event("session.usage_checkpoint", {"totalNanoAiu": 1}),
                event("result", sessionId="session-2", usage={}),
            ]
        )
        with self.assertRaisesRegex(RuntimeError, "model drift"):
            backend._parse_jsonl(output)

    @patch("experiments.shared.copilot_cli.shutil.which", return_value="/opt/bin/copilot")
    @patch("experiments.shared.copilot_cli.subprocess.run")
    def test_nonzero_exit_fails_closed(self, run, _which):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="quota exceeded"
        )
        receipts = []
        with self.assertRaisesRegex(RuntimeError, "quota exceeded"):
            CopilotCLIBackend(
                zero_overage_confirmed=True, charge_observer=receipts.append
            ).call(
                "diagnose", "return JSON", 512
            )
        self.assertEqual(len(receipts), 1)
        self.assertFalse(receipts[0]["usage_metadata_complete"])
        self.assertEqual(receipts[0]["exit_code"], 1)

    @patch("experiments.shared.copilot_cli.shutil.which", return_value="/opt/bin/copilot")
    @patch("experiments.shared.copilot_cli.subprocess.run")
    def test_non_object_json_event_is_wrapped_with_charge_receipt(self, run, _which):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="\n".join([
                "[]",
                event("assistant.message", {
                    "content": "{}", "model": "gpt-5.6-terra", "outputTokens": 1,
                }),
                event("session.usage_checkpoint", {
                    "totalNanoAiu": 9_000_000_000, "totalPremiumRequests": 1,
                }),
                event("result", sessionId="session-bad-event"),
            ]),
            stderr="",
        )
        receipts = []
        backend = CopilotCLIBackend(
            zero_overage_confirmed=True, charge_observer=receipts.append
        )
        with self.assertRaisesRegex(CopilotCLIError, "JSON object") as caught:
            backend.call("diagnose", "return JSON", 512)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(caught.exception.receipt["ai_credits"], 9.0)

    @patch("experiments.shared.copilot_cli.shutil.which", return_value="/opt/bin/copilot")
    @patch("experiments.shared.copilot_cli.subprocess.run")
    def test_non_object_nested_data_still_writes_receipt(self, run, _which):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="\n".join([
                json.dumps({"type": "assistant.message", "data": ["invalid"]}),
                event("session.usage_checkpoint", {"totalNanoAiu": 2_000_000_000}),
                event("result", sessionId="session-invalid-data"),
            ]),
            stderr="",
        )
        receipts = []
        backend = CopilotCLIBackend(
            zero_overage_confirmed=True, charge_observer=receipts.append
        )
        with self.assertRaises(CopilotCLIError):
            backend.call("diagnose", "return JSON", 512)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(receipts[0]["ai_credits"], 2.0)

    @patch("experiments.shared.copilot_cli.CopilotCLIBackend")
    def test_base_client_exposes_copilot_usage_metadata(self, backend_type):
        backend_type.return_value.call.return_value = type(
            "Response",
            (),
            {
                "text": "{}",
                "output_tokens": 3,
                "ai_credits": 0.5,
                "premium_requests": 1.0,
                "session_id": "session-3",
                "model": "gpt-5.6-terra",
            },
        )()
        client = BaseLLMClient(model="gpt-5.6-terra", provider="copilot")

        text, usage = client.call_llm("input", "system", 128)

        self.assertEqual(text, "{}")
        self.assertEqual(usage["output"], 3)
        self.assertEqual(usage["ai_credits"], 0.5)
        self.assertEqual(usage["premium_requests"], 1.0)
        self.assertEqual(usage["session_id"], "session-3")

    @patch("experiments.shared.copilot_cli.shutil.which", return_value="/opt/bin/copilot")
    def test_missing_aic_checkpoint_fails_closed(self, _which):
        backend = CopilotCLIBackend()
        output = "\n".join(
            [
                event(
                    "assistant.message",
                    {"content": "ok", "model": "gpt-5.6-terra", "outputTokens": 1},
                ),
                event("result", sessionId="session-4", usage={"premiumRequests": 1}),
            ]
        )
        with self.assertRaisesRegex(RuntimeError, "AIC usage metadata"):
            backend._parse_jsonl(output)

    @patch("experiments.shared.copilot_cli.shutil.which", return_value="/opt/bin/copilot")
    def test_tool_request_fails_closed(self, _which):
        backend = CopilotCLIBackend()
        output = event(
            "assistant.message",
            {
                "content": "",
                "model": "gpt-5.6-terra",
                "outputTokens": 0,
                "toolRequests": [{"name": "shell"}],
            },
        )
        with self.assertRaisesRegex(RuntimeError, "tool request"):
            backend._parse_jsonl(output)

    @patch("experiments.shared.copilot_cli.shutil.which", return_value="/opt/bin/copilot")
    def test_tool_event_and_nonfinite_usage_fail_closed(self, _which):
        backend = CopilotCLIBackend()
        with self.assertRaisesRegex(RuntimeError, "tool execution"):
            backend._parse_jsonl(event("tool.started", {"name": "shell"}))
        output = "\n".join([
            event("assistant.message", {
                "content": "{}", "model": "gpt-5.6-terra", "outputTokens": 1,
            }),
            event("session.usage_checkpoint", {"totalNanoAiu": float("nan")}),
            event("result", sessionId="session-bad-usage"),
        ])
        with self.assertRaisesRegex(RuntimeError, "usage metadata"):
            backend._parse_jsonl(output)

    @patch("experiments.shared.copilot_cli.shutil.which", return_value="/opt/bin/copilot")
    @patch("experiments.shared.copilot_cli.subprocess.run")
    def test_billing_guard_blocks_before_subprocess(self, run, _which):
        backend = CopilotCLIBackend(zero_overage_confirmed=False)
        with self.assertRaisesRegex(RuntimeError, "zero-overage"):
            backend.call("diagnose", "return JSON", 512)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

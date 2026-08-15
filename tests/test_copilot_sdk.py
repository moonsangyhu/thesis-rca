import hashlib
import json
import subprocess
import tempfile
import unittest
import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from experiments.shared.copilot_cli import (
    RETRYABLE_ZERO_USAGE_AUTH_FAILURE_CODE, CopilotCLIError,
)
from experiments.shared.copilot_sdk import (
    ZERO_USAGE_AUTH_MESSAGE, CopilotSDKBackend,
)
from experiments.v2_3.live_runner import ChargedCallJournal


def valid_output(nonce: str, prompt: str, system_prompt: str) -> str:
    session_id = str(uuid.uuid4())
    nano_aiu = 123_000_000
    output_tokens = 9
    premium = 1
    def ephemeral(event_type, data):
        return {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "parentId": None,
            "ephemeral": True,
            "type": event_type,
            "data": data,
        }

    records = [
        {
            "type": "thesis.sdk.binding", "schema_version": 1,
            "session_id": session_id, "mode": "empty",
            "model": "gpt-5.6-terra", "reasoning_effort": "medium",
            "available_tools": [], "excluded_tools": [], "tools": [],
            "enable_skills": False, "enable_config_discovery": False,
            "skip_custom_instructions": True, "mcp_servers": [],
            "custom_agents": [], "remote_session": "off",
            "max_output_tokens": 128, "max_ai_credits": 30,
            "request_nonce": nonce,
            "system_prompt_sha256": hashlib.sha256(system_prompt.encode()).hexdigest(),
            "user_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        },
        ephemeral("session.skills_loaded", {"skills": []}),
        ephemeral("session.tools_updated", {"model": "gpt-5.6-terra"}),
        {"type": "user.message", "data": {"content": prompt, "attachments": []}},
        ephemeral(
            "assistant.usage",
            {
                "model": "gpt-5.6-terra", "outputTokens": output_tokens,
                "cost": premium, "availableToolCount": 0, "numToolCalls": 0,
                "copilotUsage": {"totalNanoAiu": nano_aiu},
            },
        ),
        {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "parentId": str(uuid.uuid4()),
            "type": "session.usage_checkpoint",
            "data": {
                "modelCacheState": [{
                    "cacheExpiresAt": datetime.now(timezone.utc).isoformat(),
                    "cacheTtlSeconds": 1800,
                    "modelId": "gpt-5.6-terra",
                }],
                "totalNanoAiu": nano_aiu,
                "totalPremiumRequests": premium,
            },
        },
        {"type": "assistant.message", "data": {"content": '{"ok":true}'}},
        {
            "type": "thesis.sdk.result", "schema_version": 1,
            "session_id": session_id, "request_nonce": nonce,
            "response": '{"ok":true}',
            "metrics": {
                "currentModel": "gpt-5.6-terra", "totalUserRequests": 1,
                "totalNanoAiu": nano_aiu, "totalPremiumRequestCost": premium,
                "modelMetrics": {
                    "gpt-5.6-terra": {
                        "requests": {"count": 1, "cost": premium},
                        "usage": {"outputTokens": output_tokens},
                    },
                },
            },
        },
    ]
    return "\n".join(json.dumps(record) for record in records)


def zero_usage_auth_output(
    nonce: str, prompt: str, system_prompt: str,
    working_directory: str = "/tmp/working",
) -> str:
    session_id = str(uuid.uuid4())
    error_id = str(uuid.uuid4())
    parent_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    records = [
        {
            "id": str(uuid.uuid4()), "timestamp": now, "parentId": None,
            "type": "session.start",
            "data": {
                "alreadyInUse": False, "context": {"cwd": working_directory},
                "contextTier": None, "copilotVersion": "1.0.77",
                "producer": "copilot-agent", "reasoningEffort": "medium",
                "remoteSteerable": False, "selectedModel": "gpt-5.6-terra",
                "sessionId": session_id, "sessionLimits": {"maxAiCredits": 30},
                "startTime": now, "version": 1,
            },
        },
        {
            "type": "thesis.sdk.binding", "schema_version": 1,
            "session_id": session_id, "mode": "empty",
            "model": "gpt-5.6-terra", "reasoning_effort": "medium",
            "available_tools": [], "excluded_tools": [], "tools": [],
            "enable_skills": False, "enable_config_discovery": False,
            "skip_custom_instructions": True, "mcp_servers": [],
            "custom_agents": [], "remote_session": "off",
            "max_output_tokens": 128, "max_ai_credits": 30,
            "request_nonce": nonce,
            "system_prompt_sha256": hashlib.sha256(system_prompt.encode()).hexdigest(),
            "user_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
        },
        {
            "id": error_id, "timestamp": now, "parentId": parent_id,
            "type": "session.error",
            "data": {
                "errorType": "authentication", "message": ZERO_USAGE_AUTH_MESSAGE,
            },
        },
        {
            "type": "thesis.sdk.error", "schema_version": 1,
            "message": ZERO_USAGE_AUTH_MESSAGE,
        },
        {
            "id": str(uuid.uuid4()), "timestamp": now, "parentId": error_id,
            "type": "session.shutdown",
            "data": {
                "shutdownType": "routine", "totalPremiumRequests": 0,
                "totalNanoAiu": 0, "totalApiDurationMs": 0,
                "sessionStartTime": 1, "codeChanges": {
                    "linesAdded": 0, "linesRemoved": 0, "filesModified": [],
                },
                "modelMetrics": {}, "currentTokens": 3, "systemTokens": 0,
                "conversationTokens": 0, "toolDefinitionsTokens": 0,
            },
        },
    ]
    return "\n".join(json.dumps(record) for record in records)


class CopilotSDKBackendTest(unittest.TestCase):
    def backend(self, temp_dir: str, **kwargs) -> CopilotSDKBackend:
        root = Path(temp_dir)
        sdk = root / "index.js"
        runner = root / "runner.mjs"
        sdk.write_text("export class CopilotClient {}\n", encoding="utf-8")
        runner.write_text("// sealed test runner\n", encoding="utf-8")
        return CopilotSDKBackend(
            zero_overage_confirmed=True,
            sdk_index=sdk,
            runner_path=runner,
            **kwargs,
        )

    @patch("experiments.shared.copilot_sdk.shutil.which")
    @patch.object(CopilotSDKBackend, "_run_runner")
    def test_call_uses_official_empty_runner_and_journals_usage(self, run, which):
        which.side_effect = lambda name: f"/opt/bin/{name}"
        prompt = "diagnose"
        system = "return JSON"

        def completed(command, request_json, cwd, env):
            request = json.loads(request_json)
            self.assertEqual(command[0], "/opt/bin/node")
            self.assertEqual(request["model"], "gpt-5.6-terra")
            self.assertEqual(request["max_ai_credits"], 30)
            self.assertEqual(request["max_output_tokens"], 128)
            self.assertEqual(request["user_prompt"], prompt)
            self.assertEqual(request["system_prompt"], system)
            return subprocess.CompletedProcess(
                command, 0,
                valid_output(request["request_nonce"], prompt, system), "",
            ), False

        run.side_effect = completed
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "charged.jsonl"
            journal = ChargedCallJournal(journal_path)
            backend = self.backend(temp_dir, charge_observer=journal.append)
            response = backend.call(prompt, system, 128)
            receipts = [
                json.loads(line) for line in journal_path.read_text().splitlines()
            ]

        self.assertEqual(response.text, '{"ok":true}')
        self.assertEqual(response.model, "gpt-5.6-terra")
        self.assertEqual(response.output_tokens, 9)
        self.assertEqual(response.ai_credits, 0.123)
        self.assertEqual(response.premium_requests, 1.0)
        self.assertEqual(len(receipts), 1)
        self.assertTrue(receipts[0]["usage_metadata_complete"])
        self.assertIn(backend.runner_sha256, receipts[0]["cli_executable"])

    @patch("experiments.shared.copilot_sdk.shutil.which")
    @patch.object(CopilotSDKBackend, "_run_runner")
    def test_exact_zero_usage_auth_failure_is_journaled_and_retryable(
        self, run, which,
    ):
        which.side_effect = lambda name: f"/opt/bin/{name}"
        prompt, system = "diagnose", "return JSON"

        def failed(command, request_json, cwd, env):
            request = json.loads(request_json)
            return subprocess.CompletedProcess(
                command, 1,
                zero_usage_auth_output(
                    request["request_nonce"], prompt, system, str(cwd),
                ), "",
            ), False

        run.side_effect = failed
        receipts = []
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = self.backend(temp_dir, charge_observer=receipts.append)
            with self.assertRaises(CopilotCLIError) as raised:
                backend.call(prompt, system, 128)

        self.assertTrue(raised.exception.retryable_zero_usage_authentication)
        self.assertEqual(
            raised.exception.failure_code,
            RETRYABLE_ZERO_USAGE_AUTH_FAILURE_CODE,
        )
        self.assertEqual(len(receipts), 1)
        self.assertTrue(receipts[0]["usage_metadata_complete"])
        self.assertIsNone(receipts[0]["actual_model"])
        self.assertEqual(receipts[0]["output_tokens"], 0)
        self.assertEqual(receipts[0]["ai_credits"], 0.0)
        self.assertEqual(receipts[0]["premium_requests"], 0.0)

    @patch("experiments.shared.copilot_sdk.shutil.which")
    def test_zero_usage_auth_retry_requires_exact_shutdown_and_binding(self, which):
        which.side_effect = lambda name: f"/opt/bin/{name}"
        prompt, system, nonce = "diagnose", "return JSON", str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = self.backend(temp_dir)
            baseline = [
                json.loads(line) for line in
                zero_usage_auth_output(nonce, prompt, system).splitlines()
            ]
            mutations = []
            altered = json.loads(json.dumps(baseline))
            next(r for r in altered if r["type"] == "session.shutdown")[
                "data"
            ]["totalNanoAiu"] = True
            mutations.append(("bool usage", altered))
            altered = json.loads(json.dumps(baseline))
            next(r for r in altered if r["type"] == "session.shutdown")[
                "data"
            ]["totalApiDurationMs"] = 1
            mutations.append(("api activity", altered))
            altered = json.loads(json.dumps(baseline))
            next(r for r in altered if r["type"] == "session.error")["data"][
                "message"
            ] = "authentication failed"
            mutations.append(("message drift", altered))
            altered = json.loads(json.dumps(baseline))
            next(r for r in altered if r["type"] == "thesis.sdk.binding")[
                "request_nonce"
            ] = str(uuid.uuid4())
            mutations.append(("binding drift", altered))
            altered = json.loads(json.dumps(baseline))
            altered.insert(1, {"type": "model.call_start", "data": {}})
            mutations.append(("model started", altered))
            altered = json.loads(json.dumps(baseline))
            altered.insert(1, {"type": "tool.execution_start", "data": {}})
            mutations.append(("tool started", altered))
            altered = json.loads(json.dumps(baseline))
            altered.reverse()
            mutations.append(("reordered lifecycle", altered))
            altered = json.loads(json.dumps(baseline))
            altered.insert(3, {"type": "assistant.idle", "arbitrary": True})
            mutations.append(("malformed idle", altered))
            altered = json.loads(json.dumps(baseline))
            idle = {
                "id": str(uuid.uuid4()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "parentId": next(
                    r for r in altered if r["type"] == "session.error"
                )["id"],
                "ephemeral": True, "type": "assistant.idle", "data": {},
            }
            altered[2:2] = [idle, json.loads(json.dumps(idle))]
            mutations.append(("duplicate idle", altered))
            altered = json.loads(json.dumps(baseline))
            next(r for r in altered if r["type"] == "thesis.sdk.binding")[
                "schema_version"
            ] = True
            mutations.append(("binding boolean schema", altered))
            altered = json.loads(json.dumps(baseline))
            next(r for r in altered if r["type"] == "thesis.sdk.error")[
                "schema_version"
            ] = True
            mutations.append(("runner error boolean schema", altered))
            altered = json.loads(json.dumps(baseline))
            next(r for r in altered if r["type"] == "session.shutdown")[
                "data"
            ]["codeChanges"]["linesAdded"] = False
            mutations.append(("boolean code changes", altered))
            altered = json.loads(json.dumps(baseline))
            next(r for r in altered if r["type"] == "session.start")["data"][
                "sessionId"
            ] = str(uuid.uuid4())
            mutations.append(("start session drift", altered))
            altered = json.loads(json.dumps(baseline))
            next(r for r in altered if r["type"] == "session.start")["data"][
                "remoteSteerable"
            ] = True
            mutations.append(("start remote enabled", altered))
            for field, value, label in (
                ("context", {"cwd": "/etc"}, "start cwd drift"),
                ("copilotVersion", "evil", "start Copilot version drift"),
                ("producer", "other", "start producer drift"),
                ("contextTier", "unexpected", "start context tier drift"),
                ("version", 999, "start schema version drift"),
                ("version", True, "start boolean schema version"),
            ):
                altered = json.loads(json.dumps(baseline))
                next(
                    r for r in altered if r["type"] == "session.start"
                )["data"][field] = value
                mutations.append((label, altered))

            for label, records in mutations:
                output = "\n".join(json.dumps(r) for r in records)
                with self.subTest(label=label):
                    self.assertFalse(
                        backend._is_retryable_zero_usage_auth_failure(
                            output,
                            expected_prompt=prompt,
                            expected_system_prompt=system,
                            expected_max_tokens=128,
                            expected_nonce=nonce,
                            expected_working_directory=Path("/tmp/working"),
                        )
                    )

    @patch("experiments.shared.copilot_sdk.shutil.which")
    def test_parser_rejects_skill_tool_and_usage_drift(self, which):
        which.side_effect = lambda name: f"/opt/bin/{name}"
        prompt, system, nonce = "p", "s", str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = self.backend(temp_dir)
            baseline = [json.loads(line) for line in valid_output(nonce, prompt, system).splitlines()]
            mutations = []
            altered = json.loads(json.dumps(baseline))
            next(r for r in altered if r["type"] == "session.skills_loaded")["data"]["skills"] = [{"name": "builtin"}]
            mutations.append(("skills", altered))
            altered = json.loads(json.dumps(baseline))
            altered.insert(3, {"type": "tool.execution_start", "data": {}})
            mutations.append(("tool", altered))
            altered = json.loads(json.dumps(baseline))
            altered.insert(3, {"type": "sampling.requested", "data": {}})
            mutations.append(("unknown capability", altered))
            altered = json.loads(json.dumps(baseline))
            next(r for r in altered if r["type"] == "assistant.usage")["data"]["availableToolCount"] = 1
            mutations.append(("tool count", altered))
            altered = json.loads(json.dumps(baseline))
            next(r for r in altered if r["type"] == "thesis.sdk.result")["metrics"]["totalNanoAiu"] += 1
            mutations.append(("usage", altered))
            altered = json.loads(json.dumps(baseline))
            next(r for r in altered if r["type"] == "session.usage_checkpoint")["data"]["totalNanoAiu"] += 1
            mutations.append(("checkpoint", altered))
            for field in ("totalNanoAiu", "totalPremiumRequests"):
                altered = json.loads(json.dumps(baseline))
                next(
                    r for r in altered
                    if r["type"] == "session.usage_checkpoint"
                )["data"][field] = True
                mutations.append((f"checkpoint bool {field}", altered))
            for path in (
                ("totalUserRequests",),
                ("totalNanoAiu",),
                ("totalPremiumRequestCost",),
                ("modelMetrics", "gpt-5.6-terra", "requests", "count"),
                ("modelMetrics", "gpt-5.6-terra", "requests", "cost"),
                ("modelMetrics", "gpt-5.6-terra", "usage", "outputTokens"),
            ):
                altered = json.loads(json.dumps(baseline))
                target = next(
                    r for r in altered if r["type"] == "thesis.sdk.result"
                )["metrics"]
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = True
                mutations.append((f"metrics bool {'.'.join(path)}", altered))
            for label, records in mutations:
                with self.subTest(label=label), self.assertRaises(RuntimeError):
                    backend._parse_output(
                        "\n".join(json.dumps(r) for r in records),
                        expected_prompt=prompt, expected_system_prompt=system,
                        expected_max_tokens=128, expected_nonce=nonce,
                    )

    @patch("experiments.shared.copilot_sdk.shutil.which")
    @patch.object(CopilotSDKBackend, "_run_runner")
    def test_parse_failure_keeps_complete_charge_receipt(self, run, which):
        which.side_effect = lambda name: f"/opt/bin/{name}"
        prompt, system = "diagnose", "return JSON"

        def completed(command, request_json, cwd, env):
            request = json.loads(request_json)
            records = valid_output(request["request_nonce"], prompt, system).splitlines()
            records = [line for line in records if '"thesis.sdk.result"' not in line]
            return subprocess.CompletedProcess(
                command, 0, "\n".join(records), ""
            ), False

        run.side_effect = completed
        receipts = []
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = self.backend(temp_dir, charge_observer=receipts.append)
            with self.assertRaises(CopilotCLIError):
                backend.call(prompt, system, 128)
        self.assertEqual(len(receipts), 1)
        self.assertTrue(receipts[0]["usage_metadata_complete"])
        self.assertEqual(receipts[0]["ai_credits"], 0.123)

    @patch("experiments.shared.copilot_sdk.shutil.which")
    @patch.object(CopilotSDKBackend, "_run_runner")
    def test_hash_drift_blocks_before_subprocess(self, run, which):
        which.side_effect = lambda name: f"/opt/bin/{name}"
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = self.backend(temp_dir)
            backend.runner_path.write_text("changed\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "runner changed"):
                backend.call("p", "s", 128)
        run.assert_not_called()

    @patch("experiments.shared.copilot_sdk.os.killpg")
    @patch("experiments.shared.copilot_sdk.subprocess.Popen")
    @patch("experiments.shared.copilot_sdk.shutil.which")
    def test_outer_timeout_kills_entire_sdk_process_group(
        self, which, popen, killpg
    ):
        which.side_effect = lambda name: f"/opt/bin/{name}"
        process = popen.return_value
        process.pid = 4321
        process.communicate.side_effect = [
            subprocess.TimeoutExpired(["node"], 31),
            ("partial usage", "timeout"),
        ]
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = self.backend(temp_dir, timeout_seconds=1)
            completed, timed_out = backend._run_runner(
                ["node", "runner"], "{}", Path(temp_dir), {},
            )
        self.assertTrue(timed_out)
        self.assertIsNone(completed.returncode)
        self.assertEqual(completed.stdout, "partial usage")
        killpg.assert_called_once_with(4321, 9)
        self.assertTrue(popen.call_args.kwargs["start_new_session"])

    @patch("experiments.shared.copilot_sdk.os.killpg")
    @patch("experiments.shared.copilot_sdk.subprocess.Popen")
    @patch("experiments.shared.copilot_sdk.shutil.which")
    def test_keyboard_interrupt_also_kills_sdk_process_group(
        self, which, popen, killpg
    ):
        which.side_effect = lambda name: f"/opt/bin/{name}"
        process = popen.return_value
        process.pid = 4322
        process.communicate.side_effect = [KeyboardInterrupt(), ("", "")]
        with tempfile.TemporaryDirectory() as temp_dir:
            backend = self.backend(temp_dir)
            with self.assertRaises(KeyboardInterrupt):
                backend._run_runner(
                    ["node", "runner"], "{}", Path(temp_dir), {},
                )
        killpg.assert_called_once_with(4322, 9)

    @patch("experiments.shared.copilot_sdk.shutil.which")
    @patch.object(CopilotSDKBackend, "_run_runner")
    def test_call_timeout_fsyncs_complete_receipt_to_charged_journal(
        self, run, which
    ):
        which.side_effect = lambda name: f"/opt/bin/{name}"
        prompt, system = "diagnose", "return JSON"

        def timed_out(command, request_json, cwd, env):
            request = json.loads(request_json)
            return subprocess.CompletedProcess(
                command, None,
                valid_output(request["request_nonce"], prompt, system),
                "outer timeout",
            ), True

        run.side_effect = timed_out
        with tempfile.TemporaryDirectory() as temp_dir:
            journal_path = Path(temp_dir) / "charged.jsonl"
            backend = self.backend(
                temp_dir,
                charge_observer=ChargedCallJournal(journal_path).append,
            )
            with self.assertRaisesRegex(CopilotCLIError, "timed out"):
                backend.call(prompt, system, 128)
            rows = [json.loads(line) for line in journal_path.read_text().splitlines()]
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["timed_out"])
        self.assertTrue(rows[0]["usage_metadata_complete"])
        self.assertEqual(rows[0]["ai_credits"], 0.123)


if __name__ == "__main__":
    unittest.main()

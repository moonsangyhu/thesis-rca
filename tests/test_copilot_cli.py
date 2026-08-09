import json
import os
import subprocess
import unittest
import uuid
from datetime import datetime, timezone
from unittest.mock import patch

from experiments.shared.copilot_cli import CopilotCLIBackend, CopilotCLIError
from experiments.shared.llm_client import BaseLLMClient


def event(event_type, data=None, **extra):
    payload = {"type": event_type, **extra}
    if data is not None:
        payload["data"] = data
    return json.dumps(payload)


def skill_inventory(enabled):
    return [
        {
            "name": "customize-cloud-agent",
            "description": "builtin one",
            "source": "builtin",
            "path": "/opt/copilot/builtin/customize-cloud-agent",
            "enabled": enabled,
        },
        {
            "name": "github-pr-media",
            "description": "builtin two",
            "source": "builtin",
            "path": "/opt/copilot/builtin/github-pr-media",
            "enabled": enabled,
        },
    ]


def skill_preflight_results(final):
    return [
        subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(skill_inventory(True)), stderr=""
        ),
        subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(skill_inventory(False)), stderr=""
        ),
        final,
    ]


def skills_metadata(skills):
    return json.dumps({
        "id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "parentId": None,
        "ephemeral": True,
        "type": "session.skills_loaded",
        "data": {"skills": skills},
    })


def disabled_skills_metadata():
    return skills_metadata([
        {
            "name": item["name"],
            "description": item["description"],
            "source": "builtin",
            "userInvocable": True,
            "enabled": False,
            "path": item["path"],
        }
        for item in skill_inventory(False)
    ])


class CopilotCLIBackendTest(unittest.TestCase):
    @patch("experiments.shared.copilot_cli.shutil.which", return_value="/opt/bin/copilot")
    @patch("experiments.shared.copilot_cli.subprocess.run")
    def test_call_pins_model_and_disables_tools(self, run, _which):
        inference = subprocess.CompletedProcess(
            args=[],
            returncode=0,
            stdout="\n".join(
                [
                    disabled_skills_metadata(),
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
        run.side_effect = skill_preflight_results(inference)
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
        self.assertEqual(run.call_count, 3)
        command = run.call_args.args[0]
        self.assertIn("--available-tools=none", command)
        self.assertIn("--disable-builtin-mcps", command)
        self.assertNotIn("--allow-all-tools", command)
        self.assertEqual(command[command.index("--max-ai-credits") + 1], "30")
        self.assertEqual(command[command.index("--model") + 1], "gpt-5.6-terra")
        self.assertIn("<SYSTEM_INSTRUCTIONS>", command[command.index("-p") + 1])
        subprocess_env = run.call_args.kwargs["env"]
        self.assertEqual(subprocess_env["COPILOT_DYNAMIC_RETRIEVAL_SKILLS"], "off")
        self.assertTrue(subprocess_env["COPILOT_SKILLS_DIRS"].endswith("skills-empty"))
        self.assertTrue(subprocess_env["COPILOT_HOME"].endswith("copilot-home"))
        self.assertTrue(response.started_at)
        self.assertTrue(response.ended_at)
        self.assertEqual(response.cli_executable, "/opt/bin/copilot")
        self.assertTrue(response.temporary_cwd_id.startswith("thesis-copilot-inference-"))
        self.assertEqual(len(receipts), 1)
        self.assertTrue(receipts[0]["usage_metadata_complete"])
        self.assertEqual(receipts[0]["ai_credits"], 0.9669)

    @patch("experiments.shared.copilot_cli.shutil.which", return_value="/opt/bin/copilot")
    def test_cli_session_aic_cap_respects_current_minimum(self, _which):
        with self.assertRaisesRegex(ValueError, "integer at least 30"):
            CopilotCLIBackend(max_ai_credits=10)
        with self.assertRaisesRegex(ValueError, "integer at least 30"):
            CopilotCLIBackend(max_ai_credits=30.0)
        self.assertEqual(CopilotCLIBackend(max_ai_credits=30).max_ai_credits, 30)

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
        run.side_effect = skill_preflight_results(subprocess.CompletedProcess(
            args=[], returncode=1, stdout="", stderr="quota exceeded"
        ))
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
        run.side_effect = skill_preflight_results(subprocess.CompletedProcess(
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
        ))
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
        run.side_effect = skill_preflight_results(subprocess.CompletedProcess(
            args=[], returncode=0,
            stdout="\n".join([
                json.dumps({"type": "assistant.message", "data": ["invalid"]}),
                event("session.usage_checkpoint", {"totalNanoAiu": 2_000_000_000}),
                event("result", sessionId="session-invalid-data"),
            ]),
            stderr="",
        ))
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
    def test_tools_updated_metadata_is_schema_bound_but_not_tool_execution(self, _which):
        backend = CopilotCLIBackend()
        metadata = json.dumps({
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "parentId": None,
            "ephemeral": True,
            "type": "session.tools_updated",
            "data": {"model": "gpt-5.6-terra"},
        })
        output = "\n".join([
            metadata,
            event("assistant.message", {
                "content": "{}", "model": "gpt-5.6-terra", "outputTokens": 1,
            }),
            event("session.usage_checkpoint", {
                "totalNanoAiu": 1_000_000_000, "totalPremiumRequests": 1,
            }),
            event("result", sessionId="session-tools-metadata"),
        ])
        response = backend._parse_jsonl(output)
        self.assertEqual(response.session_id, "session-tools-metadata")

        invalid = json.loads(metadata)
        invalid["agentId"] = "subagent-1"
        with self.assertRaisesRegex(RuntimeError, "metadata"):
            backend._parse_jsonl(json.dumps(invalid))
        invalid = json.loads(metadata)
        invalid["data"]["model"] = "other-model"
        with self.assertRaisesRegex(RuntimeError, "metadata"):
            backend._parse_jsonl(json.dumps(invalid))
        for field, value in (
            ("parentId", "not-a-uuid/tool.started"),
            ("id", str(uuid.uuid1())),
            ("timestamp", "2026-08-10T07:00:00"),
            ("ephemeral", False),
        ):
            invalid = json.loads(metadata)
            invalid[field] = value
            with self.subTest(field=field), self.assertRaisesRegex(
                RuntimeError, "metadata"
            ):
                backend._parse_jsonl(json.dumps(invalid))

    @patch("experiments.shared.copilot_cli.shutil.which", return_value="/opt/bin/copilot")
    def test_skills_loaded_requires_exact_empty_root_metadata(self, _which):
        backend = CopilotCLIBackend()
        metadata = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "parentId": None,
            "ephemeral": True,
            "type": "session.skills_loaded",
            "data": {"skills": []},
        }
        output = "\n".join([
            json.dumps(metadata),
            event("assistant.message", {
                "content": "{}", "model": "gpt-5.6-terra", "outputTokens": 1,
            }),
            event("session.usage_checkpoint", {"totalNanoAiu": 1}),
            event("result", sessionId="session-empty-skills"),
        ])
        self.assertEqual(
            backend._parse_jsonl(output).session_id, "session-empty-skills"
        )
        metadata["data"]["skills"] = [{"name": "unexpected"}]
        with self.assertRaisesRegex(RuntimeError, "invalid"):
            backend._parse_jsonl(json.dumps(metadata))

    @patch("experiments.shared.copilot_cli.shutil.which", return_value="/opt/bin/copilot")
    def test_skills_loaded_accepts_only_exact_disabled_builtin_inventory(self, _which):
        backend = CopilotCLIBackend()
        backend._disabled_skill_names = frozenset(
            {"customize-cloud-agent", "github-pr-media"}
        )
        backend._skill_isolation_prepared = True
        skills = [
            {
                "name": item["name"],
                "description": item["description"],
                "source": "builtin",
                "userInvocable": True,
                "enabled": False,
                "path": item["path"],
            }
            for item in skill_inventory(False)
        ]
        metadata = {
            "id": str(uuid.uuid4()),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "parentId": None,
            "ephemeral": True,
            "type": "session.skills_loaded",
            "data": {"skills": skills},
        }
        output = "\n".join([
            json.dumps(metadata),
            event("assistant.message", {
                "content": "{}", "model": "gpt-5.6-terra", "outputTokens": 1,
            }),
            event("session.usage_checkpoint", {"totalNanoAiu": 1}),
            event("result", sessionId="session-disabled-skills"),
        ])
        self.assertEqual(
            backend._parse_jsonl(output).session_id, "session-disabled-skills"
        )
        for mutation in ("enabled", "source", "name"):
            altered = json.loads(json.dumps(metadata))
            if mutation == "enabled":
                altered["data"]["skills"][0]["enabled"] = True
            elif mutation == "source":
                altered["data"]["skills"][0]["source"] = "personal-copilot"
            else:
                altered["data"]["skills"][0]["name"] = "unknown"
            with self.subTest(mutation=mutation), self.assertRaisesRegex(
                RuntimeError, "skills metadata"
            ):
                backend._parse_jsonl(json.dumps(altered))

        without_metadata = "\n".join([
            event("assistant.message", {
                "content": "{}", "model": "gpt-5.6-terra", "outputTokens": 1,
            }),
            event("session.usage_checkpoint", {"totalNanoAiu": 1}),
            event("result", sessionId="session-missing-skills"),
        ])
        with self.assertRaisesRegex(RuntimeError, "missing skill-isolation"):
            backend._parse_jsonl(without_metadata)
        with self.assertRaisesRegex(RuntimeError, "duplicated"):
            backend._parse_jsonl("\n".join([
                json.dumps(metadata), json.dumps(metadata),
            ]))

    @patch("experiments.shared.copilot_cli.shutil.which", return_value="/opt/bin/copilot")
    @patch("experiments.shared.copilot_cli.subprocess.run")
    def test_skill_isolation_blocks_nonbuiltin_before_inference(self, run, _which):
        contaminated = skill_inventory(True)
        contaminated.append({
            "name": "personal-skill",
            "description": "must not load",
            "source": "personal-copilot",
            "path": "/home/test/.copilot/skills/personal-skill",
            "enabled": True,
        })
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=json.dumps(contaminated), stderr=""
        )
        backend = CopilotCLIBackend(zero_overage_confirmed=True)
        with self.assertRaisesRegex(RuntimeError, "not isolated"):
            backend.call("diagnose", "return JSON", 512)
        self.assertEqual(run.call_count, 1)

    @patch("experiments.shared.copilot_cli.shutil.which", return_value="/opt/bin/copilot")
    @patch("experiments.shared.copilot_cli.subprocess.run")
    def test_skill_isolation_writes_private_official_config(self, run, _which):
        calls = []

        def fake_run(command, **kwargs):
            calls.append(command)
            if len(calls) == 1:
                return subprocess.CompletedProcess(
                    args=[], returncode=0,
                    stdout=json.dumps(skill_inventory(True)), stderr="",
                )
            if len(calls) == 2:
                config = kwargs["env"]["COPILOT_HOME"] + "/config.json"
                self.assertEqual(os.stat(config).st_mode & 0o777, 0o600)
                with open(config, encoding="utf-8") as handle:
                    self.assertEqual(
                        json.load(handle)["disabledSkills"],
                        ["customize-cloud-agent", "github-pr-media"],
                    )
                return subprocess.CompletedProcess(
                    args=[], returncode=0,
                    stdout=json.dumps(skill_inventory(False)), stderr="",
                )
            return subprocess.CompletedProcess(
                args=[], returncode=1, stdout="", stderr="stop after preflight",
            )

        run.side_effect = fake_run
        with self.assertRaises(CopilotCLIError):
            CopilotCLIBackend(zero_overage_confirmed=True).call(
                "diagnose", "return JSON", 512
            )
        self.assertEqual(len(calls), 3)

    @patch("experiments.shared.copilot_cli.shutil.which", return_value="/opt/bin/copilot")
    @patch("experiments.shared.copilot_cli.subprocess.run")
    def test_billing_guard_blocks_before_subprocess(self, run, _which):
        backend = CopilotCLIBackend(zero_overage_confirmed=False)
        with self.assertRaisesRegex(RuntimeError, "zero-overage"):
            backend.call("diagnose", "return JSON", 512)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()

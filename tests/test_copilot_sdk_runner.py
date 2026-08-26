"""Regression tests for the Node SDK runner's JSONL output boundary."""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "experiments" / "shared" / "copilot_sdk_runner.mjs"


class CopilotSDKRunnerTest(unittest.TestCase):
    def test_large_sdk_event_is_emitted_as_complete_jsonl_record(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is required for the SDK runner")
        # Larger than the failed production boundary (65,536 bytes).  The
        # fake SDK emits it through onEvent and returns it as the final result.
        large_response = '{"diagnosis":"' + ("x" * 70_000) + '"}'
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            sdk = root / "fake_sdk.mjs"
            sdk.write_text(
                """
export class CopilotClient {
  constructor() {}
  async createSession(options) {
    const event = options.onEvent;
    const response = process.env.V23_TEST_RESPONSE;
    return {
      sessionId: "123e4567-e89b-42d3-a456-426614174000",
      sendAndWait: async ({prompt}) => {
        event({type: "assistant.message", data: {content: response}});
        return {data: {content: response}};
      },
      rpc: {usage: {getMetrics: async () => ({ok: true})}},
      disconnect: async () => {},
    };
  }
  async stop() { return []; }
}
""".strip(),
                encoding="utf-8",
            )
            request = {
                "schema_version": 1,
                "base_directory": str(root / "home"),
                "working_directory": str(root / "working"),
                "model": "gpt-5.6-terra",
                "reasoning_effort": "medium",
                "max_output_tokens": 2048,
                "max_ai_credits": 30,
                "timeout_ms": 60_000,
                "request_nonce": "nonce",
                "system_prompt": "system",
                "user_prompt": "prompt",
                "system_prompt_sha256": "a" * 64,
                "user_prompt_sha256": "b" * 64,
            }
            completed = subprocess.run(
                [node, str(RUNNER), str(sdk)],
                input=json.dumps(request),
                text=True,
                capture_output=True,
                check=False,
                env={**__import__("os").environ, "V23_TEST_RESPONSE": large_response},
                timeout=30,
            )
        self.assertEqual(
            completed.returncode,
            0,
            f"stderr={completed.stderr!r}\nstdout_tail={completed.stdout[-2_000:]!r}",
        )
        records = [json.loads(line) for line in completed.stdout.splitlines()]
        message = next(record for record in records if record["type"] == "assistant.message")
        result = next(record for record in records if record["type"] == "thesis.sdk.result")
        self.assertEqual(message["data"]["content"], large_response)
        self.assertEqual(result["response"], large_response)


if __name__ == "__main__":
    unittest.main()

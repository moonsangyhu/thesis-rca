"""ChatGPT-subscription Codex CLI backend for isolated V2.3 inference."""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .copilot_cli import CopilotCLIError, CopilotCLIResponse


CODEX_PROVIDER = "codex-cli-chatgpt-subscription"
CODEX_MODEL_PROVENANCE = "command-bound-cli-json-does-not-emit-model"


class CodexCLIBackend:
    """Use an already logged-in Codex CLI in an empty, read-only workspace.

    The Codex subscription CLI reports token counts and a thread ID, but not a
    provider-reported model or monetary AIC.  The requested model is therefore
    command-bound and the legacy AIC fields are sealed as zero, never inferred.
    """

    provider = CODEX_PROVIDER
    model_provenance = CODEX_MODEL_PROVENANCE
    max_ai_credits = 30  # legacy caller reservation only; not subscription usage

    def __init__(
        self,
        *,
        model: str,
        executable: str = "codex",
        timeout_seconds: int = 300,
        subscription_authorized: bool = False,
        charge_observer: Callable[[dict], None] | None = None,
    ) -> None:
        resolved = shutil.which(executable)
        if not resolved:
            raise RuntimeError("Codex CLI executable not found")
        if not subscription_authorized:
            raise RuntimeError("Codex subscription execution is not authorized")
        if not isinstance(timeout_seconds, int) or timeout_seconds < 1:
            raise ValueError("Codex timeout must be positive")
        self.executable = resolved
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.subscription_authorized = subscription_authorized
        self.charge_observer = charge_observer

    def _billing_guard_passes(self) -> bool:
        return self.subscription_authorized

    def call(self, prompt: str, system_prompt: str, max_tokens: int) -> CopilotCLIResponse:
        if not self._billing_guard_passes():
            raise RuntimeError("Codex subscription execution is not authorized")
        if not isinstance(max_tokens, int) or max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        combined = (
            f"<SYSTEM_INSTRUCTIONS>\n{system_prompt}\n</SYSTEM_INSTRUCTIONS>\n\n"
            f"<USER_INPUT>\n{prompt}\n</USER_INPUT>\n\n"
            f"Keep the response within approximately {max_tokens} output tokens."
        )
        started = datetime.now(timezone.utc)
        started_monotonic = time.monotonic()
        attempt_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory(prefix="thesis-codex-cli-") as temp_dir:
            root = Path(temp_dir)
            command = [
                self.executable, "exec", "--ephemeral", "--json", "--sandbox", "read-only",
                "--skip-git-repo-check", "--model", self.model, "--cd", str(root), combined,
            ]
            try:
                completed = subprocess.run(
                    command, text=True, capture_output=True,
                    timeout=self.timeout_seconds, check=False, close_fds=False,
                )
            except subprocess.TimeoutExpired as exc:
                stdout = self._text(exc.stdout)
                stderr = self._text(exc.stderr)
                receipt = self._receipt(
                    stdout, stderr, attempt_id, started, started_monotonic, None, True, root.name,
                )
                self._observe(receipt)
                raise CopilotCLIError("Codex CLI timed out", receipt) from exc
        stdout, stderr = completed.stdout, completed.stderr
        receipt = self._receipt(
            stdout, stderr, attempt_id, started, started_monotonic, completed.returncode, False, root.name,
        )
        self._observe(receipt)
        if completed.returncode != 0:
            raise CopilotCLIError(
                f"Codex CLI failed with exit code {completed.returncode}", receipt
            )
        try:
            text, session_id, output_tokens = self._parse(stdout)
        except Exception as exc:
            raise CopilotCLIError("Codex CLI emitted an invalid isolated response", receipt) from exc
        ended = datetime.now(timezone.utc)
        return CopilotCLIResponse(
            text=text, model=self.model, session_id=session_id,
            output_tokens=output_tokens, ai_credits=0.0, premium_requests=0.0,
            started_at=started.isoformat(), ended_at=ended.isoformat(),
            latency_ms=round((time.monotonic() - started_monotonic) * 1000),
            exit_code=completed.returncode, cli_executable=self.executable,
            temporary_cwd_id=root.name,
        )

    def _observe(self, receipt: dict) -> None:
        if self.charge_observer is not None:
            self.charge_observer(receipt)

    @staticmethod
    def _text(value) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    def _receipt(
        self, stdout: str, stderr: str, attempt_id: str, started: datetime, started_monotonic: float,
        exit_code: int | None, timed_out: bool, temporary_cwd_id: str,
    ) -> dict:
        session_id = None
        output_tokens = None
        if not timed_out:
            try:
                _, session_id, output_tokens = self._parse(stdout)
            except ValueError:
                pass
        ended = datetime.now(timezone.utc)
        complete = (
            exit_code == 0 and session_id is not None and output_tokens is not None
        )
        return {
            "attempt_id": attempt_id,
            "requested_model": self.model,
            "actual_model": self.model if complete else None,
            "session_id": session_id,
            "output_tokens": output_tokens,
            "ai_credits": 0.0,
            "premium_requests": 0.0,
            "usage_metadata_complete": complete,
            "started_at": started.isoformat(), "ended_at": ended.isoformat(),
            "latency_ms": round((time.monotonic() - started_monotonic) * 1000),
            "exit_code": exit_code, "timed_out": timed_out,
            "cli_executable": self.executable, "temporary_cwd_id": temporary_cwd_id,
            "stdout_hash": hashlib.sha256(stdout.encode()).hexdigest(),
            "stderr_hash": hashlib.sha256(stderr.encode()).hexdigest(),
        }

    @staticmethod
    def _parse(stdout: str) -> tuple[str, str, int]:
        thread_id = None
        message = None
        output_tokens = None
        for line in stdout.splitlines():
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError("Codex event is not an object")
            event_type = record.get("type")
            if event_type == "thread.started":
                thread_id = record.get("thread_id")
            elif event_type == "item.completed":
                item = record.get("item")
                if not isinstance(item, dict) or item.get("type") != "agent_message":
                    raise ValueError("Codex tool or non-message event detected")
                if message is not None or not isinstance(item.get("text"), str):
                    raise ValueError("Codex message event is invalid")
                message = item["text"]
            elif event_type == "turn.completed":
                usage = record.get("usage")
                if not isinstance(usage, dict):
                    raise ValueError("Codex usage event is invalid")
                output_tokens = usage.get("output_tokens")
            elif event_type not in {"turn.started"}:
                raise ValueError("unexpected Codex event")
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("Codex thread identity is unavailable")
        if not isinstance(message, str) or not message.strip():
            raise ValueError("Codex final message is unavailable")
        if isinstance(output_tokens, bool) or not isinstance(output_tokens, int) or output_tokens < 0:
            raise ValueError("Codex output token count is unavailable")
        return message, thread_id, output_tokens

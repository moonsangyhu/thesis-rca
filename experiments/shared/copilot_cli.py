"""Tool-disabled GitHub Copilot CLI backend for reproducible RCA calls."""

from __future__ import annotations

import json
import hashlib
import os
import shutil
import subprocess
import tempfile
import time
import math
import uuid
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


DEFAULT_COPILOT_MODEL = "gpt-5.6-terra"
MIN_COPILOT_SESSION_AIC = 30


class CopilotCLIError(RuntimeError):
    """A post-subprocess failure carrying the already-journaled charge receipt."""

    def __init__(self, message: str, receipt: dict):
        super().__init__(message)
        self.receipt = dict(receipt)


@dataclass(frozen=True)
class CopilotCLIResponse:
    text: str
    model: str
    session_id: str
    output_tokens: int
    ai_credits: float
    premium_requests: float
    started_at: str = ""
    ended_at: str = ""
    latency_ms: int = 0
    exit_code: int = 0
    cli_executable: str = ""
    temporary_cwd_id: str = ""


class CopilotCLIBackend:
    """Invoke Copilot in prompt mode without repository or tool access."""

    def __init__(
        self,
        model: str = DEFAULT_COPILOT_MODEL,
        executable: str = "copilot",
        timeout_seconds: int = 180,
        max_ai_credits: int = MIN_COPILOT_SESSION_AIC,
        zero_overage_confirmed: bool | None = None,
        charge_observer: Callable[[dict], None] | None = None,
    ) -> None:
        resolved = shutil.which(executable)
        if not resolved:
            raise RuntimeError(f"Copilot CLI executable not found: {executable}")
        if (
            isinstance(max_ai_credits, bool)
            or not isinstance(max_ai_credits, int)
            or max_ai_credits < MIN_COPILOT_SESSION_AIC
        ):
            raise ValueError(
                "Copilot CLI session AIC cap must be an integer at least 30"
            )
        self.executable = resolved
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_ai_credits = max_ai_credits
        self.zero_overage_confirmed = zero_overage_confirmed
        self.charge_observer = charge_observer

    def _billing_guard_passes(self) -> bool:
        if self.zero_overage_confirmed is not None:
            return self.zero_overage_confirmed
        return os.environ.get("THESIS_COPILOT_ZERO_OVERAGE_CONFIRMED") == "1"

    @staticmethod
    def _compose_prompt(prompt: str, system_prompt: str, max_tokens: int) -> str:
        return (
            "Follow the system instructions below for this single inference task. "
            "Do not use tools, inspect files, or execute commands.\n\n"
            "<SYSTEM_INSTRUCTIONS>\n"
            f"{system_prompt}\n"
            "</SYSTEM_INSTRUCTIONS>\n\n"
            "<USER_INPUT>\n"
            f"{prompt}\n"
            "</USER_INPUT>\n\n"
            f"Keep the response within approximately {max_tokens} output tokens."
        )

    def call(self, prompt: str, system_prompt: str, max_tokens: int) -> CopilotCLIResponse:
        if not self._billing_guard_passes():
            raise RuntimeError(
                "Copilot inference blocked: zero-overage billing control is not confirmed"
            )
        combined = self._compose_prompt(prompt, system_prompt, max_tokens)
        command = [
            self.executable,
            "-p",
            combined,
            "--output-format",
            "json",
            "--no-custom-instructions",
            "--no-remote",
            "--no-remote-export",
            "--disable-builtin-mcps",
            "--available-tools=none",
            "--no-auto-update",
            "--max-ai-credits",
            str(self.max_ai_credits),
            "--model",
            self.model,
        ]
        started = datetime.now(timezone.utc)
        monotonic_started = time.monotonic()
        attempt_id = str(uuid.uuid4())
        with tempfile.TemporaryDirectory(prefix="thesis-copilot-inference-") as cwd:
            temporary_cwd_id = Path(cwd).name
            try:
                completed = subprocess.run(
                    command,
                    cwd=Path(cwd),
                    text=True,
                    capture_output=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except subprocess.TimeoutExpired as exc:
                ended = datetime.now(timezone.utc)
                stdout = self._as_text(exc.stdout)
                stderr = self._as_text(exc.stderr)
                receipt = {
                    **self._tolerant_usage(stdout),
                    "attempt_id": attempt_id,
                    "requested_model": self.model,
                    "started_at": started.isoformat(),
                    "ended_at": ended.isoformat(),
                    "latency_ms": round((time.monotonic() - monotonic_started) * 1000),
                    "exit_code": None,
                    "timed_out": True,
                    "cli_executable": self.executable,
                    "temporary_cwd_id": temporary_cwd_id,
                    "stdout_hash": hashlib.sha256(stdout.encode()).hexdigest(),
                    "stderr_hash": hashlib.sha256(stderr.encode()).hexdigest(),
                }
                self._observe_charge(receipt)
                raise CopilotCLIError("Copilot CLI timed out", receipt) from exc
        ended = datetime.now(timezone.utc)
        latency_ms = round((time.monotonic() - monotonic_started) * 1000)
        stdout = self._as_text(completed.stdout)
        stderr = self._as_text(completed.stderr)
        receipt = {
            **self._tolerant_usage(stdout),
            "attempt_id": attempt_id,
            "requested_model": self.model,
            "started_at": started.isoformat(),
            "ended_at": ended.isoformat(),
            "latency_ms": latency_ms,
            "exit_code": completed.returncode,
            "timed_out": False,
            "cli_executable": self.executable,
            "temporary_cwd_id": temporary_cwd_id,
            "stdout_hash": hashlib.sha256(stdout.encode()).hexdigest(),
            "stderr_hash": hashlib.sha256(stderr.encode()).hexdigest(),
        }
        self._observe_charge(receipt)
        if completed.returncode != 0:
            detail = (stderr or stdout).strip()
            raise CopilotCLIError(
                f"Copilot CLI failed with exit code {completed.returncode}: {detail}",
                receipt,
            )
        try:
            parsed = self._parse_jsonl(stdout)
        except Exception as exc:
            raise CopilotCLIError(str(exc), receipt) from exc
        return replace(
            parsed,
            started_at=started.isoformat(),
            ended_at=ended.isoformat(),
            latency_ms=latency_ms,
            exit_code=completed.returncode,
            cli_executable=self.executable,
            temporary_cwd_id=temporary_cwd_id,
        )

    @staticmethod
    def _as_text(value) -> str:
        if value is None:
            return ""
        if isinstance(value, bytes):
            return value.decode("utf-8", errors="replace")
        return str(value)

    def _observe_charge(self, receipt: dict) -> None:
        if self.charge_observer is not None:
            self.charge_observer(receipt)

    @staticmethod
    def _tolerant_usage(output: str) -> dict:
        """Extract whatever billing identity exists without ever raising."""
        actual_model = None
        session_id = None
        output_tokens = None
        ai_credits = None
        premium_requests = None
        for line in output.splitlines():
            try:
                event = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(event, dict):
                continue
            if event.get("type") == "assistant.message":
                data = event.get("data") or {}
                if not isinstance(data, dict):
                    continue
                actual_model = data.get("model") or actual_model
                output_tokens = data.get("outputTokens", output_tokens)
            elif event.get("type") == "result":
                session_id = event.get("sessionId") or session_id
            elif event.get("type") == "session.usage_checkpoint":
                data = event.get("data") or {}
                if not isinstance(data, dict):
                    continue
                try:
                    value = float(data.get("totalNanoAiu")) / 1_000_000_000
                    if math.isfinite(value) and value >= 0:
                        ai_credits = value
                except (TypeError, ValueError):
                    pass
                try:
                    value = float(data.get("totalPremiumRequests", 0.0))
                    if math.isfinite(value) and value >= 0:
                        premium_requests = value
                except (TypeError, ValueError):
                    pass
        return {
            "actual_model": actual_model if isinstance(actual_model, str) and actual_model else None,
            "session_id": session_id if isinstance(session_id, str) and session_id else None,
            "output_tokens": (
                output_tokens
                if isinstance(output_tokens, int) and not isinstance(output_tokens, bool)
                and output_tokens >= 0 else None
            ),
            "ai_credits": ai_credits,
            "premium_requests": premium_requests,
            "usage_metadata_complete": all(value is not None for value in (
                actual_model if isinstance(actual_model, str) and actual_model else None,
                session_id if isinstance(session_id, str) and session_id else None,
                output_tokens if isinstance(output_tokens, int)
                and not isinstance(output_tokens, bool) and output_tokens >= 0 else None,
                ai_credits, premium_requests,
            )),
        }

    def _parse_jsonl(self, output: str) -> CopilotCLIResponse:
        message: dict | None = None
        result: dict | None = None
        usage_checkpoint: dict | None = None
        for line in output.splitlines():
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Copilot CLI emitted invalid JSONL") from exc
            if not isinstance(event, dict):
                raise RuntimeError("Copilot CLI event must be a JSON object")
            if event.get("type") == "assistant.message":
                message = event.get("data") or {}
                if not isinstance(message, dict):
                    raise RuntimeError("Copilot assistant message data is invalid")
                if message.get("toolRequests"):
                    raise RuntimeError("Copilot tool request detected in inference response")
                event_model = str(message.get("model") or "")
                if event_model and event_model != self.model:
                    raise RuntimeError(
                        f"Copilot model drift detected: expected {self.model}, got {event_model}"
                    )
            elif event.get("type") == "result":
                result = event
            elif event.get("type") == "session.usage_checkpoint":
                usage_checkpoint = event.get("data") or {}
                if not isinstance(usage_checkpoint, dict):
                    raise RuntimeError("Copilot usage checkpoint data is invalid")
            else:
                event_type = str(event.get("type") or "").lower()
                if event_type.startswith("tool."):
                    raise RuntimeError("Copilot tool execution detected in inference response")
                if (
                    event_type.startswith(("mcp.", "remote."))
                    or "custom_instruction" in event_type
                ):
                    raise RuntimeError("Copilot MCP/remote/custom event detected")
                raise RuntimeError(f"unrecognized Copilot event type: {event_type or 'empty'}")

        if not message or not result or not usage_checkpoint:
            raise RuntimeError(
                "Copilot CLI response is missing message, result, or AIC usage metadata"
            )
        actual_model = str(message.get("model") or "")
        if actual_model != self.model:
            raise RuntimeError(
                f"Copilot model drift detected: expected {self.model}, got {actual_model or 'unknown'}"
            )
        session_id = str(result.get("sessionId") or "")
        if not session_id:
            raise RuntimeError("Copilot CLI response is missing session ID")
        nano_aiu = usage_checkpoint.get("totalNanoAiu")
        if nano_aiu is None:
            raise RuntimeError("Copilot CLI response is missing totalNanoAiu")
        try:
            ai_credits = float(nano_aiu) / 1_000_000_000
            premium_requests = float(usage_checkpoint.get("totalPremiumRequests") or 0.0)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("Copilot CLI usage metadata is invalid") from exc
        output_tokens = message.get("outputTokens")
        if (
            isinstance(output_tokens, bool) or not isinstance(output_tokens, int)
            or output_tokens < 0 or not math.isfinite(ai_credits)
            or not math.isfinite(premium_requests) or ai_credits < 0
            or premium_requests < 0
        ):
            raise RuntimeError("Copilot CLI usage metadata is invalid")
        content = message.get("content")
        if not isinstance(content, str) or not content.strip():
            raise RuntimeError("Copilot CLI response content is empty")
        return CopilotCLIResponse(
            text=content,
            model=actual_model,
            session_id=session_id,
            output_tokens=output_tokens,
            ai_credits=ai_credits,
            premium_requests=premium_requests,
        )

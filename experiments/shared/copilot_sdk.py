"""Official Copilot SDK backend with empty-mode isolation for V2.3."""

from __future__ import annotations

import hashlib
import json
import math
import os
import signal
import shutil
import subprocess
import tempfile
import time
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .copilot_cli import (
    DEFAULT_COPILOT_MODEL,
    MIN_COPILOT_SESSION_AIC,
    CopilotCLIError,
    CopilotCLIResponse,
)


SDK_RUNNER_SCHEMA = 1
SDK_REASONING_EFFORT = "medium"
ALLOWED_SDK_EVENT_TYPES = frozenset({
    "thesis.sdk.binding", "thesis.sdk.result",
    "session.start", "pending_messages.modified", "session.skills_loaded",
    "session.info", "system.message", "session.tools_updated", "user.message",
    "session.title_changed", "assistant.turn_start", "session.usage_info",
    "model.call_start", "assistant.usage", "assistant.reasoning",
    "assistant.reasoning_delta", "assistant.message_start",
    "assistant.message_delta", "assistant.message", "assistant.turn_end",
    "assistant.idle", "session.idle", "session.shutdown",
    "session.background_tasks_changed",
})


class CopilotSDKBackend:
    """Call company Copilot through the official SDK's fail-closed empty mode."""

    def __init__(
        self,
        model: str = DEFAULT_COPILOT_MODEL,
        executable: str = "copilot",
        node_executable: str = "node",
        timeout_seconds: int = 180,
        max_ai_credits: int = MIN_COPILOT_SESSION_AIC,
        zero_overage_confirmed: bool | None = None,
        billing_execution_authorized: bool | None = None,
        charge_observer: Callable[[dict], None] | None = None,
        pre_call_guard: Callable[[], object] | None = None,
        sdk_index: Path | None = None,
        runner_path: Path | None = None,
    ) -> None:
        resolved_cli = shutil.which(executable)
        resolved_node = shutil.which(node_executable)
        if not resolved_cli:
            raise RuntimeError(f"Copilot CLI executable not found: {executable}")
        if not resolved_node:
            raise RuntimeError(f"Node executable not found: {node_executable}")
        if (
            isinstance(max_ai_credits, bool)
            or not isinstance(max_ai_credits, int)
            or max_ai_credits < MIN_COPILOT_SESSION_AIC
        ):
            raise ValueError("Copilot SDK session AIC cap must be an integer at least 30")
        if zero_overage_confirmed is not None and billing_execution_authorized is not None:
            raise ValueError("billing authorization modes are mutually exclusive")
        if (
            zero_overage_confirmed is not None
            and not isinstance(zero_overage_confirmed, bool)
        ) or (
            billing_execution_authorized is not None
            and not isinstance(billing_execution_authorized, bool)
        ):
            raise ValueError("billing authorization state must be boolean")

        cli_loader = Path(resolved_cli).resolve()
        default_sdk = (
            cli_loader.parent
            / "node_modules"
            / "@github"
            / "copilot-darwin-arm64"
            / "copilot-sdk"
            / "index.js"
        )
        self.sdk_index = (sdk_index or default_sdk).resolve(strict=True)
        self.runner_path = (
            runner_path or Path(__file__).with_name("copilot_sdk_runner.mjs")
        ).resolve(strict=True)
        self.sdk_sha256 = self._file_sha256(self.sdk_index)
        self.runner_sha256 = self._file_sha256(self.runner_path)
        self.executable = resolved_cli
        self.node_executable = resolved_node
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_ai_credits = max_ai_credits
        self.zero_overage_confirmed = zero_overage_confirmed
        self.billing_execution_authorized = billing_execution_authorized
        self.charge_observer = charge_observer
        self.pre_call_guard = pre_call_guard

    @staticmethod
    def _file_sha256(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def _billing_guard_passes(self) -> bool:
        if self.billing_execution_authorized is not None:
            return self.billing_execution_authorized is True
        if self.zero_overage_confirmed is not None:
            return self.zero_overage_confirmed
        return os.environ.get("THESIS_COPILOT_ZERO_OVERAGE_CONFIRMED") == "1"

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

    def call(self, prompt: str, system_prompt: str, max_tokens: int) -> CopilotCLIResponse:
        if not self._billing_guard_passes():
            raise RuntimeError("Copilot inference blocked: billing execution is not authorized")
        if self.pre_call_guard is not None:
            self.pre_call_guard()
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        if self._file_sha256(self.sdk_index) != self.sdk_sha256:
            raise RuntimeError("Copilot SDK changed after backend initialization")
        if self._file_sha256(self.runner_path) != self.runner_sha256:
            raise RuntimeError("Copilot SDK runner changed after backend initialization")

        started = datetime.now(timezone.utc)
        monotonic_started = time.monotonic()
        attempt_id = str(uuid.uuid4())
        request_nonce = str(uuid.uuid4())
        with tempfile.TemporaryDirectory(prefix="thesis-copilot-sdk-") as temp_dir:
            temp_root = Path(temp_dir)
            base_directory = temp_root / "copilot-home"
            working_directory = temp_root / "working"
            base_directory.mkdir(mode=0o700)
            working_directory.mkdir(mode=0o700)
            request = {
                "schema_version": SDK_RUNNER_SCHEMA,
                "base_directory": str(base_directory),
                "working_directory": str(working_directory),
                "model": self.model,
                "reasoning_effort": SDK_REASONING_EFFORT,
                "max_output_tokens": max_tokens,
                "max_ai_credits": self.max_ai_credits,
                "timeout_ms": self.timeout_seconds * 1000,
                "request_nonce": request_nonce,
                "system_prompt": system_prompt,
                "user_prompt": prompt,
                "system_prompt_sha256": hashlib.sha256(system_prompt.encode()).hexdigest(),
                "user_prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            }
            command = [
                self.node_executable,
                str(self.runner_path),
                str(self.sdk_index),
            ]
            completed, timed_out = self._run_runner(
                command,
                json.dumps(request, ensure_ascii=False, separators=(",", ":")),
                working_directory,
                {**os.environ, "COPILOT_HOME": str(base_directory)},
            )
            if timed_out:
                ended = datetime.now(timezone.utc)
                stdout = self._as_text(completed.stdout)
                stderr = self._as_text(completed.stderr)
                receipt = self._receipt(
                    stdout, attempt_id, started, ended,
                    round((time.monotonic() - monotonic_started) * 1000),
                    None, True, temp_root.name, stderr,
                )
                self._observe_charge(receipt)
                raise CopilotCLIError("Copilot SDK timed out", receipt)

        ended = datetime.now(timezone.utc)
        latency_ms = round((time.monotonic() - monotonic_started) * 1000)
        stdout = self._as_text(completed.stdout)
        stderr = self._as_text(completed.stderr)
        receipt = self._receipt(
            stdout, attempt_id, started, ended, latency_ms,
            completed.returncode, False, temp_root.name, stderr,
        )
        self._observe_charge(receipt)
        if completed.returncode != 0:
            detail = (stderr or stdout).strip()[-2000:]
            raise CopilotCLIError(
                f"Copilot SDK failed with exit code {completed.returncode}: {detail}",
                receipt,
            )
        try:
            parsed = self._parse_output(
                stdout,
                expected_prompt=prompt,
                expected_system_prompt=system_prompt,
                expected_max_tokens=max_tokens,
                expected_nonce=request_nonce,
            )
        except Exception as exc:
            raise CopilotCLIError(str(exc), receipt) from exc
        return replace(
            parsed,
            started_at=started.isoformat(),
            ended_at=ended.isoformat(),
            latency_ms=latency_ms,
            exit_code=completed.returncode,
            cli_executable=f"{self.node_executable}:{self.runner_path}#{self.runner_sha256}",
            temporary_cwd_id=temp_root.name,
        )

    def _receipt(
        self, stdout: str, attempt_id: str, started: datetime, ended: datetime,
        latency_ms: int, exit_code: int | None, timed_out: bool,
        temporary_cwd_id: str, stderr: str,
    ) -> dict:
        return {
            **self._tolerant_usage(stdout),
            "attempt_id": attempt_id,
            "requested_model": self.model,
            "started_at": started.isoformat(),
            "ended_at": ended.isoformat(),
            "latency_ms": latency_ms,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "cli_executable": (
                f"{self.node_executable}:{self.runner_path}#{self.runner_sha256}"
            ),
            "temporary_cwd_id": temporary_cwd_id,
            "stdout_hash": hashlib.sha256(stdout.encode()).hexdigest(),
            "stderr_hash": hashlib.sha256(stderr.encode()).hexdigest(),
        }

    def _run_runner(
        self, command: list[str], request: str, cwd: Path, env: dict[str, str],
    ) -> tuple[subprocess.CompletedProcess, bool]:
        """Run Node and its Copilot child in one killable process group."""
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=cwd,
            env=env,
            text=True,
            start_new_session=True,
        )
        try:
            stdout, stderr = process.communicate(
                input=request, timeout=self.timeout_seconds + 30
            )
            return subprocess.CompletedProcess(
                command, process.returncode, stdout, stderr
            ), False
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
            return subprocess.CompletedProcess(command, None, stdout, stderr), True

    @staticmethod
    def _json_lines(output: str) -> list[dict]:
        records = []
        for line in output.splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Copilot SDK emitted malformed JSONL") from exc
            if not isinstance(record, dict):
                raise RuntimeError("Copilot SDK event must be an object")
            records.append(record)
        return records

    @classmethod
    def _tolerant_usage(cls, output: str) -> dict:
        usage = None
        session_id = None
        for line in output.splitlines():
            try:
                record = json.loads(line)
            except (json.JSONDecodeError, TypeError):
                continue
            if not isinstance(record, dict):
                continue
            if record.get("type") == "assistant.usage" and isinstance(record.get("data"), dict):
                usage = record["data"]
            elif record.get("type") == "thesis.sdk.binding":
                session_id = record.get("session_id")
        copilot_usage = usage.get("copilotUsage") if isinstance(usage, dict) else None
        nano_aiu = copilot_usage.get("totalNanoAiu") if isinstance(copilot_usage, dict) else None
        ai_credits = (
            float(nano_aiu) / 1_000_000_000
            if isinstance(nano_aiu, (int, float)) and not isinstance(nano_aiu, bool)
            and math.isfinite(nano_aiu) and nano_aiu >= 0
            else None
        )
        premium = usage.get("cost") if isinstance(usage, dict) else None
        output_tokens = usage.get("outputTokens") if isinstance(usage, dict) else None
        actual_model = usage.get("model") if isinstance(usage, dict) else None
        complete = (
            isinstance(session_id, str) and bool(session_id)
            and isinstance(actual_model, str) and bool(actual_model)
            and isinstance(output_tokens, int) and not isinstance(output_tokens, bool)
            and output_tokens >= 0
            and ai_credits is not None
            and isinstance(premium, (int, float)) and not isinstance(premium, bool)
            and math.isfinite(premium) and premium >= 0
        )
        return {
            "actual_model": actual_model,
            "session_id": session_id,
            "output_tokens": output_tokens,
            "ai_credits": ai_credits,
            "premium_requests": float(premium) if complete else None,
            "usage_metadata_complete": complete,
        }

    def _parse_output(
        self, output: str, *, expected_prompt: str, expected_system_prompt: str,
        expected_max_tokens: int, expected_nonce: str,
    ) -> CopilotCLIResponse:
        records = self._json_lines(output)
        bindings = [r for r in records if r.get("type") == "thesis.sdk.binding"]
        results = [r for r in records if r.get("type") == "thesis.sdk.result"]
        errors = [r for r in records if r.get("type") == "thesis.sdk.error"]
        skills = [r for r in records if r.get("type") == "session.skills_loaded"]
        tools = [r for r in records if r.get("type") == "session.tools_updated"]
        usages = [r for r in records if r.get("type") == "assistant.usage"]
        messages = [r for r in records if r.get("type") == "assistant.message"]
        user_messages = [r for r in records if r.get("type") == "user.message"]
        if errors or any(len(items) != 1 for items in (bindings, results, skills, tools, usages, messages, user_messages)):
            raise RuntimeError("Copilot SDK response lifecycle is incomplete or duplicated")
        for record in records:
            event_type = record.get("type")
            if event_type not in ALLOWED_SDK_EVENT_TYPES:
                raise RuntimeError("Copilot SDK emitted an unapproved capability event")

        binding = bindings[0]
        session_id = binding.get("session_id")
        try:
            parsed_session_id = uuid.UUID(session_id)
        except (ValueError, TypeError, AttributeError) as exc:
            raise RuntimeError("Copilot SDK session ID is invalid") from exc
        expected_binding = {
            "type": "thesis.sdk.binding",
            "schema_version": SDK_RUNNER_SCHEMA,
            "session_id": session_id,
            "mode": "empty",
            "model": self.model,
            "reasoning_effort": SDK_REASONING_EFFORT,
            "available_tools": [],
            "excluded_tools": [],
            "tools": [],
            "enable_skills": False,
            "enable_config_discovery": False,
            "skip_custom_instructions": True,
            "mcp_servers": [],
            "custom_agents": [],
            "remote_session": "off",
            "max_output_tokens": expected_max_tokens,
            "max_ai_credits": self.max_ai_credits,
            "request_nonce": expected_nonce,
            "system_prompt_sha256": hashlib.sha256(expected_system_prompt.encode()).hexdigest(),
            "user_prompt_sha256": hashlib.sha256(expected_prompt.encode()).hexdigest(),
        }
        if binding != expected_binding or parsed_session_id.version != 4:
            raise RuntimeError("Copilot SDK empty-mode binding is invalid")

        skills_data = skills[0].get("data")
        tools_data = tools[0].get("data")
        self._validate_ephemeral_root(skills[0], "session.skills_loaded")
        self._validate_ephemeral_root(tools[0], "session.tools_updated")
        self._validate_ephemeral_root(usages[0], "assistant.usage")
        if not isinstance(skills_data, dict) or skills_data != {"skills": []}:
            raise RuntimeError("Copilot SDK loaded skills in empty mode")
        if not isinstance(tools_data, dict) or tools_data != {"model": self.model}:
            raise RuntimeError("Copilot SDK tool metadata drifted from the pinned model")

        usage = usages[0].get("data")
        if not isinstance(usage, dict):
            raise RuntimeError("Copilot SDK usage metadata is invalid")
        copilot_usage = usage.get("copilotUsage")
        nano_aiu = copilot_usage.get("totalNanoAiu") if isinstance(copilot_usage, dict) else None
        output_tokens = usage.get("outputTokens")
        premium = usage.get("cost")
        if (
            usage.get("model") != self.model
            or usage.get("availableToolCount") != 0
            or usage.get("numToolCalls") != 0
            or not isinstance(output_tokens, int) or isinstance(output_tokens, bool)
            or output_tokens < 0
            or not isinstance(nano_aiu, (int, float)) or isinstance(nano_aiu, bool)
            or not math.isfinite(nano_aiu) or nano_aiu < 0
            or not isinstance(premium, (int, float)) or isinstance(premium, bool)
            or not math.isfinite(premium) or premium < 0
        ):
            raise RuntimeError("Copilot SDK usage metadata is invalid")

        result = results[0]
        response_text = result.get("response")
        message_data = messages[0].get("data")
        user_data = user_messages[0].get("data")
        if (
            set(result) != {"type", "schema_version", "session_id", "request_nonce", "response", "metrics"}
            or result.get("schema_version") != SDK_RUNNER_SCHEMA
            or result.get("session_id") != session_id
            or result.get("request_nonce") != expected_nonce
            or not isinstance(response_text, str) or not response_text
            or not isinstance(message_data, dict)
            or message_data.get("content") != response_text
            or message_data.get("toolRequests") not in (None, [])
            or not isinstance(user_data, dict)
            or user_data.get("content") != expected_prompt
            or user_data.get("attachments") != []
        ):
            raise RuntimeError("Copilot SDK prompt or response binding is invalid")

        metrics = result.get("metrics")
        model_metrics = metrics.get("modelMetrics") if isinstance(metrics, dict) else None
        metric = model_metrics.get(self.model) if isinstance(model_metrics, dict) else None
        requests = metric.get("requests") if isinstance(metric, dict) else None
        metric_usage = metric.get("usage") if isinstance(metric, dict) else None
        ai_credits = float(nano_aiu) / 1_000_000_000
        if (
            not isinstance(metrics, dict)
            or metrics.get("currentModel") != self.model
            or metrics.get("totalUserRequests") != 1
            or set(model_metrics or {}) != {self.model}
            or not isinstance(requests, dict) or requests.get("count") != 1
            or requests.get("cost") != premium
            or not isinstance(metric_usage, dict)
            or metric_usage.get("outputTokens") != output_tokens
            or metrics.get("totalNanoAiu") != nano_aiu
            or metrics.get("totalPremiumRequestCost") != premium
        ):
            raise RuntimeError("Copilot SDK cumulative usage does not match call usage")

        return CopilotCLIResponse(
            text=response_text,
            model=self.model,
            session_id=session_id,
            output_tokens=output_tokens,
            ai_credits=ai_credits,
            premium_requests=float(premium),
        )

    @staticmethod
    def _validate_ephemeral_root(record: dict, event_type: str) -> None:
        if set(record) != {
            "id", "timestamp", "parentId", "ephemeral", "type", "data",
        }:
            raise RuntimeError(f"Copilot SDK {event_type} envelope is invalid")
        try:
            event_id = uuid.UUID(record["id"])
            parent_raw = record["parentId"]
            parent_id = None if parent_raw is None else uuid.UUID(parent_raw)
            timestamp = datetime.fromisoformat(record["timestamp"])
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            raise RuntimeError(f"Copilot SDK {event_type} envelope is invalid") from exc
        if (
            record["type"] != event_type
            or event_id.version != 4 or str(event_id) != record["id"].lower()
            or (
                parent_raw is not None
                and (
                    not isinstance(parent_raw, str) or parent_id is None
                    or parent_id.version != 4 or str(parent_id) != parent_raw.lower()
                )
            )
            or timestamp.tzinfo is None
            or record["ephemeral"] is not True
            or not isinstance(record["data"], dict)
        ):
            raise RuntimeError(f"Copilot SDK {event_type} envelope is invalid")

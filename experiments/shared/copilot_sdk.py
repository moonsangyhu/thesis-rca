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
import threading
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from .copilot_cli import (
    DEFAULT_COPILOT_MODEL,
    MIN_COPILOT_SESSION_AIC,
    RETRYABLE_MALFORMED_JSONL_FAILURE_CODE,
    RETRYABLE_ZERO_USAGE_AUTH_FAILURE_CODE,
    CopilotCLIError,
    CopilotCLIResponse,
)


SDK_RUNNER_SCHEMA = 1
SDK_REASONING_EFFORT = "medium"
SDK_COPILOT_VERSION = "1.0.77"
SDK_SESSION_EVENT_VERSION = 1
# The SDK receives the same 180-second inference deadline.  The Python parent
# has a small, fixed grace period to receive the runner's final event/usage
# envelope.  A separate watchdog is intentional: `communicate(timeout=...)`
# is not the only liveness boundary, because a runner can retain pipe handles
# while its Node/CLI process tree is wedged.
SDK_RUNNER_GRACE_SECONDS = 30
SDK_RUNNER_REAP_SECONDS = 15
ZERO_USAGE_AUTH_MESSAGE = (
    "Execution failed: Error: Session was not created with authentication info "
    "or custom provider"
)
ZERO_USAGE_AUTH_EVENT_TYPES = frozenset({
    "session.start", "thesis.sdk.binding", "pending_messages.modified", "session.error",
    "thesis.sdk.error", "assistant.idle", "session.idle", "session.shutdown",
    "session.background_tasks_changed",
})
ALLOWED_SDK_EVENT_TYPES = frozenset({
    "thesis.sdk.binding", "thesis.sdk.result",
    "session.start", "pending_messages.modified", "session.skills_loaded",
    "session.info", "system.message", "session.tools_updated", "user.message",
    "session.title_changed", "assistant.turn_start", "session.usage_info",
    "session.usage_checkpoint",
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
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, int)
            or timeout_seconds < 1
        ):
            raise ValueError("Copilot SDK timeout must be a positive integer")
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
            retryable_zero_usage_authentication = (
                self._is_retryable_zero_usage_auth_failure(
                    stdout,
                    expected_prompt=prompt,
                    expected_system_prompt=system_prompt,
                    expected_max_tokens=max_tokens,
                    expected_nonce=request_nonce,
                    expected_working_directory=working_directory,
                )
            )
            detail = (stderr or stdout).strip()[-2000:]
            raise CopilotCLIError(
                f"Copilot SDK failed with exit code {completed.returncode}: {detail}",
                receipt,
                retryable_zero_usage_authentication=(
                    retryable_zero_usage_authentication
                ),
                failure_code=(
                    RETRYABLE_ZERO_USAGE_AUTH_FAILURE_CODE
                    if retryable_zero_usage_authentication else None
                ),
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
            # The Node SDK has occasionally truncated an otherwise charged
            # JSONL response at its 64KiB output boundary.  This has no tool
            # side effects in empty mode; retrying once is safe only when the
            # durable receipt proves complete, model-bound usage.
            malformed_jsonl = str(exc) == "Copilot SDK emitted malformed JSONL"
            raise CopilotCLIError(
                str(exc), receipt,
                failure_code=(
                    RETRYABLE_MALFORMED_JSONL_FAILURE_CODE
                    if malformed_jsonl else None
                ),
            ) from exc
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
        """Run Node and its Copilot child in one killable process group.

        The timer is a second, independent liveness boundary.  In particular,
        it still kills the whole process group if `communicate()` is delayed by
        retained pipe descriptors after a child-side SDK failure.
        """
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
        watchdog_expired = threading.Event()
        watchdog_lock = threading.Lock()
        watchdog_closed = False

        def expire_watchdog() -> None:
            with watchdog_lock:
                if watchdog_closed:
                    return
                watchdog_expired.set()
            self._kill_process_group(process.pid)

        watchdog = threading.Timer(
            self.timeout_seconds + SDK_RUNNER_GRACE_SECONDS,
            expire_watchdog,
        )
        watchdog.daemon = True
        watchdog.start()

        def close_watchdog() -> bool:
            nonlocal watchdog_closed
            with watchdog_lock:
                watchdog_closed = True
                expired = watchdog_expired.is_set()
            watchdog.cancel()
            return expired

        try:
            stdout, stderr = process.communicate(
                input=request,
                timeout=self.timeout_seconds + SDK_RUNNER_GRACE_SECONDS,
            )
            if close_watchdog():
                # A process can close its inherited stdout/stderr descriptors
                # before its parent has been reaped.  Preserve the watchdog
                # outcome and wait only for the fixed reap boundary.
                self._kill_process_group(process.pid)
                try:
                    process.wait(timeout=SDK_RUNNER_REAP_SECONDS)
                except subprocess.TimeoutExpired:
                    self._kill_process_group(process.pid)
            return subprocess.CompletedProcess(
                command, process.returncode, stdout, stderr
            ), watchdog_expired.is_set()
        except subprocess.TimeoutExpired:
            close_watchdog()
            watchdog_expired.set()
            self._kill_process_group(process.pid)
            try:
                stdout, stderr = process.communicate(timeout=SDK_RUNNER_REAP_SECONDS)
            except subprocess.TimeoutExpired as exc:
                # The group was already killed.  Do not let an inherited pipe
                # descriptor hold the fault-injection/recovery state forever.
                self._kill_process_group(process.pid)
                stdout = self._as_text(exc.output)
                stderr = self._as_text(exc.stderr)
                for stream in (process.stdin, process.stdout, process.stderr):
                    try:
                        if stream is not None:
                            stream.close()
                    except OSError:
                        pass
            return subprocess.CompletedProcess(command, None, stdout, stderr), True
        except BaseException:
            close_watchdog()
            self._kill_process_group(process.pid)
            try:
                process.communicate(timeout=SDK_RUNNER_REAP_SECONDS)
            except subprocess.TimeoutExpired:
                self._kill_process_group(process.pid)
            raise
        finally:
            close_watchdog()

    @staticmethod
    def _kill_process_group(pid: int) -> None:
        try:
            os.killpg(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        except PermissionError:
            # The production runner is created as a new session, so killpg is
            # the normal process-tree cleanup path.  Some host test/process
            # configurations can nevertheless reject a group signal; never
            # leave the directly owned runner alive in that case.
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

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
        if not complete and cls._has_exact_zero_usage_auth_shutdown(output):
            return {
                "actual_model": None,
                "session_id": session_id,
                "output_tokens": 0,
                "ai_credits": 0.0,
                "premium_requests": 0.0,
                "usage_metadata_complete": True,
            }
        return {
            "actual_model": actual_model,
            "session_id": session_id,
            "output_tokens": output_tokens,
            "ai_credits": ai_credits,
            "premium_requests": float(premium) if complete else None,
            "usage_metadata_complete": complete,
        }

    @classmethod
    def _has_exact_zero_usage_auth_shutdown(cls, output: str) -> bool:
        """Recognize only the SDK's sealed pre-inference authentication failure."""
        try:
            records = cls._json_lines(output)
        except RuntimeError:
            return False
        errors = [r for r in records if r.get("type") == "session.error"]
        runner_errors = [r for r in records if r.get("type") == "thesis.sdk.error"]
        shutdowns = [r for r in records if r.get("type") == "session.shutdown"]
        bindings = [r for r in records if r.get("type") == "thesis.sdk.binding"]
        if any(len(items) != 1 for items in (errors, runner_errors, shutdowns, bindings)):
            return False
        if any(r.get("type") not in ZERO_USAGE_AUTH_EVENT_TYPES for r in records):
            return False

        event_types = [r.get("type") for r in records]
        required_order = (
            "session.start", "thesis.sdk.binding", "session.error", "thesis.sdk.error",
            "session.shutdown",
        )
        if any(event_types.count(event_type) != 1 for event_type in required_order):
            return False
        positions = [event_types.index(event_type) for event_type in required_order]
        if positions != sorted(positions):
            return False
        optional_order = (
            "pending_messages.modified", "assistant.idle", "session.idle",
            "session.background_tasks_changed",
        )
        if any(event_types.count(event_type) > 1 for event_type in optional_order):
            return False
        allowed_sequences = (
            ("session.start", "thesis.sdk.binding", "pending_messages.modified", "session.error",
             "thesis.sdk.error", "assistant.idle", "session.idle",
             "session.shutdown", "session.background_tasks_changed"),
        )
        full_sequence = allowed_sequences[0]
        projected = tuple(event_type for event_type in full_sequence if event_type in event_types)
        if tuple(event_types) != projected:
            return False

        binding = bindings[0]
        if not cls._valid_zero_usage_binding_shape(binding):
            return False
        start = next(r for r in records if r.get("type") == "session.start")
        if not cls._valid_zero_usage_start(start, binding):
            return False

        error = errors[0]
        runner_error = runner_errors[0]
        shutdown = shutdowns[0]
        if not cls._valid_event_envelope(error, "session.error", ephemeral=False):
            return False
        if not cls._valid_event_envelope(shutdown, "session.shutdown", ephemeral=False):
            return False
        if error["data"] != {
            "errorType": "authentication", "message": ZERO_USAGE_AUTH_MESSAGE,
        }:
            return False
        if (
            set(runner_error) != {"type", "schema_version", "message"}
            or runner_error.get("type") != "thesis.sdk.error"
            or not isinstance(runner_error.get("schema_version"), int)
            or isinstance(runner_error.get("schema_version"), bool)
            or runner_error["schema_version"] != SDK_RUNNER_SCHEMA
            or runner_error.get("message") != ZERO_USAGE_AUTH_MESSAGE
        ):
            return False
        if shutdown.get("parentId") != error.get("id"):
            return False
        pending = next(
            (r for r in records if r.get("type") == "pending_messages.modified"),
            None,
        )
        assistant_idle = next(
            (r for r in records if r.get("type") == "assistant.idle"), None,
        )
        session_idle = next(
            (r for r in records if r.get("type") == "session.idle"), None,
        )
        background = next(
            (r for r in records
             if r.get("type") == "session.background_tasks_changed"),
            None,
        )
        for record, event_type, expected_parent in (
            (pending, "pending_messages.modified", error.get("parentId")),
            (assistant_idle, "assistant.idle", error.get("id")),
            (session_idle, "session.idle", error.get("id")),
            (background, "session.background_tasks_changed", shutdown.get("id")),
        ):
            if record is not None and (
                not cls._valid_event_envelope(
                    record, event_type, ephemeral=True,
                )
                or record.get("data") != {}
                or record.get("parentId") != expected_parent
            ):
                return False
        data = shutdown["data"]
        code_changes = data.get("codeChanges") if isinstance(data, dict) else None
        numeric_zero_fields = (
            "totalPremiumRequests", "totalNanoAiu", "totalApiDurationMs",
            "systemTokens", "conversationTokens", "toolDefinitionsTokens",
        )
        return bool(
            isinstance(data, dict)
            and set(data) == {
                "shutdownType", "totalPremiumRequests", "totalNanoAiu",
                "totalApiDurationMs", "sessionStartTime", "codeChanges",
                "modelMetrics", "currentTokens", "systemTokens",
                "conversationTokens", "toolDefinitionsTokens",
            }
            and data["shutdownType"] == "routine"
            and all(
                isinstance(data[field], (int, float))
                and not isinstance(data[field], bool)
                and math.isfinite(data[field])
                and data[field] == 0
                for field in numeric_zero_fields
            )
            and isinstance(data["sessionStartTime"], int)
            and not isinstance(data["sessionStartTime"], bool)
            and data["sessionStartTime"] > 0
            and isinstance(data["currentTokens"], int)
            and not isinstance(data["currentTokens"], bool)
            and data["currentTokens"] >= 0
            and isinstance(code_changes, dict)
            and set(code_changes) == {
                "linesAdded", "linesRemoved", "filesModified",
            }
            and all(
                isinstance(code_changes[field], int)
                and not isinstance(code_changes[field], bool)
                and code_changes[field] == 0
                for field in ("linesAdded", "linesRemoved")
            )
            and code_changes["filesModified"] == []
            and data["modelMetrics"] == {}
        )

    @staticmethod
    def _valid_zero_usage_binding_shape(binding: dict) -> bool:
        expected_keys = {
            "type", "schema_version", "session_id", "mode", "model",
            "reasoning_effort", "available_tools", "excluded_tools", "tools",
            "enable_skills", "enable_config_discovery",
            "skip_custom_instructions", "mcp_servers", "custom_agents",
            "remote_session", "max_output_tokens", "max_ai_credits",
            "request_nonce", "system_prompt_sha256", "user_prompt_sha256",
        }
        try:
            session_id = uuid.UUID(binding["session_id"])
            request_nonce = uuid.UUID(binding["request_nonce"])
        except (ValueError, TypeError, AttributeError, KeyError):
            return False
        hashes = (binding.get("system_prompt_sha256"), binding.get("user_prompt_sha256"))
        return bool(
            set(binding) == expected_keys
            and binding["type"] == "thesis.sdk.binding"
            and isinstance(binding["schema_version"], int)
            and not isinstance(binding["schema_version"], bool)
            and binding["schema_version"] == SDK_RUNNER_SCHEMA
            and session_id.version == 4
            and str(session_id) == binding["session_id"].lower()
            and request_nonce.version == 4
            and str(request_nonce) == binding["request_nonce"].lower()
            and binding["mode"] == "empty"
            and isinstance(binding["model"], str) and bool(binding["model"])
            and binding["reasoning_effort"] == SDK_REASONING_EFFORT
            and binding["available_tools"] == []
            and binding["excluded_tools"] == []
            and binding["tools"] == []
            and binding["enable_skills"] is False
            and binding["enable_config_discovery"] is False
            and binding["skip_custom_instructions"] is True
            and binding["mcp_servers"] == []
            and binding["custom_agents"] == []
            and binding["remote_session"] == "off"
            and isinstance(binding["max_output_tokens"], int)
            and not isinstance(binding["max_output_tokens"], bool)
            and binding["max_output_tokens"] > 0
            and isinstance(binding["max_ai_credits"], int)
            and not isinstance(binding["max_ai_credits"], bool)
            and binding["max_ai_credits"] >= MIN_COPILOT_SESSION_AIC
            and all(
                isinstance(value, str) and len(value) == 64
                and all(character in "0123456789abcdef" for character in value)
                for value in hashes
            )
        )

    @staticmethod
    def _valid_zero_usage_start(start: dict, binding: dict) -> bool:
        if not CopilotSDKBackend._valid_event_envelope(
            start, "session.start", ephemeral=False, parent_nullable=True,
        ):
            return False
        data = start["data"]
        expected_data_keys = {
            "alreadyInUse", "context", "contextTier", "copilotVersion",
            "producer", "reasoningEffort", "remoteSteerable",
            "selectedModel", "sessionId", "sessionLimits", "startTime",
            "version",
        }
        context = data.get("context") if isinstance(data, dict) else None
        limits = data.get("sessionLimits") if isinstance(data, dict) else None
        try:
            start_time = datetime.fromisoformat(data["startTime"])
            session_id = uuid.UUID(data["sessionId"])
        except (ValueError, TypeError, AttributeError, KeyError):
            return False
        return bool(
            start.get("parentId") is None
            and isinstance(data, dict) and set(data) == expected_data_keys
            and data["alreadyInUse"] is False
            and isinstance(context, dict)
            and set(context) == {"cwd"}
            and isinstance(context["cwd"], str) and bool(context["cwd"])
            and data["contextTier"] is None
            and data["copilotVersion"] == SDK_COPILOT_VERSION
            and data["producer"] == "copilot-agent"
            and data["reasoningEffort"] == SDK_REASONING_EFFORT
            and data["remoteSteerable"] is False
            and data["selectedModel"] == binding["model"]
            and session_id.version == 4
            and str(session_id) == data["sessionId"].lower()
            and data["sessionId"] == binding["session_id"]
            and isinstance(limits, dict)
            and set(limits) == {"maxAiCredits"}
            and isinstance(limits["maxAiCredits"], int)
            and not isinstance(limits["maxAiCredits"], bool)
            and limits["maxAiCredits"] == binding["max_ai_credits"]
            and start_time.tzinfo is not None
            and isinstance(data["version"], int)
            and not isinstance(data["version"], bool)
            and data["version"] == SDK_SESSION_EVENT_VERSION
        )

    @staticmethod
    def _valid_event_envelope(
        record: dict, event_type: str, *, ephemeral: bool,
        parent_nullable: bool = False,
    ) -> bool:
        expected_keys = {"id", "timestamp", "parentId", "type", "data"}
        if ephemeral:
            expected_keys.add("ephemeral")
        if set(record) != expected_keys or record.get("type") != event_type:
            return False
        try:
            event_id = uuid.UUID(record["id"])
            parent_raw = record["parentId"]
            parent_id = None if parent_raw is None else uuid.UUID(parent_raw)
            timestamp = datetime.fromisoformat(record["timestamp"])
        except (ValueError, TypeError, AttributeError, KeyError):
            return False
        return bool(
            event_id.version == 4 and str(event_id) == record["id"].lower()
            and (
                parent_nullable and parent_raw is None
                or parent_id is not None and parent_id.version == 4
                and str(parent_id) == parent_raw.lower()
            )
            and timestamp.tzinfo is not None
            and isinstance(record["data"], dict)
            and (not ephemeral or record.get("ephemeral") is True)
        )

    def _is_retryable_zero_usage_auth_failure(
        self, output: str, *, expected_prompt: str,
        expected_system_prompt: str, expected_max_tokens: int,
        expected_nonce: str, expected_working_directory: Path,
    ) -> bool:
        if not self._has_exact_zero_usage_auth_shutdown(output):
            return False
        try:
            records = self._json_lines(output)
            binding = next(
                r for r in records if r.get("type") == "thesis.sdk.binding"
            )
            session_id = binding.get("session_id")
            parsed_session_id = uuid.UUID(session_id)
        except (RuntimeError, StopIteration, ValueError, TypeError, AttributeError):
            return False
        start = next(r for r in records if r.get("type") == "session.start")
        return bool(
            parsed_session_id.version == 4
            and start["data"]["context"]["cwd"]
            == str(expected_working_directory)
            and binding == {
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
                "system_prompt_sha256": hashlib.sha256(
                    expected_system_prompt.encode()
                ).hexdigest(),
                "user_prompt_sha256": hashlib.sha256(
                    expected_prompt.encode()
                ).hexdigest(),
            }
        )

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
        checkpoints = [
            r for r in records if r.get("type") == "session.usage_checkpoint"
        ]
        if errors or any(len(items) != 1 for items in (bindings, results, skills, tools, usages, messages, user_messages)):
            raise RuntimeError("Copilot SDK response lifecycle is incomplete or duplicated")
        if len(checkpoints) > 1:
            raise RuntimeError("Copilot SDK usage checkpoint is duplicated")
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
        total_user_requests = metrics.get("totalUserRequests") if isinstance(metrics, dict) else None
        total_nano_aiu = metrics.get("totalNanoAiu") if isinstance(metrics, dict) else None
        total_premium = metrics.get("totalPremiumRequestCost") if isinstance(metrics, dict) else None
        request_count = requests.get("count") if isinstance(requests, dict) else None
        request_cost = requests.get("cost") if isinstance(requests, dict) else None
        metric_output_tokens = metric_usage.get("outputTokens") if isinstance(metric_usage, dict) else None
        if (
            not isinstance(metrics, dict)
            or metrics.get("currentModel") != self.model
            or not isinstance(total_user_requests, int)
            or isinstance(total_user_requests, bool)
            or total_user_requests != 1
            or set(model_metrics or {}) != {self.model}
            or not isinstance(requests, dict)
            or not isinstance(request_count, int)
            or isinstance(request_count, bool)
            or request_count != 1
            or not isinstance(request_cost, (int, float))
            or isinstance(request_cost, bool)
            or not math.isfinite(request_cost) or request_cost < 0
            or request_cost != premium
            or not isinstance(metric_usage, dict)
            or not isinstance(metric_output_tokens, int)
            or isinstance(metric_output_tokens, bool)
            or metric_output_tokens < 0
            or metric_output_tokens != output_tokens
            or not isinstance(total_nano_aiu, (int, float))
            or isinstance(total_nano_aiu, bool)
            or not math.isfinite(total_nano_aiu) or total_nano_aiu < 0
            or total_nano_aiu != nano_aiu
            or not isinstance(total_premium, (int, float))
            or isinstance(total_premium, bool)
            or not math.isfinite(total_premium) or total_premium < 0
            or total_premium != premium
        ):
            raise RuntimeError("Copilot SDK cumulative usage does not match call usage")
        if checkpoints:
            self._validate_usage_checkpoint(
                checkpoints[0], expected_nano_aiu=nano_aiu,
                expected_premium=premium,
            )

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

    def _validate_usage_checkpoint(
        self, record: dict, *, expected_nano_aiu: float,
        expected_premium: float,
    ) -> None:
        if set(record) != {"id", "timestamp", "parentId", "type", "data"}:
            raise RuntimeError("Copilot SDK usage checkpoint envelope is invalid")
        try:
            event_id = uuid.UUID(record["id"])
            parent_id = uuid.UUID(record["parentId"])
            timestamp = datetime.fromisoformat(record["timestamp"])
        except (ValueError, TypeError, AttributeError, KeyError) as exc:
            raise RuntimeError("Copilot SDK usage checkpoint envelope is invalid") from exc
        data = record.get("data")
        cache_state = data.get("modelCacheState") if isinstance(data, dict) else None
        if (
            record["type"] != "session.usage_checkpoint"
            or event_id.version != 4 or str(event_id) != record["id"].lower()
            or parent_id.version != 4 or str(parent_id) != record["parentId"].lower()
            or timestamp.tzinfo is None
            or not isinstance(data, dict)
            or set(data) != {
                "modelCacheState", "totalNanoAiu", "totalPremiumRequests",
            }
            or not isinstance(data["totalNanoAiu"], (int, float))
            or isinstance(data["totalNanoAiu"], bool)
            or not math.isfinite(data["totalNanoAiu"])
            or data["totalNanoAiu"] < 0
            or not isinstance(data["totalPremiumRequests"], (int, float))
            or isinstance(data["totalPremiumRequests"], bool)
            or not math.isfinite(data["totalPremiumRequests"])
            or data["totalPremiumRequests"] < 0
            or data["totalNanoAiu"] != expected_nano_aiu
            or data["totalPremiumRequests"] != expected_premium
            or not isinstance(cache_state, list) or len(cache_state) != 1
        ):
            raise RuntimeError("Copilot SDK usage checkpoint is invalid")
        state = cache_state[0]
        try:
            cache_expiry = datetime.fromisoformat(state["cacheExpiresAt"])
        except (ValueError, TypeError, KeyError) as exc:
            raise RuntimeError("Copilot SDK usage checkpoint cache state is invalid") from exc
        if (
            not isinstance(state, dict)
            or set(state) != {"cacheExpiresAt", "cacheTtlSeconds", "modelId"}
            or state["modelId"] != self.model
            or not isinstance(state["cacheTtlSeconds"], int)
            or isinstance(state["cacheTtlSeconds"], bool)
            or state["cacheTtlSeconds"] <= 0
            or cache_expiry.tzinfo is None
        ):
            raise RuntimeError("Copilot SDK usage checkpoint cache state is invalid")

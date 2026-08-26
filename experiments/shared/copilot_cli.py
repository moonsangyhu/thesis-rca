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
import re
import uuid
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


DEFAULT_COPILOT_MODEL = "gpt-5.6-terra"
MIN_COPILOT_SESSION_AIC = 30
RETRYABLE_SKILL_METADATA_FAILURE_CODES = frozenset({
    "entry_type", "extra_keys", "missing_keys", "name_type", "name_empty",
    "duplicate_name", "description_type", "source", "user_invocable_type",
    "enabled_state", "path_type", "argument_hint_type",
})
RETRYABLE_ZERO_USAGE_AUTH_FAILURE_CODE = "sdk_auth_session_creation_zero_usage"
RETRYABLE_MALFORMED_JSONL_FAILURE_CODE = "sdk_malformed_jsonl_complete_usage"
# The official SDK can reject a session before it is created when GitHub's
# account response serializes all three overage-entitlement fields as null.
# This has no session, model, tool, or usage event, so it is eligible only for
# the same bounded zero-usage retry contract as a sealed auth setup failure.
RETRYABLE_QUOTA_NULL_AUTH_FAILURE_CODE = "sdk_quota_null_auth_pre_session_zero_usage"


class CopilotCLIError(RuntimeError):
    """A post-subprocess failure carrying the already-journaled charge receipt."""

    def __init__(
        self,
        message: str,
        receipt: dict,
        *,
        retryable_control_metadata: bool = False,
        retryable_zero_usage_authentication: bool = False,
        failure_code: str | None = None,
    ):
        super().__init__(message)
        self.receipt = dict(receipt)
        self.retryable_control_metadata = retryable_control_metadata
        self.retryable_zero_usage_authentication = (
            retryable_zero_usage_authentication
        )
        self.failure_code = failure_code


class RetryableCopilotMetadataError(RuntimeError):
    """A strict control-metadata rejection that may be retried once."""

    def __init__(self, failure_code: str):
        if failure_code not in RETRYABLE_SKILL_METADATA_FAILURE_CODES:
            raise ValueError("unknown retryable Copilot metadata failure code")
        super().__init__(
            f"Copilot skills metadata entry is invalid: {failure_code}"
        )
        self.failure_code = failure_code


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
        billing_execution_authorized: bool | None = None,
        charge_observer: Callable[[dict], None] | None = None,
        pre_call_guard: Callable[[], object] | None = None,
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
        self.executable = resolved
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.max_ai_credits = max_ai_credits
        self.zero_overage_confirmed = zero_overage_confirmed
        self.billing_execution_authorized = billing_execution_authorized
        self.charge_observer = charge_observer
        self.pre_call_guard = pre_call_guard
        self._disabled_skill_names: frozenset[str] = frozenset()
        self._skill_isolation_prepared = False
        self._tool_filter_binding_required = False

    def _billing_guard_passes(self) -> bool:
        if self.billing_execution_authorized is not None:
            return self.billing_execution_authorized is True
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
                "Copilot inference blocked: billing execution is not authorized"
            )
        if self.pre_call_guard is not None:
            self.pre_call_guard()
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
            # A bare variadic option is normalized to `undefined` (no filter)
            # by CLI 1.0.78.  A nonempty allowlist containing the deliberately
            # nonexistent sentinel instead preserves filter semantics and
            # resolves to zero model-visible tools.  The corresponding exact
            # unknown-sentinel diagnostic is mandatory below.
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
            isolated_skills = Path(cwd) / "skills-empty"
            isolated_skills.mkdir(mode=0o700)
            subprocess_env = {
                **os.environ,
                "COPILOT_DYNAMIC_RETRIEVAL_SKILLS": "off",
                "COPILOT_SKILLS_DIRS": str(isolated_skills),
            }
            subprocess_env = self._prepare_skill_isolation(
                Path(cwd), subprocess_env
            )
            self._tool_filter_binding_required = True
            try:
                completed = subprocess.run(
                    command,
                    cwd=Path(cwd),
                    env=subprocess_env,
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
            parsed = self._parse_jsonl(stdout, expected_user_message=combined)
        except Exception as exc:
            retryable = isinstance(exc, RetryableCopilotMetadataError)
            raise CopilotCLIError(
                str(exc),
                receipt,
                retryable_control_metadata=retryable,
                failure_code=exc.failure_code if retryable else None,
            ) from exc
        return replace(
            parsed,
            started_at=started.isoformat(),
            ended_at=ended.isoformat(),
            latency_ms=latency_ms,
            exit_code=completed.returncode,
            cli_executable=self.executable,
            temporary_cwd_id=temporary_cwd_id,
        )

    def _prepare_skill_isolation(
        self, cwd: Path, subprocess_env: dict[str, str]
    ) -> dict[str, str]:
        """Disable every skill discovered in an isolated CLI configuration.

        Copilot CLI 1.0.78 exposes the SDK's ``enableSkills`` switch internally
        but not as a prompt-mode flag.  The supported CLI equivalent is an
        isolated ``COPILOT_HOME`` plus its official ``disabledSkills`` setting.
        Discovery is performed twice before inference: once to enumerate the
        finite builtin set and once to prove that exactly that set is disabled.
        Any project, personal, plugin, custom, or newly appearing skill blocks
        the model subprocess before it can consume AIC.
        """
        isolated_home = cwd / "copilot-home"
        isolated_home.mkdir(mode=0o700)
        env = {**subprocess_env, "COPILOT_HOME": str(isolated_home)}
        discovered = self._list_isolated_skills(cwd, env)
        names = self._validate_skill_inventory(discovered, expected_enabled=True)
        config_path = isolated_home / "config.json"
        config_path.write_text(
            json.dumps(
                {
                    "banner": "never",
                    "disabledSkills": sorted(names),
                    "showTipsOnStartup": False,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n",
            encoding="utf-8",
        )
        config_path.chmod(0o600)
        verified = self._list_isolated_skills(cwd, env)
        verified_names = self._validate_skill_inventory(
            verified, expected_enabled=False
        )
        if verified_names != names:
            raise RuntimeError("Copilot skill inventory changed during isolation")
        self._disabled_skill_names = frozenset(names)
        self._skill_isolation_prepared = True
        return env

    def _list_isolated_skills(
        self, cwd: Path, subprocess_env: dict[str, str]
    ) -> list[dict]:
        completed = subprocess.run(
            [self.executable, "skill", "list", "--json", "--no-auto-update"],
            cwd=cwd,
            env=subprocess_env,
            text=True,
            capture_output=True,
            timeout=min(self.timeout_seconds, 30),
            check=False,
        )
        if completed.returncode != 0:
            raise RuntimeError("Copilot skill-isolation preflight failed")
        try:
            inventory = json.loads(self._as_text(completed.stdout))
        except json.JSONDecodeError as exc:
            raise RuntimeError(
                "Copilot skill-isolation preflight emitted invalid JSON"
            ) from exc
        if not isinstance(inventory, list):
            raise RuntimeError("Copilot skill inventory must be a JSON array")
        return inventory

    @staticmethod
    def _validate_skill_inventory(
        inventory: list[dict], *, expected_enabled: bool
    ) -> frozenset[str]:
        names: set[str] = set()
        for item in inventory:
            if not isinstance(item, dict):
                raise RuntimeError("Copilot skill inventory entry is invalid")
            name = item.get("name")
            if (
                set(item) != {"name", "description", "source", "path", "enabled"}
                or not isinstance(name, str)
                or not name
                or name in names
                or not isinstance(item.get("description"), str)
                or item.get("source") != "builtin"
                or not isinstance(item.get("path"), str)
                or not item.get("path")
                or item.get("enabled") is not expected_enabled
            ):
                raise RuntimeError(
                    "Copilot skill inventory is not isolated to the builtin set"
                )
            names.add(name)
        return frozenset(names)

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
    def _validated_ephemeral_metadata(event: dict, event_type: str) -> dict:
        expected_keys = {
            "id", "timestamp", "parentId", "ephemeral", "type", "data",
        }
        data = event.get("data")
        try:
            raw_event_id = event.get("id")
            if not isinstance(raw_event_id, str):
                raise ValueError("event ID is not a string")
            event_id = uuid.UUID(raw_event_id)
            raw_parent_id = event.get("parentId")
            parent_id = None if raw_parent_id is None else uuid.UUID(raw_parent_id)
            event_timestamp = datetime.fromisoformat(
                str(event.get("timestamp") or "")
            )
        except (ValueError, TypeError, AttributeError) as exc:
            raise RuntimeError(f"Copilot {event_type} metadata event is invalid") from exc
        if (
            set(event) != expected_keys
            or event.get("type") != event_type
            or event_id.version != 4
            or str(event_id) != raw_event_id.lower()
            or (
                raw_parent_id is not None
                and (
                    not isinstance(raw_parent_id, str)
                    or parent_id is None or parent_id.version != 4
                    or str(parent_id) != raw_parent_id.lower()
                )
            )
            or event_timestamp.tzinfo is None
            or event.get("ephemeral") is not True
            or not isinstance(data, dict)
        ):
            raise RuntimeError(f"Copilot {event_type} metadata event is invalid")
        return data

    @staticmethod
    def _validate_user_message(event: dict, expected_content: str) -> dict:
        """Bind the persisted root user event to the exact submitted prompt."""
        expected_event_keys = {"id", "timestamp", "parentId", "type", "data"}
        expected_data_keys = {
            "attachments", "content", "delivery", "interactionId",
            "parentAgentTaskId", "supportedNativeDocumentMimeTypes",
            "transformedContent",
        }
        data = event.get("data")
        try:
            event_id = uuid.UUID(event.get("id"))
            parent_id = uuid.UUID(event.get("parentId"))
            event_timestamp = datetime.fromisoformat(event.get("timestamp"))
            interaction_id = uuid.UUID(data.get("interactionId"))
            parent_task_id = uuid.UUID(data.get("parentAgentTaskId"))
        except (ValueError, TypeError, AttributeError) as exc:
            raise RuntimeError("Copilot user message event is invalid") from exc
        canonical_ids = (
            (event_id, event.get("id")),
            (parent_id, event.get("parentId")),
            (interaction_id, data.get("interactionId")),
            (parent_task_id, data.get("parentAgentTaskId")),
        )
        transformed = data.get("transformedContent")
        match = re.fullmatch(
            r"<current_datetime>([^<]+)</current_datetime>\n\n" +
            re.escape(expected_content),
            transformed if isinstance(transformed, str) else "",
        )
        try:
            transformed_timestamp = datetime.fromisoformat(match.group(1)) if match else None
        except ValueError as exc:
            raise RuntimeError("Copilot user message transform is invalid") from exc
        if (
            set(event) != expected_event_keys
            or event.get("type") != "user.message"
            or not isinstance(data, dict)
            or set(data) != expected_data_keys
            or any(
                parsed.version != 4
                or not isinstance(raw, str)
                or str(parsed) != raw.lower()
                for parsed, raw in canonical_ids
            )
            or event_timestamp.tzinfo is None
            or transformed_timestamp is None
            or transformed_timestamp.tzinfo is None
            or data.get("content") != expected_content
            or data.get("attachments") != []
            or data.get("supportedNativeDocumentMimeTypes") != []
            or data.get("delivery") != "idle"
        ):
            raise RuntimeError("Copilot user message event is invalid")
        return {
            "event_id": event.get("id"),
            "interaction_id": data.get("interactionId"),
        }

    @staticmethod
    def _validated_lifecycle_event(
        event: dict, event_type: str, *, ephemeral: bool
    ) -> dict:
        expected_keys = {"id", "timestamp", "parentId", "type", "data"}
        if ephemeral:
            expected_keys.add("ephemeral")
        data = event.get("data")
        try:
            raw_id = event.get("id")
            raw_parent = event.get("parentId")
            event_id = uuid.UUID(raw_id)
            parent_id = uuid.UUID(raw_parent)
            timestamp = datetime.fromisoformat(event.get("timestamp"))
        except (ValueError, TypeError, AttributeError) as exc:
            raise RuntimeError(f"Copilot {event_type} lifecycle event is invalid") from exc
        if (
            set(event) != expected_keys
            or event.get("type") != event_type
            or event_id.version != 4
            or parent_id.version != 4
            or str(event_id) != raw_id.lower()
            or str(parent_id) != raw_parent.lower()
            or timestamp.tzinfo is None
            or (ephemeral and event.get("ephemeral") is not True)
            or not isinstance(data, dict)
        ):
            raise RuntimeError(f"Copilot {event_type} lifecycle event is invalid")
        return data

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

    def _parse_jsonl(
        self, output: str, *, expected_user_message: str | None = None
    ) -> CopilotCLIResponse:
        message: dict | None = None
        result: dict | None = None
        usage_checkpoint: dict | None = None
        skills_metadata_count = 0
        unknown_tool_sentinel_count = 0
        user_message_count = 0
        user_metadata: dict | None = None
        turn_id: str | None = None
        message_id: str | None = None
        message_phase: str | None = None
        streamed_parts: list[str] = []
        reasoning_id: str | None = None
        reasoning_parts: list[str] = []
        reasoning_event_count = 0
        lifecycle_counts = {
            "assistant.turn_start": 0,
            "model.call_start": 0,
            "assistant.message_start": 0,
            "assistant.turn_end": 0,
            "assistant.idle": 0,
        }
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
            elif event.get("type") == "user.message":
                if expected_user_message is None:
                    raise RuntimeError("unexpected Copilot user message event")
                user_message_count += 1
                if user_message_count != 1:
                    raise RuntimeError("Copilot user message event is duplicated")
                user_metadata = self._validate_user_message(
                    event, expected_user_message
                )
            elif event.get("type") == "assistant.turn_start":
                lifecycle_counts["assistant.turn_start"] += 1
                data = self._validated_lifecycle_event(
                    event, "assistant.turn_start", ephemeral=False
                )
                if (
                    lifecycle_counts["assistant.turn_start"] != 1
                    or set(data) != {"turnId", "interactionId"}
                    or not isinstance(data.get("turnId"), str)
                    or not data["turnId"]
                    or user_metadata is None
                    or data.get("interactionId") != user_metadata["interaction_id"]
                ):
                    raise RuntimeError("Copilot assistant turn start is invalid")
                turn_id = data["turnId"]
            elif event.get("type") == "model.call_start":
                lifecycle_counts["model.call_start"] += 1
                data = self._validated_lifecycle_event(
                    event, "model.call_start", ephemeral=True
                )
                if (
                    lifecycle_counts["model.call_start"] != 1
                    or set(data) != {"turnId", "model"}
                    or data.get("turnId") != turn_id
                    or data.get("model") != self.model
                ):
                    raise RuntimeError("Copilot model call start is invalid")
            elif event.get("type") == "assistant.message_start":
                lifecycle_counts["assistant.message_start"] += 1
                data = self._validated_lifecycle_event(
                    event, "assistant.message_start", ephemeral=True
                )
                if (
                    lifecycle_counts["assistant.message_start"] != 1
                    or set(data) != {"messageId", "phase"}
                    or not isinstance(data.get("messageId"), str)
                    or not data["messageId"]
                    or not isinstance(data.get("phase"), str)
                    or not data["phase"]
                ):
                    raise RuntimeError("Copilot assistant message start is invalid")
                message_id = data["messageId"]
                message_phase = data["phase"]
            elif event.get("type") == "assistant.reasoning_delta":
                data = self._validated_lifecycle_event(
                    event, "assistant.reasoning_delta", ephemeral=True
                )
                current_id = data.get("reasoningId")
                if (
                    set(data) != {"reasoningId", "deltaContent"}
                    or not isinstance(current_id, str)
                    or not current_id
                    or (reasoning_id is not None and current_id != reasoning_id)
                    or not isinstance(data.get("deltaContent"), str)
                ):
                    raise RuntimeError("Copilot assistant reasoning delta is invalid")
                reasoning_id = current_id
                reasoning_parts.append(data["deltaContent"])
            elif event.get("type") == "assistant.reasoning":
                reasoning_event_count += 1
                data = self._validated_lifecycle_event(
                    event, "assistant.reasoning", ephemeral=True
                )
                allowed = {"reasoningId", "content"}
                if "rte" in data:
                    allowed.add("rte")
                current_id = data.get("reasoningId")
                content_value = data.get("content")
                if (
                    reasoning_event_count != 1
                    or set(data) != allowed
                    or not isinstance(current_id, str)
                    or not current_id
                    or not isinstance(content_value, str)
                    or ("rte" in data and not isinstance(data["rte"], bool))
                    or (reasoning_id is not None and current_id != reasoning_id)
                    or (reasoning_parts and "".join(reasoning_parts) != content_value)
                ):
                    raise RuntimeError("Copilot assistant reasoning event is invalid")
                reasoning_id = current_id
            elif event.get("type") == "assistant.message_delta":
                data = self._validated_lifecycle_event(
                    event, "assistant.message_delta", ephemeral=True
                )
                if (
                    set(data) != {"messageId", "deltaContent"}
                    or data.get("messageId") != message_id
                    or not isinstance(data.get("deltaContent"), str)
                ):
                    raise RuntimeError("Copilot assistant message delta is invalid")
                streamed_parts.append(data["deltaContent"])
            elif event.get("type") == "assistant.turn_end":
                lifecycle_counts["assistant.turn_end"] += 1
                data = self._validated_lifecycle_event(
                    event, "assistant.turn_end", ephemeral=False
                )
                if (
                    lifecycle_counts["assistant.turn_end"] != 1
                    or set(data) != {"turnId"}
                    or data.get("turnId") != turn_id
                ):
                    raise RuntimeError("Copilot assistant turn end is invalid")
            elif event.get("type") == "assistant.idle":
                lifecycle_counts["assistant.idle"] += 1
                data = self._validated_lifecycle_event(
                    event, "assistant.idle", ephemeral=True
                )
                if lifecycle_counts["assistant.idle"] != 1 or data != {}:
                    raise RuntimeError("Copilot assistant idle event is invalid")
            elif event.get("type") == "result":
                result = event
            elif event.get("type") == "session.usage_checkpoint":
                usage_checkpoint = event.get("data") or {}
                if not isinstance(usage_checkpoint, dict):
                    raise RuntimeError("Copilot usage checkpoint data is invalid")
            elif event.get("type") == "session.tools_updated":
                # CLI 1.0.78 emits this transient metadata event when the
                # model-specific *resolved* tool set is established. It is not
                # a tool request/execution event. Accept only the exact local
                # SDK schema for the pinned root model; every tool.* event and
                # assistant toolRequests remain fail-closed below/above.
                data = self._validated_ephemeral_metadata(
                    event, "session.tools_updated"
                )
                if set(data) != {"model"} or data.get("model") != self.model:
                    raise RuntimeError("Copilot tools metadata event is invalid")
            elif event.get("type") == "session.skills_loaded":
                skills_metadata_count += 1
                if skills_metadata_count != 1:
                    raise RuntimeError("Copilot skills metadata is duplicated")
                data = self._validated_ephemeral_metadata(
                    event, "session.skills_loaded"
                )
                if set(data) != {"skills"} or not isinstance(data.get("skills"), list):
                    raise RuntimeError("Copilot skills metadata is invalid")
                loaded_names: set[str] = set()
                for skill in data["skills"]:
                    if not isinstance(skill, dict):
                        raise RetryableCopilotMetadataError("entry_type")
                    allowed_keys = {
                        "name", "description", "source", "userInvocable",
                        "enabled", "path", "argumentHint",
                    }
                    required_keys = {
                        "name", "description", "source", "userInvocable", "enabled",
                    }
                    name = skill.get("name")
                    invalid_reason = None
                    if not set(skill).issubset(allowed_keys):
                        invalid_reason = "extra_keys"
                    elif not required_keys.issubset(skill):
                        invalid_reason = "missing_keys"
                    elif not isinstance(name, str):
                        invalid_reason = "name_type"
                    elif not name:
                        invalid_reason = "name_empty"
                    elif name in loaded_names:
                        invalid_reason = "duplicate_name"
                    elif not isinstance(skill.get("description"), str):
                        invalid_reason = "description_type"
                    elif skill.get("source") != "builtin":
                        invalid_reason = "source"
                    elif not isinstance(skill.get("userInvocable"), bool):
                        invalid_reason = "user_invocable_type"
                    elif skill.get("enabled") is not False:
                        invalid_reason = "enabled_state"
                    elif "path" in skill and not isinstance(skill["path"], str):
                        invalid_reason = "path_type"
                    elif "argumentHint" in skill and not isinstance(skill["argumentHint"], str):
                        invalid_reason = "argument_hint_type"
                    if invalid_reason is not None:
                        raise RetryableCopilotMetadataError(invalid_reason)
                    loaded_names.add(name)
                if loaded_names != set(self._disabled_skill_names):
                    raise RuntimeError(
                        "Copilot skills metadata does not match disabled inventory"
                    )
            elif event.get("type") == "session.info":
                # The nonempty allowlist sentinel produces an official
                # configuration diagnostic.  Requiring that exact sentinel
                # binds the pre-call argv to the inference session while the
                # resolved allowlist itself matches zero tools.
                data = self._validated_ephemeral_metadata(event, "session.info")
                message_text = data.get("message")
                unknown_sentinel = (
                    isinstance(message_text, str)
                    and message_text
                    == 'Unknown tool name in the tool allowlist: "none"'
                )
                disabled_summary = (
                    isinstance(message_text, str)
                    and message_text.startswith("Disabled tools: ")
                )
                if (
                    set(data) != {"infoType", "message"}
                    or data.get("infoType") != "configuration"
                    or not isinstance(message_text, str)
                    or not (unknown_sentinel or disabled_summary)
                    or len(message_text) > 4096
                    or any(ord(char) < 32 for char in message_text)
                ):
                    raise RuntimeError("Copilot informational metadata is invalid")
                if unknown_sentinel:
                    unknown_tool_sentinel_count += 1
                    if unknown_tool_sentinel_count != 1:
                        raise RuntimeError(
                            "Copilot unknown-tool sentinel metadata is duplicated"
                        )
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

        if self._skill_isolation_prepared and skills_metadata_count != 1:
            raise RuntimeError(
                "Copilot response is missing skill-isolation metadata"
            )
        if (
            self._tool_filter_binding_required
            and unknown_tool_sentinel_count != 1
        ):
            raise RuntimeError(
                "Copilot response is missing zero-tool filter metadata"
            )
        if expected_user_message is not None and user_message_count != 1:
            raise RuntimeError("Copilot response is missing bound user message metadata")
        if expected_user_message is not None and any(
            count != 1 for count in lifecycle_counts.values()
        ):
            raise RuntimeError("Copilot response lifecycle is incomplete")
        if reasoning_parts and reasoning_event_count != 1:
            raise RuntimeError("Copilot assistant reasoning lifecycle is incomplete")
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
        if expected_user_message is not None:
            required_message_keys = {
                "apiCallId", "clientRequestId", "content", "interactionId",
                "messageId", "model", "outputTokens", "phase", "requestId",
                "rte", "serviceRequestId", "toolRequests", "turnId",
            }
            optional_reasoning_keys = {
                "reasoningOpaque", "reasoningText", "reasoningWireField",
                "encryptedContent",
            }
            string_keys = (set(message) - {
                "outputTokens", "rte", "toolRequests",
            })
            if (
                not required_message_keys.issubset(message)
                or not set(message).issubset(
                    required_message_keys | optional_reasoning_keys
                )
                or any(
                    not isinstance(message.get(key), str)
                    for key in string_keys
                )
                or any(
                    not message[key]
                    for key in (
                        "content", "interactionId", "messageId", "model",
                        "phase", "turnId",
                    )
                )
                or message.get("interactionId") != user_metadata["interaction_id"]
                or message.get("messageId") != message_id
                or message.get("turnId") != turn_id
                or message.get("phase") != message_phase
                or message.get("toolRequests") != []
                or not isinstance(message.get("rte"), bool)
                or "".join(streamed_parts) != content
            ):
                raise RuntimeError("Copilot assistant lifecycle binding is invalid")
        return CopilotCLIResponse(
            text=content,
            model=actual_model,
            session_id=session_id,
            output_tokens=output_tokens,
            ai_credits=ai_credits,
            premium_requests=premium_requests,
        )

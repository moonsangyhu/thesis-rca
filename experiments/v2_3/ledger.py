"""Call-ledger schema and fail-closed provenance validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import math
import re
from typing import Callable

from .config import (
    CONDITIONS, EXPERIMENT, FAULTS, GENERATOR_OUTPUT_LIMIT, JUDGE_OUTPUT_LIMIT,
    REQUESTED_MODEL, TRIALS,
)
from .scanner import sha256_text

REQUIRED_BLOCK_FLAGS = frozenset(
    {"no-tools", "no-mcp", "no-remote", "no-custom-instructions"}
)


class ProvenanceError(RuntimeError):
    pass


@dataclass(frozen=True)
class CallLedgerEntry:
    experiment: str
    campaign_id: str
    fault_id: str
    trial: int
    context_condition: str
    role: str
    generation_repeat: int
    judge_repeat: int | None
    requested_model: str
    actual_model: str
    provider: str
    cli_executable: str
    cli_version: str
    session_id: str
    started_at: str
    ended_at: str
    latency_ms: int
    exit_code: int
    output_text_hash: str
    output_tokens: int
    ai_credits: float
    cumulative_ai_credits: float
    premium_requests: float
    system_prompt_hash: str
    user_prompt_hash: str
    runtime_context_hash: str
    additional_context_hash: str
    full_context_hash: str
    linked_runtime_context_hash: str
    linked_additional_context_hash: str
    linked_full_context_hash: str
    requested_output_limit: int
    block_flags: tuple[str, ...]
    block_flags_hash: str
    temporary_cwd_id: str
    tool_event_count: int
    mcp_event_count: int
    remote_event_count: int
    custom_instruction_event_count: int
    input_chars: int
    input_bytes: int
    input_proxy_tokens: int
    input_tokens: str = "unsupported/not_reported"

    def validate(self) -> None:
        if self.experiment != EXPERIMENT or not self.campaign_id:
            raise ProvenanceError("invalid experiment or campaign")
        if self.fault_id not in FAULTS or self.trial not in TRIALS:
            raise ProvenanceError("invalid fault or trial")
        if self.context_condition not in CONDITIONS:
            raise ProvenanceError("invalid context condition")
        if self.role not in {"generator", "judge"}:
            raise ProvenanceError("invalid call role")
        if self.generation_repeat not in {1, 2, 3}:
            raise ProvenanceError("invalid generation repeat")
        if self.role == "generator" and self.judge_repeat is not None:
            raise ProvenanceError("generator must not have a judge repeat")
        if self.role == "judge" and self.judge_repeat not in {1, 2, 3}:
            raise ProvenanceError("invalid judge repeat")
        if self.requested_model != REQUESTED_MODEL or self.actual_model != REQUESTED_MODEL:
            raise ProvenanceError("requested/actual model mismatch")
        if self.provider not in {"copilot", "mock-copilot", "codex-cli-chatgpt-subscription"}:
            raise ProvenanceError("invalid provider")
        if not self.session_id:
            raise ProvenanceError("missing session ID")
        if isinstance(self.output_tokens, bool) or not isinstance(self.output_tokens, int):
            raise ProvenanceError("output token count must be an integer")
        usage = (self.output_tokens, self.ai_credits, self.cumulative_ai_credits,
                 self.premium_requests)
        if any(not isinstance(value, (int, float)) or isinstance(value, bool) for value in usage):
            raise ProvenanceError("missing or invalid usage metadata")
        if any(value < 0 or not math.isfinite(float(value)) for value in usage):
            raise ProvenanceError("missing or invalid usage metadata")
        if self.ai_credits > self.cumulative_ai_credits:
            raise ProvenanceError("call AIC exceeds cumulative AIC")
        if self.exit_code != 0:
            raise ProvenanceError("non-zero call exit code")
        if self.latency_ms < 0 or any(
            value < 0 for value in (self.input_chars, self.input_bytes, self.input_proxy_tokens)
        ):
            raise ProvenanceError("negative timing or input metric")
        try:
            started = datetime.fromisoformat(self.started_at)
            ended = datetime.fromisoformat(self.ended_at)
        except ValueError as exc:
            raise ProvenanceError("invalid call timestamp") from exc
        if started.tzinfo is None or ended.tzinfo is None or ended < started:
            raise ProvenanceError("invalid call timestamp ordering")
        expected_limit = GENERATOR_OUTPUT_LIMIT if self.role == "generator" else JUDGE_OUTPUT_LIMIT
        if self.requested_output_limit != expected_limit:
            raise ProvenanceError("invalid role output limit")
        if frozenset(self.block_flags) != REQUIRED_BLOCK_FLAGS:
            raise ProvenanceError("incomplete isolation flags")
        if self.block_flags_hash != sha256_text("\n".join(self.block_flags)):
            raise ProvenanceError("isolation flag hash mismatch")
        if any((self.tool_event_count, self.mcp_event_count, self.remote_event_count,
                self.custom_instruction_event_count)):
            raise ProvenanceError("tool/MCP/remote/custom-instruction event detected")
        required = (
            self.cli_executable, self.cli_version, self.output_text_hash,
            self.system_prompt_hash, self.user_prompt_hash,
            self.runtime_context_hash, self.additional_context_hash,
            self.full_context_hash, self.block_flags_hash, self.temporary_cwd_id,
        )
        if any(not value for value in required):
            raise ProvenanceError("incomplete call provenance")
        hashes = (
            self.output_text_hash, self.system_prompt_hash, self.user_prompt_hash,
            self.runtime_context_hash, self.additional_context_hash,
            self.full_context_hash, self.linked_runtime_context_hash,
            self.linked_additional_context_hash, self.linked_full_context_hash,
            self.block_flags_hash,
        )
        if any(re.fullmatch(r"[0-9a-f]{64}", value) is None for value in hashes):
            raise ProvenanceError("invalid provenance hash")
        if not math.isfinite(float(self.ai_credits)) or not math.isfinite(
            float(self.cumulative_ai_credits)
        ):
            raise ProvenanceError("non-finite AIC metadata")
        if self.input_tokens != "unsupported/not_reported":
            raise ProvenanceError("provider input tokens must be marked unsupported")

    def to_dict(self) -> dict:
        return asdict(self)


class CallLedger:
    def __init__(self, on_append: Callable[[CallLedgerEntry], None] | None = None):
        self.entries: list[CallLedgerEntry] = []
        self._sessions: set[str] = set()
        self._campaign_id: str | None = None
        self._cumulative_aic = 0.0
        self._on_append = on_append

    def append(self, entry: CallLedgerEntry, invocation=None, linked_context=None) -> None:
        entry.validate()
        if invocation is not None:
            context = invocation.context
            expected = {
                "fault_id": invocation.fault_id,
                "trial": invocation.trial,
                "context_condition": invocation.condition,
                "role": invocation.role,
                "generation_repeat": invocation.generation_repeat,
                "judge_repeat": invocation.judge_repeat,
                "user_prompt_hash": sha256_text(invocation.prompt),
                "runtime_context_hash": context.runtime_context_hash,
                "additional_context_hash": context.additional_context_hash,
                "full_context_hash": context.full_context_hash,
            }
            for name, value in expected.items():
                if getattr(entry, name) != value:
                    raise ProvenanceError(f"ledger/invocation mismatch: {name}")
            prompt_bytes = len(invocation.prompt.encode("utf-8"))
            if (entry.input_chars, entry.input_bytes, entry.input_proxy_tokens) != (
                len(invocation.prompt), prompt_bytes, math.ceil(prompt_bytes / 4)
            ):
                raise ProvenanceError("ledger/invocation input metric mismatch")
        if linked_context is not None and (
            entry.linked_runtime_context_hash,
            entry.linked_additional_context_hash,
            entry.linked_full_context_hash,
        ) != (
            linked_context.runtime_context_hash,
            linked_context.additional_context_hash,
            linked_context.full_context_hash,
        ):
            raise ProvenanceError("ledger/linkage context mismatch")
        if self._campaign_id is None:
            self._campaign_id = entry.campaign_id
        elif entry.campaign_id != self._campaign_id:
            raise ProvenanceError("campaign changed within call ledger")
        expected_cumulative = self._cumulative_aic + entry.ai_credits
        if not math.isclose(entry.cumulative_ai_credits, expected_cumulative, abs_tol=1e-9):
            raise ProvenanceError("cumulative AIC does not equal previous plus call AIC")
        if entry.session_id in self._sessions:
            raise ProvenanceError("session ID reused")
        if self._on_append is not None:
            self._on_append(entry)
        self._sessions.add(entry.session_id)
        self._cumulative_aic = entry.cumulative_ai_credits
        self.entries.append(entry)

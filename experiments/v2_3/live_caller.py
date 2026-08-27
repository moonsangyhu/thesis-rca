"""Authorized Terra caller that converts Copilot JSONL into V2.3 provenance."""

from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass

from experiments.shared.copilot_cli import (
    CopilotCLIBackend, CopilotCLIError, RETRYABLE_SKILL_METADATA_FAILURE_CODES,
    RETRYABLE_ZERO_USAGE_AUTH_FAILURE_CODE,
    RETRYABLE_QUOTA_NULL_AUTH_FAILURE_CODE,
    RETRYABLE_MALFORMED_JSONL_FAILURE_CODE,
)

from .authorization import LiveAuthorization
from .conditions import text_metrics
from .config import (
    EXPERIMENT, GENERATOR_OUTPUT_LIMIT, JUDGE_OUTPUT_LIMIT, REQUESTED_MODEL,
)
from .engine import Invocation, InvocationResult
from .ledger import CallLedgerEntry
from .scanner import sha256_text

BLOCK_FLAGS = ("no-tools", "no-mcp", "no-remote", "no-custom-instructions")
GENERATOR_SYSTEM_PROMPT = (
    "You are a Kubernetes RCA evaluator. Use only the supplied runtime and additional "
    "context. Return one JSON object with exactly these keys: identified_fault_type "
    "(string), root_cause (string), remediation (non-empty array of strings). Do not "
    "use tools, files, memory, remote sources, or experiment-arm guesses."
)
JUDGE_SYSTEM_PROMPT = (
    "You are a blinded correctness judge. Compare only sealed_reference and "
    "candidate_diagnosis in the supplied JSON. Return exactly one JSON object with "
    "correctness_score, a finite number from 0 to 1. Do not identify treatment arms."
)


class LiveCallerError(RuntimeError):
    pass


def parse_json_object(text: str) -> dict:
    value = text.strip()
    if value.startswith("```"):
        lines = value.splitlines()[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        value = "\n".join(lines)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise LiveCallerError("Terra response is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise LiveCallerError("Terra response must be a JSON object")
    return parsed


@dataclass
class AuthorizedTerraCaller:
    authorization: LiveAuthorization
    backend: CopilotCLIBackend
    campaign_id: str
    cli_version: str
    max_campaign_aic: float | None = 360.0
    cumulative_aic: float = 0.0
    usage_uncertain: bool = False
    campaign_aborted: bool = False

    def __post_init__(self) -> None:
        self.authorization.revalidate()
        if self.backend.model != REQUESTED_MODEL:
            raise LiveCallerError("Copilot backend model is not gpt-5.6-terra")
        if not self.cli_version.strip() or not self.campaign_id.strip():
            raise LiveCallerError("CLI version and campaign ID are required")
        if self.max_campaign_aic is not None and (
            isinstance(self.max_campaign_aic, bool)
            or not isinstance(self.max_campaign_aic, (int, float))
            or not math.isfinite(self.max_campaign_aic)
            or self.max_campaign_aic <= 0
        ):
            raise LiveCallerError("campaign AIC cap must be positive and finite")
        if not self.backend._billing_guard_passes():
            raise LiveCallerError("Copilot backend billing guard is not enabled")
        if getattr(self.backend, "charge_observer", None) is None:
            raise LiveCallerError("durable charged-call observer is required")
        session_cap = getattr(self.backend, "max_ai_credits", None)
        if (
            isinstance(session_cap, bool)
            or not isinstance(session_cap, (int, float))
            or not math.isfinite(session_cap)
            or session_cap <= 0
            or (
                self.max_campaign_aic is not None
                and session_cap > self.max_campaign_aic
            )
        ):
            raise LiveCallerError("invalid Copilot session AIC ceiling")

    def __call__(self, invocation: Invocation) -> InvocationResult:
        self.authorization.revalidate()
        if self.campaign_aborted:
            raise LiveCallerError("campaign aborted after a failed Copilot call")
        if self.usage_uncertain:
            raise LiveCallerError("campaign AIC is uncertain after a failed call")
        session_cap = float(self.backend.max_ai_credits)
        if (
            self.max_campaign_aic is not None
            and self.cumulative_aic + session_cap > self.max_campaign_aic
        ):
            raise LiveCallerError("campaign AIC cap reached before call")
        if invocation.role == "generator":
            system_prompt = GENERATOR_SYSTEM_PROMPT
            output_limit = GENERATOR_OUTPUT_LIMIT
        elif invocation.role == "judge":
            system_prompt = JUDGE_SYSTEM_PROMPT
            output_limit = JUDGE_OUTPUT_LIMIT
        else:
            raise LiveCallerError("unknown inference role")

        retry_aic = 0.0
        retry_premium_requests = 0.0
        # A session-create failure carrying the exact quota-null envelope is
        # proven pre-inference/zero-usage.  GitHub served it twice in a row in
        # Primary40, so permit two bounded backoff retries for that *single*
        # failure code; every other retry class remains one retry.
        for attempt in range(3):
            if (
                self.max_campaign_aic is not None
                and self.cumulative_aic + session_cap > self.max_campaign_aic
            ):
                self.campaign_aborted = attempt > 0
                raise LiveCallerError("campaign AIC cap reached before call")
            try:
                response = self.backend.call(
                    invocation.prompt, system_prompt, output_limit
                )
                break
            except CopilotCLIError as exc:
                charged = exc.receipt.get("ai_credits")
                known_charge = (
                    isinstance(charged, (int, float))
                    and not isinstance(charged, bool)
                    and math.isfinite(charged)
                    and charged >= 0
                )
                if known_charge:
                    self.cumulative_aic += charged
                else:
                    self.usage_uncertain = True
                premium = exc.receipt.get("premium_requests")
                complete_usage = (
                    exc.receipt.get("usage_metadata_complete") is True
                    and exc.receipt.get("actual_model") == self.backend.model
                    and isinstance(exc.receipt.get("output_tokens"), int)
                    and not isinstance(exc.receipt.get("output_tokens"), bool)
                    and exc.receipt["output_tokens"] >= 0
                    and isinstance(premium, (int, float))
                    and not isinstance(premium, bool)
                    and math.isfinite(premium)
                    and premium >= 0
                )
                retryable_metadata = (
                    attempt == 0
                    and exc.retryable_control_metadata
                    and exc.failure_code in RETRYABLE_SKILL_METADATA_FAILURE_CODES
                    and known_charge
                    and complete_usage
                    and not self.usage_uncertain
                )
                retryable_zero_usage_auth = (
                    (
                        attempt < 2
                        if exc.failure_code == RETRYABLE_QUOTA_NULL_AUTH_FAILURE_CODE
                        else attempt == 0
                    )
                    and exc.retryable_zero_usage_authentication
                    and exc.failure_code in {
                        RETRYABLE_ZERO_USAGE_AUTH_FAILURE_CODE,
                        RETRYABLE_QUOTA_NULL_AUTH_FAILURE_CODE,
                    }
                    and known_charge and charged == 0
                    and exc.receipt.get("usage_metadata_complete") is True
                    and exc.receipt.get("actual_model") is None
                    and exc.receipt.get("output_tokens") == 0
                    and isinstance(premium, (int, float))
                    and not isinstance(premium, bool)
                    and math.isfinite(premium) and premium == 0
                    and not self.usage_uncertain
                )
                retryable_malformed_jsonl = (
                    attempt == 0
                    and exc.failure_code == RETRYABLE_MALFORMED_JSONL_FAILURE_CODE
                    and known_charge
                    and complete_usage
                    and not self.usage_uncertain
                )
                retryable = (retryable_metadata or retryable_zero_usage_auth
                             or retryable_malformed_jsonl)
                if retryable:
                    retry_aic += charged
                    retry_premium_requests += premium
                    if exc.failure_code == RETRYABLE_QUOTA_NULL_AUTH_FAILURE_CODE:
                        time.sleep(2 ** attempt)
                    continue
                self.campaign_aborted = True
                raise LiveCallerError(
                    f"Copilot CLI call failed after durable charge receipt: {exc}"
                ) from exc
        if (
            isinstance(response.ai_credits, bool)
            or not isinstance(response.ai_credits, (int, float))
            or not math.isfinite(response.ai_credits)
            or response.ai_credits < 0
        ):
            raise LiveCallerError("Copilot response AIC is invalid")
        logical_call_aic = retry_aic + response.ai_credits
        next_cumulative = self.cumulative_aic + response.ai_credits
        self.cumulative_aic = next_cumulative
        if self.max_campaign_aic is not None and next_cumulative > self.max_campaign_aic:
            raise LiveCallerError("campaign AIC cap exceeded")
        payload = parse_json_object(response.text)
        metrics = text_metrics(invocation.prompt)
        entry = CallLedgerEntry(
            experiment=EXPERIMENT,
            campaign_id=self.campaign_id,
            fault_id=invocation.fault_id,
            trial=invocation.trial,
            context_condition=invocation.condition,
            role=invocation.role,
            generation_repeat=invocation.generation_repeat,
            judge_repeat=invocation.judge_repeat,
            requested_model=REQUESTED_MODEL,
            actual_model=response.model,
            provider="copilot",
            cli_executable=response.cli_executable,
            cli_version=self.cli_version,
            session_id=response.session_id,
            started_at=response.started_at,
            ended_at=response.ended_at,
            latency_ms=response.latency_ms,
            exit_code=response.exit_code,
            output_text_hash=sha256_text(response.text),
            output_tokens=response.output_tokens,
            ai_credits=logical_call_aic,
            cumulative_ai_credits=self.cumulative_aic,
            premium_requests=retry_premium_requests + response.premium_requests,
            system_prompt_hash=sha256_text(system_prompt),
            user_prompt_hash=sha256_text(invocation.prompt),
            runtime_context_hash=invocation.context.runtime_context_hash,
            additional_context_hash=invocation.context.additional_context_hash,
            full_context_hash=invocation.context.full_context_hash,
            linked_runtime_context_hash=invocation.context.runtime_context_hash,
            linked_additional_context_hash=invocation.context.additional_context_hash,
            linked_full_context_hash=invocation.context.full_context_hash,
            requested_output_limit=output_limit,
            block_flags=BLOCK_FLAGS,
            block_flags_hash=sha256_text("\n".join(BLOCK_FLAGS)),
            temporary_cwd_id=response.temporary_cwd_id,
            tool_event_count=0,
            mcp_event_count=0,
            remote_event_count=0,
            custom_instruction_event_count=0,
            input_chars=metrics["chars"],
            input_bytes=metrics["bytes"],
            input_proxy_tokens=metrics["proxy_tokens"],
        )
        return InvocationResult(payload=payload, ledger_entry=entry)

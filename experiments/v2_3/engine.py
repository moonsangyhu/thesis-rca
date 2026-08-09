"""V2.3 k=3/m=3 aggregation over an injected, offline-safe caller."""

from __future__ import annotations

import json
import math
import statistics
from collections import Counter
from dataclasses import dataclass, replace
from typing import Callable

from .config import K_GENERATIONS, M_JUDGES, PRIMARY_THRESHOLD, ROBUSTNESS_THRESHOLDS
from .conditions import AssembledCondition
from .ledger import CallLedger, CallLedgerEntry
from .scanner import sha256_text


@dataclass(frozen=True)
class Invocation:
    role: str
    fault_id: str
    trial: int
    condition: str
    generation_repeat: int
    judge_repeat: int | None
    prompt: str
    context: AssembledCondition


@dataclass(frozen=True)
class InvocationResult:
    payload: dict
    ledger_entry: CallLedgerEntry


Caller = Callable[[Invocation], InvocationResult]


def majority(labels: list[str]) -> tuple[str, float, bool]:
    if not labels:
        raise ValueError("generation labels are empty")
    counts = Counter(labels)
    top = max(counts.values())
    winners = {label for label, count in counts.items() if count == top}
    selected = next(label for label in labels if label in winners)
    return selected, top / len(labels), len(winners) > 1


class RCAEngineV2_3:
    def __init__(
        self, caller: Caller, ledger: CallLedger | None = None,
        campaign_id: str = "offline-unspecified",
    ):
        self.caller = caller
        self.ledger = ledger or CallLedger()
        self.campaign_id = campaign_id

    def analyze_condition(
        self, context: AssembledCondition, fault_id: str, trial: int, *, judge_reference: str
    ) -> dict:
        if not judge_reference.strip():
            raise ValueError("sealed judge reference is required")
        generated: list[dict] = []
        votes: list[list[float]] = []
        for generation_repeat in range(1, K_GENERATIONS + 1):
            invocation = Invocation(
                "generator", fault_id, trial, context.condition,
                generation_repeat, None, context.full_context, context,
            )
            result = self.caller(invocation)
            self._validate_generator_payload(result.payload)
            self.ledger.append(result.ledger_entry, invocation, context)
            generated.append(result.payload)
            diagnosis = json.dumps(result.payload, sort_keys=True, ensure_ascii=False)
            sample_votes: list[float] = []
            for judge_repeat in range(1, M_JUDGES + 1):
                judge_prompt = json.dumps(
                    {
                        "rubric": (
                            "Score 0..1 using only agreement between the sealed reference "
                            "and candidate diagnosis. Do not infer or identify experiment arms."
                        ),
                        "sealed_reference": judge_reference,
                        "candidate_diagnosis": result.payload,
                    },
                    sort_keys=True,
                    ensure_ascii=False,
                )
                absent_hash = sha256_text("")
                blinded_context = replace(
                    context,
                    condition="blinded",
                    runtime_context="", additional_context="", full_context="",
                    runtime_context_hash=absent_hash,
                    additional_context_hash=absent_hash,
                    full_context_hash=absent_hash,
                    common_prompt_hash=absent_hash,
                    retrieval_provenance=None,
                )
                model_call = Invocation(
                    "judge", "BLINDED", 0, "blinded",
                    generation_repeat, judge_repeat, judge_prompt, blinded_context,
                )
                judged = self.caller(model_call)
                score = self._validate_judge_payload(judged.payload)
                corrected_entry = replace(
                    judged.ledger_entry,
                    fault_id=fault_id,
                    trial=trial,
                    context_condition=context.condition,
                    linked_runtime_context_hash=context.runtime_context_hash,
                    linked_additional_context_hash=context.additional_context_hash,
                    linked_full_context_hash=context.full_context_hash,
                )
                ledger_call = replace(
                    model_call, fault_id=fault_id, trial=trial, condition=context.condition
                )
                self.ledger.append(corrected_entry, ledger_call, context)
                sample_votes.append(score)
            votes.append(sample_votes)

        labels = [str(item.get("identified_fault_type", "")) for item in generated]
        selected, agreement, split = majority(labels)
        sample_medians = [statistics.median(v) for v in votes]
        selected_indices = [i for i, label in enumerate(labels) if label == selected]
        aggregate_score = statistics.median(sample_medians[i] for i in selected_indices)
        representative_index = min(
            selected_indices,
            key=lambda i: (abs(sample_medians[i] - aggregate_score), i),
        )
        representative_sample_score = sample_medians[representative_index]
        representative_score = aggregate_score
        representative = generated[representative_index]
        thresholds = (PRIMARY_THRESHOLD,) + ROBUSTNESS_THRESHOLDS
        return {
            "campaign_id": self.campaign_id,
            "fault_id": fault_id,
            "trial": trial,
            "context_condition": context.condition,
            "majority_label": selected,
            "generation_labels": labels,
            "generation_agreement": agreement,
            "generation_split": split,
            "judge_votes": votes,
            "sample_judge_medians": sample_medians,
            "representative_score": representative_score,
            "selected_label_aggregate_score": aggregate_score,
            "representative_generation_repeat": representative_index + 1,
            "representative_sample_score": representative_sample_score,
            "representative_output": representative,
            **{f"correct_at_{threshold}": int(representative_score >= threshold)
               for threshold in thresholds},
            "runtime_context_hash": context.runtime_context_hash,
            "additional_context_hash": context.additional_context_hash,
            "full_context_hash": context.full_context_hash,
        }

    @staticmethod
    def _validate_generator_payload(payload: dict) -> None:
        if not isinstance(payload, dict):
            raise ValueError("generator payload must be an object")
        if set(payload) != {"identified_fault_type", "root_cause", "remediation"}:
            raise ValueError("generator payload schema mismatch")
        if not isinstance(payload.get("identified_fault_type"), str) or not payload[
            "identified_fault_type"
        ].strip():
            raise ValueError("generator payload has no fault type")
        if not isinstance(payload.get("root_cause"), str) or not payload["root_cause"].strip():
            raise ValueError("generator payload has no root cause")
        remediation = payload.get("remediation")
        if not isinstance(remediation, list) or not remediation or not all(
            isinstance(item, str) and item.strip() for item in remediation
        ):
            raise ValueError("generator remediation must be a non-empty string list")

    @staticmethod
    def _validate_judge_payload(payload: dict) -> float:
        if not isinstance(payload, dict) or set(payload) != {"correctness_score"}:
            raise ValueError("judge payload schema mismatch")
        value = payload["correctness_score"]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("judge correctness score must be numeric")
        score = float(value)
        if not math.isfinite(score) or not 0.0 <= score <= 1.0:
            raise ValueError("judge correctness score must be finite and within [0,1]")
        return score

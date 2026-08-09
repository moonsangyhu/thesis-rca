"""Deterministic offline fixtures and full mock campaign."""

from __future__ import annotations

import hashlib
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .conditions import ConditionAssembler, latin_square_schedule, schedule_hash, text_metrics
from .config import (
    CONDITIONS, EXPECTED_CALLS, EXPECTED_GENERATOR_CALLS, EXPECTED_JUDGE_CALLS,
    EXPECTED_ROWS, EXPERIMENT, FAULTS, GENERATOR_OUTPUT_LIMIT,
    JUDGE_OUTPUT_LIMIT, REQUESTED_MODEL, TRIALS,
)
from .engine import Invocation, InvocationResult, RCAEngineV2_3
from .ledger import CallLedgerEntry
from .scanner import ForbiddenLexicon, sha256_text
from .retrieval import BlindProcedure, BlindProcedureBuilder, RetrievalChunk
from .storage import SafeOutputStore

BLOCK_FLAGS = ("no-tools", "no-mcp", "no-remote", "no-custom-instructions")


def clean_fixture(fault_id: str, trial: int) -> tuple[str, BlindProcedure, ForbiddenLexicon]:
    runtime = (
        f"Observed incident sample {trial}. Requests show elevated latency and a "
        "repeating warning in the frozen runtime window."
    )
    procedure_text = (
        "Neutral document. Compare the earliest timestamp with the stable baseline. "
        "Inspect neighboring signals, test one reversible hypothesis, and record the outcome."
    )
    lexicon = ForbiddenLexicon(
        canonical_labels=("memory exhaustion", "image pull failure"),
        aliases=("oomkill", "err image pull"),
        metadata=("runbooks/private-memory.md", "private memory guide"),
        entities=("secret-workload",),
        commands=("kubectl patch deployment secret-workload",),
        field_values=("resources.limits.memory=32Mi",),
        harness_markers=(fault_id, "fault injection", "experiment marker"),
    )
    procedure = BlindProcedureBuilder().build(
        runtime_context=runtime,
        runtime_query=runtime,
        chunks=(RetrievalChunk("neutral-doc", procedure_text, 0.75, 0, len(procedure_text)),),
        corpus_version="mock-corpus-v1",
        lexicon=lexicon,
    )
    return runtime, procedure, lexicon


def positive_fixture() -> tuple[str, ForbiddenLexicon]:
    lexicon = ForbiddenLexicon(
        canonical_labels=("memory exhaustion",),
        aliases=("oom-kill",),
        metadata=("runbooks/private-memory.md",),
        entities=("secret-workload",),
        commands=("kubectl patch deployment",),
        field_values=("memory 32Mi",),
        harness_markers=("F1",),
    )
    # Full-width characters and punctuation exercise NFKC/alias/n-gram folding.
    return "The ＯＯＭ—ＫＩＬＬ note says kubectl.patch/deployment secret-workload.", lexicon


class DeterministicMockCaller:
    """Manifest-producing fake. It never constructs or calls an LLM backend."""

    def __init__(self, campaign_id: str):
        self.campaign_id = campaign_id
        self.call_index = 0
        self.cumulative_aic = 0.0

    def __call__(self, invocation: Invocation) -> InvocationResult:
        self.call_index += 1
        session = f"mock-session-{self.call_index:05d}"
        if invocation.role == "generator":
            labels = ("latency anomaly", "latency anomaly", "transient saturation")
            payload = {
                "identified_fault_type": labels[(invocation.generation_repeat - 1) % 3],
                "root_cause": "A mock-only diagnosis generated without an LLM.",
                "remediation": ["Review the frozen evidence."],
            }
            output_tokens = 40
            limit = GENERATOR_OUTPUT_LIMIT
        else:
            payload = {"correctness_score": (0.7, 0.8, 0.75)[(invocation.judge_repeat or 1) - 1]}
            output_tokens = 8
            limit = JUDGE_OUTPUT_LIMIT
        output_hash = sha256_text(str(payload))
        now = datetime.now(timezone.utc).isoformat()
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
            actual_model=REQUESTED_MODEL,
            provider="mock-copilot",
            cli_executable="mock://disabled",
            cli_version="mock-1",
            session_id=session,
            started_at=now,
            ended_at=now,
            latency_ms=0,
            exit_code=0,
            output_text_hash=output_hash,
            output_tokens=output_tokens,
            ai_credits=0.0,
            cumulative_ai_credits=self.cumulative_aic,
            premium_requests=0.0,
            system_prompt_hash=sha256_text("v2.3 mock system prompt"),
            user_prompt_hash=sha256_text(invocation.prompt),
            runtime_context_hash=invocation.context.runtime_context_hash,
            additional_context_hash=invocation.context.additional_context_hash,
            full_context_hash=invocation.context.full_context_hash,
            linked_runtime_context_hash=invocation.context.runtime_context_hash,
            linked_additional_context_hash=invocation.context.additional_context_hash,
            linked_full_context_hash=invocation.context.full_context_hash,
            requested_output_limit=limit,
            block_flags=BLOCK_FLAGS,
            block_flags_hash=sha256_text("\n".join(BLOCK_FLAGS)),
            temporary_cwd_id=f"mock-cwd-{self.call_index:05d}",
            tool_event_count=0,
            mcp_event_count=0,
            remote_event_count=0,
            custom_instruction_event_count=0,
            input_chars=metrics["chars"],
            input_bytes=metrics["bytes"],
            input_proxy_tokens=metrics["proxy_tokens"],
        )
        return InvocationResult(payload, entry)


def _execute(output_dir: Path | None) -> dict:
    campaign_id = "mock-v2-3-offline"
    caller = DeterministicMockCaller(campaign_id)
    engine = RCAEngineV2_3(caller, campaign_id=campaign_id)
    assembler = ConditionAssembler()
    store = SafeOutputStore(output_dir) if output_dir is not None else None
    schedule = latin_square_schedule()
    row_count = 0
    for fault_id in FAULTS:
        for trial in TRIALS:
            ledger_start = len(engine.ledger.entries)
            runtime, procedure, lexicon = clean_fixture(fault_id, trial)
            contexts = assembler.assemble_all(runtime, procedure, lexicon)
            incident_rows: list[dict] = []
            incident_raws: list[dict] = []
            for condition in schedule[(fault_id, trial)]:
                row = engine.analyze_condition(
                    contexts[condition], fault_id, trial,
                    judge_reference=f"sealed mock reference {fault_id}",
                )
                raw = {
                    **row,
                    "schedule_order": schedule[(fault_id, trial)],
                    "schedule_hash": schedule_hash(schedule),
                    "scanner": contexts[condition].scan_report.to_dict(),
                    "retrieval_provenance": contexts[condition].retrieval_provenance,
                }
                incident_rows.append(row)
                incident_raws.append(raw)
                row_count += 1
            if store is not None:
                incident_entries = [
                    entry.to_dict() for entry in engine.ledger.entries[ledger_start:]
                ]
                for raw in incident_raws:
                    condition = raw["context_condition"]
                    raw["call_ledger"] = [
                        entry for entry in incident_entries
                        if entry["context_condition"] == condition
                    ]
                store.write_incident(incident_rows, incident_raws, incident_entries)
    entries = [entry.to_dict() for entry in engine.ledger.entries]
    roles = [entry["role"] for entry in entries]
    summary = {
        "rows": row_count,
        "calls": len(entries),
        "generator_calls": roles.count("generator"),
        "judge_calls": roles.count("judge"),
        "schedule_hash": schedule_hash(schedule),
        "output_dir": str(output_dir) if output_dir is not None else None,
    }
    expected = (EXPECTED_ROWS, EXPECTED_CALLS, EXPECTED_GENERATOR_CALLS, EXPECTED_JUDGE_CALLS)
    actual = (summary["rows"], summary["calls"], summary["generator_calls"], summary["judge_calls"])
    if actual != expected:
        raise AssertionError(f"mock manifest mismatch: expected={expected}, actual={actual}")
    return summary


def run_mock_campaign(output_dir: Path | None = None) -> dict:
    """Run the complete mock campaign in an explicit dir or an auto tempfile."""
    if output_dir is not None:
        return _execute(Path(output_dir))
    with tempfile.TemporaryDirectory(prefix="v2_3_mock_") as temp_dir:
        summary = _execute(Path(temp_dir))
        summary["output_dir"] = None
        summary["temporary_output_cleaned"] = True
        return summary


def run_dry_run() -> dict:
    """Validate the full manifest entirely in memory (zero filesystem writes)."""
    summary = _execute(None)
    summary["filesystem_writes"] = 0
    summary["external_calls"] = 0
    return summary

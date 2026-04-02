#!/usr/bin/env python3
"""
Main experiment runner for GitOps-Aware K8s RCA thesis.

Protocol per trial:
  1. Inject fault (F1~F10)
  2. Wait for symptoms to manifest (2-5 min)
  3. Collect signals
  4. Run RCA System A (observability only)
  5. Run RCA System B (+ GitOps context + RAG)
  6. Record results
  7. Recover and stabilize (+ 30 min cooldown between fault types)

Usage:
    # Run all 50 trials
    python -m scripts.run_experiment

    # Run specific fault type
    python -m scripts.run_experiment --fault F1

    # Run specific trial
    python -m scripts.run_experiment --fault F1 --trial 3

    # Dry run (no injection, only collection test)
    python -m scripts.run_experiment --dry-run
"""
import argparse
import csv
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.collector import SignalCollector
from src.processor import ContextBuilder
from src.llm import RCAEngine
from src.rag.retriever import KnowledgeRetriever
from scripts.fault_inject import FaultInjector, INJECTION_WAIT
from scripts.stabilize import Recovery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(PROJECT_ROOT / "results" / "experiment.log"),
    ],
)
logger = logging.getLogger("experiment")

# Result CSV path
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_CSV = RESULTS_DIR / "experiment_results.csv"
RESULTS_CSV_V2 = RESULTS_DIR / "experiment_results_v2.csv"
RAW_DIR = RESULTS_DIR / "raw"

# All fault types and trials
ALL_FAULTS = [f"F{i}" for i in range(1, 11)]
ALL_TRIALS = [1, 2, 3, 4, 5]

CSV_HEADERS = [
    "timestamp", "fault_id", "trial", "system",
    "identified_fault_type", "correct", "root_cause",
    "confidence", "affected_components", "remediation",
    "model", "latency_ms", "prompt_tokens", "completion_tokens",
    "error",
]

CSV_HEADERS_V2 = [
    "timestamp", "fault_id", "trial", "system",
    "identified_fault_type", "correct",
    "root_cause", "root_cause_ko",
    "confidence", "confidence_2nd",
    "affected_components",
    "remediation", "remediation_ko",
    "detail", "detail_ko",
    "reasoning",
    "evidence_chain", "alternative_hypotheses",
    "abstained", "abstention_reason", "faithfulness_score",
    "model", "latency_ms", "prompt_tokens", "completion_tokens",
    "error",
]


def _print_signal_summary(signals: dict):
    """Print a summary of collected signals for dry-run verification."""
    for key, value in signals.items():
        if isinstance(value, dict):
            non_empty = sum(1 for v in value.values() if v)
            total = len(value)
            logger.info("  %s: %d/%d fields populated", key, non_empty, total)
        elif isinstance(value, list):
            logger.info("  %s: %d items", key, len(value))
        elif isinstance(value, str):
            logger.info("  %s: %d chars", key, len(value))
        else:
            logger.info("  %s: %s", key, type(value).__name__)


def ensure_dirs():
    """Ensure output directories exist."""
    RESULTS_DIR.mkdir(exist_ok=True)
    RAW_DIR.mkdir(exist_ok=True)


def init_csv(version="v1"):
    """Initialize results CSV if not exists."""
    csv_path = RESULTS_CSV_V2 if version == "v2" else RESULTS_CSV
    headers = CSV_HEADERS_V2 if version == "v2" else CSV_HEADERS
    if not csv_path.exists():
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()


def append_result(result: dict, version="v1"):
    """Append a single result row to CSV."""
    csv_path = RESULTS_CSV_V2 if version == "v2" else RESULTS_CSV
    headers = CSV_HEADERS_V2 if version == "v2" else CSV_HEADERS
    with open(csv_path, "a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        row = {k: result.get(k, "") for k in headers}
        # Convert lists to pipe-delimited strings
        for key in ["affected_components", "remediation", "remediation_ko"]:
            if isinstance(row.get(key), list):
                row[key] = "|".join(str(x) for x in row[key])
        # Convert dicts/lists to JSON strings
        for key in ["evidence_chain", "alternative_hypotheses"]:
            if isinstance(row.get(key), (list, dict)):
                row[key] = json.dumps(row[key], ensure_ascii=False)
        # Truncate reasoning for CSV (full version in raw JSON)
        if isinstance(row.get("reasoning"), str) and len(row["reasoning"]) > 200:
            row["reasoning"] = row["reasoning"][:200] + "..."
        writer.writerow(row)


def save_raw(fault_id: str, trial: int, system: str, data: dict):
    """Save raw data (signals, context, LLM response) as JSON."""
    filename = f"{fault_id}_t{trial}_{system}_{datetime.now():%Y%m%d_%H%M%S}.json"
    filepath = RAW_DIR / filename
    with open(filepath, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2, default=str)
    logger.info("Raw data saved: %s", filepath)


def run_single_trial(
    fault_id: str,
    trial: int,
    injector: FaultInjector,
    recovery: Recovery,
    collector: SignalCollector,
    builder: ContextBuilder,
    engine: RCAEngine,
    retriever: KnowledgeRetriever,
    dry_run: bool = False,
    version: str = "v1",
):
    """Run a single trial: inject → collect → RCA(A/B) → record → recover."""
    logger.info("=" * 60)
    logger.info("Starting %s trial %d", fault_id, trial)
    logger.info("=" * 60)

    # ── Step 1: Inject ──
    injection_result = {}
    if not dry_run:
        try:
            injection_result = injector.inject(fault_id, trial)
            logger.info("Injection result: %s", injection_result.get("action", ""))
        except Exception as e:
            logger.error("Injection failed: %s", e)
            return

        # ── Step 2: Wait ──
        wait = injection_result.get("wait_seconds", 120)
        logger.info("Waiting %ds for symptoms to manifest...", wait)
        time.sleep(wait)
    else:
        logger.info("[DRY RUN] Skipping injection")

    # ── Step 3: Collect signals ──
    logger.info("Collecting signals...")
    try:
        all_signals = collector.collect_all(window_minutes=5)
        obs_signals = collector.collect_observability_only(window_minutes=5)
    except Exception as e:
        logger.error("Signal collection failed: %s", e)
        all_signals = {}
        obs_signals = {}

    # ── Step 4: RAG retrieval (for System B) ──
    rag_context = ""
    if not dry_run and retriever is not None:
        try:
            docs = retriever.query_by_fault(fault_id)
            rag_context = retriever.format_context(docs)
            logger.info("RAG retrieved %d docs for %s", len(docs), fault_id)
        except Exception as e:
            logger.warning("RAG retrieval failed: %s", e)

    # ── Step 5: Build context for A and B ──
    ctx_a = builder.build(
        obs_signals, fault_id=fault_id, trial=trial, system="A",
    )
    ctx_b = builder.build(
        all_signals, fault_id=fault_id, trial=trial, system="B",
        rag_context=rag_context,
    )

    if dry_run:
        # Dry run: just print collected signal summary and return
        logger.info("[DRY RUN] Signal collection complete.")
        logger.info("[DRY RUN] System A context length: %d chars", len(ctx_a.to_context()))
        logger.info("[DRY RUN] System B context length: %d chars", len(ctx_b.to_context()))
        _print_signal_summary(all_signals)
        return

    # ── Step 6: Run RCA System A ──
    logger.info("Running RCA System A (observability only)...")
    result_a = engine.analyze(
        ctx_a.to_context(), fault_id=fault_id, trial=trial, system="A",
    )
    logger.info(
        "System A: predicted=%s, confidence=%.2f",
        result_a.identified_fault_type, result_a.confidence,
    )

    # ── Step 7: Run RCA System B ──
    logger.info("Running RCA System B (+ GitOps + RAG)...")
    result_b = engine.analyze(
        ctx_b.to_context(), fault_id=fault_id, trial=trial, system="B",
    )
    logger.info(
        "System B: predicted=%s, confidence=%.2f",
        result_b.identified_fault_type, result_b.confidence,
    )

    # ── Step 8: Record results ──
    timestamp = datetime.now().isoformat()

    for result, system in [(result_a, "A"), (result_b, "B")]:
        row = result.to_dict()
        row["timestamp"] = timestamp
        if result.abstained:
            row["correct"] = -1  # abstained
        else:
            row["correct"] = 1 if result.identified_fault_type == fault_id else 0
        append_result(row, version=version)

    # Save raw data
    save_raw(fault_id, trial, "A", {
        "signals": obs_signals,
        "context": ctx_a.to_context(),
        "rca_output": result_a.to_dict(),
        "raw_response": result_a.raw_response,
    })
    save_raw(fault_id, trial, "B", {
        "signals": all_signals,
        "context": ctx_b.to_context(),
        "rag_docs": [{"source": d.short_source, "score": d.score} for d in retriever.query_by_fault(fault_id)],
        "rca_output": result_b.to_dict(),
        "raw_response": result_b.raw_response,
    })

    # ── Step 9: Recover ──
    if not dry_run:
        logger.info("Recovering from fault...")
        try:
            recovery.recover(fault_id, trial, injection_result)
            logger.info("Recovery complete")
        except Exception as e:
            logger.error("Recovery failed: %s — manual intervention may be needed", e)

    logger.info(
        "Trial complete: %s t%d | A: %s (%.2f) %s | B: %s (%.2f) %s",
        fault_id, trial,
        result_a.identified_fault_type, result_a.confidence,
        "✓" if result_a.identified_fault_type == fault_id else "✗",
        result_b.identified_fault_type, result_b.confidence,
        "✓" if result_b.identified_fault_type == fault_id else "✗",
    )


def main():
    parser = argparse.ArgumentParser(description="Run RCA experiment trials")
    parser.add_argument("--fault", type=str, help="Specific fault type (e.g. F1)")
    parser.add_argument("--trial", type=int, help="Specific trial number (1-5)")
    parser.add_argument("--model", type=str, default="gpt-4o-mini")
    parser.add_argument("--provider", type=str, default="openai")
    parser.add_argument("--dry-run", action="store_true", help="Skip injection, test collection only")
    parser.add_argument("--cooldown", type=int, default=900, help="Cooldown between fault types (seconds, default 900=15min)")
    parser.add_argument("--version", type=str, default="v2", choices=["v1", "v2"],
                        help="Experiment version (v1=original, v2=harness+CoT+bilingual)")
    args = parser.parse_args()

    ensure_dirs()
    init_csv(version=args.version)

    # Initialize components
    logger.info("Initializing experiment components...")
    injector = FaultInjector()
    recovery = Recovery()
    collector = SignalCollector()
    builder = ContextBuilder()
    if args.dry_run:
        engine = None
        retriever = None
    else:
        engine = RCAEngine(
            model=args.model, provider=args.provider,
            prompt_version=args.version,
        )
        retriever = KnowledgeRetriever()

    # Determine which trials to run
    faults = [args.fault] if args.fault else ALL_FAULTS
    trials = [args.trial] if args.trial else ALL_TRIALS

    total = len(faults) * len(trials)
    completed = 0

    logger.info("Experiment plan: %d trials (%s × %s)", total, faults, trials)
    logger.info("Model: %s (%s), version: %s", args.model, args.provider, args.version)
    logger.info("Dry run: %s", args.dry_run)

    for fault_id in faults:
        for trial in trials:
            try:
                run_single_trial(
                    fault_id, trial,
                    injector, recovery, collector, builder, engine, retriever,
                    dry_run=args.dry_run,
                    version=args.version,
                )
                completed += 1
                logger.info("Progress: %d/%d trials complete", completed, total)
            except Exception as e:
                logger.error("Trial %s t%d FAILED: %s", fault_id, trial, e)
                completed += 1

            # Short cooldown between trials of same fault type
            if trial < max(trials) and not args.dry_run:
                logger.info("Short cooldown (60s) between trials...")
                time.sleep(60)

        # Long cooldown between different fault types
        if fault_id != faults[-1] and not args.dry_run:
            logger.info(
                "Cooldown (%ds) between fault types (%s done)...",
                args.cooldown, fault_id,
            )
            time.sleep(args.cooldown)

    logger.info("=" * 60)
    logger.info("Experiment complete! %d/%d trials", completed, total)
    logger.info("Results: %s", RESULTS_CSV)
    logger.info("Raw data: %s", RAW_DIR)


if __name__ == "__main__":
    main()

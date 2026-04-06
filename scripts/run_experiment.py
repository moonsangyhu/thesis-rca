#!/usr/bin/env python3
"""
Main experiment runner for GitOps-Aware K8s RCA thesis.

DEPRECATED: Use experiments/v1/run.py, experiments/v2/run.py, experiments/v3/run.py instead.

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
import subprocess
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
RESULTS_CSV_V3 = RESULTS_DIR / "experiment_results_v3.csv"
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
    "correctness_score", "correctness_reasoning",
    "root_cause", "confidence",
    "affected_components", "remediation",
    "detail", "reasoning",
    "model", "latency_ms", "prompt_tokens", "completion_tokens",
    "error",
]

CSV_HEADERS_V3 = [
    "timestamp", "fault_id", "trial", "system",
    "identified_fault_type", "correct",
    "correctness_score", "correctness_reasoning",
    "root_cause", "root_cause_ko",
    "confidence", "confidence_2nd",
    "affected_components",
    "remediation", "remediation_ko",
    "detail", "detail_ko",
    "reasoning",
    "evidence_chain", "alternative_hypotheses",
    "faithfulness_score",
    "eval_evidence_grounding", "eval_diagnostic_logic",
    "eval_differential_completeness", "eval_confidence_calibration",
    "eval_overall_score", "eval_critique", "retry_count",
    "model", "latency_ms", "prompt_tokens", "completion_tokens",
    "error",
]


GROUND_TRUTH_CSV = RESULTS_DIR / "ground_truth.csv"
KUBECONFIG = os.environ.get("KUBECONFIG", os.path.expanduser("~/.kube/config-k8s-lab"))


def load_ground_truth(csv_path: str) -> dict:
    """Load ground truth CSV into dict keyed by (fault_id, trial)."""
    gt = {}
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            key = (row["fault_id"], int(row["trial"]))
            gt[key] = row
    return gt


def _check_port(port: int) -> bool:
    """Check if a local port is responding."""
    import urllib.request
    try:
        url = f"http://localhost:{port}/ready" if port == 3100 else f"http://localhost:{port}/api/v1/status/runtimeinfo"
        req = urllib.request.urlopen(url, timeout=5)
        return req.status == 200
    except Exception:
        return False


def _restart_port_forward(namespace: str, service: str, port: int):
    """Kill existing port-forward and restart."""
    # Kill any existing port-forward on this port
    subprocess.run(
        f"lsof -ti tcp:{port} | xargs kill -9 2>/dev/null",
        shell=True, capture_output=True,
    )
    time.sleep(1)
    subprocess.Popen(
        ["kubectl", "port-forward", "-n", namespace, f"svc/{service}", f"{port}:{port}"],
        env={**os.environ, "KUBECONFIG": KUBECONFIG},
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    time.sleep(3)
    if _check_port(port):
        logger.info("Port-forward %s:%d restarted successfully", service, port)
        return True
    logger.error("Port-forward %s:%d restart FAILED", service, port)
    return False


def preflight_check() -> bool:
    """Verify all infrastructure components before experiment starts."""
    logger.info("=" * 60)
    logger.info("PREFLIGHT CHECK")
    logger.info("=" * 60)
    ok = True

    # 1. SSH tunnel (check kubectl connectivity)
    r = subprocess.run(
        ["kubectl", "get", "nodes", "--no-headers"],
        env={**os.environ, "KUBECONFIG": KUBECONFIG},
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode == 0:
        node_count = len(r.stdout.strip().split("\n"))
        logger.info("[OK] kubectl: %d nodes reachable", node_count)
    else:
        logger.error("[FAIL] kubectl not reachable — check SSH tunnel")
        ok = False

    # 2. Boutique pods
    r = subprocess.run(
        ["kubectl", "get", "pods", "-n", "boutique", "--no-headers",
         "--field-selector=status.phase=Running"],
        env={**os.environ, "KUBECONFIG": KUBECONFIG},
        capture_output=True, text=True, timeout=10,
    )
    if r.returncode == 0:
        pod_count = len([l for l in r.stdout.strip().split("\n") if l.strip()])
        if pod_count >= 12:
            logger.info("[OK] boutique: %d pods running", pod_count)
        else:
            logger.error("[FAIL] boutique: only %d pods running (need >= 12)", pod_count)
            ok = False
    else:
        logger.error("[FAIL] cannot list boutique pods")
        ok = False

    # 3. Prometheus
    if _check_port(9090):
        logger.info("[OK] Prometheus (localhost:9090)")
    else:
        logger.warning("[WARN] Prometheus down — attempting restart...")
        if _restart_port_forward("monitoring", "kube-prometheus-stack-prometheus", 9090):
            logger.info("[OK] Prometheus recovered")
        else:
            logger.error("[FAIL] Prometheus recovery failed")
            ok = False

    # 4. Loki
    if _check_port(3100):
        logger.info("[OK] Loki (localhost:3100)")
    else:
        logger.warning("[WARN] Loki down — attempting restart...")
        if _restart_port_forward("monitoring", "loki", 3100):
            logger.info("[OK] Loki recovered")
        else:
            logger.error("[FAIL] Loki recovery failed")
            ok = False

    logger.info("=" * 60)
    if ok:
        logger.info("PREFLIGHT CHECK PASSED")
    else:
        logger.error("PREFLIGHT CHECK FAILED — fix issues before running")
    logger.info("=" * 60)
    return ok


def health_check(fault_id: str, trial: int) -> bool:
    """Quick health check before each trial. Auto-recovers port-forwards."""
    issues = []

    # Check Prometheus
    if not _check_port(9090):
        logger.warning("[HEALTH] Prometheus down before %s t%d — restarting...", fault_id, trial)
        if not _restart_port_forward("monitoring", "kube-prometheus-stack-prometheus", 9090):
            issues.append("Prometheus")

    # Check Loki
    if not _check_port(3100):
        logger.warning("[HEALTH] Loki down before %s t%d — restarting...", fault_id, trial)
        if not _restart_port_forward("monitoring", "loki", 3100):
            issues.append("Loki")

    if issues:
        logger.error("[HEALTH] FAILED for %s t%d: %s unreachable", fault_id, trial, ", ".join(issues))
        return False

    logger.info("[HEALTH] OK before %s t%d", fault_id, trial)
    return True


def _csv_path_for(version: str) -> Path:
    """Return the CSV path for a given experiment version."""
    if version == "v3":
        return RESULTS_CSV_V3
    elif version == "v2":
        return RESULTS_CSV_V2
    return RESULTS_CSV


def _csv_headers_for(version: str) -> list:
    """Return the CSV headers for a given experiment version."""
    if version == "v3":
        return CSV_HEADERS_V3
    elif version == "v2":
        return CSV_HEADERS_V2
    return CSV_HEADERS


def get_completed_trials(version="v1") -> set:
    """Read CSV and return set of (fault_id, trial) already completed."""
    csv_path = _csv_path_for(version)
    completed = set()
    if csv_path.exists():
        with open(csv_path) as f:
            for row in csv.DictReader(f):
                key = (row["fault_id"], int(row["trial"]))
                completed.add(key)
    return completed


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
    csv_path = _csv_path_for(version)
    headers = _csv_headers_for(version)
    if not csv_path.exists():
        with open(csv_path, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()


def append_result(result: dict, version="v1"):
    """Append a single result row to CSV."""
    csv_path = _csv_path_for(version)
    headers = _csv_headers_for(version)
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
    ground_truth: dict = None,
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
    gt_row = ground_truth.get((fault_id, trial), {}) if ground_truth else {}
    logger.info("Running RCA System A (observability only)...")
    result_a = engine.analyze(
        ctx_a.to_context(), fault_id=fault_id, trial=trial, system="A",
        ground_truth=gt_row,
    )
    logger.info(
        "System A: predicted=%s, confidence=%.2f",
        result_a.identified_fault_type, result_a.confidence,
    )

    # ── Step 7: Run RCA System B ──
    logger.info("Running RCA System B (+ GitOps + RAG)...")
    result_b = engine.analyze(
        ctx_b.to_context(), fault_id=fault_id, trial=trial, system="B",
        ground_truth=gt_row,
    )
    logger.info(
        "System B: predicted=%s, confidence=%.2f",
        result_b.identified_fault_type, result_b.confidence,
    )

    # ── Step 8: Record results ──
    timestamp = datetime.now().isoformat()

    for result in [result_a, result_b]:
        row = result.to_dict()
        row["timestamp"] = timestamp
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
        "Trial complete: %s t%d | A: %s (score=%.2f) %s | B: %s (score=%.2f) %s",
        fault_id, trial,
        result_a.identified_fault_type, result_a.correctness_score,
        "correct" if result_a.correct else "wrong",
        result_b.identified_fault_type, result_b.correctness_score,
        "correct" if result_b.correct else "wrong",
    )


def main():
    parser = argparse.ArgumentParser(description="Run RCA experiment trials")
    parser.add_argument("--fault", type=str, help="Specific fault type (e.g. F1)")
    parser.add_argument("--trial", type=int, help="Specific trial number (1-5)")
    parser.add_argument("--model", type=str, default="gpt-4o-mini")
    parser.add_argument("--provider", type=str, default="openai")
    parser.add_argument("--dry-run", action="store_true", help="Skip injection, test collection only")
    parser.add_argument("--cooldown", type=int, default=900, help="Cooldown between fault types (seconds, default 900=15min)")
    parser.add_argument("--version", type=str, default="v2", choices=["v1", "v2", "v3"],
                        help="v1=힌트+단순, v2=힌트제거+CoT, v3=v2+Harness(Evaluator+Retry)")
    parser.add_argument("--resume", action="store_true",
                        help="Skip already-completed trials (based on CSV)")
    parser.add_argument("--no-preflight", action="store_true",
                        help="Skip preflight check")
    args = parser.parse_args()

    ensure_dirs()
    init_csv(version=args.version)

    # Preflight check
    if not args.no_preflight and not args.dry_run:
        if not preflight_check():
            logger.error("Aborting due to preflight failure. Use --no-preflight to skip.")
            sys.exit(1)

    # Resume: load completed trials
    completed_trials = set()
    if args.resume:
        completed_trials = get_completed_trials(version=args.version)
        if completed_trials:
            logger.info("Resume mode: %d trials already completed, will skip them", len(completed_trials))

    # Load ground truth for LLM-as-judge correctness evaluation
    ground_truth = {}
    if GROUND_TRUTH_CSV.exists():
        ground_truth = load_ground_truth(str(GROUND_TRUTH_CSV))
        logger.info("Loaded ground truth: %d entries", len(ground_truth))
    else:
        logger.warning("Ground truth CSV not found: %s", GROUND_TRUTH_CSV)

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
            # Resume: skip completed trials
            if (fault_id, trial) in completed_trials:
                logger.info("Skipping %s t%d (already completed)", fault_id, trial)
                completed += 1
                continue

            # Health check before each trial (auto-recover port-forwards)
            if not args.dry_run:
                if not health_check(fault_id, trial):
                    logger.error("Health check failed for %s t%d — retrying once in 10s...", fault_id, trial)
                    time.sleep(10)
                    if not health_check(fault_id, trial):
                        logger.error("Health check failed again for %s t%d — SKIPPING", fault_id, trial)
                        completed += 1
                        continue

            try:
                run_single_trial(
                    fault_id, trial,
                    injector, recovery, collector, builder, engine, retriever,
                    dry_run=args.dry_run,
                    version=args.version,
                    ground_truth=ground_truth,
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
    logger.info("Results: %s", _csv_path_for(args.version))
    logger.info("Raw data: %s", RAW_DIR)


if __name__ == "__main__":
    main()

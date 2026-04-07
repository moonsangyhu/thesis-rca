#!/usr/bin/env python3
"""
v4 실험 실행: Context Reranking + Fault Layer Prompt + Harness Simplification.

Usage:
    python -m experiments.v4.run
    python -m experiments.v4.run --fault F1 --trial 3
    python -m experiments.v4.run --dry-run
"""
import argparse
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.collector import SignalCollector
from src.rag.retriever import KnowledgeRetriever
from scripts.fault_inject import FaultInjector, INJECTION_WAIT
from scripts.stabilize import Recovery

from experiments.shared.csv_io import init_csv, get_completed_trials, load_ground_truth
from experiments.shared.infra import preflight_check, health_check
from experiments.shared.runner import TrialRunner, ALL_FAULTS, ALL_TRIALS
from .engine import RCAEngineV4
from .context_builder import ContextBuilderV4
from .config import RESULTS_CSV, RAW_DIR, GROUND_TRUTH_CSV, CSV_HEADERS, RESULTS_DIR

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(RESULTS_DIR / "experiment_v4.log"),
    ],
)
logger = logging.getLogger("experiment.v4")


def main():
    parser = argparse.ArgumentParser(description="v4 RCA experiment: Context Reranking + Fault Layer")
    parser.add_argument("--fault", type=str, help="Specific fault type (e.g. F1)")
    parser.add_argument("--trial", type=int, help="Specific trial number (1-5)")
    parser.add_argument("--model", type=str, default="gpt-4o-mini")
    parser.add_argument("--provider", type=str, default="openai")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--cooldown", type=int, default=900)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--no-preflight", action="store_true")
    args = parser.parse_args()

    RESULTS_DIR.mkdir(exist_ok=True)
    RAW_DIR.mkdir(exist_ok=True)
    init_csv(RESULTS_CSV, CSV_HEADERS)

    if not args.no_preflight and not args.dry_run:
        if not preflight_check():
            logger.error("Aborting due to preflight failure.")
            sys.exit(1)

    completed_trials = set()
    if args.resume:
        completed_trials = get_completed_trials(RESULTS_CSV)
        if completed_trials:
            logger.info("Resume: %d trials already completed", len(completed_trials))

    ground_truth = {}
    if GROUND_TRUTH_CSV.exists():
        ground_truth = load_ground_truth(GROUND_TRUTH_CSV)
        logger.info("Loaded ground truth: %d entries", len(ground_truth))

    # Initialize
    injector = FaultInjector()
    recovery = Recovery()
    collector = SignalCollector()
    builder = ContextBuilderV4()  # V4 context builder

    if args.dry_run:
        engine = None
        retriever = None
    else:
        engine = RCAEngineV4(model=args.model, provider=args.provider)
        retriever = KnowledgeRetriever()

    runner = TrialRunner(
        engine=engine,
        csv_path=RESULTS_CSV,
        csv_headers=CSV_HEADERS,
        raw_dir=RAW_DIR,
        injector=injector,
        recovery=recovery,
        collector=collector,
        builder=builder,
        retriever=retriever,
    )

    faults = [args.fault] if args.fault else ALL_FAULTS
    trials = [args.trial] if args.trial else ALL_TRIALS
    total = len(faults) * len(trials)
    completed = 0

    logger.info("v4 experiment: %d trials (%s × %s)", total, faults, trials)
    logger.info("Model: %s (%s)", args.model, args.provider)
    logger.info("V4 changes: Context Reranking + Fault Layer Prompt + Harness Simplification")

    for fault_id in faults:
        for trial in trials:
            if (fault_id, trial) in completed_trials:
                logger.info("Skipping %s t%d (already completed)", fault_id, trial)
                completed += 1
                continue

            if not args.dry_run:
                if not health_check(fault_id, trial):
                    logger.error("Health check failed for %s t%d — retrying in 10s...", fault_id, trial)
                    time.sleep(10)
                    if not health_check(fault_id, trial):
                        logger.error("Health check failed again — SKIPPING %s t%d", fault_id, trial)
                        completed += 1
                        continue

            try:
                runner.run_trial(fault_id, trial, dry_run=args.dry_run, ground_truth=ground_truth)
                completed += 1
                logger.info("Progress: %d/%d", completed, total)
            except Exception as e:
                logger.error("Trial %s t%d FAILED: %s", fault_id, trial, e)
                completed += 1

            if trial < max(trials) and not args.dry_run:
                logger.info("Short cooldown (60s) + cluster stabilization check...")
                time.sleep(60)
                for attempt in range(3):
                    if health_check(fault_id, trial):
                        break
                    logger.warning("Cluster not healthy after trial, waiting 30s (attempt %d/3)...", attempt + 1)
                    time.sleep(30)
                else:
                    logger.error("Cluster still unhealthy after 3 attempts — proceeding anyway")

        if fault_id != faults[-1] and not args.dry_run:
            logger.info("Fault transition: cleaning up failed pods...")
            import subprocess as _sp
            _sp.run(
                ["kubectl", "delete", "pods", "-n", "boutique",
                 "--field-selector=status.phase=Failed"],
                env={**__import__("os").environ,
                     "KUBECONFIG": __import__("os").environ.get("KUBECONFIG", "~/.kube/config-k8s-lab")},
                capture_output=True, timeout=30,
            )
            logger.info("Cooldown (%ds) between fault types...", args.cooldown)
            time.sleep(args.cooldown)
            for attempt in range(3):
                if health_check(faults[faults.index(fault_id) + 1], 0):
                    break
                logger.warning("Cluster not ready for next fault type, waiting 60s (attempt %d/3)...", attempt + 1)
                time.sleep(60)
            else:
                logger.error("Cluster still unhealthy after fault transition — proceeding anyway")

    logger.info("=" * 60)
    logger.info("v4 experiment complete! %d/%d trials", completed, total)
    logger.info("Results: %s", RESULTS_CSV)


if __name__ == "__main__":
    main()

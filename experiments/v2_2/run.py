#!/usr/bin/env python3
"""V2.2 experiment: 5-arm ablation + self-consistency (k=3) + blinded judge (m=3).

Usage:
    python -m experiments.v2_2.run                       # full (needs cluster + API key)
    python -m experiments.v2_2.run --fault F1 --trial 1
    python -m experiments.v2_2.run --dry-run             # mock signals, no LLM
    python -m experiments.v2_2.run --mock                # offline: mock signals + mock LLM
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

from experiments.shared.csv_io import init_csv, load_ground_truth
from .engine import RCAEngineV2_2
from .runner_v2_2 import TrialRunnerV2_2, ALL_FAULTS, ALL_TRIALS
from .config import RESULTS_CSV, RAW_DIR, GROUND_TRUTH_CSV, CSV_HEADERS, RESULTS_DIR
from . import mock as mockmod

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("experiment.v2_2")


def _build_mock_engine(model: str) -> RCAEngineV2_2:
    """Construct engine without touching the real API client, then install mocks."""
    engine = RCAEngineV2_2.__new__(RCAEngineV2_2)
    engine.model = model
    engine.provider = "openai"
    engine._client = None
    mockmod.install_mock_llm(engine)
    return engine


def main():
    parser = argparse.ArgumentParser(description="V2.2 5-arm ablation RCA experiment")
    parser.add_argument("--fault", type=str)
    parser.add_argument("--trial", type=int)
    parser.add_argument("--model", type=str, default="gpt-4o-mini")
    parser.add_argument("--provider", type=str, default="openai")
    parser.add_argument("--dry-run", action="store_true",
                        help="mock signals, build arms, no LLM calls")
    parser.add_argument("--mock", action="store_true",
                        help="fully offline: mock signals + mock LLM, runs whole pipeline")
    parser.add_argument("--cooldown", type=int, default=900)
    args = parser.parse_args()

    RESULTS_DIR.mkdir(exist_ok=True)
    RAW_DIR.mkdir(exist_ok=True)
    init_csv(RESULTS_CSV, CSV_HEADERS)

    ground_truth = {}
    if GROUND_TRUTH_CSV.exists():
        ground_truth = load_ground_truth(GROUND_TRUTH_CSV)
        logger.info("Loaded ground truth: %d entries", len(ground_truth))

    offline = args.mock or args.dry_run

    # ── builder is always needed ──
    from src.processor import ContextBuilder
    builder = ContextBuilder()

    if args.mock:
        engine = _build_mock_engine(args.model)
        injector = recovery = collector = retriever = validator = None
        mock_signals_dict = None  # set per-fault below
    elif args.dry_run:
        engine = None
        from src.collector import SignalCollector
        collector = SignalCollector()
        injector = recovery = retriever = validator = None
        mock_signals_dict = None
    else:
        from src.collector import SignalCollector
        from src.rag.retriever import KnowledgeRetriever
        from scripts.fault_inject import FaultInjector
        from scripts.stabilize import Recovery
        from scripts.stabilize.state_validator import StateValidator
        engine = RCAEngineV2_2(model=args.model, provider=args.provider)
        injector = FaultInjector()
        recovery = Recovery()
        collector = SignalCollector()
        retriever = KnowledgeRetriever()
        validator = StateValidator(ground_truth=ground_truth)
        mock_signals_dict = None

    faults = [args.fault] if args.fault else ALL_FAULTS
    trials = [args.trial] if args.trial else ALL_TRIALS

    logger.info("V2.2 experiment: faults=%s trials=%s mock=%s dry_run=%s",
                faults, trials, args.mock, args.dry_run)

    for fault_id in faults:
        ms = mockmod.mock_signals(fault_id) if offline else None
        runner = TrialRunnerV2_2(
            engine=engine,
            csv_path=RESULTS_CSV,
            csv_headers=CSV_HEADERS,
            raw_dir=RAW_DIR,
            injector=injector,
            recovery=recovery,
            collector=collector,
            builder=builder,
            retriever=retriever,
            validator=validator,
            mock_signals=ms,
        )
        for trial in trials:
            try:
                runner.run_trial(
                    fault_id, trial,
                    dry_run=args.dry_run, mock=args.mock,
                    ground_truth=ground_truth,
                )
            except Exception as e:
                logger.error("Trial %s t%d FAILED: %s", fault_id, trial, e, exc_info=True)

            if not offline and trial < max(trials):
                logger.info("Cooldown 60s...")
                time.sleep(60)

        if not offline and fault_id != faults[-1]:
            logger.info("Fault-type cooldown %ds...", args.cooldown)
            time.sleep(args.cooldown)

    logger.info("=" * 60)
    logger.info("V2.2 run complete. Results: %s", RESULTS_CSV)


if __name__ == "__main__":
    main()

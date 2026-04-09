"""Shared trial runner: inject → collect → build context → RCA → record → recover."""
import logging
import time
from datetime import datetime
from pathlib import Path

from .csv_io import append_result, save_raw

logger = logging.getLogger(__name__)

ALL_FAULTS = [f"F{i}" for i in range(1, 13)]
ALL_TRIALS = [1, 2, 3, 4, 5]


class TrialRunner:
    """Orchestrate experiment trials with a version-specific engine."""

    def __init__(
        self,
        engine,           # version-specific RCAEngine
        csv_path: Path,
        csv_headers: list[str],
        raw_dir: Path,
        injector=None,
        recovery=None,
        collector=None,
        builder=None,
        retriever=None,
    ):
        self.engine = engine
        self.csv_path = csv_path
        self.csv_headers = csv_headers
        self.raw_dir = raw_dir
        self.injector = injector
        self.recovery = recovery
        self.collector = collector
        self.builder = builder
        self.retriever = retriever

    def run_trial(
        self,
        fault_id: str,
        trial: int,
        dry_run: bool = False,
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
                injection_result = self.injector.inject(fault_id, trial)
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
            all_signals = self.collector.collect_all(window_minutes=5)
            obs_signals = self.collector.collect_observability_only(window_minutes=5)
        except Exception as e:
            logger.error("Signal collection failed: %s", e)
            all_signals = {}
            obs_signals = {}

        # ── Step 4: RAG retrieval (for System B) ──
        rag_context = ""
        if not dry_run and self.retriever is not None:
            try:
                docs = self.retriever.query_by_fault(fault_id)
                rag_context = self.retriever.format_context(docs)
                logger.info("RAG retrieved %d docs for %s", len(docs), fault_id)
            except Exception as e:
                logger.warning("RAG retrieval failed: %s", e)

        # ── Step 5: Build context for A and B ──
        ctx_a = self.builder.build(
            obs_signals, fault_id=fault_id, trial=trial, system="A",
        )
        ctx_b = self.builder.build(
            all_signals, fault_id=fault_id, trial=trial, system="B",
            rag_context=rag_context,
        )

        if dry_run:
            logger.info("[DRY RUN] Signal collection complete.")
            logger.info("[DRY RUN] System A context length: %d chars", len(ctx_a.to_context()))
            logger.info("[DRY RUN] System B context length: %d chars", len(ctx_b.to_context()))
            self._print_signal_summary(all_signals)
            return

        # ── Step 6: Run RCA System A ──
        gt_row = ground_truth.get((fault_id, trial), {}) if ground_truth else {}
        logger.info("Running RCA System A (observability only)...")
        result_a = self.engine.analyze(
            ctx_a.to_context(), fault_id=fault_id, trial=trial, system="A",
            ground_truth=gt_row,
        )
        logger.info(
            "System A: predicted=%s, confidence=%.2f",
            result_a.identified_fault_type, result_a.confidence,
        )

        # ── Step 7: Run RCA System B ──
        logger.info("Running RCA System B (+ GitOps + RAG)...")
        result_b = self.engine.analyze(
            ctx_b.to_context(), fault_id=fault_id, trial=trial, system="B",
            ground_truth=gt_row,
        )
        logger.info(
            "System B: predicted=%s, confidence=%.2f",
            result_b.identified_fault_type, result_b.confidence,
        )

        # ── Step 8: Record results + verify ──
        timestamp = datetime.now().isoformat()
        for result in [result_a, result_b]:
            row = result.to_dict()
            row["timestamp"] = timestamp
            # Count rows before
            before = self._count_csv_rows()
            append_result(row, self.csv_path, self.csv_headers)
            after = self._count_csv_rows()
            if after <= before:
                logger.error(
                    "CSV write verification FAILED for %s t%d %s (before=%d, after=%d)",
                    fault_id, trial, result.system, before, after,
                )
            else:
                logger.info(
                    "CSV verified: %s t%d %s written (row %d)",
                    fault_id, trial, result.system, after,
                )

        # Save raw data
        save_raw(fault_id, trial, "A", {
            "signals": obs_signals,
            "context": ctx_a.to_context(),
            "rca_output": result_a.to_dict(),
            "raw_response": result_a.raw_response,
        }, self.raw_dir)

        raw_b = {
            "signals": all_signals,
            "context": ctx_b.to_context(),
            "rca_output": result_b.to_dict(),
            "raw_response": result_b.raw_response,
        }
        if self.retriever is not None:
            try:
                raw_b["rag_docs"] = [
                    {"source": d.short_source, "score": d.score}
                    for d in self.retriever.query_by_fault(fault_id)
                ]
            except Exception:
                pass
        save_raw(fault_id, trial, "B", raw_b, self.raw_dir)

        # ── Step 9: Recover + verify cluster health ──
        if not dry_run:
            logger.info("Recovering from fault...")
            try:
                self.recovery.recover(fault_id, trial, injection_result)
                logger.info("Recovery complete — cluster stabilized")
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

    def _count_csv_rows(self) -> int:
        """Count data rows in CSV (excluding header)."""
        if not self.csv_path.exists():
            return 0
        with open(self.csv_path) as f:
            return sum(1 for line in f if line.strip()) - 1  # minus header

    @staticmethod
    def _print_signal_summary(signals: dict):
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

"""V2.2 trial runner: copy-variant of shared TrialRunner (shared stays untouched).

Per (fault, trial): validate (if any) → inject → wait → collect once → RAG
retrieve → build ONE system="B" RCAContext → ArmAssembler builds 5 arm strings →
loop arms: engine.analyze_arm → CSV append (1 row/arm) → raw save (k samples +
m judge votes) → recover once.
"""
import logging
import time
from datetime import datetime
from pathlib import Path

from experiments.shared.csv_io import append_result, save_raw
from .arms import ArmAssembler
from .config import ARMS, T_BLOCK

logger = logging.getLogger(__name__)

ALL_FAULTS = [f"F{i}" for i in range(1, 13)]
ALL_TRIALS = [1, 2, 3, 4, 5]


class TrialRunnerV2_2:
    """Orchestrate 5-arm self-consistency trials with the v2.2 engine."""

    def __init__(
        self,
        engine,
        csv_path: Path,
        csv_headers: list[str],
        raw_dir: Path,
        injector=None,
        recovery=None,
        collector=None,
        builder=None,
        retriever=None,
        validator=None,
        mock_signals: dict = None,  # offline mode: canned signals dict
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
        self.validator = validator
        self.mock_signals = mock_signals
        self.assembler = ArmAssembler(t_block=T_BLOCK)

    def run_trial(
        self,
        fault_id: str,
        trial: int,
        dry_run: bool = False,
        mock: bool = False,
        ground_truth: dict = None,
    ):
        logger.info("=" * 60)
        logger.info("Starting %s trial %d (5-arm, k=3, m=3)", fault_id, trial)
        logger.info("=" * 60)

        # ── Step 0.5: Pre-Trial State Validation (skipped in dry_run/mock) ──
        if not dry_run and not mock and self.validator is not None:
            try:
                vr = self.validator.validate_and_correct(fault_id=fault_id, trial=trial)
                logger.info("Validator: %s", vr.summary())
                if vr.status == "skipped":
                    logger.warning("Trial SKIPPED by validator: %s t%d", fault_id, trial)
                    return
            except Exception as e:
                logger.error("Validator failed (skipping trial): %s", e)
                return

        # ── Step 1+2: Inject + wait (skipped offline) ──
        injection_result = {}
        if not dry_run and not mock:
            try:
                injection_result = self.injector.inject(fault_id, trial)
                logger.info("Injection: %s", injection_result.get("action", ""))
            except Exception as e:
                logger.error("Injection failed: %s", e)
                return
            wait = injection_result.get("wait_seconds", 120)
            logger.info("Waiting %ds for symptoms...", wait)
            time.sleep(wait)
        else:
            logger.info("[OFFLINE] Skipping injection")

        # ── Step 3: Collect signals (once) ──
        low_quality_flag = 0
        if mock:
            all_signals = self.mock_signals or {}
        else:
            try:
                all_signals = self.collector.collect_all(window_minutes=5)
            except Exception as e:
                logger.error("Signal collection failed: %s", e)
                all_signals = {}
                low_quality_flag = 1
        low_quality_flag = max(low_quality_flag, self._detect_low_quality(all_signals))

        # ── Step 4: RAG retrieval ──
        rag_context = ""
        if mock:
            rag_context = (all_signals.get("rag_context") or "")
        elif not dry_run and self.retriever is not None:
            try:
                docs = self.retriever.query_by_fault(fault_id)
                rag_context = self.retriever.format_context(docs)
                logger.info("RAG retrieved %d docs", len(docs))
            except Exception as e:
                logger.warning("RAG retrieval failed: %s", e)

        # ── Step 5: Build ONE system="B" context (obs+gitops+rag all populated) ──
        ctx = self.builder.build(
            all_signals, fault_id=fault_id, trial=trial, system="B",
            rag_context=rag_context,
        )

        jaccard = self.assembler.gitops_rag_jaccard(ctx)
        logger.info("GitOps↔RAG Jaccard: %.4f", jaccard)

        if dry_run:
            logger.info("[DRY RUN] Context built. Arm lengths:")
            for arm in ARMS:
                logger.info("  %s: %d chars", arm, len(self.assembler.assemble(ctx, arm)))
            return

        gt_row = ground_truth.get((fault_id, trial), {}) if ground_truth else {}
        timestamp = datetime.now().isoformat()

        # ── Step 6: Arm loop ──
        for arm in ARMS:
            arm_ctx = self.assembler.assemble(ctx, arm)
            logger.info("Arm %s: %d chars", arm, len(arm_ctx))
            result = self.engine.analyze_arm(
                arm_ctx, fault_id=fault_id, trial=trial, arm=arm, ground_truth=gt_row,
            )
            row = result["row"]
            row["timestamp"] = timestamp
            row["low_quality_flag"] = low_quality_flag
            row["gitops_rag_jaccard"] = jaccard

            before = self._count_csv_rows()
            append_result(row, self.csv_path, self.csv_headers)
            after = self._count_csv_rows()
            if after <= before:
                logger.error("CSV write FAILED for %s t%d %s", fault_id, trial, arm)
            else:
                logger.info(
                    "CSV verified: %s t%d %s (label=%s rep_score=%.2f agree=%.2f)",
                    fault_id, trial, arm, row["majority_label"],
                    row["rep_correctness_score"], row["gen_agreement"],
                )

            save_raw(fault_id, trial, arm, result["raw"], self.raw_dir)

        # ── Step 7: Recover once ──
        if not mock:
            try:
                self.recovery.recover(fault_id, trial, injection_result)
                logger.info("Recovery complete")
            except Exception as e:
                logger.error("Recovery failed: %s", e)

        logger.info("Trial complete: %s t%d (5 arms recorded)", fault_id, trial)

    # ── helpers ──

    @staticmethod
    def _detect_low_quality(signals: dict) -> int:
        """Flag low-quality signal collection: empty logs / collector error markers."""
        if not signals:
            return 1
        logs = signals.get("logs", {}) or {}
        pod_logs = logs.get("pod_logs", [])
        if "error" in signals:
            return 1
        if isinstance(pod_logs, list) and len(pod_logs) == 0:
            # empty logs alone is a weak signal; flag it for sensitivity analysis
            return 1
        return 0

    def _count_csv_rows(self) -> int:
        if not self.csv_path.exists():
            return 0
        with open(self.csv_path) as f:
            return sum(1 for line in f if line.strip()) - 1

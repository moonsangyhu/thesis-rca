#!/usr/bin/env python3
"""
Post-experiment analysis and statistical testing.

Computes:
- Per-fault accuracy (System A vs B)
- Overall accuracy comparison
- Wilcoxon signed-rank test (paired, non-parametric)
- Confidence interval analysis
- Per-fault-type breakdown

Usage:
    python -m scripts.evaluate.analyze
    python -m scripts.evaluate.analyze --results results/experiment_results.csv
"""
import argparse
import csv
import logging
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("evaluate")

RESULTS_CSV = PROJECT_ROOT / "results" / "experiment_results.csv"


def load_results(csv_path: str) -> pd.DataFrame:
    """Load experiment results."""
    df = pd.read_csv(csv_path)
    df["correct"] = df["correct"].astype(int)
    if "correctness_score" in df.columns:
        df["correctness_score"] = df["correctness_score"].astype(float)
    else:
        # Backward compat: V1 results without LLM-as-judge scores
        df["correctness_score"] = df["correct"].astype(float)
    return df


def compute_accuracy(df: pd.DataFrame) -> dict:
    """Compute accuracy metrics for System A vs B."""
    results = {}

    for system in ["A", "B"]:
        sys_df = df[df["system"] == system]
        total = len(sys_df)
        correct = sys_df["correct"].sum()
        accuracy = correct / total if total > 0 else 0
        avg_confidence = sys_df["confidence"].mean()
        avg_latency = sys_df["latency_ms"].mean()

        results[system] = {
            "total": total,
            "correct": correct,
            "accuracy": accuracy,
            "mean_correctness_score": sys_df["correctness_score"].mean(),
            "avg_confidence": avg_confidence,
            "avg_latency_ms": avg_latency,
        }

    return results


def compute_per_fault_accuracy(df: pd.DataFrame) -> pd.DataFrame:
    """Compute accuracy per fault type for A and B."""
    rows = []
    for fault_id in sorted(df["fault_id"].unique()):
        fault_df = df[df["fault_id"] == fault_id]
        for system in ["A", "B"]:
            sys_df = fault_df[fault_df["system"] == system]
            total = len(sys_df)
            correct = sys_df["correct"].sum()
            rows.append({
                "fault_id": fault_id,
                "system": system,
                "total": total,
                "correct": correct,
                "accuracy": correct / total if total > 0 else 0,
                "mean_correctness_score": sys_df["correctness_score"].mean(),
                "avg_confidence": sys_df["confidence"].mean(),
            })
    return pd.DataFrame(rows)


def wilcoxon_test(df: pd.DataFrame) -> dict:
    """
    Wilcoxon signed-rank test comparing System A vs B accuracy.

    Pairs: each (fault_id, trial) pair.
    Test statistic: correctness difference (B - A) per pair.
    """
    # Create paired data
    pairs = []
    for (fault_id, trial), group in df.groupby(["fault_id", "trial"]):
        a_row = group[group["system"] == "A"]
        b_row = group[group["system"] == "B"]
        if len(a_row) == 1 and len(b_row) == 1:
            pairs.append({
                "fault_id": fault_id,
                "trial": trial,
                "correct_a": a_row["correct"].values[0],
                "correct_b": b_row["correct"].values[0],
                "score_a": a_row["correctness_score"].values[0],
                "score_b": b_row["correctness_score"].values[0],
                "confidence_a": a_row["confidence"].values[0],
                "confidence_b": b_row["confidence"].values[0],
            })

    pairs_df = pd.DataFrame(pairs)
    diff_correct = pairs_df["correct_b"] - pairs_df["correct_a"]
    diff_score = pairs_df["score_b"] - pairs_df["score_a"]
    diff_confidence = pairs_df["confidence_b"] - pairs_df["confidence_a"]

    result = {"n_pairs": len(pairs)}

    # Binary accuracy improvement
    result["accuracy_diff_mean"] = diff_correct.mean()
    result["accuracy_diff_std"] = diff_correct.std()
    result["pairs_b_better"] = (diff_correct > 0).sum()
    result["pairs_equal"] = (diff_correct == 0).sum()
    result["pairs_a_better"] = (diff_correct < 0).sum()

    # Primary: Wilcoxon on continuous correctness_score (higher statistical power)
    non_zero_score = diff_score[diff_score != 0]
    if len(non_zero_score) >= 6:
        stat_s, p_s = stats.wilcoxon(non_zero_score, alternative="greater")
        result["score_wilcoxon_stat"] = stat_s
        result["score_wilcoxon_p_value"] = p_s
    else:
        result["score_wilcoxon_stat"] = None
        result["score_wilcoxon_p_value"] = None
        result["score_note"] = f"Too few non-tied pairs ({len(non_zero_score)}) for Wilcoxon test"

    result["score_diff_mean"] = diff_score.mean()
    result["score_diff_std"] = diff_score.std()

    # Secondary: Wilcoxon on binary correctness (backward compat)
    non_zero = diff_correct[diff_correct != 0]
    if len(non_zero) >= 6:
        stat, p_value = stats.wilcoxon(non_zero, alternative="greater")
        result["wilcoxon_stat"] = stat
        result["wilcoxon_p_value"] = p_value
    else:
        result["wilcoxon_stat"] = None
        result["wilcoxon_p_value"] = None
        result["note"] = f"Too few non-tied pairs ({len(non_zero)}) for Wilcoxon test"

    # Confidence comparison
    non_zero_conf = diff_confidence[diff_confidence != 0]
    if len(non_zero_conf) >= 6:
        stat_c, p_c = stats.wilcoxon(
            pairs_df["confidence_b"], pairs_df["confidence_a"],
            alternative="greater",
        )
        result["confidence_wilcoxon_stat"] = stat_c
        result["confidence_wilcoxon_p_value"] = p_c
    else:
        result["confidence_wilcoxon_stat"] = None
        result["confidence_wilcoxon_p_value"] = None

    result["confidence_diff_mean"] = diff_confidence.mean()
    result["confidence_diff_std"] = diff_confidence.std()

    return result


def print_report(df: pd.DataFrame):
    """Print full experiment report."""
    logger.info("=" * 70)
    logger.info("GitOps-Aware K8s RCA Experiment Results")
    logger.info("=" * 70)

    # Overall accuracy
    acc = compute_accuracy(df)
    logger.info("\n## Overall Accuracy")
    for system in ["A", "B"]:
        s = acc[system]
        logger.info(
            "  System %s: %d/%d correct (%.1f%%) | "
            "mean score: %.3f | avg confidence: %.3f | avg latency: %.0fms",
            system, s["correct"], s["total"], s["accuracy"] * 100,
            s["mean_correctness_score"], s["avg_confidence"], s["avg_latency_ms"],
        )

    improvement = acc["B"]["accuracy"] - acc["A"]["accuracy"]
    score_improvement = acc["B"]["mean_correctness_score"] - acc["A"]["mean_correctness_score"]
    logger.info("  Improvement (B-A): %.1f%%p accuracy, +%.3f score", improvement * 100, score_improvement)

    # Per-fault breakdown
    logger.info("\n## Per-Fault Accuracy")
    pf = compute_per_fault_accuracy(df)
    for fault_id in sorted(pf["fault_id"].unique()):
        fault_data = pf[pf["fault_id"] == fault_id]
        a = fault_data[fault_data["system"] == "A"].iloc[0] if len(fault_data[fault_data["system"] == "A"]) else None
        b = fault_data[fault_data["system"] == "B"].iloc[0] if len(fault_data[fault_data["system"] == "B"]) else None
        if a is not None and b is not None:
            logger.info(
                "  %s: A=%d/%d (%.0f%%) B=%d/%d (%.0f%%) | "
                "conf A=%.2f B=%.2f",
                fault_id,
                int(a["correct"]), int(a["total"]), a["accuracy"] * 100,
                int(b["correct"]), int(b["total"]), b["accuracy"] * 100,
                a["avg_confidence"], b["avg_confidence"],
            )

    # Statistical test
    logger.info("\n## Wilcoxon Signed-Rank Test")
    wilcox = wilcoxon_test(df)
    logger.info("  Paired samples: %d", wilcox["n_pairs"])
    logger.info(
        "  B better: %d | Equal: %d | A better: %d",
        wilcox["pairs_b_better"], wilcox["pairs_equal"], wilcox["pairs_a_better"],
    )

    # Primary: continuous correctness_score
    if wilcox["score_wilcoxon_p_value"] is not None:
        sig = "***" if wilcox["score_wilcoxon_p_value"] < 0.001 else (
            "**" if wilcox["score_wilcoxon_p_value"] < 0.01 else (
                "*" if wilcox["score_wilcoxon_p_value"] < 0.05 else "n.s."
            )
        )
        logger.info(
            "  Correctness Score: W=%.1f, p=%.4f %s (mean diff=%.3f)",
            wilcox["score_wilcoxon_stat"], wilcox["score_wilcoxon_p_value"],
            sig, wilcox["score_diff_mean"],
        )
    else:
        logger.info("  Correctness Score: %s", wilcox.get("score_note", "N/A"))

    # Secondary: binary accuracy
    if wilcox["wilcoxon_p_value"] is not None:
        sig = "***" if wilcox["wilcoxon_p_value"] < 0.001 else (
            "**" if wilcox["wilcoxon_p_value"] < 0.01 else (
                "*" if wilcox["wilcoxon_p_value"] < 0.05 else "n.s."
            )
        )
        logger.info(
            "  Binary Accuracy: W=%.1f, p=%.4f %s",
            wilcox["wilcoxon_stat"], wilcox["wilcoxon_p_value"], sig,
        )
    else:
        logger.info("  Binary Accuracy: %s", wilcox.get("note", "N/A"))

    if wilcox["confidence_wilcoxon_p_value"] is not None:
        sig = "***" if wilcox["confidence_wilcoxon_p_value"] < 0.001 else (
            "**" if wilcox["confidence_wilcoxon_p_value"] < 0.01 else (
                "*" if wilcox["confidence_wilcoxon_p_value"] < 0.05 else "n.s."
            )
        )
        logger.info(
            "  Confidence: W=%.1f, p=%.4f %s (mean diff=%.3f)",
            wilcox["confidence_wilcoxon_stat"],
            wilcox["confidence_wilcoxon_p_value"],
            sig,
            wilcox["confidence_diff_mean"],
        )

    logger.info("\n" + "=" * 70)

    # Save report as JSON
    report = {
        "overall_accuracy": acc,
        "per_fault": pf.to_dict(orient="records"),
        "wilcoxon_test": wilcox,
    }
    report_path = PROJECT_ROOT / "results" / "experiment_report.json"
    import json
    with open(report_path, "w") as f:
        json.dump(report, f, ensure_ascii=False, indent=2, default=str)
    logger.info("Report saved: %s", report_path)


def main():
    parser = argparse.ArgumentParser(description="Analyze experiment results")
    parser.add_argument("--results", type=str, default=str(RESULTS_CSV))
    args = parser.parse_args()

    df = load_results(args.results)
    print_report(df)


if __name__ == "__main__":
    main()

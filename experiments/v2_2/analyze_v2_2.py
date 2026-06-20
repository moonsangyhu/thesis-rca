#!/usr/bin/env python3
"""V2.2 basic analysis: threshold sweep + per-arm accuracy (descriptive only).

Deep statistics (GLMM / McNemar / Cohen's h / Newcombe CI / forest plots) are
the independent analyst's job (Step 5). Here we only produce the per-arm
accuracy table across thresholds plus generation-agreement / low-quality /
Jaccard summaries that the harness must surface.

Usage:
    python -m experiments.v2_2.analyze_v2_2
"""
import csv
from collections import defaultdict

from .config import RESULTS_CSV, ARMS, THRESHOLDS, PRIMARY_THRESHOLD


def _f(x, default=0.0):
    try:
        return float(x)
    except (TypeError, ValueError):
        return default


def load_rows():
    rows = []
    if not RESULTS_CSV.exists():
        return rows
    with open(RESULTS_CSV) as f:
        rows = list(csv.DictReader(f))
    return rows


def main():
    rows = load_rows()
    if not rows:
        print(f"No data in {RESULTS_CSV}")
        return

    by_arm = defaultdict(list)
    for r in rows:
        by_arm[r.get("arm", "")].append(r)

    print(f"V2.2 analysis — {len(rows)} rows from {RESULTS_CSV.name}")
    print(f"Primary threshold = {PRIMARY_THRESHOLD}\n")

    # ── per-arm accuracy across thresholds ──
    header = ["arm", "n"] + [f"acc@{t}" for t in THRESHOLDS] + ["gen_agree", "low_q%", "jaccard"]
    print(" | ".join(f"{h:>10}" for h in header))
    print("-" * (13 * len(header)))

    for arm in ARMS:
        arm_rows = by_arm.get(arm, [])
        n = len(arm_rows)
        if n == 0:
            print(" | ".join(f"{v:>10}" for v in [arm, 0] + ["-"] * (len(header) - 2)))
            continue
        accs = []
        for t in THRESHOLDS:
            col = f"correct_at_{t}"
            correct = sum(int(_f(r.get(col))) for r in arm_rows)
            accs.append(correct / n)
        gen_agree = sum(_f(r.get("gen_agreement")) for r in arm_rows) / n
        low_q = sum(int(_f(r.get("low_quality_flag"))) for r in arm_rows) / n * 100
        jac = sum(_f(r.get("gitops_rag_jaccard")) for r in arm_rows) / n
        vals = [arm, n] + [f"{a:.3f}" for a in accs] + [
            f"{gen_agree:.3f}", f"{low_q:.1f}", f"{jac:.3f}",
        ]
        print(" | ".join(f"{v:>10}" for v in vals))

    # ── overall summaries ──
    print()
    all_low_q = sum(int(_f(r.get("low_quality_flag"))) for r in rows)
    print(f"low_quality rows: {all_low_q}/{len(rows)} ({all_low_q/len(rows)*100:.1f}%)")
    jac_vals = [_f(r.get("gitops_rag_jaccard")) for r in rows]
    if jac_vals:
        print(f"mean GitOps↔RAG Jaccard: {sum(jac_vals)/len(jac_vals):.4f}")
    agree_vals = [_f(r.get("gen_agreement")) for r in rows]
    if agree_vals:
        print(f"mean gen_agreement (k=3): {sum(agree_vals)/len(agree_vals):.4f}")


if __name__ == "__main__":
    main()

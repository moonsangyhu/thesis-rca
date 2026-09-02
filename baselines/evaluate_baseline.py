#!/usr/bin/env python3
"""Evaluate baseline prediction CSVs and print/write a metric table.

The script intentionally reads only the prediction artifact, not raw contexts or
LLM outputs.  This keeps evaluation reusable across naive and future non-LLM
baselines as long as they emit the fixed columns below.
"""
from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

REQUIRED_COLUMNS = [
    "baseline",
    "fault_id",
    "trial",
    "input_target_service",
    "input_severity",
    "predicted_fault_name",
    "true_fault_name",
    "correct",
]


def load_predictions(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != REQUIRED_COLUMNS:
            raise ValueError(f"Unexpected prediction schema: {reader.fieldnames}")
        rows = list(reader)
    if not rows:
        raise ValueError(f"No predictions in {path}")
    return rows


def metric_lines(rows: list[dict[str, str]]) -> list[str]:
    n = len(rows)
    correct = sum(int(r["correct"]) for r in rows)
    by_fault = defaultdict(lambda: [0, 0])
    by_label = defaultdict(lambda: [0, 0])
    for r in rows:
        by_fault[r["fault_id"]][0] += int(r["correct"])
        by_fault[r["fault_id"]][1] += 1
        by_label[r["true_fault_name"]][0] += int(r["correct"])
        by_label[r["true_fault_name"]][1] += 1
    macro_recall = sum(c / t for c, t in by_label.values()) / len(by_label)

    lines = [
        "# baseline metric table",
        "",
        "## Overall",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| rows | {n} |",
        f"| correct | {correct}/{n} |",
        f"| accuracy | {correct / n:.4f} |",
        f"| macro_recall_by_true_label | {macro_recall:.4f} |",
        "",
        "## By fault",
        "",
        "| fault_id | correct | accuracy |",
        "|---|---:|---:|",
    ]
    for fault_id in sorted(by_fault):
        c, t = by_fault[fault_id]
        lines.append(f"| {fault_id} | {c}/{t} | {c / t:.4f} |")
    return lines


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--predictions", required=True)
    parser.add_argument("--output", help="Optional markdown output path")
    args = parser.parse_args()

    rows = load_predictions(Path(args.predictions))
    lines = metric_lines(rows)
    text = "\n".join(lines) + "\n"
    print(text)
    if args.output:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text)


if __name__ == "__main__":
    main()

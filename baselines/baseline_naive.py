#!/usr/bin/env python3
"""Deterministic naive RCA baseline.

This baseline is intentionally weak: it learns the most frequent fault label from
train split only and predicts that same label for every evaluation item.  Its
purpose is not performance; it is a leakage-free end-to-end reproducibility
anchor for future RCA methods.

Input dataset schema is fixed to `results/ground_truth.csv` with the columns
listed in `INPUT_COLUMNS`.  The target label is `fault_name`; `fault_id`,
`expected_root_cause`, `expected_*`, and `injection_method` are not used as
features because they would leak the answer or near-answer.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

INPUT_COLUMNS = [
    "fault_id",
    "trial",
    "fault_name",
    "target_service",
    "injection_method",
    "expected_root_cause",
    "affected_components",
    "severity",
    "primary_symptoms",
    "expected_metrics",
    "expected_log_patterns",
    "expected_recovery_action",
]

FEATURE_COLUMNS = ["target_service", "severity"]
TARGET_COLUMN = "fault_name"
EXCLUDED_AS_LEAKAGE = [
    "fault_id",
    "trial",
    "fault_name",
    "injection_method",
    "expected_root_cause",
    "affected_components",
    "primary_symptoms",
    "expected_metrics",
    "expected_log_patterns",
    "expected_recovery_action",
]


@dataclass(frozen=True)
class Config:
    dataset_path: Path
    output_dir: Path
    seed: int = 42
    split_strategy: str = "stratified_trial_holdout"
    test_trials_per_fault: int = 1
    baseline_name: str = "baseline_naive"


def load_config(path: Path) -> Config:
    data = json.loads(path.read_text())
    return Config(
        dataset_path=Path(data["dataset_path"]),
        output_dir=Path(data["output_dir"]),
        seed=int(data.get("seed", 42)),
        split_strategy=data.get("split_strategy", "stratified_trial_holdout"),
        test_trials_per_fault=int(data.get("test_trials_per_fault", 1)),
        baseline_name=data.get("baseline_name", "baseline_naive"),
    )


def read_dataset(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != INPUT_COLUMNS:
            raise ValueError(
                "Unexpected dataset schema.\n"
                f"expected={INPUT_COLUMNS}\nactual={reader.fieldnames}"
            )
        rows = list(reader)
    if not rows:
        raise ValueError(f"Dataset is empty: {path}")
    return rows


def dataset_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stratified_trial_holdout(rows: list[dict[str, str]], seed: int, k: int) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    by_fault: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        by_fault[row["fault_id"]].append(row)

    rng = random.Random(seed)
    train: list[dict[str, str]] = []
    test: list[dict[str, str]] = []
    for fault_id in sorted(by_fault):
        group = sorted(by_fault[fault_id], key=lambda r: int(r["trial"]))
        if len(group) <= k:
            raise ValueError(f"Not enough rows for {fault_id}: n={len(group)}, holdout={k}")
        shuffled = group[:]
        rng.shuffle(shuffled)
        held_out_keys = {(r["fault_id"], r["trial"]) for r in shuffled[:k]}
        for row in group:
            if (row["fault_id"], row["trial"]) in held_out_keys:
                test.append(row)
            else:
                train.append(row)
    return train, test


def fit_global_majority(train_rows: Iterable[dict[str, str]]) -> tuple[str, Counter[str]]:
    counts = Counter(row[TARGET_COLUMN] for row in train_rows)
    if not counts:
        raise ValueError("Cannot fit majority baseline on empty train split")
    # Deterministic tie-break: highest count, then lexicographically smallest label.
    label = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return label, counts


def write_split(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["fault_id", "trial", "split", TARGET_COLUMN] + FEATURE_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({
                "fault_id": row["fault_id"],
                "trial": row["trial"],
                "split": row["split"],
                TARGET_COLUMN: row[TARGET_COLUMN],
                **{col: row[col] for col in FEATURE_COLUMNS},
            })


def write_predictions(path: Path, test_rows: list[dict[str, str]], prediction: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "baseline",
        "fault_id",
        "trial",
        "input_target_service",
        "input_severity",
        "predicted_fault_name",
        "true_fault_name",
        "correct",
    ]
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in sorted(test_rows, key=lambda r: (r["fault_id"], int(r["trial"]))):
            writer.writerow({
                "baseline": "baseline_naive",
                "fault_id": row["fault_id"],
                "trial": row["trial"],
                "input_target_service": row["target_service"],
                "input_severity": row["severity"],
                "predicted_fault_name": prediction,
                "true_fault_name": row[TARGET_COLUMN],
                "correct": int(prediction == row[TARGET_COLUMN]),
            })


def write_metrics(path: Path, predictions_path: Path, train_n: int, test_n: int, majority_label: str, label_counts: Counter[str], seed: int) -> dict[str, float]:
    rows = list(csv.DictReader(predictions_path.open()))
    correct = sum(int(r["correct"]) for r in rows)
    accuracy = correct / len(rows) if rows else 0.0
    macro_by_label = defaultdict(lambda: [0, 0])
    for r in rows:
        bucket = macro_by_label[r["true_fault_name"]]
        bucket[0] += int(r["correct"])
        bucket[1] += 1
    macro_recall = sum(c / n for c, n in macro_by_label.values()) / len(macro_by_label)

    lines = [
        "# baseline_naive metric table",
        "",
        "| metric | value |",
        "|---|---:|",
        f"| seed | {seed} |",
        f"| train_rows | {train_n} |",
        f"| test_rows | {test_n} |",
        f"| learned_majority_label | `{majority_label}` |",
        f"| majority_label_train_count | {label_counts[majority_label]} |",
        f"| accuracy | {accuracy:.4f} |",
        f"| macro_recall | {macro_recall:.4f} |",
        f"| correct | {correct}/{len(rows)} |",
        "",
        "해석: 이 baseline은 train split의 최빈 fault_name만 예측한다. balanced multi-class RCA에서 낮은 점수가 정상이며, 향후 방법이 이 기준선을 넘지 못하면 논문 주장은 성립하기 어렵다.",
    ]
    path.write_text("\n".join(lines) + "\n")
    return {"accuracy": accuracy, "macro_recall": macro_recall}


def write_failures(path: Path, predictions_path: Path, ground_truth_rows: list[dict[str, str]], max_examples: int = 3) -> None:
    gt = {(r["fault_id"], r["trial"]): r for r in ground_truth_rows}
    pred_rows = [r for r in csv.DictReader(predictions_path.open()) if r["correct"] == "0"]
    pred_rows = sorted(pred_rows, key=lambda r: (r["fault_id"], int(r["trial"])))[:max_examples]
    lines = ["# baseline_naive failure cases", ""]
    if not pred_rows:
        lines.append("No failures found. This would be suspicious for a naive majority baseline.")
    for i, r in enumerate(pred_rows, start=1):
        key = (r["fault_id"], r["trial"])
        truth = gt[key]
        lines.extend([
            f"## Failure {i}: {r['fault_id']} trial {r['trial']}",
            "",
            "### 입력",
            f"- target_service: `{truth['target_service']}`",
            f"- severity: `{truth['severity']}`",
            "- 사용 feature: `target_service`, `severity` only",
            f"- 제외 feature(leakage 방지): `{', '.join(EXCLUDED_AS_LEAKAGE)}`",
            "",
            "### 예측 / 정답",
            f"- prediction: `{r['predicted_fault_name']}`",
            f"- ground truth: `{r['true_fault_name']}`",
            f"- expected_root_cause: {truth['expected_root_cause']}",
            "",
            "### 실패 원인 가설",
            "- global-majority baseline은 입력 증상·메트릭·로그를 읽지 않고 train split 최빈 라벨만 반복한다.",
            "- balanced fault taxonomy에서는 대부분의 non-majority fault를 구조적으로 틀린다.",
            "- 따라서 이 실패는 구현 버그라기보다 baseline의 의도된 하한 성능을 보여준다.",
            "",
        ])
    path.write_text("\n".join(lines))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="baselines/configs/baseline_naive.json")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    rows = read_dataset(cfg.dataset_path)
    if cfg.split_strategy != "stratified_trial_holdout":
        raise ValueError(f"Unsupported split_strategy={cfg.split_strategy}")
    train, test = stratified_trial_holdout(rows, seed=cfg.seed, k=cfg.test_trials_per_fault)
    for row in train:
        row["split"] = "train"
    for row in test:
        row["split"] = "test"

    majority_label, counts = fit_global_majority(train)
    cfg.output_dir.mkdir(parents=True, exist_ok=True)

    split_path = cfg.output_dir / "baseline_naive_split.csv"
    predictions_path = cfg.output_dir / "baseline_naive_predictions.csv"
    metrics_path = cfg.output_dir / "baseline_naive_metrics.md"
    failures_path = cfg.output_dir / "baseline_naive_failures.md"
    manifest_path = cfg.output_dir / "baseline_naive_manifest.json"

    write_split(split_path, train + test)
    write_predictions(predictions_path, test, majority_label)
    metrics = write_metrics(metrics_path, predictions_path, len(train), len(test), majority_label, counts, cfg.seed)
    write_failures(failures_path, predictions_path, rows, max_examples=3)
    manifest = {
        "baseline": cfg.baseline_name,
        "dataset_path": str(cfg.dataset_path),
        "dataset_sha256": dataset_sha256(cfg.dataset_path),
        "input_columns": INPUT_COLUMNS,
        "feature_columns_used": FEATURE_COLUMNS,
        "target_column": TARGET_COLUMN,
        "excluded_as_leakage": EXCLUDED_AS_LEAKAGE,
        "seed": cfg.seed,
        "split_strategy": cfg.split_strategy,
        "test_trials_per_fault": cfg.test_trials_per_fault,
        "train_rows": len(train),
        "test_rows": len(test),
        "learned_majority_label": majority_label,
        "artifacts": {
            "split": str(split_path),
            "predictions": str(predictions_path),
            "metrics": str(metrics_path),
            "failures": str(failures_path),
        },
        "metrics": metrics,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")

    print(f"baseline_naive complete: predictions={predictions_path}")
    print(f"metrics={metrics_path}")
    print(f"failures={failures_path}")


if __name__ == "__main__":
    main()

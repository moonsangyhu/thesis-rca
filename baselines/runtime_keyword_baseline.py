#!/usr/bin/env python3
"""Runtime-context keyword baseline for RCA.

This baseline is a stronger non-LLM comparator than `baseline_naive`: it reads
only runtime-observability context captured in V2.2 raw files (`C1_A` arm) and
classifies fault type using deterministic keyword/rule matching.  It does not
use GitOps, RAG, LLM responses, ground-truth root-cause text, or injected fault
metadata as prediction features.

Scope: this is still a rule baseline, not a publishable SOTA comparator.  Its
job is to test whether future LLM/GitOps/RAG methods beat a simple runtime
signal parser rather than merely beating a majority prior.
"""
from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import re
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from baselines.baseline_naive import INPUT_COLUMNS, stratified_trial_holdout

TARGET_COLUMN = "fault_name"
BASELINE_NAME = "baseline_runtime_keyword"

Rule = tuple[str, str, Callable[[str], bool]]


def has_any(text: str, patterns: list[str]) -> bool:
    return any(re.search(p, text, flags=re.IGNORECASE | re.MULTILINE) for p in patterns)


RULES: list[Rule] = [
    # Specific Kubernetes failure signatures come first.  Generic cascade
    # symptoms such as BackOff, timeout, and connection errors are intentionally
    # late because many root causes produce them secondarily.
    (
        "ResourceQuota",
        "quota_exceeded",
        lambda t: has_any(t, [r"ResourceQuota", r"exceeded quota", r"forbidden: exceeded", r"fault-quota", r"services.*forbidden"]),
    ),
    (
        "ImagePullBackOff",
        "image_pull_error",
        lambda t: has_any(t, [r"ImagePullBackOff", r"ErrImagePull", r"pull access denied", r"failed to pull image"]),
    ),
    (
        "OOMKilled",
        "oomkilled_exact",
        lambda t: has_any(t, [r"OOMKilled", r"out of memory", r"exit code 137"]),
    ),
    (
        "NodeNotReady",
        "node_not_ready",
        lambda t: has_any(t, [r"NodeNotReady", r"KubeletNotReady", r"node.*unreachable", r"Ready=False"]),
    ),
    (
        "SecretConfigMap",
        "secret_or_configmap_missing",
        lambda t: has_any(t, [r"secret .* not found", r"configmap .* not found", r"MountVolume\.SetUp failed", r"CreateContainerConfigError"]),
    ),
    (
        "PVCPending",
        "pvc_pending_or_volume",
        lambda t: has_any(t, [r"PersistentVolumeClaim", r"\bPVC\b", r"pod has unbound immediate PersistentVolumeClaims", r"FailedScheduling.*volume", r"FailedMount"]),
    ),
    (
        "NetworkPolicy",
        "network_policy_block",
        lambda t: has_any(t, [r"NetworkPolicy", r"network policy", r"egress.*denied", r"ingress.*denied", r"redis.*ConnectTimeout"]),
    ),
    (
        "CPUThrottle",
        "high_cpu_throttling",
        lambda t: has_any(t, [r"CPU throttled[^\n]*(?:9\d|100)%", r"container_cpu_cfs_throttled[^\n]*(?:9\d|100)%"]),
    ),
    (
        "CrashLoopBackOff",
        "crash_loop_or_container_error",
        lambda t: has_any(t, [r"CrashLoopBackOff", r"last terminated: Error", r"Error \(exit code"]),
    ),
    (
        "ServiceEndpoint",
        "zero_endpoints_or_service_unavailable",
        lambda t: has_any(t, [r"Services with 0 endpoints", r"\b0 endpoints\b", r"no endpoints", r"Endpoints: <none>"]),
    ),
    (
        "NetworkDelay",
        "latency_or_delay",
        lambda t: has_any(t, [r"network.*delay", r"latency", r"p95", r"p99", r"slow response"]),
    ),
    (
        "NetworkLoss",
        "packet_loss_or_connection_reset",
        lambda t: has_any(t, [r"packet loss", r"connection reset", r"network unreachable"]),
    ),
]


@dataclass(frozen=True)
class Config:
    dataset_path: Path
    raw_context_dir: Path
    output_dir: Path
    seed: int = 42
    split_strategy: str = "stratified_trial_holdout"
    test_trials_per_fault: int = 1
    arm: str = "C1_A"


def load_config(path: Path) -> Config:
    data = json.loads(path.read_text())
    return Config(
        dataset_path=Path(data["dataset_path"]),
        raw_context_dir=Path(data["raw_context_dir"]),
        output_dir=Path(data["output_dir"]),
        seed=int(data.get("seed", 42)),
        split_strategy=data.get("split_strategy", "stratified_trial_holdout"),
        test_trials_per_fault=int(data.get("test_trials_per_fault", 1)),
        arm=data.get("arm", "C1_A"),
    )


def read_dataset(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != INPUT_COLUMNS:
            raise ValueError(f"Unexpected dataset schema: {reader.fieldnames}")
        return list(reader)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def find_raw_file(raw_dir: Path, fault_id: str, trial: str, arm: str) -> Path:
    pattern = str(raw_dir / f"{fault_id}_t{trial}_{arm}_*.json")
    matches = sorted(glob.glob(pattern))
    if len(matches) != 1:
        raise FileNotFoundError(f"Expected exactly one raw context for {fault_id} t{trial} {arm}, got {len(matches)}: {matches[:3]}")
    return Path(matches[0])


def load_context(path: Path) -> str:
    data = json.loads(path.read_text())
    context = data.get("context", "")
    if not context:
        raise ValueError(f"No context field in {path}")
    return context


def predict(context: str) -> tuple[str, str]:
    for label, rule_name, predicate in RULES:
        if predicate(context):
            return label, rule_name
    return "Unknown", "no_rule_matched"


def write_predictions(path: Path, rows: list[dict[str, str]], cfg: Config) -> list[dict[str, str]]:
    out_rows: list[dict[str, str]] = []
    detail_rows: list[dict[str, str]] = []
    for row in sorted(rows, key=lambda r: (r["fault_id"], int(r["trial"]))):
        raw_path = find_raw_file(cfg.raw_context_dir, row["fault_id"], row["trial"], cfg.arm)
        context = load_context(raw_path)
        pred, rule_name = predict(context)
        out_rows.append({
            "baseline": BASELINE_NAME,
            "fault_id": row["fault_id"],
            "trial": row["trial"],
            "input_target_service": row["target_service"],
            "input_severity": row["severity"],
            "predicted_fault_name": pred,
            "true_fault_name": row[TARGET_COLUMN],
            "correct": str(int(pred == row[TARGET_COLUMN])),
        })
        detail_rows.append({
            "fault_id": row["fault_id"],
            "trial": row["trial"],
            "raw_context_path": str(raw_path),
            "matched_rule": rule_name,
            "predicted_fault_name": pred,
            "true_fault_name": row[TARGET_COLUMN],
            "correct": str(int(pred == row[TARGET_COLUMN])),
        })

    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "baseline", "fault_id", "trial", "input_target_service", "input_severity",
            "predicted_fault_name", "true_fault_name", "correct",
        ])
        writer.writeheader()
        writer.writerows(out_rows)

    detail_path = path.with_name("baseline_runtime_keyword_details.csv")
    with detail_path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(detail_rows[0].keys()))
        writer.writeheader()
        writer.writerows(detail_rows)
    return out_rows


def write_failures(path: Path, prediction_rows: list[dict[str, str]], cfg: Config, max_examples: int = 3) -> None:
    detail_path = cfg.output_dir / "baseline_runtime_keyword_details.csv"
    details = {(r["fault_id"], r["trial"]): r for r in csv.DictReader(detail_path.open())}
    failures = [r for r in prediction_rows if str(r["correct"]) == "0"][:max_examples]
    lines = ["# baseline_runtime_keyword failure cases", ""]
    if not failures:
        lines.append("No failures found. Inspect for overly broad rules or answer leakage.")
    for i, r in enumerate(failures, start=1):
        d = details[(r["fault_id"], r["trial"])]
        lines.extend([
            f"## Failure {i}: {r['fault_id']} trial {r['trial']}",
            "",
            "### 입력",
            f"- raw context: `{d['raw_context_path']}`",
            f"- input_target_service: `{r['input_target_service']}`",
            f"- input_severity: `{r['input_severity']}`",
            f"- matched_rule: `{d['matched_rule']}`",
            "- used evidence: runtime-observability context only (`C1_A`) — no GitOps/RAG/LLM response/ground-truth text",
            "",
            "### 예측 / 정답",
            f"- prediction: `{r['predicted_fault_name']}`",
            f"- ground truth: `{r['true_fault_name']}`",
            "",
            "### 실패 원인 가설",
            "- 단순 keyword rule은 cascade symptom과 root cause를 구분하지 못한다.",
            "- 여러 장애가 공통으로 `timeout`, `0 endpoints`, `BackOff`를 만들기 때문에 rule ordering에 민감하다.",
            "- 이 실패는 LLM/GitOps 방법이 넘어야 할 '증거 해석'의 최소 난점을 보여준다.",
            "",
        ])
    path.write_text("\n".join(lines))


def write_manifest(path: Path, cfg: Config, train: list[dict[str, str]], test: list[dict[str, str]], prediction_rows: list[dict[str, str]]) -> None:
    correct = sum(int(r["correct"]) for r in prediction_rows)
    manifest = {
        "baseline": BASELINE_NAME,
        "dataset_path": str(cfg.dataset_path),
        "dataset_sha256": sha256(cfg.dataset_path),
        "raw_context_dir": str(cfg.raw_context_dir),
        "arm": cfg.arm,
        "input_source": "V2.2 raw context field only; C1_A runtime-observability arm",
        "excluded_sources": ["GitOps", "RAG", "LLM response samples", "ground-truth root-cause text", "injection metadata"],
        "seed": cfg.seed,
        "split_strategy": cfg.split_strategy,
        "test_trials_per_fault": cfg.test_trials_per_fault,
        "train_rows": len(train),
        "test_rows": len(test),
        "rules": [{"label": label, "name": name} for label, name, _ in RULES],
        "metrics": {"accuracy": correct / len(prediction_rows), "correct": correct, "n": len(prediction_rows)},
        "artifacts": {
            "predictions": str(cfg.output_dir / "baseline_runtime_keyword_predictions.csv"),
            "details": str(cfg.output_dir / "baseline_runtime_keyword_details.csv"),
            "failures": str(cfg.output_dir / "baseline_runtime_keyword_failures.md"),
        },
    }
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="baselines/configs/baseline_runtime_keyword.json")
    args = parser.parse_args()

    cfg = load_config(Path(args.config))
    rows = read_dataset(cfg.dataset_path)
    if cfg.split_strategy != "stratified_trial_holdout":
        raise ValueError(f"Unsupported split strategy: {cfg.split_strategy}")
    train, test = stratified_trial_holdout(rows, seed=cfg.seed, k=cfg.test_trials_per_fault)

    cfg.output_dir.mkdir(parents=True, exist_ok=True)
    predictions_path = cfg.output_dir / "baseline_runtime_keyword_predictions.csv"
    prediction_rows = write_predictions(predictions_path, test, cfg)
    write_failures(cfg.output_dir / "baseline_runtime_keyword_failures.md", prediction_rows, cfg)
    write_manifest(cfg.output_dir / "baseline_runtime_keyword_manifest.json", cfg, train, test, prediction_rows)

    correct = sum(int(r["correct"]) for r in prediction_rows)
    print(f"{BASELINE_NAME} complete: {correct}/{len(prediction_rows)} correct -> {predictions_path}")


if __name__ == "__main__":
    main()

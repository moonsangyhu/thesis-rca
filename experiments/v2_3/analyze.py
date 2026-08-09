"""Pre-registered V2.3 paired analysis (no LLM calls or cluster access)."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import random
from pathlib import Path

from .config import CONDITIONS, FAULTS, TRIALS

BOOTSTRAP_SEED = 20260809
BOOTSTRAP_ITERATIONS = 50_000
THRESHOLDS = (0.5, 0.6, 0.7)


class AnalysisError(RuntimeError):
    pass


def _binary(value) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise AnalysisError(f"invalid binary outcome: {value!r}") from exc
    if parsed not in {0, 1}:
        raise AnalysisError(f"invalid binary outcome: {value!r}")
    return parsed


def validate_rows(rows: list[dict]) -> dict[tuple[str, int, str], dict]:
    if len(rows) != 180:
        raise AnalysisError(f"expected 180 rows, found {len(rows)}")
    indexed: dict[tuple[str, int, str], dict] = {}
    campaigns = set()
    for row in rows:
        fault = row.get("fault_id")
        try:
            trial = int(row.get("trial"))
        except (TypeError, ValueError) as exc:
            raise AnalysisError("invalid trial") from exc
        condition = row.get("context_condition")
        key = (fault, trial, condition)
        if fault not in FAULTS or trial not in TRIALS or condition not in CONDITIONS:
            raise AnalysisError(f"invalid result identity: {key}")
        if key in indexed:
            raise AnalysisError(f"duplicate result identity: {key}")
        campaigns.add(row.get("campaign_id"))
        for threshold in THRESHOLDS:
            _binary(row.get(f"correct_at_{threshold}"))
        indexed[key] = row
    expected = {(fault, trial, condition) for fault in FAULTS
                for trial in TRIALS for condition in CONDITIONS}
    missing = expected - set(indexed)
    if missing:
        raise AnalysisError(f"missing result identities: {len(missing)}")
    if len(campaigns) != 1 or None in campaigns or "" in campaigns:
        raise AnalysisError("results must belong to one non-empty campaign")
    return indexed


def _percentile(sorted_values: list[float], probability: float) -> float:
    if not sorted_values:
        raise AnalysisError("empty bootstrap distribution")
    position = probability * (len(sorted_values) - 1)
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = position - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def _fault_cluster_differences(indexed, threshold: float) -> dict[str, float]:
    field = f"correct_at_{threshold}"
    return {
        fault: sum(
            _binary(indexed[(fault, trial, "blind_procedural_rag")][field])
            - _binary(indexed[(fault, trial, "length_placebo")][field])
            for trial in TRIALS
        ) / len(TRIALS)
        for fault in FAULTS
    }


def cluster_bootstrap_ci(
    fault_differences: dict[str, float],
    *,
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
) -> tuple[float, float]:
    if iterations < 100:
        raise AnalysisError("bootstrap iterations must be at least 100")
    rng = random.Random(seed)
    values = [fault_differences[fault] for fault in FAULTS]
    distribution = sorted(
        sum(rng.choice(values) for _ in values) / len(values)
        for _ in range(iterations)
    )
    return _percentile(distribution, 0.025), _percentile(distribution, 0.975)


def exact_cluster_sign_flip_p(fault_differences: dict[str, float]) -> float:
    values = [fault_differences[fault] for fault in FAULTS]
    observed = abs(sum(values) / len(values))
    extreme = 0
    total = 0
    for signs in itertools.product((-1, 1), repeat=len(values)):
        statistic = abs(sum(sign * value for sign, value in zip(signs, values)) / len(values))
        extreme += statistic >= observed - 1e-12
        total += 1
    return extreme / total


def analyze_rows(rows: list[dict]) -> dict:
    indexed = validate_rows(rows)
    threshold_results = {}
    for threshold in THRESHOLDS:
        fault_differences = _fault_cluster_differences(indexed, threshold)
        delta = sum(fault_differences.values()) / len(fault_differences)
        threshold_results[str(threshold)] = {
            "blind_minus_placebo": delta,
            "fault_differences": fault_differences,
        }
    primary_faults = threshold_results["0.5"]["fault_differences"]
    ci_low, ci_high = cluster_bootstrap_ci(primary_faults)
    permutation_p = exact_cluster_sign_flip_p(primary_faults)
    primary_delta = threshold_results["0.5"]["blind_minus_placebo"]
    direction_stable = all(
        threshold_results[str(threshold)]["blind_minus_placebo"] > 0
        for threshold in THRESHOLDS
    )
    return {
        "rows": len(rows),
        "incidents": 60,
        "campaign_id": next(iter({row["campaign_id"] for row in rows})),
        "primary_estimand": "blind_procedural_rag-length_placebo",
        "primary_delta": primary_delta,
        "bootstrap_iterations": BOOTSTRAP_ITERATIONS,
        "bootstrap_seed": BOOTSTRAP_SEED,
        "fault_cluster_bootstrap_ci_95": [ci_low, ci_high],
        "exact_fault_cluster_sign_flip_p": permutation_p,
        "threshold_results": threshold_results,
        "threshold_direction_stable": direction_stable,
        "automated_strong_support_prerequisites": (
            primary_delta >= 0.10 and ci_low > 0 and direction_stable
        ),
        "human_primary_direction": "pending",
        "final_hypothesis_status": "pending_human_review",
    }


def load_rows(path: Path) -> list[dict]:
    with Path(path).open(newline="") as handle:
        return list(csv.DictReader(handle))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze complete V2.3 primary CSV")
    parser.add_argument("csv_path", type=Path)
    args = parser.parse_args(argv)
    result = analyze_rows(load_rows(args.csv_path))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

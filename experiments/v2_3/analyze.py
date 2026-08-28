"""Pre-registered V2.3 paired analysis (no LLM calls or cluster access)."""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import random
from pathlib import Path

from .config import CONDITIONS, FAULTS, MAIN_INCIDENTS, TRIALS

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


def _full_incidents() -> frozenset[tuple[str, int]]:
    return frozenset((fault, trial) for fault in FAULTS for trial in TRIALS)


def validate_rows(
    rows: list[dict], *, expected_incidents: frozenset[tuple[str, int]] | None = None
) -> dict[tuple[str, int, str], dict]:
    incidents = _full_incidents() if expected_incidents is None else expected_incidents
    expected_rows = len(incidents) * len(CONDITIONS)
    if len(rows) != expected_rows:
        raise AnalysisError(f"expected {expected_rows} rows, found {len(rows)}")
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
    expected = {(fault, trial, condition) for fault, trial in incidents
                for condition in CONDITIONS}
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


def _fault_cluster_differences(
    indexed, threshold: float, *, available_incidents: frozenset[tuple[str, int]],
    excluded_incidents: frozenset[tuple[str, int]] = frozenset(),
) -> dict[str, float]:
    field = f"correct_at_{threshold}"
    differences = {}
    for fault in FAULTS:
        included_trials = [
            trial for trial in TRIALS
            if (fault, trial) in available_incidents
            and (fault, trial) not in excluded_incidents
        ]
        if not included_trials:
            raise AnalysisError(f"sensitivity excludes every trial for {fault}")
        differences[fault] = sum(
            _binary(indexed[(fault, trial, "blind_procedural_rag")][field])
            - _binary(indexed[(fault, trial, "length_placebo")][field])
            for trial in included_trials
        ) / len(included_trials)
    return differences


def _sensitivity_result(
    indexed, excluded: frozenset[tuple[str, int]], *, available_incidents: frozenset[tuple[str, int]]
) -> dict:
    if not excluded.issubset(available_incidents):
        raise AnalysisError("sensitivity exclusion is outside the observed schedule")
    threshold_results = {}
    for threshold in THRESHOLDS:
        differences = _fault_cluster_differences(
            indexed, threshold, available_incidents=available_incidents,
            excluded_incidents=excluded
        )
        threshold_results[str(threshold)] = {
            "blind_minus_placebo": sum(differences.values()) / len(differences),
            "fault_differences": differences,
        }
    primary = threshold_results["0.5"]["fault_differences"]
    ci_low, ci_high = cluster_bootstrap_ci(primary)
    return {
        "excluded_incidents": [
            {"fault_id": fault, "trial": trial}
            for fault, trial in sorted(excluded)
        ],
        "incidents": len(available_incidents) - len(excluded),
        "primary_delta": threshold_results["0.5"]["blind_minus_placebo"],
        "fault_cluster_bootstrap_ci_95": [ci_low, ci_high],
        "exact_fault_cluster_sign_flip_p": exact_cluster_sign_flip_p(primary),
        "threshold_results": threshold_results,
        "threshold_direction_stable": all(
            threshold_results[str(threshold)]["blind_minus_placebo"] > 0
            for threshold in THRESHOLDS
        ),
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


def analyze_rows(
    rows: list[dict], *, expected_incidents: frozenset[tuple[str, int]] | None = None
) -> dict:
    available_incidents = _full_incidents() if expected_incidents is None else expected_incidents
    indexed = validate_rows(rows, expected_incidents=available_incidents)
    threshold_results = {}
    for threshold in THRESHOLDS:
        fault_differences = _fault_cluster_differences(
            indexed, threshold, available_incidents=available_incidents
        )
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
        "incidents": len(available_incidents),
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
        "treatment_integrity_sensitivity": {
            "exclude_f4_t3": _sensitivity_result(
                indexed, frozenset({("F4", 3)}),
                available_incidents=available_incidents,
            ),
            "exclude_f4_t4": _sensitivity_result(
                indexed, frozenset({("F4", 4)}),
                available_incidents=available_incidents,
            ),
            "exclude_f4_t3_and_t4": _sensitivity_result(
                indexed, frozenset({("F4", 3), ("F4", 4)}),
                available_incidents=available_incidents,
            ),
        },
    }


def load_rows(path: Path) -> list[dict]:
    with Path(path).open(newline="") as handle:
        return list(csv.DictReader(handle))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Analyze complete V2.3 primary CSV")
    parser.add_argument("csv_path", type=Path)
    parser.add_argument(
        "--main-schedule", action="store_true",
        help="require the approved 59-incident live schedule (F7-t5 excluded)",
    )
    args = parser.parse_args(argv)
    result = analyze_rows(
        load_rows(args.csv_path),
        expected_incidents=frozenset(MAIN_INCIDENTS) if args.main_schedule else None,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

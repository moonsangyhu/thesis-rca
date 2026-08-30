"""Pre-registered descriptive metrics; never imputes human abstentions."""

from __future__ import annotations

import math
import random
from collections import Counter
from typing import Iterable

from .io import AuditError


def wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> tuple[float, float]:
    if total <= 0 or not 0 <= successes <= total:
        raise AuditError("invalid Wilson inputs")
    p = successes / total
    denominator = 1 + z * z / total
    center = (p + z * z / (2 * total)) / denominator
    radius = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, center - radius), min(1.0, center + radius)


def count_boundaries(total: int, threshold: float = 0.20) -> tuple[int, int]:
    if total <= 0:
        return -1, 1
    green = [count for count in range(total + 1) if wilson_interval(count, total)[1] < threshold]
    red = [count for count in range(total + 1) if wilson_interval(count, total)[0] >= threshold]
    return (max(green) if green else -1, min(red) if red else total + 1)


def primary_status(discordant: int, non_abstain: int, abstain: int) -> str:
    if non_abstain == 0:
        return "NOT_EVALUATED_ABSTAIN"
    if abstain:
        return "GRAY_ABSTAIN"
    green_max, red_min = count_boundaries(non_abstain)
    if discordant <= green_max:
        return "GREEN"
    if discordant >= red_min:
        return "RED"
    return "GRAY"


def confusion(terra: Iterable[int], human: Iterable[int | str]) -> dict[str, object]:
    pairs = list(zip(terra, human))
    if any(t not in {0, 1} or h not in {0, 1, "A"} for t, h in pairs):
        raise AuditError("invalid paired rating")
    counts = Counter((t, h) for t, h in pairs if h != "A")
    abstain = sum(h == "A" for _, h in pairs)
    discordant = counts[(1, 0)] + counts[(0, 1)]
    n = len(pairs) - abstain
    return {
        "terra0_human0": counts[(0, 0)], "terra0_human1": counts[(0, 1)],
        "terra1_human0": counts[(1, 0)], "terra1_human1": counts[(1, 1)],
        "discordant": discordant, "n_non_abstain": n, "abstain": abstain,
        "wilson_95": wilson_interval(discordant, n) if n else None,
        "primary_status": primary_status(discordant, n, abstain),
    }


def cohen_kappa(left: Iterable[int], right: Iterable[int]) -> float | None:
    pairs = list(zip(left, right))
    if not pairs:
        return None
    if any(a not in {0, 1} or b not in {0, 1} for a, b in pairs):
        raise AuditError("binary kappa requires 0/1")
    observed = sum(a == b for a, b in pairs) / len(pairs)
    p_l = sum(a == 1 for a, _ in pairs) / len(pairs)
    p_r = sum(b == 1 for _, b in pairs) / len(pairs)
    expected = p_l * p_r + (1 - p_l) * (1 - p_r)
    return None if expected == 1 else (observed - expected) / (1 - expected)


def weighted_kappa(left: Iterable[int], right: Iterable[int], maximum: int = 3) -> float | None:
    pairs = list(zip(left, right))
    if not pairs:
        return None
    if any(not 0 <= a <= maximum or not 0 <= b <= maximum for a, b in pairs):
        raise AuditError("weighted kappa rating out of range")
    size = maximum + 1
    observed = [[0 for _ in range(size)] for _ in range(size)]
    left_counts, right_counts = [0] * size, [0] * size
    for a, b in pairs:
        observed[a][b] += 1; left_counts[a] += 1; right_counts[b] += 1
    weighted_observed = sum(
        ((i - j) / maximum) ** 2 * observed[i][j]
        for i in range(size) for j in range(size)
    ) / len(pairs)
    weighted_expected = sum(
        ((i - j) / maximum) ** 2 * left_counts[i] * right_counts[j]
        for i in range(size) for j in range(size)
    ) / (len(pairs) ** 2)
    return None if weighted_expected == 0 else 1 - weighted_observed / weighted_expected


def _binomial_cdf(x: int, n: int, probability: float) -> float:
    return sum(
        math.comb(n, k) * probability ** k * (1 - probability) ** (n - k)
        for k in range(x + 1)
    )


def exact_binomial_interval(successes: int, total: int, alpha: float = 0.05) -> tuple[float, float]:
    """Two-sided Clopper-Pearson interval, implemented without scipy."""
    if total <= 0 or not 0 <= successes <= total or not 0 < alpha < 1:
        raise AuditError("invalid exact-binomial inputs")
    if successes == 0:
        lower = 0.0
    else:
        lo, hi = 0.0, successes / total
        for _ in range(80):
            mid = (lo + hi) / 2
            upper_tail = 1 - _binomial_cdf(successes - 1, total, mid)
            if upper_tail < alpha / 2: lo = mid
            else: hi = mid
        lower = (lo + hi) / 2
    if successes == total:
        upper = 1.0
    else:
        lo, hi = successes / total, 1.0
        for _ in range(80):
            mid = (lo + hi) / 2
            lower_tail = _binomial_cdf(successes, total, mid)
            if lower_tail > alpha / 2: lo = mid
            else: hi = mid
        upper = (lo + hi) / 2
    return lower, upper


def directional_alert(terra_only: int, human_only: int) -> dict[str, object]:
    total = terra_only + human_only
    if total == 0:
        return {"alert": False, "interval": None, "discordant_n": 0}
    interval = exact_binomial_interval(terra_only, total)
    return {
        "alert": interval[1] < 0.5 or interval[0] > 0.5,
        "interval": interval, "discordant_n": total,
    }


def incident_cluster_kappa_bootstrap(
    incident_pairs: dict[str, list[tuple[int, int]]], repeats: int = 50_000,
    seed: int = 20_260_830,
) -> tuple[float, float] | None:
    if not incident_pairs or repeats < 100:
        raise AuditError("invalid cluster bootstrap input")
    keys = sorted(incident_pairs)
    generator = random.Random(seed)
    estimates = []
    for _ in range(repeats):
        sampled = [generator.choice(keys) for _ in keys]
        pairs = [pair for key in sampled for pair in incident_pairs[key]]
        estimate = cohen_kappa([a for a, _ in pairs], [b for _, b in pairs])
        if estimate is not None:
            estimates.append(estimate)
    if not estimates:
        return None
    estimates.sort()
    return estimates[int(0.025 * (len(estimates) - 1))], estimates[int(0.975 * (len(estimates) - 1))]

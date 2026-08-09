"""Three-condition assembly, deterministic placebo, and order scheduling."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass

from .config import CONDITIONS, FAULTS, SCHEDULE_SEED, TRIALS
from .scanner import ForbiddenLexicon, LeakageScanner, ScanReport, sha256_text
from .retrieval import BlindProcedure

ADDITIONAL_HEADING = "## Additional Context\n"
PLACEBO_VERSION = "neutral-corpus-metric-fit-1"
_NEUTRAL_CORPUS = (
    "General records follow a stable administrative sequence. "
    "Routine notes use an ordinary review cadence. "
    "Supplementary material remains informational and independent. "
)


def proxy_tokens(text: str) -> int:
    """Frozen local proxy; it deliberately does not claim model-token parity."""
    return math.ceil(len((text or "").encode("utf-8")) / 4)


def text_metrics(text: str) -> dict[str, int]:
    return {
        "chars": len(text),
        "bytes": len(text.encode("utf-8")),
        "proxy_tokens": proxy_tokens(text),
    }


def _neutral_base(length: int) -> list[str]:
    if length <= 0:
        return []
    repeated = (_NEUTRAL_CORPUS * (length // len(_NEUTRAL_CORPUS) + 1))[:length]
    return list(repeated)


def make_length_placebo(target_chars: int, target_bytes: int) -> str:
    """Create independent neutral text matching character and byte targets.

    Only the two target metrics are inputs.  UTF-8 filler characters are drawn
    from a fixed neutral alphabet to realize any valid byte/character pair.
    Matching bytes also fixes the frozen proxy-token count exactly.
    """
    if target_chars < 0 or not target_chars <= target_bytes <= 4 * target_chars:
        raise ValueError("impossible UTF-8 character/byte target")
    chars = _neutral_base(target_chars)
    extra = target_bytes - target_chars
    index = 0
    for extra_bytes, symbol in ((3, "🟦"), (2, "중"), (1, "§")):
        count, extra = divmod(extra, extra_bytes)
        if index + count > target_chars:
            raise ValueError("cannot fit byte target into character target")
        chars[index:index + count] = [symbol] * count
        index += count
    if extra:
        raise ValueError("unresolved UTF-8 byte target")
    result = "".join(chars)
    if text_metrics(result)["chars"] != target_chars or text_metrics(result)["bytes"] != target_bytes:
        raise AssertionError("placebo metric construction failed")
    return result


@dataclass(frozen=True)
class AssembledCondition:
    condition: str
    runtime_context: str
    additional_context: str
    full_context: str
    runtime_context_hash: str
    additional_context_hash: str
    full_context_hash: str
    common_prompt_hash: str
    insertion_index: int
    additional_metrics: dict[str, int]
    scan_report: ScanReport
    retrieval_provenance: dict | None


class ConditionAssembler:
    def __init__(self, scanner: LeakageScanner | None = None):
        self.scanner = scanner or LeakageScanner()

    def assemble_all(
        self,
        runtime_context: str,
        blind_procedure: BlindProcedure,
        lexicon: ForbiddenLexicon,
    ) -> dict[str, AssembledCondition]:
        # Runtime is scanned only for harness-only leakage. Legitimate observed
        # Kubernetes labels/entities remain valid runtime evidence.
        runtime_report = self.scanner.require_clean(
            runtime_context, lexicon, runtime_scope=True
        )
        if not isinstance(blind_procedure, BlindProcedure):
            raise TypeError("blind procedure must include retrieval/masking provenance")
        blind_procedure.validate(lexicon, runtime_context)
        blind_text = blind_procedure.text
        blind_report = self.scanner.require_clean(blind_text, lexicon)
        metrics = text_metrics(blind_text)
        placebo = make_length_placebo(metrics["chars"], metrics["bytes"])
        placebo_report = self.scanner.require_clean(placebo, lexicon)
        additional = {
            "runtime": "",
            "length_placebo": placebo,
            "blind_procedural_rag": blind_text,
        }
        reports = {
            "runtime": runtime_report,
            "length_placebo": placebo_report,
            "blind_procedural_rag": blind_report,
        }
        insertion_index = len(runtime_context) + 2
        common_prefix = f"{runtime_context}\n\n{ADDITIONAL_HEADING}"
        common_hash = sha256_text(common_prefix + "{additional_context}")
        result: dict[str, AssembledCondition] = {}
        for condition in CONDITIONS:
            extra = additional[condition]
            full = common_prefix + extra
            result[condition] = AssembledCondition(
                condition=condition,
                runtime_context=runtime_context,
                additional_context=extra,
                full_context=full,
                runtime_context_hash=sha256_text(runtime_context),
                additional_context_hash=sha256_text(extra),
                full_context_hash=sha256_text(full),
                common_prompt_hash=common_hash,
                insertion_index=insertion_index,
                additional_metrics=text_metrics(extra),
                scan_report=reports[condition],
                retrieval_provenance=(
                    blind_procedure.provenance if condition == "blind_procedural_rag" else None
                ),
            )
        require_treatment_integrity(result)
        return result


def require_treatment_integrity(items: dict[str, AssembledCondition]) -> None:
    if set(items) != set(CONDITIONS):
        raise ValueError("all three context conditions are required")
    if len({x.runtime_context_hash for x in items.values()}) != 1:
        raise ValueError("runtime context hash mismatch")
    if len({x.insertion_index for x in items.values()}) != 1:
        raise ValueError("additional-context insertion mismatch")
    if len({x.common_prompt_hash for x in items.values()}) != 1:
        raise ValueError("common prompt hash mismatch")
    blind = items["blind_procedural_rag"].additional_metrics
    placebo = items["length_placebo"].additional_metrics
    for metric in ("chars", "bytes"):
        if blind[metric] != placebo[metric]:
            raise ValueError(f"placebo {metric} mismatch")
    denom = max(1, blind["proxy_tokens"])
    if abs(blind["proxy_tokens"] - placebo["proxy_tokens"]) / denom > 0.01:
        raise ValueError("placebo proxy-token difference exceeds 1%")


_LATIN_SQUARE = (
    CONDITIONS,
    (CONDITIONS[1], CONDITIONS[2], CONDITIONS[0]),
    (CONDITIONS[2], CONDITIONS[0], CONDITIONS[1]),
)


def latin_square_schedule(seed: int = SCHEDULE_SEED) -> dict[tuple[str, int], tuple[str, ...]]:
    """Return a frozen, balanced 3x3 Latin-square assignment for 60 incidents."""
    # A seed-dependent rotation is enough to freeze a different square while
    # preserving exact balance (20 appearances per condition in each position).
    rotation = int(hashlib.sha256(str(seed).encode()).hexdigest(), 16) % 3
    schedule: dict[tuple[str, int], tuple[str, ...]] = {}
    for index, key in enumerate((f, t) for f in FAULTS for t in TRIALS):
        schedule[key] = _LATIN_SQUARE[(index + rotation) % 3]
    return schedule


def schedule_hash(schedule: dict[tuple[str, int], tuple[str, ...]]) -> str:
    serial = "\n".join(
        f"{fault},{trial},{','.join(order)}"
        for (fault, trial), order in sorted(schedule.items())
    )
    return sha256_text(serial)

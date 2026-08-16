"""Fail-closed lexical leakage scanner for V2.3 generator inputs."""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass, field

SCANNER_VERSION = "v2.3-nfkc-alias-ngram-2"
MAX_FORBIDDEN_TERM_TOKENS = 128


def normalize(text: str) -> str:
    """NFKC/lowercase text with punctuation and whitespace folded."""
    value = unicodedata.normalize("NFKC", text or "").lower()
    return " ".join(re.sub(r"[\W_]+", " ", value, flags=re.UNICODE).split())


def sha256_text(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def minimum_token_ngrams(tokens: list[str], minimum: int) -> tuple[str, ...]:
    """Return the smallest sufficient adjacent grams with a hard work bound.

    The full normalized term is checked separately.  For a changed suffix or
    prefix, every longer partial match contains at least one adjacent gram of
    ``minimum`` tokens, so enumerating every size from N-1 down to ``minimum``
    adds no detection coverage and grows quadratically in pattern count.
    """
    if minimum < 1:
        raise ValueError("token n-gram minimum must be positive")
    if len(tokens) > MAX_FORBIDDEN_TERM_TOKENS:
        raise ValueError("forbidden term exceeds token limit")
    if len(tokens) < minimum:
        return ()
    return tuple(
        " ".join(tokens[index:index + minimum])
        for index in range(len(tokens) - minimum + 1)
    )


@dataclass(frozen=True)
class ForbiddenLexicon:
    canonical_labels: tuple[str, ...] = ()
    aliases: tuple[str, ...] = ()
    metadata: tuple[str, ...] = ()
    entities: tuple[str, ...] = ()
    commands: tuple[str, ...] = ()
    field_values: tuple[str, ...] = ()
    harness_markers: tuple[str, ...] = ()

    def categories(self, runtime_scope: bool = False) -> dict[str, tuple[str, ...]]:
        if runtime_scope:
            return {"harness_markers": self.harness_markers}
        return {
            "canonical_labels": self.canonical_labels,
            "aliases": self.aliases,
            "metadata": self.metadata,
            "entities": self.entities,
            "commands": self.commands,
            "field_values": self.field_values,
            "harness_markers": self.harness_markers,
        }

    @property
    def hash(self) -> str:
        payload = {k: list(v) for k, v in self.categories().items()}
        return sha256_text(json.dumps(payload, sort_keys=True, ensure_ascii=False))


@dataclass(frozen=True)
class ScanMatch:
    category: str
    kind: str
    term: str
    start: int
    end: int


@dataclass
class ScanReport:
    context_hash: str
    lexicon_hash: str
    matches: list[ScanMatch] = field(default_factory=list)
    scanner_version: str = SCANNER_VERSION

    @property
    def match_count(self) -> int:
        return len(self.matches)

    @property
    def category_counts(self) -> dict[str, int]:
        result: dict[str, int] = {}
        for match in self.matches:
            result[match.category] = result.get(match.category, 0) + 1
        return result

    def to_dict(self) -> dict:
        return {
            "scanner_version": self.scanner_version,
            "lexicon_hash": self.lexicon_hash,
            "context_hash": self.context_hash,
            "match_count": self.match_count,
            "category_counts": self.category_counts,
            "matches": [m.__dict__ for m in self.matches],
        }


class LeakageDetected(RuntimeError):
    pass


class LeakageScanner:
    """Exact/alias and token n-gram scan over normalized text.

    Exact matching covers single-token terms.  Multi-token terms are also
    checked as token n-grams, making punctuation/spacing aliases visible after
    NFKC folding.  Reports retain normalized spans; the untouched source belongs
    in raw provenance and is never returned as generator context.
    """

    def scan(
        self, text: str, lexicon: ForbiddenLexicon, *, runtime_scope: bool = False
    ) -> ScanReport:
        folded = normalize(text)
        compact_text = folded.replace(" ", "")
        report = ScanReport(sha256_text(text), lexicon.hash)
        seen: set[tuple[str, str, int, int]] = set()

        def add(category: str, kind: str, term: str, start: int, end: int) -> None:
            key = (category, term, start, end)
            if key not in seen:
                seen.add(key)
                report.matches.append(ScanMatch(category, kind, term, start, end))

        for category, raw_terms in lexicon.categories(runtime_scope).items():
            for raw_term in raw_terms:
                if raw_term.startswith("re:"):
                    try:
                        pattern = re.compile(raw_term[3:], re.IGNORECASE)
                    except re.error as exc:
                        raise ValueError(f"invalid forbidden regex: {raw_term}") from exc
                    for found in pattern.finditer(folded):
                        add(category, "regex_alias", raw_term, found.start(), found.end())
                    continue
                term = normalize(raw_term)
                if not term:
                    continue
                tokens = term.split()
                if len(tokens) > MAX_FORBIDDEN_TERM_TOKENS:
                    raise ValueError("forbidden term exceeds token limit")
                pattern = re.compile(rf"(?<!\w){re.escape(term)}(?!\w)")
                for found in pattern.finditer(folded):
                    add(category, "exact_or_alias", term, found.start(), found.end())

                # Detect separator-removal and concatenation evasions.  The
                # compact coordinates are intentionally reported as normalized
                # spans; raw text remains separate provenance.
                compact_term = term.replace(" ", "")
                fault_marker = (
                    re.fullmatch(r"f(\d+)", compact_term)
                    if category == "harness_markers" else None
                )
                if fault_marker:
                    marker_pattern = re.compile(
                        rf"(?<!\w)f\s*{re.escape(fault_marker.group(1))}(?!\w)"
                    )
                    for found in marker_pattern.finditer(folded):
                        add(
                            category, "fault_id_separator_variant", term,
                            found.start(), found.end(),
                        )
                    continue
                compact_minimum = (
                    2 if category in {"harness_markers", "field_values"} else 4
                )
                if len(compact_term) >= compact_minimum:
                    start = compact_text.find(compact_term)
                    while start >= 0:
                        add(category, "compact_substring", term, start, start + len(compact_term))
                        start = compact_text.find(compact_term, start + 1)

                # A changed suffix in a path/command must not evade the gate.
                # Require at least two adjacent tokens (or three for commands)
                # to avoid single common-word false positives.
                minimum = 3 if category == "commands" else 2
                for gram in minimum_token_ngrams(tokens, minimum):
                    gram_pattern = re.compile(rf"(?<!\w){re.escape(gram)}(?!\w)")
                    for found in gram_pattern.finditer(folded):
                        add(category, "token_ngram", gram, found.start(), found.end())
        return report

    def require_clean(
        self, text: str, lexicon: ForbiddenLexicon, *, runtime_scope: bool = False
    ) -> ScanReport:
        report = self.scan(text, lexicon, runtime_scope=runtime_scope)
        if report.match_count:
            raise LeakageDetected(
                f"forbidden leakage detected: {report.match_count} match(es); "
                f"categories={report.category_counts}"
            )
        return report

"""Runtime-query-only retrieval and auditable procedure masking boundary."""

from __future__ import annotations

import re
import unicodedata
import math
from dataclasses import asdict, dataclass

from .scanner import (
    SCANNER_VERSION, ForbiddenLexicon, LeakageScanner, normalize, sha256_text,
)

MASKER_VERSION = "v2.3-procedure-mask-1"


@dataclass(frozen=True)
class RetrievalChunk:
    source_id: str
    text: str
    score: float
    start: int
    end: int


@dataclass(frozen=True)
class RemovedSpan:
    category: str
    term: str
    start: int
    end: int


@dataclass(frozen=True)
class BlindProcedure:
    text: str
    provenance: dict

    def validate(
        self, lexicon: ForbiddenLexicon | None = None, runtime_context: str | None = None
    ) -> None:
        required = {
            "query_origin", "query_text", "query_hash", "query_normalized",
            "query_normalized_hash",
            "query_source_text", "query_source_hash", "query_removed_spans",
            "runtime_context_hash", "corpus_version",
            "masker_version", "scanner_version", "lexicon_hash", "candidates",
            "removed_spans", "masked_procedure_hash",
        }
        if set(self.provenance) != required:
            raise ValueError("blind procedure provenance schema mismatch")
        if self.provenance["query_origin"] != "runtime_only":
            raise ValueError("retrieval query is not runtime-only")
        if self.provenance["masker_version"] != MASKER_VERSION:
            raise ValueError("masker version mismatch")
        if self.provenance["scanner_version"] != SCANNER_VERSION:
            raise ValueError("scanner version mismatch")
        query_normalized = self.provenance["query_normalized"]
        query_text = self.provenance["query_text"]
        if not isinstance(query_text, str) or not query_text or not query_normalized:
            raise ValueError("missing normalized retrieval query")
        if normalize(query_text) != query_normalized:
            raise ValueError("normalized retrieval query mismatch")
        if self.provenance["query_hash"] != sha256_text(query_text):
            raise ValueError("retrieval query text hash mismatch")
        if self.provenance["query_normalized_hash"] != sha256_text(query_normalized):
            raise ValueError("retrieval query hash mismatch")
        if self.provenance["masked_procedure_hash"] != sha256_text(self.text):
            raise ValueError("masked procedure hash mismatch")
        if not self.provenance["candidates"] or not self.provenance["corpus_version"]:
            raise ValueError("incomplete retrieval provenance")
        if lexicon is not None and self.provenance["lexicon_hash"] != lexicon.hash:
            raise ValueError("retrieval lexicon hash mismatch")
        if runtime_context is not None:
            if self.provenance["runtime_context_hash"] != sha256_text(runtime_context):
                raise ValueError("retrieval runtime hash mismatch")
            query_source = self.provenance["query_source_text"]
            if self.provenance["query_source_hash"] != sha256_text(query_source):
                raise ValueError("retrieval query source hash mismatch")
            if normalize(query_source) not in normalize(runtime_context):
                raise ValueError("retrieval query is not derived from runtime context")
        source_length = len(self.provenance["query_source_text"])
        for removed in self.provenance["query_removed_spans"]:
            if set(removed) != {"category", "term", "start", "end"}:
                raise ValueError("query removed-span schema mismatch")
            if (
                removed["start"] < 0 or removed["end"] < removed["start"]
                or removed["end"] > source_length
            ):
                raise ValueError("invalid query removed-span provenance")
        if lexicon is not None:
            expected_query, expected_removals = BlindProcedureBuilder._mask(
                self.provenance["query_source_text"],
                BlindProcedureBuilder._query_lexicon(lexicon),
            )
            if expected_query != self.provenance["query_text"] or [
                asdict(item) for item in expected_removals
            ] != self.provenance["query_removed_spans"]:
                raise ValueError("retrieval query masking provenance mismatch")
        candidates = self.provenance["candidates"]
        candidate_lengths: dict[int, int] = {}
        for expected_rank, candidate in enumerate(candidates, 1):
            if set(candidate) != {
                "rank", "source_id", "chunk_start", "chunk_end", "score",
                "source_text_hash", "source_length", "snapshot_locator",
            }:
                raise ValueError("retrieval candidate schema mismatch")
            if candidate["rank"] != expected_rank or not candidate["source_id"]:
                raise ValueError("retrieval candidate rank/source mismatch")
            expected_locator = (
                f"{self.provenance['corpus_version']}:{candidate['source_id']}:"
                f"{candidate['chunk_start']}:{candidate['chunk_end']}"
            )
            if candidate["snapshot_locator"] != expected_locator:
                raise ValueError("retrieval snapshot locator mismatch")
            if (
                candidate["chunk_start"] < 0
                or candidate["chunk_end"] < candidate["chunk_start"]
                or candidate["source_length"] < 0
                or not math.isfinite(float(candidate["score"]))
                or re.fullmatch(r"[0-9a-f]{64}", candidate["source_text_hash"]) is None
            ):
                raise ValueError("invalid retrieval candidate provenance")
            candidate_lengths[expected_rank] = candidate["source_length"]
        for removed in self.provenance["removed_spans"]:
            if set(removed) != {"category", "term", "start", "end", "rank"}:
                raise ValueError("removed-span schema mismatch")
            rank = removed["rank"]
            if (
                rank not in candidate_lengths or not removed["term"]
                or removed["category"] not in lexicon.categories()
                or removed["start"] < 0 or removed["end"] < removed["start"]
                or removed["end"] > candidate_lengths[rank]
            ):
                raise ValueError("invalid removed-span provenance")


class BlindProcedureBuilder:
    def __init__(self, scanner: LeakageScanner | None = None):
        self.scanner = scanner or LeakageScanner()

    @staticmethod
    def _query_lexicon(lexicon: ForbiddenLexicon) -> ForbiddenLexicon:
        # Workload/entity names observed in runtime are legitimate retrieval
        # features. Ground-truth labels, aliases, injection commands/values,
        # and harness markers are not.
        return ForbiddenLexicon(
            canonical_labels=lexicon.canonical_labels,
            aliases=lexicon.aliases,
            commands=lexicon.commands,
            field_values=lexicon.field_values,
            harness_markers=lexicon.harness_markers,
        )

    @staticmethod
    def _mask(text: str, lexicon: ForbiddenLexicon) -> tuple[str, list[RemovedSpan]]:
        value = unicodedata.normalize("NFKC", text)
        removed: list[RemovedSpan] = []
        occupied: list[tuple[int, int]] = []
        ordered_terms = sorted(
            (
                (category, raw_term)
                for category, terms in lexicon.categories().items()
                for raw_term in terms
            ),
            key=lambda item: len(normalize(item[1])),
            reverse=True,
        )
        for category, raw_term in ordered_terms:
            if raw_term.startswith("re:"):
                pattern = re.compile(raw_term[3:], re.IGNORECASE)
            else:
                tokens = normalize(raw_term).split()
                if not tokens:
                    continue
                pattern = re.compile(
                    r"(?<!\w)" + r"[\W_]*".join(map(re.escape, tokens)) + r"(?!\w)",
                    re.IGNORECASE,
                )

            for match in pattern.finditer(value):
                span = (match.start(), match.end())
                if any(span[0] < end and start < span[1] for start, end in occupied):
                    continue
                occupied.append(span)
                removed.append(RemovedSpan(category, raw_term, *span))

        masked = value
        for item in sorted(removed, key=lambda match: match.start, reverse=True):
            masked = masked[:item.start] + "[MASKED]" + masked[item.end:]
        return masked, sorted(removed, key=lambda match: match.start)

    def sanitize_runtime_query(
        self, runtime_context: str, raw_query: str, lexicon: ForbiddenLexicon
    ) -> tuple[str, list[RemovedSpan]]:
        if normalize(raw_query) not in normalize(runtime_context):
            raise ValueError("retrieval query source is not in frozen runtime context")
        query_lexicon = self._query_lexicon(lexicon)
        sanitized, removals = self._mask(raw_query, query_lexicon)
        self.scanner.require_clean(sanitized, query_lexicon)
        return sanitized, removals

    def build(
        self,
        *,
        runtime_context: str,
        runtime_query: str,
        runtime_query_source: str | None = None,
        chunks: tuple[RetrievalChunk, ...],
        corpus_version: str,
        lexicon: ForbiddenLexicon,
    ) -> BlindProcedure:
        if not runtime_context.strip() or not runtime_query.strip() or not chunks or not corpus_version.strip():
            raise ValueError("query, retrieval chunks, and corpus version are required")
        if runtime_query_source is None:
            runtime_query_source = runtime_query
            self.scanner.require_clean(runtime_query, self._query_lexicon(lexicon))
            query_removals: list[RemovedSpan] = []
        else:
            expected_query, query_removals = self.sanitize_runtime_query(
                runtime_context, runtime_query_source, lexicon
            )
            if expected_query != runtime_query:
                raise ValueError("sanitized retrieval query mismatch")
        masked_parts: list[str] = []
        removals: list[dict] = []
        candidates: list[dict] = []
        for rank, chunk in enumerate(chunks, 1):
            if not chunk.source_id or chunk.start < 0 or chunk.end < chunk.start:
                raise ValueError("invalid retrieval chunk provenance")
            if not math.isfinite(float(chunk.score)):
                raise ValueError("retrieval score must be finite")
            masked, removed = self._mask(chunk.text, lexicon)
            masked_parts.append(masked.strip())
            removals.extend({**asdict(item), "rank": rank} for item in removed)
            candidates.append(
                {
                    "rank": rank,
                    "source_id": chunk.source_id,
                    "chunk_start": chunk.start,
                    "chunk_end": chunk.end,
                    "score": float(chunk.score),
                    "source_text_hash": sha256_text(chunk.text),
                    "source_length": len(chunk.text),
                    "snapshot_locator": (
                        f"{corpus_version}:{chunk.source_id}:{chunk.start}:{chunk.end}"
                    ),
                }
            )
        procedure = "\n\n".join(masked_parts)
        report = self.scanner.require_clean(procedure, lexicon)
        provenance = {
            "query_origin": "runtime_only",
            "query_text": runtime_query,
            "query_hash": sha256_text(runtime_query),
            "query_normalized": normalize(runtime_query),
            "query_normalized_hash": sha256_text(normalize(runtime_query)),
            "query_source_text": runtime_query_source,
            "query_source_hash": sha256_text(runtime_query_source),
            "query_removed_spans": [asdict(item) for item in query_removals],
            "runtime_context_hash": sha256_text(runtime_context),
            "corpus_version": corpus_version,
            "masker_version": MASKER_VERSION,
            "scanner_version": report.scanner_version,
            "lexicon_hash": lexicon.hash,
            "candidates": candidates,
            "removed_spans": removals,
            "masked_procedure_hash": sha256_text(procedure),
        }
        result = BlindProcedure(procedure, provenance)
        result.validate(lexicon, runtime_context)
        return result

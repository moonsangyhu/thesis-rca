"""Byte-equivalent procedure reconstruction from an immutable Chroma copy."""

from __future__ import annotations

import hashlib
import sqlite3
import sys
import unicodedata
from pathlib import Path
from typing import Any

from .constants import COLLECTION_NAME
from .io import AuditError, tree_manifest

REDACTION_BYTES = b"[REDACTED]"
RECONSTRUCTION_SPEC = "v2.4-python311-str-strip-lf2-redacted-1"


def require_python311(version: tuple[int, int] | None = None) -> None:
    actual = version or (sys.version_info.major, sys.version_info.minor)
    if actual != (3, 11):
        raise AuditError(f"Python 3.11 required, got {actual[0]}.{actual[1]}")


class StoredDocuments:
    """Read stored documents with stdlib SQLite; no Chroma client is opened."""

    def __init__(self, root: Path):
        self.root = root
        self.before = tree_manifest(root)
        uri = f"file:{(root / 'chroma.sqlite3').resolve()}?mode=ro&immutable=1"
        self.connection = sqlite3.connect(uri, uri=True)
        self.connection.execute("PRAGMA query_only=ON")
        rows = self.connection.execute(
            "SELECT c.id, s.id FROM collections c JOIN segments s "
            "ON s.collection=c.id WHERE c.name=? "
            "AND s.type='urn:chroma:segment/metadata/sqlite'",
            (COLLECTION_NAME,),
        ).fetchall()
        if len(rows) != 1:
            self.connection.close()
            raise AuditError(f"collection must resolve exactly once, got {len(rows)}")
        self.collection_id, self.segment_id = rows[0]

    def get(self, source_id: str) -> str:
        rows = self.connection.execute(
            "SELECT m.string_value FROM embeddings e "
            "JOIN embedding_metadata m ON m.id=e.id "
            "WHERE e.segment_id=? AND e.embedding_id=? "
            "AND m.key='chroma:document'",
            (self.segment_id, source_id),
        ).fetchall()
        if len(rows) != 1 or not isinstance(rows[0][0], str):
            raise AuditError(f"stored document must resolve exactly once: {source_id}")
        return rows[0][0]

    def close(self) -> None:
        self.connection.close()
        after = tree_manifest(self.root)
        if after["tree_sha256"] != self.before["tree_sha256"]:
            raise AuditError("immutable SQLite open changed working tree")

    def __enter__(self) -> "StoredDocuments":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def reconstruct(raw: dict[str, Any], documents: StoredDocuments) -> tuple[str, list[dict[str, Any]]]:
    provenance = raw.get("retrieval_provenance")
    if raw.get("context_condition") != "blind_procedural_rag" or not isinstance(provenance, dict):
        raise AuditError("blind RAG retrieval provenance required")
    candidates = provenance.get("candidates")
    removals = provenance.get("removed_spans")
    if not isinstance(candidates, list) or not isinstance(removals, list):
        raise AuditError("invalid reconstruction provenance")
    valid_ranks = set(range(1, len(candidates) + 1))
    for span in removals:
        if set(span) != {"category", "term", "start", "end", "rank"}:
            raise AuditError("removed span schema mismatch")
        if (
            type(span["rank"]) is not int or span["rank"] not in valid_ranks
            or type(span["start"]) is not int or type(span["end"]) is not int
            or not isinstance(span["category"], str) or not span["category"]
            or not isinstance(span["term"], str) or not span["term"]
        ):
            raise AuditError("removed span type/orphan-rank mismatch")
    pieces: list[str] = []
    evidence = []
    for expected_rank, candidate in enumerate(candidates, 1):
        expected_keys = {
            "rank", "source_id", "chunk_start", "chunk_end", "score",
            "source_text_hash", "source_length", "snapshot_locator",
        }
        if set(candidate) != expected_keys or candidate["rank"] != expected_rank:
            raise AuditError("candidate schema/rank mismatch")
        text = documents.get(candidate["source_id"])
        raw_bytes = text.encode("utf-8", "strict")
        if raw_bytes.decode("utf-8", "strict") != text:
            raise AuditError("UTF-8 roundtrip mismatch")
        if len(text) != candidate["source_length"]:
            raise AuditError("source length mismatch")
        if hashlib.sha256(raw_bytes).hexdigest() != candidate["source_text_hash"]:
            raise AuditError("source text hash mismatch")
        start, end = candidate["chunk_start"], candidate["chunk_end"]
        if start != 0 or end != len(text):
            raise AuditError("stored document/offset mismatch")
        expected_locator = (
            f"{provenance['corpus_version']}:{candidate['source_id']}:{start}:{end}"
        )
        if candidate["snapshot_locator"] != expected_locator:
            raise AuditError("snapshot locator mismatch")
        spans = [item for item in removals if item.get("rank") == expected_rank]
        previous_start = len(text)
        for span in sorted(spans, key=lambda item: item.get("start", -1), reverse=True):
            span_start, span_end = span["start"], span["end"]
            if not (0 <= span_start < span_end <= len(text)) or span_end > previous_start:
                raise AuditError("overlapping/out-of-range removed span")
            original = text[span_start:span_end]
            compact_original = "".join(
                character for character in unicodedata.normalize("NFKC", original).casefold()
                if character.isalnum()
            )
            compact_term = "".join(
                character for character in unicodedata.normalize("NFKC", span["term"]).casefold()
                if character.isalnum()
            )
            if compact_original != compact_term:
                raise AuditError("removed span term does not match original substring")
            text = text[:span_start] + REDACTION_BYTES.decode("ascii") + text[span_end:]
            previous_start = span_start
        pieces.append(text.strip())
        evidence.append({
            "rank": expected_rank,
            "source_id": candidate["source_id"],
            "source_text_hash": candidate["source_text_hash"],
            "source_length": candidate["source_length"],
        })
    result = "\n\n".join(pieces)
    digest = hashlib.sha256(result.encode("utf-8", "strict")).hexdigest()
    if digest != provenance.get("masked_procedure_hash"):
        raise AuditError("masked procedure hash mismatch")
    if digest != raw.get("additional_context_hash"):
        raise AuditError("additional context hash mismatch")
    return result, evidence

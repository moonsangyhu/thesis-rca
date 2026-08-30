"""Phase-specific distribution schema and leakage scanners."""

from __future__ import annotations

import base64
import binascii
import json
import re
import unicodedata
import urllib.parse
import zipfile
import io
import csv
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .constants import CORRECTNESS_FIELDS, SEMANTIC_FIELDS
from .io import AuditError, sha256_bytes

COMMON_FORBIDDEN_KEYS = frozenset({
    "fault_id", "trial", "fault_name", "campaign_id", "context_condition",
    "representative_score", "judge_votes", "majority_label", "generation_split",
    "provider", "model", "source_id", "source_path", "retrieval_score", "rank",
})
FORBIDDEN_MARKERS = (
    "length_placebo", "blind_procedural_rag", "v2-3-codex-20260830-primary03",
    "gpt-5.6-terra", "Terra", "codex-cli-chatgpt-subscription",
)
IDENTITY_PATTERN = re.compile(r"(?i)(?:^|[^a-z0-9])F[1-8][- _]?t[1-5](?:$|[^a-z0-9])")
FAULT_ID_PATTERN = re.compile(r"(?i)(?<![a-z0-9])F[1-8](?![a-z0-9])")


def encoded_variants(value: str) -> set[str]:
    raw = value.encode("utf-8")
    return {
        value, value.casefold(), unicodedata.normalize("NFKC", value),
        json.dumps(value, ensure_ascii=True)[1:-1], urllib.parse.quote(value, safe=""),
        base64.b64encode(raw).decode("ascii"), binascii.hexlify(raw).decode("ascii"),
    }


def _normalized(value: str) -> str:
    return unicodedata.normalize("NFKC", value).casefold()


def _contains_variant(text: str, marker: str) -> bool:
    haystacks = {_normalized(text), text.casefold()}
    return any(
        variant and any(_normalized(variant) in haystack for haystack in haystacks)
        for variant in encoded_variants(marker)
    )


@lru_cache(maxsize=16)
def _known_pattern(known: tuple[str, ...]) -> re.Pattern[str] | None:
    normalized_variants = {
        _normalized(variant)
        for identifier in known
        for variant in encoded_variants(identifier)
        if variant
    }
    return re.compile(
        "|".join(re.escape(value) for value in sorted(normalized_variants, key=len, reverse=True))
    ) if normalized_variants else None


def scan_records(
    phase: str,
    records: list[dict[str, str]],
    known_identifiers: Iterable[str] = (),
) -> dict[str, object]:
    expected = CORRECTNESS_FIELDS if phase == "correctness" else SEMANTIC_FIELDS
    if phase not in {"correctness", "semantic"}:
        raise AuditError("unknown scanner phase")
    known = tuple(sorted({item for item in known_identifiers if item}))
    known_pattern = _known_pattern(known)
    violations = []
    for index, record in enumerate(records):
        if tuple(record) != expected:
            violations.append(f"row {index}: schema mismatch")
            continue
        serialized = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        if IDENTITY_PATTERN.search(serialized):
            violations.append(f"row {index}: raw incident identity")
        if FAULT_ID_PATTERN.search(serialized):
            violations.append(f"row {index}: raw fault identifier")
        for key in COMMON_FORBIDDEN_KEYS:
            if key in record:
                violations.append(f"row {index}: forbidden key {key}")
        for marker in FORBIDDEN_MARKERS:
            if _contains_variant(serialized, marker):
                violations.append(f"row {index}: forbidden marker {marker}")
        id_field = "case_id" if phase == "correctness" else "context_id"
        for field, value in record.items():
            if field == id_field and value in known:
                continue
            if known_pattern is not None and known_pattern.search(_normalized(value)):
                violations.append(f"row {index}: sealed identifier in {field}")
    if violations:
        raise AuditError("package scanner failed: " + "; ".join(violations[:8]))
    policy = {
        "phase": phase, "schema": list(expected),
        "forbidden_keys": sorted(COMMON_FORBIDDEN_KEYS),
        "forbidden_markers": list(FORBIDDEN_MARKERS),
        "encoding_checks": ["exact", "casefold", "NFKC", "JSON", "URL", "base64", "hex"],
    }
    return {
        "status": "PASS", "record_count": len(records),
        "policy_sha256": sha256_bytes(json.dumps(policy, sort_keys=True).encode()),
        "claim": "forbidden structured fields/markers not detected",
    }


def assert_safe_archive_members(paths: Iterable[str]) -> None:
    seen = set()
    for value in paths:
        path = Path(value)
        if (
            value in seen or path.is_absolute() or ".." in path.parts
            or any(part.startswith(".") for part in path.parts)
            or path.suffix not in {".csv", ".md", ".json"}
        ):
            raise AuditError(f"unsafe archive member: {value}")
        seen.add(value)


def scan_archive(
    phase: str, archive_bytes: bytes, known_identifiers: Iterable[str] = (),
) -> dict[str, object]:
    expected_csv = "correctness.csv" if phase == "correctness" else "semantic.csv"
    expected_members = {expected_csv, "instructions.md"}
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        names = archive.namelist()
        assert_safe_archive_members(names)
        if set(names) != expected_members or len(names) != 2:
            raise AuditError("archive member allowlist mismatch")
        if archive.comment:
            raise AuditError("archive comment forbidden")
        for info in archive.infolist():
            if (
                info.extra or info.comment or info.date_time != (1980, 1, 1, 0, 0, 0)
                or info.create_system != 3 or info.compress_type != zipfile.ZIP_DEFLATED
            ):
                raise AuditError("archive metadata mismatch")
            if (info.external_attr >> 16) & 0o777 != 0o400:
                raise AuditError("archive member mode mismatch")
        csv_text = archive.read(expected_csv).decode("utf-8", "strict")
        reader = csv.DictReader(io.StringIO(csv_text))
        records = list(reader)
        report = scan_records(phase, records, known_identifiers)
        markdown = archive.read("instructions.md").decode("utf-8", "strict")
        combined_metadata = "\n".join(names) + "\n" + markdown
        for marker in (*FORBIDDEN_MARKERS, *tuple(set(known_identifiers))):
            if marker and _contains_variant(combined_metadata, marker):
                raise AuditError(f"archive metadata/Markdown leak: {marker}")
        return {**report, "archive_member_count": len(names)}

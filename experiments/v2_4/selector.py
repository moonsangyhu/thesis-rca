"""Primary03-only parsing and preregistered outcome-blind selection."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import (
    CONDITIONS, EXPECTED_CAMPAIGN_ID, EXPECTED_SEED_HASH, SELECTED_INCIDENTS,
)
from .io import AuditError


@dataclass(frozen=True)
class CampaignData:
    campaign_id: str
    manifest: dict[str, Any]
    rows: dict[tuple[str, int, str], dict[str, str]]
    raw: dict[tuple[str, int, str], dict[str, Any]]


def _seed(manifest: dict[str, Any], raw: dict[tuple[str, int, str], dict[str, Any]]) -> str:
    schedule_hashes = {item.get("schedule_hash") for item in raw.values()}
    if len(schedule_hashes) != 1 or None in schedule_hashes:
        raise AuditError("schedule_hash is not unique")
    material = "|".join((
        "v2.4-measurement-audit-v1", manifest["campaign_id"],
        next(iter(schedule_hashes)), manifest["corpus_version"],
    ))
    digest = hashlib.sha256(material.encode()).hexdigest()
    if digest != EXPECTED_SEED_HASH:
        raise AuditError(f"preregistered seed mismatch: {digest}")
    # The published value is a commitment to the seed material.  Sampling
    # hashes the material itself, exactly as preregistered (not its hex digest).
    return material


def _select(seed: str, incidents: set[tuple[str, int]]) -> tuple[tuple[str, int], ...]:
    by_fault: dict[str, list[int]] = {}
    for fault, trial in incidents:
        by_fault.setdefault(fault, []).append(trial)
    if set(by_fault) != {f"F{i}" for i in range(1, 9)}:
        raise AuditError("Primary03 incident boundary must be F1-F8")
    primary = {}
    for fault, trials in by_fault.items():
        primary[fault] = min(
            trials, key=lambda trial: hashlib.sha256(
                f"{seed}|primary|{fault}|{trial}".encode()
            ).digest()
        )
    secondary_faults = sorted(
        by_fault,
        key=lambda fault: hashlib.sha256(
            f"{seed}|secondary-fault|{fault}".encode()
        ).digest(),
    )[:4]
    selected = {(fault, trial) for fault, trial in primary.items()}
    for fault in secondary_faults:
        remaining = [trial for trial in by_fault[fault] if trial != primary[fault]]
        trial = min(
            remaining, key=lambda value: hashlib.sha256(
                f"{seed}|secondary-incident|{fault}|{value}".encode()
            ).digest()
        )
        selected.add((fault, trial))
    return tuple(sorted(selected, key=lambda x: (int(x[0][1:]), x[1])))


def load_primary03(campaign_dir: Path) -> CampaignData:
    if campaign_dir.name != EXPECTED_CAMPAIGN_ID:
        raise AuditError("test_primary03_only: exact campaign directory required")
    manifest = json.loads((campaign_dir / "campaign_manifest.json").read_text("utf-8"))
    if manifest.get("campaign_id") != EXPECTED_CAMPAIGN_ID:
        raise AuditError("campaign manifest identity mismatch")
    csv_path = campaign_dir / "experiment_results_v2_3.csv"
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        records = list(csv.DictReader(handle))
    if len(records) != 117:
        raise AuditError(f"expected 117 CSV rows, got {len(records)}")
    rows: dict[tuple[str, int, str], dict[str, str]] = {}
    for row in records:
        if row["campaign_id"] != EXPECTED_CAMPAIGN_ID:
            raise AuditError("foreign campaign row")
        key = (row["fault_id"], int(row["trial"]), row["context_condition"])
        if key in rows or key[2] not in CONDITIONS:
            raise AuditError(f"invalid/duplicate CSV identity: {key}")
        rows[key] = row
    raw_files = sorted((campaign_dir / "raw_v2_3").glob("*.json"))
    if len(raw_files) != 117:
        raise AuditError(f"expected 117 raw JSON files, got {len(raw_files)}")
    raw = {}
    for path in raw_files:
        item = json.loads(path.read_text("utf-8"))
        key = (item["fault_id"], int(item["trial"]), item["context_condition"])
        if item.get("campaign_id") != EXPECTED_CAMPAIGN_ID or key in raw:
            raise AuditError(f"invalid/duplicate raw identity: {path.name}")
        raw[key] = item
    if set(rows) != set(raw):
        raise AuditError("row/raw identity mismatch")
    incidents = {(fault, trial) for fault, trial, _ in rows}
    if len(incidents) != 39 or any(
        sum((fault, trial, c) in rows for c in CONDITIONS) != 3
        for fault, trial in incidents
    ):
        raise AuditError("expected 39 complete incidents")
    seed = _seed(manifest, raw)
    selected = _select(seed, incidents)
    if selected != SELECTED_INCIDENTS:
        raise AuditError(f"preregistered incident mismatch: {selected}")
    return CampaignData(EXPECTED_CAMPAIGN_ID, manifest, rows, raw)


def selected_rows(data: CampaignData) -> list[tuple[dict[str, str], dict[str, Any]]]:
    result = []
    for fault, trial in SELECTED_INCIDENTS:
        for condition in CONDITIONS:
            key = (fault, trial, condition)
            row, raw = data.rows[key], data.raw[key]
            identity_fields = ("campaign_id", "fault_id", "trial", "context_condition")
            if any(str(row[k]) != str(raw[k]) for k in identity_fields):
                raise AuditError(f"row/raw key mismatch: {key}")
            if row["representative_output"] != json.dumps(
                raw["representative_output"], ensure_ascii=False, separators=(",", ":")
            ):
                # CSV writer may use default spaces; compare parsed object instead.
                if json.loads(row["representative_output"]) != raw["representative_output"]:
                    raise AuditError(f"representative output mismatch: {key}")
            result.append((row, raw))
    if len(result) != 36:
        raise AuditError("selected row count is not 36")
    return result


def validate_selector_schema(fields: set[str]) -> None:
    forbidden = {"score", "output", "condition", "correct", "judge", "label"}
    if any(any(token in field.lower() for token in forbidden) for field in fields):
        raise AuditError("outcome-blind selector received forbidden field")
    if fields != {"campaign_id", "fault_id", "trial", "schedule_hash", "corpus_version"}:
        raise AuditError("outcome-blind selector schema mismatch")


def validate_fault_id(value: str) -> None:
    if re.fullmatch(r"F(?:[1-8])", value) is None:
        raise AuditError(f"fault outside Primary03 boundary: {value}")

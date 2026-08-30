"""Append-only human-sheet locking, phase gates, and post-close analysis."""

from __future__ import annotations

import csv
import json
import os
import io
import shutil
import tempfile
import zipfile
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .constants import CORRECTNESS_FIELDS, REASON_CODES, SEMANTIC_FIELDS
from .io import AuditError, canonical_json_bytes, sha256_bytes, write_new
from .metrics import (
    cohen_kappa, confusion, count_boundaries, directional_alert,
    incident_cluster_kappa_bootstrap, weighted_kappa,
)


_TIMESTAMP_PATTERN = re.compile(
    r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})"
)


def _strict_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or _TIMESTAMP_PATTERN.fullmatch(value) is None:
        raise AuditError(f"{label} timestamp invalid")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AuditError(f"{label} timestamp invalid") from exc
    if result.tzinfo is None:
        raise AuditError(f"{label} timestamp must include timezone")
    return result


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]], bytes]:
    raw = path.read_bytes()
    text = raw.decode("utf-8", "strict")
    reader = csv.DictReader(io.StringIO(text, newline=""))
    return list(reader.fieldnames or []), list(reader), raw


def _answer(audit_root: Path) -> dict[str, Any]:
    return json.loads((audit_root / "sealed" / "answer_key.json").read_text("utf-8"))


def _status(audit_root: Path) -> dict[str, Any]:
    status = json.loads((audit_root / "manifests" / "status.json").read_text("utf-8"))
    if (audit_root / "manifests" / "phase_correctness_closed.json").is_file():
        status["correctness_phase"] = "CLOSED"
    if (audit_root / "manifests" / "phase_semantic_closed.json").is_file():
        status["semantic_phase"] = "CLOSED"
    return status


def _append_event(audit_root: Path, event: dict[str, Any]) -> None:
    path = audit_root / "ratings" / "lock_events.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("ab") as handle:
        handle.write(canonical_json_bytes(event) + b"\n")


def lock_reviewer_profile(audit_root: Path, reviewer: str, phase: str, source: Path) -> Path:
    if reviewer not in {"R1", "R2"} or phase not in {"correctness", "semantic"}:
        raise AuditError("invalid reviewer/phase")
    status = _status(audit_root)
    if phase == "semantic" and status.get("correctness_phase") != "CLOSED":
        raise AuditError("semantic qualification requires correctness CLOSED")
    profile = json.loads(source.read_text("utf-8"))
    required = {
        "reviewer", "phase", "qualified_at", "years_kubernetes_sre",
        "certification", "certification_verified",
        "conflict_disclosure", "conflict_status", "eligibility_approved_by",
        "training_correct", "training_total", "attestation",
    }
    if set(profile) != required or profile["reviewer"] != reviewer or profile["phase"] != phase:
        raise AuditError("reviewer profile schema/identity mismatch")
    qualified_at = _strict_timestamp(profile.get("qualified_at"), "reviewer qualification")
    if phase == "semantic":
        closed = json.loads(
            (audit_root / "manifests" / "phase_correctness_closed.json").read_text("utf-8")
        )
        closed_at = datetime.fromisoformat(closed["closed_at"].replace("Z", "+00:00"))
        if qualified_at < closed_at:
            raise AuditError("semantic qualification timestamp precedes correctness CLOSED")
    required_total, required_correct = (8, 7) if phase == "correctness" else (6, 5)
    experience = profile["years_kubernetes_sre"]
    certification_ok = (
        profile["certification"] in {"CKA", "CKAD"}
        and profile["certification_verified"] is True
    )
    experience_ok = (
        type(experience) in {int, float}
        and (experience >= 2 or (experience >= 1 and certification_ok))
    )
    if (
        profile["attestation"] != "SIGNED_TRUE"
        or not isinstance(profile["conflict_disclosure"], str)
        or not profile["conflict_disclosure"].strip()
        or profile["conflict_status"] not in {"NONE", "DISCLOSED_APPROVED"}
        or not isinstance(profile["eligibility_approved_by"], str)
        or not profile["eligibility_approved_by"].strip()
        or not experience_ok
        or profile["certification"] not in {"NONE", "CKA", "CKAD"}
        or type(profile["certification_verified"]) is not bool
        or type(profile["training_correct"]) is not int
        or type(profile["training_total"]) is not int
        or profile["training_total"] != required_total
        or profile["training_correct"] < required_correct
        or profile["training_correct"] > profile["training_total"]
    ):
        raise AuditError("reviewer qualification/training/conflict gate failed")
    raw = canonical_json_bytes(profile)
    destination = audit_root / "ratings" / "reviewer_profiles" / f"{reviewer}_{phase}.json"
    write_new(destination, raw, 0o400)
    return destination


def _validate_session_metadata(path: Path, phase: str, expected_ids: list[str]) -> bytes:
    document = json.loads(path.read_text("utf-8"))
    if set(document) != {"phase", "sessions", "items", "attestation"} or document["phase"] != phase:
        raise AuditError("session metadata schema/phase mismatch")
    if document["attestation"] != "SIGNED_TRUE" or not isinstance(document["sessions"], list):
        raise AuditError("session metadata attestation missing")
    maximum = 18 if phase == "correctness" else 6
    total = 0
    for index, session in enumerate(document["sessions"]):
        if set(session) != {
            "session_id", "item_count", "started_at", "ended_at",
            "break_minutes_before", "fatigue_1_5",
        }:
            raise AuditError("session metadata row schema mismatch")
        if (
            type(session["item_count"]) is not int
            or type(session["fatigue_1_5"]) is not int
            or type(session["break_minutes_before"]) not in {int, float}
            or
            not 1 <= session["item_count"] <= maximum
            or not 1 <= session["fatigue_1_5"] <= 5
            or (index and session["break_minutes_before"] < 15)
            or (not index and session["break_minutes_before"] != 0)
            or not session["started_at"] or not session["ended_at"]
        ):
            raise AuditError("fatigue/session/break gate failed")
        started = _strict_timestamp(session["started_at"], "session start")
        ended = _strict_timestamp(session["ended_at"], "session end")
        if ended < started:
            raise AuditError("session timestamp interval invalid")
        total += session["item_count"]
    if total != len(expected_ids):
        raise AuditError("session item total mismatch")
    if not isinstance(document["items"], list) or len(document["items"]) != len(expected_ids):
        raise AuditError("item timestamp count mismatch")
    for expected_id, item in zip(expected_ids, document["items"]):
        if set(item) != {"item_id", "started_at", "ended_at"} or item["item_id"] != expected_id:
            raise AuditError("item timestamp identity/order mismatch")
        started = _strict_timestamp(item["started_at"], "item start")
        ended = _strict_timestamp(item["ended_at"], "item end")
        if ended < started:
            raise AuditError("item timestamp interval invalid")
    return canonical_json_bytes(document)


def _package_archive(audit_root: Path, reviewer: str, phase: str) -> Path:
    if phase == "correctness":
        return audit_root / "distribution" / "correctness" / reviewer.lower() / f"{reviewer}_correctness.zip"
    released = audit_root / "distribution" / "semantic" / reviewer.lower() / f"{reviewer}_semantic.zip"
    return released


def _committed_sheet(audit_root: Path, reviewer: str, phase: str) -> tuple[list[dict[str, str]], str]:
    archive_path = _package_archive(audit_root, reviewer, phase)
    raw_archive = archive_path.read_bytes()
    commitment = json.loads((audit_root / "manifests" / "package_commitment.json").read_text("utf-8"))
    key = f"{reviewer}_{phase}"
    if sha256_bytes(raw_archive) != commitment["archives"][key]:
        raise AuditError("distribution archive commitment mismatch")
    csv_name = "correctness.csv" if phase == "correctness" else "semantic.csv"
    with zipfile.ZipFile(io.BytesIO(raw_archive)) as archive:
        text = archive.read(csv_name).decode("utf-8", "strict")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader), commitment["archives"][key]


def lock_submission(
    audit_root: Path, reviewer: str, phase: str, source: Path, session_metadata: Path,
) -> Path:
    if reviewer not in {"R1", "R2"} or phase not in {"correctness", "semantic"}:
        raise AuditError("invalid reviewer/phase")
    status = _status(audit_root)
    if phase == "semantic" and status.get("correctness_phase") != "CLOSED":
        raise AuditError("semantic phase cannot start before correctness closes")
    if phase == "semantic" and not (
        audit_root / "manifests" / "phase_semantic_released.json"
    ).is_file():
        raise AuditError("semantic distribution must be released before submission")
    profile_path = audit_root / "ratings" / "reviewer_profiles" / f"{reviewer}_{phase}.json"
    if not profile_path.is_file():
        raise AuditError("locked reviewer qualification profile required")
    if phase == "semantic":
        release = json.loads(
            (audit_root / "manifests" / "phase_semantic_released.json").read_text("utf-8")
        )
        if sha256_bytes(profile_path.read_bytes()) != release["reviewer_profile_sha256"][reviewer]:
            raise AuditError("semantic reviewer profile changed after distribution release")
    fields, rows, raw = _read_csv(source)
    expected_fields = list(CORRECTNESS_FIELDS if phase == "correctness" else SEMANTIC_FIELDS)
    if fields != expected_fields:
        raise AuditError("rating sheet schema mismatch")
    answer = _answer(audit_root)
    id_field = "case_id" if phase == "correctness" else "context_id"
    committed, package_hash = _committed_sheet(audit_root, reviewer, phase)
    expected_ids = [item[id_field] for item in committed]
    ids = [row[id_field] for row in rows]
    if ids != expected_ids or len(ids) != len(set(ids)):
        raise AuditError("rating sheet reviewer order/identity mismatch")
    mutable = (
        {"correctness_0_1_2_A", "reason_codes", "rationale"}
        if phase == "correctness" else
        {"severity_L0_L1_L2_L3", "label_exposed", "entity_exposed", "injection_specific", "generic_procedure", "rationale"}
    )
    for submitted, frozen in zip(rows, committed):
        for field in expected_fields:
            if field not in mutable and submitted[field] != frozen[field]:
                raise AuditError(f"frozen distribution field changed: {field}")
    if phase == "correctness":
        for row in rows:
            if row["correctness_0_1_2_A"] not in {"0", "1", "2", "A"}:
                raise AuditError("invalid correctness score")
            reasons = {item for item in row["reason_codes"].split(";") if item}
            if not reasons <= REASON_CODES:
                raise AuditError("invalid correctness reason code")
    else:
        for row in rows:
            if row["severity_L0_L1_L2_L3"] not in {"L0", "L1", "L2", "L3"}:
                raise AuditError("invalid semantic severity")
            if any(row[field] not in {"true", "false"} for field in (
                "label_exposed", "entity_exposed", "injection_specific", "generic_procedure"
            )):
                raise AuditError("invalid semantic boolean")
    destination = audit_root / "ratings" / "original_locked" / f"{reviewer}_{phase}.csv"
    metadata_raw = _validate_session_metadata(session_metadata, phase, ids)
    metadata_destination = audit_root / "ratings" / "session_metadata" / f"{reviewer}_{phase}.json"
    lock_manifest = audit_root / "ratings" / "lock_manifests" / f"{reviewer}_{phase}.json"
    event = {
        "event": "ORIGINAL_LOCKED", "reviewer": reviewer, "phase": phase,
        "timestamp": datetime.now(timezone.utc).isoformat(), "sha256": sha256_bytes(raw),
        "package_sha256": package_hash, "session_metadata_sha256": sha256_bytes(metadata_raw),
        "reviewer_profile_sha256": sha256_bytes(profile_path.read_bytes()),
    }
    created = []
    try:
        write_new(destination, raw, 0o400); created.append(destination)
        write_new(metadata_destination, metadata_raw, 0o400); created.append(metadata_destination)
        write_new(lock_manifest, canonical_json_bytes(event), 0o400); created.append(lock_manifest)
        _append_event(audit_root, event)
    except BaseException:
        for path in reversed(created):
            if path.exists(): path.unlink()
        raise
    return destination


def append_correction(audit_root: Path, reviewer: str, phase: str, source: Path) -> Path:
    sequence = len(list((audit_root / "ratings" / "corrections").glob("*.csv"))) + 1
    destination = audit_root / "ratings" / "corrections" / f"{sequence:04d}_{reviewer}_{phase}.csv"
    write_new(destination, source.read_bytes(), 0o400)
    return destination


def _verify_one_lock(audit_root: Path, reviewer: str, phase: str) -> dict[str, Any]:
    manifest_path = audit_root / "ratings" / "lock_manifests" / f"{reviewer}_{phase}.json"
    event = json.loads(manifest_path.read_text("utf-8"))
    locked = audit_root / "ratings" / "original_locked" / f"{reviewer}_{phase}.csv"
    metadata = audit_root / "ratings" / "session_metadata" / f"{reviewer}_{phase}.json"
    profile = audit_root / "ratings" / "reviewer_profiles" / f"{reviewer}_{phase}.json"
    if sha256_bytes(locked.read_bytes()) != event["sha256"]:
        raise AuditError("locked original hash mismatch")
    if sha256_bytes(metadata.read_bytes()) != event["session_metadata_sha256"]:
        raise AuditError("locked session metadata hash mismatch")
    if sha256_bytes(profile.read_bytes()) != event["reviewer_profile_sha256"]:
        raise AuditError("locked reviewer profile hash mismatch")
    _, package_hash = _committed_sheet(audit_root, reviewer, phase)
    if package_hash != event["package_sha256"]:
        raise AuditError("locked package commitment mismatch")
    return {"lock_manifest_sha256": sha256_bytes(manifest_path.read_bytes()), **event}


def close_correctness(audit_root: Path, adjudication: Path) -> None:
    locked = audit_root / "ratings" / "original_locked"
    if not all((locked / f"{reviewer}_correctness.csv").is_file() for reviewer in ("R1", "R2")):
        raise AuditError("both correctness originals must be locked")
    lock_evidence = {
        reviewer: _verify_one_lock(audit_root, reviewer, "correctness")
        for reviewer in ("R1", "R2")
    }
    fields, rows, raw = _read_csv(adjudication)
    if fields != ["case_id", "adjudicated_correctness", "rationale"]:
        raise AuditError("correctness adjudication schema mismatch")
    originals = []
    for reviewer in ("R1", "R2"):
        _, original_rows, _ = _read_csv(locked / f"{reviewer}_correctness.csv")
        originals.append({row["case_id"]: row for row in original_rows})
    expected_all = {item["case_id"] for item in _answer(audit_root)["mapping"]}
    if set(originals[0]) != expected_all or set(originals[1]) != expected_all:
        raise AuditError("locked correctness identity mismatch")
    disagreements = {
        key for key in expected_all
        if originals[0][key]["correctness_0_1_2_A"] != originals[1][key]["correctness_0_1_2_A"]
    }
    if {row["case_id"] for row in rows} != disagreements or len(rows) != len(disagreements):
        raise AuditError("adjudication must contain disagreement IDs only")
    if any(row["adjudicated_correctness"] not in {"0", "1", "2", "A"} for row in rows):
        raise AuditError("invalid adjudicated correctness")
    adjudicated = {row["case_id"]: row for row in rows}
    resolved_rows = []
    for key in sorted(expected_all):
        if key in disagreements:
            score = adjudicated[key]["adjudicated_correctness"]
            rationale = adjudicated[key]["rationale"]
            resolution = "ADJUDICATED_DISAGREEMENT"
        else:
            score = originals[0][key]["correctness_0_1_2_A"]
            rationale = ""
            resolution = "AUTO_CARRIED_UNANIMOUS"
        resolved_rows.append({
            "case_id": key, "adjudicated_correctness": score,
            "rationale": rationale, "resolution_source": resolution,
        })
    resolved_fields = ["case_id", "adjudicated_correctness", "rationale", "resolution_source"]
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=resolved_fields, lineterminator="\n")
    writer.writeheader(); writer.writerows(resolved_rows)
    resolved_raw = stream.getvalue().encode("utf-8")
    close_document = {
        "phase": "correctness", "status": "CLOSED",
        "disagreement_count": len(disagreements),
        "adjudication_sha256": sha256_bytes(raw),
        "resolved_sha256": sha256_bytes(resolved_raw),
        "original_lock_evidence": lock_evidence,
        "closed_at": datetime.now(timezone.utc).isoformat(),
    }
    parent = audit_root / "ratings" / "adjudication"
    parent.mkdir(parents=True, exist_ok=True)
    final_phase = parent / "correctness_closed"
    phase_path = audit_root / "manifests" / "phase_correctness_closed.json"
    if final_phase.exists() or phase_path.exists():
        raise AuditError("correctness close output already exists")
    stage = Path(tempfile.mkdtemp(prefix=".correctness-close-staging-", dir=parent))
    published = False
    try:
        write_new(stage / "correctness_disagreements.csv", raw, 0o400)
        write_new(stage / "correctness_resolved.csv", resolved_raw, 0o400)
        write_new(stage / "close_manifest.json", canonical_json_bytes(close_document), 0o400)
        os.rename(stage, final_phase); published = True
        # CLOSED is the last visible lifecycle write.
        write_new(phase_path, canonical_json_bytes(close_document), 0o400)
    except BaseException:
        if stage.exists(): shutil.rmtree(stage)
        if published and final_phase.exists(): shutil.rmtree(final_phase)
        if phase_path.exists(): phase_path.unlink()
        raise


def release_semantic(audit_root: Path) -> None:
    """Atomically publish both semantic archives after both reviewers qualify."""
    if _status(audit_root).get("correctness_phase") != "CLOSED":
        raise AuditError("correctness phase must close before semantic release")
    final_semantic = audit_root / "distribution" / "semantic"
    sentinel = audit_root / "manifests" / "phase_semantic_released.json"
    if final_semantic.exists() or sentinel.exists():
        raise AuditError("semantic distribution already released")
    profiles: dict[str, str] = {}
    closed_at = _strict_timestamp(
        json.loads((audit_root / "manifests" / "phase_correctness_closed.json").read_text("utf-8"))["closed_at"],
        "correctness close",
    )
    profile_fields = {
        "reviewer", "phase", "qualified_at", "years_kubernetes_sre",
        "certification", "certification_verified", "conflict_disclosure",
        "conflict_status", "eligibility_approved_by", "training_correct",
        "training_total", "attestation",
    }
    for reviewer in ("R1", "R2"):
        profile_path = audit_root / "ratings" / "reviewer_profiles" / f"{reviewer}_semantic.json"
        if not profile_path.is_file():
            raise AuditError("both locked semantic reviewer profiles are required")
        profile_raw = profile_path.read_bytes()
        profile = json.loads(profile_raw.decode("utf-8", "strict"))
        experience = profile.get("years_kubernetes_sre")
        certification_ok = (
            profile.get("certification") in {"CKA", "CKAD"}
            and profile.get("certification_verified") is True
        )
        if (
            set(profile) != profile_fields
            or profile.get("reviewer") != reviewer
            or profile.get("phase") != "semantic"
            or _strict_timestamp(profile.get("qualified_at"), "semantic qualification") < closed_at
            or type(experience) not in {int, float}
            or not (experience >= 2 or (experience >= 1 and certification_ok))
            or profile.get("certification") not in {"NONE", "CKA", "CKAD"}
            or type(profile.get("certification_verified")) is not bool
            or profile.get("training_total") != 6
            or type(profile.get("training_correct")) is not int
            or not 5 <= profile["training_correct"] <= 6
            or profile.get("attestation") != "SIGNED_TRUE"
            or profile.get("conflict_status") not in {"NONE", "DISCLOSED_APPROVED"}
            or not isinstance(profile.get("conflict_disclosure"), str)
            or not profile["conflict_disclosure"].strip()
            or not isinstance(profile.get("eligibility_approved_by"), str)
            or not profile["eligibility_approved_by"].strip()
        ):
            raise AuditError("locked semantic reviewer profile validation failed")
        profiles[reviewer] = sha256_bytes(profile_raw)
    commitment = json.loads((audit_root / "manifests" / "package_commitment.json").read_text("utf-8"))
    archive_hashes: dict[str, str] = {}
    pending_bytes: dict[str, bytes] = {}
    for reviewer in ("R1", "R2"):
        pending = audit_root / "sealed" / "pending_semantic" / f"{reviewer}_semantic.zip"
        raw_archive = pending.read_bytes()
        digest = sha256_bytes(raw_archive)
        if digest != commitment["archives"][f"{reviewer}_semantic"]:
            raise AuditError("pending semantic archive commitment mismatch")
        pending_bytes[reviewer] = raw_archive
        archive_hashes[reviewer] = digest
    parent = audit_root / "distribution"
    stage = Path(tempfile.mkdtemp(prefix=".semantic-release-staging-", dir=parent))
    published = False
    release_document = {
        "phase": "semantic", "status": "RELEASED",
        "reviewer_profile_sha256": profiles,
        "archive_sha256": archive_hashes,
        "released_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        for reviewer, raw_archive in pending_bytes.items():
            destination = stage / reviewer.lower() / f"{reviewer}_semantic.zip"
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw_archive); os.chmod(destination, 0o400)
        os.rename(stage, final_semantic); published = True
        # The release sentinel is deliberately the last visible lifecycle write.
        write_new(sentinel, canonical_json_bytes(release_document), 0o400)
    except BaseException:
        if stage.exists(): shutil.rmtree(stage)
        if published and final_semantic.exists(): shutil.rmtree(final_semantic)
        if sentinel.exists(): sentinel.unlink()
        raise


def close_semantic(audit_root: Path, adjudication: Path) -> None:
    status = _status(audit_root)
    if status.get("correctness_phase") != "CLOSED":
        raise AuditError("correctness phase must close first")
    locked = audit_root / "ratings" / "original_locked"
    if not all((locked / f"{reviewer}_semantic.csv").is_file() for reviewer in ("R1", "R2")):
        raise AuditError("both semantic originals must be locked")
    lock_evidence = {
        reviewer: _verify_one_lock(audit_root, reviewer, "semantic")
        for reviewer in ("R1", "R2")
    }
    fields, rows, raw = _read_csv(adjudication)
    expected_fields = [
        "context_id", "adjudicated_severity", "label_exposed", "entity_exposed",
        "injection_specific", "generic_procedure", "rationale",
    ]
    if fields != expected_fields:
        raise AuditError("semantic adjudication schema mismatch")
    expected_all = {
        item["context_id"] for item in _answer(audit_root)["mapping"]
        if item["condition"] == "blind_procedural_rag"
    }
    originals = []
    comparison_fields = (
        "severity_L0_L1_L2_L3", "label_exposed", "entity_exposed",
        "injection_specific", "generic_procedure",
    )
    for reviewer in ("R1", "R2"):
        _, original_rows, _ = _read_csv(locked / f"{reviewer}_semantic.csv")
        originals.append({row["context_id"]: row for row in original_rows})
    disagreements = {
        key for key in expected_all
        if any(originals[0][key][field] != originals[1][key][field] for field in comparison_fields)
    }
    if {row["context_id"] for row in rows} != disagreements or len(rows) != len(disagreements):
        raise AuditError("semantic adjudication must contain disagreement IDs only")
    if any(row["adjudicated_severity"] not in {"L0", "L1", "L2", "L3", "UNRESOLVED"} for row in rows):
        raise AuditError("invalid adjudicated semantic severity")
    if any(
        row[field] not in {"true", "false", "UNRESOLVED"}
        for row in rows
        for field in ("label_exposed", "entity_exposed", "injection_specific", "generic_procedure")
    ):
        raise AuditError("invalid adjudicated semantic boolean")
    adjudicated = {row["context_id"]: row for row in rows}
    resolved = []
    for key in sorted(expected_all):
        if key in disagreements:
            source = adjudicated[key]
            resolved.append({**source, "resolution_source": "ADJUDICATED_DISAGREEMENT"})
        else:
            source = originals[0][key]
            resolved.append({
                "context_id": key,
                "adjudicated_severity": source["severity_L0_L1_L2_L3"],
                **{field: source[field] for field in comparison_fields[1:]},
                "rationale": "", "resolution_source": "AUTO_CARRIED_UNANIMOUS",
            })
    resolved_fields = [*expected_fields, "resolution_source"]
    stream = io.StringIO(newline=""); writer = csv.DictWriter(stream, fieldnames=resolved_fields, lineterminator="\n")
    writer.writeheader(); writer.writerows(resolved); resolved_raw = stream.getvalue().encode()
    close_document = {
        "phase": "semantic", "status": "CLOSED",
        "adjudication_sha256": sha256_bytes(raw), "resolved_sha256": sha256_bytes(resolved_raw),
        "original_lock_evidence": lock_evidence,
        "closed_at": datetime.now(timezone.utc).isoformat(),
    }
    parent = audit_root / "ratings" / "adjudication"
    parent.mkdir(parents=True, exist_ok=True)
    final_phase = parent / "semantic_closed"
    sentinel = audit_root / "manifests" / "phase_semantic_closed.json"
    if final_phase.exists() or sentinel.exists():
        raise AuditError("semantic close output already exists")
    stage = Path(tempfile.mkdtemp(prefix=".semantic-close-staging-", dir=parent))
    published = False
    try:
        write_new(stage / "semantic_disagreements.csv", raw, 0o400)
        write_new(stage / "semantic_resolved.csv", resolved_raw, 0o400)
        write_new(stage / "close_manifest.json", canonical_json_bytes(close_document), 0o400)
        os.rename(stage, final_phase); published = True
        # CLOSED is the last visible lifecycle write.
        write_new(sentinel, canonical_json_bytes(close_document), 0o400)
    except BaseException:
        if stage.exists(): shutil.rmtree(stage)
        if published and final_phase.exists(): shutil.rmtree(final_phase)
        if sentinel.exists(): sentinel.unlink()
        raise


def _reverify_locked_hashes(audit_root: Path) -> None:
    expected = {(reviewer, phase) for reviewer in ("R1", "R2") for phase in ("correctness", "semantic")}
    found = set()
    for reviewer, phase in sorted(expected):
        event = _verify_one_lock(audit_root, reviewer, phase)
        key = (event["reviewer"], event["phase"]); found.add(key)
    if found != expected:
        raise AuditError("incomplete locked sheet hash evidence")
    for phase in ("correctness", "semantic"):
        manifest = json.loads(
            (audit_root / "manifests" / f"phase_{phase}_closed.json").read_text("utf-8")
        )
        phase_root = audit_root / "ratings" / "adjudication" / f"{phase}_closed"
        if phase == "semantic":
            disagreement = phase_root / "semantic_disagreements.csv"
            resolved = phase_root / "semantic_resolved.csv"
            if canonical_json_bytes(manifest) != (phase_root / "close_manifest.json").read_bytes():
                raise AuditError("semantic close manifest/sentinel mismatch")
        else:
            disagreement = phase_root / "correctness_disagreements.csv"
            resolved = phase_root / "correctness_resolved.csv"
            if canonical_json_bytes(manifest) != (phase_root / "close_manifest.json").read_bytes():
                raise AuditError("correctness close manifest/sentinel mismatch")
        if sha256_bytes(disagreement.read_bytes()) != manifest["adjudication_sha256"]:
            raise AuditError(f"locked {phase} adjudication hash mismatch")
        if sha256_bytes(resolved.read_bytes()) != manifest["resolved_sha256"]:
            raise AuditError(f"locked {phase} resolved hash mismatch")
        for reviewer in ("R1", "R2"):
            current = _verify_one_lock(audit_root, reviewer, phase)
            if current["lock_manifest_sha256"] != manifest["original_lock_evidence"][reviewer]["lock_manifest_sha256"]:
                raise AuditError(f"locked {phase} manifest commitment mismatch")


def analyze_closed(audit_root: Path) -> dict[str, Any]:
    """Analyze only real locked sheets after both phase commitments exist."""
    status = _status(audit_root)
    if status.get("correctness_phase") != "CLOSED" or status.get("semantic_phase") != "CLOSED":
        raise AuditError("both review phases must be closed")
    _reverify_locked_hashes(audit_root)
    answer_document = _answer(audit_root)
    answer = {item["case_id"]: item for item in answer_document["mapping"]}
    _, adjudicated, _ = _read_csv(
        audit_root / "ratings" / "adjudication" / "correctness_closed" / "correctness_resolved.csv"
    )
    terra, human = [], []
    for row in adjudicated:
        terra.append(answer[row["case_id"]]["terra_correct_at_0_5"])
        score = row["adjudicated_correctness"]
        human.append("A" if score == "A" else int(score) >= 1 and 1 or 0)
    result: dict[str, Any] = {"primary": confusion(terra, human), "sensitivity_score_2": confusion(
        terra, ["A" if row["adjudicated_correctness"] == "A" else int(row["adjudicated_correctness"] == "2") for row in adjudicated]
    )}
    primary = result["primary"]
    result["threshold_sensitivity"] = {
        str(threshold): {"green_max": count_boundaries(primary["n_non_abstain"], threshold)[0],
                         "red_min": count_boundaries(primary["n_non_abstain"], threshold)[1]}
        for threshold in (.10, .15, .25)
    } if primary["n_non_abstain"] else None
    result["directional_alert"] = directional_alert(
        primary["terra1_human0"], primary["terra0_human1"]
    )
    human_by_case = {
        row["case_id"]: ("A" if row["adjudicated_correctness"] == "A" else int(int(row["adjudicated_correctness"]) >= 1))
        for row in adjudicated
    }
    result["condition_strata_descriptive"] = {}
    for condition in sorted({item["condition"] for item in answer.values()}):
        keys = [key for key, item in answer.items() if item["condition"] == condition]
        result["condition_strata_descriptive"][condition] = confusion(
            [answer[key]["terra_correct_at_0_5"] for key in keys],
            [human_by_case[key] for key in keys],
        )
    reviewer_binary = []
    reviewer_ordinal = []
    correctness_score_distributions = {}
    reason_code_distributions = {}
    originals_by_reviewer = []
    for reviewer in ("R1", "R2"):
        _, rows, _ = _read_csv(audit_root / "ratings" / "original_locked" / f"{reviewer}_correctness.csv")
        originals_by_reviewer.append({row["case_id"]: row for row in rows})
        reviewer_binary.append({
            row["case_id"]: int(row["correctness_0_1_2_A"] in {"1", "2"})
            for row in rows if row["correctness_0_1_2_A"] != "A"
        })
        reviewer_ordinal.append({
            row["case_id"]: int(row["correctness_0_1_2_A"])
            for row in rows if row["correctness_0_1_2_A"] != "A"
        })
        correctness_score_distributions[reviewer] = {
            score: sum(row["correctness_0_1_2_A"] == score for row in rows)
            for score in ("0", "1", "2", "A")
        }
        reason_code_distributions[reviewer] = {
            code: sum(code in {item for item in row["reason_codes"].split(";") if item} for row in rows)
            for code in sorted(REASON_CODES)
        }
    result["correctness_score_distributions"] = correctness_score_distributions
    result["reason_code_distributions"] = reason_code_distributions
    result["original_disagreement_matrix_0_1_2_A"] = {
        f"{left}->{right}": sum(
            originals_by_reviewer[0][key]["correctness_0_1_2_A"] == left
            and originals_by_reviewer[1][key]["correctness_0_1_2_A"] == right
            for key in answer
        )
        for left in ("0", "1", "2", "A") for right in ("0", "1", "2", "A")
    }
    common = sorted(set(reviewer_binary[0]) & set(reviewer_binary[1]))
    result["reviewer_binary_kappa"] = cohen_kappa(
        [reviewer_binary[0][key] for key in common],
        [reviewer_binary[1][key] for key in common],
    )
    raw_agreement = (
        sum(reviewer_binary[0][key] == reviewer_binary[1][key] for key in common) / len(common)
        if common else None
    )
    result["reviewer_binary_raw_agreement"] = raw_agreement
    ordinal_common = sorted(set(reviewer_ordinal[0]) & set(reviewer_ordinal[1]))
    result["reviewer_correctness_weighted_kappa"] = weighted_kappa(
        [reviewer_ordinal[0][key] for key in ordinal_common],
        [reviewer_ordinal[1][key] for key in ordinal_common], maximum=2,
    )
    clusters: dict[str, list[tuple[int, int]]] = {}
    for key in common:
        mapping = answer[key]
        incident = f"{mapping['fault_id']}-t{mapping['trial']}"
        clusters.setdefault(incident, []).append((reviewer_binary[0][key], reviewer_binary[1][key]))
    result["reviewer_binary_kappa_incident_cluster_bootstrap_95"] = (
        incident_cluster_kappa_bootstrap(clusters) if clusters else None
    )
    _, semantic_rows, _ = _read_csv(
        audit_root / "ratings" / "adjudication" / "semantic_closed" / "semantic_resolved.csv"
    )
    severity_counts = {level: 0 for level in ("L0", "L1", "L2", "L3", "UNRESOLVED")}
    for row in semantic_rows:
        severity_counts[row["adjudicated_severity"]] += 1
    semantic_status = (
        "RED" if severity_counts["L3"] else
        "GRAY" if severity_counts["UNRESOLVED"] else "PASS"
    )
    result["semantic"] = {
        "severity_counts": severity_counts,
        "semantic_eligibility_status": semantic_status,
        "label_exposed": sum(row["label_exposed"] == "true" for row in semantic_rows),
        "entity_exposed": sum(row["entity_exposed"] == "true" for row in semantic_rows),
        "injection_specific": sum(row["injection_specific"] == "true" for row in semantic_rows),
    }
    severity_value = {"L0": 0, "L1": 1, "L2": 2, "L3": 3}
    semantic_originals = []
    for reviewer in ("R1", "R2"):
        _, rows, _ = _read_csv(audit_root / "ratings" / "original_locked" / f"{reviewer}_semantic.csv")
        semantic_originals.append({
            row["context_id"]: severity_value[row["severity_L0_L1_L2_L3"]]
            for row in rows if row["severity_L0_L1_L2_L3"] in severity_value
        })
    semantic_common = sorted(set(semantic_originals[0]) & set(semantic_originals[1]))
    result["semantic"]["weighted_kappa_descriptive"] = weighted_kappa(
        [semantic_originals[0][key] for key in semantic_common],
        [semantic_originals[1][key] for key in semantic_common],
    )
    reliability_alert = (
        raw_agreement is None or raw_agreement < .85
        or result["reviewer_binary_kappa"] is None
        or result["reviewer_binary_kappa"] < .70
    )
    primary_status = result["primary"]["primary_status"]
    if semantic_status == "RED" or primary_status == "RED":
        overall = "RED"
    elif semantic_status == "GRAY" or primary_status != "GREEN" or reliability_alert:
        overall = "GRAY"
    else:
        overall = "GREEN"
    result["reviewer_reliability_alert"] = reliability_alert
    non_abstain = primary["n_non_abstain"]
    point = primary["discordant"] / non_abstain if non_abstain else None
    interval = primary["wilson_95"]
    split_discordant = split_n = nonsplit_discordant = nonsplit_n = 0
    for key, human_value in human_by_case.items():
        if human_value == "A":
            continue
        is_discordant = answer[key]["terra_correct_at_0_5"] != human_value
        if answer[key]["generation_split"]:
            split_n += 1; split_discordant += int(is_discordant)
        else:
            nonsplit_n += 1; nonsplit_discordant += int(is_discordant)
    split_rate = split_discordant / split_n if split_n else 0.0
    nonsplit_rate = nonsplit_discordant / nonsplit_n if nonsplit_n else 0.0
    triggers = {
        "primary_at_or_crosses_20pct": bool(
            point is not None and (point >= .20 or (interval and interval[0] <= .20 <= interval[1]))
        ),
        "reviewer_reliability": reliability_alert,
        "condition_direction_reversal": bool(
            any(
                value["terra1_human0"] - value["terra0_human1"] > 0
                for value in result["condition_strata_descriptive"].values()
            ) and any(
                value["terra1_human0"] - value["terra0_human1"] < 0
                for value in result["condition_strata_descriptive"].values()
            )
        ),
        "split_concentration": bool(
            primary["discordant"] and split_discordant >= primary["discordant"] / 2
            or split_rate - nonsplit_rate >= .20
        ),
    }
    result["generation_split_descriptive"] = {
        "split": {"discordant": split_discordant, "n": split_n, "rate": split_rate},
        "non_split": {"discordant": nonsplit_discordant, "n": nonsplit_n, "rate": nonsplit_rate},
    }
    result["escalation_triggers"] = triggers
    result["escalation_candidate"] = any(triggers.values())
    result["overall_triage"] = overall
    write_new(audit_root / "analysis" / "correctness_metrics.json", canonical_json_bytes(result))
    write_new(audit_root / "manifests" / "measurement_complete.json", canonical_json_bytes({
        "human_measurement_status": "COMPLETE", "analysis_status": "MEASUREMENT_COMPLETE",
        "overall_triage": overall,
    }))
    return result

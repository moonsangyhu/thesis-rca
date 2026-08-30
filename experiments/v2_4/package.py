"""Build the absent-only, package-only V2.4 reviewer bundle."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import tempfile
import zipfile
from collections import OrderedDict
from pathlib import Path
from typing import Any

from .constants import (
    AUDIT_SCHEMA_VERSION, CONDITIONS, CORRECTNESS_FIELDS, EXPECTED_CAMPAIGN_ID,
    SEMANTIC_FIELDS, SELECTED_INCIDENTS,
)
from .identity import (
    GENERATION_FIELDS, INCIDENT_FIELDS, ROW_FIELDS, canonical_identity, opaque_id,
    ordered_ids,
)
from .io import (
    AuditError, assert_quiescent_chroma, canonical_json_bytes, raw_copy_tree,
    sha256_bytes, sha256_file, tree_manifest, write_new,
)
from .isolation import ExternalCallGuard
from .reconstruct import RECONSTRUCTION_SPEC, StoredDocuments, reconstruct, require_python311
from .scanner import assert_safe_archive_members, scan_archive
from .selector import CampaignData, load_primary03, selected_rows


def _csv_bytes(fields: tuple[str, ...], records: list[dict[str, str]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n", extrasaction="raise")
    writer.writeheader()
    writer.writerows(records)
    return stream.getvalue().encode("utf-8", "strict")


def _deterministic_zip(members: dict[str, bytes]) -> bytes:
    assert_safe_archive_members(members)
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(members):
            info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100400 << 16
            info.create_system = 3
            archive.writestr(info, members[name])
    return stream.getvalue()


def _ground_truth_lock(path: Path) -> tuple[dict[tuple[str, int], dict[str, str]], dict[str, Any]]:
    if path.is_symlink() or not path.is_file():
        raise AuditError("ground truth must be an explicit regular file")
    raw = path.read_bytes()
    before_digest = sha256_bytes(raw)
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8", "strict"), newline=""))
    required_columns = {
        "fault_id", "trial", "fault_name", "target_service", "injection_method",
        "expected_root_cause", "affected_components", "primary_symptoms",
        "expected_metrics", "expected_log_patterns", "expected_recovery_action",
    }
    if not required_columns <= set(reader.fieldnames or ()):
        raise AuditError("ground truth schema mismatch")
    records = list(reader)
    if sha256_file(path) != before_digest:
        raise AuditError("INVALID_INPUT_MUTATION: ground truth changed while reading")
    rows = {(row["fault_id"], int(row["trial"])): row for row in records}
    if len(rows) != len(records):
        raise AuditError("duplicate ground truth row identity")
    fields = (
        "target_service", "expected_root_cause", "primary_symptoms", "expected_metrics",
        "expected_log_patterns", "expected_recovery_action", "fault_name",
        "affected_components", "injection_method",
    )
    selected = []
    for identity in SELECTED_INCIDENTS:
        if identity not in rows:
            raise AuditError(f"ground truth row missing: {identity}")
        selected.append({
            "row_identity": {"fault_id": identity[0], "trial": identity[1]},
            "field_hashes": {
                field: sha256_bytes(rows[identity][field].encode("utf-8", "strict"))
                for field in fields
            },
        })
    return rows, {
        "schema": "v2.4-ground-truth-reference-lock-1",
        "file_sha256": before_digest, "fields": list(fields), "rows": selected,
    }


def _candidate(record: dict[str, Any]) -> tuple[str, str, str]:
    if set(record) != {"identified_fault_type", "root_cause", "remediation"}:
        raise AuditError("representative output schema mismatch")
    remediation = record["remediation"]
    if not isinstance(remediation, list) or not all(isinstance(item, str) for item in remediation):
        raise AuditError("candidate remediation must be string list")
    return (
        str(record["identified_fault_type"]), str(record["root_cause"]),
        json.dumps(remediation, ensure_ascii=False, separators=(",", ":")),
    )


def _identity_map(secret: bytes, data: CampaignData) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows, generations = [], []
    for fault, trial in SELECTED_INCIDENTS:
        incident = OrderedDict((
            ("campaign_id", EXPECTED_CAMPAIGN_ID), ("fault_id", fault), ("trial", trial),
        ))
        context_id = opaque_id(secret, "v2.4/context-id", "S-", canonical_identity(incident, INCIDENT_FIELDS))
        for condition in CONDITIONS:
            identity = OrderedDict((
                ("campaign_id", EXPECTED_CAMPAIGN_ID), ("fault_id", fault),
                ("trial", trial), ("condition", condition),
            ))
            case_id = opaque_id(secret, "v2.4/case-id", "C-", canonical_identity(identity, ROW_FIELDS))
            raw = data.raw[(fault, trial, condition)]
            rows.append({
                "case_id": case_id, "context_id": context_id, **identity,
                "terra_correct_at_0_5": int(raw["correct_at_0.5"]),
                "terra_representative_score": float(raw["representative_score"]),
                "representative_generation_repeat": int(raw["representative_generation_repeat"]),
                "generation_split": bool(raw["generation_split"]),
                "runtime_context_hash": raw["runtime_context_hash"],
                "additional_context_hash": raw["additional_context_hash"],
                "full_context_hash": raw["full_context_hash"],
            })
            generator_entries = [item for item in raw["call_ledger"] if item.get("role") == "generator"]
            if {item.get("generation_repeat") for item in generator_entries} != {1, 2, 3}:
                raise AuditError("generation ledger must contain repeats 1..3")
            for item in generator_entries:
                generation_identity = OrderedDict((*identity.items(), ("generation_repeat", item["generation_repeat"])))
                generation_id = opaque_id(
                    secret, "v2.4/generation-id", "G-",
                    canonical_identity(generation_identity, GENERATION_FIELDS),
                )
                generations.append({
                    "generation_id": generation_id, **generation_identity,
                    "output_text_hash": item["output_text_hash"],
                    "representative": item["generation_repeat"] == raw["representative_generation_repeat"],
                })
    if len({item["case_id"] for item in rows}) != 36 or len({item["context_id"] for item in rows}) != 12:
        raise AuditError("opaque row/incident ID collision")
    if len(generations) != 108 or len({item["generation_id"] for item in generations}) != 108:
        raise AuditError("all-generation seal must contain 108 unique identities")
    return rows, generations


def _instructions(phase: str) -> bytes:
    if phase == "correctness":
        text = (
            "# V2.4 correctness review\n\n"
            "각 item을 다른 item과 비교하지 말고 frozen reference에 대해 독립적으로 평가합니다. "
            "condition, 자동 점수, provider는 의도적으로 제공되지 않습니다. 입력 열 세 개만 수정합니다.\n\n"
            "- 0: 핵심 fault family, target 또는 mechanism이 틀려 제안 조치로 해결하기 어려움\n"
            "- 1: 상위 family/주요 mechanism은 맞지만 target, causal chain, remediation의 중요한 부분이 누락/오류\n"
            "- 2: target과 mechanism이 부합하고 설명이 evidence와 모순되지 않으며 remediation 원리가 원인을 해결\n"
            "- A: reference/output만으로 판정 불가능. 단순한 자신 없음의 대체값으로 쓰지 않음\n\n"
            "reason_codes는 세미콜론으로 구분합니다: WRONG_FAMILY, WRONG_TARGET, "
            "MECHANISM_MISSING, CAUSAL_CHAIN_WEAK, EVIDENCE_CONTRADICTION, "
            "REMEDIATION_INADEQUATE, REFERENCE_AMBIGUOUS, OUTPUT_UNPARSABLE.\n\n"
            "한 session은 최대 18개이며 session 사이 최소 15분 휴식합니다. 실제 item 전에 별도 "
            "synthetic training 8개 중 7개 이상 통과와 자격/노출 conflict 기록이 필요합니다.\n"
        )
    else:
        text = (
            "# V2.4 semantic shortcut review\n\n"
            "Correctness 원판정과 adjudication이 잠기고 phase가 CLOSED인 뒤에만 공개합니다. "
            "Procedure의 shortcut severity, 네 boolean, 근거 span/rationale만 입력합니다.\n\n"
            "- L0: 여러 fault에 공통인 일반 확인·분기·안전 복구 절차\n"
            "- L1: 넓은 fault family를 좁히지만 답을 유일하게 만들지 않는 약한 단서\n"
            "- L2: label 없이도 선택 incident mechanism을 사실상 유일하게 암시\n"
            "- L3: canonical/alias label, target entity, injection-specific 값·명령을 직접 노출\n\n"
            "label_exposed, entity_exposed, injection_specific, generic_procedure는 severity와 독립적으로 "
            "true/false를 기록합니다. 한 session은 최대 6개이며 session 사이 최소 15분 휴식합니다.\n"
        )
    return text.encode("utf-8")


def preflight(campaign_dir: Path, ground_truth: Path, chroma: Path) -> dict[str, Any]:
    guard = ExternalCallGuard()
    with guard.enforce():
        # Lock/reference-read happens before candidate campaign parsing by contract.
        _, reference_lock = _ground_truth_lock(ground_truth)
        campaign_before = tree_manifest(campaign_dir)
        data = load_primary03(campaign_dir)
        campaign_after = tree_manifest(campaign_dir)
        if campaign_before["tree_sha256"] != campaign_after["tree_sha256"]:
            raise AuditError("INVALID_INPUT_MUTATION")
        chroma_manifest = assert_quiescent_chroma(chroma)
        report = {
            "status": "DRY_RUN_PASS", "campaign_id": data.campaign_id,
            "csv_rows": len(data.rows), "raw_files": len(data.raw), "incidents": 39,
            "selected_incidents": [f"{f}-t{t}" for f, t in SELECTED_INCIDENTS],
            "selected_outputs": len(selected_rows(data)),
            "ground_truth_file_sha256": reference_lock["file_sha256"],
            "chroma_tree_sha256": chroma_manifest["tree_sha256"],
        }
    isolation = guard.manifest()
    report.update({
        "zero_call_assurance": isolation["zero_call_assurance"],
        "observed_external_calls": isolation["observed_external_calls"],
        "observed_k8s_calls": isolation["observed_k8s_calls"],
        "isolation_policy_sha256": isolation["policy_sha256"],
    })
    return report


def _build_package_at(
    campaign_dir: Path, ground_truth: Path, chroma: Path, audit_root: Path,
    secret: bytes | None = None,
) -> Path:
    require_python311()
    if audit_root.exists():
        raise AuditError(f"refusing to overwrite existing audit path: {audit_root}")
    # Ground truth is committed before any candidate is loaded.
    truth, reference_lock = _ground_truth_lock(ground_truth)
    guard = ExternalCallGuard()
    with guard.enforce():
        campaign_before = tree_manifest(campaign_dir)
        data = load_primary03(campaign_dir)
        audit_root.mkdir(parents=True, exist_ok=False)
        working = audit_root / "working" / "chroma_snapshot"
        chroma_source, chroma_copy = raw_copy_tree(chroma, working)
        master = secret if secret is not None else os.urandom(32)
        if len(master) != 32:
            raise AuditError("master secret must be exactly 32 bytes")
        mappings, generations = _identity_map(master, data)
        mapping_by_source = {
            (item["fault_id"], item["trial"], item["condition"]): item for item in mappings
        }
        correctness_by_id: dict[str, dict[str, str]] = {}
        semantic_by_id: dict[str, dict[str, str]] = {}
        reconstruction_evidence = []
        for row, raw in selected_rows(data):
            key = (row["fault_id"], int(row["trial"]), row["context_condition"])
            mapping = mapping_by_source[key]
            gt = truth[key[:2]]
            identified, root_cause, remediation = _candidate(raw["representative_output"])
            correctness_by_id[mapping["case_id"]] = dict(zip(CORRECTNESS_FIELDS, (
                mapping["case_id"], gt["target_service"], gt["expected_root_cause"],
                gt["primary_symptoms"], gt["expected_metrics"], gt["expected_log_patterns"],
                gt["expected_recovery_action"], identified, root_cause, remediation, "", "", "",
            )))
        with StoredDocuments(working) as documents:
            for fault, trial in SELECTED_INCIDENTS:
                raw = data.raw[(fault, trial, "blind_procedural_rag")]
                text, evidence = reconstruct(raw, documents)
                mapping = mapping_by_source[(fault, trial, "blind_procedural_rag")]
                gt = truth[(fault, trial)]
                semantic_by_id[mapping["context_id"]] = dict(zip(SEMANTIC_FIELDS, (
                    mapping["context_id"], gt["fault_name"], gt["target_service"] + "," + gt["affected_components"],
                    gt["expected_root_cause"], gt["injection_method"], text,
                    "", "", "", "", "", "",
                )))
                reconstruction_evidence.append({
                    "context_id": mapping["context_id"],
                    "masked_procedure_hash": raw["retrieval_provenance"]["masked_procedure_hash"],
                    "additional_context_hash": raw["additional_context_hash"],
                    "candidate_sources": evidence,
                })
        if len(correctness_by_id) != 36 or len(semantic_by_id) != 12:
            raise AuditError("package output count mismatch")
        all_archives = {}
        scanner_reports = {}
        orders = {}
        known_identifiers = sorted(set([
            EXPECTED_CAMPAIGN_ID,
            *(f"{fault}-t{trial}" for fault, trial in SELECTED_INCIDENTS),
            *(item["case_id"] for item in mappings),
            *(item["context_id"] for item in mappings),
            *(item["generation_id"] for item in generations),
            data.manifest["corpus_version"],
            *(
                candidate["source_id"]
                for fault, trial in SELECTED_INCIDENTS
                for candidate in data.raw[(fault, trial, "blind_procedural_rag")]["retrieval_provenance"]["candidates"]
            ),
            *(
                candidate[key]
                for fault, trial in SELECTED_INCIDENTS
                for candidate in data.raw[(fault, trial, "blind_procedural_rag")]["retrieval_provenance"]["candidates"]
                for key in ("source_text_hash", "snapshot_locator")
            ),
            *(
                str(raw.get(key, ""))
                for fault, trial in SELECTED_INCIDENTS
                for condition in CONDITIONS
                for raw in (data.raw[(fault, trial, condition)],)
                for key in (
                    "runtime_context_hash", "additional_context_hash", "full_context_hash",
                    "schedule_hash", "retrieval_query_hash", "injection_result_hash",
                )
            ),
            *(
                entry["output_text_hash"]
                for fault, trial in SELECTED_INCIDENTS
                for condition in CONDITIONS
                for entry in data.raw[(fault, trial, condition)]["call_ledger"]
                if entry.get("output_text_hash")
            ),
            *(
                str(entry[key])
                for fault, trial in SELECTED_INCIDENTS
                for condition in CONDITIONS
                for entry in data.raw[(fault, trial, condition)]["call_ledger"]
                for key in (
                    "session_id", "provider", "requested_model", "actual_model",
                    "cli_executable", "cli_version",
                )
                if entry.get(key)
            ),
            *(
                f"{EXPECTED_CAMPAIGN_ID}_{fault}_t{trial}_{condition}.json"
                for fault, trial in SELECTED_INCIDENTS for condition in CONDITIONS
            ),
        ]))
        for reviewer in ("R1", "R2"):
            c_order = ordered_ids(master, reviewer, "correctness", correctness_by_id)
            s_order = ordered_ids(master, reviewer, "semantic", semantic_by_id)
            if len(c_order) != 36 or len(s_order) != 12:
                raise AuditError("reviewer order is not a full permutation")
            orders[reviewer] = {"correctness": c_order, "semantic": s_order}
            c_records = [correctness_by_id[item] for item in c_order]
            s_records = [semantic_by_id[item] for item in s_order]
            c_zip = _deterministic_zip({
                "correctness.csv": _csv_bytes(CORRECTNESS_FIELDS, c_records),
                "instructions.md": _instructions("correctness"),
            })
            s_zip = _deterministic_zip({
                "semantic.csv": _csv_bytes(SEMANTIC_FIELDS, s_records),
                "instructions.md": _instructions("semantic"),
            })
            scanner_reports[f"{reviewer}_correctness"] = scan_archive(
                "correctness", c_zip, known_identifiers
            )
            scanner_reports[f"{reviewer}_semantic"] = scan_archive(
                "semantic", s_zip, known_identifiers
            )
            all_archives[f"{reviewer}_correctness"] = c_zip
            all_archives[f"{reviewer}_semantic"] = s_zip
        if any(orders["R1"][phase] == orders["R2"][phase] for phase in ("correctness", "semantic")):
            raise AuditError("reviewer orders must differ in each phase")
        secret_commitment = sha256_bytes(master)
        package_commitment = {
            "secret_sha256": secret_commitment,
            "orders_sha256": sha256_bytes(canonical_json_bytes(orders)),
            "archives": {name: sha256_bytes(value) for name, value in sorted(all_archives.items())},
            "scanner_reports": scanner_reports,
        }
        # Commit secret/mapping/package/order/archive before distribution files appear.
        write_new(audit_root / "sealed" / "master_blinding_secret.bin", master)
        write_new(audit_root / "sealed" / "answer_key.json", canonical_json_bytes({
            "schema": AUDIT_SCHEMA_VERSION, "mapping": mappings,
            "all_generation_seal": generations,
        }))
        write_new(audit_root / "sealed" / "ground_truth_reference_lock.json", canonical_json_bytes(reference_lock))
        write_new(audit_root / "sealed" / "reconstruction_evidence.json", canonical_json_bytes({
            "spec": RECONSTRUCTION_SPEC, "items": reconstruction_evidence,
        }))
        write_new(audit_root / "manifests" / "package_commitment.json", canonical_json_bytes(package_commitment))
        for reviewer in ("R1", "R2"):
            # Semantic stays sealed pending correctness close; it is prepared, not distributed.
            write_new(
                audit_root / "sealed" / "pending_semantic" / f"{reviewer}_semantic.zip",
                all_archives[f"{reviewer}_semantic"],
            )
            write_new(
                audit_root / "distribution" / "correctness" / reviewer.lower() / f"{reviewer}_correctness.zip",
                all_archives[f"{reviewer}_correctness"], 0o400,
            )
        campaign_after = tree_manifest(campaign_dir)
        working_after = tree_manifest(working)
        if campaign_before["tree_sha256"] != campaign_after["tree_sha256"]:
            raise AuditError("INVALID_INPUT_MUTATION")
        if sha256_file(ground_truth) != reference_lock["file_sha256"]:
            raise AuditError("INVALID_INPUT_MUTATION: ground truth")
        if chroma_copy["tree_sha256"] != working_after["tree_sha256"]:
            raise AuditError("working Chroma mutation")
        status = {
            "technical_package_status": "COMPLETE",
            "human_measurement_status": "AWAITING_REVIEW",
            "analysis_status": "PACKAGE_ONLY",
            "status_detail": "PACKAGE_READY_AWAITING_HUMAN_REVIEW",
            "human_ratings": 0, "adjudications": 0,
            "measurement_gate": "NOT_EVALUATED",
        }
        input_manifest = {
            "campaign": campaign_before, "chroma_source": chroma_source,
            "chroma_working": chroma_copy, "ground_truth": reference_lock,
        }
        write_new(audit_root / "manifests" / "input_manifest.json", canonical_json_bytes(input_manifest))
        write_new(audit_root / "manifests" / "isolation.json", canonical_json_bytes(guard.manifest()))
        write_new(audit_root / "manifests" / "status.json", canonical_json_bytes(status))
    return audit_root


def build_package(
    campaign_dir: Path, ground_truth: Path, chroma: Path, output_root: Path,
    audit_id: str, secret: bytes | None = None,
) -> Path:
    require_python311()
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", audit_id) is None:
        raise AuditError("audit ID must be a safe path component")
    output_root.mkdir(parents=True, exist_ok=True)
    final = output_root / audit_id
    if final.exists():
        raise AuditError(f"refusing to overwrite existing audit ID: {audit_id}")
    staging = Path(tempfile.mkdtemp(prefix=f".{audit_id}.staging-", dir=output_root))
    staging.rmdir()  # _build_package_at owns absent-only creation.
    try:
        _build_package_at(campaign_dir, ground_truth, chroma, staging, secret)
        if final.exists():
            raise AuditError(f"refusing to overwrite existing audit ID: {audit_id}")
        os.rename(staging, final)
    except BaseException:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return final


def verify_replay(
    audit_root: Path, campaign_dir: Path, ground_truth: Path, chroma: Path,
) -> dict[str, Any]:
    """Rebuild the same audit ID with its sealed key and compare byte-for-byte."""
    blinding_key = (audit_root / "sealed" / "master_blinding_secret.bin").read_bytes()
    if sha256_bytes(blinding_key) != json.loads(
        (audit_root / "manifests" / "package_commitment.json").read_text("utf-8")
    )["secret_sha256"]:
        raise AuditError("sealed key commitment mismatch")
    with tempfile.TemporaryDirectory(prefix="v2.4-replay-") as root:
        replay = build_package(
            campaign_dir, ground_truth, chroma, Path(root), audit_root.name, blinding_key
        )
        def source_fingerprint(root: Path) -> bytes:
            document = json.loads((root / "manifests" / "input_manifest.json").read_text("utf-8"))
            return canonical_json_bytes({
                "campaign": {
                    "tree_sha256": document["campaign"]["tree_sha256"],
                    "files": [
                        {key: item[key] for key in ("path", "size", "sha256")}
                        for item in document["campaign"]["files"]
                    ],
                },
                "ground_truth": document["ground_truth"],
                "chroma_source": {
                    "tree_sha256": document["chroma_source"]["tree_sha256"],
                    "files": [
                        {key: item[key] for key in ("path", "size", "sha256")}
                        for item in document["chroma_source"]["files"]
                    ],
                },
            })
        if source_fingerprint(audit_root) != source_fingerprint(replay):
            raise AuditError("same-audit replay input/source manifest drift")
        relatives = (
            "distribution/correctness/r1/R1_correctness.zip",
            "distribution/correctness/r2/R2_correctness.zip",
            "sealed/pending_semantic/R1_semantic.zip",
            "sealed/pending_semantic/R2_semantic.zip",
        )
        mismatches = [
            relative for relative in relatives
            if (audit_root / relative).read_bytes() != (replay / relative).read_bytes()
        ]
        if mismatches:
            raise AuditError(f"same-audit replay byte mismatch: {mismatches}")
    return {"status": "PASS", "audit_id": audit_root.name, "archives_verified": 4}

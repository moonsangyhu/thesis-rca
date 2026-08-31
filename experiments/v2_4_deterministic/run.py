"""Approval-gated offline V2.4-D runner.

The runner has no network, model, cluster, or subprocess capability.  It does
not print candidate text.  ``--dry-run`` reads only metadata and hashes; full
mode verifies approval before opening any raw candidate file.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from . import analyze, scorer


CONDITIONS = analyze.CONDITIONS
SELECTED = ("F1-t2", "F1-t3", "F2-t1", "F3-t3", "F3-t4", "F4-t1", "F5-t2", "F5-t3", "F6-t5", "F7-t1", "F7-t3", "F8-t3")
RESULT_COLUMNS = ("incident_id", "fault_id", "trial", "condition", "cm", "flm", "mca", "ra", "jlc_d", "jlc_relaxed", "full", "component_mention_path", "fault_label_mention_path", "mechanism_path", "remediation_path", "contradiction_ids", "ontology_sha256", "scorer_sha256", "input_csv_sha256", "raw_manifest_sha256")
GT_SHA256 = "d00115766dbfaa844b5325ff60aac8170b83689ccf2f2d2cd427faad9f8115c6"
GT_PROJECTION_SHA256 = "be456f903354d581ae66c8f7051ea271a9add2cb7b6a58e28d1d768aaee57b1b"


class RunInvalid(ValueError):
    pass


def sha(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _safe_relative(value: str) -> Path:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise RunInvalid("UNSAFE_PATH")
    path = Path(value)
    if path.is_absolute() or ".." in path.parts:
        raise RunInvalid("UNSAFE_PATH")
    return path


def _lstat_regular(path: Path):
    try:
        item = path.lstat()
    except OSError as exc:
        raise RunInvalid("UNSAFE_INPUT") from exc
    if not stat.S_ISREG(item.st_mode) or item.st_nlink != 1:
        raise RunInvalid("UNSAFE_INPUT")
    return item


def _check_ancestors(path: Path) -> None:
    current = path.resolve(strict=False)
    # Check the supplied lexical path too, so a symlink is never resolved away.
    for item in (path, *path.parents):
        try:
            if item.is_symlink():
                raise RunInvalid("SYMLINK")
        except OSError as exc:
            raise RunInvalid("UNSAFE_PATH") from exc
        if item == item.parent:
            break
    del current


def _open_verified(path: Path, expected: dict | None = None) -> tuple[bytes, dict]:
    _check_ancestors(path)
    before = _lstat_regular(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(path, flags)
    except OSError as exc:
        raise RunInvalid("UNSAFE_INPUT") from exc
    try:
        fst_before = os.fstat(fd)
        if not stat.S_ISREG(fst_before.st_mode) or fst_before.st_nlink != 1 or (fst_before.st_dev, fst_before.st_ino, fst_before.st_size) != (before.st_dev, before.st_ino, before.st_size):
            raise RunInvalid("TOCTOU")
        first = hashlib.sha256()
        chunks = []
        while True:
            block = os.read(fd, 1 << 20)
            if not block:
                break
            first.update(block)
            chunks.append(block)
        payload = b"".join(chunks)
        os.lseek(fd, 0, os.SEEK_SET)
        second = hashlib.sha256()
        while block := os.read(fd, 1 << 20):
            second.update(block)
        fst_after = os.fstat(fd)
    finally:
        os.close(fd)
    after = _lstat_regular(path)
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    if first.hexdigest() != second.hexdigest() or identity != (fst_after.st_dev, fst_after.st_ino, fst_after.st_size, fst_after.st_mtime_ns, fst_after.st_ctime_ns) or identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns):
        raise RunInvalid("TOCTOU")
    metadata = {"size": before.st_size, "sha256": first.hexdigest(), "device": before.st_dev, "inode": before.st_ino}
    if expected and (metadata["size"] != expected["size"] or metadata["sha256"] != expected["sha256"]):
        raise RunInvalid("INPUT_COMMITMENT_MISMATCH")
    return payload, metadata


def safe_metadata(root: Path):
    root = Path(root)
    _check_ancestors(root)
    if not root.is_dir():
        raise RunInvalid("UNSAFE_RAW")
    items = []
    for path in sorted(root.rglob("*.json")):
        relative = path.relative_to(root).as_posix()
        _safe_relative(relative)
        _, item = _open_verified(path)
        items.append((relative, item["size"], item["sha256"]))
    return items


def _load_json_metadata(path: Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunInvalid("INVALID_METADATA") from exc


def _approval_gate(path: Path) -> dict:
    approval = _load_json_metadata(path)
    required = {"approval_version", "approved_bundle", "execution_commit", "approval", "semantic_review_sha256", "input_commitment_sha256", "ontology_sha256", "scorer_sha256", "ground_truth_sha256", "ground_truth_projection_sha256"}
    if set(approval) != required or approval["approval_version"] != "v2.4-d-approval-1" or approval["approval"] != "APPROVED" or any(not isinstance(approval[key], str) or not approval[key] for key in required - {"approval_version", "approval"}):
        raise RunInvalid("APPROVAL_REQUIRED")
    return approval


def _approval_identity_gate(approval: dict, *, commitment: Path, ontology: Path, ground_truth_sha256: str, projection_sha256: str) -> None:
    expected = {"input_commitment_sha256": sha(commitment), "ontology_sha256": sha(ontology), "scorer_sha256": sha(Path(scorer.__file__)), "ground_truth_sha256": ground_truth_sha256, "ground_truth_projection_sha256": projection_sha256}
    if any(approval[key] != value for key, value in expected.items()):
        raise RunInvalid("APPROVAL_IDENTITY_MISMATCH")


def _commitment_gate(commitment_path: Path, raw_dir: Path, csv_path: Path) -> tuple[dict, list[tuple[str, int, str]], str]:
    commitment = _load_json_metadata(commitment_path)
    if set(commitment) - {"raw_files", "raw_count", "csv", "commitment_sha256", "provenance"} or not isinstance(commitment.get("raw_files"), list) or commitment.get("raw_count") != 117 or not isinstance(commitment.get("csv"), dict):
        raise RunInvalid("INPUT_COMMITMENT_MISMATCH")
    expected = []
    for item in commitment["raw_files"]:
        if set(item) != {"path", "size", "sha256"} or not isinstance(item["size"], int) or not isinstance(item["sha256"], str):
            raise RunInvalid("INPUT_COMMITMENT_MISMATCH")
        expected.append((str(_safe_relative(item["path"])).replace("\\", "/"), item["size"], item["sha256"]))
    if expected != sorted(expected) or len(set(path for path, _, _ in expected)) != 117:
        raise RunInvalid("INPUT_COMMITMENT_MISMATCH")
    actual = safe_metadata(raw_dir)
    if actual != expected:
        raise RunInvalid("RAW_COMMITMENT_MISMATCH")
    csv_meta = commitment["csv"]
    _, actual_csv = _open_verified(csv_path)
    if set(csv_meta) != {"path", "size", "sha256"} or csv_meta["path"] != csv_path.name or actual_csv["sha256"] != csv_meta["sha256"] or actual_csv["size"] != csv_meta["size"]:
        raise RunInvalid("INPUT_COMMITMENT_MISMATCH")
    manifest_sha = hashlib.sha256(_canonical([{ "path": path, "size": size, "sha256": digest} for path, size, digest in actual])).hexdigest()
    return commitment, actual, manifest_sha


def dry_run(commitment, raw_dir, csv_path):
    _, entries, _ = _commitment_gate(Path(commitment), Path(raw_dir), Path(csv_path))
    return {"status": "PREFLIGHT_PASS", "candidate_text_opened": False, "raw_count": len(entries)}


def _csv_identity(payload: bytes) -> dict:
    try:
        rows = list(csv.DictReader(payload.decode("utf-8", "strict").splitlines()))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise RunInvalid("CSV_SCHEMA") from exc
    if len(rows) != 117:
        raise RunInvalid("CSV_IDENTITY")
    output = {}
    for row in rows:
        condition = row.get("context_condition", row.get("condition"))
        try:
            key = ("F" + str(int(str(row["fault_id"])[1:])), int(row["trial"]), condition)
        except (KeyError, TypeError, ValueError) as exc:
            raise RunInvalid("CSV_SCHEMA") from exc
        if condition not in CONDITIONS or key in output:
            raise RunInvalid("CSV_IDENTITY")
        output[key] = row
    return output


def _raw_record(payload: bytes):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise RunInvalid("RAW_SCHEMA")
            result[key] = value
        return result
    try:
        item = json.loads(payload.decode("utf-8", "strict"), object_pairs_hook=pairs)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunInvalid("RAW_SCHEMA") from exc
    required = {"fault_id", "trial", "context_condition", "representative_output"}
    if not isinstance(item, dict) or not required <= set(item) or not isinstance(item["fault_id"], str) or not isinstance(item["trial"], int) or item["context_condition"] not in CONDITIONS:
        raise RunInvalid("RAW_SCHEMA")
    candidate = item["representative_output"]
    if isinstance(candidate, str):
        candidate_bytes = candidate.encode("utf-8")
    elif isinstance(candidate, dict):
        candidate_bytes = _canonical(candidate)
    else:
        raise RunInvalid("RAW_SCHEMA")
    return (item["fault_id"], item["trial"], item["context_condition"]), candidate_bytes


def _projection_hash(ground_truth: Path) -> str:
    payload, _ = _open_verified(ground_truth)
    try:
        rows = list(csv.DictReader(payload.decode("utf-8", "strict").splitlines()))
        chosen = [row for row in rows if f"{row['fault_id']}-t{int(row['trial'])}" in SELECTED]
        projection = [{key: row[key] for key in ("fault_id", "trial", "fault_name", "target_service", "expected_root_cause", "expected_recovery_action")} for row in sorted(chosen, key=lambda row: (int(row["fault_id"][1:]), int(row["trial"])))]
    except (KeyError, ValueError, UnicodeDecodeError, csv.Error) as exc:
        raise RunInvalid("GROUND_TRUTH_SCHEMA") from exc
    if len(projection) != 12:
        raise RunInvalid("GROUND_TRUTH_SCHEMA")
    return hashlib.sha256(_canonical(projection)).hexdigest()


def _score_rows(raw_dir: Path, entries, csv_rows: dict, ontology: Path, hashes: dict):
    records = {}
    for relative, size, digest in entries:
        payload, _ = _open_verified(raw_dir / _safe_relative(relative), {"size": size, "sha256": digest})
        key, candidate = _raw_record(payload)
        if key in records:
            raise RunInvalid("RAW_IDENTITY")
        records[key] = candidate
    if set(records) != set(csv_rows) or len(records) != 117:
        raise RunInvalid("RAW_CSV_MAPPING")
    expected = {(incident, condition) for incident in SELECTED for condition in CONDITIONS}
    selected = {(f"{fault}-t{trial}", condition): candidate for (fault, trial, condition), candidate in records.items() if f"{fault}-t{trial}" in SELECTED}
    if set(selected) != expected:
        raise RunInvalid("SELECTED_IDENTITY")
    rows, trace = [], []
    for incident, condition in sorted(selected, key=lambda item: (_incident_key(item[0]), CONDITIONS.index(item[1]))):
        fault, trial = incident.split("-t", 1)
        try:
            result = scorer.score(incident, selected[(incident, condition)], ontology)
        except scorer.InvalidInput as exc:
            raise RunInvalid(str(exc)) from exc
        row = {"incident_id": incident, "fault_id": fault, "trial": int(trial), "condition": condition, **{key: result[key] for key in ("cm", "flm", "mca", "ra", "jlc_d", "jlc_relaxed", "full")}, "component_mention_path": json.dumps(result["component_mention_path"], separators=(",", ":")), "fault_label_mention_path": json.dumps(result["fault_label_mention_path"], separators=(",", ":")), "mechanism_path": json.dumps(result["mechanism_path"], separators=(",", ":")), "remediation_path": json.dumps(result["remediation_path"], separators=(",", ":")), "contradiction_ids": json.dumps(result["contradiction_ids"], separators=(",", ":")), **hashes}
        rows.append(row)
        trace.append({"incident_id": incident, "condition": condition, "component_mention_path": result["component_mention_path"], "fault_label_mention_path": result["fault_label_mention_path"], "mechanism_path": result["mechanism_path"], "remediation_path": result["remediation_path"], "contradiction_ids": result["contradiction_ids"]})
    analyze.validate_rows(rows)
    return rows, trace


def _incident_key(incident: str):
    fault, trial = incident.split("-t", 1)
    return int(fault[1:]), int(trial)


def _write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=RESULT_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            item = dict(row)
            for key in ("cm", "flm", "mca", "ra", "jlc_d", "jlc_relaxed", "full"):
                item[key] = int(item[key])
            writer.writerow(item)
        handle.flush(); os.fsync(handle.fileno())


def _write_paired_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=("incident_id", "length_placebo_jlc_d", "blind_procedural_rag_jlc_d"), lineterminator="\n")
        writer.writeheader(); writer.writerows(rows)
        handle.flush(); os.fsync(handle.fileno())


def _write_bytes(path: Path, data: bytes) -> None:
    with path.open("wb") as handle:
        handle.write(data); handle.flush(); os.fsync(handle.fileno())


def _fsync_tree(root: Path) -> None:
    for item in sorted(root.iterdir()):
        if item.is_file():
            with item.open("rb") as handle: os.fsync(handle.fileno())
    descriptor = os.open(root, os.O_RDONLY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def _publish(stage: Path, output: Path) -> None:
    if output.exists():
        raise RunInvalid("OUTPUT_EXISTS")
    _fsync_tree(stage)
    os.replace(stage, output)
    descriptor = os.open(output.parent, os.O_RDONLY)
    try: os.fsync(descriptor)
    finally: os.close(descriptor)


def run_campaign(*, approval: Path, commitment: Path, raw_dir: Path, csv_path: Path, ground_truth: Path, ontology: Path, output: Path, synthetic: bool = False) -> dict:
    # This must remain before raw directory enumeration or candidate file opens.
    started_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    approved = _approval_gate(approval)
    _, ground_truth_metadata = _open_verified(ground_truth)
    gt_hash = ground_truth_metadata["sha256"]
    projection = _projection_hash(ground_truth)
    if not synthetic and (gt_hash != GT_SHA256 or projection != GT_PROJECTION_SHA256):
        raise RunInvalid("GROUND_TRUTH_COMMITMENT_MISMATCH")
    _approval_identity_gate(approved, commitment=commitment, ontology=ontology, ground_truth_sha256=gt_hash, projection_sha256=projection)
    _, entries, raw_manifest_sha = _commitment_gate(commitment, raw_dir, csv_path)
    csv_bytes, _ = _open_verified(csv_path)
    csv_rows = _csv_identity(csv_bytes)
    scorer.load_ontology(ontology)
    hashes = {"ontology_sha256": sha(ontology), "scorer_sha256": sha(Path(scorer.__file__)), "input_csv_sha256": hashlib.sha256(csv_bytes).hexdigest(), "raw_manifest_sha256": raw_manifest_sha}
    rows, trace = _score_rows(raw_dir, entries, csv_rows, ontology, hashes)
    summary = analyze.primary(rows)
    paired = [{"incident_id": incident, "length_placebo_jlc_d": int(next(row["jlc_d"] for row in rows if row["incident_id"] == incident and row["condition"] == "length_placebo")), "blind_procedural_rag_jlc_d": int(next(row["jlc_d"] for row in rows if row["incident_id"] == incident and row["condition"] == "blind_procedural_rag"))} for incident in SELECTED]
    canonical_hash = hashlib.sha256(_canonical({"rows": rows, "paired": paired, "summary": summary, "trace": trace})).hexdigest()
    manifest = {"approval": approved, "ontology_sha256": hashes["ontology_sha256"], "scorer_sha256": hashes["scorer_sha256"], "analyzer_sha256": sha(Path(analyze.__file__)), "input_commitment_sha256": sha(commitment), "input_csv_sha256": hashes["input_csv_sha256"], "raw_manifest_sha256": raw_manifest_sha, "ground_truth_sha256": gt_hash, "ground_truth_projection_sha256": projection, "python_version": sys.version, "seed": 20260831, "row_counts": {"raw": 117, "selected": 36, "conditions": {condition: 12 for condition in CONDITIONS}}, "started_utc": started_utc, "finished_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "replay_result": "PENDING_SECOND_REPLAY", "external_call_count": 0, "model_call_count": 0, "k8s_call_count": 0, "canonical_output_sha256": canonical_hash}
    output = Path(output)
    if output.exists():
        raise RunInvalid("OUTPUT_EXISTS")
    stage = Path(tempfile.mkdtemp(prefix=".v2_4_deterministic-", dir=output.parent))
    try:
        _write_csv(stage / "scores.csv", rows)
        _write_paired_csv(stage / "paired_table.csv", paired)
        _write_bytes(stage / "summary.json", _canonical(summary) + b"\n")
        _write_bytes(stage / "input_manifest.json", _canonical({"raw_manifest_sha256": raw_manifest_sha, "raw_count": 117}) + b"\n")
        _write_bytes(stage / "score_trace.jsonl", b"".join(_canonical(item) + b"\n" for item in trace))
        _write_bytes(stage / "execution.log", b"OFFLINE_SCORING_COMPLETE\n")
        _write_bytes(stage / "manifest.json", _canonical(manifest) + b"\n")
        _publish(stage, output)
    except Exception:
        if stage.exists():
            for item in stage.iterdir(): item.unlink()
            stage.rmdir()
        raise
    return {"status": "PASS", "canonical_output_sha256": canonical_hash, "output": str(output)}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--commitment", type=Path, required=True)
    parser.add_argument("--raw-dir", type=Path, required=True)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--ground-truth", type=Path)
    parser.add_argument("--ontology", type=Path, default=Path(__file__).with_name("ontology_v1.json"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--replay-out", type=Path)
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args(argv)
    if args.dry_run:
        print(json.dumps(dry_run(args.commitment, args.raw_dir, args.csv), sort_keys=True))
        return 0
    if not all((args.approval, args.ground_truth, args.out, args.replay_out)):
        raise SystemExit("APPROVAL_REQUIRED")
    first = run_campaign(approval=args.approval, commitment=args.commitment, raw_dir=args.raw_dir, csv_path=args.csv, ground_truth=args.ground_truth, ontology=args.ontology, output=args.out, synthetic=args.synthetic)
    second = run_campaign(approval=args.approval, commitment=args.commitment, raw_dir=args.raw_dir, csv_path=args.csv, ground_truth=args.ground_truth, ontology=args.ontology, output=args.replay_out, synthetic=args.synthetic)
    if first["canonical_output_sha256"] != second["canonical_output_sha256"]:
        raise SystemExit("REPLAY_MISMATCH")
    replay = _canonical({"replay_result": "MATCH", "canonical_output_sha256": first["canonical_output_sha256"]}) + b"\n"
    temp = args.out / ".replay_manifest.tmp"
    _write_bytes(temp, replay)
    os.replace(temp, args.out / "replay_manifest.json")
    print(json.dumps({"status": "PASS", "canonical_output_sha256": first["canonical_output_sha256"], "replay": "MATCH"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

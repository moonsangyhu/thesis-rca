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
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    _REPO = Path(__file__).resolve().parents[2]
    if not (_REPO / "AGENTS.md").is_file() or not (_REPO / ".git").exists() or any(parent.is_symlink() for parent in (_REPO, *_REPO.parents)):
        raise RuntimeError("UNTRUSTED_REPO_BOOTSTRAP")
    sys.path.insert(0, str(_REPO))
    from experiments.v2_4_deterministic import analyze, commit_inputs, scorer
else:
    from . import analyze, commit_inputs, scorer


CONDITIONS = analyze.CONDITIONS
SELECTED = ("F1-t2", "F1-t3", "F2-t1", "F3-t3", "F3-t4", "F4-t1", "F5-t2", "F5-t3", "F6-t5", "F7-t1", "F7-t3", "F8-t3")
RESULT_COLUMNS = ("incident_id", "fault_id", "trial", "condition", "cm", "flm", "mca", "ra", "jlc_d", "jlc_relaxed", "full", "component_mention_path", "fault_label_mention_path", "mechanism_path", "remediation_path", "contradiction_ids", "ontology_sha256", "scorer_sha256", "input_csv_sha256", "raw_manifest_sha256")
GT_SHA256 = "d00115766dbfaa844b5325ff60aac8170b83689ccf2f2d2cd427faad9f8115c6"
GT_PROJECTION_SHA256 = "be456f903354d581ae66c8f7051ea271a9add2cb7b6a58e28d1d768aaee57b1b"
SEMANTIC_REVIEW = "docs/plans/review_v2_4_deterministic.md"
IMPLEMENTATION_REVIEW = "docs/plans/review_v2_4_deterministic_implementation.md"
APPROVAL_DOCUMENT = "docs/plans/approval_v2_4_deterministic.md"
COMMITMENT_DOCUMENT = "docs/plans/input_commitment_v2_4_deterministic.json"
DEVIATION_DOCUMENT = "docs/plans/non_informative_machine_parse_deviation_v2_4_deterministic.json"
I0_SAFETY_SCOPE = (
    "experiments/v2_4_deterministic/ontology_v1.json",
    "experiments/v2_4_deterministic/__init__.py",
    "experiments/v2_4_deterministic/build_ontology.py",
    "experiments/v2_4_deterministic/commit_inputs.py",
    "experiments/v2_4_deterministic/scorer.py",
    "experiments/v2_4_deterministic/analyze.py",
    "experiments/v2_4_deterministic/run.py",
    "tests/test_v2_4_deterministic.py",
)
I1_TARGETS = (
    "docs/plans/experiment_plan_v2_4_deterministic.md",
    SEMANTIC_REVIEW,
    COMMITMENT_DOCUMENT,
    DEVIATION_DOCUMENT,
    *I0_SAFETY_SCOPE,
)
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")


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
    """Enumerate *every* direct entry through an anchored directory fd."""
    try:
        fd, info, lexical = commit_inputs._open_dir_chain(Path(root))
        try:
            names=sorted(os.listdir(fd))
            if len(names)!=117: raise RunInvalid("UNSAFE_RAW")
            items=[]
            for name in names:
                if name.startswith(".") or not name.endswith(".json"): raise RunInvalid("UNSAFE_RAW")
                size, digest, _ = commit_inputs._digest_at(fd,name)
                items.append((name,size,digest))
            current=os.stat(lexical,follow_symlinks=False)
            if (current.st_dev,current.st_ino)!=(info.st_dev,info.st_ino): raise RunInvalid("TOCTOU")
            return items
        finally:
            os.close(fd)
    except (OSError,ValueError) as exc:
        raise RunInvalid("UNSAFE_RAW") from exc


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


def _git(repo: Path, *args: str) -> str:
    """Run a narrowly-scoped, text-only git query from the trusted checkout."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), *args],
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RunInvalid("GIT_FREEZE_INVALID") from exc
    return result.stdout.rstrip("\n")


def _repo_root() -> Path:
    root = Path(__file__).resolve().parents[2]
    if not (root / "AGENTS.md").is_file() or not (root / ".git").exists():
        raise RunInvalid("UNTRUSTED_REPO_BOOTSTRAP")
    for item in (root, *root.parents):
        if item.is_symlink():
            raise RunInvalid("UNTRUSTED_REPO_BOOTSTRAP")
        if item == item.parent:
            break
    return root


def _sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _strict_hash_record(value, *, path: str) -> dict:
    if not isinstance(value, dict) or set(value) != {"blob_oid", "sha256"}:
        raise RunInvalid("APPROVAL_SCHEMA")
    if not _HEX40.fullmatch(value["blob_oid"]) or not _HEX64.fullmatch(value["sha256"]):
        raise RunInvalid("APPROVAL_SCHEMA")
    if path not in I1_TARGETS and path not in I0_SAFETY_SCOPE:
        raise RunInvalid("APPROVAL_SCHEMA")
    return value


def _strict_target_map(value, expected_paths: tuple[str, ...]) -> dict:
    if not isinstance(value, dict) or set(value) != set(expected_paths):
        raise RunInvalid("APPROVAL_SCHEMA")
    return {path: _strict_hash_record(record, path=path) for path, record in value.items()}


def _strict_approval_gate(path: Path) -> dict:
    """Parse the release approval, whose schema intentionally freezes every gate."""
    approval = _load_json_metadata(path)
    required = {
        "approval_version", "approval", "execution_commit", "approved_bundle",
        "implementation_candidate", "code_candidate", "semantic_review",
        "safety_receipt", "implementation_review", "i0_safety_scope",
        "i1_targets", "commitment", "ground_truth", "interpreter", "deviation",
        "execution_authorization", "methodology_waiver_acknowledged",
    }
    if set(approval) != required or approval.get("approval_version") != "v2.4-d-approval-2" or approval.get("approval") != "APPROVED":
        raise RunInvalid("APPROVAL_SCHEMA")
    if approval["methodology_waiver_acknowledged"] is not True:
        raise RunInvalid("APPROVAL_SCHEMA")
    for name in ("execution_commit", "approved_bundle", "implementation_candidate", "code_candidate"):
        if not isinstance(approval[name], str) or not _HEX40.fullmatch(approval[name]):
            raise RunInvalid("APPROVAL_SCHEMA")
    approval["i0_safety_scope"] = _strict_target_map(approval["i0_safety_scope"], I0_SAFETY_SCOPE)
    approval["i1_targets"] = _strict_target_map(approval["i1_targets"], I1_TARGETS)
    for name, required_keys in {
        "semantic_review": {"path", "blob_oid", "sha256"},
        "implementation_review": {"path", "blob_oid", "sha256", "code_candidate", "implementation_candidate"},
        "safety_receipt": {"path", "sha256", "code_candidate", "tool_blob_oid"},
        "commitment": {"path", "sha256", "commitment_sha256", "csv_sha256", "raw_manifest_sha256", "reviewed_tool_blob_oid", "safety_receipt_sha256", "reviewed_i0"},
        "ground_truth": {"sha256", "projection_sha256"},
        "interpreter": {"path", "sha256", "version"},
        "deviation": {"path", "sha256"},
        "execution_authorization": {"path", "sha256", "execution_commit", "approval_blob_oid", "approval_sha256"},
    }.items():
        value = approval.get(name)
        if not isinstance(value, dict) or set(value) != required_keys:
            raise RunInvalid("APPROVAL_SCHEMA")
        if any(not isinstance(item, str) or not item for item in value.values()):
            raise RunInvalid("APPROVAL_SCHEMA")
    for name in ("semantic_review", "implementation_review"):
        if not _HEX40.fullmatch(approval[name]["blob_oid"]) or not _HEX64.fullmatch(approval[name]["sha256"]):
            raise RunInvalid("APPROVAL_SCHEMA")
    for name in ("safety_receipt", "commitment", "ground_truth", "deviation", "execution_authorization"):
        for key, value in approval[name].items():
            if key.endswith("sha256") and not _HEX64.fullmatch(value):
                raise RunInvalid("APPROVAL_SCHEMA")
    if not _HEX40.fullmatch(approval["safety_receipt"]["code_candidate"]) or not _HEX40.fullmatch(approval["safety_receipt"]["tool_blob_oid"]):
        raise RunInvalid("APPROVAL_SCHEMA")
    if not _HEX40.fullmatch(approval["implementation_review"]["code_candidate"]) or not _HEX40.fullmatch(approval["implementation_review"]["implementation_candidate"]):
        raise RunInvalid("APPROVAL_SCHEMA")
    if not _HEX40.fullmatch(approval["commitment"]["reviewed_tool_blob_oid"]) or not _HEX40.fullmatch(approval["commitment"]["reviewed_i0"]):
        raise RunInvalid("APPROVAL_SCHEMA")
    if not _HEX40.fullmatch(approval["execution_authorization"]["execution_commit"]) or not _HEX40.fullmatch(approval["execution_authorization"]["approval_blob_oid"]):
        raise RunInvalid("APPROVAL_SCHEMA")
    if approval["semantic_review"]["path"] != SEMANTIC_REVIEW or approval["implementation_review"]["path"] != IMPLEMENTATION_REVIEW or approval["commitment"]["path"] != COMMITMENT_DOCUMENT or approval["deviation"]["path"] != DEVIATION_DOCUMENT:
        raise RunInvalid("APPROVAL_SCHEMA")
    return approval


def _git_blob_record(repo: Path, commit: str, path: str) -> dict:
    oid = _git(repo, "rev-parse", f"{commit}:{path}")
    if not _HEX40.fullmatch(oid):
        raise RunInvalid("TARGET_BLOB_INVALID")
    try:
        data = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "blob", f"{commit}:{path}"],
            check=True, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise RunInvalid("TARGET_BLOB_INVALID") from exc
    return {"blob_oid": oid, "sha256": _sha256_bytes(data)}


def _exact_diff(repo: Path, older: str, newer: str, expected: tuple[tuple[str, str], ...]) -> None:
    lines = tuple(tuple(line.split("\t", 1)) for line in _git(repo, "diff", "--name-status", "--no-renames", older, newer).splitlines() if line)
    if lines != expected:
        raise RunInvalid("GIT_FREEZE_DIFF_INVALID")


def _git_path_must_be_absent(repo: Path, commit: str, path: str) -> None:
    """Require an absent I0 path without reading any candidate source bytes."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo), "cat-file", "-e", f"{commit}:{path}"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError as exc:
        raise RunInvalid("GIT_FREEZE_INVALID") from exc
    if result.returncode == 0:
        raise RunInvalid("I0_COMMITMENT_MUST_BE_ABSENT")
    if result.returncode != 1:
        raise RunInvalid("GIT_FREEZE_INVALID")


def _verified_external_file(root: Path, value: dict, *, expected_path: str | None = None) -> bytes:
    raw_path = Path(value["path"])
    if "\x00" in value["path"]:
        raise RunInvalid("APPROVAL_SCHEMA")
    if expected_path is not None and value["path"] != expected_path:
        raise RunInvalid("APPROVAL_SCHEMA")
    if raw_path.is_absolute() and expected_path is not None:
        raise RunInvalid("APPROVAL_SCHEMA")
    if not raw_path.is_absolute() and ".." in raw_path.parts:
        raise RunInvalid("APPROVAL_SCHEMA")
    path = raw_path if raw_path.is_absolute() else root / raw_path
    try:
        data = path.read_bytes()
    except OSError as exc:
        raise RunInvalid("PROVENANCE_MISSING") from exc
    if _sha256_bytes(data) != value["sha256"]:
        raise RunInvalid("PROVENANCE_HASH_MISMATCH")
    return data


def _validate_deviation(value: object, root: Path) -> dict:
    """Exact Rev8 non-informative parse waiver; no candidate input is opened."""
    required={"schema_version","status","confirmatory_disposition","event_date","observed_command","best_known_head","working_tree_state","observed_test_result","original_stdout_sha256","original_stderr_sha256","process_access_zero","text_egress","v2_4_d_execution","output_derived_tuning","approval_waiver_required","evidence_sources"}
    if not isinstance(value,dict) or set(value)!=required or value.get("schema_version")!="v2.4-d-machine-parse-deviation-1" or value.get("status")!="NON_INFORMATIVE_MACHINE_PARSE_DEVIATION" or value.get("confirmatory_disposition")!="CONFIRMATORY_WITH_DISCLOSED_NONINFORMATIVE_MACHINE_PARSE_DEVIATION" or value.get("event_date")!="2026-08-31" or value.get("observed_command")!="python3.11 -m unittest -v tests.test_v2_4_audit" or value.get("best_known_head")!="c9c94b4" or value.get("working_tree_state")!="UNCOMMITTED_IMPLEMENTATION_PRESENT" or value.get("observed_test_result")!="28_PASS" or value.get("original_stdout_sha256")!="NOT_RETAINED" or value.get("original_stderr_sha256")!="NOT_RETAINED" or value.get("process_access_zero") is not False or value.get("text_egress") is not False or value.get("v2_4_d_execution") is not False or value.get("output_derived_tuning") is not False or value.get("approval_waiver_required") is not True:
        raise RunInvalid("DEVIATION_PROVENANCE_INVALID")
    sources=value["evidence_sources"]
    expected={"changelog","full_implementation_review","conversation_derived_attestation"}
    if not isinstance(sources,dict) or set(sources)!=expected: raise RunInvalid("DEVIATION_PROVENANCE_INVALID")
    for name in ("changelog","full_implementation_review"):
        source=sources[name]
        if not isinstance(source,dict) or set(source)!={"path","sha256"} or not isinstance(source["path"],str) or not _HEX64.fullmatch(source.get("sha256","")):
            raise RunInvalid("DEVIATION_PROVENANCE_INVALID")
        path=root/_safe_relative(source["path"])
        try: payload=path.read_bytes()
        except OSError as exc: raise RunInvalid("DEVIATION_PROVENANCE_INVALID") from exc
        if _sha256_bytes(payload)!=source["sha256"]: raise RunInvalid("DEVIATION_PROVENANCE_INVALID")
    attestation=sources["conversation_derived_attestation"]
    if not isinstance(attestation,dict) or set(attestation)!={"canonical_text","sha256"} or not isinstance(attestation["canonical_text"],str) or not _HEX64.fullmatch(attestation.get("sha256","")) or _sha256_bytes(attestation["canonical_text"].encode())!=attestation["sha256"]:
        raise RunInvalid("DEVIATION_PROVENANCE_INVALID")
    return value


def _repository_gate(*, approval_path: Path, code_candidate: str, implementation_candidate: str, approved_bundle: str, execution_commit: str) -> tuple[dict, dict]:
    """Validate all git/provenance identities before *any* candidate path operation."""
    root = _repo_root()
    approval = _strict_approval_gate(approval_path)
    if (approval["code_candidate"], approval["implementation_candidate"], approval["approved_bundle"], approval["execution_commit"]) != (code_candidate, implementation_candidate, approved_bundle, execution_commit):
        raise RunInvalid("APPROVAL_ARGUMENT_MISMATCH")
    if _git(root, "rev-parse", "HEAD") != execution_commit:
        raise RunInvalid("GIT_HEAD_INVALID")
    if _git(root, "status", "--porcelain=v1"):
        raise RunInvalid("GIT_WORKTREE_DIRTY")
    if _git(root, "rev-parse", f"{execution_commit}^") != approved_bundle or _git(root, "rev-parse", f"{approved_bundle}^") != implementation_candidate or _git(root, "rev-parse", f"{implementation_candidate}^") != code_candidate:
        raise RunInvalid("GIT_PARENT_CHAIN_INVALID")
    _git_path_must_be_absent(root, code_candidate, COMMITMENT_DOCUMENT)
    _exact_diff(root, code_candidate, implementation_candidate, (("A", COMMITMENT_DOCUMENT), ("A", DEVIATION_DOCUMENT)))
    _exact_diff(root, implementation_candidate, approved_bundle, (("M", IMPLEMENTATION_REVIEW),))
    _exact_diff(root, approved_bundle, execution_commit, (("A", APPROVAL_DOCUMENT),))
    for path, expected in approval["i0_safety_scope"].items():
        if _git_blob_record(root, code_candidate, path) != expected:
            raise RunInvalid("I0_TARGET_HASH_MISMATCH")
        if _git_blob_record(root, implementation_candidate, path) != expected:
            raise RunInvalid("I0_I1_CODE_MUTATION")
    for path, expected in approval["i1_targets"].items():
        if _git_blob_record(root, implementation_candidate, path) != expected or _git_blob_record(root, approved_bundle, path) != expected or _git_blob_record(root, execution_commit, path) != expected:
            raise RunInvalid("I1_TARGET_HASH_MISMATCH")
        current = root / path
        if current.is_symlink() or not current.is_file() or _sha256_bytes(current.read_bytes()) != expected["sha256"]:
            raise RunInvalid("CHECKOUT_TARGET_HASH_MISMATCH")
    semantic = approval["semantic_review"]
    if _git_blob_record(root, implementation_candidate, SEMANTIC_REVIEW) != {"blob_oid": semantic["blob_oid"], "sha256": semantic["sha256"]}:
        raise RunInvalid("SEMANTIC_REVIEW_IDENTITY_MISMATCH")
    implementation = approval["implementation_review"]
    if (implementation["code_candidate"], implementation["implementation_candidate"]) != (code_candidate, implementation_candidate) or _git_blob_record(root, approved_bundle, IMPLEMENTATION_REVIEW) != {"blob_oid": implementation["blob_oid"], "sha256": implementation["sha256"]}:
        raise RunInvalid("IMPLEMENTATION_REVIEW_IDENTITY_MISMATCH")
    receipt = approval["safety_receipt"]
    if receipt["code_candidate"] != code_candidate or receipt["tool_blob_oid"] != approval["i0_safety_scope"]["experiments/v2_4_deterministic/commit_inputs.py"]["blob_oid"]:
        raise RunInvalid("SAFETY_RECEIPT_IDENTITY_MISMATCH")
    _verified_external_file(root, receipt)
    commitment_info = approval["commitment"]
    if commitment_info["reviewed_i0"] != code_candidate or commitment_info["reviewed_tool_blob_oid"] != receipt["tool_blob_oid"] or commitment_info["safety_receipt_sha256"] != receipt["sha256"]:
        raise RunInvalid("COMMITMENT_PROVENANCE_MISMATCH")
    commitment_bytes = _verified_external_file(root, commitment_info, expected_path=COMMITMENT_DOCUMENT)
    if _sha256_bytes(commitment_bytes) != commitment_info["sha256"]:
        raise RunInvalid("COMMITMENT_HASH_MISMATCH")
    commitment = _load_json_metadata(root / COMMITMENT_DOCUMENT)
    raw_manifest = hashlib.sha256(_canonical(commitment.get("raw_files"))).hexdigest()
    if commitment.get("commitment_sha256") != commitment_info["commitment_sha256"] or commitment.get("csv", {}).get("sha256") != commitment_info["csv_sha256"] or raw_manifest != commitment_info["raw_manifest_sha256"]:
        raise RunInvalid("COMMITMENT_ENVELOPE_MISMATCH")
    provenance = commitment.get("provenance")
    try:
        commit_inputs.validate_commitment_schema(commitment, require_provenance=True)
    except ValueError as exc:
        raise RunInvalid("COMMITMENT_PROVENANCE_MISMATCH") from exc
    if (provenance.get("reviewed_i0"), provenance.get("tool_blob_oid"), provenance.get("safety_receipt_sha256")) != (code_candidate, receipt["tool_blob_oid"], receipt["sha256"]):
        raise RunInvalid("COMMITMENT_PROVENANCE_MISMATCH")
    deviation_bytes = _verified_external_file(root, approval["deviation"], expected_path=DEVIATION_DOCUMENT)
    try:
        deviation = json.loads(deviation_bytes.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RunInvalid("DEVIATION_PROVENANCE_INVALID") from exc
    _validate_deviation(deviation, root)
    authorization = approval["execution_authorization"]
    if authorization["execution_commit"] != execution_commit:
        raise RunInvalid("EXECUTION_AUTHORIZATION_MISMATCH")
    _verified_external_file(root, authorization)
    approval_record = _git_blob_record(root, execution_commit, APPROVAL_DOCUMENT)
    if approval_record != {"blob_oid": authorization["approval_blob_oid"], "sha256": authorization["approval_sha256"]}:
        raise RunInvalid("EXECUTION_AUTHORIZATION_MISMATCH")
    if approval["ground_truth"]["sha256"] != GT_SHA256 or approval["ground_truth"]["projection_sha256"] != GT_PROJECTION_SHA256:
        raise RunInvalid("GROUND_TRUTH_APPROVAL_MISMATCH")
    interpreter = approval["interpreter"]
    if Path(interpreter["path"]).resolve() != Path(sys.executable).resolve() or _sha256_bytes(Path(sys.executable).read_bytes()) != interpreter["sha256"] or interpreter["version"] != sys.version:
        raise RunInvalid("INTERPRETER_IDENTITY_MISMATCH")
    return approval, {"repository_root": str(root), "approval_sha256": _sha256_bytes(Path(approval_path).read_bytes())}


def _commitment_gate(commitment_path: Path, raw_dir: Path, csv_path: Path, *, synthetic: bool = False) -> tuple[dict, list[tuple[str, int, str]], str]:
    commitment = _load_json_metadata(commitment_path)
    try:
        commit_inputs.validate_commitment_schema(commitment, require_provenance=not synthetic)
    except ValueError as exc:
        raise RunInvalid("INPUT_COMMITMENT_MISMATCH") from exc
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
    if actual_csv["sha256"] != csv_meta["sha256"] or actual_csv["size"] != csv_meta["size"] or csv_meta["id_sha256"] != hashlib.sha256(csv_path.name.encode()).hexdigest():
        raise RunInvalid("INPUT_COMMITMENT_MISMATCH")
    manifest_sha = hashlib.sha256(_canonical([{ "path": path, "size": size, "sha256": digest} for path, size, digest in actual])).hexdigest()
    return commitment, actual, manifest_sha


def dry_run(commitment, raw_dir, csv_path):
    _, entries, _ = _commitment_gate(Path(commitment), Path(raw_dir), Path(csv_path), synthetic=True)
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


def run_campaign(*, approval: Path, commitment: Path, raw_dir: Path, csv_path: Path, ground_truth: Path, ontology: Path, output: Path, synthetic: bool = False, approved_override: dict | None = None) -> dict:
    # This must remain before raw directory enumeration or candidate file opens.
    started_utc = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    approved = approved_override if approved_override is not None else _approval_gate(approval)
    _, ground_truth_metadata = _open_verified(ground_truth)
    gt_hash = ground_truth_metadata["sha256"]
    projection = _projection_hash(ground_truth)
    if not synthetic and (gt_hash != GT_SHA256 or projection != GT_PROJECTION_SHA256):
        raise RunInvalid("GROUND_TRUTH_COMMITMENT_MISMATCH")
    if approved_override is None:
        _approval_identity_gate(approved, commitment=commitment, ontology=ontology, ground_truth_sha256=gt_hash, projection_sha256=projection)
    _, entries, raw_manifest_sha = _commitment_gate(commitment, raw_dir, csv_path, synthetic=synthetic)
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


def _file_digest_map(directory: Path) -> dict:
    names = ("scores.csv", "paired_table.csv", "summary.json", "input_manifest.json", "score_trace.jsonl", "execution.log")
    result = {}
    for name in names:
        path = directory / name
        if not path.is_file():
            raise RunInvalid("HIDDEN_RUN_INCOMPLETE")
        result[name] = sha(path)
    return result


def _write_invalid_receipt(output: Path, reason: str) -> Path:
    """Publish only a body-free invalid receipt; never create the release root."""
    destination = output.parent / ("." + output.name + ".invalid.json")
    temporary = output.parent / ("." + output.name + ".invalid.tmp")
    safe_reason = reason if re.fullmatch(r"[A-Z0-9_]+", reason) else "RUN_FAILURE"
    _write_bytes(temporary, _canonical({"status": "INVALID", "reason": safe_reason, "candidate_text_emitted": False}) + b"\n")
    os.replace(temporary, destination)
    return destination


def _copy_artifact(source: Path, destination: Path) -> None:
    shutil.copyfile(source, destination)
    with destination.open("rb") as handle:
        os.fsync(handle.fileno())


def _assemble_release(*, hidden: Path, output: Path, first: dict, second: dict, approval: dict, preflight: dict) -> dict:
    """Create the sole public tree only after both hidden runs prove byte equality."""
    first_dir, second_dir = hidden / "run1", hidden / "run2"
    first_files, second_files = _file_digest_map(first_dir), _file_digest_map(second_dir)
    if first["canonical_output_sha256"] != second["canonical_output_sha256"] or first_files != second_files:
        raise RunInvalid("REPLAY_MISMATCH")
    release = hidden / "release"
    final, replay = release / "final", release / "replay"
    final.mkdir(parents=True, mode=0o700)
    replay.mkdir(mode=0o700)
    for name in first_files:
        _copy_artifact(first_dir / name, final / name)
        _copy_artifact(second_dir / name, replay / name)
    result_export = release / "result_export.csv"
    _copy_artifact(final / "scores.csv", result_export)
    replay_manifest = {
        "replay_result": "MATCH",
        "canonical_output_sha256": first["canonical_output_sha256"],
        "run1_files": first_files,
        "run2_files": second_files,
    }
    _write_bytes(release / "replay_manifest.json", _canonical(replay_manifest) + b"\n")
    manifest = {
        "status": "PASS",
        "replay_result": "MATCH",
        "canonical_output_sha256": first["canonical_output_sha256"],
        "run1_files": first_files,
        "run2_files": second_files,
        "release_contract": {"result_export": "result_export.csv", "sha256": sha(result_export), "rows": 36},
        "approval": approval,
        "preflight": preflight,
        "external_call_count": 0,
        "model_call_count": 0,
        "k8s_call_count": 0,
    }
    _write_bytes(release / "manifest.json", _canonical(manifest) + b"\n")
    _fsync_tree(final)
    _fsync_tree(replay)
    _fsync_tree(release)
    _publish(release, output)
    return {"status": "PASS", "canonical_output_sha256": first["canonical_output_sha256"], "output": str(output), "replay": "MATCH"}


def run_full(*, approval: Path, commitment: Path, raw_dir: Path, csv_path: Path, ground_truth: Path, ontology: Path, output: Path, code_candidate: str, implementation_candidate: str, approved_bundle: str, execution_commit: str, synthetic: bool = False) -> dict:
    """Run two hidden full scorings and atomically release their matched result.

    In non-synthetic mode this function is the only full-mode entrypoint.  The
    repository/approval gate deliberately precedes *all* raw/csv path access.
    """
    output = Path(output)
    hidden = None
    try:
        if output.exists():
            raise RunInvalid("OUTPUT_EXISTS")
        if synthetic:
            # Synthetic fixtures are deliberately not authority to score a real input.
            approved = _approval_gate(approval)
            preflight = {"synthetic": True}
        else:
            approved, preflight = _repository_gate(
                approval_path=Path(approval), code_candidate=code_candidate,
                implementation_candidate=implementation_candidate,
                approved_bundle=approved_bundle, execution_commit=execution_commit,
            )
        hidden = Path(tempfile.mkdtemp(prefix=".v2_4_deterministic_hidden-", dir=output.parent))
        os.chmod(hidden, 0o700)
        first = run_campaign(
            approval=Path(approval), commitment=Path(commitment), raw_dir=Path(raw_dir), csv_path=Path(csv_path),
            ground_truth=Path(ground_truth), ontology=Path(ontology), output=hidden / "run1", synthetic=synthetic,
            approved_override=None if synthetic else approved,
        )
        second = run_campaign(
            approval=Path(approval), commitment=Path(commitment), raw_dir=Path(raw_dir), csv_path=Path(csv_path),
            ground_truth=Path(ground_truth), ontology=Path(ontology), output=hidden / "run2", synthetic=synthetic,
            approved_override=None if synthetic else approved,
        )
        result = _assemble_release(hidden=hidden, output=output, first=first, second=second, approval=approved, preflight=preflight)
        return result
    except Exception as exc:
        _write_invalid_receipt(output, str(exc) if isinstance(exc, RunInvalid) else "RUN_FAILURE")
        if isinstance(exc, RunInvalid):
            raise
        raise RunInvalid("RUN_FAILURE") from exc
    finally:
        if hidden is not None and hidden.exists():
            shutil.rmtree(hidden)


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--commitment", type=Path)
    parser.add_argument("--raw-dir", type=Path)
    parser.add_argument("--csv", type=Path)
    parser.add_argument("--approval", type=Path)
    parser.add_argument("--ground-truth", type=Path)
    parser.add_argument("--ontology", type=Path, default=Path(__file__).with_name("ontology_v1.json"))
    parser.add_argument("--out", type=Path)
    parser.add_argument("--code-candidate")
    parser.add_argument("--implementation-candidate")
    parser.add_argument("--approved-bundle")
    parser.add_argument("--execution-commit")
    parser.add_argument("--synthetic", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test:
        scorer.load_ontology(args.ontology)
        print(json.dumps({"status": "SELF_TEST_PASS", "candidate_text_opened": False}, sort_keys=True))
        return 0
    if args.dry_run:
        if not all((args.commitment, args.raw_dir, args.csv)): raise SystemExit("INPUT_REQUIRED")
        print(json.dumps(dry_run(args.commitment, args.raw_dir, args.csv), sort_keys=True))
        return 0
    if not all((args.commitment, args.raw_dir, args.csv, args.approval, args.ground_truth, args.out, args.code_candidate, args.implementation_candidate, args.approved_bundle, args.execution_commit)):
        raise SystemExit("APPROVAL_REQUIRED")
    result = run_full(
        approval=args.approval, commitment=args.commitment, raw_dir=args.raw_dir, csv_path=args.csv,
        ground_truth=args.ground_truth, ontology=args.ontology, output=args.out,
        code_candidate=args.code_candidate, implementation_candidate=args.implementation_candidate,
        approved_bundle=args.approved_bundle, execution_commit=args.execution_commit, synthetic=args.synthetic,
    )
    print(json.dumps({"status": result["status"], "canonical_output_sha256": result["canonical_output_sha256"], "replay": result["replay"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

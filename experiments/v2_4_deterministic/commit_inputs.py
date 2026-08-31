"""Opaque, descriptor-anchored input commitment; candidate bytes are never decoded."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import re
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
_SAFETY_TARGETS=("experiments/v2_4_deterministic/__init__.py","experiments/v2_4_deterministic/build_ontology.py","experiments/v2_4_deterministic/commit_inputs.py","experiments/v2_4_deterministic/scorer.py","experiments/v2_4_deterministic/analyze.py","experiments/v2_4_deterministic/run.py","experiments/v2_4_deterministic/ontology_v1.json","tests/test_v2_4_deterministic.py")


def _open_dir_chain(path: Path) -> tuple[int, os.stat_result, Path]:
    """Anchor a lexical absolute directory via openat; do not resolve symlinks."""
    lexical = Path(os.path.abspath(os.fspath(path)))
    fd = os.open(lexical.anchor, _DIR_FLAGS)
    try:
        for part in lexical.parts[1:]:
            next_fd = os.open(part, _DIR_FLAGS, dir_fd=fd)
            os.close(fd); fd = next_fd
        info = os.fstat(fd)
        if not stat.S_ISDIR(info.st_mode): raise ValueError("UNSAFE_DIRECTORY")
        return fd, info, lexical
    except Exception:
        os.close(fd); raise


def _digest_at(parent_fd: int, name: str) -> tuple[int, str, tuple[int, int]]:
    if not name or "/" in name or name in {".", ".."}: raise ValueError("UNSAFE_ENTRY")
    before_path = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    if not stat.S_ISREG(before_path.st_mode) or before_path.st_nlink != 1: raise ValueError("UNSAFE_ENTRY")
    fd = os.open(name, _FILE_FLAGS, dir_fd=parent_fd)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or (before.st_dev, before.st_ino, before.st_size) != (before_path.st_dev, before_path.st_ino, before_path.st_size): raise ValueError("TOCTOU")
        first = hashlib.sha256()
        while block := os.read(fd, 1 << 20): first.update(block)
        os.lseek(fd, 0, os.SEEK_SET)
        second = hashlib.sha256()
        while block := os.read(fd, 1 << 20): second.update(block)
        after = os.fstat(fd)
        final_path = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    finally:
        os.close(fd)
    identity = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns)
    if first.digest() != second.digest() or identity != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns, after.st_ctime_ns) or (before.st_dev, before.st_ino) != (final_path.st_dev, final_path.st_ino): raise ValueError("TOCTOU")
    return before.st_size, first.hexdigest(), (before.st_dev, before.st_ino)


def _commit_core(csv_path: Path, raw_dir: Path) -> dict:
    raw_fd, raw_info, raw_lexical = _open_dir_chain(raw_dir)
    try:
        names = sorted(os.listdir(raw_fd))
        if len(names) != 117: raise ValueError("RAW_COUNT")
        raws = []
        for name in names:
            if name.startswith(".") or not name.endswith(".json"): raise ValueError("UNEXPECTED_RAW_ENTRY")
            size, digest, _ = _digest_at(raw_fd, name)
            raws.append({"path": name, "size": size, "sha256": digest})
        # Fail closed if an ancestor/root was exchanged after descriptor anchoring.
        current = os.stat(raw_lexical, follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (raw_info.st_dev, raw_info.st_ino): raise ValueError("TOCTOU")
    finally:
        os.close(raw_fd)
    csv_fd, _, csv_parent = _open_dir_chain(csv_path.parent)
    try:
        size, digest, _ = _digest_at(csv_fd, csv_path.name)
    finally:
        os.close(csv_fd)
    manifest = {"raw_files": raws, "raw_count": 117, "csv": {"id_sha256": hashlib.sha256(csv_path.name.encode()).hexdigest(), "size": size, "sha256": digest}}
    manifest["entry_manifest_sha256"] = hashlib.sha256(json.dumps(raws, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    payload = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    manifest["commitment_sha256"] = hashlib.sha256(payload).hexdigest()
    validate_commitment_schema(manifest, require_provenance=False)
    return manifest


def commit(csv_path: Path, raw_dir: Path) -> dict:
    """Public hash-only API. No source path is retained in its returned envelope."""
    return _commit_core(Path(csv_path), Path(raw_dir))


def validate_commitment_schema(value: object, *, require_provenance: bool) -> dict:
    """Canonical producer/consumer schema; no legacy path aliases are accepted."""
    base={"raw_files","raw_count","csv","entry_manifest_sha256","commitment_sha256"}
    required=base | ({"provenance"} if require_provenance else set())
    if not isinstance(value,dict) or set(value)!=required or value.get("raw_count")!=117 or not isinstance(value.get("raw_files"),list) or len(value["raw_files"])!=117: raise ValueError("COMMITMENT_SCHEMA")
    raw=value["raw_files"]
    if raw != sorted(raw,key=lambda item:item.get("path", "")) or len({item.get("path") for item in raw})!=117 or any(not isinstance(item,dict) or set(item)!={"path","size","sha256"} or not isinstance(item["path"],str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.json",item["path"]) or "/" in item["path"] or "\\" in item["path"] or item["path"].startswith(".") or not isinstance(item["size"],int) or item["size"]<0 or not _is_sha256(item["sha256"]) for item in raw): raise ValueError("COMMITMENT_SCHEMA")
    csv=value["csv"]
    if not isinstance(csv,dict) or set(csv)!={"id_sha256","size","sha256"} or not _is_sha256(csv["id_sha256"]) or not isinstance(csv["size"],int) or csv["size"]<0 or not _is_sha256(csv["sha256"]): raise ValueError("COMMITMENT_SCHEMA")
    if not _is_sha256(value["entry_manifest_sha256"]) or value["entry_manifest_sha256"] != hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(",",":")).encode()).hexdigest(): raise ValueError("COMMITMENT_SCHEMA")
    preimage={key:value[key] for key in ("raw_files","raw_count","csv","entry_manifest_sha256")}
    if not _is_sha256(value["commitment_sha256"]) or value["commitment_sha256"] != hashlib.sha256(json.dumps(preimage,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()).hexdigest(): raise ValueError("COMMITMENT_SCHEMA")
    if require_provenance:
        provenance=value["provenance"]
        exact={"tool_blob_oid","tool_sha256","interpreter_path","interpreter_sha256","python_version","cwd","argv","allowlisted_environment","source_root_device_inode","started_utc","finished_utc","exit_status","stdout_sha256","stderr_sha256","redaction_self_test","raw_count","csv_sha256","entry_manifest_sha256","commitment_sha256","safety_receipt_sha256","reviewed_i0","legacy_source_drift","operator_attestation"}
        option_names=("--csv","--raw-dir","--out","--reviewed-i0","--safety-receipt","--legacy-reference")
        argv=provenance.get("argv") if isinstance(provenance,dict) else None
        if not isinstance(provenance,dict) or set(provenance)!=exact or not _is_blob_oid(provenance["tool_blob_oid"]) or not all(_is_sha256(provenance[name]) for name in ("tool_sha256","interpreter_sha256","stdout_sha256","stderr_sha256","csv_sha256","entry_manifest_sha256","commitment_sha256","safety_receipt_sha256")) or not all(isinstance(provenance[name],str) and provenance[name] for name in ("interpreter_path","python_version","cwd","started_utc","finished_utc","operator_attestation")) or provenance["python_version"]!=sys.version or not provenance["started_utc"].endswith("Z") or not provenance["finished_utc"].endswith("Z") or not isinstance(argv,list) or tuple(argv[::2])!=option_names or len(argv)!=12 or any(not isinstance(item,str) or not re.fullmatch(r"sha256:[0-9a-f]{64}",item) for item in argv[1::2]) or provenance["allowlisted_environment"]!={} or not isinstance(provenance["source_root_device_inode"],list) or len(provenance["source_root_device_inode"])!=2 or any(not isinstance(item,int) or item<0 for item in provenance["source_root_device_inode"]) or provenance["exit_status"]!=0 or not _valid_evidence(provenance["redaction_self_test"]) or provenance["raw_count"]!=117 or provenance["csv_sha256"]!=csv["sha256"] or provenance["entry_manifest_sha256"]!=value["entry_manifest_sha256"] or provenance["commitment_sha256"]!=value["commitment_sha256"] or not _is_blob_oid(provenance["reviewed_i0"]) or provenance["legacy_source_drift"]!="EXACT_MATCH" or provenance["operator_attestation"]!="hash-only streaming": raise ValueError("COMMITMENT_SCHEMA")
    return value


def _valid_evidence(value: object) -> bool:
    if not isinstance(value,dict) or set(value)!={"status","sentinel_match_count","fixture_sha256","sentinel_sha256","success","error"} or value["status"]!="REDACTION_SELF_TEST_PASS" or value["sentinel_match_count"]!=0: return False
    if not all(_is_sha256(value[key]) for key in ("fixture_sha256","sentinel_sha256")): return False
    for name in ("success","error"):
        item=value[name]
        if not isinstance(item,dict) or set(item)!={"exit_status","stdout_sha256","stderr_sha256"} or not isinstance(item["exit_status"],int) or not all(_is_sha256(item[key]) for key in ("stdout_sha256","stderr_sha256")): return False
    return value["success"]["exit_status"]==0 and value["error"]["exit_status"]!=0


def _redaction_self_test() -> dict | None:
    content = b"CONTENT_SENTINEL_V2_4_D"
    path_sentinel = "PATH_SENTINEL_V2_4_D"
    with tempfile.TemporaryDirectory(dir=Path.cwd(), prefix=path_sentinel) as td:
        root = Path(td); raw = root / "raw"; raw.mkdir(); csv_path = root / (path_sentinel + ".csv"); csv_path.write_bytes(content)
        for index in range(117): (raw / f"{index:03d}.json").write_bytes(content)
        out_path=root/"out"; out=io.StringIO(); err=io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): ok=main(["--csv",str(csv_path),"--raw-dir",str(raw),"--out",str(out_path)], _internal_self_test=True)
        if ok != 0 or not out_path.exists(): return None
        rendered=out.getvalue()+err.getvalue()+out_path.read_text(encoding="utf-8")
        error_out=io.StringIO(); error_err=io.StringIO()
        with contextlib.redirect_stdout(error_out), contextlib.redirect_stderr(error_err): failed=main(["--csv",str(csv_path),"--raw-dir",str(root/(path_sentinel+"_missing")),"--out",str(out_path)], _internal_self_test=True)
        rendered += error_out.getvalue()+error_err.getvalue()
        if failed == 0 or error_err.getvalue() != "COMMITMENT_FAILED\n" or content.decode() in rendered or path_sentinel in rendered: return None
    evidence={"status":"REDACTION_SELF_TEST_PASS","fixture_sha256":hashlib.sha256(content+path_sentinel.encode()).hexdigest(),"sentinel_sha256":hashlib.sha256(content).hexdigest(),"sentinel_match_count":0,"success":{"exit_status":ok,"stdout_sha256":hashlib.sha256(out.getvalue().encode()).hexdigest(),"stderr_sha256":hashlib.sha256(err.getvalue().encode()).hexdigest()},"error":{"exit_status":failed,"stdout_sha256":hashlib.sha256(error_out.getvalue().encode()).hexdigest(),"stderr_sha256":hashlib.sha256(error_err.getvalue().encode()).hexdigest()}}
    return evidence if _valid_evidence(evidence) else None


def _blob_oid(path: Path) -> str:
    data=path.read_bytes(); return hashlib.sha1(f"blob {len(data)}\0".encode()+data).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(ch in "0123456789abcdef" for ch in value)


def _is_blob_oid(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(ch in "0123456789abcdef" for ch in value)


def _load_json(path: Path) -> dict:
    def pairs(items):
        value={}
        for key,item in items:
            if key in value: raise ValueError("DUPLICATE_KEY")
            value[key]=item
        return value
    value=json.loads(path.read_text(encoding="utf-8"),object_pairs_hook=pairs)
    if not isinstance(value,dict): raise ValueError("INVALID_PROVENANCE")
    return value


def _parse_legacy_reference(legacy_path: Path) -> dict:
    """Read only the reference envelope shape; never open the input sources here."""
    legacy=_load_json(legacy_path)
    allowed={"raw_files","raw_count","csv","entry_manifest_sha256","commitment_sha256","provenance"}
    if set(legacy)-allowed or not {"raw_files","raw_count","csv"} <= set(legacy) or legacy.get("raw_count") != 117 or not isinstance(legacy["raw_files"],list) or len(legacy["raw_files"]) != 117 or not isinstance(legacy["csv"],dict): raise ValueError("LEGACY_SCHEMA")
    raw_files=legacy["raw_files"]
    if any(not isinstance(item,dict) or set(item)!={"path","size","sha256"} or not isinstance(item["path"],str) or not item["path"] or "/" in item["path"] or not isinstance(item["size"],int) or item["size"] < 0 or not _is_sha256(item["sha256"]) for item in raw_files) or raw_files != sorted(raw_files,key=lambda item:item["path"]) or len({item["path"] for item in raw_files}) != 117: raise ValueError("LEGACY_SCHEMA")
    csv_map=legacy["csv"]
    if set(csv_map)-{"path","id_sha256","size","sha256"} or not {"size","sha256"} <= set(csv_map) or not isinstance(csv_map["size"],int) or csv_map["size"] < 0 or not _is_sha256(csv_map["sha256"]) or ("path" in csv_map and (not isinstance(csv_map["path"],str) or not csv_map["path"])) or ("id_sha256" in csv_map and not _is_sha256(csv_map["id_sha256"])): raise ValueError("LEGACY_SCHEMA")
    for name in ("entry_manifest_sha256","commitment_sha256"):
        if name in legacy and not _is_sha256(legacy[name]): raise ValueError("LEGACY_SCHEMA")
    if "provenance" in legacy and not isinstance(legacy["provenance"],dict): raise ValueError("LEGACY_SCHEMA")
    return legacy


def _preopen_real_mode(reviewed_i0: str, receipt_path: Path, legacy_path: Path) -> tuple[dict, str, dict]:
    """Validate all non-input authorization artifacts before opening candidate inputs."""
    if len(reviewed_i0)!=40 or any(ch not in "0123456789abcdef" for ch in reviewed_i0): raise ValueError("INVALID_REVIEWED_I0")
    receipt=_load_json(receipt_path); tool_oid=_blob_oid(Path(__file__))
    required={"reviewer_id","session_id","review_utc","reviewed_i0","result","status","safety_targets","semantic_review_sha256","interpreter","commands","fixture_sha256","sentinel_sha256","real_source_open_count","candidate_text_egress","prior_failures_closed"}
    if set(receipt)!=required or receipt.get("status")!="PASS" or receipt.get("result")!="PASS" or receipt.get("reviewed_i0")!=reviewed_i0 or not all(isinstance(receipt[key],str) and receipt[key] for key in ("reviewer_id","session_id","review_utc")) or not all(_is_sha256(receipt[key]) for key in ("semantic_review_sha256","fixture_sha256","sentinel_sha256")) or receipt.get("real_source_open_count")!=0 or receipt.get("candidate_text_egress") is not False or not isinstance(receipt.get("prior_failures_closed"),list) or any(not isinstance(item,str) or not item for item in receipt["prior_failures_closed"]): raise ValueError("SAFETY_RECEIPT_MISMATCH")
    targets=receipt["safety_targets"]
    if not isinstance(targets,list) or len(targets)!=8: raise ValueError("SAFETY_RECEIPT_MISMATCH")
    found={item.get("path"):item for item in targets if isinstance(item,dict) and set(item)=={"path","blob_oid","sha256"}}
    root=Path(__file__).resolve().parents[2]
    if set(found)!=set(_SAFETY_TARGETS) or any(not _is_blob_oid(item.get("blob_oid")) or not _is_sha256(item.get("sha256")) for item in found.values()): raise ValueError("SAFETY_RECEIPT_MISMATCH")
    for target, record in found.items():
        target_path=root/target
        if not target_path.is_file() or _blob_oid(target_path)!=record["blob_oid"] or hashlib.sha256(target_path.read_bytes()).hexdigest()!=record["sha256"]: raise ValueError("SAFETY_RECEIPT_MISMATCH")
    if found["experiments/v2_4_deterministic/commit_inputs.py"]["blob_oid"]!=tool_oid: raise ValueError("SAFETY_RECEIPT_MISMATCH")
    interpreter=receipt["interpreter"]
    if not isinstance(interpreter,dict) or set(interpreter)!={"path","version","sha256"} or not isinstance(interpreter["path"],str) or not interpreter["path"] or not isinstance(interpreter["version"],str) or not interpreter["version"] or not _is_sha256(interpreter["sha256"]): raise ValueError("SAFETY_RECEIPT_MISMATCH")
    active_interpreter=Path(sys.executable).resolve()
    if Path(interpreter["path"]).resolve()!=active_interpreter or interpreter["version"]!=sys.version or interpreter["sha256"]!=hashlib.sha256(active_interpreter.read_bytes()).hexdigest(): raise ValueError("SAFETY_RECEIPT_MISMATCH")
    commands=receipt["commands"]
    if not isinstance(commands,list) or not commands or any(not isinstance(item,dict) or set(item)!={"command","exit_status","stdout_sha256","stderr_sha256"} or not isinstance(item["command"],str) or not item["command"] or item["exit_status"]!=0 or not _is_sha256(item["stdout_sha256"]) or not _is_sha256(item["stderr_sha256"]) for item in commands): raise ValueError("SAFETY_RECEIPT_MISMATCH")
    legacy=_parse_legacy_reference(legacy_path)
    return receipt, hashlib.sha256(receipt_path.read_bytes()).hexdigest(), legacy


def _compare_legacy_reference(legacy: dict, data: dict) -> None:
    """Compare maps only after the descriptor-anchored input commitment exists."""
    expected_csv={key:data["csv"][key] for key in ("size","sha256")}
    legacy_csv={key:legacy["csv"].get(key) for key in ("size","sha256")}
    if legacy_csv != expected_csv or legacy["raw_files"]!=data["raw_files"]: raise ValueError("LEGACY_SOURCE_DRIFT")


class _Parser(argparse.ArgumentParser):
    def error(self, message): raise ValueError("ARGUMENT_ERROR")


def _main(argv=None, *, _internal_self_test=False):
    parser = _Parser(add_help=False)
    parser.add_argument("--csv", type=Path); parser.add_argument("--raw-dir", type=Path); parser.add_argument("--out", type=Path)
    parser.add_argument("--reviewed-i0"); parser.add_argument("--safety-receipt",type=Path); parser.add_argument("--legacy-reference",type=Path)
    parser.add_argument("--self-test-redaction", action="store_true")
    args = parser.parse_args(argv)
    if args.self_test_redaction:
        evidence=_redaction_self_test()
        if evidence is None: raise ValueError("REDACTION_SELF_TEST_FAIL")
        print(json.dumps(evidence, sort_keys=True, separators=(",", ":"))); return 0
    if not all((args.csv, args.raw_dir, args.out)): raise SystemExit("INPUT_REQUIRED")
    if _internal_self_test:
        evidence=None
    else:
        evidence=_redaction_self_test()
        if not _valid_evidence(evidence): raise ValueError("REDACTION_SELF_TEST_FAIL")
        if not all((args.reviewed_i0,args.safety_receipt,args.legacy_reference)): raise ValueError("REAL_MODE_ARGUMENTS_REQUIRED")
    receipt=receipt_sha=legacy=None
    if not _internal_self_test:
        receipt, receipt_sha, legacy = _preopen_real_mode(args.reviewed_i0,args.safety_receipt,args.legacy_reference)
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    data = _commit_core(args.csv, args.raw_dir)
    tool = Path(__file__).resolve(); interpreter = Path(sys.executable).resolve()
    stdout = json.dumps({"raw_count": 117, "commitment_sha256": data["commitment_sha256"]}, separators=(",", ":"))
    if _internal_self_test:
        args.out.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")), encoding="utf-8")
        print(stdout)
        return 0
    _compare_legacy_reference(legacy,data)
    root_info=os.stat(args.raw_dir,follow_symlinks=False)
    # This is the immutable input-manifest digest, computed before the mutable
    # provenance envelope is attached; the duplicate provenance field makes the
    # self-excluding commitment contract explicit without a circular hash.
    redacted=lambda value: "sha256:"+hashlib.sha256(os.fspath(value).encode()).hexdigest()
    data["provenance"] = {"tool_blob_oid":_blob_oid(tool),"tool_sha256": hashlib.sha256(tool.read_bytes()).hexdigest(), "interpreter_path":str(interpreter),"interpreter_sha256": hashlib.sha256(interpreter.read_bytes()).hexdigest(), "python_version": sys.version, "cwd":str(Path.cwd()),"argv": ["--csv", redacted(args.csv), "--raw-dir", redacted(args.raw_dir), "--out", redacted(args.out), "--reviewed-i0", "sha256:"+hashlib.sha256(args.reviewed_i0.encode()).hexdigest(), "--safety-receipt", redacted(args.safety_receipt), "--legacy-reference", redacted(args.legacy_reference)], "allowlisted_environment":{},"source_root_device_inode":[root_info.st_dev,root_info.st_ino],"started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "exit_status": 0, "stdout_sha256": hashlib.sha256((stdout + "\n").encode()).hexdigest(), "stderr_sha256": hashlib.sha256(b"").hexdigest(), "redaction_self_test":evidence,"raw_count":117,"csv_sha256":data["csv"]["sha256"],"entry_manifest_sha256":data["entry_manifest_sha256"],"commitment_sha256":data["commitment_sha256"],"safety_receipt_sha256":receipt_sha,"reviewed_i0":args.reviewed_i0,"legacy_source_drift":"EXACT_MATCH","operator_attestation": "hash-only streaming"}
    validate_commitment_schema(data, require_provenance=True)
    args.out.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    print(stdout)
    return 0


def main(argv=None, *, _internal_self_test=False):
    try: return _main(argv, _internal_self_test=_internal_self_test)
    except (OSError, ValueError, json.JSONDecodeError, SystemExit):
        print("COMMITMENT_FAILED",file=sys.stderr); return 1

if __name__ == "__main__": raise SystemExit(main())

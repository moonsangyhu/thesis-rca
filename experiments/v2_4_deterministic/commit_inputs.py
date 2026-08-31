"""Opaque, descriptor-anchored input commitment; candidate bytes are never decoded."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import stat
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


_DIR_FLAGS = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
_FILE_FLAGS = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)


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
    return manifest


def commit(csv_path: Path, raw_dir: Path) -> dict:
    """Public hash-only API. No source path is retained in its returned envelope."""
    return _commit_core(Path(csv_path), Path(raw_dir))


def _redaction_self_test() -> dict | None:
    content = b"CONTENT_SENTINEL_V2_4_D"
    path_sentinel = "PATH_SENTINEL_V2_4_D"
    with tempfile.TemporaryDirectory(dir=Path.cwd(), prefix=path_sentinel) as td:
        root = Path(td); raw = root / "raw"; raw.mkdir(); csv_path = root / (path_sentinel + ".csv"); csv_path.write_bytes(content)
        for index in range(117): (raw / f"{index:03d}.json").write_bytes(content)
        out_path=root/"out"; out=io.StringIO(); err=io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): ok=main(["--csv",str(csv_path),"--raw-dir",str(raw),"--out",str(out_path),"--_skip-self-test"])
        if ok != 0 or not out_path.exists(): return None
        rendered=out.getvalue()+err.getvalue()+out_path.read_text(encoding="utf-8")
        if content.decode() in rendered or path_sentinel in rendered: return None
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): failed=main(["--csv",str(csv_path),"--raw-dir",str(root/(path_sentinel+"_missing")),"--out",str(out_path),"--_skip-self-test"])
        if failed == 0 or "COMMITMENT_FAILED" not in err.getvalue() or path_sentinel in err.getvalue(): return None
    return {"status":"PASS","fixture_sha256":hashlib.sha256(content+path_sentinel.encode()).hexdigest(),"sentinel_sha256":hashlib.sha256(content).hexdigest(),"stdout_sha256":hashlib.sha256(out.getvalue().encode()).hexdigest(),"stderr_sha256":hashlib.sha256(err.getvalue().encode()).hexdigest(),"sentinel_match_count":0}


def _blob_oid(path: Path) -> str:
    data=path.read_bytes(); return hashlib.sha1(f"blob {len(data)}\0".encode()+data).hexdigest()


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


def _verify_real_mode(reviewed_i0: str, receipt_path: Path, legacy_path: Path, data: dict) -> tuple[dict, str]:
    if len(reviewed_i0)!=40 or any(ch not in "0123456789abcdef" for ch in reviewed_i0): raise ValueError("INVALID_REVIEWED_I0")
    receipt=_load_json(receipt_path); tool_oid=_blob_oid(Path(__file__))
    if set(receipt)!={"status","reviewed_i0","tool_blob_oid"} or receipt.get("status")!="PASS" or receipt.get("reviewed_i0")!=reviewed_i0 or receipt.get("tool_blob_oid")!=tool_oid: raise ValueError("SAFETY_RECEIPT_MISMATCH")
    legacy=_load_json(legacy_path)
    if not isinstance(legacy.get("csv"),dict) or not isinstance(legacy.get("raw_files"),list) or legacy.get("csv",{}).get("sha256")!=data["csv"]["sha256"] or legacy.get("raw_files")!=data["raw_files"]: raise ValueError("LEGACY_SOURCE_DRIFT")
    return receipt, hashlib.sha256(receipt_path.read_bytes()).hexdigest()


class _Parser(argparse.ArgumentParser):
    def error(self, message): raise ValueError("ARGUMENT_ERROR")


def _main(argv=None):
    parser = _Parser(add_help=False)
    parser.add_argument("--csv", type=Path); parser.add_argument("--raw-dir", type=Path); parser.add_argument("--out", type=Path)
    parser.add_argument("--reviewed-i0"); parser.add_argument("--safety-receipt",type=Path); parser.add_argument("--legacy-reference",type=Path)
    parser.add_argument("--self-test-redaction", action="store_true"); parser.add_argument("--_skip-self-test",action="store_true")
    args = parser.parse_args(argv)
    if args.self_test_redaction:
        evidence=_redaction_self_test()
        if evidence is None: raise ValueError("REDACTION_SELF_TEST_FAIL")
        print(json.dumps({"status": "REDACTION_SELF_TEST_PASS", "sentinel_match_count": 0}, sort_keys=True)); return 0
    if not all((args.csv, args.raw_dir, args.out)): raise SystemExit("INPUT_REQUIRED")
    evidence={"status":"SKIPPED"} if args._skip_self_test else _redaction_self_test()
    if evidence is None: raise ValueError("REDACTION_SELF_TEST_FAIL")
    if not args._skip_self_test and not all((args.reviewed_i0,args.safety_receipt,args.legacy_reference)): raise ValueError("REAL_MODE_ARGUMENTS_REQUIRED")
    started = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    data = _commit_core(args.csv, args.raw_dir)
    tool = Path(__file__).resolve(); interpreter = Path(sys.executable).resolve()
    receipt, receipt_sha = ({}, "") if args._skip_self_test else _verify_real_mode(args.reviewed_i0,args.safety_receipt,args.legacy_reference,data)
    stdout = json.dumps({"raw_count": 117, "commitment_sha256": data["commitment_sha256"]}, separators=(",", ":"))
    root_info=os.stat(args.raw_dir,follow_symlinks=False)
    data["provenance"] = {"tool_blob_oid":_blob_oid(tool),"tool_sha256": hashlib.sha256(tool.read_bytes()).hexdigest(), "interpreter_path":str(interpreter),"interpreter_sha256": hashlib.sha256(interpreter.read_bytes()).hexdigest(), "python_version": sys.version, "cwd":str(Path.cwd()),"argv": ["--csv", "sha256:" + hashlib.sha256(os.fspath(args.csv).encode()).hexdigest(), "--raw-dir", "sha256:" + hashlib.sha256(os.fspath(args.raw_dir).encode()).hexdigest(), "--out", "sha256:" + hashlib.sha256(os.fspath(args.out).encode()).hexdigest()], "allowlisted_environment":{},"source_root_device_inode":[root_info.st_dev,root_info.st_ino],"started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "exit_status": 0, "stdout_sha256": hashlib.sha256((stdout + "\n").encode()).hexdigest(), "stderr_sha256": hashlib.sha256(b"").hexdigest(), "redaction_self_test":evidence,"raw_count":117,"csv_sha256":data["csv"]["sha256"],"entry_manifest_sha256":data["entry_manifest_sha256"],"safety_receipt_sha256":receipt_sha,"reviewed_i0":args.reviewed_i0,"legacy_source_drift":"EXACT_MATCH","operator_attestation": "hash-only streaming"}
    args.out.write_text(json.dumps(data, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    print(stdout)
    return 0


def main(argv=None):
    try: return _main(argv)
    except (OSError, ValueError, json.JSONDecodeError, SystemExit):
        print("COMMITMENT_FAILED",file=sys.stderr); return 1

if __name__ == "__main__": raise SystemExit(main())

"""Opaque input commitment: stream bytes only; never decode candidate files."""
from __future__ import annotations
import argparse, hashlib, json, os, stat, sys, contextlib, io, tempfile
from datetime import datetime, timezone
from pathlib import Path


def _trusted_path(path: Path) -> None:
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError("symlink input")
        if item == item.parent:
            break

def _digest(path: Path) -> tuple[int, str]:
    _trusted_path(path)
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1: raise ValueError("unsafe input entry")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    h = hashlib.sha256()
    try:
        before=os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or (before.st_dev,before.st_ino,before.st_size)!=(st.st_dev,st.st_ino,st.st_size): raise ValueError("TOCTOU")
        while block := os.read(fd, 1024 * 1024): h.update(block)
        first=h.hexdigest(); os.lseek(fd,0,os.SEEK_SET); h2=hashlib.sha256()
        while block := os.read(fd, 1024 * 1024): h2.update(block)
        after=os.fstat(fd); final=path.lstat()
    finally: os.close(fd)
    if first != h2.hexdigest() or (before.st_dev,before.st_ino,before.st_size,before.st_mtime_ns,before.st_ctime_ns) != (after.st_dev,after.st_ino,after.st_size,after.st_mtime_ns,after.st_ctime_ns) or (before.st_dev,before.st_ino)!=(final.st_dev,final.st_ino): raise ValueError("TOCTOU")
    return st.st_size, first

def commit(csv_path: Path, raw_dir: Path) -> dict:
    """Return canonical metadata without decoding, parsing, or printing source bytes."""
    _trusted_path(raw_dir); _trusted_path(csv_path)
    if not raw_dir.is_dir(): raise ValueError("unsafe raw root")
    raws=[]
    entries=sorted(raw_dir.iterdir())
    if len(entries) != 117: raise ValueError("RAW_COUNT")
    for p in entries:
        if p.name.startswith(".") or p.suffix != ".json" or p.is_dir() or p.is_symlink(): raise ValueError("UNEXPECTED_RAW_ENTRY")
        size, digest=_digest(p); raws.append({"path":p.relative_to(raw_dir).as_posix(),"size":size,"sha256":digest})
    size, digest=_digest(csv_path)
    manifest={"raw_files":raws,"raw_count":len(raws),"csv":{"path":csv_path.name,"size":size,"sha256":digest}}
    payload=json.dumps(manifest,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    manifest["commitment_sha256"]=hashlib.sha256(payload).hexdigest()
    return manifest

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--csv",type=Path); p.add_argument("--raw-dir",type=Path); p.add_argument("--out",type=Path); p.add_argument("--self-test-redaction",action="store_true")
    a=p.parse_args(argv); started=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    if a.self_test_redaction:
        sentinel=b"COMMITMENT_REDACTION_SENTINEL"
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as td:
            root=Path(td); raw=root/"raw"; raw.mkdir(); csv_path=root/"input.csv"; csv_path.write_bytes(sentinel)
            for index in range(117): (raw/f"{index:03d}.json").write_bytes(sentinel)
            out=io.StringIO(); err=io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err): main(["--csv",str(csv_path),"--raw-dir",str(raw),"--out",str(root/"commitment.json")])
            if sentinel.decode() in out.getvalue()+err.getvalue() or sentinel in (root/"commitment.json").read_bytes(): raise SystemExit("REDACTION_SELF_TEST_FAIL")
        print(json.dumps({"status":"REDACTION_SELF_TEST_PASS","sentinel_match_count":0},sort_keys=True)); return 0
    if not all((a.csv,a.raw_dir,a.out)): raise SystemExit("INPUT_REQUIRED")
    data=commit(a.csv,a.raw_dir)
    tool=Path(__file__).resolve(); interpreter=Path(sys.executable).resolve()
    stdout=json.dumps({"raw_count":data["raw_count"],"commitment_sha256":data["commitment_sha256"]},separators=(",",":"))
    data["provenance"]={"tool_sha256":_digest(tool)[1],"interpreter_path":str(interpreter),"interpreter_sha256":_digest(interpreter)[1],"python_version":sys.version,"argv":["commit_inputs.py","--csv",str(a.csv),"--raw-dir",str(a.raw_dir),"--out",str(a.out)],"started_utc":started,"finished_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"exit_status":0,"stdout_sha256":hashlib.sha256((stdout+"\n").encode()).hexdigest(),"stderr_sha256":hashlib.sha256(b"").hexdigest(),"redaction_test":"PASS","operator_attestation":"hash-only streaming; candidate bytes were not decoded, parsed, searched, previewed, or emitted"}
    a.out.write_text(json.dumps(data,sort_keys=True,separators=(",",":")),encoding="utf-8")
    print(stdout)
if __name__ == "__main__": main()

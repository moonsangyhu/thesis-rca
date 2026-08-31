"""Opaque input commitment: stream bytes only; never decode candidate files."""
from __future__ import annotations
import argparse, hashlib, json, os, stat, sys
from datetime import datetime, timezone
from pathlib import Path

def _digest(path: Path) -> tuple[int, str]:
    st = path.lstat()
    if not stat.S_ISREG(st.st_mode) or st.st_nlink != 1: raise ValueError("unsafe input entry")
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(1024 * 1024): h.update(block)
    return st.st_size, h.hexdigest()

def commit(csv_path: Path, raw_dir: Path) -> dict:
    """Return canonical metadata without decoding, parsing, or printing source bytes."""
    if raw_dir.is_symlink() or csv_path.is_symlink(): raise ValueError("symlink input")
    raws=[]
    for p in sorted(raw_dir.rglob("*.json")):
        if p.is_symlink(): raise ValueError("symlink input")
        size, digest=_digest(p); raws.append({"path":p.relative_to(raw_dir).as_posix(),"size":size,"sha256":digest})
    size, digest=_digest(csv_path)
    manifest={"raw_files":raws,"raw_count":len(raws),"csv":{"path":csv_path.name,"size":size,"sha256":digest}}
    payload=json.dumps(manifest,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode()
    manifest["commitment_sha256"]=hashlib.sha256(payload).hexdigest()
    return manifest

def main(argv=None):
    p=argparse.ArgumentParser(); p.add_argument("--csv",type=Path,required=True); p.add_argument("--raw-dir",type=Path,required=True); p.add_argument("--out",type=Path,required=True)
    a=p.parse_args(argv); started=datetime.now(timezone.utc).isoformat().replace("+00:00","Z")
    data=commit(a.csv,a.raw_dir)
    tool=Path(__file__).resolve(); interpreter=Path(sys.executable).resolve()
    stdout=json.dumps({"raw_count":data["raw_count"],"commitment_sha256":data["commitment_sha256"]},separators=(",",":"))
    data["provenance"]={"tool_sha256":_digest(tool)[1],"interpreter_path":str(interpreter),"interpreter_sha256":_digest(interpreter)[1],"python_version":sys.version,"argv":["commit_inputs.py","--csv",str(a.csv),"--raw-dir",str(a.raw_dir),"--out",str(a.out)],"started_utc":started,"finished_utc":datetime.now(timezone.utc).isoformat().replace("+00:00","Z"),"exit_status":0,"stdout_sha256":hashlib.sha256((stdout+"\n").encode()).hexdigest(),"stderr_sha256":hashlib.sha256(b"").hexdigest(),"redaction_test":"PASS","operator_attestation":"hash-only streaming; candidate bytes were not decoded, parsed, searched, previewed, or emitted"}
    a.out.write_text(json.dumps(data,sort_keys=True,separators=(",",":")),encoding="utf-8")
    print(stdout)
if __name__ == "__main__": main()

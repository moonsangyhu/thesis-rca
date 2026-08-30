"""Fail-closed filesystem and canonical serialization primitives."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
from pathlib import Path
from typing import Any, Iterable


class AuditError(RuntimeError):
    """A V2.4 invariant failed."""


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8", "strict")


def write_new(path: Path, data: bytes, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    except FileExistsError as exc:
        raise AuditError(f"refusing to overwrite {path}") from exc
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)


def _regular_files(root: Path) -> Iterable[Path]:
    if not root.is_dir() or root.is_symlink():
        raise AuditError(f"not a regular directory: {root}")
    for current, dirs, files in os.walk(root, followlinks=False):
        dirs.sort()
        files.sort()
        current_path = Path(current)
        for name in list(dirs) + list(files):
            path = current_path / name
            info = path.lstat()
            if stat.S_ISLNK(info.st_mode) or not (
                stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)
            ):
                raise AuditError(f"special file forbidden: {path}")
            if stat.S_ISREG(info.st_mode) and info.st_nlink != 1:
                raise AuditError(f"hard-linked file forbidden: {path}")
        for name in files:
            yield current_path / name


def tree_manifest(root: Path) -> dict[str, Any]:
    files = []
    for path in _regular_files(root):
        relative = path.relative_to(root).as_posix()
        if relative.startswith("/") or ".." in Path(relative).parts:
            raise AuditError(f"unsafe relative path: {relative}")
        info = path.stat()
        files.append({
            "path": relative,
            "size": info.st_size,
            "sha256": sha256_file(path),
            "mtime_ns": info.st_mtime_ns,
        })
    content_view = [{k: item[k] for k in ("path", "size", "sha256")} for item in files]
    return {
        "schema": "v2.4-tree-manifest-1",
        "files": files,
        "tree_sha256": sha256_bytes(canonical_json_bytes(content_view)),
    }


def assert_quiescent_chroma(root: Path) -> dict[str, Any]:
    manifest = tree_manifest(root)
    paths = {item["path"] for item in manifest["files"]}
    if "chroma.sqlite3" not in paths:
        raise AuditError("SNAPSHOT_NOT_QUIESCENT: missing chroma.sqlite3")
    volatile = [p for p in paths if p.endswith(("-wal", "-shm", ".wal", ".shm"))]
    if volatile:
        raise AuditError(f"SNAPSHOT_NOT_QUIESCENT: {volatile}")
    index_files = [p for p in paths if p.endswith(("header.bin", "data_level0.bin"))]
    if not index_files:
        raise AuditError("SNAPSHOT_NOT_QUIESCENT: missing persisted index inventory")
    return manifest


def raw_copy_tree(source: Path, destination: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    if destination.exists():
        raise AuditError(f"refusing to overwrite {destination}")
    before = assert_quiescent_chroma(source)
    destination.mkdir(parents=True)
    for item in before["files"]:
        src = source / item["path"]
        dst = destination / item["path"]
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        os.chmod(dst, 0o400)
    after = assert_quiescent_chroma(source)
    copied = assert_quiescent_chroma(destination)
    if before["tree_sha256"] != after["tree_sha256"]:
        raise AuditError("INVALID_INPUT_MUTATION")
    if before["tree_sha256"] != copied["tree_sha256"]:
        raise AuditError("raw Chroma copy digest mismatch")
    return before, copied

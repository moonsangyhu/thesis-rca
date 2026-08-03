"""Canonical campaign manifest validation and sealing."""

from __future__ import annotations

import hashlib
import json
import os
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import ManifestValidationError
from .io import atomic_write_bytes

_CAMPAIGN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,63}$")
_COMMIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_PROFILE = re.compile(r"^[a-z][a-z0-9_-]{1,63}$")
_THREAD_TS = re.compile(r"^[0-9]+\.[0-9]+$")
_ALLOWED_FAULTS = {f"F{i}" for i in range(1, 13)}
_FIELDS = {
    "schema_version",
    "campaign_id",
    "source_commit",
    "model",
    "faults",
    "trials",
    "timeout_seconds",
    "runner_profile",
    "restore_profile",
    "credential_profile",
    "expected_rows",
    "expected_raw_files",
    "thread_ts",
}


def canonical_bytes(value: dict[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8") + b"\n"


@dataclass(frozen=True)
class CampaignManifest:
    data: dict[str, Any]

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "CampaignManifest":
        if not isinstance(value, dict):
            raise ManifestValidationError("manifest must be a JSON object")
        unknown = set(value) - _FIELDS
        missing = _FIELDS - set(value)
        if unknown:
            raise ManifestValidationError(f"unknown manifest fields: {sorted(unknown)}")
        if missing:
            raise ManifestValidationError(f"missing manifest fields: {sorted(missing)}")
        if value["schema_version"] != 1:
            raise ManifestValidationError("schema_version must be 1")
        if not _CAMPAIGN_ID.fullmatch(str(value["campaign_id"])):
            raise ManifestValidationError("invalid campaign_id")
        if not _COMMIT_SHA.fullmatch(str(value["source_commit"])):
            raise ManifestValidationError("source_commit must be a lowercase 40-char SHA")
        if value["model"] != "gpt-4o-mini":
            raise ManifestValidationError("model must be gpt-4o-mini")
        faults = value["faults"]
        if not isinstance(faults, list) or not faults or len(faults) != len(set(faults)):
            raise ManifestValidationError("faults must be a non-empty unique list")
        if not set(faults) <= _ALLOWED_FAULTS:
            raise ManifestValidationError("faults contain an unsupported fault ID")
        trials = value["trials"]
        if (
            not isinstance(trials, list)
            or not trials
            or any(type(item) is not int or not 1 <= item <= 20 for item in trials)
            or len(trials) != len(set(trials))
        ):
            raise ManifestValidationError("trials must be unique integers in 1..20")
        if type(value["timeout_seconds"]) is not int or not 60 <= value["timeout_seconds"] <= 86400:
            raise ManifestValidationError("timeout_seconds must be in 60..86400")
        for key in ("runner_profile", "restore_profile", "credential_profile"):
            if not _PROFILE.fullmatch(str(value[key])):
                raise ManifestValidationError(f"invalid {key}")
        for key in ("expected_rows", "expected_raw_files"):
            if type(value[key]) is not int or value[key] < 0:
                raise ManifestValidationError(f"{key} must be a non-negative integer")
        if not _THREAD_TS.fullmatch(str(value["thread_ts"])):
            raise ManifestValidationError("invalid thread_ts")
        return cls(deepcopy(value))

    @property
    def campaign_id(self) -> str:
        return self.data["campaign_id"]

    @property
    def source_commit(self) -> str:
        return self.data["source_commit"]

    @property
    def sha256(self) -> str:
        return hashlib.sha256(canonical_bytes(self.data)).hexdigest()

    def seal_to(self, path: Path) -> None:
        if path.exists():
            existing = path.read_bytes()
            if existing != canonical_bytes(self.data):
                raise ManifestValidationError("sealed manifest already exists with different content")
            if path.stat().st_mode & 0o222:
                raise ManifestValidationError("sealed manifest is unexpectedly writable")
            return
        atomic_write_bytes(path, canonical_bytes(self.data), mode=0o400)
        os.chmod(path, 0o400)

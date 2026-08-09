"""Offline builder for a V2.3 zero-overage evidence manifest.

This module hashes user-reviewed administrator exports.  It does not infer the
meaning of an image, contact GitHub, invoke Copilot, or access the cluster.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from datetime import datetime, timezone
from pathlib import Path

from .authorization import AUTH_SCHEMA, BillingEvidence


class EvidencePreparationError(RuntimeError):
    pass


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _is_within_project(path: Path) -> bool:
    resolved = path.resolve()
    return resolved == PROJECT_ROOT or PROJECT_ROOT in resolved.parents


def _artifact(path: Path, kind: str) -> dict:
    provided = Path(path)
    if provided.is_symlink():
        raise EvidencePreparationError("evidence artifacts must not be symlinks")
    try:
        resolved = provided.resolve(strict=True)
    except OSError as exc:
        raise EvidencePreparationError(f"evidence artifact is missing: {kind}") from exc
    if not resolved.is_file():
        raise EvidencePreparationError(f"evidence artifact is not a file: {kind}")
    if _is_within_project(resolved):
        raise EvidencePreparationError("billing evidence must remain outside the repository")
    return {
        "kind": kind,
        "path": str(resolved),
        "sha256": hashlib.sha256(resolved.read_bytes()).hexdigest(),
    }


def prepare_manifest(
    *,
    paid_usage_disabled_path: Path,
    budget_hard_stop_path: Path,
    included_aic_balance_path: Path,
    account_scope: str,
    confirmed_by: str,
    included_aic_balance: float,
    output_path: Path,
    confirmed_reviewed: bool,
    confirmation_method: str = "manual-admin-console-review",
    now: datetime | None = None,
) -> dict:
    if confirmed_reviewed is not True:
        raise EvidencePreparationError("manual review confirmation is required")
    if not account_scope.strip() or not confirmed_by.strip() or not confirmation_method.strip():
        raise EvidencePreparationError("account scope, reviewer, and method are required")
    if (
        isinstance(included_aic_balance, bool)
        or not isinstance(included_aic_balance, (int, float))
        or not math.isfinite(included_aic_balance)
        or included_aic_balance <= 0
    ):
        raise EvidencePreparationError("included AIC balance must be a positive number")

    artifacts = [
        _artifact(paid_usage_disabled_path, "paid_usage_disabled"),
        _artifact(budget_hard_stop_path, "budget_hard_stop"),
        _artifact(included_aic_balance_path, "included_aic_balance"),
    ]
    artifact_paths = [item["path"] for item in artifacts]
    artifact_hashes = [item["sha256"] for item in artifacts]
    if len(set(artifact_paths)) != 3 or len(set(artifact_hashes)) != 3:
        raise EvidencePreparationError("three distinct evidence artifacts are required")

    output = Path(output_path)
    if output.is_symlink() or output.exists():
        raise EvidencePreparationError("manifest output already exists or is a symlink")
    resolved_output = output.resolve()
    if _is_within_project(resolved_output):
        raise EvidencePreparationError("billing manifest must remain outside the repository")
    if not resolved_output.parent.is_dir():
        raise EvidencePreparationError("manifest parent directory does not exist")

    observed = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    payload = {
        "schema_version": AUTH_SCHEMA,
        "account_scope": account_scope.strip(),
        "confirmed_at": observed.isoformat(),
        "confirmed_by": confirmed_by.strip(),
        "confirmation_method": confirmation_method.strip(),
        "paid_usage_disabled": True,
        "budget_hard_stop_enabled": True,
        "included_aic_balance": float(included_aic_balance),
        "balance_observed_at": observed.isoformat(),
        "evidence_files": artifacts,
    }
    with resolved_output.open("x") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    resolved_output.chmod(0o600)
    verified = BillingEvidence.load(resolved_output, now=observed)
    return {
        "manifest_path": verified.manifest_path,
        "account_scope": verified.account_scope,
        "included_aic_balance": verified.included_aic_balance,
        "evidence_sha256": list(verified.evidence_sha256),
        "manual_content_review": "required-and-asserted",
        "external_calls": 0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build an offline V2.3 zero-overage evidence manifest"
    )
    parser.add_argument("--paid-usage-disabled", required=True, type=Path)
    parser.add_argument("--budget-hard-stop", required=True, type=Path)
    parser.add_argument("--included-aic-balance", required=True, type=Path)
    parser.add_argument("--included-aic-balance-value", required=True, type=float)
    parser.add_argument("--account-scope", required=True)
    parser.add_argument("--confirmed-by", required=True)
    parser.add_argument(
        "--confirmation-method", default="manual-admin-console-review"
    )
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument(
        "--confirm-reviewed",
        required=True,
        action="store_true",
        help="assert that the three files visibly prove their declared settings",
    )
    args = parser.parse_args(argv)
    summary = prepare_manifest(
        paid_usage_disabled_path=args.paid_usage_disabled,
        budget_hard_stop_path=args.budget_hard_stop,
        included_aic_balance_path=args.included_aic_balance,
        account_scope=args.account_scope,
        confirmed_by=args.confirmed_by,
        included_aic_balance=args.included_aic_balance_value,
        output_path=args.output,
        confirmed_reviewed=args.confirm_reviewed,
        confirmation_method=args.confirmation_method,
    )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

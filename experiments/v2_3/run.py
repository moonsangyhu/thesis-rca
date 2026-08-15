#!/usr/bin/env python3
"""V2.3 offline harness and externally gated one-incident pilot entrypoint.

No import in this module initializes Copilot, Kubernetes, Prometheus, or Loki.
Live imports occur only after sealed user/billing authorization gates pass.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import signal
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .mock import run_dry_run, run_mock_campaign
from .authorization import LiveAuthorization, PAID_OVERAGE_MODE
from .config import (
    COPILOT_ACCOUNT_LOGIN, COPILOT_SESSION_MAX_AIC, FLUX_RECONCILIATION_POLICY, PILOT_FAULT_ID,
    PILOT_MANIFEST_SCHEMA, PILOT_TRIAL,
)


class RealExecutionDisabled(RuntimeError):
    pass


def _pilot_identity() -> dict:
    return {"fault_id": PILOT_FAULT_ID, "trial": PILOT_TRIAL}


def _pilot_budget_manifest_fields(max_campaign_aic: float) -> dict:
    return {
        "schema_version": PILOT_MANIFEST_SCHEMA,
        "max_campaign_aic": max_campaign_aic,
        "copilot_session_max_aic": COPILOT_SESSION_MAX_AIC,
        "flux_reconciliation_policy": FLUX_RECONCILIATION_POLICY,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="V2.3 offline review harness")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mock", action="store_true", help="run all 180 mock rows")
    mode.add_argument("--dry-run", action="store_true", help="alias for offline mock validation")
    mode.add_argument(
        "--pilot", action="store_true",
        help=f"authorized {PILOT_FAULT_ID} trial {PILOT_TRIAL} live pilot",
    )
    mode.add_argument(
        "--main", action="store_true",
        help="authorized F1-F12 x five-trial V2.3 primary campaign",
    )
    parser.add_argument("--output-dir", type=Path, help="explicit non-results output directory")
    parser.add_argument(
        "--approve-real", action="store_true",
        help="reserved follow-up approval marker; live path is still disabled",
    )
    parser.add_argument("--billing-evidence", type=Path)
    parser.add_argument(
        "--allow-paid-overage", action="store_true",
        help="record explicit user authorization for metered Copilot usage",
    )
    parser.add_argument("--approval-id")
    parser.add_argument("--campaign-id")
    parser.add_argument("--max-campaign-aic", type=float, default=360.0)
    parser.add_argument("--chroma-dir", type=Path)
    args = parser.parse_args(argv)
    if args.pilot or args.main:
        if args.output_dir is not None or args.approve_real:
            parser.error("live modes do not accept --output-dir or --approve-real")
        if not args.approval_id or not args.campaign_id or not args.chroma_dir:
            parser.error(
                "live modes require --approval-id, --campaign-id, and --chroma-dir"
            )
        if bool(args.billing_evidence) == bool(args.allow_paid_overage):
            parser.error(
                "live modes require exactly one of --billing-evidence or "
                "--allow-paid-overage"
            )
        if args.main and not args.allow_paid_overage:
            parser.error("--main requires --allow-paid-overage")
        if re.fullmatch(r"[A-Za-z0-9_.-]{8,128}", args.campaign_id) is None:
            parser.error("--campaign-id is invalid")
        if args.allow_paid_overage:
            authorization = LiveAuthorization.require_paid_overage(
                approval_id=args.approval_id
            )
        else:
            authorization = LiveAuthorization.require(
                args.billing_evidence, approval_id=args.approval_id
            )
        if args.main:
            from .main_campaign import run_authorized_main
            summary = run_authorized_main(
                authorization, campaign_id=args.campaign_id,
                chroma_dir=args.chroma_dir,
            )
        else:
            summary = _run_authorized_pilot(
                authorization,
                campaign_id=args.campaign_id,
                max_campaign_aic=args.max_campaign_aic,
                chroma_dir=args.chroma_dir,
            )
        print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        return 0
    if not (args.mock or args.dry_run):
        approval = " present" if args.approve_real else " absent"
        raise RealExecutionDisabled(
            f"V2.3 real execution is disabled (follow-up approval flag{approval})"
        )
    if any((
        args.billing_evidence, args.allow_paid_overage, args.approval_id,
        args.campaign_id, args.chroma_dir,
    )):
        parser.error("live authorization arguments are valid only with --pilot")
    if args.dry_run:
        if args.output_dir is not None:
            parser.error("--dry-run is in-memory and does not accept --output-dir")
        summary = run_dry_run()
    else:
        summary = run_mock_campaign(args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _run_cli_version_probe(
    executable: str, *, timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    process = subprocess.Popen(
        [executable, "--version"], text=True,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    return subprocess.CompletedProcess(
        [executable, "--version"], process.returncode,
        stdout=stdout, stderr=stderr,
    )


def _probe_cli_version(
    executable: str, *, timeout_seconds: int = 60, timeout_retries: int = 1
) -> str:
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or timeout_seconds < 1
    ):
        raise ValueError("CLI version timeout must be a positive integer")
    if (
        isinstance(timeout_retries, bool)
        or not isinstance(timeout_retries, int)
        or timeout_retries not in (0, 1)
    ):
        raise ValueError("CLI version timeout retries must be zero or one")
    completed = None
    for attempt in range(timeout_retries + 1):
        try:
            completed = _run_cli_version_probe(
                executable, timeout_seconds=timeout_seconds
            )
            break
        except subprocess.TimeoutExpired as exc:
            if attempt == timeout_retries:
                raise RuntimeError(
                    "Copilot CLI version probe timed out before inference"
                ) from exc
        except Exception as exc:
            raise RuntimeError(
                "Copilot CLI version probe failed before inference"
            ) from exc
    if completed is None:
        raise RuntimeError("Copilot CLI version probe did not complete")
    version = (completed.stdout or completed.stderr).strip().splitlines()
    if completed.returncode != 0 or not version:
        raise RuntimeError("Copilot CLI version probe failed")
    return version[0][:200]


def _local_cli_build_identity(executable: str) -> str:
    """Bind the installed loader/native package without executing the CLI."""
    try:
        loader = Path(executable).resolve(strict=True)
        loader_package = json.loads((loader.parent / "package.json").read_text())
        native_packages = sorted(
            loader.parent.glob("node_modules/@github/copilot-*/package.json")
        )
        if len(native_packages) != 1:
            raise RuntimeError("native Copilot package is unavailable or ambiguous")
        native_path = native_packages[0]
        native_package = json.loads(native_path.read_text())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Copilot package provenance is unavailable") from exc
    if loader.name != "npm-loader.js" or not loader.is_file():
        raise RuntimeError("Copilot loader identity is invalid")
    for payload in (loader_package, native_package):
        if not isinstance(payload, dict):
            raise RuntimeError("Copilot package provenance is invalid")
        if not isinstance(payload.get("version"), str) or not re.fullmatch(
            r"\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", payload["version"]
        ):
            raise RuntimeError("Copilot package version is invalid")
    if loader_package.get("name") != "@github/copilot" or not re.fullmatch(
        r"@github/copilot-[a-z0-9-]+", str(native_package.get("name"))
    ):
        raise RuntimeError("Copilot package identity is invalid")
    if native_package["name"] != f"@github/{native_path.parent.name}":
        raise RuntimeError("Copilot native package locator is invalid")
    if loader_package["version"] != native_package["version"]:
        raise RuntimeError("Copilot package versions are inconsistent")
    bins = native_package.get("bin")
    if not isinstance(bins, dict) or len(bins) != 1:
        raise RuntimeError("Copilot native binary mapping is invalid")
    binary_name, relative_binary = next(iter(bins.items()))
    if binary_name != native_package["name"].removeprefix("@github/"):
        raise RuntimeError("Copilot native binary mapping is invalid")
    if not isinstance(relative_binary, str) or Path(relative_binary).is_absolute():
        raise RuntimeError("Copilot native binary mapping is invalid")
    try:
        binary = (native_path.parent / relative_binary).resolve(strict=True)
        if native_path.parent.resolve() not in binary.parents or not binary.is_file():
            raise RuntimeError("Copilot native binary path is invalid")
        native_hash = hashlib.sha256(binary.read_bytes()).hexdigest()
    except OSError as exc:
        raise RuntimeError("Copilot native binary provenance is unavailable") from exc
    return (
        f"{loader_package['name']}@{loader_package['version']};"
        f"{native_package['name']}@{native_package['version']};"
        f"native-sha256={native_hash}"
    )


def _verified_git_revision(project_root: Path) -> str:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=project_root,
        text=True, capture_output=True, timeout=15, check=False,
    )
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        cwd=project_root, text=True, capture_output=True, timeout=15, check=False,
    )
    revision = head.stdout.strip()
    if head.returncode != 0 or not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError("experiment git revision is unavailable")
    if status.returncode != 0 or status.stdout.strip():
        raise RuntimeError("experiment worktree must be clean before live execution")
    return revision


def _run_authorized_pilot(
    authorization: LiveAuthorization,
    *,
    campaign_id: str,
    max_campaign_aic: float,
    chroma_dir: Path,
) -> dict:
    """Lazy-import every external dependency only after authorization."""
    authorization.revalidate()
    project_root = Path(__file__).resolve().parents[2]
    git_revision = _verified_git_revision(project_root)
    output_dir = project_root / "artifacts" / "v2_3_pilot" / campaign_id

    from experiments.shared.copilot_sdk import CopilotSDKBackend
    from experiments.shared.copilot_quota import inspect_copilot_quota

    paid_overage_authorized = authorization.billing_mode == PAID_OVERAGE_MODE

    backend = CopilotSDKBackend(
        model="gpt-5.6-terra",
        max_ai_credits=COPILOT_SESSION_MAX_AIC,
        billing_execution_authorized=True,
    )
    def quota_check():
        return inspect_copilot_quota(
            backend.executable,
            expected_login=COPILOT_ACCOUNT_LOGIN,
            required_remaining_aic=(
                0 if paid_overage_authorized
                else max_campaign_aic + COPILOT_SESSION_MAX_AIC
            ),
            allow_paid_overage=paid_overage_authorized,
        )

    quota = quota_check()
    backend.pre_call_guard = quota_check

    from experiments.shared.csv_io import load_ground_truth
    from experiments.shared.infra import preflight_check
    from scripts.fault_inject import FaultInjector
    from scripts.fault_inject.base import kubectl_get_json
    from scripts.stabilize import Recovery
    from scripts.stabilize.state_validator import StateValidator
    from src.collector import SignalCollector
    from src.rag.config import DEBUGGING_DIR, KNOWN_ISSUES_DIR, RUNBOOKS_DIR

    # Retrieval must be reproducible and must not download a model during a run.
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    resolved_chroma = Path(chroma_dir).resolve(strict=True)
    if not resolved_chroma.is_dir():
        raise RuntimeError("--chroma-dir must be an existing directory")
    from src.rag.retriever import KnowledgeRetriever

    from .engine import RCAEngineV2_3
    from .ledger import CallLedger
    from .live_caller import AuthorizedTerraCaller
    from .live_runner import (
        AttemptJournal, ChargedCallJournal, F7InjectionValidator,
        PilotIncidentRunner, PilotOutputStore, RuntimeOnlyRetriever, snapshot_tree,
    )
    from .flux_restore import build_live_flux_guard

    store = PilotOutputStore(output_dir)
    charged_journal = ChargedCallJournal(output_dir / "charged_call_ledger.jsonl")
    backend.charge_observer = charged_journal.append
    cli_version = _probe_cli_version(backend.executable)
    corpus_version = snapshot_tree(
        (DEBUGGING_DIR, RUNBOOKS_DIR, KNOWN_ISSUES_DIR, resolved_chroma)
    )
    billing_fields = {
        "billing_authorization_mode": authorization.billing_mode,
        "approval_id": authorization.approval_id,
    }
    if authorization.evidence is not None:
        billing_fields.update({
            "account_scope": authorization.evidence.account_scope,
            "billing_confirmed_at": authorization.evidence.confirmed_at,
            "billing_confirmed_by": authorization.evidence.confirmed_by,
            "billing_confirmation_method": authorization.evidence.confirmation_method,
            "billing_evidence_sha256": authorization.evidence.evidence_sha256,
            "included_aic_balance_before": authorization.evidence.included_aic_balance,
            "aic_balance_observed_at": authorization.evidence.balance_observed_at,
        })
    else:
        billing_fields.update({
            "account_scope": f"github:{quota.login}",
            "billing_confirmed_at": quota.observed_at,
            "billing_confirmed_by": "user",
            "billing_confirmation_method": "explicit-paid-overage-authorization",
            "billing_evidence_sha256": (),
            "included_aic_balance_before": quota.remaining_aic,
            "aic_balance_observed_at": quota.observed_at,
        })
    manifest = {
        **_pilot_budget_manifest_fields(max_campaign_aic),
        "campaign_id": campaign_id,
        "git_commit": git_revision,
        "git_worktree_clean_at_start": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **billing_fields,
        "server_quota": quota.to_dict(),
        "model": "gpt-5.6-terra",
        "copilot_backend": "official-sdk-empty",
        "copilot_sdk_sha256": backend.sdk_sha256,
        "copilot_sdk_runner_sha256": backend.runner_sha256,
        **_pilot_identity(),
        "expected_rows": 3,
        "expected_calls": 36,
        "corpus_version": corpus_version,
        "cli_version": cli_version,
    }
    store.write_manifest(manifest)
    store.append_event("authorization_verified")
    if not preflight_check():
        store.append_event("preflight_failed")
        raise RuntimeError("cluster preflight failed")
    store.append_event("preflight_green")

    ground_truth = load_ground_truth(project_root / "results" / "ground_truth.csv")
    gt_row = ground_truth.get((PILOT_FAULT_ID, PILOT_TRIAL))
    if gt_row is None:
        raise RuntimeError(
            f"{PILOT_FAULT_ID} trial {PILOT_TRIAL} ground truth is missing"
        )
    journal = AttemptJournal(output_dir / "attempt_call_ledger.jsonl")
    caller = AuthorizedTerraCaller(
        authorization=authorization,
        backend=backend,
        campaign_id=campaign_id,
        cli_version=cli_version,
        max_campaign_aic=max_campaign_aic,
    )
    engine = RCAEngineV2_3(
        caller,
        ledger=CallLedger(on_append=journal.append),
        campaign_id=campaign_id,
    )
    runner = PilotIncidentRunner(
        authorization=authorization,
        engine=engine,
        injector=FaultInjector(),
        recovery=Recovery(),
        collector=SignalCollector(),
        validator=StateValidator(ground_truth=ground_truth),
        injection_validator=F7InjectionValidator(
            lambda target: kubectl_get_json("deployment", target),
            lambda: kubectl_get_json("pods"),
        ),
        flux_guard=build_live_flux_guard(),
        retriever=RuntimeOnlyRetriever(
            KnowledgeRetriever(chroma_dir=resolved_chroma), corpus_version=corpus_version
        ),
        store=store,
    )
    summary = runner.run(PILOT_FAULT_ID, PILOT_TRIAL, gt_row)
    summary.update({
        "campaign_id": campaign_id,
        "aic_used": caller.cumulative_aic,
        "model": "gpt-5.6-terra",
        "recovery": "GREEN",
    })
    store.append_event("pilot_complete", aic_used=caller.cumulative_aic)
    return summary


if __name__ == "__main__":
    raise SystemExit(main())

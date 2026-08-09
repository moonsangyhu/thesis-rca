#!/usr/bin/env python3
"""V2.3 offline harness and externally gated one-incident pilot entrypoint.

No import in this module initializes Copilot, Kubernetes, Prometheus, or Loki.
Live imports occur only after fresh billing evidence and two process gates pass.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from .mock import run_dry_run, run_mock_campaign
from .authorization import LiveAuthorization


class RealExecutionDisabled(RuntimeError):
    pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="V2.3 offline review harness")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--mock", action="store_true", help="run all 180 mock rows")
    mode.add_argument("--dry-run", action="store_true", help="alias for offline mock validation")
    mode.add_argument("--pilot", action="store_true", help="authorized F7 trial 5 live pilot")
    parser.add_argument("--output-dir", type=Path, help="explicit non-results output directory")
    parser.add_argument(
        "--approve-real", action="store_true",
        help="reserved follow-up approval marker; live path is still disabled",
    )
    parser.add_argument("--billing-evidence", type=Path)
    parser.add_argument("--approval-id")
    parser.add_argument("--campaign-id")
    parser.add_argument("--max-campaign-aic", type=float, default=360.0)
    parser.add_argument("--chroma-dir", type=Path)
    args = parser.parse_args(argv)
    if args.pilot:
        if args.output_dir is not None or args.approve_real:
            parser.error("--pilot does not accept --output-dir or --approve-real")
        if (
            not args.billing_evidence or not args.approval_id
            or not args.campaign_id or not args.chroma_dir
        ):
            parser.error(
                "--pilot requires --billing-evidence, --approval-id, --campaign-id, "
                "and --chroma-dir"
            )
        if re.fullmatch(r"[A-Za-z0-9_.-]{8,128}", args.campaign_id) is None:
            parser.error("--campaign-id is invalid")
        authorization = LiveAuthorization.require(
            args.billing_evidence, approval_id=args.approval_id
        )
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
    if any((args.billing_evidence, args.approval_id, args.campaign_id, args.chroma_dir)):
        parser.error("live authorization arguments are valid only with --pilot")
    if args.dry_run:
        if args.output_dir is not None:
            parser.error("--dry-run is in-memory and does not accept --output-dir")
        summary = run_dry_run()
    else:
        summary = run_mock_campaign(args.output_dir)
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


def _probe_cli_version(executable: str) -> str:
    completed = subprocess.run(
        [executable, "--version"], text=True, capture_output=True,
        timeout=15, check=False,
    )
    version = (completed.stdout or completed.stderr).strip().splitlines()
    if completed.returncode != 0 or not version:
        raise RuntimeError("Copilot CLI version probe failed")
    return version[0][:200]


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

    from experiments.shared.copilot_cli import CopilotCLIBackend
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

    store = PilotOutputStore(output_dir)
    charged_journal = ChargedCallJournal(output_dir / "charged_call_ledger.jsonl")
    backend = CopilotCLIBackend(
        model="gpt-5.6-terra",
        max_ai_credits=10.0,
        zero_overage_confirmed=True,
        charge_observer=charged_journal.append,
    )
    cli_version = _probe_cli_version(backend.executable)
    corpus_version = snapshot_tree(
        (DEBUGGING_DIR, RUNBOOKS_DIR, KNOWN_ISSUES_DIR, resolved_chroma)
    )
    manifest = {
        "schema_version": "v2.3-pilot-campaign-1",
        "campaign_id": campaign_id,
        "git_commit": git_revision,
        "git_worktree_clean_at_start": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "account_scope": authorization.evidence.account_scope,
        "billing_confirmed_at": authorization.evidence.confirmed_at,
        "billing_confirmed_by": authorization.evidence.confirmed_by,
        "billing_confirmation_method": authorization.evidence.confirmation_method,
        "billing_evidence_sha256": authorization.evidence.evidence_sha256,
        "included_aic_balance_before": authorization.evidence.included_aic_balance,
        "aic_balance_observed_at": authorization.evidence.balance_observed_at,
        "approval_id": authorization.approval_id,
        "model": "gpt-5.6-terra",
        "fault_id": "F7",
        "trial": 5,
        "expected_rows": 3,
        "expected_calls": 36,
        "max_campaign_aic": max_campaign_aic,
        "per_call_max_aic": 10.0,
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
    gt_row = ground_truth.get(("F7", 5))
    if gt_row is None:
        raise RuntimeError("F7 trial 5 ground truth is missing")
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
        retriever=RuntimeOnlyRetriever(
            KnowledgeRetriever(chroma_dir=resolved_chroma), corpus_version=corpus_version
        ),
        store=store,
    )
    summary = runner.run("F7", 5, gt_row)
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

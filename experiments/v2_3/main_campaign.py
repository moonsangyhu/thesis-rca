"""Authorized 60-incident V2.3 primary campaign orchestration."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .authorization import LiveAuthorization, PAID_OVERAGE_MODE
from .config import (
    COPILOT_ACCOUNT_LOGIN, COPILOT_SESSION_MAX_AIC, EXPECTED_CALLS,
    EXPECTED_ROWS, FAULTS, FLUX_RECONCILIATION_POLICY, MAIN_MANIFEST_SCHEMA,
    REQUESTED_MODEL, TRIALS,
)


def run_authorized_main(
    authorization: LiveAuthorization,
    *,
    campaign_id: str,
    chroma_dir: Path,
) -> dict:
    """Run the frozen primary schedule; stop on the first invalid incident."""
    authorization.revalidate()
    project_root = Path(__file__).resolve().parents[2]

    # Local imports keep offline/dry-run imports free of live dependencies.
    from experiments.shared.copilot_identity import inspect_active_gh_account
    from experiments.shared.copilot_sdk import CopilotSDKBackend
    from experiments.shared.csv_io import load_ground_truth
    from experiments.shared.infra import preflight_check
    from scripts.fault_inject import FaultInjector
    from scripts.fault_inject.base import kubectl_get_json, ssh_node
    from scripts.stabilize import Recovery
    from scripts.stabilize.state_validator import StateValidator
    from src.collector import SignalCollector
    from src.rag.config import DEBUGGING_DIR, KNOWN_ISSUES_DIR, RUNBOOKS_DIR
    from src.rag.retriever import KnowledgeRetriever

    from .engine import RCAEngineV2_3
    from .flux_restore import build_live_flux_guard
    from .injection_validator import LiveInjectionValidator
    from .ledger import CallLedger
    from .live_caller import AuthorizedTerraCaller
    from .live_runner import (
        AttemptJournal, ChargedCallJournal, MainOutputStore,
        PilotIncidentRunner, RuntimeOnlyRetriever, snapshot_tree,
    )
    from .run import _local_cli_build_identity, _verified_git_revision

    git_revision = _verified_git_revision(project_root)
    output_dir = project_root / "artifacts" / "v2_3_main" / campaign_id
    paid_overage_authorized = authorization.billing_mode == PAID_OVERAGE_MODE
    if not paid_overage_authorized:
        raise RuntimeError("primary campaign requires explicit paid-overage authorization")

    backend = CopilotSDKBackend(
        model=REQUESTED_MODEL,
        max_ai_credits=COPILOT_SESSION_MAX_AIC,
        billing_execution_authorized=True,
    )

    def account_check():
        return inspect_active_gh_account(
            expected_login=COPILOT_ACCOUNT_LOGIN,
        )

    account = account_check()
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    resolved_chroma = Path(chroma_dir).resolve(strict=True)
    if not resolved_chroma.is_dir():
        raise RuntimeError("--chroma-dir must be an existing directory")

    store = MainOutputStore(output_dir)
    charged_journal = ChargedCallJournal(output_dir / "charged_call_ledger.jsonl")
    backend.charge_observer = charged_journal.append
    cli_version = _local_cli_build_identity(backend.executable)
    corpus_version = snapshot_tree(
        (DEBUGGING_DIR, RUNBOOKS_DIR, KNOWN_ISSUES_DIR, resolved_chroma)
    )
    manifest = {
        "schema_version": MAIN_MANIFEST_SCHEMA,
        "campaign_id": campaign_id,
        "git_commit": git_revision,
        "git_worktree_clean_at_start": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "billing_authorization_mode": authorization.billing_mode,
        "approval_id": authorization.approval_id,
        "account_scope": f"github:{account.login}",
        "billing_confirmed_at": None,
        "billing_confirmed_by": "user",
        "billing_confirmation_method": "explicit-paid-overage-authorization",
        "billing_confirmation_timestamp_status": "not-recorded-in-authorization-seal",
        "included_aic_balance_before": None,
        "aic_balance_observed_at": None,
        "server_quota": {
            "status": "not-queried-paid-overage-mode",
            "reason": "explicit-user-authorization",
        },
        "active_account": account.to_dict(),
        "max_campaign_aic": None,
        "copilot_session_max_aic": COPILOT_SESSION_MAX_AIC,
        "projected_main_aic_from_pilot": 4055,
        "model": REQUESTED_MODEL,
        "expected_incidents": len(FAULTS) * len(TRIALS),
        "expected_rows": EXPECTED_ROWS,
        "expected_calls": EXPECTED_CALLS,
        "faults": list(FAULTS),
        "trials": list(TRIALS),
        "corpus_version": corpus_version,
        "cli_version": cli_version,
        "cli_version_source": "local-package-and-native-sha256",
        "copilot_backend": "official-sdk-empty",
        "copilot_sdk_sha256": backend.sdk_sha256,
        "copilot_sdk_runner_sha256": backend.runner_sha256,
        "flux_reconciliation_policy": FLUX_RECONCILIATION_POLICY,
    }
    store.write_manifest(manifest)
    store.append_event("authorization_verified")
    if not preflight_check():
        store.append_event("preflight_failed")
        raise RuntimeError("cluster preflight failed")
    store.append_event("preflight_green")

    ground_truth = load_ground_truth(project_root / "results" / "ground_truth.csv")
    expected_identities = frozenset(
        (fault_id, trial) for fault_id in FAULTS for trial in TRIALS
    )
    if set(ground_truth) != expected_identities:
        raise RuntimeError("ground truth identity set does not match V2.3 schedule")
    journal = AttemptJournal(output_dir / "attempt_call_ledger.jsonl")
    caller = AuthorizedTerraCaller(
        authorization=authorization,
        backend=backend,
        campaign_id=campaign_id,
        cli_version=cli_version,
        max_campaign_aic=None,
    )
    engine = RCAEngineV2_3(
        caller,
        ledger=CallLedger(on_append=journal.append),
        campaign_id=campaign_id,
    )
    validator = LiveInjectionValidator(
        lambda resource, name, namespace: kubectl_get_json(
            resource, name, namespace=namespace
        ),
        lambda node, command: ssh_node(node, command, timeout=15),
    )
    runner = PilotIncidentRunner(
        authorization=authorization,
        engine=engine,
        injector=FaultInjector(),
        recovery=Recovery(),
        collector=SignalCollector(),
        validator=StateValidator(ground_truth=ground_truth),
        injection_validator=validator,
        flux_guard=build_live_flux_guard(),
        retriever=RuntimeOnlyRetriever(
            KnowledgeRetriever(chroma_dir=resolved_chroma),
            corpus_version=corpus_version,
        ),
        store=store,
        allowed_incidents=expected_identities,
    )

    completed = 0
    for fault_id in FAULTS:
        for trial in TRIALS:
            authorization.revalidate()
            store.append_event(
                "incident_scheduled", fault_id=fault_id, trial=trial,
                ordinal=completed + 1,
            )
            summary = runner.run(fault_id, trial, ground_truth[(fault_id, trial)])
            completed += 1
            progress = {
                "event": "campaign_progress",
                "campaign_id": campaign_id,
                "completed_incidents": completed,
                "expected_incidents": len(expected_identities),
                "rows": completed * 3,
                "calls": completed * 36,
                "aic_used": caller.cumulative_aic,
                "fault_id": fault_id,
                "trial": trial,
                "incident": summary,
            }
            store.append_event(
                "campaign_progress", fault_id=fault_id, trial=trial,
                completed_incidents=completed, rows=completed * 3,
                calls=completed * 36, aic_used=caller.cumulative_aic,
            )
            print(json.dumps(progress, ensure_ascii=False, sort_keys=True), flush=True)
            if completed < len(expected_identities):
                time.sleep(30)

    final = {
        "campaign_id": campaign_id,
        "incidents": completed,
        "rows": completed * 3,
        "calls": completed * 36,
        "aic_used": caller.cumulative_aic,
        "model": REQUESTED_MODEL,
        "recovery": "GREEN",
        "output_dir": str(output_dir),
    }
    store.append_event("campaign_complete", **final)
    return final

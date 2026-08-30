"""Authorized V2.3 primary campaign orchestration."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .authorization import CODEX_SUBSCRIPTION_MODE, LiveAuthorization
from .config import (
    FAULTS,
    FLUX_RECONCILIATION_POLICY, MAIN_EXCLUDED_INCIDENTS,
    MAIN_EXPECTED_CALLS, MAIN_EXPECTED_INCIDENTS, MAIN_EXPECTED_ROWS,
    MAIN_INCIDENTS, MAIN_MANIFEST_SCHEMA, PRIMARY_COPILOT_TIMEOUT_SECONDS,
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

    # This must precede every live/ML dependency import.  The local retriever
    # initializes native Torch components; running Git afterwards can stall on
    # macOS even when the command itself is otherwise spawn-safe.
    from .run import _probe_cli_version, _verified_git_revision

    git_revision = _verified_git_revision(project_root)
    # Local imports keep offline/dry-run imports free of live dependencies.
    from experiments.shared.codex_cli import (
        CODEX_MODEL_PROVENANCE, CODEX_PROVIDER, CodexCLIBackend,
    )
    from experiments.shared.csv_io import load_ground_truth
    from experiments.shared.infra import health_check, preflight_check
    from scripts.fault_inject import FaultInjector
    from scripts.fault_inject.base import kubectl_get_json, ssh_node
    from scripts.fault_inject.config import F4_T3_NODE_NAME
    from scripts.stabilize import Recovery
    from scripts.stabilize.health_verify import comprehensive_health_check
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
    output_dir = project_root / "artifacts" / "v2_3_main" / campaign_id
    if authorization.billing_mode != CODEX_SUBSCRIPTION_MODE:
        raise RuntimeError("primary campaign requires explicit Codex subscription authorization")

    backend = CodexCLIBackend(
        model=REQUESTED_MODEL,
        timeout_seconds=PRIMARY_COPILOT_TIMEOUT_SECONDS,
        subscription_authorized=True,
    )

    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
    resolved_chroma = Path(chroma_dir).resolve(strict=True)
    if not resolved_chroma.is_dir():
        raise RuntimeError("--chroma-dir must be an existing directory")

    store = MainOutputStore(output_dir)
    charged_journal = ChargedCallJournal(output_dir / "charged_call_ledger.jsonl")
    backend.charge_observer = charged_journal.append
    cli_version = _probe_cli_version(backend.executable)
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
        "account_scope": "chatgpt-subscription:locally-authenticated-codex-cli",
        "billing_confirmed_at": None,
        "billing_confirmed_by": "user",
        "billing_confirmation_method": "explicit-chatgpt-subscription-authorization",
        "billing_confirmation_timestamp_status": "not-recorded-in-authorization-seal",
        "included_aic_balance_before": None,
        "aic_balance_observed_at": None,
        "subscription_usage": {
            "status": "token-count-only",
            "reason": "Codex ChatGPT subscription does not emit monetary AIC in CLI JSON",
        },
        "max_campaign_aic": None,
        "codex_inference_timeout_seconds": PRIMARY_COPILOT_TIMEOUT_SECONDS,
        "model": REQUESTED_MODEL,
        "expected_incidents": MAIN_EXPECTED_INCIDENTS,
        "expected_rows": MAIN_EXPECTED_ROWS,
        "expected_calls": MAIN_EXPECTED_CALLS,
        "faults": list(FAULTS),
        "trials": list(TRIALS),
        "included_incidents": [
            {"fault_id": fault_id, "trial": trial}
            for fault_id, trial in MAIN_INCIDENTS
        ],
        "excluded_incidents": [
            {"fault_id": fault_id, "trial": trial,
             "reason": "invalidated-f7-t5-rollout-confounding"}
            for fault_id, trial in sorted(MAIN_EXCLUDED_INCIDENTS)
        ],
        "corpus_version": corpus_version,
        "cli_version": cli_version,
        "cli_version_source": "codex-cli---version",
        "provider": CODEX_PROVIDER,
        "codex_backend": "chatgpt-subscription-empty-readonly-ephemeral",
        "model_provenance": CODEX_MODEL_PROVENANCE,
        "isolation": {
            "working_directory": "empty-temporary-directory",
            "sandbox": "read-only",
            "ephemeral": True,
            "skip_git_repo_check": True,
            "tool_event_policy": "reject-any-non-agent-message-item",
        },
        "flux_reconciliation_policy": FLUX_RECONCILIATION_POLICY,
    }
    store.write_manifest(manifest)
    store.append_event("authorization_verified")
    if not preflight_check():
        store.append_event("preflight_failed")
        raise RuntimeError("cluster preflight failed")
    health_ok, health_issues = comprehensive_health_check(
        max_retries=1, retry_delay=0,
    )
    if not health_ok:
        store.append_event("preflight_failed", checks=health_issues)
        raise RuntimeError("comprehensive cluster preflight failed")
    store.append_event("preflight_green")

    ground_truth = load_ground_truth(project_root / "results" / "ground_truth.csv")
    ground_truth_identities = frozenset(
        (fault_id, trial) for fault_id in FAULTS for trial in TRIALS
    )
    if set(ground_truth) != ground_truth_identities:
        raise RuntimeError("ground truth identity set does not match V2.3 schedule")
    expected_identities = frozenset(MAIN_INCIDENTS)
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
            resource,
            name,
            namespace=namespace,
            timeout=(
                5 if (resource, name) == ("node", F4_T3_NODE_NAME) else 60
            ),
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
        infrastructure_flux_guard=build_live_flux_guard("infrastructure"),
        retriever=RuntimeOnlyRetriever(
            KnowledgeRetriever(chroma_dir=resolved_chroma),
            corpus_version=corpus_version,
        ),
        store=store,
        allowed_incidents=expected_identities,
    )

    completed = 0
    for fault_id, trial in MAIN_INCIDENTS:
        authorization.revalidate()
        if not health_check(fault_id, trial):
            store.append_event(
                "incident_preflight_failed", fault_id=fault_id, trial=trial,
            )
            raise RuntimeError("incident infrastructure preflight failed")
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

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from experiments.v2_3.authorization import LiveAuthorization


LIVE_ENV = {
    "THESIS_COPILOT_ZERO_OVERAGE_CONFIRMED": "1",
    "THESIS_V23_PILOT_USER_APPROVED": "1",
}


def verified_authorization(root: Path) -> LiveAuthorization:
    now = datetime.now(timezone.utc)
    artifacts = (
        ("paid_usage_disabled", "paid.txt", "paid usage disabled evidence"),
        ("budget_hard_stop", "budget.txt", "budget hard stop evidence"),
        ("included_aic_balance", "balance.txt", "included balance evidence 28850"),
    )
    evidence_files = []
    for kind, name, content in artifacts:
        path = root / name
        path.write_text(content)
        evidence_files.append({
            "kind": kind,
            "path": str(path),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
    manifest = root / "billing-evidence.json"
    manifest.write_text(json.dumps({
        "schema_version": "v2.3-zero-overage-1",
        "account_scope": "company/example-org",
        "confirmed_at": (now - timedelta(minutes=2)).isoformat(),
        "confirmed_by": "company-admin",
        "confirmation_method": "unit-test-artifacts",
        "paid_usage_disabled": True,
        "budget_hard_stop_enabled": True,
        "included_aic_balance": 28850.0,
        "balance_observed_at": (now - timedelta(minutes=1)).isoformat(),
        "evidence_files": evidence_files,
    }))
    return LiveAuthorization.require(
        manifest, approval_id="pilot-20260809", environment=LIVE_ENV, now=now
    )

import json
import hashlib
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from experiments.v2_3.authorization import (
    AuthorizationError, BillingEvidence, LiveAuthorization,
)


class AuthorizationTests(unittest.TestCase):
    NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)

    def write_manifest(self, root: Path, **overrides) -> Path:
        paid = root / "paid-usage-disabled.txt"
        budget = root / "budget-hard-stop.txt"
        balance = root / "included-aic-balance.txt"
        paid.write_text("paid usage disabled by company admin")
        budget.write_text("budget hard stop enabled by company admin")
        balance.write_text("included AIC balance: 28850")
        payload = {
            "schema_version": "v2.3-zero-overage-1",
            "account_scope": "company/example-org",
            "confirmed_at": (self.NOW - timedelta(minutes=5)).isoformat(),
            "confirmed_by": "company-admin",
            "confirmation_method": "admin-console-export",
            "paid_usage_disabled": True,
            "budget_hard_stop_enabled": True,
            "included_aic_balance": 28850.0,
            "balance_observed_at": (self.NOW - timedelta(minutes=2)).isoformat(),
            "evidence_files": [
                {
                    "kind": "paid_usage_disabled", "path": str(paid),
                    "sha256": hashlib.sha256(paid.read_bytes()).hexdigest(),
                },
                {
                    "kind": "budget_hard_stop", "path": str(budget),
                    "sha256": hashlib.sha256(budget.read_bytes()).hexdigest(),
                },
                {
                    "kind": "included_aic_balance", "path": str(balance),
                    "sha256": hashlib.sha256(balance.read_bytes()).hexdigest(),
                },
            ],
            **overrides,
        }
        path = root / "billing-evidence.json"
        path.write_text(json.dumps(payload))
        return path

    def test_both_process_gates_and_fresh_manifest_are_required(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = self.write_manifest(Path(temp_dir))
            with self.assertRaisesRegex(AuthorizationError, "zero-overage"):
                LiveAuthorization.require(path, approval_id="pilot-20260809", environment={}, now=self.NOW)
            with self.assertRaisesRegex(AuthorizationError, "user-approval"):
                LiveAuthorization.require(
                    path, approval_id="pilot-20260809",
                    environment={"THESIS_COPILOT_ZERO_OVERAGE_CONFIRMED": "1"},
                    now=self.NOW,
                )
            auth = LiveAuthorization.require(
                path,
                approval_id="pilot-20260809",
                environment={
                    "THESIS_COPILOT_ZERO_OVERAGE_CONFIRMED": "1",
                    "THESIS_V23_PILOT_USER_APPROVED": "1",
                },
                now=self.NOW,
            )
            self.assertEqual(auth.evidence.account_scope, "company/example-org")

    def test_paid_usage_budget_and_freshness_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            env = {
                "THESIS_COPILOT_ZERO_OVERAGE_CONFIRMED": "1",
                "THESIS_V23_PILOT_USER_APPROVED": "1",
            }
            for overrides in (
                {"paid_usage_disabled": False},
                {"budget_hard_stop_enabled": False},
                {"confirmed_at": (self.NOW - timedelta(days=2)).isoformat()},
            ):
                path = self.write_manifest(root, **overrides)
                with self.assertRaises(AuthorizationError):
                    LiveAuthorization.require(
                        path, approval_id="pilot-20260809", environment=env, now=self.NOW
                    )

    def test_evidence_artifact_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = self.write_manifest(root)
            (root / "paid-usage-disabled.txt").write_text("tampered")
            with self.assertRaisesRegex(AuthorizationError, "hash mismatch"):
                LiveAuthorization.require(
                    path,
                    approval_id="pilot-20260809",
                    environment={
                        "THESIS_COPILOT_ZERO_OVERAGE_CONFIRMED": "1",
                        "THESIS_V23_PILOT_USER_APPROVED": "1",
                    },
                    now=self.NOW,
                )

    def test_authorization_construction_is_sealed_and_revalidates_artifacts(self):
        with self.assertRaises(TypeError):
            BillingEvidence(account_scope="forged")
        with self.assertRaises(TypeError):
            LiveAuthorization(evidence=None, approval_id="pilot-forged")
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = self.write_manifest(root)
            env = {
                "THESIS_COPILOT_ZERO_OVERAGE_CONFIRMED": "1",
                "THESIS_V23_PILOT_USER_APPROVED": "1",
            }
            auth = LiveAuthorization.require(
                path, approval_id="pilot-20260809", environment=env, now=self.NOW
            )
            auth.revalidate(environment=env, now=self.NOW)
            (root / "budget-hard-stop.txt").write_text("tampered")
            with self.assertRaisesRegex(AuthorizationError, "hash mismatch"):
                auth.revalidate(environment=env, now=self.NOW)

    def test_three_evidence_kinds_must_use_distinct_artifacts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = self.write_manifest(root)
            payload = json.loads(path.read_text())
            shared = payload["evidence_files"][0]
            payload["evidence_files"] = [
                {**shared, "kind": kind}
                for kind in (
                    "paid_usage_disabled", "budget_hard_stop", "included_aic_balance"
                )
            ]
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(AuthorizationError, "distinct"):
                LiveAuthorization.require(
                    path,
                    approval_id="pilot-20260809",
                    environment={
                        "THESIS_COPILOT_ZERO_OVERAGE_CONFIRMED": "1",
                        "THESIS_V23_PILOT_USER_APPROVED": "1",
                    },
                    now=self.NOW,
                )


if __name__ == "__main__":
    unittest.main()

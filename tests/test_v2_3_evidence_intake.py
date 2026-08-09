import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from experiments.v2_3.authorization import BillingEvidence
from experiments.v2_3.evidence_intake import (
    EvidencePreparationError, PROJECT_ROOT, prepare_manifest,
)


class EvidenceIntakeTests(unittest.TestCase):
    NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)

    def artifacts(self, root: Path) -> tuple[Path, Path, Path]:
        paths = (
            root / "paid.png", root / "budget.png", root / "balance.png"
        )
        for path, content in zip(paths, (b"paid-disabled", b"hard-stop", b"21150")):
            path.write_bytes(content)
        return paths

    def test_builds_private_manifest_that_authorization_verifier_accepts(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paid, budget, balance = self.artifacts(root)
            output = root / "evidence.json"
            summary = prepare_manifest(
                paid_usage_disabled_path=paid,
                budget_hard_stop_path=budget,
                included_aic_balance_path=balance,
                account_scope="company/example-org",
                confirmed_by="company-admin",
                included_aic_balance=21150.0,
                output_path=output,
                confirmed_reviewed=True,
                now=self.NOW,
            )
            verified = BillingEvidence.load(output, now=self.NOW)
            self.assertEqual(verified.included_aic_balance, 21150.0)
            self.assertEqual(summary["external_calls"], 0)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_refuses_missing_attestation_duplicate_artifacts_and_repo_output(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            paid, budget, balance = self.artifacts(root)
            common = dict(
                paid_usage_disabled_path=paid,
                budget_hard_stop_path=budget,
                included_aic_balance_path=balance,
                account_scope="company/example-org",
                confirmed_by="company-admin",
                included_aic_balance=21150.0,
                output_path=root / "evidence.json",
                now=self.NOW,
            )
            with self.assertRaisesRegex(EvidencePreparationError, "manual review"):
                prepare_manifest(**common, confirmed_reviewed=False)
            with self.assertRaisesRegex(EvidencePreparationError, "distinct"):
                prepare_manifest(
                    **{
                        **common,
                        "budget_hard_stop_path": paid,
                        "confirmed_reviewed": True,
                    }
                )
            with self.assertRaisesRegex(EvidencePreparationError, "outside"):
                prepare_manifest(
                    **{
                        **common,
                        "output_path": PROJECT_ROOT / "must-not-exist.json",
                        "confirmed_reviewed": True,
                    }
                )
            self.assertFalse((PROJECT_ROOT / "must-not-exist.json").exists())


if __name__ == "__main__":
    unittest.main()

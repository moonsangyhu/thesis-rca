import json
import subprocess
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from experiments.shared.copilot_quota import (
    CopilotQuotaError, verify_zero_overage_quota,
)


def response(**overrides):
    quota = {
        "isUnlimitedEntitlement": False,
        "entitlementRequests": 50000,
        "usedRequests": 34100,
        "usageAllowedWithExhaustedQuota": False,
        "overage": 0,
        "overageAllowedWithExhaustedQuota": False,
        "remainingPercentage": 31.8,
        "resetDate": "2026-09-01T00:00:00Z",
        "hasQuota": True,
        "tokenBasedBilling": True,
        "overageEntitlement": 0,
    }
    quota.update(overrides)
    return json.dumps({
        "authenticated": True,
        "login": "researcher",
        "account": {
            "authType": "gh-cli",
            "host": "https://github.com",
            "login": "researcher",
            "copilotUserLogin": "researcher",
            "copilotPlan": "business",
            "accessTypeSku": "copilot_for_business_seat_quota",
            "tokenBasedBilling": True,
        },
        "quota": quota,
    })


class CopilotQuotaTests(unittest.TestCase):
    @patch("experiments.shared.copilot_quota.shutil.which", return_value="/usr/bin/node")
    @patch("experiments.shared.copilot_quota.subprocess.run")
    def test_exact_zero_overage_snapshot_passes_with_reserve(self, run, _which):
        run.return_value = subprocess.CompletedProcess(
            args=[], returncode=0, stdout=response(), stderr=""
        )
        snapshot = verify_zero_overage_quota(
            "/opt/bin/copilot",
            expected_login="researcher",
            required_remaining_aic=390,
            sdk_path=Path(__file__),
            now=datetime(2026, 8, 12, tzinfo=timezone.utc),
        )
        self.assertEqual(snapshot.remaining_aic, 15900)
        self.assertFalse(snapshot.overage_permitted)
        self.assertEqual(snapshot.overage_count, 0)
        self.assertIn("account.getQuota", run.call_args.kwargs["input"])
        self.assertEqual(run.call_args.args[0][1:3], ["--input-type=module", "-"])

    @patch("experiments.shared.copilot_quota.shutil.which", return_value="/usr/bin/node")
    @patch("experiments.shared.copilot_quota.subprocess.run")
    def test_server_overage_permission_fails_closed(self, run, _which):
        for field in (
            "usageAllowedWithExhaustedQuota",
            "overageAllowedWithExhaustedQuota",
        ):
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=response(**{field: True}), stderr=""
            )
            with self.subTest(field=field), self.assertRaisesRegex(
                CopilotQuotaError, "paid/additional"
            ):
                verify_zero_overage_quota(
                    "/opt/bin/copilot", expected_login="researcher", required_remaining_aic=390,
                    sdk_path=Path(__file__),
                )

    @patch("experiments.shared.copilot_quota.shutil.which", return_value="/usr/bin/node")
    @patch("experiments.shared.copilot_quota.subprocess.run")
    def test_overage_usage_and_insufficient_reserve_fail_closed(self, run, _which):
        cases = (
            (response(overage=1), "additional usage"),
            (response(overageEntitlement=1), "additional usage"),
            (response(usedRequests=49900, remainingPercentage=0.2), "reserve"),
            (response(remainingPercentage=99), "inconsistent"),
        )
        for stdout, message in cases:
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=stdout, stderr=""
            )
            with self.subTest(message=message), self.assertRaisesRegex(
                CopilotQuotaError, message
            ):
                verify_zero_overage_quota(
                    "/opt/bin/copilot", expected_login="researcher", required_remaining_aic=390,
                    sdk_path=Path(__file__),
                )

    @patch("experiments.shared.copilot_quota.shutil.which", return_value="/usr/bin/node")
    @patch("experiments.shared.copilot_quota.subprocess.run")
    def test_malformed_or_failed_probe_fails_closed(self, run, _which):
        for completed in (
            subprocess.CompletedProcess(args=[], returncode=1, stdout="", stderr="x"),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="not-json", stderr=""),
            subprocess.CompletedProcess(args=[], returncode=0, stdout="{}", stderr=""),
        ):
            run.return_value = completed
            with self.subTest(stdout=completed.stdout), self.assertRaises(CopilotQuotaError):
                verify_zero_overage_quota(
                    "/opt/bin/copilot", expected_login="researcher", required_remaining_aic=390,
                    sdk_path=Path(__file__),
                )

    @patch("experiments.shared.copilot_quota.shutil.which", return_value="/usr/bin/node")
    @patch("experiments.shared.copilot_quota.subprocess.run")
    def test_personal_or_mismatched_account_fails_closed(self, run, _which):
        payload = json.loads(response())
        for field, value in (
            ("copilotPlan", "individual"),
            ("accessTypeSku", "copilot_individual"),
            ("copilotUserLogin", "other-user"),
            ("authType", "user"),
        ):
            altered = json.loads(json.dumps(payload))
            altered["account"][field] = value
            run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout=json.dumps(altered), stderr=""
            )
            with self.subTest(field=field), self.assertRaisesRegex(
                CopilotQuotaError, "Business seat"
            ):
                verify_zero_overage_quota(
                    "/opt/bin/copilot", expected_login="researcher", required_remaining_aic=390,
                    sdk_path=Path(__file__),
                )


if __name__ == "__main__":
    unittest.main()

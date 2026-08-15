"""Read-only Copilot server quota inspection for billing-authorized experiments."""

from __future__ import annotations

import json
import math
import os
import signal
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


class CopilotQuotaError(RuntimeError):
    """The live Copilot quota cannot prove that paid overage is disabled."""


@dataclass(frozen=True)
class CopilotQuotaSnapshot:
    login: str
    copilot_plan: str
    access_type_sku: str
    entitlement_aic: int
    used_aic: int
    remaining_aic: int
    remaining_percentage: float
    reset_at: str
    observed_at: str
    token_based_billing: bool
    overage_count: int
    overage_entitlement: int
    usage_allowed_with_exhausted_quota: bool
    overage_allowed_with_exhausted_quota: bool
    overage_permitted: bool

    def to_dict(self) -> dict:
        return asdict(self)


_QUOTA_SCRIPT = r"""
const { CopilotClient } = await import(process.argv[2]);
const client = new CopilotClient({
  workingDirectory: process.cwd(),
  baseDirectory: process.argv[3],
  useLoggedInUser: true,
  logLevel: 'error'
});
try {
  await client.start();
  const auth = await client.getAuthStatus();
  const current = await client.rpc.account.getCurrentAuth();
  const authInfo = current?.authInfo || {};
  const copilotUser = authInfo?.copilotUser || {};
  const result = await client.rpc.account.getQuota({});
  const q = result?.quotaSnapshots?.premium_interactions;
  process.stdout.write(JSON.stringify({
    authenticated: auth?.isAuthenticated,
    login: auth?.login,
    account: {
      authType: authInfo?.type,
      host: authInfo?.host,
      login: authInfo?.login,
      copilotUserLogin: copilotUser?.login,
      copilotPlan: copilotUser?.copilot_plan,
      accessTypeSku: copilotUser?.access_type_sku,
      tokenBasedBilling: copilotUser?.token_based_billing
    },
    quota: q
  }));
} finally {
  await client.stop();
}
"""


def _resolve_sdk(executable: str) -> Path:
    resolved = Path(executable).resolve(strict=True)
    package_root = resolved.parent
    candidates = sorted(
        package_root.glob("node_modules/@github/copilot-*/copilot-sdk/index.js")
    )
    if len(candidates) != 1 or not candidates[0].is_file():
        raise CopilotQuotaError("pinned Copilot SDK path is unavailable or ambiguous")
    return candidates[0].resolve(strict=True)


def _integer(value: object, field: str, *, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise CopilotQuotaError(f"Copilot quota field is invalid: {field}")
    return value


def _finite(value: object, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CopilotQuotaError(f"Copilot quota field is invalid: {field}")
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0 or parsed > 100:
        raise CopilotQuotaError(f"Copilot quota field is invalid: {field}")
    return parsed


def _run_quota_probe(
    command: list[str], *, cwd: str, env: dict[str, str], timeout_seconds: int
) -> subprocess.CompletedProcess[str]:
    """Run the non-inference probe in its own process group."""
    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        stdout, stderr = process.communicate(_QUOTA_SCRIPT, timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    except BaseException:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.communicate()
        raise
    return subprocess.CompletedProcess(
        command, process.returncode, stdout=stdout, stderr=stderr
    )


def inspect_copilot_quota(
    executable: str,
    *,
    expected_login: str,
    required_remaining_aic: float = 0,
    allow_paid_overage: bool = False,
    sdk_path: Path | None = None,
    node_executable: str = "node",
    timeout_seconds: int = 60,
    timeout_retries: int = 1,
    now: datetime | None = None,
) -> CopilotQuotaSnapshot:
    """Query the official SDK without inference and bind billing/account state."""
    if (
        isinstance(required_remaining_aic, bool)
        or not isinstance(required_remaining_aic, (int, float))
        or not math.isfinite(float(required_remaining_aic))
        or required_remaining_aic < 0
    ):
        raise ValueError("required remaining AIC must be non-negative and finite")
    if not isinstance(allow_paid_overage, bool):
        raise ValueError("allow_paid_overage must be boolean")
    if not isinstance(expected_login, str) or not expected_login.strip():
        raise ValueError("expected Copilot login is required")
    if (
        isinstance(timeout_seconds, bool)
        or not isinstance(timeout_seconds, int)
        or timeout_seconds < 1
    ):
        raise ValueError("quota timeout must be a positive integer")
    if (
        isinstance(timeout_retries, bool)
        or not isinstance(timeout_retries, int)
        or timeout_retries not in (0, 1)
    ):
        raise ValueError("quota timeout retries must be zero or one")
    node = shutil.which(node_executable)
    if not node:
        raise CopilotQuotaError("Node.js executable is unavailable")
    sdk = Path(sdk_path).resolve(strict=True) if sdk_path else _resolve_sdk(executable)
    completed = None
    for attempt in range(timeout_retries + 1):
        with tempfile.TemporaryDirectory(prefix="thesis-copilot-quota-") as temp_dir:
            home = Path(temp_dir) / "copilot-home"
            home.mkdir(mode=0o700)
            try:
                completed = _run_quota_probe(
                    [node, "--input-type=module", "-", str(sdk), str(home)],
                    cwd=temp_dir,
                    env={**os.environ, "COPILOT_HOME": str(home)},
                    timeout_seconds=timeout_seconds,
                )
                break
            except subprocess.TimeoutExpired as exc:
                if attempt == timeout_retries:
                    raise CopilotQuotaError(
                        "Copilot quota probe timed out before inference"
                    ) from exc
            except Exception as exc:
                raise CopilotQuotaError(
                    "Copilot quota probe failed before inference"
                ) from exc
    if completed is None:
        raise CopilotQuotaError("Copilot quota probe did not complete")
    if completed.returncode != 0:
        raise CopilotQuotaError("Copilot quota probe failed before inference")
    try:
        payload = json.loads(completed.stdout)
    except (TypeError, json.JSONDecodeError) as exc:
        raise CopilotQuotaError("Copilot quota response is not strict JSON") from exc
    if not isinstance(payload, dict) or set(payload) != {
        "authenticated", "login", "account", "quota"
    }:
        raise CopilotQuotaError("Copilot quota response envelope is invalid")
    login = payload.get("login")
    account = payload.get("account")
    quota = payload.get("quota")
    if payload.get("authenticated") is not True or not isinstance(login, str) or not login:
        raise CopilotQuotaError("Copilot quota account is not authenticated")
    if login != expected_login.strip():
        raise CopilotQuotaError("Copilot quota login does not match the approved account")
    expected_account_keys = {
        "authType", "host", "login", "copilotUserLogin", "copilotPlan",
        "accessTypeSku", "tokenBasedBilling",
    }
    if not isinstance(account, dict) or set(account) != expected_account_keys:
        raise CopilotQuotaError("Copilot quota account metadata is invalid")
    if (
        account.get("authType") != "gh-cli"
        or account.get("host") != "https://github.com"
        or account.get("login") != login
        or account.get("copilotUserLogin") != login
        or account.get("copilotPlan") != "business"
        or account.get("accessTypeSku") != "copilot_for_business_seat_quota"
        or account.get("tokenBasedBilling") is not True
    ):
        raise CopilotQuotaError("Copilot quota is not bound to the approved Business seat")
    if not isinstance(quota, dict):
        raise CopilotQuotaError("Copilot premium-interactions quota is missing")

    entitlement = _integer(quota.get("entitlementRequests"), "entitlementRequests", minimum=1)
    used = _integer(quota.get("usedRequests"), "usedRequests")
    overage = _integer(quota.get("overage"), "overage")
    overage_entitlement = _integer(
        quota.get("overageEntitlement"), "overageEntitlement"
    )
    remaining_percentage = _finite(
        quota.get("remainingPercentage"), "remainingPercentage"
    )
    if used > entitlement and not allow_paid_overage:
        raise CopilotQuotaError("Copilot included AIC is already exhausted")
    remaining = max(0, entitlement - used)
    expected_percentage = remaining * 100 / entitlement
    if abs(remaining_percentage - expected_percentage) > 0.11:
        raise CopilotQuotaError("Copilot remaining AIC fields are inconsistent")
    if quota.get("tokenBasedBilling") is not True or quota.get("hasQuota") is not True:
        raise CopilotQuotaError("Copilot AI-credit quota is unavailable")
    if quota.get("isUnlimitedEntitlement") is not False:
        raise CopilotQuotaError("Copilot quota entitlement shape is unsupported")
    usage_after_exhaustion = quota.get("usageAllowedWithExhaustedQuota")
    overage_after_exhaustion = quota.get("overageAllowedWithExhaustedQuota")
    if not isinstance(usage_after_exhaustion, bool) or not isinstance(
        overage_after_exhaustion, bool
    ):
        raise CopilotQuotaError("Copilot overage policy fields are invalid")
    if not allow_paid_overage and (
        usage_after_exhaustion or overage_after_exhaustion
    ):
        raise CopilotQuotaError(
            "Copilot server permits paid/additional usage after included AIC exhaustion"
        )
    if not allow_paid_overage and (overage != 0 or overage_entitlement != 0):
        raise CopilotQuotaError("Copilot server reports nonzero additional usage")
    if remaining < float(required_remaining_aic):
        raise CopilotQuotaError("Copilot included AIC reserve is insufficient")
    reset_at = quota.get("resetDate")
    if not isinstance(reset_at, str) or not reset_at:
        raise CopilotQuotaError("Copilot quota reset timestamp is missing")
    try:
        parsed_reset = datetime.fromisoformat(reset_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise CopilotQuotaError("Copilot quota reset timestamp is invalid") from exc
    if parsed_reset.tzinfo is None:
        raise CopilotQuotaError("Copilot quota reset timestamp is not timezone-aware")
    observed = now or datetime.now().astimezone()
    return CopilotQuotaSnapshot(
        login=login,
        copilot_plan="business",
        access_type_sku="copilot_for_business_seat_quota",
        entitlement_aic=entitlement,
        used_aic=used,
        remaining_aic=remaining,
        remaining_percentage=remaining_percentage,
        reset_at=reset_at,
        observed_at=observed.isoformat(),
        token_based_billing=True,
        overage_count=overage,
        overage_entitlement=overage_entitlement,
        usage_allowed_with_exhausted_quota=usage_after_exhaustion,
        overage_allowed_with_exhausted_quota=overage_after_exhaustion,
        overage_permitted=usage_after_exhaustion or overage_after_exhaustion,
    )


def verify_zero_overage_quota(
    executable: str,
    *,
    expected_login: str,
    required_remaining_aic: float,
    sdk_path: Path | None = None,
    node_executable: str = "node",
    timeout_seconds: int = 60,
    timeout_retries: int = 1,
    now: datetime | None = None,
) -> CopilotQuotaSnapshot:
    """Backward-compatible strict zero-overage verifier."""
    return inspect_copilot_quota(
        executable,
        expected_login=expected_login,
        required_remaining_aic=required_remaining_aic,
        allow_paid_overage=False,
        sdk_path=sdk_path,
        node_executable=node_executable,
        timeout_seconds=timeout_seconds,
        timeout_retries=timeout_retries,
        now=now,
    )

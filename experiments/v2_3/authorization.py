"""Fail-closed authorization for any V2.3 external operation.

The manifest is evidence metadata, not a billing switch.  Live execution also
requires two explicit process-local gates so a copied/stale manifest cannot
start Copilot or cluster work by itself.
"""

from __future__ import annotations

import json
import hashlib
import os
import re
import math
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping

AUTH_SCHEMA = "v2.3-zero-overage-1"
ZERO_OVERAGE_ENV = "THESIS_COPILOT_ZERO_OVERAGE_CONFIRMED"
PILOT_APPROVAL_ENV = "THESIS_V23_PILOT_USER_APPROVED"
PAID_OVERAGE_ENV = "THESIS_V23_PAID_OVERAGE_AUTHORIZED"
ZERO_OVERAGE_MODE = "zero-overage-evidence"
PAID_OVERAGE_MODE = "paid-overage-user-authorized"
_AUTH_SEAL = object()


class AuthorizationError(RuntimeError):
    pass


@dataclass(frozen=True, init=False)
class BillingEvidence:
    account_scope: str
    confirmed_at: str
    confirmed_by: str
    confirmation_method: str
    evidence_sha256: tuple[str, ...]
    manifest_path: str
    included_aic_balance: float
    balance_observed_at: str
    _seal: object = field(repr=False, compare=False)

    @classmethod
    def _create(cls, *, seal: object, **values) -> "BillingEvidence":
        if seal is not _AUTH_SEAL:
            raise AuthorizationError("billing evidence construction is sealed")
        instance = object.__new__(cls)
        for name, value in values.items():
            object.__setattr__(instance, name, value)
        object.__setattr__(instance, "_seal", seal)
        return instance

    @classmethod
    def load(
        cls,
        path: Path,
        *,
        now: datetime | None = None,
        max_age: timedelta = timedelta(hours=24),
    ) -> "BillingEvidence":
        provided = Path(path)
        if provided.is_symlink():
            raise AuthorizationError("billing evidence must not be a symlink")
        try:
            resolved = provided.resolve(strict=True)
        except OSError as exc:
            raise AuthorizationError("billing evidence file is missing") from exc
        if not resolved.is_file():
            raise AuthorizationError("billing evidence must be a regular file")
        try:
            payload = json.loads(resolved.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise AuthorizationError("invalid billing evidence JSON") from exc
        expected = {
            "schema_version", "account_scope", "confirmed_at", "confirmed_by",
            "confirmation_method", "paid_usage_disabled", "budget_hard_stop_enabled",
            "included_aic_balance", "balance_observed_at", "evidence_files",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise AuthorizationError("billing evidence schema mismatch")
        if payload["schema_version"] != AUTH_SCHEMA:
            raise AuthorizationError("billing evidence version mismatch")
        if payload["paid_usage_disabled"] is not True:
            raise AuthorizationError("AI credits paid usage is not confirmed disabled")
        if payload["budget_hard_stop_enabled"] is not True:
            raise AuthorizationError("budget hard stop is not confirmed enabled")
        if not all(
            isinstance(payload.get(field), str) and payload[field].strip()
            for field in (
                "account_scope", "confirmed_at", "confirmed_by", "confirmation_method"
            )
        ):
            raise AuthorizationError("billing evidence identity is incomplete")
        try:
            included_balance = float(payload["included_aic_balance"])
        except (TypeError, ValueError) as exc:
            raise AuthorizationError("included AIC balance is invalid") from exc
        if not math.isfinite(included_balance) or included_balance <= 0:
            raise AuthorizationError("included AIC balance is invalid")
        evidence_files = payload["evidence_files"]
        if not isinstance(evidence_files, list) or len(evidence_files) != 3:
            raise AuthorizationError("exactly three billing evidence files are required")
        hashes: list[str] = []
        artifact_paths: list[Path] = []
        kinds: set[str] = set()
        for item in evidence_files:
            if not isinstance(item, dict) or set(item) != {"kind", "path", "sha256"}:
                raise AuthorizationError("billing evidence file schema mismatch")
            if item["kind"] not in {
                "paid_usage_disabled", "budget_hard_stop", "included_aic_balance"
            }:
                raise AuthorizationError("billing evidence kind is invalid")
            if re.fullmatch(r"[0-9a-f]{64}", str(item["sha256"])) is None:
                raise AuthorizationError("billing evidence hash is invalid")
            evidence_path = Path(item["path"])
            if evidence_path.is_symlink():
                raise AuthorizationError("billing evidence artifact must not be a symlink")
            try:
                evidence_path = evidence_path.resolve(strict=True)
            except OSError as exc:
                raise AuthorizationError("billing evidence artifact is missing") from exc
            if not evidence_path.is_file() or evidence_path == resolved:
                raise AuthorizationError("billing evidence artifact is invalid")
            actual_hash = hashlib.sha256(evidence_path.read_bytes()).hexdigest()
            if actual_hash != item["sha256"]:
                raise AuthorizationError("billing evidence artifact hash mismatch")
            kinds.add(item["kind"])
            hashes.append(actual_hash)
            artifact_paths.append(evidence_path)
        if kinds != {"paid_usage_disabled", "budget_hard_stop", "included_aic_balance"}:
            raise AuthorizationError("billing evidence kinds are incomplete")
        if len(set(artifact_paths)) != 3 or len(set(hashes)) != 3:
            raise AuthorizationError("billing evidence artifacts must be distinct")
        try:
            confirmed = datetime.fromisoformat(payload["confirmed_at"])
            balance_observed = datetime.fromisoformat(payload["balance_observed_at"])
        except (TypeError, ValueError) as exc:
            raise AuthorizationError("billing confirmation timestamp is invalid") from exc
        if confirmed.tzinfo is None:
            raise AuthorizationError("billing confirmation timestamp must be timezone-aware")
        if balance_observed.tzinfo is None:
            raise AuthorizationError("AIC balance timestamp must be timezone-aware")
        current = now or datetime.now(timezone.utc)
        confirmed = confirmed.astimezone(timezone.utc)
        balance_observed = balance_observed.astimezone(timezone.utc)
        current = current.astimezone(timezone.utc)
        if confirmed > current + timedelta(minutes=5):
            raise AuthorizationError("billing confirmation timestamp is in the future")
        if current - confirmed > max_age:
            raise AuthorizationError("billing confirmation is stale")
        if balance_observed > current + timedelta(minutes=5) or current - balance_observed > max_age:
            raise AuthorizationError("AIC balance observation is stale")
        return cls._create(
            seal=_AUTH_SEAL,
            account_scope=payload["account_scope"].strip(),
            confirmed_at=payload["confirmed_at"],
            confirmed_by=payload["confirmed_by"].strip(),
            confirmation_method=payload["confirmation_method"].strip(),
            evidence_sha256=tuple(hashes),
            manifest_path=str(resolved),
            included_aic_balance=included_balance,
            balance_observed_at=payload["balance_observed_at"],
        )


@dataclass(frozen=True, init=False)
class LiveAuthorization:
    evidence: BillingEvidence | None
    approval_id: str
    billing_mode: str
    _seal: object = field(repr=False, compare=False)

    @classmethod
    def _create(
        cls, *, evidence: BillingEvidence | None, approval_id: str,
        billing_mode: str, seal: object
    ) -> "LiveAuthorization":
        if seal is not _AUTH_SEAL:
            raise AuthorizationError("live authorization construction is sealed")
        if billing_mode == ZERO_OVERAGE_MODE:
            if evidence is None or evidence._seal is not _AUTH_SEAL:
                raise AuthorizationError("zero-overage evidence seal is invalid")
        elif billing_mode == PAID_OVERAGE_MODE:
            if evidence is not None:
                raise AuthorizationError("paid-overage authorization cannot claim evidence")
        else:
            raise AuthorizationError("live billing authorization mode is invalid")
        instance = object.__new__(cls)
        object.__setattr__(instance, "evidence", evidence)
        object.__setattr__(instance, "approval_id", approval_id)
        object.__setattr__(instance, "billing_mode", billing_mode)
        object.__setattr__(instance, "_seal", seal)
        return instance

    @classmethod
    def require(
        cls,
        evidence_path: Path,
        *,
        approval_id: str,
        environment: Mapping[str, str] | None = None,
        now: datetime | None = None,
    ) -> "LiveAuthorization":
        env = os.environ if environment is None else environment
        if env.get(ZERO_OVERAGE_ENV) != "1":
            raise AuthorizationError("zero-overage process gate is not enabled")
        if env.get(PILOT_APPROVAL_ENV) != "1":
            raise AuthorizationError("pilot user-approval process gate is not enabled")
        if not approval_id or re.fullmatch(r"[A-Za-z0-9_.-]{8,128}", approval_id) is None:
            raise AuthorizationError("pilot approval ID is missing or invalid")
        evidence = BillingEvidence.load(evidence_path, now=now)
        return cls._create(
            evidence=evidence, approval_id=approval_id,
            billing_mode=ZERO_OVERAGE_MODE, seal=_AUTH_SEAL
        )

    @classmethod
    def require_paid_overage(
        cls,
        *,
        approval_id: str,
        environment: Mapping[str, str] | None = None,
    ) -> "LiveAuthorization":
        """Seal the user's explicit authorization to permit metered overage."""
        env = os.environ if environment is None else environment
        if env.get(PAID_OVERAGE_ENV) != "1":
            raise AuthorizationError("paid-overage process gate is not enabled")
        if env.get(PILOT_APPROVAL_ENV) != "1":
            raise AuthorizationError("pilot user-approval process gate is not enabled")
        if not approval_id or re.fullmatch(r"[A-Za-z0-9_.-]{8,128}", approval_id) is None:
            raise AuthorizationError("pilot approval ID is missing or invalid")
        return cls._create(
            evidence=None,
            approval_id=approval_id,
            billing_mode=PAID_OVERAGE_MODE,
            seal=_AUTH_SEAL,
        )

    def revalidate(
        self,
        *,
        environment: Mapping[str, str] | None = None,
        now: datetime | None = None,
    ) -> "LiveAuthorization":
        """Re-read artifacts and process gates at every live boundary."""
        if (
            getattr(self, "_seal", None) is not _AUTH_SEAL
        ):
            raise AuthorizationError("live authorization seal is invalid")
        if self.billing_mode == ZERO_OVERAGE_MODE:
            if getattr(getattr(self, "evidence", None), "_seal", None) is not _AUTH_SEAL:
                raise AuthorizationError("zero-overage evidence seal is invalid")
            refreshed = type(self).require(
                Path(self.evidence.manifest_path),
                approval_id=self.approval_id,
                environment=environment,
                now=now,
            )
            if refreshed.evidence != self.evidence:
                raise AuthorizationError("billing evidence changed after authorization")
        elif self.billing_mode == PAID_OVERAGE_MODE:
            if self.evidence is not None:
                raise AuthorizationError("paid-overage authorization evidence is invalid")
            refreshed = type(self).require_paid_overage(
                approval_id=self.approval_id,
                environment=environment,
            )
        else:
            raise AuthorizationError("live billing authorization mode is invalid")
        if refreshed != self:
            raise AuthorizationError("live authorization changed after sealing")
        return self

"""Canonical HMAC identities and reviewer-specific order."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections import OrderedDict
from typing import Any, Iterable

from .io import AuditError

ROW_FIELDS = ("campaign_id", "fault_id", "trial", "condition")
INCIDENT_FIELDS = ("campaign_id", "fault_id", "trial")
GENERATION_FIELDS = ("campaign_id", "fault_id", "trial", "condition", "generation_repeat")


def canonical_identity(value: dict[str, Any], fields: tuple[str, ...]) -> bytes:
    if tuple(value) != fields or set(value) != set(fields):
        raise AuditError("canonical identity field order/schema mismatch")
    if any(not isinstance(value[field], (str, int)) or isinstance(value[field], bool) for field in fields):
        raise AuditError("canonical identity values must be string/integer")
    ordered = OrderedDict((field, value[field]) for field in fields)
    return json.dumps(
        ordered, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8", "strict")


def mac(secret: bytes, domain: str, payload: bytes) -> bytes:
    if len(secret) != 32 or not domain.startswith("v2.4/"):
        raise AuditError("invalid HMAC secret/domain")
    return hmac.new(secret, domain.encode("utf-8") + b"\x00" + payload, hashlib.sha256).digest()


def opaque_id(secret: bytes, domain: str, prefix: str, payload: bytes) -> str:
    return prefix + mac(secret, domain, payload)[:16].hex()


def ordered_ids(secret: bytes, reviewer: str, phase: str, values: Iterable[str]) -> list[str]:
    domain = f"v2.4/{reviewer}/{phase}-order"
    result = sorted(values, key=lambda value: (mac(secret, domain, value.encode("ascii")), value))
    if len(result) != len(set(result)):
        raise AuditError("opaque ID collision")
    return result

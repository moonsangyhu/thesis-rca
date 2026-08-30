"""Fail-closed validation for the optional 108-generation sensitivity audit."""

from __future__ import annotations

import hashlib
from typing import Any

from .io import AuditError


def validate_all_generation_seal(items: list[dict[str, Any]]) -> None:
    required = {
        "generation_id", "campaign_id", "fault_id", "trial", "condition",
        "generation_repeat", "output_text_hash", "representative",
    }
    if len(items) != 108 or len({item.get("generation_id") for item in items}) != 108:
        raise AuditError("escalation seal must contain exactly 108 unique generations")
    if any(set(item) != required for item in items):
        raise AuditError("escalation seal schema mismatch")
    identities = {
        (item["fault_id"], item["trial"], item["condition"], item["generation_repeat"])
        for item in items
    }
    if len(identities) != 108 or any(item["generation_repeat"] not in {1, 2, 3} for item in items):
        raise AuditError("escalation seal is not the exhaustive 12x3x3 set")


def materialize_all_generation_outputs(
    seal: list[dict[str, Any]], archived_outputs: dict[str, bytes],
) -> list[dict[str, Any]]:
    """Require every sealed byte payload; representative-only filtering is forbidden."""
    validate_all_generation_seal(seal)
    expected_ids = {item["generation_id"] for item in seal}
    if set(archived_outputs) != expected_ids:
        missing = len(expected_ids - set(archived_outputs))
        extra = len(set(archived_outputs) - expected_ids)
        raise AuditError(
            f"BLOCKED_GENERATION_CONTENT_NOT_ARCHIVED: missing={missing}, extra={extra}"
        )
    records = []
    for item in seal:
        payload = archived_outputs[item["generation_id"]]
        if hashlib.sha256(payload).hexdigest() != item["output_text_hash"]:
            raise AuditError("archived generation output hash mismatch")
        records.append({"generation_id": item["generation_id"], "output_bytes": payload})
    return records

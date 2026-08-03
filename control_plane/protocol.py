"""Authenticated command envelope between Hermes adapter and Controller."""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from .manifest import canonical_bytes

_HEX_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_FIELDS = {
    "version",
    "request_id",
    "platform",
    "user_id",
    "channel_id",
    "thread_ts",
    "command",
    "args",
    "received_at",
    "signature",
}


class EnvelopeError(ValueError):
    pass


@dataclass(frozen=True)
class CommandEnvelope:
    version: int
    request_id: str
    platform: str
    user_id: str
    channel_id: str
    thread_ts: str
    command: str
    args: str
    received_at: str
    signature: str = ""

    @classmethod
    def parse(cls, value: dict[str, Any]) -> "CommandEnvelope":
        if not isinstance(value, dict):
            raise EnvelopeError("envelope must be an object")
        unknown = set(value) - _FIELDS
        missing = _FIELDS - set(value)
        if unknown or missing:
            raise EnvelopeError("envelope fields do not match schema")
        envelope = cls(**value)
        if (
            type(envelope.version) is not int
            or envelope.version != 1
            or envelope.platform != "slack"
            or envelope.command != "thesis"
        ):
            raise EnvelopeError("unsupported envelope source or version")
        for name, field, maximum in (
            ("request_id", envelope.request_id, 256),
            ("user_id", envelope.user_id, 128),
            ("channel_id", envelope.channel_id, 128),
        ):
            if not isinstance(field, str) or not field or len(field) > maximum:
                raise EnvelopeError(f"invalid {name}")
        if not isinstance(envelope.thread_ts, str) or len(envelope.thread_ts) > 64:
            raise EnvelopeError("invalid thread_ts")
        if not isinstance(envelope.args, str) or len(envelope.args) > 2048:
            raise EnvelopeError("invalid args")
        if not isinstance(envelope.signature, str) or not _HEX_SHA256.fullmatch(envelope.signature):
            raise EnvelopeError("invalid signature encoding")
        try:
            observed = datetime.fromisoformat(envelope.received_at)
        except (TypeError, ValueError) as exc:
            raise EnvelopeError("invalid received_at") from exc
        if observed.tzinfo is None:
            raise EnvelopeError("received_at requires a timezone")
        return envelope

    def unsigned_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "request_id": self.request_id,
            "platform": self.platform,
            "user_id": self.user_id,
            "channel_id": self.channel_id,
            "thread_ts": self.thread_ts,
            "command": self.command,
            "args": self.args,
            "received_at": self.received_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return self.unsigned_dict() | {"signature": self.signature}


class EnvelopeSigner:
    def __init__(self, key_material: bytes):
        if not isinstance(key_material, bytes) or len(key_material) < 32:
            raise ValueError("envelope key material must contain at least 32 bytes")
        self._key_material = key_material

    def sign(self, envelope: CommandEnvelope) -> CommandEnvelope:
        signature = hmac.new(
            self._key_material,
            canonical_bytes(envelope.unsigned_dict()),
            hashlib.sha256,
        ).hexdigest()
        return replace(envelope, signature=signature)

    def verify(self, envelope: CommandEnvelope) -> bool:
        expected = self.sign(replace(envelope, signature="")).signature
        return hmac.compare_digest(expected, envelope.signature)


def validate_freshness(
    envelope: CommandEnvelope,
    *,
    now: datetime | None = None,
    max_age: timedelta = timedelta(seconds=30),
    future_skew: timedelta = timedelta(seconds=5),
) -> None:
    observed = datetime.fromisoformat(envelope.received_at)
    current = now or datetime.now(timezone.utc)
    if observed > current + future_skew:
        raise EnvelopeError("envelope timestamp is in the future")
    if current - observed > max_age:
        raise EnvelopeError("envelope expired")


def encode_response(value: dict[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    ) + b"\n"

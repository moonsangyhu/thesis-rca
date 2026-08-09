"""Agent-free `/thesis` Slack adapter.

This is the *only* bridge between an authenticated Slack slash command and
the campaign :class:`~control_plane.controller.CampaignController`. It is
invoked from :mod:`control_plane.gateway_hook`, a Hermes *project plugin*
that uses only Hermes's existing, unmodified ``pre_gateway_dispatch`` plugin
hook (``ctx.register_hook`` — a stock Hermes plugin API, not a custom
extension). Hermes's own source is never modified: this repository is a
consumer of the upstream Hermes gateway, connected to Slack.

Design constraints (see docs/plans/hermes_control_plane_adapter_contract.md):

* No agent, terminal tool, or Codex MCP surface may reach the signer or the
  Controller socket. The signer lives entirely inside this adapter instance.
* The request identity is derived from the gateway-verified inbound
  ``MessageEvent`` (see :mod:`control_plane.gateway_hook`); this adapter
  never forges one. Missing identity fails closed.
* Native slash commands have no thread context, so an empty ``thread_ts`` is
  signed and the Controller dereferences the sealed campaign thread.
* Responses are length-bounded and key-allowlisted so nothing unexpected is
  echoed back into Slack.

The context object is duck-typed (``platform``, ``request_id``, ``user_id``,
``channel_id``, ``thread_id``, ``command``, ``received_at``) so this module has
no hard dependency on Hermes and stays unit-testable in isolation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .ipc import send_command
from .protocol import CommandEnvelope, EnvelopeError, EnvelopeSigner

# The fixed command name this adapter is bound to. Anything else is refused so
# a mis-registered handler can never sign for a different command surface.
_COMMAND = "thesis"
_MAX_ARGS = 2048
_MAX_RESPONSE_CHARS = 800

# Only these keys are ever surfaced back to Slack. The Controller never returns
# secrets, but allowlisting keeps an unexpected field from leaking regardless.
_RESPONSE_KEYS = (
    "status",
    "reason",
    "state",
    "campaign_id",
    "manifest_sha256",
    "source_commit",
    "sequence",
    "updated_at",
    "active_campaign",
    "duplicate",
)


class AdapterError(ValueError):
    """Raised for a request this adapter refuses before touching the socket."""


@dataclass(frozen=True)
class ThesisAdapterConfig:
    """Runtime wiring for the adapter.

    ``socket_path`` and ``signer_key_path`` are fixed paths outside the agent
    workspace and outside general temp roots; the signer key is read once at
    construction and never re-exposed.
    """

    socket_path: Path
    allowed_user_id: str
    allowed_channel_id: str
    timeout: float = 5.0


def load_signer_from_path(signer_key_path: Path) -> EnvelopeSigner:
    """Read HMAC key material from *signer_key_path* and build a signer.

    The raw bytes are handed straight to :class:`EnvelopeSigner` and never
    retained by this module. ``EnvelopeSigner`` enforces the 32-byte minimum.
    """
    key_material = Path(signer_key_path).read_bytes()
    return EnvelopeSigner(key_material)


class ThesisSlashAdapter:
    """Signs `/thesis` commands and forwards them to the Controller socket."""

    def __init__(self, config: ThesisAdapterConfig, signer: EnvelopeSigner):
        if not config.allowed_user_id or not config.allowed_channel_id:
            raise ValueError("adapter requires one allowed user and channel")
        self._config = config
        # The signer is private state of this adapter instance. It is never
        # returned, logged, or attached to any object that crosses the agent
        # boundary.
        self._signer = signer

    def handle(self, raw_args: str, context: Any) -> str:
        """Validate *context*, sign the command, and return a bounded reply."""
        try:
            envelope = self._build_envelope(raw_args, context)
        except AdapterError as exc:
            return f"거부됨: {exc}"
        response = send_command(
            self._config.socket_path,
            self._signer.sign(envelope),
            timeout=self._config.timeout,
        )
        return _render_response(response)

    def _build_envelope(self, raw_args: str, context: Any) -> CommandEnvelope:
        if context is None:
            raise AdapterError("missing_request_context")
        platform = _attr(context, "platform")
        if platform != "slack":
            raise AdapterError("unsupported_platform")
        command = _attr(context, "command")
        if command != _COMMAND:
            raise AdapterError("unexpected_command")

        request_id = _attr(context, "request_id")
        user_id = _attr(context, "user_id")
        channel_id = _attr(context, "channel_id")
        received_at = _attr(context, "received_at")
        # Fail closed on any missing identity component — never substitute a
        # hash or wall-clock value for an absent Slack request identity.
        if not (request_id and user_id and channel_id and received_at):
            raise AdapterError("missing_request_identity")

        # Bind the request to the configured operator/channel before signing so
        # a foreign identity is refused locally, not just at the Controller.
        if user_id != self._config.allowed_user_id:
            raise AdapterError("user_not_allowed")
        if channel_id != self._config.allowed_channel_id:
            raise AdapterError("channel_not_allowed")

        self._require_aware_timestamp(received_at)

        args = raw_args or ""
        if len(args) > _MAX_ARGS:
            raise AdapterError("args_too_long")

        # Native slash commands carry no thread; sign an empty thread_ts and let
        # the Controller resolve the sealed campaign thread.
        thread_ts = _attr(context, "thread_id") or ""

        try:
            return CommandEnvelope(
                version=1,
                request_id=request_id,
                platform="slack",
                user_id=user_id,
                channel_id=channel_id,
                thread_ts=thread_ts,
                command=_COMMAND,
                args=args,
                received_at=received_at,
            )
        except EnvelopeError as exc:
            raise AdapterError(str(exc)) from exc

    @staticmethod
    def _require_aware_timestamp(received_at: str) -> None:
        try:
            observed = datetime.fromisoformat(received_at)
        except (TypeError, ValueError) as exc:
            raise AdapterError("invalid_received_at") from exc
        if observed.tzinfo is None:
            raise AdapterError("received_at_requires_timezone")


def _attr(context: Any, name: str) -> str:
    value = getattr(context, name, "")
    if value is None:
        return ""
    if not isinstance(value, str):
        raise AdapterError(f"invalid_{name}")
    return value.strip()


def _render_response(response: Any) -> str:
    """Render a Controller response as a short, key-allowlisted string."""
    if not isinstance(response, dict):
        return "제어면 응답 형식이 올바르지 않습니다."
    parts = []
    for key in _RESPONSE_KEYS:
        if key in response:
            parts.append(f"{key}={response[key]}")
    rendered = " ".join(parts) if parts else "제어면이 알 수 없는 응답을 반환했습니다."
    if len(rendered) > _MAX_RESPONSE_CHARS:
        rendered = rendered[:_MAX_RESPONSE_CHARS] + "…"
    return rendered


def unconfigured_handler(raw_args: str, context: Any) -> str:
    """Fail-closed stand-in used when the adapter is not configured.

    Used so that `/thesis` on Slack always produces a rejection reply and
    never falls through to the agent/skill loop, even when signing is
    unavailable. See :mod:`control_plane.gateway_hook` for the plugin entry
    point that wires this (and the real adapter) into Hermes's
    ``pre_gateway_dispatch`` hook — the only Hermes plugin extension point
    this repository uses, unmodified from upstream.
    """
    return "거부됨: thesis 제어면이 구성되지 않았습니다."

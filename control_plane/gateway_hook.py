"""Hermes project-plugin entry point: `/thesis` via ``pre_gateway_dispatch``.

This module is the *entire* integration surface with Hermes, and it uses
exactly one stock, already-existing Hermes plugin extension point:
``ctx.register_hook("pre_gateway_dispatch", callback)``. Hermes's own source
tree (``~/.hermes/hermes-agent``, upstream NousResearch/hermes-agent) is
never modified, patched, or forked to support this — Hermes is a consumer
dependency, connected to Slack, and used as-is.

``pre_gateway_dispatch`` fires once per inbound ``MessageEvent``, *before*
auth/pairing and *before* the agent/model/Codex loop ever sees the event
(gateway/run.py, ``hermes_cli/plugins.py`` ``VALID_HOOKS``). A callback may
return ``{"action": "skip", ...}`` to drop the event with no further
processing — no reply is sent to the agent loop, and it never sees the
`/thesis` command text or arguments.

Because ``invoke_hook`` calls every registered callback *synchronously*
(``cb(**kwargs)``, no ``await``) from inside the gateway's asyncio event
loop, this callback must never block on socket I/O itself (Controller IPC
can take up to several seconds). Instead it does only cheap, synchronous
identity/shape checks, then schedules the actual signed dispatch — and the
Slack reply — as a background ``asyncio`` task via
``loop.run_in_executor`` for the blocking Unix-socket round trip. The hook
callback itself always returns immediately.

Any inbound event that is not a Slack `/thesis` message is left completely
untouched (returns ``None``) so normal dispatch, auth, and every other
plugin/hook continues to behave exactly as it does without this plugin
installed.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

_COMMAND = "thesis"
_PLATFORM_SLACK = "slack"


@dataclass(frozen=True)
class _RequestContext:
    """Duck-typed identity object consumed by ``ThesisSlashAdapter.handle``.

    Field names/shape match what :mod:`control_plane.adapter` already
    expects (``platform``, ``request_id``, ``user_id``, ``channel_id``,
    ``thread_id``, ``command``, ``received_at``) — the adapter itself is
    unchanged from the version that was unit-tested against a fake context.
    """

    platform: str
    request_id: str
    user_id: str
    channel_id: str
    thread_id: str
    command: str
    received_at: str


def _extract_request_id(event: Any) -> str:
    """Best-effort stable identifier for this inbound Slack request.

    Native Slack slash commands carry a ``trigger_id`` in the raw payload
    (valid briefly, but present and unique per invocation); fall back to the
    Slack-assigned message id if it is ever absent so the envelope never
    signs an empty request id.
    """
    raw = getattr(event, "raw_message", None)
    if isinstance(raw, dict):
        trigger_id = raw.get("trigger_id")
        if isinstance(trigger_id, str) and trigger_id.strip():
            return trigger_id.strip()
    message_id = getattr(event, "message_id", None)
    if isinstance(message_id, str) and message_id.strip():
        return message_id.strip()
    return ""


def _is_slack_thesis_command(event: Any) -> bool:
    source = getattr(event, "source", None)
    if source is None:
        return False
    platform = getattr(source, "platform", None)
    platform_value = getattr(platform, "value", platform)
    if platform_value != _PLATFORM_SLACK:
        return False
    get_command = getattr(event, "get_command", None)
    if not callable(get_command):
        return False
    return get_command() == _COMMAND


def _build_context(event: Any) -> _RequestContext:
    source = event.source
    return _RequestContext(
        platform=_PLATFORM_SLACK,
        request_id=_extract_request_id(event),
        user_id=str(getattr(source, "user_id", "") or ""),
        channel_id=str(getattr(source, "chat_id", "") or ""),
        thread_id=str(getattr(source, "thread_id", "") or ""),
        command=_COMMAND,
        received_at=datetime.now(timezone.utc).isoformat(),
    )


async def _reply_only(gateway: Any, source: Any, reply: str) -> None:
    """Send *reply* back to the originating Slack channel, best-effort."""
    try:
        platform_adapter = gateway.adapters[source.platform]
    except Exception:  # noqa: BLE001 - missing/removed adapter must not raise
        logger.warning("thesis adapter: no Slack adapter to reply on", exc_info=True)
        return
    try:
        await platform_adapter.send(chat_id=source.chat_id, content=reply)
    except Exception:  # noqa: BLE001 - reply delivery failure must not raise
        logger.warning("thesis adapter: failed to send Slack reply", exc_info=True)


async def _dispatch_and_reply(adapter: Any, raw_args: str, context: _RequestContext, gateway: Any, source: Any) -> None:
    """Run the (blocking) signed dispatch off-loop, then reply to Slack.

    ``adapter.handle`` performs the Controller Unix-socket round trip
    synchronously (bounded timeout), so it runs in the default executor
    thread pool rather than directly on the gateway's event loop.
    """
    loop = asyncio.get_running_loop()
    try:
        reply = await loop.run_in_executor(None, adapter.handle, raw_args, context)
    except Exception:  # noqa: BLE001 - never let a Controller failure crash the gateway
        logger.warning("thesis adapter dispatch failed", exc_info=True)
        reply = "거부됨: 제어면 호출 중 오류가 발생했습니다."

    await _reply_only(gateway, source, reply)


def make_pre_gateway_dispatch(adapter: Optional[Any]):
    """Build the ``pre_gateway_dispatch`` callback bound to *adapter*.

    ``adapter`` is ``None`` when the control plane is not configured
    (missing socket/key/identity env vars) — in that case every `/thesis`
    Slack request is still intercepted and told it is unavailable, and never
    falls through to the agent loop.
    """

    def _pre_gateway_dispatch(event: Any, gateway: Any, session_store: Any = None, **_: Any):
        if not _is_slack_thesis_command(event):
            return None  # not ours: normal dispatch continues untouched

        context = _build_context(event)
        get_args = getattr(event, "get_command_args", None)
        raw_args = get_args() if callable(get_args) else ""

        if adapter is None:
            from .adapter import unconfigured_handler

            reply = unconfigured_handler(raw_args, context)
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(
                    _reply_only(gateway, event.source, reply)
                )
            except RuntimeError:
                logger.warning("thesis hook: no running event loop to reply on")
            return {"action": "skip", "reason": "thesis_control_plane_unconfigured"}

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                _dispatch_and_reply(adapter, raw_args, context, gateway, event.source)
            )
        except RuntimeError:
            logger.warning("thesis hook: no running event loop to dispatch on")
        return {"action": "skip", "reason": "thesis_command_dispatched_to_control_plane"}

    return _pre_gateway_dispatch


def register(ctx) -> None:
    """Hermes plugin entry point.

    Loads the adapter from environment configuration (fail-closed: ``None``
    when unconfigured) and registers the bound ``pre_gateway_dispatch``
    callback via ``ctx.register_hook`` — a stock, unmodified Hermes plugin
    API. No Hermes source file is read, patched, or depended upon beyond
    this documented extension point.
    """
    from .adapter_config import load_adapter_runtime  # local import

    adapter = load_adapter_runtime(ctx)
    ctx.register_hook("pre_gateway_dispatch", make_pre_gateway_dispatch(adapter))

"""Tests for the `pre_gateway_dispatch`-only `/thesis` Hermes integration.

These tests never import anything from Hermes: the hook module only relies
on the documented ``pre_gateway_dispatch`` callback contract (kwargs
``event``, ``gateway``, ``session_store``; return ``{"action": "skip", ...}``
or ``None``), so a duck-typed fake ``event``/``gateway`` fully exercises it.

Covers:
* Non-Slack or non-`/thesis` events are left completely untouched (``None``).
* A matching Slack `/thesis` event is always intercepted (``skip``), whether
  or not the control plane is configured, so it can never reach the agent
  loop.
* The blocking Controller round trip runs off the event loop
  (``run_in_executor``) and the reply is delivered via the platform
  adapter's own ``send()`` — never anything agent/model-facing.
* ``register()`` only calls ``ctx.register_hook`` — the stock Hermes plugin
  API this design relies on — never ``register_command``.
"""

from __future__ import annotations

import asyncio
import os
import unittest
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from control_plane.gateway_hook import make_pre_gateway_dispatch, register


@dataclass
class FakeSource:
    platform: str = "slack"
    chat_id: str = "C-allowed"
    user_id: str = "U-allowed"
    thread_id: str = ""


@dataclass
class FakeEvent:
    text: str
    source: FakeSource
    raw_message: Optional[Dict[str, Any]] = None
    message_id: Optional[str] = None

    def is_command(self) -> bool:
        return self.text.lstrip().startswith("/")

    def get_command(self) -> Optional[str]:
        if not self.is_command():
            return None
        parts = self.text.lstrip().split(maxsplit=1)
        return parts[0][1:].lower() if parts else None

    def get_command_args(self) -> str:
        parts = self.text.lstrip().split(maxsplit=1)
        return parts[1] if len(parts) > 1 else ""


class FakeSlackAdapter:
    def __init__(self):
        self.sent: List[Dict[str, Any]] = []

    async def send(self, chat_id: str, content: str) -> None:
        self.sent.append({"chat_id": chat_id, "content": content})


def make_gateway(slack_adapter: FakeSlackAdapter) -> SimpleNamespace:
    return SimpleNamespace(adapters={"slack": slack_adapter})


def thesis_event(text: str = "/thesis status", **source_kwargs) -> FakeEvent:
    return FakeEvent(
        text=text,
        source=FakeSource(**source_kwargs),
        raw_message={"trigger_id": "trigger-1"},
    )


class NonMatchingEventsPassThroughTests(unittest.TestCase):
    """Anything not a Slack `/thesis` command must be fully untouched."""

    def setUp(self):
        self.callback = make_pre_gateway_dispatch(adapter=None)
        self.slack_adapter = FakeSlackAdapter()
        self.gateway = make_gateway(self.slack_adapter)

    def test_non_slack_platform_ignored(self):
        event = thesis_event(platform="discord")
        result = self.callback(event=event, gateway=self.gateway)
        self.assertIsNone(result)
        self.assertEqual(self.slack_adapter.sent, [])

    def test_non_command_text_ignored(self):
        event = thesis_event(text="just chatting")
        result = self.callback(event=event, gateway=self.gateway)
        self.assertIsNone(result)

    def test_other_command_ignored(self):
        event = thesis_event(text="/model gpt-4o")
        result = self.callback(event=event, gateway=self.gateway)
        self.assertIsNone(result)


class MatchingEventAlwaysSkipsTests(unittest.TestCase):
    """A Slack `/thesis` event must always be intercepted (skip), even
    unconfigured -- it must never fall through to the agent loop."""

    def _run(self, callback, event, gateway):
        """Invoke *callback* inside a running loop and drain the background
        task it schedules (``loop.create_task``), so both the sync callback
        (which needs ``asyncio.get_running_loop()`` to succeed) and its
        async follow-up run exactly as they would inside the real gateway.
        """

        async def _invoke_and_drain():
            result = callback(event=event, gateway=gateway)
            current = asyncio.current_task()
            pending = [t for t in asyncio.all_tasks() if t is not current and not t.done()]
            if pending:
                await asyncio.gather(*pending)
            return result

        return asyncio.run(_invoke_and_drain())

    def test_unconfigured_adapter_still_skips_and_replies(self):
        callback = make_pre_gateway_dispatch(adapter=None)
        slack_adapter = FakeSlackAdapter()
        gateway = make_gateway(slack_adapter)
        event = thesis_event()

        result = self._run(callback, event, gateway)

        self.assertEqual(result["action"], "skip")
        self.assertEqual(len(slack_adapter.sent), 1)
        self.assertIn("거부됨", slack_adapter.sent[0]["content"])
        self.assertEqual(slack_adapter.sent[0]["chat_id"], "C-allowed")

    def test_configured_adapter_dispatches_via_executor_and_skips(self):
        calls: List[Any] = []

        class FakeAdapter:
            def handle(self, raw_args, context):
                calls.append((raw_args, context))
                return "status=approved state=APPROVED"

        callback = make_pre_gateway_dispatch(adapter=FakeAdapter())
        slack_adapter = FakeSlackAdapter()
        gateway = make_gateway(slack_adapter)
        event = thesis_event(text="/thesis status v2.3-c01")

        result = self._run(callback, event, gateway)

        self.assertEqual(
            result,
            {"action": "skip", "reason": "thesis_command_dispatched_to_control_plane"},
        )
        self.assertEqual(len(calls), 1)
        raw_args, context = calls[0]
        self.assertEqual(raw_args, "status v2.3-c01")
        self.assertEqual(context.platform, "slack")
        self.assertEqual(context.request_id, "trigger-1")
        self.assertEqual(context.user_id, "U-allowed")
        self.assertEqual(context.channel_id, "C-allowed")
        self.assertEqual(context.command, "thesis")
        self.assertTrue(context.received_at)
        self.assertEqual(len(slack_adapter.sent), 1)
        self.assertIn("status=approved", slack_adapter.sent[0]["content"])

    def test_adapter_exception_replies_with_rejection_not_crash(self):
        class BoomAdapter:
            def handle(self, raw_args, context):
                raise RuntimeError("controller unreachable")

        callback = make_pre_gateway_dispatch(adapter=BoomAdapter())
        slack_adapter = FakeSlackAdapter()
        gateway = make_gateway(slack_adapter)
        event = thesis_event()

        result = self._run(callback, event, gateway)

        self.assertEqual(result["action"], "skip")
        self.assertEqual(len(slack_adapter.sent), 1)
        self.assertIn("거부됨", slack_adapter.sent[0]["content"])

    def test_missing_slack_adapter_does_not_raise(self):
        class FakeAdapter:
            def handle(self, raw_args, context):
                return "status=approved"

        callback = make_pre_gateway_dispatch(adapter=FakeAdapter())
        gateway = SimpleNamespace(adapters={})  # no slack adapter registered
        event = thesis_event()

        # Must not raise even though gateway.adapters["slack"] is absent.
        result = self._run(callback, event, gateway)
        self.assertEqual(result["action"], "skip")


class RegisterUsesOnlyStockHookApiTests(unittest.TestCase):
    """The plugin entry point must call only ``ctx.register_hook`` -- the
    stock, already-existing Hermes plugin API -- and never anything that
    would imply a custom Hermes extension."""

    def setUp(self):
        for var in (
            "THESIS_CONTROLLER_SOCKET",
            "THESIS_SIGNER_KEY_PATH",
            "THESIS_ALLOWED_USER_ID",
            "THESIS_ALLOWED_CHANNEL_ID",
        ):
            os.environ.pop(var, None)

    def test_register_calls_register_hook_with_pre_gateway_dispatch(self):
        captured = {}

        class Ctx:
            def register_hook(self, hook_name, callback):
                captured["hook_name"] = hook_name
                captured["callback"] = callback

            def __getattr__(self, name):
                # Any other attribute access (e.g. register_command) means
                # the design regressed back to depending on a custom Hermes
                # extension point -- fail the test loudly instead of
                # silently no-op'ing.
                raise AssertionError(
                    f"register() must only use register_hook, tried to use '{name}'"
                )

        register(Ctx())
        self.assertEqual(captured["hook_name"], "pre_gateway_dispatch")
        self.assertTrue(callable(captured["callback"]))


if __name__ == "__main__":
    unittest.main()

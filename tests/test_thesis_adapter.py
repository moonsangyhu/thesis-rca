"""Tests for the agent-free `/thesis` Slack adapter.

Verifies that a gateway-verified request identity is signed into a
CommandEnvelope and routed to the campaign Controller over its Unix socket,
that the agent loop is never involved, that the signer stays private, and
that forged / partial / stale requests fail closed.
"""

from __future__ import annotations

import os
import socket
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Optional

from control_plane.adapter import (
    AdapterError,
    ThesisAdapterConfig,
    ThesisSlashAdapter,
    _render_response,
    load_signer_from_path,
)
from control_plane.commands import ThesisCommandRouter
from control_plane.controller import CampaignController, ControlPlaneConfig
from control_plane.ipc import ControllerEndpoint, UnixControllerServer
from control_plane.protocol import EnvelopeSigner

_KEY = b"thesis-adapter-key-material-32-bytes-minimum!!"


def manifest(campaign_id: str = "v2.3-c01") -> dict:
    return {
        "schema_version": 1,
        "campaign_id": campaign_id,
        "source_commit": "a" * 40,
        "model": "gpt-4o-mini",
        "faults": ["F1"],
        "trials": [1],
        "timeout_seconds": 3600,
        "runner_profile": "v2_3",
        "restore_profile": "boutique_v1",
        "credential_profile": "lab_write_v1",
        "expected_rows": 5,
        "expected_raw_files": 5,
        "thread_ts": "1234567890.123456",
    }


@dataclass(frozen=True)
class FakeContext:
    """Duck-typed stand-in for the gateway PluginCommandContext."""

    platform: str = "slack"
    request_id: str = "trigger-1"
    user_id: str = "U-allowed"
    channel_id: str = "C-allowed"
    thread_id: str = ""
    command: str = "thesis"
    received_at: Optional[str] = None

    def with_now(self) -> "FakeContext":
        if self.received_at is not None:
            return self
        return FakeContext(
            platform=self.platform,
            request_id=self.request_id,
            user_id=self.user_id,
            channel_id=self.channel_id,
            thread_id=self.thread_id,
            command=self.command,
            received_at=datetime.now(timezone.utc).isoformat(),
        )


class RenderResponseTests(unittest.TestCase):
    def test_allowlists_keys_and_drops_unexpected(self):
        rendered = _render_response(
            {"status": "approved", "state": "APPROVED", "secret_token": "abc123"}
        )
        self.assertIn("status=approved", rendered)
        self.assertIn("state=APPROVED", rendered)
        self.assertNotIn("secret_token", rendered)
        self.assertNotIn("abc123", rendered)

    def test_bounds_length(self):
        rendered = _render_response({"reason": "x" * 5000})
        self.assertLessEqual(len(rendered), 801)
        self.assertTrue(rendered.endswith("…"))

    def test_non_dict_is_safe(self):
        self.assertIn("올바르지 않", _render_response(["not", "a", "dict"]))


class AdapterLocalValidationTests(unittest.TestCase):
    """Rejections that must happen before any socket connection."""

    def setUp(self):
        self.signer = EnvelopeSigner(_KEY)
        # Point at a path that does not exist: if handle() tried to connect,
        # it would raise. A clean rejection string proves we never dialed.
        self.config = ThesisAdapterConfig(
            socket_path=Path("/nonexistent/controller.sock"),
            allowed_user_id="U-allowed",
            allowed_channel_id="C-allowed",
        )
        self.adapter = ThesisSlashAdapter(self.config, self.signer)

    def _handle(self, ctx: FakeContext, args: str = "status") -> str:
        return self.adapter.handle(args, ctx.with_now())

    def test_missing_request_id_fails_closed(self):
        result = self._handle(FakeContext(request_id=""))
        self.assertIn("missing_request_identity", result)

    def test_missing_user_fails_closed(self):
        result = self._handle(FakeContext(user_id=""))
        self.assertIn("missing_request_identity", result)

    def test_forged_user_rejected(self):
        result = self._handle(FakeContext(user_id="U-attacker"))
        self.assertIn("user_not_allowed", result)

    def test_forged_channel_rejected(self):
        result = self._handle(FakeContext(channel_id="C-attacker"))
        self.assertIn("channel_not_allowed", result)

    def test_non_slack_platform_rejected(self):
        result = self._handle(FakeContext(platform="discord"))
        self.assertIn("unsupported_platform", result)

    def test_unexpected_command_rejected(self):
        result = self._handle(FakeContext(command="approve"))
        self.assertIn("unexpected_command", result)

    def test_naive_timestamp_rejected(self):
        ctx = FakeContext(received_at="2026-08-03T12:00:00")  # no tzinfo
        result = self.adapter.handle("status", ctx)
        self.assertIn("received_at_requires_timezone", result)

    def test_none_context_rejected(self):
        self.assertIn("missing_request_context", self.adapter.handle("status", None))

    def test_signer_is_private(self):
        # No public attribute exposes the signer or key material.
        public = [a for a in dir(self.adapter) if not a.startswith("_")]
        self.assertNotIn("signer", public)
        self.assertNotIn("key", " ".join(public))


class AdapterSocketRoundTripTests(unittest.TestCase):
    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.signer = EnvelopeSigner(_KEY)
        self.controller = CampaignController(
            self.root,
            ControlPlaneConfig(allowed_user_id="U-allowed", allowed_channel_id="C-allowed"),
        )
        self.endpoint = ControllerEndpoint(ThesisCommandRouter(self.controller), self.signer)
        self.socket_path = self.root / "controller.sock"
        self.server = UnixControllerServer(
            self.socket_path,
            self.endpoint,
            allowed_peer_uids={os.getuid()},
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.adapter = ThesisSlashAdapter(
            ThesisAdapterConfig(
                socket_path=self.socket_path,
                allowed_user_id="U-allowed",
                allowed_channel_id="C-allowed",
            ),
            self.signer,
        )

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.tmp.cleanup()

    def _handle(self, args: str, **ctx_kwargs) -> str:
        ctx = FakeContext(**ctx_kwargs).with_now()
        return self.adapter.handle(args, ctx)

    def test_approve_status_stop_end_to_end(self):
        ready = self.controller.register_manifest(manifest())
        sha = ready["manifest_sha256"]

        approved = self._handle(f"approve v2.3-c01 {sha}", request_id="req-approve")
        self.assertIn("status=approved", approved)
        self.assertIn("state=APPROVED", approved)

        status = self._handle("status v2.3-c01", request_id="req-status")
        self.assertIn("state=APPROVED", status)

        stopped = self._handle("stop v2.3-c01", request_id="req-stop")
        self.assertIn("status=stopped", stopped)
        self.assertIn("state=SAFE_STOPPED", stopped)

    def test_native_slash_empty_thread_resolves_sealed_thread(self):
        ready = self.controller.register_manifest(manifest())
        # thread_id="" (native slash) must still approve via sealed manifest.
        approved = self._handle(
            f"approve v2.3-c01 {ready['manifest_sha256']}",
            request_id="req-approve",
            thread_id="",
        )
        self.assertIn("status=approved", approved)

    def test_expired_timestamp_rejected_by_controller(self):
        ready = self.controller.register_manifest(manifest())
        old = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        ctx = FakeContext(request_id="req-old", received_at=old)
        result = self.adapter.handle(f"approve v2.3-c01 {ready['manifest_sha256']}", ctx)
        self.assertIn("status=rejected", result)
        self.assertIn("expired", result)
        # State must not have advanced.
        self.assertEqual(self.controller.campaigns.read("v2.3-c01").state.value, "READY")

    def test_duplicate_request_id_is_idempotent(self):
        ready = self.controller.register_manifest(manifest())
        sha = ready["manifest_sha256"]
        first = self._handle(f"approve v2.3-c01 {sha}", request_id="req-dup")
        second = self._handle(f"approve v2.3-c01 {sha}", request_id="req-dup")
        self.assertIn("status=approved", first)
        self.assertIn("duplicate=True", second)

    def test_agent_loop_is_never_invoked(self):
        # The adapter's only outward call is the Controller socket. Prove it by
        # confirming a successful command produced exactly the Controller state
        # transition and audit record — no other surface exists on the adapter.
        ready = self.controller.register_manifest(manifest())
        self._handle(f"approve v2.3-c01 {ready['manifest_sha256']}", request_id="req-x")
        audit = (self.root / "commands.jsonl").read_text().splitlines()
        self.assertEqual(len(audit), 1)
        # The adapter exposes no agent/model/dispatch entry points.
        for forbidden in ("run_agent", "dispatch", "agent", "llm", "model"):
            self.assertFalse(
                any(forbidden in a for a in dir(self.adapter) if not a.startswith("__")),
                forbidden,
            )

    def test_concurrent_contexts_do_not_crosstalk(self):
        self.controller.register_manifest(manifest("v2.3-c01"))
        self.controller.register_manifest(manifest("v2.3-c02"))

        def run(campaign_id: str) -> str:
            return self._handle(
                f"status {campaign_id}", request_id=f"req-{campaign_id}"
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(run, "v2.3-c01")
            second = pool.submit(run, "v2.3-c02")
            r1, r2 = first.result(), second.result()
        self.assertIn("campaign_id=v2.3-c01", r1)
        self.assertIn("campaign_id=v2.3-c02", r2)


class RegisterTests(unittest.TestCase):
    """`/thesis` must always be reserved as context-required, even unconfigured."""

    def setUp(self):
        for var in (
            "THESIS_CONTROLLER_SOCKET",
            "THESIS_SIGNER_KEY_PATH",
            "THESIS_ALLOWED_USER_ID",
            "THESIS_ALLOWED_CHANNEL_ID",
        ):
            os.environ.pop(var, None)

    def test_register_always_registers_context_required(self):
        from control_plane.adapter import register

        captured = {}

        class Ctx:
            def register_command(self, name, handler, **kwargs):
                captured["name"] = name
                captured["handler"] = handler
                captured["kwargs"] = kwargs

        register(Ctx())
        self.assertEqual(captured["name"], "thesis")
        self.assertTrue(captured["kwargs"]["wants_context"])
        # Unconfigured -> fail-closed stub, never a live signer, never agent.
        reply = captured["handler"]("approve x y", FakeContext().with_now())
        self.assertIn("거부됨", reply)
        self.assertIn("구성되지 않", reply)


class SignerLoadingTests(unittest.TestCase):
    def test_load_signer_from_path_roundtrip(self):
        with TemporaryDirectory() as tmp:
            key_path = Path(tmp) / "signer.key"
            key_path.write_bytes(_KEY)
            signer = load_signer_from_path(key_path)
            self.assertTrue(isinstance(signer, EnvelopeSigner))

    def test_short_key_is_rejected(self):
        with TemporaryDirectory() as tmp:
            key_path = Path(tmp) / "short.key"
            key_path.write_bytes(b"too-short")
            with self.assertRaises(ValueError):
                load_signer_from_path(key_path)


if __name__ == "__main__":
    unittest.main()

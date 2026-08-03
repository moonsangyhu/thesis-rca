"""Strict `/thesis` subcommand parser and Controller routing."""

from __future__ import annotations

import shlex

from .controller import ApprovalRequest, CampaignController, StopRequest
from .protocol import CommandEnvelope


class ThesisCommandRouter:
    def __init__(self, controller: CampaignController):
        self.controller = controller

    def handle(self, envelope: CommandEnvelope) -> dict:
        rejection = self.controller.authorize(envelope.user_id, envelope.channel_id)
        if rejection:
            return rejection
        try:
            parts = shlex.split(envelope.args)
        except ValueError:
            return {"status": "rejected", "reason": "invalid_command_syntax"}
        if not parts:
            return {"status": "rejected", "reason": "missing_subcommand"}
        subcommand, *args = parts
        if subcommand == "status":
            if len(args) > 1:
                return {"status": "rejected", "reason": "usage_status"}
            return self.controller.status(
                envelope.user_id,
                envelope.channel_id,
                args[0] if args else None,
            )
        if subcommand == "approve":
            if len(args) != 2:
                return {"status": "rejected", "reason": "usage_approve"}
            thread_ts = envelope.thread_ts or self.controller.campaign_thread(args[0])
            if not thread_ts:
                return {"status": "rejected", "reason": "campaign_thread_unresolved"}
            return self.controller.approve(
                ApprovalRequest(
                    event_id=envelope.request_id,
                    user_id=envelope.user_id,
                    channel_id=envelope.channel_id,
                    campaign_id=args[0],
                    manifest_sha256=args[1],
                    thread_ts=thread_ts,
                )
            )
        if subcommand == "stop":
            if len(args) != 1:
                return {"status": "rejected", "reason": "usage_stop"}
            thread_ts = envelope.thread_ts or self.controller.campaign_thread(args[0])
            if not thread_ts:
                return {"status": "rejected", "reason": "campaign_thread_unresolved"}
            return self.controller.stop(
                StopRequest(
                    event_id=envelope.request_id,
                    user_id=envelope.user_id,
                    channel_id=envelope.channel_id,
                    campaign_id=args[0],
                    thread_ts=thread_ts,
                )
            )
        if subcommand == "logs":
            return {"status": "rejected", "reason": "logs_unavailable_until_redaction"}
        return {"status": "rejected", "reason": "unknown_subcommand"}

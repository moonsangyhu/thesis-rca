"""Runtime configuration for the `/thesis` Slack adapter.

Kept separate from :mod:`control_plane.adapter` so the adapter core stays
free of any environment/config coupling and remains unit-testable in
isolation. This module is only exercised on the live Hermes plugin path
(``adapter.register``); it never runs during the adapter unit tests.

Configuration is read from environment variables so nothing is hard-coded to
an operator's machine:

* ``THESIS_CONTROLLER_SOCKET``   — Controller Unix socket path
* ``THESIS_SIGNER_KEY_PATH``     — HMAC key file (outside workspace/temp roots)
* ``THESIS_ALLOWED_USER_ID``     — the single allowed Slack user id
* ``THESIS_ALLOWED_CHANNEL_ID``  — the single allowed Slack channel id
* ``THESIS_CONTROLLER_TIMEOUT``  — optional float seconds (default 5.0)

If any required value is absent the loader returns ``None`` and the command is
simply not registered — fail closed, never register an unconfigured signer.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from .adapter import (
    ThesisAdapterConfig,
    ThesisSlashAdapter,
    load_signer_from_path,
)

logger = logging.getLogger(__name__)


def load_adapter_runtime(ctx=None) -> Optional[ThesisSlashAdapter]:
    """Build a :class:`ThesisSlashAdapter` from the environment, or ``None``.

    ``ctx`` is accepted for forward compatibility with richer Hermes plugin
    config but is not required.
    """
    socket_path = os.environ.get("THESIS_CONTROLLER_SOCKET", "").strip()
    signer_key_path = os.environ.get("THESIS_SIGNER_KEY_PATH", "").strip()
    allowed_user_id = os.environ.get("THESIS_ALLOWED_USER_ID", "").strip()
    allowed_channel_id = os.environ.get("THESIS_ALLOWED_CHANNEL_ID", "").strip()
    if not (socket_path and signer_key_path and allowed_user_id and allowed_channel_id):
        logger.info(
            "thesis adapter not configured (missing socket/key/identity); "
            "command not registered."
        )
        return None

    try:
        timeout = float(os.environ.get("THESIS_CONTROLLER_TIMEOUT", "5.0"))
    except ValueError:
        timeout = 5.0

    try:
        signer = load_signer_from_path(Path(signer_key_path))
    except (OSError, ValueError) as exc:
        # Fail closed: a bad or missing key must not degrade to an unsigned or
        # partially-wired command.
        logger.warning("thesis adapter signer unavailable: %s", type(exc).__name__)
        return None

    config = ThesisAdapterConfig(
        socket_path=Path(socket_path),
        allowed_user_id=allowed_user_id,
        allowed_channel_id=allowed_channel_id,
        timeout=timeout,
    )
    return ThesisSlashAdapter(config, signer)

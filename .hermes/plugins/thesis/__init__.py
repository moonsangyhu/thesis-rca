"""Hermes project plugin: agent-free `/thesis` control-plane command.

Discovered by Hermes only when project plugins are explicitly enabled
(``HERMES_ENABLE_PROJECT_PLUGINS``). ``register`` wires a `/thesis` handler
into Hermes's existing, unmodified ``pre_gateway_dispatch`` plugin hook (see
:mod:`control_plane.gateway_hook`) — no Hermes source file is read, patched,
or forked. The actual signing and Controller IPC live in
:mod:`control_plane.adapter`.

The repository root must be importable (so ``control_plane`` resolves). We add
it to ``sys.path`` defensively; in the normal gateway launch the thesis-rca
root is already the working directory / on the path.
"""

from __future__ import annotations

import sys
from pathlib import Path

# thesis-rca repo root == three levels up from this file
# (.hermes/plugins/thesis/__init__.py -> repo root).
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def register(ctx) -> None:
    from control_plane.gateway_hook import register as _register

    _register(ctx)

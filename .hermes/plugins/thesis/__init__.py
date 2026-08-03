"""Hermes project plugin: agent-free `/thesis` control-plane command.

Discovered by Hermes only when project plugins are explicitly enabled
(``HERMES_ENABLE_PROJECT_PLUGINS``). ``register`` wires the signed command
into the gateway's structured plugin-command path; the actual signing and
Controller IPC live in :mod:`control_plane.adapter`.

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
    from control_plane.adapter import register as _register

    _register(ctx)

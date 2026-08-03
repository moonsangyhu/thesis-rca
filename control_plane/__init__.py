"""Deterministic control-plane primitives for thesis experiment campaigns."""

from .controller import (
    ApprovalRequest,
    CampaignController,
    ControlPlaneConfig,
    StopRequest,
)
from .manifest import CampaignManifest
from .state import CampaignState

__all__ = [
    "ApprovalRequest",
    "CampaignController",
    "CampaignManifest",
    "CampaignState",
    "ControlPlaneConfig",
    "StopRequest",
]

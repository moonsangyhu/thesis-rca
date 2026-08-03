"""Deterministic control-plane primitives for thesis experiment campaigns."""

from .adapter import (
    AdapterError,
    ThesisAdapterConfig,
    ThesisSlashAdapter,
    load_signer_from_path,
)
from .controller import (
    ApprovalRequest,
    CampaignController,
    ControlPlaneConfig,
    StopRequest,
)
from .manifest import CampaignManifest
from .state import CampaignState

__all__ = [
    "AdapterError",
    "ApprovalRequest",
    "CampaignController",
    "CampaignManifest",
    "CampaignState",
    "ControlPlaneConfig",
    "StopRequest",
    "ThesisAdapterConfig",
    "ThesisSlashAdapter",
    "load_signer_from_path",
]

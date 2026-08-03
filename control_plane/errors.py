"""Control-plane domain errors."""


class ControlPlaneError(RuntimeError):
    """Base class for expected control-plane failures."""


class ManifestValidationError(ControlPlaneError):
    pass


class InvalidTransition(ControlPlaneError):
    pass


class CampaignExists(ControlPlaneError):
    pass


class CampaignNotFound(ControlPlaneError):
    pass


class LockHeld(ControlPlaneError):
    pass


class LockOwnershipError(ControlPlaneError):
    pass

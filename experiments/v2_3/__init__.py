"""Offline-safe V2.3 experiment harness.

The live experiment path is intentionally unavailable in this revision.  The
package only exposes deterministic fixtures, integrity gates, and a mock
campaign used to review the 180-row/2,160-call design without external access.
"""

from .config import CONDITIONS, K_GENERATIONS, M_JUDGES

__all__ = ["CONDITIONS", "K_GENERATIONS", "M_JUDGES"]

"""
Signal collector for K8s RCA.

Collects from: Prometheus, Loki, kubectl, FluxCD, ArgoCD.

Usage:
    from src.collector import SignalCollector
    collector = SignalCollector()
    signals = collector.collect_all(window_minutes=5)
"""
import logging
from typing import Optional

from .prometheus import PrometheusCollector
from .loki import LokiCollector
from .kubectl import KubectlCollector
from .gitops import GitOpsCollector
from .config import TARGET_NAMESPACE

logger = logging.getLogger(__name__)


class SignalCollector:
    """Unified signal collector for all data sources."""

    def __init__(self, namespace: str = TARGET_NAMESPACE):
        self.namespace = namespace
        self.prometheus = PrometheusCollector()
        self.loki = LokiCollector()
        self.kubectl = KubectlCollector(namespace=namespace)
        self.gitops = GitOpsCollector()

    def collect_all(self, window_minutes: int = 5) -> dict:
        """Collect signals from all sources."""
        logger.info("Collecting signals (window=%dm)...", window_minutes)

        signals = {
            "metrics": self.prometheus.collect(
                namespace=self.namespace, window_minutes=window_minutes
            ),
            "logs": self.loki.collect(
                namespace=self.namespace,
                window_minutes=window_minutes,
                error_only=True,
            ),
            "kubectl": self.kubectl.collect(),
            "gitops": self.gitops.collect(),
        }

        logger.info("Signal collection complete")
        return signals

    def collect_observability_only(self, window_minutes: int = 5) -> dict:
        """System A: collect only observability signals (no GitOps)."""
        return {
            "metrics": self.prometheus.collect(
                namespace=self.namespace, window_minutes=window_minutes
            ),
            "logs": self.loki.collect(
                namespace=self.namespace,
                window_minutes=window_minutes,
                error_only=True,
            ),
            "kubectl": self.kubectl.collect(),
        }

    def collect_gitops_only(self) -> dict:
        """Collect only GitOps context."""
        return {"gitops": self.gitops.collect()}

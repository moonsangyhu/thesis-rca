"""Collector configuration."""
import os
from pathlib import Path

# KUBECONFIG
KUBECONFIG = os.environ.get("KUBECONFIG", str(Path.home() / ".kube" / "config-k8s-lab"))

# Prometheus
PROMETHEUS_URL = os.environ.get("PROMETHEUS_URL", "http://localhost:9090")

# Loki
LOKI_URL = os.environ.get("LOKI_URL", "http://localhost:3100")

# Namespaces
TARGET_NAMESPACE = "boutique"
MONITORING_NAMESPACE = "monitoring"
FLUX_NAMESPACE = "flux-system"
ARGOCD_NAMESPACE = "argocd"

# Collection timeouts (seconds)
QUERY_TIMEOUT = 30
COLLECTION_WINDOW = 300  # 5 minutes of data to collect after fault injection

# kubectl binary
KUBECTL = os.environ.get("KUBECTL", "kubectl")

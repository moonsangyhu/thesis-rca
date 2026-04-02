"""Fault injection configuration."""
import os
from pathlib import Path

KUBECONFIG = os.environ.get("KUBECONFIG", str(Path.home() / ".kube" / "config-k8s-lab"))
KUBECTL = os.environ.get("KUBECTL", "kubectl")
NAMESPACE = "boutique"
GIT_REPO_PATH = "/tmp/thesis-rca-work"

# SSH config for node-level operations (F4)
SSH_JUMP = "debian@211.62.97.71:22015"
WORKER_NODES = {
    "worker01": {"ip": "172.25.20.111", "ssh_user": "ktcloud", "proxy": "k8s-jump"},
    "worker02": {"ip": "172.25.20.112", "ssh_user": "ktcloud", "proxy": "k8s-jump"},
    "worker03": {"ip": "172.25.20.113", "ssh_user": "ktcloud", "proxy": "k8s-jump"},
}

# Wait time after injection before signal collection (seconds)
INJECTION_WAIT = {
    "F1": 120,   # OOMKilled: wait for restart cycle
    "F2": 120,   # CrashLoopBackOff: wait for backoff escalation
    "F3": 90,    # ImagePullBackOff: quick to manifest
    "F4": 180,   # NodeNotReady: node lease timeout ~40s + pod eviction
    "F5": 90,    # PVCPending: quick to manifest
    "F6": 60,    # NetworkPolicy: immediate effect
    "F7": 120,   # CPUThrottle: need load to manifest
    "F8": 60,    # ServiceEndpoint: immediate effect
    "F9": 90,    # SecretConfigMap: varies
    "F10": 90,   # ResourceQuota: immediate on new pod creation
}

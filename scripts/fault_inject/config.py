"""Fault injection configuration."""
import os
from pathlib import Path

KUBECONFIG = os.environ.get("KUBECONFIG", str(Path.home() / ".kube" / "config-k8s-lab"))
KUBECTL = os.environ.get("KUBECTL", "kubectl")
NAMESPACE = "boutique"
GIT_REPO_PATH = "/tmp/thesis-rca-work"

# SSH config for node-level operations (F4/F11/F12).
# Rebuilt direct K8s lab: each node is reached directly via host:port (no jump host).
# Keys are the Kubernetes node names as reported by `kubectl get nodes`.
WORKER_NODES = {
    "yms-proxmox-02": {"host": "211.62.97.71", "port": 22016, "ssh_user": "debian"},
    "yms-proxmox-03": {"host": "211.62.97.71", "port": 22017, "ssh_user": "debian"},
    "yms-proxmox-04": {"host": "211.62.97.71", "port": 22018, "ssh_user": "debian"},
    "yms-proxmox-05": {"host": "211.62.97.71", "port": 22019, "ssh_user": "debian"},
    "yms-proxmox-06": {"host": "211.62.97.71", "port": 22020, "ssh_user": "debian"},
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
    "F11": 120,  # NetworkDelay: wait for latency to propagate
    "F12": 120,  # NetworkLoss: wait for packet loss effects
}

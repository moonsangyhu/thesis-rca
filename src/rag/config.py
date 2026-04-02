"""RAG pipeline configuration."""
import os
from pathlib import Path

# Project root
PROJECT_ROOT = Path(__file__).parent.parent.parent

# Document paths
DOCS_DIR = PROJECT_ROOT / "docs"
DEBUGGING_DIR = DOCS_DIR / "debugging"
RUNBOOKS_DIR = DOCS_DIR / "runbooks"
KNOWN_ISSUES_DIR = DOCS_DIR / "known-issues"

# ChromaDB
CHROMA_DIR = PROJECT_ROOT / "data" / "chromadb"
COLLECTION_NAME = "k8s-rca-knowledge"

# Embedding model (local, no API key needed)
EMBEDDING_MODEL = "all-MiniLM-L6-v2"

# Chunking
CHUNK_SIZE = 512        # tokens
CHUNK_OVERLAP = 64      # tokens
MIN_CHUNK_SIZE = 100    # skip tiny chunks

# Retrieval
TOP_K = 5               # number of docs to retrieve
SCORE_THRESHOLD = 0.3   # minimum similarity score (cosine distance < 1 - threshold)

# Document categories and their weights for retrieval
DOC_CATEGORIES = {
    "debugging": 1.0,
    "runbooks": 1.2,    # slightly prefer actionable runbooks
    "known-issues": 1.1,
}

# Fault type mapping (F1~F10)
FAULT_TYPES = {
    "F1": {
        "name": "OOMKilled",
        "description": "Container memory limit exceeded, process killed by OOM killer",
        "keywords": ["OOMKilled", "memory", "limit", "killed", "137", "oom"],
    },
    "F2": {
        "name": "CrashLoopBackOff",
        "description": "Container repeatedly crashing and restarting",
        "keywords": ["CrashLoopBackOff", "crash", "restart", "exit code", "BackOff"],
    },
    "F3": {
        "name": "ImagePullBackOff",
        "description": "Container image cannot be pulled from registry",
        "keywords": ["ImagePullBackOff", "ErrImagePull", "registry", "pull", "image"],
    },
    "F4": {
        "name": "NodeNotReady",
        "description": "Node is not ready, workloads may be rescheduled",
        "keywords": ["NotReady", "node", "kubelet", "unreachable", "taint"],
    },
    "F5": {
        "name": "PVCPending",
        "description": "PersistentVolumeClaim stuck in Pending state",
        "keywords": ["PVC", "Pending", "storage", "provisioner", "PersistentVolume"],
    },
    "F6": {
        "name": "NetworkPolicy",
        "description": "Network connectivity blocked by NetworkPolicy or CNI issue",
        "keywords": ["NetworkPolicy", "blocked", "connection refused", "timeout", "Cilium"],
    },
    "F7": {
        "name": "CPUThrottle",
        "description": "Container CPU throttled due to resource limits",
        "keywords": ["throttled", "CPU", "cfs_throttled", "limit", "latency"],
    },
    "F8": {
        "name": "ServiceEndpoint",
        "description": "Service has no healthy endpoints or misconfigured selector",
        "keywords": ["endpoints", "selector", "service", "unreachable", "no endpoints"],
    },
    "F9": {
        "name": "SecretConfigMap",
        "description": "Secret or ConfigMap missing, wrong key, or failed injection",
        "keywords": ["Secret", "ConfigMap", "missing", "key", "env", "volume"],
    },
    "F10": {
        "name": "ResourceQuota",
        "description": "Namespace resource quota exceeded, new resources cannot be created",
        "keywords": ["ResourceQuota", "exceeded", "quota", "forbidden", "LimitRange"],
    },
}

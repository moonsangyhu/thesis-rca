# GitOps-Aware Kubernetes Root Cause Analysis

> **Thesis**: Evaluating the effectiveness of GitOps context integration in LLM-based root cause analysis for Kubernetes cluster failures

## Research Objective

Traditional Kubernetes RCA (Root Cause Analysis) relies on runtime observability alone — metrics, logs, and events. This research investigates whether augmenting LLM-based RCA with **GitOps context** (deployment history, manifest diffs, reconciliation state from FluxCD/ArgoCD) significantly improves diagnostic accuracy compared to observability-only approaches.

### Research Questions

| ID | Question |
|----|----------|
| **RQ1** | Does incorporating GitOps context (FluxCD/ArgoCD state, manifest diffs) improve LLM-based RCA accuracy compared to observability-only approaches? |
| **RQ2** | Which GitOps signals (deployment history, drift detection, reconciliation status) contribute most to RCA performance? |

### Experimental Design

**System A (Baseline)**: LLM + Prometheus metrics + Loki logs + kubectl events
**System B (Proposed)**: System A + FluxCD reconciliation state + ArgoCD sync status + Git commit diffs + RAG knowledge base

Both systems are evaluated against 10 fault types (F1–F10), each injected 5 times (50 total trials), with statistical validation via Wilcoxon signed-rank test.

## Fault Types (F1–F10)

| ID | Name | Description |
|----|------|-------------|
| F1 | OOMKilled | Container memory limit exceeded, OOM killer |
| F2 | CrashLoopBackOff | Application repeatedly crashing |
| F3 | ImagePullBackOff | Image registry pull failure |
| F4 | NodeNotReady | Node failure / network partition |
| F5 | PVCPending | Storage provisioning failure |
| F6 | NetworkPolicy | Network policy blocking connectivity |
| F7 | CPUThrottle | CPU resource contention / throttling |
| F8 | ServiceEndpoint | Service selector mismatch |
| F9 | SecretConfigMap | Secret/ConfigMap missing or misconfigured |
| F10 | ResourceQuota | Namespace resource quota exceeded |

## Cluster Environment

- **Kubernetes** v1.29.15 (kubeadm, 3 masters + 3 workers)
- **CNI**: Cilium 1.15.6 (VXLAN, MTU 1450)
- **GitOps**: FluxCD v2.3.0 + ArgoCD v7.9.1 (dual GitOps)
- **Monitoring**: kube-prometheus-stack v65.8.1 + Loki v6.55.0 + Promtail v6.17.1
- **Storage**: local-path-provisioner v0.0.28
- **Target Application**: Google Online Boutique (microservices demo)

## Repository Structure

```
.
├── README.md
├── docs/                    # RAG knowledge base (65 documents)
│   ├── debugging/           # Kubernetes failure debugging guides (20)
│   ├── runbooks/            # Fault-specific RCA runbooks (20)
│   └── known-issues/        # Known cluster issues and solutions (25)
├── k8s/                     # Kubernetes manifests (GitOps-managed)
│   ├── flux/                # FluxCD bootstrap and Kustomization CRs
│   ├── infrastructure/      # StorageClass, cluster-level resources
│   ├── monitoring/          # Prometheus, Loki, Promtail HelmReleases
│   ├── argocd/              # ArgoCD HelmRelease (dual GitOps)
│   └── app/                 # Online Boutique deployment (upcoming)
├── src/                     # Pipeline source code
│   ├── collector/           # Prometheus/Loki data collection
│   ├── processor/           # Feature extraction and preprocessing
│   ├── llm/                 # LLM-based RCA inference
│   └── rag/                 # ChromaDB RAG pipeline
├── scripts/                 # Experiment automation (upcoming)
│   ├── fault_inject/        # Fault injection scripts
│   ├── stabilize/           # Post-injection stabilization
│   └── evaluate/            # Evaluation and scoring
├── results/                 # Experiment results
│   └── ground_truth.csv     # 50 labeled fault cases (F1-F10 x 5)
├── configs/                 # Pipeline configuration
└── requirements.txt         # Python dependencies
```

## Experiment Workflow

```
1. Pre-check     → Verify cluster, monitoring, GitOps health
2. RAG Ingest    → Load 65 docs into ChromaDB (1,243 chunks)
3. Ground Truth  → Define 50 labeled fault cases (F1-F10 x 5 trials)
4. Deploy App    → Online Boutique via FluxCD HelmRelease
5. Inject Faults → F1-F10, compare System A vs B
6. Ablation      → AB-1 to AB-5 (isolate GitOps signal contributions)
7. Statistics    → Wilcoxon signed-rank test for significance
```

## Quick Start

```bash
# RAG knowledge base ingestion
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m src.rag.ingest --reset

# Cluster access (requires SSH tunnel)
ssh -N -f k8s-lab-tunnel
export KUBECONFIG=~/.kube/config-k8s-lab
kubectl get nodes
```

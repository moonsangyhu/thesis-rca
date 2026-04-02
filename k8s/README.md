# k8s/ — Kubernetes Manifests (GitOps-Managed)

## Purpose

All cluster infrastructure is declared here and deployed via **FluxCD GitOps**. FluxCD watches this repository and automatically reconciles cluster state to match these manifests. This is central to the thesis: the Git commit history and FluxCD reconciliation state captured here become **GitOps context signals** that System B uses for enhanced RCA.

Every infrastructure change flows through Git → FluxCD → cluster, producing an auditable deployment history that the RCA pipeline can correlate with failure events.

## Structure

```
k8s/
├── flux/                # FluxCD Kustomization CRs (orchestration layer)
│   ├── flux-system/     # FluxCD bootstrap components
│   ├── infrastructure/  # Points to ../infrastructure/
│   ├── monitoring/      # Points to ../monitoring/
│   └── argocd/          # Points to ../argocd/
├── infrastructure/      # Cluster-level resources
│   └── local-path-provisioner  # Default StorageClass (v0.0.28)
├── monitoring/          # Observability stack (HelmReleases)
│   ├── kube-prometheus-stack v65.8.1  # Prometheus, Grafana, node-exporter
│   ├── loki v6.55.0                   # Log aggregation (SingleBinary)
│   └── promtail v6.17.1              # Log shipping (DaemonSet)
├── argocd/              # ArgoCD for dual GitOps (v7.9.1)
└── app/                 # Online Boutique deployment (upcoming)
```

## Dependency Chain

```
flux-system → infrastructure → monitoring
                             → argocd
                             → app (planned)
```

FluxCD Kustomizations enforce ordering via `dependsOn` — monitoring and argocd only deploy after infrastructure (StorageClass) is ready.

## Dual GitOps Architecture

This experiment runs both **FluxCD** and **ArgoCD** simultaneously:

- **FluxCD**: Primary GitOps operator managing all infrastructure. Produces reconciliation events, Helm release state, and Kustomization health signals.
- **ArgoCD**: Secondary GitOps tool providing application sync status, drift detection, and resource tracking. Deployed *by* FluxCD.

Both tools generate GitOps signals (sync status, drift, reconciliation timing) that System B correlates with runtime failures for improved RCA.

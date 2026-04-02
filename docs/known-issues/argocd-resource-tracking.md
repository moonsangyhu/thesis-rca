# Known Issue: ArgoCD Resource Tracking Conflict with FluxCD

## Issue ID
KI-005

## Affected Components
- ArgoCD (v7.9.1)
- FluxCD v2 (Kustomize Controller, Helm Controller)
- All Kubernetes resources managed by both tools

## Symptoms
- ArgoCD Application shows resources as `OutOfSync` even when manifests match the Git source
- ArgoCD sync operations fail with:
  ```
  ComparisonError: failed to compare desired state to live state: resource is managed by another tool
  ```
- Resources show unexpected labels being added/removed during ArgoCD sync
- FluxCD reconciliation overwrites ArgoCD's tracking labels, causing oscillation
- `kubectl get <resource> -o yaml` shows conflicting annotations/labels from both controllers
- ArgoCD health check shows `Degraded` state cycling back to `Progressing`

## Root Cause
ArgoCD uses two resource tracking modes:
1. **Label tracking** (default): Adds `app.kubernetes.io/instance: <app-name>` label to every managed resource
2. **Annotation tracking**: Adds `argocd.argoproj.io/tracking-id` annotation instead

When ArgoCD uses label tracking (default) alongside FluxCD, the following conflict occurs:
- FluxCD manages resources and owns their label set as defined in Git
- ArgoCD adds its tracking label to live resources
- FluxCD sees the added label as drift from the Git state and removes it on next reconcile
- ArgoCD detects the missing tracking label and marks the resource as OutOfSync
- This creates an infinite oscillation loop

Additionally, `app.kubernetes.io/instance` is a standard Helm label that FluxCD's Helm controller already sets to the HelmRelease name. ArgoCD attempts to overwrite this with the Application name, causing a conflict on the value itself.

## Diagnostic Commands
```bash
# Check ArgoCD application sync status
kubectl -n argocd get applications
argocd app list  # if argocd CLI is available

# Look for conflicting labels/annotations
kubectl get deployment <name> -n <namespace> -o yaml | grep -A20 "metadata:"

# Check ArgoCD tracking mode
kubectl -n argocd get configmap argocd-cm -o yaml | grep "application.resourceTrackingMethod"

# Check FluxCD kustomization status
kubectl get kustomization -A
flux get all -A

# Watch for oscillation (reconcile loop)
kubectl get events -n <namespace> --watch | grep -i "argocd\|flux"
```

## Resolution
Switch ArgoCD to annotation-based tracking mode, which avoids modifying resource labels.

**Step 1**: Edit the ArgoCD ConfigMap:
```bash
kubectl -n argocd edit configmap argocd-cm
```

**Step 2**: Add or update the tracking method:
```yaml
data:
  application.resourceTrackingMethod: annotation
```

**Step 3**: Restart ArgoCD application controller to pick up the change:
```bash
kubectl -n argocd rollout restart deployment/argocd-application-controller
kubectl -n argocd rollout restart statefulset/argocd-application-controller
# (depends on ArgoCD version — check what's deployed)
kubectl -n argocd rollout status deployment/argocd-repo-server
```

**Step 4**: Force re-sync ArgoCD applications to re-establish tracking via annotations:
```bash
argocd app sync <app-name> --force
# Or via kubectl
kubectl -n argocd patch application <app-name> \
  --type merge -p '{"operation": {"sync": {"syncStrategy": {"force": {"force": true}}}}}'
```

**Step 5**: Verify no more OutOfSync state:
```bash
kubectl -n argocd get applications
# All should show Synced / Healthy
```

## Workaround
If switching tracking modes is not immediately feasible:
1. Remove the conflicting resources from ArgoCD's scope by adding them to `spec.ignoreDifferences`:
```yaml
spec:
  ignoreDifferences:
  - group: apps
    kind: Deployment
    jsonPointers:
    - /metadata/labels/app.kubernetes.io~1instance
```
2. This prevents ArgoCD from trying to reconcile the label back, but is not a permanent fix.

## Prevention
- In multi-tool GitOps environments (FluxCD + ArgoCD), always configure ArgoCD with `application.resourceTrackingMethod: annotation` from the start
- Clearly define ownership boundaries: which namespaces are managed by Flux vs ArgoCD
- Use namespace-scoped ArgoCD projects to prevent accidental overlap
- Document resource ownership in cluster README

## References
- ArgoCD resource tracking: https://argo-cd.readthedocs.io/en/stable/user-guide/resource_tracking/
- ArgoCD + Flux coexistence: https://fluxcd.io/flux/use-cases/argocd/
- ArgoCD annotation tracking: https://argo-cd.readthedocs.io/en/stable/operator-manual/app-any-namespace/

# Debugging FluxCD Issues

## Overview
FluxCD is a GitOps operator that reconciles cluster state with Git repository declarations. Issues typically involve source fetching, Kustomization reconciliation, or HelmRelease lifecycle failures. This guide covers common FluxCD v2.3.0 troubleshooting patterns.

## Symptoms
- Kustomization stuck in `Reconciliation in progress` or `False` ready state
- HelmRelease showing `pending-install`, `pending-upgrade`, or `failed`
- Source-controller unable to fetch Git repository or Helm chart
- Cluster state drifting from Git (manual changes not reverted)
- Events: `context deadline exceeded`, `artifact not found`

## Diagnostic Commands

```bash
# Check all Flux resources status
flux get all

# Check source sync status
flux get sources git
flux get sources helm

# Check Kustomization status
flux get kustomizations
kubectl get kustomization -n flux-system -o wide

# Check HelmRelease status
flux get helmreleases -A
kubectl get helmrelease -A -o wide

# Detailed status with conditions
kubectl describe kustomization <name> -n flux-system
kubectl describe helmrelease <name> -n <ns>

# Source-controller logs (artifact fetch issues)
kubectl logs -n flux-system deploy/source-controller --tail=50

# Kustomize-controller logs (reconciliation issues)
kubectl logs -n flux-system deploy/kustomize-controller --tail=50

# Helm-controller logs (HelmRelease issues)
kubectl logs -n flux-system deploy/helm-controller --tail=50

# Check Flux component health
flux check

# Force reconciliation
flux reconcile source git flux-system
flux reconcile kustomization <name>
flux reconcile helmrelease <name> -n <ns>
```

## Common Causes

### 1. HelmRelease stuck in pending-install
First install timed out, leaving Helm release in broken state.
```bash
# Check Helm secrets
kubectl get secrets -n <ns> -l owner=helm,name=<release>

# Fix: delete the stuck Helm secret and force reconcile
kubectl delete secret -n <ns> sh.helm.release.v1.<name>.v1
kubectl annotate helmrelease <name> -n <ns> \
  reconcile.fluxcd.io/requestedAt="$(date -u +%Y-%m-%dT%H:%M:%SZ)" --overwrite
```

### 2. Source fetch failure (artifact not found)
Source-controller cannot reach Git repository or Helm registry.
```bash
# Check source-controller logs
kubectl logs -n flux-system deploy/source-controller | grep -i "error\|fail"

# Verify Git repo accessibility
kubectl get gitrepository flux-system -n flux-system -o yaml | grep -A5 "status:"

# Network issue: check cross-node connectivity (Cilium MTU)
kubectl exec -n flux-system deploy/source-controller -- wget -qO- https://github.com 2>&1 | head -5
```

### 3. Kustomization build error
Invalid YAML, missing resources, or Kustomize patch conflict.
```bash
# Check the error message
kubectl get kustomization <name> -n flux-system -o jsonpath='{.status.conditions[0].message}'

# Validate locally
kustomize build k8s/monitoring/
```

### 4. Dependency not ready
Kustomization or HelmRelease with `dependsOn` waiting for prerequisite.
```bash
kubectl get kustomization -n flux-system -o custom-columns=\
NAME:.metadata.name,READY:.status.conditions[0].status,DEPENDS:.spec.dependsOn[*].name
```

### 5. Suspended resources
Resources manually suspended won't reconcile.
```bash
flux get all --status-selector ready=false | grep -i suspended
flux resume kustomization <name>
flux resume helmrelease <name> -n <ns>
```

## Resolution Steps

### Force full re-reconciliation
```bash
# Trigger Git source update
flux reconcile source git flux-system

# Wait for source, then reconcile downstream
flux reconcile kustomization flux-system
flux reconcile kustomization monitoring
```

### Reset a failed HelmRelease
```bash
# Suspend → delete Helm secrets → resume
flux suspend helmrelease <name> -n <ns>
kubectl delete secret -n <ns> -l owner=helm,name=<name>
flux resume helmrelease <name> -n <ns>
```

### Rollback HelmRelease
```bash
# Check release history
helm history <name> -n <ns>
# Flux will auto-rollback if upgrade.remediation.strategy=rollback is set
```

## Prevention
- Set `install.remediation.retries` and `upgrade.remediation.strategy: rollback`
- Use `dependsOn` for ordering (e.g., infrastructure before apps)
- Pin chart versions with semver ranges (e.g., `>=7.0.0 <8.0.0`)
- Monitor Flux metrics: `gotk_reconcile_condition`, `gotk_reconcile_duration_seconds`
- Set health checks on Kustomizations for deployment readiness validation

## Related Issues
- [FluxCD Pending Install](../known-issues/flux-pending-install.md)
- [Helm Release Timeout](../known-issues/helm-release-timeout.md)
- [GitOps Drift Detection](../known-issues/gitops-drift-detection.md)
- [Kustomize Patch Conflict](../known-issues/kustomize-patch-conflict.md)

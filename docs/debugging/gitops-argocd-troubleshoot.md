# Debugging ArgoCD Issues

## Overview
ArgoCD is a declarative GitOps continuous delivery tool. In this dual GitOps setup (FluxCD manages infrastructure, ArgoCD manages applications), common issues include sync failures, resource tracking conflicts, and RBAC permission errors.

## Symptoms
- Application showing `OutOfSync` status that won't resolve
- Sync failed: `ComparisonError`, `one or more objects failed to apply`
- Application health: `Degraded`, `Missing`, or `Unknown`
- ArgoCD UI showing `Unable to load data`
- Repo connection failed: `repository not accessible`
- Resources managed by both FluxCD and ArgoCD conflicting

## Diagnostic Commands

```bash
# Check ArgoCD application status
kubectl get applications -n argocd
kubectl describe application <name> -n argocd

# ArgoCD CLI (if installed)
argocd app list
argocd app get <name>
argocd app diff <name>

# Check sync status and conditions
kubectl get application <name> -n argocd -o jsonpath='{.status.sync.status}'
kubectl get application <name> -n argocd -o jsonpath='{.status.health.status}'
kubectl get application <name> -n argocd -o jsonpath='{.status.conditions}'

# Check ArgoCD component logs
kubectl logs -n argocd deploy/argocd-server --tail=50
kubectl logs -n argocd deploy/argocd-repo-server --tail=50
kubectl logs -n argocd deploy/argocd-application-controller --tail=50

# Check repo connectivity
kubectl get secret -n argocd -l argocd.argoproj.io/secret-type=repository
argocd repo list

# Check RBAC
kubectl auth can-i '*' '*' --as=system:serviceaccount:argocd:argocd-application-controller

# Resource tracking mode
kubectl get configmap argocd-cm -n argocd -o yaml | grep tracking
```

## Common Causes

### 1. OutOfSync due to server-side defaults
Kubernetes API adds default fields (e.g., `strategy`, `dnsPolicy`) that don't exist in Git manifests, causing permanent OutOfSync.

```bash
# Check diff
argocd app diff <name> --local ./manifests/

# Fix: use ignoreDifferences in Application spec
spec:
  ignoreDifferences:
    - group: apps
      kind: Deployment
      jsonPointers:
        - /spec/revisionHistoryLimit
        - /spec/template/spec/dnsPolicy
```

### 2. Resource tracking conflict with FluxCD
Both FluxCD and ArgoCD try to manage the same resource.

```bash
# Check for FluxCD labels/annotations on the resource
kubectl get deployment <name> -n <ns> -o yaml | grep -E "fluxcd|kustomize.toolkit"

# Fix: use annotation-based tracking (avoids label conflicts)
kubectl edit configmap argocd-cm -n argocd
# Add: application.resourceTracking: annotation
```

### 3. Repository connection failure
```bash
# Check repo server logs
kubectl logs -n argocd deploy/argocd-repo-server | grep -i "error\|fail"

# Test git connectivity from repo-server
kubectl exec -n argocd deploy/argocd-repo-server -- \
  git ls-remote https://github.com/moonsangyhu/thesis-rca.git HEAD

# Check/recreate repo secret
argocd repo add https://github.com/moonsangyhu/thesis-rca.git --username <user> --password <token>
```

### 4. RBAC insufficient permissions
ArgoCD application-controller needs cluster-admin or specific RBAC to manage resources.
```bash
# Check what controller can do
kubectl auth can-i create deployments --as=system:serviceaccount:argocd:argocd-application-controller -n boutique

# If using AppProject with destination restrictions
kubectl get appproject default -n argocd -o yaml | grep -A20 "destinations"
```

### 5. Sync retry loop / auto-heal conflict
Auto-sync with self-heal enabled + external operator modifying same resources = infinite sync loop.
```yaml
spec:
  syncPolicy:
    automated:
      selfHeal: true  # ArgoCD reverts manual/external changes
      prune: true
    retry:
      limit: 5
```

## Resolution Steps

### Force sync
```bash
argocd app sync <name> --force --replace
# Or via kubectl
kubectl patch application <name> -n argocd --type merge \
  -p '{"operation":{"initiatedBy":{"username":"admin"},"sync":{"revision":"HEAD"}}}'
```

### Hard refresh (clear cache)
```bash
argocd app get <name> --hard-refresh
```

### Reset application
```bash
argocd app delete <name> --cascade=false  # delete ArgoCD app but keep K8s resources
argocd app create <name> ...              # recreate
```

## Prevention
- Use annotation-based resource tracking when coexisting with FluxCD
- Define `ignoreDifferences` for known server-side defaults
- Separate ArgoCD and FluxCD management domains (different namespaces/resources)
- Monitor application sync status:
  ```promql
  argocd_app_info{sync_status="OutOfSync"} > 0
  argocd_app_info{health_status!="Healthy"} > 0
  ```

## Related Issues
- [ArgoCD Resource Tracking](../known-issues/argocd-resource-tracking.md)
- [GitOps Drift Detection](../known-issues/gitops-drift-detection.md)
- [RBAC Insufficient Permissions](../known-issues/rbac-insufficient-permissions.md)

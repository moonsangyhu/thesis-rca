# Runbook: FluxCD HelmRelease Recovery

## Trigger Conditions
- HelmRelease stuck in `pending-install` or `pending-upgrade`
- HelmRelease showing `install retries exhausted` or `upgrade retries exhausted`
- Helm chart install/upgrade timeout exceeded
- Manual Helm state corruption (partial install, dangling secrets)

## Severity
High (blocks GitOps deployments)

## Estimated Resolution Time
5-15 minutes

## Prerequisites
- kubectl access to flux-system and target namespace
- FluxCD CLI (`flux`) optional but helpful
- Understanding of Helm release lifecycle (install → installed, upgrade → deployed)

## Investigation Steps

### Step 1: Check HelmRelease status
```bash
# Overview of all HelmReleases
kubectl get helmrelease -A

# Detailed status
kubectl describe helmrelease <name> -n <ns>

# Status conditions
kubectl get helmrelease <name> -n <ns> -o jsonpath='{.status.conditions[*]}' | python3 -m json.tool

# Last attempted values
kubectl get helmrelease <name> -n <ns> -o jsonpath='{.status.lastAttemptedRevision}'
```

### Step 2: Check helm-controller logs
```bash
# Helm controller logs for the specific release
kubectl logs -n flux-system deploy/helm-controller | grep <release-name> | tail -20

# Error-only
kubectl logs -n flux-system deploy/helm-controller | grep -i "error\|fail" | tail -20
```

### Step 3: Check Helm release secrets
```bash
# Helm stores release state in secrets
kubectl get secrets -n <ns> -l owner=helm,name=<release-name>

# Check release status (deployed, pending-install, failed, etc.)
kubectl get secrets -n <ns> -l owner=helm,name=<release-name> \
  -o jsonpath='{range .items[*]}{.metadata.name}: {.metadata.labels.status}{"\n"}{end}'
```

### Step 4: Check if chart is available
```bash
# Check HelmRepository
kubectl get helmrepository -A
kubectl describe helmrepository <repo> -n <ns>

# Check if source-controller fetched the chart
kubectl logs -n flux-system deploy/source-controller | grep <chart-name> | tail -10
```

## Resolution

### Fix: pending-install (first install timed out)
This is the most common issue. The first install exceeded the timeout, leaving Helm in a broken state.

```bash
# 1. Suspend the HelmRelease to stop Flux retries
flux suspend helmrelease <name> -n <ns>
# Or: kubectl patch helmrelease <name> -n <ns> --type merge -p '{"spec":{"suspend":true}}'

# 2. Delete the stuck Helm secret
kubectl delete secret -n <ns> sh.helm.release.v1.<name>.v1

# 3. Delete any partially-created resources (StatefulSets, Deployments, etc.)
kubectl delete statefulset,deployment,service -n <ns> -l app.kubernetes.io/instance=<name>

# 4. Resume the HelmRelease
flux resume helmrelease <name> -n <ns>

# 5. Force reconcile
kubectl annotate helmrelease <name> -n <ns> \
  reconcile.fluxcd.io/requestedAt="$(date -u +%Y-%m-%dT%H:%M:%SZ)" --overwrite

# 6. Watch progress
kubectl get helmrelease <name> -n <ns> -w
```

### Fix: pending-upgrade (upgrade timed out)
```bash
# 1. Check current Helm release version
kubectl get secrets -n <ns> -l owner=helm,name=<name> --sort-by=.metadata.creationTimestamp

# 2. Delete the latest (pending) secret only
kubectl delete secret -n <ns> sh.helm.release.v1.<name>.v<latest>

# 3. Force reconcile
kubectl annotate helmrelease <name> -n <ns> \
  reconcile.fluxcd.io/requestedAt="$(date -u +%Y-%m-%dT%H:%M:%SZ)" --overwrite
```

### Fix: install retries exhausted
```bash
# Reset the failure count by suspending and resuming
flux suspend helmrelease <name> -n <ns>
flux resume helmrelease <name> -n <ns>

# If the underlying issue is fixed, it will retry
```

### Fix: chart fetch failure
```bash
# Force source update
flux reconcile source helm <repo-name> -n <ns>

# Check connectivity from source-controller
kubectl exec -n flux-system deploy/source-controller -- \
  wget -qO- --timeout=10 https://argoproj.github.io/argo-helm/index.yaml | head -5
```

### Fix: increase timeout for large charts
```yaml
# In HelmRelease spec
spec:
  install:
    timeout: 10m    # increase from default 5m
    remediation:
      retries: 3
  upgrade:
    timeout: 10m
    cleanupOnFail: true
    remediation:
      strategy: rollback
      retries: 3
```

### Nuclear option: full reset
```bash
# 1. Suspend
flux suspend helmrelease <name> -n <ns>

# 2. Uninstall via Helm directly
helm uninstall <name> -n <ns>

# 3. Clean up any remaining resources
kubectl delete all -n <ns> -l app.kubernetes.io/instance=<name>

# 4. Delete all Helm secrets for this release
kubectl delete secrets -n <ns> -l owner=helm,name=<name>

# 5. Resume Flux (will do a fresh install)
flux resume helmrelease <name> -n <ns>
```

## Verification
```bash
# HelmRelease should be Ready=True
kubectl get helmrelease <name> -n <ns>

# All pods running
kubectl get pods -n <ns> -l app.kubernetes.io/instance=<name>

# Kustomization should also be healthy
kubectl get kustomization -n flux-system
```

## Loki Queries
```logql
# Helm controller errors
{namespace="flux-system", app="helm-controller"} |~ "(?i)(error|fail|timeout)" | logfmt | release=~".*<name>.*"

# Source controller chart fetch issues
{namespace="flux-system", app="source-controller"} |~ "(?i)(error|fetch|artifact)" | logfmt
```

## Prometheus Queries
```promql
# HelmRelease reconciliation failures
gotk_reconcile_condition{type="Ready", status="False", kind="HelmRelease"}

# Reconciliation duration (detect timeouts)
gotk_reconcile_duration_seconds{kind="HelmRelease"} > 300
```

## Escalation
If HelmRelease issues persist after reset:
1. Check helm-controller resource limits (may need more memory for large charts)
2. Check source-controller disk space (artifact cache)
3. Verify chart compatibility with cluster K8s version

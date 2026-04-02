# Known Issue: FluxCD HelmRelease Stuck in pending-install

## Issue ID
KI-004

## Affected Components
- FluxCD v2 Helm Controller
- HelmRelease custom resource
- Helm release secrets (`sh.helm.release.v1.*`)

## Symptoms
- `kubectl get helmrelease -A` shows status `False` with reason `pending-install`:
  ```
  NAME    READY   STATUS                      AGE
  loki    False   HelmRelease not ready       45m
  ```
- `kubectl describe helmrelease <name>` shows:
  ```
  Status:
    Conditions:
    - Message: Helm install failed: another operation (install/upgrade/rollback) is in progress
      Reason: AnotherOperationInProgress
      Status: "False"
      Type: Ready
  ```
- Helm controller logs show:
  ```
  helm install failed: another operation (install/upgrade/rollback) is in progress
  ```
- The HelmRelease never progresses even after waiting
- `helm list -n <namespace>` shows the release in `pending-install` state

## Root Cause
When a Helm release installation is interrupted mid-flight (e.g., helm-controller pod restart, node failure, timeout during CRD installation), Helm writes a release secret with status `pending-install` but never completes the transaction. Helm's locking mechanism prevents any new install/upgrade/rollback from proceeding while this pending secret exists.

FluxCD's Helm controller respects Helm's own locking mechanism and will not force-clear this state automatically (to avoid data loss in legitimate concurrent operations). The controller repeatedly attempts reconciliation but always encounters the lock, causing the HelmRelease to remain stuck indefinitely.

In this cluster, this occurred when:
1. The initial Loki HelmRelease timed out (default 5 minute timeout exceeded due to slow image pulls)
2. The Prometheus stack HelmRelease had its controller pod restarted during initial CRD installation

The pending-install secret was left behind:
```bash
kubectl -n monitoring get secrets | grep sh.helm.release
# sh.helm.release.v1.loki.v1   helm.sh/release.v1   1      67m
```

## Diagnostic Commands
```bash
# Check HelmRelease status
kubectl get helmrelease -A
kubectl describe helmrelease <release-name> -n <namespace>

# Check Helm release secrets
kubectl -n <namespace> get secrets -l owner=helm
# or
kubectl -n <namespace> get secrets | grep sh.helm.release

# Check Helm release state
helm list -n <namespace> --all
helm status <release-name> -n <namespace>

# Check Flux Helm controller logs
kubectl -n flux-system logs deployment/helm-controller --tail=100 | grep -i "pending\|error\|failed"

# List all StatefulSets/Deployments that may be in broken state
kubectl -n <namespace> get all
```

## Resolution
This issue was resolved in this cluster by deleting the stale Helm secret and orphaned resources, then forcing a reconciliation.

**Step 1**: Suspend the HelmRelease to prevent interference during cleanup:
```bash
flux suspend helmrelease <release-name> -n <namespace>
```

**Step 2**: Delete the stale Helm release secret(s):
```bash
# List all Helm secrets for this release
kubectl -n <namespace> get secrets | grep "sh.helm.release.v1.<release-name>"

# Delete them (replace <release-name> and version numbers as needed)
kubectl -n <namespace> delete secret sh.helm.release.v1.<release-name>.v1
# Delete any additional versions (v2, v3, etc.) if present
```

**Step 3**: Delete any partially-created resources (StatefulSets, Deployments, etc.) that may conflict with a fresh install:
```bash
# Example for Loki
kubectl -n monitoring delete statefulset loki --ignore-not-found
kubectl -n monitoring delete pods -l app.kubernetes.io/name=loki --force --grace-period=0
```

**Step 4**: Resume and force reconcile:
```bash
flux resume helmrelease <release-name> -n <namespace>
flux reconcile helmrelease <release-name> -n <namespace> --force
```

**Step 5**: Monitor until the release succeeds:
```bash
kubectl get helmrelease <release-name> -n <namespace> -w
# Expected: READY=True, STATUS=Helm install succeeded
```

## Workaround
If the above fails, completely uninstall using Helm directly and let Flux reinstall:
```bash
# Suspend Flux reconciliation first
flux suspend helmrelease <release-name> -n <namespace>

# Force uninstall via Helm
helm uninstall <release-name> -n <namespace>

# Delete all remaining resources in the namespace if needed
kubectl delete all -l app.kubernetes.io/instance=<release-name> -n <namespace>

# Resume Flux
flux resume helmrelease <release-name> -n <namespace>
```

## Prevention
- Increase the HelmRelease `spec.install.timeout` for large charts:
  ```yaml
  spec:
    install:
      timeout: 15m
    upgrade:
      timeout: 15m
  ```
- Pre-pull large container images before deploying HelmReleases
- Avoid interrupting the Flux helm-controller during active installations
- Monitor `kubectl get helmrelease -A` in CI/CD pipelines after deployments

## References
- FluxCD HelmRelease API: https://fluxcd.io/flux/components/helm/helmreleases/
- Helm troubleshooting: https://helm.sh/docs/faq/troubleshooting/#helm-is-locked-unable-to-install-or-upgrade
- Flux troubleshooting guide: https://fluxcd.io/flux/cheatsheets/troubleshooting/

# Known Issue: HelmRelease Install Timeout Exceeded

## Issue ID
KI-021

## Affected Components
- FluxCD Helm Controller
- HelmRelease custom resource
- Large Helm charts (Prometheus stack, Loki, ArgoCD)
- Nodes with slow image pull throughput

## Symptoms
- HelmRelease status shows `False` with install timeout message:
  ```
  install retries exhausted
  Helm install failed: context deadline exceeded
  ```
- `kubectl get helmrelease -A` shows READY=False for the release
- Flux Helm controller logs show:
  ```
  helmrelease/monitoring/kube-prometheus-stack: install failed: context deadline exceeded
  ```
- Resources are partially created (some CRDs installed, some Deployments missing)
- The HelmRelease enters `failed` state and stops retrying until manually reconciled
- Pods related to the chart are stuck in `Pending` or `ContainerCreating` (image pulling)

## Root Cause
FluxCD's HelmRelease has a default install timeout of **5 minutes** (`spec.install.timeout: 5m0s`). This default is insufficient for large Helm charts or slow environments:

**Large Helm charts**: The `kube-prometheus-stack` chart installs 30+ CRDs plus numerous Deployments, StatefulSets, and DaemonSets. Creating all these resources plus waiting for them to become ready often exceeds 5 minutes.

**Slow image pulls**: If the container registry is remote or the node has limited bandwidth, pulling large images (Prometheus, Grafana, Alertmanager, etc.) can take 10-20+ minutes on first installation.

**CRD establishment delay**: Helm 3 waits for CRDs to be established (GET returns successfully) before proceeding with dependent resources. In slow API servers, CRD registration can take longer than expected.

**Helm's atomic install behavior**: With `atomic: true`, a failed install triggers an automatic rollback, which also counts against the timeout. This can cause the timeout to trigger mid-rollback.

Default HelmRelease spec (implicitly):
```yaml
spec:
  install:
    timeout: 5m0s    # Default — too short for large charts
    remediation:
      retries: 3     # Retries 3 times then gives up
  upgrade:
    timeout: 5m0s
```

## Diagnostic Commands
```bash
# Check HelmRelease status
kubectl get helmrelease -A
kubectl describe helmrelease <name> -n <namespace>

# Get detailed status
kubectl get helmrelease <name> -n <namespace> -o yaml | grep -A30 "status:"

# Check Flux Helm controller logs
kubectl -n flux-system logs deployment/helm-controller --tail=100

# Monitor image pull progress
kubectl -n <namespace> get pods
kubectl -n <namespace> describe pod <pod-name> | grep -A10 "Events:"

# Check how long image pulls are taking
kubectl -n <namespace> get events | grep -i "pull\|pulling"

# Check if CRDs were created
kubectl get crd | grep <chart-name>

# Check Helm release status directly
helm list -n <namespace> --all
helm status <release-name> -n <namespace>
```

## Resolution
**Step 1**: Increase the timeout in the HelmRelease spec:
```yaml
apiVersion: helm.toolkit.fluxcd.io/v2
kind: HelmRelease
metadata:
  name: kube-prometheus-stack
  namespace: monitoring
spec:
  interval: 30m
  timeout: 20m              # Increase from default 5m
  install:
    timeout: 20m            # Install-specific timeout
    remediation:
      retries: 3
      remediateLastFailure: true
  upgrade:
    timeout: 20m            # Upgrade-specific timeout
    remediation:
      retries: 3
      remediateLastFailure: true
  chart:
    spec:
      chart: kube-prometheus-stack
      version: ">=55.0.0"
      sourceRef:
        kind: HelmRepository
        name: prometheus-community
```

**Step 2**: For immediate recovery, clean up the failed state and force reconcile:
```bash
# Suspend the HelmRelease
flux suspend helmrelease <name> -n <namespace>

# Delete any stale Helm secrets
kubectl -n <namespace> get secrets -l owner=helm
kubectl -n <namespace> delete secret sh.helm.release.v1.<name>.v1

# Resume and force reconcile
flux resume helmrelease <name> -n <namespace>
flux reconcile helmrelease <name> -n <namespace> --force
```

**Step 3**: Pre-pull images on nodes before deploying large charts (optional but effective):
```bash
# On each node, pre-pull heavy images
ssh worker01 "sudo crictl pull quay.io/prometheus/prometheus:v2.49.1"
ssh worker01 "sudo crictl pull grafana/grafana:10.2.3"
```

**Step 4**: Monitor the installation progress:
```bash
kubectl get helmrelease <name> -n <namespace> -w
# Watch for READY=True
```

## Workaround
Deploy the Helm chart directly using the Helm CLI (bypassing FluxCD timeout constraints) and then let FluxCD take over management:
```bash
helm upgrade --install <release-name> <chart> \
  -n <namespace> \
  --timeout 30m \
  --wait \
  -f values.yaml
```
After Helm install succeeds, apply the HelmRelease with `spec.install.skipCRDs: true` to prevent duplicate CRD installation.

## Prevention
- Set appropriate timeouts in HelmRelease specs based on chart complexity:
  - Simple charts: 10m
  - Medium charts (ArgoCD, Loki): 15m
  - Large charts (kube-prometheus-stack): 20-30m
- Pre-pull images on cluster nodes before scheduled deployments
- Use `spec.install.remediation.retries: -1` for indefinite retries in lab environments
- Add image registry mirror to reduce pull times in production environments

## References
- FluxCD HelmRelease API reference: https://fluxcd.io/flux/components/helm/helmreleases/
- Helm install timeout: https://helm.sh/docs/helm/helm_install/
- FluxCD troubleshooting: https://fluxcd.io/flux/cheatsheets/troubleshooting/

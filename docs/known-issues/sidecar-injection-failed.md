# Known Issue: Service Mesh Sidecar Injection Failure

## Issue ID
KI-020

## Affected Components
- Istio / Linkerd sidecar injection
- MutatingWebhookConfiguration
- Namespace labels for injection control
- Pods with explicit injection opt-out annotations

## Symptoms
- Pods start without the expected sidecar proxy container (no `istio-proxy` or `linkerd-proxy` container)
- `kubectl get pods -n <namespace>` shows pods with `1/1` READY instead of `2/2`
- mTLS fails between services that should be in the mesh
- Traffic is not appearing in the service mesh observability dashboard (Kiali, Jaeger)
- Some pods in the namespace have sidecars while others do not (inconsistent injection)
- Admission webhook errors in pod events:
  ```
  Warning  FailedCreate  mutating webhook "istio-sidecar-injector.istio.io" denied the request: ...
  ```
- After upgrading Istio/Linkerd, existing pods do not get updated sidecar versions

## Root Cause
Service mesh sidecar injection is handled by a `MutatingWebhookConfiguration` that intercepts pod creation requests and injects the sidecar container. Injection fails or is skipped due to several conditions:

**Cause 1: Missing namespace label**
Istio requires the namespace to have `istio-injection: enabled` label. Linkerd requires `linkerd.io/inject: enabled`. Without these labels, the webhook ignores all pods in the namespace.
```bash
# Namespace without injection label — no injection happens
kubectl get namespace <ns> --show-labels | grep inject
# (no output)
```

**Cause 2: Pod-level opt-out annotation**
Individual pods can override namespace-level injection:
```yaml
metadata:
  annotations:
    sidecar.istio.io/inject: "false"   # Explicitly disabled on this pod
```
This is sometimes left in manifests by mistake after initial debugging.

**Cause 3: Webhook selector not matching**
`MutatingWebhookConfiguration` uses `namespaceSelector` and `objectSelector`. If the namespace label or pod annotation doesn't match the webhook selector, the webhook is never invoked.

**Cause 4: Webhook service unavailable**
If the Istio control plane (`istiod`) or Linkerd control plane is not running, the webhook fails. Depending on `failurePolicy`:
- `Fail`: Pod creation is blocked entirely
- `Ignore`: Pod is created without sidecar

**Cause 5: Injection disabled in control plane config**
Global injection can be disabled in `istio-system/istio` ConfigMap.

## Diagnostic Commands
```bash
# Check namespace labels for injection
kubectl get namespace <ns> --show-labels | grep -i inject

# Check all namespaces for injection labels
kubectl get namespaces --show-labels | grep inject

# Check pod annotations
kubectl get pod <pod-name> -n <namespace> -o yaml | grep -i inject

# List containers in a pod (check if sidecar is present)
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].name}'

# Check MutatingWebhookConfiguration
kubectl get mutatingwebhookconfigurations | grep -i istio
kubectl describe mutatingwebhookconfiguration istio-sidecar-injector | grep -A10 "Namespace Selector"

# Check istiod / control plane status
kubectl -n istio-system get pods
kubectl -n istio-system logs deployment/istiod | grep -i "inject\|webhook\|error"

# Check webhook endpoints
kubectl -n istio-system get svc istiod

# Verify injection would be triggered for a namespace
istioctl analyze -n <namespace>  # if istioctl is available

# For Linkerd
kubectl -n linkerd get pods
linkerd check  # if linkerd CLI available
```

## Resolution
**Fix for missing namespace label (Istio)**:
```bash
# Enable injection for the namespace
kubectl label namespace <namespace> istio-injection=enabled

# Verify
kubectl get namespace <namespace> --show-labels | grep istio-injection

# Restart existing pods to get sidecar injected
kubectl rollout restart deployment/<name> -n <namespace>
# Or restart all deployments in namespace
kubectl -n <namespace> rollout restart deployment
```

**Fix for missing namespace label (Linkerd)**:
```bash
kubectl annotate namespace <namespace> linkerd.io/inject=enabled
kubectl rollout restart deployment -n <namespace>
```

**Fix for pod-level opt-out annotation**:
```bash
# Remove the annotation from the Deployment template
kubectl patch deployment <name> -n <namespace> --type=json \
  -p='[{"op":"remove","path":"/spec/template/metadata/annotations/sidecar.istio.io~1inject"}]'
kubectl rollout restart deployment/<name> -n <namespace>
```

**Fix for webhook service unavailable**:
```bash
# Check istiod health
kubectl -n istio-system get pods -l app=istiod
kubectl -n istio-system describe pod <istiod-pod>

# Restart istiod if unhealthy
kubectl -n istio-system rollout restart deployment/istiod
```

**Verify injection after fix**:
```bash
kubectl get pod <new-pod> -n <namespace> -o jsonpath='{.spec.containers[*].name}'
# Expected: app istio-proxy
```

## Workaround
For immediate testing without mesh, use `istioctl kube-inject` to manually inject sidecar into a manifest:
```bash
istioctl kube-inject -f deployment.yaml | kubectl apply -f -
```
This is not recommended for production but is useful for one-off debugging.

## Prevention
- Add namespace injection label as part of namespace provisioning automation
- Include `istioctl analyze` or `linkerd check` in deployment CI/CD pipelines
- Monitor sidecar injection ratio: `(pods with sidecar) / (total pods in mesh namespaces)` — alert if < 100%
- After Istio/Linkerd upgrade, verify all pods are restarted and get new sidecar versions
- Document which namespaces are in-mesh and which are intentionally excluded

## References
- Istio sidecar injection: https://istio.io/latest/docs/setup/additional-setup/sidecar-injection/
- Linkerd injection: https://linkerd.io/2.14/tasks/adding-your-service/
- MutatingWebhookConfiguration: https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/
- istioctl analyze: https://istio.io/latest/docs/reference/commands/istioctl/#istioctl-analyze

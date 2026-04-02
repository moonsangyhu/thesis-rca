# Known Issue: HPA Showing <unknown>/50% for Target Metrics

## Issue ID
KI-009

## Affected Components
- HorizontalPodAutoscaler (HPA)
- metrics-server
- All pods targeted by HPA without resource requests

## Symptoms
- `kubectl get hpa` shows `<unknown>/50%` in the TARGETS column:
  ```
  NAME              REFERENCE              TARGETS           MINPODS   MAXPODS   REPLICAS
  frontend-hpa      Deployment/frontend    <unknown>/50%     2         10        2
  ```
- HPA does not scale up or down regardless of actual load
- `kubectl describe hpa <name>` shows:
  ```
  Conditions:
    Type                   Status  Reason                   Message
    AbleToScale            True    SucceededGetScale         the HPA controller was able to get the target's current scale
    ScalingActive          False   FailedGetResourceMetric  the HPA was unable to compute the replica count: failed to get cpu utilization: unable to get metrics for resource cpu: unable to fetch metrics from resource metrics API: the server is currently unable to handle the request (get pods.metrics.k8s.io)
  ```
- `kubectl top pods` returns `error: Metrics API not available`
- Applications experience degraded performance during load spikes due to no autoscaling

## Root Cause
HPA `<unknown>` in the TARGETS column has two distinct causes:

**Cause 1: metrics-server not available**
The Kubernetes metrics API (`metrics.k8s.io`) is served by metrics-server. If metrics-server is not installed, is crashing, or has connectivity issues to the kubelet, the HPA controller cannot retrieve current resource utilization and displays `<unknown>`.

**Cause 2: Missing resource requests on pods**
HPA calculates CPU utilization as: `(current CPU usage) / (requested CPU)`. If the target pods have no `resources.requests.cpu` set, the denominator is undefined and HPA cannot compute a utilization percentage. This cause is particularly insidious because metrics-server may be healthy and `kubectl top pods` may work, but HPA still shows `<unknown>`.

Example of problematic pod spec:
```yaml
spec:
  containers:
  - name: frontend
    image: frontend:v1.0
    # No resources section — HPA will show <unknown>
```

## Diagnostic Commands
```bash
# Check HPA status
kubectl get hpa -A
kubectl describe hpa <hpa-name> -n <namespace>

# Check if metrics-server is running
kubectl -n kube-system get pods -l k8s-app=metrics-server
kubectl -n kube-system logs -l k8s-app=metrics-server --tail=50

# Test metrics API availability
kubectl top nodes
kubectl top pods -n <namespace>

# Check if pods have resource requests
kubectl get deployment <name> -n <namespace> -o jsonpath='{.spec.template.spec.containers[*].resources}'

# Check metrics-server API registration
kubectl get apiservice v1beta1.metrics.k8s.io
kubectl describe apiservice v1beta1.metrics.k8s.io

# Get HPA events
kubectl get events -n <namespace> | grep -i hpa

# Check HPA controller logs
kubectl -n kube-system logs -l component=kube-controller-manager --tail=100 | grep -i hpa
```

## Resolution
**Fix for Cause 1 (metrics-server not available)**:

Install metrics-server if missing:
```bash
kubectl apply -f https://github.com/kubernetes-sigs/metrics-server/releases/latest/download/components.yaml
```

If metrics-server is installed but failing due to TLS issues (common in kubeadm clusters):
```bash
kubectl -n kube-system edit deployment metrics-server
# Add to args:
# - --kubelet-insecure-tls
# - --kubelet-preferred-address-types=InternalIP
```

**Fix for Cause 2 (missing resource requests)**:

Add resource requests to the Deployment:
```yaml
spec:
  template:
    spec:
      containers:
      - name: frontend
        resources:
          requests:
            cpu: "100m"
            memory: "128Mi"
          limits:
            cpu: "500m"
            memory: "256Mi"
```

After adding resource requests:
```bash
kubectl apply -f deployment.yaml
kubectl rollout status deployment/<name> -n <namespace>

# Verify HPA now shows real metrics
kubectl get hpa -n <namespace>
# Expected: TARGETS shows actual utilization like "5%/50%"
```

## Workaround
For testing purposes, use custom metrics or external metrics with HPA instead of resource metrics. Or temporarily use a custom metrics adapter like Prometheus Adapter which can provide metrics even without resource requests.

## Prevention
- Always set `resources.requests` and `resources.limits` on all containers — this is also required for proper scheduling
- Add resource request validation via LimitRange at namespace level:
  ```yaml
  apiVersion: v1
  kind: LimitRange
  spec:
    limits:
    - default:
        cpu: 500m
        memory: 256Mi
      defaultRequest:
        cpu: 100m
        memory: 128Mi
      type: Container
  ```
- Include metrics-server health in cluster readiness checks
- Add `kubectl top pods -A` to post-deployment smoke tests

## References
- HPA documentation: https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale/
- metrics-server: https://github.com/kubernetes-sigs/metrics-server
- HPA troubleshooting: https://kubernetes.io/docs/tasks/run-application/horizontal-pod-autoscale-walkthrough/#appendix-horizontal-pod-autoscaler-algorithm-details

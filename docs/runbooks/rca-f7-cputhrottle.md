# Runbook: F7 - CPU Throttle Root Cause Analysis

## Trigger Conditions
Use this runbook when services show increased latency without obvious errors, when `container_cpu_cfs_throttled_periods_total` metric is high, or when `KubeContainerCpuThrottling` alerts fire. Also applicable when response times degrade under load but pods remain Running.

## Severity
**Medium-High** — CPU throttling does not crash services but causes latency degradation. In Online Boutique, a throttled `productcatalogservice` or `recommendationservice` can cause checkout timeouts.

## Estimated Resolution Time
20-35 minutes

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- Prometheus/Grafana access
- GitOps repo access for resource limit changes

## Investigation Steps

### Step 1: Identify throttled containers
```bash
# Check current CPU usage vs limits
kubectl top pods -n <namespace> --sort-by=cpu --containers

# Identify pods where CPU usage is near or exceeding requests
kubectl top pods -A --sort-by=cpu | head -20
```

### Step 2: Query Prometheus for throttling metrics
```bash
# Port-forward Prometheus
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090

# Then query in Prometheus UI or via curl:
# See Prometheus Queries section below
```

The key metric is:
```
container_cpu_cfs_throttled_periods_total / container_cpu_cfs_periods_total
```
Values > 0.25 (25%) indicate significant throttling.

### Step 3: Check current CPU limits and requests
```bash
# Get resource configuration for all containers in namespace
kubectl get pods -n <namespace> -o json | jq -r '
  .items[] | 
  .metadata.name as $pod |
  .spec.containers[] | 
  [$pod, .name, 
   (.resources.requests.cpu // "none"), 
   (.resources.limits.cpu // "none")] | 
  @tsv'

# For a specific deployment
kubectl get deployment <deployment-name> -n <namespace> -o json | \
  jq '.spec.template.spec.containers[] | {name: .name, resources: .resources}'
```

### Step 4: Understand CPU limits vs requests ratio
Kubernetes CPU throttling is driven by CFS (Completely Fair Scheduler) quotas:
- **Requests**: Used for scheduling (guaranteed CPU)
- **Limits**: Enforced via CFS quotas — even if node has free CPU, a container is throttled when it hits its limit

**Dangerous patterns:**
- `limits.cpu` = `requests.cpu` (no burst headroom)
- Very low `limits.cpu` (e.g., `100m`) with bursty workloads
- `limits.cpu` not set (unlimited — but can cause noisy neighbor issues)

### Step 5: Identify the hot service
```bash
# Get CPU throttle ratio per container
# (run this as a Prometheus query — see section below)
# Target pods with throttle ratio > 0.25

# Check HPA — is the service autoscaling?
kubectl get hpa -n <namespace>
kubectl describe hpa <hpa-name> -n <namespace>

# Check if more replicas would help
kubectl get deployment <deployment-name> -n <namespace> -o jsonpath='{.spec.replicas}'
```

### Step 6: Correlate throttling with latency
```bash
# Check application latency metrics
# Look for correlation between CPU throttle spikes and latency p99 increases

# In Grafana, check:
# 1. container_cpu_cfs_throttled_periods_total rate
# 2. Application latency p50/p95/p99 (e.g., grpc_server_handling_seconds_bucket)
# 3. Timeline correlation
```

### Step 7: Check node-level CPU contention
```bash
# CPU utilization per node
kubectl top nodes --sort-by=cpu

# Check if a node is CPU-saturated
kubectl describe node <node-name> | grep -A 10 "Allocated resources"
# Compare "Requests" percentage — if > 80%, node is overcommitted
```

## Resolution

### Fix A: Increase CPU limits
```bash
# Direct patch (temporary — update GitOps too)
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[
    {"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/cpu", "value": "500m"},
    {"op": "replace", "path": "/spec/template/spec/containers/0/resources/requests/cpu", "value": "200m"}
  ]'

# Watch rollout
kubectl rollout status deployment/<deployment-name> -n <namespace>
```

**Recommended CPU limits for Online Boutique services (baseline):**
| Service | Requests | Limits |
|---------|----------|--------|
| frontend | 100m | 200m |
| cartservice | 200m | 300m |
| productcatalogservice | 100m | 200m |
| checkoutservice | 100m | 200m |
| paymentservice | 100m | 200m |
| emailservice | 100m | 200m |
| recommendationservice | 200m | 500m |

### Fix B: Scale out (add more replicas)
```bash
# Manual scale
kubectl scale deployment <deployment-name> -n <namespace> --replicas=3

# Configure HPA to auto-scale based on CPU
cat <<EOF | kubectl apply -f -
apiVersion: autoscaling/v2
kind: HorizontalPodAutoscaler
metadata:
  name: <deployment-name>-hpa
  namespace: <namespace>
spec:
  scaleTargetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: <deployment-name>
  minReplicas: 2
  maxReplicas: 10
  metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
EOF
```

### Fix C: Remove CPU limits (allow bursting)
```bash
# Use with caution — only in namespace with ResourceQuota guard
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "remove", "path": "/spec/template/spec/containers/0/resources/limits/cpu"}]'
```

### Fix D: Use VPA for automatic right-sizing
```bash
cat <<EOF | kubectl apply -f -
apiVersion: autoscaling.k8s.io/v1
kind: VerticalPodAutoscaler
metadata:
  name: <deployment-name>-vpa
  namespace: <namespace>
spec:
  targetRef:
    apiVersion: apps/v1
    kind: Deployment
    name: <deployment-name>
  updatePolicy:
    updateMode: "Auto"
  resourcePolicy:
    containerPolicies:
    - containerName: "*"
      minAllowed:
        cpu: 50m
      maxAllowed:
        cpu: "2"
EOF
```

## Verification
```bash
# CPU throttle ratio should drop below 10%
# Check in Prometheus:
# rate(container_cpu_cfs_throttled_periods_total{pod=~"<pod-prefix>.*"}[5m])
# / rate(container_cpu_cfs_periods_total{pod=~"<pod-prefix>.*"}[5m])

# Application latency should decrease
kubectl top pods -n <namespace> --containers

# Confirm new limits are applied
kubectl get pod <new-pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].resources}'
```

## Escalation
- If throttling persists after 4x limit increase: application may have a performance regression — profile the application
- If throttling affects multiple services simultaneously: check if a shared dependency (e.g., Redis, database) is the real bottleneck
- If node-level CPU steal time is high: escalate to infrastructure team for VM/hypervisor CPU allocation

## Loki Queries

```logql
# Slow request log entries (application-level latency)
{namespace="<namespace>"} |= "timeout" or |= "slow" or |= "latency"

# gRPC deadline exceeded (common when CPU-throttled)
{namespace="<namespace>"} |= "DeadlineExceeded" or |= "context deadline exceeded"

# HTTP 503/504 errors (timeout from throttled upstream)
{namespace="<namespace>", app="frontend"} | json | status >= 503

# Request duration exceeding SLA
{namespace="<namespace>"} | json | duration > 1000
```

## Prometheus Queries

```promql
# CPU throttling ratio per container (alert if > 0.25)
rate(container_cpu_cfs_throttled_periods_total{namespace="<namespace>", container!=""}[5m])
  / rate(container_cpu_cfs_periods_total{namespace="<namespace>", container!=""}[5m])

# Top 10 most throttled containers
topk(10,
  rate(container_cpu_cfs_throttled_periods_total{namespace="<namespace>"}[5m])
  / rate(container_cpu_cfs_periods_total{namespace="<namespace>"}[5m])
)

# CPU usage vs limit
sum by (pod, container) (rate(container_cpu_usage_seconds_total{namespace="<namespace>"}[5m]))
  / sum by (pod, container) (kube_pod_container_resource_limits{resource="cpu", namespace="<namespace>"})

# Node CPU saturation
1 - avg by (node) (rate(node_cpu_seconds_total{mode="idle"}[5m]))

# gRPC/HTTP p99 latency (Online Boutique services expose these)
histogram_quantile(0.99, 
  rate(grpc_server_handling_seconds_bucket{namespace="<namespace>"}[5m]))

# CPU requests vs allocatable per node
sum by (node) (kube_pod_container_resource_requests{resource="cpu"})
  / kube_node_status_allocatable{resource="cpu"}
```

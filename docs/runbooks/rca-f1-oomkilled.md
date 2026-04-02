# Runbook: F1 - OOMKilled Root Cause Analysis

## Trigger Conditions
Use this runbook when containers are being killed with `OOMKilled` reason, pods are in `CrashLoopBackOff` after OOM events, or Prometheus alerts fire for memory saturation (e.g., `KubePodOOMKilled`, `ContainerMemoryNearLimit`).

## Severity
**Critical** — OOMKill cascades can take down entire service chains. In Online Boutique, a killed `cartservice` will cause `frontend` to return 500s.

## Estimated Resolution Time
15-30 minutes (limit adjustment + rollout)

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- Prometheus/Grafana access (port-forward or ingress)
- Loki/Grafana access for log correlation
- Write access to GitOps repo (FluxCD HelmRelease values)

## Investigation Steps

### Step 1: Identify OOMKilled pods
```bash
# Find all OOMKilled pods in the last hour
kubectl get pods -A --field-selector=status.phase=Running -o json | \
  jq '.items[] | select(.status.containerStatuses[]?.lastState.terminated.reason == "OOMKilled") | 
      {name: .metadata.name, ns: .metadata.namespace, container: .status.containerStatuses[].name}'

# Quick grep across all namespaces
kubectl get pods -A | grep -E 'OOMKilled|Error|CrashLoop'

# Describe a specific pod to see OOM event
kubectl describe pod <pod-name> -n <namespace>
```

Look for lines like:
```
Last State: Terminated
  Reason: OOMKilled
  Exit Code: 137
  Finished: ...
```

### Step 2: Examine pod events
```bash
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | grep -i oom
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | grep <pod-name>
```

### Step 3: Check current memory limits vs actual usage
```bash
# Check resource requests/limits
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].resources}'

# Live memory usage via metrics-server
kubectl top pod <pod-name> -n <namespace> --containers

# Top pods across namespace
kubectl top pods -n <namespace> --sort-by=memory
```

### Step 4: Identify the culprit container
```bash
# If multi-container pod, check each container's last state
kubectl get pod <pod-name> -n <namespace> -o json | \
  jq '.status.containerStatuses[] | {name: .name, lastState: .lastState, restartCount: .restartCount}'
```

### Step 5: Pull logs from the killed container
```bash
# Logs from the previous (killed) container instance
kubectl logs <pod-name> -n <namespace> -c <container-name> --previous

# Look for OOM-related messages (Java heap, Go runtime, etc.)
kubectl logs <pod-name> -n <namespace> --previous | tail -100
```

### Step 6: Correlate with Prometheus memory metrics
```bash
# Port-forward Prometheus if needed
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090

# Query current memory usage ratio
# container_memory_working_set_bytes / container_spec_memory_limit_bytes
```

See Prometheus Queries section below.

### Step 7: Check for memory leaks or traffic spikes
```bash
# Check HPA status (was there a scale event?)
kubectl get hpa -n <namespace>

# Check recent deployments
kubectl rollout history deployment/<deployment-name> -n <namespace>
```

## Resolution

### Option A: Increase memory limits (immediate fix)
```bash
# Patch deployment directly (temporary — must also update GitOps)
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "512Mi"}]'

# Verify rollout
kubectl rollout status deployment/<deployment-name> -n <namespace>
```

### Option B: Update via GitOps (FluxCD HelmRelease)
```bash
# Suspend FluxCD reconciliation temporarily
flux suspend helmrelease <release-name> -n <namespace>

# Edit values in git repo, then commit and push
# In values.yaml:
# resources:
#   limits:
#     memory: 512Mi
#   requests:
#     memory: 256Mi

# Resume reconciliation
flux resume helmrelease <release-name> -n <namespace>
flux reconcile helmrelease <release-name> -n <namespace>
```

### Option C: Add/configure Vertical Pod Autoscaler (VPA)
```bash
# Check if VPA exists
kubectl get vpa -n <namespace>

# Create VPA in recommendation mode
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
    updateMode: "Off"
EOF

# Check VPA recommendations after a few minutes
kubectl get vpa <deployment-name>-vpa -n <namespace> -o jsonpath='{.status.recommendation}'
```

## Verification
```bash
# Confirm no more OOMKilled events
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | grep -i oom

# Confirm pod is running and not restarting
kubectl get pod <pod-name> -n <namespace> -w

# Check restart count is stable
kubectl get pods -n <namespace> -o wide

# Validate memory usage is below new limit
kubectl top pod -n <namespace> --containers
```

## Escalation
- If OOM persists after 2x limit increase: suspect memory leak → escalate to dev team for heap dump analysis
- If multiple pods across nodes are OOMKilling simultaneously: suspect node memory pressure → check `kubectl describe node` for `MemoryPressure` condition
- If OOM coincides with traffic spike: review HPA configuration and request capacity planning

## Loki Queries

```logql
# OOM-related log entries across all pods in namespace
{namespace="<namespace>"} |= "OOM" or |= "out of memory" or |= "killed"

# Java heap space errors
{namespace="<namespace>", container="<container>"} |= "java.lang.OutOfMemoryError"

# Go runtime OOM
{namespace="<namespace>"} |= "runtime: out of memory"

# Last 100 lines before kill for specific pod
{namespace="<namespace>", pod=~"<pod-prefix>.*"} | json | line_format "{{.message}}"
  | last 100 lines before OOM timestamp

# Error rate spike correlating with OOM
rate({namespace="<namespace>"} |= "error" [5m])
```

## Prometheus Queries

```promql
# Memory usage ratio (working set / limit) — alert if > 0.9
container_memory_working_set_bytes{namespace="<namespace>", container="<container>"}
  / container_spec_memory_limit_bytes{namespace="<namespace>", container="<container>"}

# Memory usage over time (last 1h)
container_memory_working_set_bytes{namespace="<namespace>", container="<container>"}[1h]

# OOMKill count per container
kube_pod_container_status_last_terminated_reason{reason="OOMKilled", namespace="<namespace>"}

# Node-level memory pressure
node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes

# Memory usage by pod, sorted (top memory consumers)
topk(10, sum by (pod, namespace) (container_memory_working_set_bytes{namespace="<namespace>"}))

# Rate of memory growth (memory leak indicator)
deriv(container_memory_working_set_bytes{namespace="<namespace>", container="<container>"}[10m])
```

# CPU Throttling Detection and Resolution

## Overview
CPU throttling occurs when a container's CPU usage exceeds its configured CPU limit. Unlike memory limits (which cause OOMKill), CPU limits use cgroup CPU quota to restrict CPU time without killing the process. The Linux kernel forces the container to pause when it has used its allocated CPU quota for the period (typically 100ms). Throttling causes increased latency and degraded throughput but does not crash the pod. It is often invisible without proper metrics, making it a stealthy performance issue.

## Symptoms
- Elevated request latency without obvious errors
- CPU usage in `kubectl top pods` shows consistently at or near the limit
- Application responds slowly but no errors in logs
- Timeout errors in downstream services calling this service
- Prometheus metric `container_cpu_cfs_throttled_seconds_total` increases
- Application health checks start failing due to slow response

## Diagnostic Commands

```bash
# Step 1: Check current CPU usage vs limits
kubectl top pods -n <namespace>
kubectl top pods -n <namespace> --sort-by=cpu

# Compare with limits
kubectl get pods -n <namespace> -o custom-columns=\
'NAME:.metadata.name,CPU_REQ:.spec.containers[0].resources.requests.cpu,CPU_LIM:.spec.containers[0].resources.limits.cpu'

# Step 2: Check throttling via Prometheus metrics
# These metrics come from kubelet/cadvisor

# Throttling ratio (% of time throttled)
# rate(container_cpu_cfs_throttled_seconds_total{namespace="<namespace>", pod="<pod>"}[5m])
# / rate(container_cpu_cfs_periods_total{namespace="<namespace>", pod="<pod>"}[5m])

# Step 3: Check cgroup CPU stats directly on the node
# SSH to node
# Get container ID
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.status.containerStatuses[0].containerID}'
# Strip the prefix (docker:// or containerd://)

# Find cgroup path
# CONTAINER_ID=<container-id-without-prefix>
# cat /sys/fs/cgroup/cpu/kubepods/*/pod*/*/cpu.stat
# Key metrics:
#   nr_periods: total CFS periods
#   nr_throttled: periods throttled
#   throttled_time: nanoseconds throttled

# Step 4: Check CPU requests vs node allocatable
kubectl describe node <node-name> | grep -A10 "Allocated resources"
# Overcommitted CPU requests means less actual CPU available per pod

# Step 5: Check for CPU limit presence
kubectl get pods -n <namespace> -o json | python3 -c "
import sys, json
pods = json.load(sys.stdin)['items']
for p in pods:
    name = p['metadata']['name']
    for c in p['spec']['containers']:
        lim = c.get('resources', {}).get('limits', {})
        req = c.get('resources', {}).get('requests', {})
        print(f'{name}/{c[\"name\"]}: requests={req.get(\"cpu\",\"none\")} limits={lim.get(\"cpu\",\"none\")}')
"

# Step 6: Identify throttled containers using Prometheus
# Grafana query or port-forward to Prometheus
kubectl port-forward -n monitoring svc/prometheus 9090:9090 &

# Query in Prometheus UI:
# Top throttled containers:
# topk(10, rate(container_cpu_cfs_throttled_seconds_total[5m]) / rate(container_cpu_cfs_periods_total[5m]))

# Step 7: Check CPU burst patterns (short spikes)
# container_cpu_usage_seconds_total shows cumulative CPU
# rate(container_cpu_usage_seconds_total{namespace="<ns>"}[1m]) shows instantaneous rate

# Step 8: Check node CPU usage
kubectl top nodes
# SSH to node:
# top -b -n 1 | head -20
# mpstat -P ALL 1 3  (if sysstat installed)

# Step 9: Check if CPU throttling correlates with latency spikes
# Prometheus query:
# histogram_quantile(0.99, rate(http_request_duration_seconds_bucket{service="<svc>"}[5m]))

# Step 10: Check CPU shares/quota via cgroup
# SSH to node:
# POD_UID=$(kubectl get pod <pod-name> -n <ns> -o jsonpath='{.metadata.uid}')
# find /sys/fs/cgroup/cpu/kubepods -name "cpu.cfs_quota_us" | head -5
# cat /sys/fs/cgroup/cpu/kubepods/pod${POD_UID}/*/cpu.cfs_quota_us
# cat /sys/fs/cgroup/cpu/kubepods/pod${POD_UID}/*/cpu.cfs_period_us

# Formula: cpu_limit = cpu.cfs_quota_us / cpu.cfs_period_us
# e.g., 100000 / 100000 = 1 CPU, 50000 / 100000 = 500m CPU

# Step 11: For Online Boutique - check all services throttling
for pod in $(kubectl get pods -n online-boutique -o jsonpath='{.items[*].metadata.name}'); do
  echo -n "$pod: "
  kubectl get pod $pod -n online-boutique \
    -o jsonpath='{.spec.containers[0].resources.limits.cpu}' 2>/dev/null || echo "no limit"
done

# Step 12: Check Java GC pauses (JVM throttling amplification)
kubectl logs <pod-name> -n <namespace> | grep -E "GC pause|GC overhead|Full GC"
```

## Common Causes

1. **CPU limit too low for workload**: The limit was set based on average CPU usage, but the application has burst patterns (GC pauses, batch processing, request spikes) that exceed the limit.

2. **Java GC amplification**: Java garbage collection requires CPU bursts. When CPU is throttled during GC, GC pauses become extremely long (10x or more), causing application-level timeouts.

3. **Node CPU overcommitment**: Many pods on the same node, each with small limits, but when all are active simultaneously, they compete for actual CPU, increasing throttling.

4. **CPU limit set without understanding the application**: Limits copied from memory limits or set arbitrarily without profiling the actual CPU usage pattern.

5. **Startup CPU spike**: Applications use much more CPU during startup (class loading, cache warming, connection pooling) than during steady state. Limits appropriate for steady state throttle startup severely.

6. **Burstable QoS with low requests**: Pod has high CPU limit but low request. Node may be scheduled full based on requests, but actual burst causes contention.

7. **CFS scheduler granularity**: Linux CFS scheduler operates in 100ms periods. An application that needs 500ms CPU in 100ms bursts will be heavily throttled even if its average usage is within limits.

## Resolution Steps

### Step 1: Calculate appropriate CPU limit
```bash
# Profile CPU usage before setting limits
# Collect CPU usage over time
watch -n 5 kubectl top pod <pod-name> -n <namespace>

# Use Prometheus to get P95 CPU usage
# quantile_over_time(0.95, rate(container_cpu_usage_seconds_total{pod="<pod>"}[5m])[1h:5m])

# Set limit to P99 CPU usage or 2x P95
# Never set limit equal to request for CPU (unlike memory)
# Rule of thumb: limit = 2-5x request for bursty workloads

kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/cpu", "value": "500m"}]'
```

### Step 2: Remove CPU limits (controversial but sometimes correct)
```bash
# For guaranteed low latency: consider removing CPU limits
# Requests still provide scheduling guarantees
# Without limits, pods can burst up to node capacity

kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "remove", "path": "/spec/template/spec/containers/0/resources/limits/cpu"}]'

# Note: Without CPU limits, a single pod can monopolize node CPU
# Use this carefully and with HPA to scale out instead of up
```

### Step 3: Tune Java JVM for container CPU
```bash
# Java 11+ is container-aware, but GC tuning is still important
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/env/-", "value": {
    "name": "JAVA_OPTS",
    "value": "-XX:+UseG1GC -XX:MaxGCPauseMillis=200 -XX:+ParallelRefProcEnabled -XX:+DisableExplicitGC -XX:+AlwaysPreTouch -XX:ActiveProcessorCount=2"
  }}]'
# ActiveProcessorCount should match CPU limit (1 = 1000m, 2 = 2000m, etc.)
```

### Step 4: Scale out instead of up
```bash
# More replicas with lower CPU usage per replica = less throttling
# Each replica gets its own CPU quota

# Create HPA based on CPU usage
kubectl autoscale deployment <deployment-name> -n <namespace> \
  --cpu-percent=70 \
  --min=2 \
  --max=10

# Or use custom metrics (request rate)
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

### Step 5: Increase CPU request and limit
```bash
# Increase both request and limit proportionally
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[
    {"op": "replace", "path": "/spec/template/spec/containers/0/resources/requests/cpu", "value": "200m"},
    {"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/cpu", "value": "1000m"}
  ]'
```

## Prometheus Alerting for CPU Throttling

```yaml
# Alert: Container CPU throttling above 25% for 5 minutes
- alert: ContainerCPUThrottling
  expr: |
    rate(container_cpu_cfs_throttled_seconds_total{container!=""}[5m])
    / rate(container_cpu_cfs_periods_total{container!=""}[5m]) > 0.25
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Container {{ $labels.container }} in {{ $labels.pod }} is CPU throttled {{ $value | humanizePercentage }}"

# Alert: Severe CPU throttling above 75%
- alert: ContainerCPUSevereThrottling
  expr: |
    rate(container_cpu_cfs_throttled_seconds_total{container!=""}[5m])
    / rate(container_cpu_cfs_periods_total{container!=""}[5m]) > 0.75
  for: 2m
  labels:
    severity: critical
```

## cgroup v2 Differences

```bash
# In newer kernels/distros using cgroup v2:
# Path changes from /sys/fs/cgroup/cpu/ to /sys/fs/cgroup/
# cpu.stat file contains:
#   usage_usec, user_usec, system_usec
#   nr_periods, nr_throttled, throttled_usec

# Check cgroup version
ls /sys/fs/cgroup/cgroup.controllers 2>/dev/null && echo "cgroup v2" || echo "cgroup v1"

# cgroup v2 stats
# cat /sys/fs/cgroup/kubepods.slice/*/cpu.stat
```

## Prevention
- Profile CPU usage in load tests before setting limits
- Set CPU limit to at least 3x the average CPU request for bursty applications
- Use VPA in recommendation mode to get suggested CPU limits
- Consider not setting CPU limits for latency-sensitive services (use requests only for scheduling)
- Monitor throttling with Prometheus from day 1
- Include throttle ratio in SLI/SLO definitions

## Related Issues
- `memory-pressure.md` - Memory-related performance issues
- `pod-oomkilled.md` - Memory limits causing pod kills
- `readiness-liveness-probe.md` - Probes failing due to slow response from throttling
- `pod-crashloopbackoff.md` - Startup failures due to CPU throttling during initialization

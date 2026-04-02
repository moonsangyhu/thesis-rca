# Pod OOMKilled Diagnosis

## Overview
OOMKilled (Out of Memory Killed) occurs when a container exceeds its configured memory limit. The Linux kernel OOM killer terminates the process with SIGKILL (exit code 137). This is distinct from node-level OOM events. Kubernetes enforces memory limits using cgroup memory limits, and when a container hits this limit, the kernel immediately terminates the process without a graceful shutdown.

## Symptoms
- Pod shows STATUS `OOMKilled` or transitions to `CrashLoopBackOff`
- Exit code is `137` in pod describe output
- `kubectl describe pod` shows `OOMKilled` in Last State reason
- `kubectl top pod` shows memory usage close to or at limit before the kill
- Node events may show memory pressure if many pods are being OOMKilled
- Application logs are often truncated (process killed mid-write)

## Diagnostic Commands

```bash
# Step 1: Confirm OOMKilled exit code
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.status.containerStatuses[0].lastState.terminated.reason}'
# Should return "OOMKilled"

kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.status.containerStatuses[0].lastState.terminated.exitCode}'
# Should return 137

# Step 2: Check current memory limits and requests
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].resources}' | python3 -m json.tool

# Step 3: Check current memory usage
kubectl top pod <pod-name> -n <namespace>
kubectl top pod -n <namespace> --sort-by=memory

# Step 4: Check historical memory usage before OOM
# Prometheus query (via port-forward or Grafana):
# container_memory_usage_bytes{namespace="<namespace>", pod="<pod-name>"}
# container_memory_working_set_bytes{namespace="<namespace>", pod="<pod-name>"}

# Step 5: Check previous container logs (may be truncated)
kubectl logs <pod-name> -n <namespace> --previous --tail=100

# Step 6: Check node-level OOM events
# SSH to the node where the pod is running
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.nodeName}'
# Then on that node:
# dmesg | grep -i "out of memory" | tail -20
# dmesg | grep -i oomkill | tail -20

# Step 7: Check node memory pressure
kubectl describe node <node-name> | grep -A5 "Conditions:"
kubectl describe node <node-name> | grep -A10 "Allocated resources"

# Step 8: Check all pods memory usage in namespace
kubectl top pods -n <namespace> --sort-by=memory

# Step 9: Check if pod has QoS class (affects eviction order)
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.status.qosClass}'
# Guaranteed: limits == requests (best protection)
# Burstable: limits > requests (middle)
# BestEffort: no limits/requests (first to be evicted/OOMKilled)

# Step 10: Check deployment/statefulset resource specs
kubectl get deployment <deployment-name> -n <namespace> -o yaml | grep -A10 resources:

# Step 11: Prometheus OOM rate query
# increase(kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}[1h])

# Step 12: Check if it's a specific JVM-based service
# Look for these in logs before kill:
kubectl logs <pod-name> -n <namespace> --previous | grep -E "OutOfMemoryError|GC overhead|Heap"

# Step 13: For Online Boutique, check which microservice
kubectl get pods -n online-boutique -o custom-columns=\
'NAME:.metadata.name,MEM_LIMIT:.spec.containers[0].resources.limits.memory,MEM_REQ:.spec.containers[0].resources.requests.memory'

# Step 14: Check container memory cgroup limit on node
# On the node:
# POD_UID=$(kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.metadata.uid}')
# cat /sys/fs/cgroup/memory/kubepods/*/pod${POD_UID}/*/memory.limit_in_bytes

# Step 15: Memory usage trend (Prometheus)
# max_over_time(container_memory_working_set_bytes{pod="<pod-name>"}[1h]) / 
# container_spec_memory_limit_bytes{pod="<pod-name>"}
```

## Common Causes

1. **Memory limit too low**: The limit was set based on average usage without accounting for peak load or memory spikes during request bursts.

2. **Memory leak**: Application accumulates memory over time and never releases it. Common in long-running services with improper object cleanup, unclosed connections, or growing caches.

3. **JVM heap misconfiguration**: Java applications default to using up to 25% of available system memory for heap, but in containers they may calculate based on node memory rather than container limit. Without `-Xmx`, JVM may request more than the container limit.

4. **Go runtime memory growth**: Go's garbage collector is lazy by default (GOGC=100). Under memory pressure it may hold large amounts of heap before GC runs, causing spikes that exceed limits.

5. **Cache growth**: In-memory caches (Redis client, application-level caches) grow unbounded without proper size limits.

6. **Large request payloads**: Processing large files or payloads causes temporary memory spikes. A single large request can exceed the limit.

7. **Node-level memory pressure**: If the node is under memory pressure, the kernel OOM killer may target pods even below their limits (rare with proper limits set).

8. **Init container leaving large files**: Init containers that write to shared volumes can cause memory pressure if the data is mmap'd by the main container.

9. **Sidecar container consuming memory**: Injected sidecar (e.g., Istio envoy, Cilium CNI) consuming memory counted against pod but not accounted in resource limits of main container.

## Resolution Steps

### Step 1: Increase memory limit
```bash
# Check current limit first
kubectl get deployment <deployment-name> -n <namespace> -o jsonpath='{.spec.template.spec.containers[0].resources.limits.memory}'

# Patch the deployment with increased limit
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "512Mi"}]'

# Or edit directly
kubectl edit deployment <deployment-name> -n <namespace>
```

### Step 2: Fix JVM heap settings
```bash
# For Java applications, add JVM flags via environment variables
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/env/-", "value": {"name": "JAVA_OPTS", "value": "-Xms256m -Xmx384m -XX:+UseG1GC -XX:MaxRAMPercentage=75.0"}}]'

# Alternative: use MaxRAMPercentage (Java 11+) to automatically calculate from cgroup limit
# -XX:MaxRAMPercentage=75.0  # Use 75% of container memory limit for heap
# -XX:+UseContainerSupport   # Enable container-aware memory detection (Java 11+ default)
```

### Step 3: Fix Go GC tuning
```bash
# Set GOGC to trigger GC more frequently (lower value = more frequent GC)
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/env/-", "value": {"name": "GOGC", "value": "50"}}]'

# Or set memory limit (Go 1.19+)
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/env/-", "value": {"name": "GOMEMLIMIT", "value": "400MiB"}}]'
```

### Step 4: Identify and fix memory leaks
```bash
# For Go: enable pprof endpoint and capture heap profile
kubectl port-forward <pod-name> -n <namespace> 6060:6060
# In another terminal:
curl http://localhost:6060/debug/pprof/heap > heap.out
go tool pprof heap.out

# For Java: capture heap dump before OOM (add to JVM args)
# -XX:+HeapDumpOnOutOfMemoryError -XX:HeapDumpPath=/tmp/heapdump.hprof

# For Node.js:
# Use --inspect flag and Chrome DevTools Memory tab

# Exec into running pod to check memory
kubectl exec -it <pod-name> -n <namespace> -- /bin/sh
# Check process memory
cat /proc/1/status | grep -E "VmRSS|VmSize|VmPeak"
```

### Step 5: Set proper requests alongside limits
```bash
# Always set both requests and limits for Guaranteed QoS
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[
    {"op": "replace", "path": "/spec/template/spec/containers/0/resources/requests/memory", "value": "256Mi"},
    {"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "512Mi"}
  ]'
```

### Step 6: Add memory-based HPA to scale before OOM
```bash
# Scale out when memory usage exceeds 80% of request
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
  minReplicas: 1
  maxReplicas: 5
  metrics:
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
EOF
```

### Step 7: Rolling restart after fix
```bash
kubectl rollout restart deployment/<deployment-name> -n <namespace>
kubectl rollout status deployment/<deployment-name> -n <namespace> --timeout=5m
```

## Memory Leak Detection Patterns

```bash
# Watch memory growth over time
watch -n 5 kubectl top pod <pod-name> -n <namespace>

# Prometheus: check if memory only grows (never shrinks)
# rate(container_memory_usage_bytes{pod="<pod-name>"}[5m]) > 0
# Alert if memory grows consistently for 30+ minutes

# Check /proc/meminfo inside container
kubectl exec <pod-name> -n <namespace> -- cat /proc/meminfo

# Check memory maps
kubectl exec <pod-name> -n <namespace> -- cat /proc/1/maps | wc -l
```

## Prevention
- Profile application memory usage under realistic load before setting limits
- Set limits at 2x the P95 memory usage under load
- For JVM apps: always set `-Xmx` or `-XX:MaxRAMPercentage`
- For Go apps: set `GOMEMLIMIT` in Go 1.19+
- Implement `/debug/pprof` endpoints in Go services for production profiling
- Set up Prometheus alerts for memory usage > 85% of limit
- Use VPA (Vertical Pod Autoscaler) in recommendation mode to suggest limit values
- Regularly review `kubectl top pods` during load testing
- Set `terminationMessagePath` to capture last words before OOM kill

## Prometheus Alerts

```yaml
# Alert: Pod memory usage above 90% of limit
- alert: PodMemoryNearLimit
  expr: |
    container_memory_working_set_bytes / container_spec_memory_limit_bytes > 0.9
  for: 5m
  labels:
    severity: warning
  annotations:
    summary: "Pod {{ $labels.pod }} memory near limit"

# Alert: OOMKill detected
- alert: PodOOMKilled
  expr: |
    increase(kube_pod_container_status_last_terminated_reason{reason="OOMKilled"}[1h]) > 0
  labels:
    severity: critical
```

## Related Issues
- `pod-crashloopbackoff.md` - CrashLoopBackOff often caused by OOMKilled
- `memory-pressure.md` - Node-level memory pressure
- `node-pressure.md` - Node MemoryPressure condition
- `pod-evicted.md` - Pods evicted due to memory pressure

# Debugging Memory Pressure (Node and Pod Level)

## Overview
Memory pressure occurs when a node or pod approaches or exceeds its available memory capacity. At the node level, kubelet detects MemoryPressure condition and begins evicting pods. At the pod level, containers exceeding their memory limits are OOMKilled by the kernel's OOM killer.

## Symptoms
- Node condition `MemoryPressure=True`
- Pods evicted with reason `Evicted` and message referencing memory
- Container status `OOMKilled` with exit code 137
- Application performance degradation (excessive GC, swap thrashing)
- `kubectl top node` showing high memory utilization (>85%)
- Prometheus alert `NodeMemoryHighUtilization` firing

## Diagnostic Commands

```bash
# Check node memory conditions
kubectl get nodes -o custom-columns=NAME:.metadata.name,MEM_PRESSURE:.status.conditions[?\(@.type==\"MemoryPressure\"\)].status

# Node-level memory usage
kubectl top node

# Pod-level memory usage on specific node
kubectl top pod --all-namespaces --sort-by=memory | head -20

# Detailed node allocatable vs capacity
kubectl describe node worker01 | grep -A10 "Allocated resources"

# Check eviction events
kubectl get events --all-namespaces --field-selector reason=Evicted --sort-by='.lastTimestamp'

# Check container memory limits vs actual usage
kubectl get pods -n boutique -o custom-columns=\
NAME:.metadata.name,\
REQ:.spec.containers[0].resources.requests.memory,\
LIM:.spec.containers[0].resources.limits.memory

# Check OOMKilled containers
kubectl get pods --all-namespaces -o json | \
  python3 -c "import sys,json; d=json.load(sys.stdin)
for p in d['items']:
  for cs in p.get('status',{}).get('containerStatuses',[]):
    t=cs.get('lastState',{}).get('terminated',{})
    if t.get('reason')=='OOMKilled':
      print(f\"{p['metadata']['namespace']}/{p['metadata']['name']}: OOMKilled (exit {t.get('exitCode')})\")"

# Inspect cgroup memory stats (on node via debug pod)
kubectl debug node/worker01 -it --image=busybox -- sh -c \
  "cat /host/sys/fs/cgroup/memory/kubepods/memory.usage_in_bytes"
```

## Common Causes

### 1. Container memory limit too low
Application needs more memory than the configured limit. Common with JVM apps where heap + metaspace + native memory exceeds container limit.

```bash
# Check current limits
kubectl describe pod frontend-xyz -n boutique | grep -A2 Limits

# Compare with actual usage
kubectl top pod frontend-xyz -n boutique --containers
```

### 2. Memory leak in application
Gradual memory growth over time indicates a leak. Working set bytes keeps increasing without plateau.

```promql
# PromQL: detect memory growth trend
deriv(container_memory_working_set_bytes{namespace="boutique", container="frontend"}[1h]) > 0
```

### 3. JVM heap misconfiguration
JVM defaults may allocate heap larger than container limit, or off-heap memory (metaspace, thread stacks, NIO buffers) is not accounted for.

```bash
# Check JVM memory settings inside container
kubectl exec -n boutique frontend-xyz -- java -XshowSettings:vm 2>&1 | grep -i heap

# Recommended: Use container-aware JVM flags
# -XX:MaxRAMPercentage=75.0 (leave 25% for off-heap)
```

### 4. Go runtime memory usage
Go GC defaults to GOGC=100 (double heap before GC). In memory-constrained containers, this can cause spikes.

```bash
# Check Go memory stats via pprof (if exposed)
kubectl port-forward -n boutique svc/productcatalog 8080:8080
curl http://localhost:8080/debug/pprof/heap > heap.prof
go tool pprof heap.prof
```

### 5. Node-level overcommitment
Sum of all pod memory requests exceeds node capacity. Kubelet allows this when requests < capacity, but actual usage can exceed.

```bash
# Check node allocation
kubectl describe node worker01 | grep -A5 "Allocated resources"
# Memory Requests vs Allocatable ratio should be < 80%
```

## Resolution Steps

### For Pod-level OOMKill
1. Identify the killed container: `kubectl describe pod <name> -n <ns>`
2. Check previous logs: `kubectl logs <pod> -c <container> --previous`
3. Analyze memory usage pattern in Prometheus
4. Increase memory limit (and request proportionally):
   ```yaml
   resources:
     requests:
       memory: "256Mi"
     limits:
       memory: "512Mi"  # increase from previous value
   ```

### For Node-level MemoryPressure
1. Identify top memory consumers: `kubectl top pod --sort-by=memory`
2. Evict non-critical pods or scale down
3. Check for memory leaks in top consumers
4. Consider adding nodes or increasing node memory

## Prometheus Queries

```promql
# Node memory available (should stay above eviction threshold)
node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes * 100

# Container working set memory (what OOM killer looks at)
container_memory_working_set_bytes{namespace="boutique"}

# Container RSS (resident set size - actual physical memory)
container_memory_rss{namespace="boutique"}

# Memory usage vs limit ratio (alert when > 80%)
container_memory_working_set_bytes{namespace="boutique"}
  / container_spec_memory_limit_bytes{namespace="boutique"} * 100

# Rate of memory growth (detect leaks)
deriv(container_memory_working_set_bytes{namespace="boutique"}[1h])
```

## Prevention
- Always set memory requests AND limits for all containers
- Use VPA (Vertical Pod Autoscaler) recommendations for right-sizing
- Monitor `container_memory_working_set_bytes / container_spec_memory_limit_bytes` ratio
- For JVM: use `-XX:MaxRAMPercentage=75.0` instead of fixed `-Xmx`
- For Go: set `GOMEMLIMIT` environment variable
- Set node eviction thresholds appropriately in kubelet config

## Related Issues
- [Pod OOMKilled](pod-oomkilled.md)
- [Pod Evicted](pod-evicted.md)
- [Node Pressure](node-pressure.md)
- [Resource Limits Missing](../known-issues/resource-limits-missing.md)

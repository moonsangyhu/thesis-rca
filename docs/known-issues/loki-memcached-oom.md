# Known Issue: Loki Memcached OOM in SingleBinary Mode

## Issue ID
KI-003

## Affected Components
- Grafana Loki (SingleBinary / monolithic mode)
- Memcached (chunks cache and results cache sidecars/pods)
- Nodes hosting Loki stack (memory pressure)

## Symptoms
- Memcached pods repeatedly crash with OOMKilled status:
  ```
  NAME                              READY   STATUS      RESTARTS
  loki-chunks-cache-0               0/1     OOMKilled   12
  loki-results-cache-0              0/1     OOMKilled   8
  ```
- Node where Loki is scheduled experiences MemoryPressure
- Other pods on the same node are evicted
- Loki itself may be evicted or fail to schedule
- `kubectl top nodes` shows memory at 95%+
- Loki log ingestion may work intermittently but queries return errors

## Root Cause
The official Grafana Loki Helm chart (grafana/loki) enables memcached-based caching by default for both chunks cache and results cache, regardless of the deployment mode. In SingleBinary (monolithic) mode, all Loki components run in a single process that already performs in-process caching. The external memcached instances are redundant and wasteful.

The default Helm values allocate significant memory to each memcached instance (often 1-2 GiB). On resource-constrained lab nodes (e.g., 4-8 GiB RAM), having two extra memcached StatefulSets running alongside Loki itself exhausts available memory.

In this cluster, nodes had 8 GiB RAM. Loki requested 1 GiB, each memcached requested 2 GiB, totaling 5 GiB just for the logging stack — leaving little headroom for other workloads.

Relevant default Helm values (loki chart v6.x):
```yaml
chunksCache:
  enabled: true        # problematic default
  allocatedMemory: 2048
resultsCache:
  enabled: true        # problematic default
  allocatedMemory: 2048
```

## Diagnostic Commands
```bash
# Check pod statuses in monitoring namespace
kubectl -n monitoring get pods | grep -E "loki|memcached"

# Check OOMKilled reason
kubectl -n monitoring describe pod loki-chunks-cache-0 | grep -A5 "Last State"

# Check node memory pressure
kubectl describe node <node-name> | grep -A5 Conditions | grep -i memory

# Check Helm release values
helm -n monitoring get values loki

# Check current memory usage
kubectl -n monitoring top pods | grep -E "loki|memcached"

# Check events for eviction
kubectl -n monitoring get events --sort-by='.lastTimestamp' | grep -i "oom\|evict\|kill"
```

## Resolution
This issue was resolved in this cluster by disabling both cache components in the Loki Helm values.

**Step 1**: Update the Loki HelmRelease or values file to disable caches:
```yaml
# loki-values.yaml
loki:
  commonConfig:
    replication_factor: 1
  storage:
    type: filesystem
chunksCache:
  enabled: false
resultsCache:
  enabled: false
```

**Step 2**: If using FluxCD HelmRelease, update the values and commit:
```bash
# Edit the HelmRelease resource
kubectl -n monitoring edit helmrelease loki

# Or update the values ConfigMap/Secret and trigger reconcile
flux reconcile helmrelease loki -n monitoring
```

**Step 3**: If deploying directly with Helm:
```bash
helm upgrade loki grafana/loki \
  -n monitoring \
  --set chunksCache.enabled=false \
  --set resultsCache.enabled=false \
  -f loki-values.yaml
```

**Step 4**: Verify memcached pods are no longer created:
```bash
kubectl -n monitoring get pods | grep memcached
# Expected: no output

kubectl -n monitoring get pods | grep loki
# Expected: loki pod in Running state
```

## Workaround
If you cannot update the Helm values immediately, you can scale down the memcached StatefulSets:
```bash
kubectl -n monitoring scale statefulset loki-chunks-cache --replicas=0
kubectl -n monitoring scale statefulset loki-results-cache --replicas=0
```
Note: This will be reverted by the next Helm reconciliation unless you suspend it first.

## Prevention
- For SingleBinary/monolithic Loki deployments on resource-constrained nodes, always disable external caches
- Review Helm chart default values before deploying — many production-oriented defaults are excessive for lab/small environments
- Set resource requests and limits on all cache pods to prevent unbounded memory consumption
- Use `helm template` to preview all resources before deploying

## References
- Grafana Loki deployment modes: https://grafana.com/docs/loki/latest/get-started/deployment-modes/
- Loki Helm chart values: https://github.com/grafana/loki/tree/main/production/helm/loki
- Loki caching configuration: https://grafana.com/docs/loki/latest/operations/caching/

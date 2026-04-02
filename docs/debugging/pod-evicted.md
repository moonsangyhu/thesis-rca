# Pod Eviction Diagnosis

## Overview
Pod eviction occurs when the kubelet proactively removes pods from a node to reclaim resources (disk, memory, PIDs). Evictions can also be triggered by the Kubernetes scheduler via the Eviction API for preemption or node draining. Evicted pods show STATUS `Evicted` and remain as a record in the namespace until manually deleted. Understanding QoS classes is critical: BestEffort pods are evicted first, then Burstable, and Guaranteed pods last.

## Symptoms
- `kubectl get pods` shows STATUS `Evicted`
- Large number of failed pods accumulating in namespace
- Node shows `MemoryPressure`, `DiskPressure`, or `PIDPressure` condition
- `kubectl describe pod` shows reason `Evicted` with eviction message
- Pods restart frequency increases across a node
- Monitoring shows node resource usage spike before evictions

## Diagnostic Commands

```bash
# Step 1: Find evicted pods
kubectl get pods -n <namespace> | grep Evicted
kubectl get pods -A | grep Evicted

# Step 2: Count evicted pods per namespace
kubectl get pods -A --field-selector=status.phase=Failed | grep Evicted | awk '{print $1}' | sort | uniq -c | sort -rn

# Step 3: Get eviction reason from pod
kubectl describe pod <evicted-pod-name> -n <namespace>
# Look for:
#   Status: Failed
#   Reason: Evicted
#   Message: The node was low on resource: memory. Threshold quantity: 100Mi, available: 80Mi
#   OR: The node was low on resource: ephemeral-storage

# Step 4: Check which node the pod was on
kubectl get pod <evicted-pod-name> -n <namespace> -o jsonpath='{.status.nominatedNodeName}'
# For evicted pods, check the events
kubectl describe pod <evicted-pod-name> -n <namespace> | grep -E "Node:|Reason:|Message:"

# Step 5: Check node conditions
kubectl get nodes
kubectl describe nodes | grep -A10 "Conditions:"
kubectl get nodes -o json | python3 -c "
import sys, json
nodes = json.load(sys.stdin)['items']
for n in nodes:
    name = n['metadata']['name']
    conds = {c['type']:c['status'] for c in n['status']['conditions']}
    print(f'{name}: MemoryPressure={conds.get(\"MemoryPressure\",\"N/A\")} DiskPressure={conds.get(\"DiskPressure\",\"N/A\")} PIDPressure={conds.get(\"PIDPressure\",\"N/A\")}')
"

# Step 6: Check disk usage on nodes (ephemeral storage)
kubectl describe node <node-name> | grep -A5 "Allocated resources"
# SSH to node: df -h
# SSH to node: du -sh /var/lib/kubelet/pods/*

# Step 7: Check node memory pressure
kubectl top nodes
kubectl describe node <node-name> | grep -A3 "Memory:"

# Step 8: Check kubelet eviction thresholds (on the node)
# cat /var/lib/kubelet/config.yaml | grep -A10 evictionHard
# Or check process args: ps aux | grep kubelet | tr ' ' '\n' | grep eviction

# Step 9: Check QoS class of evicted pods
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.status.qosClass}'

# Step 10: Check all pod QoS classes
kubectl get pods -n <namespace> -o custom-columns=\
'NAME:.metadata.name,QOS:.status.qosClass,STATUS:.status.phase'

# Step 11: Check for large log files consuming ephemeral storage
# SSH to node:
# find /var/lib/docker/containers -name "*.log" -size +100M 2>/dev/null
# find /var/log/pods -name "*.log" -size +100M 2>/dev/null

# Step 12: Prometheus queries for eviction analysis
# kube_pod_status_reason{reason="Evicted"} > 0
# node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"} < 0.1

# Step 13: Check if evictions are from admission control (Preemption)
kubectl get events -n <namespace> | grep -E "Preempt|Evict"

# Step 14: Check node allocatable ephemeral storage
kubectl get node <node-name> -o jsonpath='{.status.allocatable.ephemeral-storage}'

# Step 15: Check pod ephemeral storage limits
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].resources.limits.ephemeral-storage}'
```

## Common Causes

1. **Node memory pressure**: Total memory usage on node exceeds eviction threshold (default: `memory.available < 100Mi`). Kubelet evicts BestEffort pods first, then Burstable.

2. **Node disk pressure on root filesystem**: The root filesystem (/) or image storage filesystem fills up. Default threshold: `nodefs.available < 10%` or `nodefs.inodesFree < 5%`.

3. **Ephemeral storage limit exceeded**: A pod writes more than its `ephemeral-storage` limit to emptyDir volumes, container logs, or container writable layers.

4. **Large container logs**: Containers writing excessive logs fill up the node's `/var/log/pods` directory. This counts as ephemeral storage.

5. **Node PID pressure**: Too many processes on the node (default threshold: `pid.available < 1000`). Can be caused by process leaks in containers.

6. **Preemption for higher-priority pods**: A higher-priority pod (via PriorityClass) cannot be scheduled and the scheduler evicts lower-priority pods to make room.

7. **Node drain**: `kubectl drain` forcefully evicts all pods from a node for maintenance.

8. **Imagefs pressure**: The container image storage filesystem fills up from many large images being pulled.

## Resolution Steps

### Step 1: Clean up evicted pod records
```bash
# Delete all evicted pods in a namespace
kubectl get pods -n <namespace> --field-selector=status.phase=Failed -o name | xargs kubectl delete -n <namespace>

# Delete all evicted pods across all namespaces
kubectl get pods -A --field-selector=status.phase=Failed | grep Evicted | \
  awk '{print "kubectl delete pod " $2 " -n " $1}' | bash

# Or use this one-liner
for ns in $(kubectl get ns -o jsonpath='{.items[*].metadata.name}'); do
  kubectl get pods -n $ns --field-selector=status.phase=Failed -o name | \
    xargs --no-run-if-empty kubectl delete -n $ns
done
```

### Step 2: Fix disk pressure - clean up disk space
```bash
# Find large log files
# SSH to the node:
sudo du -sh /var/log/pods/* | sort -rh | head -20
sudo du -sh /var/lib/containerd/io.containerd.snapshotter.v1.overlayfs/snapshots/* | sort -rh | head -10

# Remove unused container images
# On the node:
sudo crictl rmi --prune
# Or:
sudo ctr -n k8s.io images ls | grep -v sha256 | awk '{print $1}' | xargs -I {} sudo ctr -n k8s.io images rm {}

# Clean up unused volumes
sudo crictl rmp $(sudo crictl pods -q --state=Exited) 2>/dev/null

# Check and rotate logs
sudo journalctl --vacuum-size=500M
sudo journalctl --vacuum-time=3d
```

### Step 3: Fix memory pressure - reduce memory usage
```bash
# Identify top memory consumers
kubectl top pods -A --sort-by=memory | head -20

# Add memory limits to BestEffort pods
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[
    {"op": "add", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "256Mi"},
    {"op": "add", "path": "/spec/template/spec/containers/0/resources/requests/memory", "value": "128Mi"}
  ]'
```

### Step 4: Add ephemeral storage limits to prevent disk pressure
```bash
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[
    {"op": "add", "path": "/spec/template/spec/containers/0/resources/limits/ephemeral-storage", "value": "1Gi"},
    {"op": "add", "path": "/spec/template/spec/containers/0/resources/requests/ephemeral-storage", "value": "500Mi"}
  ]'
```

### Step 5: Configure log rotation to prevent disk pressure
```bash
# Add log rotation via deployment spec
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/terminationMessagePolicy", "value": "FallbackToLogsOnError"}]'

# Configure kubelet log rotation (on each node - /var/lib/kubelet/config.yaml):
# containerLogMaxSize: "50Mi"
# containerLogMaxFiles: 3

# For containerd log rotation, configure in /etc/containerd/config.toml
```

### Step 6: Increase eviction thresholds (adjust kubelet config)
```bash
# SSH to node and edit /var/lib/kubelet/config.yaml
# Modify eviction thresholds:
# evictionHard:
#   memory.available: "200Mi"  # was 100Mi
#   nodefs.available: "15%"    # was 10%
#   nodefs.inodesFree: "10%"   # was 5%
# Then restart kubelet: systemctl restart kubelet
```

### Step 7: Upgrade pod QoS to protect from eviction
```bash
# Make pod Guaranteed by setting requests == limits
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[
    {"op": "replace", "path": "/spec/template/spec/containers/0/resources/requests/memory", "value": "256Mi"},
    {"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "256Mi"},
    {"op": "replace", "path": "/spec/template/spec/containers/0/resources/requests/cpu", "value": "100m"},
    {"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/cpu", "value": "100m"}
  ]'
```

## QoS Classes Reference

| QoS Class | Condition | Eviction Priority |
|-----------|-----------|-------------------|
| BestEffort | No requests or limits set | Evicted first |
| Burstable | Requests < Limits, or only one set | Evicted second |
| Guaranteed | requests == limits for all containers | Evicted last |

```bash
# Check QoS class distribution
kubectl get pods -n <namespace> -o json | python3 -c "
import sys, json
pods = json.load(sys.stdin)['items']
from collections import Counter
qos = Counter(p['status'].get('qosClass', 'Unknown') for p in pods)
print(dict(qos))
"
```

## Prevention
- Always set resource requests and limits on all containers
- Set `ephemeral-storage` limits to prevent log-induced disk pressure
- Configure kubelet `containerLogMaxSize` and `containerLogMaxFiles`
- Set up Prometheus alerts for disk usage > 80%: `node_filesystem_avail_bytes / node_filesystem_size_bytes < 0.2`
- Use `PodDisruptionBudget` to control voluntary evictions
- Implement log aggregation (Loki) so logs don't accumulate on nodes
- Regularly clean up completed/failed jobs and their pods
- Monitor `kube_pod_status_reason{reason="Evicted"}` metric

## Related Issues
- `node-pressure.md` - Node pressure conditions
- `memory-pressure.md` - Memory pressure detailed diagnosis
- `pod-pending.md` - Pods pending after eviction
- `resource-quota-exceeded.md` - Quota preventing pod replacement after eviction

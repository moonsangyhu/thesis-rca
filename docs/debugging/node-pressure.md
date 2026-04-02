# Node Pressure Conditions: DiskPressure, MemoryPressure, PIDPressure

## Overview
Kubernetes monitors node resources and sets pressure conditions when thresholds are exceeded. When a pressure condition becomes True, the kubelet applies taints to prevent new pod scheduling and may begin evicting pods. The three pressure conditions are: `DiskPressure` (filesystem or inode exhaustion), `MemoryPressure` (available memory below threshold), and `PIDPressure` (process ID count near limit). These conditions are checked by the kubelet every `housekeeping-interval` (default 10 seconds).

## Symptoms
- `kubectl get nodes` shows node with `STATUS` having pressure indicator
- `kubectl describe node` shows condition `True` for DiskPressure/MemoryPressure/PIDPressure
- Pods on the node being evicted with message referencing node resource
- Node automatically receives taints: `node.kubernetes.io/disk-pressure`, `node.kubernetes.io/memory-pressure`, `node.kubernetes.io/pid-pressure`
- New pods not scheduled to the pressured node
- `kubectl top nodes` shows high memory/disk usage

## Diagnostic Commands

```bash
# Step 1: Check all node conditions at once
kubectl get nodes -o custom-columns=\
'NAME:.metadata.name,STATUS:.status.conditions[-1].type,DISK:.status.conditions[?(@.type=="DiskPressure")].status,MEM:.status.conditions[?(@.type=="MemoryPressure")].status,PID:.status.conditions[?(@.type=="PIDPressure")].status'

# Step 2: Detailed conditions with messages
kubectl describe node <node-name> | grep -A30 "Conditions:"

# Step 3: Check all nodes for pressure
for node in $(kubectl get nodes -o jsonpath='{.items[*].metadata.name}'); do
  echo "=== $node ==="
  kubectl describe node $node | grep -E "DiskPressure|MemoryPressure|PIDPressure" | grep -v "^$"
done

# Step 4: Check eviction threshold settings
# These are kubelet flags/config - check on the node:
# cat /var/lib/kubelet/config.yaml | grep -A20 eviction

# Default eviction thresholds:
# memory.available < 100Mi  -> MemoryPressure
# nodefs.available < 10%    -> DiskPressure (root filesystem)
# nodefs.inodesFree < 5%    -> DiskPressure (inode exhaustion)
# imagefs.available < 15%   -> DiskPressure (image filesystem)
# pid.available < 1000      -> PIDPressure

# --- DISK PRESSURE ---

# Step 5: Check disk usage on the node
# SSH to node:
# df -h
# df -ih  (check inodes)

# Step 6: Find what's consuming disk space
# SSH to node:
# du -sh /var/lib/kubelet/pods/* | sort -rh | head -20
# du -sh /var/lib/containerd/* | sort -rh | head -10
# du -sh /var/log/pods/* | sort -rh | head -20
# du -sh /tmp/*

# Step 7: Check container image sizes
kubectl exec -n kube-system -l k8s-app=kube-proxy -- df -h 2>/dev/null || \
  kubectl debug node/<node-name> -it --image=busybox -- df -h

# Step 8: Check Prometheus disk metrics
# node_filesystem_avail_bytes{instance="<node-ip>:9100", mountpoint="/"}
# node_filesystem_avail_bytes / node_filesystem_size_bytes

# --- MEMORY PRESSURE ---

# Step 9: Check node memory
kubectl top nodes
kubectl describe node <node-name> | grep -A10 "Allocated resources:"

# Step 10: Check total pod memory requests vs allocatable
kubectl describe node <node-name> | grep -A5 "Resource\|Requests\|Limits"

# Step 11: Prometheus memory metrics
# node_memory_MemAvailable_bytes{instance="<node-ip>:9100"}
# node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes

# Step 12: Check which pods consume most memory
kubectl top pods -A --sort-by=memory | head -20
kubectl top pods -A -o wide | grep <node-name>

# Step 13: Check for memory-intensive pods via cgroups on node
# SSH to node:
# cat /sys/fs/cgroup/memory/kubepods/memory.usage_in_bytes
# cat /sys/fs/cgroup/memory/kubepods/memory.limit_in_bytes

# --- PID PRESSURE ---

# Step 14: Check PID usage
# SSH to node:
# cat /proc/sys/kernel/pid_max
# ps aux | wc -l
# find /proc -maxdepth 1 -type d -name '[0-9]*' | wc -l

# Step 15: Find processes leaking PIDs
# SSH to node:
# ps aux --sort=-%cpu | head -20
# Find container consuming most PIDs:
# for pod_dir in /var/lib/kubelet/pods/*/; do
#   count=$(find /proc -maxdepth 1 -type d -name '[0-9]*' 2>/dev/null | wc -l)
#   echo "$count $pod_dir"
# done | sort -rn | head -10

# Step 16: Check kubelet eviction stats
kubectl describe node <node-name> | grep -A5 "Conditions" | grep -E "Pressure|Ready"
```

## Common Causes

### Disk Pressure
1. **Container log accumulation**: Containers writing excessive logs. Each log file is stored at `/var/log/pods/<namespace>_<pod>_<uid>/<container>/`.
2. **Large container images**: Many large images pulled to the node filling up the image filesystem.
3. **emptyDir volumes**: Pods writing large amounts of data to emptyDir volumes without ephemeral-storage limits.
4. **Core dumps**: Applications generating core dump files in container writable layers.
5. **Inode exhaustion**: Many small files (node_modules, cache files) exhausting inodes even if disk space is available.
6. **kubelet state files**: Old pod state files accumulated in `/var/lib/kubelet/pods/`.

### Memory Pressure
1. **Overcommitted memory requests**: Total memory requests across pods exceed available node memory.
2. **Memory leaks in pods**: One or more pods continuously growing in memory without limits.
3. **System processes consuming memory**: Non-Kubernetes processes (monitoring agents, logging agents) consuming significant memory.
4. **Huge pages allocation**: Huge pages reserved but not all used.

### PID Pressure
1. **Process forking bugs**: Application creating child processes without reaping them (zombie processes).
2. **Shell script loops**: Init containers or sidecar scripts in infinite loops creating processes.
3. **Java thread pools**: Java applications with too many threads contributing to PID count.
4. **Default PID limit too low**: Kubelet default pod PID limit is 1024 which is low for busy applications.

## Resolution Steps

### Resolve Disk Pressure

```bash
# Step 1: SSH to the node and identify top consumers
ssh <node-user>@<node-ip>

# Check overall disk usage
df -h

# Find large files in kubelet pod directories
sudo du -sh /var/log/pods/* 2>/dev/null | sort -rh | head -20

# Step 2: Clean up old/failed pod log directories
sudo find /var/log/pods -name "*.log" -mtime +7 -delete

# Step 3: Remove unused container images
sudo crictl rmi --prune
# List current images
sudo crictl images

# Step 4: Clean up exited containers and pods
sudo crictl rmp $(sudo crictl pods -q --state=Exited 2>/dev/null) 2>/dev/null
sudo crictl rm $(sudo crictl ps -q --state=Exited 2>/dev/null) 2>/dev/null

# Step 5: Clean up system journals
sudo journalctl --vacuum-size=200M
sudo journalctl --vacuum-time=3d

# Step 6: For containerd image storage
sudo ctr -n k8s.io snapshots ls | grep -v INUSE | awk 'NR>1{print $1}' | \
  head -5 | xargs -I {} sudo ctr -n k8s.io snapshots rm {}

# Step 7: Add ephemeral storage limits to top offenders
kubectl get pods -n <namespace> -o yaml | grep -B5 "ephemeral" | head -30
kubectl patch deployment <offending-deployment> -n <namespace> --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/resources/limits/ephemeral-storage", "value": "500Mi"}]'

# Step 8: Configure kubelet log rotation (persistent fix)
# Edit /var/lib/kubelet/config.yaml:
# containerLogMaxSize: "50Mi"
# containerLogMaxFiles: 3
# sudo systemctl restart kubelet
```

### Resolve Memory Pressure

```bash
# Step 1: Identify top memory consumers
kubectl top pods -A --sort-by=memory | head -20

# Step 2: Check for pods with no memory limits (BestEffort)
kubectl get pods -A -o json | python3 -c "
import sys, json
pods = json.load(sys.stdin)['items']
for p in pods:
    if p['status'].get('qosClass') == 'BestEffort':
        print(p['metadata']['namespace'], p['metadata']['name'])
" | head -20

# Step 3: Add limits to top memory consumers
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "256Mi"}]'

# Step 4: Scale down non-critical deployments temporarily
kubectl scale deployment <non-critical> -n <namespace> --replicas=0

# Step 5: Restart pods with suspected memory leaks
kubectl rollout restart deployment/<leak-suspect> -n <namespace>

# Step 6: Adjust kubelet eviction thresholds for soft eviction
# /var/lib/kubelet/config.yaml:
# evictionSoft:
#   memory.available: "300Mi"
# evictionSoftGracePeriod:
#   memory.available: "2m"
# evictionHard:
#   memory.available: "100Mi"
```

### Resolve PID Pressure

```bash
# Step 1: Find which container is creating many processes
# SSH to node:
for cgroup in /sys/fs/cgroup/pids/kubepods/*/; do
  pids=$(cat ${cgroup}pids.current 2>/dev/null || echo 0)
  echo "$pids $cgroup"
done | sort -rn | head -10

# Step 2: Increase pod PID limit in kubelet config
# /var/lib/kubelet/config.yaml:
# podPidsLimit: 4096  # default is 1024
# sudo systemctl restart kubelet

# Step 3: Find and fix process-leaking pods
kubectl logs <offending-pod> -n <namespace> | grep -i "fork\|spawn\|thread"

# Step 4: Restart the offending pod
kubectl delete pod <offending-pod> -n <namespace>
```

## Prometheus Alerts for Node Pressure

```yaml
# Disk pressure alert
- alert: NodeDiskPressure
  expr: kube_node_status_condition{condition="DiskPressure",status="true"} == 1
  for: 5m
  labels:
    severity: critical

# Memory pressure alert
- alert: NodeMemoryPressure
  expr: kube_node_status_condition{condition="MemoryPressure",status="true"} == 1
  for: 5m
  labels:
    severity: critical

# Preemptive disk alert (before pressure)
- alert: NodeDiskUsageHigh
  expr: |
    node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"} < 0.15
  for: 10m
  labels:
    severity: warning

# Preemptive memory alert
- alert: NodeMemoryUsageHigh
  expr: |
    node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes < 0.10
  for: 5m
  labels:
    severity: warning
```

## Prevention
- Configure `containerLogMaxSize: "50Mi"` and `containerLogMaxFiles: 3` in kubelet config
- Set ephemeral-storage limits on all pods
- Use Loki for centralized log aggregation to reduce node-local log pressure
- Set memory limits on all containers to prevent runaway memory usage
- Use VPA to right-size memory requests based on actual usage
- Implement regular node cleanup CronJob for unused images
- Monitor node resources with Prometheus + Grafana dashboards
- Set up multi-level alerting: warning at 80%, critical at 90%

## Related Issues
- `pod-evicted.md` - Pods evicted due to node pressure
- `memory-pressure.md` - Detailed memory pressure analysis
- `node-notready.md` - Pressure conditions leading to NotReady
- `cpu-throttling.md` - CPU pressure (not a kubelet condition but related)

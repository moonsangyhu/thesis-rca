# Known Issue: Container Log Rotation Not Configured Causing Disk Full

## Issue ID
KI-025

## Affected Components
- Node kubelet (log management)
- All pods on affected node
- Node disk (/var/log/pods, /var/log/containers)
- Pod scheduling (DiskPressure taint)

## Symptoms
- Node condition `DiskPressure=True`
- Pods being evicted from the node with reason `DiskPressure`
- `df -h` shows `/var` or root filesystem near 100% usage
- New pods cannot be scheduled to the node (DiskPressure taint)
- kubelet logs show: `eviction manager: attempting to reclaim ephemeral-storage`
- `du -sh /var/log/pods/*` shows some pod log directories consuming GBs

## Root Cause
By default, kubelet does not enforce container log rotation limits. Applications writing verbose logs (especially at DEBUG level, or logging request/response bodies) can fill the node disk:

1. Container stdout/stderr is written to `/var/log/pods/<namespace>_<pod>_<uid>/<container>/0.log`
2. Without `containerLogMaxSize` and `containerLogMaxFiles`, log files grow unbounded
3. When node disk usage exceeds eviction threshold (default: `imagefs.available < 15%`), kubelet starts evicting pods
4. Eviction cascade: evicted pods reschedule to other nodes → those nodes fill up too
5. Particularly dangerous with:
   - Java apps with verbose GC logging
   - Debug-level logging left enabled in production
   - Applications logging full request/response payloads
   - Sidecar containers with logging agents that buffer to disk

## Diagnostic Commands

```bash
# Check node conditions
kubectl get nodes -o custom-columns=NAME:.metadata.name,DISK:.status.conditions[?\(@.type==\"DiskPressure\"\)].status

# Check disk usage on affected node (via debug pod or SSH)
kubectl debug node/worker01 -it --image=busybox -- sh -c "df -h /host/var"

# Find largest log directories
kubectl debug node/worker01 -it --image=busybox -- sh -c \
  "du -sh /host/var/log/pods/* | sort -rh | head -20"

# Check specific pod log sizes
kubectl debug node/worker01 -it --image=busybox -- sh -c \
  "ls -lh /host/var/log/pods/boutique_frontend-*/frontend/*.log"

# Check kubelet log rotation config
kubectl get --raw "/api/v1/nodes/worker01/proxy/configz" | python3 -m json.tool | grep -i log

# Check eviction events
kubectl get events --all-namespaces --field-selector reason=Evicted --sort-by='.lastTimestamp'

# Check current eviction thresholds
kubectl describe node worker01 | grep -A5 "Conditions" | grep DiskPressure
```

## Resolution

### Step 1: Immediate cleanup (on affected node)
```bash
# SSH to the node or use kubectl debug
# Find and truncate the largest log files (keeps file handle intact)
find /var/log/pods -name "*.log" -size +100M -exec truncate -s 0 {} \;

# Or remove rotated log files
find /var/log/pods -name "*.log.*" -delete

# Verify disk space recovered
df -h /var
```

### Step 2: Configure kubelet log rotation
```yaml
# Edit kubelet configuration (KubeletConfiguration)
# For kubeadm clusters, edit the kubelet config:
apiVersion: kubelet.config.k8s.io/v1beta1
kind: KubeletConfiguration
containerLogMaxSize: "50Mi"    # Max size per log file
containerLogMaxFiles: 3         # Max number of log files per container
evictionHard:
  imagefs.available: "10%"
  nodefs.available: "10%"
evictionSoft:
  imagefs.available: "15%"
  nodefs.available: "15%"
evictionSoftGracePeriod:
  imagefs.available: "1m"
  nodefs.available: "1m"
```

```bash
# Apply on each node (kubeadm cluster)
# Edit /var/lib/kubelet/config.yaml on each node, then:
systemctl restart kubelet
```

### Step 3: Fix verbose application logging
```bash
# Identify which pods generate the most logs
kubectl top pod --all-namespaces --sort-by=cpu  # high CPU often correlates with log volume

# Check application log level configuration
kubectl get configmap -n boutique frontend-config -o yaml | grep -i log
```

### Step 4: Verify recovery
```bash
# Check DiskPressure cleared
kubectl get node worker01 -o jsonpath='{.status.conditions[?(@.type=="DiskPressure")].status}'
# Should return: False

# Check evicted pods are rescheduled
kubectl get pods --all-namespaces --field-selector status.phase=Failed,status.reason=Evicted
```

## Workaround
- Emergency: truncate large log files (`truncate -s 0 /var/log/pods/.../0.log`)
- Cordon the node to prevent new scheduling while cleaning up
- Scale down the verbose application temporarily

## Prevention
- **Always configure kubelet log rotation** in cluster bootstrap:
  - `containerLogMaxSize: 50Mi`
  - `containerLogMaxFiles: 3`
- Set application log levels via ConfigMap (easy to change without redeployment)
- Monitor node disk usage with Prometheus alert:
  ```promql
  # Alert when /var disk is above 80%
  (1 - node_filesystem_avail_bytes{mountpoint="/var"} / node_filesystem_size_bytes{mountpoint="/var"}) > 0.8
  ```
- Use structured logging (JSON) with log level filtering
- Consider log shipping to Loki with retention policies instead of local storage
- Add ephemeral storage limits to pod specs:
  ```yaml
  resources:
    limits:
      ephemeral-storage: "500Mi"
  ```

## Loki Queries
```logql
# Find pods generating the most log volume
topk(10, sum by (pod) (bytes_rate({namespace="boutique"}[5m])))

# Find error-heavy pods (likely to have verbose logging)
topk(10, sum by (pod) (rate({namespace="boutique"} |= "error" [5m])))
```

## Prometheus Queries
```promql
# Node disk usage (alert threshold)
100 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"} * 100) > 80

# DiskPressure condition active
kube_node_status_condition{condition="DiskPressure", status="true"} == 1

# Pod evictions
increase(kube_pod_container_status_last_terminated_reason{reason="Evicted"}[1h]) > 0
```

## References
- Kubelet config: https://kubernetes.io/docs/reference/config-api/kubelet-config.v1beta1/
- Eviction policy: https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/

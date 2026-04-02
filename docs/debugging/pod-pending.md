# Pod Stuck in Pending State

## Overview
A pod in `Pending` state means Kubernetes has accepted the pod definition but the scheduler cannot place it on any node. The pod exists in etcd but has not been bound to a node yet. This can be caused by insufficient resources, scheduling constraints (node selectors, taints, affinity rules), or unbound PersistentVolumeClaims. The pod will remain Pending indefinitely until the constraint is resolved.

## Symptoms
- `kubectl get pods` shows STATUS `Pending` for an extended period (more than a few seconds)
- No node assigned in `kubectl get pod -o wide` (NODE column shows `<none>`)
- `kubectl describe pod` shows `Events` with scheduling failures
- Pod never progresses to `ContainerCreating` or `Running`
- HPA may prevent scale-down while pending pods exist

## Diagnostic Commands

```bash
# Step 1: Confirm pod is pending and check for how long
kubectl get pod <pod-name> -n <namespace> -o wide
# Check AGE and NODE columns

# Step 2: Get the scheduling failure reason
kubectl describe pod <pod-name> -n <namespace>
# Focus on Events section at the bottom:
#   "0/6 nodes are available" - no schedulable node
#   "Insufficient cpu/memory" - resource constraint
#   "node(s) had untolerated taint" - taint mismatch
#   "node(s) didn't match Pod's node affinity/selector" - affinity constraint
#   "pod has unbound immediate PersistentVolumeClaims" - PVC not bound

# Step 3: Check resource availability across all nodes
kubectl describe nodes | grep -A5 "Allocated resources"
kubectl top nodes

# Step 4: Check specific resource requests vs node allocatable
kubectl get nodes -o custom-columns=\
'NAME:.metadata.name,CPU:.status.allocatable.cpu,MEMORY:.status.allocatable.memory'

# Step 5: Check the pod's resource requests
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].resources.requests}'

# Step 6: Find nodes with enough free resources
kubectl describe nodes | grep -A10 "Allocated resources:" | grep -E "cpu|memory"

# Step 7: Check node selectors on the pod
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.nodeSelector}'

# Step 8: Check node labels
kubectl get nodes --show-labels
kubectl get nodes -l <key>=<value>

# Step 9: Check taints on nodes
kubectl describe nodes | grep -A3 "Taints:"
kubectl get nodes -o custom-columns='NAME:.metadata.name,TAINTS:.spec.taints'

# Step 10: Check tolerations on the pod
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.tolerations}'

# Step 11: Check affinity and anti-affinity rules
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.affinity}' | python3 -m json.tool

# Step 12: Check PVC binding status (if pod uses PVCs)
kubectl get pvc -n <namespace>
kubectl describe pvc <pvc-name> -n <namespace>

# Step 13: Check scheduler logs for more details
kubectl logs -n kube-system -l component=kube-scheduler --tail=50

# Step 14: Check if namespace has ResourceQuota preventing scheduling
kubectl describe resourcequota -n <namespace>
kubectl get resourcequota -n <namespace> -o yaml

# Step 15: Check PodDisruptionBudget constraints
kubectl get pdb -n <namespace>
kubectl describe pdb -n <namespace>

# Step 16: Check if kube-scheduler is running
kubectl get pods -n kube-system | grep scheduler
kubectl describe pod -n kube-system -l component=kube-scheduler

# Step 17: Simulate scheduling to see which nodes are eligible
# Use dry-run to see if pod can be scheduled
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | grep <pod-name>

# Step 18: For Online Boutique namespace
kubectl get pods -n online-boutique | grep Pending
kubectl describe pod -n online-boutique <pending-pod> | tail -30
```

## Common Causes

1. **Insufficient CPU resources**: All nodes have their CPU requests fully allocated. The pod's CPU request cannot be satisfied. Note: this is about `requests`, not actual usage.

2. **Insufficient memory resources**: Similar to CPU - memory requests on all nodes are fully committed.

3. **Node selector mismatch**: Pod requires a specific node label (e.g., `disktype=ssd`) that no available node has.

4. **Unmatched taint/toleration**: Nodes have taints (e.g., `node-role.kubernetes.io/master:NoSchedule`) that the pod does not tolerate.

5. **Pod affinity/anti-affinity**: `podAntiAffinity` rules prevent scheduling when required pods already exist on all available nodes.

6. **Unbound PVC**: Pod references a PVC in `Pending` state. The scheduler waits for the PVC to be bound before placing the pod (unless `WaitForFirstConsumer` is used, in which case the pod gets scheduled first).

7. **ResourceQuota exceeded**: The namespace has a ResourceQuota and the new pod would exceed it.

8. **Node is cordoned**: All suitable nodes have been marked as unschedulable via `kubectl cordon`.

9. **DaemonSet namespace/node selector conflict**: DaemonSet pods pending because no nodes match the selector.

10. **Topology spread constraints**: `topologySpreadConstraints` cannot be satisfied with current node/pod distribution.

11. **No nodes with GPU/special resource**: Pod requests a special resource (nvidia.com/gpu) but no nodes have it.

## Resolution Steps

### Step 1: Fix insufficient resources - scale up or reduce requests
```bash
# Option A: Reduce resource requests (if over-provisioned)
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/resources/requests/cpu", "value": "100m"}]'

# Option B: Identify and remove over-allocated pods
kubectl top pods -n <namespace> --sort-by=cpu
# Look for pods using much less than they requested

# Option C: Add a new node to the cluster (infrastructure level)
# kubectl scale... (depends on your cloud provider/autoscaler)
```

### Step 2: Fix node selector mismatch
```bash
# Option A: Add the required label to a node
kubectl label node <node-name> disktype=ssd

# Option B: Remove or fix the nodeSelector in the pod
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "remove", "path": "/spec/template/spec/nodeSelector"}]'

# Option C: Change nodeSelector to match existing labels
kubectl get nodes --show-labels | grep <label-key>
kubectl edit deployment <deployment-name> -n <namespace>
```

### Step 3: Fix taint/toleration mismatch
```bash
# Option A: Add toleration to the pod
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/tolerations", "value": [{"key": "node-role.kubernetes.io/master", "operator": "Exists", "effect": "NoSchedule"}]}]'

# Option B: Remove taint from node (if appropriate)
kubectl taint node <node-name> <taint-key>-  # trailing dash removes the taint

# Option C: Check which nodes are available (not tainted)
kubectl get nodes -o json | python3 -c "
import sys, json
nodes = json.load(sys.stdin)['items']
for n in nodes:
    taints = n['spec'].get('taints', [])
    print(n['metadata']['name'], ':', taints if taints else 'No taints')
"
```

### Step 4: Fix unbound PVC
```bash
# Check PVC status
kubectl get pvc -n <namespace>
# See pvc-pending.md for detailed PVC troubleshooting

# Quick check: is StorageClass available?
kubectl get storageclass
```

### Step 5: Fix ResourceQuota
```bash
# Check quota usage
kubectl describe resourcequota -n <namespace>

# Option A: Reduce resource requests in the pod
# Option B: Delete unused pods/deployments to free quota
# Option C: Increase quota (requires admin privileges)
kubectl patch resourcequota <quota-name> -n <namespace> \
  --type='json' -p='[{"op": "replace", "path": "/spec/hard/requests.cpu", "value": "4"}]'
```

### Step 6: Uncordon a cordoned node
```bash
# Check for cordoned nodes
kubectl get nodes | grep SchedulingDisabled

# Uncordon the node
kubectl uncordon <node-name>
```

### Step 7: Fix topology spread constraints
```bash
# Check current constraint
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.topologySpreadConstraints}'

# Relax the constraint by changing whenUnsatisfiable to ScheduleAnyway
kubectl edit deployment <deployment-name> -n <namespace>
# Change: whenUnsatisfiable: DoNotSchedule
# To:     whenUnsatisfiable: ScheduleAnyway
```

## Quick Diagnosis Checklist

```bash
# Run this diagnostic script to identify the issue quickly
POD=<pod-name>
NS=<namespace>

echo "=== Pod Resource Requests ==="
kubectl get pod $POD -n $NS -o jsonpath='{.spec.containers[*].resources.requests}' | python3 -m json.tool

echo "=== Node Selector ==="
kubectl get pod $POD -n $NS -o jsonpath='{.spec.nodeSelector}'

echo "=== Tolerations ==="
kubectl get pod $POD -n $NS -o jsonpath='{.spec.tolerations}' | python3 -m json.tool

echo "=== PVCs ==="
kubectl get pod $POD -n $NS -o jsonpath='{.spec.volumes[*].persistentVolumeClaim}'

echo "=== Node Allocatable ==="
kubectl describe nodes | grep -E "Name:|Allocatable:" -A5

echo "=== Recent Events ==="
kubectl describe pod $POD -n $NS | tail -20
```

## Prevention
- Use Cluster Autoscaler to automatically add nodes when pending pods exist
- Set `PodDisruptionBudget` thoughtfully to avoid blocking evictions
- Use `podAntiAffinity` with `preferredDuringSchedulingIgnoredDuringExecution` instead of required when possible
- Monitor pending pod duration: `kube_pod_status_phase{phase="Pending"} > 0`
- Set resource requests based on actual P95 usage, not estimated
- Use `LimitRange` to set default requests/limits to prevent pods with no requests from consuming all resources
- Regularly audit ResourceQuota against actual usage

## Related Issues
- `pvc-pending.md` - PVC binding issues causing pod pending
- `resource-quota-exceeded.md` - ResourceQuota blocking pod creation
- `node-notready.md` - Node issues reducing schedulable capacity
- `node-pressure.md` - Node pressure marking nodes unschedulable

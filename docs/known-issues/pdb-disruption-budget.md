# Known Issue: PodDisruptionBudget Blocking Node Drain

## Issue ID
KI-008

## Affected Components
- PodDisruptionBudget (PDB)
- `kubectl drain` / node maintenance operations
- Cluster autoscaler (if enabled)
- All workloads with PDB configured with `minAvailable: 1` and single replica

## Symptoms
- `kubectl drain <node>` hangs indefinitely and never completes
- `kubectl drain` output shows:
  ```
  error when evicting pods/<pod-name>: Cannot evict pod as it would violate the pod's disruption budget.
  ```
- Node stays in `SchedulingDisabled` state (cordoned) but is never fully drained
- Maintenance window extends far beyond planned duration
- Cluster upgrade (which requires node drain) cannot proceed
- `kubectl get pdb -A` shows `0` in ALLOWED DISRUPTIONS column

## Root Cause
A PodDisruptionBudget with `minAvailable: 1` on a Deployment with `replicas: 1` means: "at least 1 pod must be available at all times." Since there is only 1 replica and the PDB requires 1 to be available, there is never an allowed disruption window.

The eviction API (used by `kubectl drain`) respects PDBs. When a drain is attempted, the eviction request for the pod is rejected because evicting it would bring the available count below `minAvailable: 1`.

This is logically consistent — the PDB is doing exactly what it was configured to do — but is a misconfiguration when:
- The intent was to protect against accidental deletion, not maintenance drains
- The application was scaled down from multi-replica to single-replica without updating the PDB
- The PDB was copy-pasted from a multi-replica deployment

Common problematic configurations:
```yaml
# PDB that always blocks drain for single-replica deployments
apiVersion: policy/v1
kind: PodDisruptionBudget
spec:
  minAvailable: 1
  selector:
    matchLabels:
      app: redis-master
---
# The matching Deployment with only 1 replica
apiVersion: apps/v1
kind: Deployment
spec:
  replicas: 1
```

## Diagnostic Commands
```bash
# Check drain status
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --dry-run

# List all PDBs and their disruption allowance
kubectl get pdb -A
kubectl describe pdb -A | grep -A10 "Disruptions Allowed: 0"

# Find single-replica deployments with minAvailable PDBs
kubectl get pdb -A -o json | jq '.items[] | select(.status.disruptionsAllowed == 0) | {name: .metadata.name, namespace: .metadata.namespace}'

# Check which PDB is blocking a specific pod
kubectl get pdb -n <namespace> -o yaml | grep -B5 "disruptionsAllowed: 0"

# Try evicting a pod manually to see PDB error
kubectl evict pod/<pod-name> -n <namespace>

# Check the pod's disruption budget
kubectl describe pdb <pdb-name> -n <namespace>
```

## Resolution
**Option A (Permanent Fix)**: Scale the Deployment to 2+ replicas before maintenance:
```bash
kubectl scale deployment <name> -n <namespace> --replicas=2
# Wait for new pod to be ready
kubectl rollout status deployment/<name> -n <namespace>
# Now drain can proceed (1 can be evicted while 1 remains)
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data
```

**Option B (Temporary Fix)**: Modify the PDB to allow disruptions:
```bash
# Change minAvailable to 0
kubectl patch pdb <pdb-name> -n <namespace> \
  --type merge -p '{"spec": {"minAvailable": 0}}'

# Perform drain
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data

# Restore PDB after drain
kubectl patch pdb <pdb-name> -n <namespace> \
  --type merge -p '{"spec": {"minAvailable": 1}}'
```

**Option C (Temporary Fix)**: Delete PDB for maintenance window:
```bash
kubectl delete pdb <pdb-name> -n <namespace>
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data
# Reapply PDB from Git after drain
kubectl apply -f pdb.yaml
```

**Option D**: Use `--force` and `--grace-period=0` as last resort (data loss risk):
```bash
kubectl drain <node> --ignore-daemonsets --delete-emptydir-data --force --grace-period=0
# WARNING: This will kill pods without waiting for graceful shutdown
```

## Workaround
Use `maxUnavailable` instead of `minAvailable` for single-replica stateless workloads:
```yaml
spec:
  maxUnavailable: 1  # Allows 1 disruption, even if it means 0 available
```
Note: This removes all protection for single-replica deployments.

## Prevention
- Use `minAvailable: 0` or `maxUnavailable: 1` for single-replica non-critical workloads
- Add automation check: alert when `disruptionsAllowed: 0` for more than 1 hour
- Include PDB review in deployment templates: ensure replicas >= minAvailable + 1
- Use percentage-based values for flexibility: `minAvailable: "50%"` automatically adjusts

## References
- K8s PodDisruptionBudgets: https://kubernetes.io/docs/tasks/run-application/configure-pdb/
- kubectl drain documentation: https://kubernetes.io/docs/tasks/administer-cluster/safely-drain-node/
- Disruption budgets best practices: https://kubernetes.io/docs/concepts/workloads/pods/disruptions/

# Known Issue: nodeSelector and nodeAffinity Over-Constraining Pod Scheduling

## Issue ID
KI-012

## Affected Components
- Pod scheduler
- All pods using both `nodeSelector` and `nodeAffinity`
- Deployments, StatefulSets, DaemonSets

## Symptoms
- Pods remain in `Pending` state indefinitely
- `kubectl describe pod <name>` shows:
  ```
  Events:
    Warning  FailedScheduling  <time>  default-scheduler  0/6 nodes are available: 3 node(s) didn't match Pod's node affinity/selector, 3 node(s) had taints that the pod didn't tolerate.
  ```
- No nodes satisfy the scheduling constraints despite nodes appearing healthy
- `kubectl get nodes --show-labels` shows nodes that should match, but pods still won't schedule
- Issue is not present when either `nodeSelector` OR `nodeAffinity` is used alone

## Root Cause
`nodeSelector` and `nodeAffinity` are both AND-combined by the Kubernetes scheduler. A pod will only be scheduled on a node that satisfies ALL of the following simultaneously:
1. All key-value pairs in `nodeSelector`
2. All `requiredDuringSchedulingIgnoredDuringExecution.nodeSelectorTerms` in `nodeAffinity`
3. Preferred affinity (soft constraints, weighted)

A common mistake is duplicating constraints in both fields with slightly different label keys or values, or specifying conflicting requirements:

```yaml
# PROBLEMATIC: nodeSelector requires disk=ssd, but nodeAffinity limits to zone=us-east-1a
# If no node has BOTH labels, pod is unschedulable
spec:
  nodeSelector:
    disk: ssd               # Constraint 1
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: topology.kubernetes.io/zone
            operator: In
            values: [us-east-1a]  # Constraint 2 (AND with Constraint 1)
```

Another common pattern is specifying the same node type with different label naming conventions:
```yaml
nodeSelector:
  node-type: gpu                    # Old label format
affinity:
  nodeAffinity:
    requiredDuringSchedulingIgnoredDuringExecution:
      nodeSelectorTerms:
      - matchExpressions:
        - key: accelerator
          operator: In
          values: [nvidia-gpu]      # New label format - different label!
```

If nodes only have one of these labels (not both), no node satisfies the combined constraints.

## Diagnostic Commands
```bash
# Check pod scheduling failure reason
kubectl describe pod <pod-name> -n <namespace> | grep -A20 "Events:"

# List all node labels
kubectl get nodes --show-labels

# Check a specific node's labels
kubectl describe node <node-name> | grep -A20 "Labels:"

# Test if a specific node would match nodeSelector
kubectl get node <node-name> -o json | jq '.metadata.labels' | grep -E "disk|zone|gpu"

# Use kubectl explain to understand the fields
kubectl explain pod.spec.affinity.nodeAffinity

# Simulate scheduling decision (requires kube-scheduler log level 5)
# Or use kubectl-who-can / kube-scheduler simulator

# Check all pending pods
kubectl get pods -A --field-selector=status.phase=Pending
```

## Resolution
**Step 1**: Determine which constraints are actually necessary.

If `nodeSelector` and `nodeAffinity` specify different aspects of the same requirement, consolidate them into `nodeAffinity` only:

```yaml
# CORRECT: Use only nodeAffinity, eliminate nodeSelector
spec:
  # Remove nodeSelector entirely
  affinity:
    nodeAffinity:
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: disk
            operator: In
            values: [ssd]
          - key: topology.kubernetes.io/zone
            operator: In
            values: [us-east-1a]
```

**Step 2**: If both constraints are genuinely required, ensure nodes actually have both labels:
```bash
# Add missing label to appropriate nodes
kubectl label node <node-name> disk=ssd

# Verify
kubectl get nodes --show-labels | grep disk=ssd
```

**Step 3**: If some nodes should match but don't have labels, consider using `preferredDuringSchedulingIgnoredDuringExecution` for non-critical constraints:
```yaml
spec:
  affinity:
    nodeAffinity:
      # Hard requirement
      requiredDuringSchedulingIgnoredDuringExecution:
        nodeSelectorTerms:
        - matchExpressions:
          - key: disk
            operator: In
            values: [ssd]
      # Soft preference (won't block scheduling)
      preferredDuringSchedulingIgnoredDuringExecution:
      - weight: 50
        preference:
          matchExpressions:
          - key: topology.kubernetes.io/zone
            operator: In
            values: [us-east-1a]
```

## Workaround
Temporarily remove `nodeSelector` to allow the pod to schedule while you investigate which nodes should have the required labels. Then add labels to appropriate nodes and restore the constraint.

## Prevention
- Do not use `nodeSelector` and `nodeAffinity` simultaneously unless explicitly needed and well-documented
- Prefer `nodeAffinity` exclusively as it is more expressive and replaces `nodeSelector`
- Before deploying, verify that at least one schedulable node satisfies all constraints: `kubectl get nodes -l <key>=<value>`
- Add scheduling constraint validation to CI/CD: simulate scheduling with `kubectl apply --dry-run=server`

## References
- Assigning pods to nodes: https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/
- nodeAffinity documentation: https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/#node-affinity
- nodeSelector deprecation note: https://kubernetes.io/docs/concepts/scheduling-eviction/assign-pod-node/#nodeselector

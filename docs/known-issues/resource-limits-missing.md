# Known Issue: Missing Resource Limits Causing Noisy-Neighbor Evictions

## Issue ID
KI-018

## Affected Components
- All pods without `resources.limits` configured
- kubelet resource pressure eviction
- Other pods on the same node (eviction victims)
- Node stability

## Symptoms
- Pods on a node are evicted with reason `The node was low on resource: memory`
- `kubectl describe node <name>` shows:
  ```
  Conditions:
    Type                 Status   Reason
    MemoryPressure       True     KubeletHasSufficientMemory   False
  ```
- Pods evicted are not the offending pod — other well-behaved pods are evicted because they have lower priority
- OOMKilled events for the offending pod but not before it has impacted neighbors
- `kubectl top pods -n <namespace>` shows one pod consuming far more than expected
- Node becomes `NotReady` temporarily during memory pressure

## Root Cause
Without `resources.limits`, a pod operates in the `BestEffort` QoS class and can consume any available node resources without restriction. When a memory-hungry process (memory leak, large batch job, unbounded cache) grows without limits, it can consume all available node memory.

Kubernetes kubelet eviction policy:
1. `BestEffort` pods (no requests/limits) are evicted first
2. `Burstable` pods (requests < limits or only requests) next
3. `Guaranteed` pods (requests = limits) last

Paradoxically, the offending pod is often in `BestEffort` class too (no limits), so it may be evicted alongside its victims. But the disruption it caused to neighbor workloads has already occurred.

QoS classes:
- **BestEffort**: No requests, no limits — first eviction target
- **Burstable**: Has requests, may have different/no limits
- **Guaranteed**: requests == limits for all resources — evicted last

Without cluster-wide LimitRange defaults, developers often omit resource specs:
```yaml
# Problematic: No resources configured
spec:
  containers:
  - name: app
    image: myapp:v1.0
    # No resources section
```

## Diagnostic Commands
```bash
# Find all pods without resource limits
kubectl get pods -A -o json | jq -r '
  .items[] |
  select(.spec.containers[].resources.limits == null) |
  [.metadata.namespace, .metadata.name, .spec.containers[].name] |
  @tsv
'

# Check QoS class of pods
kubectl get pods -n <namespace> -o custom-columns="NAME:.metadata.name,QOS:.status.qosClass"

# Check current resource usage vs limits
kubectl top pods -n <namespace>
kubectl top nodes

# Check for eviction events
kubectl get events -A | grep -i evict

# Check node resource pressure
kubectl describe node <node> | grep -A10 "Allocated resources"

# Find the node's eviction thresholds
kubectl describe node <node> | grep -i "eviction\|pressure"
# Or check kubelet config
ssh <node> cat /var/lib/kubelet/config.yaml | grep -A5 eviction
```

## Resolution
**Step 1**: Set resource requests and limits on all pod specs:
```yaml
spec:
  containers:
  - name: app
    resources:
      requests:
        cpu: "100m"       # Guaranteed CPU allocation for scheduling
        memory: "128Mi"   # Guaranteed memory for scheduling
      limits:
        cpu: "500m"       # Maximum CPU (throttled if exceeded)
        memory: "256Mi"   # Maximum memory (OOMKilled if exceeded)
```

**Step 2**: Apply a LimitRange to set namespace defaults so unspecified pods get reasonable limits automatically:
```yaml
apiVersion: v1
kind: LimitRange
metadata:
  name: default-limits
  namespace: production
spec:
  limits:
  - type: Container
    default:
      cpu: "500m"
      memory: "256Mi"
    defaultRequest:
      cpu: "100m"
      memory: "128Mi"
    max:
      cpu: "2"
      memory: "2Gi"
    min:
      cpu: "50m"
      memory: "64Mi"
```

Apply to all application namespaces:
```bash
for ns in production staging; do
  kubectl apply -f limitrange.yaml -n $ns
done
```

**Step 3**: Apply a ResourceQuota to cap total namespace consumption:
```yaml
apiVersion: v1
kind: ResourceQuota
metadata:
  name: namespace-quota
  namespace: production
spec:
  hard:
    requests.cpu: "10"
    requests.memory: "20Gi"
    limits.cpu: "20"
    limits.memory: "40Gi"
    pods: "50"
```

**Step 4**: Identify and fix the current offending pod:
```bash
kubectl top pods -A --sort-by=memory | head -20
# Identify the highest memory consumer

kubectl describe pod <offender> | grep -A10 "resources:"
# Confirm missing limits

# Set limits via patch (temporary)
kubectl patch deployment <name> -n <namespace> --type=json -p='[
  {"op":"add","path":"/spec/template/spec/containers/0/resources","value":{"requests":{"memory":"256Mi"},"limits":{"memory":"512Mi"}}}
]'
```

## Workaround
Use Kubernetes priority classes to protect critical pods from eviction:
```yaml
apiVersion: scheduling.k8s.io/v1
kind: PriorityClass
metadata:
  name: high-priority
value: 1000000
globalDefault: false
description: "Critical production services"
---
spec:
  priorityClassName: high-priority
```
This ensures critical pods are evicted last, but does not solve the root cause of unbounded resource consumption.

## Prevention
- Enforce resource limits via admission webhook (Kyverno or OPA):
  ```yaml
  # Kyverno: require limits on all containers
  spec:
    rules:
    - name: require-limits
      validate:
        message: "Resource limits are required"
        pattern:
          spec:
            containers:
            - resources:
                limits:
                  memory: "?*"
                  cpu: "?*"
  ```
- Apply LimitRange to every namespace as part of namespace provisioning
- Include `kubectl top nodes` and `kubectl top pods` in regular operational checks
- Set Prometheus alerts for pods exceeding 80% of their memory limits

## References
- Resource management: https://kubernetes.io/docs/concepts/configuration/manage-resources-containers/
- LimitRange: https://kubernetes.io/docs/concepts/policy/limit-range/
- ResourceQuota: https://kubernetes.io/docs/concepts/policy/resource-quotas/
- Eviction policy: https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/

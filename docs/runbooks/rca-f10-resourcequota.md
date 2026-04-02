# Runbook: F10 - ResourceQuota Exceeded Root Cause Analysis

## Trigger Conditions
Use this runbook when new pods, deployments, or other resources fail to create with `exceeded quota` errors, when FluxCD/ArgoCD reconciliation fails due to quota limits, or when scale-out operations are blocked.

## Severity
**High** — Quota exhaustion prevents any new workloads from starting, blocking recovery operations, scaling events, and deployments. Can turn a minor incident into a major outage if replacement pods cannot be created.

## Estimated Resolution Time
15-30 minutes (quota increase) or 30-60 minutes (cleanup + right-sizing)

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- Namespace admin or cluster-admin permissions (to modify ResourceQuotas)
- GitOps repo access for quota changes

## Investigation Steps

### Step 1: Identify the quota error
```bash
# Look for quota errors in recent events
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | grep -i quota

# Or describe a failing deployment/replicaset
kubectl describe replicaset <rs-name> -n <namespace>
# Look for: "exceeded quota: namespace-quota, requested: <resource>=<value>, used: ..., limited: ..."
```

### Step 2: Get current quota usage report
```bash
# List all ResourceQuotas in namespace
kubectl get resourcequota -n <namespace>

# Detailed usage view
kubectl describe resourcequota -n <namespace>
```

Example output:
```
Name:            namespace-quota
Namespace:       online-boutique
Resource         Used    Hard
--------         ----    ----
limits.cpu       3800m   4000m      <-- 95% used!
limits.memory    6144Mi  8192Mi
requests.cpu     1500m   2000m
requests.memory  3072Mi  4096Mi
pods             18      20
services         8       10
configmaps       12      15
```

### Step 3: Identify which resource is exhausted
```bash
# CPU/memory requests vs limits
kubectl get resourcequota -n <namespace> -o json | \
  jq '.items[] | {name: .metadata.name, status: .status}'

# Find which pods are consuming the most resources
kubectl top pods -n <namespace> --sort-by=cpu
kubectl top pods -n <namespace> --sort-by=memory

# Get detailed resource requests/limits per pod
kubectl get pods -n <namespace> -o json | jq -r '
  .items[] | 
  .metadata.name as $pod |
  .spec.containers[] |
  [$pod, .name,
   (.resources.requests.cpu // "0"),
   (.resources.requests.memory // "0"),
   (.resources.limits.cpu // "0"),
   (.resources.limits.memory // "0")] |
  @tsv' | column -t
```

### Step 4: Check LimitRange (per-pod defaults)
```bash
# LimitRange sets default limits if pods don't specify them
kubectl get limitrange -n <namespace>
kubectl describe limitrange -n <namespace>

# If a LimitRange sets default limits of e.g., 500m CPU per container,
# every new pod without explicit limits consumes that quota
```

### Step 5: Find and identify idle or oversized pods
```bash
# Pods with actual usage much lower than their limits (over-provisioned)
kubectl top pods -n <namespace> --containers

# Compare requests vs actual usage
# If actual CPU is 10m but requests are 500m → massive over-provisioning

# List pods with no resource requests set (will use LimitRange defaults)
kubectl get pods -n <namespace> -o json | \
  jq '.items[] | select(.spec.containers[].resources.requests == null) | .metadata.name'
```

### Step 6: Check if failed resources are from automated systems
```bash
# Check HPA scale events
kubectl get events -n <namespace> | grep -i 'scale\|HPA\|autoscal'

# Check if FluxCD is trying to deploy something that hits quota
kubectl get events -n flux-system | grep <namespace>
flux get helmreleases -n <namespace>
```

## Resolution

### Fix A: Increase the ResourceQuota (GitOps preferred)
```bash
# Direct patch (must also update in GitOps)
kubectl patch resourcequota <quota-name> -n <namespace> --type='json' \
  -p='[
    {"op": "replace", "path": "/spec/hard/limits.cpu", "value": "8000m"},
    {"op": "replace", "path": "/spec/hard/limits.memory", "value": "16Gi"},
    {"op": "replace", "path": "/spec/hard/pods", "value": "40"}
  ]'

# Via GitOps (FluxCD Kustomization) — edit the quota manifest in Git:
# spec:
#   hard:
#     requests.cpu: "4"
#     requests.memory: 8Gi
#     limits.cpu: "8"
#     limits.memory: 16Gi
#     pods: "40"

flux reconcile kustomization <kustomization-name> -n flux-system --with-source
```

### Fix B: Clean up unused/idle resources
```bash
# Delete completed/failed pods
kubectl delete pods -n <namespace> --field-selector=status.phase=Succeeded
kubectl delete pods -n <namespace> --field-selector=status.phase=Failed

# Scale down idle deployments
kubectl scale deployment <idle-deployment> -n <namespace> --replicas=0

# Delete old ReplicaSets with 0 replicas
kubectl get replicasets -n <namespace> | grep " 0 " | awk '{print $1}' | \
  xargs kubectl delete replicaset -n <namespace>
```

### Fix C: Right-size resource requests/limits
```bash
# Reduce over-provisioned limits on a specific deployment
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[
    {"op": "replace", "path": "/spec/template/spec/containers/0/resources/requests/cpu", "value": "50m"},
    {"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/cpu", "value": "200m"},
    {"op": "replace", "path": "/spec/template/spec/containers/0/resources/requests/memory", "value": "64Mi"},
    {"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "128Mi"}
  ]'

# Use VPA recommendations to right-size
kubectl get vpa -n <namespace> -o json | \
  jq '.items[] | {name: .metadata.name, recommendations: .status.recommendation.containerRecommendations}'
```

### Fix D: Move workloads to another namespace
```bash
# If quota in current namespace is genuinely exhausted,
# deploy to an overflow namespace with available quota
kubectl create namespace <overflow-namespace>
kubectl label namespace <overflow-namespace> environment=production

# Apply necessary RBAC and NetworkPolicies to the new namespace
# Update service references and DNS entries
```

## Verification
```bash
# Quota usage should show headroom
kubectl describe resourcequota -n <namespace>

# Previously blocked pods should now be creatable
kubectl rollout restart deployment/<deployment-name> -n <namespace>
kubectl rollout status deployment/<deployment-name> -n <namespace>

# No more quota exceeded events
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | grep -i quota

# Check FluxCD reconciliation is clean
flux get helmreleases -n <namespace>
```

## Escalation
- If cluster-level quota (ClusterResourceQuota) is exhausted: requires cluster-admin intervention
- If quota increase is blocked by organizational policy: escalate to platform team with business justification
- If ResourceQuota is managed by a GitOps system you cannot modify: raise PR in the infra repo and escalate to team lead

## Loki Queries

```logql
# ResourceQuota admission webhook rejections
{job="kubernetes-apiserver"} |= "exceeded quota" or |= "forbidden: exceeded quota"

# FluxCD HelmRelease failures due to quota
{namespace="flux-system", app="helm-controller"} |= "quota" or |= "forbidden"

# Deployment controller errors from quota
{job="kube-controller-manager"} |= "quota" |= "namespace" |= "<namespace>"

# Application errors from insufficient replicas
{namespace="<namespace>"} |= "no healthy upstream" or |= "circuit breaker"
```

## Prometheus Queries

```promql
# ResourceQuota usage ratio (alert if > 0.9)
kube_resourcequota{namespace="<namespace>", type="used"}
  / kube_resourcequota{namespace="<namespace>", type="hard"}

# CPU requests quota utilization
kube_resourcequota{namespace="<namespace>", resource="requests.cpu", type="used"}
  / kube_resourcequota{namespace="<namespace>", resource="requests.cpu", type="hard"}

# Memory limits quota utilization
kube_resourcequota{namespace="<namespace>", resource="limits.memory", type="used"}
  / kube_resourcequota{namespace="<namespace>", resource="limits.memory", type="hard"}

# Pod count quota utilization
kube_resourcequota{namespace="<namespace>", resource="pods", type="used"}
  / kube_resourcequota{namespace="<namespace>", resource="pods", type="hard"}

# Deployments with unavailable replicas (symptom of quota exhaustion)
kube_deployment_status_replicas_unavailable{namespace="<namespace>"} > 0

# Namespace-level CPU request sum
sum by (namespace) (kube_pod_container_resource_requests{resource="cpu", namespace="<namespace>"})
```

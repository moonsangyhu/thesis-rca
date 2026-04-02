# Runbook: Recovery After OOMKill Cascade

## Trigger Conditions
Use this runbook when an OOMKill event has caused a cascade of failures — multiple pods across a service chain are restarting, traffic is being dropped, and the system has not self-recovered within 5 minutes.

## Severity
**Critical**

## Estimated Resolution Time
30-60 minutes (full recovery including traffic normalization)

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- Prometheus/Grafana access for traffic and memory monitoring
- GitOps repo write access (FluxCD/ArgoCD)
- Optional: Load balancer or ingress access to stop incoming traffic

## Recovery Procedure

### Phase 1: Stop the Bleeding — Reduce Traffic Load

```bash
# Option A: Scale down frontend to stop new requests
kubectl scale deployment frontend -n online-boutique --replicas=0

# Option B: Apply rate limiting at ingress level
kubectl annotate ingress <ingress-name> -n online-boutique \
  nginx.ingress.kubernetes.io/limit-rps="10"

# Option C: If using Cilium L7 policy, apply traffic shaping
# (see cilium-network-troubleshoot.md for details)
```

### Phase 2: Identify Root Cause

```bash
# Identify which pods are OOMKilled and in CrashLoopBackOff
kubectl get pods -n online-boutique | grep -E 'OOMKill|CrashLoop|Error'

# Find the cascade origin (which service killed first?)
kubectl get events -n online-boutique --sort-by='.lastTimestamp' | grep -i oom | head -20

# Check memory usage trend leading up to the kill
# (Prometheus query — see section below)
kubectl top pods -n online-boutique --sort-by=memory

# Identify restart counts
kubectl get pods -n online-boutique -o json | \
  jq '.items[] | {name: .metadata.name, restarts: [.status.containerStatuses[].restartCount] | add}'
```

### Phase 3: Adjust Memory Limits

```bash
# Suspend FluxCD to prevent it from reverting changes
flux suspend helmrelease online-boutique -n online-boutique

# For each OOMKilled service, increase memory limit
# (Rule of thumb: 2x current limit, minimum 256Mi)
for deployment in cartservice frontend productcatalogservice; do
  CURRENT=$(kubectl get deployment $deployment -n online-boutique \
    -o jsonpath='{.spec.template.spec.containers[0].resources.limits.memory}')
  echo "$deployment current limit: $CURRENT"
done

# Apply new limits
kubectl patch deployment cartservice -n online-boutique --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "512Mi"}]'

kubectl patch deployment frontend -n online-boutique --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "256Mi"}]'

# Adjust other affected services similarly
```

### Phase 4: Stabilize the Cascade Services

```bash
# Force restart affected deployments in dependency order
# (Start with leaf services, work up to frontend)
RECOVERY_ORDER="redis-cart cartservice productcatalogservice currencyservice paymentservice shippingservice emailservice recommendationservice checkoutservice frontend"

for svc in $RECOVERY_ORDER; do
  echo "Restarting $svc..."
  kubectl rollout restart deployment/$svc -n online-boutique 2>/dev/null || true
  kubectl rollout status deployment/$svc -n online-boutique --timeout=120s || echo "WARNING: $svc not ready"
done
```

### Phase 5: Restore Traffic

```bash
# Restore frontend replicas
kubectl scale deployment frontend -n online-boutique --replicas=2

# Remove rate limiting if applied
kubectl annotate ingress <ingress-name> -n online-boutique \
  nginx.ingress.kubernetes.io/limit-rps-

# Resume FluxCD after updating values.yaml in Git
# (Update memory limits in the HelmRelease values before resuming)
flux resume helmrelease online-boutique -n online-boutique
```

### Phase 6: Update GitOps Configuration

```bash
# Update HelmRelease values in Git to persist the new limits
# Edit: online-boutique/helmrelease.yaml or values.yaml
# Example:
# cartservice:
#   resources:
#     limits:
#       memory: 512Mi
#     requests:
#       memory: 256Mi

# Commit and push, then verify FluxCD picks it up
flux reconcile helmrelease online-boutique -n online-boutique --with-source
flux get helmreleases -n online-boutique
```

## Verification

```bash
# All pods should be Running and Ready
kubectl get pods -n online-boutique

# No more OOM events
kubectl get events -n online-boutique --sort-by='.lastTimestamp' | grep -i oom

# Memory usage is stable and below new limits
kubectl top pods -n online-boutique --sort-by=memory

# Application is serving requests
kubectl run smoke-test --image=curlimages/curl --rm -it -n online-boutique -- \
  curl -s -o /dev/null -w "%{http_code}" http://frontend/

# Monitor for 10 minutes for recurrence
watch -n 30 'kubectl get pods -n online-boutique | grep -v Running'
```

## Post-Incident Actions
1. Capture VPA recommendations for all services
2. Update memory limits in GitOps with 20% headroom above peak usage
3. Add/tune `KubePodOOMKilled` Prometheus alert
4. Document in thesis: cascade pattern, detection time, MTTD/MTTR

## Escalation
- If OOMKill recurs within 1 hour of recovery: memory leak suspected — escalate to dev team for heap analysis
- If multiple nodes are under MemoryPressure: cluster capacity issue — escalate to infrastructure

## Loki Queries

```logql
# OOM timeline reconstruction
{namespace="online-boutique"} |= "OOM" or |= "Killed" or |= "memory"
  | json | __error__ = ""
  | line_format "{{.ts}} {{.pod}} {{.message}}"

# Error cascade after OOM
{namespace="online-boutique"} | json | level="error"
  | line_format "{{.ts}} [{{.pod}}] {{.message}}"
```

## Prometheus Queries

```promql
# Memory usage trend (last 2 hours) — spot the leak/spike
container_memory_working_set_bytes{namespace="online-boutique"}[2h]

# OOMKill count timeline
increase(kube_pod_container_status_restarts_total{namespace="online-boutique"}[5m])

# Memory usage ratio — current state
container_memory_working_set_bytes{namespace="online-boutique"}
  / container_spec_memory_limit_bytes{namespace="online-boutique"}

# Request error rate during recovery
rate(http_requests_total{namespace="online-boutique", status=~"5.."}[2m])
```

# Runbook: F8 - Service Endpoint Misconfiguration Root Cause Analysis

## Trigger Conditions
Use this runbook when services return `Connection refused` or `no endpoints available` errors, when Service has 0 endpoints despite pods being Running, or when traffic is intermittently routed to wrong pods. Also applies after selector label changes or namespace migrations.

## Severity
**High** — A misconfigured Service selector means 100% of traffic fails to reach the intended pods. Pods are healthy but completely unreachable via the Service abstraction.

## Estimated Resolution Time
15-25 minutes

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- Access to Service and Deployment manifests in GitOps repo

## Investigation Steps

### Step 1: Confirm the Service has no endpoints
```bash
# Check endpoints
kubectl get endpoints <service-name> -n <namespace>

# Healthy output:
# NAME        ENDPOINTS           AGE
# cartservice  10.244.1.5:7070    5d

# Unhealthy output:
# NAME        ENDPOINTS   AGE
# cartservice  <none>     5d

# Get detailed endpoint info
kubectl describe endpoints <service-name> -n <namespace>

# Check EndpointSlices (newer API)
kubectl get endpointslices -n <namespace> | grep <service-name>
kubectl describe endpointslice -n <namespace> <endpointslice-name>
```

### Step 2: Compare Service selector with Pod labels
```bash
# Get Service selector
kubectl get svc <service-name> -n <namespace> -o jsonpath='{.spec.selector}'
# Example output: {"app":"cartservice","version":"v1"}

# Get labels of pods that SHOULD be selected
kubectl get pods -n <namespace> -l app=<app-label> --show-labels

# Check if labels match exactly (case-sensitive!)
kubectl get pods -n <namespace> --show-labels | grep <service-name>

# Run selector against pods to verify match
SERVICE_SELECTOR=$(kubectl get svc <service-name> -n <namespace> -o jsonpath='{.spec.selector}' | \
  jq -r 'to_entries | map("\(.key)=\(.value)") | join(",")')
kubectl get pods -n <namespace> -l "$SERVICE_SELECTOR"
```

### Step 3: Verify pod readiness
```bash
# Endpoints only include Ready pods
kubectl get pods -n <namespace> -l <selector> -o json | \
  jq '.items[] | {name: .metadata.name, ready: .status.conditions[] | select(.type=="Ready") | .status}'

# Check readinessProbe configuration
kubectl get deployment <deployment-name> -n <namespace> -o json | \
  jq '.spec.template.spec.containers[].readinessProbe'

# A pod may be Running but not Ready (failed readiness probe)
kubectl describe pod <pod-name> -n <namespace> | grep -A 5 "Conditions:"
```

### Step 4: Check Service port configuration
```bash
# Get Service port details
kubectl get svc <service-name> -n <namespace> -o json | \
  jq '{type: .spec.type, clusterIP: .spec.clusterIP, ports: .spec.ports}'

# Verify target port matches container port
kubectl get deployment <deployment-name> -n <namespace> -o json | \
  jq '.spec.template.spec.containers[].ports'

# targetPort in Service must match containerPort in Pod
# Example mismatch: Service.targetPort=8080 but container listens on 7070
```

### Step 5: Verify Service namespace and DNS resolution
```bash
# Test DNS resolution from within cluster
kubectl run dns-test --image=busybox -n <namespace> --rm -it -- \
  nslookup <service-name>.<namespace>.svc.cluster.local

# Test cross-namespace DNS
kubectl run dns-test --image=busybox -n <other-namespace> --rm -it -- \
  nslookup <service-name>.<namespace>.svc.cluster.local

# Check CoreDNS logs
kubectl logs -n kube-system -l k8s-app=kube-dns | grep <service-name>
```

### Step 6: Check kube-proxy rules (iptables/ipvs)
```bash
# On a node, check iptables rules for the service ClusterIP
SERVICE_IP=$(kubectl get svc <service-name> -n <namespace> -o jsonpath='{.spec.clusterIP}')
echo "Service ClusterIP: $SERVICE_IP"

# SSH to a node and check
ssh -J debian@211.62.97.71:22015 ktcloud@172.25.20.111 \
  "sudo iptables -t nat -L KUBE-SERVICES | grep $SERVICE_IP"

# Or check with Cilium (which replaces kube-proxy)
kubectl exec -n kube-system <cilium-pod> -- \
  cilium service list | grep $SERVICE_IP
```

### Step 7: Check for recent label changes
```bash
# Check when deployment labels were last modified
kubectl get deployment <deployment-name> -n <namespace> -o json | \
  jq '.metadata.annotations."kubectl.kubernetes.io/last-applied-configuration"' | \
  python3 -m json.tool | grep -A5 '"labels"'

# Check recent FluxCD changes
flux get helmreleases -A
kubectl get events -n flux-system --sort-by='.lastTimestamp' | tail -10
```

## Resolution

### Fix A: Fix Service selector to match pod labels
```bash
# Option 1: Update Service selector
kubectl patch svc <service-name> -n <namespace> --type='json' \
  -p='[{"op": "replace", "path": "/spec/selector/app", "value": "<correct-label-value>"}]'

# Option 2: Update pod labels to match existing Service selector
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/metadata/labels/app", "value": "<correct-label>"}]'
```

### Fix B: Fix targetPort mismatch
```bash
# Update Service targetPort
kubectl patch svc <service-name> -n <namespace> --type='json' \
  -p='[{"op": "replace", "path": "/spec/ports/0/targetPort", "value": 7070}]'
```

### Fix C: Fix readiness probe so pods become Ready
```bash
# Increase initialDelaySeconds if app is slow to start
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/readinessProbe/initialDelaySeconds", "value": 30}]'

# Fix the readiness probe path/port if wrong
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[
    {"op": "replace", "path": "/spec/template/spec/containers/0/readinessProbe/httpGet/path", "value": "/health"},
    {"op": "replace", "path": "/spec/template/spec/containers/0/readinessProbe/httpGet/port", "value": 8080}
  ]'
```

### Fix D: Update via GitOps (recommended for persistence)
```bash
# Suspend FluxCD, fix the HelmRelease values, commit, then resume
flux suspend helmrelease <release-name> -n <namespace>

# Edit service selector in values.yaml or chart templates

flux resume helmrelease <release-name> -n <namespace>
flux reconcile helmrelease <release-name> -n <namespace> --with-source
```

## Verification
```bash
# Endpoints should now be populated
kubectl get endpoints <service-name> -n <namespace>

# Service should route traffic successfully
kubectl run curl-test --image=curlimages/curl -n <namespace> --rm -it -- \
  curl -v http://<service-name>:<port>/

# Application health check
kubectl exec -n <namespace> deploy/<client-deployment> -- \
  curl -s -o /dev/null -w "%{http_code}" http://<service-name>:<port>/

# Confirm EndpointSlice is populated
kubectl get endpointslices -n <namespace> -l kubernetes.io/service-name=<service-name> -o json | \
  jq '.items[].subsets[].addresses[].ip'
```

## Escalation
- If selector is correct but endpoints still empty: check if pods are in a different namespace
- If Service type=LoadBalancer and external IP is not assigned: check cloud LB controller
- If Cilium is not programming the service correctly: `kubectl exec <cilium-pod> -- cilium service list`

## Loki Queries

```logql
# No endpoints available error
{namespace="<namespace>"} |= "no endpoints available" or |= "connection refused"

# Service discovery failures
{namespace="<namespace>"} |= "failed to resolve" or |= "dial tcp: lookup"

# Kubernetes events for endpoint changes
{job="kubernetes-events", namespace="<namespace>"} |= "Endpoints" or |= "EndpointSlice"

# Application-level upstream errors
{namespace="<namespace>", app="frontend"} | json | http_status >= 502
```

## Prometheus Queries

```promql
# Service has no ready endpoints
kube_endpoint_address_not_ready{namespace="<namespace>"}

# Count of ready endpoints per service
kube_endpoint_address_available{namespace="<namespace>"}

# Pods that are Running but not Ready (not included in endpoints)
kube_pod_status_ready{namespace="<namespace>", condition="false"}

# HTTP 5xx error rate (downstream effect of no endpoints)
rate(http_requests_total{namespace="<namespace>", status=~"5.."}[5m])

# Service request success rate
rate(http_requests_total{namespace="<namespace>", status=~"2.."}[5m])
  / rate(http_requests_total{namespace="<namespace>"}[5m])
```

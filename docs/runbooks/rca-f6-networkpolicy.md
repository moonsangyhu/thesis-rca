# Runbook: F6 - NetworkPolicy Connectivity Blocked Root Cause Analysis

## Trigger Conditions
Use this runbook when services cannot communicate despite being healthy, HTTP requests return connection timeouts or resets, or Cilium Hubble shows dropped flows. Applies when a NetworkPolicy was recently added/modified or when namespace labels changed.

## Severity
**High** — Network policy misconfiguration causes silent failures: services appear healthy but cannot reach each other, leading to cascading 502/503 errors.

## Estimated Resolution Time
20-40 minutes

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- Cilium CLI (`cilium`) installed
- Hubble CLI (`hubble`) for flow analysis
- Access to NetworkPolicy objects in affected namespaces

## Investigation Steps

### Step 1: Confirm connectivity failure
```bash
# Test connectivity between two services
kubectl exec -n <source-namespace> <source-pod> -- \
  curl -v --max-time 5 http://<target-service>.<target-namespace>.svc.cluster.local:<port>/

# Quick check with wget
kubectl exec -n <source-namespace> <source-pod> -- \
  wget -qO- --timeout=5 http://<target-service>.<target-namespace>.svc.cluster.local:<port>/

# Check DNS resolution separately
kubectl exec -n <source-namespace> <source-pod> -- \
  nslookup <target-service>.<target-namespace>.svc.cluster.local
```

If DNS works but TCP/HTTP fails: network policy is the likely culprit.

### Step 2: Check existing NetworkPolicies
```bash
# List all NetworkPolicies in affected namespaces
kubectl get networkpolicy -A

# Describe policies in source and target namespaces
kubectl get networkpolicy -n <source-namespace> -o yaml
kubectl get networkpolicy -n <target-namespace> -o yaml

# Check if any "deny-all" policy exists
kubectl get networkpolicy -n <namespace> -o json | \
  jq '.items[] | select(.spec.podSelector == {} and (.spec.ingress == [] or .spec.egress == []))'
```

### Step 3: Use Cilium Hubble to analyze dropped flows
```bash
# Enable Hubble UI port-forward
kubectl port-forward -n kube-system svc/hubble-ui 12000:80 &

# Or use Hubble CLI directly
# Find a Cilium pod to use as Hubble relay
kubectl exec -n kube-system -it <cilium-pod> -- hubble observe \
  --namespace <namespace> \
  --verdict DROPPED \
  --last 100

# Filter for specific source/destination
kubectl exec -n kube-system -it <cilium-pod> -- hubble observe \
  --from-namespace <source-namespace> \
  --to-namespace <target-namespace> \
  --verdict DROPPED \
  --last 50

# Show all flows (including forwarded) for debugging
kubectl exec -n kube-system -it <cilium-pod> -- hubble observe \
  --namespace <namespace> \
  --last 200 -o json | jq '{source: .source, destination: .destination, verdict: .verdict, type: .type}'
```

### Step 4: Check Cilium endpoint and policy enforcement
```bash
# List Cilium endpoints and their policy enforcement status
kubectl exec -n kube-system <cilium-pod> -- cilium endpoint list

# Get policy for a specific endpoint
kubectl exec -n kube-system <cilium-pod> -- cilium endpoint get <endpoint-id>

# Check policy verdict for specific traffic
kubectl exec -n kube-system <cilium-pod> -- \
  cilium policy trace \
  --src-k8s-pod <source-namespace>/<source-pod> \
  --dst-k8s-pod <target-namespace>/<target-pod> \
  --dport <port>

# Check Cilium network policy (translated from K8s NetworkPolicy)
kubectl exec -n kube-system <cilium-pod> -- cilium policy get
```

### Step 5: Analyze the NetworkPolicy logic
```bash
# For a target pod receiving traffic, check ingress rules:
kubectl get networkpolicy -n <target-namespace> -o json | jq '
  .items[] | 
  {name: .metadata.name, 
   podSelector: .spec.podSelector,
   ingress: .spec.ingress}'

# Key questions:
# 1. Is there a default-deny-ingress policy?
# 2. Does any ingress rule allow traffic from the source namespace/pod?
# 3. Are the podSelector labels correct?

# Check pod labels (must match NetworkPolicy podSelector)
kubectl get pod <source-pod> -n <source-namespace> --show-labels
kubectl get pod <target-pod> -n <target-namespace> --show-labels

# Check namespace labels (must match namespaceSelector)
kubectl get namespace <source-namespace> --show-labels
```

### Step 6: Build connectivity test matrix
```bash
# Create a test script to check all service-to-service paths
# For Online Boutique services:
services=(frontend cartservice productcatalogservice currencyservice paymentservice shippingservice emailservice checkoutservice recommendationservice adservice)

for svc in "${services[@]}"; do
  echo "Testing: frontend -> $svc"
  kubectl exec -n online-boutique deploy/frontend -- \
    curl -s --max-time 3 http://$svc:$(kubectl get svc $svc -n online-boutique -o jsonpath='{.spec.ports[0].port}')/ \
    -o /dev/null -w "%{http_code}" 2>&1 || echo "FAILED"
done
```

### Step 7: Check if NetworkPolicy was recently changed
```bash
# Check FluxCD Git diff for NetworkPolicy changes
kubectl get networkpolicy -A -o yaml | grep -A5 "creationTimestamp"

# Check kustomization status
flux get kustomizations -A

# Check recent FluxCD reconcile events
kubectl get events -n flux-system --sort-by='.lastTimestamp' | tail -20
```

## Resolution

### Fix A: Add missing ingress allow rule
```bash
# Allow traffic from specific namespace
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-from-<source-ns>
  namespace: <target-namespace>
spec:
  podSelector:
    matchLabels:
      app: <target-app>
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: <source-namespace>
    - podSelector:
        matchLabels:
          app: <source-app>
    ports:
    - protocol: TCP
      port: <port>
EOF
```

### Fix B: Add missing egress allow rule
```bash
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-egress-to-<target-app>
  namespace: <source-namespace>
spec:
  podSelector:
    matchLabels:
      app: <source-app>
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: <target-namespace>
    ports:
    - protocol: TCP
      port: <port>
  # Always allow DNS
  - ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
EOF
```

### Fix C: Temporarily remove blocking policy (for diagnosis)
```bash
# CAUTION: Only in test environments
kubectl delete networkpolicy <policy-name> -n <namespace>

# Test if connectivity is restored
kubectl exec -n <source-ns> <pod> -- curl http://<target-svc>.<target-ns>/

# Recreate with correct rules after diagnosis
```

### Fix D: Label namespace correctly for selector matching
```bash
kubectl label namespace <namespace> \
  kubernetes.io/metadata.name=<namespace> \
  environment=production
```

## Verification
```bash
# Confirm traffic flows after policy update
kubectl exec -n <source-namespace> <source-pod> -- \
  curl -v --max-time 5 http://<target-service>.<target-namespace>.svc.cluster.local:<port>/

# Hubble should show FORWARDED instead of DROPPED
kubectl exec -n kube-system -it <cilium-pod> -- hubble observe \
  --from-namespace <source-namespace> \
  --to-namespace <target-namespace> \
  --last 20

# Application-level health check
kubectl exec -n <namespace> deploy/frontend -- \
  curl -s http://frontend/healthz
```

## Escalation
- If Cilium is dropping traffic even with permissive NetworkPolicies: check CiliumNetworkPolicy CRDs and L7 policies
- If policy is correct but traffic still drops after Cilium restart: check BPF map corruption (`cilium bpf policy get`)
- If MTU mismatch causing fragmentation: see Cilium MTU runbook

## Loki Queries

```logql
# Connection refused/timeout errors in application logs
{namespace="<namespace>"} |= "connection refused" or |= "i/o timeout" or |= "no route to host"

# DNS resolution failures (often caused by missing egress UDP/53 rule)
{namespace="<namespace>"} |= "no such host" or |= "DNS" |= "error"

# Cilium policy drop events
{namespace="kube-system", app="cilium"} |= "Policy verdict" |= "denied"

# HTTP 5xx errors (downstream effect of network policy blocking)
{namespace="<namespace>"} | json | status >= 500
```

## Prometheus Queries

```promql
# Cilium policy drop rate
rate(cilium_drop_count_total{reason="Policy denied"}[5m])

# HTTP error rate (indirect effect)
rate(http_requests_total{namespace="<namespace>", status=~"5.."}[5m])
  / rate(http_requests_total{namespace="<namespace>"}[5m])

# TCP connection errors
rate(node_netstat_Tcp_RetransSegs[5m])

# Network receive errors on pods
rate(container_network_receive_errors_total{namespace="<namespace>"}[5m])

# Cilium endpoint policy drops per pod
rate(cilium_policy_endpoint_enforcement_status[5m])
```

# NetworkPolicy Troubleshooting

## Overview
Kubernetes NetworkPolicy resources control traffic flow between pods. When NetworkPolicies are applied incorrectly, traffic is silently dropped without clear error messages to the application. With Cilium 1.15.6 as the CNI, NetworkPolicy enforcement is done via eBPF programs and Hubble provides observability into policy decisions. Common pitfalls include default-deny policies blocking legitimate traffic, misconfigured pod selectors, and namespace selectors not matching intended namespaces. Cilium also supports CiliumNetworkPolicy (CNP) for extended functionality.

## Symptoms
- Connection timeout or connection refused between pods that should communicate
- Application returns errors indicating downstream service unavailable
- Hubble shows packets with verdict `DROPPED` and reason `POLICY_DENIED`
- Traffic works from debug pod with no policies but fails from application pod
- Inter-namespace communication fails (e.g., ingress controller to backend)
- Traffic was working before but stopped after a NetworkPolicy was applied

## Diagnostic Commands

```bash
# Step 1: List all NetworkPolicies
kubectl get networkpolicy -n <namespace>
kubectl get networkpolicy -A  # all namespaces

# Step 2: Describe specific policy
kubectl describe networkpolicy <policy-name> -n <namespace>

# Step 3: Check for default-deny policies
kubectl get networkpolicy -n <namespace> -o json | python3 -c "
import sys, json
policies = json.load(sys.stdin)['items']
for p in policies:
    spec = p['spec']
    pod_sel = spec.get('podSelector', {})
    types = spec.get('policyTypes', [])
    # Default deny: empty podSelector (matches all pods) with policyType but no rules
    if pod_sel == {} or pod_sel.get('matchLabels') is None:
        ingress_rules = spec.get('ingress', [])
        egress_rules = spec.get('egress', [])
        if ('Ingress' in types and not ingress_rules) or ('Egress' in types and not egress_rules):
            print(f'DEFAULT DENY: {p[\"metadata\"][\"name\"]}')
"

# Step 4: Use Hubble to see policy drops
CILIUM_POD=$(kubectl get pod -n kube-system -l k8s-app=cilium -o jsonpath='{.items[0].metadata.name}')

# Observe all drops in namespace
kubectl exec -n kube-system $CILIUM_POD -- \
  hubble observe --namespace <namespace> --verdict DROPPED --last 100

# Observe drops for specific pod
kubectl exec -n kube-system $CILIUM_POD -- \
  hubble observe \
  --from-pod <namespace>/<pod-name> \
  --verdict DROPPED --last 50

kubectl exec -n kube-system $CILIUM_POD -- \
  hubble observe \
  --to-pod <namespace>/<pod-name> \
  --verdict DROPPED --last 50

# Step 5: Cilium monitor for live drop events
kubectl exec -n kube-system $CILIUM_POD -- cilium monitor --type drop

# Step 6: Check Cilium endpoint policy
EP_ID=$(kubectl exec -n kube-system $CILIUM_POD -- \
  cilium endpoint list -o json | python3 -c "
import sys, json
eps = json.load(sys.stdin)
for ep in eps:
    if '<pod-name>' in ep.get('labels', {}).get('k8s:io.kubernetes.pod.name', ''):
        print(ep['id'])
        break
")
kubectl exec -n kube-system $CILIUM_POD -- cilium endpoint get $EP_ID
kubectl exec -n kube-system $CILIUM_POD -- cilium policy get

# Step 7: Check if CiliumNetworkPolicy (Cilium-specific) is applied
kubectl get ciliumnetworkpolicy -n <namespace>
kubectl describe ciliumnetworkpolicy -n <namespace>

# Step 8: Check namespace labels (used in namespaceSelector)
kubectl get namespace <namespace> --show-labels

# Step 9: Simulate traffic to test policy
# Create test pod in source namespace
kubectl run src-test -n <source-ns> --image=nicolaka/netshoot --rm -it --restart=Never -- \
  curl -v http://<service-name>.<target-ns>.svc.cluster.local:<port>/

# Step 10: Test connectivity and compare with/without policy
# Check what would happen without NetworkPolicy
kubectl run bypass-test -n <namespace> --image=nicolaka/netshoot --rm -it --restart=Never -- \
  curl -v http://<target-pod-ip>:<port>/
# If this works but named service doesn't, it's a selector or DNS issue, not policy

# Step 11: Check policy for specific pod selector
kubectl get networkpolicy -n <namespace> -o json | python3 -c "
import sys, json
policies = json.load(sys.stdin)['items']
pod_labels = {'app': '<app-label>'}  # Replace with actual pod labels
for p in policies:
    sel = p['spec'].get('podSelector', {}).get('matchLabels', {})
    if not sel or all(pod_labels.get(k) == v for k,v in sel.items()):
        print(f'Policy applies to pod: {p[\"metadata\"][\"name\"]}')
        print(json.dumps(p['spec'], indent=2)[:500])
"

# Step 12: Check if ingress from specific namespace is allowed
kubectl get networkpolicy <policy-name> -n <namespace> -o yaml | grep -A20 "ingress:"

# Step 13: Use Hubble for namespace-level drop analysis
# With hubble relay/CLI:
hubble observe --namespace <namespace> --type drop -o json 2>/dev/null | \
  python3 -c "
import sys, json
for line in sys.stdin:
    try:
        e = json.loads(line)
        flow = e.get('flow', {})
        if flow.get('verdict') == 'DROPPED':
            src = flow.get('source', {})
            dst = flow.get('destination', {})
            reason = flow.get('drop_reason_desc', 'UNKNOWN')
            print(f'{src.get(\"namespace\")}/{src.get(\"pod_name\",src.get(\"ip\",\"?\"))} -> {dst.get(\"namespace\")}/{dst.get(\"pod_name\",dst.get(\"ip\",\"?\"))} [{reason}]')
    except: pass
"
```

## Common Causes

1. **Default-deny policy without whitelist rules**: A NetworkPolicy with empty podSelector (matches all pods) and policyTypes Ingress/Egress with no rules blocks all traffic in the namespace.

2. **Missing egress rule for DNS**: After applying a default-deny egress policy, DNS queries to CoreDNS (kube-dns port 53) are blocked, causing all service resolution to fail.

3. **Namespace selector mismatch**: Policy allows ingress from `namespaceSelector` with specific labels, but the source namespace doesn't have those labels.

4. **Pod selector too narrow**: Policy allows traffic from pods with label `app=frontend` but the pods have label `app=frontend-v2`.

5. **Missing egress rule for egress traffic**: Application initiates outbound connections (e.g., to external APIs) but egress is blocked.

6. **Wrong port in policy**: Policy allows TCP port 80 but service is running on port 8080.

7. **Policy blocks Cilium health checks**: Cilium's internal health check traffic is blocked, causing nodes to report as unhealthy.

8. **CiliumNetworkPolicy conflict with Kubernetes NetworkPolicy**: Conflicting rules between standard Kubernetes NetworkPolicy and Cilium-specific CiliumNetworkPolicy.

## Resolution Steps

### Step 1: Add allow rule for missing traffic
```bash
# Example: allow ingress to backend pods from frontend pods
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-frontend-to-backend
  namespace: <namespace>
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Ingress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: frontend
    ports:
    - protocol: TCP
      port: 8080
EOF
```

### Step 2: Fix DNS egress blocking
```bash
# Always include this rule when using egress policies
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-egress
  namespace: <namespace>
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
    ports:
    - protocol: UDP
      port: 53
    - protocol: TCP
      port: 53
EOF
```

### Step 3: Fix namespace selector (add required label)
```bash
# Check current namespace labels
kubectl get namespace <source-namespace> --show-labels

# Add required label to allow traffic
kubectl label namespace <source-namespace> environment=production

# Verify the NetworkPolicy uses this label
kubectl get networkpolicy -n <target-namespace> -o yaml | grep -A5 namespaceSelector
```

### Step 4: Temporarily remove policy for debugging
```bash
# CAUTION: Only in dev/test environments
kubectl delete networkpolicy <policy-name> -n <namespace>

# Test if connectivity works without policy
kubectl exec -it <pod-name> -n <namespace> -- curl http://<service>:<port>/

# Re-apply corrected policy
kubectl apply -f corrected-policy.yaml
```

### Step 5: Create permissive policy for debugging
```bash
# Temporarily allow all traffic to identify which flow is blocked
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-all-debug
  namespace: <namespace>
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - {}
  egress:
  - {}
EOF

# Test connectivity
# ...
# Remove debug policy and apply targeted fix
kubectl delete networkpolicy allow-all-debug -n <namespace>
```

### Step 6: Online Boutique NetworkPolicy example
```bash
# Online Boutique requires specific inter-service communication
# Frontend needs to reach multiple backends
cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: frontend-egress
  namespace: online-boutique
spec:
  podSelector:
    matchLabels:
      app: frontend
  policyTypes:
  - Egress
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: cartservice
    ports:
    - port: 7070
  - to:
    - podSelector:
        matchLabels:
          app: productcatalogservice
    ports:
    - port: 3550
  - to:
    - podSelector:
        matchLabels:
          app: currencyservice
    ports:
    - port: 7000
  - to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system
    ports:
    - port: 53
      protocol: UDP
EOF
```

### Step 7: Use CiliumNetworkPolicy for L7 policies
```bash
# CiliumNetworkPolicy allows L7 (HTTP) policies
cat <<EOF | kubectl apply -f -
apiVersion: cilium.io/v2
kind: CiliumNetworkPolicy
metadata:
  name: allow-specific-http-path
  namespace: <namespace>
spec:
  endpointSelector:
    matchLabels:
      app: backend
  ingress:
  - fromEndpoints:
    - matchLabels:
        app: frontend
    toPorts:
    - ports:
      - port: "8080"
        protocol: TCP
      rules:
        http:
        - method: "GET"
          path: "/api/.*"
EOF
```

## NetworkPolicy Testing Checklist

```bash
# Comprehensive test script for namespace policies
NS=<namespace>

echo "=== Network Policies in $NS ==="
kubectl get networkpolicy -n $NS

echo ""
echo "=== Pod Labels ==="
kubectl get pods -n $NS --show-labels | grep -v "^NAME"

echo ""
echo "=== Namespace Labels ==="
kubectl get ns $NS --show-labels

echo ""
echo "=== Cilium Policy (if using Cilium CNP) ==="
kubectl get ciliumnetworkpolicy -n $NS 2>/dev/null

echo ""
echo "=== Hubble Drops (last 20) ==="
CILIUM_POD=$(kubectl get pod -n kube-system -l k8s-app=cilium -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n kube-system $CILIUM_POD -- \
  hubble observe --namespace $NS --verdict DROPPED --last 20 2>/dev/null || echo "Hubble not available"
```

## Prevention
- Always include a DNS egress rule when creating egress policies
- Label namespaces consistently for use in namespaceSelector
- Use Hubble UI to visualize traffic flows before implementing policies
- Test NetworkPolicy in staging environment before production
- Use `cilium network-policy-to-human-readable` tools to document policies
- Implement a policy-as-code workflow (policies in Git, applied via FluxCD)
- Use `--policy-audit-mode` in Cilium to log violations before enforcing

## Related Issues
- `network-connectivity.md` - General network connectivity issues
- `service-unreachable.md` - Service access blocked by policy
- `dns-resolution-failure.md` - DNS blocked by egress policy
- `gitops-flux-troubleshoot.md` - Deploying policies via FluxCD

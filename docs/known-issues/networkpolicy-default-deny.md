# Known Issue: Default-Deny NetworkPolicy Blocking DNS and Monitoring Traffic

## Issue ID
KI-017

## Affected Components
- NetworkPolicy
- CoreDNS (kube-system namespace)
- Prometheus scraping (monitoring namespace)
- All pods in namespaces with default-deny NetworkPolicy
- Cilium network policy enforcement

## Symptoms
- All pods in the namespace fail to resolve DNS names after applying default-deny policy:
  ```
  curl: (6) Could not resolve host: redis-master.cache.svc.cluster.local
  ```
- Pod logs show: `dial tcp: lookup <hostname> on 10.96.0.10:53: i/o timeout`
- Prometheus shows targets in `DOWN` state for pods in the restricted namespace
- `kubectl exec` into pods shows no network connectivity to any external service
- Application-level health checks fail due to inability to connect to downstream services
- Monitoring alerts fire for all services in the namespace simultaneously after policy is applied

## Root Cause
A default-deny NetworkPolicy blocks all ingress and egress traffic to pods in the selected namespace:
```yaml
# Common default-deny pattern that causes issues
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: production
spec:
  podSelector: {}          # Matches ALL pods in namespace
  policyTypes:
  - Ingress
  - Egress
  # No ingress/egress rules = deny all
```

This blocks traffic that administrators often forget about:

**1. DNS traffic (UDP/TCP port 53 to kube-dns)**
CoreDNS runs in `kube-system` namespace. Every pod needs egress to `kube-system` on port 53. Without this exception, all DNS lookups fail, breaking virtually all network communication.

**2. Prometheus scraping**
Prometheus (in `monitoring` namespace) needs ingress access to scrape metrics endpoints. Default-deny blocks this, causing all targets to show as DOWN.

**3. Liveness/readiness probe traffic from kubelet**
Kubelet sends HTTP probes from the node's IP. Ingress from node CIDRs must be allowed, or HTTP probes fail and pods are killed/marked unready.

## Diagnostic Commands
```bash
# Check NetworkPolicies in a namespace
kubectl get networkpolicy -n <namespace>
kubectl describe networkpolicy default-deny-all -n <namespace>

# Test DNS from inside a pod
kubectl exec -it <pod> -n <namespace> -- nslookup kubernetes.default

# Test connectivity to CoreDNS
kubectl exec -it <pod> -n <namespace> -- nc -zv 10.96.0.10 53  # ClusterIP of kube-dns

# Check Prometheus targets (if accessible)
# curl http://prometheus:9090/api/v1/targets | jq '.data.activeTargets[] | select(.health=="down")'

# Check Cilium network policy enforcement
kubectl -n kube-system exec -it ds/cilium -- cilium monitor --type policy-verdict 2>&1 | head -50

# Check if the probe traffic is being blocked
kubectl get events -n <namespace> | grep -i "probe\|network\|connect"

# Verify kube-dns ClusterIP
kubectl -n kube-system get svc kube-dns
```

## Resolution
When applying a default-deny policy, always include explicit allow rules for essential traffic.

**Complete NetworkPolicy with all necessary exceptions**:
```yaml
---
# Default deny all
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-all
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  - Egress

---
# Allow DNS egress to kube-system
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-egress
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
    to:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: kube-system

---
# Allow Prometheus scraping ingress
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-prometheus-scrape
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - from:
    - namespaceSelector:
        matchLabels:
          kubernetes.io/metadata.name: monitoring
    ports:
    - port: 8080   # Adjust to your metrics port
    - port: 9090

---
# Allow kubelet health probe ingress
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-kubelet-probes
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Ingress
  ingress:
  - from:
    - ipBlock:
        cidr: 172.25.20.0/24   # Node CIDR for this cluster
```

**Apply in the correct order** (allow rules before deny):
```bash
kubectl apply -f allow-dns-egress.yaml -n production
kubectl apply -f allow-prometheus-scrape.yaml -n production
kubectl apply -f allow-kubelet-probes.yaml -n production
kubectl apply -f default-deny-all.yaml -n production
```

**Verify after applying**:
```bash
kubectl exec -it <pod> -n production -- nslookup kubernetes.default
# Expected: returns IP address
```

## Workaround
If default-deny was applied and broke DNS, quickly add the DNS allow policy:
```bash
kubectl apply -f - <<EOF
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: allow-dns-emergency
  namespace: production
spec:
  podSelector: {}
  policyTypes:
  - Egress
  egress:
  - ports:
    - port: 53
      protocol: UDP
    - port: 53
      protocol: TCP
EOF
```

## Prevention
- Never apply a default-deny policy without simultaneously applying the DNS allow policy
- Test NetworkPolicy changes in a staging namespace first
- Use `--dry-run=client` combined with a policy simulation tool before applying
- Include DNS egress and monitoring ingress in all default-deny NetworkPolicy templates
- Ensure the `kube-system` namespace has the label `kubernetes.io/metadata.name: kube-system` (set by default in K8s 1.21+)

## References
- NetworkPolicy documentation: https://kubernetes.io/docs/concepts/services-networking/network-policies/
- Cilium NetworkPolicy: https://docs.cilium.io/en/stable/network/kubernetes/policy/
- Network policy recipes: https://github.com/ahmetb/kubernetes-network-policy-recipes

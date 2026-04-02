# Debugging DNS Resolution Failure

## Overview
DNS resolution in Kubernetes is handled by CoreDNS. Pods use the cluster DNS service to resolve both cluster-internal service names and external hostnames. Failures cause connection errors, timeouts, and application startup issues.

## Symptoms
- Application logs: `could not resolve host`, `NXDOMAIN`, `dial tcp: lookup X: no such host`
- Slow service discovery (high latency before connection)
- `nslookup` or `dig` failing inside pods
- CoreDNS pods in CrashLoopBackOff or high error rate
- Intermittent connection failures between services

## Diagnostic Commands

```bash
# Check CoreDNS pods status
kubectl get pods -n kube-system -l k8s-app=kube-dns

# Check CoreDNS logs for errors
kubectl logs -n kube-system -l k8s-app=kube-dns --tail=50

# Test DNS from a debug pod
kubectl run dnstest --rm -it --image=busybox:1.36 --restart=Never -- sh -c \
  "nslookup kubernetes.default.svc.cluster.local && \
   nslookup frontend.boutique.svc.cluster.local && \
   nslookup google.com"

# Check pod's DNS configuration
kubectl exec <pod> -n <ns> -- cat /etc/resolv.conf

# Check CoreDNS ConfigMap
kubectl get configmap coredns -n kube-system -o yaml

# Check kube-dns service
kubectl get svc kube-dns -n kube-system
kubectl get endpoints kube-dns -n kube-system

# Measure DNS latency
kubectl run dnsperf --rm -it --image=busybox:1.36 --restart=Never -- sh -c \
  "time nslookup frontend.boutique.svc.cluster.local"
```

## Common Causes

### 1. ndots:5 causing excessive DNS lookups
Default `ndots: 5` means any name with fewer than 5 dots is tried against all search domains first.
For `frontend.boutique.svc.cluster.local`, resolv.conf tries:
1. `frontend.boutique.svc.cluster.local.boutique.svc.cluster.local` (NXDOMAIN)
2. `frontend.boutique.svc.cluster.local.svc.cluster.local` (NXDOMAIN)
3. `frontend.boutique.svc.cluster.local.cluster.local` (NXDOMAIN)
4. `frontend.boutique.svc.cluster.local` (SUCCESS)

This 4x overhead is worse for external names like `api.example.com`.

```yaml
# Fix: reduce ndots or use FQDN with trailing dot
spec:
  dnsConfig:
    options:
      - name: ndots
        value: "2"
```

### 2. CoreDNS pods not running or overloaded
```bash
kubectl top pod -n kube-system -l k8s-app=kube-dns
# High CPU = overloaded, consider scaling up replicas
kubectl scale deployment coredns -n kube-system --replicas=3
```

### 3. kube-dns service IP unreachable
NetworkPolicy blocking DNS traffic (port 53 UDP/TCP).
```bash
# Verify DNS service is reachable
kubectl run dnstest --rm -it --image=busybox:1.36 --restart=Never -- \
  nslookup kubernetes.default 10.96.0.10
```

### 4. Pod dnsPolicy misconfigured
```yaml
dnsPolicy: ClusterFirst  # default, uses CoreDNS
dnsPolicy: Default        # uses node's /etc/resolv.conf (no cluster DNS!)
dnsPolicy: None           # must provide dnsConfig
```

### 5. Upstream DNS failure
CoreDNS forwards external queries to upstream DNS. If upstream is down:
```bash
kubectl logs -n kube-system -l k8s-app=kube-dns | grep -i "upstream\|forward\|SERVFAIL"
```

## Resolution Steps

1. **CoreDNS not running**: Restart or check for resource issues
   ```bash
   kubectl rollout restart deployment coredns -n kube-system
   ```

2. **NetworkPolicy blocking DNS**: Allow egress to kube-dns
   ```yaml
   apiVersion: networking.k8s.io/v1
   kind: NetworkPolicy
   metadata:
     name: allow-dns
   spec:
     podSelector: {}
     policyTypes: [Egress]
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
   ```

3. **Slow resolution (ndots)**: Set ndots:2 or use FQDNs
4. **Scale CoreDNS** for high query volume

## Prometheus Queries
```promql
# CoreDNS request rate
rate(coredns_dns_requests_total[5m])

# CoreDNS error rate
rate(coredns_dns_responses_total{rcode="SERVFAIL"}[5m])

# DNS latency
histogram_quantile(0.99, rate(coredns_dns_request_duration_seconds_bucket[5m]))
```

## Prevention
- Always allow DNS egress in NetworkPolicies
- Set appropriate ndots for applications making external calls
- Monitor CoreDNS metrics and scale proactively
- Use node-local DNS cache for high-throughput workloads

## Related Issues
- [NetworkPolicy Default Deny](../known-issues/networkpolicy-default-deny.md)
- [K8s DNS ndots](../known-issues/k8s-dns-ndots.md)

# Known Issue: High DNS Latency Due to ndots:5 Default

## Issue ID
KI-006

## Affected Components
- CoreDNS
- All pods using Kubernetes DNS resolution
- Applications making frequent external HTTP/gRPC calls
- Online Boutique microservices (cross-service calls)

## Symptoms
- Service-to-service calls have consistently elevated latency (50-200ms extra per call)
- External hostname resolution is slow even for well-known domains
- High CoreDNS CPU and query rate visible in Prometheus metrics
- `kubectl exec` into a pod and `time nslookup google.com` shows multiple queries before resolution
- Application logs show connection timeouts on the first request to a service
- DNS query logs show NXDOMAIN responses for short names before the correct FQDN resolves

## Root Cause
Kubernetes sets `ndots:5` by default in pod `/etc/resolv.conf`. The `ndots` option specifies the minimum number of dots in a name before the resolver considers it absolute (FQDN). With `ndots:5`, any hostname with fewer than 5 dots is treated as relative and the search domain list is tried first.

The default search domain list in Kubernetes is:
```
search <namespace>.svc.cluster.local svc.cluster.local cluster.local
```

For a call to `redis.cache.svc.cluster.local` (which has 4 dots, fewer than 5), the resolver will:
1. Try `redis.cache.svc.cluster.local.<namespace>.svc.cluster.local` → NXDOMAIN
2. Try `redis.cache.svc.cluster.local.svc.cluster.local` → NXDOMAIN
3. Try `redis.cache.svc.cluster.local.cluster.local` → NXDOMAIN
4. Try `redis.cache.svc.cluster.local` → SUCCESS (4th lookup!)

For external hostnames like `api.stripe.com` (3 dots):
1. Try `api.stripe.com.<namespace>.svc.cluster.local` → NXDOMAIN
2. Try `api.stripe.com.svc.cluster.local` → NXDOMAIN
3. Try `api.stripe.com.cluster.local` → NXDOMAIN
4. Try `api.stripe.com` → SUCCESS

Each NXDOMAIN lookup adds ~10-50ms of latency. For microservices making hundreds of calls per second, this compounds significantly.

## Diagnostic Commands
```bash
# Check current ndots setting in a pod
kubectl exec -it <pod-name> -- cat /etc/resolv.conf

# Trace DNS queries to see all lookups
kubectl exec -it <pod-name> -- nslookup -debug <hostname>

# Count DNS queries to CoreDNS (high rate indicates ndots issue)
kubectl -n kube-system top pods -l k8s-app=kube-dns

# Check CoreDNS query metrics in Prometheus
# Query: rate(coredns_dns_requests_total[5m])

# Check for NXDOMAIN responses
kubectl -n kube-system logs -l k8s-app=kube-dns | grep NXDOMAIN | head -20

# Time a DNS lookup from inside a pod
kubectl exec -it <pod-name> -- time nslookup google.com

# Verify with dig (more detailed)
kubectl exec -it <pod-name> -- dig +search +stats google.com
```

## Resolution
**Option A**: Reduce ndots to 2 in pod DNS config (recommended):
```yaml
apiVersion: v1
kind: Pod
spec:
  dnsConfig:
    options:
    - name: ndots
      value: "2"
```

For a Deployment:
```yaml
spec:
  template:
    spec:
      dnsConfig:
        options:
        - name: ndots
          value: "2"
```

**Option B**: Use FQDNs (with trailing dot) in service URLs:
```
# Instead of:
http://redis-master.cache.svc.cluster.local

# Use:
http://redis-master.cache.svc.cluster.local.
```
The trailing dot makes the resolver treat the name as absolute, skipping search domain lookups.

**Option C**: For cluster-wide change, modify CoreDNS configuration:
```bash
kubectl -n kube-system edit configmap coredns
# Add ndots override in the Corefile (advanced, affects all pods)
```

**Option D** (K8s 1.27+): Use the `ndots` field in the pod DNS policy spec — same as Option A.

## Workaround
For services that make external calls frequently, set `dnsPolicy: None` with explicit `nameservers` pointing to CoreDNS and set `ndots: 1`. This is aggressive but eliminates all unnecessary search-domain lookups.

## Prevention
- Set `ndots: 2` in Deployment templates as a cluster convention
- Always use FQDNs for cross-namespace service references in configuration files
- Add CoreDNS latency monitoring: alert if `coredns_dns_request_duration_seconds` p99 > 10ms
- Include DNS config review in deployment checklists for latency-sensitive services

## References
- K8s DNS for services and pods: https://kubernetes.io/docs/concepts/services-networking/dns-pod-service/
- ndots explained: https://pracucci.com/kubernetes-dns-resolution-ndots-options-and-why-it-may-affect-application-performance.html
- CoreDNS performance tuning: https://coredns.io/plugins/cache/

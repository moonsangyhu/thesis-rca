# Runbook: Online Boutique Application Troubleshooting

## Trigger Conditions
Use this runbook when the Online Boutique demo application shows end-to-end failures — frontend errors, checkout failures, cart issues, or payment problems. Use as a starting point for any Online Boutique-specific incident.

## Severity
**Varies** — Use this runbook to triage before escalating to fault-specific runbooks.

## Estimated Resolution Time
15-30 minutes (triage) + additional time per fault type

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- Browser or curl access to the frontend service
- Prometheus/Grafana access

## Service Architecture Reference

```
[User] 
  └─> frontend:8080
        ├─> productcatalogservice:3550  (gRPC - product listing)
        ├─> currencyservice:7000        (gRPC - currency conversion)
        ├─> cartservice:7070            (gRPC - cart management)
        │     └─> redis-cart:6379       (TCP - cart storage)
        ├─> adservice:9555              (gRPC - ad recommendations)
        ├─> recommendationservice:8080  (gRPC - recommendations)
        │     └─> productcatalogservice (gRPC)
        └─> checkoutservice:5050        (gRPC - checkout)
              ├─> cartservice           (gRPC)
              ├─> productcatalogservice (gRPC)
              ├─> currencyservice       (gRPC)
              ├─> shippingservice:50051 (gRPC - shipping calc)
              ├─> paymentservice:50051  (gRPC - payment processing)
              └─> emailservice:8080     (gRPC - confirmation email)
```

## Investigation Steps

### Step 1: Quick Health Check — All Services
```bash
# Check all pod statuses
kubectl get pods -n online-boutique -o wide

# Check for any non-Running pods
kubectl get pods -n online-boutique | grep -v Running

# Check restart counts (high restarts = instability)
kubectl get pods -n online-boutique -o json | \
  jq -r '.items[] | "\(.metadata.name)\t\([.status.containerStatuses[].restartCount] | add)"' | \
  sort -k2 -n -r | head -10

# Check service endpoints are populated
kubectl get endpoints -n online-boutique | grep -v "^NAME"
```

### Step 2: Test Frontend Accessibility
```bash
# Get the frontend service address
kubectl get svc frontend -n online-boutique

# If using NodePort:
NODE_IP=$(kubectl get nodes -o jsonpath='{.items[0].status.addresses[?(@.type=="InternalIP")].address}')
NODE_PORT=$(kubectl get svc frontend -n online-boutique -o jsonpath='{.spec.ports[0].nodePort}')
curl -s -o /dev/null -w "%{http_code}" http://$NODE_IP:$NODE_PORT/

# If using port-forward:
kubectl port-forward svc/frontend -n online-boutique 8080:80 &
curl -s -o /dev/null -w "%{http_code}" http://localhost:8080/

# Test specific pages that exercise the service chain
curl -s http://localhost:8080/ | grep -i "online boutique"  # homepage
curl -s http://localhost:8080/cart | grep -i cart            # cart (cartservice + redis)
curl -s http://localhost:8080/product/OLJCESPC7Z | grep -c product  # product page
```

### Step 3: Test Each Service Directly (gRPC)
```bash
# Test from within the cluster
kubectl run grpc-test --image=fullstorydev/grpcurl:latest -n online-boutique --rm -it -- \
  -plaintext productcatalogservice:3550 hipstershop.ProductCatalogService/ListProducts

# Test cartservice
kubectl run grpc-test --image=fullstorydev/grpcurl:latest -n online-boutique --rm -it -- \
  -plaintext cartservice:7070 hipstershop.CartService/GetCart \
  -d '{"user_id": "test-user-1"}'

# Test currencyservice
kubectl run grpc-test --image=fullstorydev/grpcurl:latest -n online-boutique --rm -it -- \
  -plaintext currencyservice:7000 hipstershop.CurrencyService/GetSupportedCurrencies
```

### Step 4: Check Redis Cart (Common Failure Point)
```bash
# Redis health
kubectl exec -n online-boutique deploy/redis-cart -- redis-cli PING
# Expected: PONG

# Redis connection count and info
kubectl exec -n online-boutique deploy/redis-cart -- redis-cli INFO | grep -E 'connected|memory|rdb'

# Check cartservice can reach Redis
kubectl exec -n online-boutique deploy/cartservice -- \
  sh -c 'nc -zv redis-cart 6379 && echo "Redis: REACHABLE" || echo "Redis: UNREACHABLE"'

# Check Redis PVC
kubectl get pvc -n online-boutique | grep redis
```

### Step 5: Check the Checkout Flow
```bash
# Checkout service is the most complex (fan-out to 6 services)
kubectl logs deploy/checkoutservice -n online-boutique | tail -30

# Check each dependency of checkoutservice
for svc in cartservice productcatalogservice currencyservice shippingservice paymentservice emailservice; do
  echo -n "Checking $svc: "
  kubectl exec -n online-boutique deploy/checkoutservice -- \
    sh -c "nc -zv $svc \$(kubectl get svc $svc -n online-boutique -o jsonpath='{.spec.ports[0].port}') 2>&1 | tail -1"
done 2>/dev/null || \
# Simpler fallback:
kubectl get endpoints -n online-boutique | grep -E 'cart|product|currency|shipping|payment|email'
```

### Step 6: Identify Error Patterns in Logs
```bash
# Frontend errors (shows which upstream is failing)
kubectl logs deploy/frontend -n online-boutique | grep -i error | tail -20

# gRPC errors across all services
for svc in frontend cartservice productcatalogservice currencyservice checkoutservice; do
  echo "=== $svc ==="
  kubectl logs deploy/$svc -n online-boutique 2>/dev/null | grep -iE 'error|failed|unavailable' | tail -5
done

# Check for rate/throttle errors
kubectl logs deploy/frontend -n online-boutique | grep -i 'Resource exhausted\|DeadlineExceeded\|UNAVAILABLE'
```

### Step 7: Correlate with Prometheus Metrics
```bash
# Port-forward Prometheus
kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090 &

# Key metrics to check:
# - grpc_server_handled_total{grpc_code!="OK"} (gRPC errors per service)
# - container_cpu_cfs_throttled_periods_total (CPU throttling)
# - container_memory_working_set_bytes (memory pressure)
# See Prometheus Queries section
```

## Common Fault Patterns

### Pattern 1: Frontend returns 500 for all requests
- **Cause**: productcatalogservice is down (frontend always queries it for homepage)
- **Check**: `kubectl get pod -n online-boutique -l app=productcatalogservice`
- **Fix**: See rca-f2-crashloopbackoff.md or rca-f3-imagepullbackoff.md

### Pattern 2: Cart shows empty / cart errors
- **Cause**: cartservice or redis-cart is down
- **Check**: `kubectl get pods -n online-boutique | grep -E 'cart|redis'`
- **Fix**: Check redis PVC (rca-f5-pvcpending.md) or cartservice health

### Pattern 3: Checkout fails at payment step
- **Cause**: paymentservice crash, config error, or network policy blocking
- **Check**: `kubectl logs deploy/paymentservice -n online-boutique | tail -20`
- **Fix**: See rca-f9-secretconfigmap.md (payment credentials) or rca-f6-networkpolicy.md

### Pattern 4: Product images not loading
- **Cause**: frontend cannot reach external CDN, or imageservice is OOMKilled
- **Check**: `kubectl logs deploy/frontend -n online-boutique | grep image`

### Pattern 5: Slow responses (>2s latency)
- **Cause**: CPU throttling on recommendationservice or productcatalogservice
- **Check**: `kubectl top pods -n online-boutique --sort-by=cpu`
- **Fix**: See rca-f7-cputhrottle.md

## Resolution
Refer to the appropriate fault-specific runbook based on the identified pattern above.

## Verification
```bash
# Full health check after fix
kubectl get pods -n online-boutique

# End-to-end smoke test via frontend
kubectl port-forward svc/frontend -n online-boutique 8080:80 &
sleep 2

# Test homepage (productcatalog, currency, recommendations)
curl -s -o /dev/null -w "Homepage: %{http_code}\n" http://localhost:8080/

# Test cart
curl -s -o /dev/null -w "Cart: %{http_code}\n" \
  "http://localhost:8080/cart?sessionID=test-$(date +%s)"

# Test product page
curl -s -o /dev/null -w "Product: %{http_code}\n" \
  http://localhost:8080/product/OLJCESPC7Z

# Kill port-forward
pkill -f "kubectl port-forward svc/frontend"
```

## Escalation
- If all services healthy but frontend still errors: check ingress/LB configuration
- If intermittent failures only under load: HPA configuration or connection pool exhaustion
- For thesis documentation: record MTTD, MTTR, and which service was root cause

## Loki Queries

```logql
# Frontend upstream errors (shows which service is failing)
{namespace="online-boutique", app="frontend"} |= "error" or |= "failed"

# gRPC deadline exceeded (often CPU throttle induced)
{namespace="online-boutique"} |= "DeadlineExceeded" or |= "context deadline exceeded"

# Payment failures (sensitive — may indicate config issue)
{namespace="online-boutique", app="paymentservice"} |= "error" or |= "invalid"

# Cart/Redis connection errors
{namespace="online-boutique", app="cartservice"} |= "redis" |= "error"

# All errors across all services, rate
sum(rate({namespace="online-boutique"} |= "error" [5m])) by (app)
```

## Prometheus Queries

```promql
# gRPC error rate per service
sum by (grpc_service) (
  rate(grpc_server_handled_total{namespace="online-boutique", grpc_code!="OK"}[5m])
)

# Request rate to each service
sum by (app) (rate(grpc_server_started_total{namespace="online-boutique"}[5m]))

# Memory usage by service
topk(10, container_memory_working_set_bytes{namespace="online-boutique", container!=""})

# CPU throttling by service
topk(10,
  rate(container_cpu_cfs_throttled_periods_total{namespace="online-boutique"}[5m])
  / rate(container_cpu_cfs_periods_total{namespace="online-boutique"}[5m])
)

# Pod restart count (instability indicator)
sum by (pod) (kube_pod_container_status_restarts_total{namespace="online-boutique"})

# Service availability (ready endpoints per service)
kube_endpoint_address_available{namespace="online-boutique"}
```

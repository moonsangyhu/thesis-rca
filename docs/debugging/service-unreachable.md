# Service Unreachable Diagnosis

## Overview
A Kubernetes Service provides a stable endpoint for accessing pods. When a service is unreachable, the cause can be at multiple layers: selector mismatch (no endpoints), unhealthy endpoints (pods not ready), kube-proxy or Cilium eBPF rules not programmed, DNS resolution failure, or NetworkPolicy blocking traffic. This guide covers systematic debugging of all these layers for the Online Boutique microservices on Cilium 1.15.6.

## Symptoms
- Application returns connection refused, connection timeout, or HTTP 503
- `curl` to service ClusterIP returns no response or connection refused
- DNS resolves but connection fails
- Some pods can reach the service but others cannot
- Intermittent failures suggesting endpoint health issues
- Cilium Hubble shows dropped packets

## Diagnostic Commands

```bash
# Step 1: Verify service exists and get basic info
kubectl get svc -n <namespace>
kubectl get svc <service-name> -n <namespace> -o wide
# Check: CLUSTER-IP, PORT(S), SELECTOR

# Step 2: Check if service has endpoints
kubectl get endpoints <service-name> -n <namespace>
kubectl describe endpoints <service-name> -n <namespace>
# If ENDPOINTS shows <none>, no pods match the selector

# Step 3: Check service selector
kubectl get svc <service-name> -n <namespace> -o jsonpath='{.spec.selector}'

# Step 4: Check pod labels match selector
SELECTOR=$(kubectl get svc <service-name> -n <namespace> -o jsonpath='{.spec.selector}' | python3 -c "import sys,json; d=json.load(sys.stdin); print(','.join(f'{k}={v}' for k,v in d.items()))")
kubectl get pods -n <namespace> -l $SELECTOR
# If no pods returned, selector doesn't match any pods

# Step 5: Check pod labels vs service selector
kubectl get pods -n <namespace> --show-labels | grep <pod-pattern>
kubectl describe pod <pod-name> -n <namespace> | grep -A5 "Labels:"

# Step 6: Check if pods are Ready (not just Running)
kubectl get pods -n <namespace> -l <selector>
# Pods must be Ready (all readiness probes passing) to appear in endpoints

# Step 7: Test connectivity from within the cluster
# Create a test pod
kubectl run nettest -n <namespace> --image=nicolaka/netshoot --rm -it --restart=Never -- \
  curl -v http://<service-name>.<namespace>.svc.cluster.local:<port>/

# Or use existing pod
kubectl exec -it <pod-name> -n <namespace> -- \
  curl -v http://<service-name>:<port>/

# Step 8: Test by IP directly (bypass DNS)
SVC_IP=$(kubectl get svc <service-name> -n <namespace> -o jsonpath='{.spec.clusterIP}')
SVC_PORT=$(kubectl get svc <service-name> -n <namespace> -o jsonpath='{.spec.ports[0].port}')
kubectl run nettest -n <namespace> --image=nicolaka/netshoot --rm -it --restart=Never -- \
  curl -v http://${SVC_IP}:${SVC_PORT}/

# Step 9: Test DNS resolution separately
kubectl run dns-test -n <namespace> --image=nicolaka/netshoot --rm -it --restart=Never -- \
  nslookup <service-name>.<namespace>.svc.cluster.local

# Step 10: Check if kube-proxy rules are programmed (if using kube-proxy)
kubectl get configmap -n kube-system kube-proxy -o yaml | grep mode
# SSH to node:
# iptables -t nat -L KUBE-SERVICES | grep <service-cluster-ip>

# Step 11: Check Cilium service rules (Cilium replaces kube-proxy in this cluster)
# SSH to node or use cilium pod:
CILIUM_POD=$(kubectl get pod -n kube-system -l k8s-app=cilium -o jsonpath='{.items[0].metadata.name}')
kubectl exec -n kube-system $CILIUM_POD -- cilium service list
kubectl exec -n kube-system $CILIUM_POD -- cilium service list | grep <service-cluster-ip>

# Step 12: Use Hubble to observe traffic (Cilium 1.15.6)
kubectl exec -n kube-system $CILIUM_POD -- hubble observe \
  --namespace <namespace> \
  --to-pod <destination-pod> \
  --last 50

# Or with hubble CLI (if installed):
hubble observe --namespace <namespace> --type drop --last 100

# Step 13: Check NetworkPolicy blocking traffic
kubectl get networkpolicy -n <namespace>
kubectl describe networkpolicy -n <namespace>

# Step 14: Check if service port matches container port
kubectl get svc <service-name> -n <namespace> -o jsonpath='{.spec.ports}'
kubectl describe pod <pod-name> -n <namespace> | grep -A5 "Ports:"

# Step 15: For Online Boutique - check all services
kubectl get svc -n online-boutique
kubectl get endpoints -n online-boutique
kubectl get pods -n online-boutique -o wide

# Step 16: Check if service is NodePort/LoadBalancer - verify external access
kubectl get svc <service-name> -n <namespace> -o jsonpath='{.spec.type}'
# For NodePort: test with node IP and nodePort
NODE_PORT=$(kubectl get svc <service-name> -n <namespace> -o jsonpath='{.spec.ports[0].nodePort}')
echo "Test: curl http://<node-ip>:$NODE_PORT/"

# Step 17: EndpointSlices (v1.21+)
kubectl get endpointslice -n <namespace> | grep <service-name>
kubectl describe endpointslice -n <namespace> | grep -A10 <service-name>

# Step 18: Check for service topology and traffic policies
kubectl get svc <service-name> -n <namespace> -o jsonpath='{.spec.internalTrafficPolicy}'
kubectl get svc <service-name> -n <namespace> -o jsonpath='{.spec.externalTrafficPolicy}'
```

## Common Causes

1. **Selector mismatch**: The service selector labels do not match any pod labels. Pods may have been created with different labels, or labels were changed after the service was created.

2. **Pods not Ready**: Pods match the selector but are not Ready (readiness probe failing). Kubernetes removes not-Ready pods from Endpoints.

3. **Wrong port mapping**: Service port or targetPort does not match the container's listening port.

4. **NetworkPolicy blocking**: A default-deny NetworkPolicy or specific policy blocks ingress to the pods or egress from the caller.

5. **DNS resolution failure**: Service DNS name resolves to wrong IP or doesn't resolve at all. See `dns-resolution-failure.md`.

6. **Cilium eBPF rules not synced**: Cilium agent crashed or is unhealthy, so service load balancing rules are not properly programmed.

7. **Pod scheduled on wrong network segment**: In multi-network setups, pod cannot reach service IP because of routing issues.

8. **Service account or RBAC issue**: Rarely, application-level auth between microservices fails (not Kubernetes networking, but causes "service unreachable" from application perspective).

9. **Service ClusterIP exhaustion**: No more ClusterIPs available in the service CIDR range.

10. **Headless service misuse**: Service has `clusterIP: None` (headless) but caller expects a VIP. DNS returns individual pod IPs.

## Resolution Steps

### Step 1: Fix selector mismatch
```bash
# Get current pod labels
kubectl get pod <pod-name> -n <namespace> --show-labels

# Fix service selector to match pod labels
kubectl patch svc <service-name> -n <namespace> \
  -p '{"spec": {"selector": {"app": "correct-label-value"}}}'

# Or fix the pod labels (if deployment label is wrong)
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "add", "path": "/spec/template/metadata/labels/app", "value": "correct-label-value"}]'
```

### Step 2: Fix failing readiness probe
```bash
# Check what readiness probe is configured
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].readinessProbe}'

# Manually test the readiness check
kubectl exec -it <pod-name> -n <namespace> -- wget -q -O- http://localhost:<port>/health

# Fix probe configuration in deployment
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/readinessProbe/timeoutSeconds", "value": 5}]'
```

### Step 3: Fix port mapping
```bash
# Check current service ports
kubectl get svc <service-name> -n <namespace> -o yaml | grep -A5 "ports:"

# Check what port the container is actually listening on
kubectl exec -it <pod-name> -n <namespace> -- ss -tlnp
kubectl exec -it <pod-name> -n <namespace> -- netstat -tlnp 2>/dev/null || \
  kubectl exec -it <pod-name> -n <namespace> -- cat /proc/net/tcp

# Fix service target port
kubectl patch svc <service-name> -n <namespace> --type='json' \
  -p='[{"op": "replace", "path": "/spec/ports/0/targetPort", "value": 8080}]'
```

### Step 4: Fix NetworkPolicy blocking
```bash
# Check what policies exist
kubectl get networkpolicy -n <namespace>

# Describe all policies to understand rules
kubectl describe networkpolicy -n <namespace>

# Temporarily allow all traffic to diagnose (do not leave in production)
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

# Test if traffic works now
kubectl exec -it <pod-name> -n <namespace> -- curl http://<service-name>:<port>/

# If it works, the issue was NetworkPolicy - now create correct policies
# Clean up debug policy
kubectl delete networkpolicy allow-all-debug -n <namespace>
```

### Step 5: Restart Cilium to re-sync rules
```bash
# Check Cilium agent health
kubectl exec -n kube-system $CILIUM_POD -- cilium status

# Restart Cilium if unhealthy
kubectl rollout restart daemonset/cilium -n kube-system
kubectl rollout status daemonset/cilium -n kube-system

# Verify service is now in Cilium service list
kubectl exec -n kube-system $CILIUM_POD -- cilium service list | grep <cluster-ip>
```

### Step 6: Debug with ephemeral container (non-intrusive)
```bash
# Attach debug container to running pod without restart
kubectl debug -it <pod-name> -n <namespace> \
  --image=nicolaka/netshoot \
  --target=<container-name>

# Inside debug container:
curl -v http://<service-name>.<namespace>.svc.cluster.local:<port>/
nslookup <service-name>
ss -tlnp
```

## Service Debugging Checklist

```bash
SERVICE=<service-name>
NS=<namespace>

echo "=== Service Info ==="
kubectl get svc $SERVICE -n $NS -o wide

echo "=== Selector ==="
kubectl get svc $SERVICE -n $NS -o jsonpath='{.spec.selector}'

echo "=== Endpoints ==="
kubectl get endpoints $SERVICE -n $NS

echo "=== Matching Pods ==="
SELECTOR=$(kubectl get svc $SERVICE -n $NS -o json | python3 -c "import sys,json; d=json.load(sys.stdin); print(','.join(f'{k}={v}' for k,v in d['spec']['selector'].items()))")
kubectl get pods -n $NS -l $SELECTOR -o wide

echo "=== NetworkPolicies ==="
kubectl get networkpolicy -n $NS

echo "=== Cilium Service ==="
CILIUM_POD=$(kubectl get pod -n kube-system -l k8s-app=cilium -o jsonpath='{.items[0].metadata.name}')
SVC_IP=$(kubectl get svc $SERVICE -n $NS -o jsonpath='{.spec.clusterIP}')
kubectl exec -n kube-system $CILIUM_POD -- cilium service list | grep $SVC_IP
```

## Prevention
- Use label validators in CI/CD to catch selector mismatches before deployment
- Always test service connectivity in integration tests
- Set up Prometheus alerts for zero-endpoint services: `kube_endpoint_address_available == 0`
- Use Hubble UI for visual traffic flow monitoring
- Document service topology for Online Boutique microservices

## Related Issues
- `dns-resolution-failure.md` - DNS not resolving service names
- `network-connectivity.md` - Pod-to-pod connectivity issues
- `network-policy-debug.md` - NetworkPolicy troubleshooting
- `readiness-liveness-probe.md` - Pods not becoming Ready

# Network Connectivity Debugging

## Overview
Network connectivity issues in Kubernetes can occur at multiple layers: pod-to-pod within the same node, pod-to-pod across nodes, pod-to-service, service-to-external, and external-to-service. This cluster uses Cilium 1.15.6 in VXLAN mode as the CNI, which replaces both kube-proxy and provides eBPF-based load balancing, NetworkPolicy enforcement, and observability via Hubble. VXLAN mode encapsulates traffic in UDP port 8472 for cross-node communication.

## Symptoms
- Microservice A cannot connect to microservice B
- Intermittent connection timeouts between pods
- Services reachable from some pods but not others
- Cross-node pod communication fails but same-node works
- External traffic cannot reach NodePort or LoadBalancer services
- DNS queries timeout or return NXDOMAIN for existing services
- Hubble shows dropped packets with policy verdict DROPPED

## Diagnostic Commands

```bash
# Step 1: Basic pod connectivity test
# Deploy a debug pod
kubectl run nettest -n <namespace> --image=nicolaka/netshoot \
  --rm -it --restart=Never -- bash

# From inside nettest pod:
# ping <pod-ip>
# curl http://<pod-ip>:<port>/
# traceroute <pod-ip>
# nc -zv <pod-ip> <port>

# Step 2: Get pod IPs and node placement
kubectl get pods -n <namespace> -o wide
# Check which pods are on the same node vs different nodes

# Step 3: Test same-node pod communication
kubectl exec -it <pod-a> -n <namespace> -- \
  curl -v http://<pod-b-same-node-ip>:<port>/

# Step 4: Test cross-node pod communication
kubectl exec -it <pod-a> -n <namespace> -- \
  curl -v http://<pod-b-diff-node-ip>:<port>/

# Step 5: Check Cilium overall health
kubectl exec -n kube-system ds/cilium -- cilium status
kubectl exec -n kube-system ds/cilium -- cilium status --verbose

# Step 6: Check Cilium endpoint list
kubectl exec -n kube-system ds/cilium -- cilium endpoint list

# Step 7: Check Cilium connectivity test
kubectl apply -f https://raw.githubusercontent.com/cilium/cilium/v1.15.6/examples/kubernetes/connectivity-check/connectivity-check.yaml -n cilium-test
kubectl get pods -n cilium-test

# Built-in connectivity test:
kubectl exec -n kube-system ds/cilium -- cilium connectivity test 2>&1 | tail -30

# Step 8: Use Hubble to observe traffic
# Enable Hubble if not already (or use hubble-relay)
CILIUM_POD=$(kubectl get pod -n kube-system -l k8s-app=cilium -o jsonpath='{.items[0].metadata.name}')

# Observe all traffic in namespace
kubectl exec -n kube-system $CILIUM_POD -- \
  hubble observe --namespace <namespace> --last 100

# Observe drops only
kubectl exec -n kube-system $CILIUM_POD -- \
  hubble observe --namespace <namespace> --verdict DROPPED --last 50

# Observe traffic between specific pods
kubectl exec -n kube-system $CILIUM_POD -- \
  hubble observe --from-pod <namespace>/<pod-a> \
  --to-pod <namespace>/<pod-b> --last 50

# Step 9: Check VXLAN tunnel status (Cilium VXLAN mode)
kubectl exec -n kube-system $CILIUM_POD -- cilium tunnel list
# Should show tunnel entries for each remote node

# Step 10: Check if VXLAN UDP 8472 is open
# On the node:
# ss -unl | grep 8472
# iptables -L INPUT | grep 8472

# Step 11: Check Cilium BPF maps
kubectl exec -n kube-system $CILIUM_POD -- cilium bpf lb list
kubectl exec -n kube-system $CILIUM_POD -- cilium bpf policy list

# Step 12: Check pod IP routing
kubectl exec -n kube-system $CILIUM_POD -- cilium bpf ipcache list | grep <pod-ip>

# Step 13: Check if pod CIDRs are correctly allocated
kubectl get nodes -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.podCIDR}{"\n"}{end}'

# Step 14: Check Cilium CiliumNode objects
kubectl get ciliumnode
kubectl describe ciliumnode <node-name>

# Step 15: Network policy check via Cilium
kubectl exec -n kube-system $CILIUM_POD -- cilium policy get

# Step 16: Check MTU issues (common in VXLAN)
# VXLAN adds 50 bytes of overhead, so effective MTU is typically 1450 (from 1500)
kubectl exec -it <pod-name> -n <namespace> -- ip link show eth0 | grep mtu
# SSH to node: ip link show cilium_vxlan | grep mtu

# Step 17: Test DNS resolution
kubectl exec -it <pod-name> -n <namespace> -- \
  nslookup kubernetes.default.svc.cluster.local

# Step 18: Check iptables (should be minimal with Cilium kube-proxy replacement)
# SSH to node:
# iptables -t nat -L KUBE-SERVICES 2>/dev/null | head -10
# iptables -t nat -L CILIUM-FORWARD 2>/dev/null | head -10

# Step 19: For Online Boutique - map service dependencies
# frontend -> cartservice, productcatalogservice, currencyservice, checkoutservice, etc.
kubectl get svc -n online-boutique
kubectl get endpoints -n online-boutique

# Step 20: Check if Cilium has correct node IPs for tunneling
kubectl exec -n kube-system $CILIUM_POD -- cilium node list
```

## Common Causes

1. **Cilium agent unhealthy on one node**: If Cilium crashes or restarts on a node, all pods on that node lose network connectivity temporarily. Cross-node VXLAN tunnels break.

2. **NetworkPolicy blocking traffic**: A NetworkPolicy with default-deny blocks legitimate traffic. Very common when NetworkPolicies are deployed without careful planning.

3. **MTU mismatch**: VXLAN encapsulation requires reduced MTU (1450). If pods are configured with MTU 1500, large packets are silently dropped. Symptoms: small requests work, large ones fail.

4. **Cilium BPF maps full**: Under high load, Cilium BPF maps can reach capacity, causing new connections to be rejected. Rare but impactful.

5. **VXLAN port blocked**: Firewall or security group blocking UDP 8472 between nodes. Cross-node traffic fails completely.

6. **Pod CIDR overlap**: Two nodes assigned overlapping pod CIDRs. Traffic intended for one pod is routed to another node.

7. **Node-to-node routing broken**: Underlying infrastructure routing between nodes fails. All cross-node pod communication breaks.

8. **DNS coreDNS overloaded**: High DNS query rate causes CoreDNS to drop queries, causing apparent connectivity failures (DNS actually succeeds but times out).

9. **Incorrect endpoint slice**: Stale EndpointSlice pointing to pods that no longer exist.

10. **hostNetwork pod conflict**: Pod using hostNetwork conflicting with another pod's port.

## Resolution Steps

### Step 1: Restart Cilium on affected node
```bash
NODE=<node-name>
CILIUM_POD=$(kubectl get pod -n kube-system -o wide | grep cilium | grep $NODE | awk '{print $1}')

# Restart Cilium agent
kubectl delete pod $CILIUM_POD -n kube-system
# Wait for it to restart
kubectl rollout status ds/cilium -n kube-system

# Verify health after restart
NEW_CILIUM=$(kubectl get pod -n kube-system -o wide | grep cilium | grep $NODE | awk '{print $1}')
kubectl exec -n kube-system $NEW_CILIUM -- cilium status
```

### Step 2: Fix MTU mismatch
```bash
# Check current MTU configuration
kubectl get configmap -n kube-system cilium-config -o yaml | grep mtu

# Check node interface MTU
# SSH to node: ip link show | grep mtu

# Update Cilium MTU config (requires Cilium restart)
kubectl patch configmap -n kube-system cilium-config \
  -p '{"data": {"mtu": "1450"}}'

# Restart Cilium to apply
kubectl rollout restart ds/cilium -n kube-system
```

### Step 3: Debug NetworkPolicy drops via Hubble
```bash
# See network-policy-debug.md for detailed NetworkPolicy debugging

# Quick check - observe drops
kubectl exec -n kube-system $CILIUM_POD -- \
  hubble observe --verdict DROPPED --last 50 -o json | \
  python3 -c "
import sys, json
for line in sys.stdin:
    try:
        e = json.loads(line)
        flow = e.get('flow', {})
        src = flow.get('source', {})
        dst = flow.get('destination', {})
        print(f'DROP: {src.get(\"pod_name\",\"?\")} -> {dst.get(\"pod_name\",\"?\")} reason={flow.get(\"drop_reason_desc\",\"?\")}')
    except: pass
"
```

### Step 4: Test connectivity layer by layer
```bash
# Layer 1: Can we ping across nodes?
kubectl run ping-test -n default --image=nicolaka/netshoot --rm -it --restart=Never -- \
  ping -c 5 <pod-ip-on-another-node>

# Layer 2: Can we reach the service ClusterIP?
SVC_IP=$(kubectl get svc <service> -n <namespace> -o jsonpath='{.spec.clusterIP}')
kubectl run curl-test -n <namespace> --image=curlimages/curl --rm -it --restart=Never -- \
  curl -v http://$SVC_IP:<port>/

# Layer 3: Can we reach by DNS?
kubectl run dns-test -n <namespace> --image=nicolaka/netshoot --rm -it --restart=Never -- \
  curl -v http://<service>.<namespace>.svc.cluster.local:<port>/
```

### Step 5: Fix VXLAN firewall rules
```bash
# Check if UDP 8472 is blocked between nodes
# On node (using nmap or nc):
# nc -zu <remote-node-ip> 8472

# If blocked, add iptables rule
# iptables -I INPUT -p udp --dport 8472 -j ACCEPT
# iptables -I OUTPUT -p udp --sport 8472 -j ACCEPT

# For persistent firewall rules, update /etc/iptables/rules.v4 or firewalld config
```

### Step 6: Reset Cilium BPF maps (destructive - use carefully)
```bash
# WARNING: This will briefly disrupt all pod networking on the node
# SSH to node:
# sudo systemctl stop kubelet
# sudo ip link delete cilium_vxlan 2>/dev/null
# sudo ip link delete cilium_net 2>/dev/null  
# sudo systemctl start kubelet
# sudo systemctl restart containerd

# Better approach: let Cilium self-heal by restarting the agent
kubectl delete pod $CILIUM_POD -n kube-system
```

## Cilium Troubleshooting Reference

```bash
# Check Cilium version
kubectl exec -n kube-system $CILIUM_POD -- cilium version

# Check all Cilium endpoints
kubectl exec -n kube-system $CILIUM_POD -- cilium endpoint list

# Check policy verdicts for a specific endpoint
EP_ID=$(kubectl exec -n kube-system $CILIUM_POD -- cilium endpoint list | grep <pod-ip> | awk '{print $1}')
kubectl exec -n kube-system $CILIUM_POD -- cilium endpoint get $EP_ID

# Monitor live traffic
kubectl exec -n kube-system $CILIUM_POD -- cilium monitor --type drop

# Check Cilium CiliumNetworkPolicy objects
kubectl get ciliumnetworkpolicy -n <namespace>
kubectl describe ciliumnetworkpolicy -n <namespace>
```

## Prevention
- Deploy Hubble (Cilium observability) and enable Hubble UI
- Set up Prometheus alerts for Cilium agent health
- Test cross-node connectivity after every cluster change
- Document service dependency map for Online Boutique
- Set MTU explicitly in Cilium Helm values
- Use cilium connectivity test in CI/CD smoke tests
- Monitor `cilium_drop_count_total` metric for unexpected drops

## Related Issues
- `network-policy-debug.md` - NetworkPolicy specific debugging
- `service-unreachable.md` - Service layer connectivity
- `dns-resolution-failure.md` - DNS-layer connectivity failures
- `node-notready.md` - Node issues affecting network

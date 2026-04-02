# Runbook: Cilium Network Troubleshooting

## Trigger Conditions
- Pod-to-pod or pod-to-service connectivity failures
- NetworkPolicy enforcement issues
- Cross-node communication failures
- Suspected CNI (Cilium 1.15.6 with VXLAN) issues

## Severity
High (network issues affect all cluster communication)

## Estimated Resolution Time
15-45 minutes

## Prerequisites
- Cilium CLI (`cilium` binary) or access via kubectl exec
- Hubble CLI (optional, for flow analysis)
- SSH tunnel active for kubectl access

## Investigation Steps

### Step 1: Check Cilium agent health
```bash
# Cilium agent pods
kubectl get pods -n kube-system -l k8s-app=cilium -o wide

# Cilium status on each node
kubectl exec -n kube-system ds/cilium -- cilium status

# Brief status check
kubectl exec -n kube-system ds/cilium -- cilium status --brief

# Check for endpoint issues
kubectl exec -n kube-system ds/cilium -- cilium endpoint list | grep -v "ready"
```

### Step 2: Connectivity test
```bash
# Run Cilium connectivity test (comprehensive)
cilium connectivity test

# Quick manual connectivity test
# From pod A to pod B (same node)
kubectl exec -n boutique <pod-a> -- wget -qO- --timeout=5 http://<pod-b-ip>:port

# From pod A to pod B (cross-node)
kubectl exec -n boutique <pod-a> -- wget -qO- --timeout=5 http://<pod-b-ip>:port

# To service ClusterIP
kubectl exec -n boutique <pod-a> -- wget -qO- --timeout=5 http://<service>:port

# To external
kubectl exec -n boutique <pod-a> -- wget -qO- --timeout=5 http://1.1.1.1
```

### Step 3: Hubble flow analysis (if Hubble is enabled)
```bash
# Observe all flows for a pod
kubectl exec -n kube-system ds/cilium -- hubble observe --pod boutique/frontend

# Filter dropped flows
kubectl exec -n kube-system ds/cilium -- hubble observe --verdict DROPPED

# Filter by source and destination
kubectl exec -n kube-system ds/cilium -- hubble observe \
  --from-pod boutique/frontend --to-pod boutique/checkout

# Filter by protocol/port
kubectl exec -n kube-system ds/cilium -- hubble observe --protocol TCP --port 8080
```

### Step 4: BPF policy and maps
```bash
# Check BPF policy for an endpoint
ENDPOINT_ID=$(kubectl exec -n kube-system ds/cilium -- cilium endpoint list | grep frontend | awk '{print $1}')
kubectl exec -n kube-system ds/cilium -- cilium bpf policy get $ENDPOINT_ID

# List BPF maps
kubectl exec -n kube-system ds/cilium -- cilium bpf ct list global | head -20

# Check service map
kubectl exec -n kube-system ds/cilium -- cilium service list
```

### Step 5: MTU / VXLAN specific (this cluster)
```bash
# This cluster: physical ens18 MTU=1500, OpenStack OVS br-int MTU=1400
# Cilium VXLAN adds 50 bytes overhead → effective MTU should be 1350-1450

# Check Cilium configured MTU
kubectl get configmap cilium-config -n kube-system -o jsonpath='{.data.mtu}'
# Should be: 1450 (or lower for OpenStack environments)

# Verify pod interface MTU
kubectl exec -n boutique <pod> -- ip link show eth0 | grep mtu

# Test with large packets (detect MTU issues)
kubectl exec -n boutique <pod> -- ping -s 1400 -c 3 -M do <target-pod-ip>
# If this fails with "message too long", MTU is too high

# Correct MTU fix
kubectl -n kube-system patch configmap cilium-config --patch '{"data":{"mtu":"1450"}}'
kubectl rollout restart ds/cilium -n kube-system
# Then restart all affected pods
```

### Step 6: Check Cilium identity and policy
```bash
# List identities
kubectl exec -n kube-system ds/cilium -- cilium identity list

# Check if policy is being enforced
kubectl exec -n kube-system ds/cilium -- cilium policy get

# Check CiliumNetworkPolicy resources
kubectl get cnp,ccnp -A
```

## Resolution

### Connection reset by peer (MTU issue)
1. Set correct MTU in cilium-config: `mtu: "1450"`
2. Restart Cilium DaemonSet
3. Restart affected workloads
4. Verify with large packet ping test

### NetworkPolicy blocking traffic
1. Identify which policy is blocking: check Hubble DROPPED flows
2. Add allow rules for required traffic
3. Don't forget DNS (port 53) and monitoring (port 9090) egress

### Cross-node failure
1. Check VXLAN tunnels: `cilium bpf tunnel list`
2. Verify node-to-node connectivity on VXLAN port (8472/UDP)
3. Check firewall rules on underlying infrastructure

### Endpoint not ready
1. Check `cilium endpoint list` for not-ready endpoints
2. Restart the affected pod
3. If persistent, restart Cilium agent on that node

## Verification
```bash
# Verify connectivity restored
kubectl exec -n boutique <pod> -- wget -qO- --timeout=5 http://<target>:port

# Check no dropped flows
kubectl exec -n kube-system ds/cilium -- hubble observe --verdict DROPPED --last 10

# Cilium status healthy
kubectl exec -n kube-system ds/cilium -- cilium status --brief
```

## Loki Queries
```logql
# Cilium agent errors
{namespace="kube-system", app="cilium-agent"} |~ "(?i)(error|warn|fail|timeout)"

# VXLAN related
{namespace="kube-system", app="cilium-agent"} |~ "(?i)(vxlan|tunnel|mtu|encap)"
```

## Prometheus Queries
```promql
# Cilium agent readiness
cilium_agent_api_process_time_seconds

# Dropped packets
rate(cilium_drop_count_total[5m])

# Policy enforcement
rate(cilium_policy_import_errors_total[5m])
```

## Escalation
If Cilium agents are crash-looping or BPF programs fail to load:
1. Check kernel compatibility (requires >= 4.19, ideally 5.4+)
2. Check dmesg for BPF verifier errors
3. Consider Cilium version upgrade

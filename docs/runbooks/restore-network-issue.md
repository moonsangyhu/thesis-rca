# Runbook: Network Recovery (Cilium/CNI)

## Trigger Conditions
Use this runbook when pods cannot communicate despite correct NetworkPolicies, when Cilium agent is in a bad state, when VXLAN/Geneve tunnels are broken, or after a node failure caused CNI state corruption.

## Severity
**Critical** — CNI failure causes complete network outage for affected pods/nodes.

## Estimated Resolution Time
20-45 minutes

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- Cilium CLI: `cilium` (install: `curl -L --remote-name-all https://github.com/cilium/cilium-cli/releases/latest/download/cilium-linux-amd64.tar.gz`)
- Hubble CLI: `hubble`
- SSH access to nodes

## Recovery Procedure

### Phase 1: Diagnose Cilium Health

```bash
# Check overall Cilium status
kubectl exec -n kube-system ds/cilium -- cilium status --verbose

# Check Cilium agent pod health
kubectl get pods -n kube-system -l k8s-app=cilium -o wide
kubectl describe pod -n kube-system <cilium-pod-name>

# Check Cilium error logs
kubectl logs -n kube-system <cilium-pod-name> --previous | grep -E 'error|Error|ERR' | tail -30
kubectl logs -n kube-system <cilium-pod-name> | grep -E 'error|Error|ERR' | tail -30

# Check all Cilium components
kubectl get pods -n kube-system | grep -E 'cilium|hubble'
```

### Phase 2: Test Connectivity

```bash
# Use Cilium connectivity test (comprehensive)
cilium connectivity test --namespace online-boutique

# Or manual connectivity test between specific pods
kubectl exec -n online-boutique deploy/frontend -- \
  curl --max-time 5 http://productcatalogservice:3550/ \
  -o /dev/null -w "Status: %{http_code}, Time: %{time_total}s\n"

# Test cross-node connectivity (pick pods on different nodes)
POD1_NODE=$(kubectl get pod -n online-boutique -l app=frontend -o jsonpath='{.items[0].spec.nodeName}')
POD2_NODE=$(kubectl get pod -n online-boutique -l app=cartservice -o jsonpath='{.items[0].spec.nodeName}')
echo "frontend is on: $POD1_NODE"
echo "cartservice is on: $POD2_NODE"
# If same node, cross-node traffic isn't being tested
```

### Phase 3: Check Hubble Flows for Drop Reason

```bash
# Port-forward Hubble relay
kubectl port-forward -n kube-system svc/hubble-relay 4245:80 &

# Use hubble observe
hubble observe --namespace online-boutique --verdict DROPPED -f

# Or directly via exec
kubectl exec -n kube-system ds/cilium -- \
  hubble observe --verdict DROPPED --last 50 \
  --output json | jq '{
    src: .source.namespace + "/" + .source.pod_name,
    dst: .destination.namespace + "/" + .destination.pod_name,
    reason: .drop_reason_desc,
    verdict: .verdict
  }'
```

**Common drop reasons:**
- `POLICY_DENIED` → NetworkPolicy issue (see rca-f6-networkpolicy.md)
- `CT_UNKNOWN` → Connection tracking table full or corrupted
- `INVALID` → Packet validation failure (MTU issue)
- `DROP_UNKNOWN_CONNECTION` → BPF map state inconsistency

### Phase 4A: Restart Cilium on Affected Node

```bash
# Targeted restart — delete Cilium pod on the affected node
# DaemonSet will recreate it
kubectl get pods -n kube-system -l k8s-app=cilium -o wide
kubectl delete pod -n kube-system <cilium-pod-on-affected-node>

# Watch the new pod come up
kubectl get pods -n kube-system -l k8s-app=cilium -w

# Wait for Cilium to be ready (can take 30-60 seconds)
kubectl rollout status daemonset/cilium -n kube-system
```

### Phase 4B: Full Cilium Restart (Cluster-wide)

```bash
# Use only if targeted restart doesn't fix the issue
kubectl rollout restart daemonset/cilium -n kube-system
kubectl rollout status daemonset/cilium -n kube-system

# Also restart Hubble relay
kubectl rollout restart deployment/hubble-relay -n kube-system
```

### Phase 4C: Flush Stale BPF Maps (Advanced)

```bash
# SSH to the affected node
ssh -J debian@211.62.97.71:22015 ktcloud@<node-ip>

# Check BPF map health
sudo cilium bpf lb list 2>/dev/null | head -20
sudo cilium bpf policy get 2>/dev/null | head -20

# If maps are corrupted, Cilium restart usually fixes this
# In extreme cases, flush CT (connection tracking) table:
sudo cilium bpf ct flush global

# Remove stale endpoints
sudo cilium endpoint list
sudo cilium endpoint delete <stale-endpoint-id>
```

### Phase 4D: MTU Issue Fix

```bash
# Check MTU configuration
kubectl exec -n kube-system ds/cilium -- cilium config get tunnel
kubectl exec -n kube-system ds/cilium -- cilium config get mtu

# Check actual MTU on node network interfaces
ssh -J debian@211.62.97.71:22015 ktcloud@<node-ip> \
  "ip link show | grep -E 'mtu|eth|ens'"

# For VXLAN tunnels, MTU should be node MTU - 50 bytes
# e.g., if node MTU is 1500, Cilium VXLAN MTU should be 1450

# If MTU is wrong, update Cilium ConfigMap
kubectl edit configmap cilium-config -n kube-system
# Set: mtu: "1450"  (or appropriate value)

# Restart Cilium after MTU change
kubectl rollout restart daemonset/cilium -n kube-system
```

### Phase 5: Validate Policy Flush and Reapplication

```bash
# List all NetworkPolicies
kubectl get networkpolicy -A

# Delete and recreate NetworkPolicies if they seem stuck
kubectl get networkpolicy -n online-boutique -o yaml > /tmp/netpol-backup.yaml
kubectl delete networkpolicy -n online-boutique --all

# Test connectivity without any policies
kubectl exec -n online-boutique deploy/frontend -- \
  curl -s --max-time 5 http://cartservice:7070/ -o /dev/null -w "%{http_code}"

# If connectivity works now → policy issue (see rca-f6)
# If still failing → CNI infrastructure issue

# Reapply policies
kubectl apply -f /tmp/netpol-backup.yaml
```

### Phase 6: Restart Application Pods to Re-establish Connections

```bash
# After Cilium is healthy, restart pods to re-register endpoints
kubectl rollout restart deployment -n online-boutique

# Wait for all to be ready
kubectl rollout status deployment -n online-boutique --timeout=300s
```

## Verification

```bash
# Cilium health check
kubectl exec -n kube-system ds/cilium -- cilium status | grep "Cilium:"

# No dropped flows
kubectl exec -n kube-system ds/cilium -- \
  hubble observe --verdict DROPPED --last 10

# Connectivity test
kubectl exec -n online-boutique deploy/frontend -- \
  curl -s http://cartservice:7070/ -o /dev/null -w "%{http_code}"

# End-to-end application test
kubectl run smoke-test --image=curlimages/curl -n online-boutique --rm -it -- \
  curl -s -o /dev/null -w "Frontend HTTP: %{http_code}\n" http://frontend/

# Hubble shows only FORWARDED verdicts for service traffic
kubectl exec -n kube-system ds/cilium -- \
  hubble observe --namespace online-boutique --last 30 | grep -c FORWARDED
```

## Escalation
- If Cilium v1.15.6 has a known bug causing this: check Cilium release notes and apply hotfix
- If BPF maps are permanently corrupt and Cilium restart doesn't help: node reboot required
- If cross-node connectivity is completely broken after node rejoin: check Cilium node list and BGP/VXLAN config

## Loki Queries

```logql
# Cilium errors
{namespace="kube-system", app="cilium"} |= "error" or |= "Error" or |= "failed"

# BPF related errors
{namespace="kube-system", app="cilium"} |= "BPF" |= "error"

# Connection tracking errors
{namespace="kube-system", app="cilium"} |= "CT" or |= "conntrack"

# MTU-related drops
{namespace="kube-system", app="cilium"} |= "MTU" or |= "fragmentation"

# Application-level network errors (result of CNI issue)
{namespace="online-boutique"} |= "connection refused" or |= "i/o timeout" or |= "network unreachable"
```

## Prometheus Queries

```promql
# Cilium BPF policy drops
rate(cilium_drop_count_total[5m])

# Cilium BPF drops by reason
sum by (reason) (rate(cilium_drop_count_total[5m]))

# Cilium endpoint state (should all be "ready")
cilium_endpoint_state{state!="ready"}

# Cilium policy enforcement
cilium_policy_count

# Network errors at node level
rate(node_netstat_Tcp_InErrs[5m])
rate(node_netstat_Tcp_RetransSegs[5m])

# Cilium agent memory/CPU usage
container_memory_working_set_bytes{namespace="kube-system", container="cilium-agent"}
rate(container_cpu_usage_seconds_total{namespace="kube-system", container="cilium-agent"}[5m])
```

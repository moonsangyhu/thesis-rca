# Runbook: F12 - NetworkLoss Root Cause Analysis

## Trigger Conditions
Use this runbook when services experience intermittent connection failures, TCP reset errors, broken pipe, or EOF errors, with elevated TCP retransmission rates. Applies when `tc netem` packet loss rules are injected on a node network interface.

## Severity
**High** — Packet loss causes intermittent failures that are difficult to reproduce, leading to unpredictable gRPC/HTTP errors, increased retry storms, and cascading instability.

## Estimated Resolution Time
10-20 minutes

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- SSH access to worker nodes
- `tc` (iproute2) command available on target nodes

## Symptoms

- Intermittent `connection reset by peer`, `broken pipe`, or `EOF` errors in logs
- TCP retransmission rate elevated (`node_netstat_Tcp_RetransSegs` > 1/s per node)
- Node-level network transmit/receive errors (`node_network_transmit_errs_total`)
- gRPC errors: `Unavailable`, `ResourceExhausted`, or `Internal` codes
- Failures are **intermittent** — not every request fails (key differentiator from F6 and F11)
- All pods are Running and Ready
- No Cilium policy drops

## Differentiation

### F12 vs F6 (NetworkPolicy)
| Signal | F12 NetworkLoss | F6 NetworkPolicy |
|--------|----------------|-----------------|
| Failure pattern | **Intermittent** — some requests succeed | **Complete block** — all requests fail |
| Error type | `connection reset`, `broken pipe`, `EOF` | `connection refused`, policy DROPPED |
| Cilium drops | **None** | Present |
| TCP retransmissions | **Elevated** | Not elevated |
| `tc qdisc show` | `netem loss X%` visible | No netem rules |

### F12 vs F11 (NetworkDelay)
| Signal | F12 NetworkLoss | F11 NetworkDelay |
|--------|----------------|-----------------|
| Error type | `reset`, `broken pipe`, `EOF` (abrupt close) | `deadline exceeded`, `timeout` (slow response) |
| Request outcome | Random subset of requests fail completely | All requests slow, eventual timeout |
| p95 latency | May be elevated due to retransmit | Uniformly elevated |
| TCP retransmissions | **Primary indicator** — high rate | Moderate |
| `tc qdisc` | `netem loss X%` | `netem delay Xms` |

### F12 vs F2 (CrashLoopBackOff)
| Signal | F12 NetworkLoss | F2 CrashLoopBackOff |
|--------|----------------|---------------------|
| Pod status | All Running/Ready | CrashLoopBackOff, restarts > 0 |
| Error scope | Network-level across node | Application-level, specific pod |
| `tc qdisc` | netem loss visible | Clean |

## Investigation Steps

### Step 1: Check TCP retransmissions
```promql
# Primary indicator for F12
rate(node_netstat_Tcp_RetransSegs[2m]) > 1.0
```

### Step 2: Check node-level network errors
```promql
# Transmit errors on physical interfaces
rate(node_network_transmit_errs_total{device!~"lo|veth.*|cali.*|cilium.*"}[2m]) > 0

# Receive errors
rate(node_network_receive_errs_total{device!~"lo|veth.*|cali.*|cilium.*"}[2m]) > 0
```

### Step 3: Confirm no Cilium drops (rule out F6)
```promql
# Should return empty for F12
rate(cilium_drop_count_total[2m]) > 0
```

```bash
# Confirm nodes are all Ready (rule out F4)
kubectl get nodes
```

### Step 4: Check application logs for intermittent failures
```logql
# TCP reset and broken pipe errors
{namespace="boutique"} |= "connection reset by peer"
{namespace="boutique"} |= "broken pipe"
{namespace="boutique"} |= "EOF"

# gRPC errors (Unavailable indicates intermittent connectivity)
{namespace="boutique"} |= "Unavailable"
{namespace="boutique"} |= "rpc error"
```

### Step 5: Identify the node with netem loss rules
```bash
# SSH into each worker node and check tc rules
ssh worker01 "sudo tc qdisc show dev ens18"
ssh worker02 "sudo tc qdisc show dev ens18"
ssh worker03 "sudo tc qdisc show dev ens18"

# A node with F12 shows something like:
# qdisc netem 8001: root refcnt 2 limit 1000 loss 20%
# or:
# qdisc netem 8001: root refcnt 2 limit 1000 loss 10% 25%
```

### Step 6: Correlate affected pods to the node
```bash
# Find which pods run on the affected node
kubectl get pods -n boutique -o wide | grep <affected-node>

# Check pod-level network metrics
kubectl exec -n boutique <pod> -- ss -s
```

## Resolution

### Remove tc netem loss rule
```bash
# On the affected node (replace ens18 with actual interface)
sudo tc qdisc del dev ens18 root

# Verify the rule is removed
sudo tc qdisc show dev ens18
# Should show: qdisc noqueue 0: root refcnt 2
```

### Verify recovery
```bash
# TCP retransmission rate should drop to near-zero within 1-2 minutes

# Application-level intermittent failure check (run multiple times)
for i in {1..10}; do
  kubectl exec -n boutique deploy/frontend -- \
    curl -s --max-time 5 http://productcatalogservice:3550/ -o /dev/null -w "%{http_code}\n"
done
# All should return 200
```

## Recovery Script (automated)
```python
# scripts/stabilize/recovery.py — _recover_f12_network_loss()
ssh_node(node_name, f"sudo tc qdisc del dev {iface} root 2>/dev/null; echo ok")
```

## Prometheus Queries

```promql
# TCP retransmission rate (primary indicator)
rate(node_netstat_Tcp_RetransSegs[2m])

# Node network transmit errors on physical interfaces
rate(node_network_transmit_errs_total{device!~"lo|veth.*|cali.*|cilium.*"}[2m])

# Node network receive errors
rate(node_network_receive_errs_total{device!~"lo|veth.*|cali.*|cilium.*"}[2m])

# gRPC error rate by code (Unavailable = intermittent network failure)
sum(rate(grpc_server_handled_total{grpc_code!="OK"}[2m]))
by (grpc_service, grpc_code)
```

## Loki Queries

```logql
# TCP reset and connection loss errors
{namespace="boutique"} |= "connection reset by peer"

# Broken pipe (write to closed connection)
{namespace="boutique"} |= "broken pipe"

# Unexpected EOF (read from closed connection)
{namespace="boutique"} |= "EOF"

# gRPC Unavailable (typically means intermittent network, not permanent block)
{namespace="boutique"} |= "code = Unavailable"

# All network-related errors
{namespace="boutique"} |~ "reset|broken pipe|EOF|retransmit"
```

## Escalation
- If `tc qdisc del` fails: check if loss rule is applied on a different interface (use `tc qdisc show` on all interfaces)
- If retransmissions persist after netem removal: check physical NIC statistics (`ethtool -S <device> | grep -i error`)
- If multiple nodes show packet loss simultaneously: check upstream switch port error counters
- If packet loss is reproducible on all interfaces: check for kernel network stack issues (`/proc/net/snmp`)

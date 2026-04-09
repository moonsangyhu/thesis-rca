# Runbook: F11 - NetworkDelay Root Cause Analysis

## Trigger Conditions
Use this runbook when services are experiencing high response times, gRPC DeadlineExceeded errors, or connection timeouts, but pods are Running and healthy. Applies when `tc netem` delay rules are injected on a node network interface.

## Severity
**High** — Artificial network delay causes cascading timeouts across all services on the affected node, degrading end-to-end request latency significantly.

## Estimated Resolution Time
10-20 minutes

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- SSH access to worker nodes
- `tc` (iproute2) command available on target nodes

## Symptoms

- gRPC `DeadlineExceeded` errors in application logs
- p95 request latency > 500ms (observable via `request_latency` metric)
- Connection timeout errors: `context deadline exceeded`, `i/o timeout`
- All pods are Running and Ready (delay is network-level, not application-level)
- No Cilium policy drops (key differentiator from F6)
- Node remains Ready with no DiskPressure/MemoryPressure conditions

## Differentiation

### F11 vs F6 (NetworkPolicy)
| Signal | F11 NetworkDelay | F6 NetworkPolicy |
|--------|-----------------|-----------------|
| Cilium drops | **None** | Present (`cilium_drop_count_total > 0`) |
| Connectivity | Slow but succeeds (until timeout) | Complete block, immediate failure |
| Error type | `context deadline exceeded`, `timeout` | `connection refused`, `DROPPED` |
| Pod status | All Running | Often 0 endpoints or CrashLoop |
| `tc qdisc show` | `netem delay Xms` visible | No netem rules |

### F11 vs F4 (NodeNotReady)
| Signal | F11 NetworkDelay | F4 NodeNotReady |
|--------|-----------------|----------------|
| Node status | **Ready** | NotReady |
| Scope | All pods on node experience slow responses | Pods evicted/rescheduled |
| Kubelet | Healthy | Stopped or unreachable |
| Impact | Latency increase | Pod unavailability |

### F11 vs F7 (CPUThrottle)
| Signal | F11 NetworkDelay | F7 CPUThrottle |
|--------|-----------------|---------------|
| CPU throttle ratio | Low/normal | High (`> 50%`) |
| Latency pattern | Uniform across all calls | Variable, worse under load |
| `tc qdisc` | netem delay visible | Clean |

## Investigation Steps

### Step 1: Confirm latency anomaly
```promql
# p95 gRPC latency — should be < 100ms in healthy state
histogram_quantile(0.95,
  sum(rate(grpc_server_handling_seconds_bucket[2m]))
  by (le, grpc_service, grpc_method)
)

# gRPC DeadlineExceeded error rate
sum(rate(grpc_server_handled_total{grpc_code="DeadlineExceeded"}[2m]))
by (grpc_service)
```

### Step 2: Confirm no Cilium drops
```promql
# Should return empty if F11 (not F6)
rate(cilium_drop_count_total[2m]) > 0
```

```bash
# Confirm nodes are all Ready
kubectl get nodes
```

### Step 3: Check TCP retransmissions
```promql
# Elevated TCP retransmissions indicate network-level issue
rate(node_netstat_Tcp_RetransSegs[2m]) > 1.0
```

### Step 4: Identify which node has netem rules
```bash
# SSH into each worker node and check tc rules
ssh worker01 "sudo tc qdisc show dev ens18"
ssh worker02 "sudo tc qdisc show dev ens18"
ssh worker03 "sudo tc qdisc show dev ens18"

# A healthy node shows:
# qdisc noqueue 0: root refcnt 2
# A node with F11 shows something like:
# qdisc netem 8001: root refcnt 2 limit 1000 delay 200ms
```

### Step 5: Correlate affected pods to the node
```bash
# Find which pods run on the affected node
kubectl get pods -n boutique -o wide | grep <affected-node>
```

### Step 6: Check application logs for timeout errors
```logql
{namespace="boutique"} |= "context deadline exceeded"
{namespace="boutique"} |= "DeadlineExceeded"
{namespace="boutique"} |= "timeout"
```

## Resolution

### Remove tc netem delay rule
```bash
# On the affected node (replace ens18 with actual interface)
sudo tc qdisc del dev ens18 root

# Verify the rule is removed
sudo tc qdisc show dev ens18
# Should show: qdisc noqueue 0: root refcnt 2
```

### Verify recovery
```bash
# Check latency returns to normal within 1-2 minutes
# gRPC p95 should drop below 100ms

# Application-level check
kubectl exec -n boutique deploy/frontend -- \
  curl -s --max-time 5 http://productcatalogservice:3550/ -o /dev/null -w "%{http_code}"
```

## Recovery Script (automated)
```python
# scripts/stabilize/recovery.py — _recover_f11_network_delay()
ssh_node(node_name, f"sudo tc qdisc del dev {iface} root 2>/dev/null; echo ok")
```

## Prometheus Queries

```promql
# p95 request latency per service
histogram_quantile(0.95,
  sum(rate(grpc_server_handling_seconds_bucket[2m]))
  by (le, grpc_service, grpc_method)
)

# DeadlineExceeded error rate
sum(rate(grpc_server_handled_total{grpc_code="DeadlineExceeded"}[2m]))
by (grpc_service)

# TCP retransmission rate per node
rate(node_netstat_Tcp_RetransSegs[2m])

# Node network transmit errors
rate(node_network_transmit_errs_total{device!~"lo|veth.*|cali.*|cilium.*"}[2m])
```

## Loki Queries

```logql
# Timeout and deadline errors
{namespace="boutique"} |= "deadline exceeded"

# Slow gRPC calls
{namespace="boutique"} |= "timeout" | json | latency > 500

# All error-level logs on boutique namespace
{namespace="boutique"} | logfmt | level="error"
```

## Escalation
- If `tc qdisc del` fails: check if the rule is on a veth or bond interface instead of ens18
- If latency persists after netem removal: check for physical NIC issues (`ethtool -S <device>`)
- If multiple nodes affected simultaneously: check for upstream switch/router QoS configuration

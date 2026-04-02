# Runbook: F4 - NodeNotReady Root Cause Analysis

## Trigger Conditions
Use this runbook when nodes show `NotReady` status in `kubectl get nodes`, when `KubeNodeNotReady` or `KubeNodeUnreachable` alerts fire, or when pods are stuck in `Pending` or `Terminating` state due to node issues.

## Severity
**Critical** — A NotReady node means all pods on that node are either evicted or unreachable. Service capacity is reduced and workloads may not reschedule if resources are tight.

## Estimated Resolution Time
30-90 minutes (recovery or workload migration)

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- SSH access to affected nodes (via jump host: `ssh -J debian@211.62.97.71:22015 ktcloud@<node-ip>`)
- Access to Proxmox/OpenStack hypervisor console (for hard node reset)
- Prometheus for node metrics correlation

## Investigation Steps

### Step 1: Identify the NotReady node(s)
```bash
# Overview of all node states
kubectl get nodes -o wide

# Get detailed condition info
kubectl get nodes -o json | jq '.items[] | select(.status.conditions[] | select(.type=="Ready" and .status!="True")) | 
  {name: .metadata.name, conditions: .status.conditions, addresses: .status.addresses}'

# Describe the problematic node
kubectl describe node <node-name>
```

Look for conditions like:
```
Conditions:
  Type                 Status  LastHeartbeatTime   Reason
  ----                 ------  -----------------   ------
  MemoryPressure       False   ...
  DiskPressure         False   ...
  PIDPressure          False   ...
  Ready                False   ...                 KubeletNotReady / NodeStatusUnknown
```

### Step 2: Check when the node last sent a heartbeat
```bash
# Node heartbeat is in .status.conditions[].lastHeartbeatTime
kubectl get node <node-name> -o jsonpath='{.status.conditions[?(@.type=="Ready")].lastHeartbeatTime}'

# If > 5 minutes ago, kubelet is likely down or network is partitioned
```

### Step 3: Check kubelet status on the node
```bash
# SSH to the node (adjust IPs from cluster config)
# worker01: 172.25.20.111, worker02: 172.25.20.112, worker03: 172.25.20.113
ssh -J debian@211.62.97.71:22015 ktcloud@172.25.20.111

# Check kubelet service
sudo systemctl status kubelet
sudo journalctl -u kubelet -n 100 --no-pager

# Check for common kubelet errors
sudo journalctl -u kubelet | grep -E 'error|Error|failed|Failed' | tail -30
```

### Step 4: Check Cilium CNI status on the node
```bash
# Check Cilium agent on the affected node
kubectl get pods -n kube-system -o wide | grep cilium | grep <node-name>

# Check Cilium agent logs
kubectl logs -n kube-system <cilium-pod-name> | tail -50

# Check Cilium status
kubectl exec -n kube-system <cilium-pod-name> -- cilium status

# Check if VXLAN/Geneve tunnels are up
kubectl exec -n kube-system <cilium-pod-name> -- cilium node list
```

### Step 5: Check node resource pressure
```bash
# From the node itself
free -h          # Memory
df -h /          # Disk (root)
df -h /var/lib/kubelet  # Kubelet data dir

# PID count
cat /proc/sys/kernel/pid_max
ps aux | wc -l

# Check containerd/docker
sudo systemctl status containerd
sudo crictl ps 2>&1 | head -20

# Check for stuck processes
sudo ps aux | grep -E 'D\s' | head -20  # Processes in uninterruptible sleep (disk I/O hang)
```

### Step 6: Check network connectivity from the node
```bash
# On the affected node
ping -c 3 172.25.20.101  # Ping master01
ping -c 3 172.25.20.200  # Ping VIP
curl -k https://172.25.20.200:6443/healthz  # API server health

# Check if node can reach other nodes
for ip in 172.25.20.101 172.25.20.102 172.25.20.103 172.25.20.111 172.25.20.112 172.25.20.113; do
  ping -c 1 -W 1 $ip && echo "$ip: OK" || echo "$ip: FAIL"
done
```

### Step 7: Check kube-ovn if applicable
```bash
# kube-ovn components (per CLAUDE.md, CNI is kube-ovn)
kubectl get pods -n kube-system | grep ovn
kubectl logs -n kube-system <ovn-controller-pod> | tail -30
```

## Resolution

### Option A: Restart kubelet (most common fix)
```bash
# On the affected node
sudo systemctl restart kubelet
sudo systemctl status kubelet

# Watch node recover from control plane
kubectl get nodes -w
# Should transition: NotReady → Ready within 1-2 minutes
```

### Option B: Restart Cilium agent
```bash
# Delete cilium pod to force restart (DaemonSet will recreate)
kubectl delete pod -n kube-system <cilium-pod-on-node>

# Or restart all cilium pods on the node
kubectl rollout restart daemonset/cilium -n kube-system
```

### Option C: Cordon and drain the node (if node is unrecoverable short-term)
```bash
# Cordon: prevent new pods from scheduling
kubectl cordon <node-name>

# Drain: evict all pods (except DaemonSets)
kubectl drain <node-name> \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --grace-period=60 \
  --timeout=300s

# Verify pods have migrated
kubectl get pods -A -o wide | grep <node-name>
kubectl get pods -A --field-selector=status.phase=Pending
```

### Option D: Hard reboot via Proxmox/OpenStack
```bash
# Use Proxmox console to restart the VM
# After reboot, verify node rejoins:
kubectl get nodes -w

# Once Ready, uncordon
kubectl uncordon <node-name>
```

### Option E: Node replacement (node is permanently failed)
```bash
# Remove the node from cluster
kubectl delete node <node-name>

# Provision a new node via kubeadm
# On new node:
sudo kubeadm join 172.25.20.200:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash>

# Generate new join token if needed (on master)
kubeadm token create --print-join-command
```

## Verification
```bash
# Node should be Ready
kubectl get nodes

# All pods on node should be Running
kubectl get pods -A -o wide | grep <node-name>

# No pending pods (from eviction backlog)
kubectl get pods -A | grep Pending

# Node resource conditions should be Normal
kubectl describe node <node-name> | grep -A 20 "Conditions:"

# Events should be clean
kubectl get events -A --sort-by='.lastTimestamp' | grep <node-name> | tail -10
```

## Escalation
- If node refuses to rejoin and `kubeadm join` fails with certificate errors: regenerate bootstrap token and CA hash
- If network partition is suspected (node unreachable from all masters): escalate to network/infrastructure team
- If multiple nodes go NotReady simultaneously: suspect etcd issues or VIP (172.25.20.200) problems — check HAProxy/keepalived

## Loki Queries

```logql
# Kubelet errors on the affected node
{job="kubelet", node="<node-name>"} |= "error" or |= "Error"

# Node condition change events
{job="kubernetes-events"} |= "NodeNotReady" or |= "NodeHasSufficientMemory"

# Cilium agent errors on node
{namespace="kube-system", pod=~"cilium.*", node="<node-name>"} |= "error"

# OOM killer invocations (kernel logs via node exporter/journal)
{job="node-syslog"} |= "Out of memory" or |= "oom_kill_process"
```

## Prometheus Queries

```promql
# Node Ready condition (0 = NotReady)
kube_node_status_condition{condition="Ready", status="true"}

# Node memory pressure
kube_node_status_condition{condition="MemoryPressure", status="true"}

# Node disk pressure
kube_node_status_condition{condition="DiskPressure", status="true"}

# Node CPU utilization
1 - avg by (node) (rate(node_cpu_seconds_total{mode="idle"}[5m]))

# Node memory available
node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes

# Node disk usage
1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})

# Pods not scheduled (waiting for a Ready node)
kube_pod_status_phase{phase="Pending"}

# Kubelet up status
up{job="kubelet"}
```

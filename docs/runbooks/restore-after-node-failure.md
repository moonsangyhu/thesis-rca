# Runbook: Node Failure Recovery

## Trigger Conditions
Use this runbook when a Kubernetes worker node goes `NotReady`, is completely unreachable, or requires replacement. Applies to both transient failures (kubelet crash, OOM) and permanent failures (disk failure, hardware fault).

## Severity
**Critical** — Node failure reduces cluster capacity by 33% (3-node cluster) and may leave pods unscheduled.

## Estimated Resolution Time
- Soft recovery (kubelet restart): 15-30 minutes
- Hard recovery (node reboot): 30-60 minutes
- Node replacement: 60-120 minutes

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- SSH access via jump host: `ssh -J debian@211.62.97.71:22015 ktcloud@<node-ip>`
- Proxmox/OpenStack hypervisor console access
- `kubeadm` token if re-joining a node

## Recovery Procedure

### Phase 1: Assess the Situation

```bash
# Check all node statuses
kubectl get nodes -o wide

# Get node conditions
kubectl describe node <failed-node-name>

# Check when the node last reported in
kubectl get node <failed-node-name> -o jsonpath='{.status.conditions[?(@.type=="Ready")].lastHeartbeatTime}'

# List pods that were running on the failed node
kubectl get pods -A -o wide | grep <failed-node-name>
kubectl get pods -A -o wide | grep <failed-node-name> | grep -v Running
```

### Phase 2: Cordon the Node (Prevent New Scheduling)

```bash
# Mark node as unschedulable immediately
kubectl cordon <failed-node-name>

# Verify it is cordoned
kubectl get nodes | grep <failed-node-name>
# STATUS should show: Ready,SchedulingDisabled  or  NotReady,SchedulingDisabled
```

### Phase 3: Diagnose the Root Cause

```bash
# Try to reach the node via SSH
ssh -J debian@211.62.97.71:22015 ktcloud@<node-ip>

# If SSH works, check:
sudo systemctl status kubelet
sudo journalctl -u kubelet -n 100 --no-pager
sudo systemctl status containerd
free -h && df -h /

# Check for kernel/hardware errors
sudo dmesg | tail -50 | grep -E 'error|fail|panic|killed'
sudo journalctl -k | tail -50
```

### Phase 4A: Soft Recovery (Node is SSH-accessible)

```bash
# Fix common issues and restart kubelet
sudo systemctl restart kubelet
sudo systemctl restart containerd  # if containerd is also down

# Check kubelet is running
sudo systemctl status kubelet
sudo journalctl -u kubelet -f  # watch for errors

# Back on control plane, watch node recover
kubectl get nodes -w
# Should show: NotReady -> Ready within 1-2 minutes after kubelet restart
```

### Phase 4B: Hard Recovery (Node needs reboot)

```bash
# Via Proxmox API or console — graceful reboot
# (Use Proxmox web UI or proxmox CLI)

# After reboot, verify node rejoins automatically
kubectl get nodes -w

# If node doesn't rejoin within 5 minutes, check kubelet on node
ssh -J debian@211.62.97.71:22015 ktcloud@<node-ip>
sudo systemctl status kubelet
sudo systemctl enable --now kubelet
```

### Phase 4C: Node Drain and Workload Migration (When Node Won't Recover)

```bash
# Drain the node — evict all pods gracefully
kubectl drain <failed-node-name> \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --grace-period=60 \
  --timeout=300s

# If pods are stuck in Terminating, force delete
kubectl get pods -A --field-selector=spec.nodeName=<failed-node-name> | grep Terminating
kubectl delete pod <stuck-pod> -n <namespace> --force --grace-period=0

# Verify all workloads have migrated
kubectl get pods -A -o wide | grep <failed-node-name>  # should be empty or DaemonSets only
```

### Phase 5: Validate Workload Redistribution

```bash
# Check pods are running on healthy nodes
kubectl get pods -n online-boutique -o wide

# Verify all services have Ready endpoints
kubectl get endpoints -n online-boutique

# Check for Pending pods (may indicate resource pressure on remaining nodes)
kubectl get pods -A | grep Pending

# If Pending due to insufficient resources, check node capacity
kubectl describe nodes | grep -A 10 "Allocated resources"
```

### Phase 6: Node Replacement (If Permanent Failure)

```bash
# Remove the dead node from the cluster
kubectl delete node <failed-node-name>

# Provision a new VM in Proxmox/OpenStack with same spec:
# - OS: Ubuntu 22.04
# - CPU: 4 vCPU
# - RAM: 8GB
# - Storage: 50GB

# On the new VM — run these steps:
# 1. Install containerd and Kubernetes packages (same version as cluster: v1.29.15)
# 2. Disable swap: sudo swapoff -a && sudo sed -i '/swap/d' /etc/fstab
# 3. Configure sysctl for Kubernetes networking
# 4. Join the cluster:

# Generate fresh join token on master01
ssh -J debian@211.62.97.71:22015 ktcloud@192.168.100.201
kubeadm token create --print-join-command

# On new node, run the join command:
sudo kubeadm join 172.25.20.200:6443 \
  --token <token> \
  --discovery-token-ca-cert-hash sha256:<hash>

# Wait for node to appear and become Ready
kubectl get nodes -w
```

### Phase 7: Restore Traffic and Uncordon

```bash
# After node is fully Ready and all pods are stable
kubectl uncordon <recovered-or-new-node-name>

# Verify workloads spread across all nodes
kubectl get pods -n online-boutique -o wide

# Run smoke test
kubectl run smoke-test --image=curlimages/curl -n online-boutique --rm -it -- \
  curl -s -o /dev/null -w "%{http_code}" http://frontend/
```

## Verification

```bash
# All nodes should be Ready
kubectl get nodes

# No Pending pods
kubectl get pods -A | grep -v Running | grep -v Completed

# Service endpoints are healthy
kubectl get endpoints -n online-boutique

# PVCs are bound (local-path PVs are tied to specific nodes)
kubectl get pvc -n online-boutique

# Cluster capacity is sufficient
kubectl describe nodes | grep -E "Allocatable|Allocated"
```

## Post-Recovery Actions
1. Take a new Proxmox snapshot
2. Document the failure mode and timeline in results/
3. Verify monitoring alerts would have fired (check alert history in Alertmanager)

## Escalation
- If replaced node's PVs had data that is now lost: initiate data recovery procedure
- If more than one node fails simultaneously: suspect network partition — check switch/hypervisor
- If cluster cannot reach quorum (etcd): do NOT drain/delete nodes — escalate to etcd recovery procedure

## Loki Queries

```logql
# Kubelet errors on the failed node
{job="kubelet", node="<failed-node>"} |= "error" or |= "Error"

# Pod eviction events
{job="kubernetes-events"} |= "Evicted" or |= "eviction"

# Node controller events
{job="kube-controller-manager"} |= "NodeNotReady" or |= "node" |= "NotReady"
```

## Prometheus Queries

```promql
# Node Ready status history
kube_node_status_condition{condition="Ready", status="true"}

# Pod eviction rate after node failure
rate(kube_pod_status_phase{phase="Failed"}[10m])

# Cluster CPU/memory headroom after node loss
sum(kube_node_status_allocatable{resource="cpu"}) - sum(kube_pod_container_resource_requests{resource="cpu"})

# Pods rescheduled to new node (watch count increase on other nodes)
count by (node) (kube_pod_info{namespace="online-boutique"})
```

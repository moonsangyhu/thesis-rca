# Node NotReady Diagnosis

## Overview
A node in `NotReady` state means the Kubernetes control plane has lost contact with the node's kubelet, or the kubelet has reported that the node is not healthy. The node controller marks a node as NotReady after `node-monitor-grace-period` (default 40 seconds) of no heartbeat. After `pod-eviction-timeout` (default 5 minutes), pods on the node are evicted. This is one of the most impactful failures as all pods on the affected node become unavailable.

## Symptoms
- `kubectl get nodes` shows STATUS `NotReady`
- Pods on the node show status `NodeLost`, `Unknown`, or `Terminating` indefinitely
- New pods are not scheduled to the node
- Node shows taint `node.kubernetes.io/not-ready:NoSchedule` and `node.kubernetes.io/not-ready:NoExecute`
- Monitoring shows no metrics from the node
- SSH to node may succeed (node alive) but kubelet is unhealthy

## Diagnostic Commands

```bash
# Step 1: Identify NotReady nodes
kubectl get nodes
kubectl get nodes -o wide
# Check STATUS and ROLES columns

# Step 2: Describe the node for detailed conditions
kubectl describe node <node-name>
# Look at:
#   Conditions section - True/False/Unknown for each condition
#   Events section at bottom
#   Kubelet Version - verify it matches expected version

# Step 3: Check node conditions in detail
kubectl get node <node-name> -o json | python3 -c "
import sys, json
n = json.load(sys.stdin)
for c in n['status']['conditions']:
    print(f'{c[\"type\"]}: {c[\"status\"]} - {c.get(\"message\",\"\")[:100]}')
"

# Step 4: Check taints applied to NotReady node
kubectl describe node <node-name> | grep -A5 "Taints:"

# Step 5: Check pods on the NotReady node
kubectl get pods -A -o wide | grep <node-name>
kubectl get pods -A --field-selector spec.nodeName=<node-name>

# Step 6: Check kubelet status (SSH to node)
# ssh <user>@<node-ip>
# systemctl status kubelet
# journalctl -u kubelet -f --since "30 minutes ago"

# Step 7: Check container runtime (containerd)
# systemctl status containerd
# crictl info
# crictl pods

# Step 8: Check certificate expiry (common cause of kubelet auth failure)
# On the node:
# openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -noout -dates
# openssl x509 -in /etc/kubernetes/pki/apiserver.crt -noout -dates

# Step 9: Check network connectivity to API server
# On the node:
# curl -k https://<api-server-vip>:6443/healthz
# In this cluster: curl -k https://172.25.20.200:6443/healthz

# Step 10: Check Cilium CNI health (this cluster uses Cilium 1.15.6)
kubectl get pods -n kube-system | grep cilium
kubectl exec -n kube-system -l k8s-app=cilium -- cilium status
kubectl exec -n kube-system ds/cilium -- cilium status --verbose 2>&1 | grep -E "KV|Ctrl|Proxy"

# Step 11: Check Cilium agent on the specific node
kubectl get pod -n kube-system -o wide | grep cilium | grep <node-name>
CILIUM_POD=$(kubectl get pod -n kube-system -o wide | grep cilium | grep <node-name> | awk '{print $1}')
kubectl logs -n kube-system $CILIUM_POD --tail=50

# Step 12: Check network plugin socket
# On the node:
# ls -la /run/cilium/
# ls -la /var/run/cilium/cilium.sock

# Step 13: Check system resources (disk, memory)
# On the node:
# df -h
# free -h
# systemctl status

# Step 14: Check kube-proxy or Cilium kube-proxy replacement
kubectl get pods -n kube-system | grep kube-proxy
kubectl get configmap -n kube-system kube-proxy -o yaml | grep mode

# Step 15: Check API server connectivity from node
# On the node:
# nc -zv 172.25.20.200 6443
# curl -k https://172.25.20.200:6443/healthz

# Step 16: Check system logs for kernel panics, hardware errors
# On the node:
# dmesg | tail -50
# journalctl -k --since "1 hour ago" | grep -E "error|panic|oom"

# Step 17: Check NTP synchronization (clock skew causes cert issues)
# On the node:
# timedatectl status
# chronyc tracking

# Step 18: Check node disk pressure specifically
# On the node:
# df -h /var/lib/kubelet
# df -h /var/lib/containerd
# df -i /var/lib/kubelet
```

## Common Causes

1. **Kubelet process crashed or stopped**: The kubelet service on the node has stopped. This can be caused by OOM on the node itself, a bug, or manual stop.

2. **Container runtime (containerd) failure**: The kubelet cannot communicate with containerd via its Unix socket. Containerd crash or unresponsive state.

3. **Network partition**: The node is isolated from the control plane. Physical network issues, switch failures, or CNI misconfiguration preventing control plane communication.

4. **Cilium CNI agent failure**: The Cilium agent pod crashed or is unhealthy. Without a healthy CNI, kubelet reports node as not ready.

5. **Certificate expiry**: Kubelet client certificates have expired. The kubelet cannot authenticate to the API server. Certificates expire after 1 year by default.

6. **Disk full**: The node's root filesystem or kubelet data directory is full, preventing kubelet from functioning.

7. **Node resource exhaustion**: Node is under extreme memory pressure and kubelet process itself got OOMKilled.

8. **API server unreachable**: The API server is down or the VIP (172.25.20.200) is unreachable from the node.

9. **Clock skew**: Node time is more than 5 minutes off from the rest of the cluster, causing TLS certificate validation failures.

10. **Kernel panic or hardware failure**: The node has experienced a kernel panic or hardware failure. The OS may be running but in degraded state.

## Resolution Steps

### Step 1: Check if node is physically accessible
```bash
# Try SSH to the node
ssh ktcloud@<node-ip>  # for master nodes
# If SSH fails - physical/network issue, requires infrastructure intervention

# Check if node responds to ping
ping -c 3 <node-ip>
```

### Step 2: Restart kubelet
```bash
# SSH to node, then:
sudo systemctl daemon-reload
sudo systemctl restart kubelet
sudo systemctl status kubelet

# Check logs after restart
sudo journalctl -u kubelet -f --since "2 minutes ago"
```

### Step 3: Restart container runtime
```bash
# SSH to node:
sudo systemctl restart containerd
sudo systemctl status containerd

# Verify containerd is responding
sudo crictl info
```

### Step 4: Fix Cilium CNI issues
```bash
# Restart Cilium agent on the problematic node
NODE=<node-name>
CILIUM_POD=$(kubectl get pod -n kube-system -o wide | grep cilium | grep $NODE | awk '{print $1}')
kubectl delete pod $CILIUM_POD -n kube-system
# Wait for new pod to start
kubectl rollout status ds/cilium -n kube-system

# If Cilium is broken on all nodes:
kubectl rollout restart ds/cilium -n kube-system
kubectl rollout restart ds/cilium-operator -n kube-system

# Check Cilium connectivity
kubectl exec -n kube-system ds/cilium -- cilium status
kubectl exec -n kube-system ds/cilium -- cilium endpoint list
```

### Step 5: Fix expired certificates
```bash
# Check certificate expiry on node
# SSH to node:
openssl x509 -in /var/lib/kubelet/pki/kubelet-client-current.pem -noout -dates

# For kubeadm clusters - renew certificates on master
kubectl get csr
# Approve pending CSRs for kubelet cert renewal:
kubectl certificate approve <csr-name>

# Force certificate rotation on the node:
# SSH to node:
sudo rm /var/lib/kubelet/pki/kubelet-client-current.pem
sudo systemctl restart kubelet
# Kubelet will request new certificate via CSR

# On master - approve the CSR:
kubectl get csr
kubectl certificate approve <csr-name>
```

### Step 6: Free disk space
```bash
# SSH to node:
df -h
# Clean up container images
sudo crictl rmi --prune
# Clean up old logs
sudo journalctl --vacuum-size=500M
# Clean up old container layers
sudo crictl rmp $(sudo crictl pods -q --state=Exited)
```

### Step 7: Fix NTP/clock skew
```bash
# SSH to node:
sudo chronyc makestep  # Force time sync
sudo timedatectl set-ntp true
systemctl restart chronyd
```

### Step 8: Cordon and drain as temporary measure
```bash
# While investigating, prevent new pods from being scheduled on the node
kubectl cordon <node-name>

# If node is recoverable but needs maintenance
kubectl drain <node-name> \
  --ignore-daemonsets \
  --delete-emptydir-data \
  --force \
  --timeout=300s

# After fix, uncordon
kubectl uncordon <node-name>
```

## Post-Recovery Verification

```bash
# Verify node is Ready
kubectl get node <node-name>

# Verify Cilium is healthy on the node
kubectl exec -n kube-system $CILIUM_POD -- cilium status

# Verify pods are re-scheduled and running
kubectl get pods -A -o wide | grep <node-name> | grep -v Running

# Run connectivity test
kubectl apply -f https://raw.githubusercontent.com/cilium/cilium/main/examples/kubernetes/connectivity-check/connectivity-check.yaml
```

## Prevention
- Set up node monitoring with Prometheus `node_exporter`
- Alert on `kube_node_status_condition{condition="Ready",status="true"} == 0`
- Configure automatic kubelet certificate rotation: `rotateCertificates: true` in kubelet config
- Use node lease renewals for faster failure detection
- Set up external monitoring (separate from in-cluster) for node accessibility
- Implement log rotation to prevent disk full from kubelet logs
- Use infrastructure monitoring for disk SMART data and hardware errors

## Related Issues
- `node-pressure.md` - DiskPressure, MemoryPressure causing NotReady
- `network-connectivity.md` - Network issues causing node isolation
- `network-policy-debug.md` - Cilium CNI issues

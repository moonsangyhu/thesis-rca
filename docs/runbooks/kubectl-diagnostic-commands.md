# Runbook: Essential kubectl Diagnostic Commands for RCA

## Trigger Conditions
Initial diagnostic procedure for any Kubernetes incident. Use as the first step before consulting fault-specific runbooks.

## Severity
N/A (diagnostic procedure)

## Estimated Resolution Time
5-15 minutes for initial assessment

## Prerequisites
- kubectl configured with cluster access
- KUBECONFIG: `~/.kube/config-k8s-lab`
- SSH tunnel active: `ssh -N -f k8s-lab-tunnel`

## Investigation Steps

### Step 1: Cluster-wide overview
```bash
# Node status
kubectl get nodes -o wide

# All pods with issues
kubectl get pods -A --field-selector 'status.phase!=Running,status.phase!=Succeeded'

# Recent events cluster-wide (last 30 min)
kubectl get events -A --sort-by='.lastTimestamp' | tail -30

# Resource usage overview
kubectl top nodes
kubectl top pods -A --sort-by=memory | head -20
```

### Step 2: Namespace-level investigation
```bash
# All resources in namespace
kubectl get all -n boutique

# Pod details with status
kubectl get pods -n boutique -o wide

# Events in namespace
kubectl get events -n boutique --sort-by='.lastTimestamp'

# Filtered events
kubectl get events -n boutique --field-selector reason=BackOff
kubectl get events -n boutique --field-selector reason=FailedScheduling
kubectl get events -n boutique --field-selector reason=Unhealthy
kubectl get events -n boutique --field-selector reason=OOMKilling
kubectl get events -n boutique --field-selector reason=Evicted
```

### Step 3: Pod-level deep dive
```bash
# Full pod description (events, conditions, containers)
kubectl describe pod <pod> -n <ns>

# Current container logs
kubectl logs <pod> -n <ns> -c <container>

# Previous container logs (after restart)
kubectl logs <pod> -n <ns> -c <container> --previous

# Logs since specific time
kubectl logs <pod> -n <ns> --since=30m
kubectl logs <pod> -n <ns> --since-time="2024-01-15T10:00:00Z"

# Follow logs in real-time
kubectl logs <pod> -n <ns> -f

# All container logs in a pod
kubectl logs <pod> -n <ns> --all-containers

# Container resource usage
kubectl top pod <pod> -n <ns> --containers
```

### Step 4: Interactive debugging
```bash
# Execute command in running container
kubectl exec -it <pod> -n <ns> -- sh
kubectl exec -it <pod> -n <ns> -c <container> -- bash

# Check environment variables
kubectl exec <pod> -n <ns> -- env | sort

# Check filesystem
kubectl exec <pod> -n <ns> -- ls -la /app/config/
kubectl exec <pod> -n <ns> -- cat /etc/resolv.conf

# Check network connectivity
kubectl exec <pod> -n <ns> -- wget -qO- http://service:port/healthz
kubectl exec <pod> -n <ns> -- nslookup kubernetes.default

# Check processes
kubectl exec <pod> -n <ns> -- ps aux
```

### Step 5: Node-level debugging
```bash
# Node conditions and info
kubectl describe node <node> | grep -A20 "Conditions:"
kubectl describe node <node> | grep -A10 "Allocated resources:"

# Debug node (runs privileged pod)
kubectl debug node/<node> -it --image=busybox -- sh
# Inside: chroot /host to access node filesystem

# Check kubelet logs (via debug pod or SSH)
kubectl debug node/<node> -it --image=busybox -- sh -c \
  "chroot /host journalctl -u kubelet --since '30 min ago' | tail -50"

# Taints and labels
kubectl get node <node> -o jsonpath='{.spec.taints}'
kubectl get node <node> --show-labels
```

### Step 6: Service and networking
```bash
# Service details and endpoints
kubectl describe svc <service> -n <ns>
kubectl get endpoints <service> -n <ns>
kubectl get endpointslice -n <ns> -l kubernetes.io/service-name=<service>

# DNS resolution test
kubectl run dns-test --rm -it --image=busybox:1.36 --restart=Never -- \
  nslookup <service>.<namespace>.svc.cluster.local

# Port forwarding for direct testing
kubectl port-forward svc/<service> -n <ns> 8080:80

# Check NetworkPolicies affecting a pod
kubectl get networkpolicy -n <ns>
```

### Step 7: Storage
```bash
# PVC status
kubectl get pvc -n <ns>
kubectl describe pvc <pvc> -n <ns>

# PV details
kubectl get pv
kubectl describe pv <pv>

# StorageClass
kubectl get storageclass
```

### Step 8: RBAC and permissions
```bash
# Check if a service account can perform an action
kubectl auth can-i create pods --as=system:serviceaccount:<ns>:<sa> -n <ns>
kubectl auth can-i '*' '*' --as=system:serviceaccount:<ns>:<sa> -n <ns>

# List roles and bindings
kubectl get roles,rolebindings -n <ns>
kubectl get clusterroles,clusterrolebindings | grep <sa>
```

### Step 9: GitOps status
```bash
# FluxCD
flux get all
kubectl get kustomization -n flux-system
kubectl get helmrelease -A

# ArgoCD
kubectl get applications -n argocd
```

## Quick Reference: Common Field Selectors
```bash
# Pods by phase
--field-selector status.phase=Pending
--field-selector status.phase=Failed
--field-selector status.phase!=Running

# Events by reason
--field-selector reason=BackOff
--field-selector reason=FailedMount
--field-selector reason=FailedScheduling
--field-selector reason=Evicted

# Pods on specific node
--field-selector spec.nodeName=worker01
```

## Verification
- Root cause identified or narrowed down to specific component
- Proceed to fault-specific runbook (rca-f1 through rca-f10)

## Escalation
If unable to access cluster or kubectl commands timing out:
1. Check SSH tunnel: `ssh -N -f k8s-lab-tunnel`
2. Check API server: `kubectl cluster-info`
3. Check kubeconfig: `KUBECONFIG=~/.kube/config-k8s-lab kubectl get nodes`

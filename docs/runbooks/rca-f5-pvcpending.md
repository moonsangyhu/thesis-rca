# Runbook: F5 - PVCPending Root Cause Analysis

## Trigger Conditions
Use this runbook when PersistentVolumeClaims (PVCs) remain in `Pending` state, pods are stuck in `Pending` because their PVC is unbound, or storage provisioning errors appear in events.

## Severity
**High** — Stateful services (databases, caches, message queues) cannot start without their PVCs. In Online Boutique, this primarily affects `cartservice` (Redis) and any persistent data stores.

## Estimated Resolution Time
20-45 minutes

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- Access to storage provisioner pods (check `kube-system` namespace)
- SSH access to nodes for local-path storage issues
- StorageClass admin permissions

## Investigation Steps

### Step 1: Identify pending PVCs
```bash
# List all pending PVCs
kubectl get pvc -A | grep Pending

# Get details on a specific PVC
kubectl describe pvc <pvc-name> -n <namespace>
```

Look for events like:
```
Events:
  Warning  ProvisioningFailed  ...  storageclass.storage.k8s.io "standard" not found
  Warning  ProvisioningFailed  ...  failed to provision volume: ...
  Normal   WaitForFirstConsumer ...  waiting for first consumer to be created before binding
```

### Step 2: Check the StorageClass
```bash
# List available StorageClasses
kubectl get storageclass

# Check the default StorageClass
kubectl get storageclass | grep '(default)'

# Describe the StorageClass referenced by the PVC
kubectl describe storageclass <sc-name>

# Compare what PVC requests vs what's available
kubectl get pvc <pvc-name> -n <namespace> -o jsonpath='{.spec.storageClassName}'
```

**Common issues:**
- PVC references a non-existent StorageClass name
- StorageClass exists but `VOLUMEBINDINGMODE=WaitForFirstConsumer` — pod must be scheduled first
- StorageClass `Reclaim Policy` is `Retain` — old PVs may be cluttering

### Step 3: Check the storage provisioner
```bash
# Find the provisioner for the StorageClass
kubectl get storageclass <sc-name> -o jsonpath='{.provisioner}'

# Common provisioners:
# - rancher.io/local-path (local-path-provisioner)
# - docker.io/hostpath (Docker Desktop)
# - csi.vsphere.volume (vSphere CSI)
# - rook.io/block (Rook-Ceph)
# - nfs.csi.k8s.io (NFS CSI)

# Check provisioner pod status
kubectl get pods -n kube-system | grep -E 'provisioner|csi|storage'

# Check provisioner logs
kubectl logs -n kube-system <provisioner-pod-name> | tail -50
kubectl logs -n kube-system <provisioner-pod-name> | grep -i 'error\|fail\|warn'
```

### Step 4: Check available PersistentVolumes
```bash
# List all PVs and their status
kubectl get pv

# Check for available PVs that could bind
kubectl get pv | grep Available

# Check capacity and access mode match
kubectl get pvc <pvc-name> -n <namespace> -o json | jq '{storage: .spec.resources.requests.storage, accessModes: .spec.accessModes}'
kubectl get pv -o json | jq '.items[] | select(.status.phase=="Available") | {name: .metadata.name, capacity: .spec.capacity, accessModes: .spec.accessModes}'
```

### Step 5: Check node-level storage capacity (for local-path provisioner)
```bash
# For local-path-provisioner, check disk space on each node
for node in worker01 worker02 worker03; do
  echo "=== $node ==="
  kubectl debug node/$node -it --image=busybox -- df -h /host/var/local-path-provisioner 2>/dev/null || \
  kubectl debug node/$node -it --image=busybox -- df -h /host 2>/dev/null
done

# Or SSH to each worker
ssh -J debian@211.62.97.71:22015 ktcloud@172.25.20.111 'df -h /'
ssh -J debian@211.62.97.71:22015 ktcloud@172.25.20.112 'df -h /'
ssh -J debian@211.62.97.71:22015 ktcloud@172.25.20.113 'df -h /'
```

### Step 6: Check for volume topology constraints
```bash
# If WaitForFirstConsumer, check what node the pod is scheduled on
kubectl get pod <pod-name> -n <namespace> -o wide

# PVC should bind to a PV on the same node
kubectl get pvc <pvc-name> -n <namespace> -o json | jq '.metadata.annotations'

# Check node affinity on PV
kubectl get pv <pv-name> -o json | jq '.spec.nodeAffinity'
```

### Step 7: Check CSI driver health
```bash
# Check CSI driver pods
kubectl get pods -n kube-system | grep csi

# Check CSI node info
kubectl get csinodes

# CSI driver registered?
kubectl get csidrivers
```

## Resolution

### Fix A: StorageClass doesn't exist — create it
```bash
# For local-path-provisioner (common in lab environments)
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/master/deploy/local-path-storage.yaml

# Set as default StorageClass
kubectl patch storageclass local-path \
  -p '{"metadata": {"annotations":{"storageclass.kubernetes.io/is-default-class":"true"}}}'
```

### Fix B: Fix PVC to reference correct StorageClass
```bash
# Delete and recreate PVC with correct storageClassName
kubectl delete pvc <pvc-name> -n <namespace>

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: <pvc-name>
  namespace: <namespace>
spec:
  accessModes:
    - ReadWriteOnce
  storageClassName: local-path
  resources:
    requests:
      storage: 1Gi
EOF
```

### Fix C: Manually provision PV (static provisioning)
```bash
# Create a PV manually to satisfy the PVC
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: manual-pv-<namespace>
spec:
  capacity:
    storage: 1Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Delete
  storageClassName: local-path
  hostPath:
    path: /mnt/data/<namespace>
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - worker01
EOF

# Create the directory on the node
ssh -J debian@211.62.97.71:22015 ktcloud@172.25.20.111 'sudo mkdir -p /mnt/data/<namespace>'
```

### Fix D: Free up disk space on nodes
```bash
# Remove unused container images
ssh -J debian@211.62.97.71:22015 ktcloud@172.25.20.111 'sudo crictl rmi --prune'

# Clean up unused volumes
ssh -J debian@211.62.97.71:22015 ktcloud@172.25.20.111 'sudo df -h / && sudo du -sh /var/lib/rancher/local-path-provisioner/'
```

### Fix E: Restart the storage provisioner
```bash
kubectl rollout restart deployment/local-path-provisioner -n local-path-storage
# Or
kubectl delete pod -n kube-system -l app=local-path-provisioner
```

## Verification
```bash
# PVC should move to Bound state
kubectl get pvc -n <namespace> -w

# Confirm PV was created and bound
kubectl get pv | grep <pvc-name>

# Pod should now move from Pending to Running
kubectl get pods -n <namespace> -w

# Confirm pod can write to the volume
kubectl exec -n <namespace> <pod-name> -- df -h /data
kubectl exec -n <namespace> <pod-name> -- touch /data/test && echo "Write OK"
```

## Escalation
- If provisioner logs show permission errors: check provisioner ServiceAccount RBAC permissions
- If node disk is full and cannot be easily freed: request additional storage from infrastructure team
- If Rook-Ceph or distributed storage is degraded: escalate to storage team with `ceph -s` output

## Loki Queries

```logql
# Storage provisioner errors
{namespace="kube-system", app=~".*provisioner.*"} |= "error" or |= "Error" or |= "failed"

# PVC-related Kubernetes events
{job="kubernetes-events"} |= "ProvisioningFailed" or |= "FailedMount"

# CSI driver errors
{namespace="kube-system", app=~".*csi.*"} |= "error"

# Volume mount failures in pods
{namespace="<namespace>"} |= "MountVolume" or |= "volume" |= "error"
```

## Prometheus Queries

```promql
# PVCs not bound
kube_persistentvolumeclaim_status_phase{phase!="Bound", namespace="<namespace>"}

# PV capacity available
kube_persistentvolume_capacity_bytes{storageclass="<sc-name>"}

# PV status by phase
count by (phase) (kube_persistentvolume_status_phase)

# Node disk pressure
kube_node_status_condition{condition="DiskPressure", status="true"}

# Node filesystem usage
1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})

# Pods pending due to unbound PVC
kube_pod_status_phase{phase="Pending", namespace="<namespace>"}
```

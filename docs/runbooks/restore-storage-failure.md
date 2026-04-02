# Runbook: Storage Failure Recovery

## Trigger Conditions
Use this runbook when PersistentVolumes are in `Failed` or `Released` state, when pods cannot mount volumes and are stuck in `ContainerCreating`, or when data corruption/loss is suspected on a persistent volume.

## Severity
**Critical** (for stateful services) / **High** (for stateless services with config volumes)

## Estimated Resolution Time
30-90 minutes (depending on whether data recovery is needed)

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- SSH access to nodes for local-path storage inspection
- Storage admin access (if using distributed storage)
- Backup access (if data recovery is needed)

## Recovery Procedure

### Phase 1: Identify Failed Volumes

```bash
# Check PV status
kubectl get pv

# PV states:
# Available  — unbound, ready
# Bound      — in use by a PVC
# Released   — PVC deleted but PV not yet reclaimed
# Failed     — provisioning or binding failed

# Check PVC status
kubectl get pvc -A | grep -v Bound

# Get details on a stuck PVC
kubectl describe pvc <pvc-name> -n <namespace>

# Find pods stuck waiting for volume
kubectl get pods -A | grep ContainerCreating
kubectl describe pod <pod-name> -n <namespace> | grep -A10 "Events:"
```

Look for:
```
Warning  FailedMount  Unable to attach or mount volumes: ...
Warning  FailedMount  MountVolume.SetUp failed for volume "..." : ...
```

### Phase 2: Diagnose the Volume Problem

```bash
# Check if the PV exists and what node it's on
kubectl get pv <pv-name> -o json | jq '{
  name: .metadata.name,
  status: .status.phase,
  nodeAffinity: .spec.nodeAffinity,
  hostPath: .spec.hostPath,
  capacity: .spec.capacity,
  reclaimPolicy: .spec.persistentVolumeReclaimPolicy
}'

# For local-path provisioner, check if directory exists on the node
NODE=$(kubectl get pv <pv-name> -o jsonpath='{.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0]}')
echo "PV is on node: $NODE"

# Check node IP mapping
# worker01: 172.25.20.111, worker02: 172.25.20.112, worker03: 172.25.20.113
ssh -J debian@211.62.97.71:22015 ktcloud@<node-ip> \
  "ls -la /var/local-path-provisioner/ 2>/dev/null || ls -la /opt/local-path-provisioner/ 2>/dev/null"

# Check if node is Ready
kubectl get node $NODE
```

### Phase 3: Check Mount on Node

```bash
# SSH to the node where the PV should be mounted
ssh -J debian@211.62.97.71:22015 ktcloud@<node-ip>

# Check mount points
mount | grep <pvc-name>
df -h | grep <pvc-name>

# Check for filesystem errors
sudo dmesg | grep -E 'error|fail|ext4|xfs' | tail -30

# Check if the backing directory exists and has data
ls -la /var/local-path-provisioner/<pvc-uid>/
du -sh /var/local-path-provisioner/<pvc-uid>/

# Check filesystem health
sudo fsck /dev/<device>  # for block devices (if applicable)
```

### Phase 4: Recovery Scenarios

#### Scenario A: PV is in Released state (PVC deleted, PV still has data)

```bash
# The PV is Released but has data — patch it to Available
kubectl patch pv <pv-name> \
  --type json \
  -p '[{"op": "remove", "path": "/spec/claimRef"}]'

# Now create a new PVC that binds to this specific PV
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
      storage: <same-size-as-PV>
  volumeName: <pv-name>  # Bind to specific PV
EOF
```

#### Scenario B: Pod cannot mount — volume is on a different node

```bash
# Local path volumes are node-specific
# If the pod is scheduled on a different node, it can't mount

# Option 1: Add node affinity to pod to pin it to the correct node
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/nodeSelector", "value": {"kubernetes.io/hostname": "<correct-node>"}}]'

# Option 2: Migrate data to new node
# 1. Create new PVC on new node
# 2. Use a migration job to copy data
cat <<EOF | kubectl apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: migrate-data
  namespace: <namespace>
spec:
  template:
    spec:
      nodeName: <target-node>
      restartPolicy: Never
      volumes:
      - name: old-pvc
        persistentVolumeClaim:
          claimName: <old-pvc-name>
      - name: new-pvc
        persistentVolumeClaim:
          claimName: <new-pvc-name>
      containers:
      - name: migrator
        image: busybox
        command: ['sh', '-c', 'cp -av /old-data/. /new-data/']
        volumeMounts:
        - name: old-pvc
          mountPath: /old-data
        - name: new-pvc
          mountPath: /new-data
EOF
```

#### Scenario C: Filesystem corruption

```bash
# On the node, unmount and repair the filesystem
sudo umount /var/local-path-provisioner/<pvc-uid>/
sudo fsck -y /dev/<device>
sudo mount /dev/<device> /var/local-path-provisioner/<pvc-uid>/

# Check data integrity
ls -la /var/local-path-provisioner/<pvc-uid>/
```

#### Scenario D: PV is Failed — delete and reprovision

```bash
# WARNING: This destroys data
# Only do this if data is not important OR you have a backup

# Delete the PVC and PV
kubectl delete pvc <pvc-name> -n <namespace>
kubectl delete pv <pv-name>

# Clean up the directory on the node
ssh -J debian@211.62.97.71:22015 ktcloud@<node-ip> \
  "sudo rm -rf /var/local-path-provisioner/<pvc-uid>/"

# Recreate the PVC — provisioner will create a new PV
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

# Restore data from backup if available
kubectl exec -n <namespace> <pod-name> -- \
  tar -xzf /backup/data.tar.gz -C /data/
```

### Phase 5: Verify Data Integrity

```bash
# Check application can read/write data
kubectl exec -n <namespace> <pod-name> -- ls -la /data/

# For Redis (cartservice)
kubectl exec -n online-boutique deploy/redis-cart -- \
  redis-cli PING
kubectl exec -n online-boutique deploy/redis-cart -- \
  redis-cli DBSIZE

# Check application logs for data errors
kubectl logs -n <namespace> <pod-name> | grep -i 'data\|storage\|error' | tail -20
```

## Verification

```bash
# PVC should be Bound
kubectl get pvc -n <namespace>

# Pod should be Running
kubectl get pods -n <namespace> -w

# Volume mounted correctly
kubectl exec -n <namespace> <pod-name> -- df -h /data

# Write test
kubectl exec -n <namespace> <pod-name> -- touch /data/.write-test && \
  echo "Write test PASSED" || echo "Write test FAILED"

# Application health
kubectl exec -n <namespace> <pod-name> -- \
  curl -s http://localhost:<port>/healthz
```

## Escalation
- If data corruption is extensive: engage DBA/data team before any recovery attempts
- If the storage node itself has hardware failure: escalate to infrastructure team for disk replacement
- If using distributed storage (Rook-Ceph) and OSD is down: `ceph -s` for cluster health before proceeding

## Loki Queries

```logql
# Storage mount errors
{job="kubernetes-events"} |= "FailedMount" or |= "MountVolume"

# Filesystem errors in kubelet
{job="kubelet"} |= "filesystem" |= "error" or |= "read-only"

# Application data access errors
{namespace="<namespace>"} |= "EIO" or |= "read-only file system" or |= "no space left"

# Provisioner errors
{namespace="kube-system", app=~".*provisioner.*"} |= "error" or |= "failed"
```

## Prometheus Queries

```promql
# PVC not bound
kube_persistentvolumeclaim_status_phase{phase!="Bound"}

# Node filesystem usage (watch for full disks)
1 - (node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})

# Node disk pressure
kube_node_status_condition{condition="DiskPressure", status="true"}

# PV capacity
kube_persistentvolume_capacity_bytes

# I/O wait on nodes (high I/O wait indicates storage issues)
avg by (node) (rate(node_cpu_seconds_total{mode="iowait"}[5m]))
```

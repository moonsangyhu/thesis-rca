# PVC Lost/Released State Diagnosis

## Overview
A PersistentVolumeClaim can enter a `Lost` state when the bound PersistentVolume no longer exists or has become inaccessible. This is a critical situation as it means the application cannot access its persistent data. A PV enters `Released` state when the PVC it was bound to is deleted, and the reclaim policy determines what happens next. `Retain` policy leaves data intact, `Delete` policy removes the underlying storage, and `Recycle` (deprecated) scrubs the volume. Understanding these states is essential for data recovery operations.

## Symptoms
- `kubectl get pvc` shows STATUS `Lost`
- Pods mounting the lost PVC fail to start with volume-related errors
- `kubectl get pv` shows STATUS `Released` (PVC deleted) or `Failed`
- Application logs show "no such file or directory" or "device not found"
- Events show "FailedAttachVolume" or "FailedMount"
- StatefulSet pods stuck in Terminating or Pending

## Diagnostic Commands

```bash
# Step 1: Check PVC and PV status
kubectl get pvc -n <namespace>
kubectl get pv

# Step 2: Get detailed PVC status
kubectl describe pvc <pvc-name> -n <namespace>
# Key fields:
#   Status: Lost (bound PV no longer exists)
#   Volume: <pv-name> (which PV it was bound to)
#   Events: failure messages

# Step 3: Check if the previously bound PV still exists
PV_NAME=$(kubectl get pvc <pvc-name> -n <namespace> -o jsonpath='{.spec.volumeName}')
echo "PV name: $PV_NAME"
kubectl get pv $PV_NAME
kubectl describe pv $PV_NAME

# Step 4: Check Released PVs (previously bound, PVC deleted)
kubectl get pv | grep Released

# Step 5: Check Failed PVs
kubectl get pv | grep Failed
kubectl describe pv | grep -A10 "Status.*Failed"

# Step 6: Check reclaim policy on the PV
kubectl get pv <pv-name> -o jsonpath='{.spec.persistentVolumeReclaimPolicy}'

# Step 7: Check if underlying storage still exists
# For hostPath PVs - check on the node
kubectl get pv <pv-name> -o jsonpath='{.spec.hostPath.path}'
# SSH to node and verify: ls -la <path>

# For NFS PVs
kubectl get pv <pv-name> -o jsonpath='{.spec.nfs}'
# Verify NFS server is accessible from cluster

# Step 8: Check events in the namespace
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | grep -E "volume|mount|attach"

# Step 9: Check if StatefulSet pods are affected (common for StatefulSets)
kubectl get statefulset -n <namespace>
kubectl describe statefulset <sts-name> -n <namespace> | grep -A5 "Volume Claims"

# Step 10: Check volume attachment status
kubectl get volumeattachment
kubectl describe volumeattachment <attachment-name> 2>/dev/null

# Step 11: Check CSI volume status
kubectl get volumeattachment -o json | python3 -c "
import sys, json
va = json.load(sys.stdin)['items']
for a in va:
    print(a['metadata']['name'], a['status'].get('attached', False), a['spec'].get('nodeName', ''))
"

# Step 12: Check if claimRef is blocking PV re-use
kubectl get pv <pv-name> -o jsonpath='{.spec.claimRef}'
# Released PV still has claimRef - must be cleared for re-binding

# Step 13: Check storage class reclaim policy
kubectl get storageclass -o custom-columns=\
'NAME:.metadata.name,RECLAIM:.reclaimPolicy,BINDING:.volumeBindingMode'

# Step 14: For cloud volumes - check if underlying disk exists
# AWS EBS example:
# VOLUME_ID=$(kubectl get pv <pv-name> -o jsonpath='{.spec.awsElasticBlockStore.volumeID}')
# aws ec2 describe-volumes --volume-ids $VOLUME_ID
```

## Common Causes

1. **Node failure while volume attached**: The node hosting a PV with `hostPath` or `local` storage went down. The PV data exists but is inaccessible until the node recovers.

2. **PVC accidentally deleted**: Someone deleted the PVC (possibly during namespace cleanup) while the PV still exists with `Retain` policy.

3. **Storage backend failure**: NFS server, Longhorn, or cloud storage backend has failed. PVC becomes Lost because the PV cannot be accessed.

4. **Manual PV deletion**: The PV was manually deleted while still bound. The PVC references a non-existent PV and enters Lost state.

5. **StorageClass provisioner error**: Dynamic provisioning started but failed partway through, leaving PV in Failed state.

6. **Released PV not recycled**: PVC was deleted, PV is Released with `Retain` policy. New PVC cannot bind because the Released PV still has claimRef pointing to the old PVC.

7. **Volume expansion failure**: PVC requested volume expansion, expansion failed, leaving PVC in Resize state or Lost.

8. **Node migration**: Volumes with `local` or `hostPath` type tied to a specific node that was removed from the cluster.

## Resolution Steps

### Step 1: Recover data from Released PV (Retain policy)
```bash
# PV is Released (old PVC was deleted), data still exists
# Need to clear claimRef to allow re-binding

# Option A: Clear claimRef to allow any PVC to bind
kubectl patch pv <pv-name> \
  -p '{"spec": {"claimRef": null}}'

# Then create a new PVC that matches the PV specs exactly
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: <new-pvc-name>
  namespace: <namespace>
spec:
  accessModes:
    - ReadWriteOnce
  resources:
    requests:
      storage: 10Gi
  storageClassName: <storage-class>
  volumeName: <pv-name>   # Pin to specific PV
EOF
```

### Step 2: Recover from Lost PVC (bound PV no longer exists)
```bash
# The PVC references a PV that no longer exists
# Option A: If PV was accidentally deleted but underlying storage exists

# Re-create the PV with same name and claimRef pointing to the existing PVC
PVC_NS=<namespace>
PVC_NAME=<pvc-name>
PVC_UID=$(kubectl get pvc $PVC_NAME -n $PVC_NS -o jsonpath='{.metadata.uid}')

cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: <original-pv-name>
spec:
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  persistentVolumeReclaimPolicy: Retain
  storageClassName: <storage-class>
  hostPath:
    path: /mnt/data/<original-path>   # Original data path
  claimRef:
    apiVersion: v1
    kind: PersistentVolumeClaim
    name: $PVC_NAME
    namespace: $PVC_NS
    uid: $PVC_UID    # Must match existing PVC UID exactly
EOF
```

### Step 3: For StatefulSet PVC recovery
```bash
# StatefulSets have special PVC naming: <volume-claim-name>-<pod-name>-<ordinal>
# e.g., data-my-sts-0, data-my-sts-1

# Scale down StatefulSet first
kubectl scale statefulset <sts-name> -n <namespace> --replicas=0

# Recover each PVC following Step 2 above

# Scale back up
kubectl scale statefulset <sts-name> -n <namespace> --replicas=<original-count>
```

### Step 4: Delete Lost PVC and re-provision (data loss - last resort)
```bash
# WARNING: This will cause DATA LOSS if data is not recovered first
# Only use if data is backed up or ephemeral

# For StatefulSet - need to handle PVC deletion carefully
kubectl delete pvc <pvc-name> -n <namespace>

# If PVC is stuck terminating (finalizer issue)
kubectl patch pvc <pvc-name> -n <namespace> \
  -p '{"metadata": {"finalizers": null}}'

# Let StatefulSet recreate the PVC
kubectl delete pod <sts-pod> -n <namespace>
```

### Step 5: Force-delete stuck volume attachments
```bash
# Sometimes VolumeAttachment objects get stuck
kubectl get volumeattachment | grep <pv-name>

# Delete the stuck attachment
kubectl delete volumeattachment <attachment-name>

# If stuck in terminating:
kubectl patch volumeattachment <attachment-name> \
  -p '{"metadata": {"finalizers": null}}'
```

### Step 6: Fix PV reclaim policy to prevent future issues
```bash
# Change reclaim policy to Retain on important PVs
kubectl patch pv <pv-name> \
  -p '{"spec": {"persistentVolumeReclaimPolicy": "Retain"}}'

# Change StorageClass default reclaim policy (for new PVs)
kubectl patch storageclass <sc-name> \
  -p '{"reclaimPolicy": "Retain"}'
```

## Data Recovery Checklist

```bash
# 1. Identify what data was on the volume
kubectl describe pvc <pvc-name> -n <namespace>
kubectl get pv <pv-name> -o jsonpath='{.spec}' | python3 -m json.tool

# 2. Check if hostPath data still exists on node
NODE=$(kubectl get pv <pv-name> -o jsonpath='{.spec.nodeAffinity.required.nodeSelectorTerms[0].matchExpressions[0].values[0]}')
PATH=$(kubectl get pv <pv-name> -o jsonpath='{.spec.local.path}')
echo "Data should be at: $PATH on node $NODE"
# SSH to node and check: ls -la $PATH

# 3. Create a recovery pod to access data
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: data-recovery
  namespace: <namespace>
spec:
  nodeName: <node-name>
  containers:
  - name: recovery
    image: busybox
    command: ["sleep", "3600"]
    volumeMounts:
    - mountPath: /data
      name: recovery-vol
  volumes:
  - name: recovery-vol
    hostPath:
      path: <data-path>
EOF

kubectl exec -it data-recovery -n <namespace> -- ls /data
# Copy data out
kubectl cp data-recovery:/data /tmp/recovered-data -n <namespace>
kubectl delete pod data-recovery -n <namespace>
```

## Prevention
- Use `Retain` reclaim policy for production PVCs with important data
- Implement regular volume backup (Velero, application-level backups)
- Use RBAC to prevent accidental PVC deletion by non-admin users
- Enable `--enable-admission-plugins=... ` with appropriate admission controllers
- Monitor PVC status: `kube_persistentvolumeclaim_status_phase{phase="Lost"} > 0`
- Alert on Released PVs that are not re-claimed within SLA
- Document PV-to-data mapping for quick recovery
- Test backup/restore procedures regularly

## Related Issues
- `pvc-pending.md` - PVC stuck in Pending state
- `pod-pending.md` - Pods pending due to PVC issues
- `node-notready.md` - Node issues causing volume detachment

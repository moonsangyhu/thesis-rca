# PVC Stuck in Pending State

## Overview
A PersistentVolumeClaim (PVC) in `Pending` state means Kubernetes has not been able to bind it to a PersistentVolume (PV). This prevents any pod that mounts the PVC from starting. PVCs can be stuck Pending due to no available PV matching the request, StorageClass provisioner failures, topology constraints, or capacity exhaustion. With dynamic provisioning, the provisioner creates a PV automatically, so provisioner errors are a common cause.

## Symptoms
- `kubectl get pvc` shows STATUS `Pending`
- Pods mounting the PVC are stuck in `Pending` with reason `pod has unbound immediate PersistentVolumeClaims`
- No PV is bound to the PVC
- StorageClass provisioner pod may have errors
- `kubectl describe pvc` shows events with provisioning errors

## Diagnostic Commands

```bash
# Step 1: Check PVC status
kubectl get pvc -n <namespace>
kubectl get pvc -A | grep Pending

# Step 2: Describe the PVC for detailed error
kubectl describe pvc <pvc-name> -n <namespace>
# Key fields to check:
#   StorageClass - which provisioner to use
#   Capacity - requested size
#   Access Modes - ReadWriteOnce, ReadWriteMany, ReadOnlyMany
#   Events - provisioning errors

# Step 3: Check if a matching PV exists
kubectl get pv
kubectl describe pv | grep -E "StorageClass|Claim|Status|Capacity|Access Modes"

# Step 4: Check StorageClass
kubectl get storageclass
kubectl describe storageclass <storage-class-name>
# Check:
#   Provisioner - which provisioner handles it
#   VolumeBindingMode - Immediate or WaitForFirstConsumer
#   ReclaimPolicy
#   AllowVolumeExpansion

# Step 5: Check provisioner pod logs
# For local path provisioner:
kubectl get pods -n kube-system | grep -i provisioner
kubectl logs -n kube-system -l app=local-path-provisioner --tail=50

# For NFS provisioner:
kubectl get pods -n <provisioner-namespace> | grep nfs
kubectl logs -n <provisioner-namespace> -l app=nfs-provisioner --tail=50

# For Longhorn:
kubectl get pods -n longhorn-system | grep manager
kubectl logs -n longhorn-system -l app=longhorn-manager --tail=50

# Step 6: Check if default StorageClass exists
kubectl get storageclass | grep "(default)"

# Step 7: Check if PVC specifies a StorageClass that exists
kubectl get pvc <pvc-name> -n <namespace> -o jsonpath='{.spec.storageClassName}'
SC=$(kubectl get pvc <pvc-name> -n <namespace> -o jsonpath='{.spec.storageClassName}')
kubectl get storageclass $SC

# Step 8: Check volume binding mode - WaitForFirstConsumer requires a pod
kubectl get pvc <pvc-name> -n <namespace> -o jsonpath='{.spec.volumeName}'
kubectl get storageclass <sc-name> -o jsonpath='{.volumeBindingMode}'
# WaitForFirstConsumer: PVC stays Pending until a pod is scheduled

# Step 9: Check available capacity in the storage backend
# For local storage - check node disk space
kubectl describe node | grep -A5 "Ephemeral Storage"

# For Longhorn
kubectl get nodes.longhorn.io -n longhorn-system
kubectl describe nodes.longhorn.io -n longhorn-system | grep "Storage Available"

# Step 10: Check RBAC for provisioner
kubectl get clusterrolebinding | grep provisioner
kubectl get rolebinding -n <provisioner-namespace> | grep provisioner

# Step 11: Check events in the namespace
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | grep -E "pvc|volume|provision"

# Step 12: Check if PVC has label selector (static binding)
kubectl get pvc <pvc-name> -n <namespace> -o jsonpath='{.spec.selector}'
# If set, only PVs with matching labels will be bound

# Step 13: For WaitForFirstConsumer - check if pod is scheduled
kubectl get pod -n <namespace> -o wide | grep <pod-using-pvc>
# Pod must be scheduled to a node for volume provisioning to start

# Step 14: Check CSI driver health
kubectl get csidrivers
kubectl get csinodes
kubectl get pods -n kube-system | grep csi

# Step 15: Check volume plugin logs via events
kubectl get events -n <namespace> -o json | python3 -c "
import sys, json
evts = json.load(sys.stdin)['items']
for e in evts:
    if 'volume' in e.get('reason','').lower() or 'provision' in e.get('reason','').lower():
        print(e['lastTimestamp'], e['reason'], e['message'][:200])
"
```

## Common Causes

1. **No default StorageClass**: PVC does not specify a storageClassName and no default StorageClass exists. Kubernetes cannot determine which provisioner to use.

2. **StorageClass does not exist**: The PVC specifies a StorageClass by name but that class has not been created.

3. **Provisioner pod not running**: The external provisioner responsible for the StorageClass is not running or crashed.

4. **Insufficient storage capacity**: The storage backend does not have enough free space to provision the requested volume size.

5. **Access mode not supported**: The PVC requests `ReadWriteMany` but the storage backend only supports `ReadWriteOnce`.

6. **WaitForFirstConsumer binding mode**: The StorageClass uses `WaitForFirstConsumer` which means the PV is only provisioned when a pod that mounts it gets scheduled. The PVC appears Pending until a pod is scheduled.

7. **RBAC permissions missing**: The provisioner service account lacks permissions to create PV objects or read StorageClass.

8. **Node topology constraints**: For topology-aware provisioners, no node satisfies both pod scheduling constraints and volume topology constraints.

9. **PV selector mismatch**: PVC has a label selector but no PV with matching labels exists (for static provisioning).

10. **PV has wrong reclaim policy or is not available**: Available PVs are in `Released` state (previously bound, now released) and need to be recycled.

## Resolution Steps

### Step 1: Fix missing default StorageClass
```bash
# List storage classes and check which is default
kubectl get storageclass

# Set an existing StorageClass as default
kubectl patch storageclass <sc-name> \
  -p '{"metadata": {"annotations": {"storageclass.kubernetes.io/is-default-class": "true"}}}'

# Create a local-path StorageClass (simple option for lab)
cat <<EOF | kubectl apply -f -
apiVersion: storage.k8s.io/v1
kind: StorageClass
metadata:
  name: local-path
  annotations:
    storageclass.kubernetes.io/is-default-class: "true"
provisioner: rancher.io/local-path
reclaimPolicy: Delete
volumeBindingMode: WaitForFirstConsumer
EOF
```

### Step 2: Fix provisioner not running
```bash
# Check provisioner health
kubectl get pods -n kube-system -l app=local-path-provisioner

# Restart provisioner if crashlooping
kubectl rollout restart deployment -n kube-system <provisioner-deployment>

# Check provisioner logs for errors
kubectl logs -n kube-system -l app=local-path-provisioner --tail=100

# If provisioner is missing entirely, deploy it:
# For local-path-provisioner:
kubectl apply -f https://raw.githubusercontent.com/rancher/local-path-provisioner/master/deploy/local-path-storage.yaml
```

### Step 3: Fix RBAC for provisioner
```bash
# Check what permissions provisioner has
kubectl get clusterrole | grep provisioner
kubectl describe clusterrole <provisioner-role>

# Grant missing permissions
kubectl create clusterrolebinding provisioner-binding \
  --clusterrole=cluster-admin \
  --serviceaccount=<namespace>:<service-account>
# Note: cluster-admin is too broad for production; use minimal permissions
```

### Step 4: Handle WaitForFirstConsumer - ensure pod is scheduled
```bash
# Check if the pod using the PVC exists and is scheduled
kubectl get pod -n <namespace> -o wide | grep <pod-name>

# If pod is also Pending, resolve pod scheduling first
kubectl describe pod <pod-name> -n <namespace> | tail -20
# See pod-pending.md for pod scheduling issues
```

### Step 5: Manually create a PV for static binding
```bash
# For a local volume on a specific node:
cat <<EOF | kubectl apply -f -
apiVersion: v1
kind: PersistentVolume
metadata:
  name: local-pv-<node>
  labels:
    type: local
spec:
  storageClassName: local-path
  capacity:
    storage: 10Gi
  accessModes:
    - ReadWriteOnce
  hostPath:
    path: "/mnt/data"
  nodeAffinity:
    required:
      nodeSelectorTerms:
      - matchExpressions:
        - key: kubernetes.io/hostname
          operator: In
          values:
          - worker01
EOF
```

### Step 6: Verify fix
```bash
# Watch PVC status change
kubectl get pvc -n <namespace> -w

# Check if pod starts after PVC binds
kubectl get pods -n <namespace> -w
```

## StorageClass Comparison

```bash
# Check all storage classes in the cluster
kubectl get storageclass -o custom-columns=\
'NAME:.metadata.name,PROVISIONER:.provisioner,RECLAIM:.reclaimPolicy,BINDING:.volumeBindingMode,DEFAULT:.metadata.annotations.storageclass\.kubernetes\.io/is-default-class'

# Check PV to PVC binding
kubectl get pv -o custom-columns=\
'NAME:.metadata.name,CAPACITY:.spec.capacity.storage,CLAIM:.spec.claimRef.name,NAMESPACE:.spec.claimRef.namespace,STATUS:.status.phase,SC:.spec.storageClassName'
```

## Prevention
- Always specify `storageClassName` explicitly in PVC definitions; don't rely on default
- Test provisioner health in pre-deployment checks
- Monitor pending PVCs: `kube_persistentvolumeclaim_status_phase{phase="Pending"} > 0`
- Ensure provisioner pods have resource limits and restart policies
- For critical workloads, pre-provision PVs to avoid provisioner delays
- Set up capacity alerting on storage backends

## Related Issues
- `pvc-lost.md` - PVC in Lost/Released state
- `pod-pending.md` - Pod pending due to PVC not bound
- `pod-evicted.md` - Pods evicted due to storage pressure

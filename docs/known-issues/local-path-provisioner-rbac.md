# Known Issue: local-path-provisioner Missing RBAC for Helper Pods

## Issue ID
KI-002

## Affected Components
- local-path-provisioner (rancher/local-path-provisioner)
- PersistentVolumeClaim provisioning
- ClusterRole / RBAC subsystem

## Symptoms
- PersistentVolumeClaims remain in `Pending` state indefinitely
- `kubectl describe pvc <name>` shows event: `Failed to create helper pod`
- local-path-provisioner pod logs show:
  ```
  E  Failed to create helper pod: pods is forbidden: User "system:serviceaccount:local-path-storage:local-path-provisioner-service-account" cannot create resource "pods" in API group "" in the namespace "local-path-storage"
  ```
- Dynamic volume provisioning completely non-functional
- StatefulSets with volumeClaimTemplates stuck in Pending

## Root Cause
local-path-provisioner uses a helper pod to initialize and clean up volumes (e.g., creating directory structure, setting permissions). This helper pod is created and deleted programmatically by the provisioner during volume lifecycle events.

The default ClusterRole shipped with many versions of local-path-provisioner grants CRUD on PersistentVolumes and PersistentVolumeClaims, and `get/list/watch` on pods, but omits `create` and `delete` verbs for pods. Without these permissions, the service account cannot create or remove the transient helper pod, causing all PVC provisioning to fail.

In this cluster, the issue appeared after a fresh deployment from the upstream manifest, which had an incomplete RBAC definition:
```yaml
# Missing from ClusterRole rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
  # create and delete were absent
```

## Diagnostic Commands
```bash
# Check PVC status
kubectl get pvc -A | grep Pending

# Describe the stuck PVC
kubectl describe pvc <pvc-name> -n <namespace>

# Check provisioner logs
kubectl -n local-path-storage logs -l app=local-path-provisioner --tail=50

# Verify RBAC permissions for the service account
kubectl auth can-i create pods \
  --as=system:serviceaccount:local-path-storage:local-path-provisioner-service-account \
  -n local-path-storage

kubectl auth can-i delete pods \
  --as=system:serviceaccount:local-path-storage:local-path-provisioner-service-account \
  -n local-path-storage

# List current ClusterRole rules
kubectl get clusterrole local-path-provisioner-role -o yaml
```

## Resolution
This issue was resolved in this cluster by adding a dedicated rule for pod create/delete to the ClusterRole.

**Step 1**: Edit the ClusterRole:
```bash
kubectl edit clusterrole local-path-provisioner-role
```

**Step 2**: Add the following rule (separate from any existing pod rule):
```yaml
rules:
  # ... existing rules ...
  - apiGroups: [""]
    resources: ["pods"]
    verbs: ["get", "list", "watch", "create", "patch", "update", "delete"]
```

**Step 3**: Verify the fix:
```bash
kubectl auth can-i create pods \
  --as=system:serviceaccount:local-path-storage:local-path-provisioner-service-account \
  -n local-path-storage
# Expected: yes

# Re-test by creating a PVC
kubectl apply -f - <<EOF
apiVersion: v1
kind: PersistentVolumeClaim
metadata:
  name: test-pvc
spec:
  accessModes: [ReadWriteOnce]
  storageClassName: local-path
  resources:
    requests:
      storage: 1Gi
EOF
kubectl get pvc test-pvc -w
# Expected: transitions to Bound within ~10s
```

**Step 4**: Clean up the test PVC:
```bash
kubectl delete pvc test-pvc
```

## Workaround
If you cannot edit the ClusterRole immediately, you can create a separate ClusterRoleBinding that binds a permissive role:
```bash
kubectl create clusterrolebinding local-path-pod-creator \
  --clusterrole=edit \
  --serviceaccount=local-path-storage:local-path-provisioner-service-account
```
This is overly permissive and should be replaced with the targeted fix as soon as possible.

## Prevention
- After installing local-path-provisioner, always run the RBAC check commands above before declaring the environment ready
- Pin to a verified manifest version and validate the ClusterRole includes pod create/delete
- Add a smoke-test PVC creation to cluster provisioning CI/CD pipeline

## References
- local-path-provisioner GitHub: https://github.com/rancher/local-path-provisioner
- Upstream RBAC fix PR: https://github.com/rancher/local-path-provisioner/pull/225
- K8s RBAC docs: https://kubernetes.io/docs/reference/access-authn-authz/rbac/

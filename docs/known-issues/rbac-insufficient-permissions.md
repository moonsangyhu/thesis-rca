# Known Issue: Insufficient RBAC Permissions for Operators and Controllers

## Issue ID
KI-016

## Affected Components
- Kubernetes RBAC (Role, ClusterRole, RoleBinding, ClusterRoleBinding)
- Operators (FluxCD, ArgoCD, Prometheus Operator, etc.)
- Custom controllers
- ServiceAccounts used by operators

## Symptoms
- Operator or controller pod logs show permission errors:
  ```
  E0101 controller.go:XXX reconciler error ... "deployments.apps" is forbidden: User "system:serviceaccount:flux-system:kustomize-controller" cannot patch resource "deployments" in API group "apps"
  ```
- Resources managed by the operator never reach desired state
- `kubectl get <crd>` shows error conditions on managed resources
- Controller keeps retrying and producing identical error log entries
- CRD status subresource not updated (operator cannot write back status)
- `kubectl auth can-i` returns `no` for operations the operator should perform

## Root Cause
RBAC in Kubernetes requires explicit permission grants. Common patterns where insufficient RBAC causes controller failures:

**Pattern 1: Operator needs watch/list on CRDs it manages**
A custom controller that manages a CRD must have `get`, `list`, and `watch` permissions on that CRD. Without `watch`, the controller cannot receive update events and may only process changes on restart. Without `list`, the controller cannot reconcile all existing objects on startup.

**Pattern 2: Controller needs update/patch on status subresource**
Writing to a resource's `.status` field requires permission on the `status` subresource separately from the main resource. Many operators grant `update` on the resource but forget the status subresource:
```yaml
# Incomplete — cannot update status
rules:
- apiGroups: ["mygroup.io"]
  resources: ["myresources"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
# Missing:
- apiGroups: ["mygroup.io"]
  resources: ["myresources/status"]
  verbs: ["get", "update", "patch"]
```

**Pattern 3: Namespace-scoped vs cluster-scoped permissions**
Using a `Role` (namespace-scoped) when the operator needs to manage resources across namespaces. Must use `ClusterRole` with appropriate `ClusterRoleBinding`.

**Pattern 4: Missing permissions for dependencies**
An operator that manages Deployments may also need permissions on Services, ConfigMaps, ServiceAccounts, or Secrets that it creates as part of the managed resource lifecycle.

## Diagnostic Commands
```bash
# Check what permissions a service account has
kubectl auth can-i --list \
  --as=system:serviceaccount:<namespace>:<sa-name> \
  -n <namespace>

# Test a specific permission
kubectl auth can-i patch deployments/status \
  --as=system:serviceaccount:flux-system:helm-controller \
  -n default

kubectl auth can-i watch customresourcedefinitions \
  --as=system:serviceaccount:monitoring:prometheus-operator \
  -n monitoring

# Check operator pod logs for RBAC errors
kubectl logs -n <operator-namespace> deployment/<operator> | grep -i "forbidden\|rbac\|permission\|cannot"

# List ClusterRoles and ClusterRoleBindings for an SA
kubectl get clusterrolebindings -o json | \
  jq '.items[] | select(.subjects[]?.name=="<sa-name>" and .subjects[]?.namespace=="<namespace>") | .roleRef'

# Check a specific ClusterRole's rules
kubectl get clusterrole <name> -o yaml

# Debug with impersonation
kubectl get pods -n default \
  --as=system:serviceaccount:<namespace>:<sa-name>
```

## Resolution
**Step 1**: Identify the exact permission error from logs:
```bash
kubectl logs -n flux-system deployment/kustomize-controller | grep "forbidden" | head -5
# Example: "deployments.apps" is forbidden: cannot "patch" resource "deployments"
# in API group "apps" in the namespace "production"
```

**Step 2**: Add the missing permission to the ClusterRole:
```yaml
# For an operator that needs full resource + status management
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: my-operator-role
rules:
# Manage the primary resource
- apiGroups: ["mygroup.io"]
  resources: ["myresources"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
# Update status subresource (separate entry required)
- apiGroups: ["mygroup.io"]
  resources: ["myresources/status"]
  verbs: ["get", "update", "patch"]
# Manage finalizers
- apiGroups: ["mygroup.io"]
  resources: ["myresources/finalizers"]
  verbs: ["update"]
# Manage dependent resources
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["services", "configmaps", "secrets"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
# Watch events for debugging
- apiGroups: [""]
  resources: ["events"]
  verbs: ["create", "patch"]
```

**Step 3**: Apply and verify:
```bash
kubectl apply -f clusterrole.yaml
kubectl auth can-i patch myresources/status \
  --as=system:serviceaccount:<namespace>:<sa-name>
# Expected: yes
```

**Step 4**: Restart the operator to clear any backoff state:
```bash
kubectl rollout restart deployment/<operator> -n <operator-namespace>
```

## Workaround
For a quick unblock during an incident, temporarily bind the operator's SA to `cluster-admin`:
```bash
kubectl create clusterrolebinding temp-admin \
  --clusterrole=cluster-admin \
  --serviceaccount=<namespace>:<sa-name>
```
**WARNING**: This grants full cluster access. Remove immediately once the correct minimal role is in place:
```bash
kubectl delete clusterrolebinding temp-admin
```

## Prevention
- Always include `status` and `finalizers` subresource permissions for CRD controllers
- Use `ClusterRole` for operators that manage cross-namespace resources
- Test RBAC with `kubectl auth can-i --list` for each SA before deploying operators
- Follow the Operator SDK / Kubebuilder RBAC markers documentation for correct marker annotations
- Periodically audit operator permissions with `polaris` or `rbac-lookup` tools

## References
- K8s RBAC: https://kubernetes.io/docs/reference/access-authn-authz/rbac/
- Status subresource: https://kubernetes.io/docs/tasks/extend-kubernetes/custom-resources/custom-resource-definitions/#status-subresource
- kubectl auth can-i: https://kubernetes.io/docs/reference/generated/kubectl/kubectl-commands#auth
- rbac-lookup tool: https://github.com/FairwindsOps/rbac-lookup

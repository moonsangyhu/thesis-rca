# Known Issue: Service Account Token Automount Security and Permission Issues

## Issue ID
KI-015

## Affected Components
- ServiceAccount (default and custom)
- All pods relying on in-cluster API access
- Applications using Kubernetes API via in-cluster config
- Operators and controllers

## Symptoms
- Application fails with `403 Forbidden` when attempting Kubernetes API calls after `automountServiceAccountToken: false` is set
- Error messages in pod logs:
  ```
  Error from server (Forbidden): pods is forbidden: User "system:serviceaccount:default:default" cannot list resource "pods" in API group ""
  ```
- Applications that previously worked fail after security hardening of ServiceAccounts
- `kubectl exec` into pod shows no `/var/run/secrets/kubernetes.io/serviceaccount/token` file
- Kubernetes client libraries fail to initialize: `unable to load in-cluster configuration`
- Security scanner flags pods in namespace `default` with default SA token auto-mounted

## Root Cause
By default, Kubernetes automatically mounts a service account token into every pod at `/var/run/secrets/kubernetes.io/serviceaccount/`. This token grants the pod the permissions of the associated ServiceAccount (by default, the `default` SA).

**Security concern**: The default ServiceAccount in most namespaces has no RBAC permissions, but the token itself exists and can be stolen via container escape or path traversal vulnerabilities. Best practice is to disable automounting and only grant tokens where needed.

**Breaking change when disabling**: When `automountServiceAccountToken: false` is set (either on the ServiceAccount or the Pod spec), applications that make API calls via the in-cluster configuration fail because they cannot find the token file or CA certificate.

The two locations where automount can be disabled:
```yaml
# Method 1: On the ServiceAccount (affects all pods using this SA)
apiVersion: v1
kind: ServiceAccount
metadata:
  name: default
automountServiceAccountToken: false  # Disables for all pods using this SA

# Method 2: On the Pod spec (overrides SA setting)
spec:
  automountServiceAccountToken: false  # Disables for this specific pod
```

If a pod genuinely needs API access and either is set to false, it will fail.

## Diagnostic Commands
```bash
# Check if default SA has automount disabled
kubectl get serviceaccount default -n <namespace> -o yaml | grep automount

# Check if pod spec overrides automount
kubectl get pod <pod-name> -n <namespace> -o yaml | grep automount

# Check if token is mounted in a running pod
kubectl exec -it <pod-name> -n <namespace> -- ls /var/run/secrets/kubernetes.io/serviceaccount/

# Check permissions of the pod's service account
kubectl auth can-i --list --as=system:serviceaccount:<namespace>:<sa-name>

# Check what SA a pod is using
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.serviceAccountName}'

# Check RBAC for the SA
kubectl get clusterrolebindings,rolebindings -A -o json | \
  jq '.items[] | select(.subjects[]?.name=="<sa-name>" and .subjects[]?.namespace=="<namespace>")'
```

## Resolution
**For pods that DO need API access**:

Step 1: Create a dedicated ServiceAccount with minimal required permissions:
```yaml
apiVersion: v1
kind: ServiceAccount
metadata:
  name: my-app-sa
  namespace: my-namespace
automountServiceAccountToken: true  # Explicitly enable
```

Step 2: Create a Role with only necessary permissions:
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: my-app-role
  namespace: my-namespace
rules:
- apiGroups: [""]
  resources: ["pods"]
  verbs: ["get", "list", "watch"]
- apiGroups: ["apps"]
  resources: ["deployments"]
  verbs: ["get", "list"]
```

Step 3: Bind the Role to the ServiceAccount:
```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: my-app-rolebinding
  namespace: my-namespace
subjects:
- kind: ServiceAccount
  name: my-app-sa
  namespace: my-namespace
roleRef:
  kind: Role
  name: my-app-role
  apiGroup: rbac.authorization.k8s.io
```

Step 4: Reference the ServiceAccount in the Pod spec:
```yaml
spec:
  serviceAccountName: my-app-sa
  automountServiceAccountToken: true
```

**For pods that DO NOT need API access**:
```yaml
spec:
  serviceAccountName: default
  automountServiceAccountToken: false  # Disable for security
```

**Disable automount on default SA cluster-wide** (security hardening):
```bash
# For each namespace
for ns in $(kubectl get namespaces -o name | cut -d/ -f2); do
  kubectl patch serviceaccount default -n $ns \
    -p '{"automountServiceAccountToken": false}'
done
```

## Workaround
If an application unexpectedly needs API access after `automountServiceAccountToken: false` was set, temporarily re-enable it on the pod spec while you audit what API calls the application is making:
```bash
kubectl patch deployment <name> -n <namespace> --type=json \
  -p='[{"op":"add","path":"/spec/template/spec/automountServiceAccountToken","value":true}]'
```

## Prevention
- Default all new ServiceAccounts to `automountServiceAccountToken: false`
- Create application-specific SAs with least-privilege RBAC for any app that needs API access
- Use policy enforcement (Kyverno/OPA) to require `automountServiceAccountToken: false` on workloads that don't explicitly need it
- Audit service account permissions with `kubectl auth can-i --list --as=system:serviceaccount:<ns>:<name>`

## References
- ServiceAccount documentation: https://kubernetes.io/docs/concepts/security/service-accounts/
- RBAC authorization: https://kubernetes.io/docs/reference/access-authn-authz/rbac/
- Securing service accounts: https://kubernetes.io/docs/tasks/configure-pod-container/configure-service-account/
- CIS K8s Benchmark 5.1.5: Ensure that default service accounts are not bound to active cluster admin role

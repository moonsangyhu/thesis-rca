# Known Issue: Secret Updates Not Reflected in Pods (Env Var vs Volume Mount)

## Issue ID
KI-011

## Affected Components
- Kubernetes Secrets
- All pods using secrets as environment variables
- All pods using secrets as volume mounts
- External Secrets Operator (if in use)

## Symptoms
- After updating a Secret, application continues using old credentials
- Database connection failures after credential rotation because pods still use old password
- Only some pods pick up the new secret (newly started pods get new value, existing pods do not)
- Volume-mounted secrets update within ~1 minute, but `env`/`envFrom` references do not update at all
- Horizontal scaling creates new pods with new secret values while old pods retain old values
- SSL certificate rotation not picked up by running pods

## Root Cause
Kubernetes handles secret propagation differently depending on how the secret is consumed:

**Environment variables** (`env` with `secretKeyRef`, or `envFrom` with `secretRef`):
- Secret values are injected into the process environment at pod startup time
- Environment variables are immutable after a process starts
- There is no mechanism to update environment variables in a running process
- The only way to pick up new secret values is to restart the pod (which triggers a new container with the updated env)

**Volume mounts** (`volumes` with `secret` type):
- kubelet periodically syncs secret contents to the volume (default sync period: 1 minute, controlled by `--sync-frequency`)
- Updated secret data is written to the volume file automatically
- The application must re-read the file to see the new value — which is application-dependent
- Some apps (e.g., Nginx, applications that re-read certs) handle this natively

This behavioral difference is a common source of confusion and incidents during credential rotation.

## Diagnostic Commands
```bash
# Check current secret value
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.<key>}' | base64 -d

# Check how a pod consumes the secret
kubectl get pod <pod-name> -n <namespace> -o yaml | grep -A10 "env:\|envFrom:\|volumes:"

# Check what value a running pod has in env (may differ from current secret)
kubectl exec -it <pod-name> -n <namespace> -- env | grep <SECRET_KEY>

# Check volume-mounted secret content in a running pod
kubectl exec -it <pod-name> -n <namespace> -- cat /path/to/mounted/secret/<key>

# Check kubelet sync frequency (on a node)
ps aux | grep kubelet | grep sync-frequency
# Default is 1m if not set

# Check pod restart time vs secret update time
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.status.containerStatuses[0].state.running.startedAt}'
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.metadata.creationTimestamp}'
```

## Resolution
**Secret Rotation Procedure for Env-Var Based Secrets**:

Step 1: Update the secret:
```bash
kubectl create secret generic <secret-name> \
  --from-literal=<key>=<new-value> \
  -n <namespace> \
  --dry-run=client -o yaml | kubectl apply -f -
```

Step 2: Trigger a rolling restart of all affected Deployments:
```bash
kubectl rollout restart deployment/<name> -n <namespace>
kubectl rollout status deployment/<name> -n <namespace>

# For StatefulSets
kubectl rollout restart statefulset/<name> -n <namespace>

# For DaemonSets
kubectl rollout restart daemonset/<name> -n <namespace>
```

Step 3: Verify new pods have the updated value:
```bash
kubectl exec -it <new-pod-name> -n <namespace> -- env | grep <SECRET_KEY>
```

**Secret Rotation Procedure for Volume-Mounted Secrets**:

Step 1: Update the secret (same as above).

Step 2: Wait ~1-2 minutes for kubelet to sync the new value.

Step 3: Verify the file in the pod has been updated:
```bash
kubectl exec -it <pod-name> -n <namespace> -- cat /path/to/secret/file
```

Step 4: If the application does not re-read the file automatically, trigger a reload or restart.

**Best Practice - Convert env vars to volume mounts for rotatable secrets**:
```yaml
spec:
  volumes:
  - name: db-creds
    secret:
      secretName: db-credentials
  containers:
  - name: app
    volumeMounts:
    - name: db-creds
      mountPath: /etc/secrets/db
      readOnly: true
    # Application reads /etc/secrets/db/password at request time, not startup time
```

## Workaround
Use an annotation-based rolling restart trigger with GitOps. Store a `secret-hash` annotation on the Deployment that contains a hash of the secret. When the secret changes, update the hash, which triggers a rolling restart automatically:
```yaml
spec:
  template:
    metadata:
      annotations:
        secret-hash: "<sha256-of-secret>"
```

With Kustomize, use `secretGenerator` which automatically updates the secret name hash and triggers restarts.

## Prevention
- Prefer volume-mounted secrets over environment variable secrets for credentials that require rotation
- Implement secret rotation automation that also triggers pod restarts for env-var consumers
- Use External Secrets Operator with `refreshInterval` to keep secrets in sync with vault backends
- Document secret consumption method for each application in its runbook

## References
- K8s secrets: https://kubernetes.io/docs/concepts/configuration/secret/
- Secret auto-update behavior: https://kubernetes.io/docs/concepts/configuration/secret/#using-secrets-as-files-from-a-pod
- External Secrets Operator: https://external-secrets.io/latest/
- Kustomize secretGenerator: https://kubectl.docs.kubernetes.io/references/kustomize/builtins/#_secretgenerator_

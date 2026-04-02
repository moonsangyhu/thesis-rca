# Known Issue: Init Container Failure Prevents Main Container from Starting

## Issue ID
KI-019

## Affected Components
- All pods with `initContainers` configured
- Applications with database dependency checks (wait-for-db pattern)
- Applications with configuration initialization steps

## Symptoms
- Pod stuck in `Init:0/1` or `Init:CrashLoopBackOff` state indefinitely
- `kubectl get pods` shows:
  ```
  NAME              READY   STATUS              RESTARTS
  myapp-abc123      0/1     Init:CrashLoopBackOff   5
  ```
- Main application container never starts
- `kubectl describe pod` shows init container status:
  ```
  Init Containers:
    wait-for-db:
      State: Terminated
        Reason: Error
        Exit Code: 1
  ```
- Application appears to be deployed but serves no traffic
- Liveness/readiness probes show the pod as not ready

## Root Cause
Init containers run sequentially before any main containers start. If any init container exits with a non-zero code, the pod is restarted (according to the pod's `restartPolicy`). The main container never starts until all init containers complete successfully.

Common causes of init container failure:

**Cause 1: Wrong hostname or service name for dependency check**
The most frequent issue is using an incorrect hostname in a "wait for database" init container:
```yaml
initContainers:
- name: wait-for-db
  image: busybox
  command: ['sh', '-c', 'until nc -zv postgres 5432; do echo waiting; sleep 2; done']
  # "postgres" is wrong — should be "postgres-svc.database.svc.cluster.local"
  # or the actual Service name
```

**Cause 2: Wrong credentials in init container database check**
```yaml
initContainers:
- name: db-migrate
  image: myapp:v1.0
  command: ['./migrate', '--check']
  env:
  - name: DB_PASSWORD
    value: "wrongpassword"   # Incorrect credentials
```

**Cause 3: Init container image pull failure**
```yaml
initContainers:
- name: init
  image: private-registry.example.com/init-tool:v1.0  # No imagePullSecret configured
```

**Cause 4: Service doesn't exist yet (timing issue)**
```yaml
# Init container waits for a service that is created by the same Helm release
# and hasn't been created yet when the pod starts
```

## Diagnostic Commands
```bash
# Check pod state
kubectl get pod <pod-name> -n <namespace>

# Describe the pod for detailed init container status
kubectl describe pod <pod-name> -n <namespace> | grep -A30 "Init Containers:"

# View init container logs
kubectl logs <pod-name> -n <namespace> -c <init-container-name>

# View previous attempt logs (if in CrashLoopBackOff)
kubectl logs <pod-name> -n <namespace> -c <init-container-name> --previous

# Test DNS resolution from a debug pod
kubectl run debug --image=busybox --rm -it -- nslookup <service-name>.<namespace>.svc.cluster.local

# Test connectivity to the database service
kubectl run debug --image=nicolaka/netshoot --rm -it -- \
  nc -zv <service-name>.<namespace>.svc.cluster.local 5432

# Check if the target service exists
kubectl get svc -n <target-namespace> | grep <service-name>

# Check the service endpoint
kubectl get endpoints <service-name> -n <namespace>
```

## Resolution
**Fix for wrong hostname**:

Step 1: Identify the actual Service name and namespace:
```bash
kubectl get svc -A | grep postgres
# Output: database   postgres-svc   ClusterIP   10.96.100.5   <none>   5432/TCP
```

Step 2: Update the init container command with the correct FQDN:
```yaml
initContainers:
- name: wait-for-db
  image: busybox:1.35
  command:
  - sh
  - -c
  - |
    until nc -zv postgres-svc.database.svc.cluster.local 5432; do
      echo "Waiting for database..."
      sleep 3
    done
    echo "Database is ready!"
```

Step 3: Apply the fix:
```bash
kubectl apply -f deployment.yaml
kubectl rollout status deployment/<name> -n <namespace>
```

**Fix for wrong credentials**:
```bash
# Verify the secret exists and has correct data
kubectl get secret db-credentials -n <namespace> -o jsonpath='{.data.password}' | base64 -d

# Update the secret if wrong
kubectl create secret generic db-credentials \
  --from-literal=password=<correct-password> \
  -n <namespace> \
  --dry-run=client -o yaml | kubectl apply -f -

# Trigger pod restart to pick up new secret
kubectl rollout restart deployment/<name> -n <namespace>
```

**Fix for image pull failure in init container**:
```yaml
spec:
  imagePullSecrets:
  - name: registry-credentials  # Add to pod spec
  initContainers:
  - name: init
    image: private-registry.example.com/init-tool:v1.0
```

**General emergency workaround — exec into pod to debug**:
```bash
# If you need to bypass the init container temporarily for debugging
# There is no direct way to skip init containers
# Instead, temporarily remove initContainers from the spec
kubectl patch deployment <name> -n <namespace> --type=json \
  -p='[{"op":"remove","path":"/spec/template/spec/initContainers"}]'
```

## Workaround
Replace strict init container checks with application-level retry logic and use readiness probes to gate traffic. The app can start even if the DB is not ready, and simply retry connections. This avoids the init container failure loop but requires the application to handle startup retries.

## Prevention
- Always test init container commands locally or in a debug pod before deploying
- Use FQDNs in init containers: `<service>.<namespace>.svc.cluster.local`
- Add `timeoutSeconds` to init container wait loops to avoid infinite hangs
- Use standard wait-for-it tools: `wait-for-it.sh` or `dockerize` with timeout flags
- Verify that target services exist before deploying dependent workloads (deployment ordering)

## References
- Init containers: https://kubernetes.io/docs/concepts/workloads/pods/init-containers/
- wait-for-it.sh: https://github.com/vishnubob/wait-for-it
- Init container patterns: https://kubernetes.io/docs/tasks/configure-pod-container/configure-pod-initialization/

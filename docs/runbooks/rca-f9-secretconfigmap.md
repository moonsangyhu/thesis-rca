# Runbook: F9 - Secret/ConfigMap Missing or Misconfigured Root Cause Analysis

## Trigger Conditions
Use this runbook when pods fail to start with `CreateContainerConfigError`, when applications log configuration errors at startup, when pods crash with exit code 1 due to missing environment variables, or when secret rotation causes service disruption.

## Severity
**High** — Missing or wrong config/secrets cause immediate pod failure or silent misconfiguration (e.g., wrong database password causes auth failures in app logic).

## Estimated Resolution Time
15-30 minutes

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- Access to Kubernetes Secrets (RBAC: `get/list secrets`)
- GitOps repo (for FluxCD-managed secrets/configmaps)
- External secret manager access if applicable (Vault, AWS Secrets Manager)

## Investigation Steps

### Step 1: Identify the configuration error
```bash
# Find pods in CreateContainerConfigError
kubectl get pods -A | grep -E 'CreateContainer|ContainerConfig|Error'

# Describe the pod for detailed error
kubectl describe pod <pod-name> -n <namespace>
```

Look for events like:
```
Error: couldn't find key DATABASE_URL in ConfigMap default/app-config
Error: secret "db-credentials" not found
Error: configmap "app-settings" not found
```

### Step 2: Check referenced ConfigMaps and Secrets exist
```bash
# List all configmaps in the namespace
kubectl get configmap -n <namespace>

# List all secrets in the namespace (names only — not values)
kubectl get secrets -n <namespace>

# Get all volume and env references from the pod spec
kubectl get pod <pod-name> -n <namespace> -o json | \
  jq '{
    envFrom: [.spec.containers[].envFrom[]? | {type: (if .configMapRef then "configmap" else "secret" end), name: (.configMapRef.name // .secretRef.name)}],
    volumes: [.spec.volumes[]? | {name: .name, source: (.configMap.name // .secret.secretName // "other")}]
  }'

# Compare with what actually exists
```

### Step 3: Validate ConfigMap contents
```bash
# View ConfigMap data
kubectl get configmap <cm-name> -n <namespace> -o yaml

# Check a specific key exists
kubectl get configmap <cm-name> -n <namespace> -o jsonpath='{.data.<key-name>}'

# List all keys in a ConfigMap
kubectl get configmap <cm-name> -n <namespace> -o json | jq '.data | keys'

# Check if key casing is correct (UPPER_CASE vs lower-case)
kubectl get configmap <cm-name> -n <namespace> -o json | jq '.data'
```

### Step 4: Validate Secret contents
```bash
# Check secret exists and has the right keys
kubectl get secret <secret-name> -n <namespace> -o json | jq '.data | keys'

# Decode a specific secret value (base64)
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.<key-name>}' | base64 -d
echo  # Add newline

# Check secret type
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.type}'

# Decode all values in a secret (for debugging — avoid in production)
kubectl get secret <secret-name> -n <namespace> -o json | \
  jq '.data | with_entries(.value |= @base64d)'
```

### Step 5: Check volume mounts
```bash
# Get volume mount paths
kubectl get pod <pod-name> -n <namespace> -o json | \
  jq '.spec.containers[].volumeMounts[] | {name: .name, mountPath: .mountPath, readOnly: .readOnly}'

# Exec into pod (if it starts long enough) to check
kubectl exec <pod-name> -n <namespace> -- ls -la /etc/config/
kubectl exec <pod-name> -n <namespace> -- cat /etc/config/<key-file>

# Check if the file has correct content
kubectl exec <pod-name> -n <namespace> -- env | grep <EXPECTED_VAR>
```

### Step 6: Check environment variable injection
```bash
# Verify env vars from secrets/configmaps are injected
kubectl exec <pod-name> -n <namespace> -- env | sort

# Check for empty values (misconfigured key reference)
kubectl get pod <pod-name> -n <namespace> -o json | \
  jq '.spec.containers[].env[] | select(.valueFrom != null) | 
      {name: .name, 
       from: (.valueFrom.secretKeyRef.name // .valueFrom.configMapKeyRef.name),
       key: (.valueFrom.secretKeyRef.key // .valueFrom.configMapKeyRef.key)}'
```

### Step 7: Check FluxCD/ArgoCD secret management
```bash
# Check if secrets are managed by FluxCD (Sealed Secrets, SOPS, etc.)
kubectl get sealedsecrets -n <namespace> 2>/dev/null
kubectl get externalsecrets -n <namespace> 2>/dev/null

# Check FluxCD kustomization events
kubectl get events -n flux-system --sort-by='.lastTimestamp' | grep -i secret

# Check if FluxCD decryption is working
flux get kustomizations -A
kubectl logs -n flux-system deployment/kustomize-controller | grep -i 'decrypt\|secret\|error'
```

## Resolution

### Fix A: Create missing ConfigMap
```bash
# From literal values
kubectl create configmap <cm-name> \
  --from-literal=DATABASE_HOST=postgres-service \
  --from-literal=DATABASE_PORT=5432 \
  --from-literal=LOG_LEVEL=info \
  -n <namespace>

# From a file
kubectl create configmap <cm-name> \
  --from-file=config.yaml=./config.yaml \
  -n <namespace>

# From env file
kubectl create configmap <cm-name> \
  --from-env-file=.env \
  -n <namespace>
```

### Fix B: Create missing Secret
```bash
# Generic secret from literals
kubectl create secret generic <secret-name> \
  --from-literal=DATABASE_PASSWORD='<password>' \
  --from-literal=API_KEY='<api-key>' \
  -n <namespace>

# From file
kubectl create secret generic <secret-name> \
  --from-file=tls.crt=./cert.pem \
  --from-file=tls.key=./key.pem \
  -n <namespace>

# TLS secret
kubectl create secret tls <tls-secret-name> \
  --cert=./cert.pem \
  --key=./key.pem \
  -n <namespace>
```

### Fix C: Update existing ConfigMap/Secret
```bash
# Edit ConfigMap directly
kubectl edit configmap <cm-name> -n <namespace>

# Patch specific key in ConfigMap
kubectl patch configmap <cm-name> -n <namespace> \
  --type merge \
  -p '{"data": {"DATABASE_HOST": "new-postgres-service"}}'

# Update Secret (values must be base64 encoded)
NEW_VALUE=$(echo -n "new-password" | base64)
kubectl patch secret <secret-name> -n <namespace> \
  --type merge \
  -p "{\"data\": {\"DATABASE_PASSWORD\": \"$NEW_VALUE\"}}"
```

### Fix D: Trigger pod restart to pick up new config
```bash
# ConfigMap/Secret changes don't auto-restart pods (unless configured)
kubectl rollout restart deployment/<deployment-name> -n <namespace>

# Verify restart triggered
kubectl rollout status deployment/<deployment-name> -n <namespace>
```

### Fix E: Propagate config to the right namespace (cross-namespace copy)
```bash
# Copy secret from one namespace to another
kubectl get secret <secret-name> -n source-namespace -o json | \
  jq 'del(.metadata.namespace, .metadata.resourceVersion, .metadata.uid, .metadata.creationTimestamp)' | \
  kubectl apply -n <target-namespace> -f -
```

### Fix F: Hot-reload config without restart (if app supports it)
```bash
# Send SIGHUP to process in container (if app listens for SIGHUP)
kubectl exec <pod-name> -n <namespace> -- kill -HUP 1

# Or use the app-specific reload endpoint
kubectl exec <pod-name> -n <namespace> -- \
  curl -X POST http://localhost:<port>/reload
```

## Verification
```bash
# Pod should now be in Running state
kubectl get pods -n <namespace> -w

# Verify env var is injected correctly
kubectl exec <pod-name> -n <namespace> -- env | grep <EXPECTED_VAR>

# Verify config file is mounted correctly
kubectl exec <pod-name> -n <namespace> -- cat /etc/config/<file>

# Application health check
kubectl exec <pod-name> -n <namespace> -- \
  curl -s http://localhost:<port>/healthz

# No configuration errors in logs
kubectl logs <pod-name> -n <namespace> | grep -v -i 'config\|error'
```

## Escalation
- If secrets are managed by Vault/External Secrets Operator and not syncing: check `ExternalSecret` CRD status and Vault token rotation
- If SOPS decryption fails in FluxCD: check age/GPG key availability in kustomize-controller
- If secret rotation causes cascading failures: coordinate with dev team for graceful rotation procedure

## Loki Queries

```logql
# Configuration-related startup errors
{namespace="<namespace>"} |= "configuration" |= "error" or |= "failed to load config"

# Missing environment variable errors
{namespace="<namespace>"} |= "environment variable" or |= "required env" or |= "not set"

# Connection failures from wrong credentials
{namespace="<namespace>"} |= "authentication failed" or |= "invalid credentials" or |= "permission denied"

# Kubernetes secret mount errors
{job="kubernetes-events", namespace="<namespace>"} |= "MountVolume.SetUp failed"

# General startup configuration failures
{namespace="<namespace>", container="<container>"} 
  | json | level="error" | line_format "{{.message}}"
```

## Prometheus Queries

```promql
# Pods in CreateContainerConfigError (Waiting)
kube_pod_container_status_waiting_reason{reason="CreateContainerConfigError", namespace="<namespace>"}

# Pods not ready (may be stuck on config validation)
kube_pod_status_ready{namespace="<namespace>", condition="false"}

# Container restart rate (config errors cause crash loops)
rate(kube_pod_container_status_restarts_total{namespace="<namespace>"}[15m])

# Deployment unavailable replicas
kube_deployment_status_replicas_unavailable{namespace="<namespace>"}
```

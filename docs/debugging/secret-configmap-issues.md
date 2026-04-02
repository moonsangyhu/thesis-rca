# Debugging Secret and ConfigMap Issues

## Overview
Secrets and ConfigMaps are the primary mechanisms for injecting configuration into pods. Issues range from missing resources, wrong keys, encoding problems, to stale mounted data. These often manifest as application startup failures or runtime configuration errors.

## Symptoms
- Pod stuck in `CreateContainerConfigError` status
- Events: `Error: configmap "X" not found` or `Error: secret "X" not found`
- Events: `couldn't find key Y in ConfigMap/Secret`
- Application logs showing missing or empty configuration values
- Application behavior not changing after ConfigMap/Secret update

## Diagnostic Commands

```bash
# Check pod events for config-related errors
kubectl describe pod <pod> -n <ns> | grep -A5 "Events"

# Verify ConfigMap exists and has expected keys
kubectl get configmap <name> -n <ns> -o yaml

# Verify Secret exists and decode values
kubectl get secret <name> -n <ns> -o jsonpath='{.data}' | python3 -m json.tool
kubectl get secret <name> -n <ns> -o jsonpath='{.data.password}' | base64 -d

# Check what env vars are injected
kubectl exec <pod> -n <ns> -- env | sort

# Check mounted volume contents
kubectl exec <pod> -n <ns> -- ls -la /etc/config/
kubectl exec <pod> -n <ns> -- cat /etc/config/application.yaml

# Check if ConfigMap/Secret is referenced correctly in pod spec
kubectl get pod <pod> -n <ns> -o yaml | grep -A10 "configMapRef\|secretRef\|configMap\|secret"
```

## Common Causes

### 1. ConfigMap/Secret does not exist in namespace
Resource referenced by pod is missing. Must be in the same namespace.
```bash
kubectl get configmap,secret -n <ns>
# Cross-namespace references are NOT supported for env/volume mounts
```

### 2. Wrong key name
ConfigMap has key `config.yaml` but pod references `config.yml`.
```bash
kubectl get configmap <name> -n <ns> -o jsonpath='{.data}' | python3 -c "import sys,json; print('\n'.join(json.load(sys.stdin).keys()))"
```

### 3. Base64 encoding issues (Secrets)
Double-encoded or wrong encoding. `stringData` vs `data` confusion.
```bash
# data: requires base64-encoded values
# stringData: accepts plain text (auto-encoded on create)
echo -n "password123" | base64  # correct: no newline (-n flag)
echo "password123" | base64     # WRONG: includes trailing newline
```

### 4. Env var injection with wrong reference type
Using `configMapKeyRef` when it should be `secretKeyRef`, or vice versa.
```yaml
env:
- name: DB_PASSWORD
  valueFrom:
    secretKeyRef:       # not configMapKeyRef
      name: db-credentials
      key: password
```

### 5. Volume-mounted ConfigMap not updating
When ConfigMap is mounted as a volume, kubelet updates it within ~60s. But:
- **subPath mounts do NOT auto-update** (kubelet limitation)
- Env vars from ConfigMap NEVER auto-update (requires pod restart)
- Immutable ConfigMaps/Secrets cannot be updated at all

### 6. Optional reference not set
If a ConfigMap/Secret may not exist, set `optional: true`:
```yaml
envFrom:
- configMapRef:
    name: optional-config
    optional: true
```

## Resolution Steps

### Missing ConfigMap/Secret
```bash
# Create the missing resource
kubectl create configmap app-config -n boutique --from-file=config.yaml
kubectl create secret generic db-creds -n boutique --from-literal=password=mypass

# Or apply from Git (FluxCD)
kubectl annotate kustomization monitoring -n flux-system \
  reconcile.fluxcd.io/requestedAt="$(date -u +%Y-%m-%dT%H:%M:%SZ)" --overwrite
```

### Wrong key
Fix the pod spec or rename the key in the ConfigMap/Secret.

### Force pod to pick up changes
```bash
# For env-based injection: restart the pod
kubectl rollout restart deployment <name> -n <ns>

# For volume mounts (non-subPath): wait ~60s or check
kubectl exec <pod> -n <ns> -- cat /etc/config/config.yaml
```

## Prevention
- Use `optional: false` (default) to fail fast on missing configs
- Validate ConfigMap/Secret existence in CI/CD before deployment
- Prefer volume mounts over env vars for configs that may change
- Avoid subPath if you need auto-update capability
- Use Kustomize configMapGenerator with hash suffix for immutable rolling updates
- Store sensitive values in Sealed Secrets or external secret managers

## Related Issues
- [Init Container Failure](../known-issues/init-container-failure.md)
- [Secret Rotation](../known-issues/secret-rotation.md)

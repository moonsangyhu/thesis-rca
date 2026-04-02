# Known Issue: Kustomize Strategic Merge Patch Conflicts

## Issue ID
KI-022

## Affected Components
- FluxCD Kustomize Controller
- Kustomize (kustomize.io)
- Multiple Kustomization overlays patching the same resources
- HelmRelease post-renderer kustomize patches

## Symptoms
- FluxCD Kustomization shows `False` with message about conflict:
  ```
  kustomize build failed: strategic merge patch of object failed: ...
  ```
- `kustomize build` locally fails with merge error
- The final applied resource has incorrect values (one patch overwrites another)
- Resources are applied from one kustomization but not another
- Unexpected field values in deployed resources despite correct patch files
- `kubectl diff` shows fields toggling between values on consecutive reconcile cycles

## Root Cause
Kustomize's strategic merge patch (SMP) follows specific rules for merging list fields that differ from JSON Merge Patch (RFC 7396). When two patches modify the same field, the behavior depends on the field type:

**Scalar fields** (string, integer, boolean): Last writer wins — the patch applied last overwrites earlier patches with no error or warning.

**List fields without merge keys**: The entire list is replaced by the last patch. A patch adding one container to `spec.containers` will replace the entire containers array from a previous patch.

**List fields with merge keys** (e.g., `spec.containers` uses `name` as merge key): Patches are merged by the merge key. Two patches for containers with different names both take effect. But two patches for the same container name conflict on shared fields.

Common conflict scenarios in this project:

**Scenario 1: Two overlays both set `replicas`**
```yaml
# overlay-dev/patch.yaml
spec:
  replicas: 1
---
# overlay-prod/patch.yaml
spec:
  replicas: 3
```
When both are composed, the result is unpredictable.

**Scenario 2: Multiple patches on the same container's env vars**
```yaml
# base-patch.yaml — sets env DATABASE_URL
spec:
  template:
    spec:
      containers:
      - name: app
        env:
        - name: DATABASE_URL
          value: postgres://base

# overlay-patch.yaml — also sets env, accidentally replacing entire env list
spec:
  template:
    spec:
      containers:
      - name: app
        env:
        - name: LOG_LEVEL
          value: debug
        # DATABASE_URL from base-patch is now missing!
```

## Diagnostic Commands
```bash
# Test kustomize build locally
kustomize build ./overlays/production/ 2>&1

# Or with kubectl
kubectl kustomize ./overlays/production/ 2>&1

# Check FluxCD kustomization errors
kubectl get kustomization -A
kubectl describe kustomization <name> -n flux-system | grep -A20 "Status:"

# Check Flux controller logs
kubectl -n flux-system logs deployment/kustomize-controller --tail=100 | grep -i "error\|conflict\|patch"

# Compare the result of different build paths
kustomize build overlays/dev/ > /tmp/dev.yaml
kustomize build overlays/prod/ > /tmp/prod.yaml
diff /tmp/dev.yaml /tmp/prod.yaml

# Check what patches are being applied
kustomize build --load-restrictor=LoadRestrictionsNone overlays/prod/ | grep -A5 "replicas"

# View the kustomization file
cat overlays/production/kustomization.yaml
```

## Resolution
**Option A: Use JSON patch for precise targeting (eliminates ambiguity)**

JSON patch (`patchesJson6902`) targets a specific field by path, avoiding unintended field replacement:
```yaml
# kustomization.yaml
patches:
- target:
    kind: Deployment
    name: frontend
  patch: |
    - op: replace
      path: /spec/replicas
      value: 3
    - op: replace
      path: /spec/template/spec/containers/0/env/0/value
      value: "debug"
```

JSON patch is unambiguous: it either succeeds or fails with a clear error.

**Option B: Consolidate conflicting patches into a single patch file**
```yaml
# Combined patch (no conflict possible)
apiVersion: apps/v1
kind: Deployment
metadata:
  name: frontend
spec:
  replicas: 3
  template:
    spec:
      containers:
      - name: app
        env:
        - name: DATABASE_URL
          value: postgres://prod-db
        - name: LOG_LEVEL
          value: info
```

**Option C: Use `replacements` for cross-resource value propagation**
When the same value needs to appear in multiple places, use Kustomize `replacements` instead of multiple patches:
```yaml
# kustomization.yaml
replacements:
- source:
    kind: ConfigMap
    name: env-config
    fieldPath: data.replicaCount
  targets:
  - select:
      kind: Deployment
    fieldPaths:
    - spec.replicas
```

**Option D: Use HelmRelease post-renderer carefully**
For HelmRelease with kustomize post-renderer, ensure patches don't conflict with chart-generated values:
```yaml
spec:
  postRenderers:
  - kustomize:
      patches:
      - target:
          kind: Deployment
          name: frontend
        patch: |
          - op: add
            path: /spec/template/metadata/annotations/checksum
            value: "abc123"
```

## Workaround
Temporarily disable the conflicting kustomization by suspending it:
```bash
flux suspend kustomization <conflicting-kustomization> -n flux-system
```
Then fix the patch conflict and resume.

## Prevention
- Always use JSON patch (`op: replace/add/remove`) for modifying specific scalar fields
- Only use strategic merge patch for adding new items to lists (containers, volumes, env vars)
- Run `kustomize build` locally and inspect the full YAML output before committing
- Add `kustomize build` as a CI/CD check on pull requests touching `kustomization.yaml` files
- Structure overlays to minimize overlap: each overlay should own distinct aspects of the configuration

## References
- Kustomize patches documentation: https://kubectl.docs.kubernetes.io/references/kustomize/kustomization/patches/
- JSON patch specification: https://jsonpatch.com/
- Strategic merge patch: https://github.com/kubernetes/community/blob/master/contributors/devel/sig-api-machinery/strategic-merge-patch.md
- FluxCD Kustomize: https://fluxcd.io/flux/components/kustomize/kustomizations/

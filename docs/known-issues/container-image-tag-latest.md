# Known Issue: Using `latest` Image Tag Causes Unexpected Updates and Rate Limits

## Issue ID
KI-007

## Affected Components
- All workloads using `image: <name>:latest` or no explicit tag
- Container runtime (containerd)
- Image registry (Docker Hub, ECR, GCR, etc.)
- Deployment rollout behavior

## Symptoms
- Pod restarts with `ErrImagePull` or `ImagePullBackOff` during peak hours (Docker Hub rate limit hit)
- Unexpected application version changes after node restart or pod rescheduling
- Pods on different nodes running different versions of the same image
- `kubectl describe pod` shows `imagePullPolicy: Always` even when not explicitly set
- Application behavior inconsistency across replicas
- `kubectl rollout history` shows no meaningful diff between deployments
- CI/CD pipeline image pulls fail intermittently with HTTP 429

## Root Cause
When a container image tag is `latest` (or no tag is specified, which defaults to `latest`), Kubernetes sets `imagePullPolicy: Always` by default. This means every pod start — including restarts, node rescheduling, and scaling events — triggers a fresh pull from the registry.

This causes two categories of problems:

**1. Unexpected updates**: If the registry has a newer `latest` image, pods started at different times may run different image versions. This violates reproducibility and can cause split-brain scenarios where some replicas run v1.2 and others run v1.3 of the same service.

**2. Registry rate limits**: Docker Hub imposes pull rate limits (100 pulls/6h for anonymous, 200 for free accounts). With `imagePullPolicy: Always` across many pods and nodes, pull limits are quickly exhausted, causing `ImagePullBackOff` for all pods cluster-wide.

From the Kubernetes documentation: if the tag is `latest` or omitted, `imagePullPolicy` defaults to `Always`. For any other tag, it defaults to `IfNotPresent`.

## Diagnostic Commands
```bash
# Find all pods using latest tag or Always pull policy
kubectl get pods -A -o jsonpath='{range .items[*]}{.metadata.namespace}{"\t"}{.metadata.name}{"\t"}{range .spec.containers[*]}{.image}{"\t"}{.imagePullPolicy}{"\n"}{end}{end}' | grep -E "latest|Always"

# Check for ImagePullBackOff
kubectl get pods -A | grep -i "imagepull\|backoff"

# Describe a failing pod
kubectl describe pod <pod-name> -n <namespace> | grep -A10 "Events:"

# Check Docker Hub rate limit (run from a node)
TOKEN=$(curl -s "https://auth.docker.io/token?service=registry.docker.io&scope=repository:ratelimitpreview/test:pull" | jq -r .token)
curl -s --head -H "Authorization: Bearer $TOKEN" https://registry-1.docker.io/v2/ratelimitpreview/test/manifests/latest | grep -i ratelimit

# Check imagePullPolicy on deployments
kubectl get deployments -A -o yaml | grep -B5 "imagePullPolicy: Always"
```

## Resolution
**Step 1**: Replace `latest` tags with specific, immutable tags in all manifests:
```yaml
# Before (problematic)
spec:
  containers:
  - name: frontend
    image: gcr.io/google-samples/microservices-demo/frontend:latest

# After (correct)
spec:
  containers:
  - name: frontend
    image: gcr.io/google-samples/microservices-demo/frontend:v0.10.1
    imagePullPolicy: IfNotPresent
```

**Step 2**: For GitOps workflows, use image automation (Flux Image Automation Controller) to update tags automatically via Git PRs rather than relying on `latest`:
```yaml
# flux image policy
apiVersion: image.toolkit.fluxcd.io/v1beta2
kind: ImagePolicy
metadata:
  name: frontend
spec:
  imageRepositoryRef:
    name: frontend
  policy:
    semver:
      range: ">=0.10.0"
```

**Step 3**: Configure Docker Hub credentials to increase rate limits:
```bash
kubectl create secret docker-registry dockerhub-creds \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username=<user> \
  --docker-password=<token> \
  -n default

# Add to service account
kubectl patch serviceaccount default \
  -p '{"imagePullSecrets": [{"name": "dockerhub-creds"}]}'
```

## Workaround
If you must use `latest` temporarily, explicitly set `imagePullPolicy: IfNotPresent` to at least prevent repeat pulls on every pod start (note: this means updates to `latest` won't be picked up without manual image deletion from nodes).

## Prevention
- Enforce immutable image tags via OPA/Kyverno policy:
  ```yaml
  # Kyverno policy to deny latest tag
  spec:
    rules:
    - name: deny-latest-tag
      match:
        resources:
          kinds: [Pod]
      validate:
        message: "Using latest tag is not allowed"
        pattern:
          spec:
            containers:
            - image: "!*:latest"
  ```
- Use SHA-pinned image references for maximum reproducibility: `image: nginx@sha256:abc123...`
- Set up an internal image registry mirror to avoid Docker Hub rate limits

## References
- K8s image pull policy: https://kubernetes.io/docs/concepts/containers/images/#image-pull-policy
- Docker Hub rate limits: https://docs.docker.com/docker-hub/download-rate-limit/
- Flux image automation: https://fluxcd.io/flux/guides/image-update/
- Kyverno best practices: https://kyverno.io/policies/best-practices/disallow-latest-tag/

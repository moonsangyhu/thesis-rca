# Pod ImagePullBackOff Diagnosis

## Overview
ImagePullBackOff (and its precursor ErrImagePull) occurs when Kubernetes cannot pull the container image from the registry. The kubelet attempts to pull the image and upon failure, enters a backoff state with increasing retry intervals. This can be caused by authentication failures, incorrect image names or tags, network connectivity issues, or registry unavailability.

## Symptoms
- `kubectl get pods` shows STATUS `ImagePullBackOff` or `ErrImagePull`
- Pod never reaches Running state
- `kubectl describe pod` shows events like `Failed to pull image`, `unauthorized`, `not found`
- Containers show `Waiting` state with reason `ImagePullBackOff`
- High frequency initially (`ErrImagePull`), then slower retries (`ImagePullBackOff`)

## Diagnostic Commands

```bash
# Step 1: Identify pods with image pull issues
kubectl get pods -n <namespace> | grep -E "ImagePull|ErrImage"
kubectl get pods -A | grep -E "ImagePull|ErrImage"

# Step 2: Get detailed error message
kubectl describe pod <pod-name> -n <namespace>
# Look for Events section - specific error messages:
#   "Failed to pull image": general pull failure
#   "unauthorized": authentication failure
#   "not found" or "manifest unknown": wrong image name or tag
#   "connection refused" or "timeout": network/registry issue
#   "toomanyrequests": Docker Hub rate limit

# Step 3: Check the exact image being pulled
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].image}'
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.initContainers[*].image}'

# Step 4: Check imagePullSecrets on the pod
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.imagePullSecrets}'

# Step 5: Check imagePullSecrets on the service account
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.serviceAccountName}'
SA=$(kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.serviceAccountName}')
kubectl get serviceaccount $SA -n <namespace> -o jsonpath='{.imagePullSecrets}'

# Step 6: Verify the secret exists and is of correct type
kubectl get secret -n <namespace> | grep dockerconfigjson
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.type}'
# Should be: kubernetes.io/dockerconfigjson

# Step 7: Decode and inspect the dockerconfig secret
kubectl get secret <secret-name> -n <namespace> -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | python3 -m json.tool

# Step 8: Check kubelet logs on the node for detailed errors
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.nodeName}'
# On the node: journalctl -u kubelet -f | grep <pod-name>

# Step 9: Test image pull manually from within the cluster
kubectl run test-pull -n <namespace> --image=<image-name> --restart=Never -- sleep 3600
kubectl describe pod test-pull -n <namespace>
kubectl delete pod test-pull -n <namespace>

# Step 10: Check if image exists in registry
# For Docker Hub:
curl -s https://hub.docker.com/v2/repositories/<org>/<image>/tags/<tag>/ | python3 -m json.tool

# Step 11: Check if image tag is correct (most common mistake)
# List available tags (Docker Hub example):
curl -s "https://registry.hub.docker.com/v2/repositories/<org>/<image>/tags/?page_size=20" | python3 -m json.tool | grep name

# Step 12: Check node's container runtime configuration
# On node: cat /etc/containerd/config.toml | grep -A5 registry

# Step 13: For Online Boutique - verify all image tags
kubectl get pods -n online-boutique -o jsonpath='{range .items[*]}{.metadata.name}{"\t"}{.spec.containers[0].image}{"\n"}{end}'

# Step 14: Check if it's a Docker Hub rate limit issue
kubectl describe pod <pod-name> -n <namespace> | grep -i "toomanyrequests\|rate limit"
```

## Common Causes

1. **Wrong image tag**: The specified tag does not exist in the registry. Common after a typo or when using a tag that was never pushed (e.g., `latest` when only versioned tags exist).

2. **Wrong image name**: Repository or image name is misspelled or the full registry URL is missing for private registries.

3. **Missing imagePullSecret**: Private registry requires authentication but no pull secret is configured on the pod or service account.

4. **Expired or invalid credentials**: The dockerconfig secret has expired credentials. Common when registry tokens have short TTL.

5. **Secret in wrong namespace**: The imagePullSecret exists in a different namespace. Secrets are namespace-scoped and cannot be referenced across namespaces.

6. **Docker Hub rate limiting**: Anonymous pulls are limited to 100/6h per IP. Authenticated free-tier is 200/6h. CI environments hitting this frequently.

7. **Registry unreachable**: Private registry is down, has network issues, or DNS cannot resolve the registry hostname.

8. **Wrong secret type**: Secret exists but is of type `Opaque` instead of `kubernetes.io/dockerconfigjson`.

9. **Malformed dockerconfig**: The `.dockerconfigjson` field has invalid JSON or incorrect base64 encoding.

10. **Image digest mismatch**: Image was specified by digest but the digest no longer exists (deleted from registry).

## Resolution Steps

### Step 1: Fix wrong image name or tag
```bash
# Update the image in the deployment
kubectl set image deployment/<deployment-name> \
  <container-name>=<correct-registry>/<image>:<correct-tag> \
  -n <namespace>

# Or edit deployment directly
kubectl edit deployment <deployment-name> -n <namespace>
```

### Step 2: Create imagePullSecret for private registry
```bash
# Create secret from Docker credentials
kubectl create secret docker-registry <secret-name> \
  --docker-server=<registry-server> \
  --docker-username=<username> \
  --docker-password=<password> \
  --docker-email=<email> \
  -n <namespace>

# Create secret from existing docker config file
kubectl create secret generic <secret-name> \
  --from-file=.dockerconfigjson=$HOME/.docker/config.json \
  --type=kubernetes.io/dockerconfigjson \
  -n <namespace>

# For AWS ECR
AWS_ACCOUNT=123456789
AWS_REGION=us-east-1
TOKEN=$(aws ecr get-login-password --region $AWS_REGION)
kubectl create secret docker-registry ecr-secret \
  --docker-server=${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com \
  --docker-username=AWS \
  --docker-password=$TOKEN \
  -n <namespace>
```

### Step 3: Attach imagePullSecret to pod/deployment
```bash
# Patch deployment to add imagePullSecrets
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "add", "path": "/spec/template/spec/imagePullSecrets", "value": [{"name": "<secret-name>"}]}]'

# Or add to service account (affects all pods using that SA)
kubectl patch serviceaccount <sa-name> -n <namespace> \
  -p '{"imagePullSecrets": [{"name": "<secret-name>"}]}'
```

### Step 4: Copy secret from another namespace
```bash
# Secrets cannot be referenced across namespaces - copy them
kubectl get secret <secret-name> -n source-namespace -o yaml | \
  sed 's/namespace: source-namespace/namespace: target-namespace/' | \
  kubectl apply -f -
```

### Step 5: Fix Docker Hub rate limiting
```bash
# Create authenticated pull secret for Docker Hub
kubectl create secret docker-registry dockerhub-secret \
  --docker-server=https://index.docker.io/v1/ \
  --docker-username=<dockerhub-user> \
  --docker-password=<dockerhub-token> \
  -n <namespace>

# Apply to default service account in namespace
kubectl patch serviceaccount default -n <namespace> \
  -p '{"imagePullSecrets": [{"name": "dockerhub-secret"}]}'

# Alternatively, use a mirror registry
# In containerd config: configure registry mirrors
```

### Step 6: Update expired ECR token (ECR tokens expire every 12 hours)
```bash
# Get new token and update secret
TOKEN=$(aws ecr get-login-password --region us-east-1)
kubectl create secret docker-registry ecr-secret \
  --docker-server=${AWS_ACCOUNT}.dkr.ecr.us-east-1.amazonaws.com \
  --docker-username=AWS \
  --docker-password=$TOKEN \
  -n <namespace> \
  --dry-run=client -o yaml | kubectl apply -f -
```

### Step 7: Verify fix
```bash
# Delete the failing pod to force re-pull attempt
kubectl delete pod <pod-name> -n <namespace>
# Watch new pod status
kubectl get pods -n <namespace> -w
```

## Image Pull Secret Verification

```bash
# Verify the secret content is valid JSON
kubectl get secret <secret-name> -n <namespace> \
  -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | python3 -c "import sys,json; json.load(sys.stdin); print('Valid JSON')"

# Check the auth field is correctly base64 encoded user:password
kubectl get secret <secret-name> -n <namespace> \
  -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | \
  python3 -c "import sys,json,base64; d=json.load(sys.stdin); \
  [print(r, base64.b64decode(v['auth']).decode()) for r,v in d.get('auths',{}).items()]"
```

## Prevention
- Use image digest pinning instead of mutable tags in production
- Store imagePullSecrets in external secret management (Vault, AWS Secrets Manager) with auto-rotation
- Use a private registry mirror to avoid Docker Hub rate limits
- Set up registry mirror in containerd configuration at cluster level
- Use ECR/GCR/ACR for cloud-based clusters (no rate limits within same account)
- Validate image names and tags in CI/CD pipeline before deploying
- Use admission webhooks to enforce image pull policy and registry allowlists
- Monitor for `ErrImagePull` events with alerting

## Related Issues
- `secret-configmap-issues.md` - For secret management issues
- `pod-crashloopbackoff.md` - What happens after image pulls successfully
- `gitops-flux-troubleshoot.md` - FluxCD image automation issues

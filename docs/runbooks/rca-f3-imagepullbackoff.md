# Runbook: F3 - ImagePullBackOff Root Cause Analysis

## Trigger Conditions
Use this runbook when pods are stuck in `ImagePullBackOff` or `ErrImagePull` state, or when deployment rollouts stall with image-related errors. Also applies to `ErrImageNeverPull` in air-gapped or offline scenarios.

## Severity
**High** — New pods and rollouts are blocked. Existing pods continue running, but scaling and recovery operations will fail.

## Estimated Resolution Time
10-25 minutes

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- Access to container registry (Harbor, Docker Hub, GCR, ECR, etc.)
- Credentials for `imagePullSecret` if using private registry
- `docker` or `crane` CLI for registry validation (optional)

## Investigation Steps

### Step 1: Confirm the error and get image details
```bash
# Find affected pods
kubectl get pods -A | grep -E 'ImagePull|ErrImage'

# Describe pod to see the exact error message
kubectl describe pod <pod-name> -n <namespace>
```

Look for events like:
```
Failed to pull image "registry.example.com/app:v1.2.3": 
  rpc error: code = Unknown 
  desc = failed to pull and unpack image: ... 
  unauthorized: authentication required
```

```bash
# Get the exact image reference
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].image}'
```

### Step 2: Identify the failure category
```bash
# Check the event message carefully
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | grep -i 'pull\|image'
```

**Common error categories:**
| Error | Meaning |
|-------|---------|
| `unauthorized` / `403` | Authentication failure — bad or missing imagePullSecret |
| `not found` / `404` | Image tag does not exist in registry |
| `connection refused` / `timeout` | Registry unreachable (network/DNS) |
| `TLS` / `certificate` | TLS verification failure |
| `manifest unknown` | Tag exists but manifest is corrupt or wrong arch |

### Step 3: Check imagePullSecret configuration
```bash
# List secrets in namespace
kubectl get secrets -n <namespace> | grep -i 'docker\|registry\|pull'

# Check what secret the pod references
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.imagePullSecrets}'

# Inspect the secret (base64 encoded)
kubectl get secret <pull-secret-name> -n <namespace> -o jsonpath='{.data.\.dockerconfigjson}' | base64 -d | jq .

# Verify the secret contains correct registry URL, username, password
kubectl get secret <pull-secret-name> -n <namespace> -o json | \
  jq '.data | map_values(@base64d)'
```

### Step 4: Verify network connectivity to registry from node
```bash
# Find which node the pod is scheduled on
kubectl get pod <pod-name> -n <namespace> -o wide

# Test connectivity from a debug pod on the same node
kubectl run net-debug --image=busybox -n <namespace> \
  --overrides='{"spec":{"nodeName":"<node-name>"}}' -- sleep 3600
kubectl exec -it net-debug -n <namespace> -- wget -qO- https://<registry-host>/v2/
kubectl delete pod net-debug -n <namespace>

# Or use kubectl debug on the node
kubectl debug node/<node-name> -it --image=busybox
```

### Step 5: Verify the image/tag exists in registry
```bash
# Using crane (if available)
crane ls <registry-host>/<repo>/<image>

# Using curl with credentials
curl -u <user>:<password> \
  https://<registry-host>/v2/<image>/tags/list

# Docker pull test (from a machine with registry access)
docker pull <full-image-reference>
```

### Step 6: Check if image is available on node cache
```bash
# SSH to the node and check crictl
ssh <node-name>
sudo crictl images | grep <image-name>

# Or check via kubectl node debug
kubectl debug node/<node-name> -it --image=busybox -- chroot /host crictl images
```

### Step 7: Check DNS resolution for registry hostname
```bash
# Test DNS from within cluster
kubectl run dns-test --image=busybox -n <namespace> --rm -it -- nslookup <registry-hostname>

# Check CoreDNS is healthy
kubectl get pods -n kube-system -l k8s-app=kube-dns
kubectl logs -n kube-system -l k8s-app=kube-dns | tail -20
```

## Resolution

### Fix A: Create or update imagePullSecret
```bash
# Create new Docker registry secret
kubectl create secret docker-registry <secret-name> \
  --docker-server=<registry-host> \
  --docker-username=<username> \
  --docker-password=<password> \
  --docker-email=<email> \
  -n <namespace>

# Patch service account to auto-mount the secret
kubectl patch serviceaccount default -n <namespace> \
  -p '{"imagePullSecrets": [{"name": "<secret-name>"}]}'

# Or patch deployment directly
kubectl patch deployment <deployment-name> -n <namespace> \
  --type='json' \
  -p='[{"op":"add","path":"/spec/template/spec/imagePullSecrets","value":[{"name":"<secret-name>"}]}]'
```

### Fix B: Fix the image tag (tag does not exist)
```bash
# Update image tag in deployment
kubectl set image deployment/<deployment-name> \
  <container-name>=<registry>/<image>:<correct-tag> \
  -n <namespace>

# Via GitOps — update the tag in HelmRelease values and commit
flux reconcile helmrelease <release-name> -n <namespace>
```

### Fix C: Registry unreachable — use image mirror or cached image
```bash
# Update deployment to use a mirror registry
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op":"replace","path":"/spec/template/spec/containers/0/image","value":"<mirror-registry>/<image>:<tag>"}]'

# Pre-pull image on all nodes (DaemonSet approach)
cat <<EOF | kubectl apply -f -
apiVersion: apps/v1
kind: DaemonSet
metadata:
  name: image-prepull
  namespace: kube-system
spec:
  selector:
    matchLabels:
      app: image-prepull
  template:
    metadata:
      labels:
        app: image-prepull
    spec:
      initContainers:
      - name: pull
        image: <registry>/<image>:<tag>
        command: ['sh', '-c', 'echo pulled']
      containers:
      - name: pause
        image: pause:3.9
EOF
```

### Fix D: TLS certificate issue
```bash
# Add registry to containerd insecure registries (on each node)
# Edit /etc/containerd/config.toml and add:
# [plugins."io.containerd.grpc.v1.cri".registry.configs."<registry-host>".tls]
#   insecure_skip_verify = true

# Or add CA cert to node trust store
sudo cp registry-ca.crt /usr/local/share/ca-certificates/
sudo update-ca-certificates
sudo systemctl restart containerd
```

## Verification
```bash
# Pod should transition from ImagePullBackOff to ContainerCreating then Running
kubectl get pods -n <namespace> -w

# Force a retry by deleting the pod (deployment will recreate)
kubectl delete pod <pod-name> -n <namespace>

# Confirm image is now pulled on the node
kubectl debug node/<node-name> -it --image=busybox -- chroot /host crictl images | grep <image-name>

# Check events are clean
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | tail -10
```

## Escalation
- If registry is completely unreachable cluster-wide: check cluster egress/firewall rules, escalate to infrastructure team
- If credentials are correct but still getting `unauthorized`: registry may have IP whitelist — check with registry admin
- If image architecture mismatch (amd64 vs arm64): rebuild image with correct platform or use multi-arch manifest

## Loki Queries

```logql
# Kubelet image pull errors
{app="kubelet"} |= "Failed to pull image" or |= "ErrImagePull"

# Failed pull events for specific namespace
{job="kubernetes-events", namespace="<namespace>"} |= "ImagePullBackOff" or |= "ErrImagePull"

# Registry authentication failures
{app="kubelet"} |= "unauthorized" or |= "authentication required"

# Node-level containerd pull errors
{job="node-logs"} |= "failed to pull" or |= "reference not found"
```

## Prometheus Queries

```promql
# Pods stuck in ImagePullBackOff (waiting state)
kube_pod_container_status_waiting_reason{reason="ImagePullBackOff", namespace="<namespace>"}

# Pods with ErrImagePull
kube_pod_container_status_waiting_reason{reason="ErrImagePull", namespace="<namespace>"}

# All non-running pod containers by reason
count by (reason) (kube_pod_container_status_waiting_reason{namespace="<namespace>"})

# Pods not scheduled (may indicate image pull blocking rollout)
kube_deployment_status_replicas_unavailable{namespace="<namespace>"}
```

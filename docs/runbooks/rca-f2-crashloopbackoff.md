# Runbook: F2 - CrashLoopBackOff Root Cause Analysis

## Trigger Conditions
Use this runbook when pods are in `CrashLoopBackOff` state, containers are repeatedly restarting (restartCount > 3), or alerts fire for `KubePodCrashLooping`. Also applicable when a pod shows `Error` state between restarts.

## Severity
**Critical** — CrashLoopBackOff with exponential backoff means the service is unavailable for increasingly long periods. Downstream services will accumulate errors.

## Estimated Resolution Time
20-45 minutes (depending on root cause: config error vs application bug)

## Prerequisites
- `kubectl` with KUBECONFIG set to `~/.kube/config-k8s-lab`
- Loki/Grafana for log analysis
- Access to ConfigMaps and Secrets in the namespace
- GitOps repo access for configuration changes

## Investigation Steps

### Step 1: Confirm CrashLoopBackOff and get pod details
```bash
# Find all crashing pods
kubectl get pods -A | grep -E 'CrashLoop|Error'

# Get detailed pod status
kubectl describe pod <pod-name> -n <namespace>
```

### Step 2: Decode the exit code
```bash
# Get the last exit code
kubectl get pod <pod-name> -n <namespace> -o json | \
  jq '.status.containerStatuses[] | {name: .name, exitCode: .lastState.terminated.exitCode, reason: .lastState.terminated.reason, restartCount: .restartCount}'
```

**Exit Code Reference:**
| Exit Code | Meaning | Likely Cause |
|-----------|---------|--------------|
| 0 | Success (unexpected exit) | Main process completed — no daemon mode, wrong entrypoint |
| 1 | Application error | App startup failure, unhandled exception |
| 2 | Misuse of shell builtin | Script error, bash syntax |
| 137 | SIGKILL (128+9) | OOMKill or manual kill — check memory limits |
| 139 | Segfault (128+11) | Memory corruption, native code bug |
| 143 | SIGTERM (128+15) | Graceful shutdown requested — liveness probe timeout, preStop hook issue |
| 255 | Exit(-1) | Java/Go app fatal error |

### Step 3: Extract crash logs
```bash
# Current container logs (if still running briefly)
kubectl logs <pod-name> -n <namespace> -c <container-name>

# Previous container instance logs (most useful for CrashLoop)
kubectl logs <pod-name> -n <namespace> -c <container-name> --previous

# Follow logs to catch the crash moment
kubectl logs <pod-name> -n <namespace> -c <container-name> -f

# Get logs with timestamps
kubectl logs <pod-name> -n <namespace> --previous --timestamps=true | tail -50
```

### Step 4: Check for configuration errors
```bash
# Inspect environment variables
kubectl exec <pod-name> -n <namespace> -- env 2>/dev/null || \
  kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].env}'

# Check mounted ConfigMaps
kubectl get pod <pod-name> -n <namespace> -o json | jq '.spec.volumes'
kubectl get configmap <cm-name> -n <namespace> -o yaml

# Check mounted Secrets
kubectl get pod <pod-name> -n <namespace> -o json | \
  jq '.spec.containers[].volumeMounts'

# Validate that referenced secrets/configmaps exist
kubectl get secret -n <namespace>
kubectl get configmap -n <namespace>
```

### Step 5: Check liveness/readiness probe configuration
```bash
kubectl get pod <pod-name> -n <namespace> -o json | \
  jq '.spec.containers[] | {name: .name, livenessProbe: .livenessProbe, readinessProbe: .readinessProbe}'
```

Common probe issues:
- `initialDelaySeconds` too short (app not ready yet)
- `timeoutSeconds` too low (app is slow to respond)
- Wrong probe path or port

### Step 6: Check resource constraints
```bash
# Ensure requests <= limits and limits are reasonable
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].resources}'

# Check if node has sufficient resources
kubectl describe node <node-name> | grep -A 10 "Allocated resources"
```

### Step 7: Attempt interactive debugging
```bash
# Run a debug container alongside the crashing pod
kubectl debug pod/<pod-name> -n <namespace> -it --image=busybox --share-processes --copy-to=debug-pod

# Or override the entrypoint to keep it running
kubectl run debug-pod --image=<same-image> -n <namespace> -- sleep 3600
kubectl exec -it debug-pod -n <namespace> -- sh
```

## Resolution

### Fix A: Configuration/environment variable error
```bash
# Fix ConfigMap
kubectl edit configmap <cm-name> -n <namespace>
# OR update via GitOps

# Force pod restart after config fix
kubectl rollout restart deployment/<deployment-name> -n <namespace>
```

### Fix B: Wrong entrypoint or command
```bash
# Patch the deployment command
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/command", "value": ["/app/server"]}]'
```

### Fix C: Liveness probe causing premature restarts
```bash
# Increase initialDelaySeconds
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/livenessProbe/initialDelaySeconds", "value": 60}]'
```

### Fix D: Missing dependency (database not ready)
```bash
# Add an init container to wait for dependency
# Update deployment YAML via GitOps:
# initContainers:
# - name: wait-for-db
#   image: busybox
#   command: ['sh', '-c', 'until nc -z db-service 5432; do sleep 2; done']
```

### Fix E: Application crash (exit code 1) — rollback
```bash
# Roll back to previous revision
kubectl rollout undo deployment/<deployment-name> -n <namespace>

# Roll back to specific revision
kubectl rollout undo deployment/<deployment-name> -n <namespace> --to-revision=3

# Via FluxCD — revert the Git commit, then reconcile
flux reconcile helmrelease <release-name> -n <namespace>
```

## Verification
```bash
# Watch pod stabilize (restartCount should stop increasing)
kubectl get pods -n <namespace> -w

# Confirm no crash events
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | grep -v Normal

# Check logs are now showing healthy startup
kubectl logs <pod-name> -n <namespace> | head -20

# Validate application endpoint responds
kubectl exec -n <namespace> deploy/<other-deployment> -- curl -s http://<service>:<port>/health
```

## Escalation
- Exit code 139 (segfault): escalate to development team immediately — core dump needed
- Repeated exit code 1 with no clear log output: may require remote debugging or adding verbose logging
- If crash only occurs under load: may be a race condition — escalate with load test reproduction steps

## Loki Queries

```logql
# All error/fatal logs for crashing pod
{namespace="<namespace>", pod=~"<pod-prefix>.*"} |= "error" or |= "fatal" or |= "panic"

# Last N lines before crash (narrow time window around restart event)
{namespace="<namespace>", pod="<pod-name>"} | json
  | line_format "{{.ts}} {{.level}} {{.message}}"

# CrashLoop pattern — pods that keep restarting
count_over_time({namespace="<namespace>"} |= "Back-off restarting failed container" [1h])

# Startup failure messages
{namespace="<namespace>", container="<container>"} 
  |= "failed to start" or |= "connection refused" or |= "no such file"

# Java exception stack traces
{namespace="<namespace>", container="<container>"} 
  |~ "Exception|Error|FATAL" | regexp `(?P<exception>[A-Za-z]+Exception)`

# Rate of error logs per pod
rate({namespace="<namespace>"} |= "level=error" [5m])
```

## Prometheus Queries

```promql
# Container restart count (threshold alert: > 5 in 15m)
increase(kube_pod_container_status_restarts_total{namespace="<namespace>"}[15m]) > 5

# Pods currently not ready
kube_pod_status_ready{namespace="<namespace>", condition="false"}

# Container last exit code (non-zero indicates problem)
kube_pod_container_status_last_terminated_exitcode{namespace="<namespace>"}

# Restart rate over time
rate(kube_pod_container_status_restarts_total{namespace="<namespace>", pod=~"<pod-prefix>.*"}[5m])

# Time since last successful pod start
(time() - kube_pod_start_time{namespace="<namespace>"}) 
  * on(pod) group_left() kube_pod_status_ready{condition="true"}
```

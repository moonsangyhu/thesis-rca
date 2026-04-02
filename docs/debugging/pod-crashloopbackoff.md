# Pod CrashLoopBackOff Diagnosis

## Overview
CrashLoopBackOff occurs when a container repeatedly starts, crashes, and Kubernetes backs off restarting it. The backoff interval doubles each time (10s, 20s, 40s... up to 5 minutes). This is one of the most common pod failure states and can stem from application errors, misconfigurations, resource exhaustion, or failed health checks.

## Symptoms
- `kubectl get pods` shows STATUS as `CrashLoopBackOff`
- RESTARTS counter is high and increasing
- Pod alternates between `Running` and `Error` or `OOMKilled` states
- Application logs show startup errors or immediate exits
- Events show `Back-off restarting failed container`

## Diagnostic Commands

```bash
# Step 1: Identify the affected pod
kubectl get pods -n <namespace> --field-selector=status.phase!=Running
kubectl get pods -n <namespace> | grep -E "CrashLoop|Error"

# Step 2: Get detailed pod status - check exit codes and restart count
kubectl describe pod <pod-name> -n <namespace>
# Look for:
#   Last State: Terminated (reason, exit code)
#   Restart Count
#   Events section at the bottom

# Step 3: Check current logs
kubectl logs <pod-name> -n <namespace>

# Step 4: Check previous container logs (critical - current logs may be empty if crash is immediate)
kubectl logs <pod-name> -n <namespace> --previous

# Step 5: Check logs with timestamps
kubectl logs <pod-name> -n <namespace> --previous --timestamps=true

# Step 6: If multiple containers in pod, specify container
kubectl logs <pod-name> -n <namespace> -c <container-name> --previous

# Step 7: Check exit code to understand crash type
# Exit 0: Success (liveness probe may be failing)
# Exit 1: General error
# Exit 2: Misuse of shell command
# Exit 126: Command invoked cannot execute
# Exit 127: Command not found
# Exit 128+N: Fatal signal N (137 = SIGKILL/OOMKilled, 143 = SIGTERM)
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.status.containerStatuses[0].lastState.terminated.exitCode}'

# Step 8: Check resource limits
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].resources}'

# Step 9: Check liveness probe configuration
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].livenessProbe}'

# Step 10: Check environment variables and secrets/configmaps
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.containers[*].env}'
kubectl get pod <pod-name> -n <namespace> -o yaml | grep -A5 envFrom

# Step 11: Check events for the namespace
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | tail -20

# Step 12: Check resource usage on the node
kubectl top pod <pod-name> -n <namespace>
kubectl top node <node-name>

# Step 13: Check if init containers are failing
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.status.initContainerStatuses}'
kubectl logs <pod-name> -n <namespace> -c <init-container-name> --previous

# Step 14: For Online Boutique specific - check all services
kubectl get pods -n online-boutique
kubectl get events -n online-boutique --sort-by='.lastTimestamp' | grep -i crash

# Step 15: Loki log query for crash patterns
# {namespace="online-boutique"} |= "panic" or "fatal" or "SIGKILL"

# Step 16: Prometheus metric for restart rate
# rate(kube_pod_container_status_restarts_total{namespace="online-boutique"}[5m]) > 0
```

## Common Causes

1. **Application startup failure**: The application exits immediately due to missing configuration, failed database connections, or initialization errors. Check logs for connection refused, missing env vars, or panic messages.

2. **OOMKilled (Exit 137)**: The container exceeded its memory limit and was killed by the kernel OOM killer. Memory limit is too low or there is a memory leak.

3. **Missing ConfigMap or Secret**: Application cannot start because a referenced ConfigMap key or Secret does not exist. Exit code typically 1 with error about missing env var or file.

4. **Liveness probe killing healthy container**: The liveness probe timeout or threshold is too aggressive. The container starts fine but is killed before it's ready to serve. Common during slow startup.

5. **Command not found (Exit 127)**: The container entrypoint or command does not exist in the image. Wrong image tag, image corruption, or wrong command specification.

6. **Port conflict**: Application tries to bind a port already in use. Rare in containers but can happen if using host networking.

7. **File permission issues**: Application cannot read config files or write to log directories due to security context / fsGroup settings.

8. **Dependency service unavailable**: Application hard-exits when it cannot connect to a required service (database, message queue, etc.) instead of retrying.

9. **Resource limits too low (CPU throttling causing timeout)**: CPU limits are so restrictive that the application times out during initialization.

10. **Wrong security context**: Application requires root but SecurityContext sets runAsNonRoot or specific UID that lacks permissions.

## Resolution Steps

### Step 1: Determine the crash type from exit code
```bash
EXIT_CODE=$(kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.status.containerStatuses[0].lastState.terminated.exitCode}')
echo "Exit code: $EXIT_CODE"
# 137 -> OOMKilled (see pod-oomkilled.md)
# 1   -> Application error (check logs)
# 127 -> Command not found (check image and command)
```

### Step 2: Fix missing ConfigMap/Secret
```bash
# Check if referenced configmaps/secrets exist
kubectl get configmap -n <namespace>
kubectl get secret -n <namespace>

# Check what the pod references
kubectl get pod <pod-name> -n <namespace> -o yaml | grep -A3 configMapKeyRef
kubectl get pod <pod-name> -n <namespace> -o yaml | grep -A3 secretKeyRef

# Create missing configmap if needed
kubectl create configmap <name> -n <namespace> --from-literal=key=value

# Or apply from file
kubectl apply -f configmap.yaml
```

### Step 3: Fix liveness probe issues
```bash
# Edit deployment to increase initialDelaySeconds and failureThreshold
kubectl edit deployment <deployment-name> -n <namespace>
# Change:
#   livenessProbe:
#     initialDelaySeconds: 30   # increase from default
#     failureThreshold: 5       # increase from default 3
#     periodSeconds: 15
#     timeoutSeconds: 5

# Or patch directly
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/livenessProbe/initialDelaySeconds", "value": 60}]'
```

### Step 4: Fix resource limits
```bash
# Increase memory/CPU limits
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits/memory", "value": "512Mi"}]'
```

### Step 5: Debug by running a shell in the container image
```bash
# Override entrypoint to prevent crash and debug manually
kubectl run debug-pod --image=<same-image> -n <namespace> \
  --command -- sleep 3600

kubectl exec -it debug-pod -n <namespace> -- /bin/sh
# Manually run the application command to see errors
```

### Step 6: Temporarily remove liveness probe to let pod stay up
```bash
kubectl patch deployment <deployment-name> -n <namespace> --type='json' \
  -p='[{"op": "remove", "path": "/spec/template/spec/containers/0/livenessProbe"}]'
# Then exec into the pod to debug
kubectl exec -it <pod-name> -n <namespace> -- /bin/sh
```

### Step 7: Force pod restart after fix
```bash
kubectl rollout restart deployment/<deployment-name> -n <namespace>
kubectl rollout status deployment/<deployment-name> -n <namespace>
```

## Log Patterns to Look For

```
# Java/Spring Boot startup failure
java.lang.RuntimeException: Failed to configure a DataSource
Connection refused: <db-host>:5432

# Go application panic
panic: runtime error: invalid memory address or nil pointer dereference
goroutine 1 [running]

# Node.js crash
Error: Cannot find module './config'
UnhandledPromiseRejectionWarning

# Python application
ModuleNotFoundError: No module named 'xxx'
ConnectionRefusedError: [Errno 111] Connection refused

# Generic missing env var
required environment variable "DATABASE_URL" is not set

# OOM in logs before kill (may not appear - kernel kills directly)
# Check dmesg on node instead:
# Out of memory: Kill process <pid> (<name>) total-vm:<X>kB, rss:<Y>kB
```

## Prevention
- Always set appropriate `initialDelaySeconds` for liveness probes based on measured startup time
- Implement graceful startup in applications (retry connections with backoff)
- Set proper resource requests and limits based on profiling
- Use `startupProbe` for applications with variable startup times
- Store configuration in ConfigMaps/Secrets with proper validation
- Use `preStop` lifecycle hook for graceful shutdown
- Monitor restart count metric: `kube_pod_container_status_restarts_total`
- Set up alerts: `increase(kube_pod_container_status_restarts_total[1h]) > 5`

## Related Issues
- `pod-oomkilled.md` - For Exit 137 (OOMKilled) crashes
- `readiness-liveness-probe.md` - For probe configuration issues
- `secret-configmap-issues.md` - For missing configuration crashes
- `memory-pressure.md` - For memory-related crashes

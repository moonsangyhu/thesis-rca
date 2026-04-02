# Debugging Readiness and Liveness Probe Failures

## Overview
Kubernetes uses probes to determine pod health. Liveness probes restart unhealthy containers. Readiness probes remove pods from service endpoints. Startup probes delay liveness checks for slow-starting applications. Misconfigured probes cause unnecessary restarts or traffic to unhealthy pods.

## Symptoms
- Container repeatedly restarting (liveness probe failure)
- Events: `Liveness probe failed: ...` or `Readiness probe failed: ...`
- Pod shows Running but 0/1 Ready (readiness probe failing)
- Service has no endpoints despite pods running
- Application receiving traffic before fully initialized

## Diagnostic Commands

```bash
# Check probe configuration
kubectl describe pod <pod> -n <ns> | grep -A10 "Liveness\|Readiness\|Startup"

# Check events for probe failures
kubectl get events -n <ns> --field-selector involvedObject.name=<pod>,reason=Unhealthy

# Check container restart count and reason
kubectl get pod <pod> -n <ns> -o jsonpath='{.status.containerStatuses[0].restartCount}'

# Test probe endpoint manually
kubectl exec <pod> -n <ns> -- wget -qO- http://localhost:8080/healthz
kubectl exec <pod> -n <ns> -- wget -qO- http://localhost:8080/readyz

# Check if port is listening
kubectl exec <pod> -n <ns> -- netstat -tlnp 2>/dev/null || \
kubectl exec <pod> -n <ns> -- ss -tlnp

# Check pod logs during probe failure window
kubectl logs <pod> -n <ns> --since=5m | grep -i "health\|ready\|probe"
```

## Common Causes

### 1. Liveness probe too aggressive
Short `timeoutSeconds` or `failureThreshold` kills pods during:
- GC pauses (JVM, Go)
- High load (slow response)
- Database connection pool exhaustion

```yaml
# Too aggressive:
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 5
  periodSeconds: 5
  timeoutSeconds: 1     # too short for heavy apps
  failureThreshold: 1   # one failure = restart

# Better:
livenessProbe:
  httpGet:
    path: /healthz
    port: 8080
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3   # 3 consecutive failures before restart
```

### 2. No startup probe for slow-starting apps
JVM apps, apps loading large models, or apps with DB migrations:
```yaml
startupProbe:
  httpGet:
    path: /healthz
    port: 8080
  periodSeconds: 5
  failureThreshold: 60  # 5s × 60 = 5 minutes to start
# Liveness probe doesn't start until startup probe succeeds
```

### 3. Health endpoint depends on external service
Liveness probe checks DB connectivity → DB is temporarily slow → pod restarts → reconnects → DB slow again → restart loop.

**Rule**: Liveness probe should check only local health (process alive, not deadlocked). Readiness probe can check dependencies.

### 4. Wrong port or path
```bash
# Verify the endpoint exists
kubectl exec <pod> -n <ns> -- wget -qO- --spider http://localhost:8080/healthz
# Check if app listens on expected port
kubectl exec <pod> -n <ns> -- ss -tlnp | grep 8080
```

### 5. Probe and graceful shutdown conflict
During termination: pod receives SIGTERM → starts shutdown → liveness probe fails → kubelet sends SIGKILL before graceful shutdown completes.

Fix: `terminationGracePeriodSeconds` must be longer than probe `failureThreshold × periodSeconds`.

## Resolution Steps

1. **Identify which probe is failing**: Check events and describe output
2. **Test the endpoint**: `kubectl exec` into pod and curl/wget the health endpoint
3. **Adjust timing**: Increase `timeoutSeconds`, `failureThreshold`, `initialDelaySeconds`
4. **Add startup probe**: For apps taking >30s to initialize
5. **Simplify liveness check**: Remove external dependency checks from liveness probe

## Prevention
- Liveness: check only process health (not dependencies)
- Readiness: check if ready to serve traffic (can include dependency checks)
- Startup: use for slow-starting applications
- Set `failureThreshold >= 3` for liveness probes
- Set `timeoutSeconds >= 3` for HTTP probes
- Test probe endpoints return quickly (<1s) under load

## Related Issues
- [Liveness Probe Too Aggressive](../known-issues/liveness-probe-too-aggressive.md)
- [Termination Grace Period](../known-issues/termination-grace-period.md)
- [Pod CrashLoopBackOff](pod-crashloopbackoff.md)

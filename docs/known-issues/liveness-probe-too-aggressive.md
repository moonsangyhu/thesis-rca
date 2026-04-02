# Known Issue: Aggressive Liveness Probe Killing Pods During Startup or GC Pause

## Issue ID
KI-013

## Affected Components
- All pods with liveness probes configured
- JVM-based applications (Java, Kotlin, Scala) with GC pauses
- Applications with slow initialization (database migration, cache warming)
- Online Boutique services: `frontend`, `checkoutservice`, `recommendationservice` (Python)

## Symptoms
- Pods restart repeatedly with reason `Liveness probe failed`
- `kubectl describe pod <name>` shows:
  ```
  Liveness probe failed: HTTP probe failed with statuscode: 503
  # or
  Liveness probe failed: Get "http://10.0.0.5:8080/healthz": context deadline exceeded (Client.Timeout exceeded while awaiting headers)
  ```
- Pods in CrashLoopBackOff during initial deployment despite no actual application bugs
- High restart count visible in `kubectl get pods`: `RESTARTS: 47`
- Application logs show startup completing successfully, then process killed immediately after
- Pods killed during JVM full GC (Stop-The-World pause) of several hundred milliseconds to seconds
- Service unavailability during rolling deployments (probe kills pods before they finish starting)

## Root Cause
Liveness probes are used to detect and restart genuinely stuck or dead processes. However, if the probe thresholds are too aggressive relative to the application's normal startup and operational characteristics, the probe will kill healthy pods:

**Case 1: Slow-starting applications**
An application doing database migrations, loading large ML models, or connecting to external services may take 2-5 minutes to complete initialization. If the liveness probe starts checking immediately with a short `failureThreshold`, it will kill the pod before startup completes.

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 10    # Only 10s before first probe — too short for slow apps
  periodSeconds: 5
  failureThreshold: 3        # 3 failures = killed after 15s of unhealthy
  timeoutSeconds: 1          # 1s timeout — may not be enough under load
```

**Case 2: JVM GC pauses**
Java applications undergoing a full (Stop-The-World) GC pause cannot respond to HTTP probes for the duration of the pause. With a `timeoutSeconds: 1`, any GC pause longer than 1 second causes a probe failure. After `failureThreshold` consecutive failures, the pod is killed, only to hit GC again shortly after restart.

**Case 3: Resource contention under load**
Under high CPU load, the application may not respond within the probe `timeoutSeconds`. This is often misinterpreted as application failure when it is actually a transient slowdown.

## Diagnostic Commands
```bash
# Check probe configuration for a pod
kubectl describe pod <pod-name> -n <namespace> | grep -A10 "Liveness:"

# Check restart count and last exit reason
kubectl get pods -n <namespace>
kubectl describe pod <pod-name> -n <namespace> | grep -E "Restart Count|Last State|Exit Code"

# Check if killed by liveness probe (exit code 137 = SIGKILL)
kubectl describe pod <pod-name> -n <namespace> | grep "Exit Code"
# Exit Code 137 = SIGKILL from liveness probe

# View probe failure events
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | grep "Liveness probe"

# Check application startup time from logs
kubectl logs <pod-name> -n <namespace> | grep -i "started\|ready\|listening\|init"

# Check for GC pauses in JVM applications
kubectl logs <pod-name> -n <namespace> | grep -i "gc\|pause\|stop.the.world"
```

## Resolution
**For slow-starting applications — use startupProbe (K8s 1.18+)**:

`startupProbe` runs before liveness and readiness probes. The liveness probe only begins after the startupProbe succeeds. This allows a generous startup window without affecting ongoing liveness checks.

```yaml
spec:
  containers:
  - name: app
    startupProbe:
      httpGet:
        path: /healthz
        port: 8080
      failureThreshold: 30     # 30 attempts x 10s = 5 minutes startup window
      periodSeconds: 10
    livenessProbe:
      httpGet:
        path: /healthz
        port: 8080
      periodSeconds: 10
      failureThreshold: 3
      timeoutSeconds: 5        # More generous timeout
    readinessProbe:
      httpGet:
        path: /ready
        port: 8080
      periodSeconds: 5
      failureThreshold: 3
```

**For JVM applications with GC pauses**:
```yaml
livenessProbe:
  httpGet:
    path: /actuator/health/liveness
    port: 8080
  initialDelaySeconds: 60
  periodSeconds: 15
  failureThreshold: 3
  timeoutSeconds: 10    # Allow up to 10s for GC pause to complete
```

**Recommended minimum thresholds by application type**:
| Application Type | initialDelaySeconds | timeoutSeconds | failureThreshold |
|-----------------|---------------------|----------------|------------------|
| Simple HTTP service | 5 | 3 | 3 |
| JVM (Spring Boot) | 60 | 10 | 3 |
| Python (ML model load) | 120 | 5 | 3 |
| DB-migrating app | Use startupProbe | 5 | 3 |

## Workaround
Increase `initialDelaySeconds` significantly as a quick fix:
```bash
kubectl patch deployment <name> -n <namespace> --type=json -p='[
  {"op":"replace","path":"/spec/template/spec/containers/0/livenessProbe/initialDelaySeconds","value":120}
]'
```

## Prevention
- Use `startupProbe` for any application with variable or slow startup time
- Set liveness probe `timeoutSeconds` to at least 3-5x the p99 response time of the health endpoint under normal load
- Implement separate health endpoints: `/healthz` (liveness — is process alive?) vs `/readyz` (readiness — can serve traffic?)
- Load test health endpoints specifically to determine appropriate probe thresholds
- Review liveness probe settings as part of deployment review checklists

## References
- K8s probe configuration: https://kubernetes.io/docs/tasks/configure-pod-container/configure-liveness-readiness-startup-probes/
- startupProbe documentation: https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#container-probes
- Liveness probe best practices: https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#when-should-you-use-a-liveness-probe

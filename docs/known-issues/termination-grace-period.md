# Known Issue: terminationGracePeriodSeconds Too Short Causes In-Flight Request Failures

## Issue ID
KI-014

## Affected Components
- All pods handling long-lived or in-flight requests
- Pods with database connections or message queue consumers
- Load-balanced services during rolling deployments
- Online Boutique services (especially `checkoutservice`, `paymentservice`)

## Symptoms
- HTTP 502/503 errors spike during rolling deployments or pod terminations
- Clients receive connection reset errors at the end of ongoing requests
- Database transactions are aborted mid-flight, causing data inconsistency
- Message queue consumers lose messages (unacked messages requeued but processing was incomplete)
- Application logs show abrupt shutdown: process killed before "Shutdown complete" log
- `kubectl describe pod` shows termination reason: `DeadlineExceeded` or just no graceful shutdown log

## Root Cause
When a pod is terminated (via `kubectl delete pod`, rolling update, node drain, or HPA scale-down), Kubernetes follows this shutdown sequence:

1. Pod transitions to `Terminating` state
2. Pod is removed from Service endpoint slice (stops receiving new traffic)
3. `SIGTERM` signal sent to container PID 1
4. `terminationGracePeriodSeconds` countdown begins (default: **30 seconds**)
5. If process is still running after grace period, `SIGKILL` is sent

The default grace period of 30 seconds is insufficient for several scenarios:
- **Long-running requests**: Requests longer than 30s (file uploads, video processing, report generation) are killed mid-execution
- **Database transactions**: Complex multi-step transactions may need more than 30s to commit or rollback cleanly
- **Connection draining**: Load balancers may take longer than 30s to drain connections from the terminating pod
- **JVM shutdown hooks**: Spring Boot graceful shutdown + JVM finalization can exceed 30s under load

Additionally, there is a race condition: even after the pod is removed from endpoints, the kube-proxy iptables rules may still direct traffic to the pod for several seconds. This means the pod may still receive new requests while already handling SIGTERM.

## Diagnostic Commands
```bash
# Check current terminationGracePeriodSeconds
kubectl get pod <pod-name> -n <namespace> -o jsonpath='{.spec.terminationGracePeriodSeconds}'

# Check deployment default
kubectl get deployment <name> -n <namespace> -o jsonpath='{.spec.template.spec.terminationGracePeriodSeconds}'

# Check if pods were SIGKILLed (exit code 137)
kubectl describe pod <pod-name> -n <namespace> | grep "Exit Code"

# Monitor pod termination timing
kubectl get events -n <namespace> | grep -i "kill\|terminat"

# Check application shutdown log messages
kubectl logs <pod-name> -n <namespace> --previous | tail -50

# Test graceful shutdown duration manually
time kubectl delete pod <pod-name> -n <namespace>
# If this completes quickly (<5s), the app is not handling SIGTERM gracefully

# Check if application implements SIGTERM handler
kubectl exec -it <pod-name> -- kill -TERM 1  # sends SIGTERM to PID 1 inside container
kubectl logs <pod-name> -f  # watch for shutdown messages
```

## Resolution
**Step 1**: Increase `terminationGracePeriodSeconds` in the Deployment:
```yaml
spec:
  template:
    spec:
      terminationGracePeriodSeconds: 60   # Increase from default 30s
      containers:
      - name: app
```

For applications with longer shutdown requirements:
```yaml
terminationGracePeriodSeconds: 120  # 2 minutes for heavy workloads
```

**Step 2**: Implement graceful shutdown in the application.

For Go:
```go
// Handle SIGTERM
sigCh := make(chan os.Signal, 1)
signal.Notify(sigCh, syscall.SIGTERM, syscall.SIGINT)
<-sigCh
// Stop accepting new connections
server.SetKeepAlivesEnabled(false)
ctx, cancel := context.WithTimeout(context.Background(), 50*time.Second)
defer cancel()
server.Shutdown(ctx)
```

For Java (Spring Boot), add to `application.yaml`:
```yaml
server:
  shutdown: graceful
spring:
  lifecycle:
    timeout-per-shutdown-phase: 50s
```

**Step 3**: Add a `preStop` hook to delay SIGTERM until load balancer draining completes:
```yaml
spec:
  containers:
  - name: app
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 5"]  # Wait for LB to drain
```
The `preStop` hook runs before SIGTERM, giving the load balancer time to remove the pod from rotation. Total allowed time = `preStop` duration + `terminationGracePeriodSeconds`.

**Step 4**: For critical services, combine all three approaches:
```yaml
spec:
  terminationGracePeriodSeconds: 75
  containers:
  - name: app
    lifecycle:
      preStop:
        exec:
          command: ["/bin/sh", "-c", "sleep 10"]
```
Timeline: 10s preStop (LB drain) + 60s SIGTERM handling + 5s buffer = 75s total grace period.

## Workaround
For immediate relief without redeployment, patch the grace period:
```bash
kubectl patch deployment <name> -n <namespace> --type=json \
  -p='[{"op":"replace","path":"/spec/template/spec/terminationGracePeriodSeconds","value":60}]'
```

## Prevention
- Set `terminationGracePeriodSeconds: 60` as the minimum default for all production workloads
- Implement SIGTERM handlers in all applications — never rely on SIGKILL for clean shutdown
- Add `preStop: sleep 10` hook to all HTTP services to account for load balancer propagation delay
- Test graceful shutdown as part of application development (not just deployment)
- Monitor error rates during rolling deployments with Prometheus alerts

## References
- K8s pod termination lifecycle: https://kubernetes.io/docs/concepts/workloads/pods/pod-lifecycle/#pod-termination
- Container lifecycle hooks: https://kubernetes.io/docs/concepts/containers/container-lifecycle-hooks/
- Graceful node shutdown: https://kubernetes.io/docs/concepts/architecture/nodes/#graceful-node-shutdown
- Spring Boot graceful shutdown: https://docs.spring.io/spring-boot/docs/current/reference/html/web.html#web.graceful-shutdown

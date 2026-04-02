# Runbook: Loki LogQL Analysis for Root Cause Analysis

## Trigger Conditions
When investigating application failures, pod restarts, or performance issues that require log-based evidence correlation with metrics and events.

## Severity
N/A (diagnostic procedure, not incident response)

## Estimated Resolution Time
15-30 minutes per investigation

## Prerequisites
- Loki running in monitoring namespace
- Promtail collecting logs from all nodes
- Grafana with Loki datasource configured
- `logcli` CLI (optional) or Grafana Explore UI

## Investigation Steps

### Step 1: Identify the time window
```bash
# Get event timestamps for the incident
kubectl get events -n boutique --sort-by='.lastTimestamp' | tail -20

# Note the timestamps of relevant events (pod restart, failure, etc.)
```

### Step 2: Query logs by namespace and pod
```logql
# All logs from a specific namespace
{namespace="boutique"}

# Specific pod
{namespace="boutique", pod="frontend-abc123"}

# Specific container in multi-container pod
{namespace="boutique", pod="frontend-abc123", container="server"}

# All pods of a deployment (label selector)
{namespace="boutique", app="frontend"}
```

### Step 3: Filter for errors and warnings
```logql
# Error logs only
{namespace="boutique"} |= "error" | logfmt | level="error"

# Multiple severity levels
{namespace="boutique"} |~ "(?i)(error|warn|fatal|panic)"

# Exclude noisy patterns
{namespace="boutique"} |= "error" != "healthcheck" != "readiness"

# JSON log parsing
{namespace="boutique", app="frontend"} | json | level="error"
```

### Step 4: Fault-type specific queries

**F1 - OOMKilled:**
```logql
# Look for memory warnings before OOMKill
{namespace="boutique", pod=~"frontend.*"} |~ "(?i)(out of memory|OOM|heap|memory allocation)"

# System-level OOM messages
{job="systemd-journal"} |= "oom-kill" | logfmt
```

**F2 - CrashLoopBackOff:**
```logql
# Last logs before crash (look for panic, fatal, unhandled exception)
{namespace="boutique", pod=~"frontend.*"} |~ "(?i)(panic|fatal|exception|segfault|SIGABRT)"

# Startup errors
{namespace="boutique", pod=~"frontend.*"} |~ "(?i)(failed to start|cannot listen|bind: address already in use)"
```

**F3 - ImagePullBackOff:**
```logql
# Kubelet image pull logs
{job="systemd-journal", unit="kubelet.service"} |~ "(?i)(pull|image|ErrImagePull|BackOff)"
```

**F4 - NodeNotReady:**
```logql
# Kubelet health logs
{job="systemd-journal", unit="kubelet.service"} |~ "(?i)(not ready|node condition|PLEG)"

# Cilium agent logs
{namespace="kube-system", app="cilium-agent"} |~ "(?i)(unreachable|endpoint|error)"
```

**F5 - PVC Pending:**
```logql
# Storage provisioner logs
{namespace="local-path-storage"} |~ "(?i)(provision|pvc|volume|error)"
```

**F6 - NetworkPolicy:**
```logql
# Cilium policy enforcement
{namespace="kube-system", app="cilium-agent"} |~ "(?i)(policy|deny|drop|verdict)"

# Application connection errors
{namespace="boutique"} |~ "(?i)(connection refused|connection timed out|no route to host)"
```

**F7 - CPU Throttle:**
```logql
# Application latency spikes (look for timeout messages)
{namespace="boutique"} |~ "(?i)(timeout|deadline exceeded|slow|latency)"
```

**F8 - Service Endpoint:**
```logql
# Connection errors between services
{namespace="boutique"} |~ "(?i)(connection refused|no such host|dial tcp.*refused)"

# kube-proxy / Cilium service resolution
{namespace="kube-system"} |~ "(?i)(endpoint|service|stale)"
```

**F9 - Secret/ConfigMap:**
```logql
# Missing config errors
{namespace="boutique"} |~ "(?i)(config.*not found|missing.*key|env.*empty|no such file)"
```

**F10 - ResourceQuota:**
```logql
# Controller manager quota logs
{namespace="kube-system", pod=~"kube-controller-manager.*"} |~ "(?i)(quota|exceeded|forbidden)"
```

### Step 5: Rate analysis (detect anomalies)
```logql
# Error rate over time
sum(rate({namespace="boutique"} |~ "(?i)error" [5m])) by (pod)

# Log volume spike (indicator of issues)
sum(bytes_rate({namespace="boutique"}[5m])) by (pod)

# Count specific error patterns
sum(count_over_time({namespace="boutique"} |= "connection refused" [5m])) by (pod)
```

### Step 6: Correlate with Prometheus metrics timestamps
```bash
# In Grafana: use split view with Loki + Prometheus panels
# Align time ranges to correlate log events with metric anomalies

# Useful PromQL to pair with LogQL:
# - rate(container_restarts_total[5m]) - when pods restart
# - container_memory_working_set_bytes - memory before OOMKill
# - container_cpu_cfs_throttled_periods_total - CPU throttle events
```

## Verification
- Root cause is identified and documented
- Timeline of events is reconstructed from logs + metrics
- Fix applied and verified in subsequent log queries (no more error patterns)

## Escalation
If logs are missing or incomplete:
- Check Promtail is running on all nodes: `kubectl get pods -n monitoring -l app.kubernetes.io/name=promtail`
- Check Promtail can push to Loki: `kubectl logs -n monitoring -l app.kubernetes.io/name=promtail | grep error`
- Verify Loki retention hasn't expired the relevant logs

## Prometheus Queries
```promql
# Loki ingestion rate (is it receiving logs?)
loki_distributor_bytes_received_total

# Loki query performance
histogram_quantile(0.99, rate(loki_request_duration_seconds_bucket{route=~".*query.*"}[5m]))
```

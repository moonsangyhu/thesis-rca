# Runbook: Prometheus Alert → RCA Workflow

## Trigger Conditions
Use this runbook as the primary alert triage guide when a Prometheus alert fires. Provides the workflow from alert reception through root cause identification and resolution.

## Severity
**Varies by alert**

## Estimated Resolution Time
5-10 minutes (triage) + fault-specific resolution time

## Prerequisites
- Prometheus access: `kubectl port-forward svc/prometheus-operated -n monitoring 9090:9090`
- Grafana access: `kubectl port-forward svc/grafana -n monitoring 3000:3000`
- Alertmanager access: `kubectl port-forward svc/alertmanager-operated -n monitoring 9093:9093`
- `kubectl` access

## Alert Triage Workflow

### Step 1: Receive and Acknowledge Alert

```bash
# Check active alerts in Alertmanager
curl -s http://localhost:9093/api/v2/alerts | jq '.[] | {name: .labels.alertname, severity: .labels.severity, namespace: .labels.namespace, pod: .labels.pod, message: .annotations.message}'

# Or check in Prometheus
curl -s http://localhost:9090/api/v1/alerts | jq '.data.alerts[] | select(.state=="firing") | {alert: .labels.alertname, labels: .labels, value: .value}'
```

### Step 2: Alert → Runbook Mapping

| Alert Name | Likely Fault | Runbook |
|------------|-------------|---------|
| `KubePodOOMKilled` | F1: OOMKilled | rca-f1-oomkilled.md |
| `KubePodCrashLooping` | F2: CrashLoopBackOff | rca-f2-crashloopbackoff.md |
| `KubePodContainerWaiting` reason=ImagePullBackOff | F3: ImagePull | rca-f3-imagepullbackoff.md |
| `KubeNodeNotReady` | F4: NodeNotReady | rca-f4-nodenotready.md |
| `KubePersistentVolumeFillingUp` / `KubePVCPending` | F5: PVCPending | rca-f5-pvcpending.md |
| `CiliumPolicyDrops` / HTTP 5xx spike | F6: NetworkPolicy | rca-f6-networkpolicy.md |
| `KubeContainerCpuThrottling` | F7: CPUThrottle | rca-f7-cputhrottle.md |
| `KubeEndpointNotReady` | F8: ServiceEndpoint | rca-f8-serviceendpoint.md |
| `KubePodContainerWaiting` reason=CreateContainerConfigError | F9: Secret/ConfigMap | rca-f9-secretconfigmap.md |
| `KubeQuotaExceeded` | F10: ResourceQuota | rca-f10-resourcequota.md |

### Step 3: Navigate to Grafana Dashboard

```bash
# Port-forward Grafana
kubectl port-forward svc/grafana -n monitoring 3000:3000

# Default credentials: admin/prom-operator (check secret)
kubectl get secret grafana -n monitoring -o jsonpath='{.data.admin-password}' | base64 -d
```

**Key Dashboards:**
- `Kubernetes / Compute Resources / Namespace (Pods)` — CPU/memory per namespace
- `Kubernetes / Compute Resources / Pod` — Individual pod details
- `Node Exporter / Nodes` — Node-level metrics
- `Cilium / Overview` — Network health
- `Kubernetes / Persistent Volumes` — Storage health

### Step 4: Drill Down with PromQL

```bash
# Get the specific value that triggered the alert
# (Use the alert's expr from the PrometheusRule)
kubectl get prometheusrule -A -o json | \
  jq '.items[].spec.groups[].rules[] | select(.alert == "<alert-name>") | {alert: .alert, expr: .expr, threshold: .for}'

# Example: for KubePodCrashLooping
# expr: rate(kube_pod_container_status_restarts_total{...}[15m]) * 60 * 5 > 0
```

### Step 5: Correlate with Logs

```bash
# Find the affected pod from alert labels
NAMESPACE="<from-alert>"
POD="<from-alert>"

# Get recent logs
kubectl logs $POD -n $NAMESPACE --previous --tail=50

# Search Loki (if grafana explore is available)
# Or use logcli
logcli query --tail --no-labels \
  '{namespace="'$NAMESPACE'", pod="'$POD'"} |= "error"'
```

### Step 6: Check Kubernetes Events

```bash
# Events for the affected namespace
kubectl get events -n <namespace> --sort-by='.lastTimestamp' | tail -20

# Filter for warnings only
kubectl get events -n <namespace> --sort-by='.lastTimestamp' \
  --field-selector type=Warning
```

## Alert Configuration Reference

### Viewing Existing Alert Rules
```bash
# List all PrometheusRules
kubectl get prometheusrule -A

# View rules for a specific component
kubectl get prometheusrule -n monitoring kube-prometheus-stack-kubernetes-apps -o yaml | \
  grep -A5 "alert:"

# Check if alerts are being evaluated
curl -s http://localhost:9090/api/v1/rules | \
  jq '.data.groups[].rules[] | select(.type=="alerting") | {alert: .name, state: .state}'
```

### Creating Custom Alert for Thesis Experiments
```bash
cat <<EOF | kubectl apply -f -
apiVersion: monitoring.coreos.com/v1
kind: PrometheusRule
metadata:
  name: thesis-experiment-alerts
  namespace: monitoring
  labels:
    release: kube-prometheus-stack
spec:
  groups:
  - name: thesis.experiments
    interval: 30s
    rules:
    # F1: OOMKilled
    - alert: ThesisOOMKillDetected
      expr: kube_pod_container_status_last_terminated_reason{reason="OOMKilled", namespace="online-boutique"} > 0
      for: 0m
      labels:
        severity: critical
        fault_type: F1
      annotations:
        summary: "OOMKill detected in {{ \$labels.namespace }}/{{ \$labels.pod }}"
        runbook_url: "docs/runbooks/rca-f1-oomkilled.md"
    
    # F2: CrashLoopBackOff
    - alert: ThesisCrashLoopDetected
      expr: rate(kube_pod_container_status_restarts_total{namespace="online-boutique"}[15m]) * 900 > 3
      for: 1m
      labels:
        severity: critical
        fault_type: F2
      annotations:
        summary: "CrashLoopBackOff in {{ \$labels.namespace }}/{{ \$labels.pod }}"
        runbook_url: "docs/runbooks/rca-f2-crashloopbackoff.md"

    # F7: CPU Throttle  
    - alert: ThesisCPUThrottleHigh
      expr: |
        rate(container_cpu_cfs_throttled_periods_total{namespace="online-boutique", container!=""}[5m])
        / rate(container_cpu_cfs_periods_total{namespace="online-boutique", container!=""}[5m]) > 0.5
      for: 5m
      labels:
        severity: warning
        fault_type: F7
      annotations:
        summary: "CPU throttle >50% for {{ \$labels.container }} in {{ \$labels.pod }}"
        runbook_url: "docs/runbooks/rca-f7-cputhrottle.md"

    # F10: ResourceQuota
    - alert: ThesisQuotaNearLimit
      expr: |
        kube_resourcequota{namespace="online-boutique", type="used"}
        / kube_resourcequota{namespace="online-boutique", type="hard"} > 0.85
      for: 2m
      labels:
        severity: warning
        fault_type: F10
      annotations:
        summary: "Resource quota >85% used in {{ \$labels.namespace }}: {{ \$labels.resource }}"
        runbook_url: "docs/runbooks/rca-f10-resourcequota.md"
EOF
```

## Verification
```bash
# Check alert is firing as expected during fault injection
curl -s http://localhost:9090/api/v1/alerts | \
  jq '.data.alerts[] | select(.labels.namespace=="online-boutique") | {alert: .labels.alertname, state: .state, value: .value}'

# Check alertmanager received the alert
curl -s http://localhost:9093/api/v2/alerts | \
  jq '.[] | select(.labels.namespace=="online-boutique")'
```

## Escalation
- If Prometheus itself is down: `kubectl get pods -n monitoring` and check operator logs
- If alertmanager is not sending notifications: check Alertmanager config and webhook endpoints
- If alerts are flapping (firing/resolved rapidly): adjust `for:` duration or alert expression threshold

## Loki Queries

```logql
# Prometheus evaluation errors (alert rule failures)
{namespace="monitoring", app="prometheus"} |= "error" or |= "Error"

# Alertmanager dispatch errors
{namespace="monitoring", app="alertmanager"} |= "error"

# Prometheus scrape errors (targets unavailable)
{namespace="monitoring", app="prometheus"} |= "scrape" |= "error"
```

## Prometheus Queries

```promql
# List all currently firing alerts
ALERTS{alertstate="firing"}

# Alert evaluation frequency
rate(prometheus_rule_evaluations_total[5m])

# Alertmanager notification success rate
rate(alertmanager_notifications_total[5m])
rate(alertmanager_notifications_failed_total[5m])

# Prometheus target scrape health
up{job=~"kubernetes.*"}

# Number of active time series (cardinality)
prometheus_tsdb_head_series
```

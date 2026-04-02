# Known Issue: Prometheus High Cardinality Labels Causing OOM

## Issue ID
KI-024

## Affected Components
- Prometheus server (StatefulSet)
- Custom application metrics
- Grafana dashboards (slow queries)

## Symptoms
- Prometheus pod memory usage steadily increasing over days
- Grafana dashboards loading slowly or timing out
- `prometheus_tsdb_head_series` metric growing unboundedly
- OOMKilled events on Prometheus pod
- `container_memory_working_set_bytes{container="prometheus"}` exceeding limits

## Root Cause
High cardinality labels in custom metrics cause exponential growth in time series count.
Common culprits:
- **Pod name as label**: Each pod restart creates a new time series (e.g., `http_requests_total{pod="frontend-abc12"}`)
- **Request ID / trace ID**: Unique per request, creates unbounded series
- **User ID / session ID**: Grows with user base
- **URL path with parameters**: `/api/users/12345` creates a series per user
- **Error message as label**: Unique error strings create unbounded series

Each unique label combination creates a separate time series. With N labels of cardinality C1, C2, ..., CN, the total series count is C1 × C2 × ... × CN.

## Diagnostic Commands

```bash
# Check current head series count
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  promtool tsdb analyze /prometheus/

# Query current series count via PromQL
# prometheus_tsdb_head_series

# Find top metrics by series count
# topk(20, count by (__name__)({__name__=~".+"}))

# Check Prometheus memory usage
kubectl top pod -n monitoring -l app.kubernetes.io/name=prometheus

# Check for OOMKilled events
kubectl get events -n monitoring --field-selector reason=OOMKilling

# Inspect TSDB stats via API
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- http://localhost:9090/api/v1/status/tsdb | python3 -m json.tool

# Check label cardinality for a specific metric
# count(http_requests_total) by (pod)
# This shows how many series exist per pod label value
```

## Resolution

### Step 1: Identify high-cardinality metrics
```yaml
# Use metric_relabel_configs in Prometheus to analyze before dropping
# Check /api/v1/status/tsdb for seriesCountByMetricName and labelValueCountByLabelName
```

### Step 2: Drop high-cardinality labels via metric_relabel_configs
```yaml
# In kube-prometheus-stack HelmRelease values:
prometheus:
  prometheusSpec:
    additionalScrapeConfigs:
      - job_name: 'app-metrics'
        metric_relabel_configs:
          # Drop pod name label from application metrics
          - source_labels: [__name__]
            regex: 'http_requests_total|app_.*'
            action: keep
          - regex: 'pod|instance'
            action: labeldrop
          # Drop metrics with high cardinality entirely
          - source_labels: [__name__]
            regex: 'app_request_details_total'
            action: drop
```

### Step 3: Fix application metrics at source
- Replace high-cardinality labels with bounded alternatives (e.g., `status_code` instead of `response_body`)
- Use histograms instead of per-value counters
- Aggregate at the application level before exposing

### Step 4: Compact TSDB to reclaim space
```bash
# After fixing the source, wait for old series to expire (based on retention)
# Or trigger TSDB compaction
kubectl exec -n monitoring prometheus-kube-prometheus-stack-prometheus-0 -c prometheus -- \
  wget -qO- -X POST http://localhost:9090/api/v1/admin/tsdb/clean_tombstones
```

## Workaround
- Temporarily increase Prometheus memory limits
- Reduce retention period to limit total series stored:
  ```yaml
  prometheus:
    prometheusSpec:
      retention: 7d  # reduce from 30d
  ```

## Prevention
- Set naming conventions for custom metrics (no unbounded labels)
- Add `metric_relabel_configs` to scrape configs as standard practice
- Monitor `prometheus_tsdb_head_series` with alerting threshold (e.g., > 500,000)
- Review new ServiceMonitor/PodMonitor additions for cardinality impact
- Use recording rules to pre-aggregate high-cardinality queries

## PromQL Monitoring Queries
```promql
# Alert on series count growth
prometheus_tsdb_head_series > 500000

# Series growth rate (should be near 0 for stable workloads)
rate(prometheus_tsdb_head_series[1h]) > 100

# Memory usage vs limit
container_memory_working_set_bytes{namespace="monitoring", container="prometheus"}
  / container_spec_memory_limit_bytes{namespace="monitoring", container="prometheus"} > 0.8
```

## References
- Prometheus Best Practices: https://prometheus.io/docs/practices/naming/
- TSDB format: https://ganeshvernekar.com/blog/prometheus-tsdb-the-head-block/

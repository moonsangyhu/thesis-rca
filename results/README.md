# results/ — Experiment Results

## Purpose

This directory stores all experiment outputs: ground truth labels, per-trial RCA results from System A and B, evaluation scores, and statistical analysis. Every experimental claim in the thesis is traceable back to data files here.

## Ground Truth (`ground_truth.csv`)

**50 labeled fault cases** (F1–F10 x 5 trials) defining the expected outcome for each fault injection experiment. This is the evaluation baseline — System A and System B outputs are scored against these labels.

### Schema

| Column | Description |
|--------|-------------|
| `fault_id` | Fault type identifier (F1–F10) |
| `trial` | Trial number (1–5) per fault type |
| `fault_name` | Human-readable fault name (e.g., OOMKilled) |
| `target_service` | Online Boutique service targeted for injection |
| `injection_method` | Exact method used to inject the fault |
| `expected_root_cause` | Ground truth root cause description |
| `affected_components` | Services impacted by the fault (comma-separated) |
| `severity` | Expected severity: critical, high, medium, low |
| `primary_symptoms` | Observable symptoms (pod status, HTTP errors, etc.) |
| `expected_metrics` | Prometheus metrics/queries that should fire |
| `expected_log_patterns` | Log patterns expected in Loki |
| `expected_recovery_action` | Correct remediation action |

### Design Principles

- Each fault type targets **different Online Boutique services** across trials for diversity
- Injection methods vary per trial (e.g., F1 tests OOMKilled on frontend, cartservice, checkoutservice, etc.)
- Severity reflects **user-facing impact**: critical = full service outage, low = non-critical feature degraded

## Planned Output Files

| File | Description |
|------|-------------|
| `system_a_results.csv` | System A (baseline) RCA output per trial |
| `system_b_results.csv` | System B (proposed) RCA output per trial |
| `evaluation_scores.csv` | Per-trial accuracy, precision, recall, F1 scores |
| `ablation_results.csv` | AB-1 to AB-5 ablation study results |
| `wilcoxon_test.json` | Statistical significance test results |

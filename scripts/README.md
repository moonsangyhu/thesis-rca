# scripts/ — Experiment Automation

## Purpose

Automation scripts for the fault injection experiment lifecycle: injecting faults into the Online Boutique application, stabilizing the cluster between trials, and evaluating RCA pipeline output against ground truth labels.

These scripts ensure **reproducible experiments** — each fault injection follows the same procedure, timing, and data collection protocol across all 50 trials.

## Structure

| Directory | Description |
|-----------|-------------|
| `fault_inject/` | Fault injection scripts for F1–F10. Each script applies a specific fault (e.g., set memory limit to 32Mi for F1-OOMKilled), waits for symptoms to manifest, and triggers data collection. |
| `stabilize/` | Post-injection recovery scripts. Restore cluster to clean state between trials: revert manifest changes, wait for pod health, verify monitoring baseline. 30-minute stabilization window per the experiment protocol. |
| `evaluate/` | Scoring and evaluation scripts. Compare System A/B RCA outputs against `results/ground_truth.csv`, compute accuracy/precision/recall/F1, and run Wilcoxon signed-rank test for statistical significance. |

## Status

All scripts are **planned** — to be implemented alongside the Online Boutique deployment and fault injection experiment phases.

## Experiment Protocol

```
For each fault F_i (i = 1..10):
  For each trial t (t = 1..5):
    1. Verify cluster stable          (stabilize/)
    2. Inject fault F_i trial t       (fault_inject/)
    3. Wait for symptoms (~2-5 min)
    4. Collect signals                 (src/collector/)
    5. Run System A RCA               (src/llm/)
    6. Run System B RCA               (src/rag/ + src/llm/)
    7. Record results                  (results/)
    8. Restore and stabilize           (stabilize/, 30 min wait)
```

# Reproduction Commands

## Naive baseline

```bash
python3 -m baselines.baseline_naive --config baselines/configs/baseline_naive.json
python3 -m baselines.evaluate_baseline \
  --predictions baselines/results/baseline_naive/baseline_naive_predictions.csv \
  --output baselines/results/baseline_naive/baseline_naive_metric_table.md
```

Expected artifacts:

- `baselines/results/baseline_naive/baseline_naive_predictions.csv`
- `baselines/results/baseline_naive/baseline_naive_metrics.md`
- `baselines/results/baseline_naive/baseline_naive_failures.md`
- `baselines/results/baseline_naive/baseline_naive_manifest.json`

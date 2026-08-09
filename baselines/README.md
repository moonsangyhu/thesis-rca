# Baselines

## `baseline_naive`

목적: proposed method와 비교할 최소 기준선이다. 성능을 높이는 것이 아니라, 데이터 split·입출력·metric 산출이 end-to-end로 재현되는지 확인한다.

### 입력/출력 계약

- 입력 데이터셋: `results/ground_truth.csv`
- 고정 schema: `baselines/baseline_naive.py`의 `INPUT_COLUMNS`
- target: `fault_name`
- 사용 feature: `target_service`, `severity`
- leakage 방지를 위해 사용하지 않는 열: `fault_id`, `trial`, `fault_name`, `injection_method`, `expected_root_cause`, `affected_components`, `primary_symptoms`, `expected_metrics`, `expected_log_patterns`, `expected_recovery_action`
- 출력:
  - `baselines/results/baseline_naive/baseline_naive_split.csv`
  - `baselines/results/baseline_naive/baseline_naive_predictions.csv`
  - `baselines/results/baseline_naive/baseline_naive_metrics.md`
  - `baselines/results/baseline_naive/baseline_naive_failures.md`
  - `baselines/results/baseline_naive/baseline_naive_manifest.json`

### 재현 명령

```bash
python3 -m baselines.baseline_naive --config baselines/configs/baseline_naive.json
python3 -m baselines.evaluate_baseline \
  --predictions baselines/results/baseline_naive/baseline_naive_predictions.csv \
  --output baselines/results/baseline_naive/baseline_naive_metric_table.md
```

이 baseline은 train split의 최빈 `fault_name`만 예측한다. balanced multi-class RCA에서 낮은 점수가 정상이며, 향후 방법론이 이 기준선을 넘지 못하면 연구 주장의 최소 요건을 만족하지 못한다.

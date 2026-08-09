# baseline_naive metric table

| metric | value |
|---|---:|
| seed | 42 |
| train_rows | 48 |
| test_rows | 12 |
| learned_majority_label | `CPUThrottle` |
| majority_label_train_count | 4 |
| accuracy | 0.0833 |
| macro_recall | 0.0833 |
| correct | 1/12 |

해석: 이 baseline은 train split의 최빈 fault_name만 예측한다. balanced multi-class RCA에서 낮은 점수가 정상이며, 향후 방법이 이 기준선을 넘지 못하면 논문 주장은 성립하기 어렵다.

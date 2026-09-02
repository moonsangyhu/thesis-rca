# baseline_runtime_keyword failure cases

## Failure 1: F1 trial 4

### 입력
- raw context: `results/raw_v2_2/F1_t4_C1_A_20260620_145951.json`
- input_target_service: `productcatalogservice`
- input_severity: `high`
- matched_rule: `no_rule_matched`
- used evidence: runtime-observability context only (`C1_A`) — no GitOps/RAG/LLM response/ground-truth text

### 예측 / 정답
- prediction: `Unknown`
- ground truth: `OOMKilled`

### 실패 원인 가설
- 단순 keyword rule은 cascade symptom과 root cause를 구분하지 못한다.
- 여러 장애가 공통으로 `timeout`, `0 endpoints`, `BackOff`를 만들기 때문에 rule ordering에 민감하다.
- 이 실패는 LLM/GitOps 방법이 넘어야 할 '증거 해석'의 최소 난점을 보여준다.

## Failure 2: F11 trial 4

### 입력
- raw context: `results/raw_v2_2/F11_t4_C1_A_20260622_001458.json`
- input_target_service: `worker03`
- input_severity: `medium`
- matched_rule: `no_rule_matched`
- used evidence: runtime-observability context only (`C1_A`) — no GitOps/RAG/LLM response/ground-truth text

### 예측 / 정답
- prediction: `Unknown`
- ground truth: `NetworkDelay`

### 실패 원인 가설
- 단순 keyword rule은 cascade symptom과 root cause를 구분하지 못한다.
- 여러 장애가 공통으로 `timeout`, `0 endpoints`, `BackOff`를 만들기 때문에 rule ordering에 민감하다.
- 이 실패는 LLM/GitOps 방법이 넘어야 할 '증거 해석'의 최소 난점을 보여준다.

## Failure 3: F12 trial 2

### 입력
- raw context: `results/raw_v2_2/F12_t2_C1_A_20260622_003437.json`
- input_target_service: `worker02`
- input_severity: `high`
- matched_rule: `no_rule_matched`
- used evidence: runtime-observability context only (`C1_A`) — no GitOps/RAG/LLM response/ground-truth text

### 예측 / 정답
- prediction: `Unknown`
- ground truth: `NetworkLoss`

### 실패 원인 가설
- 단순 keyword rule은 cascade symptom과 root cause를 구분하지 못한다.
- 여러 장애가 공통으로 `timeout`, `0 endpoints`, `BackOff`를 만들기 때문에 rule ordering에 민감하다.
- 이 실패는 LLM/GitOps 방법이 넘어야 할 '증거 해석'의 최소 난점을 보여준다.

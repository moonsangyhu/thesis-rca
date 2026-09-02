# baseline_naive failure cases

## Failure 1: F1 trial 4

### 입력
- target_service: `productcatalogservice`
- severity: `high`
- 사용 feature: `target_service`, `severity` only
- 제외 feature(leakage 방지): `fault_id, trial, fault_name, injection_method, expected_root_cause, affected_components, primary_symptoms, expected_metrics, expected_log_patterns, expected_recovery_action`

### 예측 / 정답
- prediction: `CPUThrottle`
- ground truth: `OOMKilled`
- expected_root_cause: Container productcatalogservice memory exceeded 16Mi limit when loading full catalog into memory

### 실패 원인 가설
- global-majority baseline은 입력 증상·메트릭·로그를 읽지 않고 train split 최빈 라벨만 반복한다.
- balanced fault taxonomy에서는 대부분의 non-majority fault를 구조적으로 틀린다.
- 따라서 이 실패는 구현 버그라기보다 baseline의 의도된 하한 성능을 보여준다.

## Failure 2: F10 trial 4

### 입력
- target_service: `boutique`
- severity: `high`
- 사용 feature: `target_service`, `severity` only
- 제외 feature(leakage 방지): `fault_id, trial, fault_name, injection_method, expected_root_cause, affected_components, primary_symptoms, expected_metrics, expected_log_patterns, expected_recovery_action`

### 예측 / 정답
- prediction: `CPUThrottle`
- ground truth: `ResourceQuota`
- expected_root_cause: Only 3 Services allowed in namespace; remaining Services cannot be created

### 실패 원인 가설
- global-majority baseline은 입력 증상·메트릭·로그를 읽지 않고 train split 최빈 라벨만 반복한다.
- balanced fault taxonomy에서는 대부분의 non-majority fault를 구조적으로 틀린다.
- 따라서 이 실패는 구현 버그라기보다 baseline의 의도된 하한 성능을 보여준다.

## Failure 3: F11 trial 4

### 입력
- target_service: `worker03`
- severity: `medium`
- 사용 feature: `target_service`, `severity` only
- 제외 feature(leakage 방지): `fault_id, trial, fault_name, injection_method, expected_root_cause, affected_components, primary_symptoms, expected_metrics, expected_log_patterns, expected_recovery_action`

### 예측 / 정답
- prediction: `CPUThrottle`
- ground truth: `NetworkDelay`
- expected_root_cause: 300ms delay with normal distribution jitter on worker03

### 실패 원인 가설
- global-majority baseline은 입력 증상·메트릭·로그를 읽지 않고 train split 최빈 라벨만 반복한다.
- balanced fault taxonomy에서는 대부분의 non-majority fault를 구조적으로 틀린다.
- 따라서 이 실패는 구현 버그라기보다 baseline의 의도된 하한 성능을 보여준다.

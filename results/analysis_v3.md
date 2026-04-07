# V3 실험 결과 분석 리포트

- **실험 버전**: V3 (CoT + Harness: Evidence Verification + Evaluator + Retry Loop)
- **모델**: gpt-4o-mini (OpenAI)
- **수행 일시**: 2026-04-07 15:36 ~ 21:18 (약 5시간 42분)
- **규모**: System A/B 각 50 trials (fault 10종 x trial 5회), 총 100건

---

## 1. 버전별 전체 정확도 비교

| 버전 | System A | System B | B-A 격차 |
|------|----------|----------|----------|
| V1 (CoT + 힌트) | 30.0% (15/50) | 84.0% (42/50) | +54.0pp |
| V2 (CoT, 힌트 제거) | 26.0% (13/50) | 42.0% (21/50) | +16.0pp |
| V3 (CoT + Harness) | 30.0% (15/50) | 40.0% (20/50) | +10.0pp |

**추세 요약**

- V1 -> V2: 힌트 제거로 System B 84% -> 42%로 42pp 하락
- V2 -> V3: Harness 추가 후 System A 26% -> 30%(+4pp), System B 42% -> 40%(-2pp). 유의미한 개선 없음
- B-A 격차: V1(54pp) -> V2(16pp) -> V3(10pp)로 지속 축소

---

## 2. V3 Fault별 정확도

| Fault | 장애 유형 | A (%) | B (%) | B-A |
|-------|-----------|-------|-------|-----|
| F1 | OOMKilled | 20 | 20 | 0pp |
| F2 | CrashLoopBackOff | 20 | 20 | 0pp |
| F3 | ImagePullBackOff | 40 | 20 | -20pp |
| F4 | NodeNotReady | 0 | 0 | 0pp |
| F5 | PVCPending | 40 | 60 | +20pp |
| F6 | NetworkPolicy | 0 | 40 | +40pp |
| F7 | CPUThrottle | 60 | 60 | 0pp |
| F8 | ServiceEndpoint | 20 | 40 | +20pp |
| F9 | SecretConfigMap | 60 | 80 | +20pp |
| F10 | ResourceQuota | 40 | 60 | +20pp |

### V1/V2/V3 전체 버전 fault별 비교

| Fault | 장애 유형 | V1_A | V1_B | V2_A | V2_B | V3_A | V3_B |
|-------|-----------|------|------|------|------|------|------|
| F1 | OOMKilled | 20 | 60 | 40 | 40 | 20 | 20 |
| F2 | CrashLoopBackOff | 60 | 100 | 0 | 40 | 20 | 20 |
| F3 | ImagePullBackOff | 40 | 80 | 40 | 40 | 40 | 20 |
| F4 | NodeNotReady | 0 | 60 | 0 | 0 | 0 | 0 |
| F5 | PVCPending | 100 | 100 | 20 | 20 | 40 | 60 |
| F6 | NetworkPolicy | 0 | 60 | 20 | 40 | 0 | 40 |
| F7 | CPUThrottle | 0 | 100 | 0 | 60 | 60 | 60 |
| F8 | ServiceEndpoint | 0 | 80 | 20 | 40 | 20 | 40 |
| F9 | SecretConfigMap | 0 | 100 | 60 | 60 | 60 | 80 |
| F10 | ResourceQuota | 80 | 100 | 60 | 80 | 40 | 60 |

---

## 3. V3 Harness 효과 분석

### 3-1. Retry 발생 분포

전체 100건 중 retry 발생: 44건 (44.0%)

| retry_count | 전체 | System A | System B |
|-------------|------|----------|----------|
| 0 | 56 | 32 | 24 |
| 1 | 28 | 9 | 19 |
| 2 | 16 | 9 | 7 |

System B에서 retry 발생 비율(52.0%)이 System A(36.0%)보다 높음.

### 3-2. Retry와 정확도

| System | retry=0 정확도 | retry>0 정확도 | 변화 |
|--------|---------------|---------------|------|
| A | 34.4% (11/32) | 22.2% (4/18) | **-12.2pp** |
| B | 25.0% (6/24) | 53.8% (14/26) | **+28.8pp** |

System B에서 retry가 발생한 케이스의 정확도(53.8%)가 retry 없는 케이스(25.0%) 대비 28.8pp 높다. Evaluator가 오답을 감지하고 재시도를 유도하는 효과가 System B에서 유효하게 작동. 반면 System A는 retry 시 정확도 하락(-12.2pp) -- 관측 신호만으로는 retry로 진단을 개선할 추가 근거 부족.

### 3-3. Faithfulness Score

전체 100건 모두 faithfulness_score = 1.0 (분산 = 0). keyword matching 기반 Evidence Verification이 실질적 필터링을 수행하지 않음. 상수 수렴으로 정보 가치 없음.

### 3-4. Evaluator 점수와 정답률 상관관계

| 지표 | 전체 Pearson r | System A | System B |
|------|---------------|----------|----------|
| eval_overall_score <-> correct | -0.020 | +0.315 | -0.296 |

eval_overall_score 88%가 8점대에 집중 (변별력 없음). System B에서 역상관(r=-0.296)이 관찰되어, Evaluator 점수는 진단 정확성의 신뢰할 만한 예측 변수로 기능하지 못함.

| 평가 항목 | System A | System B |
|-----------|----------|----------|
| eval_evidence_grounding | 8.96 | 9.02 |
| eval_diagnostic_logic | 8.04 | 8.06 |
| eval_differential_completeness | 7.18 | 7.14 |
| eval_confidence_calibration | 7.82 | 8.00 |
| eval_overall_score | 8.00 | 8.05 |

A/B 간 점수 차이 최대 0.18점으로 미미. Evaluator가 두 시스템 출력을 사실상 동등하게 평가.

---

## 4. System A vs B 차이 분석 (GitOps 컨텍스트 효과)

### GitOps 효과가 있는 fault 유형 (B > A)
- **F6(NetworkPolicy)**: +40pp -- NetworkPolicy manifest 변경 이력이 RAG에서 검색
- **F9(SecretConfigMap)**: +20pp -- Secret/ConfigMap 추가/삭제 이력이 증거 체인에 포함
- **F5(PVCPending)**: +20pp -- StorageClass/PVC 설정 변경 이력 활용
- **F8(ServiceEndpoint)**: +20pp -- Service selector/targetPort 변경 이력 추적
- **F10(ResourceQuota)**: +20pp -- ResourceQuota 설정 이력 참조

### GitOps 효과가 없는 fault 유형
- **F4(NodeNotReady)**: A=B=0% -- 노드 레벨 장애는 GitOps 이력에 미반영
- **F1(OOMKilled)**, **F2(CrashLoopBackOff)**: A=B=20% -- 런타임 장애, manifest 이력보다 실시간 메트릭이 유효

### Prompt Token 차이
System B 평균 prompt token(5,847)이 System A(3,980) 대비 +46.9%. GitOps/RAG 컨텍스트 추가에 따른 입력 증가 확인되나 비례적 정확도 향상은 없음.

---

## 5. 통계 검정

### McNemar Test (V3 System A vs B, paired)

| | B=1 | B=0 |
|-|-----|-----|
| **A=1** | 11 | 4 |
| **A=0** | 9 | 26 |

- McNemar test p-value: **0.2668** (유의하지 않음)

### Wilcoxon Signed-Rank Test

| 비교 | statistic | p-value | 결론 |
|------|-----------|---------|------|
| V3 A vs B (fault별) | 3.5 | 0.1400 | 유의하지 않음 |
| V1B vs V2B | 0.00 | **0.002** | 유의함 (V1->V2 하락 확인) |
| V2B vs V3B | 10.50 | 1.000 | 유의하지 않음 (변화 없음) |

---

## 6. 비용 및 레이턴시

| 항목 | System A | System B | 전체 |
|------|----------|----------|------|
| 평균 latency | 16,575ms | 18,603ms | 17,589ms |
| 평균 prompt tokens | 3,980 | 5,847 | 4,914 |
| 평균 completion tokens | 1,103 | 1,180 | 1,141 |
| 추정 비용 합계 | $0.063 | $0.079 | $0.142 |

V2 대비: latency +114%, completion tokens +151%

---

## 7. 핵심 발견

1. **Harness는 전체 정확도를 유의미하게 개선하지 못함** -- V3B 40% vs V2B 42% (Wilcoxon p=1.000)
2. **Retry는 System B에서만 효과적** -- B: +28.8pp, A: -12.2pp. GitOps 컨텍스트가 있을 때만 retry가 진단 개선
3. **Evaluator 점수가 정답 예측 불가** -- 8점대 집중, System B에서 역상관
4. **Faithfulness Score 상수 수렴** -- keyword matching 기반 evidence verification의 한계
5. **GitOps 효과는 fault 유형 의존적** -- manifest 관련 fault(F5,F6,F8,F9,F10)에서 B 우위, 런타임/노드 장애(F1,F2,F4)에서 무효
6. **V1 B=84%는 힌트 의존** -- 힌트 없는 환경에서 GitOps 순수 기여는 10-16pp 수준

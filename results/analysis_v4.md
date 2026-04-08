# V4 실험 결과 분석 (40/50 trials, 부분 완료)

> 분석일: 2026-04-08
> 상태: F3(2/5), F5(0/5), F10(3/5) 미완 — Prometheus port-forward 재시작 실패

## 1. 전체 성능 요약

| 버전 | System A | System B | B-A 격차 |
|------|----------|----------|---------|
| V3 (베이스라인) | 30.0% (15/50) | 40.0% (20/50) | +10.0pp |
| **V4 (부분)** | **20.0% (8/40)** | **32.5% (13/40)** | **+12.5pp** |
| 변화 | -10.0pp | -7.5pp | +2.5pp |

## 2. Fault별 정확도 비교 (V3 vs V4)

| Fault | 장애 유형 | V3_A | V3_B | V4_A | V4_B | B 변화 |
|-------|-----------|------|------|------|------|--------|
| F1 | OOMKilled | 20% | 20% | 20% | 20% | 0pp |
| F2 | CrashLoopBackOff | 20% | 20% | 20% | 40% | +20pp |
| F3 | ImagePullBackOff | 40% | 20% | 50%* | 50%* | +30pp* |
| F4 | NodeNotReady | 0% | 0% | 0% | 0% | 0pp |
| F5 | PVCPending | 40% | 60% | — | — | 측정 불가 |
| F6 | NetworkPolicy | 0% | 40% | 0% | **0%** | **-40pp** |
| F7 | CPUThrottle | 60% | 60% | 20% | 60% | 0pp (A -40pp) |
| F8 | ServiceEndpoint | 20% | 40% | 20% | 40% | 0pp |
| F9 | SecretConfigMap | 60% | 80% | 40% | **40%** | **-40pp** |
| F10 | ResourceQuota | 40% | 60% | 33%* | 67%* | +7pp* |

*F3, F10은 완료된 trial 기준 (각 2/5, 3/5)

## 3. 하락 원인 분석

### 3-1. Fault Layer Classification의 "분류 잠금(Classification Lock-in)"

**가장 핵심적인 하락 원인.** Layer 분류 단계가 한 번 오분류되면 이후 추론이 고착됨.

- **F1**: 5/5 trial에서 DiskPressure로 집중 오분류. Fault Layer가 k8s-worker03 DiskPressure를 Layer 1(Infrastructure)로 분류 → OOMKilled 신호 무시
- **F6**: 5/5 trial에서 Service/Endpoint로 오분류. NetworkPolicy 신호보다 "endpoints=0" 신호가 먼저 분류됨
- **F9**: 3/5 trial에서 DiskPressure 오분류. Secret/ConfigMap 신호가 있음에도 DiskPressure가 Infrastructure 레이어로 잘못 분류

V1의 힌트 문제와 유사한 메커니즘: 프롬프트 내 구체적 증상 키워드가 LLM 진단을 특정 방향으로 유도.

### 3-2. Context Reranking의 GitOps 컨텍스트 과도 필터링

"GitOps NOT READY only" 필터가 V3에서 효과적이었던 NetworkPolicy, SecretConfigMap 관련 commit diff를 제외.
- F6 B: 40% → 0% (-40pp)
- F9 B: 80% → 40% (-40pp)

### 3-3. 3변수 동시 변경으로 원인 분리 불가

Context Reranking, Fault Layer, Harness 간소화를 동시에 변경하여 개별 영향 측정 불가능.

## 4. Retry 패턴 (V3 vs V4)

| 항목 | V3 | V4 |
|------|----|----|
| System A retry | 활성 | **비활성** |
| System B retry 발생률 | 52.0% | 62.5% |
| System B retry 2회 | 14.0% | 25.0% |

V4에서 retry 비율이 증가했으나, 잘못된 방향의 진단을 반복 개선하는 효과만 발생.

## 5. V5를 위한 핵심 교훈

1. **Fault Layer Classification 제거 또는 재설계**: "분류 잠금" 현상이 V4 하락의 주요 원인
2. **GitOps 컨텍스트 필터링 보수적 적용**: NOT READY만 포함하면 핵심 변경 이력 누락
3. **단일 변수 변경 원칙 준수**: 3가설 병렬 프레임워크 활용
4. **Prometheus port-forward 안정성 강화**: F5 전체 누락 방지
5. **Evaluator 근본 개선 필요**: 8점대 집중 + 정답률 역상관 문제 미해결

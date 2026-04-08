# V6 실험 결과 분석 리포트

**실험 버전**: V6 (SOP-Guided Diagnosis Prompt)
**모델**: gpt-4o-mini (고정)
**수행 일시**: 2026-04-08
**규모**: System A/B 각 50 trials (fault 10종 × trial 5회), 총 100건

## 1. 성공 기준 평가

| 기준 | 목표 | V6 실측 | 판정 |
|------|------|---------|------|
| Primary: System B 정확도 | ≥ 46% | **38%** (19/50) | **미달** |
| Secondary: F1-F4 중 2개 향상 | +20pp 이상 2개 | F2만 +40pp | **미달** |
| Safety: F9/F10 하락 ≤ -10pp | ≤ -10pp | F9: **-60pp** | **위반** |

**종합 판정: 실패** — Primary 기준 미달. V3 대비 B -2pp, A -4pp 하락.

## 2. 전체 정확도 버전 비교

| 버전 | System A | System B | B-A 격차 |
|------|----------|----------|----------|
| V1 (CoT + 힌트) | 30% (15/50) | 84% (42/50) | +54pp |
| V2 (CoT, 힌트 제거) | 26% (13/50) | 42% (21/50) | +16pp |
| V3 (CoT + Harness) | 30% (15/50) | 40% (20/50) | +10pp |
| **V6 (SOP + Harness)** | **26% (13/50)** | **38% (19/50)** | **+12pp** |

B-A 격차는 V3(+10pp) → V6(+12pp) 소폭 확대. 절대 정확도는 A·B 모두 하락.

## 3. Fault별 상세 비교

| Fault | 장애 유형 | V6 A | V6 B | V3 A | V3 B | B 변화 |
|-------|-----------|------|------|------|------|--------|
| F1 | OOMKilled | 20% (1/5) | 20% (1/5) | 20% | 20% | → |
| F2 | CrashLoopBackOff | 20% (1/5) | **60% (3/5)** | 20% | 20% | **+40pp** |
| F3 | ImagePullBackOff | 40% (2/5) | 40% (2/5) | 40% | 20% | **+20pp** |
| F4 | NodeNotReady | 0% (0/5) | 0% (0/5) | 0% | 0% | → |
| F5 | PVCPending | 20% (1/5) | 20% (1/5) | 40% | 60% | **-40pp** |
| F6 | NetworkPolicy | 0% (0/5) | 0% (0/5) | 0% | 40% | **-40pp** |
| F7 | CPUThrottle | 40% (2/5) | **100% (5/5)** | 60% | 60% | **+40pp** |
| F8 | ServiceEndpoint | 20% (1/5) | **60% (3/5)** | 20% | 40% | **+20pp** |
| F9 | SecretConfigMap | 40% (2/5) | 20% (1/5) | 60% | 80% | **-60pp** |
| F10 | ResourceQuota | 60% (3/5) | 60% (3/5) | 40% | 60% | → |
| **합계** | | **26% (13/50)** | **38% (19/50)** | **30%** | **40%** | **-2pp** |

## 4. SOP 효과 분석

### 개선된 fault (SOP Step이 직접 매칭)

**F7 CPUThrottle (+40pp, 60%→100%)**: SOP Step 5 "CPU throttling > 50%" 체크가 완벽 작동. 5/5 정답, retry가 3/5에서 발생하여 모두 정답 전환.

**F2 CrashLoopBackOff (+40pp, 20%→60%)**: SOP Step 2 "CrashLoopBackOff" 분기 + retry 복합 효과. 5/5 모두 retry 발생, 3건 정답 전환.

**F8 ServiceEndpoint (+20pp, 40%→60%)**: SOP Step 3 "0 endpoints" 효과적. 3/5 정답.

**F3 ImagePullBackOff (+20pp, 20%→40%)**: SOP Step 2 "ImagePullBackOff" 분기 활성화.

### 악화된 fault (Step 3 흡수 문제)

**F9 SecretConfigMap (-60pp, 80%→20%)**: V3 최강 fault가 급락.
- SOP의 단계별 조기 종료 구조가 DiskPressure noise에 취약
- CreateContainerConfigError를 감지해도 근본 원인(Secret/ConfigMap 누락) 특정 실패

**F6 NetworkPolicy (-40pp, 40%→0%)**: 5/5 모두 "Service Endpoint Mismatch/Connectivity Issue"로 오진.
- 경로: Step 1(노드 정상) → Step 2(포드 정상) → Step 3(0 endpoints 발견) → "Service Endpoint 문제" 확진
- NetworkPolicy 차단이 유발한 0 endpoints를 Step 3에서 흡수

**F5 PVCPending (-40pp, 60%→20%)**: 동일한 Step 3 흡수 패턴.

### Step 3 흡수 문제 (핵심 실패 요인)

SOP의 선형 3단계 구조(Node → Pod → Service)에서 Step 1·2를 통과하면 Step 3의 "0 endpoints" 신호가 최종 원인으로 확진됨. **근본 원인이 NetworkPolicy, PVC, Secret으로 달라도 증상(0 endpoints)이 동일하면 조기 확진**되는 구조적 결함.

## 5. Retry 효과 분석

| System | retry=0 정확도 | retry>0 정확도 | delta |
|--------|----------------|----------------|-------|
| V6 A | 24.3% (9/37) | 30.8% (4/13) | +6.4pp |
| V6 B | 29.0% (9/31) | 52.6% (10/19) | **+23.6pp** |
| V3 B (참고) | 25.0% | 53.8% | +28.8pp |

V6 B retry 효과(+23.6pp)는 V3 B(+28.8pp)와 유사 수준 유지.

## 6. 비용 및 레이턴시

| 항목 | V6 A | V6 B | V3 A | V3 B |
|------|------|------|------|------|
| 평균 latency | 17,456ms | 17,035ms | 16,575ms | 18,603ms |
| 평균 prompt tokens | 4,258 | 6,033 | 3,980 | 5,847 |
| 평균 completion tokens | 1,042 | 1,034 | 1,103 | 1,180 |

SOP 프롬프트 길이 증가로 prompt tokens +7%. 조기 확진으로 completion tokens -12%.

## 7. 핵심 발견 요약

1. **SOP 효과 양면성**: 개선(F7 +40, F2 +40, F8 +20, F3 +20 = +120pp) vs 악화(F9 -60, F6 -40, F5 -40 = -140pp). 악화가 개선을 상회하여 전체 -2pp.

2. **Step 3 흡수 문제가 핵심 실패 요인**: "0 endpoints"가 다양한 근본 원인의 공통 증상으로, SOP가 증상에서 멈추고 원인까지 역추적하지 못함.

3. **SOP Early Stopping이 noise에 취약**: F9에서 DiskPressure noise → Step 1 조기 확진.

4. **Retry는 SOP 환경에서도 유효**: B retry>0 정확도 52.6%.

5. **B-A 격차 소폭 확대**: V3 +10pp → V6 +12pp. SOP가 GitOps 컨텍스트 활용을 강화.

## 8. V7 방향 제안

**베이스라인**: V3(B=40%) 유지 — V6(B=38%)보다 우수.

### V7-A (권고): Step 3에 근본 원인 역추적 강화
- "0 endpoints 감지 시 원인 분기" 추가: (a) NetworkPolicy 차단, (b) PVC/Storage 문제, (c) Secret/ConfigMap 누락
- "0 endpoints는 증상이지 원인이 아니다 — 반드시 원인을 역추적하라" 명시적 지시

### V7-B: 조기 종료 조건 강화
- Step 1 확진에 "복합 증거 2개 이상 필요" 규칙 추가
- noise false positive 방지

### V7-C: SOP + V3 하이브리드
- F7/F8/F2/F3에만 SOP 적용, 나머지는 V3 자유 CoT 유지
- fault-specific prompt switching

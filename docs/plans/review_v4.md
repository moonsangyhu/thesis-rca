# V4 실험 계획서 리뷰

**리뷰 대상**: `docs/plans/experiment_plan_v4.md`
**리뷰 일시**: 2026-04-07
**리뷰어**: @hypothesis-reviewer

---

## 1. 전반적 평가

V4 계획서는 V3 실험 결과를 정밀하게 분석하고, 구체적 근거에 기반하여 세 가지 변경사항을 도출한 점에서 높은 수준의 계획이다. 특히 V3 컨텍스트 구조를 비율/위치 단위로 분석한 것(3.3절)과, "Lost in the Middle" 선행 연구를 인용한 이론적 근거는 설득력이 있다. 그러나 아래 관점에서 보완이 필요하다.

---

## 2. 방법론 비평: 단일 변수 분리 실패 (핵심 문제)

### 2-1. 세 가지 변경을 동시에 도입하는 문제

V4는 V3 대비 최소 세 가지 독립 변수를 동시에 변경한다:

1. **컨텍스트 리랭킹**: 섹션 순서 변경 + 정상 pod/node 필터링 + Events 축소(30->15)
2. **Fault Layer 프롬프트**: Step 0 계층적 제거 프레임워크 추가
3. **하네스 간소화**: Evidence Verification 제거 + System A retry 비활성화

만약 V4 B 정확도가 45%로 향상된다면, 이것이 (a) 컨텍스트 순서 때문인지, (b) 정보 필터링(정상 pod 제거) 때문인지, (c) Fault Layer 프롬프트 때문인지, (d) Evidence Verification 제거 때문인지 분리할 수 없다. 이는 V3 리뷰에서 "Harness는 단일 변수가 아니다"라고 지적한 것과 동일한 구조적 문제가 반복되고 있다.

**권고**: 최소한 사후 분석에서 변수 분리를 시도할 수 있는 설계를 사전에 포함해야 한다. 예를 들어:
- V4 raw JSON에서 Anomaly Summary 섹션의 길이/내용을 기록하여, "정보량 변화"와 "순서 변화"의 상대적 기여를 추정
- retry=0인 trial만 추출하여 하네스 간소화 효과를 분리
- 각 fault type에 대해 "Layer 분류가 정확했는가"를 수동 코딩하여 프롬프트 효과를 독립 분석

### 2-2. 컨텍스트 리랭킹의 실제 구성

계획서는 "순서 변경"으로 설명하지만, 실제 변경은 순서만이 아니다:

- **정보 필터링**: 정상 pod/node 제거, Events 30->15개 축소, Ready 상태 GitOps 제거
- **정보 재구성**: `_build_abnormal_pods()`, `_build_abnormal_nodes()` 신규 메서드
- **정보량 변화**: 전체 컨텍스트 20-30% 감소 예상

이것은 "컨텍스트 순서 변경(reranking)"이 아니라 "컨텍스트 재설계(redesign)"에 해당한다. 정확도가 향상되더라도 "순서 때문"이라고 결론 내리기 어려우며, "노이즈 제거" 효과일 수 있다. 논문에서 이 변경을 기술할 때 "context reranking"이라는 용어 사용에 주의가 필요하다.

**대안 가설 A**: 정확도 향상이 순서 변경이 아니라, 정상 pod/node 제거에 의한 노이즈 감소 때문일 수 있다.

---

## 3. 교란 변수 식별

### 3-1. 컨텍스트 길이의 교란 효과

V4는 컨텍스트를 20-30% 축소할 것으로 예상한다. "Lost in the Middle" 연구(Liu et al., 2023)에 따르면 성능 저하는 컨텍스트가 길 때 중간 정보가 묻히는 현상이다. 그러나 gpt-4o-mini의 V3 평균 prompt tokens(System B 5,847)은 모델 컨텍스트 윈도우(128K)의 약 4.6%에 불과하다. 이 길이에서 "Lost in the Middle" 효과가 실제로 발생하는지는 의문이다.

**권고**: V4 결과에서 컨텍스트 길이(prompt_tokens)와 정확도의 상관관계를 분석하여, 길이 축소 자체가 효과의 원인인지 점검해야 한다.

### 3-2. Fault Layer 프롬프트의 정보 누출(information leakage) 위험

Fault Layer 프롬프트(Step 0)는 Layer별로 체크할 구체적 증상을 열거한다:

> "Layer 2: Any pod in ImagePullBackOff? CreateContainerConfigError? PVC Pending? Service endpoints=0? ResourceQuota exceeded?"

이 목록은 F1-F10 장애 유형의 증상을 거의 그대로 나열하고 있다. V1에서 "힌트 제거"로 84%->42%로 하락한 경험을 고려하면, Fault Layer 프롬프트가 사실상 "반구조화된 힌트(semi-structured hint)"로 기능할 수 있다.

**대안 가설 B**: Fault Layer 프롬프트의 효과가 "계층적 제거 로직"이 아니라, 체크리스트에 포함된 증상 키워드가 힌트로 작용하는 것일 수 있다.

**권고**: Layer 체크리스트에서 구체적 증상명(ImagePullBackOff, PVC Pending 등)을 제거하고, 추상적 기술("image-related errors", "storage issues")로 대체하는 것을 고려해야 한다.

### 3-3. System A/B 간 비대칭 변경

컨텍스트 리랭킹은 System A와 B 모두에 적용되지만, 변경의 영향은 비대칭적이다:
- System B는 "Correlated Changes" 섹션이 신설되어 상단에 배치됨
- System A에는 이 섹션이 없음

따라서 B-A 격차 변화가 "GitOps 효과"인지 "Correlated Changes 섹션의 위치 효과"인지 분리가 어렵다.

### 3-4. 이전 버전과의 비교 시 시점 효과

V4와 V3는 다른 시점에 실행된다. 클러스터 상태, 네트워크 지연, 노드 디스크 상태 등 환경 변수가 다를 수 있다.

---

## 4. 가설의 반증 가능성 검토

### 4-1. H1 반증 조건의 적절성

H1 반증 조건: "V4 B <= 40%이면 기각" — 적절하다.

다만 "성공" 기준의 "V4 B >= 48% (Wilcoxon p < 0.05)"에서, n=10에서 medium effect를 탐지할 검정력(power)은 약 0.30-0.40으로 0.80 기준에 크게 미달한다.

**권고**: H1 성공 기준을 "효과 크기(effect size) + 방향 일관성"으로 보완. 예: "10개 fault 중 7개 이상에서 B 정확도 개선 + Cohen's r >= 0.3"

### 4-2. H2 반증 조건의 문제

H2 반증 조건: "F4 B = 0%이고 F6 A = 0%이면 기각" — 너무 관대하다.

5 trials 중 1회 정답(20%)은 우연(base rate 10%)으로도 가능. Fisher exact test에서 0/5 vs 1/5의 차이는 p > 0.5.

**권고**: 기저 확률을 명시하고, "방향성 + 질적 분석(raw JSON에서 Layer 분류가 정확했는가)"으로 평가하는 것이 현실적.

### 4-3. H4 퇴행 감시

F3(ImagePullBackOff)도 감시 대상에 포함 필요. K8s Events의 "Failed to pull image" 메시지가 핵심 단서인데, Events 하단 이동으로 추가 하락 위험.

---

## 5. 리스크 분석 보완

### 5-1. 누락된 리스크: Anomaly Summary의 F7 누락

F7(CPU Throttle)에서 pod가 Running이고 container도 ready이지만 성능이 저하된 상태. `_build_abnormal_pods()` 필터에 해당하지 않아 Anomaly Summary에서 누락 가능.

**권고**: Metric Anomalies(CPU throttle 등)를 pod 상태와 독립적으로 상단에 배치.

### 5-2. 누락된 리스크: V4 전용 context_builder 구현 복잡도

`RCAContext.to_system_a_context()`와 `to_system_b_context()` 메서드가 순서를 하드코딩하고 있어, V4 전용 빌더의 구현 복잡도가 과소평가되었을 수 있다.

### 5-3. 누락된 리스크: Evaluator가 Fault Layer 형식을 이해하지 못함

Evaluator 프롬프트는 V3와 동일하므로 "Layer 분류가 정확한가"를 평가하지 않음. Layer 분류 오류가 retry를 trigger하지 않을 수 있다.

---

## 6. 대안 가설 종합

| 대안 가설 | 설명 | 검증 방법 |
|-----------|------|-----------|
| A. 노이즈 제거 효과 | 순서가 아니라 정상 pod/node 제거 때문 | prompt_tokens과 정확도 상관 분석 |
| B. 반구조화 힌트 효과 | Fault Layer 체크리스트가 힌트로 작용 | Layer 분류 정확도 vs 최종 진단 정확도 분리 |
| C. LLM 비결정성 | 5-10pp 차이가 출력 변동성 범위 내 | bootstrap CI |
| D. Evidence Verification 제거 효과 | 제거가 retry 패턴 변화시킴 | retry 발생률 V3 vs V4 비교 |
| E. 컨텍스트 길이 감소 효과 | 짧은 컨텍스트가 유리 | prompt_tokens 4분위별 정확도 분석 |

---

## 7. 통계 검정 평가

### 7-1. Wilcoxon (n=10) 검정력 부족

n=10에서 medium effect size(r=0.3) 검정력은 약 0.30-0.40. 0.80 기준에 크게 미달.

**권고**:
1. Trial별 McNemar test(n=50)를 주 검정으로 승격
2. 효과 크기(Cohen's r)와 95% CI 필수 보고
3. Bootstrap paired difference CI 추가

### 7-2. Bonferroni 보정

주요 비교 3건에 Bonferroni 보정(alpha=0.017)은 V3 리뷰 권고를 반영한 좋은 개선.

---

## 8. "Lost in the Middle" 논거에 대한 반론

Liu et al.(2023)의 실험 조건과 V4의 차이:
1. **컨텍스트 길이**: Liu et al.은 수천-수만 토큰. V3 System B는 5,847 tokens으로 "middle"이 존재하기에 너무 짧을 수 있다
2. **태스크 유형**: Multi-document QA(단일 정답 검색) vs RCA(여러 신호 종합 추론)
3. **모델 세대**: 2023년 모델 기준. gpt-4o-mini(2024)는 positional bias 개선 가능성

---

## 9. 긍정적 평가

1. V3 데이터 기반 의사결정 (retry -12.2pp, faithfulness=1.0 상수)
2. V3 리뷰 권고 반영 (Bonferroni 보정, effect size 보고)
3. 퇴행 방어 설계 (H4)
4. 코드 독립성 (V4 전용 context_builder)
5. 비용 분석 정량화

---

## 10. 종합 판단

| 관점 | 평가 | 핵심 권고 |
|------|------|-----------|
| 구성 타당도 | 주의 필요 | 3개 변경 동시 도입. "context redesign"으로 명명 권고 |
| 내적 타당도 | 보통 | Fault Layer 힌트 효과, Anomaly Summary F7 누락 위험 |
| 외적 타당도 | V1-V3와 동일 | Online Boutique + gpt-4o-mini 한정 |
| 통계적 타당성 | 주의 필요 | n=10 Wilcoxon 검정력 부족. McNemar(n=50) 주 검정 승격 권고 |
| 대안 가설 | 중요 | 노이즈 제거, 힌트 효과, 길이 효과 — 사후 분리 분석 설계 필요 |

**결론**: **실험 진행을 권고하되**, (1) Fault Layer 프롬프트의 증상 키워드를 추상화하여 힌트 효과 최소화, (2) McNemar test(n=50)를 주 검정으로 승격, (3) 사후 변수 분리 분석 계획 사전 설계를 반영해야 한다.

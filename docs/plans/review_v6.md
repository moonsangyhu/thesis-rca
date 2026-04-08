# V6 실험 계획서 리뷰

> 리뷰일: 2026-04-08
> 리뷰어: hypothesis-reviewer agent
> 대상: V6 SOP-Guided Diagnosis Prompt (단일 변수: SYSTEM_PROMPT 교체)
> 베이스라인: V3 (System B 40%)

---

## 1. 방법론 비평

### 1-1. 긍정적 측면

- **단일 독립변수 설계의 엄밀성**: V4(3변수 동시 변경), V5(LLM 호출 횟수 변경)의 실패를 반성하여, SYSTEM_PROMPT 하나만 교체하는 최소 개입 설계. 이는 V3 이후 가장 깨끗한 실험 설계로 평가할 수 있다.
- **V3 인프라 완전 재사용**: Context Builder, Evaluator, Retry, RAG, Signal Collection을 V3과 동일하게 유지하여 변수 격리가 확보되었다.
- **문헌 근거의 명확성**: Flow-of-Action(WWW '25)의 SOP ablation 결과(54% -> 15%)를 근거로 제시한 것은 가설의 이론적 기반을 강화한다.
- **V4 분류 잠금 교훈의 직접 반영**: "If NO: Proceed to next step" 패턴으로 V4의 핵심 실패 원인을 구조적으로 회피하려는 의도가 명확하다.

### 1-2. 핵심 우려사항

**(1) "단일 변수"라는 주장의 실질적 검증이 필요하다**

표면적으로 SYSTEM_PROMPT만 변경되지만, SOP 프롬프트는 V3 CoT와 질적으로 다른 인지 전략을 요구한다. V3는 "가설 생성 -> 증거 매칭"이라는 귀추법(abduction) 기반이고, V6는 "조건 확인 -> 분기"라는 결정 트리(decision tree) 기반이다. 동일한 "SYSTEM_PROMPT"라는 변수명 아래 실질적으로 진단 패러다임이 전환된다. 이것이 교란이라기보다는 의도된 독립변수이므로, 논문에서 "프롬프트 교체"가 아닌 "진단 전략의 전환(CoT -> SOP)"으로 정확히 기술할 필요가 있다.

**(2) SOP 프롬프트에 정답이 내재(embedded)되어 있을 가능성**

SOP의 Step 2에 "OOMKilled -> Memory limit exceeded", "CrashLoopBackOff -> Application crash", "ImagePullBackOff -> Image pull failure", "CreateContainerConfigError -> Missing Secret or ConfigMap"이 명시되어 있다. 이는 10개 fault type 중 F1, F2, F3, F9를 거의 직접 매핑한다. 또한 Step 1의 "NotReady, DiskPressure"는 F4, F7을, Step 3의 "0 endpoints"는 F8을, Step 4의 "cilium drops"는 F6을, Step 5의 "ResourceQuota violations"는 F10을 매핑한다. Step 2의 "Pending"은 F5를 매핑한다.

결국 SOP가 10개 fault type 전부에 대한 진단 룩업 테이블(lookup table)로 기능할 수 있다. 이것이 "LLM의 진단 능력 향상"인가, 아니면 "프롬프트에 정답 힌트를 포함"한 것인가? V1에서 힌트 제공(84%)이 기각된 것과 유사한 위험이 있다.

**완화 가능성**: V1의 힌트는 "이번 장애는 X이다"라는 직접 힌트였고, V6의 SOP는 "이런 조건이면 X를 고려하라"는 조건부 안내이므로 성격이 다르다. 그러나 10개 fault가 모두 SOP에 매핑되므로, 미지(unseen) 장애에 대한 일반화 가능성은 낮다. 논문에서 이 제한점을 명시적으로 논의해야 한다.

**(3) Priority Rule의 잠재적 오진단 유도**

"Node > Pod > Service > Network > Resource" 우선순위는 다중 이상 상황에서 상위 레이어를 우선시한다. 그러나 실제 fault injection 시나리오에서는:

- F1(OOMKilled) injection 시 대상 서비스 외의 다른 pod에도 cascade failure가 발생하고, 동시에 node-level DiskPressure(V3 실험에서 관찰됨)가 공존할 수 있다.
- 이 경우 SOP는 Step 1에서 DiskPressure를 먼저 감지하고 "NODE-LEVEL fault"로 진단할 가능성이 있다. 실제 원인은 F1(OOMKilled)인데 F7(DiskPressure)로 오진단.

V4의 분류 잠금과 메커니즘이 다르지만, Priority Rule이 "조기 확정(early commitment)"을 유발하는 새로운 형태의 잠금을 만들 수 있다. V3 F1 t1의 실제 데이터를 보면, DiskPressure가 k8s-worker03에 존재했고 gpt-4o-mini는 이에 끌렸다(V4에서도 동일 패턴 재현).

---

## 2. V4 분류 잠금 위험: SOP의 조건부 진행은 진짜 lock-in을 방지하는가?

### V4 vs V6 메커니즘 비교

| 측면 | V4 Fault Layer | V6 SOP |
|------|---------------|--------|
| 정보 접근 | 분류 후 해당 레이어 정보만 제공 | 모든 정보 제공, 점검 순서만 안내 |
| 오류 복구 | 불가 (정보가 물리적으로 제거됨) | 가능 (다음 step 진행 가능) |
| 잠금 유형 | 정보 잠금 (hard lock) | 주의 잠금 (soft lock) |

V6는 V4의 "정보 잠금(hard lock)"을 확실히 회피한다. 그러나 "If YES: diagnose"라는 지시가 gpt-4o-mini에게 해당 step에서 진단을 확정하도록 유도할 수 있다. LLM이 Step 1에서 NodeNotReady 조건을 발견하면 "If YES" 분기로 진입하여 즉시 진단을 출력하고, Step 2 이하를 건너뛸 가능성이 있다.

**핵심 질문**: gpt-4o-mini가 "If YES: diagnose" 이후에도 나머지 step을 계속 확인하는가, 아니면 첫 번째 매칭에서 멈추는가? 이를 dry-run에서 반드시 검증해야 한다.

### 권고

- dry-run에서 **F1 t1(OOMKilled + DiskPressure 공존)** 케이스의 reasoning을 확인하여, Step 1에서 조기 종료되는지 Step 2까지 진행하는지 검증할 것.
- 만약 조기 종료 패턴이 관찰되면, Priority Rule을 "진단 전 모든 step을 확인한 후 최종 우선순위 적용"으로 수정하는 것을 고려할 것.

---

## 3. SOP 편향 위험: 특정 장애 유형에만 유리하고 다른 유형을 해치지 않는가?

### 3-1. SOP에 유리한 fault type (명시적 조건 매칭)

F1(OOMKilled), F3(ImagePullBackOff), F9(CreateContainerConfigError)는 SOP Step 2에 거의 1:1 매핑된다. 이들은 pod status에 명시적 키워드가 나타나므로 SOP 조건 매칭이 쉽다.

### 3-2. SOP에 불리할 수 있는 fault type

- **F2(CrashLoopBackOff)**: SOP Step 2에 매핑되지만, "Application crash or misconfiguration. Check logs for exit code"라는 안내가 충분한가? CrashLoop의 원인은 다양하고(exit code 1, port conflict, missing flag 등), SOP가 로그 분석까지 안내하지는 않는다. V3에서 F2의 실패 원인은 "CPU throttle과 혼동"인데, SOP가 이를 해결하려면 Step 2에서 CrashLoop을 확인한 후 Step 5의 CPU throttle을 무시해야 한다. 그러나 SOP의 순차 구조가 이를 보장하는가?

- **F4(NodeNotReady)**: Step 1에서 최우선 감지되어야 하나, 실제 signal collection에서 NotReady 상태가 명확히 수집되는지가 관건이다. V3에서 5/5 전부 실패한 것은 signal 자체의 문제일 수 있다. SOP가 아무리 좋아도 입력에 NotReady 신호가 약하면 Step 1에서 "NO"로 판정될 수 있다.

- **F8(ServiceEndpoint)**: 5개 trial의 injection 방식이 다양하다(selector 불일치, targetPort 오류, label 제거, readiness 실패, port mismatch). SOP Step 3의 "0 endpoints" 조건은 이 중 일부(selector, label)에만 적용된다. targetPort 오류(F8 t2)나 readiness 실패(F8 t4)에서는 endpoints > 0이므로 Step 3을 통과하여 놓칠 수 있다.

### 3-3. 기대치 과잉 추정 우려

계획서의 Fault별 예상 효과에서 F1의 기대치가 "20% -> 40%+"이다. 그러나 V3 F1의 실패 원인은 "shippingservice 노이즈에 주의 분산"이었다. SOP Step 2에서 OOMKilled 조건이 있더라도, 동시에 shippingservice의 CrashLoop도 Step 2에서 감지된다. 두 신호가 동일 step에서 경합할 때 SOP는 어떤 기준으로 선택하는가? Priority Rule은 step 간 우선순위이지, step 내 다중 신호 간 우선순위를 제공하지 않는다.

---

## 4. 통계적 검정력 분석

### 4-1. McNemar Test (주 검정)

V3_B=40%(20/50)에서 V6_B=46%(23/50)로 +6pp 차이를 검출하려 한다.

McNemar test는 불일치 쌍(discordant pairs)에 기반한다. V3에서 정답이고 V6에서 오답인 경우(b), V3에서 오답이고 V6에서 정답인 경우(c)만 사용한다.

- 최선의 시나리오: c=3, b=0 (V6가 3개 추가 정답, 기존 정답 유지) -> McNemar chi2 = 3.0, p = 0.083 (유의하지 않음)
- 현실적 시나리오: c=5, b=2 (V6가 5개 추가 정답, 2개 기존 정답 손실) -> McNemar chi2 = 9/7 = 1.29, p = 0.257

**n=50에서 +6pp 차이는 McNemar test로 유의성을 달성하기 극히 어렵다.** 최소 +12pp (6개 순증가) 이상이 필요하며, 이마저도 기존 정답의 손실이 없어야 한다.

### 4-2. 권고

- 효과 크기(effect size)와 95% 신뢰구간을 주 보고 지표로, p-value는 참고 지표로 제시하는 것이 현실적이다.
- fault type별 paired comparison(McNemar on 2x2 per fault)는 n=5로 무의미하므로 기술 통계만 보고할 것.
- 사전에 "실험의 탐색적(exploratory) 성격"을 명시하고, "프롬프트 전략의 방향성 확인"이 주 목적임을 기술할 것.

---

## 5. 대안 가설

SOP 교체 외에 같은 목표(System B 정확도 향상)를 달성할 수 있는 대안적 설명 또는 접근을 검토한다.

### 대안 1: SOP가 아닌 "체크리스트 효과"

SOP의 핵심 메커니즘이 "순서 강제"가 아니라, 단순히 "가능한 장애 유형을 명시적으로 나열"한 것(즉, 체크리스트)에서 오는 효과일 수 있다. V3의 "Consider common Kubernetes failure modes such as..."도 나열식이지만 추상적(resource exhaustion, configuration errors 등)인 반면, V6는 구체적(OOMKilled, CrashLoopBackOff, ImagePullBackOff 등)이다. 정확도 향상이 "SOP 구조" 때문인지 "구체적 키워드 나열" 때문인지 구분이 필요하다.

**검증 방법**: V3 프롬프트에 동일한 구체적 키워드를 나열하되 SOP 구조 없이 제공하는 대조 실험. 단, 이는 V6 이후 후속 실험으로 적합하다.

### 대안 2: 정확도 향상이 "노이즈 감소" 때문

SOP가 LLM의 출력 구조를 제약하여, V3에서 발생하던 "관련 없는 서비스에 대한 장황한 분석"을 억제하는 효과. 즉, 진단 능력 향상이 아니라 "주의 산만(distraction) 감소"에 의한 것일 수 있다.

### 대안 3: 프롬프트 길이/구조가 gpt-4o-mini의 JSON 출력 안정성에 영향

V3와 V6의 프롬프트 길이가 비슷하다고 하지만, SOP의 조건부 구조가 gpt-4o-mini의 instruction following 패턴에 더 적합할 수 있다. 이 경우 정확도 향상은 "진단 전략"이 아닌 "프롬프트-모델 호환성"에 의한 것이다.

### 대안 4: V3 대비 실질적 개선이 아닌 LLM 비결정성(stochasticity)

gpt-4o-mini의 temperature=0에서도 출력이 완전히 결정적이지 않다. +6pp(3/50 차이)는 비결정성 범위 내일 수 있다. V3를 동일 조건으로 재실행했을 때의 분산을 모르므로, V6 결과가 V3의 자연 분산 범위 내인지 판단하기 어렵다.

---

## 6. Flow-of-Action 논문 적용의 한계

### 6-1. 원논문과의 핵심 차이

| 측면 | Flow-of-Action (원논문) | V6 (적용) |
|------|------------------------|-----------|
| 아키텍처 | Multi-agent + Tool-use | Single-prompt |
| SOP 실행 | 에이전트가 각 step에서 실제 도구 호출 (API, CLI) | LLM이 텍스트 내에서 조건 판단 |
| 정보 수집 | Step별로 필요한 정보를 동적 수집 | 모든 정보가 사전에 컨텍스트로 제공 |
| SOP 커버리지 | 실제 운영 SOP (수백 개) | 5-step 단일 SOP |
| 보고 효과 | +28.5pp (35.5% -> 64.0%) | 목표 +6pp (40% -> 46%) |

### 6-2. 축소 적용의 구조적 한계

원논문에서 SOP의 효과가 큰 이유는 "각 step에서 도구를 호출하여 실시간으로 정보를 수집"하기 때문이다. 예를 들어 Step 1에서 node health를 확인하려면 `kubectl get nodes`를 실행한다. 반면 V6에서는 모든 정보가 이미 컨텍스트에 포함되어 있으므로, SOP의 "단계적 정보 수집" 이점이 사라진다.

V6에서 SOP가 제공하는 가치는 "정보 수집 안내"가 아닌 "정보 해석 안내(interpretation guide)"로 축소된다. 이는 원논문의 핵심 메커니즘과 다르므로, 기대 효과도 축소될 수 있다. +28.5pp에서 +6pp로 목표를 낮춘 것은 현실적이나, 실제로는 이마저도 달성이 어려울 수 있다.

### 6-3. 논문 기술 시 주의점

V6의 결과를 논문에 기술할 때, "Flow-of-Action의 SOP 기법을 적용했다"고 주장하기보다는 "Flow-of-Action에서 영감을 받은 조건부 진단 프롬프트를 설계했다"로 기술하는 것이 정확하다. 원논문의 multi-agent + tool-use 아키텍처를 single-prompt로 축소한 것은 본질적으로 다른 개입(intervention)이므로, 원논문의 효과 크기를 직접 인용하여 V6의 기대치를 정당화하는 것은 적절하지 않을 수 있다.

---

## 7. 교란 변수 식별

### 7-1. 클러스터 상태의 시간적 변동

V3과 V6는 서로 다른 시점에 실행된다. 클러스터의 baseline DiskPressure, 네트워크 상태, 잔여 리소스가 달라질 수 있다. V3 실험에서 관찰된 DiskPressure(k8s-worker03)가 V6 실험 시점에도 동일하게 존재하는지 확인이 필요하다.

### 7-2. SOP 내 Step 간 정보 불균형

Step 2(Pod Status)에 5개 하위 조건이 있고, Step 1/3/4/5는 각 1개 조건만 있다. 이로 인해 Step 2에 해당하는 fault type(F1, F2, F3, F5, F9)이 구조적으로 유리하고, Step 4(Network, F6)나 Step 5(Resource, F10)는 상대적으로 안내가 부족하다.

### 7-3. "Pending" 조건의 모호성

Step 2에서 "Pending -> Scheduling issue. Check PVC binding, ResourceQuota, node affinity"라고 안내한다. F5(PVCPending)와 F10(ResourceQuota) 모두 Pending 상태를 유발하므로, 이 두 fault의 구분이 SOP만으로는 어려울 수 있다. V3에서 이 두 fault의 B 정확도가 각각 60%로 비교적 높았으므로, SOP가 오히려 혼란을 줄 가능성도 검토해야 한다.

---

## 8. 개선 제안

### 제안 1: Step 내 다중 신호 처리 규칙 추가

현재 Priority Rule은 step 간 우선순위만 정의한다. Step 2에서 OOMKilled와 CrashLoopBackOff가 동시에 관찰되는 경우(F1 injection 시 다른 서비스의 cascade failure)의 처리 규칙이 없다. "동일 step 내 다중 이상 시, 가장 많은 pod가 영향받는 조건을 우선시하라"와 같은 규칙 추가를 고려할 수 있다.

### 제안 2: "If YES: diagnose" -> "If YES: note as primary candidate, then continue"

조기 확정 위험을 완화하기 위해, 각 step에서 조건 매칭 시 즉시 진단하지 않고, 후보로 기록한 뒤 모든 step을 완료한 후 최종 진단하도록 변경하는 것을 고려할 수 있다. 이는 원논문의 단계적 도구 호출과 달리, 모든 정보가 이미 제공된 V6의 특성에 더 적합하다.

### 제안 3: dry-run 검증 강화

계획서의 3개 dry-run(F1, F4, F8)에 추가하여, **F7(DiskPressure, Step 1 경유)**을 포함시킬 것을 권고한다. F7은 Step 1에서 감지되어야 하지만, F4(NodeNotReady)와 혼동될 수 있다. F1과 F7이 모두 Step 1/2에서 경합하는 패턴을 사전에 확인하는 것이 중요하다.

### 제안 4: Safety 기준의 강화

현재 safety 기준은 "-10pp 이상 하락"이다. V3에서 강점이었던 F9(80%), F5(60%), F7(60%), F10(60%)에서 SOP로 인한 예기치 않은 하락이 발생할 수 있다. 특히 F5와 F10이 모두 "Pending"으로 매핑되므로, 둘 중 하나에서 하락이 발생할 가능성이 있다. Safety 기준을 "F5+F10 합산 정확도가 V3 합산 대비 -20pp 이상 하락하지 않을 것"으로 보완하는 것을 제안한다.

---

## 9. 종합 평가

### 강점

1. V4/V5 실패 교훈을 충분히 반영한 단일 변수 설계
2. 문헌 근거가 명확하고, 원논문과의 차이를 인식한 목표 설정(+6pp)
3. 실패 판정 기준, safety 기준, dry-run 계획이 구체적
4. 비용과 시간 추정이 현실적

### 약점

1. SOP가 10개 fault type 전부를 직접 매핑하여, "진단 능력 향상" vs "힌트 제공" 경계가 모호
2. Priority Rule에 의한 조기 확정(early commitment) 위험이 V4 분류 잠금과 유사한 패턴을 만들 수 있음
3. Step 내 다중 신호 처리 규칙 부재
4. n=50에서 +6pp 차이의 통계적 유의성 달성이 현실적으로 어려움

### 결론: **조건부 승인**

다음 2가지 수정을 반영한 후 실험 진행을 권고한다:

1. **(필수) dry-run에서 조기 확정 패턴 검증**: F1 t1의 reasoning에서 Step 1 DiskPressure 감지 후 Step 2로 진행하는지 확인. 조기 확정이 관찰되면, "If YES: diagnose"를 "If YES: note as primary candidate, continue checking remaining steps"로 수정.

2. **(권장) dry-run 케이스 추가**: F7 t1(DiskPressure)을 dry-run에 추가하여, Step 1에서 F4와 F7의 구분이 가능한지 확인.

위 2가지를 dry-run 단계에서 확인하고, 필요시 SOP 프롬프트를 조정한 후 본 실험을 진행하는 것이 타당하다. 프롬프트 조정은 SYSTEM_PROMPT 범위 내이므로 단일 변수 설계를 훼손하지 않는다.

# 심층 분석: V5 실험 설계를 위한 개선점 도출

> 분석일: 2026-04-08
> 분석 대상: V1-V4 실험 결과
> 목적: V5 실험의 3개 가설 수립을 위한 데이터 기반 근거 확보

---

## 1. 오답 패턴 분석

### 1-1. V3 전체 오답 레이블 빈도 Top 5

| 오답 레이블 | 빈도 | 실제 fault type |
|------------|------|-----------------|
| Service Misconfiguration | 9회 | F4, F6, F8 등 다양 |
| Service Endpoint Misconfiguration | 6회 | F4, F6, F8 |
| Service Configuration Error/Issue | 6회 | F4, F6 |
| Image Pull Failure | 3회 | F3 (B에서 3회, 오답으로 처리됨) |
| Container/Resource 관련 | 4회 | F1, F2 |

**핵심 발견**: 오답의 32%가 "Service Misconfiguration/Endpoint" 계열. 특히 F4(NodeNotReady), F6(NetworkPolicy)에서 LLM이 노드/네트워크 문제를 서비스 설정 문제로 오분류하는 패턴이 지배적.

### 1-2. A/B 공통 오답 비율

V3에서 System A와 B가 **완전히 동일한 오답**을 낸 비율: 0% (0/26). 그러나 **같은 계열** 오답(Service Misc* 계열)을 낸 비율은 높음. 이는 컨텍스트 차이에도 불구하고 LLM이 유사한 실패 경로를 밟는다는 것을 의미.

### 1-3. Fault별 핵심 오답 패턴

| Fault | 핵심 오답 패턴 | 원인 분석 |
|-------|---------------|----------|
| F1 (OOMKilled) | 다양한 오답 분산 (Container Init, Resource Exhaust, Service Misc) | OOMKilled 신호가 context에 존재하나 LLM이 다른 noise에 주의를 빼앗김 |
| F2 (CrashLoop) | CPU throttle, Resource Exhaust, Readiness 등으로 분산 | CrashLoopBackOff 원인을 식별하지 못하고 증상만 나열 |
| F4 (NodeNotReady) | Service Config/Endpoint로 100% 오분류 | 노드가 이미 복구된 상태에서 수집 → "endpoints=0" 증상만 보임 |
| F6 (NetworkPolicy) | Service Endpoint로 A 100% 오분류 | cilium_drop 신호가 있으나 "endpoints=0"이 더 눈에 띔 |

---

## 2. 버전 간 변화 추적

### V2 → V3 변화 (Harness 추가 효과)

| 범주 | 개선된 fault (ΔB > 0) | 퇴행한 fault (ΔB < 0) |
|------|----------------------|----------------------|
| Manifest 관련 | F5 +40pp, F9 +20pp | F10 -20pp |
| Runtime 관련 | — | F1 -20pp, F2 -20pp, F3 -20pp |
| Node/Network | — | — |

**V2→V3 핵심**: Harness의 retry가 manifest 관련 fault(F5, F9)에서 B 정확도를 올렸으나, runtime fault(F1, F2, F3)에서는 오히려 퇴행. Retry가 "그럴듯한 오답"을 강화하는 역효과.

### V3 → V4 변화 (Context Reranking + Fault Layer + Harness 간소화)

- **심각한 퇴행**: F6 B -40pp, F9 B -40pp (V3의 최고 성과 fault에서 퇴행)
- **미미한 개선**: F2 B +20pp
- **원인**: Fault Layer Classification의 "분류 잠금" + GitOps 필터링 과도

---

## 3. 컨텍스트 구조 분석

### 정답 vs 오답 trial 비교 (V3 System B)

| 지표 | 정답 (n=20) | 오답 (n=30) | 차이 |
|------|-------------|-------------|------|
| 평균 prompt_tokens | 6,011 | 5,738 | +273 (+4.8%) |
| 평균 confidence | 0.830 | 0.825 | +0.005 |

**발견**: 정답과 오답 간 prompt_tokens 및 confidence 차이가 미미. LLM이 정답이든 오답이든 비슷한 수준의 확신을 보임 → **calibration 문제**

### Raw JSON 질적 분석 (V3 B system)

**정답 trial 공통 특성:**
- F6_t3_B: "frontend service reports 0 endpoints" + GitOps에서 NetworkPolicy 관련 단서 → "Network Policy Block" (conf 0.8, retry 0)
- F9_t5_B: CrashLoopBackOff + "invalid environment variable" 이벤트 → "Configuration Error" (conf 0.8, retry 1)
- F7_t1_B: "CPU throttling 36%, 53%" 명확한 수치 → "CPU Throttling" (conf 0.8, retry 2)

**정답 패턴**: 명확한 수치/키워드(OOMKilled, CPU throttling %, invalid env var)가 context에 직접 노출될 때 정답률 높음.

**오답 trial 공통 특성:**
- F1_t1_B: OOMKilled 신호 존재하나 shippingservice CrashLoop, paymentservice readiness 실패 등 **다중 노이즈**에 주의 분산 → "Image Configuration Failure" (conf 0.9!)
- F4_t1_B: "all pods Running" + "frontend 0 endpoints" → 노드 문제 무시하고 Service Endpoint로 오분류
- F2_t1_B: CrashLoopBackOff + CPU throttling 50% → CrashLoop의 **원인**을 못 찾고 증상만 반복

**오답 패턴**: (1) 다중 이상 신호가 동시에 존재할 때 LLM이 가장 눈에 띄는 신호에 고착, (2) 증상(CrashLoopBackOff)과 원인(entrypoint corruption)을 구분 못함, (3) 높은 confidence로 오답 반환(0.8-0.9)

---

## 4. Evaluator 효과 분석

### Evaluator Score 분포 (V3)

| 구분 | n | 평균 | 범위 |
|------|---|------|------|
| 정답 | 35 | 8.01 | 7.8 ~ 8.5 |
| 오답 | 65 | 8.02 | 7.5 ~ 8.8 |

**Evaluator는 정답과 오답을 구분하지 못함.** 정답 평균 8.01 vs 오답 평균 8.02 — 사실상 동일. 오답이 오히려 더 높은 점수를 받는 경우도 존재 (8.8).

### Retry 발생 조건

| 조건 | 건수 |
|------|------|
| B_correct + retry | 14 |
| B_correct + no retry | 6 |
| B_wrong + retry | 12 |
| B_wrong + no retry | 18 |
| A_correct + retry | 4 |
| A_wrong + retry | 14 |

**System B**: retry 발생 시 정확도 53.8% vs 미발생 시 25.0% (+28.8pp).
**System A**: retry 발생 시 정확도 22.2% vs 미발생 시 34.4% (-12.2pp).

### Retry의 Fault별 효과 (B system)

| 효과 | Fault types |
|------|-------------|
| Retry가 매우 효과적 (+50pp 이상) | F1, F7, F8, F9, F10 |
| Retry 효과 있음 (+17~33pp) | F3, F5 |
| Retry 효과 없음 (0pp) | F4 |
| Retry 역효과 (-33~-40pp) | F2, F6 |

**핵심 인사이트**: Retry는 "정답 단서가 context에 있으나 첫 시도에서 놓친" 경우에 효과적. F2(증상과 원인 혼동)와 F6(retry 없이 직접 정답 5건)에서는 역효과.

---

## 5. GitOps 컨텍스트 효과 분석

### B만 정답인 trial (n=9)

| Trial | B 진단 | A 오답 |
|-------|--------|--------|
| F6_t3 | Network Policy Block | Service Misconfiguration |
| F6_t4 | Network Policy Issue | Service Endpoint Issue |
| F9_t5 | Configuration Error | Environment Variable Issue |
| F10_t2 | Resource Quota Exceeded | Application Crash Loop |
| F10_t3 | Resource Quota Exceeded | Application Crash Loop |
| F5_t4 | PVC Binding Failure | PVC Pending Issue |
| F7_t1 | CPU Throttling | Service Misconfiguration |
| F8_t4 | Readiness Probe / Service Miscon | Disk Pressure Impact |
| F3_t3 | Image Pull Failure | (빈 응답) |

**GitOps가 결정적인 3개 fault**: F6(NetworkPolicy), F10(ResourceQuota), F9(SecretConfigMap). 이 fault들에서 manifest 변경 이력이 정답 단서 역할.

### A만 정답인 trial (n=4)

| Trial | A 진단 | B 오답 |
|-------|--------|--------|
| F3_t1 | Image Pull Failure | Image Pull Failure (오답 처리?) |
| F3_t2 | Image Pull Failure | Image Pull Failure (오답 처리?) |
| F10_t5 | Memory Quota Exceeded | Resource Quota Exhaustion |
| F7_t5 | Resource Exhaustion | CPU Throttling and Health Probe Failures |

F3_t1, F3_t2: B도 "Image Pull Failure"로 진단했으나 오답 처리 — 세부 내용 차이로 인한 것으로 추정 (label 완전 일치 기준 문제).

---

## 6. 참조 기법 (인터넷 서칭)

### 6-1. Flow-of-Action (ACM WWW 2025)
- **기법**: SOP(Standard Operating Procedure) 기반 multi-agent RCA
- **성과**: ReAct 35.5% → Flow-of-Action 64.0% (+28.5pp)
- **핵심**: SOP로 tool invocation 순서를 구조화하여 LLM hallucination 감소
- **적용 가능성**: ★★★ — 우리 RAG KB의 runbook/debugging guide를 SOP로 변환하여 진단 순서를 구조화할 수 있음

### 6-2. RCACopilot (EuroSys 2024, Microsoft)
- **기법**: 인시던트별 handler 매칭 → 진단 정보 수집 → RCA 카테고리 예측
- **성과**: RCA 정확도 76.6%
- **핵심**: 과거 유사 인시던트의 해결 사례를 few-shot 예제로 제공
- **적용 가능성**: ★★★ — 이전 trial의 정답 사례를 few-shot 예제로 프롬프트에 포함 가능

### 6-3. ThinkFL (2025)
- **기법**: Recursion-of-Thought + GRPO fine-tuning으로 self-refining failure localization
- **성과**: SOTA 대비 localization 정확도 향상 + 10x 속도
- **핵심**: 다단계 진단 경로 탐색 (trace → metrics → 가설 수정)
- **적용 가능성**: ★★ — fine-tuning 불가(gpt-4o-mini 고정), 단 multi-step 진단 구조는 프롬프트로 모방 가능

### 6-4. Iter-CoT (NAACL 2024)
- **기법**: Iterative Chain-of-Thought — 추론 체인을 반복적으로 수정하여 최종 정답 도출
- **성과**: 기존 CoT 대비 유의미한 정확도 향상
- **핵심**: 자기 교정(self-correction)이 아닌 자기 검증(self-verification) 기반
- **적용 가능성**: ★★★ — 현재 evaluator+retry가 이 방식이지만, 검증 기준이 불명확(8점대 집중)하여 개선 여지

### 6-5. Confidence-Improved Self-Consistency (ACL 2025)
- **기법**: Self-consistency에 confidence 가중치 적용 — 단순 다수결 대신 confidence 높은 응답에 가중치
- **성과**: 기존 self-consistency 대비 46% 적은 샘플로 동일 정확도 달성
- **적용 가능성**: ★★★ — 3회 생성 + confidence 가중 다수결로 V3 대비 개선 가능

---

## 7. 개선 가설 3개

### 가설 V5a: Structured Symptom Extraction → Diagnosis 2단계 분리

**변경 변수**: V3의 단일 프롬프트를 2단계 파이프라인으로 분리 (프롬프트 구조 변경)

**근거**:
- 데이터 근거: F1_t1_B에서 OOMKilled 신호가 context에 존재하지만 shippingservice CrashLoop, paymentservice readiness 실패 등 **다중 노이즈에 주의 분산** → 오진단 (conf 0.9). F4_t1_B에서 "all pods Running"에 현혹되어 NotReady 신호 무시. V3 오답의 핵심 패턴은 "핵심 신호가 있으나 노이즈에 묻힘".
- 문헌 근거: Flow-of-Action (WWW 2025)에서 SOP 기반 구조화가 hallucination을 줄이며 35.5%→64.0% 달성. Iter-CoT (NAACL 2024)에서 단계별 추론 분리가 정확도 향상.

**메커니즘**: 
Step 1 (Symptom Extraction): "진단하지 말고, 모든 이상 신호를 구조화된 리스트로 추출하라"
- 비정상 pod (status != Running, ready != True)
- 비정상 metric (임계값 초과)
- 비정상 event (Warning/Error)
- 비정상 node (NotReady, Pressure)
Step 2 (Diagnosis): 추출된 구조화 증상만을 입력으로 받아 진단
- Step 1의 출력이 noise를 걸러주는 필터 역할
- "이 증상 목록에서 가장 가능성 높은 root cause를 진단하라"

**대상 fault types**: F1 (OOMKilled, noise 문제), F2 (CrashLoop, 증상/원인 혼동), F4 (NodeNotReady, 신호 매몰)

**예상 효과**:
- F1 B: 20% → 40% (noise 필터링으로 OOMKilled 신호 부각)
- F2 B: 20% → 40% (증상 추출에서 CrashLoop 원인 분리)
- 전체 System B: 40% → 48%

**리스크**: 
- Step 1에서 핵심 신호를 누락하면 Step 2가 더 나빠질 수 있음
- 2x API call로 비용 증가
- V4의 "Fault Layer" 실패와 유사한 경로일 수 있으나, 핵심 차이는 **진단하지 않고 추출만** 한다는 점

**구현 범위**:
- `experiments/v5a/prompts.py`: SYMPTOM_EXTRACTION_PROMPT + DIAGNOSIS_PROMPT 신규
- `experiments/v5a/engine.py`: RCAEngineV5a에 `_extract_symptoms()` → `_diagnose()` 파이프라인
- `experiments/v5a/config.py`: MAX_TOKENS_EXTRACTION=1024, MAX_TOKENS_DIAGNOSIS=2048
- 나머지 V3와 동일 (evaluator, retry, context builder)

---

### 가설 V5b: Confidence-Weighted Self-Consistency Voting

**변경 변수**: V3의 단일 생성을 3회 독립 생성 + confidence 가중 다수결로 변경 (생성 전략 변경)

**근거**:
- 데이터 근거: V3 B system에서 같은 fault type 내 trial간 정답률 분산이 매우 큼 — F1(1/5), F2(1/5), F7(3/5), F9(4/5). 이는 LLM 출력의 확률적 변동이 크다는 것을 의미하며, 복수 샘플링으로 분산 감소 가능. 특히 F7_t1_B는 retry 2회 만에 정답(CPU Throttling)에 도달 — 반복 시도가 정답 확률을 높이는 직접 증거.
- 문헌 근거: Confidence-Improved Self-Consistency (ACL Findings 2025)에서 confidence 가중 방식이 단순 다수결 대비 46% 적은 샘플로 동일 성능 달성. Wang et al. (2023) Self-Consistency가 CoT 대비 10-20pp 향상 보고.

**메커니즘**: 
- 동일 context로 3회 독립 생성 (temperature=0.7)
- 각 생성의 `identified_fault_type`을 추출
- `confidence` 값으로 가중한 다수결 투표
- 가장 높은 가중 득표의 생성 결과를 최종 출력으로 선택
- Evaluator + retry는 최종 선택된 출력에만 적용

**대상 fault types**: 
- 높은 분산 fault: F7(60%→80%), F9(80%→100%), F10(60%→80%)
- 중간 분산: F5(60%→80%), F8(40%→60%)
- 약점 fault(F1, F2): p=0.2일 때 3회 중 1회 이상 정답 확률 = 1-(0.8)^3 = 48.8%, 단 다수결에서 선택되려면 2/3 이상이어야 → p=0.2에서는 효과 제한적

**예상 효과**:
- F7 B: 60% → 80%, F9 B: 80% → 100%
- F5, F10 B: 각 +10~20pp
- F1, F2 B: 미미한 변화 (0~+5pp)
- 전체 System B: 40% → 50%

**리스크**: 
- 3x API cost ($0.24/trial → $0.72/trial)
- p < 0.5인 fault(F1, F2, F4)에서는 "오답의 다수결"이 될 수 있음
- V3에서 이미 높은 fault(F9=80%)를 더 올리는 것은 논문 기여도가 낮을 수 있음

**구현 범위**:
- `experiments/v5b/engine.py`: RCAEngineV5b에 `_generate_multi()` 3회 생성 + `_vote()` 가중 다수결
- `experiments/v5b/config.py`: VOTING_SAMPLES=3, VOTING_TEMPERATURE=0.7
- `experiments/shared/llm_client.py`: `call_llm()`에 `temperature` 파라미터 추가
- 나머지 V3와 동일

---

### 가설 V5c: Differential Evaluator + 구체적 피드백 Retry

**변경 변수**: V3의 Evaluator 프롬프트를 완전 재설계 (evaluator 개선)

**근거**:
- 데이터 근거: V3 Evaluator 평균 점수가 정답(8.01) vs 오답(8.02)으로 **구분 불가**. 88%가 8점대 집중, System B에서 r=-0.296 역상관. Evaluator가 "논리적 완결성"을 평가하지만 "진단의 정확성"을 평가하지 못함. 반면 retry 자체는 B에서 +28.8pp 효과 — evaluator 판별력만 개선하면 retry 효과 극대화 가능.
- 문헌 근거: Madaan et al. (2023) Self-Refine에서 "피드백 품질이 iterative refinement의 bottleneck"임을 입증. RCACopilot (EuroSys 2024)에서 과거 유사 인시던트를 참조하는 방식이 76.6% 달성.

**메커니즘**: V3 Evaluator의 3가지 문제를 해결:

**(1) Evidence Cross-Check (증거 교차 검증)**
현재: keyword matching → constant 1.0
개선: Evaluator가 진단에서 인용한 각 증거를 원본 context에서 검색. NOT FOUND이면 hallucination으로 표시.

**(2) Alternative Hypothesis Generation (대안 가설 생성)**
현재: Generator의 alternative_hypotheses를 그대로 평가
개선: Evaluator가 **독립적으로** 자신의 top-2 대안 진단을 생성하고, 각각에 대해 context에서 지지 증거를 나열. Generator 진단과 비교하여 더 강한 증거를 가진 대안이 있으면 should_retry=true.

**(3) Specific Critique Template (구체적 비평 템플릿)**
현재: "Specific actionable feedback" (추상적)
개선: "Your diagnosis was [X]. Signal [Y] in the context contradicts this because [Z]. Consider [W] which is supported by signal [V]."

**대상 fault types**:
- Retry가 이미 효과적인 fault에서 극대화: F7(+75pp), F9(+50pp), F8(+50pp), F10(+67pp)
- Retry 역효과인 F2(-33pp), F6(-40pp)에서 방향 수정: 구체적 비평으로 올바른 방향의 retry 유도

**예상 효과**:
- F7 B: 60% → 80% (retry 품질 향상)
- F8 B: 40% → 60% (Service Endpoint 증거 교차 검증)
- F1 B: 20% → 40% (OOMKilled 신호를 가리키는 구체적 비평)
- 전체 System B: 40% → 50%

**리스크**: 
- Evaluator도 gpt-4o-mini → 동일 모델이 자기 오류를 감지하는 한계 ("LLMs Cannot Self-Correct", ICLR 2024)
- Evaluator 프롬프트 복잡화로 evaluator 자체의 오류율 증가 가능
- Retry 횟수가 증가하면 비용·시간 증가
- System A에서도 retry 효과가 나아지는지는 불확실 (V3에서 A retry = -12.2pp)

**구현 범위**:
- `experiments/v5c/prompts.py`: EVALUATOR_PROMPT 완전 재작성 (evidence cross-check + alternative hypothesis + specific critique), RETRY_PROMPT_TEMPLATE 개선 (evaluator의 대안 가설 포함)
- `experiments/v5c/engine.py`: `_evaluate()` 결과 파싱 로직 수정 (새 evaluator 출력 구조)
- `experiments/v5c/config.py`: RETRY_ENABLED_A=False (V3의 A retry -12.2pp 교훈 유지)
- 나머지 V3와 동일 (system prompt, context builder, evidence verification 제거)

---

## 8. 요약 및 권장 우선순위

### 3개 가설 비교

| 차원 | V5a (Decomposition) | V5b (Voting) | V5c (Evaluator) |
|------|---------------------|--------------|------------------|
| 변경 축 | 프롬프트 구조 | 생성 전략 | 하네스(Evaluator) |
| 주요 메커니즘 | Noise 분리 | 분산 감소 | Retry 품질 향상 |
| 대상 fault | F1, F2, F4 (약점) | F7, F9, F10 (강점 극대화) | F1, F7, F8 (전체) |
| 예상 System B | 48% | 50% | 50% |
| API cost 배수 | 2x | 3x | 1.5-2.5x |
| 논문 기여도 | ★★★ (decomposed RCA) | ★★ (기존 기법 적용) | ★★★ (adaptive evaluator) |
| 리스크 | Step 1 누락 시 퇴행 | 약점 fault 개선 한계 | 동일 모델 자기 교정 한계 |

### 권장 우선순위

1. **V5a (Decomposition)** — 가장 기대 효과가 큼. 약점 fault(F1, F2)를 직접 겨냥하며, V4의 "Fault Layer" 실패를 교훈 삼아 "분류 잠금" 없는 설계. 논문 기여도도 높음.
2. **V5c (Evaluator)** — Evaluator 비효율은 V3부터 미해결 과제. Retry의 잠재력(B +28.8pp)을 극대화할 수 있으며, V5a와 다른 축(하네스)을 개선하여 상호 보완적.
3. **V5b (Voting)** — 가장 안전한 가설이지만 약점 fault 개선이 제한적. API cost 3x가 부담. 하지만 구현이 가장 단순하여 baseline 비교용으로 가치.

### 3개 모두 V3 기준 단일 변수 변경을 준수하며, 병렬 실행 후 최선을 선택한다.

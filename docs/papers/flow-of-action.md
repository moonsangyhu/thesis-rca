# 논문 심층 분석: Flow-of-Action: SOP Enhanced LLM-Based Multi-Agent System for Root Cause Analysis

> 분석일: 2026-04-08
> 분석자: 20년차 SRE 전문가 관점
> 논문: Changhua Pei et al., WWW Companion '25, 2025
> URL: https://arxiv.org/pdf/2502.08224

---

## 1. 한 줄 요약

SRE가 실제로 따르는 표준 운영 절차(SOP)를 LLM 에이전트에 주입하여, ReAct의 hallucination을 줄이고 RCA 정확도를 35.5% → 64.0%로 올린 논문.

---

## 2. 핵심 문제와 기존 한계

### 해결하려는 문제
마이크로서비스 환경에서 LLM 에이전트(ReAct)로 RCA를 수행할 때 발생하는 2가지 핵심 문제:

**Challenge 1: Hallucination에 의한 비합리적 행동 선택**
- LLM이 확률적 모델이므로 tool 호출 시 파라미터 오류, 컨텍스트와 무관한 tool 선택 발생
- 한 단계의 hallucination이 이후 전체 RCA 경로를 오염시킴
- **우리 실험 연관**: V4의 "분류 잠금(classification lock-in)"과 정확히 같은 문제. Fault Layer에서 한 번 잘못 분류하면 이후 모든 추론이 고착됨

**Challenge 2: 복잡한 관측에서 다중 합리적 행동 존재**
- 동일 관측에서 여러 합리적 행동이 가능 (예: "Service name not found" → 코드 재생성 or SOP 문서 수정)
- tool이 수백 개일 때 올바른 행동 선택이 극도로 어려움
- **우리 실험 연관**: V3에서 F1 오답 시 "CrashLoop인가 OOMKill인가 Config Error인가" 다중 가설 중 선택 실패

### 기존 접근법 한계
| 방법 | 한계 | Average(LA+TA) |
|------|------|----------------|
| K8SGPT | K8s 메타데이터만 조회, 정보 부족 | 11.11% |
| HolmesGPT | 동일 | 11.11% |
| CoT (GPT-4-Turbo) | 복잡한 RCA에서 단계적 추론 실패 | 32.61% |
| ReAct (GPT-4-Turbo) | Hallucination + 비합리적 tool 선택 | 35.50% |
| Reflexion (GPT-4-Turbo) | 틀린 경로를 반복 반성 → 오히려 혼란 | 29.06% |

---

## 3. 핵심 기법과 원리

### 3-1. SOP Knowledge Base (도메인 지식 구조화)

**원리**: SRE가 실제로 사용하는 표준 운영 절차(SOP)를 knowledge base에 구조화하여 저장. 각 SOP는 `name`(검색용) + `steps`(실행 단계)로 구성.

**핵심 인사이트**: LLM에게 "스스로 생각해서 진단하라"가 아니라 "이 절차를 따라서 진단하라"로 바꿈. 이것이 hallucination을 극적으로 줄이는 핵심 메커니즘.

**우리 실험 연관**: 우리의 RAG KB에는 debugging guide 20개, runbook 20개, known-issue 25개가 있지만, 이들은 **참조 문서**이지 **실행 절차**가 아님. SOP처럼 "Step 1: X를 확인 → Step 2: Y이면 Z를 실행" 형태로 재구조화하면 효과가 클 것.

### 3-2. SOP Flow (절차 기반 실행 흐름)

```
Fault Info → match_sop → [SOP 없으면 generate_sop]
         → generate_sop_code → run_sop
         → match_observation → [ObAgent가 fault type 추정]
         → (반복) 더 세부적인 SOP로 drill-down
         → JudgeAgent가 "충분히 찾았다" 판단 → Speak (결과 출력)
```

**핵심 설계 원칙**: 
1. **Soft constraint**: SOP flow를 강제하지 않고 프롬프트로 유도. "대부분 SOP flow를 따르되, 예외적 상황에서는 벗어날 수 있음" → 유연성과 정확성 균형
2. **Hierarchical SOP**: macro → micro, general → specific으로 점진적 drill-down. 네트워크 문제 → 네트워크 파티션 → 특정 서비스 간 파티션
3. **SOP → Code 변환**: SOP의 각 단계를 Python 코드로 변환하여 실행. 텍스트 실행보다 코드 실행이 훨씬 정확함 (Chain-of-Code 인사이트)

**Ablation 결과**:
- SOP Knowledge 제거: 54.06% → 15.39% (-38.67pp) — **가장 큰 하락**
- SOP Flow 제거: 54.06% → 27.50% (-26.56pp)
- Action Set 제거: 54.06% → 42.34% (-11.72pp)

### 3-3. Action Set (행동 집합 생성 후 선택)

**원리**: ReAct의 "thought → action" 대신 "thought → **action set** → action" 패러다임. 먼저 가능한 행동 목록을 생성하고, 그 중에서 선택.

**메커니즘**:
1. ActionAgent가 SOP flow 정보와 예제를 기반으로 합리적 행동 집합 생성
2. JudgeAgent가 "root cause 찾았는가?" 판단하여 Speak 행동 추가 여부 결정
3. Rule 기반 보완: 이전 행동이 `generate_sop`이면 `generate_sop_code`를 집합에 필수 포함
4. MainAgent가 최종 선택

**Action set size 실험**: size=5가 최적. 너무 작으면 복잡한 시나리오 대응 불가, 너무 크면 모델이 randomness에 빠짐.

### 3-4. Multi-Agent System (역할 분리)

| Agent | 역할 | 핵심 기능 |
|-------|------|----------|
| MainAgent | 전체 오케스트레이션 | SOP flow에 따라 진단 진행 |
| ActionAgent | 행동 집합 생성 | flow 정보 + 예제 기반 합리적 행동 제안 |
| ObAgent | 관측 분석 + fault type 추정 | match_observation 후 유사 과거 인시던트 기반 추정 |
| JudgeAgent | 진단 완료 판정 | "충분한 근거가 모였는가?" 판단 |
| CodeAgent | SOP → 코드 변환 | tool 정보를 기반으로 실행 가능 코드 생성 |

---

## 4. 실험 결과와 비평

### 실험 환경
- **시스템**: Google Online Boutique (10+ 서비스, K8s) — **우리와 동일 시스템!**
- **모니터링**: Prometheus, Elastic, DeepFlow, Jaeger
- **Fault injection**: ChaosMesh
- **9가지 fault type**: CPU stress, Memory stress, Pod Failure, Network Delay/Loss/Partition/Duplicate/Corrupt/Bandwidth
- **데이터셋**: 90 incidents
- **모델**: GPT-3.5-Turbo, GPT-4-Turbo

### 결과 (Table 3, GPT-4-Turbo 기준)

| Method | LA | TA | Average | APL |
|--------|----|----|---------|-----|
| ReAct | 47.67 | 23.33 | 35.50 | 28.09 |
| Reflexion | 33.67 | 24.44 | 29.06 | - |
| **Flow-of-Action** | **70.89** | **57.12** | **64.01** | **15.10** |

### SRE 관점 비평

**강점:**
1. 동일 시스템(Online Boutique)에서 검증 — 직접 비교 가능
2. Ablation study가 충실하여 각 구성요소의 기여를 분리 가능
3. APL(평균 경로 길이)을 측정하여 효율성도 평가

**약점:**
1. **fault type이 우리와 상이**: 네트워크 관련 fault 5종(Delay, Loss, Partition, Duplicate, Corrupt)에 편중. 우리의 F1(OOMKill), F3(ImagePull), F4(NodeNotReady), F5(PVC), F8(ServiceEndpoint), F9(SecretConfigMap) 같은 설정/리소스 오류가 없음
2. **GPT-4-Turbo 사용**: 우리는 gpt-4o-mini 고정. GPT-4-Turbo 대비 추론 능력이 약하므로 동일 효과 기대 어려움
3. **90 incidents만**: 통계적 검정 없음. p-value, 신뢰구간 미보고
4. **tool 호출 기반**: 실시간 tool 호출(kubectl, Prometheus API)이 필요. 우리는 사전 수집된 컨텍스트를 LLM에 전달하는 방식이라 직접 적용 불가
5. **SOP는 사전에 작성 필요**: "SOP Knowledge 제거 시 15.39%"라는 결과는 SOP 없이는 이 프레임워크가 무의미함을 의미. SOP 작성 비용이 큼

---

## 5. 실무 적용 가능성

### 직접 적용 가능한 것
1. **SOP Knowledge 개념** → 우리 RAG KB를 SOP 형태로 재구조화
2. **Hierarchical diagnosis** → macro→micro 점진적 진단 구조를 프롬프트에 반영
3. **ObAgent의 역할** → Symptom Extraction(V5)과 유사하지만, fault type 추정까지 포함

### 직접 적용 불가능한 것
1. **SOP Code 생성/실행**: 우리는 사전 수집 컨텍스트 기반이므로 tool 호출 불가
2. **Multi-Agent 실시간 협업**: 우리는 단일 LLM 호출 구조
3. **ActionAgent/CodeAgent**: tool 선택 문제가 없으므로 불필요

### 비용 분석
- 현재: trial당 LLM 2-3회 호출 (~$0.003)
- SOP flow 적용 시: trial당 5-8회 호출 예상 (~$0.008) — 수용 가능

---

## 6. SRE 직감 평가

**"이 기법이 실제 on-call에서 동작할까?"**

**YES, 단 조건부.** SOP가 충분히 갖춰져 있다면 매우 효과적. 실제 SRE 팀에서도 runbook/SOP를 따라 진단하는 것이 가장 정확한데, 문제는:

1. **SOP 커버리지**: 새로운 유형의 장애에는 SOP가 없음. 논문의 `generate_sop`이 이를 해결하려 하지만, 자동 생성된 SOP의 품질이 핵심 변수
2. **Runtime vs 사후분석**: 이 프레임워크는 runtime tool 호출 기반이라 사후분석(우리 케이스)에는 변형이 필요
3. **가장 효과적인 장애 유형**: 정형화된 패턴(네트워크, 리소스)에 강함. 복합/연쇄 장애에는 SOP가 부족할 수 있음

**가장 인상적인 점**: SOP Knowledge 제거 시 54% → 15%로 하락. 이는 **도메인 지식의 구조화가 LLM 능력보다 훨씬 중요하다**는 것을 의미. 우리 실험에서도 RAG KB의 품질/구조가 모델 성능보다 더 큰 레버일 수 있음.

---

## 7. 약점과 위험

1. **SOP 의존성 과다**: SOP 없으면 성능 15.39%로 ReAct보다 낮음. SOP 작성 비용을 무시한 평가
2. **Online Boutique 특화**: 9가지 fault type 중 5개가 네트워크 관련. 다른 시스템/fault에 일반화 가능한지 불확실
3. **GPT-4-Turbo 기준**: gpt-4o-mini에서 SOP→Code 변환 품질이 크게 하락할 가능성
4. **통계적 검정 없음**: 90건에서 p-value 없이 절대 수치만 비교. 우연에 의한 차이 가능성 배제 못함
5. **Reproducibility**: 코드 비공개, SOP 내용 비공개. 재현 어려움

---

## 8. 우리 실험에의 적용 방안 (V6 설계)

### 적용 방안 A: SOP-Guided Diagnosis Prompt (권장, 구현 난이도 ★★☆)

**원리**: 현재 V3/V5의 "자유 CoT" 프롬프트를 "SOP flow 기반 구조화 진단"으로 교체.

**구체적 변경**:

현재 V3 SYSTEM_PROMPT:
```
Step 1 - Signal Inventory: List every anomalous signal...
Step 2 - Hypothesis Generation: Generate 3-5 hypotheses...
Step 3 - Evidence Matching: Cite EXACT signal...
Step 4 - Differential Diagnosis: ...
Step 5 - Confidence Assessment: ...
```

V6 SOP-Guided SYSTEM_PROMPT:
```
You are given raw diagnostic signals. Follow this Standard Operating Procedure:

## SOP: K8s Fault Diagnosis
Step 1 - Check Node Health: Are any nodes NotReady, DiskPressure, MemoryPressure?
  → If YES: This is likely a NODE-LEVEL fault. Identify which node and why.
  → If NO: Proceed to Step 2.

Step 2 - Check Pod Status: Are any pods not Running/Ready? What is the reason?
  → OOMKilled → Memory exhaustion (check memory metrics)
  → CrashLoopBackOff → Application crash (check logs for exit code/error)
  → ImagePullBackOff → Image issue (check image tag/registry)
  → CreateContainerConfigError → Secret/ConfigMap missing
  → Pending → Scheduling issue (check PVC, ResourceQuota, nodeSelector)
  → If all pods Running but unhealthy: Proceed to Step 3.

Step 3 - Check Service Connectivity: Are any services showing 0 endpoints?
  → If YES: Check Service selector, targetPort, pod labels, readiness probes.
  → If NO: Proceed to Step 4.

Step 4 - Check Network: Are there cilium drops, connection refused, DNS failures?
  → If YES: Check NetworkPolicy rules.
  → If NO: Proceed to Step 5.

Step 5 - Check Resource Limits: Is CPU throttling > 50%? Memory near limit?
  → If YES: Resource exhaustion issue.
  → If NO: Check GitOps changes and RAG knowledge base for hints.

At each step, cite the EXACT evidence from the input that led to your decision.
If multiple steps show anomalies, prioritize: Node > Pod > Service > Network > Resource.
```

**예상 효과**:
- F1(OOMKill): Step 2에서 OOMKilled reason을 직접 체크 → 20% → 40%+
- F4(NodeNotReady): Step 1에서 노드 상태를 먼저 확인 → 0% → 20%+
- F6(NetworkPolicy): Step 4에서 cilium drops를 명시적으로 체크 → 40% 유지 또는 개선
- F9(SecretConfigMap): Step 2에서 CreateContainerConfigError 매칭 → 80% 유지

**V4 "분류 잠금" 회피**: 
- V4는 "이 장애는 Layer X이다"라고 **분류 결과를 확정**했음
- V6 SOP는 "Step 1이 해당 없으면 Step 2로" **조건부 진행**이므로 잠금이 발생하지 않음
- 핵심 차이: V4는 "분류 → 진단", V6은 "조건 확인 → 해당 시 진단, 아니면 다음 단계"

**구현 범위**:
- `experiments/v6/prompts.py`: SOP_GUIDED_SYSTEM_PROMPT 신규
- `experiments/v6/engine.py`: V3 engine fork (프롬프트만 교체)
- 나머지 V3와 동일

### 적용 방안 B: RAG KB를 SOP 형태로 재구조화 (구현 난이도 ★★★)

**원리**: 현재 RAG KB의 debugging guide/runbook을 SOP(name + steps) 형태로 변환하여, 검색 시 "관련 SOP의 steps"를 컨텍스트에 직접 포함.

**구체적 변경**:

현재 RAG 출력 (참조 문서):
```
[RAG] OOMKilled Debugging Guide: When a container is OOMKilled, check the memory 
limits and working set. Common causes include memory leaks, insufficient limits...
```

V6 RAG 출력 (SOP 형태):
```
[SOP: OOMKilled Diagnosis]
Step 1: Check kube_pod_container_status_last_terminated_reason for "OOMKilled"
Step 2: Compare container_memory_working_set_bytes vs memory limit
Step 3: If working_set > 80% of limit → Memory limit too low
Step 4: Check if memory usage is growing over time → Memory leak
Step 5: Recommended fix: Increase memory limit or optimize application
```

**구현 범위**:
- `docs/runbooks/` 20개 파일을 SOP JSON 형태로 변환
- `src/rag/ingest.py`: SOP 형식 인식 + 구조화 임베딩
- `src/rag/retriever.py`: SOP steps를 structured format으로 반환

### 적용 방안 C: JudgeAgent 역할 도입 (구현 난이도 ★★☆)

**원리**: Flow-of-Action의 JudgeAgent 개념을 우리 Evaluator에 접목. "이 진단이 맞는가?"가 아니라 "충분한 근거가 모였는가?"를 판단.

**구체적 변경**: Evaluator 프롬프트에 JudgeAgent 로직 추가:
```
Before scoring, answer this question first:
"Has the diagnosis gathered SUFFICIENT evidence to confidently identify the root cause?"

Evidence sufficiency criteria:
1. At least 2 independent signals pointing to the same root cause
2. Alternative hypotheses explicitly ruled out with specific contradicting signals
3. The causal chain from root cause to observed symptoms is complete

If evidence is INSUFFICIENT: should_retry=true, and specify what additional evidence 
to look for in the critique.
```

---

## 9. 핵심 인용

> "SOPs, to a certain extent, impose constraints on LLMs at crucial junctures, guiding the entire process towards the correct trajectory." (Section 2.1.1)

> "Directly instructing the agent to execute all steps of the SOP one by one often leads to errors. This is because LLM tends to focus more on proximal text, and the outcome of a particular step can significantly influence the selection of subsequent actions." (Section 2.3.2)

> "When the SOP was removed, lacking domain-specific guidance, the model relied solely on its own orchestration, essentially reverting to ReAct. The significantly low accuracy underscores the crucial role of SOP." (Section 3.4, Ablation — SOP 제거 시 54%→15%)

> "Through action set, we have effectively mitigated the challenges posed by diverse observations... enabling the LLM Agent to attain a nuanced equilibrium between stochasticity and determinism." (Section 2.4)

> "In RCA tasks, excessive randomness may induce divergence in the localization process, impeding the formation of effective diagnostics. Conversely, an overly deterministic approach may incline the model towards scripted operations, limiting its capacity to handle unforeseeable and rapidly changing circumstances." (Section 2.4)

---

## 10. 권장 적용 우선순위

| 순위 | 방안 | 난이도 | 예상 효과 | 리스크 |
|------|------|--------|----------|--------|
| **1** | **A: SOP-Guided Prompt** | ★★☆ | B: 40%→52% | V4 분류잠금 위험 낮음 (조건부 진행 방식) |
| 2 | C: JudgeAgent 도입 | ★★☆ | Retry 효과 +10pp | A와 독립적으로 적용 가능 |
| 3 | B: RAG KB SOP 변환 | ★★★ | B: +5-10pp | 65개 문서 변환 필요, 시간 소요 |

**V6 권장**: 방안 A(SOP-Guided Prompt)를 단일 변수로 적용. V3 대비 SYSTEM_PROMPT만 교체.

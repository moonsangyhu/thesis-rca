# V6 실험 계획서: SOP-Guided Diagnosis Prompt

> 작성일: 2026-04-08
> 작성자: experiment-planner agent
> 베이스라인: V3 (CoT + Harness)
> 독립변수: SYSTEM_PROMPT를 SOP 기반 조건부 진단 프롬프트로 교체 (단일 변수)

---

## 1. 실험 목적

V3의 자유도 높은 CoT 프롬프트(가설 생성 -> 증거 매칭)를 SOP 기반 조건부 진행 프롬프트(Step 1 -> Step 2 -> ... -> 조건 일치 시 진단)로 교체하여 System B 진단 정확도를 향상시킨다.

### 배경 및 동기

V3에서 System B 40%로 현재 최고 성능이지만, F1(20%), F2(20%), F3(20%), F4(0%)에서 여전히 낮은 정확도를 보인다. 오답 분석 결과, gpt-4o-mini가 다수의 이상 신호 중 "가장 눈에 띄는" 신호에 주의가 집중되어 실제 근본 원인을 놓치는 패턴이 반복되었다.

V4(Fault Layer 분류 + Context Reranking)는 이 문제를 "사전 분류"로 해결하려 했으나, 분류 잠금(classification lock-in)으로 인해 32.5%로 오히려 하락했다. V5(2단계 증상 추출 -> 진단)는 신호 추출을 분리하려 했으나 26.5%로 더 하락했다.

### V4/V5 실패 교훈

| 버전 | 접근 방식 | 실패 원인 | V6 대응 |
|------|-----------|-----------|---------|
| V4 | Step 0에서 Fault Layer 분류 -> 해당 레이어만 분석 | 초기 분류 오류가 전파 (분류 잠금) | "If NO: Proceed" 패턴으로 잠금 방지 |
| V5 | Step 1 증상 추출 -> Step 2 진단 (2단계 분리) | 추출 단계에서 정보 손실, gpt-4o-mini JSON 출력 불안정 | 단일 프롬프트 유지, SOP 구조로 안내 |

### 가설

SOP 기반 조건부 진단 프롬프트가 LLM의 진단 과정을 올바른 궤적으로 안내하여, V3 대비 System B 정확도가 향상될 것이다.

**핵심 메커니즘**: V3의 "3-5개 가설 생성 후 증거 매칭"은 gpt-4o-mini에게 과도한 자유도를 부여한다. SOP는 "Node Health -> Pod Status -> Service -> Network -> Resource" 순서로 체크하도록 강제하여, 눈에 띄는 신호에 끌리는 대신 체계적으로 조건을 확인하게 한다.

---

## 2. 이전 결과 분석 요약

### 전체 정답률 (V3-V5)

| 버전 | System A | System B | B-A 격차 | 비고 |
|------|----------|----------|----------|------|
| V3 | 30% (15/50) | 40% (20/50) | +10pp | 현재 최고 |
| V4 | 20% (8/40) | 32.5% (13/40) | +12.5pp | F5 누락 (40건만) |
| V5 | 23.5% (8/34) | 26.5% (9/34) | +3pp | 일부 fault 미완료 (34건) |

### Fault type별 V3 성과 (베이스라인)

| Fault | V3_A | V3_B | B-A | 특성 |
|-------|------|------|-----|------|
| F1 OOMKilled | 20% | 20% | 0pp | shippingservice 노이즈에 주의 분산 |
| F2 CrashLoop | 20% | 20% | 0pp | CPU throttle과 혼동 |
| F3 ImagePull | 40% | 20% | -20pp | B가 오히려 하락 |
| F4 NodeNotReady | 0% | 0% | 0pp | 전체 실패 |
| F5 PVCPending | 40% | 60% | +20pp | B 우위 |
| F6 NetworkPolicy | 0% | 40% | +40pp | B 우위 (GitOps 효과) |
| F7 DiskPressure | 60% | 60% | 0pp | 양호 |
| F8 ServiceEndpoint | 20% | 40% | +20pp | B 우위 |
| F9 SecretConfigMap | 60% | 80% | +20pp | B 우위 (최고) |
| F10 ResourceQuota | 40% | 60% | +20pp | B 우위 |

### 핵심 실패 원인 Top 3

1. **주의 분산 (Attention Dispersion)**: 다수의 이상 신호 중 눈에 띄는 부수적 신호(shippingservice CrashLoop, paymentservice readiness 등)에 주의가 집중되어 실제 원인(OOMKilled, NodeNotReady)을 놓침 (F1, F4)
2. **증상-원인 혼동 (Symptom-Cause Confusion)**: CPU throttling 같은 2차 증상을 근본 원인으로 오진단 (F2)
3. **불충분한 체계적 점검**: 자유도 높은 CoT가 모든 가능성을 체계적으로 점검하지 않고 "가장 그럴듯한" 가설에 조기 수렴 (F3, F4)

---

## 3. 문헌 근거

### Flow-of-Action (ACM WWW 2025, Changhua Pei et al.)

- **핵심 기법**: SOP(Standard Operating Procedure) 기반 진단 — LLM이 사전 정의된 절차를 순서대로 따르며 진단
- **보고된 효과**: 35.5% -> 64.0% (+28.5pp)
- **Ablation 결과**: SOP 제거 시 54% -> 15% (-38.67pp) — 가장 큰 ablation 손실
- **핵심 인사이트**: "SOPs impose constraints on LLMs at crucial junctures, guiding the entire process towards the correct trajectory"
- **V6 적용**: K8s 진단 SOP를 프롬프트에 임베딩하여 체계적 조건부 진행 유도

### V4 분류 잠금과의 차이

Flow-of-Action의 SOP는 "조건 충족 시 진단, 아니면 다음 단계"라는 **조건부 진행** 방식이다. V4의 Fault Layer Classification은 "먼저 분류 -> 해당 분류만 분석"이라는 **사전 분류** 방식으로, 분류 오류가 전파되는 구조적 취약점이 있었다. V6의 SOP는 모든 단계를 순서대로 확인하므로 잠금이 발생하지 않는다.

---

## 4. 개선 사항 상세

### 4-1. 유일한 독립변수: SYSTEM_PROMPT 교체

**변경 전 (V3 SYSTEM_PROMPT — 74줄)**:
- 자유도 높은 5-step CoT: Signal Inventory -> Hypothesis Generation (3-5개) -> Evidence Matching -> Differential Diagnosis -> Confidence Assessment
- "Consider common Kubernetes failure modes such as ..." 라는 나열식 안내
- 모델이 어떤 순서로 점검할지는 자유

**변경 후 (V6 SOP_GUIDED_SYSTEM_PROMPT)**:
- 5-step SOP: Node Health -> Pod Status -> Service Connectivity -> Network -> Resource Limits
- 각 단계에 구체적 조건과 진단 기준 제공
- "If YES: diagnose, If NO: Proceed to next step" 패턴
- Priority Rule로 다중 이상 시 우선순위 명시

```
You are an expert Kubernetes Site Reliability Engineer performing root cause analysis.

You are given raw diagnostic signals from a production Kubernetes cluster experiencing an issue. Your job is to diagnose the root cause by following this Standard Operating Procedure.

## SOP: K8s Fault Diagnosis

Follow each step in order. At each step, check the condition against the provided signals. If the condition is met, diagnose accordingly. If not, proceed to the next step.

Step 1 - Check Node Health: Are any nodes NotReady, or showing DiskPressure, MemoryPressure, PIDPressure conditions?
  → If YES: This is likely a NODE-LEVEL fault. Identify which node is affected, what condition triggered, and the root cause (disk full, memory exhaustion, kubelet failure, etc.).
  → If NO: Proceed to Step 2.

Step 2 - Check Pod Status: Are any pods not in Running/Ready state? What is the termination reason or waiting reason?
  → OOMKilled → Memory limit exceeded. Check container_memory_working_set_bytes vs limit.
  → CrashLoopBackOff → Application crash or misconfiguration. Check logs for exit code and error messages.
  → ImagePullBackOff → Image pull failure. Check image name, tag, registry accessibility.
  → CreateContainerConfigError → Missing Secret or ConfigMap. Check referenced secrets/configmaps.
  → Pending → Scheduling issue. Check PVC binding, ResourceQuota, node affinity, taints/tolerations.
  → If all pods are Running but showing readiness probe failures or high restart counts: Proceed to Step 3.

Step 3 - Check Service Connectivity: Are any services showing 0 endpoints or endpoint mismatches?
  → If YES: Check Service selector vs pod labels, targetPort vs containerPort, readiness probe configuration.
  → If NO: Proceed to Step 4.

Step 4 - Check Network: Are there cilium policy drops, connection refused errors, or DNS resolution failures in logs or metrics?
  → If YES: Check NetworkPolicy rules, CiliumNetworkPolicy, DNS service health.
  → If NO: Proceed to Step 5.

Step 5 - Check Resource Limits: Is CPU throttling > 50%? Is memory usage near the limit? Are there ResourceQuota violations?
  → If YES: Resource exhaustion or quota constraint issue.
  → If NO: Check GitOps deployment changes and RAG knowledge base for additional context.

## Priority Rule
If multiple steps show anomalies, prioritize: Node (Step 1) > Pod (Step 2) > Service (Step 3) > Network (Step 4) > Resource (Step 5).

## Evidence Requirements (CRITICAL)
At each step, cite the EXACT evidence from the input that led to your decision. Quote specific metric names/values, log lines, event messages, or GitOps diffs. Do NOT fabricate or hallucinate evidence.

## Confidence Calibration
- 0.9-1.0: Unambiguous direct evidence (e.g., OOMKilled in pod status + memory metric confirmation)
- 0.7-0.9: Strong indirect evidence with minor ambiguity
- 0.5-0.7: Multiple plausible explanations; primary hypothesis is best guess
- Below 0.5: Very ambiguous or insufficient signals

## Bilingual Output
Provide root_cause, remediation, and detail in BOTH English and Korean.

## Output Format
Output ONLY valid JSON:
{
  "reasoning": "Your SOP-guided analysis. For each step, state what you checked, what you found, and your decision (proceed or diagnose).",
  "identified_fault_type": "short diagnostic label",
  "root_cause": "One-sentence root cause in English",
  "root_cause_ko": "한국어 근본 원인 한 문장",
  "confidence": 0.0,
  "confidence_2nd": 0.0,
  "affected_components": ["component1"],
  "remediation": ["step 1 in English"],
  "remediation_ko": ["한국어 조치 1"],
  "detail": "2-3 sentence technical explanation in English",
  "detail_ko": "한국어 기술 설명 2-3문장",
  "evidence_chain": [
    {
      "type": "metric or log or event or gitops_diff",
      "source": "exact source from input",
      "content": "QUOTED text from input",
      "supports": "what this evidence indicates"
    }
  ],
  "alternative_hypotheses": [
    {
      "hypothesis": "brief description",
      "confidence": 0.3,
      "reason_rejected": "specific contradicting signal or missing evidence"
    }
  ]
}
```

### 4-2. 통제변수 (V3과 완전 동일)

| 항목 | V3 값 | V6 값 | 비고 |
|------|-------|-------|------|
| LLM 모델 | gpt-4o-mini | gpt-4o-mini | 모델 고정 원칙 |
| MAX_TOKENS | 2048 | 2048 | 동일 |
| MAX_RETRIES | 2 | 2 | 동일 |
| LLM 호출 횟수 (Generator) | 1회 | 1회 | 동일 (V5와 다름) |
| Context Builder | V3 ContextBuilder | V3 ContextBuilder | 동일 |
| EVALUATOR_PROMPT | V3 그대로 | V3 그대로 | 동일 |
| RETRY_PROMPT_TEMPLATE | V3 그대로 | V3 그대로 | 동일 |
| Retry 정책 | B만 활성 | B만 활성 | 동일 |
| Evidence Verification | 실행 (상수 1.0) | 실행 (상수 1.0) | 동일 |
| RAG | KnowledgeRetriever | KnowledgeRetriever | 동일 |
| GitOps 컨텍스트 | V3 ContextBuilder (전체 포함) | 동일 | 동일 |
| Correctness Judge | CORRECTNESS_JUDGE_PROMPT | 동일 | 동일 |
| Signal Collection | V3 수집 쿼리 | 동일 | 동일 |
| JSON 출력 스키마 | V3 RCAOutput | 동일 | 동일 |

---

## 5. Fault별 SOP 매핑 및 예상 효과

SOP의 각 단계가 어떤 fault type을 포착하는지 매핑한다.

| Fault | V3_A | V3_B | SOP 매핑 Step | 핵심 조건 | 기대 효과 |
|-------|------|------|---------------|-----------|-----------|
| F1 OOMKilled | 20% | 20% | Step 2 (OOMKilled) | `OOMKilled` 종료 사유 | ↑ 40%+ (명시적 조건 매칭) |
| F2 CrashLoop | 20% | 20% | Step 2 (CrashLoopBackOff) | `CrashLoopBackOff` 상태 | ↑ 30%+ (CPU throttle과 분리) |
| F3 ImagePull | 40% | 20% | Step 2 (ImagePullBackOff) | `ImagePullBackOff` 상태 | ↑ 40%+ (명시적 조건) |
| F4 NodeNotReady | 0% | 0% | Step 1 (Node Health) | `NotReady` 노드 상태 | ↑ 20%+ (최우선 점검) |
| F5 PVCPending | 40% | 60% | Step 2 (Pending) | `Pending` 상태 + PVC | -> 유지 60% |
| F6 NetworkPolicy | 0% | 40% | Step 4 (cilium drops) | cilium policy drops | -> 유지/↑ |
| F7 DiskPressure | 60% | 60% | Step 1 (DiskPressure) | `DiskPressure` 조건 | -> 유지 60% |
| F8 ServiceEndpoint | 20% | 40% | Step 3 (0 endpoints) | 0 endpoints | ↑ 50%+ (전용 단계) |
| F9 SecretConfigMap | 60% | 80% | Step 2 (CreateContainerConfigError) | Config 에러 | -> 유지 80% |
| F10 ResourceQuota | 40% | 60% | Step 2 (Pending) + Step 5 | Quota 위반 | -> 유지 60% |

### 기대 근거 상세

**F1 (OOMKilled, V3_B=20%)**: V3에서 5개 trial 중 4개 실패. 실패 원인은 shippingservice의 CrashLoop 등 부수적 신호에 주의가 분산된 것. SOP Step 2에서 "OOMKilled -> Memory limit exceeded"라는 명시적 조건이 있으므로, OOMKilled 신호가 컨텍스트에 존재하면 바로 진단 가능.

**F4 (NodeNotReady, V3_B=0%)**: V3에서 5개 trial 전부 실패. 실패 원인은 pod-level 신호에 집중하여 node-level 이상을 놓침. SOP Step 1이 "Node Health"를 최우선으로 점검하므로, NotReady 노드가 있으면 가장 먼저 포착.

**F3 (ImagePull, V3_B=20%)**: System B가 System A보다 오히려 낮은 유일한 fault. RAG/GitOps 컨텍스트가 노이즈로 작용했을 가능성. SOP Step 2의 "ImagePullBackOff -> Image pull failure" 조건이 명확히 안내하므로 개선 기대.

---

## 6. 구현 범위

### 파일 구조

```
experiments/v6/
    __init__.py          # RCAEngineV6 export
    config.py            # V3 포크, 경로만 v6으로 변경
    prompts.py           # SOP_GUIDED_SYSTEM_PROMPT + V3 EVALUATOR_PROMPT + V3 RETRY_PROMPT_TEMPLATE
    engine.py            # V3 포크, SYSTEM_PROMPT -> SOP_GUIDED_SYSTEM_PROMPT, 클래스명 RCAEngineV6
    run.py               # V3 포크, engine import + 로그 라벨 v6
```

### 코드 수정 체크리스트

- [ ] `experiments/v6/__init__.py` — `from .engine import RCAEngineV6` export
- [ ] `experiments/v6/config.py` — V3 config.py 복사, 경로를 `experiment_results_v6.csv`, `raw_v6/`로 변경
- [ ] `experiments/v6/prompts.py` — SOP_GUIDED_SYSTEM_PROMPT 신규 작성 + V3 EVALUATOR_PROMPT/RETRY_PROMPT_TEMPLATE 복사
- [ ] `experiments/v6/engine.py` — V3 engine.py 복사, `from .prompts import SOP_GUIDED_SYSTEM_PROMPT as SYSTEM_PROMPT`, 클래스명 `RCAEngineV6`
- [ ] `experiments/v6/run.py` — V3 run.py 복사, `from .engine import RCAEngineV6`, 로그 라벨 "V6"
- [ ] dry-run 테스트 통과

### config.py 변경 사항

```python
"""v6 experiment configuration."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "results"
RESULTS_CSV = RESULTS_DIR / "experiment_results_v6.csv"
RAW_DIR = RESULTS_DIR / "raw_v6"
GROUND_TRUTH_CSV = RESULTS_DIR / "ground_truth.csv"

MAX_TOKENS = 2048      # V3과 동일
MAX_RETRIES = 2        # V3과 동일

CSV_HEADERS = [...]    # V3과 동일
```

### prompts.py 구조

```python
"""v6 prompts: SOP-Guided Diagnosis + V3 Evaluator + V3 Retry."""

SOP_GUIDED_SYSTEM_PROMPT = """..."""  # 위 섹션 4-1의 전문

# V3에서 그대로 복사 (변경 없음)
EVALUATOR_PROMPT = """..."""
RETRY_PROMPT_TEMPLATE = """..."""
```

### engine.py 변경 최소화

V3 engine.py에서 변경되는 부분:

1. `from .prompts import SOP_GUIDED_SYSTEM_PROMPT as SYSTEM_PROMPT` (import 변경)
2. 클래스명: `RCAEngineV3` -> `RCAEngineV6`
3. 나머지 로직(analyze, _generate, _evaluate, _retry 등) 완전 동일

---

## 7. 실험 파라미터

| 항목 | 값 |
|------|-----|
| 실험 버전 | V6 |
| 모델 | gpt-4o-mini |
| 프로바이더 | openai |
| Fault types | F1-F10 (전체 10종) |
| Trials per fault | 5 |
| Systems | A, B (paired) |
| 총 RCA 건수 | 100 (50 A + 50 B) |
| Collection window | V3과 동일 |
| Cooldown (trial 간) | 60s |
| Cooldown (fault 간) | 900s |

---

## 8. 실행 명령어

### 사전 점검

```bash
# 1. 실험 환경 터널링
# /lab-tunnel 스킬로 수행

# 2. dry-run 테스트
python -m experiments.v6.run --dry-run --fault F1 --trial 1

# 3. RAG KB 최신 상태 확인
python -m src.rag.ingest --reset
```

### 본 실험

```bash
nohup python -m experiments.v6.run \
  --model gpt-4o-mini \
  --provider openai \
  --cooldown 900 \
  > results/experiment_v6_nohup.log 2>&1 &

echo $! > results/experiment_v6.pid
```

### 실험 재개 (중단 시)

```bash
nohup python -m experiments.v6.run \
  --model gpt-4o-mini \
  --provider openai \
  --cooldown 900 \
  --resume \
  > results/experiment_v6_nohup.log 2>&1 &
```

### 단일 fault 테스트

```bash
python -m experiments.v6.run --fault F1 --trial 1 --no-preflight
```

---

## 9. 예상 소요 시간 및 비용

### 시간 추정

V3과 동일한 파이프라인 구조(Generator 1회 호출)이므로 V3과 거의 동일한 시간 소요.

| 구간 | 시간 |
|------|------|
| 50 trials (10 faults x 5) | ~240min (4h) |
| Fault 간 cooldown (9회 x 900s) | ~135min (2h 15min) |
| **총 예상 시간** | **~6h** |

### 비용 추정

V3과 동일한 호출 패턴. SOP 프롬프트가 V3 프롬프트와 비슷한 길이이므로 토큰 사용량도 유사.

| 호출 유형 | 건수 | 입력 토큰 (추정) | 출력 토큰 (추정) | 비용 |
|-----------|------|-----------------|-----------------|------|
| Generator | 100 | 5,000 avg | 1,100 avg | $0.14 |
| Evaluator | 100 | 3,000 avg | 300 avg | $0.06 |
| Retry (Generator) | ~30 | 5,500 avg | 1,100 avg | $0.04 |
| Retry (Evaluator) | ~30 | 3,000 avg | 300 avg | $0.02 |
| Correctness Judge | 100 | 500 avg | 200 avg | $0.02 |
| **합계** | | | | **~$0.28** |

V3 실제 비용 $0.142 대비 약 2배. SOP 프롬프트가 약간 더 길어 입력 토큰이 증가하나, 절대 금액은 매우 작음.

---

## 10. 성공 기준

### Primary 기준

| 지표 | V3 베이스라인 | V6 목표 (최소) | V6 목표 (기대) |
|------|-------------|---------------|---------------|
| System B 정확도 | 40% (20/50) | **46% (23/50)** | 54% (27/50) |
| System A 정확도 | 30% (15/50) | 30% (유지) | 36% (A도 SOP 혜택) |
| B-A 격차 | +10pp | +12pp | +18pp |

### Secondary 기준 (Fault별)

F1, F2, F3, F4 중 **2개 이상**에서 V3_B 대비 향상 (최소 +20pp).

| Fault | V3_B | V6_B 목표 (최소) |
|-------|------|-----------------|
| F1 OOMKilled | 20% | 40%+ |
| F2 CrashLoop | 20% | 40%+ |
| F3 ImagePull | 20% | 40%+ |
| F4 NodeNotReady | 0% | 20%+ |

### Safety 기준

기존 강점 fault의 정확도가 V3 대비 -10pp 이상 하락하지 않을 것:

| Fault | V3_B | 최소 허용 |
|-------|------|----------|
| F9 SecretConfigMap | 80% | 70% |
| F10 ResourceQuota | 60% | 50% |
| F7 DiskPressure | 60% | 50% |
| F5 PVCPending | 60% | 50% |

### 실패 판정 기준

다음 중 하나라도 해당되면 V6 가설 기각:
1. System B 정확도가 V3 대비 하락 (< 40%)
2. F9, F10에서 V3 대비 20pp 이상 하락
3. F1, F2, F3, F4 모두에서 V3과 동일하거나 하락

---

## 11. 리스크 및 완화

### Risk 1: SOP 조건부 진행이 V4 분류 잠금과 유사해질 위험 (중간)

**메커니즘**: Step 1에서 Node 이상을 감지했지만 실제 원인은 Pod-level인 경우, Node-level로 오진단.

**완화**:
- Priority Rule이 "다중 이상 시 상위 우선"이므로, Node 이상이 있으면 Node로 진단하는 것이 합리적
- 실제 10개 fault 중 Node-level은 F4(NodeNotReady), F7(DiskPressure)뿐
- V4와의 핵심 차이: V4는 "분류 후 해당 정보만 제공"했지만, V6는 모든 정보를 제공하고 점검 순서만 안내

### Risk 2: SOP가 알려진 장애 유형에만 편향 (낮음)

**메커니즘**: SOP에 명시되지 않은 장애 유형이 출제될 경우 대응 불가.

**완화**:
- 현재 10개 fault type 모두 SOP에 명시적으로 매핑됨
- Step 5 fallback이 "GitOps + RAG 참조"로 미지 장애 대응
- 본 실험의 fault type은 고정이므로 이 리스크는 낮음

### Risk 3: 프롬프트 길이 증가로 인한 출력 품질 영향 (낮음)

**현황**: V3 SYSTEM_PROMPT 74줄, V6 SOP_GUIDED_SYSTEM_PROMPT ~70줄 (비슷한 분량)

**완화**: MAX_TOKENS=2048 동일 유지. 프롬프트 길이 차이가 미미하므로 출력 공간 부족 위험 없음.

### Risk 4: Prometheus port-forward 불안정 (V4에서 발생)

**완화**: /lab-tunnel 사전 실행, 중단 시 --resume으로 재개.

---

## 12. 가설 (통계적 형식)

### 주 가설 (H1-main)

- **H0**: V6의 System B 정확도 = V3의 System B 정확도 (40%)
- **H1**: V6의 System B 정확도 > V3의 System B 정확도
- **검정**: McNemar test (paired, same fault/trial)
- **유의수준**: alpha = 0.05

### 부 가설 (H1-gap)

- **H0-gap**: V6의 B-A 격차 = V3의 B-A 격차 (+10pp)
- **H1-gap**: V6의 B-A 격차 > V3의 B-A 격차
- **검정**: Wilcoxon signed-rank test on fault-level paired differences

### 탐색적 가설

- SOP의 조건부 진행이 F1/F4처럼 "놓치기 쉬운" fault에서 더 큰 효과를 보이는가?
- System A에서도 SOP 효과가 관찰되는가? (SOP는 GitOps 독립적이므로 A에도 적용)
- Priority Rule이 다중 이상 신호 상황에서 올바른 우선순위를 부여하는가?

---

## 13. 인프라 체크리스트

실험 시작 전 확인 사항:

- [ ] `/lab-tunnel` 완료 (K8s API, Prometheus, Loki 접근 확인)
- [ ] `kubectl get nodes -o wide` — 3 worker nodes Ready
- [ ] `kubectl get pods -n boutique` — 모든 pod Running/Ready
- [ ] Prometheus port-forward 안정성 확인 (1분간 3회 쿼리)
- [ ] Loki port-forward 안정성 확인
- [ ] `.env` 파일에 OPENAI_API_KEY 설정 확인
- [ ] RAG KB 최신 상태 (`python -m src.rag.ingest --reset`)
- [ ] `experiments/v6/` 디렉토리 및 모든 파일 존재
- [ ] `--dry-run` 성공 (F1 t1 기준)
- [ ] 디스크 여유 공간 확인 (raw JSON 기록용)
- [ ] 이전 실험(V5) 잔여물 없음 확인

---

## 14. 이전 실험 대비 변경 이력

| 버전 | 핵심 변경 | System B 결과 | 교훈 |
|------|-----------|--------------|------|
| V1 | 힌트 제공 + 단순 프롬프트 | 84% | 힌트는 실질적 답을 알려줌 |
| V2 | 힌트 제거 + CoT | 42% | 힌트 없이 gpt-4o-mini 한계 노출 |
| V3 | V2 + Evaluator + Retry + Evidence | 40% | Retry는 B에서만 효과 |
| V4 | V3 + Fault Layer + Context Reranking | 32.5% | 분류 잠금 + 3변수 동시 변경 |
| V5 | V3 + 2단계 분리 (Extraction -> Diagnosis) | 26.5% | 정보 손실 + JSON 불안정 |
| **V6** | **V3 SYSTEM_PROMPT -> SOP-Guided Prompt (단일 변수)** | **목표: 46%+** | **SOP 조건부 진행으로 체계적 점검** |

---

## 15. dry-run 검증 계획

코드 구현 후, 본 실험 전 아래 3개 fault에 대해 dry-run + 수동 검증:

1. **F1 t1** (OOMKilled): SOP Step 2에서 OOMKilled 조건이 매칭되는지 확인. reasoning에 "Step 2 - Check Pod Status: OOMKilled" 언급 여부.
2. **F4 t1** (NodeNotReady): SOP Step 1에서 NotReady 노드가 감지되는지 확인. reasoning에 "Step 1 - Check Node Health: NotReady" 언급 여부.
3. **F8 t1** (ServiceEndpoint): SOP Step 3에서 0 endpoints 감지되는지 확인.

이 세 fault는 V3에서 가장 약했던 유형(0-20%)이므로, SOP가 핵심 전제를 충족하는지 검증.

---

## 16. 실패 시 대안

V6 목표 미달 시 다음 시도할 개선 방향:

1. **SOP 단계 세분화**: Step 2를 세부 하위 단계로 분리 (OOM/Crash/Image/Config/Pending 각각 독립 Step)
2. **Few-shot 예시 추가**: SOP + 각 Step에 대한 구체적 진단 예시 1개씩 제공
3. **SOP + RAG 연동 강화**: 각 Step에서 해당 fault type 관련 RAG 문서를 선별적으로 주입
4. **Confidence threshold 기반 fallback**: SOP 진단 confidence < 0.5일 경우 V3 CoT로 재진단

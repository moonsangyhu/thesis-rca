# V5 실험 계획서: Structured Symptom Extraction -> Diagnosis 2단계 분리

> 작성일: 2026-04-08
> 작성자: experiment-planner agent
> 베이스라인: V3 (CoT + Harness)
> 가설 코드: V5a

---

## 1. 실험 목적

V3의 단일 프롬프트 RCA를 2단계 파이프라인(Symptom Extraction -> Diagnosis)으로 분리하여, 핵심 신호가 노이즈에 묻히는 문제를 해결하고 진단 정확도를 향상시킨다.

### 배경 및 동기

V3 오답 분석에서 반복적으로 관찰된 핵심 패턴:

| 사례 | 컨텍스트에 존재하는 핵심 신호 | 오진단 원인 |
|------|-------------------------------|-------------|
| F1_t1_B | OOMKilled exit code 137 | shippingservice CrashLoop + paymentservice readiness 등 다중 노이즈에 주의 분산 -> "Image Configuration Failure" |
| F4_t1_B | Node NotReady 상태 | "all pods Running" + "frontend 0 endpoints" -> Service Endpoint 문제로 오분류 |
| F2_t1_B | CrashLoopBackOff + BackOff 이벤트 | CPU throttling 50% 동시 존재 -> 증상과 원인 구분 실패 |
| F1_t1_A | OOMKilled (cartservice) | shippingservice /bin/sh 오류에 주의 집중 -> "Container Initialization Failure" |

**공통 메커니즘**: gpt-4o-mini가 3,000-6,000 토큰의 진단 컨텍스트를 받을 때, 가장 "눈에 띄는" 신호(에러 메시지, 스택 트레이스)에 주의가 집중되어 실제 근본 원인 신호를 놓침.

### 가설

2단계 분리를 통해 Step 1에서 **모든** 이상 신호를 빠짐없이 구조화하면, Step 2에서 진단 시 핵심 신호가 누락되는 확률이 감소한다.

---

## 2. 가설 (통계적 형식)

### 주 가설 (H1-main)
- **H0**: V5의 System B 정확도 = V3의 System B 정확도 (40%)
- **H1**: V5의 System B 정확도 > V3의 System B 정확도
- **검정**: McNemar test (paired, same fault/trial)
- **유의수준**: alpha = 0.05

### 부 가설 (H1-sub)
- **H0-gap**: V5의 B-A 격차 = V3의 B-A 격차 (+10pp)
- **H1-gap**: V5의 B-A 격차 > V3의 B-A 격차
- **검정**: Wilcoxon signed-rank test on fault-level paired differences

### 탐색적 가설
- V5에서 F1, F2, F4(V3에서 약점이었던 fault)의 System B 정확도가 개선되는가?
- 2단계 분리가 Symptom Extraction 단계에서 핵심 신호 포착률을 높이는가?

---

## 3. 변경 사항 상세 (V3 대비)

### 변경되는 것 (독립변수: 1개)

| 항목 | V3 | V5 | 변경 이유 |
|------|----|----|-----------|
| 프롬프트 구조 | 단일 SYSTEM_PROMPT (5-step CoT) | 2단계: SYMPTOM_EXTRACTION_PROMPT + DIAGNOSIS_PROMPT | 신호 추출과 진단 분리 |
| LLM 호출 횟수 (Generator) | 1회 | 2회 (extraction + diagnosis) | 파이프라인 분리에 따른 필연적 증가 |

### 변경되지 않는 것 (통제변수)

| 항목 | V3 값 | V5 값 | 비고 |
|------|-------|-------|------|
| LLM 모델 | gpt-4o-mini | gpt-4o-mini | 모델 고정 원칙 |
| Context Builder | V3 ContextBuilder | V3 ContextBuilder | V4의 ContextBuilderV4 사용하지 않음 |
| Evaluator | V3 EVALUATOR_PROMPT | V3 EVALUATOR_PROMPT (동일) | 평가 기준 유지 |
| Retry | B만 활성 (MAX_RETRIES=2) | B만 활성 (MAX_RETRIES=2) | V3/V4 교훈 반영 |
| Evidence Verification | 실행하나 상수 1.0 | 스킵 (V3에서 정보가치 없음 확인) | 불필요 제거 |
| RAG | KnowledgeRetriever | KnowledgeRetriever (동일) | |
| GitOps 컨텍스트 | V3 ContextBuilder (전체 포함) | 동일 | V4의 NOT READY 필터 사용하지 않음 |
| Correctness Judge | CORRECTNESS_JUDGE_PROMPT | 동일 | |
| Trial 구조 | 10 faults x 5 trials | 동일 | |
| Cooldown | trial 간 60s, fault 간 900s | 동일 | |

---

## 4. 프롬프트 설계

### 4-1. SYMPTOM_EXTRACTION_PROMPT (Step 1)

```
You are a Kubernetes observability analyst. Your ONLY job is to extract and structure ALL anomalous signals from the diagnostic context below.

## Rules
1. Do NOT diagnose or identify root causes. Do NOT suggest fixes.
2. Extract EVERY anomalous signal, no matter how minor.
3. For each signal, quote the EXACT text from the input.
4. Categorize signals by type.
5. If a signal could indicate multiple issues, list it once with all possible interpretations.

## Output Format
Output ONLY valid JSON:
{
  "pod_anomalies": [
    {
      "pod": "pod name",
      "signals": [
        {
          "type": "status|restart|probe_failure|oom|crash|image_error|config_error|resource_limit",
          "severity": "critical|high|medium|low",
          "raw_evidence": "EXACT quoted text from input",
          "source_section": "which section of input this came from"
        }
      ]
    }
  ],
  "node_anomalies": [
    {
      "node": "node name",
      "signals": [
        {
          "type": "not_ready|disk_pressure|memory_pressure|pid_pressure|network_unavailable|runtime_error",
          "severity": "critical|high|medium|low",
          "raw_evidence": "EXACT quoted text from input",
          "source_section": "which section of input this came from"
        }
      ]
    }
  ],
  "metric_anomalies": [
    {
      "metric": "metric name or category",
      "type": "oom|cpu_throttle|memory_high|endpoint_zero|pvc_pending|network_drop|quota_exceeded",
      "severity": "critical|high|medium|low",
      "raw_evidence": "EXACT quoted text from input",
      "affected_components": ["component1"]
    }
  ],
  "event_anomalies": [
    {
      "object": "resource name",
      "type": "warning|error",
      "raw_evidence": "EXACT quoted text from input",
      "count": 1
    }
  ],
  "log_anomalies": [
    {
      "pod": "pod name",
      "severity": "error|warning",
      "raw_evidence": "EXACT quoted text from input (first 200 chars)",
      "pattern": "brief description of the error pattern"
    }
  ],
  "gitops_changes": [
    {
      "source": "fluxcd|argocd|git",
      "raw_evidence": "EXACT quoted text from input",
      "affected_resources": ["resource1"]
    }
  ],
  "signal_count_summary": {
    "total_signals": 0,
    "critical": 0,
    "high": 0,
    "medium": 0,
    "low": 0
  }
}
```

#### 설계 근거

1. **"Do NOT diagnose" 명시적 금지**: V4의 Fault Layer Classification이 "분류 잠금"을 유발한 교훈. 진단 관련 용어(root cause, fault type, diagnosis)를 의도적으로 배제하여 추출 단계에서 편향 방지.
2. **severity 분류**: Step 2에서 중요도 기반 가설 생성을 위한 사전 정렬. 단, 이 severity는 "이 신호가 얼마나 심각한 이상인가"이지 "이것이 원인일 가능성"이 아님.
3. **raw_evidence 필수**: 할루시네이션 방지. Step 2에서 원문 증거 대조 가능.
4. **gitops_changes 분리 카테고리**: System B에서만 채워지며, System A에서는 빈 배열.
5. **signal_count_summary**: Step 2에서 신호의 전체적 규모 파악용.

### 4-2. DIAGNOSIS_PROMPT (Step 2)

```
You are an expert Kubernetes Site Reliability Engineer performing root cause analysis.

You will receive a STRUCTURED SYMPTOM REPORT extracted from a production Kubernetes cluster. Your job is to diagnose the root cause based ONLY on the symptoms provided.

## Analysis Protocol (Chain-of-Thought)
Think step-by-step BEFORE giving your final answer:

Step 1 - Signal Prioritization: Review all extracted symptoms. Identify the TOP 3 most critical signals that are most likely to indicate the root cause. Explain why each is significant.

Step 2 - Hypothesis Generation: Based on the prioritized signals, generate 3-5 plausible root cause hypotheses. Consider common Kubernetes failure modes: resource exhaustion (memory, CPU), configuration errors (secrets, configmaps, selectors), network issues (policies, DNS), storage problems (PVC, volumes), container crashes, image pull failures, node issues, and scheduling/quota constraints.

Step 3 - Evidence Matching: For your top hypothesis, cite the SPECIFIC symptoms from the report that support it. Reference the exact raw_evidence fields.

Step 4 - Differential Diagnosis: For each alternative, explain the specific symptom that CONTRADICTS it, or the expected symptom that is MISSING.

Step 5 - Confidence Assessment: Based on how many symptoms directly confirm your top hypothesis vs how many are ambiguous or contradictory, assign confidence honestly.

## Confidence Calibration
- 0.9-1.0: Unambiguous direct evidence (e.g., OOMKilled in pod status with memory metric confirmation)
- 0.7-0.9: Strong indirect evidence with minor ambiguity
- 0.5-0.7: Multiple plausible explanations; primary hypothesis is best guess
- Below 0.5: Very ambiguous or insufficient signals

## Bilingual Output
Provide root_cause, remediation, and detail in BOTH English and Korean.

## Output Format
Output ONLY valid JSON:
{
  "reasoning": "Your step-by-step chain-of-thought (Steps 1-5). Be thorough.",
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
      "source": "exact source from symptom report",
      "content": "QUOTED raw_evidence from symptom report",
      "supports": "what this evidence indicates"
    }
  ],
  "alternative_hypotheses": [
    {
      "hypothesis": "brief description",
      "confidence": 0.3,
      "reason_rejected": "specific contradicting symptom or missing evidence"
    }
  ]
}
```

#### 설계 근거

1. **V3 SYSTEM_PROMPT와 동일한 CoT 5단계 유지**: 단, Step 1이 "Signal Inventory"에서 "Signal Prioritization"으로 변경. 이미 추출된 신호를 재나열하는 대신 우선순위를 매기는 역할로 전환.
2. **"based ONLY on the symptoms provided"**: 원본 컨텍스트가 아닌 구조화된 증상 리포트만 입력으로 받음을 명시.
3. **출력 형식은 V3과 100% 동일**: RCAOutput 호환성 유지. CSV 헤더 변경 불필요.

### 4-3. EVALUATOR_PROMPT, RETRY_PROMPT_TEMPLATE

V3의 EVALUATOR_PROMPT와 RETRY_PROMPT_TEMPLATE을 **그대로 재사용**. 변경 없음.

단, Retry 시 `_generate_with_feedback()`에서는 Step 1(Symptom Extraction)을 다시 수행하지 않고, 기존 추출 결과 + 평가 피드백으로 Step 2(Diagnosis)만 재실행.

---

## 5. 엔진 파이프라인 설계

### 5-1. RCAEngineV5.analyze() 전체 흐름

```
analyze(context, fault_id, trial, system, ground_truth)
    |
    +-- Step 1: _extract_symptoms(context)
    |     - SYMPTOM_EXTRACTION_PROMPT + context -> LLM 호출 (max_tokens=1024)
    |     - JSON 파싱 -> structured_symptoms (dict)
    |     - 토큰 카운트 누적
    |
    +-- Step 2: _diagnose(structured_symptoms)
    |     - structured_symptoms를 JSON 문자열로 포맷
    |     - DIAGNOSIS_PROMPT + formatted_symptoms -> LLM 호출 (max_tokens=2048)
    |     - JSON 파싱 -> RCAOutput 필드 채우기
    |     - 토큰 카운트 누적
    |
    +-- Step 3: Evidence Verification -> SKIP (V3에서 상수 1.0)
    |     - output.faithfulness_score = 0.0
    |
    +-- Step 4: _evaluate(context, output)
    |     - V3 동일 EVALUATOR_PROMPT 사용
    |     - 원본 context 기반 평가 (추출 결과가 아닌 원본)
    |     - eval scores 적용
    |
    +-- Step 5: Retry loop (System B only, max 2회)
    |     - retry 시: _diagnose_with_feedback(structured_symptoms, eval_result)
    |     - Step 1(extraction)은 재실행하지 않음
    |     - _evaluate() 재실행
    |
    +-- Step 6: judge_correctness(output, ground_truth)
    |
    +-- return output
```

### 5-2. 핵심 메서드 시그니처

```python
class RCAEngineV5(BaseLLMClient):

    def analyze(self, context, fault_id, trial, system, ground_truth) -> RCAOutput:
        """V5 메인 파이프라인."""

    def _extract_symptoms(self, context: str) -> tuple[dict, int, int]:
        """Step 1: 구조화된 증상 추출. Returns (symptoms_dict, prompt_tokens, completion_tokens)."""

    def _diagnose(self, symptoms: dict, fault_id, trial, system) -> RCAOutput:
        """Step 2: 추출된 증상 기반 진단."""

    def _diagnose_with_feedback(self, symptoms, fault_id, trial, system, eval_result) -> RCAOutput:
        """Retry: 증상 + 평가 피드백 기반 재진단."""

    def _evaluate(self, context, output) -> dict:
        """V3 동일: 원본 컨텍스트 기반 평가."""

    def _apply_eval(self, output, eval_result) -> RCAOutput:
        """V3 동일."""
```

### 5-3. Retry 시 재사용 전략

- **Step 1 결과 캐싱**: extraction 결과를 `self._cached_symptoms`에 저장하지 않고, `analyze()` 내 로컬 변수로 유지. Retry 시 동일한 `structured_symptoms`를 재사용.
- **근거**: 동일 입력에 동일 extraction을 반복하면 토큰 낭비. 증상 추출은 진단보다 결정적(deterministic)이므로 1회로 충분.

### 5-4. Evaluator 입력

Evaluator는 **원본 context**를 받음 (구조화된 symptoms가 아님). 이유:
- Evaluator의 역할은 "진단이 원본 데이터와 일치하는가"를 검증하는 것
- 구조화된 symptoms만 보면 extraction 단계의 누락을 검출할 수 없음

---

## 6. 파일 구조

```
experiments/v5/
    __init__.py
    config.py          # V5 설정 (토큰 제한, retry, 경로)
    prompts.py         # SYMPTOM_EXTRACTION_PROMPT, DIAGNOSIS_PROMPT
    engine.py          # RCAEngineV5
    run.py             # V3 run.py fork (engine import만 변경)
```

### config.py 설계

```python
MAX_TOKENS_EXTRACTION = 1024    # Step 1: 증상 추출 (구조화 JSON)
MAX_TOKENS_DIAGNOSIS = 2048     # Step 2: 진단 (V3과 동일)
MAX_RETRIES = 2                 # V3과 동일
RETRY_ENABLED_A = False         # V3/V4 교훈: A retry = -12.2pp
RETRY_ENABLED_B = True
```

### 추가 측정 필드 (RCAOutput 확장)

V5에서 RCAOutput에 추가할 필드:

```python
# experiments/v5/ 내부에서만 사용 (shared output 수정 불필요)
# raw JSON에 포함하여 기록
extraction_tokens_prompt: int = 0      # Step 1 입력 토큰
extraction_tokens_completion: int = 0  # Step 1 출력 토큰
extraction_signal_count: int = 0       # 추출된 총 신호 수
extraction_critical_count: int = 0     # critical 신호 수
```

이 필드들은 CSV에는 기존 prompt_tokens/completion_tokens에 합산하여 기록하고, raw JSON에는 별도 기록한다.

### CSV 헤더

V3 CSV_HEADERS와 **동일**. 추가 필드 없음. 버전 간 비교를 위해 동일 스키마 유지.

---

## 7. 실험 범위

| 항목 | 값 |
|------|-----|
| Fault types | F1-F10 (전체 10종) |
| Trials per fault | 5 |
| Systems | A, B (paired) |
| 총 RCA 건수 | 100 (50 A + 50 B) |
| 모델 | gpt-4o-mini (OpenAI) |

---

## 8. 실행 명령어

### 사전 점검

```bash
# 1. 실험 환경 터널링
# /lab-tunnel 스킬로 수행

# 2. Preflight check (자동)
python -m experiments.v5.run --dry-run

# 3. RAG KB 최신 상태 확인
python -m src.rag.ingest --reset
```

### 실험 실행

```bash
# 전체 실험 (nohup)
nohup python -m experiments.v5.run \
  --model gpt-4o-mini \
  --provider openai \
  --cooldown 900 \
  > results/experiment_v5_nohup.log 2>&1 &

echo $! > results/experiment_v5.pid
```

### 실험 재개 (중단 시)

```bash
nohup python -m experiments.v5.run \
  --model gpt-4o-mini \
  --provider openai \
  --cooldown 900 \
  --resume \
  > results/experiment_v5_nohup.log 2>&1 &
```

### 단일 fault 테스트

```bash
python -m experiments.v5.run --fault F1 --trial 1 --no-preflight
```

---

## 9. 성공 기준

### 주요 기준

| 지표 | V3 베이스라인 | V5 목표 (최소) | V5 목표 (기대) | 근거 |
|------|-------------|---------------|---------------|------|
| System B 정확도 | 40% (20/50) | 46% (23/50) | 54% (27/50) | Flow-of-Action 논문에서 +28.5pp 보고; 보수적 1/3 적용 |
| System A 정확도 | 30% (15/50) | 30% (15/50) | 36% (18/50) | A도 2단계 분리 혜택 가능 |
| B-A 격차 | +10pp | +12pp | +18pp | |
| McNemar p-value (V5B vs V3B) | - | < 0.10 | < 0.05 | |

### Fault별 목표

| Fault | V3_B | V5_B 목표 | 개선 기대 근거 |
|-------|------|-----------|---------------|
| F1 (OOMKilled) | 20% | 40%+ | 증상 추출에서 OOMKilled 신호 명시적 포착 |
| F2 (CrashLoop) | 20% | 40%+ | CrashLoop vs CPU throttle 분리 |
| F4 (NodeNotReady) | 0% | 20%+ | 노드 이상 신호가 별도 카테고리로 추출 |
| F6 (NetworkPolicy) | 40% | 40%+ | 유지 또는 개선 |
| F9 (SecretConfigMap) | 80% | 80%+ | 기존 강점 유지 |

### 실패 판정 기준

다음 중 하나라도 해당되면 V5 가설 기각:
1. System B 정확도가 V3 대비 하락 (< 40%)
2. F6 또는 F9에서 V3 대비 20pp 이상 하락 (V4의 실패 패턴 재현)
3. 2단계 호출로 인한 latency가 V3 대비 3배 이상 증가

---

## 10. 측정 항목

### 기본 측정 (V3과 동일)

| 항목 | 설명 |
|------|------|
| correct (0/1) | 정답 여부 |
| correctness_score (0.0-1.0) | LLM-as-judge 점수 |
| identified_fault_type | 진단 레이블 |
| confidence / confidence_2nd | 진단 신뢰도 |
| eval_overall_score | Evaluator 종합 점수 |
| retry_count | Retry 횟수 |
| latency_ms | 총 소요 시간 |
| prompt_tokens / completion_tokens | 총 토큰 사용량 |

### V5 추가 측정 (raw JSON에 기록)

| 항목 | 설명 | 분석 목적 |
|------|------|-----------|
| extraction_signal_count | Step 1에서 추출된 총 신호 수 | 추출 완전성 평가 |
| extraction_critical_count | Critical 신호 수 | 핵심 신호 포착률 |
| extraction_tokens | Step 1 토큰 사용량 | 비용 분해 |
| diagnosis_tokens | Step 2 토큰 사용량 | 비용 분해 |
| ground_truth_signal_captured | GT 핵심 신호가 extraction에 포함되었는가 (수동 검증) | 가설 검증의 핵심 |

### 분석 시 비교 대상

1. **V3 vs V5 System B 정확도** (McNemar test, paired by fault/trial)
2. **V3 vs V5 B-A 격차** (Wilcoxon signed-rank test on fault-level)
3. **Fault별 정확도 비교** (V3 vs V5, per fault type)
4. **Extraction 품질 vs 진단 정확도 상관관계**: extraction에서 핵심 신호를 포착한 경우 vs 못한 경우의 정답률 차이
5. **토큰 효율성**: 추가 토큰(Step 1) 대비 정확도 향상 비율
6. **Retry 효과**: V5에서도 B retry가 효과적인가?

---

## 11. 리스크 및 대응 방안

### Risk 1: Step 1 추출 품질 불량 (높은 가능성)

**증상**: gpt-4o-mini가 복잡한 JSON 구조를 올바르게 출력하지 못하거나, 핵심 신호를 누락.

**대응**:
- MAX_TOKENS_EXTRACTION = 1024로 충분한 출력 공간 확보
- JSON 파싱 실패 시 fallback: V3 단일 프롬프트로 자동 전환
- Dry-run에서 F1, F4, F6 세 가지 fault type으로 extraction 품질 사전 검증

### Risk 2: 2단계 호출로 인한 비용/시간 증가 (확실함)

**추정 증가분**:
- Step 1 추가 호출: 입력 ~4,000 토큰 + 출력 ~800 토큰
- Trial당 추가 비용: ~$0.0007 (gpt-4o-mini 기준)
- 총 추가 비용: 100건 x $0.0007 = ~$0.07

**대응**: 허용 범위 내. V3 총 비용 $0.142 대비 ~50% 증가로 $0.21 예상. 절대 금액이 작아 문제 없음.

### Risk 3: "분류 잠금" 재현 (낮은 가능성)

**증상**: SYMPTOM_EXTRACTION_PROMPT의 severity 분류가 V4 Fault Layer와 유사한 편향을 유발.

**대응**:
- severity는 "이상의 심각도"이지 "원인일 가능성"이 아님을 프롬프트에 명시
- severity 분류 자체가 진단을 유도하지 않도록 설계 (분류 카테고리에 fault type 이름 미포함)
- 만약 dry-run에서 편향이 관찰되면: severity 필드 제거하고 flat list로 단순화

### Risk 4: Step 2에서 Step 1 결과를 무시 (중간 가능성)

**증상**: gpt-4o-mini가 구조화된 증상 리포트를 받아도 자체적으로 "추론"하여 리포트에 없는 진단을 내림.

**대응**:
- DIAGNOSIS_PROMPT에 "based ONLY on the symptoms provided" 명시
- Step 2 입력에 원본 context를 포함하지 않음 (증상 리포트만 전달)
- 이를 통해 모델이 원본 데이터를 직접 볼 수 없으므로 추출된 증상에 의존할 수밖에 없음

### Risk 5: Prometheus port-forward 불안정 (V4에서 발생)

**대응**:
- V4에서 F5 전체 누락의 원인. port-forward 모니터링 스크립트 사전 실행
- 실험 시작 전 `/lab-tunnel`로 안정성 확인
- 중단 시 `--resume`으로 재개

---

## 12. 비용 추정

### LLM API 비용 (gpt-4o-mini 가격 기준)

gpt-4o-mini: input $0.15/1M tokens, output $0.60/1M tokens

| 호출 유형 | 건수 | 입력 토큰 (추정) | 출력 토큰 (추정) | 비용 |
|-----------|------|-----------------|-----------------|------|
| Step 1: Extraction | 100 | 4,500 avg | 800 avg | $0.12 |
| Step 2: Diagnosis | 100 | 2,500 avg | 1,100 avg | $0.10 |
| Evaluator | 100 | 3,000 avg | 300 avg | $0.06 |
| Retry (Diagnosis) | ~30 | 3,000 avg | 1,100 avg | $0.03 |
| Retry (Evaluator) | ~30 | 3,000 avg | 300 avg | $0.02 |
| Correctness Judge | 100 | 500 avg | 200 avg | $0.02 |
| **합계** | | | | **~$0.35** |

V3 대비 약 2.5배 증가 ($0.142 -> $0.35). 절대 금액은 매우 작음.

### 시간 추정

| 단계 | Trial당 시간 |
|------|-------------|
| Injection + Wait | ~120s |
| Signal Collection | ~30s |
| Step 1 (Extraction) x 2 (A+B) | ~10s |
| Step 2 (Diagnosis) x 2 (A+B) | ~20s |
| Evaluator x 2 | ~15s |
| Retry (B만, ~50% 확률) | ~20s |
| Judge x 2 | ~10s |
| Recovery + Cooldown (trial 간) | ~60s |
| **Trial 합계** | **~285s (~4.75min)** |

| 구간 | 시간 |
|------|------|
| 50 trials (10 faults x 5) | ~237min (3h 57min) |
| Fault 간 cooldown (9회 x 900s) | ~135min (2h 15min) |
| **총 예상 시간** | **~6h 12min** |

V3 소요 시간 (5h 42min) 대비 약 30분 증가.

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
- [ ] `experiments/v5/` 디렉토리 및 모든 파일 존재
- [ ] `--dry-run` 성공 (F1 t1 기준)
- [ ] 디스크 여유 공간 확인 (raw JSON 기록용)
- [ ] 이전 실험(V4) 잔여물 없음 확인

---

## 14. 이전 실험 대비 변경 이력

| 버전 | 핵심 변경 | 결과 | 교훈 |
|------|-----------|------|------|
| V1 | 힌트 제공 + 단순 프롬프트 | B=84% (힌트 의존) | 힌트는 실질적 답을 알려줌 |
| V2 | 힌트 제거 + CoT | B=42% (-42pp) | 힌트 없이 gpt-4o-mini 한계 노출 |
| V3 | V2 + Evaluator + Retry + Evidence | B=40% (-2pp, ns) | Retry는 B에서만 효과; Evaluator 변별력 없음 |
| V4 | V3 + Fault Layer + Context Reranking | B=32.5% (-7.5pp) | 분류 잠금 + GitOps 과도 필터링 + 3변수 동시 변경 |
| **V5** | **V3 + 2단계 분리 (Extraction -> Diagnosis)** | **목표: B>=46%** | **단일 변수 변경; V3 인프라 재사용** |

---

## 15. 문헌 근거 요약

| 논문 | 핵심 기법 | 보고된 효과 | V5 적용 |
|------|-----------|------------|---------|
| Flow-of-Action (ACM WWW 2025) | SOP 기반 구조화 추출 -> 진단 분리 | 35.5% -> 64.0% (+28.5pp) | 2단계 파이프라인 구조 차용 |
| Iter-CoT (NAACL 2024) | 단계별 추론 분리, 이전 단계 출력을 다음 입력으로 | 복잡한 추론에서 단일 CoT 대비 유의미 향상 | Extraction 출력을 Diagnosis 입력으로 |
| RCACopilot (EuroSys 2024, Microsoft) | 구조화된 진단 정보 수집 -> RCA | 76.6% 정확도 (production 환경) | 구조화된 증상 리포트 개념 |

---

## 16. dry-run 검증 계획

코드 구현 후, 본 실험 전 아래 3개 fault에 대해 dry-run + 수동 검증:

1. **F1 t1** (OOMKilled): Step 1에서 OOMKilled 신호가 critical로 추출되는지 확인
2. **F4 t1** (NodeNotReady): Step 1에서 node_anomalies에 NotReady가 포착되는지 확인
3. **F6 t1** (NetworkPolicy): Step 1에서 network_drop 메트릭이 추출되는지 확인

이 세 fault는 V3에서 가장 약했던 유형(0-20%)이므로, extraction 품질이 가설의 핵심 전제를 충족하는지 검증.

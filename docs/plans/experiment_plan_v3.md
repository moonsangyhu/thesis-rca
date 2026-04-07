# V3 실험 계획서

> 작성일: 2026-04-07
> 작성자: experiment-planner agent
> 버전: v3 (CoT + Harness: Evaluator + Retry + Evidence Verification)

---

## 1. 실험 목적

V3 Harness 파이프라인(Evidence Verification + Evaluator + Retry)이 V2(CoT only) 대비 RCA 정확도를 개선하는지 검증한다.

### 핵심 질문

1. **Harness 효과**: Evaluator + Retry 루프가 초기 진단의 오류를 교정하여 정확도를 높이는가?
2. **Evidence Faithfulness**: LLM이 입력 컨텍스트에 없는 증거를 환각(hallucinate)하는 비율은 얼마이며, keyword matching 기반 검증이 이를 효과적으로 탐지하는가?
3. **System A vs B 격차 변화**: Harness가 System A의 구조적 약점(GitOps 컨텍스트 부재)을 보완하는가, 아니면 System B에만 유의미한 효과가 있는가?

---

## 2. 가설

### 주 가설 (H1)

V3 System B의 정확도가 V2 System B(42%) 대비 유의미하게 향상된다.

- **근거**: Evaluator가 약한 진단을 식별하고 critique 피드백으로 재분석을 유도하므로, 초기 오진 사례 중 일부가 retry를 통해 교정될 것으로 예상
- **기대 효과**: V2 B 42% -> V3 B 50-60% (Harness만으로 +8-18%p 개선)
- **한계**: 같은 모델(gpt-4o-mini)이 generator와 evaluator를 모두 수행하므로 자기 평가 편향(self-evaluation bias)으로 인해 개선 폭이 제한될 수 있음

### 부 가설 (H2)

V3 System A의 정확도가 V2 System A(26%) 대비 소폭 향상된다.

- **근거**: System A는 GitOps 컨텍스트가 없어 구조적으로 진단이 어려운 fault type(F4, F6, F7, F8, F9)이 존재. Retry로도 없는 정보를 보완할 수 없으므로 개선 폭이 제한적
- **기대 효과**: V2 A 26% -> V3 A 28-35% (소폭 개선)

### 부 가설 (H3)

Retry가 실제로 trigger되는 비율은 전체 trial의 30-50%이며, retry 후 정답으로 전환되는 비율은 그 중 20-40%일 것이다.

- **측정 지표**: `retry_count > 0`인 trial 비율, retry 후 correct 전환율

---

## 3. V2 -> V3 변경점 분석

### 3.1 Harness 파이프라인 추가 (핵심 변경)

| 단계 | V2 | V3 | 기대 효과 |
|------|----|----|-----------|
| Generator | CoT 프롬프트 | 동일 CoT + bilingual + evidence chain | evidence chain 구조화로 진단 추적성 향상 |
| Evidence Verification | 없음 | keyword matching (match_ratio >= 0.5) | 환각 증거 탐지, faithfulness_score 제공 |
| Evaluator | 없음 | 독립 evaluator (4차원 평가) | 진단 품질 정량화 |
| Retry | 없음 | critique 피드백 기반 재분석 (MAX_RETRIES=2) | 약한 진단 교정 기회 |

### 3.2 프롬프트 변경

- **System Prompt**: V2와 거의 동일한 CoT 구조이나 evidence chain JSON 출력 포맷 추가
- **Evaluator Prompt**: Few-shot calibration 예시 포함 (score 8-9 good / 3-4 poor)
- **Retry Prompt**: evaluator critique + 4차원 점수를 피드백으로 제공하여 재분석 유도

### 3.3 출력 확장

- V2: 20개 CSV 컬럼
- V3: 33개 CSV 컬럼 (evidence_chain, alternative_hypotheses, faithfulness_score, eval_* 6개, retry_count 등 추가)

### 3.4 LLM 호출 횟수 증가

| 시나리오 | V2 호출 수 | V3 호출 수 |
|----------|------------|------------|
| Retry 없음 (System A+B) | 4회 (gen_A + judge_A + gen_B + judge_B) | 6회 (gen_A + eval_A + judge_A + gen_B + eval_B + judge_B) |
| Retry 1회 (한 시스템) | 4회 | 8회 (위 + retry_gen + retry_eval) |
| Retry 2회 (한 시스템) | 4회 | 10회 |
| 최악 (양쪽 2회씩) | 4회 | 14회 |

---

## 4. 인프라 안정성 개선 (필수 선행 작업)

### 4.1 V3 run.py에 반영해야 할 V2 개선사항

V2 실행 중 발견되어 V2 run.py에는 적용되었으나 V3 run.py에는 미반영된 4가지 안정성 개선:

| # | 개선사항 | V2 run.py | V3 run.py | 필요 조치 |
|---|---------|-----------|-----------|-----------|
| 1 | dotenv 로드 | `from dotenv import load_dotenv; load_dotenv()` (line 16-17) | **누락** | 파일 상단에 추가 |
| 2 | Post-trial health check | trial 간 60초 대기 후 3회 x 30초 health check loop (line 136-144) | **누락** (60초 대기만, line 131-134) | health check 루프 추가 |
| 3 | Fault 전환 시 Failed pod 정리 | `kubectl delete pods --field-selector=status.phase=Failed` (line 148-156) | **누락** | Failed pod 삭제 로직 추가 |
| 4 | Fault 전환 후 health verification | 3회 x 60초 health check (line 159-166) | **누락** | 정상화 확인 루프 추가 |

**결론**: V3 실험 실행 전에 `@experiment-modifier`가 위 4가지를 V3 run.py에 반영해야 한다.

### 4.2 추가 권장 개선

- **Evaluator timeout**: evaluator LLM 호출이 실패할 경우 retry를 중단하고 현재 결과를 저장하는 fallback 로직 확인 (현재 engine.py line 176-178에 try/except으로 구현됨 -- 양호)
- **Token 누적**: retry 시 prompt_tokens/completion_tokens가 누적되는지 확인 (engine.py line 173-174에서 `+=`로 누적됨 -- 양호)

---

## 5. 실험 파라미터

### 5.1 모델 및 프로바이더

| 항목 | 값 | 근거 |
|------|----|------|
| 모델 | `gpt-4o-mini` | V1/V2와 동일 모델 사용하여 Harness 효과만 분리 측정 |
| 프로바이더 | `openai` | V1/V2 동일 |
| MAX_TOKENS | 2048 | V3 config.py 기본값, evidence chain + bilingual 출력에 충분 |
| MAX_RETRIES | 2 | V3 config.py 기본값 |

**모델 변경하지 않는 이유**: V3의 목적은 Harness 효과 측정이다. 모델을 변경하면 Harness 효과와 모델 효과를 분리할 수 없다. 모델 변경 실험은 별도 ablation study로 수행한다.

### 5.2 실험 범위

| 항목 | 값 |
|------|----|
| Fault types | F1-F10 전체 (10종) |
| Trials per fault | 5 |
| Systems per trial | A + B |
| 총 trial 수 | 50 (= 10 x 5) |
| 총 RCA 실행 수 | 100 (= 50 x 2 systems) |

### 5.3 Cooldown 전략

| 구간 | 대기 시간 | 추가 검증 |
|------|----------|-----------|
| Trial 간 (같은 fault 내) | 60초 | + health check 3회 x 30초 |
| Fault 간 (F_n -> F_{n+1}) | 900초 (15분) | + Failed pod 삭제 + health check 3회 x 60초 |

### 5.4 RAG 파라미터

| 항목 | 값 | 출처 |
|------|----|------|
| TOP_K | 5 | `src/rag/config.py` |
| SCORE_THRESHOLD | 0.3 | `src/rag/config.py` |
| EMBEDDING_MODEL | all-MiniLM-L6-v2 | `src/rag/config.py` |

### 5.5 수집 윈도우

| 항목 | 값 | 출처 |
|------|----|------|
| COLLECTION_WINDOW | 300초 (5분) | `src/collector/config.py` |
| INJECTION_WAIT | fault별 상이 (60-180초) | `scripts/fault_inject.py` |

---

## 6. 평가 메트릭

### 6.1 주요 메트릭 (V1/V2와 동일)

| 메트릭 | 정의 | 목표 |
|--------|------|------|
| **Accuracy** | `correct == 1`인 trial 비율 | System B > V2 B (42%) |
| **Correctness Score** | LLM-as-judge 0.0-1.0 연속값 | 평균 비교 |

### 6.2 V3 신규 메트릭

| 메트릭 | 정의 | 관심 포인트 |
|--------|------|------------|
| **faithfulness_score** | evidence chain 중 verified 비율 (0.0-1.0) | System A vs B 차이, 환각 비율 |
| **eval_overall_score** | evaluator 4차원 평균 (1-10) | 진단 품질 정량 지표 |
| **eval_evidence_grounding** | 증거 기반성 (1-10) | 환각 감소 여부 |
| **eval_diagnostic_logic** | 추론 논리성 (1-10) | CoT 품질 |
| **eval_differential_completeness** | 감별 진단 완전성 (1-10) | 대안 가설 고려도 |
| **eval_confidence_calibration** | 신뢰도 보정 (1-10) | 과신 감소 여부 |
| **retry_count** | 재분석 횟수 (0-2) | Harness 활성화 빈도 |

### 6.3 분석 계획

1. **V2 vs V3 정확도 비교**: Wilcoxon signed-rank test (paired, fault별)
2. **Retry 효과 분석**: retry_count > 0인 trial에서 correct 전환율
3. **Evaluator 점수 분포**: System A vs B의 eval_overall_score 분포 비교
4. **Faithfulness 분석**: System A vs B의 faithfulness_score 비교 (B가 더 높은 faithfulness를 보이는지)
5. **Fault type별 Harness 효과**: F1-F10 각각에서 retry 비율 및 교정 성공률

---

## 7. 위험 요소 및 완화 방안

### 7.1 자기 평가 편향 (Self-Evaluation Bias)

- **위험**: 같은 gpt-4o-mini 모델이 generator와 evaluator를 모두 수행. Evaluator가 generator의 오류를 인식하지 못하고 높은 점수를 부여할 가능성
- **완화**: Few-shot calibration 예시를 evaluator 프롬프트에 포함하여 기준 명확화 (이미 구현됨)
- **측정**: eval_overall_score와 correctness_score 간 상관관계 분석. 상관이 낮으면 evaluator가 실제 품질을 반영하지 못하는 것
- **대안 (추후)**: evaluator를 다른 모델(예: claude-sonnet)로 분리하는 ablation 실험

### 7.2 Keyword Matching 기반 Evidence Verification 한계

- **위험**: `_verify_evidence()`가 단순 keyword matching(4자 이상 단어, match_ratio >= 0.5)으로 작동. 의미적 정확성이 아닌 표면적 단어 매칭만 수행
- **예시**: LLM이 "memory pressure detected"라고 인용하고 입력에 "memory"와 "detected"가 있으면 verified=True이지만, 실제 입력에서는 다른 맥락의 단어일 수 있음
- **완화**: faithfulness_score를 참고 지표로만 사용하고, 최종 판정은 correctness_score에 의존
- **측정**: faithfulness_score=1.0이면서 correct=0인 사례 수 (false positive 환각 통과율)

### 7.3 API 비용 증가

- **위험**: V3는 V2 대비 LLM 호출 횟수가 50-250% 증가 (evaluator + retry)
- **추정**: 아래 비용 추정 섹션 참조
- **완화**: MAX_RETRIES=2로 제한. Evaluator의 should_retry 기준이 적절한지 dry-run으로 사전 확인

### 7.4 실험 시간 증가

- **위험**: Retry로 인해 trial당 실행 시간이 불균일해짐. 최악의 경우 trial 하나에 LLM 14회 호출
- **완화**: 전체 실험을 nohup 백그라운드로 실행하고 로그로 모니터링

### 7.5 Evaluator should_retry 기준 불명확

- **위험**: evaluator 프롬프트에 should_retry 기준이 명시적으로 정의되지 않음. "score < 7이면 retry" 같은 규칙이 없고 evaluator LLM 재량에 맡겨짐
- **완화**: 이는 의도적 설계일 수 있으나, retry 비율이 너무 높거나 낮으면 조정 필요. 첫 5 trial의 retry 패턴을 확인 후 필요시 프롬프트 조정

---

## 8. 인프라 체크리스트

실험 시작 전 확인해야 할 항목:

```
[ ] SSH 터널 활성화 (K8s API, Prometheus, Loki)
[ ] kubectl get nodes -- 모든 노드 Ready
[ ] kubectl get pods -n boutique -- 12개 이상 Running
[ ] Prometheus (localhost:9090) 응답 확인
[ ] Loki (localhost:3100) 응답 확인
[ ] .env 파일에 OPENAI_API_KEY 설정 확인
[ ] KUBECONFIG 환경변수 확인 (~/.kube/config-k8s-lab)
[ ] RAG ChromaDB 빌드 확인 (python -m src.rag.ingest --reset)
[ ] V3 run.py 안정성 개선 4건 반영 확인
[ ] dry-run 테스트 통과 (python -m experiments.v3.run --dry-run)
[ ] 디스크 여유 공간 확인 (raw JSON 파일 약 100개 생성 예상)
[ ] Error/Evicted pod 잔여물 제거 (kubectl delete pods -n boutique --field-selector=status.phase=Failed)
```

---

## 9. 실행 명령어

### 9.1 사전 준비

```bash
# 1. 환경 활성화
cd /Users/yumunsang/Documents/thesis-rca
source .venv/bin/activate

# 2. SSH 터널 (별도 터미널)
# /lab-tunnel 스킬 사용

# 3. RAG KB 확인/재빌드
python -m src.rag.ingest --reset

# 4. V3 run.py 안정성 개선 반영 (experiment-modifier 에이전트가 수행)

# 5. dry-run 테스트
python -m experiments.v3.run --dry-run
```

### 9.2 전체 실험 실행

```bash
# nohup 백그라운드 실행
nohup python -m experiments.v3.run \
  --model gpt-4o-mini \
  --provider openai \
  --cooldown 900 \
  > results/experiment_v3_nohup.log 2>&1 &

# PID 기록
echo $! > results/experiment_v3.pid
```

### 9.3 모니터링

```bash
# 로그 실시간 확인
tail -f results/experiment_v3.log

# 진행 상황 확인
grep "Progress:" results/experiment_v3.log | tail -5

# CSV 행 수 확인
wc -l results/experiment_results_v3.csv

# Retry 발생 현황
grep "Retry" results/experiment_v3.log | wc -l
```

### 9.4 중단 후 재개

```bash
python -m experiments.v3.run \
  --model gpt-4o-mini \
  --provider openai \
  --cooldown 900 \
  --resume
```

### 9.5 단일 fault/trial 재실행

```bash
python -m experiments.v3.run --fault F2 --trial 1 --model gpt-4o-mini --provider openai
```

---

## 10. 예상 소요 시간 및 비용

### 10.1 시간 추정

V2 기준 1 trial 소요 시간 분석 (experiment_results_v2.csv 기반):

| 단계 | 시간 |
|------|------|
| Injection + wait | ~120초 |
| Signal collection | ~30초 |
| RCA System A (gen + judge) | ~15초 (latency_ms 평균 ~6000ms x 2) |
| RCA System B (gen + judge) | ~15초 |
| Recovery | ~60초 |
| **V2 trial 소계** | **~240초 (4분)** |

V3 추가 시간:

| 추가 단계 | 시간 |
|----------|------|
| Evaluator A + B | ~10초 (1024 토큰 제한, 빠름) |
| Evidence verification A + B | <1초 (로컬 처리) |
| Retry (발생 시, 1회당) | ~15초 (gen + eval + verify) |
| **V3 trial 소계 (retry 없음)** | **~250초** |
| **V3 trial 소계 (retry 1회)** | **~265초** |

전체 실험:

| 항목 | 시간 |
|------|------|
| 50 trials x 265초 | ~3.7시간 |
| Trial 간 cooldown (40 x 60초) | ~0.7시간 |
| Trial 간 health check (40 x 90초 평균) | ~1시간 |
| Fault 간 cooldown (9 x 900초) | ~2.3시간 |
| Fault 간 health check (9 x 180초) | ~0.5시간 |
| **총 예상 시간** | **~8-9시간** |

### 10.2 비용 추정

V2 토큰 사용량 기준:

| 항목 | V2 평균 | V3 예상 (retry 없음) | V3 예상 (retry 1회) |
|------|---------|---------------------|---------------------|
| Prompt tokens/trial | ~6,500 | ~9,500 (+evaluator) | ~14,000 (+retry) |
| Completion tokens/trial | ~900 | ~1,400 (+evaluator) | ~2,300 (+retry) |

gpt-4o-mini 요금 (2026-04 기준):
- Input: $0.15/1M tokens
- Output: $0.60/1M tokens

| 시나리오 | Prompt 총량 | Completion 총량 | 비용 |
|----------|------------|----------------|------|
| Retry 없음 (100건) | ~950K | ~140K | ~$0.23 |
| Retry 30% (100건) | ~1,100K | ~180K | ~$0.27 |
| Retry 50% (100건) | ~1,200K | ~210K | ~$0.31 |

**결론**: 비용은 $0.23-0.31 수준으로 무시 가능. V2($0.05)의 약 5배이나 절대액은 미미.

---

## 11. 성공 기준

### 11.1 실험 완료 기준

- [ ] experiment_results_v3.csv에 100행 (50 trials x 2 systems) 기록
- [ ] results/raw/에 100개 JSON 파일 생성
- [ ] error 컬럼이 비어있는 행이 95% 이상
- [ ] retry_count, faithfulness_score, eval_overall_score 등 V3 고유 컬럼에 유효한 값이 기록됨

### 11.2 분석 완료 기준

- [ ] V2 vs V3 정확도 비교 (System A/B 각각)
- [ ] Wilcoxon signed-rank test 수행 (V3 B vs V2 B)
- [ ] Retry 효과 분석 (retry 발생률, 교정 성공률)
- [ ] Evaluator 점수 분포 분석
- [ ] Faithfulness score 분포 분석
- [ ] Fault type별 상세 분석

### 11.3 논문 기여 판단 기준

| 결과 | 해석 | 논문 기여 |
|------|------|-----------|
| V3 B > V2 B (통계적 유의) | Harness가 정확도 개선에 효과적 | 주요 기여 -- Harness 설계의 가치 입증 |
| V3 B = V2 B | Harness 효과 없음 (같은 모델 자기 평가 한계) | 부정적 결과이나 유의미 -- 자기 평가 편향 분석 |
| V3 B < V2 B | Harness가 오히려 성능 저하 | 예상 외 -- retry가 정답을 오답으로 변경하는 사례 분석 필요 |

---

## 12. 이전 실험 대비 변경점 요약

| 항목 | V1 | V2 | V3 |
|------|----|----|-----|
| 힌트 (F1-F10 목록) | 포함 | 제거 | 제거 |
| 프롬프트 방식 | 단순 | CoT | CoT + evidence chain |
| Evidence Verification | 없음 | 없음 | keyword matching |
| Evaluator | 없음 | 없음 | 4차원 독립 평가 |
| Retry | 없음 | 없음 | MAX_RETRIES=2 |
| Bilingual 출력 | 없음 | 없음 | 한/영 이중 출력 |
| CSV 컬럼 수 | 15 | 20 | 33 |
| LLM 호출 수/trial | 4 | 4 | 6-14 |
| 모델 | gpt-4o-mini | gpt-4o-mini | gpt-4o-mini |
| System A 정확도 | 30% | 26% | **?** |
| System B 정확도 | 84% | 42% | **?** |

---

## 13. 실험 실행 전 필수 코드 수정 목록

`@experiment-modifier`가 실험 전에 반드시 수행해야 할 수정:

### 13.1 V3 run.py 안정성 개선 (4건)

```
파일: experiments/v3/run.py

1. Line 1 부근: dotenv 로드 추가
   from dotenv import load_dotenv
   load_dotenv()

2. Line 131-134: Post-trial health check 루프 추가
   현재: time.sleep(60) 만 수행
   변경: V2 run.py line 136-144 패턴 적용
   (60초 대기 + health_check 3회 x 30초)

3. Line 135-136: Fault 전환 시 Failed pod 정리 추가
   현재: cooldown만 수행
   변경: V2 run.py line 148-156 패턴 적용
   (kubectl delete pods --field-selector=status.phase=Failed)

4. Line 135-136: Fault 전환 후 health verification 추가
   현재: cooldown 후 바로 다음 fault 진행
   변경: V2 run.py line 159-166 패턴 적용
   (health_check 3회 x 60초)
```

### 13.2 수정 후 검증

```bash
# dry-run으로 코드 오류 확인
python -m experiments.v3.run --dry-run

# F1 t1 단건 실행으로 전체 파이프라인 검증
python -m experiments.v3.run --fault F1 --trial 1 --model gpt-4o-mini --provider openai
```

---

## 14. 실험 일정 (권장)

| 단계 | 예상 소요 | 담당 |
|------|----------|------|
| V3 run.py 코드 수정 | 30분 | @experiment-modifier |
| dry-run + 단건 테스트 | 30분 | @experiment |
| 전체 실험 실행 (F1-F10) | 8-9시간 | @experiment (nohup) |
| 결과 분석 리포트 | 1시간 | @results-writer |
| **총 소요** | **~10-11시간** | |

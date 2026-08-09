# 논문 심층 분석: RCAgent — Tool-Augmented Autonomous Agents for Cloud RCA

> 분석일: 2026-08-09
> 분석 관점: 20년차 cloud SRE
> 논문: Zefan Wang et al., CIKM 2024
> DOI: https://doi.org/10.1145/3627673.3680016
> 원문: https://arxiv.org/pdf/2310.16340

## 1. 한 줄 요약

RCAgent는 사내 배치 Vicuna-13B가 로그·DB·코드용 전문 도구를 자율 호출하게 하고, 긴 관측의 손실과 도구 호출 오류를 별도 안정화 장치로 통제한 산업용 Flink RCA agent다.

## 2. 핵심 문제와 기존 한계

기존 LLM RCA는 사람이 미리 정한 workflow에 의존해 장애마다 달라지는 조사 경로를 충분히 탐색하지 못한다. 반대로 자유로운 ReAct agent는 긴 로그로 context가 팽창하고, 작은 로컬 모델에서 잘못된 tool/parameter와 malformed JSON이 다음 단계로 전파된다. RCAgent가 다루는 핵심은 모델의 지식 자체보다 **증거 수집 행동의 자율성과 안정성**이다.

## 3. 핵심 기법과 원리

```text
Controller agent
  -> semantically minimal tool 선택
  -> log / code / database expert agent
  -> OBSK로 원 관측을 외부 key-value store에 보존
  -> JsonRegen·error handling으로 action 안정화
  -> finalization 시 trajectory-level self-consistency(TSC)
  -> root cause·solution·evidence·responsibility
```

- **전문 agent/tool**: controller가 원시 로그와 코드를 직접 모두 해석하지 않고 도메인별 agent에게 분석을 위임한다. SQL/SLS 같은 범용 query tool보다 의미가 좁은 tool이 작은 모델의 invalid action을 줄였다.
- **OBservation Snapshot Key(OBSK)**: 긴 tool output의 앞부분만 prompt에 두고 전체 내용은 key로 저장한다. controller가 필요할 때 원문을 다시 가져오므로 단순 truncation의 증거 손실을 줄인다.
- **JsonRegen과 error handling**: JSON-like output을 정리하고 YAML 변환을 거쳐 재생성해 구조화 tool call 실패를 복구한다.
- **Trajectory-level Self-Consistency**: 전체 trajectory를 처음부터 여러 번 실행하지 않고 finalization 직전에만 분기해 후보를 만들고 LLM으로 합친다. 앞선 greedy action history를 공유해 비용과 무작위 tool 오류를 낮춘다.

## 4. 모델·데이터셋·실험 설계

| 항목 | 원문에서 확인한 내용 |
|---|---|
| 대상 시스템 | Alibaba Cloud Real-time Compute Platform for Apache Flink |
| 모델 | Vicuna-13B-v1.5-16K, vLLM, 단일 NVIDIA A100 SXM4 80GB |
| decoding | 기본 greedy; self-consistency에서 Vicuna 기본 sampling |
| judge | frozen `gpt-4-0613`, greedy, 0–10 correctness/helpfulness |
| embedding | GTE-LARGE |
| offline 원천 | 한 달간 anomalous job 15,616건 -> non-trivial 약 5,000건 |
| 최종 offline set | 원인별 최대 2건의 class-balance 제약을 적용한 161 jobs |
| annotation | Flink Advisor 결과를 LLM이 4항목으로 요약 후 SRE가 교정 |
| 입력 | platform/runtime/infrastructure logs, advisor DB history, advisor code repositories |
| 비교 | ReAct, component ablation, XGBoost, fine-tuned T5, LLM summary |

현재 incident 이후의 정보를 보지 않도록 anomaly detection 이전 데이터만 tool이 조회한다. 또한 expert-agent의 retrieval history는 label 작성에 사용한 내용과 겹치지 않는다고 보고한다. 다만 15,616건에서 161건으로 줄이는 과정과 Advisor 기반 label 생성은 selection bias와 규칙 지식 의존을 남긴다.

## 5. 정량 결과와 ablation

### Offline 161 jobs

| 지표 | ReAct | RCAgent | RCAgent + TSC |
|---|---:|---:|---:|
| root-cause METEOR | 6.44 | 15.15 | 16.49±0.09 |
| root-cause G-Correctness / 10 | 3.06 | 5.22 | 5.47±0.06 |
| solution METEOR | 6.42 | 12.94 | 16.45±0.06 |
| solution G-Helpfulness / 10 | 3.41 | 5.48 | 5.69±0.02 |
| evidence METEOR | 11.82 | 28.10 | 30.84±0.43 |

구성요소 제거 시 root-cause METEOR는 expert agents 제거 9.60, JsonRegen 제거 13.89, OBSK 제거 12.37이었다. 즉 가장 큰 기여는 controller prompt가 아니라 전문 분석 tool이었다. OBSK 제거는 root-cause G-Correctness를 5.22에서 4.53으로 낮췄다.

### 안정성과 online OoD

- full RCAgent: 15-step 이내 pass rate 99.38%, invalid rate 7.93%, 평균 trajectory 6.78 steps.
- ReAct: pass rate 86.33%, invalid rate 22.82%, 7.48 steps.
- controller를 nucleus sampling으로 바꾸면 pass rate 70.19%, invalid rate 44.80%로 악화했다.
- 배치 초기 2주의 OoD jobs에서 RCAgent+TSC는 responsibility precision 82.06±0.42%, human helpfulness 2.92±0.21/5였다. ReAct는 각각 73.53%, 1.36±0.03이었다.
- human helpfulness의 ReAct 대비 차이는 TSC 포함 `t=5.84, p=0.001`, 미포함 `t=4.08, p=0.001`인 Tukey HSD로 보고했다.
- 데이터 양 증가에 따른 자원 사용은 거의 선형이었고(Pearson correlation의 모든 소비 유형 `p<0.05`), 성능 저하는 Kruskal–Wallis `p=1.0`으로 관찰되지 않았다고 보고했다.

Self-consistency는 표본 수 20 부근에서 포화한다. 그러나 대부분의 표준편차는 10 runs에 대해서만 제시되고, offline main comparison에는 confidence interval이나 paired test가 없다.

## 6. 실험 비평과 재현성

강점은 실제 대규모 Flink 운영 데이터, 시점 누출 방지, component ablation, human evaluation, 일부 통계 검정을 함께 제시한 점이다. agent가 실패하는 이유를 accuracy 하나가 아니라 pass/invalid/trajectory 지표로 해부한다.

재현성은 낮다. 논문은 코드·Flink 데이터·Advisor KB·prompt 전문을 공개하지 않으며, SRE가 만든 ground truth도 비공개다. 내부 Vicuna 배치 사양은 명확하지만 tool backend와 운영 데이터 없이는 end-to-end replication이 불가능하다. GPT-4 judge의 semantic preference와 SRE 평가자 수·inter-rater reliability도 충분히 보고되지 않았다. 원인별 최대 2건으로 만든 161건은 실제 long-tail 분포를 인위적으로 바꾼다.

## 7. SRE 직감 평가

운영에서 가장 설득력 있는 부분은 “큰 모델에게 모든 것을 맡기기”가 아니라 작은 모델이 실수하지 않게 tool을 좁히고 원 관측을 보존한 설계다. 다만 자동 조사 권한이 넓어질수록 stale state, 잘못된 query 범위, tool-side 데이터 누출이 새로운 failure mode가 된다. RCAgent의 높은 pass rate는 **정답의 인과적 타당성**보다 **workflow가 끝까지 실행되는 안정성**을 강하게 증명한다.

## 8. thesis-rca 적용과 차별점

- 직접 적용 후보: 긴 runtime/GitOps 관측을 요약으로 덮지 않고 provenance key와 함께 보존하는 OBSK형 evidence store.
- 직접 적용 후보: final answer 직전 제한된 반복 생성과 집계. 단, V2.3의 단일 독립변수 원칙상 retrieval/leakage 통제와 동시에 넣지 않는다.
- 경계: thesis-rca는 autonomous tool policy의 최고 성능을 주장하지 않는다. 고정 `gpt-4o-mini`와 동일 수집 campaign에서 Runtime·GitOps·RAG의 독립 기여와 leakage를 감사한다.
- 차별점: RCAgent는 rule-uncovered OoD 대응과 agent 안정성이 중심이고, thesis-rca는 desired/observed/reconciliation evidence의 provenance와 counterfactual validity가 중심이다.

## 9. 기억할 핵심 문구

원문의 핵심 표현은 “free-form data collection”, “Trajectory-level Self-Consistency”, “semantically minimalist tools”다. 이 논문의 실질적 교훈은 agent autonomy보다 **도구 표면·context 보존·decoding 안정화의 공동 설계**에 있다.

# GitOps-aware LLM Kubernetes RCA 심층 Scoping Review

> 조사일: 2026-08-09
> 조사 범위: 2018~2026, 핵심 2023~2026
> 검증 자료: 고유 논문 20편의 전문·표·실험 절 + Kubernetes/OpenGitOps/Argo CD/OpenTelemetry 공식 문서
> 성격: exhaustive systematic review가 아닌 재현 가능한 심층 scoping review
> 목적: thesis-rca의 근본 배경, 경쟁 연구 상황, 평가 타당성, 학술적 포지셔닝과 V2.3 설계 근거 정립

## 0. 결론부터

이 연구의 가장 강한 방향은 **새로운 RCA agent를 하나 더 만드는 것**이 아니다. 이미 Flow-of-Action, RCAgent, RCACopilot, SynergyRCA, MetaRCA, Auditable Graph-Guided RCA처럼 SOP·tool·graph·RAG·verification을 조합한 강한 선행연구가 있다.

본 논문의 방어 가능한 중심은 다음과 같다.

> **GitOps-managed Kubernetes에서 Runtime·GitOps·RAG context의 독립적 진단 기여를 분해하고, 관찰된 gain이 실제 evidence contribution인지 fault-label·runbook·manifest diff leakage, context 위치, judge 비결정성, trial contamination의 결과인지 감사한다.**

문헌과 현재 실험을 함께 보면 핵심 결론은 열 가지다.

1. **RCA는 label 맞히기가 아니라 증거가 지지하는 causal localization이다.** Root-cause entity, affected entity, propagation chain, supporting/contradicting evidence를 분리해야 한다.
2. **관측 신호를 더 많이 넣는다고 자동으로 좋아지지 않는다.** RCAEval에서는 multi-source CIRCA가 metric-only보다 나빴고, RCACopilot에서도 모든 source를 섞은 조건이 요약 진단정보만 쓴 조건보다 낮았다.
3. **구조와 pruning이 중요하다.** MetaRCA는 online pruning 제거 시 production AC@3가 service 0.88→0.63, metric 0.82→0.56으로 하락했다.
4. **Kubernetes state graph는 유망하지만 순수 기여가 충분히 분리되지 않았다.** SynergyRCA는 두 production cluster에서 precision 0.88/0.92를 보고했으나 no-graph·flat-RAG baseline과 end-to-end ablation이 없다.
5. **SOP/RAG 지식은 강력한 동시에 shortcut이 될 수 있다.** Flow-of-Action은 SOP Knowledge 제거 시 54.06%→15.39%로 떨어졌지만, thesis V2.2의 자기 런북 회수는 같은 지식 주입이 정답 누출로 변할 수 있음을 보였다.
6. **headline gain은 audit 후 크게 줄 수 있다.** Auditable Graph-Guided RCA는 entity F1 0.6087→0.9130을 보였지만 hint 제거 조건의 이전 iteration 대비 순증가는 약 1.2%p였다.
7. **시간·위치·실행 캠페인은 독립 교란변수다.** CloudRanger는 window에 따라 AC@1이 98.6%에서 12.0%까지 변했고, Lost in the Middle은 같은 증거의 위치만으로 20%p 이상 차이를 보였다.
8. **LLM judge도 측정 오차의 원천이다.** position·verbosity bias가 있고, 반복 judge의 Krippendorff α가 task/model에 따라 0.265~0.788 수준으로 흔들렸다.
9. **GitOps 직접 선행연구는 비어 있다.** 조사 범위에서 Argo CD/Flux의 desired·observed·reconciliation signal을 LLM RCA에 넣고 runtime-only 대비 정량 ablation한 논문은 찾지 못했다.
10. **따라서 thesis의 새로움은 성능 최고치보다 평가 설계에 있다.** blind retrieval, full/masked/no-diff, length placebo, 동일 캠페인, generation/judge 반복, evidence provenance를 결합하는 것이 가장 방어 가능하다.

## 1. RCA를 근본에서 다시 정의하기

### 1.1 증상, 원인 후보, 근본 원인은 다르다

분산 시스템 장애에는 최소 네 층이 있다.

```text
사용자 영향
  <- 서비스 증상
     <- Kubernetes observed-state 변화
        <- 직접 fault 또는 잘못된 desired state / reconcile failure
```

- **사용자 영향**: checkout 실패, latency 증가, error rate 증가
- **증상**: pod restart, OOMKilled, endpoint 0, trace 단절, CPU throttling
- **원인 후보**: 특정 workload, node, config object, change, controller action
- **근본 원인**: 증상을 발생시킨 가장 상류의 intervention·state mismatch·resource failure

CloudRanger와 MicroRCA는 propagation graph에서 symptom service와 culprit service를 구별하려 했다. Auditable Graph-Guided RCA는 entity identification, propagation chain, localization, reasoning을 별도 metric으로 둔다. 이는 exact fault label 하나만 채점하면 RCA의 핵심을 놓친다는 뜻이다.

### 1.2 상관, graph edge, 인과는 같은 말이 아니다

전통 AIOps RCA는 metric correlation과 topology를 결합해 후보를 순위화한다. 하지만 observational time series의 conditional dependence, PageRank edge, rule-built relation은 intervention으로 검증한 causal effect가 아니다.

[Causal Inference RCA empirical study](../papers/causal-inference-rca-how-far.md)는 9개 causal discovery method의 directed F1이 synthetic graph에서도 0.04~0.54에 머물고, 대형 Train Ticket에서는 많은 방법이 random baseline과 비슷하거나 지나치게 느리다고 보고했다. 따라서 본 논문에서 `causal contribution`은 “LLM이 causal graph를 만들었다”는 선언이 아니라 다음 조건을 의미해야 한다.

1. 같은 incident에서 context source만 바꾼 paired comparison
2. fault와 context 사이의 예상 visibility 사전 명시
3. 정답을 직접 노출하는 evidence 제거 또는 masking
4. supporting·contradicting evidence와 chain 기록
5. 동일 campaign·collection timing 유지

### 1.3 Observability는 evidence의 재료이지 정답이 아니다

[OpenTelemetry](https://opentelemetry.io/docs/concepts/signals/)는 traces, metrics, logs를 서로 다른 system output으로 정의한다.

| Signal | 주로 답하는 질문 | RCA 한계 |
|---|---|---|
| Metrics | 무엇이 얼마나 변했는가 | aggregation으로 원인 entity와 순서 손실 |
| Logs/Events | 어떤 discrete event가 발생했는가 | noise·template·시간 동기화 문제 |
| Traces | 요청이 어디를 통과했는가 | sampling·instrumentation gap·downstream symptom 편향 |
| Kubernetes state | 어떤 object가 어떤 상태인가 | snapshot race와 controller-induced transient |
| Change/GitOps | 무엇을 의도했고 어떻게 적용됐는가 | 정답 entity 노출과 recency bias |
| Runbook/RAG | 어떤 절차·과거 지식이 있는가 | self-runbook·label leakage |

RCA의 성능은 LLM의 추론 능력만이 아니라 collector completeness, time alignment, provenance, context serialization에 의해 결정된다.

## 2. Kubernetes와 GitOps가 RCA를 어렵게 만드는 이유

### 2.1 Kubernetes는 계속 수렴 중인 시스템이다

[Kubernetes controller 문서](https://kubernetes.io/docs/concepts/architecture/controller/)에 따르면 controller는 current state를 desired state에 가깝게 만드는 non-terminating control loop다. 이 구조에서 하나의 장애는 다음처럼 여러 state를 만든다.

```text
desired spec
  -> reconciliation attempt
     -> observed object transition
        -> replacement pod / event / metric / log / trace
           -> user-visible symptom
```

따라서 pod 상태 한 장면만 보면 다음을 구별하기 어렵다.

- desired state 자체가 잘못됨
- controller가 desired state를 적용하지 못함
- 적용은 됐지만 workload가 실패함
- runtime fault를 controller가 자동 복구 중임
- 이전 trial의 잔류 object가 현재 증상처럼 보임

SynergyRCA가 timestamped StateGraph와 entity reconciliation을 사용한 이유가 여기에 있다. 반대로 5분 snapshot을 느슨하게 허용했을 때 precision이 올라간 것은 state timing이 평가 기준 자체를 흔든다는 증거다.

### 2.2 GitOps는 RCA에 세 번째 상태축을 추가한다

[OpenGitOps](https://opengitops.dev/)는 desired state가 declarative·versioned·immutable하게 저장되고 agent가 이를 pull하여 actual state와 지속적으로 reconcile하는 것을 핵심 원칙으로 둔다. 이때 RCA evidence는 세 층으로 나뉜다.

| State | 예 | 진단 가치 | 누출 위험 |
|---|---|---|---|
| Desired | Git revision, manifest spec, intended resource graph | 무엇을 의도했는지 | fault field/value가 정답을 직접 노출 |
| Observed | live object spec/status, pod/node/event | 실제로 무엇이 일어났는지 | injection annotation·object name 노출 |
| Reconciliation | sync/health, drift, retry, prune, error | 의도와 실제가 왜 수렴하지 못했는지 | controller error가 원인명을 직접 포함 |

[Argo CD diff 문서](https://argo-cd.readthedocs.io/en/stable/user-guide/diffing/)는 successful sync 직후에도 mutating webhook, HPA reordering, unknown field 제거, pruning 미수행 등으로 OutOfSync가 발생할 수 있음을 설명한다. 즉 diff는 곧 원인이 아니며, controller-generated 정상 변화와 fault-linked 변화가 섞일 수 있다.

### 2.3 GitOps evidence의 장점과 함정

장점:

- runtime symptom보다 upstream에 있는 change provenance를 제공한다.
- rollback 가능한 revision·field·actor를 알려준다.
- desired/live mismatch와 reconcile failure를 구분할 수 있다.
- temporal ordering과 ownership 관계를 복원할 수 있다.

함정:

- 최근 commit을 무조건 원인으로 보는 recency bias
- manifest diff가 정답 field/value를 그대로 보여주는 leakage
- high-degree Argo/Flux controller가 모든 incident의 중심 node가 되는 graph bias
- controller retry를 여러 독립 evidence로 중복 집계
- imperative fault에서는 GitOps에 아무 신호가 없어 구조적으로 placebo가 됨

## 3. 선행연구의 발전 계보

### 3.1 1세대: metric·topology·random-walk RCA

- [CloudRanger](../papers/cloudranger.md): topology 없이 metric dependency graph를 학습. Pymicro latency AC@1 59.4%, window 민감성 큼.
- [MicroRCA](../papers/microrca.md): service response time, host/container resource, topology를 attributed graph로 결합. Kubernetes Sock Shop 95 cases에서 PR@1 0.89.
- [CloudRCA](../papers/cloudrca.md): KPI·log·CMDB topology·expert prior를 Bayesian network로 결합. topology 제거 시 platform별 F1이 최대 0.74→0.47로 하락.

교훈은 topology와 multi-source join이 유용하다는 것이지만, correlation graph를 causal proof로 간주하면 안 된다는 점이다.

### 3.2 2세대: change/event intelligence

- [GROOT](../papers/groot-event-graph.md): deployment/configuration activity를 metric/log event와 graph로 연결. eBay 952 incidents에서 Top-1 78%, Top-3 95%; live에서는 missing event로 최대 9%p 하락.
- [ChangeRCA](../papers/changerca.md): dependency·change flow·KPI·time을 결합해 defective change를 찾음. WeChat+Online Boutique에서 평균 HR@1 85.78%, HR@3 96%; graph 제거 영향이 큼.
- [EventADL](../papers/eventadl-cloud-intervention-events.md): actor-operation-resource intervention graph. 520 production incident 분석에서 68%가 multiple interventions를 포함.
- [KGroot](../papers/kgroot-kubernetes-fault-event-knowledge-graph.md): historical fault event graph와 online event graph를 비교. Kubernetes dataset A@3 93.5%를 보고했으나 Top-k/F1 표 내부 불일치가 있어 수치 신뢰에 주의.

이 연구들은 change가 RCA evidence가 될 수 있음을 보였지만 GitOps desired·observed·reconciliation을 분리하지 않았다.

### 3.3 3세대: LLM이 운영 지식과 tool을 사용

- [RCACopilot](../papers/rcacopilot-cloud-incidents.md): handler가 수집한 진단정보를 요약하고 과거 incident를 few-shot으로 제공. 653 production incidents에서 Micro-F1 0.766.
- [RCAgent](../papers/rcagent-tool-augmented-agents.md): specialist tool, observation snapshot key, JSON recovery, trajectory self-consistency. 161 offline jobs에서 ReAct 대비 correctness·evidence score 향상, online responsibility precision 82.06%.
- [Flow-of-Action](../papers/flow-of-action.md): SOP와 5-agent flow. Online Boutique에서 ReAct 35.50% 대비 64.01%; SOP knowledge 제거가 가장 큰 하락.
- [SpecRCA](../papers/specrca-hypothesize-verify.md): 병렬 hypothesis 생성 후 독립 verify. 후보 탐색 방향은 유망하지만 component ablation·반복·CI가 부족한 preliminary evidence.

교훈은 LLM 단독 지식보다 tool surface, structured procedure, relevant context가 더 큰 레버라는 것이다. 동시에 handler·SOP·runbook이 label shortcut인지 검사해야 한다.

### 3.4 4세대: graph-RAG와 claim audit

- [SynergyRCA](../papers/synergyrca-stategraph-llm.md): Kubernetes StateGraph/MetaGraph와 GPT-4o. 619/843 examples에서 precision 0.88/0.92, 평균 119~131초와 매우 큰 input token 비용.
- [MetaRCA](../papers/metarca.md): metadata-level causal graph에 LLM·incident report·statistical evidence를 융합. 252 public+59 production failures; production AC@3 0.88/0.82(service/metric).
- [Auditable Graph-Guided RCA](../papers/auditable-graph-guided-rca.md): graph traversal에 same-judge, prompt ablation, cascade-source, telemetry no-leak audit 결합. headline gain 대부분이 hint 제거 후 사라짐.

이 단계에서 연구 질문은 “LLM이 RCA를 할 수 있는가?”에서 “어떤 evidence와 architecture가 어떤 shortcut을 통제한 뒤에도 기여하는가?”로 이동한다.

## 4. 핵심 논문 비교표

서로 다른 task·metric·judge의 절대 수치는 직접 순위표로 해석하지 않는다.

| 연구 | 환경·표본 | 핵심 기법 | 대표 정량 결과 | thesis에 주는 근거 | 핵심 한계 |
|---|---|---|---|---|---|
| CloudRanger 2018 | Pymicro+IBM Bluemix | dynamic graph+2nd-order RW | latency AC@1 59.4% | timing/window audit | production n·CI 불명 |
| MicroRCA 2020 | K8s Sock Shop 95 | attributed graph+PPR | PR@1 .89 | telemetry/topology 결합 | 3 fault, 단일 system |
| GROOT 2021 | eBay 952 | event graph+change | Top-1 78%, Top-3 95% | change provenance | change-only ablation 없음 |
| CloudRCA 2021 | Alibaba 3 platforms | KPI+log+CMDB KHBN | best baseline 대비 F1 +.09~.19 | topology prior | 비표준 F1, private data |
| ChangeRCA 2024 | 81 cases | dependency+change flow | HR@1 85.78% | concurrent normal change 통제 | production 30건 |
| RCACopilot 2024 | 653 incidents | workflow+summary+retrieval | Micro/Macro F1 .766/.533 | context source ablation | retrieval leakage 미감사 |
| RCAgent 2024 | 161+online OoD | tool-agent+OBSK+TSC | responsibility precision 82.06% | evidence 보존·agent 안정성 | private artifact |
| Flow-of-Action 2025 | Online Boutique 90 | SOP+5-agent | 35.50%→64.01% | structured knowledge 기여 | SOP label shortcut 위험 |
| [RCAEval 2025](../papers/rcaeval.md) | 3 systems 735 | 공개 multimodal benchmark | 최고 평균 AC@1 .69 | dual scoring·public baseline | GitOps fault 없음 |
| SynergyRCA 2025 | production K8s 1,462 | StateGraph+LLM | precision .88/.92 | K8s temporal graph | no-graph E2E ablation 없음 |
| KGroot 2024 | 99+156 failures | event KG+RGCN | K8s A@3 93.5% | historical graph | 원문 표 불일치 |
| SpecRCA 2026 | AIOps2022 | hypothesize-verify | recall/latency 개선 보고 | alternative hypothesis | preliminary, ablation 부족 |
| EventADL 2026 | 520 reports+benchmarks | intervention graph | benchmark AC@3 1.00 | actor-operation-resource schema | real RCL 2 incidents |
| MetaRCA 2026 | public 252+prod 59 | meta causal knowledge | prod AC@3 .88/.82 | prior+online pruning | private production corpus |
| Auditable Graph RCA 2026 | ITBench 19/23 | typed graph+claim audit | F1 .6087→.9130; stripped .6958 | shortcut 감사 | single-run, 자체 baseline |

## 5. 가장 중요한 연구 상황: 무엇이 이미 해결됐고 무엇이 비었는가

### 5.1 이미 경쟁이 강한 영역

- SOP·multi-agent architecture 자체
- tool-augmented autonomous investigation
- incident summary와 similar-case retrieval
- Kubernetes StateGraph와 graph database retrieval
- causal/meta-knowledge graph와 online pruning
- hypothesize-then-verify reasoning
- generic auditable graph-guided RCA

이 영역에서 “우리도 agent/RAG/graph를 썼다”는 것만으로는 기여가 약하다.

### 5.2 여전히 열린 영역

1. **GitOps-specific signal model**: desired·observed·reconciliation을 별도 evidence source로 정의한 정량 평가
2. **GitOps-specific leakage taxonomy**: full diff, masked diff, no diff, commit message, controller error의 누출 위험
3. **RAG utility와 self-runbook shortcut 분리**
4. **동일 incident에서 Runtime·GitOps·RAG·length를 직교화한 context factorial design**
5. **trial contamination과 campaign history를 평가 설계의 1차 요소로 다루는 연구**
6. **generation variance와 judge variance를 분리한 Kubernetes RCA 평가**

### 5.3 직접 선행연구 부재의 해석

이번 검색에서 Argo CD/Flux signal을 직접 사용한 정량 LLM-RCA 논문을 찾지 못했다. 이는 `최초`를 바로 주장할 근거가 아니다. 검색 DB·키워드·비영문 문헌·비공개 산업 연구의 한계가 있기 때문이다.

안전한 표현은 다음과 같다.

> 조사된 2018~2026 1차 문헌에서는 change/event intelligence와 Kubernetes graph-RCA는 확인됐지만, GitOps desired·observed·reconciliation context의 독립 기여와 leakage를 함께 ablation한 정량 LLM-RCA 연구는 확인하지 못했다.

## 6. 평가 타당성: 이 분야의 가장 큰 취약점

### 6.1 Evidence leakage

leakage는 label 문자열만의 문제가 아니다.

| Leakage 수준 | 예 | 필요한 통제 |
|---|---|---|
| 직접 label | `NetworkDelay`, `OOMKill` | label masking |
| entity | fault injector object, target service명 | entity masking 또는 downstream target 재정의 |
| procedural | 자기 fault의 runbook | blind/procedure-only/cross-fault retrieval |
| manifest | 잘못된 port·image·resource 값 | full/masked/no-diff |
| metadata | injection annotation, commit message | provenance allow-list |
| judge | reference에 fault-specific 설명 | reference audit |

[Controlled contamination study](../papers/controlled-data-contamination-impact.md)는 source-target가 결합된 full contamination이 clean task gain과 달리 최대 30 BLEU의 평가 inflation을 만들 수 있음을 보였다. pretraining contamination과 test-time RAG leakage는 다른 현상이지만, input과 target의 결합 노출이 능력보다 점수를 부풀린다는 통제 원리는 같다.

### 6.2 Context length와 위치

[Lost in the Middle](../papers/lost-in-the-middle.md)은 동일 문서 집합에서 정답 문서 위치만 바꿔 20%p 이상 차이를 보였다. 따라서 V2.3은 다음을 기록해야 한다.

- total tokens와 source별 token 수
- 핵심 evidence의 start token과 상대 위치
- section ordering seed
- top-k retrieval recall과 RCA correctness
- 대표 subset의 front/middle/end paired audit

### 6.3 Judge reliability

[Judging LLM-as-a-Judge](../papers/judging-llm-as-a-judge.md)는 GPT-4의 위치 일관성이 default 65.0%였고, verbosity attack failure도 확인했다. [Rating Roulette](../papers/rating-roulette.md)은 같은 judge를 3회 돌린 self-reliability가 MT-Bench에서 α 0.265~0.563, factual task에서도 0.326~0.788에 머물 수 있음을 보였다.

최소 평가 세트:

```text
case × arm × generation_repeat × judge_repeat × blinded_order
```

- 원 judge vote 보존
- majority correctness와 unanimous/split rate
- nominal/ordinal Krippendorff α
- system/arm label blinding
- A/B와 B/A 순서 교환
- human calibration subset
- threshold sweep와 paired CI

### 6.4 Trial contamination과 operational attrition

실패 trial을 common subset에서 제외하면 model accuracy와 system reliability가 섞인다. 다음을 별도 outcome으로 둬야 한다.

- injection success
- evidence collection completeness
- recovery success
- LLM generation success
- judge completion
- final scored case

V2.2처럼 다른 시점에 재수집한 fault group은 arm 간 paired 비교에는 사용할 수 있어도 fault-category 비교에는 campaign confounding이 남는다.

### 6.5 통계

fault×trial 반복은 완전 독립 표본이 아니다. trial-level McNemar만 쓰면 같은 fault의 반복을 독립 증거로 과대계상할 수 있다.

권장 순서:

1. paired effect size와 confidence interval
2. fault-cluster bootstrap 또는 mixed-effects model
3. threshold 0.5/0.6/0.7 사전 지정 sweep
4. fault-level majority 보조 분석
5. accuracy 외 evidence precision·unsupported claim·attrition 보고

## 7. V1~V2.2를 문헌으로 다시 해석하기

| 실험 | 관찰 | 문헌 기반 해석 | 논문에서 허용되는 주장 |
|---|---|---|---|
| V1 | System B 84% | prompt/evidence leakage 사례 | 성능 증거가 아니라 shortcut 사례 |
| V2~V3 | 힌트 제거 후 26/42, harness 30/40 | context·evaluation 구조 영향 | 공정 baseline 형성 과정 |
| V6 | SOP 회귀 | Flow-of-Action의 SOP 효과가 domain/fault taxonomy에 자동 일반화되지 않음 | SOP early-confirmation failure |
| V7~V8 | network fault 실패·잔류 신호 | collector completeness와 contamination이 reasoning보다 선행 | trial isolation의 중요성 |
| V2.1 | threshold 0.5/0.6 순위 역전 | judge/threshold measurement artifact | 단일 임계값 성능 주장 금지 |
| V2.2 | RAG 65%, baseline 31.7% | self-runbook 75%로 retrieval leakage 유력 | RAG 내용은 유효하나 reasoning gain 미확정 |
| V2.2 | GitOps=placebo 36.7% | imperative injection과 path error로 signal 손상 | GitOps 무효 판정 보류 |

중요한 전환은 실패를 버리는 것이 아니라 validity evidence로 승격하는 것이다. V1은 leakage 사례, V6은 SOP shortcut, V8은 contamination, V2.1은 judge instability, V2.2는 retrieval leakage와 damaged treatment 사례다.

## 8. 본 논문의 권장 연구질문과 기여

### 8.1 연구질문

| ID | 권장 질문 | 핵심 estimand |
|---|---|---|
| RQ1 | Runtime-only 대비 GitOps와 RAG의 독립 기여는 무엇인가? | paired arm difference |
| RQ2 | label·runbook·manifest leakage를 제거한 뒤 gain이 남는가? | full−masked shortcut, masked−no-context residual utility |
| RQ3 | judge·threshold·context 위치·campaign이 순위에 미치는 영향은? | robustness and variance decomposition |
| RQ4 | desired·observed·reconciliation 중 어떤 signal이 어떤 fault에서 유효한가? | source×fault-group interaction |

### 8.2 잠정 기여

1. **Context contribution design**: Runtime·GitOps·RAG·length를 분해한 통제 실험
2. **GitOps evidence model**: desired·observed·reconciliation provenance schema
3. **Leakage audit**: self/masked/cross/no-RAG와 full/masked/no-diff
4. **Measurement reliability**: repeated generation, blinded repeated judge, threshold sweep
5. **Operational validity**: identical campaign, recovery gate, attrition accounting

### 8.3 경쟁 논문 대비 한 문장

- Flow-of-Action 대비: SOP architecture가 아니라 지식 주입의 순기여와 shortcut을 평가한다.
- RCACopilot 대비: production category retrieval이 아니라 context source의 causal contribution을 분리한다.
- RCAgent 대비: autonomous tool policy보다 evidence provenance와 evaluation validity가 중심이다.
- SynergyRCA 대비: StateGraph 절대 precision이 아니라 GitOps signal source별 effect를 동일 incident에서 비교한다.
- MetaRCA 대비: cross-system meta knowledge가 아니라 control-loop evidence와 leakage의 독립 효과를 측정한다.
- Auditable Graph RCA 대비: generic prompt/telemetry audit를 GitOps diff·reconciliation·runbook retrieval로 확장한다.

## 9. V2.3 브레인스토밍: 최소 실험과 확장 실험

### 9.1 먼저 고정할 fault taxonomy

각 fault는 결과를 보기 전에 다음 필드를 가져야 한다.

```yaml
fault_id:
fault_group:
target_entity:
injection_mode: declarative | imperative | infrastructure
expected_runtime_visibility:
expected_desired_visibility:
expected_reconciliation_visibility:
rag_self_document_exists:
leakage_risk:
causal_distance:
```

특히 imperative fault에서 GitOps signal이 보이지 않는 것은 실패가 아니라 예상된 negative control일 수 있다.

### 9.2 최소 causal contrast

범위를 억제하려면 V2.3의 1차 질문을 retrieval leakage에 둔다.

| Arm | 목적 |
|---|---|
| Runtime-only | 기준선 |
| Length placebo | token/attention 효과 |
| Self-runbook full | 운영 총유용성 상한 |
| Self-runbook masked/procedure-only | label 제거 후 잔여 지식 기여 |
| Cross-fault or irrelevant runbook | retrieval specificity control |

주요 분해:

- `full − masked` = direct/semantic shortcut 성분
- `masked − runtime` = procedure knowledge의 잔여 기여
- `cross − runtime` = 무관 retrieval의 오염 효과
- `placebo − runtime` = 길이/attention 효과

### 9.3 GitOps arm은 signal integrity 후 별도 factor로

GitOps 효과는 다음 gate를 통과한 뒤 평가한다.

1. fault-linked desired change 존재
2. expected live-state transition 수집
3. reconciliation event/status 수집
4. Git path·revision·resource identity 연결
5. injection label·annotation 제거

그 뒤 다음 source ablation을 수행한다.

| Condition | 포함 신호 |
|---|---|
| no-GitOps | runtime only |
| metadata-only | revision/resource/timestamp, 값 없음 |
| masked-diff | field path·direction, 정답 value 제거 |
| full-diff | 실제 desired change |
| reconciliation-only | sync/health/error/retry |

### 9.4 출력과 채점

최종 응답 schema:

```json
{
  "root_cause_type": "",
  "root_cause_entity": "",
  "affected_entity": "",
  "supporting_evidence": [],
  "contradicting_evidence": [],
  "causal_chain": [],
  "alternative_hypotheses": [],
  "confidence": 0.0
}
```

채점은 fault label 정확도, entity localization, evidence grounding, chain validity, unsupported claim, confidence calibration을 분리한다.

### 9.5 성공·기각 기준

- masked RAG가 runtime 대비 paired CI에서 양의 효과를 유지하면 procedure knowledge 기여를 지지한다.
- full만 높고 masked가 baseline으로 돌아가면 V2.2 gain은 shortcut 중심으로 판정한다.
- GitOps 효과가 deployment-visible fault에서만 나타나고 infrastructure fault에서 0이면 fault-selective contribution으로 해석한다.
- signal integrity가 실패하면 accuracy 차이를 GitOps 효과로 해석하지 않고 treatment failure로 처리한다.

## 10. 논문 보고서·장별 활용안

| 논문 장 | 사용할 내용 | 핵심 자료 |
|---|---|---|
| 서론 | K8s 동적 control loop, RCA의 evidence 문제 | Kubernetes/OpenGitOps 공식 문서 |
| 배경 | telemetry, topology, change, desired/observed/reconcile | CloudRanger, MicroRCA, GROOT, EventADL |
| 관련연구 | traditional→LLM→graph/audit 계보 | 20개 paper notes |
| 문제정의 | context contribution과 leakage | Auditable RCA, contamination, Lost in the Middle |
| 방법론 | factorial/placebo/masking/repetition | RCACopilot, MetaRCA, judge papers |
| 실험설계 | fault taxonomy, campaign, dual scoring | RCAEval, causal RCA empirical study |
| 결과 | effect size·CI·robustness·attrition | V2.3 결과 |
| 논의 | shortcut, generalization, production boundary | V1~V2.2 실패 재해석 |

## 11. Claim–Evidence Ledger

| Claim 후보 | 근거 | 상태 | 허용 표현 |
|---|---|---|---|
| topology/context 구조는 RCA에 기여할 수 있다 | CloudRCA topology ablation, MetaRCA pruning | 지지 | 해당 dataset·architecture에서 기여 |
| 더 많은 modality가 항상 낫다 | RCAEval, RCACopilot 반례 | 기각 | source relevance와 구조가 중요 |
| SOP/RAG 지식은 RCA를 향상시킨다 | Flow-of-Action | 조건부 지지 | label leakage 통제 전 추론 gain 불명 |
| graph-RAG가 Kubernetes RCA에 유용하다 | SynergyRCA | 조건부 지지 | 절대 precision은 높으나 순수 graph effect 미분리 |
| LLM judge 단일 호출은 안정적이다 | judge studies | 기각 | 반복·blinding·reliability 필요 |
| GitOps context가 항상 유용하다 | 직접 근거 없음 | 미지 | fault visibility에 따라 달라질 가설 |
| V2.2 RAG 65%는 reasoning 향상이다 | self-runbook 75% | 미지/과장 위험 | leakage 통제 전 총유용성 관측치 |
| V2.2 GitOps 36.7%는 무효 근거다 | signal 손상·placebo 동률 | 기각 | treatment integrity 복구 전 판정 보류 |
| 본 연구는 auditable RCA 최초다 | Auditable Graph RCA 존재 | 기각 | GitOps-specific audit 확장으로 포지셔닝 |
| 본 연구는 production-ready다 | 단일 cluster·synthetic faults | 기각 | controlled benchmark 결과로 한정 |

## 12. 조사 로그와 선정 현황

### 12.1 조사 축

1. 전통 RCA·causal/topology
2. microservice·Kubernetes benchmark
3. LLM RCA architecture
4. GitOps/change intelligence
5. RAG/context leakage
6. judge·evaluation reliability

### 12.2 포함된 고유 논문 20편

- 전통/causal/topology: CloudRanger, MicroRCA, CloudRCA, Causal Inference RCA empirical study
- change/event: GROOT, ChangeRCA, KGroot, EventADL
- benchmark: RCAEval
- LLM RCA: RCACopilot, RCAgent, Flow-of-Action, SynergyRCA, SpecRCA
- graph/audit: MetaRCA, Auditable Graph-Guided RCA
- 평가 인접 근거: Lost in the Middle, Controlled Data Contamination, Judging LLM-as-a-Judge, Rating Roulette

### 12.3 제외·보류

| 후보 | 처리 | 이유 |
|---|---|---|
| MHP-RCA | 보류 | paywall로 전문 검증 불가; 2차 수치만으로 포함하지 않음 |
| generic RAG/agent 논문 | 제외 | RCA·evaluation validity에 직접 전이 근거 부족 |
| vendor blog·상업 성능 주장 | 제외 | 1차 실험·재현 정보 부족 |
| OpenGitOps/Kubernetes/Argo docs | 논문 수에서 제외 | 기술 정의용 공식 표준·문서 |

### 12.4 조사 한계

- scoping review이며 formal database export·PRISMA systematic review는 아니다.
- 최신 2026 preprint는 peer review 전일 수 있다.
- proprietary production dataset의 수치는 독립 재현할 수 없다.
- 서로 다른 RCA task·ground truth·metric·judge의 절대 성능을 직접 비교할 수 없다.
- “직접 GitOps LLM-RCA 논문을 찾지 못함”은 부재의 증명이나 최초성 증명이 아니다.

## 13. 최종 권고

V2.3의 목표를 성능 상승으로 두지 말고 **오염을 제거한 뒤 남는 context contribution의 크기와 불확실성을 측정하는 것**으로 둬야 한다.

가장 안전한 논문 메시지는 다음과 같다.

> GitOps와 RAG는 Kubernetes RCA에 잠재적으로 유용한 upstream knowledge를 제공하지만, context gain은 정보량·정답 노출·evidence 위치·judge·campaign 상태에 의해 쉽게 과대평가된다. 본 연구는 동일 incident에서 evidence source와 leakage 수준을 분리하고, 어떤 fault에서 어떤 state signal이 실제 진단 기여를 남기는지 감사 가능한 방식으로 측정한다.

이 메시지는 현재 V2.2의 실패를 숨기지 않는다. 오히려 그 실패들을 연구 기여의 근거로 바꾼다.

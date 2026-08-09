# 논문 심층 분석: MetaRCA — A Generalizable RCA Framework Powered by Meta Causal Knowledge

> 분석일: 2026-08-09
> 분석자: 20년차 cloud SRE 관점
> 논문: Shuai Liang et al., FSE 2026 accepted paper
> 원문: https://arxiv.org/abs/2603.02032
> 전문 검증: https://arxiv.org/html/2603.02032v1

## 1. 한 줄 요약

LLM·사고보고서·통계적 causal discovery를 metadata-level causal graph로 축적하고, incident 시점의 topology와 telemetry로 국소화·가중·pruning하여 서로 다른 cloud-native system에서도 재학습 없이 RCA하려는 hybrid framework다.

## 2. 핵심 문제와 기존 한계

전통 causal RCA는 대체로 system instance마다 graph를 다시 학습한다. 이 방식은 서비스 수가 늘면 계산량과 spurious edge가 증가하고, topology가 바뀌면 학습된 graph가 재사용되지 않으며, domain knowledge를 규칙으로 넣으면 유지비가 커진다.

MetaRCA는 문제를 세 축으로 정의한다.

1. system complexity에 대한 scalability
2. 다른 topology로의 generalization
3. LLM·사고보고서·observability evidence의 안정적 결합

## 3. 핵심 기법과 원리

### 3.1 Meta Causal Graph

특정 서비스 이름이 아니라 component type, metric type, connection pattern 수준으로 causal relation을 추상화한다. Gemini 2.5 Flash가 skeleton graph를 bootstrapping하지만 초기 belief는 0.5로 두어 LLM 출력을 확정 사실로 취급하지 않는다.

### 3.2 Evidence-driven evolution

- 563개 production incident report에서 DeepSeek R1-70B로 cause/effect entity를 추출한다.
- RCAEval-RE1 375건과 AIOps2022 239건에서 PCMCI를 사용해 통계적 causal evidence를 추출한다.
- service dependency와 맞지 않는 edge를 제거하고 metadata relation으로 정렬한다.
- report evidence와 statistical evidence를 log-odds 형태로 누적하고 시간 감쇠를 적용한다.

저자는 expert-reviewed report를 더 신뢰해 base impact를 0.5, statistical evidence를 0.05로 비대칭 설정한다.

### 3.3 Online instantiation and pruning

장애 시점에는 전체 graph를 탐색하지 않는다. 현재 topology와 anomaly로 Fault Relevance Zone을 만들고 MCG를 local causal graph로 instantiate한 뒤 real-time data로 edge를 가중하고 threshold 0.3에서 prune한다. 이 과정이 knowledge prior를 현재 incident evidence에 맞게 제한한다.

## 4. 실험 결과와 비평

### 4.1 데이터셋

| 구분 | 시스템 | Cases | Services |
|---|---|---:|---:|
| Public | Online Boutique | 90 | 12 |
| Public | Sock Shop | 90 | 15 |
| Public | Train Ticket | 72 | 64 |
| Production | 4개 subsystem | 59 | 9~112 |

Production 59건은 offline MCG 구축용 incident report와 겹치지 않는다고 명시한다. Public dataset은 6개 fault type의 injection point를 ground truth로 사용한다.

### 4.2 주요 정확도

AC@1 기준 예시는 다음과 같다.

| Dataset | MetaRCA service | MetaRCA metric | 강한 비교점 |
|---|---:|---:|---|
| RE2-OB | 0.66 | 0.21 | CIRCA 0.27/0.17 |
| RE2-SS | 0.79 | 0.19 | CIRCA 0.86/0.29 |
| RE2-TT | 0.75 | 0.33 | CIRCA 0.64/0.17 |
| Production | 0.66 | 0.54 | CIRCA 0.38/0.12 |

MetaRCA가 모든 cell에서 항상 최고는 아니다. Sock Shop AC@1에서는 CIRCA가 앞선다. 그러나 production과 큰 Train Ticket에서 service·metric localization의 균형이 좋다.

Production AC@3는 service 0.88, metric 0.82이며 평균 RCA time은 0.90초다. OpenRCA는 production에서 AC@1 service 0.20, metric 0.10, 평균 384.22초로 보고됐다. 다만 OpenRCA와 MetaRCA는 online inference 구조와 출력 granularity가 달라 단순 speed ratio는 신중히 해석해야 한다.

### 4.3 Ablation

| Variant | RE2-TT service/metric AC@3 | Production service/metric AC@3 |
|---|---:|---:|
| Full | 0.88 / 0.76 | 0.88 / 0.82 |
| report evidence 제거 | 0.83 / 0.63 | 0.80 / 0.72 |
| data evidence 제거 | 0.81 / 0.70 | 0.86 / 0.76 |
| 모든 evidence 제거 | 0.80 / 0.62 | 0.79 / 0.70 |
| online pruning 제거 | 0.78 / 0.51 | 0.63 / 0.56 |

가장 큰 하락은 online pruning 제거에서 발생한다. 이것은 “많은 지식을 넣는 것”보다 **현재 incident와 무관한 causal path를 제거하는 것**이 더 중요하다는 강한 증거다. Production에서는 report evidence가 statistical evidence보다 더 크게 기여한다.

### 4.4 Graph-quality 통제 실험

같은 PageRank ranker에 graph만 바꾼 production 실험에서 MetaRCA graph는 service 0.82, metric 0.71을 보였고 CIRCA graph는 0.31, 0.14였다. 최종 ranker보다 graph construction 품질이 결과를 지배할 수 있음을 보여준다.

### 4.5 강점

- public 252건과 production 59건, 총 7개 system을 사용한다.
- knowledge graph 구성요소와 online pruning을 ablation으로 분리한다.
- coarse service와 fine metric localization을 함께 보고한다.
- offline knowledge와 online incident context의 역할을 분리한다.

### 4.6 한계

- production dataset과 563개 report corpus는 공개되지 않아 독립 재현이 어렵다.
- hyperparameter가 validation set에서 조정됐지만 구체적 split과 leakage 방어가 충분히 설명되지 않는다.
- AC@k는 MTTR의 proxy일 뿐 실제 recovery benefit은 측정하지 않는다.
- 유사 technology stack 중심이라 Kubernetes control-loop나 GitOps reconciliation로의 일반화는 미검증이다.
- 평균과 표준편차는 일부 runtime에 제시되지만 incident-level CI·paired significance는 핵심 표에 없다.
- LLM이 bootstrapping과 report extraction에 쓰였지만 online diagnosis 자체는 주로 graph ranking이다. 순수 LLM RCA와 직접 동급 비교하면 안 된다.

## 5. 실무 적용 가능성

실제 SRE 환경에서 가장 설득력 있는 부분은 metadata abstraction과 online pruning이다. 서비스 이름이 바뀌어도 `frontend latency → downstream saturation` 같은 관계는 재사용할 수 있다. 반면 incident report 품질이 낮거나 조직마다 metric semantics가 다르면 MCG가 잘못된 prior를 축적할 수 있다.

thesis-rca에서는 완전한 MCG 구현보다 다음 아이디어가 현실적이다.

- GitOps object type과 reconciliation relation을 metadata schema로 정의한다.
- desired/observed/reconciliation evidence를 모두 넣은 뒤 fault relevance로 prune한다.
- RAG full 문서를 그대로 붙이지 않고 procedure/evidence unit으로 분해한다.
- historical runbook evidence와 live runtime evidence를 서로 다른 provenance와 confidence로 표시한다.

## 6. SRE 직감 평가

**Graph prior + current evidence pruning은 현장성이 높다.** 운영자는 과거 장애 패턴을 완전히 버리지도, 현재 telemetry만 맹신하지도 않는다. 이 논문은 그 균형을 잘 모델링했다. 다만 production report가 얼마나 정제됐는지가 숨은 비용이며, 좋은 report corpus가 없는 조직에서는 효과가 크게 낮아질 수 있다.

## 7. 약점과 위험

1. historical report에 잘못된 RCA가 있으면 causal prior가 조직의 오진을 재생산한다.
2. injection point ground truth는 실제 causal root보다 실험 bookkeeping label에 가까울 수 있다.
3. pruning threshold는 signal loss와 noise reduction 사이의 민감한 tuning point다.
4. service·metric AC@k가 높아도 explanation fidelity나 contradictory evidence 처리는 검증하지 않는다.
5. GitOps는 단순 service topology보다 reconciliation loop가 중요해 별도 relation schema가 필요하다.

## 8. thesis-rca 적용 방안

### V2.3 설계

1. `fault_taxonomy`에 `expected_visible_sources`와 `causal_distance`를 사전 등록한다.
2. GitOps evidence를 object/entity/type/relation/provenance 단위로 구조화한다.
3. runtime anomaly가 없는 GitOps edge는 제거하는 context-pruning condition을 둔다.
4. full context와 pruned context를 길이-matched placebo와 비교한다.
5. 각 arm에서 root cause뿐 아니라 evidence precision과 unsupported edge 비율을 측정한다.

### 논문 포지셔닝

MetaRCA가 이미 “LLM+historical report+observability causal graph”를 강하게 제안하므로 knowledge fusion 자체를 contribution으로 주장하기 어렵다. thesis-rca는 다음처럼 구별해야 한다.

> MetaRCA가 cross-system causal knowledge의 정확도를 연구한다면, thesis-rca는 GitOps control-loop evidence가 실제로 추가 정보를 주는지와 그 gain이 leakage인지 causal contribution인지 평가한다.

## 9. 기억할 핵심 문구

원문을 길게 인용하지 않고 핵심 주장을 의역한다.

- metadata-level causal knowledge는 topology가 달라도 재사용 가능성을 높인다.
- historical knowledge는 current evidence로 가중·pruning해야 한다.
- production incident report는 metric-only evidence보다 더 강한 prior가 될 수 있다.

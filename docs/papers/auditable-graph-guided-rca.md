# 논문 심층 분석: Auditable Graph-Guided Root Cause Analysis for Kubernetes Incidents

> 분석일: 2026-08-09
> 분석자: 20년차 cloud SRE 관점
> 논문: Anastasiia Kuvshinova, Seungmin Jin, 2026, arXiv preprint
> 원문: https://arxiv.org/abs/2606.08590
> 전문 검증: https://arxiv.org/html/2606.08590v1

## 1. 한 줄 요약

Typed evidence graph와 bounded traversal로 Kubernetes RCA를 수행하되, 높은 점수가 실제 incident evidence에서 왔는지 prompt hint·fault injector 노출·judge 차이·fallback shortcut에서 왔는지를 별도의 claim audit로 제한한 연구다.

## 2. 핵심 문제와 기존 한계

이 논문은 RCA를 단순 entity classification이 아니라 **증거가 뒷받침하는 root-cause entity와 propagation chain을 함께 복원하는 작업**으로 정의한다. 기존 LLM RCA의 주요 위험은 다음과 같다.

- scenario name이나 fault-specific prompt가 답을 사실상 알려줄 수 있다.
- benchmark 안의 injector object가 ground truth entity로 그대로 노출될 수 있다.
- agent가 결론을 내리지 못했을 때 deterministic fallback이 답을 채워도 agent reasoning 성과로 집계될 수 있다.
- 서로 다른 LLM judge를 사용한 점수를 직접 비교하면 시스템 효과와 judge 효과가 섞인다.
- snapshot 성능이 좋아도 live cluster의 alert·trace·trial isolation이 불안정하면 운영 성과로 일반화할 수 없다.

이는 thesis-rca V1의 prompt hint, V2.2의 자기 런북 검색, V8의 잔류 신호, V2.1의 judge threshold 민감성과 구조적으로 같은 문제다.

## 3. 핵심 기법과 원리

### 3.1 Typed evidence graph

Kubernetes resource, service, alert, trace entity, fault-injection object를 node로 두고 `owns`, `hosts`, `selects`, `mounts`, `fronts`, `calls` 관계를 출처와 함께 저장한다. 목적은 LLM에 거대한 텍스트를 한 번에 주는 대신 탐색 공간과 증거 provenance를 제한하는 것이다.

### 3.2 Bounded graph traversal

LangGraph state machine이 graph construction → triage → breadth-first traversal → per-node investigation → validation → chain construction을 수행한다. SQLite checkpoint로 각 단계를 재생할 수 있고 agent 간 자유 대화 대신 공유 state를 사용한다.

### 3.3 Read-only tool-grounded investigation

Investigator는 Kubernetes object, event, log, Prometheus, Jaeger를 조회한 뒤 node를 root cause, intermediate, symptom, unrelated로 분류한다. Secret 접근은 차단하고 tool allow-list를 둔다.

### 3.4 Independent validation

Validator는 시간 선후관계, cited evidence의 실재성, metric과 trace의 cross-modal consistency를 확인한다. 모호한 경우 read-only 추가 조회를 한 번 제안하고 accept·retry·redirect를 결정한다.

### 3.5 Claim audit

| Audit | 검출 대상 | 논문의 상태 |
|---|---|---|
| Same-judge comparison | judge 교체에 따른 점수 변화 | 수행 |
| Prompt-level ablation | scenario-specific hint 의존 | 수행 |
| Cascade-source check | fallback이 만든 정답을 agent 성과로 오인 | 구현, 최종 artifact 미완 |
| Telemetry no-leak test | run metadata의 prompt 혼입 | 수행 |
| Live validation | 실제 cluster 운용 가능성 | 불안정하여 성능 주장 철회 |

## 4. 실험 결과와 비평

### 4.1 평가 설정

- 대상: ITBench OpenTelemetry Demo snapshot
- fault injector: ChaosMesh
- agent backend: qwen-flash
- judge: 모든 핵심 표에서 qwen-plus 고정
- 비교: 동일 prompt level의 이전 자체 iteration과 audited iteration
- 반복: 고정 scenario subset의 single-run sweep

### 4.2 정량 결과

23개 공통 scenario에서 root-cause entity F1은 0.6087에서 0.9130으로 30.4%p 상승했다. 그러나 이것은 여러 코드·prompt 변경이 누적된 자체 iteration 비교이지 단일 구성요소의 causal effect가 아니다.

19개 3-way 공통 subset의 prompt ablation은 더 중요하다.

| Metric | 이전 iteration | Hint 포함 LEVEL_2 | Hint 제거 LEVEL_0 |
|---|---:|---:|---:|
| Root-cause entity F1 | 0.6842 | 0.9474 | 0.6958 |
| Propagation chain | 0.4092 | 0.4504 | 0.2881 |
| Fault localization | 0.5263 | 0.5263 | 0.3684 |
| Root-cause reasoning | 0.6842 | 0.9474 | 0.7368 |

Hint 제거 후 entity F1의 순증가는 약 1.2%p에 불과하다. 즉 headline gain 대부분은 scenario-specific prompt에 의존했다. ChaosMesh 5개 scenario는 LEVEL_0에서도 5/5를 풀었지만 ground-truth injector object가 evidence graph에 node로 존재했다. 논문은 이를 숨은 production cause 복원이 아니라 benchmark-coupled object selection으로 제한한다.

### 4.3 Case와 운영 실패

- ConfigMap feature-flag scenario는 graph가 configuration object를 first-class node로 다룰 때의 강점을 보였다: entity F1 1.0, reasoning 1.0, chain 0.8, localization 1.0.
- live environment-variable scenario에서는 tool output truncation, dead Jaeger port-forward, 잘못된 service DNS 해석, traversal ordering이 겹쳐 오답이 발생했다.
- 5개 live ChaosMesh stress test는 alert carry-over와 trace 불안정 때문에 success rate를 보고하지 않았다.

### 4.4 방법론적 강점

- 잘 나온 결과보다 **어떤 주장을 철회해야 하는지**를 명시한다.
- common subset·same judge·run identifier를 고정해 비교 단위를 분명히 한다.
- entity accuracy와 localization·propagation을 분리해 “답 이름 맞히기”를 RCA 전체로 취급하지 않는다.
- positive case와 negative live failure를 함께 제시한다.

### 4.5 한계

- 23개/19개 scenario의 single-run 결과이며 평균·CI·반복 분산이 없다.
- cascade-source audit가 핵심임에도 최종 report artifact가 아직 없다.
- baseline은 외부 SOTA가 아니라 이전 자체 iteration이다.
- ChaosMesh object 노출은 thesis-rca의 자기 런북 노출과 같은 construct-validity 문제다.
- preprint이며 독립 peer review 상태가 확인되지 않았다.

## 5. 실무 적용 가능성

실제 on-call에는 graph와 evidence provenance가 유용하지만, 현재 결과만으로 production readiness를 말할 수 없다. tool result truncation, port-forward health, trace availability 같은 “evidence transport” 실패가 reasoning보다 먼저 시스템을 무너뜨리기 때문이다.

thesis-rca에는 전체 LangGraph architecture보다 audit protocol이 더 직접적으로 적용 가능하다.

- 각 context block에 provenance와 retrieval reason을 기록한다.
- root-cause label뿐 아니라 affected entity·causal chain·supporting/contradicting evidence를 별도 채점한다.
- headline score와 stripped/masked condition을 항상 같은 judge·scenario subset에서 비교한다.
- agent verdict와 fallback·retrieval direct match를 결과 필드에서 분리한다.

## 6. SRE 직감 평가

**Audit framework는 즉시 유용하고, architecture의 운영성은 아직 미확인이다.** 현장에서는 “왜 이 결론이 나왔는지”를 재생할 수 있는 graph trace가 중요하다. 다만 LLM이 graph를 썼다는 사실만으로 진단이 causal해지는 것은 아니다. graph node 자체가 정답을 노출하면 더 정교한 shortcut이 될 수 있다.

## 7. 약점과 위험

1. graph construction 단계에서 이미 benchmark label이 들어가면 traversal은 reasoning이 아니라 lookup이 된다.
2. common-subset 분석은 공정하지만 실패 scenario를 제외함으로써 operational reliability가 과대평가될 수 있다.
3. 같은 judge 고정은 필요조건이지 judge validity의 충분조건은 아니다.
4. prompt ablation 후 낮아진 chain/localization은 entity F1만으로는 보이지 않는다.
5. live log artifact 부재로 negative case의 외부 재현이 어렵다.

## 8. thesis-rca 적용 방안

### 즉시 적용

1. V2.3에 `evidence_source`, `evidence_entity`, `retrieval_self_match`, `verdict_source` 필드를 추가한다.
2. RAG full/blind/procedure-only/irrelevant 조건을 같은 trial signal과 judge로 비교한다.
3. GitOps full-diff/masked-diff/no-diff를 분리해 entity leakage를 계량한다.
4. exact fault label 정확도 외에 affected workload와 causal-chain score를 추가한다.
5. 실패·SKIP을 common subset에서 조용히 제외하지 말고 operational attrition으로 별도 보고한다.

### 논문 포지셔닝

이 논문 때문에 `auditable RCA 최초` 주장은 불가능하다. 대신 thesis-rca의 차별점은 다음처럼 좁혀야 한다.

> 일반 telemetry·graph shortcut audit를 GitOps desired/observed/reconciliation evidence와 runbook retrieval에 특화해, full/masked/blind/placebo 조건으로 context contribution을 분해한다.

## 9. 기억할 핵심 문구

저작권 한도를 지키기 위해 원문을 길게 옮기지 않고 핵심을 의역한다.

- 높은 entity 점수는 propagation 이해를 보장하지 않는다.
- prompt hint 제거 후 남는 gain만 일반화 후보로 취급해야 한다.
- injector object가 보이는 benchmark 성공은 hidden production cause 진단과 다르다.

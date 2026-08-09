# 논문 심층 분석: SynergyRCA — Kubernetes StateGraph and LLM

> 분석일: 2026-08-09
> 분석 관점: 20년차 cloud SRE
> 논문: Yong Xiang et al., arXiv preprint, 2025
> 식별자: arXiv:2506.02490
> 원문: https://arxiv.org/pdf/2506.02490

## 1. 한 줄 요약

SynergyRCA는 Kubernetes entity의 시간·공간 관계를 StateGraph/MetaGraph에 보존하고, GPT-4o가 관련 경로만 조회·검증·재시도하여 두 production cluster에서 평균 precision 0.88/0.92를 보고한 graph-RAG RCA 시스템이다.

## 2. 핵심 문제와 기존 한계

Kubernetes error message의 동일 명칭은 ConfigMap·Secret·PVC처럼 서로 다른 실제 자원을 가리킬 수 있고, controller reconciliation과 비동기 snapshot 때문에 증상만으로 원인을 정하기 어렵다. rule/handler는 version과 custom resource 변화에 유지비가 높고, 평문 RAG는 빠르게 변하는 runtime state와 관계를 잘 보존하지 못한다.

## 3. 핵심 기법과 원리

```text
incident message + namespace + timestamp
  -> source entity kind 식별
  -> Triage: destination/intermediate kinds 예측
  -> MetaGraph: metapath 탐색
  -> PathQueryGen: Cypher 생성
  -> StateGraph: timestamped statepath 조회
  -> StateChecker: 존재·정확성·상태 불일치 검증
  -> ReportGen: 원인+remediation command
  -> ReportQualityChecker: 불충분하면 최대 3회 재탐색
```

- **StateGraph**: entity, snapshot, event 및 `ReferInternal`, `UseExternal`, `HasState`, `HasEvent` 관계를 시간 유효구간과 함께 저장한다.
- **MetaGraph**: 실제 StateGraph에서 kind-level schema를 추출하므로 문서 기반 schema가 custom resource 관계를 누락하거나 만들어내는 문제를 줄인다.
- **State reconciliation 기반 검증**: (1) state 존재 여부, (2) state 값의 정상성, (3) 연관 entity 사이 상태 일치 여부를 확인한다.
- **expert prompt + retry**: Triage, query generation, state checking, report generation, quality checking을 분리하고 설명이 error를 충분히 설명하지 못하면 다른 graph path를 시도한다.
- graph는 production cluster에 LLM이 직접 명령을 실행하지 못하게 하는 read-oriented boundary 역할도 한다.

## 4. 모델·데이터셋·실험 설계

| 항목 | 원문에서 확인한 내용 |
|---|---|
| LLM | GPT-4o via Azure OpenAI Assistants API |
| graph stack | PySpark, GraphFrames, Neo4j |
| 구현 규모 | Python 약 5,900 LOC: collection 1,620, graph 2,480, LLM analysis 1,760 |
| cluster 1 | Kubernetes 1.18, 27 nodes, 1주, 중복 제거 후 13.2GB |
| cluster 2 | Kubernetes 1.21, 88 nodes, 6개월, 중복 제거 후 118.8GB |
| ground truth | incident owners와 senior Kubernetes administrators |
| evaluation set | dataset-1 619 examples, dataset-2 843 examples |
| faults | FailedCreate, FailedMount, Evicted, FailedScheduling 등 다수 reason/type |
| retry | error message당 최대 3 trials |

저자는 두 데이터셋에서 18개와 20개 root-cause types를 찾았고, 두 번째에서 새 유형 5개를 발견했다고 보고한다. 표본은 namespace와 timestamp에 걸쳐 무작위 추출했으나, 전체 incident population에서 evaluation set을 만드는 상세 sampling frame은 공개하지 않는다.

## 5. 정량 결과와 ablation

### End-to-end precision (Table II)

| 데이터셋 | correct / examples | 저자 보고 average precision |
|---|---:|---:|
| cluster 1 | 549 / 619 | 0.88 |
| cluster 2 | 759 / 843 | 0.92 |

유형별 편차가 크다. 예를 들어 dataset-1의 `FailedScheduling-UnboundPVC`는 10/38=0.26, `FailedCreate-ExceedQuotaReplicaSet`은 18/32=0.56인 반면 여러 NotFound/AccessDenied 유형은 1.00이었다. 5분 주기 snapshot의 비일관성을 허용하면 precision이 0.95 이상으로 오른다고 서술하지만, 이는 평가 기준을 느슨하게 한 sensitivity 결과이며 주 결과와 분리해야 한다.

### Module evaluation (Table III)

| metric | dataset-1 weighted/arithmetic | dataset-2 weighted/arithmetic |
|---|---:|---:|
| Triage precision | 0.89 / 0.91 | 0.92 / 0.95 |
| Triage without knowledge | 0.84 / 0.79 | 0.91 / 0.90 |
| PathQueryGen precision | 0.95 / 0.95 | 0.95 / 0.94 |
| ReportGen conclusion precision | 0.92 / 0.94 | 0.93 / 0.95 |
| ReportGen command precision | 0.97 / 0.97 | 0.94 / 0.94 |
| ReportQualityChecker FPR | 0.09 / 0.08 | 0.10 / 0.07 |
| ReportQualityChecker FNR | 0.04 / 0.04 | 0.07 / 0.05 |

knowledge 제거 ablation은 Triage만 비교하며 graph 전체 제거나 StateChecker 제거의 end-to-end precision 변화는 보고하지 않는다. 따라서 0.88/0.92가 StateGraph 때문인지 expert prompt·GPT-4o·retry 때문인지 완전히 분리되지 않는다.

### 비용

- 평균 attempt time: dataset-1 131.00초, dataset-2 118.67초.
- 평균 total tokens: 160,728.63과 73,085.47; 약 99%가 input tokens.
- 저자 환산 비용은 attempt당 약 $0.19–$0.41.
- dataset-1 `Failed-ArtifactNotFound`는 평균 741.95초와 1.34M tokens로 극단적 tail을 보였다.

## 6. 실험 비평과 재현성

실제 두 cluster, resource/version 차이, 유형별 표본 수, module별 오류율, 시간/token 비용을 함께 공개한 점은 강하다. 특히 snapshot inconsistency를 실패 원인으로 식별한 것은 production K8s RCA에서 중요한 관찰이다.

그러나 전통 RCA, K8sGPT, flat-RAG, no-graph와의 동일 데이터 end-to-end baseline이 없다. precision의 정의는 최대 3회 중 “reasonably explains”한 report이고 expert의 blind 여부, 평가자 수, agreement, confidence interval, 유의성 검정은 미보고다. 코드와 production dataset은 공개되지 않았고 snapshot interval도 원인 유형별로 다른 정보 손실을 만든다. 논문은 arXiv preprint이며 확인 가능한 peer-reviewed venue를 원문에서 제시하지 않는다.

## 7. SRE 직감 평가

Kubernetes control plane을 graph로 읽는 방향은 타당하다. 특히 entity-kind 추측 후 실제 관계와 timestamped snapshot을 좁혀 가는 방식은 거대한 `kubectl get all` dump보다 안전하다. 그러나 5분 snapshot은 빠른 reconciliation을 놓치고, 73K–161K 평균 tokens와 2분 latency는 incident triage에 가볍지 않다. graph가 잘못된 시점의 상태를 정교하게 구조화하면 오히려 더 설득력 있는 오답이 된다.

## 8. thesis-rca 적용과 차별점

- 직접 적용 근거: desired/observed/reconciliation state를 entity relationship과 시간으로 구분해야 한다는 RQ4의 가장 가까운 선행연구다.
- 적용 후보: LLM 앞에서 deterministic validator가 snapshot timestamp, owner/reference, desired-observed mismatch를 검사하도록 한다.
- 차별점: SynergyRCA는 graph-RAG system의 절대 precision을 보고한다. thesis-rca는 같은 injected fault와 campaign에서 Runtime-only, GitOps, RAG, length placebo를 분리하고 diff/runbook/fault-label leakage를 감사한다.
- 반증 가능성: fault-linked GitOps state를 넣어도 blind/masked 조건에서 향상이 사라지면, graph 구조가 아니라 label-bearing evidence가 성능을 만든 것이다.
- 주의: SynergyRCA의 0.90을 thesis-rca validator 정확도 목표나 직접 baseline으로 쓰면 안 된다. task, model, retry, label, precision 정의가 모두 다르다.

## 9. 기억할 핵심 문구

원문의 핵심 표현은 “state reconciliation”, “StateGraph”, “context-specific insights”다. 핵심 교훈은 graph 자체보다 **시간이 붙은 state와 관계를 검증 가능한 provenance로 제공해야 한다**는 것이다.

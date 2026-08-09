# 논문 심층 분석: GROOT: An Event-graph-based Approach for Root Cause Analysis in Industrial Settings

> 분석일: 2026-08-09
> 분석 관점: 20년차 cloud SRE
> 논문: Hanzhang Wang, Zhengkai Wu, Huai Jiang, Yichao Huang, Jiamu Wang, Selcuk Kopru, Tao Xie, ASE 2021, pp. 419–429
> DOI: [10.1109/ASE51524.2021.9678708](https://doi.org/10.1109/ASE51524.2021.9678708)
> preprint: [arXiv:2108.00344](https://arxiv.org/abs/2108.00344)
> 저자 공개 전문: [Tao Xie publication PDF](https://taoxiease.github.io/publications/ase21-groot.pdf)
> 증거 분류: **인접 근거** — production AIOps에서 deployment/configuration activity를 event로 직접 사용하지만 GitOps desired/observed/reconciliation semantics나 독립 기여 ablation은 없다.

## 1. 한 줄 요약

metrics·logs·developer activities를 event node로 통일하고 SRE rule로 causal link를 만들어, 5,000개 production service의 incident를 해석 가능한 event graph로 순위화한다.

## 2. 핵심 문제와 기존 한계

GROOT는 산업 microservice RCA의 어려움을 세 가지로 정리한다.

- **operation complexity**: 중앙 SRE와 domain SRE 사이의 지식 격차
- **scale complexity**: 수천 서비스와 수많은 alert, 긴 전파 경로
- **monitoring complexity**: metrics, logs, status, developer activity의 이질성

기존 ML 접근은 학습 데이터 부족과 낮은 해석 가능성이 문제이고, 기존 graph 접근은 service/host 수준 node와 정적 dependency에 머물러 세부 event context와 동적 외부 의존성을 잃는다고 본다.

## 3. 핵심 기법과 원리

```text
initial alert services
  -> dependency subgraph
  -> heterogeneous event collection
  -> static / conditional / dynamic SRE rules
  -> event causality graph
  -> GrootRank
  -> event-level root-cause ranking + visual explanation
```

### event as node

node는 service가 아니라 `Latency Spike`, error, status change, code deployment, configuration change 같은 구체 event다. 각 event는 service, type, start time, properties를 가진다. 이를 통해 “Service C가 이상”보다 “Service C의 특정 deployment/config/event가 원인 후보”라는 더 세밀한 결과를 낸다.

### rule-engineered causal links

SRE 지식은 source event와 target event 사이의 link rule로 표현된다.

- **basic/static rule**: 같은 service 또는 upstream/downstream의 알려진 event 관계
- **conditional rule**: data center, property 등 조건이 맞을 때만 link 생성
- **dynamic rule**: DB나 외부 provider처럼 dependency graph에 없던 entity/event를 실행 중 생성

이는 통계적 causal discovery가 아니라 명시적 domain rule에 의해 구성한 operational causal graph다. 높은 해석 가능성과 반대로 rule coverage·정확도 의존성이 생긴다.

### GrootRank

PageRank를 기반으로 dangling node와 event propagation을 조정한 personalization vector를 사용하고, 동점은 initial anomaly service까지의 access distance와 과거 root-cause event type 빈도로 푼다. 과거 빈도는 labeled data를 사용하므로 완전한 unsupervised method가 아니다.

## 4. 데이터셋·실험·정량 결과

### 4.1 production 환경

| 항목 | 내용 |
|---|---|
| 시스템 | eBay e-commerce production |
| 규모 | 3 data centers, 5,000+ services, 일평균 147B traces |
| 데이터 기간 | 2020-01~2021-04, 15개월 |
| incidents | 952: business-domain 782, service-based 170 |
| ground truth | SRE가 사건별 가장 actionable/influential event 하나를 수동 label·검증 |
| 배포 | Kubernetes 위 3 microservices, 3개 DC federation |
| 비교군 | naive service-level PageRank, non-adaptive rule graph |

### 4.2 offline dataset 결과 — Table III

| incident | GROOT Top-1 | GROOT Top-3 | naive Top-1/3 | non-adaptive Top-1/3 |
|---|---:|---:|---:|---:|
| service-based | 74% | 92% | 16% / 25% | 62% / 84% |
| business domain | 81% | 96% | 1% / 2% | 26% / 28% |
| combined | **78%** | **95%** | 3% / 6% | 33% / 38% |

GROOT와 non-adaptive variant의 차이는 context-aware dynamic/conditional rule의 큰 기여를 시사한다. 다만 non-adaptive baseline은 CauseInfer·Microscope 등의 원 구현이 아니라 저자들이 만든 근사체다.

### 4.3 end-to-end production 결과 — Table IV

| incident | offline Top-1/3 | live Top-1/3 | offline 평균/최대 | live 평균/최대 |
|---|---:|---:|---:|---:|
| service-based | 74% / 92% | 73% / 91% | 1.06s / 1.69s | 3.16s / 4.56s |
| business domain | 81% / 96% | 73% / 87% | 0.98s / 1.14s | 2.98s / 3.61s |

live에서는 missing data와 service/storage failure 때문에 정확도가 최대 9 percentage points 하락하고, data fetch 때문에 runtime이 약 3초 늘었다. 이 offline–live gap 자체가 중요한 운영 근거다.

### 4.4 사용자 조사

14명의 GROOT 사용자와 6명의 개발자가 응답했다. 저자들은 대체로 helpful/convenient하다고 해석하지만 표본이 작고, 개발자 조사에서는 논문 저자인 연구·개발자를 제외했다고 명시한다. raw 응답 분포나 통계 검정은 제공하지 않는다.

## 5. 실험 설계 비평

### 장점

- 실제 production incident 952건과 live deployment 결과를 함께 제시한다.
- 단순 fault injection 연구보다 규모와 event diversity가 크다.
- offline dataset과 end-to-end system 결과를 분리해 data-fetch·missing-event 비용을 드러낸다.
- 실패의 주원인이 missing event임을 밝히고 event/rule 추가로 일부 실패를 수정한 운영 학습 루프를 설명한다.

### 한계와 통계

- 단일 기업·도메인 자료이며 data, rules, 구현이 공개되지 않아 독립 재현이 어렵다.
- ground truth가 사건당 하나의 actionable event만 남겨 multi-causal incident를 단일 label로 축소한다.
- GrootRank의 동점 해소에 과거 label 빈도를 쓰므로 시간 분할·누출 통제가 없으면 historical prevalence shortcut이 생길 수 있다.
- baseline 두 개가 저자 구현이며 강한 production-ready 경쟁 시스템과 직접 비교하지 않는다.
- confidence interval, 유의성 검정, 시간대별 drift 분석이 없다.
- rule 추가가 같은 실패 사례를 바탕으로 이뤄졌다면 평가 데이터에 대한 iterative overfitting 가능성이 있다.
- “causal link”는 SRE 규칙·휴리스틱이지 intervention으로 검증한 causal effect가 아니다.

## 6. SRE 직감 평가

실제 on-call에서 가장 가치 있는 부분은 점수 자체보다 event graph와 provenance다. SRE가 왜 특정 deployment나 DB event가 원인 후보인지 경로를 따라가고, 잘못된 rule을 수정할 수 있다. 반면 missing critical event 하나가 전혀 다른 원인을 만들 수 있다는 저자의 경고는, evidence completeness가 reasoning sophistication보다 선행 조건임을 보여준다.

GROOT는 alert precision이 0.6 이상이면 유용하다고 추정하고 recall을 더 중요하게 본다. false positive는 ranking이 낮출 수 있지만 누락된 evidence는 복구할 수 없기 때문이다.

## 7. thesis-rca 연결

### 직접 가져올 설계 원리

1. **event-level provenance**: Git commit, manifest diff, reconcile result, pod event를 섞지 말고 type·timestamp·source를 보존한다.
2. **evidence graph 설명**: LLM 답변이 원인명만 쓰지 않고 `event -> propagation -> symptom` 경로를 제시하게 한다.
3. **missing evidence audit**: wrong answer를 prompt failure와 수집 누락으로 분리한다.
4. **offline/live gap**: 저장된 fixture 성능과 실시간 수집 조건의 성능을 구분한다.
5. **rule leakage 통제**: fault-specific rule/runbook이 label shortcut이 되는지 masked condition으로 검사한다.

### GROOT와 thesis-rca의 차이

GROOT의 developer activity는 heterogeneous event 중 하나이며 GitOps control-loop state를 별도 causal signal로 분해하지 않는다. thesis-rca는 desired, observed, reconciliation을 provenance별로 마스킹하고 runtime-only 대비 독립 효과를 평가해야 한다. 따라서 GROOT는 architecture precedent이지 GitOps 효과의 직접 증거가 아니다.

## 8. 직접 지지 범위

| 주장 | 판정 |
|---|---|
| metrics·logs·activities를 event graph로 결합하면 service-level graph보다 유용할 수 있다 | 직접 지지 |
| dynamic/conditional domain rule이 production RCA 성능에 크게 기여했다 | 해당 시스템에서 직접 지지 |
| missing event가 RCA 실패를 유발한다 | 직접 지지 |
| GitOps reconciliation signal이 독립적 진단 기여를 가진다 | 지지하지 않음 |
| rule-built graph가 자연적 인과성을 증명한다 | 지지하지 않음 |

## 9. 기억할 핵심 원문 표현

- “events as basic nodes”
- “developer activities”
- “missing event(s)”
- “domain-specific rules”

발췌는 기법 식별을 위한 짧은 표현으로 제한했다.

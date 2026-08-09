# 논문 심층 분석: KGroot: A Knowledge Graph-Enhanced Method for Root Cause Analysis

> 분석일: 2026-08-09
> 분석자: 20년차 SRE 전문가 관점
> 논문: Tingting Wang, Guilin Qi, Tianxing Wu, 2024, Expert Systems with Applications 255, 124679
> DOI: [10.1016/j.eswa.2024.124679](https://doi.org/10.1016/j.eswa.2024.124679)
> 공개 전문: [arXiv:2402.13264](https://arxiv.org/abs/2402.13264)
> 축 D 관련성: **인접 선행연구** — Kubernetes 구성 오류와 fault event propagation을 다루지만 GitOps controller나 desired/observed comparison은 입력으로 쓰지 않는다.

## 1. 한 줄 요약

KGroot는 과거 장애의 event propagation graph를 knowledge graph로 축적하고 온라인 장애 graph와 비교해 Kubernetes root cause를 추천하지만, GitOps evidence가 아니라 주로 metric·log에서 구조화한 observed event에 의존한다.

## 2. 핵심 문제와 기존 한계

저자들은 microservice RCA가 heterogeneous monitoring data, 복잡한 dependency, cascade fault 때문에 느리고 부정확하다고 본다. 특히 반복되는 fault가 많음에도 과거 incident의 event 관계를 재사용하지 못하는 점을 문제로 제기한다.

서론은 service deployment, configuration modification, pod auto-scaling을 중요한 activity로 열거한다. 그러나 실제 방법 설명에서는 대용량 log와 metric을 structured event로 바꾸고, 과거 labeled failure에서 recurring propagation pattern을 학습하는 데 초점을 둔다.

## 3. 핵심 기법과 원리

```text
historical log/metric -> structured events -> historical FPGs
                                      -> fault별 FEKG
online log/metric     -> online FPG ----> RGCN graph similarity
                                      -> root-cause type
                                      -> time+distance ranking으로 concrete event
```

### 3.1 Fault Propagation Graph와 Fault Event Knowledge Graph

FPG는 event와 sequential/causal relation의 graph다. 같은 fault의 여러 historical FPG를 clustering하고 공통 graph structure를 추출해 FEKG를 만든다. online incident에서는 실시간 FPG를 만들어 각 FEKG와 비교한다.

논문은 configuration semantics의 예로 `Pod memory=10M`과 `JVM memory=2G`가 함께 있을 때 Pod startup failure를 일으키는 상황을 제시한다. 이는 단일 field가 아니라 여러 설정의 관계가 장애를 만든다는 점을 모델링하려는 사례다.

### 3.2 Relation classifier와 graph similarity

event pair의 relation은 SVM으로 분류한다. node를 abstract event로 정규화한 뒤 word2vec/BERT embedding과 adjacency를 RGCN에 넣고, pooling·MLP로 online FPG와 FEKG의 similarity를 계산한다. 가장 유사한 knowledge graph의 fault type을 선택한다.

같은 root-cause type에 여러 concrete event가 있으면 alarm과의 시간 간격과 graph distance를 가중 합산해 최종 Top-N을 정한다.

## 4. 실험 결과와 비평

### 4.1 평가 설계

- Dataset A: 은행의 실제 failure 99개, metric 2,594개, failure class 41개
- Dataset B: 4-node Kubernetes의 Train-Ticket 64 microservice, Chaos Mesh로 주입한 failure 156개·23종, metric 5,724개
- Dataset B fault: configuration error, network delay, kill pod, CPU overload, memory overload
- split: train/validation/test = 40/20/40
- 모든 실험 10회 반복 후 평균 보고
- baseline: DéjàVu, JSS, iSQUAD, DT, GB, RF, SVM 및 KG/GCN 제거 ablation

### 4.2 핵심 정량 결과

Dataset B에서 KGroot는 A@1 75.18%, A@2 86.12%, A@3 93.50%를 보고했다. A@3는 DéjàVu의 90.62%보다 2.88%p 높다. KG 제거 시 A@3 90.15%, GCN 제거 시 89.16%로 낮아졌다. inference time은 Dataset A 351ms, Dataset B 578ms였다.

Dataset A에서는 KGroot A@1 71.24%, A@3 84.27%였고, KG 제거 A@3 79.51%, GCN 제거 82.16%였다.

### 4.3 결과표 감사와 비평

논문 표에는 내부 불일치가 있다.

- Dataset B의 KGroot A@5가 85.17%로 A@3 93.50%보다 낮다. 일반적인 누적 Top-k accuracy 정의라면 불가능하므로 오기 또는 metric 구현 오류 가능성이 있다.
- Dataset A KGroot의 precision 75.41%, recall 73.24%인데 F1이 76.18%로 둘보다 높게 보고됐다. 조화평균 성질과 맞지 않는다.
- Dataset B는 156회 injection을 23종에 나누고 40%만 test로 써 fault type별 표본이 작을 수 있으나, class별 반복 수와 분산·confidence interval은 제시하지 않는다.

따라서 A@3 93.5%는 원문 보고값으로 인용할 수 있지만, 정확한 효과 크기나 production generalization의 강한 근거로 쓰면 안 된다. 무엇보다 KG/GCN ablation이지 configuration/change event ablation이 아니다.

## 5. GitOps-aware diagnosis와의 관계

### 5.1 논문이 직접 입증한 것

- Kubernetes에서 configuration error를 포함한 fault를 event propagation graph로 표현하고 정량 평가했다.
- 과거 fault pattern과 현재 observed event graph의 similarity는 recurring fault 진단에 이용할 수 있다.
- 단일 설정값보다 설정 간 관계와 시간·graph distance가 중요할 수 있다.

### 5.2 논문이 입증하지 않은 것

- source-of-truth Git revision이나 desired manifest를 입력으로 쓰지 않았다.
- live state와 desired state의 drift를 계산하지 않았다.
- Argo CD/Flux reconciliation status, error, retry, health/sync signal을 쓰지 않았다.
- 논문 서론의 deployment/configuration/autoscaling activity 열거가 실제 feature set 또는 ablation으로 이어지는지는 명확하지 않다.

### 5.3 thesis-rca로의 논리적 전이

다음은 **논문 결과의 직접 복제가 아니라** KGroot graph abstraction을 GitOps signal model로 확장하는 제안이다.

- FEKG node에 `desired_change`, `observed_transition`, `reconcile_action`, `runtime_symptom`의 provenance type을 보존한다.
- 같은 fault label의 historical graph를 그대로 retrieval하면 답 누출이 생길 수 있으므로 fault name과 runbook text를 제거하고 구조적 pattern만 쓴다.
- configuration conflict는 raw full diff 대신 field path와 change direction을 masked representation으로 만들어 leakage condition과 비교한다.
- recurrent graph matching은 V2.3 이후 충분한 trial history가 생긴 뒤 별도 실험으로 두고, 당장 V2.3의 독립변수에는 섞지 않는다.

## 6. SRE 직감 평가

반복 fault가 많은 안정된 platform에서는 유용할 수 있다. 예를 들어 같은 resource-limit mismatch가 여러 namespace에서 반복되면 graph pattern이 빠른 후보 축소에 도움 된다. 반면 새 deployment 구조, unseen fault, rapidly changing controller behavior에는 과거 graph similarity가 잘못된 확신을 줄 수 있다.

현재 thesis의 고정 model·소표본 조건에서는 RGCN 학습을 추가하는 것보다, KGroot가 강조한 event 관계를 prompt 내 명시적 provenance graph로 제공하는 편이 구현·해석 가능성이 높다. 모델 architecture 변경은 GitOps context 자체의 효과 측정을 흐릴 수 있다.

## 7. 약점과 위험

- 표의 Top-k와 F1 수치에 내부 불일치가 있어 결과 신뢰성 감사를 요구한다.
- Dataset A의 원시 데이터와 labeling 절차가 충분히 설명되지 않는다.
- Dataset B의 fault별 sample size와 통계적 불확실성이 없다.
- historical labeled failure에 의존하므로 unseen fault와 label leakage에 취약하다.
- causal relation classifier가 진정한 causality를 식별하는지, 단순 association을 학습하는지 불명확하다.
- GitOps control loop와 reconciliation episode를 모델링하지 않는다.

## 8. 우리 실험에의 적용 방안

### 8.1 즉시 적용 가능한 최소안

LLM prompt 안에서 다음과 같은 작은 evidence graph를 생성한다.

```text
commit/revision -> desired field change
desired resource -> observed resource transition
controller -> reconciliation outcome
observed resource -> runtime symptom
```

각 edge에는 timestamp, namespace/name, provenance, 수집 성공 여부만 넣는다. fault label과 fault-specific 설명은 넣지 않는다.

### 8.2 후속 연구안

충분한 raw trial이 축적되면 fault label을 가린 historical graph retrieval을 별도 condition으로 평가할 수 있다. 평가 시에는 runtime+current GitOps와 runtime+current GitOps+historical graph를 비교하고, 동일 fault trial이 retrieval되는 leave-one-fault-out 조건을 반드시 포함해야 한다.

## 9. 핵심 인용

저작권 한도를 지키기 위해 기억할 짧은 원문 구절만 기록한다.

- “configuration modifications”
- “pod auto-scaling events”
- “fault propagation graph”

## 10. 선정 판정

**포함 — 축 D 인접 근거, 수치 주의.** Kubernetes configuration fault와 event relation을 직접 다루고 정량 비교·ablation이 있으나, GitOps-aware RCA는 아니다. 표의 내부 불일치 때문에 수치는 claim–evidence ledger에서 경고와 함께 사용한다.

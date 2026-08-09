# 논문 심층 분석: MicroRCA: Root Cause Localization of Performance Issues in Microservices

> 분석일: 2026-08-09
> 분석 관점: 20년차 cloud SRE
> 논문: Li Wu, Johan Tordsson, Erik Elmroth, Odej Kao, IEEE/IFIP NOMS 2020, pp. 1–9
> DOI·공식 페이지: [10.1109/NOMS47738.2020.9110353](https://doi.org/10.1109/NOMS47738.2020.9110353)
> 저자 페이지: [Li Wu publications](https://lillywu.github.io/publications/)
> 공개 구현: [elastisys/MicroRCA](https://github.com/elastisys/MicroRCA)
> 전문 확인본: [저자 업로드 전문](https://www.researchgate.net/publication/338864142_MicroRCA_Root_Cause_Localization_of_Performance_Issues_in_Microservices)
> 증거 분류: **인접 근거** — Kubernetes fault injection과 service/resource correlation을 직접 평가하지만 change history나 GitOps control loop는 입력으로 쓰지 않는다.

## 1. 한 줄 요약

service response-time anomaly, service call path, container/host resource utilization을 attributed graph로 결합하고 Personalized PageRank로 원인 서비스를 실시간 순위화한다.

## 2. 핵심 문제와 기존 한계

microservice 환경은 기술 이질성, 많은 서비스 수, 빈번한 배포 때문에 성능 장애의 원인과 전파 증상을 구별하기 어렵다. 기존 접근은 다음 중 하나를 요구했다.

- 코드 instrumentation과 완전한 distributed trace
- 방대한 단일 계층 metric 분석
- frontend와 backend correlation만으로 만든 순위

마지막 유형은 frontend에 영향이 약한 leaf service나 non-compute-intensive service를 놓치기 쉽다. MicroRCA의 핵심 질문은 “어느 service response time이 비정상인가”와 “그 service의 어떤 resource pressure가 그 비정상과 함께 움직이는가”를 topology 안에서 결합하면 symptom-as-cause 오류를 줄일 수 있는가이다.

## 3. 핵심 기법과 원리

```text
service mesh response time + Prometheus resource metrics
  -> SLO anomaly detection
  -> service/host attributed graph
  -> anomalous subgraph extraction
  -> edge correlation + node anomaly score
  -> Personalized PageRank
  -> suspicious service ranking
```

### attributed graph

node는 service와 host이며 edge는 service call과 co-location을 표현한다. 5초마다 Prometheus에서 CPU, memory, sent bytes를 수집하고 service mesh에서 pairwise response time을 얻는다. 이는 호출 관계가 없는 container도 같은 host의 resource contention으로 영향을 주고받을 수 있다는 운영 현실을 반영한다.

### 상관 기반 weighting

anomalous service의 response-time 변화와 다음 항목의 correlation을 edge/node weight로 쓴다.

- communicating service 간 response-time anomaly
- service anomaly와 해당 container resource utilization
- host-level contention과 collocated service anomaly

Personalized PageRank vector를 root-cause score로 사용한다. 따라서 이름은 RCA지만 실제 계산은 관측 상관과 graph centrality 기반의 localization이다.

## 4. 데이터셋·실험·정량 결과

### 4.1 환경

| 항목 | 내용 |
|---|---|
| benchmark | Sock Shop, 13 microservices |
| platform | Google Cloud Engine의 Kubernetes cluster |
| nodes | master 1, worker 4; 그중 3개 application, 1개 data collection |
| fault | latency(`tc`), CPU hog(`stress-ng`), memory leak(`stress-ng`) |
| 주입 대상 | 7개 주요 microservices, fault별 가능한 service에 주입 |
| 전체 시나리오 | 95 |
| 비교군 | random selection, MonitorRank, Microscope |
| 지표 | PR@1, PR@3, MAP |

각 실험은 한 번에 한 service에 한 fault만 주입한다. 즉, single-root-cause ranking 문제다.

### 4.2 전체 성능 — Table V

| 방법 | PR@1 | PR@3 | MAP |
|---|---:|---:|---:|
| random selection | 0.21 | 0.46 | 0.58 |
| MonitorRank | 0.41 | 0.65 | 0.73 |
| Microscope | 0.79 | 0.86 | 0.85 |
| MicroRCA | **0.89** | **1.00** | **0.97** |

MicroRCA는 가장 강한 비교군 Microscope 대비 PR@1이 10 percentage points, MAP가 12 points 높다. 저자 표의 상대 개선율은 각각 13.3%, 14.7%다.

### 4.3 fault별 성능 — Table V

| fault | MicroRCA PR@1 | MicroRCA PR@3 | MicroRCA MAP |
|---|---:|---:|---:|
| latency | 0.89 | 1.00 | 0.97 |
| CPU hog | 0.90 | 1.00 | 0.97 |
| memory leak | 0.90 | 1.00 | 0.98 |

anomaly detector의 F1이 0.4 미만인 18건에서도 13건을 top-1에 올렸다고 보고한다. 다만 shipping과 payment는 낮은 request volume, leaf 위치, resource pressure가 response time에 덜 드러나는 특성 때문에 상대적으로 약했다.

### 4.4 비용 — Table VI

| module | 비용 |
|---|---:|
| data collection | 0.6 vCPU, 1,511 MB RAM |
| anomaly detection | 0.01초, 8 cores |
| attributed graph construction | 3.3초, 8 cores |
| root-cause localization | 0.03초, 8 cores |

5초 collection interval 기준 계산 latency는 실시간 사용 가능 범위지만, 저자도 수집 overhead가 다소 높다고 인정한다.

## 5. 실험 설계 비평

### 장점

- thesis-rca와 같이 실제 Kubernetes에 fault를 주입했다.
- service-level과 infrastructure-level metric을 결합하고 host co-location을 모델링했다.
- fault type, service position, detector quality, threshold sensitivity, runtime overhead를 나눠 분석했다.
- 코드가 공개되어 graph construction과 ranking을 추적할 수 있다.

### 한계와 통계

- Sock Shop 단일 benchmark와 7개 service subset이므로 topology·workload 다양성이 작다.
- latency, CPU hog, memory leak 세 fault뿐이며 configuration drift, image/version error, reconciliation failure는 없다.
- single simultaneous fault만 평가해 cascading multi-fault나 competing changes를 검증하지 않는다.
- 95개 시나리오의 반복 구조는 공개하지만 독립 반복 수, variance, confidence interval, 유의성 검정이 없다.
- PR@k 정의는 한 root cause 설정에서 사실상 hit rate에 가깝다. 일반적인 precision이라는 이름과 혼동할 수 있다.
- anomaly threshold `0.045`, anomalous-node confidence `α=0.55`를 같은 benchmark에서 선택했고 held-out tuning 설명이 없다. `α >= 0.7`에서 성능이 하락했다.
- response-time 증가로 나타나는 anomaly만 적용 범위라고 명시하므로 correctness failure나 silent config error에는 약하다.

## 6. SRE 직감 평가

Prometheus와 service mesh가 이미 있는 cluster에서 원인 service 후보를 빠르게 좁히는 방식은 현실적이다. 특히 leaf service와 host contention을 함께 보도록 한 설계는 유용하다. 다만 production Kubernetes에서는 pod churn, HPA, retry, queueing, mesh sampling, noisy neighbor가 correlation을 쉽게 왜곡한다. 또한 symptom이 response time에 나타나지 않는 GitOps drift나 잘못된 desired state는 MicroRCA 입력만으로 구분하기 어렵다.

## 7. thesis-rca 연결

### 가져올 원리

1. **계층 간 evidence join**: service latency와 pod/node resource를 한 graph에서 연결한다.
2. **co-location 고려**: call graph 밖의 node/resource 경합을 원인 후보에 포함한다.
3. **detector와 localizer 분리**: anomaly detection 실패와 RCA reasoning 실패를 별도 오류로 기록한다.
4. **fault-group breakdown**: 전체 정확도 외에 latency/resource/config/network 그룹별 효과를 보고한다.

### GitOps 실험에서 확장할 점

MicroRCA의 graph에 다음 event/entity를 추가하는 것은 개념적으로 가능하다.

- Git commit / manifest revision
- desired object spec
- observed object status
- Flux/Argo reconciliation result와 timestamp
- deployment rollout과 pod replacement

그러나 이 논문은 그런 확장의 효과를 검증하지 않았다. thesis-rca는 LLM prompt에 graph를 직접 구현하기보다, 동일 trial의 runtime evidence와 GitOps evidence를 provenance label과 함께 제공하고 masking ablation으로 각 신호의 순기여를 측정하는 편이 현재 연구질문에 맞다.

## 8. 직접 지지 범위

| 주장 | 판정 |
|---|---|
| service anomaly와 resource utilization 결합이 service-only correlation보다 유리할 수 있다 | 직접 지지 |
| Kubernetes에서 graph-based RCA를 fault injection으로 평가할 수 있다 | 직접 지지 |
| topology 밖 co-location edge가 원인 식별에 유용하다 | 직접 지지 |
| GitOps context가 정확도를 높인다 | 지지하지 않음 |
| 상관 기반 PageRank가 causal root cause를 증명한다 | 지지하지 않음 |

## 9. 기억할 핵심 원문 표현

- “attributed graph”
- “without any application instrumentation”
- “correlating application performance symptoms”

짧은 표현만 인용했으며, 수치와 비평은 전문의 Table IV–VI 및 Discussion을 대조했다.

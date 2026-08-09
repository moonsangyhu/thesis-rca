# 논문 심층 분석: RCAEval — A Benchmark for Root Cause Analysis of Microservice Systems with Telemetry Data

> 분석일: 2026-08-09
> 분석 관점: 20년차 cloud SRE
> 논문: Luan Pham, Hongyu Zhang, Huong Ha, Flora Salim, Xiuzhen Zhang, WWW Companion 2025
> DOI: [10.1145/3701716.3715290](https://doi.org/10.1145/3701716.3715290)
> 전문: [arXiv:2412.17015](https://arxiv.org/abs/2412.17015)
> benchmark: [GitHub](https://github.com/phamquiluan/RCAEval)

## 1. 한 줄 요약

RCAEval은 Kubernetes의 Online Boutique, Sock Shop, Train Ticket에서 11개 fault type과 metrics·logs·traces를 수집한 735-case 공개 benchmark로, service-level과 indicator-level RCA를 15개 baseline으로 비교할 수 있게 한다.

## 2. 해결하는 평가 문제

기존 microservice RCA 논문은 1–2 systems, 2–3 faults, private telemetry 또는 특정 modality만 사용해 method 간 수치를 비교하기 어려웠다. RCAEval은 dataset와 evaluation library를 함께 공개하고 다음 두 수준의 ground truth를 제공한다.

- coarse-grained: root-cause service
- fine-grained: root-cause indicator(metric/log/trace evidence)

이는 exact component label뿐 아니라 어떤 telemetry가 원인을 나타냈는지를 분리할 수 있다는 점에서 evidence-grounded RCA 평가에 중요하다.

## 3. 핵심 기법과 원리 — 시스템과 telemetry 수집

| system | services | 특징 |
|---|---:|---|
| Online Boutique | 12 | Google e-commerce, gRPC |
| Sock Shop | 15 | Weaveworks e-commerce, HTTP |
| Train Ticket | 64 | synchronous+asynchronous, 긴 call chain |

세 system을 Kubernetes cluster에 배치하고 전체 service에 10–200 requests/s의 random load를 발생시켰다.

- metrics: Prometheus, cAdvisor, Istio의 application/resource metrics
- logs: Vector→Loki 수집 후 Elasticsearch 저장
- traces: Jaeger→Elasticsearch
- normal telemetry를 먼저 수집한 뒤 random service에 fault를 주입하고 abnormal telemetry를 수집했다.
- 5년 경력 DevOps engineer가 deployment, collection, verification에 참여했다.

## 4. dataset·fault taxonomy·표본

| suite | systems | fault class | cases | repetitions | telemetry scale |
|---|---:|---|---:|---|---|
| RE1 | 3 | CPU, MEM, DISK, DELAY, LOSS | 375 | fault×service당 5회 | 49–212 metrics |
| RE2 | 3 | CPU, MEM, DISK, SOCKET, DELAY, LOSS | 270 | fault×service당 3회 | 77–376 metrics, logs 8.6–26.9M lines, traces 39.6–76.7M |
| RE3 | 3 | 5 code-level faults | 90 | system당 30 cases | 68–322 metrics, logs 1.7–2.7M, traces 4.5–4.7M |

총 735 cases와 11 fault types다.

### taxonomy

- resource: CPU hog, memory leak, disk stress, socket stress (`stress-ng`)
- network: delay, packet loss (`tc`)
- code: incorrect parameter, missing parameter, missing function call, incorrect return value, missing exception handler

resource root-cause indicator는 해당 usage metric, delay는 latency metric, loss는 failed-request metric/trace response code다. code fault는 주로 stack trace의 faulty line이며, 없으면 error log나 affected service response code를 사용한다.

이 label 정의는 실용적이지만 일부 code case에서 stack trace 자체가 정답을 직접 드러낼 수 있다. 따라서 indicator-level 성능은 reasoning과 evidence availability를 분리해 해석해야 한다.

## 5. baseline과 metric

15개 baseline은 다음 modality를 포괄한다.

- metric causal: RUN, CausalRCA, CIRCA, RCD, MicroCause, EasyRCA
- metric non-causal/representation: MSCRED, BARO, ε-Diagnosis
- trace: TraceRCA, MicroRank
- multi-source: PDiagnose, multi-source BARO/RCD/CIRCA

공개 구현과 원 논문 권장 default를 사용하고 원/관련 연구 결과 재현으로 correctness를 확인했다. PDiagnose는 source가 없어 이전 논문의 기술을 따라 재구현했다.

- AC@k: top-k result가 true root cause를 포함할 확률
- Avg@k: AC@1…AC@k의 평균

## 6. 정량 결과

논문의 Table 6은 RE2 Train Ticket 6개 fault에서 11개 구성의 결과를 제시한다.

| data/method | AC@1 avg | AC@3 avg | Avg@5 avg |
|---|---:|---:|---:|
| metric BARO | 0.67 | 0.82 | 0.80 |
| metric CausalRCA | 0.22 | 0.47 | 0.43 |
| metric CIRCA | 0.32 | 0.47 | 0.46 |
| trace TraceRCA | 0.66 | 0.79 | 0.77 |
| trace MicroRank | 0.16 | 0.37 | 0.31 |
| multi-source PDiagnose | 0.48 | 0.70 | 0.67 |
| multi-source BARO | **0.69** | **0.82** | **0.81** |

단일 winner는 fault에 따라 달랐다.

- metric/multi-source BARO는 memory와 disk resource fault에서 Avg@5 0.99와 1.00이었다.
- TraceRCA는 delay에서 Avg@5 0.88로 강했지만 loss는 0.67이었다.
- PDiagnose는 delay 0.87이지만 disk 0.69였다.
- multi-source CIRCA 평균 Avg@5는 0.13으로 metric-only CIRCA 0.46보다 낮았다. modality 추가가 자동 성능 향상을 보장하지 않는다.
- 전체 최고 평균 AC@1도 0.69에 그쳐 상당한 개선 여지가 남는다.

## 7. validity threats와 SRE 판단

강점은 공개 raw telemetry, system/fault/modality 다양성, 반복 주입, coarse/fine label, reusable evaluation library다. 특히 현재 thesis와 같은 Prometheus·Loki·Kubernetes 조합에 가장 직접적인 benchmark 근거다.

하지만 WWW Companion 4-page 논문이라 통계 검정, confidence interval, 상세 campaign timing, cluster topology, cooldown, failure manifestation 기준이 충분히 설명되지 않는다. 각 case가 독립적인지, random load seed와 injection order를 통제했는지, repeated case 사이 contamination이 없는지도 본문만으로 확인할 수 없다.

세 system 모두 demo benchmark이며 fault는 single-target synthetic injection이다. Kubernetes-native control-plane, scheduler, reconciliation, rollout, RBAC, quota, image, DNS configuration fault가 없다. GitOps desired/reconciliation state도 수집하지 않는다.

더 중요한 construct threat는 ground-truth indicator에 있다. injected CPU target의 CPU metric이나 faulty code의 stack trace가 명시적으로 존재하면 retrieval/localization이 실제 causal reasoning 없이 label shortcut으로 풀릴 수 있다. benchmark는 evidence를 제공하지만 evidence leakage audit 자체를 제공하지 않는다.

## 8. thesis-rca 적용성

1. **fault taxonomy mapping**: 현재 F1–F12를 resource/network/configuration/GitOps-control-loop로 매핑하고 RCAEval과 겹치는 영역과 고유 영역을 명시한다.
2. **coarse/fine dual scoring**: service/pod localization과 root-cause indicator/evidence grounding을 분리해 보고한다.
3. **modality ablation**: Runtime metrics/logs, GitOps, RAG를 동일 snapshot에서 분리한다. RCAEval의 multi-source 결과처럼 “더 많은 modality=더 좋음”을 가정하지 않는다.
4. **indicator masking**: stack trace, injected object name, fault-specific label을 masked/full 조건으로 나누어 shortcut을 측정한다.
5. **campaign protocol 공개**: trial count뿐 아니라 injection duration, stabilization, collection window, cooldown, seed, missing telemetry를 기록한다.
6. **external validation 후보**: model 고정 실험 harness를 RCAEval 일부 cases에 적용하면 Online Boutique 단일 cluster 결과와 별도의 공개 benchmark generalization check가 가능하다.

RCAEval을 직접 사용한다면 raw data license/version, exact dataset release와 library commit을 pin해야 한다. repository main branch가 계속 변하므로 paper 당시 version과 현재 version을 섞지 않아야 한다.

## 9. 기억할 원문 표현

- “reproducible baselines”
- “coarse-grained and fine-grained”
- “root cause indicator”

## 10. 증거 수준

WWW Companion peer-reviewed primary benchmark이며 DOI, 공개 전문, GitHub artifact를 확인했다. dataset 재사용성과 축 B 직접성은 **높음**이다. 다만 4-page paper의 방법 보고 밀도와 injection-centric construct 때문에 production generalization 및 leakage 통제 근거는 **중간 이하**다.

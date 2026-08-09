# 논문 심층 분석: Root Cause Analysis for Microservices based on Causal Inference — How Far Are We?

> 분석일: 2026-08-09
> 분석 관점: 20년차 cloud SRE
> 논문: Luan Pham, Huong Ha, Hongyu Zhang, ASE 2024
> DOI: [10.1145/3691620.3695065](https://doi.org/10.1145/3691620.3695065)
> 전문: [arXiv:2408.13729](https://arxiv.org/abs/2408.13729)
> artifact: [RCAEval repository](https://github.com/phamquiluan/RCAEval)

## 1. 한 줄 요약

이 대규모 비교 연구는 causal graph를 학습한 뒤 PageRank/random walk를 붙이는 일반 해법이 작은 synthetic graph에서는 그럴듯해도 실제 대형 microservice telemetry에서는 random baseline 수준이거나 지나치게 느릴 수 있음을 보였다.

## 2. 핵심 기법과 원리 — 연구 질문과 방법 계보

논문은 metric-based RCA를 두 단계로 분해한다.

```text
multivariate time-series
  -> causal discovery (graph structure/direction)
  -> graph scoring or intervention recognition
  -> ranked root-cause service
```

9개 causal discovery method(Granger, PC, PCMCI, FCI, DirectLiNGAM, ICALiNGAM, GES, fGES, NTLR)와 21개 RCA 구성/방법을 effectiveness, efficiency, input length, failure-time sensitivity 관점에서 비교한다. graph scoring에는 PageRank와 random walk가 포함되고, end-to-end 계열로 CausalRCA, RUN, MicroCause, CIRCA, RCD, NSigma, BARO, ε-Diagnosis, CausalAI 등을 포함한다.

핵심 문제는 telemetry correlation을 causal direction으로 식별하기 어렵고, service 수가 늘면 metric graph가 폭발하며, 일부 방법이 실제로는 정확한 failure occurrence time을 oracle처럼 요구한다는 것이다.

## 3. 시스템·fault taxonomy·표본

### synthetic graph datasets

- CIRCA10/50, RCD10/50: 각 200 cases, graph node 10 또는 50
- CausIL10/50: 각 10 cases
- 총 820 synthetic cases

### Kubernetes microservice datasets

4-node AWS Kubernetes cluster에 Istio, Prometheus, cAdvisor를 사용하고 100–200 concurrent users로 load를 생성했다.

| dataset | metrics | services | target services | faults | cases |
|---|---:|---:|---:|---:|---:|
| Sock Shop 1 | 38 | 13 | 5 | 2 | 50 |
| Sock Shop 2 | 46 | 15 | 5 | 5 | 125 |
| Online Boutique | 49 | 12 | 5 | 5 | 125 |
| Train Ticket | 212 | 64 | 5 | 5 | 125 |

새로 수집한 세 dataset은 CPU hog, memory leak, disk I/O stress, network delay, packet loss를 각 5개 service에 주입했다. microservice cases는 총 425개다. 본문 threats section은 “four common faults”라고 적지만 Table 2와 setup은 새 dataset에 5개 fault를 명시한다는 내부 불일치가 있다.

## 4. 평가 metric과 실행 통제

- graph recovery: directed F1, skeleton F1(F1-S), Structural Hamming Distance(SHD)
- RCA: AC@k와 Avg@k; 핵심 비교표는 Avg@5
- efficiency: case당 runtime, 2시간 timeout
- 모든 experiment를 10회 반복하고 평균을 보고했다.
- source code가 있는 구현을 재사용하고 원 논문 결과 재현으로 correctness를 점검했다.
- 실행 환경은 Linux, 8 CPU, 16 GB RAM이다.
- Dummy(random node selection)를 반드시 포함해 graph method가 우연보다 나은지 검사했다.

## 5. 정량 결과

### causal graph 자체의 정확도

- default setting에서 9개 method의 directed F1은 synthetic datasets 전반에서 0.04–0.54에 머물렀다.
- PC는 18개 metric 조합 중 7개, FCI는 9개에서 최고였지만, 모든 방법에서 direction-aware F1이 skeleton F1보다 체계적으로 낮았다.
- 50-node graph에서 성능과 runtime이 크게 악화했다. RCD50의 PC/FCI는 OOM, GES/DirectLiNGAM/NTLR은 1시간/case 제한을 넘었다.
- tuning은 작은 graph에는 도움이 됐지만 CIRCA50에서 PC F1은 0.38→0.31, FCI는 0.33→0.30으로 오히려 하락했다.

### 실제 microservice RCA

- Online Boutique에서 CausalRCA Avg@5는 CPU 0.97, MEM 0.98, DISK 0.71, DELAY 0.92, LOSS 0.52였다.
- 같은 CausalRCA가 Train Ticket에서는 0.53, 0.30, 0.13, 0.17, 0.11로 급락했다.
- 정확한 failure time을 준 BARO는 Train Ticket fault별 Avg@5 0.90, 0.96, 0.84, 0.77, 0.66이었고, 60초 어긋난 time에서도 0.81, 0.99, 0.77, 0.82, 0.72였다.
- CIRCA는 Train Ticket에서 정확한 time일 때 0.66, 0.93, 0.64, 0.64, 0.57이지만 60초 오차 시 0, 0, 0.07, 0.03, 0.10으로 붕괴했다.
- PC/FCI/Granger/LiNGAM/GES/NTLR + PageRank/random-walk 계열 다수는 Dummy와 비슷하거나 약간 나은 수준이었다.

### efficiency

- Train Ticket case당 BARO/NSigma는 약 0.01초, RCD 12.44초였다.
- CausalAI 643.29초, CausalRCA 1326.34초, CIRCA 3792.29초였다.
- RUN, MicroCause, NTLR 계열 일부는 2시간/case 제한을 넘겨 결과가 없었다.

즉 accuracy만 좋아 보이는 method도 detection timing oracle이나 긴 observation window, large-graph runtime을 포함하면 on-call에 부적합할 수 있다.

## 6. validity threats

저자들은 다음을 명시한다.

- construct: RCA method는 원 논문의 default hyperparameter를 사용했으므로 완전한 공정 tuning을 보장하지 않는다.
- internal: 공개 구현 재사용·결과 재현·10회 반복으로 완화했지만 tool/data extraction의 미확인 threat가 남는다.
- external: benchmark와 common synthetic faults는 널리 쓰이나 다른 application/fault의 전파 특성은 다를 수 있다.

추가로 볼 위험은 다음과 같다.

- injection target service가 곧 root cause label이어서 causality의 operational definition이 단순하다.
- 동일 service/fault 반복이 독립 production incident diversity를 대체하지 못한다.
- exact failure time을 제공하는 configuration은 현실적 detector error를 제거한 oracle evaluation이다.
- synthetic dataset에서의 graph ground truth와 실제 microservice에서의 service label metric은 서로 다른 construct다.
- statistical uncertainty나 paired significance test 없이 평균 위주로 비교한다.

## 7. thesis-rca 적용성

1. **random/dummy baseline 유지**: LLM이 plausible label을 내는 것만으로 runtime evidence를 쓴다고 볼 수 없다. label prior나 class frequency baseline을 포함해야 한다.
2. **scale stratification**: Online Boutique 결과를 Train Ticket급 system으로 일반화하지 않는다. 현재 단일 Online Boutique 결과의 외적 타당성 경계를 명시한다.
3. **collection-time ablation**: fault onset 기준 window를 ±1 collection interval로 이동해 Runtime/GitOps arm ranking이 유지되는지 확인한다.
4. **graph direction audit**: topology adjacency 제공과 causal direction 제공을 별도 arm으로 분리한다. dependency graph를 causal graph라고 부르지 않는다.
5. **end-to-end 평가**: anomaly detection timestamp를 ground truth로 주입하지 않고 실제 alert/collector가 산출한 시점을 사용한다.
6. **latency 보고**: LLM accuracy와 함께 collection delay, inference latency, API calls를 trial별 기록한다.

이 논문은 thesis-rca가 “더 좋은 graph architecture”를 주장하기보다, evidence source·timing·scale 교락을 통제하는 평가 연구로 포지셔닝해야 한다는 강한 근거다.

## 8. 기억할 원문 표현

- “no method stands out”
- “sensitive to specific parameters”
- “synthetic datasets may not accurately reflect”

## 9. 증거 수준

ASE peer-reviewed empirical study이며 DOI, 공개 전문, code/data artifact를 확인했다. 비교 범위와 재현성은 **높음**, fault diversity와 production representativeness는 **중간 이하**다. 특히 scale·timing·random baseline에 관한 근거는 thesis 평가 설계에 직접 적용 가능하다.

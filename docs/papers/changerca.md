# 논문 심층 분석: ChangeRCA: Finding Root Causes from Software Changes in Large Online Systems

> 분석일: 2026-08-09
> 분석 관점: 20년차 cloud SRE
> 논문: Guangba Yu, Pengfei Chen, Zilong He, Qiuyu Yan, Yu Luo, Fangyuan Li, Zibin Zheng, Proceedings of the ACM on Software Engineering 1(FSE), 2024, Article 2, pp. 24–46
> DOI: [10.1145/3643728](https://doi.org/10.1145/3643728)
> 공식 학회 페이지: [FSE 2024](https://2024.esec-fse.org/details/fse-2024-research-papers/3/ChangeRCA-Finding-Root-Causes-from-Software-Changes-in-Large-Online-Systems)
> 저자 공개 전문: [ChangeRCA PDF](https://yuxiaoba.github.io/files/FSE24/changerca.pdf)
> 공개 구현·Online Boutique 데이터: [IntelligentDDS/ChangeRCA](https://github.com/IntelligentDDS/ChangeRCA)
> 증거 분류: **직접 RCA 근거 / GitOps에는 인접 근거** — change ticket·change flow를 원인 단위로 직접 평가하지만 Git repository desired state와 controller reconciliation state를 분해하지 않는다.

## 1. 한 줄 요약

개별 change의 anomaly만 보는 ACD를 넘어, pre/post instance 차이·change time·service dependency·fault propagation을 결합해 incident를 유발한 구체 change ticket을 순위화한다.

## 2. 핵심 문제와 기존 한계

대규모 online system에는 짧은 시간에 많은 정상 change와 소수 defective change가 공존한다. 기존 abnormal change detection(ACD)은 보통 변경 서비스의 pre/post KPI 차이만 본다. 이 때문에 다음을 놓친다.

- **silent defective change**: 변경된 service 자체 KPI는 정상처럼 보이지만 downstream/upstream에서 실패가 발생
- **delayed failure**: memory leak처럼 change 완료 12시간 뒤 나타나는 장애
- **propagated false positive**: 피해 service의 동시 change를 원인으로 오판
- **service-to-change gap**: 전통 RCA가 service까지만 좁히고 어떤 change가 문제인지는 SRE가 다시 조사

저자들은 incident를 유발한 defective change를 `root cause change`로 정의하고, 이를 찾는 문제를 Root Cause Change Analysis(RCCA)로 구분한다.

## 3. 핵심 기법과 원리

```text
service-level RCA trigger
  -> (1) defective canary change identifier
  -> (2) non-change fault identifier
  -> (3) suspicious change scorer
       = KPI + dependency + time
  -> ranked change tickets / rollback candidate
```

### Stage 1: canary causal comparison

pre-change instance를 control, post-change instance를 treatment로 보고 KPI 차이를 검사한다. Difference-in-Differences와 hypothesis test를 사용하며 기본 significance level `λ=0.05`, score threshold `η=0.8`이다. 이는 random traffic split과 parallel pre/post instance가 존재할 때 change effect를 식별하려는 준실험 설계다.

### Stage 2: non-change fault 분기

resource 부족이나 one-instance failure 같은 비변경 장애를 먼저 분리해 모든 incident를 change 탓으로 돌리는 오류를 줄인다.

### Stage 3: suspicious change score

- **KPI scorer**: 변경 전후 instance 차이
- **dependency scorer**: RCA service와 change service의 graph distance·전파 가능성
- **time scorer**: anomaly와 change 사이 시간 거리; 30분 base window를 8단계 배수로 확장

세 score의 weight는 SRE 판단에 따라 기본값을 모두 1로 둔다. change-level answer를 얻지만 dependency와 time은 여전히 관찰·휴리스틱 evidence이며, 자동으로 causal proof가 되는 것은 아니다.

## 4. 데이터셋·실험·정량 결과

### 4.1 두 데이터셋

| 데이터 | 내용 |
|---|---|
| A | WeChat production에서 3개월간 SRE가 label한 change-induced incidents 30건 |
| B | 12-node Kubernetes의 Online Boutique, incidents 51건 |
| 전체 | 81 incidents |
| B change 구성 | case마다 defective change 1개 + 서로 다른 service의 normal change 2~5개 |
| B fault taxonomy | backend 7종, configuration 3종, resource 2종 |

Online Boutique의 12종은 missing function call, wrong exception handling, missing parameter value, wrong return value, wrong SQL/cache/parameter order, wrong port, inconsistent config file, wrong access key, memory leak, insufficient resource allocation이다.

입력은 RCA service, service dependency graph, change flow, request success ratio KPI다. latency는 timeout이 success ratio 감소에 반영된다는 이유로 제외했다.

### 4.2 핵심 성능 — Table 3

| 데이터 | 방법 | HR@1 | HR@3 | HR@5 | Exam Score |
|---|---|---:|---:|---:|---:|
| A | ChangeRCA | **83.33%** | **90.00%** | **93.33%** | **1.83** |
| A | best ACD(SCWarn) | 70.00% | 80.00% | 80.00% | 3.43 |
| B | ChangeRCA | **88.23%** | **100.0%** | **100.0%** | **1.13** |
| B | best ACD HR@1(Gandalf) | 64.70% | 64.70% | 72.54% | 4.16 |

두 데이터 평균으로 ChangeRCA는 HR@1 85.78%, HR@3 96%, HR@5 96.67%를 보고한다. ACD 세 방법 대비 HR@1은 20~28 percentage points 높고, SRE가 실제 원인 전에 확인해야 하는 false-positive change 수인 Exam Score는 62~65% 감소했다.

### 4.3 ablation — Table 3

dependency graph 제거의 영향이 가장 크다.

| 데이터 | full HR@1 | without graph HR@1 | 차이 |
|---|---:|---:|---:|
| A | 83.33% | 56.67% | -26.66 points |
| B | 88.23% | 37.25% | -50.98 points |

KPI scorer 제거는 A/B에서 각각 73.33%, 72.54% HR@1이고, dependency scorer 제거는 70.00%, 80.39%, time scorer 제거는 60.00%, 82.35%였다. component 기여가 데이터셋마다 달라 단일 weight가 보편 최적이라는 근거는 없다.

### 4.4 TTI와 upstream RCA — Figure 9, Table 4

- WeChat의 defective change 90%를 3분 이내에 찾았고 SCWarn 35분, Gandalf 37분, FUNNEL 41분 대비 90% 이상 단축했다.
- 이 TTI는 실제 wall-clock incident resolution이 아니라 `approach runtime + false-positive ticket당 SRE 검토 2분`으로 계산한 모델 기반 지표다.
- Dataset B에서 upstream RCA를 GIED, Microscope, MicroRCA로 바꾸면 HR@1은 각각 88.23%, 74.50%, 88.23%였다. HR@3은 100%, 96.07%, 96.07%로 영향이 줄었다.

## 5. 실험 설계 비평

### 장점

- production incident와 공개 Kubernetes benchmark를 함께 사용한다.
- defective change와 2~5개 normal concurrent changes를 함께 넣어 realistic candidate competition을 만든다.
- dependency graph, KPI, time scorer를 각각 제거한 ablation이 있다.
- change-level ground truth와 Top-k/Exam Score를 사용해 실제 SRE 조사 부담을 반영한다.
- 공개 코드와 Online Boutique 데이터가 있어 benchmark 부분은 재현 가능성이 높다.

### 한계와 통계

- production 표본은 30건뿐이며 KPI retention 때문에 더 수집하지 못했다.
- 전체 81건에 confidence interval, repeated campaign variance, 유의성 검정이 없다.
- FUNNEL, Gandalf, Microscope는 공개 구현이 없어 저자 재구현이며 implementation bias 가능성이 있다.
- `λ`, `η`, time window는 dataset/system 특성에 의존하고 동일 데이터에서 sensitivity를 확인했다.
- Online Boutique fault는 1 defective change/case로 제한되어 multiple defective changes나 controller race를 다루지 않는다.
- TTI는 ticket당 2분이라는 추정에 크게 의존하고 detection·remediation time을 제외한다.
- service dependency graph와 change flow가 완전·정확하다고 가정한다.
- 신규 service는 pre-change instance가 없고 삭제 service는 post-change instance가 없어 식별이 어렵다.
- 사용자에게만 보이는 장애 feedback을 입력하지 않는다.

## 6. SRE 직감 평가

GitOps 환경과 가장 가까운 기반 연구다. “최근 change가 있었으니 그것이 원인”이라는 단순 temporal correlation을 넘어서, 피해 service까지의 dependency와 canary pre/post 차이를 함께 본다. 특히 silent backend/config change와 delayed fault를 별도로 논의한 점은 실제 on-call에 중요하다.

하지만 GitOps에서는 controller가 desired state를 적용하지 못했거나, 적용 후 drift를 되돌렸거나, health check만 실패했을 수도 있다. ChangeRCA의 change ticket만으로는 “의도된 change”, “실제 적용된 state”, “reconciliation 결과”를 구분하지 못한다.

## 7. thesis-rca 연결

### 가장 직접적인 적용

1. **change를 entity로 보존**: Git commit/manifest revision을 runtime symptom의 부가 문장이 아니라 독립 evidence로 모델링한다.
2. **동시 정상 change 통제**: 한 fault마다 관련 없는 GitOps change를 placebo candidate로 추가해 단순 recency shortcut을 검사한다.
3. **silent/delayed group 분리**: 변경 service metric이 직접 이상한 fault와 downstream에서만 드러나는 fault를 나눠 보고한다.
4. **pre/post 비교**: 가능하면 동일 workload에서 revision 전후 또는 canary instance를 비교한다.
5. **top-k와 review burden**: exact RCA accuracy 외에 후보 change 수와 Exam Score를 보조 지표로 사용한다.

### thesis-rca가 추가해야 할 GitOps signal model

```text
commit / manifest desired state
  -> controller reconciliation attempt
  -> applied revision / observed resource state
  -> rollout and pod events
  -> runtime symptoms
```

위 각 edge의 timestamp와 provenance를 분리해야 한다. `manifest diff`에 fault label이나 정답에 가까운 설명이 포함되면 ChangeRCA식 유용한 change evidence가 아니라 evidence leakage가 될 수 있으므로 masked/full/no-diff 조건이 필요하다.

## 8. 직접 지지 범위

| 주장 | 판정 |
|---|---|
| service dependency와 change flow가 defective change localization에 기여한다 | 직접 지지 |
| change-level RCA가 service-level RCA 이후의 수동 조사 범위를 줄일 수 있다 | 직접 지지 |
| concurrent normal changes를 포함한 평가가 가능하다 | 직접 지지 |
| GitOps desired/observed/reconciliation 각각의 독립 기여가 있다 | 지지하지 않음 |
| manifest diff를 prompt에 넣으면 reasoning이 향상된다 | 지지하지 않음; leakage 가능성 별도 감사 필요 |

## 9. 기억할 핵심 원문 표현

- “root cause change”
- “silent defective changes”
- “change flow”
- “pre-change and post-change instances”

발췌는 개념 식별을 위한 짧은 표현이며, 수치·한계는 전문의 Table 2–4, Figure 9–10, Threats to Validity를 대조했다.

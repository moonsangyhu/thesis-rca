# V2.4 결정론적 정답지 채점 전환 심층 분석

> 분석일: 2026-08-31
>
> 분석 대상: V2.3 Primary03의 사전선택 12 incidents·36 representative outputs,
> V2.4 package-only 결과, 공개 Kubernetes/microservice RCA benchmark
>
> 목적: 실제 사람 reviewer를 확보할 수 없는 조건에서 AI judge 없이
> `RAG가 RCA를 개선하는가`를 재현 가능하게 판정할 단일 측정 가설 고정

## 결론부터

공개 정답지가 있는 Kubernetes RCA benchmark는 존재한다. 그러나 다른 benchmark의 정답을
Primary03 출력에 붙이는 것은 불가능하다. Primary03에는 이미 incident별 정확한
`results/ground_truth.csv`가 있으며, 빠진 것은 정답이 아니라 자유서술 출력을 정답과 비교하는
독립 scorer다.

Primary03의 36개 representative output은 모두 다음 동일 schema다.

```text
identified_fault_type: string
root_cause: string
remediation: list[string]
```

따라서 공개 benchmark의 구조화 평가 계약을 차용해, 현재 출력 본문을 보지 않고 먼저
fault ontology·alias·concept atom·반증 규칙을 봉인한 뒤 local deterministic scorer로 평가할
수 있다. 이 전환은 V2.4의 `Terra-human agreement` 질문을 폐기하고, 다음 질문 하나로
대체한다.

> **H-V2.4-D:** 같은 12 incidents에서 blind procedural RAG는 length placebo보다
> deterministic Joint RCA Accuracy를 개선하는가?

새 모델 호출, 새 K8s 수집, 사람/AI judge는 모두 0이다. 기존 세 조건의 frozen output만
재채점하므로 조작 독립변수도 새로 도입하지 않는다. 바뀌는 한 변수는 **outcome 측정법**이다.

## 1. 입력과 측정 가능성 실측

Python `csv`/`json`으로 본문을 출력하지 않고 identity·schema만 확인했다.

```text
Primary03 CSV rows                    117
Primary03 raw JSON                    117
selected incidents                    12
selected outputs                      36
runtime / length placebo / blind RAG  12 / 12 / 12
representative output schema match    36 / 36
remediation list type match            36 / 36
selected ground-truth rows             12
Primary03 CSV SHA-256                  5fd2c1c52c8c37462f7f47eecb248a5a147166165c1cf2495d6e9b43956f8c5b
```

새 scorer의 lexicon을 출력에 맞춰 사후 조정하지 않도록 이 분석에서는 representative output
본문을 새로 읽지 않았다. 정답·오답 raw의 질적 표본은 이미 승인 전
`docs/surveys/deep_analysis_v2_4.md`에 기록돼 있으며, 새 ontology의 입력으로 사용하지 않는다.

## 2. 공개 정답지 benchmark 조사

### 2.1 Cloud-OpsBench — 평가 계약의 1순위 근거

[Cloud-OpsBench 공식 저장소](https://github.com/LLM4Ops/Cloud-OpsBench)는 Online Boutique
550건과 Train-Ticket 204건, 총 754 cases·57 fault types를 공개한다. 각 case의
`metadata.json`에는 fault label·namespace·query·ground-truth diagnosis가 있고,
`process-label/`에는 evidence milestone, `golden-trajectory/`에는 case당 두 expert diagnostic
trajectory가 있다. 공식 outcome metric은 Component Accuracy(CA), Fault-Type Accuracy(FA),
Joint RCA Accuracy(JRA)다.

공개 taxonomy와 본 실험 ground truth를 **출력과 무관하게** 비교하면 다음 대응이 가능하다.

| 우리 fault | 공개 taxonomy 대응 | 적용 |
|---|---|---|
| F1 memory limit OOM | `ContainerMemoryLimitTooLow` | 직접 대응 |
| F2 corrupted entrypoint | 없음 | local extension |
| F3 nonexistent image tag | `IncorrectImageReference` | 직접 대응 |
| F4 kubelet stopped | `KubeletUnavailable` | 직접 대응 |
| F5 missing StorageClass | `PVCStorageClassMismatch` | 직접 대응 |
| F6 deny-all NetworkPolicy | 없음 | local extension |
| F7 CPU limit 10m | `PodCPUOverload`와 증상 유사, mechanism은 다름 | local stricter extension |
| F8 selector mismatch | `ServiceSelectorMismatch` | 직접 대응 |

F7을 단순 `PodCPUOverload`로 합치면 CPU 수요 급증과 잘못된 CPU limit을 혼동하므로
`ContainerCPULimitTooLow`로 더 엄격히 봉인한다. 따라서 본 scorer는 “Cloud-OpsBench
compatible extension”이지 공식 Cloud-OpsBench 점수 재현이라고 주장하지 않는다.

### 2.2 RCAEval — service/fault exact scoring 근거

[RCAEval 공식 저장소](https://github.com/phamquiluan/RCAEval)와
[공식 논문](https://arxiv.org/abs/2412.17015)은 735 failure cases를 제공한다. 공개
`cases.parquet`에는 ground-truth root-cause service, fault type, injection time이 있으며,
RE1 375건·RE2 270건·RE3 90건으로 구성된다. 이는 service localization과 fault-type exact
scoring이 사람 rubric 없이도 정당한 RCA outcome이라는 근거다. 다만 remediation과 완전한
causal explanation은 평가하지 않는다.

### 2.3 OpenRCA — 구조화 free-text 변환 계약 근거

[Microsoft OpenRCA](https://github.com/microsoft/OpenRCA)는 prediction을
`root cause occurrence datetime`, `root cause component`, `root cause reason` 구조로 제출하고
공식 evaluator로 ground truth와 비교한다. 긴 telemetry를 읽는 LLM benchmark지만 최종 outcome을
구조화하는 계약은 본 실험의 `identified_fault_type/root_cause` 분리에 적용 가능하다. 데이터가
본 실험과 다른 Telecom/Bank/Market이므로 정답 자체를 가져오지는 않는다.

### 2.4 AIOps Challenge 2025 — evidence atom 근거

[공식 dataset 설명](https://www.aiops.cn/gitlab/aiops-live-benchmark/agenticopseval/-/commit/57c36fa46fb2f4dec19b5f5ca9cbf5a90f9c9e00?file_path=AIOps2025/README.md)은
Kubernetes HipsterShop 기반 400 cases를 공개한다. `groundtruth.jsonl`은 fault category/type,
instance level, service/instance, start/end time, log·metric·trace `key_observations`, `key_metrics`,
fault description을 포함한다. 따라서 fault label뿐 아니라 evidence concept atom을 명시적으로
봉인하는 방식의 근거가 된다. CC BY-NC 4.0이므로 데이터 재배포 없이 평가 계약만 인용한다.

### 2.5 AIOpsLab·SREGym — recovery validation과 제외 근거

[AIOpsLab](https://github.com/microsoft/AIOpsLab)은 Kubernetes 문제 코드에 expected solution과
실제 recovery state 검사를 구현하며 detection/localization/analysis/mitigation task를 분리한다.
이는 remediation을 실제 desired-state 복구로 평가해야 한다는 근거지만, 본 V2.4는 새 live
cluster 실행을 금지하므로 직접 사용하지 않는다.

[SREGym](https://github.com/SREGym/SREGym)은 90개 live SRE problems를 제공하지만 기본 실행이
별도 judge model을 사용한다. AI judge 순환을 제거하려는 본 전환의 primary evaluator로는
부적합하다.

### 2.6 rca-lab — 증상 checklist 근거

[coroot/rca-lab](https://github.com/coroot/rca-lab)은 실제 Kubernetes·database failure mechanism과
`expectedSymptoms`를 제공하고 이를 RCA grading rubric으로 사용한다. 그러나 live cluster와
새 telemetry가 필요하므로 본 frozen-output 평가가 아니라 후속 외적 타당성 실험 후보로 둔다.

## 3. 결정론적 outcome 계약

### 3.1 Primary outcome

각 output에 대해 다음 binary를 계산한다.

1. `CA`: canonical target component가 지정 field에서 탐지됨
2. `FA`: canonical fault family가 `identified_fault_type`에서 탐지됨
3. `MCA`: root cause가 사전등록된 mechanism concept group을 모두 만족하고 모순 group을 만족하지 않음
4. `JRA`: `CA ∧ FA ∧ MCA`

Primary outcome은 `JRA`다. Cloud-OpsBench JRA보다 mechanism gate 하나가 더 엄격하므로
`JRA-D`로 명명한다.

### 3.2 Secondary outcome

- `RA`: remediation list가 action·target·desired-state concept group을 모두 만족
- `FULL`: `JRA-D ∧ RA`
- CA, FA, MCA, RA 각각의 failure matrix
- strict/relaxed sensitivity: relaxed는 JRA에서 MCA만 제외한 `CA ∧ FA`

### 3.3 Matcher 고정 규칙

- UTF-8 strict decode → Unicode NFKC → casefold
- 영숫자 이외 문자는 단일 공백으로 정규화
- token 또는 명시적 regex concept group만 허용; embedding·LLM·fuzzy distance 금지
- matcher는 field별 allowlist를 적용한다. remediation의 정답 단어가 root-cause 점수를 올릴 수 없다.
- positive concept group은 그룹마다 하나 이상의 alias가 필요하다.
- contradiction group이 하나라도 맞으면 해당 축은 0이다.
- negated phrase는 positive로 세지 않는다. negation window와 pattern을 사전 테스트로 고정한다.
- output에 맞춘 alias 추가 금지. 변경 시 새 scorer version과 전체 재분석이 필요하다.

## 4. 통계·판정 계약

### 4.1 비교

- **Primary:** blind procedural RAG vs length placebo, 동일 12 incidents paired JRA-D
- **Secondary:** blind procedural RAG vs runtime paired JRA-D
- exploratory: 세 조건 Cochran's Q, fault별 component matrix, RA/FULL

Length placebo를 primary control로 고른 이유는 context 길이는 비슷하고 procedural content만
다르기 때문이다. Runtime 비교만 사용하면 길이·형식 차이가 함께 움직인다.

### 4.2 추정과 검정

- paired risk difference와 12-pair 원자료 표
- discordant pair exact one-sided McNemar/binomial test: H1=`RAG-only > placebo-only`
- effect CI는 paired binary bootstrap을 고정 seed `20260831`, 50,000회로 계산
- primary 하나만 confirmatory로 취급; secondary는 descriptive이며 p-value를 성공 판정에 사용하지 않음
- 결측·parse 실패·schema mismatch는 오답으로 대체하지 않고 전체 run을 fail-closed

### 4.3 판정

| 상태 | 사전등록 조건 |
|---|---|
| `SUPPORTED` | RAG JRA-D > placebo JRA-D, exact one-sided p<0.05, RAG FULL이 placebo보다 낮지 않음 |
| `DIRECTIONAL_ONLY` | RAG JRA-D > placebo지만 p≥0.05 |
| `NO_EVIDENCE` | JRA-D 동률 또는 discordant pair 0 |
| `REVERSED` | RAG JRA-D < placebo JRA-D |
| `INVALID` | ontology/hash/input/schema/blinding/replay gate 실패 |

n=12에서 유의성은 매우 보수적이다. 예를 들어 placebo-only가 0이면 RAG-only가 최소 5여야
one-sided exact p=0.03125가 된다. 따라서 `DIRECTIONAL_ONLY`를 효과 입증으로 표현하지 않는다.

## 5. 타당성 위협과 통제

### 구성 타당성

lexical concept matching은 올바른 paraphrase를 놓칠 수 있다. strict/relaxed 결과와 축별 matrix를
함께 보고하고 `FULL`을 별도로 둔다. 이는 free-text 전체 품질의 human-equivalent 점수가 아니다.

### 내적 타당성

ontology가 output을 본 뒤 작성되면 사후 overfitting이다. ontology JSON·scorer code·test·plan hash를
결과 계산 전에 commit하고, 별도 fresh reviewer가 output을 열지 않은 상태에서 P0 검토한다.

### 통계 타당성

12 pairs는 power가 낮다. primary comparison과 outcome을 하나로 제한하고 raw discordance를
숨기지 않는다. fault별 비율은 기술 통계로만 사용한다.

### 외적 타당성

Primary03은 F1~F8 incomplete non-random prefix이며 Online Boutique 단일 환경이다. 공개 benchmark
taxonomy 차용은 metric 정당성을 높이지만 dataset 외적 타당성을 자동으로 제공하지 않는다.

### 대안 가설

- RAG가 실제 RCA를 개선한 것이 아니라 canonical label lexical match만 늘렸을 수 있다.
- strict matcher가 condition별 문체 차이를 성능 차이로 오인할 수 있다.
- representative generation 선택이 결과를 좌우할 수 있으나 비대표 72개 본문이 없다.
- public benchmark label이 모델 사전학습에 포함됐더라도 본 출력은 private incident identity와
  generation-before-evaluation 순서를 가지므로 scorer 설계 누출과는 구분해야 한다.

## 6. 단일 가설과 실행 권고

### 1순위 가설: public-benchmark-aligned deterministic JRA-D

- **변경 변수:** Terra/human outcome 대신 frozen ground-truth ontology 기반 JRA-D 한 가지로 변경
- **데이터 근거:** 36/36 output이 구조화 schema이며 12 paired incidents×3 conditions가 완전함
- **문헌 근거:** Cloud-OpsBench CA/FA/JRA, RCAEval service/fault ground truth,
  AIOps2025 evidence atoms, AIOpsLab recovery validation
- **메커니즘:** 정답 component·fault family·mechanism을 field-isolated exact concept matcher로
  판정해 judge 비결정성과 사람 부재를 제거
- **예상 효과:** 방향은 사전 예측하지 않는다. 효과 크기 예측도 결과 독립성을 위해 금지한다.
- **반증:** RAG JRA-D가 placebo와 같거나 낮으면 H-V2.4-D는 지지되지 않는다.
- **비용:** 새 model/K8s call 0; local parser·test·analysis만 필요

### 후속 후보 A: Cloud-OpsBench frozen external replication

V2.4-D가 directional 이상이면 Cloud-OpsBench의 Online Boutique exact-overlap cases에 같은 모델·
prompt를 사전등록해 외적 타당성을 검증한다. 이는 새 모델 호출이 필요한 별도 실험이며 본 round에
포함하지 않는다.

### 후속 후보 B: live recovery validation

AIOpsLab/rca-lab 방식으로 remediation 실행 후 desired-state와 service health를 측정한다. 안전·비용·
cluster mutation이 필요한 별도 실험으로 둔다.

## 7. 실행 전 hard gate

1. 기존 `experiment_plan_v2_4.md`를 덮어쓰지 않고 deterministic addendum을 새 문서로 작성한다.
2. ontology는 ground truth와 공개 taxonomy만 입력으로 만들고 output text를 열지 않는다.
3. ontology/scorer/test/plan hash를 결과 실행 전에 commit·push한다.
4. fresh methodology reviewer가 alias coverage, negation, field isolation, multiple testing,
   outcome-independent design을 승인해야 한다.
5. scorer 실행은 별도 clean checkout에서 frozen commit과 frozen Primary03 digest로 수행한다.
6. 결과 계산 후 fresh results critic이 raw 36 rows와 paired table을 독립 재계산한다.

이 gate를 만족하면 실제 사람을 구하지 않고도 **구조화 RCA 정확도에 한정하여** RAG의 순기여를
판정할 수 있다. Terra-human agreement와 semantic L3는 폐기된 질문으로 기록하며 결과를 사람 평가와
동등하다고 표현하지 않는다.

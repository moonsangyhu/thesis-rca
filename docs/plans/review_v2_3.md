# V2.3-RAG 방법론 비평 — 승인 전 5축 리뷰

> 리뷰일: 2026-08-09
> 대상: `docs/plans/experiment_plan_v2_3.md`
> 판정: **조건부 승인 가능** — 아래 P0 수정 4건을 계획에 반영하기 전 구현 금지

## 1. 요약 판정

설계의 중심 대비는 타당하다. 같은 incident에서 runtime evidence를 한 번만 수집하고 `blind_procedural_rag − length_placebo`를 paired estimand로 삼았으므로, V2.2에서 분리하지 못한 절차 지식과 길이 효과를 직접 비교할 수 있다. GitOps·context position·V2.2 절대 비교를 제외한 것도 단일변수 원칙에 맞다.

그러나 현재 계획대로 실행하면 다음 네 약점이 논문의 중심 결론을 제한한다.

1. F1 파일럿은 가장 긴 prompt와 가장 비싼 AIC 사용을 대표하지 않아 본실험 비용을 과소추정할 수 있다.
2. generator와 judge가 동일 Terra인데 human audit이 36건뿐이라 primary accuracy가 self-evaluation bias의 산물이라는 반론을 충분히 막지 못한다.
3. 12개 fault cluster에 대한 bootstrap CI만으로는 작은 cluster 수에서 불안정하며, mixed-effects 구현 가능성도 고정되지 않았다.
4. lexical scanner 0건은 필요조건이지만, procedure가 정답 후보를 사실상 하나로 좁히는 semantic shortcut을 검출하지 못한다.

## 2. 구성 타당성

### 강점

- 독립변수 `context_condition` 하나와 세 수준이 명확하다.
- 1차 estimand가 `blind_procedural_rag − length_placebo`로 고정돼 있다.
- runtime은 기준선, placebo는 길이/attention 대조라는 역할이 분리돼 있다.
- full/self-runbook·GitOps·position을 제외해 해석 범위를 억제했다.
- model 변경을 명시하고 V2.2 절대값 비교를 금지했다.

### 위험

`blind_procedural_rag`가 label 문자열을 제거해도 procedure sequence가 특정 fault 하나에만 대응한다면 처치는 “절차 지식”보다 “간접 정답 후보 제한”을 측정할 수 있다. 이는 완전히 제거할 수 없으므로 구성개념을 다음처럼 좁혀야 한다.

> 측정 대상은 causal reasoning 자체가 아니라 **label·entity가 제거된 retrieved procedure의 잔여 진단 효용**이다.

또한 placebo는 blind block의 내용을 보고 생성하면 내용 차이가 또 다른 처치가 된다. 사전 고정된 neutral corpus에서 문자/byte/proxy-token 목표 길이만 사용해 deterministic truncate/pad해야 하며, blind text의 단어나 문장구조를 참조하면 안 된다.

### 필수 수정 P0-C

- procedure corpus 전체에 대해 `label exposed / entity exposed / unique mechanism cue / generic procedure` 4축 semantic audit rubric을 고정한다.
- 각 procedure가 어떤 fault에 매핑되는지 가린 상태에서 사람 검토를 수행하고, `unique mechanism cue`가 남은 문서는 제외하거나 별도 플래그로 sensitivity 분석한다.
- 논문 용어를 “reasoning improvement”가 아니라 “residual diagnostic utility”로 고정한다.

## 3. 내적 타당성

### 강점

- incident당 injection·collection을 한 번만 하고 runtime hash를 세 condition이 공유한다.
- balanced Latin-square order와 새 Copilot session으로 순서·대화상태 교락을 줄인다.
- leakage/treatment/recovery/model provenance 실패를 accuracy 결측으로 처리하지 않고 campaign 중단으로 정의했다.
- 서로 다른 sub-campaign을 primary dataset에 이어 붙이지 않는다.

### 위험

- Copilot CLI의 동일 model ID는 backend weights·serving policy 불변을 보장하지 않는다.
- 세 condition을 직렬 호출하므로 서비스 시간 drift가 남는다. Latin-square는 평균 순서효과를 완화하지만 제거하지 않는다.
- runtime context 안의 `OOMKilled` 같은 실제 관측 label은 legitimate evidence다. 이를 blind-RAG forbidden lexicon과 혼동해 runtime에서 지우면 실제 task가 바뀐다.
- 자동 재시도는 성공한 조건만 더 많이 호출하는 informative retry가 될 수 있다.

### 필수 통제

- runtime evidence는 harness marker만 검사하고 실제 Kubernetes status/error label은 보존한다.
- CLI 오류·schema 오류는 동일 조건에 자동 재시도하지 않고 row/campaign attrition으로 기록한 뒤 중단 규칙을 적용한다.
- condition별 호출 시작시각과 전체 campaign 동안 CLI version/model ID를 기록한다.
- 모델 backend의 비가시적 변경 가능성을 외적·재현성 한계로 명시한다.

## 4. 외적 타당성

단일 6-node cluster, Online Boutique, 12개 synthetic fault, 한 corpus와 한 시점의 Copilot Terra에 한정된다. V2.3에서 입증 가능한 것은 다음뿐이다.

> 이 testbed의 동일 incident에서 blind procedural RAG가 matched placebo보다 남기는 평균 paired accuracy 차이.

production MTTR, 다른 LLM, 다른 retriever, 다른 runbook 품질, GitOps 효과로 일반화할 수 없다. 특히 Terra는 V2.2 모델과 다르므로 V2.2→V2.3 성능 변화는 방법 개선 효과가 아니다.

12 fault의 선택이 전체 Kubernetes fault population을 대표하지 않으므로 fault-average는 design set average다. fault-group 결과는 탐색적이어야 한다.

## 5. 통계 타당성

### 강점

- 2,160 LLM call을 표본수로 세지 않고 60 incident/12 fault cluster를 추론 단위로 둔다.
- +10%p를 최소 실질 효과로 사전 지정했다.
- threshold sweep과 continuous score를 sensitivity로 분리했다.

### 위험

- cluster bootstrap은 cluster가 12개뿐이라 CI endpoint가 resampling 방식에 민감하다.
- `statsmodels`의 일반 GLMM 지원 여부가 보장되지 않으며, 분석 후 임의 구현을 선택하면 researcher degree of freedom이 생긴다.
- `strong support = CI lower > 0`은 엄격하지만, 이 조건을 만족하지 못했다고 효과가 없다고 결론내리면 안 된다.
- Terra judge의 binary threshold가 사람 판정과 어긋나면 정밀한 CI도 잘못된 outcome을 정밀하게 추정할 뿐이다.

### 필수 수정 P0-S

1. primary는 fault-cluster bootstrap CI와 점추정으로 유지한다.
2. 보조 검정으로 fault cluster 전체의 condition label을 함께 swap하는 정확한 cluster permutation test(`2^12` 가능)를 사전 고정한다.
3. mixed-effects model은 구현 패키지·버전·수렴 기준을 dry-run 전에 고정할 수 있을 때만 보조 분석으로 사용한다. 실패 시 다른 모델로 바꾸지 않고 미실행을 보고한다.
4. percentile/BCa 등 bootstrap 방식을 코드와 plan에 사전 고정하고 동일 data에서 유리한 방식을 선택하지 않는다.
5. CI가 0을 포함하는 양의 효과는 “방향 지지이나 불확실”로만 표현한다.

## 6. Judge 타당성

Terra generator를 Terra judge가 평가하는 것은 condition 간 동일하게 적용되므로 비교의 공정성은 있지만, correlated error와 self-preference를 제거하지 못한다. 현재 계획의 fault당 1 trial × 3 condition = 36 representative output audit은 전체 180 row outcome의 calibration 근거로 약하다.

### 필수 수정 P0-J

- condition·fault·retrieval source를 가린 상태에서 primary human reviewer가 180개 representative output 전체를 동일 rubric으로 채점한다.
- 독립 second reviewer가 사전 층화 무작위 36개를 채점해 agreement와 Krippendorff α 또는 Cohen κ를 보고한다.
- Terra-judge outcome을 1차 자동 지표로 유지하되, human-primary 재채점 결과에서 효과 방향이 반대이면 “강한 지지”를 선언하지 않는다.
- 사람 reviewer가 한 명뿐이면 180개 전수 single review + 36개 delayed repeat를 차선으로 사용하고 독립성 한계를 명시한다.

## 7. AIC·운영 타당성

F1 × trial 1은 기능 검증에는 적합하지만 비용 stress test로는 약하다. V2.2 raw에서 가장 긴 context는 F7 trial 5 계열로 약 16.6k characters였으며, F1의 일부 context는 약 3.7k~7.8k였다. F1 비용을 60배 하면 긴 fault의 AIC를 과소추정할 수 있다.

### 필수 수정 P0-B

- 최초 historical maximum proxy F7 trial 5는 실제 5m rollout이 Ready가 되지 않아 CPU-throttle과 rollout failure가 교락됐으므로 무효화한다. 사용자 승인에 따라 pilot-only target을 F7 trial 1(10m frontend, historical 최대 약 12.9k chars)로 변경하고, t5/t1 context ratio 약 1.29를 비용 투영에 추가한다.
- 기능 smoke는 mock/F1으로 무료 수행하고, 유료 36-call AIC pilot은 cost-stress incident 하나만 사용한다.
- budget projection은 `P×60×1.15×1.29`와 `(540×Gmax + 1,620×Jmax)×1.15×1.29` 중 큰 값을 사용한다.
- 파일럿 전후 UI의 실제 AIC balance와 call-ledger 합이 일치하지 않으면 본실험을 중단한다.
- 10% account reserve 외에 사용자가 별도로 보존할 회사 AIC가 있으면 그 금액을 먼저 차감한다.
- 잔여 AIC와 무관하게 조직 관리자의 `AI credits paid usage = Disabled` 및 budget hard-stop 증빙이 없으면 Copilot subprocess를 실행하지 않는다. 로컬 환경 flag와 per-session AIC cap은 보조 gate일 뿐 관리자 정책을 대체하지 않는다.
- Copilot CLI 1.0.78의 세션 상한 최소값 30 AIC를 사용하되, 다음 호출 전에 해당 30 AIC를 campaign 잔여 상한에서 예약해 누적 최악값이 360 AIC를 넘으면 subprocess를 시작하지 않는다.
- F7 live patch가 Flux의 10분 reconcile로 소실될 수 있으므로 `flux-system/app`을 incident 동안만 suspend한다. 원래 suspend field의 존재 여부와 값을 mutation 전에 fsync하고, F7 desired state를 복구한 뒤 Flux를 정확히 원복하지 못하면 결과를 commit하지 않는다. 이 조치는 세 arm 공통이지만 active reconciliation 환경에 대한 외적 타당성 한계로 보고한다.

## 8. 대안 가설

양의 결과가 나와도 다음 설명이 가능하다.

1. 절차 지식이 reasoning을 개선한 것이 아니라 후보 fault 공간을 좁혔다.
2. RAG block의 형식·명령어 밀도·구조가 neutral prose보다 attention을 끌었다.
3. same-model judge가 자신의 문체와 procedure 용어가 포함된 답변을 선호했다.
4. 긴 context가 정확도를 높였고 proxy-token ±1%가 실제 Terra token 길이를 맞추지 못했다.
5. retriever가 runtime에 이미 존재하는 canonical label을 query로 사용해 사실상 label-conditioned retrieval을 수행했다.
6. condition 실행 순서나 서비스 시간대가 결과에 영향을 줬다.

따라서 결과 해석에는 treatment-integrity, retrieval query provenance, human outcome, order/time sensitivity를 함께 제시해야 한다.

## 9. 최종 판정과 다음 gate

### 유지할 설계

- 세 condition과 paired incident 구조
- Terra generator/judge 고정 및 V2.2 절대 비교 금지
- k=3, m=3과 180 rows/2,160 calls
- leakage 0건, runtime hash, recovery, provenance hard gate
- GitOps·context position 후속 분리

### 구현 전 반영할 P0

| ID | 수정 |
|---|---|
| P0-C | semantic shortcut rubric와 deterministic independent placebo |
| P0-S | exact cluster permutation 및 bootstrap/GLMM 구현 사전 고정 |
| P0-J | human 180 전수 + 독립/반복 36 calibration |
| P0-B | 최대-context 36-call AIC stress pilot과 보수적 비용 상한 |

이 네 항목을 계획서에 반영하고 사용자가 수정 설계를 승인하기 전에는 Step 3 구현, lab tunnel, fault injection을 시작하지 않는다.

## Step 3B 독립 코드 재리뷰 결과 — 2026-08-09

초기 구현은 authorization 직접 생성, 실패 호출 과금 provenance 유실, recovery 전 결과 commit, post-injection 검증 부재, 짧은 field-value 누출, bootstrap 횟수 변경 가능성 때문에 승인되지 않았다. 반복 적대 검토 후 다음 hard gate를 확인했다.

- 증거 artifact 3종·환경 gate·사용자 approval을 live 경계마다 재검증하며 forged authorization을 거부한다.
- 모든 Copilot subprocess attempt는 strict parse보다 먼저 charged-call receipt를 fsync한다. 비정형 JSONL이나 nested data도 receipt를 보존한 채 `CopilotCLIError`로 중단한다.
- known 실패-call AIC는 campaign 누적값에 반영하고 usage가 불명확하면 campaign을 영구 중단한다.
- F7 trial 1의 실제 `frontend` deployment와 `server` container, 10m CPU, Ready pod 상태를 검증한 뒤에만 collection과 36 calls를 허용한다.
- recovery GREEN 후에만 3-row pilot 결과를 commit한다.
- primary 분석 bootstrap은 fault-cluster 50,000회·seed 20260809로 고정되어 CLI에서 변경할 수 없다.

최종 독립 판정은 승인이다. 리뷰 과정의 모든 재현은 mock subprocess/cluster fixture로 수행했으며 실제 Copilot·클러스터 호출은 0건이다.

# 실험 계획서 V2.3-RAG — Blind procedural RAG의 누출 통제 순기여

> 작성: 2026-08-09 · Experiment Track Step 1 설계 초안
> 입력: `docs/surveys/deep_analysis_v2_3.md`, `results/analysis_v2_2.md`, `docs/plans/next_experiment_goal_v2_3.md`, `docs/plans/experiment_plan_v2_2.md`
> 사용자 승인 고정사항: Copilot CLI `gpt-5.6-terra`, generator/judge 모두 Terra, 독립변수 `context_condition` 하나
> 상태: **설계 승인·Step 3A/3B 코드 검증 완료** — 2026-08-12 사용자의 paid-overage 허용 지시에 따라 36-call 파일럿 재개 준비 완료
> Step 3B: zero-overage evidence verifier, gated Terra caller, runtime-only retriever, post-injection validator, recovery-before-commit pilot runner와 고정 분석 스크립트가 독립 재리뷰를 통과했다. 실행 runbook은 `docs/plans/v2_3_pilot_runbook.md`.

## 0. 설계 결정과 선행 조건

### 0.1 이번 라운드의 단일 질문

V2.3-RAG는 같은 incident의 동일 runtime evidence에 길이가 같은 두 추가 컨텍스트를 붙였을 때, 정답 단서를 제거한 절차형 RAG가 무의미한 길이 placebo보다 RCA 정확도를 높이는지만 검증한다.

> **독립변수:** `context_condition` 하나
> **수준:** `runtime`, `length_placebo`, `blind_procedural_rag`

GitOps 처치와 context-position 처치는 포함하지 않는다. GitOps 신호 정상화는 별도 후속 실험이며, 컨텍스트 위치는 세 조건에서 고정하는 통제값일 뿐 V2.3의 요인이 아니다. Full/self-runbook arm도 포함하지 않으므로 V2.3은 `full − masked` shortcut 크기를 직접 추정하지 않는다.

### 0.2 모델 정책의 명시적 예외와 비교 경계

repo 정본은 실험 간 `gpt-4o-mini` 고정을 요구하지만, 이번 라운드는 사용자의 명시적 승인에 따라 다음처럼 예외를 적용한다.

- provider: GitHub Copilot CLI prompt mode
- generator: `gpt-5.6-terra`
- judge: `gpt-5.6-terra`
- 본실험 SDK inference deadline: 300초(+독립 watchdog cleanup grace 30초). 이 값은
  `campaign_manifest.json`에 봉인하며, timeout은 사용량 불확실성으로 fail-closed한다.
- auto routing: 명시적 모델 지정과 실제 응답 model ID 검증으로 차단
- tools: `--available-tools=none`; tool event가 관찰되면 fail-closed
- built-in MCP: `--disable-builtin-mcps`
- remote/remote export: `--no-remote`, `--no-remote-export`
- custom instructions: `--no-custom-instructions`
- repository 접근: 매 호출마다 빈 임시 작업 디렉터리를 사용하고 prompt에도 파일·명령·tool 사용 금지를 명시

현재 adapter의 `--allow-all-tools`는 비대화형 승인 flag이지만 `--available-tools=none`과 함께 전달된다. Step 2/3에서는 이 조합의 **실효 tool surface가 빈 집합**임을 테스트해야 하며, tool이 하나라도 노출되면 사용자 승인 조건 위반으로 중단한다.

따라서 V2.2의 `gpt-4o-mini` 절대 정확도(예: RAG 65.0%, placebo 36.7%)와 V2.3 Terra 절대 정확도를 직접 비교하지 않는다. V2.2 수치는 결함과 설계 동기의 근거로만 사용하며, V2.3의 1차 주장은 같은 Terra·같은 incident 안의 paired contrast로 한정한다.

### 0.3 최근 Research Track 산출물 통합 prerequisite

최근 survey `docs/surveys/paper_survey_v1.md`와 관련 paper note는 현재 원본 worktree `/Users/yumunsang/thesis-rca`에만 있고 이 feature worktree에는 아직 통합되지 않았다. 다음을 **Step 2 방법론 비평 완료 및 Step 3 구현 진입의 선행 gate**로 둔다.

1. survey와 본 계획이 인용한 paper note가 정식 PR 경로로 이 branch의 `docs/surveys/`, `docs/papers/`에 통합돼야 한다.
2. 상대 링크, 제목·저자·연도·원문 URL, 정량 수치가 실제 파일과 일치해야 한다.
3. 통합 전에는 원본 worktree의 문헌을 설계 입력으로 읽을 수만 있으며, 이 branch에 존재하는 정본처럼 주장하거나 계획 승인을 구현 승인으로 간주하지 않는다.

## 1. 실험 목적과 근거

### 1.1 V2.2에서 해결해야 할 문제

V2.2는 12 fault × 5 trial × 5 arm의 300행을 수집했다. RAG arm은 39/60=65.0%, length placebo는 22/60=36.7%였고 paired discordance는 RAG-only 18건, placebo-only 1건이었다. 그러나 RAG가 포함된 120 arm-row 중 90건(75%)에서 주입 fault의 자기 런북이 검색됐으며, 자기 런북 회수군 정확도는 67.8%, 비회수군은 46.7%였다. 파일명·제목·진단명이 정답을 드러냈으므로 이 차이는 절차 지식의 순효과가 아니라 retrieval leakage를 포함한 총효과다.

또한 V2.2는 F1–F8과 F9–F12가 서로 다른 sub-campaign에서 수집돼 fault-group 비교에 시점 교락이 남았다. V2.3은 모든 fault를 같은 campaign과 동일 복구 규칙 아래 수집한다.

### 1.2 최근 문헌에서 가져온 설계 원칙

| 근거 | 핵심 관찰 | V2.3 적용 |
|---|---|---|
| *Flow-of-Action* — Changhua Pei et al., 2025, [arXiv 2502.08224](https://arxiv.org/abs/2502.08224) | SOP knowledge 제거 시 54.06%→15.39%로 하락 | 진단명 대신 확인·분기·복구 절차만 제공하되 shortcut과 분리 |
| *Auditable Graph-Guided Root Cause Analysis for Kubernetes Incidents* — Anastasiia Kuvshinova, Seungmin Jin, 2026, [arXiv 2606.08590](https://arxiv.org/abs/2606.08590) | hint 제거 시 headline entity F1 gain이 크게 축소 | label·entity·provenance leakage scanner와 stripped context gate |
| *Overestimation in LLM Evaluation — Data Contamination's Impact* — Muhammed Yusuf Kocyigit et al., 2025, [PMLR](https://proceedings.mlr.press/v267/kocyigit25a.html) | source-target 결합 오염이 최대 30 BLEU inflation | 입력과 정답의 결합 노출을 test-time retrieval leakage로 분리 감사 |
| *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena* — Lianmin Zheng et al., 2023, [NeurIPS](https://proceedings.neurips.cc/paper_files/paper/2023/hash/91f18a1287b398d378ef22505bf41832-Abstract-Datasets_and_Benchmarks.html) | 위치·장황성·자기선호 편향 | condition/source/model 표식을 judge에서 제거하고 reference rubric 고정 |
| *Rating Roulette* — Rajarshi Haldar, Julia Hockenmaier, 2025, [ACL Anthology](https://aclanthology.org/2025.findings-emnlp.1361/) | 반복 judge의 Krippendorff α가 task/model에 따라 0.265~0.788 | judge `m=3`, 원 vote·분열률·α 보존 |
| *Lost in the Middle* — Nelson F. Liu et al., 2024, [TACL](https://aclanthology.org/2024.tacl-1.9/) | 같은 증거도 위치에 따라 20%p 이상 차이 | V2.3에서는 위치를 바꾸지 않고 고정·기록; 위치 실험은 후속 분리 |

문헌의 절대 성능은 task·모델·judge가 달라 V2.3의 기대 정확도로 전용하지 않는다.

## 2. 1차 estimand와 가설

### 2.1 분석 단위

`i`를 fault(F1–F12), `j`를 trial(1–5), `c`를 context condition이라 한다. 한 `(i,j)` incident에서 fault를 한 번 주입하고 runtime evidence를 한 번 수집한 뒤 세 condition이 그 동일 직렬화 결과를 공유한다.

각 condition에서 generator를 `k=3`회 독립 호출하고, 생성 응답 각각을 blinded judge가 `m=3`회 독립 채점한다. 세 judge score의 중앙값을 생성 응답의 score로, 다수 진단 label에 속한 생성 응답 score의 중앙값을 row-level 대표 score로 삼는다. `Y_ijc`는 사전 지정 primary threshold 0.5에서 row-level 대표 score가 정답이면 1, 아니면 0이다.

생성·judge 호출 수는 표본수가 아니다. 추론 단위는 **60개 paired incident가 12개 fault에 중첩된 반복측정**이다.

### 2.2 1차 estimand

```text
Δ_primary = (1 / 60) × Σ_i Σ_j
            [Y_ij,blind_procedural_rag − Y_ij,length_placebo]
```

즉, 같은 Terra·같은 incident·같은 runtime evidence·같은 추가 길이에서 blind procedural RAG가 length placebo보다 만드는 정확도 차이(%p)다. incident를 동일 가중하고 fault마다 trial 수가 같으므로 fault도 동일 가중된다.

### 2.3 사전 가설과 기대 범위

- `H0: Δ_primary ≤ 0`
- `H1: Δ_primary > 0`
- 실질적으로 의미 있는 사전 목표: 점추정 **+10%p 이상**
- 95% CI와 threshold 0.5/0.6/0.7의 방향 안정성을 함께 보고하며, p-value 하나로 성공을 선언하지 않는다.

V2.2 수치에서 Terra 효과를 예측하지 않는다. +10%p는 blind procedure가 길이만 늘린 대조보다 남겨야 할 최소 실질 효과의 운영적 목표이지, V2.2 대비 향상 목표가 아니다.

## 3. 처치 정의와 treatment integrity

### 3.1 세 condition

| 값 | 입력 | 역할 |
|---|---|---|
| `runtime` | kubectl·Prometheus·Loki 등 동일 runtime evidence만 | 무추가-context 기준선 |
| `length_placebo` | runtime + 의미 없는 중립 filler | blind RAG와 추가 길이/attention 부담 통제 |
| `blind_procedural_rag` | runtime + 검색된 procedure-only block | 정답 단서를 제거한 절차 지식의 순기여 |

`blind_procedural_rag`는 기존 retriever 설정과 corpus version을 campaign 전에 동결한다. 검색된 source의 파일명·제목·fault name은 generator에게 주지 않고, `확인 → 분기 → 다음 관찰 → 안전한 복구` 절차만 중립 문서 ID 아래 직렬화한다. retrieval query는 runtime evidence에서만 만들며 ground truth, injected fault ID, injection command를 사용하지 않는다. 원 source ID·chunk span·retrieval score·mask transform은 generator context가 아닌 raw provenance에만 저장한다.

`length_placebo`는 K8s·fault·runbook·entity·조치 단어가 없는 사전 고정 neutral corpus에서 deterministic truncate/pad로 만든다. 목표 문자·byte·proxy-token 길이만 입력으로 사용하고 blind procedure의 단어·문장구조·source는 참조하지 않는다. 각 incident의 blind procedure block과 Unicode 문자 수 및 UTF-8 byte 수를 맞추고, 사전 고정한 local proxy tokenizer 기준 차이를 ±1% 이내로 제한한다. Copilot CLI가 실제 input-token count를 제공하지 않으므로 이를 모델 토큰의 완전한 동등성으로 표현하지 않는다.

### 3.2 고정 요소

세 condition 사이에서 다음은 완전히 같아야 한다.

- runtime evidence의 원문, 수집 시각, 정렬, 직렬화, SHA-256 hash
- generator/judge model과 provider, system prompt, output schema, approximate max-output-token 지시
- context section 순서와 additional block 삽입 위치
- generator `k=3`, judge `m=3`, judge rubric, aggregation, threshold
- retriever/corpus/masker/scanner version과 source snapshot
- 호출별 빈 임시 cwd, tool/MCP/remote/custom-instruction 차단 정책
- cluster state, fault injection, collection window, arm 사이 cooldown 없음

condition 호출 순서는 새 독립변수가 되지 않도록 `(fault, trial)`에 대해 사전 생성한 균형 Latin-square 순서를 사용한다. 순서표와 seed는 campaign 전에 고정하고 raw provenance에 남긴다. 각 Copilot 호출은 새 session이어야 하며 session 재사용으로 condition 간 대화 상태를 공유하지 않는다.

### 3.3 treatment-integrity gate

한 incident라도 아래를 만족하지 않으면 그 다음 condition 호출 전에 campaign을 정지하고 원인을 조사한다.

1. 세 condition의 `runtime_context_hash`가 동일하다.
2. blind RAG와 placebo의 추가 block 문자·byte 길이가 일치하고 proxy-token 차이가 ±1% 이내다.
3. section insertion index와 common prompt hash가 동일하다.
4. 실제 응답 model이 모든 호출에서 정확히 `gpt-5.6-terra`다.
5. session ID가 비어 있지 않고 호출 간 중복되지 않는다.
6. tool/MCP/remote event가 0건이며 custom instruction이 적용되지 않았다.
7. retrieval provenance에 ground-truth 기반 query 또는 condition별 runtime 재수집이 없다.

위 gate 실패 row를 제외하고 분석을 계속하지 않는다. 이는 모델 실패가 아니라 처치 실패이며 accuracy 효과를 추정할 수 없는 중단 사유다.

## 4. Masking과 leakage scanner 0건 gate

### 4.1 금지 정보 사전

ground truth와 injection catalog에서 campaign 전에 fault별 forbidden lexicon을 만든다.

- `F1`~`F12` 같은 fault ID와 대소문자·구두점·띄어쓰기 변형
- canonical fault label과 알려진 alias·약어
- source path, basename, heading, slug에 포함된 진단명
- 주입 대상의 고유 workload/pod/node/container/entity 이름
- injection annotation, experiment marker, commit message, injection command
- 답을 직접 복원시키는 고유 error string, manifest field/value, expected recovery 문구

masker는 source 선택 뒤 filename·metadata를 제거하고 procedure text를 문장/field 단위로 변환한다. 단순 문자열 치환으로 문법적 빈칸을 남기지 않고, 제거된 span 수와 transform version을 provenance에 기록한다. 중립 문서 ID는 fault와 무관한 salted hash로 만들고 salt/hash는 campaign 전에 고정한다.

### 4.2 scanner

scanner는 최종 generator 입력 직전에 다음 두 단계로 실행한다.

1. Unicode NFKC, lowercase, whitespace·punctuation folding 후 exact/substring/regex alias scan
2. source metadata·entity·command·field/value와의 token n-gram overlap scan

검사 scope는 provenance source별로 구분한다. target workload/entity가 kubectl·log에 자연스럽게 나타나는 것은 정당한 runtime evidence이므로 제거하지 않는다. 다만 그 entity가 RAG/placebo metadata에서 유입되면 금지하며, injection annotation·fault ID·experiment marker처럼 운영 관측이 아닌 harness-only 단서는 공통 runtime block에서도 금지한다.

출력에는 `scanner_version`, `lexicon_hash`, 검사 대상 context hash, category별 match count와 span을 남긴다. raw provenance에는 원문을 보존하되 generator에게는 노출하지 않는다.

### 4.3 hard gate

- `blind_procedural_rag`: forbidden match **0건**
- `length_placebo`: forbidden match **0건**
- 공통 runtime context: injection marker·실험 label 같은 harness leakage **0건**

한 건이라도 검출되면 LLM을 호출하지 않고 fail-closed한다. 마스킹 수정 후에는 dry-run부터 다시 시작한다. lexical scanner 0건은 semantic leakage 부재의 증명이 아니다. 구현 전 전체 procedure corpus를 fault mapping을 가린 중립 ID로 제시하고 `label exposed / entity exposed / unique mechanism cue / generic procedure` 4축 rubric으로 사람 검토한다. `unique mechanism cue`가 남은 문서는 제외하거나 사전 플래그를 남겨 sensitivity 분석한다. V2.3이 측정하는 구성개념은 causal reasoning 자체가 아니라 **label·entity 제거 후 retrieved procedure의 잔여 진단 효용**이다.

## 5. 반복, 출력, provenance

### 5.1 `k=3` generation과 `m=3` judge

- generator: condition당 독립 session 3회; 진단 label 다수결, 3-way split은 사전 호출 순서의 첫 label로 결정하고 split을 별도 표시
- judge: 생성 응답마다 독립 session 3회; arm/source/model/vendor 표식을 제거한 reference-guided rubric, score 중앙값
- row representative score: 다수 label 생성 응답들의 judge-median score 중앙값
- primary threshold: 0.5; 0.6·0.7은 robustness only
- 보존 지표: generation agreement, judge unanimous/split rate, raw judge votes, nominal/ordinal Krippendorff α

Copilot CLI는 temperature와 seed를 지원하지 않는다. 따라서 V2.2의 `temperature=0.7`, judge `temperature=0`, seed 고정은 재현하지 못하며, 반복은 sampling hyperparameter 통제가 아닌 **관찰된 서비스 비결정성을 표본화하는 절차**다. 같은 prompt 재실행이 독립·동일분포라는 강한 가정도 하지 않는다.

### 5.2 호출별 필수 provenance

generator와 judge의 모든 호출에 다음을 별도 call ledger로 남긴다.

- experiment/campaign/fault/trial/condition, role(generator|judge), generation repeat, judge repeat
- requested model과 actual model, provider, Copilot CLI executable path와 version
- session ID, 시작·종료 timestamp, latency, exit code
- output text hash, actual output tokens, 해당 호출 AIC, 누적 AIC
- system prompt hash, user prompt hash, runtime/additional/full context hash
- requested approximate output limit(generator 2048, judge 512)과 실제 output tokens
- 차단 flag set/hash, 임시 cwd 식별자, tool/MCP/remote event count
- 문자·byte·proxy-token 수; **input token은 `unsupported/not_reported`로 명시**

Copilot의 output-token limit도 API hard cap이 아니라 prompt의 approximate 지시다. 실제 `output_tokens`를 정본으로 기록하고 조건별 분포를 비교한다. model mismatch, session ID 결측, usage/AIC 파싱 실패, tool event는 fail-closed한다.

## 6. 표본수와 통계 계획

### 6.4 실행 중 고정 schedule amendment — F7-t5 제외 (2026-08-28)

F7-t5(`currencyservice`, CPU 5m)는 120초 관찰 창에서 target pod가 Ready가 되지 않아
`CPUThrottle`의 사전 등록 latency phenotype 대신 rollout/startup failure를 만들었다. 이는
동일한 5m 처치에서 이미 기록된 ISS-003의 재발이며, unready를 CPU throttling 성공으로
재분류하면 구성 타당성을 훼손한다. 따라서 원시 `ground_truth.csv`는 불변으로 보존하고,
새 main campaign에서는 F7-t5를 명시적으로 제외한다.

- live estimand: 59 paired incidents × 3 conditions = **177 rows**, 2,124 logical calls
- F7 fault-cluster 평균은 유효한 4 trials만으로 계산한다. 전체 효과는 fault-cluster를 동일 가중한다.
- 분석 CLI는 `--main-schedule`일 때만 이 정확한 제외 집합을 수용한다. 누락 177행을 일반 180행 결과처럼 해석하지 않는다.
- 이미 중단된 Primary45 및 이전 incomplete artifact는 모두 primary estimand에서 제외한다.
- F7-t5는 별도의 injector 설계와 승인된 ground truth amendment 없이는 재도입하지 않는다.

### 6.1 표본과 호출 예산

| 단위 | 수 |
|---|---:|
| faults | 12 (F1–F12) |
| trials per fault | 5 |
| paired incidents | 60 |
| conditions per incident | 3 |
| 결과 rows/raw records | 180 |
| generator calls | 12×5×3×3 = 540 |
| judge calls | 540×3 = 1,620 |
| 본실험 Copilot calls | 2,160 |

파일럿은 별도 namespace/output에 최대-context stress incident 1건 × 3 conditions × (`k=3` generation + 각 generation의 `m=3` judge)로 수행하므로 3 rows, 9 generator calls, 27 judge calls, 총 36 calls다. 파일럿 row는 primary dataset 180행에 포함하지 않는다.

Terra의 effect size·intra-fault correlation 사전값이 없으므로 V2.2에서 formal power를 전용하지 않는다. `k`와 `m`은 측정 노이즈를 줄이지만 독립 표본수를 늘리지 않는다. 따라서 V2.3은 추정 중심이며, 12 fault cluster에서 +10%p의 유의성을 보장하는 실험이라고 주장하지 않는다.

### 6.2 1차 분석

1. 60개 incident의 paired difference로 `Δ_primary`와 %p를 계산한다.
2. fault 12개를 cluster 단위로 resample하는 bootstrap 95% CI를 주 결과로 보고한다. pairing을 보존하며 trial 또는 180 arm-row를 독립 표본처럼 bootstrap하지 않는다.
3. fault별 다섯 trial의 condition label을 cluster 전체로 swap하는 exact cluster permutation test를 `2^12=4,096`개 배치 전체 열거로 수행한다.
4. bootstrap은 fault cluster 50,000회 percentile 95% CI, 분석 seed `20260809`로 사전 고정한다. 다른 bootstrap 방식을 결과를 본 뒤 선택하지 않는다.
5. 보조 모델은 binomial mixed-effects model `correct ~ context_condition + (1|fault) + (1|fault:trial)`로 두되, dry-run 전에 패키지·버전·수렴 기준을 고정할 수 있을 때만 실행한다. 수렴 실패 시 다른 모델로 교체하지 않고 미실행을 보고한다.
6. incident-level McNemar exact와 fault-level majority paired 분석은 보조로만 보고한다.

### 6.3 사전 지정 보조·민감도 분석

- `blind_procedural_rag − runtime`, `length_placebo − runtime`
- threshold 0.6·0.7에서 같은 paired effect와 방향
- continuous representative score의 paired 차이
- fault별 forest와 fault group별 효과: 탐색적이며 다중성 보정 없이 가설 생성용
- generation/judge reliability, AIC·latency·output-token 차이
- low-quality/attrition 포함·완전사례 sensitivity; 결측을 조용히 삭제하지 않음
- F4-t3는 SSH가 응답할 때 exact live stress identity와 `Ready!=True` 또는 host
  `MemAvailable<=2 GiB`를 treatment-integrity gate로 사용한다. 단, exact
  `Ready!=True`와 인식 가능한 SSH-unreachable이 동시에 관측될 때만 durable
  sealed launch receipt를 live 재검증의 대체 근거로 허용하고, 이 branch의
  live-identity와 memory-observation flag는 반드시 false로 기록한다. low-memory
  branch는 NotReady 자체가 아니라 extreme-memory-pressure precursor이므로 전체
  60건 paired primary와 별도로 F4-t3를 제외한 59건 paired sensitivity를 반드시 보고한다.
- F4-t4는 `/tmp`가 tmpfs인 현재 worker 형상에서 kubelet nodefs와 무관한 파일을
  만들지 않는다. `/var/tmp`와 `/var/lib/kubelet`의 exact device를 preflight에서
  결합한다. preflight는 read-only이며 cryptographic nonce와 nodefs prestate를
  exact Node UID·Ready=True·DiskPressure=False baseline과 함께 local event
  journal에 먼저 fsync한다. 그 뒤에만 nonce-bound mode-0700
  experiment-owned directory와 intent receipt를 원격에 생성·fsync한다. nodefs
  capacity의 9% available을 목표로 하되 poststate는 8% 이상
  10% 미만이어야 한다. file device·work/file inode·size·allocated blocks와
  nodefs capacity·pre/post available을 atomic post receipt와 live validator에
  교차결합하며 allocated blocks가 requested bytes를 실제로 뒷받침해야 한다.
  root-owned mode-0700 nonce directory의 live 검증에만 quoted `sudo sh -c` read-only
  probe를 사용하고, 모든 exact identity·filesystem test를 marker 전에 fail-close한다.
  recovery는 파일 부재만으로 성공하지 않고 동일 nodefs의 available이 10% 이상
  회복됐는지 확인하고 current Node가 아직 NotReady/DiskPressure일 때만 kubelet을
  정확히 1회 재시작한다. active marker 뒤에는 재시작을 반복하지 않고 2초 간격
  최대 15회의 same-UID `Ready=True`·`DiskPressure=False` condition poll만 수행하며,
  끝까지 stale이면 recovery를 실패시킨다. atomic
  post receipt와 live file identity가 유효한 상태에서 `DiskPressure=True` 또는
  `Ready!=True`가 관측되면 GC 이후 available 반등과 무관하게 직접 endpoint로
  기록한다. validation event에는 injection 당시 post threshold/allocation/nonce·
  inode identity와 validation 시점 live threshold를 분리해 영속화한다.
  condition이 관측되지 않고 live threshold만 직접
  입증된 branch는 `node_disrupted=false`, `disk_pressure_observed=false`,
  `treatment_basis=nodefs-available-threshold` precursor로 기록한다. 전체 60건
  primary와 별도로 F4-t4 제외 59건 및 F4-t3/t4 동시 제외 58건 paired
  sensitivity를 반드시 보고한다.
- condition·fault·retrieval source를 가린 primary human reviewer의 180 representative output 전수 채점
- 독립 second reviewer의 사전 층화 무작위 36건 채점과 agreement·Krippendorff α 또는 Cohen κ. second reviewer가 없으면 primary reviewer의 delayed repeat 36건을 차선으로 쓰고 독립성 한계를 명시

결과를 본 뒤 threshold, fault subset, trial subset을 1차 분석으로 승격하지 않는다.

## 7. 동일 campaign과 복구 gate

### 7.1 campaign 불변 조건

본실험 시작 후 종료까지 다음을 고정한다.

- 단일 git commit과 clean experiment code snapshot
- 동일 cluster, Online Boutique 배포, collector와 corpus snapshot
- 동일 Copilot CLI/version·Terra model·prompt·rubric
- F1–F12의 사전 고정 순서와 trial schedule
- 단일 background process와 연속 campaign ID

캠페인 도중 code/prompt/corpus/cluster 구성 또는 Copilot 정책이 바뀌면 기존 row와 이어 붙이지 않는다. 중단 전 데이터는 operational attrition으로 보존하고, 수정 후 재실험은 새 campaign/version과 사용자 승인을 요구한다.

### 7.2 incident 절차

```text
recovery gate GREEN
  → fault 1회 주입
  → injection validator PASS
  → collection window 1회
  → runtime evidence freeze + hash
  → scanner/treatment-integrity precheck
  → counterbalanced order로 3 conditions 실행
  → raw/call ledger fsync
  → fault 복구
  → cooldown
  → recovery gate GREEN 확인 후 다음 trial
```

### 7.3 GREEN 조건

- 6개 node `Ready`, pressure condition 없음
- `boutique` workload가 사전 정의 replica/Ready 상태
- injection object·patch·traffic control·network policy·node mutation 잔류 0건
- Prometheus·Loki와 K8s API health 정상, 수집 window query 성공
- Flux/ArgoCD가 환경 오염을 만들지 않는 정상 상태; GitOps 정보는 모델 context에 넣지 않음. live patch fault가 reconcile로 소실되는 것을 막기 위해 상위 `flux-system`과 관리 child Kustomization을 root→child 순서로 incident 동안 일시 suspend하고, 두 객체의 원래 field 존재 여부·값을 durable hierarchy receipt로 봉인해 recovery 후 child→root 순서로 정확히 복원한다. 기본 child는 `app`이고, local-path provisioner를 직접 scale하는 F5-t3만 sibling `infrastructure` child를 사용한다. child identity가 sealed receipt와 일치하지 않으면 fail-closed한다.
- recovery manifest path와 대상 revision/hash가 계획값과 일치
- 이전 trial marker와 low-quality signal 0건

복구 gate가 실패하면 다음 fault를 주입하지 않는다. 같은 원인의 복구 실패가 3회 반복되면 campaign을 중단하고 `lab-restore` 후 상태를 보고한다. 다른 날짜나 복구 이력의 sub-campaign 결과를 primary dataset에 합치지 않는다.

## 8. 단계별 절차와 승인 gate

### 8.1 Step 1 — 현재 단계

- 이 계획서를 사용자에게 제시한다.
- 사용자가 설계를 명시 승인하기 전에는 구현·dry-run·클러스터 접근·Copilot 호출을 하지 않는다.

### 8.2 Step 2 — 방법론 비평

- 최근 survey/paper note 통합 prerequisite를 먼저 확인한다.
- 구성·내적·외적·통계 타당성·대안가설 5축으로 `docs/plans/review_v2_3.md`를 작성한다.
- 특히 mask 사전, semantic leakage, same-model judge bias, 12 fault cluster의 검정력, AIC rule을 독립 비평한다.
- 비평 반영본에 대한 사용자 승인을 다시 받은 뒤에만 Step 3으로 간다.

### 8.3 Step 3 — 구현과 dry-run 계획

구현 단계의 예상 범위는 `experiments/v2_3/` 격리 모듈, blind retriever/masker/scanner, 3-condition assembler, Terra generation/judge 반복, call ledger, 분석 스크립트다. 기존 `results/*.csv`, `results/raw_v*/*.json`, `results/ground_truth.csv`는 수정·삭제하지 않는다.

| 변경 전 | 계획된 변경 후 | 예상 소유 경로 |
|---|---|---|
| V2.2 5-arm GitOps/RAG/full/placebo assembler | 단일 `context_condition`의 3-condition assembler | `experiments/v2_3/` |
| 파일명·제목·진단명이 남은 retrieved runbook | procedure-only transform + forbidden lexicon + fail-closed scanner | `experiments/v2_3/` |
| OpenAI 중심 k/m metadata | Copilot Terra call별 session/model/output-token/AIC ledger | `experiments/v2_3/`, shared adapter |
| campaign 분할을 사후 발견 | pre-injection GREEN, post-trial recovery, campaign ID hard gate | `experiments/v2_3/` |

정확한 파일·함수·line 변경은 Step 2 비평 후 writing-plan에서 확정한다. 이 표는 구현 지시가 아니라 설계상 필요한 책임 경계다.

dry-run은 실제 fault나 유료 Copilot 호출 없이 다음을 검증해야 한다.

1. 3 conditions × k=3 × m=3 loop와 aggregation
2. 180-row/2,160-call 예상 schema 및 pilot output 격리
3. runtime hash 동일성, 길이 매칭, 위치 고정, order schedule
4. forbidden positive fixture 검출과 clean fixture 0건
5. judge blinding과 provenance completeness
6. 기존 결과 경로 overwrite 거부
7. model drift·session/AIC 결측·tool event fail-closed

### 8.4 Step 4a — 1 fault × 1 trial 파일럿

dry-run과 코드 리뷰를 통과한 뒤, 라이브 fault injection에 대한 별도 사용자 승인을 받고 1 incident 유료 파일럿을 수행한다. 최초 선택한 historical 최대-context proxy F7 trial 5(약 16.6k characters)는 실제 5m rollout에서 새 currencyservice pod가 Ready가 되지 않아 CPU-throttle과 rollout failure가 교락됐고 Copilot 호출 전 무효화했다. 2026-08-09 사용자 승인에 따라 pilot-only target을 ground truth상 10m인 F7 trial 1(`frontend`, historical 최대 약 12.9k characters)로 변경한다. 이는 primary dataset의 fault/trial 구성 변경이 아니라 live harness·AIC 검증용 pilot 변경이다. 비용 투영에는 t5/t1 context ratio 약 1.29를 기존 15% margin과 함께 적용한다. F1 기능 smoke는 mock으로만 수행한다. 파일럿은 다음을 동시에 확인한다.

- injection/collection/recovery GREEN
- Flux app suspend/restore receipt 완전성과 F7 처치 전 구간 유지
- three-condition runtime hash와 length match
- leakage scanner 0건
- Terra JSON schema, k/m aggregation, session uniqueness
- model/output-token/AIC provenance 36/36 calls 완전성
- 실제 AIC와 latency로 전체 campaign 비용 추정

파일럿 후 prompt/masker/길이/collector를 수정하면 파일럿을 폐기하고 dry-run부터 다시 승인받는다.

Flux 일시 suspend는 세 condition 모두에 공통으로 적용되므로 RAG 독립변수 차이를 만들지는 않지만, active reconciliation이 동작하는 production 환경으로의 외적 타당성을 제한한다. 기본적으로 `app`, F5-t3에서는 `infrastructure` child까지 일시 정지한 “reconciliation이 정지된 통제 incident”로 결과를 명시하며 GitOps 효과에 관한 근거로 사용하지 않는다.

### 8.5 AIC budget stop rule

#### Zero-overage 외부 gate

GitHub의 조직용 usage-based billing은 included pool 소진 후 paid usage가 기본 활성화될 수 있다. 따라서 잔여 AIC가 보인다는 사실만으로 별도 과금 0을 보장하지 않는다([organization billing](https://docs.github.com/en/copilot/concepts/billing/usage-based-billing-for-organizations-and-enterprises), [budget controls](https://docs.github.com/en/copilot/concepts/billing/budgets-for-usage-based-billing)). 첫 유료 호출 전에 다음을 모두 증빙한다.

1. 조직/엔터프라이즈 관리자가 `AI credits paid usage = Disabled`를 확인한다.
2. 적용되는 budget에 `Stop usage when budget limit is reached = Enabled`를 확인한다.
3. 증빙 일시·적용 account/org와 확인 방법을 campaign manifest에 남긴다. 비밀값이나 관리자 화면 전체는 저장하지 않는다.
4. 위 확인 뒤에만 로컬 실행 gate `THESIS_COPILOT_ZERO_OVERAGE_CONFIRMED=1`을 설정한다.
5. Copilot CLI 1.0.78이 허용하는 최소 세션 상한인 `--max-ai-credits 30`을 적용한다. 이는 예상 단일-call 사용량이 아니라 runaway 방지용 보조장치이며 paid-usage 비활성화를 대체하지 않는다. adapter는 각 subprocess 전에 `누적 AIC + 30 <= 360`을 검사해 세션 최악 상한을 예약하므로 campaign 360 AIC를 사후 초과하지 않는다.
6. 공식 SDK의 model-free `account.getQuota`에서 현재 계정의 `premium_interactions`를 확인한다. `usageAllowedWithExhaustedQuota=false`, `overageAllowedWithExhaustedQuota=false`, overage와 overage entitlement 0, active token-based quota, `remaining >= campaign max + session max`를 K8s import 전과 각 Copilot subprocess 전에 모두 만족해야 한다.

2026-08-12 사용자 결정으로 현재 실행에는 상호 배타적인 `paid-overage-user-authorized` 모드를 적용한다. 2026-08-16 본실험 경로는 비결정적인 SDK quota 조회를 제거하고, SDK `useLoggedInUser`가 사용하는 active GitHub login을 campaign 시작 시 검증한다. manifest는 server quota 미조회 사유를 명시한다. 30 AIC session limit, Terra/model/tool/skill isolation, durable charge journal과 실패 후 중단은 그대로 유지한다. 위 6항은 legacy zero-overage 경로에만 적용한다.

2026-08-12 후속 사용자 결정으로 본실험은 campaign AIC 상한을 중단 조건으로 사용하지 않는다. 본실험 manifest의 `max_campaign_aic`는 `null`로 기록하며, 매 subprocess의 Copilot CLI 30 AIC 상한, 실제 AIC durable receipt, account/Business seat/model/session/tool isolation, 실패 후 campaign 중단은 유지한다. 이 결정은 비용 제약만 해제하며 60 incident·2,160 call의 사전 지정 표본이나 안전·유효성 gate를 축소하지 않는다. 파일럿 이후 본실험용 cluster-resource collector가 추가되므로 변경된 clean commit에서 F7 t1 36-call 파일럿을 다시 수행해 context·AIC·recovery를 확인한 후 본실험을 시작한다.

어느 하나라도 확인되지 않으면 mock/dry-run만 허용하고 Copilot inference는 adapter 수준에서 subprocess 실행 전에 차단한다.

deep-analysis 작성 시점의 보고 잔여량은 28,850 AIC다. 파일럿 직전에 실제 계정 잔여량 `B0`를 다시 기록하고 이 값이 다르면 실제값을 사용한다. 파일럿 36 calls의 AIC 합을 `P`, 파일럿 후 잔여량을 `B1`, generator/judge 각 역할의 파일럿 최대 단일-call AIC를 `Gmax`, `Jmax`라 한다.

```text
scaled_pilot   = P × 60 × 1.15 × 1.29
role_upper     = (540 × Gmax + 1,620 × Jmax) × 1.15 × 1.29
projected_main = ceil(max(scaled_pilot, role_upper))
reserve        = ceil(B0 × 0.10)
진행 조건      = usage metadata 36/36 완전
                 AND B1 - projected_main >= reserve
                 AND projected_main <= 28,850
```

`×60`은 1 incident 파일럿과 같은 60개 본실험 incident, `×1.15`는 output 길이·과금 변동을 위한 15% 보수 계수, `×1.29`는 F7 t1과 historical maximum F7 t5의 context 차이를 보정하는 계수다. 평균비용 외에 역할별 최대 단가 상한도 적용한다. 다음 중 하나면 **본실험을 시작하지 않는다**.

- AIC/session/output-token metadata 누락 또는 계정 잔여량 불일치
- 예측 비용이 진행 조건을 넘음
- 단일 호출 AIC가 파일럿 안에서 비정상적으로 급증하거나 역할별 비용을 설명할 수 없음
- 예산을 맞추기 위해 결과를 본 뒤 `k`, `m`, fault, trial을 임의 축소해야 함

예산 부족 시 scope 축소안은 새 설계·통계 계획으로 사용자 승인을 다시 받는다. 자동 재시도는 예산에 포함하지 않으며, 재실행도 별도 승인 대상이다.

### 8.6 예상 소요 시간

Copilot CLI와 cluster 상태의 최신 실측이 없으므로 설계 단계에서 고정 시간을 만들지 않는다. 파일럿에서 36 calls의 실제 wall time `T_pilot`, condition별 p50/p95 latency, injection·collection·recovery 시간을 측정한 뒤 다음처럼 보고한다.

```text
serial inference upper estimate = T_pilot × 60
cluster operation estimate      = 60 × (injection + collection + recovery + cooldown)
total estimate                  = 두 항 + preflight/restore + 15% contingency
```

본실험 승인 요청에는 이 시간 추정, `projected_main` AIC, 예상 종료 시각을 함께 제시한다. 비용·시간을 줄이기 위한 병렬화는 session 격리와 rate limit을 dry-run/파일럿에서 검증한 경우에만 허용하며, fault injection·collection·recovery 자체는 직렬로 유지한다.

### 8.7 Step 4b — 본실험과 background 운용

파일럿과 budget gate를 통과하고 사용자 본실험 승인을 받은 뒤에만 수행한다.

1. `$lab-tunnel`로 기존 tunnel health를 먼저 확인하고 정상이면 재사용한다.
2. K8s API·Prometheus·Loki·cluster/output-path preflight와 빈 V2.3 결과 경로를 확인한다.
3. 단일 background process로 시작해 PID, log path, results path, campaign ID를 즉시 보고한다.
4. `$experiment-status`로 PID, fault/trial/condition, row/raw/call counts, AIC 누계, 오류 의미를 주기적으로 보고한다.
5. 중단 조건이 없을 때 F1–F12 × 5 trials를 같은 campaign에서 끝낸다.

실제 CLI 명령은 Step 3 구현 후 `--help`와 dry-run으로 검증해 review 문서에 고정한다. 존재하지 않는 `experiments/v2_3` 명령을 이 설계 단계에서 실행 가능한 것처럼 제시하지 않는다.

현재 구현된 본실험 entrypoint는 `python -m experiments.v2_3.run --main --allow-paid-overage --approval-id <id> --campaign-id <id> --chroma-dir <path>`이며, 결과는 기존 불변 `results/`가 아니라 `artifacts/v2_3_main/<campaign-id>/`에 incident별 원자 커밋된다. 본실험은 새 디렉터리만 허용하고 중복 campaign을 거부한다.

### 8.8 복원과 완료 검증

성공·중단과 무관하게 `$lab-restore`를 수행하고 node/workload/GitOps/monitoring/disk 상태를 확인한다. 완료 주장은 실제 명령으로 다음을 검증한 뒤에만 한다.

- primary CSV: 정확히 180 data rows, `(fault,trial,condition)` 중복·결측 0
- raw primary JSON: 180개, CSV와 1:1
- call ledger: 본실험 2,160개 성공 call record와 role/repeat mapping
- pilot: 별도 3 rows/36 calls, primary 결과와 혼합 0
- F1–F12 각 5 trial·3 condition 완결
- scanner forbidden match 총 0건, treatment-integrity 위반 0건
- actual model mismatch 0건, session 결측·중복 0건, tool/MCP/remote event 0건
- provenance의 output-token/AIC 합이 Copilot usage와 일치
- 로그의 SKIP·traceback·recovery failure·미설명 재시도 0건
- restore 후 cluster GREEN

Step 5 분석은 대화 성공 기대를 전달받지 않은 fresh `results_critic`이 수행한다.

## 9. 성공, 판정, 중단 기준

### 9.1 실험 유효성 성공

다음을 모두 충족해야 결과 해석 단계로 간다.

1. 60/60 paired incidents와 180/180 rows 완결
2. leakage scanner 0건 및 treatment-integrity 위반 0건
3. 단일 campaign·복구 gate 위반 0건
4. k=3/m=3와 provenance 완결, model drift 0건
5. 파일럿·AIC budget·restore gate 통과

### 9.2 가설 판정

- **강한 지지:** `Δ_primary ≥ +10%p`, fault-cluster bootstrap 95% CI 하한 `>0`, threshold 0.5/0.6/0.7에서 모두 방향이 양수이며 180건 human-primary 재채점에서도 효과 방향이 양수
- **방향 지지이나 불확실:** 점추정 `>0`이나 +10%p 미만 또는 CI가 0 포함. 성공으로 과장하지 않고 추가 표본 가설로 분류
- **기각/반대:** `Δ_primary ≤0` 또는 threshold에서 방향이 일관되지 않음
- **판정 불가:** leakage/treatment/campaign/recovery/provenance gate 위반. accuracy가 높아도 RAG 효과로 해석 금지

`runtime` 대비 비교와 fault별 차이는 2차 결과다. V2.3 절대 정확도가 V2.2보다 높거나 낮은 것은 성공·실패 기준이 아니다.

### 9.3 즉시 중단

- scanner match 1건 이상 또는 ground-truth 기반 retrieval 확인
- requested/actual model 불일치, tool/MCP/remote/custom-instruction 개입
- 같은 incident의 runtime hash·collection window 불일치
- recovery gate 실패 후 다음 injection 위험
- 다른 campaign으로 이어 붙여야 하는 장시간 중단이나 cluster/config 변경
- AIC stop rule 위반 또는 usage provenance 결손
- zero-overage 외부 gate 미확인 또는 paid usage 정책 변경
- 원본 결과/ground truth overwrite 위험
- 같은 infra·recovery·Copilot 오류 3회 반복

### 9.4 가설이 지지되지 않을 때의 대안

- blind RAG≈placebo이면 절차 지식의 잔여 기여가 이 설정에서 검출되지 않았다고 판정하고, 같은 결과에서 prompt나 corpus를 사후 조정하지 않는다.
- CI가 넓으면 `k/m`을 독립 표본처럼 늘리지 않고 fault/trial 증량의 새 검정력 계획을 만든다.
- Terra judge 불일치가 크면 독립 모델 judge 또는 확대 human audit을 **후속 실험의 새 측정 설계**로 제안한다.
- semantic leakage가 발견되면 해당 결과는 판정 불가로 두고 corpus/mask taxonomy를 다시 설계한다.
- GitOps나 context-position을 실패 구제용으로 같은 라운드에 추가하지 않는다.

## 10. 주장 경계와 알려진 한계

1. **버전 간 절대 비교 금지:** V2.2는 `gpt-4o-mini`, V2.3은 Terra이므로 정확도·비용·분산을 모델 개선처럼 비교하지 않는다.
2. **RAG 총효과 아님:** full/self-runbook과 cross-fault arm이 없으므로 V2.3은 blind procedure 대 matched placebo의 잔여 기여만 추정한다.
3. **누출 0의 한계:** scanner 0건은 정의된 lexical/entity leakage 0건이지 semantic shortcut 부재의 증명이 아니다.
4. **추론 증명의 한계:** blind procedure가 유리해도 절차가 정답 후보를 강하게 좁힌 효과일 수 있으며 causal reasoning 자체를 증명하지 않는다.
5. **same-model judge:** generator와 judge가 모두 Terra이므로 correlated error와 self-evaluation bias가 남는다. blinding·m=3·human audit은 완화이지 제거가 아니다.
6. **재현성 한계:** Copilot CLI는 temperature·seed·input-token count를 제공하지 않고 output limit도 advisory다. session/model/output-token/AIC provenance로 관찰 가능성을 높일 뿐 동일 출력을 보장하지 않는다.
7. **통계 한계:** 12 fault cluster·5 trials는 작은 표본이다. 2,160 LLM call을 독립 표본으로 세거나 비유의를 효과 없음으로 표현하지 않는다.
8. **외적 타당성:** 단일 KT Cloud 6-node K8s cluster, Online Boutique, fault taxonomy F1–F12, 단일 corpus/masker, 단일 Terra 서비스 시점에 한정한다. production readiness·일반 MTTR 개선으로 확대하지 않는다.
9. **GitOps·position 주장 금지:** 두 변수는 이번 실험에서 조작하지 않으므로 효과·무효를 말하지 않는다.
10. **운영 attrition 분리:** injection, collection, recovery, generation, judge, scored-case 성공률을 따로 보고하고 실패 case를 common subset에서 조용히 제거하지 않는다.

## 11. 예상 산출물과 다음 checkpoint

| 단계 | 산출물 |
|---|---|
| Step 1 | `docs/plans/experiment_plan_v2_3.md` (이 문서) |
| Step 2 | `docs/plans/review_v2_3.md` |
| Step 3 | `experiments/v2_3/`, `results/experiment_changes_v2_3.md`, dry-run evidence |
| Step 4 | `results/experiment_results_v2_3.csv`, `results/raw_v2_3/`, call ledger, logs |
| Step 5 | `results/analysis_v2_3.md` |
| Step 6 | `docs/plans/next_experiment_goal_v2_4.md`, 새 session prompt, TickTick handoff |

**다음 checkpoint:** clean feature-branch SHA에서 클러스터 preflight를 통과한 뒤 `paid-overage-user-authorized` F7 trial 1 최대-context 36-call 파일럿을 실행하고, 결과·호출 ledger·recovery GREEN을 검증한다.

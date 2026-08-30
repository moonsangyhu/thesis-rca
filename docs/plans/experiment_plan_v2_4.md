# 실험 계획서 V2.4 — Primary03 무호출 retrospective measurement audit

> 작성: 2026-08-30 · Experiment Track Step 1 설계 초안
>
> 입력 정본: `docs/surveys/deep_analysis_v2_4.md`, `results/analysis_v2_3.md`,
> `docs/plans/next_experiment_goal_v2_4.md`, `docs/plans/experiment_plan_v2_3.md`,
> `docs/plans/review_v2_3.md`, `docs/surveys/paper_survey_v1.md`
>
> 상태: **Step 2 P0 반영본 단일 승인 대기 — 구현·package 생성·사람 채점·분석 금지**
>
> 데이터 경계: `Primary03` 하나의 보존 artifact만 사용하며, 새 LLM/API/Codex/Copilot
> 호출과 K8s 접근·mutation·fault injection은 모두 0이다.

## 0. 결론과 hard gate

V2.4는 RAG 효과를 다시 검정하는 실험이 아니다. V2.3 `Primary03`의 보존된 자동 outcome이
condition/Terra-blind 사람이 frozen synthetic ground-truth rubric으로 판정한 결과와 얼마나
일치하는지, 그리고 blind procedural RAG block이 semantic shortcut 자료로 부적격하지
않은지를 확인하는 **retrospective measurement audit**다. V2.3은 incomplete, non-random
prefix이므로 어떤 audit 결과도 이를 confirmatory dataset으로 승격하지 못한다.

이 audit에는 실험자가 조작하는 독립변수가 없다. 같은 archived output에 두 측정법을
paired 적용하며, 단일 1차 estimand는 다음 하나뿐이다.

```text
조작 독립변수 = 없음(retrospective paired measurement audit)
primary estimand = P(
  archived Terra correct_at_0.5
  != condition/Terra-blind dual-human adjudicated score>=1
)
```

discordance의 `Terra-only`/`human-only` 방향은 보조 estimand이자 별도 alert다. context
condition은 고정 descriptive strata이고, L0~L3 semantic audit는 blind-RAG construct의
자료 적격성 gate다. 사람 score `=2` 기준은 사전 지정 sensitivity일 뿐 두 번째 가설이
아니다.

승인 흐름은 다음 하나로 고정한다.

```text
Step 1 plan 초안
→ Step 2 fresh 독립 review
→ review의 P0 amendment를 plan에 반영(현재 문서)
→ 최종 plan SHA-256 + review SHA-256 + 미해결 P1 목록을 approval bundle로 제시
→ 사용자 단일 명시 승인
→ Step 3 구현
```

최종 plan은 자신의 hash를 본문에 넣는 self-reference를 만들지 않는다. 대신 문서가
고정된 뒤 별도 read-only approval bundle에 두 file hash, review 판정, P1-1~P1-5의 반영
상태를 기록한다. 이 **단일 사용자 승인** 전에는 `experiments/v2_4/` 생성, 구현, dry-run,
Chroma open/copy, package 생성, reviewer 모집·배포·채점, 결과 분석, cluster/tunnel 접근을
모두 금지한다.

Review amendment 추적은 다음과 같다.

| review 항목 | 반영 위치 | 상태 |
|---|---|---|
| P0-1 조작 없음·primary magnitude 단일화 | §0, §2 | 반영 |
| P0-2 actual-n Wilson 정수 gate·cluster bootstrap | §11 | 반영 |
| P0-3 frozen-reference construct·blinding 범위 | §2, §6, §8, §18 | 반영 |
| P0-4 correctness close 후 semantic 배포 | §6, §10, §15 | 반영 |
| P0-5 Chroma quiescence·immutable byte spec | §3, §5, §15 | 반영 |
| P0-6 별도 scanner·canonical HMAC replay | §6, §7, §15 | 반영 |
| P0-7 network-none/K8s 실행 격리 | §15, §16 | 반영 |
| P0-8 사용자 단일 승인 | §0, §19 | 반영 |
| P1-1 108 generation identity 선봉인 | §6, §12 | 반영 |
| P1-2 제3 adjudicator | §10 | 선호안 반영; 실제 R3 확보 여부는 실행 dependency |
| P1-3 qualification·fatigue | §10, §17 | 반영 |
| P1-4 10/15/25% sensitivity | §11 | 반영 |
| P1-5 package/measurement 완료 분리 | §13 | 반영 |

## 1. 이전 결과와 이번 audit의 필요성

### 1.1 V2.3에서 보존된 사실

- 사전 계획은 F7-t5 제외 단일 campaign 59 incidents·177 rows·2,124 logical calls였다.
- 전체 49개 artifact directory에 `campaign_complete`는 0건이었다.
- `Primary03`은 F1~F8의 39 incidents·117 rows만 완료한 비무작위 prefix이며 F9에서
  중단됐다. 직전 Service exact-recovery 결손도 확인됐다.
- `Primary03`의 threshold 0.5 기준 runtime/placebo/blind RAG는 모두 23/39였다.
- blind RAG와 placebo의 paired discordance는 각 방향 2건씩이었다.
- generation agreement 평균은 0.598~0.607이고 generation split은 조건별 17~19/39였다.
- Terra 계열이 generation과 judge를 모두 수행했고 계획된 human-primary review 및
  semantic audit는 완료되지 않았다.

따라서 `23/39 동률`은 RAG 효과 없음의 증거가 아니다. 현재 답할 수 있는 질문은 자동
outcome과 frozen ground-truth rubric 기반 human concordance가 이 표본에서 얼마나
어긋나는지뿐이다.

### 1.2 최근 Research Track 근거

최근 survey와 V2.4 deep analysis가 요구하는 통제 원칙을 다음처럼 적용한다.

| 근거 | 보고된 관찰 | V2.4 반영 |
|---|---|---|
| Zheng et al., *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena* (2023), [원문](https://proceedings.neurips.cc/paper_files/paper/2023/hash/91f18a1287b398d378ef22505bf41832-Abstract-Datasets_and_Benchmarks.html) | GPT-4 position consistency 65.0%, 위치·장황성·자기선호 위험 | condition/score/source를 숨기고 reviewer별 item order를 다르게 고정 |
| Haldar & Hockenmaier, *Rating Roulette* (2025), [원문](https://aclanthology.org/2025.findings-emnlp.1361/) | 반복 judge의 Krippendorff alpha 0.265~0.788 | 자동 judge 단독 결론 금지, 두 사람의 원판정·agreement·CI 보존 |
| Kocyigit et al., *Overestimation in LLM Evaluation — Data Contamination's Impact* (2025), [원문](https://proceedings.mlr.press/v267/kocyigit25a.html) | source-target 결합 오염이 최대 30 BLEU inflation | answer key 물리 분리, lexical package scanner, semantic shortcut 별도 audit |
| Pei et al., *Flow-of-Action* (2025), [원문](https://arxiv.org/abs/2502.08224) | SOP knowledge 제거 시 54.06%→15.39% | 절차 지식은 유용할 수 있으나 self-runbook shortcut과 분리 |
| *Self-Preference Bias in LLM-as-a-Judge* (2024), [원문](https://arxiv.org/abs/2410.21819) | same-family judge의 self-preference 관찰 | Terra-generated output과 archived Terra judge의 상관오차를 사람 outcome으로 감사 |
| *Judging the Judges* (2025), [원문](https://aclanthology.org/2025.ijcnlp-long.18/) | 15 judges·22 tasks·약 40 generators·15만+ 평가에서 position bias가 judge/task/candidate별로 달라짐 | 두 reviewer에게 서로 다른 deterministic order 제공 |
| *SSA: Semantic Contamination* (2025), [원문](https://aclanthology.org/2025.emnlp-main.744/) | 3B 이상 `r>=.97`, 전체 `rho>=.9`의 contamination 민감도 | lexical match 0을 semantic leakage 0으로 간주하지 않고 L0~L3 audit 수행 |
| *Counting on Consensus* (2026), [원문](https://aclanthology.org/2026.lrec-1.347/) | task·불균형·missingness에 맞는 agreement metric과 CI 필요 | raw agreement, confusion, kappa, weighted kappa, abstain을 함께 보고 |

문헌의 절대 수치를 V2.4 예상 성능으로 전용하지 않는다. V2.4의 수치는 `Primary03`에만
해당한다.

## 2. 조작 없음과 단일 primary paired estimand

### 2.1 paired measurement 정의

조작 독립변수는 없다. `Terra`와 `human`은 같은 output에 적용된 paired measurement
method이며, primary construct는 현실의 절대 정답이 아니라 **frozen ground-truth rubric과
archived candidate 사이의 condition/Terra-blind human concordance**다.

- `T_i`: 보존된 `Primary03` row의 Terra `correct_at_0.5` (`0|1`)
- `H_i`: 두 사람의 독립 원판정 후 condition/Terra/provider/provenance는 보지 않되 frozen
  diagnostic reference는 본 adjudication score가 `1` 또는 `2`이면 1, `0`이면 0,
  `A`이면 missing
- `D_i = 1[T_i != H_i]`
- 1차 endpoint: 36 representative outputs에서 `sum(D_i)/n_non_abstain`

단일 **가설 A (H-V2.4)**는 discordance의 크기에만 관한 것이다.

> **H-V2.4:** archived Terra `correct_at_0.5`와 condition/Terra-blind,
> diagnostic-reference-visible dual-human adjudicated
> `score>=1` 사이의 discordance magnitude가 사전 지정 20% 운영 경계에 비추어
> `Primary03` 해석을 자동 outcome 하나에 맡기기 어려운 수준인가?

20%는 보편적인 judge-validity cutoff가 아니라 n=36 triage용 사전 운영 경계다. 실제
판정은 §11의 Wilson 정수 경계로 수행한다. 방향성은 `DIRECTIONAL_ALERT`로만 분리하고
Green/Gray/Red를 바꾸지 않는다. `H_i=1[score=2]`는 full-correctness sensitivity로 같은
confusion/CI를 계산하되 별도 가설이나 유리한 primary threshold로 승격하지 않는다.

### 2.2 금지되는 효과 추정

다음을 계산하거나 보고하지 않는다.

- RAG-placebo confirmatory effect, CI, p-value 또는 McNemar test
- 서로 다른 V2.3 campaign prefix 결합
- V2.2 절대값과의 성능 비교
- condition별 accuracy를 V2.3 처치 효과로 해석
- human agreement를 사람 판정의 절대 gold-standard 증명으로 표현

condition별 Terra-human disagreement 방향은 package lock 해제 뒤 descriptive strata로만
보고한다.

## 3. 불변 데이터 경계와 provenance

### 3.1 읽기 전용 입력 allowlist

승인 후 구현은 다음 세 입력만 읽는다.

1. `artifacts/v2_3_main/v2-3-codex-20260830-primary03/`
   - `experiment_results_v2_3.csv`
   - `raw_v2_3/*.json`
   - `campaign_manifest.json`, event/call ledger 중 provenance 검증에 필요한 파일
2. `results/ground_truth.csv`
3. `Primary03` manifest/provenance가 지정한 동결 Chroma snapshot과 collection
   `k8s-rca-knowledge`

현재 feature worktree에 ignored artifact가 없거나 외부 snapshot을 resolve하지 못하면
구현은 fail-closed한다. 다른 campaign이나 유사 파일을 대신 사용하지 않는다.

### 3.2 content 불변성과 Chroma quiescence

- 위 입력 파일·디렉터리의 content 수정, 삭제, rename, re-ingest 금지
- `results/*.csv`, `results/raw_v*/*.json`, `results/ground_truth.csv` 쓰기 금지
- Chroma source snapshot을 직접 open-write하거나 embedding/retrieval 재실행 금지
- 결과를 보고 sample, rubric, threshold, package order seed 변경 금지

구현은 regular file relative path, type, byte size, SHA-256을 정렬한 versioned
`input_manifest.json`을 만들고 이 canonical manifest의 SHA-256을 tree digest로 쓴다.
symlink, device, socket, FIFO, path traversal은 fail한다. 시작·복사 직후·종료 시 source
content digest를 비교하며 하나라도 다르면 `INVALID_INPUT_MUTATION`으로 중단하고 배포하지
않는다. atime/mtime/stat은 별도 audit field로 기록하되 content mutation 판정과 섞지
않는다.

Chroma/SQLite source에는 Chroma나 SQLite library를 열지 않고 raw filesystem read/copy만
수행한다. preflight는 required main SQLite DB와 index/data file inventory를 고정하고,
SQLite `-wal` 또는 `-shm`가 존재하거나 WAL size가 0이 아니거나 checkpoint/quiescence를
raw inventory만으로 입증할 수 없으면 `SNAPSHOT_NOT_QUIESCENT`로 fail-closed한다. source를
checkpoint하거나 복구하려 하지 않는다.

새 audit output 아래 working copy는 file content와 relative path를 byte-for-byte 복사한
뒤 source tree digest와 같아야 한다. working copy만 network/telemetry-off 경계에서
SQLite `mode=ro&immutable=1` 또는 동등한 OS read-only mount로 열 수 있다. open 전후
working tree digest가 같아야 하며 schema migration, journal/WAL 생성, metadata write,
telemetry 또는 network 시도는 hard fail이다. collection name `k8s-rca-knowledge`는 정확히
한 collection ID로 resolve되어야 한다.

## 4. outcome-blind deterministic sample — 사전 등록 완료

### 4.1 seed와 선택 알고리즘

seed material은 다음 immutable provenance를 정확히 연결한다.

```text
v2.4-measurement-audit-v1|campaign_id|schedule_hash|corpus_version
```

공개 SHA-256은 다음 값으로 고정한다.

```text
b6d27015ce04ec86b7296e3762b2a38eb98ba5b5e602ca6c357d7533f62fbbe8
```

구현은 `Primary03` manifest/raw에서 세 값을 읽어 위 digest와 일치하는지 먼저 검증한다.
선택에는 correctness, judge score/vote, output, condition, generation agreement/split을
사용하지 않는다.

1. 관측 F1~F8 각 fault에서 `SHA256(seed|primary|fault|trial)`이 최소인 incident를 하나
   선택한다.
2. 두 번째 incident를 받을 네 fault는
   `SHA256(seed|secondary-fault|fault)`가 작은 순서로 선택한다.
3. 해당 fault의 남은 trial 중
   `SHA256(seed|secondary-incident|fault|trial)`이 최소인 incident를 추가한다.
4. 각 incident의 세 condition과 archived representative output을 모두 포함한다.

### 4.2 고정된 12 incidents와 36 outputs

선택 결과는 다음과 같으며 이후 변경하지 않는다.

```text
F1-t2, F1-t3,
F2-t1,
F3-t3, F3-t4,
F4-t1,
F5-t2, F5-t3,
F6-t5,
F7-t1, F7-t3,
F8-t3
```

두 번째 sample strata는 F5, F7, F3, F1이다. 각 incident의 `runtime`,
`length_placebo`, `blind_procedural_rag` representative output 하나씩, 총 36개다.
representative output이 이미 Terra votes/majority로 선택됐다는 selection bias는 숨기지
않으며 §12의 108-output escalation으로만 감사한다. 이 목록은 구현·human rating 전에는
고정됐지만 연구자가 전체 V2.3 결과를 본 뒤 seed namespace와 알고리즘을 정했으므로
prospective random sample이라고 주장하지 않는다. 사전 기록은 이후 outcome-contingent
변경을 막는 audit trail이다.

## 5. byte-equivalent blind procedure reconstruction

새 retrieval, embedding, masking 판단을 수행하지 않는다. reconstruction spec은
`v2.4-byte-reconstruction-1`로 고정한다. 12개 선택 incident의 blind-RAG raw provenance로
당시 additional block을 다음 순서로 기계적으로 재구성한다.

1. `retrieval_provenance.candidates`를 rank 순서대로 읽는다.
2. working-copy의 exact collection ID에서 document ID=`source_id`, stored offset=
   `chunk_start:chunk_end`인 record를 찾는다. 0건 또는 2건 이상 match는 fail한다.
3. stored bytes를 UTF-8 strict로 decode한다. decode 전후 Unicode normalization, newline
   변환, replacement character 삽입을 하지 않는다.
4. 각 rank에서 `source_length`, `chunk_start`, `chunk_end`, `source_text_hash`를 검증한다.
   length/span은 V2.3과 같은 Python 3.11 `str` code-point index semantics를 쓴다.
5. 해당 rank의 `removed_spans`가 `{category,term,start,end,rank}` exact schema이고 범위가
   겹치지 않는지 확인한다.
6. span을 start 내림차순으로 적용해 원문을 ASCII byte sequence
   `5b52454441435445445d`인 `[REDACTED]`로 치환한다. 새 lexicon scan이나 의미 기반
   마스킹을 추가하지 않는다.
7. rank별 결과에 Python 3.11 `str.strip()`의 default Unicode-whitespace semantics를
   정확히 적용하고 ASCII LF 두 개(`0a0a`, `"\n\n"`)로 결합한다.
8. 결과를 UTF-8 strict로 encode하고 SHA-256이 raw `masked_procedure_hash`와 일치해야 한다.
9. 같은 byte sequence의 SHA-256이 row/raw `additional_context_hash`와 일치해야 한다.

12/12 block에 대해 source hash, masked hash, additional hash가 모두 일치해야 package를
만든다. 하나라도 다르면 `RECONSTRUCTION_MISMATCH`로 중단하며 가장 비슷한 text를 대신
사용하거나 현재 corpus에서 다시 검색하지 않는다. Step 0.5에서는 같은 방식으로 39/39
block, 모든 hash mismatch 0건을 확인했지만 구현은 12건을 독립 재검증해야 한다. source와
working tree의 before/after digest, WAL/SHM inventory, immutable-open evidence도 12/12 hash
결과와 함께 distribution 전 필수 evidence로 잠근다.

## 6. blinded package와 answer-key 분리

### 6.1 correctness package allowlist

36개 item 각각 reviewer에게 제공하는 필드는 다음 exact allowlist다.

| 필드 | 출처/의미 |
|---|---|
| `case_id` | private master salt의 HMAC으로 만든 opaque ID |
| `expected_target_service` | ground truth `target_service` 원문 |
| `expected_root_cause` | ground truth `expected_root_cause` 원문 |
| `expected_primary_symptoms` | ground truth `primary_symptoms` 원문 |
| `expected_metrics` | ground truth `expected_metrics` 원문; 실제 관측값이 아님 |
| `expected_log_patterns` | ground truth `expected_log_patterns` 원문; 실제 관측값이 아님 |
| `expected_recovery_action` | ground truth `expected_recovery_action` 원문 |
| `candidate_identified_fault_type` | archived representative output 원문 |
| `candidate_root_cause` | archived representative output 원문 |
| `candidate_remediation` | archived representative output 원문 list |
| `correctness_0_1_2_A` | reviewer 입력, 초기 blank |
| `reason_codes` | reviewer 입력, 초기 blank |
| `rationale` | reviewer 입력, 초기 blank |

`fault_name`을 별도 답 필드로 복제하지 않고, fault/trial/campaign/condition을 제거한다.
reference는 paraphrase나 LLM 요약 없이 ground truth의 고정 필드를 그대로 사용한다.
package 생성은 candidate를 읽기 전에 `results/ground_truth.csv` file SHA-256, row identity,
각 제공 source field 이름·UTF-8 byte SHA-256을 sealed reference manifest에 먼저 lock한다.
candidate를 본 뒤 reference를 보완·요약·교정할 수 없다.

이 package의 blinding은 **condition/Terra outcome/provider/provenance blind**이며
diagnostic-reference blind가 아니다. expected fields는 실제 Primary03에서 관측된 evidence가
아니라 사전 작성 synthetic ground truth이므로 primary construct는 incident truth의 절대
gold standard가 아니라 frozen ground-truth rubric과 candidate의 human concordance다.
reviewer instruction은 동일 reference가 반복되는 세 sibling candidate를 직접 비교하지
말고 각 item을 절대 기준으로 독립 채점하도록 요구한다. 반복 reference 때문에 incident
grouping을 추론하고 일관성 압력을 받을 가능성은 제거할 수 없는 한계로 보고한다.

package에는 `fault_id`, `trial`, `fault_name` key, `injection_method`, `campaign_id`, condition,
Terra score/vote/correctness, generation repeat/agreement/split, provider/model, retrieval
source/provenance/hash, input filename/path를 넣지 않는다.

### 6.2 semantic package allowlist

같은 두 reviewer에게 correctness와 분리된 order로 다음 12개 item을 제공한다.

| 필드 | 의미 |
|---|---|
| `context_id` | correctness `case_id`와 연결되지 않는 별도 opaque ID |
| `audit_reference_label_aliases` | ground truth `fault_name`과 사전 고정 alias; 노출 여부 판정 전용 |
| `audit_reference_entities` | `target_service`, `affected_components`; entity 노출 판정 전용 |
| `audit_reference_mechanism` | `expected_root_cause`; unique-mechanism 판정 전용 |
| `audit_reference_injection_signature` | `injection_method`; field/value/command 노출 판정 전용 |
| `procedure_text` | §5에서 byte-equivalent 재구성한 block |
| `severity_L0_L1_L2_L3` | reviewer 입력, 초기 blank |
| `label_exposed` | reviewer boolean |
| `entity_exposed` | reviewer boolean |
| `injection_specific` | reviewer boolean |
| `generic_procedure` | reviewer boolean |
| `rationale` | 근거 span과 설명 |

semantic reference는 correctness를 채점하기 위한 answer key가 아니라 procedure 안의
직접 label/entity/injection cue와 unique mechanism을 판별하기 위한 최소 비교 기준이다.
reference는 ground truth에서 기계적으로 복사하고 새 해석·paraphrase를 만들지 않는다.
semantic sheet에는 candidate output, Terra outcome, condition 이름, source ID/path/rank/
score, fault/trial을 넣지 않는다. reviewer는 opaque ID로 correctness sheet와 semantic
sheet의 같은 incident를 직접 연결할 수 없어야 한다. 두 correctness 원판정을 먼저
lock하고 correctness disagreement adjudication까지 lock·close한 뒤에만 semantic package를
배포해 semantic reference가 최종 correctness score에 역으로 영향을 주지 못하게 한다.

### 6.3 canonical identity, opaque ID, reviewer별 order

package 생성 시 OS CSPRNG로 256-bit `master_blinding_secret`을 한 번 생성한다. secret은
sealed answer-key 디렉터리에만 쓰고 public manifest에는 SHA-256 commitment만 남긴다.

canonical identity spec `v2.4-identity-json-1`은 JSON object를 UTF-8 strict로 serialize한다.
field order는 사전 지정 list, integer는 JSON decimal, string은 원 byte를 UTF-8 decode한
값이며 Unicode normalization을 하지 않는다. serializer는 `ensure_ascii=false`,
`separators=(",",":")`, trailing newline 없음으로 고정한다. row object field order는
`campaign_id,fault_id,trial,condition`, incident object는 `campaign_id,fault_id,trial`,
generation object는 여기에 `generation_repeat`를 추가한다. delimiter 연결 문자열은 쓰지
않는다.

```text
MAC(domain, payload_bytes) = HMAC-SHA256(
  master_blinding_secret,
  UTF8(domain) || 0x00 || payload_bytes
)
case_id    = "C-" + hex(MAC("v2.4/case-id", canonical(row_identity))[:16])
context_id = "S-" + hex(MAC("v2.4/context-id", canonical(incident_identity))[:16])
generation_id = "G-" + hex(MAC("v2.4/generation-id", canonical(generation_identity))[:16])
R1 order key = MAC("v2.4/R1/correctness-order", UTF8(case_id))
R2 order key = MAC("v2.4/R2/correctness-order", UTF8(case_id))
semantic order domains = "v2.4/R1/semantic-order", "v2.4/R2/semantic-order"
generation order domains = "v2.4/R1/generation-order", "v2.4/R2/generation-order"
```

opaque ID는 HMAC binary digest의 첫 16 bytes=128 bits를 32 lowercase hex characters로
표현한다. 같은 namespace 안 collision은 hard fail한다. order는 full 32-byte key의 unsigned
lexicographic order, tie이면 opaque ID ASCII order로 정한다. reviewer 1/2는 서로 다른
correctness/semantic order를 받는다.

최초 생성 secret은 OS CSPRNG source와 함께 sealed 보존하고 `SHA256(secret)` commitment를
배포 전 append-only manifest에 쓴다. 동일 audit ID replay는 새 secret을 만들지 않고 sealed
secret과 같은 source digest를 사용해야 한다. CSV LF, entry order, archive entry timestamp,
mode를 고정한 deterministic archive가 byte-identical하지 않으면 replay fail이다. package
schema/order/archive SHA-256과 secret commitment를 **rating 배포 전에** manifest에 commit한다.
모든 rating/adjudication lock 뒤에는 secret과 mapping을 sealed audit scope에서 reveal해
commitment, ID, order, archive를 재검증한다. reviewer에게 phase 종료 전에 reveal하지 않는다.

### 6.4 물리적 answer-key 분리

- 배포 archive: reviewer별 correctness와 semantic archive를 물리적으로 분리한다. semantic
  archive는 correctness adjudication phase가 폐쇄되기 전 배포할 수 없다.
- sealed key: 별도 directory에 `case_id/context_id -> source identity`, condition,
  archived Terra outcome/score, representative repeat, generation split, source hashes를 보존.
- escalation 여부와 무관하게 선택 12 incidents의 세 condition×세 generation=108개
  `generation_id`, canonical identity, output byte hash를 최초 manifest에 모두 봉인한다.
- reviewer archive와 sealed directory 사이 symlink/hardlink 금지.
- archive 내부에 hidden sheet, formula, comment, workbook metadata, answer-key filename을
  넣지 않는다. CSV+UTF-8 Markdown만 사용한다.
- correctness·semantic 두 phase의 adjudication sheet가 모두 lock되기 전에는 answer key를
  join하지 않는다.

## 7. correctness/semantic 별도 package scanner — fail closed

package는 raw에서 field를 빼는 방식이 아니라 §6의 phase별 allowlist로 새 record를 만드는
방식으로 구성한다. correctness와 semantic은 truth field가 다르므로 schema와 scanner
policy를 공유하지 않는다.

### 7.1 correctness scanner policy

- §6.1 column만 허용하고 semantic audit reference, condition, Terra outcome/score,
  provider/model, provenance, generation metadata는 모두 금지한다.
- candidate/reference의 실제 RCA 진단명과 expected field 값은 지정된 allowlisted column
  안에서만 허용한다.
- archive entry name, Markdown, CSV header/value, manifest metadata 전체를 recursive scan한다.

### 7.2 semantic scanner policy

- §6.2 column만 허용하고 candidate output, correctness score/reference-only field,
  Terra outcome/score, condition, provider/model, source provenance를 금지한다.
- label/entity/injection audit reference 값은 지정된 audit column 안에서만 허용한다.
- correctness package와 다른 schema hash, policy hash, positive/clean fixtures를 사용한다.

두 policy의 공통 hard-fail 대상은 다음과 같다.

- internal key/name: `fault_id`, `trial`, raw `fault_name` key, `campaign_id`,
  `context_condition`, `representative_score`, `judge_votes`, `correct_at_`, `majority_label`,
  `generation_split`
- condition value/slug: `length_placebo`, `blind_procedural_rag` 및 내부 condition enum
- campaign/provider/model marker: Primary03 full ID, `Terra`, `gpt-5.6-terra`, Codex/Copilot
  provider string
- provenance: source ID/path/basename, retrieval score/rank, hashes, raw/CSV filename
- identity pattern: `F[1-8]-t[1-5]`, raw artifact key/filename
- archive integrity: sealed key 포함, symlink/hardlink, absolute path, `..`, hidden file,
  duplicate filename, unexpected extension, non-allowlisted column

sealed answer key의 모든 known identifier/value로 canary corpus를 만든다. exact UTF-8,
case-folded, NFKC-normalized, JSON-escaped, URL-percent-encoded, base64, UTF-8 hex variant가
archive name/header/value/metadata의 **허용되지 않은 위치**에 있으면 각각 검출돼야 한다.
allowlisted truth column의 의도적 diagnostic value는 false positive로 막지 않되 동일 값이
다른 column/metadata로 이동하면 fail한다. policy별 positive fixtures는 각 forbidden class와
encoding을 최소 1개씩 포함하고 모두 fail해야 하며 clean fixture와 실제 archive는 pass해야
한다.

scanner pass report, schema/policy hash, archive SHA-256이 없으면 배포하지 않는다. pass가
증명하는 것은 **금지된 구조화 field/marker 미검출**뿐이며, reference 내용으로 incident를
추론할 semantic leakage가 0이라는 뜻은 아니다.

## 8. 사람 correctness rubric: 0/1/2/A

reviewer는 candidate 전체를 frozen reference의 target, mechanism, causal chain, expected
evidence, remediation과 대조한다. `identified_fault_type` exact string만으로 판정하지
않는다. `expected_metrics`와 `expected_log_patterns`는 실제 Primary03 관측 evidence가
아니므로 candidate가 이를 그대로 반복했다는 이유만으로 2점을 주지 않는다.

| 점수 | 정의 | 경계 예시 |
|---|---|---|
| `0 Incorrect` | 핵심 fault family, target 또는 mechanism이 틀리고 제안한 조치로 incident를 해결하기 어려움 | 증상만 맞고 다른 fault family/target을 원인으로 단정; reference와 모순되는 mechanism |
| `1 Partially correct` | 상위 fault family/주요 mechanism은 맞지만 target, mechanism detail, causal chain 또는 remediation의 중요한 부분이 빠지거나 일부 잘못됨 | resource exhaustion은 맞지만 target이 없거나, 직접 원인 대신 상위 증상에서 멈춤 |
| `2 Fully correct` | target과 mechanism이 reference에 부합하고 causal explanation이 evidence와 모순되지 않으며 remediation 원리가 원인을 해결함 | 표현/동의어가 달라도 incident-specific target·mechanism·복구가 모두 정렬 |
| `A Abstain` | reference/output만으로 판정할 수 없거나 guideline 경계가 실제로 모호함 | candidate가 파싱 불가능하거나 reference가 상충; 자신 없음의 대체값으로 사용 금지 |

reason code는 `WRONG_FAMILY`, `WRONG_TARGET`, `MECHANISM_MISSING`,
`CAUSAL_CHAIN_WEAK`, `EVIDENCE_CONTRADICTION`, `REMEDIATION_INADEQUATE`,
`REFERENCE_AMBIGUOUS`, `OUTPUT_UNPARSABLE`의 고정 집합을 사용한다. 여러 개 선택 가능하며
자유 rationale에 판정 근거를 적는다.

## 9. semantic shortcut rubric: L0~L3

| 등급 | 정의 | 판정 예시 | 처리 |
|---|---|---|---|
| `L0 generic` | 여러 fault에 공통인 확인·분기·안전 복구 절차 | 상태/이벤트/메트릭을 확인하고 가설을 좁히라는 일반 절차 | 적격 |
| `L1 weak narrowing` | 넓은 fault family를 좁히지만 답을 유일하게 만들지 않음 | 메모리·네트워크처럼 큰 계열을 보라는 힌트, 여러 원인이 가능 | flag, sensitivity |
| `L2 unique mechanism cue` | label 없이도 선택 incident의 mechanism을 사실상 유일하게 암시 | 특정 probe/field/resource mechanism의 독특한 조합이 하나의 원인만 남김 | construct 부적격 후보, 재설계 필요 |
| `L3 explicit shortcut` | canonical/alias label, target entity, injection-specific value·명령이 직접 노출 | 내부 fault ID, 고유 target, 주입값/명령, 사실상의 answer string | hard fail |

boolean은 severity와 독립 기록한다.

- `label_exposed`: canonical/alias diagnosis가 직접 남음
- `entity_exposed`: 선택 incident의 고유 target entity가 직접 남음
- `injection_specific`: 주입 value/field/command가 직접 남음
- `generic_procedure`: 여러 fault에 재사용 가능한 일반 절차임

adjudicated L3가 1건이라도 있으면 V2.3의 `leakage-controlled blind RAG` 표현은 철회하고
construct gate를 Red로 판정한다. L2는 빈도와 사례를 그대로 기술하되 n=12에서 보편적
허용 threshold를 만들지 않는다.

## 10. 두 독립 reviewer, sheet lock, adjudication

### 10.1 qualification, training, fatigue control

- correctness와 semantic에 사람 reviewer 2명 `R1`, `R2`를 등록한다. 각각 최근 5년 안에
  Kubernetes/SRE incident 대응 실무 2년 이상, 또는 CKA/CKAD와 실무 1년 이상을 문서화한다.
- V2.3 설계·실행·Terra 결과·Primary03 answer key를 본 사람은 conflict를 공개하고 교체를
  우선한다. 완전한 무노출 reviewer가 없으면 exposure 범위와 bias risk를 기록한다.
- Primary03가 아닌 frozen synthetic training set으로 correctness 8개 중 7개 이상 rubric
  key와 일치하고, semantic 6개 중 5개 이상 severity가 일치해야 참여한다. 통과 전 실제
  sample을 보지 않는다.
- 실제 sample item으로 rubric을 수정하지 않는다. 수정이 필요하면 rubric version을 올리고
  이미 본 score를 덮어쓰지 않으며 fresh reviewer pair가 전체 phase를 처음부터 수행한다.
- correctness는 session당 최대 18 items, semantic은 최대 6 items로 나누고 session 사이
  최소 15분 휴식한다. item별 시작/종료 시각, session ID, 종료 후 fatigue 1~5를 기록하되
  속도 quota는 두지 않는다.
- reviewer identity는 공개 산출물에서 pseudonym으로 처리한다.

### 10.2 phase 순서 hard gate

semantic answer reference가 correctness adjudication을 오염시키지 않도록 다음 순서를
바꿀 수 없는 gate로 고정한다.

```text
correctness training pass
→ R1/R2 correctness 독립 판정 lock
→ correctness disagreement adjudication lock
→ correctness phase CLOSED 선언 + sheet/adjudication hash commitment
→ semantic synthetic training pass
→ semantic package 최초 배포
→ R1/R2 semantic 독립 판정 lock
→ semantic disagreement adjudication lock
→ semantic phase CLOSED 선언
→ sealed key join 및 분석
```

correctness phase가 `CLOSED`가 되기 전 semantic archive의 파일 내용, reference, ID를
reviewer 또는 adjudicator에게 공개하지 않는다. 동일 pair를 두 phase에 쓰므로 기억을 통한
cross-sheet relinking 가능성은 semantic phase 결과의 한계로 기록한다.

### 10.3 lock

각 reviewer 제출 또는 adjudication 완료 때 다음을 즉시 수행한다.

1. blank·허용값·중복·case set을 검증한다.
2. 제출 CSV를 append-only `original_locked/` 또는 `adjudication/`에 복사한다.
3. UTC/KST timestamp, rubric version, package hash, sheet SHA-256을 lock manifest에 기록한다.
4. read-only permission을 적용하고 이후 수정하지 않는다.

오류 수정은 원본을 덮어쓰지 않고 새 correction record로 추가한다. phase가 닫히기 전에는
해당 phase의 answer key를 join하지 않으며, 다른 phase package를 공개하지 않는다.

### 10.4 condition/Terra-blind adjudication

가능하면 R1/R2 원판정을 보되 condition, Terra, semantic-next-phase reference에 blind인
세 번째 domain adjudicator `R3`가 disagreement를 판정한다. R3도 §10.1 qualification과
conflict disclosure를 통과해야 한다. R3를 확보하지 못하면 R1/R2가 원판정과 rationale를
검토해 합의 score/flags를 append-only sheet에 기록하며 그 한계를 명시한다.

어느 방식에서도 원판정과 disagreement matrix를 primary evidence로 보존하고 consensus가
uncertainty를 제거했다고 표현하지 않는다. 합의하지 못한 correctness는 `A`, semantic은
`UNRESOLVED`로 남긴다. correctness adjudication이 먼저 완전히 lock·close된 뒤에만
semantic package를 배포한다. semantic adjudication까지 lock·close된 뒤에만 sealed key를
join해 Terra-human 분석과 condition별 descriptive strata를 만든다.

## 11. metric, confidence interval, Green/Gray/Red gate

### 11.1 보고 metric

보고 순서는 상태 색보다 point estimate, raw count, confusion matrix, CI가 먼저다. 20%,
human-human raw agreement 85%, kappa 0.70은 이 표본과 rubric에서 검증된 보편 cutoff가
아니라 의사결정용 운영 경계다.

Correctness 원판정:

- 0/1/2/A 분포와 reason-code 빈도
- exact 4-category raw agreement
- 0/1/2의 quadratic weighted Cohen's kappa와 binary(`>=1`) Cohen's kappa
- binary raw agreement 85%는 36 pair 모두 유효할 때 31/36 pass, 30/36 fail인 운영 alert로
  보고하며 A 포함/제외 denominator를 명시
- adjudication 전 disagreement matrix

Terra 대 adjudicated human:

- `T`와 primary `H(score>=1)` 2x2 confusion matrix
- 전체 discordance와 방향별 `Terra-only`, `human-only` count
- discordance Wilson 95% CI
- discordant pair 안에서 방향 비율의 exact Clopper-Pearson 95% CI
- direction CI가 0.5를 제외하면 `DIRECTIONAL_ALERT=true`; primary status는 바꾸지 않음
- `score=2` binary sensitivity의 같은 표
- condition별 값은 descriptive only
- primary 20% 외에 10%·15%·25% Wilson state/count boundary sensitivity를 같은 table에
  descriptive로 제시하되 primary cutoff를 교체하지 않음

Semantic:

- L0/L1/L2/L3/UNRESOLVED 분포와 boolean flag 빈도
- exact raw agreement와 quadratic weighted kappa
- L3 adjudicated count와 L2 사례 목록

proportion CI는 Wilson 95%, 방향 비율은 exact Clopper-Pearson 95%로 고정한다. correctness
kappa 95% CI는 12 incident cluster를 50,000회 resample하고 각 incident의 세 condition을
함께 유지하는 percentile bootstrap, seed `20260830`로 계산한다. 36 row를 독립 resample하지
않는다. semantic weighted kappa(n=12)는 raw matrix와 함께 **descriptive point only**이며
gate나 안정성 인증에 쓰지 않는다. degenerate prevalence로 kappa가 정의되지 않으면 다른
metric으로 교체하지 않고 `undefined`와 confusion/raw agreement를 보고한다. A/UNRESOLVED는
임의로 0 또는 중간값 대치하지 않는다.

### 11.2 primary discordance 정수 gate

먼저 reconstruction/package/input integrity gate가 모두 pass해야 measurement status를
부여한다. integrity fail은 `technical_status=RED`이며 사람에게 배포하거나 score를 분석하지
않는다.

실제 `n_non_abstain=n`과 discordant count `d`에서 다음을 기계적으로 계산해 manifest에
고정한다.

```text
green_max_discordant_count(n) = max d where Wilson95_upper(d,n) < 0.20
red_min_discordant_count(n)   = min d where Wilson95_lower(d,n) >= 0.20
Green = d <= green_max
Gray  = green_max < d < red_min
Red   = d >= red_min
```

Green 집합이 비면 `green_max=-1`, Red 집합이 비면 `red_min=n+1`로 기록한다. n=0은 아래
abstain 규칙에 따라 interval/status를 계산하지 않는다.

n=36, A=0일 때 primary discordance 축의 exact 운영표는 다음과 같다.

| discordant count | 비율 범위 | primary status | 의미 |
|---:|---:|---|---|
| 0~2 | 0~5.6% | **Green** | Wilson 상한이 20% 미만인 강한 저불일치 증거 |
| 3~11 | 8.3~30.6% | **Gray** | 20% 경계에 대해 interval이 결정적이지 않음 |
| 12~36 | 33.3~100% | **Red** | Wilson 하한이 20% 이상 |

따라서 Green은 단순 point `<20%`가 아니라 n=36에서 최대 2건이라는 강한 조건이다.
adjudicated correctness에 `A`가 하나라도 있으면 대치하지 않고 actual n의 Green/Red count를
계산·기록하되 `primary_status=GRAY_ABSTAIN`으로 override한다. 예를 들어 n=33은 Green 최대
2건, n=32는 최대 1건이지만 구현은 예시를 hard-code하지 않고 실제 n에서 계산한다.
`n_non_abstain=0`이면 Wilson status를 계산하지 않고 `NOT_EVALUATED_ABSTAIN`으로 기록하며
overall triage는 Gray다.

### 11.3 분리된 상태와 보조 alert

한 색으로 서로 다른 construct를 합치지 않고 다음을 별도 기록한다.

| 필드 | 판정 |
|---|---|
| `technical_status` | input/reconstruction/package/isolation integrity pass 또는 Red |
| `primary_discordance_status` | §11.2의 Green/Gray/Red; H-V2.4의 유일한 primary 상태 |
| `directional_alert` | discordant 방향 exact CI가 0.5를 제외하면 true; primary 색 불변 |
| `reviewer_reliability_alert` | binary raw `<85%` 또는 kappa `<0.70`/undefined; 운영 alert일 뿐 gold-standard 판정 아님 |
| `semantic_eligibility_status` | adjudicated L3=0이고 unresolved=0이면 pass, L3>=1이면 Red, unresolved>=1이면 Gray; L0~L2/kappa는 descriptive |
| `overall_triage` | technical/semantic Red 또는 primary Red면 Red; 그 외 A/reliability alert/primary Gray면 Gray; 나머지 Green |

condition별 disagreement 방향이 상반되면 descriptive `STRATUM_DIRECTION_ALERT`를 추가하되
primary status를 바꾸지 않는다. Green/Gray/Red는 `Primary03` measurement triage일 뿐
V2.3 RAG 가설의 성공/기각 판정이 아니다.

## 12. 108-output escalation

최초 36 package를 만들 때 escalation 여부와 무관하게 §6.4의 108 archived generation
identity와 output byte hash를 sealed manifest에 결과 독립적으로 고정한다. 이 봉인은
generation-level audit을 수행했다는 뜻이 아니며 sample/order를 사후 선택하지 못하게 하는
provenance다.

초기 36개가 Gray이거나 대표 선택 bias가 결론을 지배할 가능성이 있으면 동일 12
incidents의 **세 condition × archived generation 3개 = 108 outputs**로 확대한다. 새 model
generation/judge 호출은 없다.

다음 중 하나면 escalation 후보를 자동 기록한다.

1. primary Terra-human discordance point가 20% 이상이거나 Wilson CI가 20%를 가로지름
2. human-human raw agreement `<85%` 또는 kappa `<0.70`
3. condition별 `Terra-only`와 `human-only` 우세 방향이 서로 반대
4. 36 discordant cases의 절반 이상이 archived `generation_split=true` row에 있거나,
   split stratum의 discordance가 non-split보다 20%p 이상 높음

2번은 먼저 rubric 문제인지 확인한다. rubric을 수정해야 하면 기존 score를 덮어쓰지 않고
rubric v2와 fresh reviewer pair로 108개를 처음부터 독립 판정한다. escalation package는
generation repeat/condition/기존 representative 여부를 숨기고, 최초 sealed 108개를 누락
없이 outcome과 무관하게 포함한다. 새 secret을 만들지 않고 최초 master secret의
`v2.4/*/generation-order` domain으로 reviewer별 order를 재현한다. 두 reviewer 기준 216
ratings다.

108 결과는 원래 36 audit을 대체하지 않는다. 대표 선택 disagreement, generation 내
분산, representative-vs-all-generation 차이를 sensitivity로 병기한다. 사람 reviewer가
없으면 escalation을 실행하거나 score를 생성하지 않는다. Gray를 보고 선택한 108 확대는
outcome-contingent sensitivity이므로 generation distribution의 unbiased primary audit으로
표현하지 않는다. 논문에서 generation-level 주장이 필요하면 별도 사전 승인된 sensitivity
audit으로 108 전체를 수행한다.

## 13. reviewer가 없을 때의 package-only 종료

기술 package 완료와 measurement 완료를 같은 `complete`로 표현하지 않는다. 상태 manifest는
항상 다음 세 필드를 분리한다.

```text
technical_package_status = NOT_STARTED | COMPLETE | INVALID
human_measurement_status = NOT_STARTED | AWAITING_REVIEW | COMPLETE | INVALID
analysis_status = NOT_STARTED | PACKAGE_ONLY | MEASUREMENT_COMPLETE
```

두 실제 사람 reviewer가 확보되지 않으면 다음 상태에서 멈춘다.

```text
technical_package_status = COMPLETE
human_measurement_status = AWAITING_REVIEW
analysis_status = PACKAGE_ONLY
status_detail = PACKAGE_READY_AWAITING_HUMAN_REVIEW
human_ratings = 0
adjudications = 0
measurement_gate = NOT_EVALUATED
```

이 경우 허용되는 완료 주장은 input/reconstruction/package scanner 검증과 두 reviewer
archive 준비뿐이다. AI, Codex, Copilot, LLM judge, 규칙 기반 추정으로 사람 score를
채우지 않는다. Terra-human metric, kappa, Green/Gray/Red measurement 판정을 만들지
않고 `results/analysis_v2_4.md`, changelog, PR summary에서도 H-V2.4 판정 또는
`human_measurement_status=COMPLETE`로 표현하지 않는다.

## 14. 구현 범위와 출력 경로 — 승인 후에만

예상 소유 경계는 다음과 같다. Step 2 P0가 반영된 현재 plan/review hash bundle에 대한
사용자의 단일 승인 뒤 Step 3에서 정확한 파일을 확정한다.

| 용도 | 경로 |
|---|---|
| offline selector/reconstructor/package/scanner/analyzer | `experiments/v2_4/` |
| 새 audit root | `artifacts/v2_4_measurement_audit/<audit_id>/` |
| 입력 digest와 실행 manifest | `<audit_root>/manifests/` |
| Chroma working copy | `<audit_root>/working/chroma_snapshot/` |
| reviewer 1/2 배포 archive | `<audit_root>/distribution/reviewer_01/`, `reviewer_02/` |
| sealed answer key·blinding secret | `<audit_root>/sealed/` |
| locked reviewer 원본 | `<audit_root>/ratings/original_locked/` |
| append-only adjudication | `<audit_root>/ratings/adjudication/` |
| 분석 table/figure | `<audit_root>/analysis/` |
| 방법론 비평 | `docs/plans/review_v2_4.md` |
| 변경 기록 | `results/experiment_changes_v2_4.md` |
| 최종 해석 | `results/analysis_v2_4.md` |

기존 `Primary03`, `results/*.csv`, `results/raw_v*`, `ground_truth.csv`는 출력 경로가 될 수
없다. 모든 새 output은 absent path에서만 생성하고 overwrite를 거부한다.

## 15. 승인 후 실행 단계와 검증 test

실제 CLI는 Step 3 구현·`--help` 검증 뒤 review 문서에 고정한다. 아래 이름은 계획된
interface이며 현재 실행 가능한 것처럼 주장하지 않는다.

### 15.1 단계

1. §16의 network-none/K8s-unmounted execution isolation과 policy hash를 먼저 검증한다.
2. read-only preflight: exact input path, 117 CSV rows/117 raw, 39 complete incidents,
   세 condition, selected 12 incident 존재 확인
3. source inventory/WAL/SHM quiescence와 input hash manifest를 잠근 뒤 raw Chroma working
   copy를 만들고 source/copy digest를 검증한다.
4. preregistered selector 재현 및 12/36 identity exact match를 확인하고 108 generation
   identity/hash도 sealed manifest에 고정한다.
5. immutable working copy에서 12 blind block byte-equivalent reconstruction을 수행한다.
6. ground-truth reference manifest를 candidate보다 먼저 lock하고 canonical JSON/HMAC secret,
   ID/order, sealed key, deterministic phase별 archive를 생성한다.
7. correctness/semantic 별도 scanner와 archive inventory를 검사하고 secret/package/order/
   archive commitment를 배포 전에 잠근다.
8. 사람 reviewer가 있으면 §10.2 순서대로 correctness 배포→원판정 lock→correctness
   adjudication lock→phase close→semantic 최초 배포→원판정/adjudication lock→key join→분석.
9. reviewer가 없으면 package-only status로 종료한다.
10. 입력/working digest, replay archive, output count/hash, isolation attempt log를 최종 검증한다.

### 15.2 필수 automated test

- `test_primary03_only`: 다른 campaign row를 주입하면 fail
- `test_input_read_only`: source tree digest before/after exact match
- `test_chroma_quiescence`: WAL/SHM/unknown checkpoint state와 special file을 fail
- `test_raw_copy_only`: source library open 없이 raw copy하고 source/copy tree digest exact match
- `test_sqlite_immutable`: working copy migration/journal/write/telemetry 시도 fail
- `test_preregistered_seed`: 공개 seed hash와 12 incident 목록 exact match
- `test_outcome_blind_selector`: selector input schema에 score/output/condition이 들어가면 fail
- `test_row_raw_identity`: 36 row/raw key와 representative output exact match
- `test_chroma_source_hash`: exact collection/document/offset가 유일하며 12×candidate
  source length/hash/locator 검증
- `test_utf8_reconstruction_spec`: invalid UTF-8, normalization/newline 변환, Python version
  mismatch를 fail
- `test_reverse_span_reconstruction`: span reverse apply, Python 3.11 strip, LF join,
  `[REDACTED]` bytes exactness
- `test_masked_and_additional_hash`: 12/12 두 hash 일치
- `test_ground_truth_reference_lock`: candidate read 전 file/row/field hash commitment 확인
- `test_correctness_package_policy`: correctness unexpected/semantic-only field fail
- `test_semantic_package_policy`: semantic unexpected/candidate/correctness-only field fail
- `test_blinding_separation`: case/context ID 역매핑이 distribution에 없고 두 sheet 연결 불가
- `test_canonical_identity_json`: fixed UTF-8/field order/integer/no-normalization fixture 일치
- `test_hmac_128bit_domains`: ID 길이, domain separation, collision, order tie-break 검증
- `test_reviewer_order`: R1/R2 order가 각각 36/12 permutation이며 서로 다름
- `test_commit_before_distribution`: secret/package/order/archive hash가 배포보다 먼저 lock
- `test_replay_byte_identity`: 같은 audit ID/secret/input의 archive가 byte-identical 아니면 fail
- `test_leak_scanner_canaries`: 별도 policy의 exact/casefold/NFKC/JSON/URL/base64/hex fixture fail
- `test_leak_scanner_clean_fixture`: policy별 clean fixture와 실제 package pass
- `test_archive_safety`: symlink/hardlink/path traversal/hidden metadata/answer key 포함 fail
- `test_sheet_lock`: locked original overwrite fail, correction append만 허용
- `test_phase_order`: correctness adjudication close 전 semantic distribution fail
- `test_abstain_no_imputation`: A/UNRESOLVED 대치 금지
- `test_metric_fixture`: confusion, Wilson actual-n count boundary, exact direction interval,
  incident-cluster kappa bootstrap의 hand-calculated fixture 일치
- `test_n36_gate`: 0~2 Green, 3~11 Gray, 12~36 Red, any A Gray exact match
- `test_semantic_kappa_descriptive`: semantic kappa가 gate를 변경하면 fail
- `test_threshold_sensitivity`: 10/15/25% 결과가 primary 20% status를 변경하면 fail
- `test_no_human_package_only`: reviewer file 0이면 score/analysis/gate 생성 금지
- `test_all_generation_seal`: escalation 전 108 unique identity/hash가 commitment에 존재
- `test_all_generation_escalation`: sealed 108 전수 외 sample과 representative-only filter 금지
- `test_execution_isolation`: HTTP library, raw socket, DNS, cloud proxy, `kubectl`, Kubernetes
  client, Codex/Copilot binary, Chroma telemetry fixture가 실제로 차단됨
- `test_child_process_inventory`: PATH 외 binary와 미기록 child process가 fail
- `test_output_overwrite_refusal`: existing audit ID에 쓰기 fail

dry-run 통과 여부는 현재 **NOT RUN**이다. 승인 전에는 어떤 test도 구현하거나 실행하지
않는다.

### 15.3 수동 verification checklist

- distribution archive 두 개를 직접 풀어 forbidden field·hidden metadata 부재 확인
- sealed key가 archive 밖에 있고 inode/link가 공유되지 않음을 확인
- correctness 36개, semantic 12개, reviewer별 순열과 hash 확인
- source/working input digest before/after, WAL/SHM absence, immutable-open log 확인
- correctness adjudication close가 semantic 최초 배포보다 앞선 timestamp인지 확인
- canonical JSON/HMAC commitment와 동일 audit replay의 byte identity 확인
- execution isolation policy, cleared environment, mount/PATH, child/socket attempt log 확인
- analysis가 사람의 실제 locked score만 읽는지 확인
- 보고서가 confirmatory effect나 V2.3 campaign 결합을 만들지 않는지 확인

## 16. 0-call, 모델, K8s 안전 계약

repo의 모델 정책은 `gpt-4o-mini` 고정이다. V2.4에서는 이 모델도 호출하지 않으므로
실행 model-call budget은 정확히 0이다. `Terra`는 새 모델 선택이 아니라 보존된 V2.3
automatic outcome의 출처 이름으로만 읽는다.

| 행위 | V2.4 허용량 |
|---|---:|
| 새 LLM inference | 0 |
| OpenAI/기타 model API call | 0 |
| Codex CLI subprocess/call | 0 |
| Copilot CLI subprocess/call | 0 |
| embedding/retrieval model call | 0 |
| K8s API/kubectl read 또는 write | 0 |
| K8s mutation/fault injection | 0 |
| lab tunnel 생성/재사용 | 0 |

Chroma stored chunk의 immutable local read는 외부 API나 retrieval query가 아니다. Step 3
실행은 단순 denylist가 아니라 다음 격리 profile을 먼저 적용한다.

1. container/network namespace `network=none` 또는 OS firewall의 동등한 egress/DNS/socket
   deny를 사용하고 policy hash를 기록한다.
2. HTTP(S)/ALL proxy, cloud credential/metadata, OpenAI/Codex/Copilot, `KUBECONFIG`, Kubernetes
   service host/port, SSH agent 관련 환경변수를 제거한다.
3. kubeconfig, service-account token, cloud credential, SSH key/socket을 mount하지 않는다.
4. PATH는 audited Python runtime과 package가 필요로 하는 read-only allowlist만 포함하고
   `codex`, `copilot`, `kubectl`, shell, network client를 제외한다.
5. Chroma telemetry를 명시적으로 disable하고 working copy는 immutable/read-only로 연다.
6. execution wrapper가 child-process spawn과 socket/DNS/network attempt를 기록·차단한다.
7. manifest에 isolation type/policy hash, cleared-env key inventory, mount inventory, PATH,
   child-process inventory, blocked-attempt count를 기록한다.

negative fixtures는 Python HTTP client, raw socket, DNS, cloud metadata, `kubectl`, Kubernetes
client library, Codex/Copilot binary, Chroma telemetry가 실제로 차단됨을 보여야 한다.
manifest의 자체 `*_calls=0`은 isolation evidence를 대체하지 않는다.

플랫폼에서 network-none과 mount/PATH/child-process 통제를 강제할 수 없으면
`zero_call_assurance=OBSERVED_ONLY`로 낮추고 “외부 호출 0 보장”을 주장하지 않는다. 이 경우
관측 가능한 process/socket log에서 0이었음과 관측 한계를 함께 보고한다. 어느 assurance
수준에서도 live Chroma retrieval, embedding, 모델 호출, K8s read/write는 허용되지 않으며,
격리 또는 하향 claim을 manifest에 남기지 못하면 완료를 주장하지 않는다.

## 17. 예상 시간·비용과 실패 시 대안

### 17.1 비용

- 모델/API/Codex/Copilot 비용: 0
- cluster 비용·mutation: 0
- 사람 비용: 1차 36 correctness + 12 semantic = reviewer당 48 ratings, 두 명 96 ratings
- escalation: reviewer당 correctness 108 ratings, 두 명 216 ratings; semantic 재검토가
  필요하면 별도 계획에 명시

사람 소요시간은 실제 reviewer pilot이 없으므로 고정 숫자를 만들지 않는다. §10.1의
session 분할·휴식·item별 시작/종료 시각·fatigue 기록은 필수이며 피로·순서 효과를
descriptive로 보고한다.

### 17.2 실패 시 대안

- Primary03/Chroma exact snapshot 부재: 대체 campaign 사용 금지, `BLOCKED_INPUT_MISSING`
- reconstruction hash mismatch: 재검색/근사 복원 금지, `Technical Red`
- package leak: 배포 금지, allowlist/scanner 수정 후 새 audit ID로 전부 재생성
- reviewer agreement 실패: 원판정 보존, rubric 취약점 기록, fresh reviewers/rubric v2 검토
- L3 발견: blind corpus construct 재설계, 기존 V2.3 RAG effect 근거 제외
- Gray/representative bias: §12의 108 archived outputs로 확대
- reviewer 부재: §13 package-only 종료, 점수 생성 금지

## 18. 타당성 위협과 주장 경계

### 구성 타당성

사람 reviewer도 frozen synthetic ground-truth reference와 rubric의 산물이다. 0/1/2는
reference-candidate concordance를 세분하지만 현실의 절대 근본원인 truth나 causal reasoning의
직접 측정은 아니다. blinding은 condition/Terra/provider/provenance에 한정되고 diagnostic
reference는 의도적으로 보인다. L0~L3도 semantic shortcut의 ordered 판단이지 객관적
물리량이 아니다.

### 내적 타당성

sample은 outcome-blind지만 Primary03 자체가 F1~F8의 sequential prefix다. archived
representative는 Terra majority/score를 사용해 선택됐으므로 36 audit만으로 generation
selection bias를 제거하지 못한다. reviewer blinding은 자동 outcome 상관오차를 줄이지만
reference 작성자와 fault taxonomy의 공통 편향을 제거하지 못한다. 동일 incident의 세
reference 반복으로 sibling grouping을 추론할 수 있고 상대 비교·일관성 압력이 생길 수
있다. correctness phase를 semantic보다 먼저 완전히 닫아 직접 역오염은 차단하지만 같은
reviewer pair의 기억을 통한 relinking 한계는 남는다.

### 외적 타당성

결과는 Primary03, F1~F8, 한 cluster/Online Boutique/corpus, V2.3 Terra outputs에만
해당한다. 다른 모델, provider, corpus, production MTTR 또는 complete campaign으로
일반화하지 않는다.

### 통계 타당성

n=36, semantic n=12이므로 CI가 넓고 kappa가 prevalence에 민감하다. 세 condition row는
12 incident에 clustered되어 correctness kappa CI는 incident-cluster bootstrap을 쓴다.
semantic kappa는 descriptive point only다. raw count·agreement·confusion·CI를 상태 색과
kappa보다 우선 해석한다. Green이 나오더라도 V2.3 causal effect가 입증되는 것은 아니다.

### 반증 가능성

가설은 primary discordant count가 n=36에서 0~2건이고 Terra-human confusion이 거의
대각이며 L3=0인 관찰로 약화된다. 방향 alert, reviewer agreement, L0~L2는 원인을
설명하는 보조 결과이지 primary magnitude 가설과 결합하지 않는다. 낮은 불일치도 두
측정법이 같은 synthetic reference 표현에 정렬된 공통방법 편향일 수 있고, incomplete
campaign이라는 별도 결함은 남는다.

## 19. 단계별 산출물과 다음 checkpoint

| 단계 | 산출물/상태 |
|---|---|
| Step 1 | `docs/plans/experiment_plan_v2_4.md` — Step 2 P0 반영본 |
| Step 2 | `docs/plans/review_v2_4.md` — fresh 독립 5축 방법론 비평 완료 |
| 승인 gate | plan/review hash+P1 status bundle에 대한 사용자 단일 명시 승인 대기 |
| Step 3 | 단일 승인 후 `experiments/v2_4/`, mock/dry-run evidence, 변경 기록 |
| Step 4 | offline package 생성; 실제 reviewer가 있으면 lock/adjudication, 없으면 package-only |
| Step 5 | fresh `results_critic`의 `results/analysis_v2_4.md` |
| Step 6 | 다음 goal/session handoff; PR은 사용자 승인 뒤 merge |

**바로 다음 checkpoint:** 고정된 plan/review SHA-256과 P1-1~P1-5 반영 상태를 묶어
사용자에게 제시하고 단일 명시 승인을 받는다. 승인 전에는 구현, dry-run, Chroma open/copy,
package 생성·배포·채점, 분석을 하지 않는다.

# V2.4 독립 비판 분석 — Primary03 무호출 retrospective measurement audit

> 분석일: 2026-08-31
>
> 역할: Experiment Track Step 5 fresh results critic
>
> 분석 대상: 승인된 V2.4 plan/review, `Primary03` 보존 입력, V2.4 구현·테스트,
> `artifacts/v2_4_measurement_audit/v2-4-primary03-audit-20260831`
>
> 1차 판정: **기술 package 준비 완료, 사람 측정 및 H-V2.4 판정 미완료**

## 결론부터

V2.4의 현재 상태는 계획서가 정의한
`PACKAGE_READY_AWAITING_HUMAN_REVIEW`와 일치한다. 입력·working copy의 content digest,
12개 blind-RAG block 재구성, reviewer별 36개 correctness/12개 semantic archive,
108 generation identity/hash 봉인, scanner report, archive commitment와 same-key replay는
검증됐다. 따라서 **기술 package는 완료**로 판정한다.

그러나 실제 사람 rating과 adjudication은 모두 0건이다. 그러므로 Terra-human
discordance, human-human agreement, Cohen's κ, semantic L0~L3, McNemar 검정,
Green/Gray/Red는 계산할 수 없다. **H-V2.4는 성공도 실패도 아니며 `NOT_EVALUATED`다.**
V2.3의 blind RAG가 RCA를 개선하는지, 또는 semantic shortcut을 통제했는지도 이 결과로
판정할 수 없다.

격리 보장도 OS 수준이 아니라 `OBSERVED_ONLY`다. 실행 중 관측된 외부/model/K8s 호출은
각각 0으로 기록됐지만, host PATH·mount·network namespace가 강제되지 않았으므로
“외부 호출 0을 독립 보장했다”는 표현은 사용하지 않는다.

## 1. 데이터 검증

### 1.1 승인·입력 정본

승인 기록이 가리키는 plan/review hash를 다시 계산했다.

```text
experiment_plan_v2_4.md  65ce766364f57c1fd2a8fbbf829cd50ba55cdb7d788ad1123a37667c713dcf63
review_v2_4.md           d16b1aea52bbe863d234cba2741a4784606f39c4102cee003bf0a35bd22aed64
```

두 값은 `docs/plans/approval_v2_4.md`의 승인 bundle과 일치한다. 승인된 primary estimand는
같은 archived representative output에서 Terra `correct_at_0.5`와 condition/Terra-blind
dual-human adjudicated `score>=1`의 불일치율이다. 조작 독립변수는 없고, V2.4는 RAG 효과
실험이 아니라 retrospective paired measurement audit다.

입력 정본은 다음 하나다.

```text
/Users/yumunsang/thesis-rca-v2-3-terra/artifacts/v2_3_main/
  v2-3-codex-20260830-primary03
```

CSV/raw를 직접 센 명령 결과는 다음과 같다.

```text
experiment_results_v2_3.csv data rows = 117
raw_v2_3/*.json                    = 117
unique incidents                   = 39
context conditions                 = runtime 39, length_placebo 39,
                                     blind_procedural_rag 39
fault rows                          = F1~F6 각 15, F7 12, F8 15
selected audit rows                = 36
```

117 CSV key와 117 raw key의 1:1 일치는 실제-input integration test에서도 fail-closed
fixture와 함께 통과했다. 선택 incident는 계획대로
`F1-t2,F1-t3,F2-t1,F3-t3,F3-t4,F4-t1,F5-t2,F5-t3,F6-t5,F7-t1,F7-t3,F8-t3`이며,
F1/F3/F5/F7 각 6 outputs, F2/F4/F6/F8 각 3 outputs다.

### 1.2 로그·중단 경계

Primary03에는 별도 `.log/.out/.err` 파일이 없고, 실행 이력은 JSONL ledger에 있다.

```text
campaign_events.jsonl       = 485 records
call_ledger_v2_3.jsonl      = 1,404 records
incident_committed          = 39
incident_failed             = 1
standalone source log files = 0
standalone V2.4 audit logs  = 0
```

마지막 실패 sequence는 `F9-t1 injection_started → incident_failed(PilotError) →
flux_restored → recovery_green`이다. 따라서 Primary03은 계획된 59 incidents/177 rows가
아니라 F1~F8의 39 incidents/117 rows에서 끝난 비무작위 prefix다. V2.4가 이 prefix를
confirmatory dataset으로 승격하지 않고 측정 package 재료로만 사용한 것은 적절하다.

V2.4 자체의 영속 실행 로그는 없어서 build 당시 stdout/stderr를 사후 재검사할 수 없다.
대신 `input_manifest.json`, `isolation.json`, `package_commitment.json`, `status.json`과
재실행 테스트가 기술 evidence다. 후속 재현성을 위해서는 build/replay 검증 출력을
append-only 실행 receipt로 남기는 편이 더 강하다.

### 1.3 입력 불변성과 재구성

실제 filesystem에서 tree manifest를 다시 계산했다.

| 대상 | 파일 수 | 실제 tree SHA-256 | manifest와 일치 |
|---|---:|---|---|
| Primary03 campaign | 123 | `023c4dc90480d19c13e969508afae13255cb278011fd0b9ba5e5e548871a9655` | 예 |
| source Chroma | 6 | `8ef1886aa14c4f1c0489eb2b8033b0582194515d2f7c1e7d3eacf0fc65c676fe` | 예 |
| working Chroma | 6 | `8ef1886aa14c4f1c0489eb2b8033b0582194515d2f7c1e7d3eacf0fc65c676fe` | 예 |

source와 working Chroma에는 `-wal/-shm`가 없었고 working 파일은 모두 read-only,
link count 1이었다. `reconstruction_evidence.json`에는 12개 context와 context당 5개 source
hash가 있다. 구현은 source length/hash, exact locator, removed span, reconstructed
`masked_procedure_hash`, raw `additional_context_hash`가 모두 일치하지 않으면 artifact를
생성하지 않는다. 실제 입력 재구성 integration test와 동일 sealed-key replay를 다시
실행한 결과는 다음과 같다.

```text
same-audit replay status = PASS
byte-identical archives  = 4/4
V2.4 unittest            = 28/28 PASS (9.666s)
```

이 결과는 현재 보존 입력에서 12개 block을 byte-equivalent하게 다시 만들 수 있다는
기술 근거다. block이 semantic shortcut으로부터 안전하다는 사람 판정은 아니다.

### 1.4 package·commitment·blinding

Python `csv` parser로 archive 내부를 직접 읽은 결과다. semantic procedure에는 개행이
있으므로 물리 line count가 아니라 CSV record count를 사용했다.

| archive | records | unique opaque IDs | 입력된 rating cell |
|---|---:|---:|---:|
| R1 correctness | 36 | 36 | 0 |
| R2 correctness | 36 | 36 | 0 |
| R1 semantic, sealed pending | 12 | 12 | 0 |
| R2 semantic, sealed pending | 12 | 12 | 0 |

R1/R2는 correctness와 semantic 모두 순서가 다르고 ID 집합은 같다. 각 archive는 CSV와
instructions Markdown 두 member만 가지며, archive SHA-256 네 개가
`package_commitment.json`과 모두 일치했다. obvious forbidden marker
(`campaign_id`, `fault_id`, condition slug, Terra/model marker, `F*-t*`)의 독립 text scan은
4개 archive 모두 0건이었다. manifest scanner report도 각 archive `PASS`이며 claim을
“forbidden structured fields/markers not detected”로 제한했다.

correctness archive 두 개만 distribution에 있고 semantic archive 두 개는
`sealed/pending_semantic/`에 있다. `ratings/` 파일과 semantic distribution은 각각 0개다.
이는 `correctness CLOSED → semantic qualification → semantic release` 순서를 아직 시작하지
않았다는 뜻이며 phase 역오염을 막는 현재 상태로 타당하다.

sealed answer key에는 correctness mapping 36개와 generation identity/hash 108개가 있다.
generation ID는 모두 유일하고 repeat 1/2/3이 각 36개, representative 36개와
non-representative 72개다. 다만 비대표 72개의 full output 본문은 Primary03에 보존되지
않았다. 그러므로 108-output sensitivity는 hash/identity 봉인만 가능하고 실제 채점 package
materialization은 `BLOCKED_GENERATION_CONTENT_NOT_ARCHIVED`로 막힌다.

### 1.5 상태 manifest와 0-call 주장 범위

`status.json`은 다음을 기록한다.

```text
technical_package_status = COMPLETE
human_measurement_status = AWAITING_REVIEW
analysis_status          = PACKAGE_ONLY
status_detail            = PACKAGE_READY_AWAITING_HUMAN_REVIEW
human_ratings            = 0
adjudications            = 0
measurement_gate         = NOT_EVALUATED
```

`isolation.json`은 observed external/model/K8s call을 모두 0으로 기록하지만,
`zero_call_assurance=OBSERVED_ONLY`, `mount_control=not-enforced-host-process`,
`path_control=not-enforced-host-process`다. Python socket/DNS/subprocess 차단 fixture는
통과했으나 host OS의 egress·mount·PATH를 독립 강제하지 않았다. 따라서 기술 상태
`COMPLETE`는 plan이 허용한 하향 claim 안에서는 타당하지만, 물리적 network-none 증명은
아니다.

## 2. 통계 분석

### 2.1 V2.4 primary 통계 — 미평가

사람 correctness와 semantic rating이 0건이므로 다음 값은 계산하지 않았다.

- Terra-human confusion 및 discordant count/비율/Wilson 95% CI
- Terra-only 대 human-only 방향 exact interval
- System A/B 또는 condition별 human correctness
- 두 reviewer raw agreement, Cohen's κ와 50,000회 incident-cluster bootstrap CI
- semantic L0~L3 분포, weighted κ, L3 eligibility gate
- McNemar χ²/exact p-value
- `score=2` sensitivity와 10/15/25% cutoff sensitivity
- Green/Gray/Red 및 overall triage

이는 누락이 아니라 plan §13의 fail-closed 규칙이다. rating 0에서 McNemar 또는 κ를
0/1로 채우거나 AI가 사람 점수를 대신 만들면 measurement construct 자체를 위반한다.
계획상 n=36, abstain=0일 때 향후 primary discordant count 경계는 Green 0~2,
Gray 3~11, Red 12~36이지만 현재 관측값은 어느 구간에도 배정할 수 없다.

V2.4는 같은 archived output에 두 측정법을 적용하는 audit이므로 Experiment pipeline의
일반적 “System A vs B McNemar”도 적용되지 않는다. 향후 실제 rating이 잠긴 뒤에야
Terra-human paired discordance를 분석할 수 있고, 그것도 RAG treatment effect McNemar로
해석하면 안 된다.

### 2.2 보존된 automatic outcome — 배경 통계일 뿐

Primary03 CSV를 다시 집계한 자동 결과는 다음과 같다.

| condition | n | correct@0.5 / @0.6 / @0.7 | generation split | mean agreement | 대표 score median (범위) |
|---|---:|---:|---:|---:|---:|---:|
| runtime | 39 | 23 / 21 / 20 | 18 | 0.607 | 0.86 (0.00~1.00) |
| length placebo | 39 | 23 / 22 / 22 | 19 | 0.598 | 0.86 (0.00~1.00) |
| blind procedural RAG | 39 | 23 / 22 / 22 | 17 | 0.598 | 0.76 (0.00~1.00) |

세 조건의 23/39 동률은 V2.4 결과가 아니라 감사 대상인 Terra outcome이다. Primary03은
incomplete prefix이고 Terra가 generation과 judge 양쪽에 관여했으므로 “RAG 효과 없음”의
증거로 사용하지 않는다.

### 2.3 이전 baseline 대비 추세

검증된 이전 문서의 변화는 다음과 같다.

| 버전 | 관찰 | 해석 한계 |
|---|---|---|
| V2.1 | B 25/58=43.1%, A 20/58=34.5%; threshold 0.6에서 순위 역전 | judge/threshold 민감성 |
| V2.2 | RAG 39/60=65.0%, runtime 19/60=31.7%, placebo 22/60=36.7% | RAG 45/60=75%가 자기 런북 회수 |
| V2.3 Primary03 | 세 조건 모두 23/39 | incomplete prefix, 사람/semantic audit 부재 |
| V2.4 현재 | package-only | 새 accuracy·효과량 없음 |

따라서 V2.4는 성능 추세의 새 점이 아니다. V2.2의 큰 격차와 V2.3의 동률 사이에서
measurement validity를 먼저 확인하기 위한 gate다.

## 3. 비판적 회고

### 3.1 구성 타당성

장점은 RAG 효과와 측정기 감사를 분리하고, correctness와 semantic construct도 별도
phase/package로 나눈 점이다. frozen ground-truth file·row·field hash, candidate read 전
reference lock, opaque ID, 별도 scanner는 사후 rubric 변경과 구조화 leakage 위험을 줄인다.

그러나 사람 reviewer가 보는 expected reference는 synthetic ground truth이며 실제
Primary03에서 관측된 절대 truth가 아니다. 향후 점수도 “현실 RCA 정확도”가 아니라
frozen synthetic rubric과 candidate의 concordance다. 동일 incident의 reference가 세
condition에 반복돼 sibling grouping과 일관성 압력을 유발할 수 있다. 현재는 사람 결과가
없으므로 이 construct가 실제로 안정적인지도 알 수 없다.

scanner 0은 semantic shortcut 0을 뜻하지 않는다. SSA 관련 survey는 token overlap 밖의
semantic contamination에서 3B 이상 `r>=.97`, 전체 `rho>=.9`의 민감도를 보고했다
([deep analysis](../docs/surveys/deep_analysis_v2_4.md)). V2.4 package scanner가 통과한 것은
구조화 marker 미검출뿐이며 L2/L3는 실제 사람 semantic audit가 필요하다.

### 3.2 내적 타당성

단일 Primary03만 사용하고 다른 revision prefix를 결합하지 않은 점, exact tree digest,
same-key byte replay, correctness-before-semantic gate는 강점이다. 초기 코드 리뷰에서 발견된
submission mutation, unanimous adjudication 변경, partial semantic publish, Markdown/metadata
scanner 누락과 training-before-release 위반은 실제 package 생성 전에 수정됐고 사람
배포·평점 오염은 없었다.

남은 위협은 다음과 같다.

1. deterministic sample은 결과를 본 뒤 seed namespace와 알고리즘을 정한 audit trail이지
   prospective random sample이 아니다.
2. representative output은 Terra majority/score를 이용해 이미 선택됐다. 36개 audit은
   generation distribution의 unbiased 표본이 아니다.
3. 108 identity/hash는 봉인됐지만 비대표 72개 본문이 없어 selection-bias sensitivity를
   실행할 수 없다.
4. OS-level network/mount/PATH isolation이 없어 0-call assurance가 `OBSERVED_ONLY`다.
5. 실제 qualified R1/R2와 선호되는 blind R3 adjudicator가 아직 없다.
6. 영속 build/replay stdout/stderr receipt가 없어 manifest 밖 실행 사건의 사후 감사성이
   제한된다.

### 3.3 외적 타당성

범위는 Primary03의 F1~F8, 단일 cluster/Online Boutique/corpus, archived Terra
representative outputs에 한정된다. F9~F12, complete 12-fault campaign, 다른 model/provider,
다른 corpus/cluster, active GitOps reconciliation, production MTTR로 일반화할 수 없다.
어떤 향후 색 판정도 Primary03을 confirmatory dataset으로 승격하지 않는다.

위키의 claim-audit 정본도 synthetic/controlled 결과를 production readiness나 MTTR로
확대하지 말고, retrieval 자기 런북과 trial contamination을 분리하라고 요구한다
([LLM RCA claim 감사 절차](</Users/yumunsang/ms/wiki/wiki/concepts/LLM RCA claim 감사 절차.md>),
[GitOps-aware 평가 프레임](</Users/yumunsang/ms/wiki/wiki/concepts/GitOps-aware LLM RCA 평가 프레임.md>)).

### 3.4 통계 타당성

현재 human n=0이므로 측정 추론은 불가능하다. 향후에도 correctness n=36은 12 incidents
안에 세 condition이 묶인 clustered sample이고 semantic n=12는 작다. κ는 prevalence에
민감하므로 raw matrix와 agreement를 먼저 봐야 하며, 20%·85%·κ 0.70은 보편 validity
cutoff가 아니라 운영 경계다. Green이 최대 2 discordance만 허용하고 3~11이 모두 Gray인
넓은 불확실성 구간이라는 점도 숨기면 안 된다.

LLM judge 문헌은 이 감사를 정당화하지만 결과를 대신하지 않는다. Zheng et al. 분석은
GPT-4 position consistency 65.0%를, Rating Roulette은 task/model별 반복 judge
Krippendorff α 0.265~0.788을 보고했다
([Judging LLM-as-a-Judge](../docs/papers/judging-llm-as-a-judge.md),
[Rating Roulette](../docs/papers/rating-roulette.md)). 이 수치는 V2.4의 예상 discordance나
Terra reliability로 전용할 수 없다.

### 3.5 대안 가설

향후 Terra-human 불일치가 나오더라도 same-model self-preference 하나로 단정할 수 없다.

1. Terra threshold 0.5와 사람 `score>=1`의 partial-correctness 정의가 다를 수 있다.
2. 사람이 실제 incident truth보다 expected mechanism/recovery 문구에 anchoring될 수 있다.
3. Terra representative selection이 human과 잘 맞거나 안 맞는 generation을 골랐을 수 있다.
4. 특정 fault/reference 난이도가 12-incident sample에서 과대표집됐을 수 있다.
5. sibling candidate를 알아본 reviewer의 상대 비교·일관성 압력이 생길 수 있다.
6. expertise, fatigue, order, training 차이가 measurement-method 차이보다 클 수 있다.
7. 높은 일치도 두 측정법이 같은 synthetic 표현에 정렬된 공통방법 편향일 수 있다.
8. L2/L3 판단도 semantic shortcut 자체보다 reviewer의 사후 유사성 과대평가일 수 있다.

지식 주입은 실제로 유용할 수 있다. Flow-of-Action은 SOP knowledge 제거 시 54.06%에서
15.39%로 하락했다([paper review](../docs/papers/flow-of-action.md)). 반대로 controlled
contamination 연구는 source-target 결합 오염이 최대 30 BLEU의 inflation을 만들 수 있음을
보였다([paper review](../docs/papers/controlled-data-contamination-impact.md)). 그러므로
“절차 지식이 강하다”와 “이 V2.3 RAG가 leakage 없이 RCA를 개선했다”는 서로 다른 명제다.

## 4. 개선 가설과 다음 checkpoint

### 1순위 — V2.4 사람 측정 완료, 새 효과 실험은 보류

**가설:** qualified R1/R2의 condition/Terra-blind 독립 판정과 disagreement-only adjudication을
수행하면 archived Terra outcome의 운영 적격성을 실제 discordance와 agreement로 판정할 수
있다.

- 데이터 근거: technical package는 준비됐지만 `human_ratings=0`, `adjudications=0`,
  `measurement_gate=NOT_EVALUATED`다.
- 방법: plan의 qualification/training/session/fatigue gate를 통과한 실제 사람 R1/R2를
  등록하고 correctness를 먼저 lock·close한다. 그 뒤 semantic qualification/package를
  release하고 독립 판정·adjudication한다. 가능하면 blind R3를 확보한다.
- 문헌 근거: LLM judge self-inconsistency와 사람 guideline 취약성 때문에 rubric·독립 원점수·
  disagreement를 함께 보존해야 한다.
- 반증: 36개에서 discordance 0~2, 안정적인 raw matrix/agreement, semantic L3=0이면
  “Terra-only가 명백히 부적격”이라는 H-V2.4는 약화된다. 그래도 RAG 효과는 입증되지 않는다.

이는 새 V2.5가 아니라 **아직 끝나지 않은 V2.4의 필수 continuation**이다. 사람 결과 없이
다음 RAG 효과 실험으로 넘어가면 이번 audit의 목적을 달성하지 못한다.

### 2순위 — generation payload 완전 보존을 단일 변경으로 검증

**가설:** 같은 12 incidents에서 representative 36개가 아니라 세 generation 전체를
사전 봉인·보존하면 representative-selection에 따른 measurement 차이를 정량화할 수 있다.

- 독립변수: audit unit을 representative-only에서 all-generation으로 바꾸는 것 하나.
- 데이터 근거: mean generation agreement 0.598~0.607, split 17~19/39, 비대표 본문
  72/108 부재.
- 선행 조건: 후속 수집 harness가 모든 generation full response를 append-only raw에 저장하고
  identity/hash와 1:1 검증해야 한다. 현재 hash에서 본문을 추정·재생성하지 않는다.
- 위치: V2.4 36-output 결과가 Gray이거나 selection bias가 중심 설명일 때 별도 사전 승인된
  sensitivity로 수행한다. outcome을 본 뒤 유리한 108 subset을 선택하지 않는다.

### 3순위 — 물리 격리와 실행 receipt 강화

**가설:** 동일 package build를 network-none/credential-unmounted/PATH-allowlist runner에서
재생하면 `OBSERVED_ONLY`를 강한 zero-call assurance로 올리면서 archive bytes를 유지할 수 있다.

- 데이터 근거: archive replay는 PASS지만 현재 isolation manifest는 host 통제 미강제를
  명시한다.
- 판정: OS-level runner 전후 4 archive hash가 같고 blocked/child/socket receipt가
  append-only로 남아야 한다.
- 성격: RCA 효과 실험이 아니라 provenance/재현성 개선이다.

## 5. 결론·한계

### 성패 판정

| 판정 대상 | 결론 |
|---|---|
| 입력·package·reconstruction 기술 무결성 | **PASS** |
| zero-call 독립 보장 | **미달; OBSERVED_ONLY로 하향된 관측 주장만 가능** |
| H-V2.4 Terra-human discordance | **NOT_EVALUATED** |
| reviewer reliability | **NOT_EVALUATED** |
| semantic L3 eligibility | **NOT_EVALUATED** |
| V2.3 RAG→RCA 개선 주장 | **판정 불가** |
| V2.4 전체 measurement 완료 | **아님 — PACKAGE_ONLY** |

기술 package는 승인 plan의 package-only 종료 조건을 충족했다. 하지만 V2.4의 연구 가설은
아직 결과가 없는 상태다. 이 분석의 가장 중요한 결론은 **“기술 산출물 완료”와
“측정 실험 완료”를 분리해야 한다**는 것이다.

### 잔여 한계

- qualified human R1/R2, 선호 R3, rating, adjudication이 없다.
- semantic package는 정당하게 sealed pending 상태이며 L0~L3 결과가 없다.
- 72개 비대표 generation의 full body가 없어 108-output sensitivity가 막힌다.
- 격리는 Python-process 관측 수준이며 host OS의 network/mount/PATH를 강제하지 않았다.
- Primary03은 F1~F8의 incomplete non-random prefix다.
- sample 설계와 representative 선택에는 각각 사후 설계와 Terra selection bias가 남는다.
- synthetic reference concordance는 production RCA truth 또는 MTTR가 아니다.
- standalone build/replay log가 없어 manifest 이외의 실행 provenance가 제한된다.

**바로 다음 checkpoint:** 실제 qualified R1/R2의 profile/training을 lock하고, correctness
36개씩 독립 평가하는 것이다. 이 단계 전에는 V2.4를 Green/Gray/Red로 부르거나,
RAG/GitOps가 RCA를 개선했다고 쓰지 않는다.

# V2.4-D 결정론적 lexical concordance 독립 결과 비평

> 분석일: 2026-09-01
>
> 분석 역할: fresh `results_critic`
>
> 판정 대상: V2.4-D exact execution chain
> `I0=594cd5d444d8b6534a724e5ed6699cbcef809150`,
> `I1=9ce797287f0f3d893318624a3e53edc7568969c7`,
> `B=bbf73284536bcbfd717a1cd71587f201433dfea8`,
> `A=2ed523eee0c887c64694dc8bf20bdbe51d133ee1`
>
> 독립성·비접근 선언: 이 분석에서는 candidate output과 ground truth의 의미 본문을 열거나,
> decode·parse·search·preview·인용하지 않았다. 실데이터 scorer와 금지된
> `tests.test_v2_4_audit`를 실행하지 않았다. 대화의 성공·실패 기대를 판정 근거로 사용하지
> 않았으며, 승인된 Revision 8 plan, exact source, Git identity, opaque commitment metadata와
> body-free INVALID receipt만 검증했다.

## 1. 데이터 검증

### 1.1 승인·freeze chain

실행 checkout에서 다음을 확인했다.

```text
$ git rev-parse HEAD
2ed523eee0c887c64694dc8bf20bdbe51d133ee1

$ git show -s --format='%H %P %s' I0 I1 B A
594cd5d444d8b6534a724e5ed6699cbcef809150 cdb9aeda7b161cb5fb9df44cb5766e30f42a61f6 V2.4 pre-gate bytecode를 격리한다
9ce797287f0f3d893318624a3e53edc7568969c7 594cd5d444d8b6534a724e5ed6699cbcef809150 실험: V2.4 입력 커밋 고정
bbf73284536bcbfd717a1cd71587f201433dfea8 9ce797287f0f3d893318624a3e53edc7568969c7 검토: V2.4 구현 안전성 승인
2ed523eee0c887c64694dc8bf20bdbe51d133ee1 bbf73284536bcbfd717a1cd71587f201433dfea8 실험: V2.4 실행 승인 고정
```

세 parent 관계의 `git merge-base --is-ancestor`는 모두 exit 0이었다. 실제 diff는 다음 exact
allowlist와 일치했다.

```text
I0..I1
A  docs/plans/input_commitment_v2_4_deterministic.json
A  docs/plans/non_informative_machine_parse_deviation_v2_4_deterministic.json

I1..B
M  docs/plans/review_v2_4_deterministic_implementation.md

B..A
A  docs/plans/approval_v2_4_deterministic.md
```

Tracked diff는 0이었다. `git status --porcelain=v1 --untracked-files=all`에는 승인 후 생성되는
execution-authorization sidecar
`docs/plans/execution_authorization_v2_4_deterministic.json` 하나만 untracked로 남았다. 이는
Revision 8 implementation review가 명시한 post-`A` external authorization 방식과 일치한다.

승인·소스 파일의 실제 SHA-256도 approval/review map과 일치했다.

| 대상 | 확인한 SHA-256 |
|---|---|
| Revision 8 plan | `3a9c7586f51bc7444ea432a933bd149f31e4f06f47d3a5383fb561407e2870f1` |
| cumulative semantic review | `842a484710461ed109a9263b387fb21fb4e78defe4a80d7daa5a818251e3b2d8` |
| final implementation review | `5c7da59b96fe19df870ad3e06d2259f3d832d0fd3398e67085088dda69f8ef34` |
| tracked approval | `3e0fcc2d9f81becbab0760659bcbed5b6366338d2bf3e75eee5c12bf6d4b154b` |
| scorer | `09e41c11cac74ecee1b2b88270a09d5d31675b263d4152118359af420fb38130` |
| runner | `f0bcc06251da7a1d26c0b25387cd95032408e071245d978116c7704d8ea31d32` |

### 1.2 입력 계수와 scoring gate 도달

Candidate body를 읽지 않고 exact `I1`의 opaque commitment를 JSON metadata로 검증한 실제 출력은
다음과 같다.

```text
{'raw_count_field': 117,
 'raw_files_len': 117,
 'raw_paths_unique': 117,
 'csv_sha256': '5fd2c1c52c8c37462f7f47eecb248a5a147166165c1cf2495d6e9b43956f8c5b',
 'commitment_sha256': '48d4d9e6e652b05cf7321a80889dea9b963cc1cd0ea7a73d06690ab070ea0995'}
```

이는 commitment 안의 raw JSON count가 117이고, 117개 path가 모두 unique이며, CSV identity가
승인값과 일치한다는 metadata-level 검증이다. 실행이 남긴 reason이 preflight 오류가 아니라
`UNSUPPORTED_NEGATION`이라는 사실도 중요하다. Exact `A`의 `run.py`는 다음 순서로 실행한다.

```text
repository/approval/hash gate
→ raw commitment 117-entry gate
→ CSV 117-row identity gate
→ raw:CSV 117:117 mapping gate
→ selected 12 incidents × 3 conditions = 36 identity gate
→ scorer.score(...)
→ unresolved negation에서 RunInvalid("UNSUPPORTED_NEGATION")
```

따라서 exact 승인 source가 실행됐다는 전제에서, body-free receipt의 reason은 commitment 117,
CSV/raw 117:117 및 selected 36 identity gate를 통과해 첫 hidden scoring에 도달했다는
control-flow evidence다. 이는 36개 결과 row가 생성됐다는 뜻이 아니다. 첫 hidden scoring이
중단됐으므로 완전한 36-row score set은 존재하지 않는다.

### 1.3 INVALID receipt와 공개 산출물 부재

실제 receipt를 strict JSON으로 읽고 exact key set을 검사한 결과는 다음과 같다.

```text
$ stat -f '%N type=%HT size=%z mode=%Sp' /private/tmp/.v24d-output-2ed523e.invalid.json
/private/tmp/.v24d-output-2ed523e.invalid.json type=Regular File size=84 mode=-rw-------

$ shasum -a 256 /private/tmp/.v24d-output-2ed523e.invalid.json
8281d230761b981a6d5e98c035ce4a54e7a180169f93c2b1357b448942447869
  /private/tmp/.v24d-output-2ed523e.invalid.json

$ stat -f 'birth=%SB mtime=%Sm' -t '%Y-%m-%dT%H:%M:%S%z' \
    /private/tmp/.v24d-output-2ed523e.invalid.json
birth=2026-09-01T22:06:32+0900 mtime=2026-09-01T22:06:32+0900

{'candidate_text_emitted': False,
 'reason': 'UNSUPPORTED_NEGATION',
 'status': 'INVALID'}
```

Ephemeral receipt의 exact bytes는 다음 durable evidence path에도 보존됐다.

```text
$ shasum -a 256 \
    results/evidence_v2_4_deterministic/invalid_receipt_8281d230761b981a.json
8281d230761b981a6d5e98c035ce4a54e7a180169f93c2b1357b448942447869
  results/evidence_v2_4_deterministic/invalid_receipt_8281d230761b981a.json
```

따라서 durable copy는 ephemeral source와 byte-identical하다. Nonsemantic execution audit도
`results/evidence_v2_4_deterministic/execution_audit_2ed523e.json`에 보존됐으며 SHA-256는
`29a4e4875e8c890b8e13a23f16700e714a6f4b5bc24050e2040135bb15e2e282`다.

여기서 `candidate_text_emitted=false`는 **현재 V2.4-D scoring attempt가 candidate text를
receipt/public output으로 내보내지 않았음**을 뜻한다. 이는 historical machine-only parse의
`process_access_zero=false`를 뒤집지 않는다. 또한 current scorer process가 candidate bytes를
읽지 않았다는 뜻도 아니다. 실제로 scoring이 시도됐으므로 current process access는 있었다.

공개·tracked 결과를 확인한 실제 출력은 다음과 같다.

```text
results/experiment_results_v2_4_deterministic.csv ABSENT
results/analysis_v2_4_deterministic.md ABSENT          # 이 분석 작성 전
/private/tmp/v24d-output-2ed523e ABSENT
/private/tmp/.v24d-output-2ed523e.invalid.json type=Regular File size=84

$ find /private/tmp -maxdepth 1 -type d \
    -name '.v2_4_deterministic_hidden-*' -print | wc -l
0

$ find artifacts/v2_4_deterministic -mindepth 1 -maxdepth 1 \
    -type d -print | wc -l
0
```

따라서 result CSV, summary, paired table, score trace, final/replay release root 및 hidden partial은
공개되지 않았다. Result CSV는 “0행 CSV”가 아니라 **파일 자체가 absent**이므로 row count는
`NA`다. 빈 결과 파일을 만들어 0행으로 바꾸면 안 된다.

### 1.4 로그와 원본 불변성의 증거 범위

성공 run이 만드는 public `execution.log`는 존재하지 않는다. Durable nonsemantic audit
`results/evidence_v2_4_deterministic/execution_audit_2ed523e.json`은 actual invocation이 승인된
고정 Python interpreter와 `-I` isolated flag를 사용했지만, preregistered `env -i` allowlist 대신
parent process environment를 상속했다고 기록한다. 이는 Revision 8 §12 Step 4의 canonical
environment 계약에서 벗어난 **execution-protocol deviation**이다. 또한 exact `A`에서 실행한
pre-execution test transcript, full invocation stdout/stderr와 exact nonzero exit code는 보존되지
않았다. 따라서 synthetic/static tests가 exact `A`에서 실행 직전에 다시 통과했는지를 독립적으로
재검증할 수 없고, receipt 생성 전후의 전체 execution을 transcript로 재생할 수도 없다.

이 편차와 evidence 결손은 실행 준수 주장을 제한하지만 이번 scientific status를 바꾸지는 않는다.
Inherited environment 아래에서도 approved scorer가 실데이터 scoring에 도달해 사전등록된
`UNSUPPORTED_NEGATION`으로 fail-close했고, score/result/public release는 생성되지 않았기 때문이다.
따라서 valid effect result로 승격할 근거는 없으며 `INVALID`가 유지된다. 실행 시각과 오류의 독립
증거는 durable receipt의 explicit `+0900` filesystem timestamp·exact bytes·SHA-256, post-`A`
authorization sidecar,
execution audit와 exact source control flow에 한정된다. 이 evidence가 실제 실행 전 과정을
cryptographically 증명한다고 과장할 수 없다.

원본 CSV/raw JSON/ground truth에 대한 tracked diff는 0이고, scorer/runner source에는 이 입력을
쓰기 모드로 여는 경로가 없다. 또한 승인된 commitment digest와 실제 execution이 scoring gate까지
도달한 사실은 실행 시 source identity가 승인값과 일치했다는 근거다. 그러나 이 분석은 금지된
semantic body를 다시 열거나 원본 전체를 재해시하지 않았으므로, “원본 불변” 주장의 범위는
tracked diff, 승인 commitment, passed input gate와 read-only source inspection까지다.

## 2. 통계 분석

통계 분석은 **미실행이며 전 항목 `NA`**다.

Revision 8은 candidate missing, parse/schema failure, unsupported language/negation 또는 다른 gate
실패를 0점으로 대체하지 않고 run 전체를 `INVALID`로 두도록 사전등록했다. 이번 run에는 완전한
12-pair JLC-D 결과가 없으므로 다음 값을 계산·추정·인용해서는 안 된다.

| 항목 | 상태 | 이유 |
|---|---|---|
| RAG/placebo 조건별 JLC-D rate | `NA` | public 36-row result absent |
| fault별·카테고리별 CM/FLM/MCA/RA/FULL | `NA` | complete score set absent |
| paired risk difference `RD` | `NA` | 12 valid pairs absent |
| discordant counts `b`, `c` | `NA` | 12 valid pairs absent |
| one-sided exact McNemar/binomial `p` | `NA` | valid discordance table absent |
| Clopper–Pearson interval | `NA` | valid `b,c` absent |
| paired bootstrap interval | `NA` | valid paired vector absent |
| 이전 baseline 대비 추세 | 판정 금지 | 측정 outcome과 valid sample이 없음 |

`UNSUPPORTED_NEGATION` candidate를 오답 0으로 impute하거나, 그 row를 제외한 complete-case 결과를
primary로 바꾸거나, relaxed/FULL/runtime comparison을 대신 primary로 승격하면 missingness 계약과
result-independent change control을 동시에 위반한다. 따라서 이번 결과로 “RAG 효과가 없다”,
“placebo와 동률이다”, “RAG가 역전됐다”라는 통계 문장을 만들 수 없다.

## 3. 비판적 회고

### 3.1 구성 타당성

측정 대상은 semantic RCA correctness가 아니라 component/fault/mechanism의 사전 고정 영어 lexical
concordance인 `JLC-D`다. Revision 8도 CM을 culprit localization이 아닌 token mention, FLM을 fault
understanding이 아닌 label mention으로 제한한다. 이번 invalidation은 frozen output 중 적어도 한
scoring 경로를 finite negation instrument가 유효한 binary score로 변환하지 못했음을 보여준다.
즉 deterministic evaluator는 judge stochasticity를 제거했지만 실제 corpus에 대한 construct
coverage를 보장하지 못했다.

이 현상만으로 matcher가 틀렸다고 단정할 수는 없다. Fail-close는 모호한 문장을 임의로 positive나
negative로 분류하지 않는 보수적 선택이다. 반대로 lexical grammar가 유효한 semantic paraphrase를
놓치거나 condition별 문체 차이를 효과처럼 반영할 위험도 그대로 남는다. 이번 round는 그
trade-off를 score가 아니라 `INVALID`로 표면화했다.

### 3.2 내적 타당성

강점은 exact `I0→I1→B→A` freeze, approval-before-open, input commitment, candidate-open 전 hash
gates, hidden two-run과 single-root publication 계약이다. 실제 실패에서도 partial result를
공개하지 않고 body-free receipt만 남겨, 실패한 prefix가 효과 추정에 섞이는 것을 막았다.

한계는 세 가지다.

1. 2026-08-31 generic regression의 historical machine-only parse는
   `process_access_zero=false`다. 승인 waiver는 `text_egress=false`,
   `v2_4_d_execution=false`, `output_derived_tuning=false`라는 제한된 historical disposition일 뿐,
   pristine access-zero를 복원하지 않는다.
2. 현재 run에서는 실제 V2.4-D scoring이 시도됐다. 다만 public receipt에는
   `candidate_text_emitted=false`이고 score·candidate body·matched text가 없다. Historical waiver의
   `v2_4_d_execution=false`와 current attempted execution을 혼동하면 안 된다.
3. `UNSUPPORTED_NEGATION` reason code는 candidate text나 arm score는 아니지만, 입력에서 파생된
   저대역폭 진단 정보다. 이를 근거로 grammar를 반복 수정·probe하면 reason-code oracle을 통한
   data-contingent instrument tuning이 된다.

또한 semantic text 비접근 조건에서는 실제 표현이 승인 grammar 밖이었는지, 승인 grammar 안인데
parser가 false-positive했는지 구분할 수 없다. 따라서 현재 증거는 contract-compliant fail-close를
지지하지만 implementation defect의 부재를 절대적으로 증명하지는 않는다.

### 3.3 외적 타당성

설령 valid result가 나왔어도 대상은 V2.3 Primary03의 비무작위 incomplete prefix, 선택 12 incidents,
F1~F8, 단일 Online Boutique 환경과 frozen representative outputs다. 다른 fault, cluster, 모델,
언어, production incident, MTTR 또는 복구 성공으로 일반화할 수 없다. 이번에는 valid lexical
outcome조차 없으므로 외적 주장의 범위는 더 좁다. 오직 “이 승인된 instrument가 이 frozen corpus를
완전 채점하지 못하고 안전하게 닫혔다”까지만 관찰했다.

### 3.4 통계 타당성

사전 계획의 표본 자체가 12 pairs로 작아, valid하더라도 `c=0`에서 `b≥5`가 필요한 낮은 검정력과
넓은 불확실성이 예정돼 있었다. 현재는 complete pair가 없으므로 low-power 문제가 아니라
estimand가 관찰되지 않은 상태다. 어떤 p-value·CI·rate도 계산하지 않는 것이 통계적으로 올바른
처리다. Failure prefix, 내부 임시 row 또는 조건 일부를 복구해 분석하면 publication gate와 paired
design을 깨뜨린다.

### 3.5 대안 가설

현재 관찰을 설명할 수 있는 대안은 다음과 같고, semantic body 비접근 상태에서는 구분할 수 없다.

- 실제 candidate가 승인된 finite negation grammar 밖의 표현을 포함했다.
- 표현은 승인 grammar 안이지만 runtime classifier가 false-positive했다.
- 특정 condition의 문체가 negation을 더 자주 사용해 instrument support failure와 treatment가
  결합됐다. 이는 RCA 품질 차이와 다른 메커니즘이다.
- 대표 출력 선택 또는 upstream schema/문체가 selected 12의 support failure를 유발했다.
- Strict lexical support를 넓히면 invalid는 줄지만 false-positive concordance가 늘어날 수 있다.

Receipt는 어느 candidate/row/arm이 원인인지 공개하지 않으며, 이 분석도 code order로 그 identity를
추론하거나 노출하지 않는다. 원인 identity를 알아내려는 반복 실행도 허용하지 않는다.

### 3.6 repo 선행연구 대비 위치

`docs/papers/rcaeval.md`가 확인한 RCAEval은 3개 microservice system, 11 fault types, 735 cases에
coarse root-cause service와 fine root-cause indicator ground truth를 제공한다. 이는 구조화된
component/fault ground truth로 자동 평가하는 방향을 뒷받침한다. 그러나 RCAEval은 본 실험의
free-text negation grammar, JLC-D semantic validity 또는 condition별 문체 불변성을 검증하지 않는다.
따라서 공개 benchmark의 존재가 이번 matcher coverage를 보증하지 않는다.

`docs/papers/judging-llm-as-a-judge.md`에는 GPT-4 judge의 position-swap consistency 65.0%,
MT-Bench non-tie human agreement 85%와 tie·position-inconsistent를 포함한 first-turn agreement 66%가
기록돼 있다. `docs/papers/rating-roulette.md`에는 MT-Bench 3회 self-reliability가 모델별
Krippendorff's alpha 0.265·0.507·0.563이고, 가장 높은 모델도 3회 완전 일치 case가 61.3%였다고
기록돼 있다. 이 선행연구는 single LLM judge를 피하고 결정론적 측정기를 찾은 동기를 지지한다.
그러나 stochastic judge를 제거하는 것과 측정 구성개념의 coverage·정확성을 확보하는 것은 별개다.
이번 `INVALID`는 평가 비결정성을 줄인 대신 보수적 lexical instrument가 실제 입력을 포괄하지 못할
수 있다는 부족점을 직접 드러냈다.

## 4. 개선 가설

### 4.1 1순위 — V2.4-D2의 one-shot, total negation instrument revision

> **개선 가설:** Candidate body·row·arm·score를 계속 비공개로 유지한 채, public linguistic
> sources와 synthetic counterexample만으로 unresolved concept-associated negation을 항상
> deterministic하게 처리하는 versioned total policy를 사전 고정하면, reason-code oracle를 반복
> 조회하지 않고 frozen 36 outputs 전체에 대해 재현 가능한 score를 생성할 수 있다.

이 가설은 원 V2.4-D의 효과 가설과 다르다. 우선순위가 높은 이유는 현재 blocker가 effect size가
아니라 instrument의 totality이기 때문이다. 다음 변경 통제는 필수다.

1. 원 V2.4-D와 receipt를 **영구 `INVALID`**로 보존한다. In-place ontology/scorer 변경이나 원
   result의 소급 교정은 금지한다.
2. 현재 알려진 `UNSUPPORTED_NEGATION` reason code가 input-derived adaptation trigger였음을 새 plan,
   review, analysis에 공개한다. 이를 outcome-independent였다고 표현하지 않는다.
3. Candidate body, ground-truth semantic text, failing row/incident/condition/arm과 어떤 score도 열거나
   추론하지 않는다. Real-input 재실행을 중단해 reason-code oracle의 추가 query를 0으로 고정한다.
4. Fresh 설계자가 public linguistic source, 이미 승인된 ontology contract와 **synthetic-only**
   counterexample으로 일반 정책을 설계한다. 실제 phrase에 맞춘 alias·grammar patch는 금지한다.
5. 가능한 설계는 모든 unresolved concept-associated negator를 clause boundary까지 보수적으로
   suppress하는 total policy다. 이는 invalid를 score로 바꾸지만 acceptance set과 construct가
   달라지므로 `JLC-D2`처럼 새 metric/version으로 명명하고 false-negative 위험을 사전 공개한다.
   유한 grammar를 확장하는 대안도 가능하지만, 외부 근거와 완결된 synthetic matrix가 먼저
   고정돼야 한다.
6. 새 plan·ontology·scorer·tests를 commit/hash하고 fresh semantic·implementation review와 사용자
   승인을 받은 뒤 **one-shot full 36-output run**만 수행한다. 재실패 시 다시 probe하지 않고 새
   version도 `INVALID`로 닫는다.
7. 새 결과의 methodology disposition에는
   `reason-only data-contingent instrument adaptation`을 분리 기록한다. Candidate text와 arm score가
   비공개였다는 이유만으로 원 Rev8 confirmatory 지위를 소급 부여하지 않는다. 보수적으로는 새
   결과를 sensitivity/exploratory로 해석하고, confirmatory 주장이 필요하면 사전 고정된 외부
   dataset에서 별도 prospective replication을 수행한다.

Implementation defect를 주장하려면 real candidate를 열어 맞춤 수정하지 말고, 독립적인 synthetic
counterexample에서 승인 grammar가 false-positive invalid를 내는 것을 먼저 재현해야 한다. 재현되지
않으면 현재 실패는 parser bug가 아니라 measurement support failure로 유지한다.

### 4.2 후속 우선순위

- **2순위: prospective external replication.** V2.4-D2 instrument를 frozen external benchmark에
  먼저 적용해 grammar coverage와 structured ground-truth concordance를 검증한다.
- **3순위: blinded human semantic calibration.** Candidate egress를 허용하는 별도 exploratory
  protocol에서 lexical false-positive/false-negative를 측정한다. 이는 현 confirmatory corpus를
  수정하는 근거로 소급 사용하지 않는다.

## 5. 결론·한계

### 5.1 최종 판정

```text
primary_status = INVALID
reason = UNSUPPORTED_NEGATION
candidate_text_emitted = false
```

H-V2.4-D, 즉 동일 12 incidents에서 blind procedural RAG가 length placebo보다 JLC-D를 높이는지는
**지지할 수도 반박할 수도 없다.** 현재 결과는 `NO_EVIDENCE`나 `REVERSED`가 아니다. 완전한
36-row score, 12 paired outcomes, summary와 replay release가 생성되지 않았기 때문이다.

실행 동작 자체는 Revision 8이 요구한 **expected fail-close**와 일치한다. 승인 밖 negation을 임의
score로 바꾸지 않았고, partial outcome을 공개하지 않았으며, body-free INVALID receipt만 남겼다.
따라서 현재 관찰만으로 implementation defect라고 판정하지 않는다. 동시에 semantic body를 보지
않았으므로 parser false-positive 가능성도 완전히 배제하지 못한다.

### 5.2 허용되는 주장과 금지되는 주장

허용되는 주장은 다음뿐이다.

- Exact 승인·hash/input gate 뒤 current V2.4-D scoring이 시도됐다.
- Scorer가 `UNSUPPORTED_NEGATION`으로 fail-close했다.
- Current public receipt의 `candidate_text_emitted`는 false다.
- Result CSV·summary·partial/public release가 없으므로 효과는 판정 불가다.
- Historical deviation의 `process_access_zero`는 계속 false다.

다음 주장은 금지한다.

- “RAG가 효과가 없다/있다”, “placebo와 동률이다”, “RAG가 역전됐다.”
- “Candidate 접근 0” 또는 “완전한 blinding.”
- “Current process가 candidate를 읽지 않았다.”
- “Unsupported phrase가 실제로 무엇이었다” 또는 failing row/arm identity 추정.
- “Parser bug가 확정됐다” 또는 “candidate가 승인 문법을 위반했다.”

### 5.3 잔여 한계와 round closure evidence

Receipt reason은 text/score egress는 아니지만 향후 설계에 영향을 줄 수 있는 input-derived 진단
정보다. Exact persisted execution transcript와 exact `A` pre-execution test transcript가 없고,
actual invocation은 `-I`를 사용했지만 preregistered `env -i` allowlist를 사용하지 않았다. 따라서
receipt 생성 전후의 전체 command·exit 흐름과 canonical environment 준수를 독립 재생할 수 없다.
이 분석은 semantic 원본도 재해시하지 않았다. 또한 결과가 valid했더라도 lexical construct,
12-pair small-n, non-random prefix와 단일 demo cluster의 한계가 남았을 것이다.

V2.4 round를 종료하려면 최소한 다음 증거와 handoff가 필요하다.

1. Body-free INVALID receipt는
   `results/evidence_v2_4_deterministic/invalid_receipt_8281d230761b981a.json`에 exact SHA-256
   `8281d230761b981a6d5e98c035ce4a54e7a180169f93c2b1357b448942447869`로 durable 보존됐다. 이 분석도
   함께 보존하되 receipt에 candidate text나 partial score를 추가하지 않는다.
2. `A/B/I0/I1`, authorization identity, interpreter, `-I`, `env -i` 미사용, transcript 결손과
   public/partial release absence는
   `results/evidence_v2_4_deterministic/execution_audit_2ed523e.json`에 기록됐다. 보존되지 않은
   pre-execution test/full execution transcript나 exact exit code를 발명하지 않는다.
3. `results/experiment_changes_v2_4.md`에 append-only INVALID execution과 result nonpublication을
   기록하고 version/status 및 논문 주장 경계를 갱신한다.
4. Step 6의 다음 experiment goal 문서, 새 세션 `[GOAL]` prompt, TickTick `ai-continue` handoff를
   모두 만든다.
5. Feature branch commit/push, 한국어 PR, 사용자 승인 merge까지 완료한다.

이 조건이 끝나기 전 상태는 **`RUN_INVALID — ROUND_CLOSURE_PENDING`**이다. 원 V2.4-D를 valid effect
result로 복구하는 작업은 남아 있지 않으며, 후속 작업은 공개된 reason-only adaptation을 가진 새
instrument version 또는 별도 prospective replication이어야 한다.

# V2.4-D 결정론적 채점 구현 독립 검토

> 검토일: 2026-08-31
>
> exact implementation candidate `I`:
> `e86e26b4eb00aca899f42eab008132c0664a5cfc`
>
> 최종 판정: **FAIL — P0 7개, P1 4개. candidate scoring 및 bundle `B` 진행 금지.**

## 1. 독립성·검토 범위

이 검토에서는 Primary03 candidate output JSON/CSV의 `identified_fault_type`, `root_cause`,
`remediation` 본문을 열거나 decode/parse/search/preview/출력하지 않았다. V2.4-D scorer/full run과
`tests.test_v2_4_audit` real-input regression도 실행하지 않았다. candidate output, matched text,
condition별 score를 보지 않았으며 synthetic fixture, plan/review, ontology/code/test와 hash metadata만
사용했다.

검토 계약은 `AGENTS.md`, `CLAUDE.md`, `rules/experiment-pipeline.md`, `rules/data-safety.md`,
`experiment_plan_v2_4_deterministic.md` revision 4 및 누적 semantic review의 Revision 4 최종
PASS다.

별도 worktree `/tmp/thesis-v24d-review.XzPb8r`를 만들어 exact `I`를 detached checkout했다.

```text
$ git rev-parse HEAD
e86e26b4eb00aca899f42eab008132c0664a5cfc
$ git status --short --branch
## HEAD (no branch)
$ git status --porcelain=v1
<empty>
```

검토 종료 시 이 temporary worktree를 제거했다.

## 2. 봉인 hash

아래 Git blob SHA-256는 `git cat-file blob I:path | shasum -a 256`, filesystem SHA-256는 detached
worktree의 파일 bytes에 `shasum -a 256`을 적용했다. 둘은 모두 일치했다.

| implementation target | Git blob OID | blob/filesystem SHA-256 |
|---|---|---|
| `docs/plans/experiment_plan_v2_4_deterministic.md` | `1eeb41195ff48cef9bd5fea86190e194a65a381f` | `24385717f3de42f3288ca44e80ab040d498fb1a5cabf59ec7ac43424e10145db` |
| `docs/plans/review_v2_4_deterministic.md` | `b44a2705851818b115aba2b58e2f85544b254ab0` | `2c0013d0dc2695c366536d19f35ecf63bb6120c18abdc46c80e74c673cffd689` |
| `docs/plans/input_commitment_v2_4_deterministic.json` | `6e5a4cdb0a0950c27b12fc42ea0767da975ab22f` | `c4d9bd1b0ee54a23e1f29a4f6483efe4f051126d5a8020277cad9bf764462085` |
| `experiments/v2_4_deterministic/ontology_v1.json` | `b048e10b8e9e4b0ac03264d9e4329bc1f8db36e4` | `456bc7c562b5c1896fa37041f4f6ceda6184994be77af9c2a55b3daee086035d` |
| `experiments/v2_4_deterministic/commit_inputs.py` | `316f5b5ce8905e7bcfccf0718a174c4c3998867e` | `dfa38c09e183e94421f8eee66510caa140857735febaf7518173e705d0ebaf94` |
| `experiments/v2_4_deterministic/scorer.py` | `397132a90515eab77f12af6cc7a867f4847660ca` | `33530d3348cbcd731f995414158e9875d3f37e1a785e8e096732ea893ee9433f` |
| `experiments/v2_4_deterministic/analyze.py` | `3bf804ff9f584c6a506fb5ae7f162e0dfab02613` | `b72040f8f0abe757ad842bae903238701c41049dc07381bea375814f06474be7` |
| `tests/test_v2_4_deterministic.py` | `1a10ff6c11e11dea953761d1fd8b919d595e4a34` | `812af9de4e3545b247662cfb9a7d2b62429327a3a219873f5d1fc37d45eac665` |

semantic review의 외부 계산 filesystem SHA-256는
`2c0013d0dc2695c366536d19f35ecf63bb6120c18abdc46c80e74c673cffd689`다. review 파일 내부에는
자기 SHA가 없으며 plan의 non-self-reference 계약과 일치한다.

실제 full-run 경로지만 target 목록에서 누락된 파일의 별도 hash는 다음과 같다.

| non-target implementation file | Git blob OID | blob/filesystem SHA-256 |
|---|---|---|
| `experiments/v2_4_deterministic/run.py` | `745059327124b415e60df8d18b2046f8a3daeb28` | `b9cdeb747afc5c5937093a20a2e4f55b1ce81c0c5d00fecc6c2a6d114d42d29a` |
| `experiments/v2_4_deterministic/build_ontology.py` | `d3618444f910f2586d2ade385d5fa7f519aea600` | `00ab8f970f5859b7e66df8e3e17db05926e60d2ae197ebeb9c9220f739a881ed` |
| `experiments/v2_4_deterministic/__init__.py` | `4f41104d187ceaeedbd576a3c6de418d3b4ce9b0` | `f0fb79df74c533d1634777b223e8330b45ae775050677a3c3530355e14b95816` |

## 3. 실행한 허용 검증

| 명령 | exit/result |
|---|---|
| `python3 -m unittest tests.test_v2_4_deterministic` | exit 0, 25 tests, `OK` |
| `python3 -m py_compile` + V2.4-D Python 파일 7개와 test 파일 | exit 0 |
| `python3 experiments/v2_4_deterministic/build_ontology.py --ontology experiments/v2_4_deterministic/ontology_v1.json` | exit 0, `ONTOLOGY_CHECK_PASS`, incidents 12 |
| recorded Python 3.11.15로 `-I -m unittest tests.test_v2_4_deterministic` | exit 1, `ModuleNotFoundError: tests` |
| recorded Python 3.11.15로 `-I tests/test_v2_4_deterministic.py` | exit 1, `ModuleNotFoundError: experiments` |

commitment는 117 raw entry, 정렬·unique path, stored/recomputed commitment digest 일치가 확인됐다.
기록된 tool SHA는 실제 `commit_inputs.py`와 일치했고, 기록된 interpreter binary SHA
`216061c513cab74dec6698580a9d51c5ab8ae8dc3d90f3ae88a57bbc4a9b1a92` 및 Python 3.11.15도 현재
파일과 일치했다. 이는 provenance field의 내부 일관성 확인이지 redaction/비열람의 cryptographic
proof는 아니다.

## 4. P0 findings

### P0-1 — ontology가 revision 4 byte semantics와 일치하지 않고 validator가 const를 강제하지 않음

- plan §3의 `additionalProperties:false` schema에는 instance-level `token_predicates`와
  `negation.syntax`가 없지만 ontology에는 두 필드가 추가됐다. 이 representation 변경은 별도
  semantic review를 받지 않았다.
- F1 MCA의 `M_MEMORY_LIMIT`은 plan의 `memory limit / memory cgroup limit / container memory limit`
  중 `memory limit` 하나만 구현돼 plan 난이도 표의 11 aliases가 실제 9 aliases가 됐다.
- validator는 `ontology_version`, negation 배열의 exact 값·순서, incident ID pattern/trial 범위,
  group/path ID pattern을 const/schema로 강제하지 않는다. synthetic mutation에서 version 변경,
  negation token 역순, arbitrary incident ID가 모두 load됐다.
- ontology duplicate JSON key도 거부하지 않는다. 따라서 현재 `ONTOLOGY_CHECK_PASS`는 approved
  ontology의 exact validation이 아니다.

이 결함은 acceptance set과 metric을 바꿀 수 있으므로 P0다.

### P0-2 — finite negation grammar가 구현되지 않음

scorer는 grammar parse/consumption 대신 concept 주변 heuristic을 사용한다.

- `rule out the network policy`는 plan의 `PRE_RULE`로 suppress돼야 하지만 match됐다.
- `network policy has been ruled out`/`have been ruled out`은 plan의 `POST_RULE`이지만 match됐다.
- `memory limit is not generally relevant`는 unresolved marker로
  `UNSUPPORTED_NEGATION`이어야 하지만 positive match됐다.
- `neither cpu throttling nor memory limit`은 승인된 NEG/PRE_COORD 조합인데 ontology의 별도
  `unsupported_markers` 때문에 INVALID가 됐다.
- `NOT_ONLY`는 C1을 parse하지 않고 앞의 `not only`와 뒤의 아무 `but` 존재만으로 exception 처리한다.

positive/RA contradiction에 동일한 finite span classification을 적용한다는 계약, consumed span,
unresolved marker/scope fail-close가 충족되지 않는다.

### P0-3 — candidate schema fail-close 계약 위반

빈 `identified_fault_type`/`root_cause`와 literal U+FFFD replacement character가 validation을
통과했다. remediation 전체 1,024-token 상한도 별도로 계산하지 않는다. plan §7이 요구한 empty
string/replacement/total-token fail-close와 다르므로 run 유효성에 직접 영향을 준다.

### P0-4 — approval/freeze/hash gate가 실행 코드로 강제되지 않음

- full-run entrypoint인 `run.py` 자체가 plan §9.1 implementation target 목록과 approval hash
  schema에서 빠졌다. `I→B` target equality로 runner 변경을 봉인할 수 없다.
- runner는 current `HEAD == execution_commit`, exact `A^=B`, approved bundle `B`, I→B/B→A
  one-file diff, semantic review blob OID를 확인하지 않는다. `approved_bundle`과
  `execution_commit`은 non-empty string인지 검사한 뒤 사용하지 않는다.
- Primary03 고정 CSV SHA-256
  `5fd2c1c52c8c37462f7f47eecb248a5a147166165c1cf2495d6e9b43956f8c5b`를 runner가 비교하지 않는다.
- commitment의 `commitment_sha256`와 provenance는 runner에서 required/exact 검증되지 않는다.
- plan/review/approval/analyzer/test/commitment-tool/interpreter hash와 actual git commit이 manifest의
  required identity로 완결되지 않는다.

승인 파일과 input commitment를 함께 새로 만들면 unrelated tree/CSV/runner도 통과할 수 있어
approval-before-open의 순서만 맞고 승인 대상 identity는 고정되지 않는다.

### P0-5 — replay 전 결과를 publish함

`run_campaign()`은 첫 output directory를 atomic rename한 뒤 반환하고, CLI가 그 후 두 번째 run을
수행한다. replay mismatch나 second-run failure가 나도 첫 score/summary/trace가 이미 공개된다.
plan은 두 run의 canonical hash가 같을 때만 result report를 release하도록 요구한다. 첫 manifest도
`replay_result=PENDING_SECOND_REPLAY` 상태로 남고 replay success 뒤 갱신되지 않는다.

### P0-6 — opaque commitment의 no-follow/TOCTOU/redaction provenance가 구현되지 않음

`commit_inputs.py`는 final path의 `lstat` 후 일반 `Path.open()`을 사용한다. ancestor symlink,
`O_NOFOLLOW`, fd `fstat`, before/after identity·rehash를 확인하지 않으므로 lstat/open 사이 교체와
symlink ancestor를 봉인하지 못한다. `redaction_test: PASS`는 실행 검증 결과가 아니라 코드가
상수로 기록한다. unit test도 stdout/stderr에 synthetic secret이 없는지만 확인하며 output
provenance의 exact argv/exit/error path와 source mutation을 공격하지 않는다.

### P0-7 — required synthetic/static gate의 test adequacy 부족 및 `python -I` 실행 불가

25개 test method가 있어도 plan의 22개 범주를 충족하지 않는다.

- ontology negation constants의 추가/누락/재정렬 거부와 난이도 표 exact count test가 없다.
- coordinated negation은 두 concept 모두의 span suppression을 assert하지 않고, `NOT_ONLY`도 C1/C2,
  consumed marker, unresolved count를 assert하지 않는다.
- PRE/POST grammar의 filler, `has been`/`have been`, unsupported residual marker 반증 fixture가 없다.
- absence test는 ontology의 `polarity=absence_assertion` matcher가 아니라 affirmative helper를 쓴다.
- empty/replacement/total remediation token, CSV/GT/projection/ontology/scorer/plan hash mismatch,
  identity duplicate/missing/unexpected, exact 50,000-bootstrap bytes, shuffled-input byte equality가
  충분히 검증되지 않는다.
- approval-before-open test는 malformed approval 한 경우만 보며 commit chain/hash binding을 검증하지
  않는다.
- plan §12의 recorded interpreter + `python -I` 재실행은 두 표준 invocation 모두 import 단계에서
  실패한다.

따라서 green suite가 P0-1~P0-6을 놓치는 false assurance다.

## 5. P1 findings

1. `safe_metadata()`는 `rglob("*.json")`만 세므로 raw tree의 non-JSON regular file과 일부
   unexpected entry를 거부하지 않는다. commitment tool도 같은 방식이다.
2. invalid gate에서 plan이 요구한 `INVALID` receipt를 남기지 않고 exception만 발생한다.
3. run artifact 이름이 plan의 `manifest.json/input_manifest.json/score_trace.jsonl/paired_table.csv/
   summary.json/execution.log/replay_manifest.json` 계약과 일부 맞지만 첫 run의 replay manifest 및
   최종 manifest 상태 갱신이 분리돼 있고 tracked 36-row result publication은 runner가 완결하지 않는다.
4. exact McNemar known answers와 stdlib CP/bootstrap 구현 자체는 정적 검토상 타당하다. 다만 test는
   `b=c=0`, exact CP known values, fixed 50,000-replicate expected serialization과 input shuffle의
   독립 known answer를 고정하지 않는다.

## 6. 기존 `tests.test_v2_4_audit` real-input 실행의 절차 편차 판정

정적 코드상 `RealInputIntegrationTests`는 `load_primary03()`에서 117 raw JSON을 UTF-8 decode/JSON
parse하고, `selected_rows()`에서 representative output을 object로 비교하며, package build에서
선택 candidate의 세 필드를 구조화했다. 따라서 그 test가 candidate `I` 전에 실행됐다면
**process-level candidate parse는 0이 아니었다.** 향후 provenance에 “candidate 접근 0”이라고
기록하면 사실과 다르다.

다만 제공된 실행 이력대로 candidate 본문이 stdout/stderr 또는 agent/human context로 노출되지
않았고 V2.4-D scorer/ontology가 호출되지 않았다면, 이 machine-only parse는 ontology alias,
threshold 또는 arm score를 구현자에게 전달하는 정보 경로가 없다. V2.4 human-audit package의
기존 generic parser 검증이지 V2.4-D 결과 적합화도 아니다.

**독립 causal 판정:** 이 편차 하나만으로 `EXPLORATORY_ONLY`나 outcome `INVALID`로 강등할 필요는
없고 confirmatory 지위를 유지할 수 있다. 단, 이를 “비접근”으로 숨기지 말고 승인 전에
`NON_INFORMATIVE_MACHINE_PARSE_DEVIATION`으로 기록하며 다음 네 사실을 명시해야 한다.

1. 실행 명령·시각·commit과 stdout/stderr digest,
2. candidate body가 stdout/stderr/agent/human context로 전달되지 않았다는 operator attestation,
3. V2.4-D scorer/ontology/alias extraction/score가 실행되지 않았다는 정적·로그 근거,
4. 해당 machine parse 이후 ontology/metric에 observed-output-derived 변경이 없다는 diff provenance.

이는 causal anti-overfitting 관점의 비중대 편차 판정이다. revision 4 문구를 process access까지
절대 0으로 해석해 waiver 없이 운용한다면 formal gate는 실패하므로 그 경우에는 `INVALID`가 맞다.
본 review의 권고는 위 transparent deviation record를 승인 provenance에 포함해 causal blinding을
보존하는 것이다. 현재 구현의 P0 FAIL은 이 별도 편차 판정과 무관하게 scoring을 막는다.

## 7. 최종 gate 표

| gate | 판정 |
|---|---|
| exact `I`, detached clean evidence | PASS |
| candidate output 미열람/미채점 | PASS |
| semantic review external SHA 및 target hashes | PASS |
| ontology-plan byte semantics/provenance/count | **FAIL** |
| scorer single source/negation/absence/RA/schema | **FAIL** |
| runner approval-before-open | PASS only for ordering |
| runner exact commit/hash/mapping/schema/no-text/atomic/replay | **FAIL** |
| statistics implementation | PASS with test P1 |
| commitment provenance/tool/interpreter hash | PASS for recorded hashes, **FAIL** for safety/redaction proof |
| synthetic/static test adequacy and isolated replay | **FAIL** |

**최종 판정: FAIL.** P0가 하나라도 남으면 plan에 따라 implementation review PASS를 기록하거나
bundle `B`, 사용자 승인 `A`, candidate scoring으로 진행할 수 없다. 다음 checkpoint는 candidate
본문을 계속 보지 않은 상태에서 P0를 synthetic counterexample로 수정하고, `run.py`를 포함한 새
implementation candidate commit `I2`를 봉인한 뒤 fresh implementation review를 다시 받는 것이다.

## 8. Revision 7 full implementation 재검토

> 재검토 시각: 2026-08-31T16:44:24Z
>
> code-only candidate `I0`:
> `4843b35f26ae65a4229bb1b1ea25c204e609142e`
>
> full implementation candidate `I1`:
> `2ad0fa22898ce4854422cde6ee41700c1660179c`
>
> 최종 판정: **FAIL — P0 5개, P1 1개. PASS approval 및 bundle `B` 진행 금지.**

### 8.1 독립성·candidate nonaccess 선언

이 재검토는 별도 detached worktree
`/tmp/thesis-v24d-full-review.mNM6qR`의 exact `I1`에서 수행했다. Primary03 실제 candidate
JSON/CSV body를 decode, parse, search, preview 또는 출력하지 않았다. V2.4-D full/scorer real run과
기존 `tests.test_v2_4_audit` real-input test도 실행하지 않았다. 실제 입력에 대해서는 Git에 봉인된
commitment의 opaque `relative_path,size,sha256` map과 CSV digest/count만 검증했다. candidate value,
matched text, arm score와 outcome은 보지 않았다.

```text
$ git rev-parse HEAD
2ad0fa22898ce4854422cde6ee41700c1660179c
$ git rev-parse HEAD^
4843b35f26ae65a4229bb1b1ea25c204e609142e
$ git status --short --branch
## HEAD (no branch)
$ git status --porcelain=v1
<empty>
```

검토 계약은 `experiment_plan_v2_4_deterministic.md` revision 7, cumulative semantic review의
Revision 7 PASS, 최초 implementation FAIL의 P0-1~P0-7 closure다.

### 8.2 I0→I1 chain과 불변성

```text
$ git cat-file -e I0:docs/plans/input_commitment_v2_4_deterministic.json
exit 1 (required absence)
$ git diff --name-status --no-renames I0..I1
A  docs/plans/input_commitment_v2_4_deterministic.json
A  docs/plans/non_informative_machine_parse_deviation_v2_4_deterministic.json
$ git diff --name-only I0..I1 | wc -l
2
```

`I1^ == I0`이고 exact `A/A` two-file addition이다. raw diff에도 위 두 `000000 → blob` addition만
있다. 따라서 plan, semantic review와 여덟 code/test blob을 포함한 allowlist 밖 모든 `I0` blob은
`I1`에서 불변이다.

### 8.3 I1 전체 target hash

Git blob SHA-256는 `git cat-file blob I1:path` bytes, filesystem SHA-256는 detached checkout
bytes로 독립 계산했다. 전 target에서 두 SHA-256가 일치했다.

| I1 target | Git blob OID | blob SHA-256 | filesystem SHA-256 |
|---|---|---|---|
| `docs/plans/experiment_plan_v2_4_deterministic.md` | `51794ca049abc353956f94a7ab6cc944fd2a7a81` | `33435f87ce56c9bcef38b6ea3bb985e305ac02b5a1ebebdb4af69e9a241b4381` | `33435f87ce56c9bcef38b6ea3bb985e305ac02b5a1ebebdb4af69e9a241b4381` |
| `docs/plans/review_v2_4_deterministic.md` | `0f90140649357a9762c1b96b22ee5a221cdbf11e` | `14826d4d0a35da53e4a8603759916b667bfcc844d3c027ca2a1abd0d8636602d` | `14826d4d0a35da53e4a8603759916b667bfcc844d3c027ca2a1abd0d8636602d` |
| `docs/plans/input_commitment_v2_4_deterministic.json` | `83f3a5c744513d6f060a59dfd6bee75877d63cb1` | `8e29d1febbaa4ddeb86f814ec885e5cebedfc1008316e484ddfeccd86ee55e90` | `8e29d1febbaa4ddeb86f814ec885e5cebedfc1008316e484ddfeccd86ee55e90` |
| `docs/plans/non_informative_machine_parse_deviation_v2_4_deterministic.json` | `cab9e3eab3ae573bb8f3338694c8f58e19374285` | `8efada27f3f567f2cce9f5181f3e349c82344f22ba01443f4812607c01211785` | `8efada27f3f567f2cce9f5181f3e349c82344f22ba01443f4812607c01211785` |
| `experiments/v2_4_deterministic/ontology_v1.json` | `e4624a40f3f98acd85020c956fab167962d28904` | `ae9956f9a6a89523b2a6f57f1eaa707a132b9763a7c7a1b909ab7ee4376b2bd7` | `ae9956f9a6a89523b2a6f57f1eaa707a132b9763a7c7a1b909ab7ee4376b2bd7` |
| `experiments/v2_4_deterministic/__init__.py` | `4f41104d187ceaeedbd576a3c6de418d3b4ce9b0` | `f0fb79df74c533d1634777b223e8330b45ae775050677a3c3530355e14b95816` | `f0fb79df74c533d1634777b223e8330b45ae775050677a3c3530355e14b95816` |
| `experiments/v2_4_deterministic/build_ontology.py` | `715bfb0dd32827c8fc9420937f54b919ad364144` | `8aa31eade0992e03f5aa941782822468bd37f08c931070b3334b73a4575dd3b4` | `8aa31eade0992e03f5aa941782822468bd37f08c931070b3334b73a4575dd3b4` |
| `experiments/v2_4_deterministic/commit_inputs.py` | `e8d71651fb8b7380d0242e1a640b8eb96abac67d` | `622a0ab991a8c61a4a54f47b542a671cd0bbab89343e050b97d3d290097f9ae1` | `622a0ab991a8c61a4a54f47b542a671cd0bbab89343e050b97d3d290097f9ae1` |
| `experiments/v2_4_deterministic/scorer.py` | `b80b1a4aae1b6ed3c3281ed64ce23a6c502d7a08` | `57bf95239fc4af9b52ad2b7d7b878ddc264ef3b830ebfd47fe153a1aaeb365f7` | `57bf95239fc4af9b52ad2b7d7b878ddc264ef3b830ebfd47fe153a1aaeb365f7` |
| `experiments/v2_4_deterministic/analyze.py` | `3bf804ff9f584c6a506fb5ae7f162e0dfab02613` | `b72040f8f0abe757ad842bae903238701c41049dc07381bea375814f06474be7` | `b72040f8f0abe757ad842bae903238701c41049dc07381bea375814f06474be7` |
| `experiments/v2_4_deterministic/run.py` | `fbbca193df2a578201166dde4e722f7406f92b5f` | `017aad5eb15af23165ff63c314b4e7e23a166d47a9023526a1af31c51548ee1a` | `017aad5eb15af23165ff63c314b4e7e23a166d47a9023526a1af31c51548ee1a` |
| `tests/test_v2_4_deterministic.py` | `1f91416698e5e569f0d253e58c8739725b22be97` | `798a2db522e670bbd680e59387ad72716998bee70eaa2ec7515769f7e2336680` | `798a2db522e670bbd680e59387ad72716998bee70eaa2ec7515769f7e2336680` |

semantic review external filesystem SHA-256는
`14826d4d0a35da53e4a8603759916b667bfcc844d3c027ca2a1abd0d8636602d`다.

### 8.4 I0 safety receipt와 새 commitment/deviation provenance

외부 receipt
`artifacts/v2_4_deterministic/i0_safety_receipt_4843b35.json`의 SHA-256는
`492afcb0d1ec1e234fd7711e92c166007d403a886a72b1cf096aea794ce3ea19`다. receipt는 exact `I0`,
`PASS`, real source open count 0, candidate text egress false를 기록한다. 여덟 safety target 각각의
receipt blob OID/SHA-256를 `I0:path`, detached filesystem bytes와 재계산해 모두 exact 일치했다.

새 commitment의 검증된 opaque metadata는 다음과 같다.

```text
file SHA-256              8e29d1febbaa4ddeb86f814ec885e5cebedfc1008316e484ddfeccd86ee55e90
commitment_sha256 stored  48d4d9e6e652b05cf7321a80889dea9b963cc1cd0ea7a73d06690ab070ea0995
commitment_sha256 recomputed from producer base envelope
                           48d4d9e6e652b05cf7321a80889dea9b963cc1cd0ea7a73d06690ab070ea0995
raw_count/raw map length   117 / 117, sorted and unique
entry manifest stored/recomputed
                           05d5e002519307549714b8e309dfd042a82cd43483d571834c2675a3acf79835
fixed CSV SHA-256          5fd2c1c52c8c37462f7f47eecb248a5a147166165c1cf2495d6e9b43956f8c5b
tool blob OID              e8d71651fb8b7380d0242e1a640b8eb96abac67d
tool SHA-256               622a0ab991a8c61a4a54f47b542a671cd0bbab89343e050b97d3d290097f9ae1
reviewed_i0                4843b35f26ae65a4229bb1b1ea25c204e609142e
safety receipt SHA-256     492afcb0d1ec1e234fd7711e92c166007d403a886a72b1cf096aea794ce3ea19
legacy source drift        EXACT_MATCH
```

provenance의 tool blob/SHA는 실제 `I0` tool과 같고, `I0→I1`에서도 tool blob은 불변이다. CSV
size/digest와 117-entry opaque map은 deprecated envelope
`590e8e006d5adc449bb8e0bdd12b0beaaf7bc8197015dd65a7131525cf90ca64`의 legacy map과 exact
일치한다. 새 envelope digest를 old digest와 비교하지 않았다.

deviation file SHA-256는
`8efada27f3f567f2cce9f5181f3e349c82344f22ba01443f4812607c01211785`다. 네
`evidence_material` 문자열의 SHA-256는 각각 해당 `evidence` 값과 일치했다.

### 8.5 실행한 허용 검증

| 명령 | 결과 |
|---|---|
| recorded Python 3.11.15 `-I tests/test_v2_4_deterministic.py` | exit 0, 52 tests, `OK` |
| recorded Python 3.11.15 `-I -m py_compile` + V2.4-D Python 6개, init, test | exit 0 |
| recorded Python 3.11.15 `-I experiments/v2_4_deterministic/build_ontology.py --ontology .../ontology_v1.json` | exit 0, `ONTOLOGY_CHECK_PASS`, incidents 12 |
| recorded Python 3.11.15 `-I experiments/v2_4_deterministic/commit_inputs.py --self-test-redaction` | exit 0, `REDACTION_SELF_TEST_PASS`, sentinel match 0 |
| recorded Python 3.11.15 `-I experiments/v2_4_deterministic/run.py --self-test --ontology .../ontology_v1.json` | exit 0, `SELF_TEST_PASS`, candidate text opened false |
| synthetic producer `commit_inputs.commit()` envelope → runner `_commitment_gate()` | `RunInvalid: INPUT_COMMITMENT_MISMATCH` |
| scorer loader mutation: token predicate expansion | **ACCEPTED** (fail-open) |
| scorer loader mutation: `post_rule` 변경 | **ACCEPTED** (fail-open) |
| scorer loader mutation: incident order reversal | **ACCEPTED** (fail-open) |
| scorer loader mutation: clause-boundary order reversal | **ACCEPTED** (fail-open) |
| finite negation counterexample `memory limit is not generally relevant` | **positive match true**; expected `UNSUPPORTED_NEGATION` |

### 8.6 P0 findings

#### P0-R7-1 — runtime ontology loader가 revision 7 exact const/count를 강제하지 않음

`build_ontology.py`의 정본 ontology check는 PASS하지만 실제 scorer가 호출하는
`scorer.load_ontology()`는 다음 result-changing mutation을 모두 허용했다.

- `MEMORY_LIMIT_EXCEEDED_V1`에 임의 acceptance phrase 추가
- `negation.syntax.post_rule` 변경
- incident order reversal
- clause-boundary order reversal

loader는 `_NEGATION_CONST` 일부만 exact 비교하고 token predicate exact 9-sequence/order,
`negation.syntax` exact 값, normalization exact 배열/order, incident exact identity/order와 난이도 표
inventory를 강제하지 않는다. 승인 ontology bytes가 hash gate로 동결돼도 loader 자체가 plan의
single-source/static-validator 계약을 구현하지 않았고, mutation test도 이를 놓친다. 최초 P0-1은
미해결이다.

#### P0-R7-2 — unresolved finite negation fail-close가 여전히 구현되지 않음

`memory limit is not generally relevant`는 승인 grammar 밖 negation이므로
`INVALID_UNSUPPORTED_NEGATION`이어야 하지만 scorer는 `memory limit` positive match로 처리했다.
`_unsupported_negation()`은 `unsupported_prefixes`만 검사하고 ontology의
`unsupported_markers`를 사용하지 않으며, `_suppressed()`가 소비하지 않은 `not` marker를 clause
단위로 fail-close하지 않는다. PRE/POST/coordinated happy-path test가 PASS해도 “소비 후 남은 marker”
계약은 충족되지 않는다. 최초 P0-2는 미해결이다. 반면 empty/replacement/total-remediation-token
candidate schema fail-close는 synthetic test와 정적 검토에서 closure됐다.

#### P0-R7-3 — commitment producer와 real runner consumer가 내부적으로 불호환

실제 commitment를 열지 않고 동일 producer가 만든 synthetic envelope로 반증했다.

1. producer는 top-level `entry_manifest_sha256`를 기록하지만 `_commitment_gate()` allowlist에는
   해당 key가 없어 즉시 `INPUT_COMMITMENT_MISMATCH`다.
2. producer CSV map은 `id_sha256,size,sha256`지만 runner는 exact `path,size,sha256`를 요구한다.
3. producer provenance는 `reviewed_i0`를 기록하지만 `_repository_gate()`는
   `reviewed_code_candidate`를 요구한다. 실제 I1 commitment에는 후자가 없다.

따라서 향후 exact `B→A` approval이 만들어져도 candidate source open 전 repository gate 또는
commitment gate에서 반드시 INVALID가 된다. chain/diff/hash 검사는 대체로 구현됐지만 봉인된
commitment를 실제로 소비할 수 없으므로 최초 P0-4와 P0-6 provenance closure는 실패다.

#### P0-R7-4 — historical machine-parse deviation의 formal evidence가 불완전함

deviation record는 `process_access_zero=false`, `candidate_text_egress=false`,
`scorer_execution_zero=true`를 투명하게 기록하고 evidence material 자체의 네 digest도 맞는다.
그러나 material은 exact original stdout/stderr byte streams가 보존되지 않았다고 명시한다. 실행
시각과 parse 당시 exact git commit, stdout/stderr/log digest가 없고, parse commit→I0→I1 exact
file/diff provenance도 일반 attestation으로 대체됐다. 이는 plan §9.3의 필수 evidence 1과 4를
충족하지 않는다. runner는 네 evidence digest가 64-hex인지 확인할 뿐 material과 digest 관계나
필수 provenance 내용을 검증하지 않는다.

독립 causal 해석으로는 현재 attestation이 text egress나 scorer 실행을 시사하지 않으므로
“정보성 parse였다”고 단정할 근거도 없다. 그러나 confirmatory hard gate는 네 evidence 전부를
요구하므로 현재 상태를 검증된 `NON_INFORMATIVE_MACHINE_PARSE_DEVIATION`으로 승인할 수 없다.

```text
MACHINE_PARSE_CAUSAL_DISPOSITION=FORMAL_GATE_FAIL_UNVERIFIED_NON_INFORMATIVE
PROCESS_ACCESS_ZERO=false
HUMAN_AGENT_TEXT_EGRESS=0_ATTESTED_NOT_REPRODUCIBLY_VERIFIED
V2_4_D_SCORER_EXECUTION=0_ATTESTED
OBSERVED_OUTPUT_DERIVED_CHANGES=0_ATTESTED_WITHOUT_EXACT_DIFF_PROVENANCE
CONFIRMATORY_STATUS=INVALID_UNTIL_REQUIRED_EVIDENCE_OR_EXPLICIT_PROTOCOL_CHANGE
```

#### P0-R7-5 — 52-test green suite가 위 P0를 놓침

fixed isolated suite는 52/52 PASS지만 다음 direct contract test가 없다.

- scorer loader의 predicate/syntax/normalization/incident order exact mutation rejection
- 소비되지 않은 negation marker의 clause-level fail-close
- real producer envelope를 real `_repository_gate`/`_commitment_gate`가 받아들이는 end-to-end test
- actual I1 commitment provenance key와 runner expected key equality
- deviation evidence material의 required fields/hash recomputation

synthetic full e2e fixture는 legacy adapter shape으로 commitment를 바꿔 runner를 통과시키므로 actual
producer-consumer 불일치를 숨긴다. 최초 P0-7은 미해결이다.

### 8.7 P1 finding

`run.safe_metadata()`는 `root.rglob("*.json")`만 순회한다. root 바로 아래가 아닌 nested JSON과
non-JSON regular file을 명시적으로 거부하지 않는다. commitment tool은 exact 117 direct entries를
검사하지만 runtime source tree가 이후 extra non-JSON/nested entry를 얻어도 runner가 무시할 수 있어
plan의 “모든 unexpected entry 거부”와 다르다. scoring input map 자체가 같다면 outcome을 바꾸지
않으므로 이 재검토에서는 P1로 분류한다.

### 8.8 최초 P0-1~P0-7 closure 표

| 최초 P0 | Revision 7 판정 | 근거 |
|---|---|---|
| P0-1 ontology exact semantics/const/count | **FAIL** | runtime loader가 acceptance/syntax/order mutation 허용 |
| P0-2 finite negation grammar | **FAIL** | unresolved `not` marker positive match |
| P0-3 candidate schema fail-close | PASS | empty/replacement/total remediation 상한 closure |
| P0-4 approval/freeze/hash runner | **FAIL** | chain hash는 강화됐으나 actual commitment provenance/envelope를 소비 못함 |
| P0-5 hidden replay atomic release | PASS | 두 hidden run hash/file equality 뒤 단일 atomic release; second failure/mismatch 비공개 |
| P0-6 commitment safety/provenance | **FAIL** | no-follow/TOCTOU/redaction과 receipt binding은 PASS, runner provenance key 불일치 |
| P0-7 synthetic/static adequacy | **FAIL** | 52 tests가 세 functional incompatibility와 deviation evidence gap을 놓침 |

### 8.9 최종 gate와 승인 권고

| gate | 판정 |
|---|---|
| exact I0/I1 parent, I0 commitment absence, exact A/A diff | PASS |
| detached clean, all other blobs immutable | PASS |
| I1 12-target blob/filesystem hash map | PASS |
| I0 receipt SHA/8 target identity | PASS |
| commitment internal digest, tool/I0/receipt/legacy opaque map | PASS |
| deviation file/material digest integrity | PASS |
| ontology runtime exact const/count | **FAIL** |
| finite negation/schema | **FAIL** (schema subset PASS) |
| runner chain/hash plus actual commitment consumption | **FAIL** |
| hidden replay atomic release | PASS |
| machine-parse causal evidence hard gate | **FAIL** |
| synthetic/static test adequacy | **FAIL** |

**Revision 7 full implementation 판정은 FAIL, P0 PASS approval recommendation은 0이다.**
`B`, 사용자 승인 `A`, actual candidate scoring으로 진행하면 안 된다. 다음 checkpoint는 candidate
본문을 계속 비접근 상태로 유지하면서 ontology loader exact validator, unresolved negation fail-close,
producer/runner 단일 commitment schema·provenance를 수정하고 위 반증 test를 추가한 새 code-only
candidate를 봉인하는 것이다. machine-parse evidence는 plan의 exact 요구를 충족할 수 있는 원본이
없다면, 이를 숨기거나 현재 digest로 대체하지 말고 사용자 승인 아래 protocol status를 명시적으로
변경해야 한다.

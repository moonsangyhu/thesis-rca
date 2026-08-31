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

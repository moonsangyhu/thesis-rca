# V2.4 실험 변경 이력

### 1. Primary03 무호출 측정 감사 가설 고정 — 2026-08-30

- **수정 에이전트**: @Codex
- **증상/문제**: V2.3은 완결 campaign이 없어 RAG 효과를 판정할 수 없었고, 보존 prefix도 same-model Terra judge와 미실시 semantic shortcut audit에 의존했다. 자동 점수의 타당성을 확인하지 않고 fresh main campaign을 반복하면 잘못된 outcome을 더 정밀하게 재생산할 위험이 있었다.
- **원인**: V2.3 계획의 human-primary calibration과 procedure semantic audit가 운영 attrition 전에 완료되지 않았다. lexical scanner 0건은 의미론적 shortcut 부재를 증명하지 않으며, generator와 judge가 같은 requested model을 사용해 correlated evaluation error 가능성이 남았다.
- **수정 내용**: 모든 이전 결과 CSV를 Python으로 파싱하고 Primary03 117 rows의 조건별 threshold·generation split·paired discordance를 재계산했다. 정답 3건·오답 3건 raw를 질적으로 읽고, 39개 blind procedure를 동결 Chroma와 provenance에서 재구성해 source/masked/additional hash 불일치 0건을 확인했다. V2.4의 1차 가설을 36 representative outputs의 blinded dual-human outcome audit로 고정하고 semantic L0~L3 screen을 자료 적격성 gate로 분리했다. outcome-blind hash 층화 규칙과 선택된 12 incidents를 구현 전에 사전 기록했으며, 새 LLM/K8s 호출은 허용하지 않았다.
- **수정 파일**: `docs/surveys/deep_analysis_v2_4.md:1`, `results/experiment_changes_v2_4.md:1`
- **상태**: 분석 완료 — 상세 experiment plan과 독립 방법론 리뷰 승인 전 package 구현 금지. 기존 CSV/raw/artifact/ground truth 수정 0, LLM/API/Codex/Copilot 호출 0, K8s mutation/fault injection 0.

### 2. 측정 감사 상세 계획과 독립 P0 비평 반영 — 2026-08-30

- **수정 에이전트**: @experiment-planner, fresh @hypothesis-reviewer, @Codex
- **증상/문제**: 초기 V2.4 분석은 36-output human audit의 방향을 제시했지만 measurement method를 독립변수로 오해할 여지, n=36에서 20% Wilson gate의 실제 정수 의미, correctness 이후 semantic reference가 합의판정을 역오염할 순서, Chroma/HMAC/scanner/0-call 격리의 실행 계약이 상세히 고정되지 않았다.
- **원인**: 저비용 triage라는 목적과 통계·자료보안·reviewer workflow를 하나의 검증 가능한 protocol로 아직 변환하지 않았고, 초기 계획 초안은 Step 1/Step 2 뒤 중복 사용자 승인을 요구했다.
- **수정 내용**: 조작 독립변수 없음과 Terra-human paired discordance 하나를 primary estimand로 고정했다. n=36에서 Green 0~2, Gray 3~11, Red 12~36의 Wilson 정수 gate와 abstain/incident-cluster bootstrap을 사전 명시했다. correctness adjudication을 완전 lock·close한 뒤 semantic package를 배포하도록 순서를 교정하고, Chroma quiescence·byte-equivalent reconstruction, phase별 scanner, canonical JSON/HMAC replay, network-none/credential-unmounted execution isolation을 구현 gate로 만들었다. 108 generation identity 선봉인, reviewer qualification·피로 통제, package-only/measurement-complete 상태 분리도 반영했다. fresh reviewer는 P0 8개를 재검증해 8 PASS/0 FAIL, 최종 `approve plan`을 기록했다. Step 3 진입은 plan/review hash bundle에 대한 사용자 단일 명시 승인 뒤로 제한했다.
- **수정 파일**: `docs/plans/experiment_plan_v2_4.md:1`, `docs/plans/review_v2_4.md:1`, `results/experiment_changes_v2_4.md:12`
- **상태**: 설계 완료·승인 대기 — plan SHA-256 `65ce766364f57c1fd2a8fbbf829cd50ba55cdb7d788ad1123a37667c713dcf63`, review SHA-256 `d16b1aea52bbe863d234cba2741a4784606f39c4102cee003bf0a35bd22aed64`. 미해결 비차단 dependency는 qualified R3 adjudicator 확보 여부와 Step 3의 실제 isolation/replay 검증이다. 구현·dry-run·Chroma open/copy·package 생성·사람 채점 0.

### 3. V2.4 Step 3 승인 provenance 고정 — 2026-08-31

- **수정 에이전트**: @Codex
- **증상/문제**: 승인된 plan/review bundle과 실제 구현 허가의 연결이 대화에만 남으면 이후 package가 어떤 protocol을 기준으로 생성됐는지 재현할 수 없다.
- **원인**: 계획 승인 이후 Step 3 진입 전에 사용자 지시, branch/commit, 문서 hash를 묶은 저장소 내 승인 기록이 없었다.
- **수정 내용**: 사용자의 `v2.4 실험 완료해` 지시를 단일 명시 승인으로 기록하고 승인 시각, base commit, plan/review SHA-256, 계속 적용되는 0-call·0-K8s·원본 불변·human score 비생성 경계를 고정했다.
- **수정 파일**: `docs/plans/approval_v2_4.md:1`
- **상태**: 승인 기록 완료 — 사람 reviewer가 없으면 완료 주장을 `PACKAGE_READY_AWAITING_HUMAN_REVIEW`로 제한한다.

### 4. Zero-call 측정 감사 harness와 실제 package 생성 — 2026-08-31

- **수정 에이전트**: @experiment, fresh @code-reviewer, @Codex
- **증상/문제**: Primary03의 Terra 자동 correctness와 사람이 판단한 RCA correctness의 불일치를 측정하려면 reviewer blinding, phase 순서, 입력 불변성, archive leakage, replay를 실제 파일 수준에서 보장하는 offline harness가 필요했다.
- **원인**: 기존 artifact에는 대표 output과 자동 점수는 있지만 독립 human measurement lifecycle과 immutable commitment가 없었다. 초기 구현은 frozen 제출 변조, adjudication 변조, 부분 publish, 불완전 scanner, semantic training 전 sample 공개를 독립 공격 리뷰에서 차단하지 못했다.
- **수정 내용**: outcome-blind 12-incident selector, 36-output correctness package, 12-block semantic package, canonical HMAC identity/order, Chroma byte reconstruction, recursive archive scanner, full-source fingerprint replay, phase-specific reviewer qualification, atomic close/release/rollback, 50,000회 incident-cluster bootstrap analyzer를 구현했다. 독립 리뷰의 P0를 모두 수정하고 V2.4 28 tests와 V2.3 179 regression tests를 통과했다. 실제 audit package를 absent path에 원자적으로 생성하고 4 archives byte replay, correctness 36행×2, sealed semantic 12행×2, mapping 36, generation seal 108, 공개 semantic archive 0을 검증했다.
- **수정 파일**: `.gitignore`, `experiments/v2_4/`, `tests/test_v2_4_audit.py`, `docs/issues/experiment_issues_v2_4.md`, `results/experiment_changes_v2_4.md`
- **상태**: 기술 package 완료·human measurement 대기 — audit ID `v2-4-primary03-audit-20260831`, `zero_call_assurance=OBSERVED_ONLY`, observed external/K8s calls 0, 동일 audit replay PASS. 인간 rating/adjudication 0이므로 measurement gate와 RAG/RCA 효과는 `NOT_EVALUATED`; 비대표 generation 72개 본문 부재로 108-output sensitivity는 fail-closed 상태다.

### 5. 독립 결과 비평과 V2.4 human-review handoff — 2026-08-31

- **수정 에이전트**: fresh @results-critic, @Codex
- **증상/문제**: 기술 package 완료를 V2.4 측정 가설 완료나 RAG→RCA 효과로 오인할 위험이 있고, 다음 session이 새 효과 실험으로 건너뛸 수 있었다.
- **원인**: 실제 human rating/adjudication이 0건이라 primary discordance, reviewer reliability, semantic L3와 Green/Gray/Red를 계산할 관측값이 없다.
- **수정 내용**: fresh results critic이 Primary03 117행/117 raw/39 incidents, ledger, input/Chroma digest, archive 36·12 record, 108 generation seal, 4 archive commitment/replay를 독립 재검증하고 `results/analysis_v2_4.md`에 필수 5개 섹션과 타당성 비평을 작성했다. 다음 checkpoint를 새 V2.5 효과 실험이 아닌 V2.4 qualified human measurement continuation으로 고정하고, 새 session [GOAL]과 TickTick `ai-continue` handoff를 생성했다.
- **수정 파일**: `results/analysis_v2_4.md:1`, `docs/plans/next_experiment_goal_v2_5.md:1`, `results/experiment_changes_v2_4.md`
- **상태**: Step 5·6 package-only handoff 완료 — technical package PASS, zero-call `OBSERVED_ONLY`, H-V2.4·semantic eligibility·RAG→RCA `NOT_EVALUATED`. TickTick task ID `6a94bf8a8f0861e0f0ffa43a`; qualified R1/R2가 없으면 현재 상태에서 멈춘다.

### 6. 공개 benchmark 기반 결정론적 측정 전환 가설 고정 — 2026-08-31

- **수정 에이전트**: @Codex
- **증상/문제**: V2.4 기술 package는 완성됐지만 qualified human reviewer를 확보하지 못해 36개 frozen output의 correctness와 `RAG가 RCA를 개선하는가`를 판정할 수 없었다.
- **원인**: 기존 protocol의 primary outcome이 dual-human rating과 adjudication에 의존하며, 사람을 대체할 AI judge는 평가 순환과 추가 호출 문제 때문에 사용할 수 없었다.
- **수정 내용**: Cloud-OpsBench·RCAEval·OpenRCA·AIOps Challenge 2025의 공개 구조화 RCA 평가 계약을 조사하고, 기존 Primary03 ground truth만으로 component·fault family·mechanism·remediation을 field-isolated exact concept matcher로 평가하는 H-V2.4-D를 고정했다. primary 비교는 동일 12 incidents의 blind procedural RAG 대 length placebo paired `JRA-D`이며, ontology·scorer·tests·plan을 candidate output 열람 전에 commit하는 anti-overfitting gate와 exact paired test를 명시했다. 새 모델/API/K8s 호출과 기존 결과 수정은 금지했다.
- **수정 파일**: `docs/surveys/deep_analysis_v2_4_deterministic.md:1`, `results/experiment_changes_v2_4.md`
- **상태**: 심층분석 완료·상세 계획 대기 — 기존 human V2.4 질문은 폐기하지 않고 `AWAITING_REVIEW`로 보존하며, 결정론적 측정은 별도 addendum·독립 방법론 리뷰·사용자 승인 전 실행하지 않는다.

### 7. V2.4-D 결정론적 채점 상세 계획 사전등록 — 2026-08-31

- **수정 에이전트**: @experiment-planner, @Codex
- **증상/문제**: H-V2.4-D의 방향은 고정됐지만, 자유서술을 binary RCA outcome으로 바꾸는 exact ontology·부정 처리·field isolation·통계·freeze 순서가 구현 가능한 수준으로 정의되지 않았다.
- **원인**: 공개 benchmark의 CA/FA/JRA 계약만으로는 본 실험의 mechanism과 remediation, paraphrase, 모순 표현, 12-pair small-n 판정을 자동으로 결정할 수 없다.
- **수정 내용**: candidate output 본문을 열지 않은 상태에서 12 incidents의 component·fault·mechanism·remediation positive path와 contradiction group, JSON schema, NFKC/token/negation 규칙, synthetic-only tests 20범주, opaque input commitment, exact one-sided paired test와 descriptive sensitivity, fail-closed missingness, clean-checkout replay, result-independent change control과 DoD를 상세 계획으로 고정했다. 기존 human plan은 수정하지 않았다.
- **수정 파일**: `docs/plans/experiment_plan_v2_4_deterministic.md:1`, `results/experiment_changes_v2_4.md`
- **상태**: Step 1 완료·Step 2 독립 비평 대기 — candidate output 본문 접근 0, scorer 실행 0, 결과 생성 0, 외부 모델/API/K8s 호출 0.

### 8. V2.4-D 최초 방법론 비평의 P0 승인 거부 — 2026-08-31

- **수정 에이전트**: fresh @methodology-reviewer, @Codex
- **증상/문제**: 최초 계획의 lexical matcher가 정답 ontology를 전사했더라도 component mention을 localization으로 해석하고, 일부 fault·negation·remediation 표현을 비대칭적으로 판정할 위험이 있었다.
- **원인**: 자유서술 `root_cause`에는 culprit 전용 field가 없고, FA에 mechanism alias와 다른 7 family 일괄 contradiction이 섞였으며, 3-token negation·ASCII regex boundary·remediation multi-item 결합·선택적 secondary test·implementation 이전 freeze review가 충분히 엄격하지 않았다.
- **수정 내용**: candidate output을 열지 않은 fresh reviewer가 ground truth와 plan만으로 17개 P0 gate를 검토했다. exact paired test, MCA core, missingness와 주장 경계는 통과했지만 component 구성, FA 대칭성, DNF, negation, regex, multiplicity, 2단계 freeze gate를 FAIL로 기록하고 Step 3 승인을 거부했다. 실패 리뷰를 보존하고 plan 수정·재검토를 다음 checkpoint로 고정했다.
- **수정 파일**: `docs/plans/review_v2_4_deterministic.md:1`, `results/experiment_changes_v2_4.md`
- **상태**: 수정 요구 — candidate output 본문 접근 0, scorer 실행 0, 결과 생성 0. 모든 P0가 PASS하기 전 구현·실데이터 채점 금지.

### 9. V2.4-D semantic plan revision 4 승인 권고 — 2026-08-31

- **수정 에이전트**: @experiment-planner, fresh @methodology-reviewer, @Codex
- **증상/문제**: 최초 계획과 revision 2·3에는 component localization 과장, fault alias 비대칭, negation 검증 공백, implementation review freeze 틈과 review self-hash 자기참조가 순차적으로 발견됐다.
- **원인**: 자유서술 lexical matcher의 구성개념과 candidate 접근 전 commit/review/approval 순서를 동시에 엄밀하게 봉인해야 했으며, 최초 계약은 이 두 층을 충분히 분리하지 못했다.
- **수정 내용**: primary를 `JLC-D=CM∧FLM∧MCA`로 낮춰 RCA/JRA 호환 주장을 철회하고 FLM을 canonical orthographic mention으로 제한했다. raw regex와 broad contradiction을 제거하고 finite negation·unsupported fail-close, same-item RA, secondary inference 0, GT projection hash, exact `I→B→A` freeze chain을 고정했다. review 자체 SHA는 파일 외부 provenance에서만 기록하도록 자기참조도 제거했다. 동일 fresh reviewer가 누적 실패 기록을 보존한 채 revision 4를 재검토해 P0 18 PASS/0 FAIL로 semantic plan 승인을 권고했다.
- **수정 파일**: `docs/plans/experiment_plan_v2_4_deterministic.md:1`, `docs/plans/review_v2_4_deterministic.md:1`, `results/experiment_changes_v2_4.md`
- **상태**: Step 2 완료·implementation candidate `I` 대기 — plan SHA-256 `24385717f3de42f3288ca44e80ab040d498fb1a5cabf59ec7ac43424e10145db`, review SHA-256(외부 보고) `2c0013d0dc2695c366536d19f35ecf63bb6120c18abdc46c80e74c673cffd689`; candidate 본문 접근/채점 0.

### 10. V2.4-D implementation candidate와 입력 commitment 생성 — 2026-08-31

- **수정 에이전트**: @implementation-worker, @implementation-handoff-worker, @Codex
- **증상/문제**: 승인된 lexical concordance 계획을 실제로 재현하려면 ontology 단일 정본 scorer, fail-closed 입력 gate, paired statistics, immutable input commitment와 atomic replay runner가 필요했다.
- **원인**: 최초 구현은 ontology provenance가 불완전했고 scorer에 중복 hardcode가 있었으며 paired bootstrap이 pair를 깨고 36행 primary validation이 runtime 때문에 항상 실패하는 결함이 있었다. full publish/replay 경로도 없었다.
- **수정 내용**: 12-incident static ontology에 모든 axis/path/matcher provenance를 전개하고 scorer의 semantic hardcode를 제거했다. finite negation, same-item remediation, schema/language/size gate, exact paired test·Clopper–Pearson·paired bootstrap을 구현했다. approval-before-open, 117:117 commitment, no-follow/lstat/hardlink/TOCTOU, 36행 score, text-free trace, atomic publish와 second replay를 구현하고 synthetic 117-row E2E를 포함한 25 tests를 통과했다. 실제 Primary03에는 hash-only commitment만 수행해 raw 117·CSV digest를 봉인했고 V2.4-D scorer/full run은 실행하지 않았다.
- **수정 파일**: `docs/plans/input_commitment_v2_4_deterministic.json:1`, `experiments/v2_4_deterministic/`, `tests/test_v2_4_deterministic.py:1`, `results/experiment_changes_v2_4.md`
- **상태**: implementation candidate `I` 준비·fresh review 대기 — ontology SHA-256 `456bc7c562b5c1896fa37041f4f6ceda6184994be77af9c2a55b3daee086035d`, commitment raw 117/CSV `5fd2c1c5…f8c5b`. 절차 편차: 신규·기존 회귀 검증 중 `tests.test_v2_4_audit`의 real-input integration code가 Primary03을 machine-only로 파싱했다. 본문 stdout/stderr·agent context 노출과 V2.4-D scoring은 0이나 process-level access 0 주장은 철회하며 fresh reviewer가 confirmatory 유지 여부를 판정해야 한다.

### 11. V2.4-D implementation candidate I 독립 검토 실패 — 2026-08-31

- **수정 에이전트**: fresh @implementation-reviewer, @Codex
- **증상/문제**: synthetic 25 tests가 통과한 구현 후보라도 plan과 exact ontology semantics, finite negation, approval chain과 replay-before-release가 실제 코드에서 강제되는지 독립 확인이 필요했다.
- **원인**: candidate `I=e86e26b`는 plan에 없는 ontology representation을 추가하면서 const validation이 약했고, negation heuristic·빈 문자열/replacement gate·commit chain·CSV 고정 hash·replay publication·commitment TOCTOU와 redaction test가 계약보다 느슨했다. test suite도 이 결함을 포착하지 못했다.
- **수정 내용**: fresh reviewer가 exact I detached clean checkout에서 candidate를 열지 않고 파일 hash, synthetic 25 tests, pycompile, ontology check와 정적 공격 검토를 수행했다. P0 7개·P1 4개를 기록하고 bundle B·실채점을 거부했다. machine-only 기존 regression parse는 본문 egress와 scorer 실행이 없고 observed-output-derived 변경도 없음을 투명하게 기록하는 조건에서 causal confirmatory 유지 가능하다고 별도 판정했다.
- **수정 파일**: `docs/plans/review_v2_4_deterministic_implementation.md:1`, `results/experiment_changes_v2_4.md`
- **상태**: FAIL — candidate scoring 0, bundle B 금지. plan revision과 I2 구현 보완·fresh 재검토 필요.

### 12. V2.4-D revision 6의 I0→I1 안전 체인 승인 — 2026-08-31

- **수정 에이전트**: @experiment-planner, fresh @methodology-reviewer, @Codex
- **증상/문제**: implementation review P0를 계획에 반영하는 과정에서 새 provenance를 요구하면서 구 unsafe commitment digest를 고정하는 모순과, 검토 전 commitment tool이 실제 입력 bytes를 먼저 읽는 순서 역전이 발견됐다.
- **원인**: code safety review와 real hash-only commitment 생성을 하나의 implementation commit에 묶어, commitment tool 자체의 안전성을 candidate-unmounted 상태에서 선검증할 수 없었다.
- **수정 내용**: 구 commitment envelope를 `DEPRECATED_MACHINE_HASH_ONLY_COMMITMENT`로 강등하고 CSV/raw path·size·digest를 source-drift reference로만 보존했다. code-only `I0`을 candidate-unmounted fresh safety review한 뒤 exact reviewed tool로 새 commitment를 생성하고, commitment+deviation provenance 두 파일만 더한 `I1`, review-only `B`, approval-only `A` 순서를 hard gate로 고정했다. runner·ontology·negation·hidden two-run release·commit safety·37-category tests의 revision 5 보완도 유지했다. cumulative reviewer가 P0 20 PASS/0 FAIL로 revision 6을 승인 권고했다.
- **수정 파일**: `docs/plans/experiment_plan_v2_4_deterministic.md:1`, `docs/plans/review_v2_4_deterministic.md:1`, `results/experiment_changes_v2_4.md`
- **상태**: semantic plan 재승인 완료 — plan SHA-256 `169f59e40b4619c15613cce6360ca4b03063dfa1cd451e79160c86be949d936d`, review SHA-256(외부) `7f125f15b5469f1e8e51ba84386628dcedf4392c82958e37bb1496c5a8f903b7`; 다음 gate는 commitment가 없는 code-only I0.

### 13. V2.4-D code-only I0 안전 구현 보완 — 2026-09-01

- **수정 에이전트**: @implementation-worker, @runner-worker, @Codex
- **증상/문제**: 최초 implementation review가 ontology const, finite negation, candidate fail-close, git approval chain, replay-before-release, hash-only TOCTOU와 synthetic coverage에서 P0 7개를 발견했다.
- **원인**: green test가 semantic schema의 exact const와 runner의 실제 git ancestry를 검증하지 않았고, 첫 run을 replay 전에 공개했으며, commitment tool이 path swap·symlink와 redaction provenance를 충분히 방어하지 못했다.
- **수정 내용**: deprecated real commitment를 code-only tree에서 제거했다. ontology duplicate/version/negation order/ID/alias count, finite negation consumed-span, empty/U+FFFD/total-token gate를 강화했다. commitment tool에 ancestor/no-follow/fstat/pre-post rehash와 실행형 redaction self-test를 추가했다. runner는 I0→I1→B→A ancestry·exact diff·all target hash/blob를 candidate open 전에 검증하고, 두 hidden full run이 모두 일치한 뒤에만 final/replay/manifest/export를 단일 atomic release하도록 변경했다. second-run failure/mismatch는 body-free INVALID receipt만 남긴다. isolated Python `-I`를 포함한 synthetic 41 tests를 통과했다.
- **수정 파일**: `docs/plans/input_commitment_v2_4_deterministic.json`(deprecated 삭제), `experiments/v2_4_deterministic/build_ontology.py`, `experiments/v2_4_deterministic/commit_inputs.py`, `experiments/v2_4_deterministic/ontology_v1.json`, `experiments/v2_4_deterministic/run.py`, `experiments/v2_4_deterministic/scorer.py`, `tests/test_v2_4_deterministic.py`, `results/experiment_changes_v2_4.md`
- **상태**: code-only I0 commit 대기 — synthetic 41 PASS, ontology check PASS, redaction self-test PASS, pycompile/diff-check PASS. 실제 candidate path·metadata·hash/content 접근과 real scoring 0.

### 14. V2.4-D I0 safety review 실패와 path-race/redaction 보완 — 2026-09-01

- **수정 에이전트**: fresh @i0-safety-reviewer, @implementation-worker, @Codex
- **증상/문제**: 최초 code-only I0 `fffb426`의 synthetic suite는 통과했지만 fresh safety probe에서 ancestor directory를 검사 직후 symlink로 교체하면 다른 bytes를 승인했고, source path sentinel이 provenance argv로 노출됐다.
- **원인**: 최종 파일만 `O_NOFOLLOW`로 열고 ancestor path는 선행 검사에 의존했으며, provenance가 실제 절대 argv를 저장했다. redaction PASS도 실실행 결과가 아닌 상수였다.
- **수정 내용**: safety reviewer가 receipt 생성을 거부하고 두 P0를 기록했다. commitment tool은 lexical directory를 fd chain/openat `O_DIRECTORY|O_NOFOLLOW`로 고정하고 final entry도 relative no-follow open·fstat·pre/post rehash로 검증하도록 변경했다. provenance는 option과 SHA-256 identifier만 저장하며 path/basename을 제거했고, content/path/error sentinel을 쓰는 executable redaction self-test가 매 commitment 전에 성공해야만 출력하도록 했다. ancestor 교체 fixture와 path sentinel test를 추가했다.
- **수정 파일**: `experiments/v2_4_deterministic/commit_inputs.py`, `tests/test_v2_4_deterministic.py`, `results/experiment_changes_v2_4.md`
- **상태**: 수정 완료·새 I0 safety review 대기 — isolated 43 tests PASS, redaction self-test PASS, 실제 candidate source 접근 0, 이전 I0 receipt 0.

### 15. V2.4-D 두 번째 I0 safety review의 error-path/provenance 보완 — 2026-09-01

- **수정 에이전트**: second fresh @i0-safety-reviewer, @implementation-worker, @Codex
- **증상/문제**: descriptor-anchor 보완 후에도 missing path sentinel이 Python traceback stderr로 노출됐고, redaction self-test가 같은 CLI error wrapper를 검증하지 않아 PASS 상수와 required I0/receipt provenance가 불충분했다.
- **원인**: expected filesystem exception을 CLI 경계에서 고정 오류로 변환하지 않았으며, real commitment 명령에 reviewed I0·external receipt·legacy source map identity를 전달하고 검증할 contract가 없었다.
- **수정 내용**: CLI expected error를 path-free `COMMITMENT_FAILED` 하나로 변환하고, 동일 success/error wrapper를 content/path/error sentinel로 실행한 evidence가 없으면 출력하지 않도록 했다. real mode에 reviewed I0, safety receipt, legacy reference를 필수화하고 receipt PASS/I0/tool blob 및 legacy CSV/raw identity exact 비교를 구현했다. provenance에 redacted argv, tool/interpreter/fd source identity, self-test evidence, receipt/legacy result를 포함했다.
- **수정 파일**: `experiments/v2_4_deterministic/commit_inputs.py`, `tests/test_v2_4_deterministic.py`, `results/experiment_changes_v2_4.md`
- **상태**: 새 code-only I0 commit 대기 — isolated 45 tests PASS, executable redaction PASS, actual candidate source 접근 0, 두 이전 safety receipt 0.

### 16. V2.4-D 세 번째 I0 safety review의 evidence/receipt schema 보완 — 2026-09-01

- **수정 에이전트**: third fresh @i0-safety-reviewer, @implementation-worker, @Codex
- **증상/문제**: path·error redaction은 통과했지만 self-test가 `SKIPPED` evidence를 반환해도 real mode가 진행됐고, plan-complete safety receipt가 3-key 축약 schema에 의해 거부됐다. provenance도 commitment digest와 safety 관련 argv identity를 누락했다.
- **원인**: self-test evidence와 external receipt를 최소 truthy/축약 객체로만 검증하고, revision 6이 요구하는 content-addressed 필드 전체를 runtime schema로 구현하지 않았다.
- **수정 내용**: self-test evidence의 exact status·exit·digest·sentinel schema를 검증해 incomplete/injected 값을 pre-open 차단했다. reviewer/session/UTC, 8 target blob/hash, semantic review, interpreter, command digests, fixture/sentinel, open/egress, prior-failure closure를 포함하는 full receipt를 exact 검증하고 tool blob에 bind했다. canonical redacted argv 6 options와 self-excluding commitment digest를 provenance required field로 추가했다. fixed Python 3.11 isolated tests로 검증했다.
- **수정 파일**: `experiments/v2_4_deterministic/commit_inputs.py`, `tests/test_v2_4_deterministic.py`, `results/experiment_changes_v2_4.md`
- **상태**: 수정 완료·네 번째 fresh safety review 대기 — 48 tests PASS, pycompile/ontology/redaction/diff-check PASS, 실제 candidate source 접근 0, receipt 0.

### 17. V2.4-D 네 번째 I0 safety review의 pre-open 순서 보완 — 2026-09-01

- **수정 에이전트**: fourth fresh @i0-safety-reviewer, @implementation-worker, @Codex
- **증상/문제**: invalid safety receipt도 최종적으로는 거부됐지만 `_commit_core`가 먼저 실행돼 source를 hash한 뒤 receipt mismatch를 판정했다.
- **원인**: receipt identity 검증과 source-derived legacy digest 비교를 하나의 post-commit 함수에 묶어, source 접근 전에 판정 가능한 gate까지 뒤로 밀렸다.
- **수정 내용**: redaction evidence 다음에 I0/full receipt/8 targets/tool/interpreter/command evidence와 legacy schema를 pre-open 검증하고, 그 후에만 `_commit_core`를 호출하도록 분리했다. source-derived CSV/raw map 비교는 commit 후단에만 수행한다. malformed/missing/wrong identity 6종에서 source-open spy 0, valid receipt에서만 1임을 synthetic test로 고정했다.
- **수정 파일**: `experiments/v2_4_deterministic/commit_inputs.py`, `tests/test_v2_4_deterministic.py`, `results/experiment_changes_v2_4.md`
- **상태**: 수정 완료·다섯 번째 fresh safety review 대기 — fixed Python 3.11 isolated 49 tests PASS, 실제 candidate source 접근 0, receipt 0.

### 18. V2.4-D I0→I1 A/A chain 정합성 교정 — 2026-09-01

- **수정 에이전트**: fifth fresh @i0-safety-reviewer, @experiment-planner, fresh @methodology-reviewer, @Codex
- **증상/문제**: I0 safety는 마침내 PASS했지만 code-only I0에서 real commitment를 제외한다는 계약과 `I0→I1`에서 commitment를 `M`으로 요구하는 diff 표기가 모순이었다.
- **원인**: deprecated commitment 삭제를 I0 설계에 반영하면서 downstream diff status 한 곳이 과거 placeholder 전제에 남아 있었다.
- **수정 내용**: fifth reviewer가 I0 `7388a41`의 8 targets·49 tests·prior failure closure를 검증해 PASS receipt SHA `b90aa91b…4676`을 생성했다. 그 reviewed tool로 hash-only commitment를 한 번 생성해 source map exact 일치를 확인했으나 M/A 모순 발견 즉시 uncommitted artifact를 폐기하고 confirmatory provenance에서 제외했다. revision 7은 I0 commitment path absent와 I0→I1 `A commitment + A deviation`을 exact gate로 고쳤고 cumulative reviewer가 P0 8 PASS/0 FAIL로 승인했다.
- **수정 파일**: `docs/plans/experiment_plan_v2_4_deterministic.md:1`, `docs/plans/review_v2_4_deterministic.md:1`, `results/experiment_changes_v2_4.md`
- **상태**: revision 7 승인·새 I0 필요 — plan SHA `33435f87ce56c9bcef38b6ea3bb985e305ac02b5a1ebebdb4af69e9a241b4381`, review SHA `14826d4d0a35da53e4a8603759916b667bfcc844d3c027ca2a1abd0d8636602d`. Discarded artifact는 scoring/approval/commit 0, candidate decode/parse/output 0.

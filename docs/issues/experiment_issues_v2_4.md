# V2.4 실험 이슈 트래커

## 요약

- 총 이슈: 5건
- 심각(실험 무효화): 1건
- 경고(후속 범위 제한·구현 수정): 4건
- 참고(영향 미미): 0건

## 이슈 목록

### [ISS-001] 비대표 generation 72개의 본문이 Primary03에 보존되지 않음

- **카테고리**: data / reproducibility
- **심각도**: warning (P1)
- **영향**: V2.4의 12 incidents × 3 conditions에서 generator identity와 `output_text_hash`는 108개 모두 보존됐지만, full output 본문은 condition별 대표 generation 36개만 raw/CSV에 남았다. 따라서 계획서의 선택적 108-output human sensitivity audit는 현재 artifact만으로 실행할 수 없다.
- **발생 빈도**: 비대표 generation 72/108. 대표 generation 36/108은 본문과 hash가 모두 존재한다.
- **관찰한 사실**: 각 raw의 generator call ledger에는 repeat 1~3의 identity와 output hash가 존재한다. `representative_output`은 한 repeat의 full payload만 보존하며, 나머지 두 repeat의 본문 field나 별도 파일은 artifact tree에서 발견되지 않았다.
- **근본 원인**: V2.3 저장 schema가 row-level representative output과 모든 call provenance/hash는 보존했지만 모든 generation response 본문을 보존하지 않았다.
- **현재 영향**: V2.4 primary 36-output correctness audit와 12-block semantic audit에는 영향이 없다. 108 identity/hash는 결과 독립적으로 sealed manifest에 고정하되, 본문을 추정·재생성하지 않는다.
- **처리**: 108 본문 materialization은 모든 sealed payload와 hash가 일치할 때만 허용한다. 현재는 `BLOCKED_GENERATION_CONTENT_NOT_ARCHIVED`로 fail-closed한다. 후속 live experiment에서는 generation별 full response를 append-only raw에 저장해야 한다.

### [ISS-002] 초기 Step 3 package 구현이 reviewer·phase 무결성 공격을 차단하지 못함

- **카테고리**: code / data
- **심각도**: warning (P1, package 배포 전 발견)
- **영향**: 초기 구현의 happy-path 21 tests는 통과했지만, frozen reference/candidate 변조 제출, unanimous 판정의 임의 adjudication 변경, correctness close 중 semantic 부분 배포, archive Markdown/metadata scanner false negative를 차단하지 못했다.
- **발생 빈도**: 독립 code-review PoC에서 각 failure mode 1회씩 재현. 실제 reviewer 배포와 사람 rating은 0건이다.
- **관찰한 사실**: 변조된 `expected_root_cause` 제출과 `R1=R2=1`을 adjudicated 0으로 바꾼 sheet가 초기 lock을 통과했다. R2 semantic destination 충돌을 주입하면 correctness CLOSED와 R1 semantic archive만 남았다. `Terra`, full-width `Ｔｅｒｒａ`, Markdown의 internal marker도 초기 record-only scanner를 통과했다.
- **근본 원인**: 제출 schema/ID만 확인하고 committed distribution의 frozen columns와 order를 재검증하지 않았으며, phase publish가 원자적이지 않았다. scanner 범위가 CSV records에 한정되고 known identifiers와 symmetric normalization을 적용하지 않았다.
- **현재 영향**: 실제 V2.4 package 생성·배포 전 독립 리뷰에서 발견했으므로 보존 artifact나 human outcome 오염은 없다. 수정 전 구현은 승인하지 않는다.
- **처리**: committed archive 대조, disagreement-only adjudication, atomic stage/publish/CLOSED-last, recursive archive scanner와 symmetric encoding canary, pre-parse source digest를 P0 회귀 테스트로 추가한 뒤에만 실제 package를 생성한다.

### [ISS-003] Semantic package가 reviewer training lock 전에 공개될 수 있었음

- **카테고리**: code / data
- **심각도**: warning (P0, package 생성 전 해결)
- **영향**: 중간 구현은 correctness close와 동시에 semantic archive를 공개한 뒤 semantic reviewer profile/training을 잠갔다. 이 순서는 실제 sample을 training 전에 볼 수 있게 해 semantic 평가의 독립성을 훼손할 수 있었다.
- **발생 빈도**: 독립 code-review에서 lifecycle 순서 1건으로 재현. 실제 audit package 생성, reviewer 열람, human rating은 모두 0건인 시점에 발견했다.
- **관찰한 사실**: 당시 `close_correctness`가 semantic distribution을 생성했고, semantic profile은 correctness CLOSED 이후에만 생성 가능했다. 따라서 계획의 `correctness CLOSED → semantic training PASS → semantic 최초 배포` 순서와 반대였다.
- **근본 원인**: correctness 종료와 semantic 공개를 하나의 lifecycle operation에 결합했다.
- **현재 영향**: 실제 패키지 생성 전에 수정돼 평가 오염은 없다. 최종 package의 공개 영역에는 correctness archive 2개만 있고 semantic archive 2개는 sealed pending 영역에 있다.
- **처리**: `close_correctness`를 correctness-only atomic close로 제한하고, 두 qualified semantic profile을 검증한 뒤에만 동작하는 atomic `release-semantic` 단계를 추가했다. 0/1 profile 거부, release 전 archive 부재·submission 차단, publish 실패 rollback을 회귀 테스트로 고정했다.

### [ISS-004] V2.4-D finite negation instrument가 frozen corpus를 완전 채점하지 못함

- **카테고리**: data / measurement
- **심각도**: critical (P0, V2.4-D 효과 판정 무효화)
- **영향**: Exact 승인·hash·117:117·선택 36 identity gate 뒤 첫 hidden scoring이 `UNSUPPORTED_NEGATION`으로 중단됐다. 완전한 36-row 결과와 12 paired outcomes가 없어 RAG 대 length-placebo 효과를 지지하거나 반박할 수 없다.
- **발생 빈도**: 승인된 V2.4-D 실측 1회 중 1회. Public result CSV·summary·paired table·partial release는 0개다.
- **관찰한 사실**: Body-free receipt는 `status=INVALID`, `reason=UNSUPPORTED_NEGATION`, `candidate_text_emitted=false`이며 exact SHA-256는 `8281d230761b981a6d5e98c035ce4a54e7a180169f93c2b1357b448942447869`다. 결과 CSV는 파일 자체가 absent다.
- **근본 원인**: 사전등록 finite negation instrument의 support coverage가 frozen corpus의 scoring path를 total binary outcome으로 바꾸지 못했다. Candidate 의미 본문 비접근 상태에서는 실제 문법 범위 초과와 parser false-positive를 구분할 수 없으므로 어느 한쪽을 확정하지 않는다.
- **현재 영향**: V2.4-D `primary_status=INVALID`. RD·b/c·p-value·CI·조건별 rate는 전부 NA이며 0 imputation과 complete-case 대체 분석을 금지한다.
- **처리**: 원 V2.4-D와 receipt를 영구 INVALID로 보존한다. Real-input 반복 probe와 in-place tuning을 금지하고, 후속은 reason-only adaptation을 공개한 별도 V2.4-D2에서 public linguistic source와 synthetic fixture만으로 사전 설계한다.

### [ISS-005] 최초 V2.4-D 실측의 canonical 환경·transcript 증거 누락

- **카테고리**: code / reproducibility
- **심각도**: warning (P1)
- **영향**: 최초 실측은 승인된 fixed Python과 `-I`를 사용했지만 plan의 `env -i` allowlist를 사용하지 않았고 exact A pre-execution test transcript, full invocation transcript와 exact nonzero exit code를 content-addressed evidence로 보존하지 않았다.
- **발생 빈도**: 최초 V2.4-D 실측 1회.
- **관찰한 사실**: 실행 뒤 canonical `env -i` 환경에서 exact A의 90 tests·ontology check·runner self-test는 모두 PASS했다. 이 사후 검증은 최초 실행 편차를 소급 치유하지 않으며 `primary_status=INVALID`를 바꾸지 않는다.
- **근본 원인**: Step 4 orchestration에서 canonical launcher와 pre-execution command transcript 보존을 실제 invocation 앞에 강제하지 않았다.
- **현재 영향**: `UNSUPPORTED_NEGATION` fail-close와 결과 비공개는 source·receipt로 확인되지만, 실행 전 과정의 독립 재현 증거 범위는 제한된다.
- **처리**: 후속 one-shot 실행은 reviewed launcher가 `env -i` allowlist, exact preflight tests, command/exit/timestamp transcript의 content-addressed publication을 scoring 전에 강제해야 한다. 보존되지 않은 digest나 exit code는 사후 발명하지 않는다.

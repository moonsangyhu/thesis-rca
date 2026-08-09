# V2.3 실험 변경 이력

### 1. GitHub Copilot CLI–GPT-5.6 Terra 추론 adapter 추가 — 2026-08-09

- **수정 에이전트**: @Codex
- **증상/문제**: 기존 실험 하네스는 OpenAI·Anthropic API만 지원해 회사 Copilot AIC와 `gpt-5.6-terra`를 RCA generator/judge로 사용할 수 없었다.
- **원인**: `BaseLLMClient`에 Copilot provider와 Copilot JSONL 응답·사용량 파서가 없었다.
- **수정 내용**: Copilot 모델을 `gpt-5.6-terra`로 고정하고 auto routing·custom instructions·remote·MCP·agent tool을 비활성화하는 격리 adapter를 추가했다. JSONL에서 실제 모델·session ID·output token·AIC를 추출하고, 모델 drift나 CLI 오류는 fail-closed 처리한다. 실제 smoke test에서 Terra JSON 응답 파싱과 session metadata를 확인했으며 1.0 AIC가 사용됐다.
- **수정 파일**: `experiments/shared/copilot_cli.py:1`, `experiments/shared/llm_client.py:20`, `tests/test_copilot_cli.py:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 실제 fault injection 전 1 fault × 1 trial AIC pilot와 V2.3 계획 승인 필요

### 2. V2.3-RAG deep-analysis 및 단일변수 가설 고정 — 2026-08-09

- **수정 에이전트**: @Codex
- **증상/문제**: 기존 V2.3 goal은 RAG 누출 통제, GitOps 정상화, campaign 복구를 한 버전에 함께 제안해 독립변수와 인과 해석 범위가 넓었다. Copilot–Terra로 모델도 변경돼 V2.2 절대값과 직접 비교할 수 없다.
- **원인**: V2.2 RAG 처치의 75% self-runbook leakage와 GitOps treatment failure를 서로 다른 검증 문제로 분리하지 않았다.
- **수정 내용**: 7개 결과 CSV 960행과 V2.2 raw JSON의 정답 3개·오답 3개를 Python으로 재검증했다. V2.3의 독립변수를 `context_condition` 하나(runtime/length-placebo/blind-procedural-RAG)로 고정하고, GitOps와 context position은 후속 실험으로 분리했다. V2.3 내부 paired contrast만 1차 주장으로 정했다.
- **수정 파일**: `docs/surveys/deep_analysis_v2_3.md:1`, `results/experiment_changes_v2_3.md:12`
- **상태**: 수정됨 — experiment plan과 방법론 리뷰 승인 대기

### 3. V2.3 상세 계획과 5축 방법론 비평 반영 — 2026-08-09

- **수정 에이전트**: @experiment-planner, @Codex
- **증상/문제**: blind RAG의 단일변수 설계가 arm·반복·통계·예산·중단 기준까지 구체화되지 않았고, 초기 초안의 F1 파일럿·36건 human audit·12-cluster bootstrap만으로는 비용과 judge 타당성이 약했다.
- **원인**: 최대 context AIC stress, same-model judge 보정, 작은 fault cluster의 보조 검정, semantic shortcut audit이 계획에 충분히 사전 고정되지 않았다.
- **수정 내용**: 3-condition paired estimand, 180 rows/2,160 calls, leakage/treatment/recovery gate를 고정했다. 방법론 비평 5축을 적용해 deterministic independent placebo, semantic audit rubric, exact 2^12 cluster permutation, 고정 bootstrap, 180건 human 전수 채점, 최대-context 36-call AIC pilot과 역할별 비용 상한을 필수 P0로 반영했다.
- **수정 파일**: `docs/plans/experiment_plan_v2_3.md:1`, `docs/plans/review_v2_3.md:1`, `results/experiment_changes_v2_3.md:22`
- **상태**: 수정됨 — 사용자 설계 승인 전 구현·클러스터 접근 금지

### 4. Research 산출물 통합과 Copilot zero-overage fail-closed 보강 — 2026-08-09

- **수정 에이전트**: @Codex
- **증상/문제**: V2.3 branch에 최근 survey/paper 정본이 없어 계획의 문헌 prerequisite가 미충족이었고, Copilot adapter가 legacy `premiumRequests`를 실제 AIC로 잘못 해석했다. 조직의 paid usage 정책을 확인하지 않아도 subprocess를 실행할 수 있었다.
- **원인**: Copilot JSONL의 실제 AIC는 `session.usage_checkpoint.totalNanoAiu`에 기록되지만 result 호환 필드를 사용했고, 외부 과금정책과 로컬 실행 gate가 분리되지 않았다.
- **수정 내용**: 검증된 survey와 고유 paper note 20편을 experiment worktree에 통합하고 local link 누락 0건을 확인했다. AIC를 `totalNanoAiu / 1e9`로 계산하고 premium request는 별도 필드로 보존한다. usage checkpoint·session·model·tool event를 fail-closed 검증하며, 관리자 zero-overage 확인 flag가 없으면 subprocess 실행 전에 차단하고 호출별 `--max-ai-credits 10.0` 상한을 추가했다. 실제 Copilot 호출 없이 mock 단위 테스트만 수행했다.
- **수정 파일**: `docs/surveys/paper_survey_v1.md:1`, `docs/surveys/research_scope_v1.md:1`, `docs/papers/*.md`, `experiments/shared/copilot_cli.py:1`, `experiments/shared/llm_client.py:20`, `tests/test_copilot_cli.py:1`, `docs/plans/experiment_plan_v2_3.md:329`, `docs/plans/review_v2_3.md:113`, `results/experiment_changes_v2_3.md:31`
- **상태**: 수정됨 — 관리자 `AI credits paid usage = Disabled` 증빙 전 Copilot inference 금지

### 5. V2.3 격리형 오프라인 harness와 코드리뷰 결함 보강 — 2026-08-09

- **수정 에이전트**: @Codex, @worker, @explorer-reviewer
- **증상/문제**: V2.2 dry-run도 production 결과 경로를 쓰고 fault-ID retrieval·부분 incident·raw overwrite 위험이 있었다. 최초 V2.3 초안도 scanner 우회, malformed/NaN judge 결과, provenance 교차검증, incident별 ledger 내구성이 부족했다.
- **원인**: 계산 loop와 저장·검증·외부 실행 경계가 분리되지 않았고, whole-term lexical match와 캠페인 종료 시점 ledger 일괄 기록만 사용했다.
- **수정 내용**: `experiments/v2_3/`에 외부 dependency를 import하지 않는 3-condition/k=3/m=3 harness를 격리했다. dry-run은 180행·2,160호출 manifest를 메모리에서만 검증하고 real mode는 승인 marker와 무관하게 차단한다. deterministic placebo, Latin square, NFKC·compact substring·regex·token n-gram scanner, model/session/AIC/tool-event 및 invocation 교차검증, finite schema gate, judge context redaction, campaign 4-tuple dedupe, production results 경로 거부, incident별 raw/CSV/ledger staged 저장을 추가했다. 기존 `results/` 경로·해시 불변을 확인했다.
- **수정 파일**: `experiments/v2_3/*.py:1`, `tests/test_v2_3_*.py:1`, `docs/plans/experiment_plan_v2_3.md:1`, `results/experiment_changes_v2_3.md:41`
- **상태**: 부분 수정 — 오프라인 Step 3A 완료; live retriever/runner·recovery와 Copilot 파일럿은 zero-overage 증빙 및 별도 승인 전 미구현/금지

### 6. V2.3 독립 재리뷰의 provenance·blinding 차단 결함 수정 — 2026-08-09

- **수정 에이전트**: @Codex, @explorer-reviewer
- **증상/문제**: 첫 수정본에도 fault ID 구두점 우회, judge reference 부재, 실제 judge 입력 hash와 arm linkage hash 혼동, 선언적인 runtime-only retrieval 표기, 조작 가능한 retrieval provenance가 남았다.
- **원인**: scanner가 underscore를 word 문자로 취급했고, judge 호출 정보와 분석 linkage를 하나의 context 필드로 기록했으며, retrieval builder 입력과 frozen runtime/corpus/masking provenance 사이 교차검증이 부족했다.
- **수정 내용**: underscore·NFKC·spacing 변형을 포함한 fail-closed scanner/masker를 적용했다. judge에는 arm/source/fault metadata 대신 sealed reference·공통 rubric·candidate diagnosis만 전달하고, 실제 입력 hash와 linked arm hash를 별도 ledger 필드로 분리했다. runtime context에서 유래한 query만 허용하며 fault/command/entity/field-value query를 차단한다. query·runtime·corpus·candidate·score·chunk·removed span·scanner·lexicon·masked text hash를 서로 bind하고 assembler에서 재검증한다. aggregate estimand와 representative sample audit도 분리했다.
- **수정 파일**: `experiments/v2_3/scanner.py:1`, `experiments/v2_3/retrieval.py:1`, `experiments/v2_3/conditions.py:1`, `experiments/v2_3/engine.py:1`, `experiments/v2_3/ledger.py:1`, `experiments/v2_3/storage.py:1`, `experiments/v2_3/mock.py:1`, `tests/test_v2_3_*.py:1`, `results/experiment_changes_v2_3.md:49`
- **상태**: 수정됨 — 전체 offline 검증 및 최종 독립 재리뷰 대기; 실제 Copilot·클러스터 호출은 계속 0건

### 7. V2.3 Step 3A 최종 오프라인 검증 및 독립 승인 — 2026-08-09

- **수정 에이전트**: @Codex, @explorer-reviewer
- **증상/문제**: 순차 마스킹 시 뒤쪽 removed span 좌표가 변형된 문자열 기준으로 기록되어 원문 provenance와 어긋났다.
- **원인**: 금지어마다 즉시 `[MASKED]` 치환한 후 다음 match를 탐색해 원문 offset을 보존하지 않았다.
- **수정 내용**: NFKC 원문에서 모든 non-overlap match를 먼저 수집하고 원문 좌표를 보존한 채 역순 치환했다. 동결 corpus version·source ID·chunk span을 결합한 snapshot locator를 저장·검증한다. 전체 93개 테스트, 180행/2,160호출 in-memory dry-run, `results/` 전후 SHA-256 불변, `git diff --check`를 확인했고 독립 reviewer가 최종 승인했다.
- **수정 파일**: `experiments/v2_3/retrieval.py:1`, `tests/test_v2_3_retrieval.py:1`, `results/experiment_changes_v2_3.md:58`
- **상태**: 수정됨 — Step 3A 오프라인 승인; 실제 Copilot·클러스터 호출 0건, live 단계는 zero-overage 관리자 증빙 대기

### 8. V2.3 Step 3B live 경계 구현과 독립 보안·방법론 승인 — 2026-08-09

- **수정 에이전트**: @Codex, @explorer-reviewer
- **증상/문제**: 첫 live 초안은 authorization 객체 직접 생성, strict parse 실패 호출의 AIC 누락, recovery GREEN 전 결과 commit, post-injection 상태 미검증, `5m`·`10m` 같은 짧은 injection 값 누출, 사전 고정 bootstrap 변경 가능성이 있었다. 실제 Online Boutique의 `currencyservice` deployment와 `server` container 이름 차이도 초기 validator가 처리하지 못했다.
- **원인**: 증빙 검증과 live 객체 수명, subprocess charge 관측과 응답 parse, incident 계산과 결과 publish, injector receipt와 실제 cluster 상태가 각각 하나의 원자적 gate로 묶이지 않았다.
- **수정 내용**: 증거 3종의 고유 file/hash·24시간 freshness·두 process gate를 검증하고 live 실행·runner·호출마다 재검증하는 sealed authorization을 구현했다. Copilot subprocess 종료 즉시 성공·timeout·nonzero·비정형 JSONL과 무관하게 charged-call receipt를 fsync하며, known 실패 AIC는 누적하고 unknown usage는 campaign hard-stop한다. F7 trial 5 injector identity와 실제 `currencyservice/server` deployment·Ready pod CPU 5m 상태를 확인한 뒤에만 collect/call하고, recovery GREEN 뒤에만 pilot 결과를 commit한다. 짧은 field value scanner와 50,000회 고정 fault-cluster bootstrap을 추가했다. 독립 적대 재리뷰에서 blocker 0건으로 승인됐고, 전체 123개 테스트와 180행/2,160호출 in-memory dry-run을 통과했다.
- **수정 파일**: `experiments/shared/copilot_cli.py:1`, `experiments/v2_3/authorization.py:1`, `experiments/v2_3/live_caller.py:1`, `experiments/v2_3/live_runner.py:1`, `experiments/v2_3/analyze.py:1`, `experiments/v2_3/run.py:1`, `experiments/v2_3/scanner.py:1`, `tests/test_copilot_cli.py:1`, `tests/test_v2_3_*.py:1`, `docs/plans/experiment_plan_v2_3.md:1`, `docs/plans/review_v2_3.md:1`, `docs/plans/v2_3_pilot_runbook.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — Step 3B 코드 승인; 실제 Copilot·클러스터 호출 0건, 관리자 zero-overage 증빙과 별도 36-call 파일럿 승인 대기

### 9. Zero-overage 증빙용 오프라인 intake 추가 — 2026-08-09

- **수정 에이전트**: @Codex
- **증상/문제**: 관리자 화면을 확인해도 세 파일의 절대경로·SHA-256·관측 시각을 수동으로 JSON에 옮겨야 해 오타, repo 내 민감 증빙 추적, 동일 artifact 중복 제출 위험이 있었다.
- **원인**: authorization verifier는 있었지만 verifier 입력 manifest를 안전하게 만드는 표준 오프라인 경로가 없었다.
- **수정 내용**: 사람이 paid usage disabled, budget hard stop, included AIC balance를 직접 검토했다는 명시적 flag를 요구하는 intake CLI를 추가했다. 세 artifact와 manifest가 repo 밖인지, 파일·hash가 고유한지, balance가 양의 유한값인지 검증하고, manifest를 exclusive create·mode 0600·fsync한 뒤 기존 `BillingEvidence` verifier로 즉시 재검증한다. GitHub·Copilot·Kubernetes·네트워크 호출은 없다.
- **수정 파일**: `experiments/v2_3/evidence_intake.py:1`, `tests/test_v2_3_evidence_intake.py:1`, `docs/plans/v2_3_pilot_runbook.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — intake 2개 단위 테스트 및 authorization 5개 회귀 테스트 통과; 실제 관리자 증빙 파일 수신 대기

### 10. Live campaign의 clean git revision gate 추가 — 2026-08-09

- **수정 에이전트**: @Codex
- **증상/문제**: 계획서는 단일 git commit과 clean code snapshot을 요구하지만 pilot manifest가 실제 commit SHA를 기록하지 않아 실행 코드 버전을 campaign artifact만으로 재구성할 수 없었다.
- **원인**: corpus·CLI·billing provenance는 manifest에 포함했지만 source revision과 dirty 상태 검증이 빠졌다.
- **수정 내용**: 외부 dependency import와 cluster/Copilot 접근 전에 40자리 HEAD SHA와 전체 untracked를 포함한 clean worktree를 검사한다. dirty/unavailable revision이면 live 실행을 차단하고, 통과한 SHA와 `git_worktree_clean_at_start=true`를 campaign manifest에 기록한다.
- **수정 파일**: `experiments/v2_3/run.py:1`, `tests/test_v2_3_storage_and_run.py:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — clean/dirty revision 단위 테스트 추가; 파일럿 실행 전 재커밋·전체 검증 필요

### 11. V2.3 첫 launch 무실행 판정과 지속 PTY 재시도 절차 — 2026-08-09

- **수정 에이전트**: @Codex, @experiment
- **증상/문제**: experiment agent가 보고한 nohup PID 48358이 즉시 종료했고 agent 환경 log는 0 bytes, campaign artifact는 생성되지 않았다.
- **원인**: background child가 agent command executor 종료 시 유지되지 않은 것으로 추정한다. Python 출력이 없어 코드·authorization 원인으로 단정하지 않는다.
- **수정 내용**: artifact/result/raw/validated/charged ledger 0개와 Copilot·fault injection 0건을 확인했다. currencyservice CPU 200m, 6/6 Ready, DiskPressure False, Boutique 12 deployments 1/1, residual resource와 Failed pod 0, Prometheus/Loki Ready를 확인했다. 다음 단일 재시도는 root의 지속 PTY exec session, 새 campaign ID, root-side session/log/artifact 교차검증으로 고정한다.
- **수정 파일**: `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 무실행·무과금 launch failure로 분류 — 기록 commit-push 후 새 campaign으로 단일 재시도

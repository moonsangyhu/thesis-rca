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

### 12. V2.3 live Python·Chroma 경로 사전검증 보강 — 2026-08-09

- **수정 에이전트**: @Codex
- **증상/문제**: 지속 PTY로 시작한 두 번째 pilot이 전역 Python 3.11의 PyYAML 누락으로 import 단계에서 종료했다. repo venv로 바꿔도 `src.rag` package import가 기본 worktree Chroma 경로를 조기 고정해 승인된 외부 동결 Chroma 경로가 적용되지 않았다.
- **원인**: live launcher interpreter가 고정되지 않았고 `KnowledgeRetriever`가 module-level `CHROMA_DIR`만 참조해 V2.3 `--chroma-dir`와 실행 객체 사이의 명시적 binding이 없었다.
- **수정 내용**: `KnowledgeRetriever` 생성자에 선택적 `chroma_dir`를 추가하고 V2.3 runner가 `resolve(strict=True)`로 검증한 경로를 직접 전달하게 했다. repo venv Python 3.11.15에서 PyYAML·ChromaDB·sentence-transformers와 Copilot CLI 1.0.78을 확인하고, offline embedding으로 동결 Chroma corpus 일반 질의 2건을 실제 조회했다. targeted unittest 11개가 통과했다. 실패 attempt의 artifact/result/raw/call ledger/charged receipt와 fault injection은 모두 0건이었다.
- **수정 파일**: `src/rag/retriever.py:1`, `experiments/v2_3/run.py:1`, `tests/test_v2_3_storage_and_run.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 전체 테스트·dry-run·diff 검증과 commit-push 후 새 campaign ID로 pilot 실행

### 13. F7 recovery desired-state 봉인과 false-GREEN 차단 — 2026-08-09

- **수정 에이전트**: @Codex
- **증상/문제**: campaign `v2-3-pilot-20260809-2145`에서 currencyservice 5m 새 pod가 Ready가 되지 않아 post-injection gate가 차단했다. 자동 recovery는 `recovery_green`을 기록했지만 desired CPU 5m와 비정상 새 pod가 남았고, `kubectl rollout restart deployment --all`도 현재 CLI에서 실패했다.
- **원인**: injector receipt에 주입 전 CPU limit/request와 container identity가 없어 revision-based undo에 의존했다. generic health는 old 200m pod 하나의 Ready 상태를 정상으로 오판했고 namespace-wide restart 명령도 지원하지 않는 flag를 사용했다.
- **수정 내용**: F7 주입 전에 target container와 CPU limit/request를 캡처하고 campaign event에 fsync한 뒤 recovery state로 먼저 보유한다. apply 직후 timeout 예외에도 이 pre-state를 복구에 전달한다. mutation은 캡처한 container 하나로 제한하고, recovery는 receipt 값을 `kubectl set resources`로 명시 복원한 뒤 Deployment generation/observedGeneration, updated/ready/available replicas, container limit/request가 모두 일치하지 않으면 실패한다. namespace-wide restart는 netem F11/F12에만 수행하며 실제 deployment 목록을 순회하고 F10의 미지원 restart를 제거했다. 실제 클러스터는 currencyservice 200m/100m와 전체 health GREEN으로 수동 복원했고, 실패 artifact의 result·attempt·charged·pilot ledger가 0임을 확인했다. 실패 campaign provenance는 삭제하지 않고 `artifacts/v2_3_pilot/`에서 로컬 보존하되 git 추적과 다음 clean-revision gate에서 제외한다. partial-mutation/F10 회귀를 포함한 targeted live-runner 테스트 16개가 통과했다.
- **수정 파일**: `.gitignore:1`, `scripts/fault_inject/injector.py:1`, `scripts/stabilize/recovery.py:1`, `tests/test_v2_3_live_runner.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 복구 false-GREEN 수정됨 — F7 t5 5m 처치의 readiness 교락은 미해결이며 자동 재시도 금지

### 14. V2.3 pilot target을 F7 trial 1로 변경 — 2026-08-09

- **수정 에이전트**: @Codex
- **증상/문제**: 최초 pilot target F7 trial 5의 currencyservice 5m 새 pod가 Ready가 되지 않아 CPU-throttle과 rollout/restart가 교락됐고, 동일 처치를 반복하면 유효한 36-call pilot에 도달할 수 없었다.
- **원인**: historical 최대 context만으로 pilot을 선택하고 현재 클러스터에서 injection treatment가 Ready 상태와 양립하는지 반영하지 않았다.
- **수정 내용**: 사용자 승인에 따라 pilot-only target을 ground truth상 10m인 F7 trial 1 `frontend/server`로 변경했다. shared pilot identity 상수를 manifest·ground-truth lookup·runner hard gate가 함께 사용해 실제 실행과 provenance가 어긋나지 않게 했고, manifest identity와 무효화된 t5의 주입 전 거부를 검증하는 회귀 테스트를 추가했다. V2.2 historical context 최대치는 t1 약 12.9k, t5 약 16.6k chars이므로 본실험 AIC 투영의 `scaled_pilot`과 `role_upper`에 1.29 보정계수를 기존 15% margin과 함께 적용한다. runbook은 repo venv Python을 명시한다. primary V2.3의 60 incident·3 condition 설계는 변경하지 않았다.
- **수정 파일**: `experiments/v2_3/config.py:1`, `experiments/v2_3/run.py:1`, `experiments/v2_3/live_runner.py:1`, `tests/test_v2_3_live_runner.py:1`, `tests/test_v2_3_storage_and_run.py:1`, `docs/plans/experiment_plan_v2_3.md:1`, `docs/plans/review_v2_3.md:1`, `docs/plans/v2_3_pilot_runbook.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 전체 test/dry-run·독립 리뷰·commit-push 후 새 campaign으로 36-call pilot 실행

### 15. Runtime query masker와 scanner 규칙 정합화 — 2026-08-09

- **수정 에이전트**: @Codex
- **증상/문제**: campaign `v2-3-pilot-f7t1-20260809-2230`은 F7 t1 10m Ready 처치를 검증했지만 runtime-only retrieval query에서 leakage 6건을 탐지해 Copilot 호출 전에 중단했다.
- **원인**: masker는 금지 문구 전체만 치환하고 scanner는 부분 n-gram까지 탐지했다. masker boundary는 underscore를 단어 문자로 보았고, scanner의 2글자 fault-ID compact scan은 SHA/UID 내부 우연한 `f7`도 false positive로 처리했다.
- **수정 내용**: masker version을 `v2.3-procedure-mask-2`로 올리고 category별 scanner n-gram을 동일하게 생성해 긴 span부터 원문 좌표로 제거한다. underscore를 separator로 처리하고 fault ID는 separator 변형 전용 경계 scan으로 분리해 hash substring false positive를 제거했다. leakage 예외에는 원문 대신 category count, campaign에는 `incident_failed` error type을 남긴다. 직전 5분 collector 신호 read-only replay에서 pre-scan 12건, removal 6개, post-scan 0건을 확인했다. 실패 campaign의 result·attempt·charged·pilot ledger와 AIC 사용은 모두 0이다.
- **수정 파일**: `experiments/v2_3/retrieval.py:1`, `experiments/v2_3/scanner.py:1`, `experiments/v2_3/live_runner.py:1`, `tests/test_v2_3_retrieval.py:1`, `tests/test_v2_3_scanner.py:1`, `tests/test_v2_3_live_runner.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 전체 test/dry-run·독립 리뷰·commit-push 후 다음 live checkpoint 대기

### 16. 실패 이벤트와 fault-ID 변형의 fail-closed 보완 — 2026-08-09

- **수정 에이전트**: @Codex, @explorer-reviewer
- **증상/문제**: 독립 적대 리뷰에서 `incident_failed` event fsync 오류가 필수 recovery보다 먼저 전파될 수 있었고, scanner가 차단하는 `F-7`·`F_7`·`F 7` 변형을 masker가 제거하지 못했다.
- **원인**: 진단 event 기록을 recovery safety boundary 안에서 필수 작업처럼 처리했고, fault ID의 내부 separator 전용 규칙은 scanner에만 구현했다.
- **수정 내용**: 실패 event 기록은 primary error를 보존하는 best-effort 진단으로 격리해 기록 오류와 무관하게 recovery를 수행한다. masker에도 NFKC 이후 fault-ID 전용 Unicode separator pattern을 추가해 공백·하이픈·underscore·전각 변형을 제거하되 SHA/UID 내부 `f7` substring은 유지한다. disk-full mock과 fault-ID 적대 변형 회귀 테스트를 추가했다.
- **수정 파일**: `experiments/v2_3/live_runner.py:1`, `experiments/v2_3/retrieval.py:1`, `tests/test_v2_3_live_runner.py:1`, `tests/test_v2_3_retrieval.py:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 전체 136개 테스트, 180행/2,160호출 무파일·무외부호출 dry-run, `git diff --check` 통과 및 독립 재리뷰 승인

### 17. Copilot CLI 세션 상한 호환성과 campaign 선예약 gate — 2026-08-09

- **수정 에이전트**: @Codex
- **증상/문제**: campaign `v2-3-pilot-f7t1-20260809-220152`의 첫 subprocess가 CLI 1.0.78의 최소 세션 상한 30보다 낮은 `--max-ai-credits 10.0` 옵션을 거부했다.
- **원인**: adapter와 승인 문서가 현재 CLI의 세션 상한 최소값을 사전 검증하지 않았다.
- **수정 내용**: Copilot backend는 30 이상의 정수 세션 상한만 허용하고 pilot은 최소값 30을 사용한다. caller는 subprocess 전에 `누적 AIC + 세션 상한 <= campaign 360`을 강제해 상한 변경이 전체 예산 경계를 약화하지 않게 했다. manifest schema를 v2로 올리고 세션 상한 의미를 명시했다. 실패 campaign은 actual model/session/AIC 결측, charged receipt 1·정상 ledger/result 0으로 보존하며 usage uncertain으로 처리한다.
- **수정 파일**: `experiments/shared/copilot_cli.py:1`, `experiments/v2_3/config.py:1`, `experiments/v2_3/live_caller.py:1`, `experiments/v2_3/run.py:1`, `tests/test_copilot_cli.py:1`, `tests/test_v2_3_live_caller.py:1`, `tests/test_v2_3_storage_and_run.py:1`, `docs/plans/experiment_plan_v2_3.md:1`, `docs/plans/review_v2_3.md:1`, `docs/plans/v2_3_pilot_runbook.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 전체 139개 테스트, 180행/2,160호출 무파일·무외부호출 dry-run, manifest direct assertion, `git diff --check` 통과 및 독립 재리뷰 승인; live 자동 재시도 금지

### 18. Flux reconciliation에 의한 F7 처치 소실 기록 — 2026-08-09

- **수정 에이전트**: @Codex
- **증상/문제**: campaign `v2-3-pilot-f7t1-20260809-221556`에서 10m frontend 처치가 생성됐지만 120초 validator 전에 200m/100m desired state로 원복됐다.
- **원인**: live Deployment patch가 Flux `app` Kustomization의 Git desired state와 충돌했고, 10분 reconcile 주기와 겹쳐 처치가 유지되지 않았다. event 시각과 interval에 근거한 추론이며 actor audit log 직접 확인은 남은 검증 과제다.
- **수정 내용**: campaign을 결과 0행으로 무효화하고 manifest/events만 보존했다. charged·attempt·pilot ledger와 Copilot/AIC 호출 0건, recovery GREEN과 전체 cluster 정상 상태를 확인했다. 자동 재시도는 금지하고 Flux 일시 suspend와 Git-native fault injection을 다음 방법론 checkpoint의 선택지로 분리했다.
- **수정 파일**: `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 미해결 — 처치 유지 전략에 대한 사용자 승인 대기

### 19. Flux app 일시 suspend와 exact restore gate — 2026-08-10

- **수정 에이전트**: @Codex
- **증상/문제**: F7 live patch가 Flux `app` Kustomization의 reconcile과 충돌해 validator 전에 소실됐다.
- **원인**: 실험 runner가 GitOps controller의 desired-state 복원을 처치 생명주기에 포함하지 않았다.
- **수정 내용**: 사용자 승인에 따라 별도 `FluxAppGuard`를 추가했다. `flux-system/app`의 UID·resourceVersion·원래 suspend field 존재 여부·값을 mutation 전에 event journal에 fsync하고, resourceVersion CAS 응답과 suspend=true를 재조회 검증한 뒤에만 F7을 주입한다. 정상·injection 예외·partial suspend·F7 recovery 실패 모두에서 F7 복구 후 Flux field를 원래 형태로 CAS 복원하며, concurrent false 변경은 덮어쓰지 않는다. process/SIGKILL 경계는 campaign의 sealed receipt를 사용하는 독립 idempotent `flux_restore` 명령과 오케스트레이터 checkpoint로 보완한다. 어느 복구든 exact original이 아니면 결과 commit을 차단한다. manifest와 plan/review/runbook에 공통 처치 및 외적 타당성 한계를 기록했다.
- **수정 파일**: `experiments/v2_3/config.py:1`, `experiments/v2_3/flux_restore.py:1`, `experiments/v2_3/live_runner.py:1`, `experiments/v2_3/run.py:1`, `tests/test_v2_3_flux_restore.py:1`, `tests/test_v2_3_live_runner.py:1`, `tests/test_v2_3_storage_and_run.py:1`, `docs/plans/experiment_plan_v2_3.md:1`, `docs/plans/review_v2_3.md:1`, `docs/plans/v2_3_pilot_runbook.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — F7→Flux 및 pre-F7 Flux-only 강제종료 복구, truncated-tail 내성을 포함한 targeted 48개·전체 156개 테스트, 180행/2,160호출 무파일·무외부호출 dry-run, `git diff --check` 통과 및 최종 독립 재리뷰 승인

### 20. Flux root/app 계층 suspend gate — 2026-08-10

- **수정 에이전트**: @Codex
- **증상/문제**: child `app`만 suspend한 campaign에서도 F7 10m 처치가 약 12초 뒤 200m로 원복됐다.
- **원인**: 상위 `flux-system` Kustomization이 child `app` 객체 자체를 관리해 desired manifest를 재적용하면서 child suspend field를 제거했다. controller 로그의 동일 reconcile 경로에서 `Kustomization/flux-system/app: configured`와 `Deployment/boutique/frontend: configured`를 직접 확인했다.
- **수정 내용**: root와 app의 exact state를 단일 hierarchy receipt에 봉인하고 root→app CAS suspend·각 10회 안정화 후에만 F7을 주입한다. recovery/emergency는 F7 뒤 app→root exact restore를 수행하며 일부 restore 실패에도 나머지 복구를 시도한다. 실패 campaign은 result/raw/attempt/charged/pilot ledger 0건이고 cluster recovery GREEN이다.
- **수정 파일**: `experiments/v2_3/config.py:1`, `experiments/v2_3/flux_restore.py:1`, `experiments/v2_3/live_runner.py:1`, `tests/test_v2_3_live_runner.py:1`, `tests/test_v2_3_storage_and_run.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `docs/plans/experiment_plan_v2_3.md:1`, `docs/plans/review_v2_3.md:1`, `docs/plans/v2_3_pilot_runbook.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — root/app 공동 안정화·F7 직전 동시 검증·nested receipt canonical binding을 포함한 targeted 52개·전체 160개 테스트, 180행/2,160호출 무파일·무외부호출 dry-run, `git diff --check` 통과 및 최종 독립 재리뷰 승인

### 21. Copilot resolved-tools metadata schema 호환 — 2026-08-10

- **수정 에이전트**: @Codex
- **증상/문제**: 계층 격리 파일럿의 첫 Terra subprocess가 exit 0과 완전한 AIC receipt를 냈지만 `session.tools_updated` 미등록 event로 parse 실패했다.
- **원인**: CLI 1.0.78 공식 로컬 SDK가 emitting하는 transient resolved-tools metadata를 adapter가 tool execution과 구분하지 못했다.
- **수정 내용**: 해당 event는 공식 exact schema와 pinned Terra model, root/session event, ephemeral=true일 때만 허용한다. 실제 tool request/execution, MCP/remote/custom event는 계속 거부한다. 실패 campaign은 included AIC 1.9994, result/validated ledger 0, recovery GREEN으로 보존한다.
- **수정 파일**: `experiments/shared/copilot_cli.py:1`, `tests/test_copilot_cli.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 관련 60개·전체 161개 테스트와 독립 검토 묶음 70개, 180행/2,160호출 무파일·무외부호출 dry-run, `git diff --check` 통과 및 최종 독립 재리뷰 승인

### 22. Copilot skill metadata 격리 — 2026-08-10

- **수정 에이전트**: @Codex
- **증상/문제**: tools metadata 호환 후 다음 파일럿 첫 호출이 `session.skills_loaded`에서 fail-closed했다.
- **원인**: CLI는 custom instructions 비활성화와 별개로 resolved skill metadata event를 emit하며 adapter가 이를 아직 분류하지 않았다.
- **수정 내용**: mode-0700 임시 cwd·격리 `COPILOT_HOME`·빈 추가 skill dir를 만들고, 모델 호출 전 공식 `skill list --json`으로 builtin-only 집합을 확인한다. 그 전부를 공식 `disabledSkills` config(mode 0600)에 기록한 뒤 재조회해 동일 집합이 모두 disabled인지 검증한다. project/personal/plugin/custom/신규 skill 또는 inventory drift는 AIC 사용 전에 차단한다. skills event는 공식 UUID/timestamp/root/ephemeral envelope와 exact preflight 집합의 `enabled=false` metadata만 허용하며 실제 invocation은 거부한다. 실패 call은 Terra, exit0, included AIC 2.02915이고 누적 무효 파일럿 사용량은 4.02855다. 결과/validated ledger 0, recovery GREEN이다.
- **수정 파일**: `experiments/shared/copilot_cli.py:1`, `tests/test_copilot_cli.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 기존 빈 directory 방식의 독립 리뷰 반려를 반영해 공식 `disabledSkills` 이중 preflight로 교체하고, exact `session.skills_loaded` 1건을 inference binding 증거로 필수화함. targeted 16개·전체 165개 테스트, 실제 비과금 CLI preflight, 180행/2,160호출 무파일·무외부호출 dry-run, `git diff --check` 통과 및 최종 독립 재리뷰 승인

### 23. Copilot empty tool allowlist와 configuration metadata 정합화 — 2026-08-10

- **수정 에이전트**: @Codex
- **증상/문제**: skill 격리 후 campaign의 첫 Terra subprocess가 exit 0과 included AIC 2.025 receipt를 냈지만 `session.info` 미등록 event로 parse 실패했다.
- **원인**: nonempty `--available-tools=none`은 의도대로 0개 tool과 매칭하지만, CLI가 unknown-name configuration info event를 emit했고 adapter가 이를 분류하지 못했다. 값 없는 bare option은 후단에서 filter 없음으로 collapse돼 사용할 수 없다.
- **수정 내용**: nonempty sentinel allowlist를 유지하고 byte-exact `Unknown tool name in the available tools filter: none` configuration metadata 1건을 inference binding 증거로 필수화한다. isolated config는 banner와 startup tip도 끈다. 같은 exact envelope의 disabled-tools summary만 허용하고 excluded/다른 filter의 unknown, persistent/extra/duplicate/missing event와 실제 tool request/execution은 계속 fail-closed한다. 실패 campaign은 result/raw/attempt/pilot ledger 0, exact recovery GREEN으로 보존하며 exact 무효 파일럿 누적 included AIC는 6.05355다.
- **수정 파일**: `experiments/shared/copilot_cli.py:1`, `tests/test_copilot_cli.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — bare option의 tool 노출 독립 리뷰 반려를 반영해 nonempty zero-match sentinel + byte-exact available-filter metadata binding으로 교체함. targeted 17개·전체 166개 테스트, 180행/2,160호출 무파일·무외부호출 dry-run, `git diff --check` 통과 및 최종 독립 재리뷰 승인

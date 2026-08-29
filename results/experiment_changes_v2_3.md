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

### 24. Copilot native allowlist diagnostic exact binding 교정 — 2026-08-12

- **수정 에이전트**: @Codex
- **증상/문제**: 첫 `session.info` 호환 수정 뒤 재실행한 campaign도 Terra 첫 호출에서 `Copilot informational metadata is invalid`로 fail-closed했다.
- **원인**: 추정한 `available tools filter: none` 문구가 pinned CLI 1.0.78 native diagnostic의 실제 출력과 달랐다.
- **수정 내용**: native `sessionPlanToolFilterDiagnosticsForSessionJson`을 모델 호출 없이 실행해 nonempty `availableTools=['none']`의 exact 출력 `Unknown tool name in the tool allowlist: "none"`과 반대 의미인 `tool excludedlist`를 확인했다. parser는 exact allowlist event 1건만 inference binding으로 인정하고 기존 추정 문구·excludedlist·missing/duplicate/malformed metadata를 거부하도록 교정했다. 실패 campaign의 actual model은 Terra, exit 0, included AIC는 2.0857이며 result/raw/attempt/pilot ledger는 0, recovery는 GREEN이다. exact 무효 파일럿 누적 included AIC는 8.13925다.
- **수정 파일**: `experiments/shared/copilot_cli.py:1`, `tests/test_copilot_cli.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — targeted 17개·전체 166개 테스트, 180행/2,160호출 무파일·무외부호출 dry-run, `git diff --check` 통과 및 독립 read-only 재리뷰 승인

### 25. Copilot 서버 zero-overage quota 실시간 검증 — 2026-08-12

- **수정 에이전트**: @Codex
- **증상/문제**: 과거 수동 zero-overage 증거가 만료됐고, 현재 공식 SDK quota는 exhausted quota 뒤 추가 사용을 허용한다고 보고해 사용자의 별도 과금 금지 조건과 충돌했다.
- **원인**: 수동 관리자 증거와 실제 Copilot 서버 quota policy 사이의 시간적 drift를 실행기가 검증하지 않았다.
- **수정 내용**: 공식 SDK의 비추론 `account.getCurrentAuth`와 `account.getQuota`를 격리 임시 home에서 실행해 approved login `moonsangyhu`·GitHub CLI auth·Business seat SKU·token-based billing과 premium-interactions quota를 strict binding한다. 두 overage 허용 flag false, overage/overage entitlement 0, 내부 수치 정합성과 `campaign max + session max` 잔여 reserve를 모두 요구한다. 이 검사는 artifact/K8s import 전과 각 model subprocess 전에 반복되며 실패·malformed·account drift는 외부작용 전에 차단한다. 현재 서버의 true flag는 의도대로 차단됐고 조회 AIC는 0이다. quota provenance 추가에 따라 pilot manifest schema를 v3로 올렸다.
- **수정 파일**: `experiments/shared/copilot_quota.py:1`, `experiments/shared/copilot_cli.py:1`, `experiments/v2_3/config.py:1`, `experiments/v2_3/run.py:1`, `tests/test_copilot_quota.py:1`, `tests/test_copilot_cli.py:1`, `tests/test_v2_3_storage_and_run.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `docs/plans/experiment_plan_v2_3.md:1`, `docs/plans/review_v2_3.md:1`, `docs/plans/v2_3_pilot_runbook.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 관련 37개·전체 173개 테스트와 180행/2,160호출 무파일·무외부호출 dry-run 통과; 현재 live server overage=true를 model/K8s/artifact 이전에 재현 차단

### 26. 사용자 승인 paid-overage 실행 모드 — 2026-08-12

- **수정 에이전트**: @Codex
- **증상/문제**: zero-overage 전용 authorization이 사용자의 최신 결정과 충돌해, 포함 AIC가 남아 있어도 V2.3 파일럿을 진행할 수 없었다.
- **원인**: billing authorization이 관리자 hard-stop 증거 한 방식으로만 모델링되어 사용자 승인 paid-overage 실행을 사실대로 기록할 수 없었다.
- **수정 내용**: sealed authorization에 상호 배타적 `zero-overage-evidence`/`paid-overage-user-authorized` 모드를 추가하고, 후자에 전용 CLI/process gate를 요구했다. 공식 SDK quota 조회는 account·Business seat·수치 schema 검증을 유지하면서 paid mode에서는 overage 상태를 차단하지 않고 snapshot으로 반환한다. manifest schema v4에 authorization mode와 실제 quota를 기록하며, backend는 의미가 거짓인 zero-overage flag 대신 billing execution authorization을 사용한다.
- **수정 파일**: `experiments/v2_3/authorization.py:1`, `experiments/v2_3/run.py:1`, `experiments/v2_3/config.py:1`, `experiments/shared/copilot_cli.py:1`, `experiments/shared/copilot_quota.py:1`, `tests/test_v2_3_authorization.py:1`, `tests/test_v2_3_storage_and_run.py:1`, `tests/test_copilot_cli.py:1`, `tests/test_copilot_quota.py:1`, `docs/plans/v2_3_pilot_runbook.md:1`, `docs/plans/experiment_plan_v2_3.md:1`, `docs/plans/review_v2_3.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 전체 178개 테스트 통과, 실제 Business quota snapshot(overage 허용 true, 사용량 0)을 비추론 paid mode로 검증

### 27. paid-overage 파일럿 고정 명령 교정 — 2026-08-12

- **수정 에이전트**: @Codex
- **증상/문제**: runbook의 설명은 paid-overage mode로 바뀌었지만 실행 환경변수와 고정 명령 예시는 이전 zero-overage evidence mode를 가리켰다.
- **원인**: authorization 구현 변경 시 runbook의 실행 블록이 함께 교체되지 않았다.
- **수정 내용**: 현재 실행 변수를 `THESIS_V23_PAID_OVERAGE_AUTHORIZED=1`로, CLI를 `--allow-paid-overage --approval-id paid-overage-20260812`로 교정하고 legacy mode 차이를 명시했다.
- **수정 파일**: `docs/plans/v2_3_pilot_runbook.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 고정 명령과 구현 CLI/parser의 인자·gate 일치 확인

### 28. Copilot lifecycle JSONL exact binding — 2026-08-12

- **수정 에이전트**: @Codex
- **증상/문제**: 실제 CLI 1.0.78이 정상 Terra 호출에 `user.message`, turn/streaming/reasoning lifecycle event를 출력해 기존 unknown-event fail-close가 파일럿을 중단했다.
- **원인**: strict parser의 허용 schema가 기존 assistant/result/usage와 tool/skill metadata에 고정되어 최신 공식 lifecycle schema를 반영하지 못했다.
- **수정 내용**: 공식 로컬 `session-events.schema.json`과 실제 root call을 대조해 user prompt, interaction/turn/message ID, model, stream delta/final content, optional reasoning과 idle lifecycle를 exact envelope로 검증한다. tool request/execution, MCP/remote/custom, subagent/source/attachment/steering, parent-tool과 알 수 없는 field는 계속 fail-close한다. reasoning payload는 ledger에 저장하지 않는다.
- **수정 파일**: `experiments/shared/copilot_cli.py:1`, `tests/test_copilot_cli.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — actual Terra strict-parser smoke PASS, 전체 181개 테스트·dry-run PASS; 무효 파일럿 1.91085 AIC와 진단 11.00435 AIC 사용, 결과 0, recovery GREEN

### 29. V2.3 본실험 60-incident 실행·복구 경계 — 2026-08-12

- **수정 에이전트**: @Codex
- **증상/문제**: 유효 F7 파일럿 뒤에도 live runner가 F7 trial 1에 고정되어 본실험을 실행할 수 없었고, 다른 fault의 독립 treatment 검증·강제종료 recovery 및 storage/quota 관측이 없었다.
- **원인**: 파일럿 구현 범위를 본실험 lifecycle로 일반화하지 않았으며 boutique namespace 중심 collector가 cluster-scoped fault를 누락했다. F5 일부 injection은 실제 local-path 동작에서 결정적 실패 신호를 만들지 못했다.
- **수정 내용**: 본실험 manifest/store와 F1–F12×5 고정 schedule, incident별 3 rows/36 calls 원자 커밋, progress/AIC event, 전 fault live-state validator를 추가했다. 사용자 결정에 따라 본실험 campaign AIC cap은 `null`로 기록하되 매 call의 30 AIC CLI 상한·quota provenance·durable charge·실패 중단을 유지한다. 모든 fault의 pre-mutation receipt와 active-incident emergency recovery를 추가하고, F5 capacity/provisioner/affinity probe 및 cluster resource collector로 관측 가능성을 보강했다.
- **수정 파일**: `experiments/v2_3/config.py:1`, `experiments/v2_3/main_campaign.py:1`, `experiments/v2_3/injection_validator.py:1`, `experiments/v2_3/live_caller.py:1`, `experiments/v2_3/live_runner.py:1`, `experiments/v2_3/run.py:1`, `experiments/v2_3/flux_restore.py:1`, `scripts/fault_inject/injector.py:1`, `scripts/stabilize/recovery.py:1`, `src/collector/kubectl.py:1`, `tests/test_v2_3_injection_validator.py:1`, `tests/test_v2_3_flux_restore.py:1`, `tests/test_v2_3_live_caller.py:1`, `tests/test_v2_3_storage_and_run.py:1`, `docs/plans/experiment_plan_v2_3.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 전체 test/dry-run·clean commit-push 후 변경된 collector 기준 F7 t1 재파일럿 대기

### 30. Flux 계층 2단계 durable receipt — 2026-08-15

- **수정 에이전트**: @Codex
- **증상/문제**: 첫 본실험은 F1 trial 1–4의 12행·144 call을 commit한 뒤 F1 trial 5에서 root Flux만 suspend되고 app CAS 전에 실패했다. app은 원래 상태, root는 exact CAS restore돼 recovery GREEN이었지만 campaign은 불완전해 primary 결과로 사용할 수 없다.
- **원인**: root/app resourceVersion을 root 안정화 전에 동시에 봉인해, root settle 10초 동안 app resourceVersion이 전진하면 오래된 app receipt로 CAS했다.
- **수정 내용**: root settle 뒤 app pre-state를 다시 읽고 identity·원래 suspend shape/value가 동일하며 resourceVersion만 달라졌는지 검증한다. 새 full hierarchy receipt를 mutation 전에 `flux_app_recovery_receipt_refreshed`로 fsync하고, runner 반환값·recovery context를 이 정본에 결합한다. emergency restore도 active refresh receipt를 우선 선택하며 duplicate/malformed/unbound receipt를 fail-close한다. 본실험 artifact 경로를 git ignore에 추가해 clean-revision gate와 원시 provenance 보존을 양립시켰다.
- **수정 파일**: `.gitignore:1`, `experiments/v2_3/live_runner.py:1`, `experiments/v2_3/flux_restore.py:1`, `tests/test_v2_3_live_runner.py:1`, `tests/test_v2_3_flux_restore.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — targeted test 44개 통과; 전체 test/dry-run·commit-push 후 새 파일럿 대기

### 31. F4 trial 3 메모리 고갈 주입의 실행·관측 결합 — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: 두 번째 본실험은 17 incidents·51 rows·612 calls 뒤 F4 t3에서 node disruption을 관측하지 못해 fail-closed 중단됐다.
- **원인**: worker03에 `stress-ng`가 없었고 background shell은 실제 child 실패를 숨겼다. 설치 뒤에도 percentage 방식은 총 6.35 GiB만 할당해 16 GiB 노드에 압력을 만들지 못했다.
- **수정 내용**: worker03에 `stress-ng=0.19.02-1`을 설치하고, injector가 binary/version/기존-process 부재와 stale receipt/temp/log 제거·fsync, 13 GiB 절대 총량·`--vm-keep`·PID/start tick/cmdline hash receipt를 강제하도록 변경했다. production stress 300초가 validation wait 180초를 초과하도록 단일 config 계약으로 묶었다. launch identity는 node-local mode-0600 temp file fsync→atomic rename으로 보존하고 sealed preflight와 launch receipt를 runner 반환값에 병합한다. validator는 receipt와 실제 Ready/MemoryPressure를 함께 검사하며 recovery는 동일 process만 SSH 재시도로 종료한다. receipt 없는/stale PID crash window도 모든 stress process 부재 전 GREEN을 금지한다. production-command live probe는 약 40초 내 Ready=Unknown과 validator PASS를 확인했고, 첫 반환 병합 누락은 fail-closed 후 emergency recovery 20회·health PASS로 복구했다.
- **수정 파일**: `scripts/fault_inject/injector.py:1`, `experiments/v2_3/injection_validator.py:1`, `scripts/stabilize/recovery.py:1`, `tests/test_v2_3_injection_validator.py:1`, `tests/test_v2_3_live_runner.py:1`, `docs/lab-environment.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — targeted/전체 test와 offline dry-run 검증 후 새 campaign으로 처음부터 재실행 예정

### 32. Copilot skill control-metadata 단일 재시도와 사용량 합산 — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: 세 번째 본실험은 F1 t1의 3행·36 calls를 commit한 뒤 F1 t2 첫 호출에서 `session.skills_loaded` 개별 항목 검증이 비결정적으로 실패했다.
- **원인**: 실패 stdout은 durable hash만 남아 정확한 변형 필드는 미확정이다. 공식 CLI schema 대조와 추가 82회 sanitized 진단에서는 모두 동일 exact metadata가 관찰돼 지속 schema drift나 backend 누적은 재현되지 않았다.
- **수정 내용**: 엄격 skill schema는 유지하면서 개별 불변식 실패를 비민감 reason code로 분류한다. 해당 control-metadata 오류에만 최대 1회 재시도하고, 두 subprocess의 charged receipt를 모두 fsync하며 실패 시도 AIC/premium을 논리 호출 ledger에 합산한다. 두 번째 실패와 다른 모든 parser/tool/model/usage 오류는 기존처럼 즉시 중단한다. primary3는 3행/36 validated calls/37 charged attempts, recovery GREEN인 불완전 attrition으로 보존한다.
- **수정 파일**: `experiments/shared/copilot_cli.py:1`, `experiments/v2_3/live_caller.py:1`, `tests/test_copilot_cli.py:1`, `tests/test_v2_3_live_caller.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — targeted 33개·전체 204개 테스트, 180행/2,160호출 무파일·무외부호출 dry-run, `git diff --check` 및 독립 적대 검토(12 logical/13 charged, AIC cumulative 일치) 통과. 새 campaign으로 처음부터 재실행 예정

### 33. Copilot 공식 SDK empty-mode 생성시점 격리 — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: 네 번째 본실험도 F1 t1에서 builtin skill 2개가 동시에 `enabled=true`로 반복 관측되어 11 logical attempts·15 charged attempts 뒤 중단됐다. result/raw/call ledger는 0이고 21.06225 AIC의 charged provenance와 recovery GREEN만 남았다.
- **원인**: CLI prompt mode는 session 생성 요청에 `enableSkills=false`를 전달하지 않고 post-create `options.update(disabledSkills=...)`를 수행한다. 실제 RCA generator/judge 프롬프트에서 전체 builtin 집합이 간헐적으로 enabled로 로드돼 이 비활성화 경합이 재현됐다.
- **수정 내용**: V2.3 live backend를 공식 Copilot SDK `mode="empty"`로 교체해 `session.create`에 empty tool allowlist, `enableSkills=false`, config discovery/custom instructions/MCP/custom agents/remote/memory/file hooks/host git/session store 비활성과 30 AIC limit을 결합했다. 해시 고정 Node runner와 격리 home/cwd를 사용하며 native empty skill metadata, Terra tool metadata, root usage의 tool count 0, exact prompt/session/model/usage를 검증한다. strict parse 전에 기존 17-field charged journal schema로 receipt를 fsync하고, outer timeout은 새 process group 전체를 kill/wait한다. manifest schema는 pilot v5/main v2로 올려 SDK·runner SHA-256을 기록한다.
- **수정 파일**: `experiments/shared/copilot_sdk.py:1`, `experiments/shared/copilot_sdk_runner.mjs:1`, `experiments/v2_3/config.py:1`, `experiments/v2_3/main_campaign.py:1`, `experiments/v2_3/run.py:1`, `tests/test_copilot_sdk.py:1`, `tests/test_v2_3_storage_and_run.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 대표 RCA generator 10회·judge 10회 모두 skills/tools 0과 완전 usage로 통과(16.1139 AIC), 전체 210개 테스트, 180행/2,160호출 무파일·무외부호출 dry-run, Python/Node syntax와 `git diff --check` 및 독립 적대 재리뷰 통과. 새 campaign으로 처음부터 재실행 예정

### 34. Copilot SDK durable usage checkpoint 결합 — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: primary5 첫 Terra generator가 정상 SDK empty-mode call과 1.56755 AIC receipt를 만들었지만 대형 prompt에서만 emit된 `session.usage_checkpoint`를 unknown capability로 거부했다. 결과/validated ledger는 0이고 exact recovery GREEN이다.
- **원인**: SDK event allowlist가 transient usage와 최종 metrics만 포함하고 persisted cache/accounting checkpoint schema를 누락했다.
- **수정 내용**: checkpoint를 최대 1건의 root UUIDv4/timezone event로 제한하고 nano-AIU·premium 합계를 assistant usage·최종 metrics와 교차검증한다. cache state도 Terra 단일 모델, 양수 TTL, timezone expiry와 exact keys를 요구한다. process group cleanup은 timeout뿐 아니라 모든 outer interruption에도 적용한다.
- **수정 파일**: `experiments/shared/copilot_sdk.py:1`, `tests/test_copilot_sdk.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — targeted 7개와 동일 대형 RCA prompt actual Terra strict smoke, 전체 211개 테스트, 180행/2,160호출 무파일·무외부호출 dry-run, syntax/diff-check와 numeric boolean 우회 독립 적대 재리뷰 통과. clean commit-push 후 fresh campaign 재실행 예정

### 35. Copilot quota probe timeout 격리·제한 재시도 — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: primary6은 F1 t1 첫 Terra call 뒤 두 번째 call 직전 비추론 quota probe가 30초 timeout을 내 result/raw/call ledger 0인 채 중단됐다. 첫 call의 attempt/charged receipt 1건과 1.76945 AIC는 보존됐고 recovery는 GREEN이다.
- **원인**: 매 call의 account/quota binding을 새 Node SDK process로 확인하면서 timeout을 30초로 고정했다. 실제 10회 조회가 최대 28.071초여서 transient 지연 여유가 부족했고, 기존 `subprocess.run` timeout은 SDK 자식 process tree 정리를 명시적으로 보장하지 않았다.
- **수정 내용**: 비추론 probe를 독립 process group으로 실행하고 timeout을 60초로 확대했다. timeout이면 group 전체를 kill/wait한 뒤 fresh 임시 home에서 한 번만 재시도한다. 두 번째 timeout과 non-timeout 오류는 inference 전에 fail-closed하며, account·Business seat·quota exact binding은 그대로 유지한다.
- **수정 파일**: `experiments/shared/copilot_quota.py:1`, `tests/test_copilot_quota.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — timeout/interruption process-group 정리·단일 재시도·두 번째 timeout 및 non-timeout 예외 정규화 unit 11개와 실제 비추론 quota 연속 조회 10회 통과. 전체 검증·독립 리뷰 후 fresh campaign 재실행 예정

### 36. Copilot CLI version probe timeout 격리 — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: primary7은 최초 quota 확인 뒤 `copilot --version`이 15초 timeout을 내 artifact 내용·event·result/raw/ledger/charge 0, K8s mutation 0인 채 중단됐다.
- **원인**: quota 조회의 외부 process lifecycle은 보강했지만 version provenance 확인은 짧은 15초 `subprocess.run` 경계에 남아 있었다.
- **수정 내용**: version probe도 독립 process group·60초 timeout·timeout 전용 1회 재시도를 사용한다. timeout/interruption은 group kill/wait, 두 번째 timeout과 일반 프로세스 오류는 inference 전 도메인 오류로 fail-closed한다.
- **수정 파일**: `experiments/v2_3/run.py:1`, `tests/test_v2_3_storage_and_run.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — storage/run targeted 23개와 실제 비추론 pinned version 연속 조회 10회 통과. 전체 검증·독립 리뷰 후 fresh campaign 재실행 예정

### 37. 실행 전 kubectl check timeout 격리 — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: primary8 launch 전 root preflight의 첫 `kubectl get nodes`가 10초 timeout을 냈다. campaign/artifact/inference/K8s mutation/AIC는 시작 전이라 모두 0이다.
- **원인**: shared infra의 read-only kubectl check가 짧은 10초 `subprocess.run`과 raw TimeoutExpired 경계에 남아 있었다.
- **수정 내용**: kubectl check를 독립 process group·30초 timeout으로 실행하고 timeout에만 group kill/wait 뒤 한 번 재시도한다. 최종 timeout/process 생성 실패는 preflight false로 fail-closed하고 interruption은 cleanup 뒤 보존한다.
- **수정 파일**: `experiments/shared/infra.py:1`, `tests/test_infra.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — infra 적대 unit 5개와 실제 K8s/Prometheus/Loki preflight 통과. 전체 검증·독립 리뷰 후 primary8 시작 예정

### 38. paid 본실험의 quota gate를 startup account binding으로 대체 — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: primary8 startup의 비추론 SDK quota 조회가 60초씩 두 번 timeout해 artifact/inference/mutation/AIC 0으로 시작 전 중단됐다. primary6에서도 같은 per-call 조회가 30초 timeout을 냈다.
- **원인**: paid-overage 승인 뒤에도 2,160 model call마다 별도 SDK account/quota client를 시작해 비결정적 외부 failure surface를 유지했다.
- **수정 내용**: paid 본실험은 server quota를 조회하지 않고 SDK `useLoggedInUser`의 active GitHub login을 campaign 시작 시 `gh api user`로 결합한다. manifest에 quota 미조회 사유·active account·null balance를 기록한다. Terra/model/tool/skill/usage/charged receipt와 30 AIC session guard는 유지하며 legacy zero-overage/pilot quota 경로는 변경하지 않는다.
- **수정 파일**: `experiments/shared/copilot_identity.py:1`, `experiments/v2_3/main_campaign.py:1`, `experiments/v2_3/config.py:1`, `tests/test_copilot_identity.py:1`, `docs/plans/experiment_plan_v2_3.md:1`, `docs/plans/review_v2_3.md:1`, `docs/plans/v2_3_pilot_runbook.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — identity unit 5개, main wiring 통합 1개, storage/run 23개 통과. 전체 검증·독립 리뷰 후 fresh campaign 재실행 예정

### 39. CLI 실행 없는 package/native build provenance — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: primary9은 active account 확인 뒤 `copilot --version`이 60초 timeout 2회로 실패해 빈 artifact 외 inference/mutation/AIC 0으로 중단됐다.
- **원인**: 재현성 문자열 확인을 위해 native CLI process를 실행해 외부 lifecycle failure surface를 만들었고, 과거 self-report 1.0.78은 설치 package 1.0.77과도 불일치했다.
- **수정 내용**: paid main은 loader/native package JSON의 name/version과 유일한 binary mapping을 검증하고 native binary SHA-256을 직접 계산한다. manifest v4와 call ledger에 이 결합 identity 및 local source를 기록한다. model inference나 CLI daemon/network는 사용하지 않는다.
- **수정 파일**: `experiments/v2_3/run.py:1`, `experiments/v2_3/main_campaign.py:1`, `experiments/v2_3/config.py:1`, `tests/test_v2_3_storage_and_run.py:1`, `tests/test_v2_3_main_campaign.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — local build unit 2개, main wiring 통합 및 실제 package/native SHA provenance 확인 통과. 전체 검증·독립 리뷰 후 fresh campaign 재실행 예정

### 40. incident별 account API 재검증 제거 — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: primary10은 startup account·manifest·preflight 뒤 첫 incident account API가 nonzero로 실패해 result/raw/ledger/charge/mutation 0으로 중단됐다.
- **원인**: 사용자 승인 paid mode에서도 estimand와 무관한 GitHub REST account 조회를 60 incident마다 반복해 외부 failure surface를 남겼다.
- **수정 내용**: active account는 campaign 시작 시 한 번만 manifest에 봉인하고 incident 경계는 process-local authorization만 재검증한다. 실제 SDK call의 authentication, Terra/model/tool/skill/usage/charge receipt와 session limit은 유지한다.
- **수정 파일**: `experiments/v2_3/main_campaign.py:1`, `tests/test_v2_3_main_campaign.py:1`, `docs/plans/experiment_plan_v2_3.md:1`, `docs/plans/review_v2_3.md:1`, `docs/plans/v2_3_pilot_runbook.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — main wiring integration에서 identity 1회·quota 0회·incident network identity event 0을 검증. 전체 검증·독립 리뷰 후 fresh campaign 재실행 예정

### 41. SDK 추론 전 zero-usage 인증 실패 단일 재시도 — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: primary11은 F1 t1에서 성공한 SDK 호출 3건 뒤 네 번째 세션이 logged-in authentication 정보를 얻지 못해 중단됐다. result/raw/call ledger는 0, attempt 3건, charged 4건이며 성공 사용량은 1.97535 AIC다. 실패 receipt 1건은 기존 parser에서 usage unknown이었다.
- **원인**: SDK가 model call 전에 `Session was not created with authentication info or custom provider`를 냈고 routine shutdown은 premium/nano-AIU/API duration/model metrics가 모두 0이었다. 기존 backend는 성공 `assistant.usage`만 durable usage로 해석해 이 명시적인 zero-usage failure를 제한 재시도할 수 없었다.
- **수정 내용**: exact empty-mode binding·UUID·byte-exact authentication error·routine zero-usage shutdown·model/user/tool event 부재를 하나의 failure code로 봉인한다. required/optional event의 cardinality·canonical 순서와 optional UUID/timezone/ephemeral/data/parent linkage도 exact 검증한다. 해당 경우만 charged receipt에 AIC/premium/output tokens 0을 기록하고 fresh SDK session으로 최대 1회 재시도한다. 두 번째 실패와 schema/binding/message/order/usage/API/model/tool drift는 즉시 fail-closed하며, 각 subprocess receipt와 성공 논리 call의 합산 provenance를 유지한다.
- **수정 파일**: `experiments/shared/copilot_cli.py:1`, `experiments/shared/copilot_sdk.py:1`, `experiments/v2_3/live_caller.py:1`, `tests/test_copilot_sdk.py:1`, `tests/test_v2_3_live_caller.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — SDK/live-caller 23개, V2.3 관련 136개와 SDK 9개, 180행/2,160호출 무파일·무외부호출 dry-run 통과. 전체 240개 suite는 변경과 무관한 control-plane socket/process timing 2개만 실패(238 통과; process test 단독 재실행 통과, adapter socket timeout 재현). 독립 재리뷰·clean commit-push 후 fresh campaign 재실행 예정

### 42. zero-usage 인증 matcher의 persisted session-start 결합 — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: primary12도 F1 t1에서 6회 정상 Terra 호출 뒤 동일 pre-inference authentication error로 중단됐다. attempt 6건/charged 7건/알려진 3.5765 AIC, result/raw/call 0이며 exact recovery GREEN이다. 첫 수정의 matcher가 재시도를 열지 않았다.
- **원인**: 실제 SDK stdout은 runner의 `thesis.sdk.binding` 앞에 persisted `session.start`를 emit한다. 첫 수정은 binding을 첫 event로 강제해 exact zero-usage suffix가 맞아도 전체 lifecycle을 거부했다. 이는 느슨한 재시도 대신 usage unknown 중단을 선택한 fail-closed 결과다.
- **수정 내용**: 공식 로컬 SDK schema와 durable 최소 진단 2회(합계 0.0512 AIC; 두 번째 auth failure known 0.0)로 persisted start의 실제 event/data key와 안전 필드 값을 확인했다. start UUID/timezone/root, exact data keys, session/model/reasoning, remote=false, call별 actual temp cwd, Copilot 1.0.77, producer, null tier, 30 AIC limit, event schema version을 binding과 교차검증하고 canonical order를 `session.start→binding→...→zero shutdown`으로 확장한다. 각 필드 drift는 적대 테스트로 거부한다.
- **수정 파일**: `experiments/shared/copilot_sdk.py:1`, `tests/test_copilot_sdk.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — targeted 검증·독립 재리뷰·전체 V2.3 회귀·dry-run 후 clean commit-push 및 fresh campaign 재실행 예정

### 43. Flux app CAS 경쟁의 bounded receipt 재봉인 — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: primary13은 F1 t1의 root Flux suspend 뒤 app suspend merge-patch가 resourceVersion conflict로 거부돼 inference·fault injection·AIC·result/ledger 0으로 중단됐다. 자동 app already-original/root CAS restore 후 recovery GREEN이었다.
- **원인**: root settle 뒤 app receipt를 새로 봉인했지만, 그 refresh와 patch 사이에도 Flux status writer가 resourceVersion을 갱신할 수 있었다. 기존 guard는 UID와 original suspend 상태가 그대로인 transient CAS race도 한 번만 시도했다.
- **수정 내용**: app identity·original suspend field와 canonical 전체 spec SHA-256이 동일하고 resourceVersion만 전진한 경우에만 새 full hierarchy receipt를 fsync하고 최대 3회 재시도한다. normal runner는 각 fsync 직후 recovery context를 최신 receipt로 교체하고 emergency restore도 initial binding·엄격 증가 sequence를 확인한 마지막 receipt를 사용한다. 상한 초과·중복/역행 version·unrelated spec drift는 fail-closed한다.
- **수정 파일**: `experiments/v2_3/live_runner.py:1`, `experiments/v2_3/flux_restore.py:1`, `tests/test_v2_3_live_runner.py:1`, `tests/test_v2_3_flux_restore.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — Flux/live-runner targeted 58개와 전체 V2.3 회귀·dry-run·독립 리뷰 후 clean commit-push 및 fresh campaign 재실행 예정

### 44. F4-t3 memory stress 관측·복구 시간 분리 — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: primary14는 17 incidents·51 rows·612 calls 뒤 F4 t3의 36 calls까지 수행했지만 13 GiB/300초 stress로 yms-proxmox-04가 약 32분간 SSH/Ready를 잃어 normal 및 첫 emergency recovery가 실패했다. campaign은 미완료이며 attempt/charged 648, known AIC 306.7476이다.
- **원인**: disruption은 약 40초에 이미 관측 가능했지만 stress를 300초 유지해 node control-plane과 recovery SSH를 필요 이상으로 고갈시켰다.
- **수정 내용**: F4 t3만 observation wait=60초와 stress timeout=180초를 사용한다. 13 GiB 처치와 atomic PID/start/hash receipt는 유지한다. validator는 wait=60과 Ready!=True를 exact 요구하고 runner는 full collector가 injection 후 175초 안에 끝났음을 durable event로 증명한 경우만 inference한다. recovery는 shared constant의 exact command identity만 정리하며 다른 F4 trial wait=180초는 유지한다.
- **수정 파일**: `scripts/fault_inject/config.py:1`, `scripts/fault_inject/injector.py:1`, `experiments/v2_3/injection_validator.py:1`, `scripts/stabilize/recovery.py:1`, `tests/test_v2_3_live_runner.py:1`, `tests/test_v2_3_injection_validator.py:1`, `docs/lab-environment.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — targeted/전체 회귀·dry-run·독립 리뷰·clean commit-push 뒤 model-free bounded live probe와 fresh campaign 재실행 예정

### 45. F4-t3 시험 후보 내 유효 절대 처치량 재보정 — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: 13 GiB/180초 model-free probe는 60초 validator에서 `Ready=True`로 거부됐고, 별도 bounded polling에서도 123초까지 Ready 상태가 유지돼 F4-t3의 NodeNotReady 처치가 성립하지 않았다.
- **원인**: probe 시점 yms-proxmox-04의 가용 메모리가 약 14.68 GB여서 13 GiB stress가 kubelet/Ready 경계를 넘지 못했다.
- **수정 내용**: 별도 14 GiB/90초 model-free calibration에서 52.034초에 `Ready=False`가 관측되고 sealed PID exact cleanup 1회로 복구된 근거에 따라 shared 절대 처치량만 14 GiB로 조정한다. wait=60초, timeout=180초, full-collector deadline<175초, Ready!=True, PID/start/hash receipt와 다른 F4 trial wait=180초 계약은 유지한다.
- **수정 파일**: `scripts/fault_inject/config.py:1`, `tests/test_v2_3_live_runner.py:1`, `tests/test_v2_3_injection_validator.py:1`, `docs/lab-environment.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 회귀·dry-run·독립 리뷰 뒤 model-free full-collector/recovery live probe 통과를 fresh main campaign의 실행 gate로 둔다.

### 46. F4-t3 stress-ng worker별 할당 의미 결합 — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: `--vm 2 --vm-bytes 14G` live probe가 60초와 25–123초 polling 모두 Ready=True로 재현되지 않았다. 두 probe는 exact recovery GREEN, model/AIC/result write 0이었다.
- **원인**: 설치된 stress-ng 0.19.02는 `--vm-bytes`를 worker별로 적용하므로 기존 command가 16 GiB node에 최대 28 GiB를 요청해 stable 14 GiB 처치가 아니라 child OOM churn을 만들었다.
- **수정 내용**: shared `F4_T3_STRESS_VM_WORKERS=1`을 추가해 총 요청량을 14 GiB로 일치시키고, durable preflight/result receipt·validator·exact recovery command에 worker 수를 결합한다. malformed/missing worker count는 inference와 recovery 전에 fail-closed한다.
- **수정 파일**: `scripts/fault_inject/config.py:1`, `scripts/fault_inject/injector.py:1`, `experiments/v2_3/injection_validator.py:1`, `scripts/stabilize/recovery.py:1`, `tests/test_v2_3_live_runner.py:1`, `tests/test_v2_3_injection_validator.py:1`, `docs/lab-environment.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 회귀·dry-run·독립 리뷰·clean commit-push 뒤 model-free full-collector/recovery live probe 재실행 예정.

### 47. F4-t3 transient NotReady bounded observation latch — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: worker 1개·14 GiB/180초 full probe는 60초 단일 시점의 Ready=True로 안전 중단됐지만, 같은 구성의 후속 probe는 51.191초 Ready=False와 live process identity를 관측하고 full collector를 52.685초에 완료했다.
- **원인**: Node Ready가 stress 동안 단조롭게 유지되지 않는데 runner가 60초 한 점만 읽어 transient NotReady를 놓쳤다.
- **수정 내용**: F4-t3에만 40–60초, 2초 간격 bounded observation window를 적용한다. `F4DisruptionNotObserved`만 deadline까지 재시도하고 최초 NotReady를 latch하며, 다른 validator 오류는 즉시 중단한다. poll 시작과 validation 완료 elapsed를 event provenance에 포함하고 성공 완료도 60초를 넘으면 거부하며 기존 full-collector<175초·exact recovery gate를 유지한다.
- **수정 파일**: `scripts/fault_inject/config.py:1`, `experiments/v2_3/live_runner.py:1`, `experiments/v2_3/injection_validator.py:1`, `tests/test_v2_3_live_runner.py:1`, `docs/lab-environment.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — targeted/전체 회귀·독립 리뷰·clean commit-push 뒤 production window로 model-free full lifecycle probe 재실행 예정.

### 48. F4-t3 node observation timeout·schema fail-close — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: production-window probe는 첫 node poll 뒤 다음 poll 시작 전에 60초 deadline을 소진해 안전 중단됐다. recovery 8회 GREEN, model/AIC/result write 0이었다. 코드 감사에서는 빈 node `{}`도 Ready=None이라 disruption으로 오인될 수 있었다.
- **원인**: F4-t3 named-node read가 공용 kubectl 최대 60초 timeout을 사용했고 Node envelope/identity/Ready cardinality를 검증하지 않았다.
- **수정 내용**: receipt node를 shared yms-proxmox-04 정본에 load/SSH 전에 결합하고 해당 named-node read만 5초로 제한한다. 실제 timeout과 not-observed만 40–60초 window 안에서 재시도한다. 매 poll의 attempt/start/completion/outcome을 retryable·fatal·invalid·verified 모두 반환/재시도 전에 fsync한다. kind=Node, exact name, nonempty UID, conditions list, unique Ready와 허용 status를 강제해 empty/malformed/wrong/duplicate 응답은 즉시 거부한다.
- **수정 파일**: `scripts/fault_inject/base.py:1`, `scripts/fault_inject/config.py:1`, `scripts/fault_inject/injector.py:1`, `scripts/stabilize/recovery.py:1`, `experiments/v2_3/main_campaign.py:1`, `experiments/v2_3/live_runner.py:1`, `experiments/v2_3/injection_validator.py:1`, `tests/test_v2_3_injection_validator.py:1`, `tests/test_v2_3_live_runner.py:1`, `tests/test_v2_3_main_campaign.py:1`, `docs/lab-environment.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 회귀·독립 리뷰·clean commit-push 뒤 production-window model-free lifecycle probe 재실행 예정.

### 49. F4-t3 처치량과 observation deadline 실측 확정 — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: 14 GiB production-window probe는 40–58.6초 10회 모두 Ready=True로 실패했고, 첫 15 GiB probe도 60초까지 전환을 보지 못했다. 모든 실패는 inference 전 중단·exact recovery GREEN·model/AIC/result write 0이었다.
- **원인**: memory-pressure onset이 run마다 변동하며 60초 deadline이 늦은 전환을 배제했다. 처치 duration은 이미 180초라 deadline 확대가 노드 stress 시간을 늘리지는 않는다.
- **수정 내용**: worker 1개와 timeout180은 유지하고 절대 byte를 15 GiB, observation window를 40–120초/2초 polling으로 확정한다. 독립 model-free calibration 2회에서 Ready=False onset 45.079초·65.334초, full collector 46.475초·66.833초, exact recovery 3회·4회 GREEN을 확인했다. full collector<175초 gate는 유지한다.
- **수정 파일**: `scripts/fault_inject/config.py:1`, `experiments/v2_3/live_runner.py:1`, `tests/test_v2_3_injection_validator.py:1`, `tests/test_v2_3_live_runner.py:1`, `docs/lab-environment.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 수정됨 — 회귀·독립 리뷰·clean commit-push 뒤 정본 production helper로 model-free full lifecycle probe 1회 통과를 fresh main campaign gate로 둔다.

### 50. F4-t3 low-memory precursor treatment gate — 2026-08-16

- **수정 에이전트**: @Codex
- **증상/문제**: 15G/120초 정본과 page-in·16G·2-worker·170초 후보가 연속해서 실제 low memory를 만들고도 Node NotReady를 재현하지 못했다. 모든 시도는 inference 전 중단, exact recovery GREEN, model/AIC/result 0이었다.
- **원인**: stress-ng 상세 man page와 2×8G 메모리 감소 실측은 `vm-bytes`가 worker 전체 총량임을 보였고, NotReady 전환은 memory exhaustion 자체보다 kubelet lease와 kernel reclaim/OOM scheduling에 의존했다. ISS-027의 per-worker/28G 해석은 잘못됐다.
- **수정 내용**: exact command를 worker2·총15G·timeout180으로 고정한다. 10–120초 poll에서 bound process가 live이고 Node NotReady 또는 같은 host의 `MemAvailable<=2 GiB`가 확인될 때만 treatment를 승인한다. low-memory-only case는 `node_disrupted=false` precursor로 라벨링한다. 원격 identity 검사는 `set -eu`로 fail-closed하고, NotReady+SSH-timeout 예외는 sealed-launch 근거만 기록하며 memory/live identity를 관측한 것으로 표시하지 않는다. primary60과 F4-t3 제외59 sensitivity를 함께 보고한다.
- **수정 파일**: `scripts/fault_inject/config.py:1`, `experiments/v2_3/injection_validator.py:1`, `experiments/v2_3/live_runner.py:1`, `tests/test_v2_3_injection_validator.py:1`, `tests/test_v2_3_live_runner.py:1`, `docs/lab-environment.md:1`, `docs/plans/experiment_plan_v2_3.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 검증 완료 — targeted 62, V2.3 전체 156, dry-run 180/2,160 external0/fs0와 독립 리뷰를 통과했다. clean `6efd23b` production-helper probe는 66.237초 low-memory precursor, 105.737초 full collector<175, exact recovery 3회와 recovery health gate PASS, model/AIC/result 0을 확인했다. pressure 중 Loki error query 1건은 30초 timeout이었다. 별도 post-check의 첫 Loki readiness 5초도 timeout됐으나 즉시 10초 재시도에서 HTTP 200·pod 2/2를 확인했고 최종 nodes6/6·Boutique12/12·Flux5/5·Prometheus/Loki GREEN이었다.

### 51. F4-t4 nodefs-bound crash-safe disk-pressure treatment — 2026-08-17

- **수정 에이전트**: @Codex
- **증상/문제**: Primary15는 18 incidents·54 rows·648 calls를 commit한 뒤 F4-t4에서 처치를 관측하지 못해 중단됐다. 기존 구현은 root filesystem available의 95%를 4.16GB `/tmp` tmpfs에 fallocate해 실패했지만 원격 nonzero exit를 놓쳤고, Node condition만 180초 뒤 확인했다.
- **원인**: `/tmp` device 37은 kubelet nodefs `/dev/mapper/vg0-root` device 64512와 달랐다. injection·validator·recovery에 filesystem identity, allocated blocks, pre/post available과 durable crash receipt가 없었다.
- **수정 내용**: read-only preflight가 cryptographic nonce와 nodefs prestate를 수집하고 local recovery event가 fsync된 뒤에만 `/var/tmp/v23-f4t4-<nonce>` mode-0700 directory와 intent receipt를 생성한다. target available 9%, safety floor 8%로 최소 fallocate하며 device·work/file inode·size·allocated blocks·capacity·pre/post available·allocation formula를 atomic post receipt와 live validator에 교차결합한다. Ready/DiskPressure singleton과 honest treatment basis를 기록하고, recovery는 exact nonce receipt만 제거한 뒤 같은 nodefs available이 10% 이상 회복돼야 GREEN이다. 분석은 primary60과 F4-t3 제외59, F4-t4 제외59, 동시 제외58 paired sensitivity를 사전 고정한다.
- **수정 파일**: `scripts/fault_inject/config.py:1`, `scripts/fault_inject/injector.py:1`, `experiments/v2_3/injection_validator.py:1`, `scripts/stabilize/recovery.py:1`, `experiments/v2_3/analyze.py:1`, `tests/test_v2_3_injection_validator.py:1`, `tests/test_v2_3_live_runner.py:1`, `tests/test_v2_3_analyze.py:1`, `docs/lab-environment.md:1`, `docs/plans/experiment_plan_v2_3.md:1`, `docs/plans/review_v2_3.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 코드 검증 완료 — targeted 67 PASS, py_compile·diff-check PASS, dry-run 180 rows/2,160 calls/external0/fs0, 독립 reviewer APPROVE. fresh campaign 전 model-free F4-t4 lifecycle probe가 남아 있다.

### 52. F4-t4 GC endpoint와 bounded condition recovery — 2026-08-17

- **수정 에이전트**: @Codex
- **증상/문제**: clean `2d9c6ad` model-free probe는 inference·AIC·result 0 상태에서 injection 직후 nodefs available 약 9.0%와 `DiskPressure=True`를 만들었다. kubelet GC가 live available을 약 38.17GB까지 올려 기존 ongoing 8–10% validator가 처치를 거부했고, exact file cleanup 뒤에도 condition이 health timeout 동안 True로 남았다. 수동 kubelet restart 1회 뒤 즉시 exact GREEN이 됐다.
- **원인**: injection 순간의 threshold와 validation 순간의 live threshold를 같은 조건으로 취급했고, DiskPressure condition lifecycle과 GC의 available 반등을 분리하지 않았다. 후속 recovery 구현은 restart marker 직후 API condition이 stale이면 outer loop로 돌아가 kubelet을 반복 restart할 수 있었다.
- **수정 내용**: exact Node UID·Ready=True·DiskPressure=False baseline과 injection post threshold/allocation을 durable하게 봉인하고, 같은 UID의 live file identity·8% safety floor가 유지될 때 새 DiskPressure/NotReady condition을 직접 endpoint로 우선한다. precursor branch만 live `<10%`를 요구한다. recovery는 exact cleanup·available `>=10%` 뒤 비GREEN condition에서 kubelet을 invocation당 1회만 restart하고, active marker 뒤 2초 간격 최대 15회 same-UID exact GREEN을 poll한다. stale condition으로 재시작을 반복하지 않으며 영구 stale은 RuntimeError로 fail-close한다.
- **수정 파일**: `scripts/fault_inject/injector.py:1`, `experiments/v2_3/injection_validator.py:1`, `scripts/stabilize/recovery.py:1`, `tests/test_v2_3_injection_validator.py:1`, `tests/test_v2_3_live_runner.py:1`, `docs/lab-environment.md:1`, `docs/plans/experiment_plan_v2_3.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 코드 검증 완료 — targeted 67 PASS, py_compile·diff-check PASS, 독립 reviewer APPROVE. fresh campaign 전 수정 정본의 model-free F4-t4 full lifecycle probe가 남아 있다.

### 53. F4-t4 root-owned live receipt 검증 경계 — 2026-08-17

- **수정 에이전트**: @Codex
- **증상/문제**: clean `913bfc5` model-free probe는 injection post available 4,460,826,624/49,564,815,360 bytes와 `DiskPressure=True`를 만들었지만 t180 live probe marker가 없어 inference 전에 `PilotError`로 중단됐다. exact recovery는 cleanup1·kubelet restart1·condition poll2로 health GREEN이었고 model/AIC/result는 0이었다.
- **원인**: root-owned mode-0700 nonce directory와 receipt를 일반 SSH 사용자 권한의 validator가 traverse하려 했다. 원격 test가 marker 전에 실패해 malformed로 fail-closed됐다.
- **수정 내용**: F4-t4 read-only live validator에만 전체 inner command를 `shlex.quote`한 `sudo sh -c`를 적용한다. wrapper 내부 `set -eu`와 receipt/file/device/inode/size/blocks/capacity/available exact test는 모두 marker 전에 유지하고 다른 fault validator에는 sudo를 확장하지 않는다. pressure로 Evicted된 monitoring DaemonSet pod 2개만 정확히 제거하고 replacement 및 comprehensive cluster GREEN을 확인했다.
- **수정 파일**: `experiments/v2_3/injection_validator.py:1`, `tests/test_v2_3_injection_validator.py:1`, `docs/lab-environment.md:1`, `docs/plans/experiment_plan_v2_3.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 코드 검증 완료 — targeted 67 PASS, py_compile·diff-check PASS, 독립 reviewer APPROVE. clean commit 뒤 model-free F4-t4 full lifecycle probe 재실행이 남아 있다.

### 54. F4-t4 model-free full lifecycle gate GREEN — 2026-08-17

- **수정 에이전트**: @Codex
- **검증 내용**: clean `84eb369`에서 Copilot 없이 F4-t4 production helper를 실행했다. injection post available 4,460,826,624 bytes와 exact allocation 33,394,939,290 bytes를 봉인했고, t180 same-UID `Ready=True`·`DiskPressure=True`, live available 4,775,100,416 bytes와 root-owned receipt/file identity를 검증했다. collector는 181.843초에 14 metric groups·2 log groups·6 kubectl groups를 완료했다.
- **복구/안전**: exact cleanup attempts1, kubelet restart1, condition poll2 뒤 recovery health gate PASS였다. pressure로 Evicted된 monitoring DaemonSet pod 2개만 exact 삭제해 replacements 6/6을 확인했다. 최종 nodes6/6 Ready·DiskPressure/MemoryPressure false, Boutique12/12, Flux5/5, Prometheus/Loki Ready, Failed pod0, nonce workdir0이다.
- **증거**: `/tmp/v23-f4t4-probe-20260817T0120Z/probe_events.jsonl` 8 events, SHA-256 `f075061b70d5c0f7505ecc6d36e023e7d9725cabe770098c5711ca1479d44c7a`; `probe_complete` model_calls0·AIC0·result_rows0.
- **수정 파일**: `docs/lab-environment.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: GREEN — F4-t4 model-free fresh-campaign 실행 gate 충족.

### 55. Recovery disk marker와 checked-out manifest binding — 2026-08-17

- **수정 에이전트**: @Codex
- **증상/문제**: Primary16 F1-t1은 36 Terra calls(AIC 17.487)를 완료하고 Flux exact restore까지 성공했지만, five-worker disk check가 locale stderr를 숫자와 합쳐 parse하며 recovery false-RED로 중단됐다. result/raw/call은 0/0/0이다. fallback full reset은 존재하지 않는 `/tmp/thesis-rca-work` manifest를 사용했다.
- **원인**: `ssh_node`의 stdout+stderr 계약을 고려하지 않은 whole-string `int()` parse와 optional scratch clone에 대한 stale absolute path였다.
- **수정 내용**: remote `set -eu`·`LC_ALL=C df -P /`가 exact disk marker를 마지막에 1회 출력하고 parser는 exactly-one digits 0..100만 허용한다. unrelated stderr는 무시하되 missing/duplicate/invalid/timeout과 disk>=80은 RED다. full reset/F8 manifest는 `Path(__file__).resolve().parents[2]`의 checked-out revision 파일로 결합한다.
- **수정 파일**: `scripts/stabilize/health_verify.py:1`, `scripts/stabilize/recovery.py:1`, `tests/test_health_verify.py:1`, `docs/lab-environment.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 검증 완료 — targeted 71 PASS, pycompile·diff-check PASS, actual comprehensive health `(True, [])`, 독립 reviewer APPROVE. fresh campaign 재실행 예정.

### 56. F4-t4 누출 scanner/masker 복잡도 상한 — 2026-08-17

- **수정 에이전트**: @Codex
- **증상/문제**: Primary17은 F4-t3까지 18 incidents·54 rows/raw·648 calls를 commit한 뒤 F4-t4 처치 검증 후 모델 호출 전에 9분 이상 CPU 100%로 정체됐다. ledger는 648에서 증가하지 않았고 stack sample은 regex·bytearray search·GC에 집중됐다.
- **원인**: F4-t4의 수백 토큰 crash-safe shell `command`와 `ssh_output`이 일반 forbidden field value로 들어갔고, scanner/masker가 N-token term의 모든 크기 adjacent n-gram을 생성해 O(N²) pattern·O(N³) 문자열 작업을 수행했다.
- **수정 내용**: command·ssh/kubectl output을 lexical scalar에서 제외하되 nonce·path·nodefs receipt 값은 유지한다. full exact match와 최소 충분 2/3-token adjacent grams만 사용해 pattern 수를 선형으로 제한하고, forbidden term은 128 normalized tokens를 넘으면 fail-closed한다. scanner/masker provenance version을 각각 `v2.3-nfkc-alias-ngram-2`, `v2.3-procedure-mask-3`으로 갱신했다.
- **수정 파일**: `experiments/v2_3/scanner.py:1`, `experiments/v2_3/retrieval.py:1`, `experiments/v2_3/live_runner.py:1`, `tests/test_v2_3_scanner.py:1`, `tests/test_v2_3_live_runner.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 검증 완료 — 관련 73 PASS, 전체 271 PASS, F4-t4 유사 18KB command·16KB transport·22KB runtime benchmark 0.041초, dry-run과 diff-check 통과 후 fresh campaign 재실행 예정. Primary17은 KeyboardInterrupt 뒤 exact Flux restore·recovery_green, nodes6/6·Boutique12/12·Flux5/5·Prometheus/Loki GREEN과 nonce workdir/Failed pod 0을 확인했다.

### 57. 짧은 fault ID의 구조화 marker와 누출 진단 provenance — 2026-08-17

- **수정 에이전트**: @Codex
- **증상/문제**: Primary18은 F4-t4를 포함해 19 incidents·57 rows/raw·684 calls를 정상 commit한 뒤 F4-t5 node disruption 검증 직후 모델 호출 전에 `LeakageDetected`로 중단됐다. 당시 event는 error type만 보존해 match stage/category/term을 사후 감사할 수 없었다.
- **원인**: production harness lexicon이 단독 두 글자 `F4`를 금지해 UUID·pod/container hash의 독립 `-f4-` token도 누출로 판정할 수 있었다. synthetic adversarial context로 false-positive를 재현했지만 Primary18 당시 exact scan report는 보존되지 않아 직접 원인 결론은 제한한다.
- **수정 내용**: production fault marker를 `fault_id=F4`/`fault F-4`/`F4_t5`처럼 fault field 또는 scheduled trial과 결합된 Unicode-aware regex로 제한하고, 일반 scanner의 raw marker 기능과 `fault injection`/`experiment marker` 차단은 유지한다. `LeakageDetected`는 source text 없이 stage·category·kind·term hash와 context/lexicon hash를 제공하며 runner는 failure event에 이 진단을 fsync한 뒤 mandatory recovery를 수행한다. scanner version을 `v2.3-nfkc-alias-ngram-3`으로 갱신했다.
- **수정 파일**: `experiments/v2_3/scanner.py:1`, `experiments/v2_3/retrieval.py:1`, `experiments/v2_3/conditions.py:1`, `experiments/v2_3/live_runner.py:1`, `experiments/v2_3/mock.py:1`, `tests/test_v2_3_scanner.py:1`, `tests/test_v2_3_live_runner.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 검증 완료 — targeted 77 PASS, 전체 275 PASS, dry-run 180/2,160 external0/fs0, pycompile·diff-check PASS. Primary18은 `incident_failed→flux_restored→recovery_green` 후 nodes6/6·Boutique12/12·Flux5/5·Prometheus/Loki·Failed pod0 GREEN을 확인했으며 fresh campaign 재실행 예정.

### 58. compact label separator 변형의 masker/scanner 정합 — 2026-08-17

- **수정 에이전트**: @Codex
- **증상/문제**: Primary19는 19 incidents·57 rows/raw·684 calls를 commit한 뒤 F4-t5 `retrieved_procedure`에서 모델 호출 전에 leakage fail-close됐다. 안전 진단은 canonical/alias의 동일 compact term hash를 기록했고 이는 normalized `nodenotready`와 exact 일치했다.
- **원인**: scanner는 punctuation/spacing 제거 후 `NodeNotReady`와 `node not ready`를 동일하게 탐지했지만 procedure masker는 single-token 원형만 마스킹해 separator 변형을 남겼다.
- **수정 내용**: non-regex masker가 scanner와 동일한 boundaryless compact minimum 및 문자 사이 Unicode separator 허용 규칙을 사용하도록 맞췄다. `NodeNotReady`의 spaced/embedded corpus 표현을 마스킹하고, 동일 term의 category precedence를 deterministic하게 고정해 removed-span provenance와 post-mask scanner clean을 검증한다. masker version은 `v2.3-procedure-mask-4`로 올렸다.
- **수정 파일**: `experiments/v2_3/retrieval.py:1`, `tests/test_v2_3_retrieval.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 검증 완료 — targeted 78 PASS, 전체 276 PASS, dry-run 180/2,160 external0/fs0, pycompile·diff-check PASS. Primary19 F4-t5는 calls/AIC 증가 없이 exact Flux restore·recovery_green 후 종료됐으며 fresh campaign 재실행 예정.

### 59. F5-t3 infrastructure Flux guard 분리 — 2026-08-17

- **수정 에이전트**: @Codex
- **증상/문제**: Primary20은 22 incidents·66 rows/raw·792 calls를 정상 commit한 뒤 F5 t3에서 `F5 provisioner treatment is absent`로 Copilot 호출 전 중단됐다. runner가 root→app만 suspend한 동안 local-path provisioner의 replicas가 1로 복귀했다.
- **원인**: local-path provisioner Deployment는 Flux `infrastructure` Kustomization이 관리하지만, 기존 hierarchy guard의 child identity는 `app`으로 고정돼 있었다. 따라서 F5 t3의 `replicas=0` scale 처치가 sibling reconciliation으로 소실될 수 있었다.
- **수정 내용**: production Flux guard builder가 허용 목록의 `app` 또는 `infrastructure` child를 명시적으로 선택하게 했다. incident runner는 F5 t3에서만 root→infrastructure CAS suspend·exact restore를 사용하고 나머지 incidents는 root→app guard를 계속 사용한다. SIGKILL emergency restore는 sealed child receipt를 읽어 동일 child guard를 재구성하며, unsupported child identity는 fail-closed한다.
- **수정 파일**: `experiments/v2_3/live_runner.py:1`, `experiments/v2_3/flux_restore.py:1`, `experiments/v2_3/main_campaign.py:1`, `experiments/v2_3/run.py:1`, `tests/test_v2_3_live_runner.py:1`, `tests/test_v2_3_flux_restore.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 검증 완료 — targeted 87 PASS 및 `git diff --check` PASS. Primary20은 불완전 artifact로 보존하고 clean revision에서 fresh campaign을 처음부터 재실행한다.

### 60. F5-t3 infrastructure guard 모델 프리 lifecycle gate — 2026-08-17

- **수정 에이전트**: @Codex
- **검증 내용**: clean `d11c726`에서 Copilot 없이 F5-t3 production guard를 실행했다. root→`infrastructure` suspend 뒤 local-path provisioner replicas=0과 `storage-probe-pvc=Pending`을 90초 후 확인했다.
- **복구/안전**: `Recovery().recover(F5,3)` 뒤 child→root Flux CAS exact restore와 recovery GREEN을 확인했다. local-path provisioner는 1/1로 복원됐고, probe artifact `artifacts/v2_3_main/v2-3-f5t3-probe-20260817-055642/campaign_events.jsonl`의 SHA-256은 `c463f29b4f827fab36a5912eed5ef5a14994d35dc98beeea5aafe78ea8fe8500`이다.
- **수정 파일**: `docs/plans/experiment_plan_v2_3.md:1`, `docs/plans/review_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: GREEN — model_calls=0, AIC=0. fresh primary campaign은 새 ID에서 처음부터 실행한다.

### 61. SDK runner 독립 watchdog과 bounded drain — 2026-08-17

- **수정 에이전트**: @Codex
- **증상/문제**: Primary22 F1 t2가 SDK judge 호출의 `process.communicate()`에서 진행하지 않아 operator interrupt 후에만 recovery로 전환됐다. F1 t1의 3 rows/36 calls만 commit됐으며 Primary22는 불완전 artifact다.
- **원인**: Python `communicate(timeout=210)` 단일 timeout은 SDK/CLI process tree의 retained pipe descriptor 또는 selector wait 지연 시 parent-level liveness를 독립적으로 보장하지 못했다.
- **수정 내용**: SDK runner process group에 동일 deadline의 daemon watchdog을 추가해 expiry 즉시 전체 group을 kill한다. watchdog expiry는 `communicate()`가 뒤늦게 return해도 timeout으로 분류하며, timeout/interrupt 후 reaping은 15초 상한으로 제한한다. timeout 입력은 bool 제외 positive integer로 봉인했다.
- **수정 파일**: `experiments/shared/copilot_sdk.py:1`, `tests/test_copilot_sdk.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 검증 완료 — SDK unit 12 PASS, 전체 283 PASS, offline dry-run 180 rows/2,160 calls·external0·filesystem0, pycompile·diff-check PASS. clean commit-push 뒤 새 campaign에서 검증한다.

### 62. 완전 과금 JSONL 절단 1회 재시도 — 2026-08-17

- **수정 에이전트**: @Codex
- **증상/문제**: Primary23 F4 t4에서 SDK stdout JSONL 한 줄이 약 64KiB 지점에서 절단돼 strict parser가 거부했다. 해당 subprocess는 exit 0이며 Terra 모델·output token·AIC 3.1204의 durable charged receipt를 남겼지만 논리 호출은 commit되지 않았다.
- **수정 내용**: 정확히 `Copilot SDK emitted malformed JSONL`인 경우에만, 첫 시도·완전 usage/model/AIC receipt·zero side-effect empty mode 조건을 모두 만족할 때 1회 재시도한다. 두 번째 실패 또는 불완전 usage는 기존처럼 fail-closed하며, 재시도 비용은 논리 호출 AIC에 합산된다.
- **수정 파일**: `experiments/shared/copilot_cli.py:1`, `experiments/shared/copilot_sdk.py:1`, `experiments/v2_3/live_caller.py:1`, `tests/test_v2_3_live_caller.py:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: targeted 27 PASS, `git diff --check` PASS. Primary23은 불완전 artifact로 보존하고 fresh campaign에서 처음부터 재실행한다.

### 63. F7-t4 Java startup CPU-starvation 처치 검증 분기 — 2026-08-17

- **수정 에이전트**: @Codex
- **증상/문제**: Primary24는 33 incidents·99 rows/raw·1,188 validated calls를 정상 commit한 뒤 F7 t4에서 CPU 5m adservice rollout이 Ready가 아니어서 Copilot 호출 전 fail-closed했다.
- **원인**: F7 validator가 모든 trial에 Ready target pod를 요구했다. 그러나 t4 ground truth는 Java adservice의 5m startup starvation과 수 분 startup 지연을 사전 정의한다.
- **수정 내용**: exact deployment CPU limit/request·target/container identity는 유지한 채, `F7/t4/adservice/5m`에서만 resource-matched non-ready pod를 `java-startup-cpu-starvation` 처치 basis로 검증한다. 다른 F7 trial의 non-ready pod는 계속 거부한다.
- **수정 파일**: `experiments/v2_3/live_runner.py:588`, `tests/test_v2_3_live_runner.py:818`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 검증 완료 — targeted live-runner 61 PASS, pycompile·diff-check PASS. Primary24은 불완전 artifact로 보존하고 clean commit 후 fresh campaign을 처음부터 재시작한다.

### 64. SDK watchdog 권한 거부 시 runner PID cleanup 보강 — 2026-08-17

- **수정 에이전트**: @Codex
- **증상/문제**: full regression의 real watchdog child cleanup에서 `killpg` 권한 오류가 전파돼 직접 runner PID가 남을 수 있었다.
- **원인**: cleanup helper가 production 새 session의 group-kill만 가정하고 host가 group signal을 거부하는 경우를 처리하지 않았다.
- **수정 내용**: `killpg`의 `PermissionError`에서 직접-owned runner PID에 SIGKILL fallback을 수행한다. group kill 정상 경로와 process-missing 무시는 유지하고 fallback 회귀를 추가했다.
- **수정 파일**: `experiments/shared/copilot_sdk.py:397`, `tests/test_copilot_sdk.py:518`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 검증 완료 — full 286 PASS, dry-run 180/2,160 external0/filesystem0, pycompile·diff-check PASS. clean commit 후 fresh primary campaign을 시작한다.

### 65. F1 memory pre-state exact recovery — 2026-08-17

- **수정 에이전트**: @Codex
- **증상/문제**: Primary25 F1 t1의 OOM 처치 후 `rollout undo`가 cartservice memory 32Mi/32Mi를 남겨 recovery health를 막았다.
- **수정 내용**: injector가 original memory limit/request/container를 receipt에 봉인하고, 실제 주입도 해당 container로 한정한다. recovery는 exact resources를 재설정·rollout·desired equality 검증하도록 변경했다.
- **수정 파일**: `scripts/fault_inject/injector.py:286`, `scripts/stabilize/recovery.py:201`, `tests/test_f1_memory_recovery.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: F1 receipt/restore 적대 회귀 4건과 관련 79건, 전체 290 unittest, offline dry-run 180/2,160 external/filesystem 0, pycompile·diff-check PASS. Primary25은 불완전 artifact로 보존하며, 새 primary 전 model-free F1 lifecycle probe를 실행한다.

### 66. F1 sealed-memory model-free lifecycle 검증 — 2026-08-17

- **수정 에이전트**: @Codex
- **검증 내용**: clean `ded79ce`에서 F1-t1의 `32Mi` OOM 처치를 Copilot 없이 실행했다. receipt는 `server`와 pre-state request/limit `64Mi/128Mi`를 보존했고 120초 관찰 뒤 exact resource 복원과 1/1 Ready를 확인했다.
- **복구/안전**: 같은 sealed receipt로 `Recovery().recover()`가 `restore_memory_resources`, `health_check_passed=true`를 반환했고 `comprehensive_health_check(max_retries=1)`은 `(True, [])`였다. 모델 호출·AIC·primary row/raw는 모두 0이다.
- **수정 파일**: `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: GREEN — 새 full primary campaign을 clean commit에서 시작할 수 있다.

### 67. GitHub identity 503 bounded retry — 2026-08-26

- **수정 에이전트**: @Codex
- **증상/문제**: active GitHub account identity의 `gh api user`가 일시 HTTP 503을 반환하면, Copilot·fault injection 전에 primary launch가 즉시 중단됐다.
- **수정 내용**: 특정 GitHub 503 diagnostic에만 최대 한 번 재시도한다. timeout retry 상한과 account mismatch·인증 오류·기타 process failure의 즉시 fail-closed 계약은 유지한다.
- **수정 파일**: `experiments/shared/copilot_identity.py:1`, `tests/test_copilot_identity.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: targeted identity/main wiring 7 PASS. 전체 회귀·offline dry-run·clean commit 후 fresh primary26을 재실행한다.

### 68. Primary25 Flux suspend 잔여의 exact-original 복구 — 2026-08-26

- **수정 에이전트**: @Codex
- **증상/문제**: Primary25 recovery failure 뒤 Flux `app`과 `flux-system` Kustomization이 `spec.suspend=true`로 남아 다음 campaign의 pre-injection guard를 차단했다.
- **수정 내용**: Primary25 durable receipt의 original presence/value를 기준으로 두 `spec.suspend` field를 null merge-patch로 제거하고 reconcile을 요청했다. 양쪽은 new generation과 observedGeneration 일치·Ready=True까지 확인했다.
- **수정 파일**: `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: GREEN — 이번 복구 자체는 Copilot/AIC/fault injection/result를 생성하지 않았다. Primary26 pre-injection artifact는 제외하고 새 campaign ID로 재시작한다.

### 69. SDK runner JSONL partial-write 및 EAGAIN 보강 — 2026-08-27

- **수정 에이전트**: @Codex
- **증상/문제**: Primary27 F6 t2에서 SDK stdout JSONL event가 65,536 byte 부근에서 절단되어 strict parser가 `Copilot SDK emitted malformed JSONL`로 fail-closed했다. 최초 시도와 제한된 재시도 모두 과금 provenance를 남겼지만 logical call은 commit되지 않아 campaign은 26/60 incidents·78/180 rows에서 불완전 종료됐다.
- **원인**: Node `fs.writeSync()`는 pipe에 대한 부분 write byte 수를 반환하거나 transient `EAGAIN`을 던질 수 있는데 runner가 반환값을 무시했다.
- **수정 내용**: UTF-8 Buffer와 offset loop로 record 전체 write를 보장하고, `EAGAIN`은 bounded 1 ms retry로 처리한다. 0-byte·비정상·retry 소진 write는 예외로 fail-closed한다. 70,000-byte SDK event의 JSONL 완결성 회귀를 추가했다.
- **수정 파일**: `experiments/shared/copilot_sdk_runner.mjs:1`, `tests/test_copilot_sdk_runner.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 검증 완료 — SDK/live-caller targeted 29 PASS, 전체 292 unittest PASS, `node --check`·`git diff --check` PASS. Primary27은 append-only 불완전 artifact로 보존하며 새 campaign을 F1 t1부터 실행한다.

### 70. 주입 observation wait 진행 provenance 기록 — 2026-08-27

- **수정 에이전트**: @Codex
- **증상/문제**: Primary28 F1 t2에서 `injection_started`와 `injection_verified` 사이 120초 fixed wait의 시작/기한이 durable event에 없어 정상 실행이 정지로 오인돼 operator interrupt가 발생했다. F1 t1 3 rows/36 calls만 유효하고 campaign은 불완전하다.
- **원인**: runner가 injection result의 wait interval을 검증하기 전에 blocking validation helper로 진입했고, fixed-wait phase를 event journal에 표현하지 않았다.
- **수정 내용**: injection result의 wait interval을 bool 제외 integer·0..600으로 먼저 봉인하고 `injection_observation_started`를 fsync한다. fixed wait와 F4 t3 bounded poll mode를 구분해 모니터가 사전 정의 deadline을 계산할 수 있게 한다.
- **수정 파일**: `experiments/v2_3/live_runner.py:1`, `tests/test_v2_3_live_runner.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: targeted 91 PASS, full unittest·dry-run·clean commit 후 새 primary campaign을 F1 t1부터 실행한다.

### 71. 본실험 Terra inference deadline 여유 확대 — 2026-08-27

- **수정 에이전트**: @Codex
- **증상/문제**: Primary29 F3 t3의 SDK 호출이 229.938초 뒤 timeout되어 incomplete-usage charged receipt와 `incident_failed`를 남겼다. 해당 incident는 결과로 커밋되지 않았고 campaign은 12/60 incidents에서 불완전 종료됐다.
- **원인**: 본실험 SDK inference deadline 180초에 독립 watchdog cleanup grace 30초를 더한 210초 경계가 실제 Terra 지연에 부족했다.
- **수정 내용**: primary-only `PRIMARY_COPILOT_TIMEOUT_SECONDS=300`을 backend request와 parent watchdog에 전달하고, main manifest schema를 v5로 올려 timeout 값을 durable provenance로 기록한다. session AIC 30, fail-closed unknown usage, tool/skill/model isolation 및 처치 설계는 변경하지 않는다.
- **수정 파일**: `experiments/v2_3/config.py:1`, `experiments/v2_3/main_campaign.py:1`, `tests/test_v2_3_main_campaign.py:1`, `docs/plans/experiment_plan_v2_3.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: 검증 완료 — main wiring·SDK·live caller 29 PASS, offline dry-run 180 rows/2,160 calls·external0·filesystem0, `git diff --check` PASS. Primary29은 append-only artifact로 보존하고 fresh main campaign을 새 ID에서 시작한다.

### 72. Torch 초기화 후 macOS kubectl spawn 경로 보강 — 2026-08-27

- **수정 에이전트**: @Codex
- **증상/문제**: Primary30/31은 local sentence-transformer/Torch 초기화 뒤 pre-injection state snapshot의 `kubectl` subprocess가 30초씩 정체했다. Primary31은 F1 t1 scheduled까지 기록했지만 Flux suspend·fault injection·Copilot/AIC·result/raw/ledger는 0이다.
- **원인**: macOS Python에서 bare `kubectl`과 default `close_fds=True`는 fork/exec를 선택한다. native ML runtime thread가 존재하면 child exec errpipe 준비가 멈출 수 있었고, 같은 KUBECONFIG의 shell kubectl은 즉시 정상 응답했다.
- **수정 내용**: fault injector, state validator, kubectl collector, GitOps collector가 각 command executable을 절대 경로로 resolve하고 `close_fds=False`를 전달해 `posix_spawn` 조건을 충족하게 했다. fault·corpus·retrieval/model·prompt·condition은 변경하지 않는다.
- **수정 파일**: `scripts/fault_inject/base.py:1`, `scripts/stabilize/state_validator.py:1`, `src/collector/kubectl.py:1`, `src/collector/gitops.py:1`, `tests/test_kubectl_posix_spawn.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: unit/main/live-runner 65 PASS, pycompile·diff-check PASS. Torch-after-spawn read-only smoke는 model import 장기화 중 cluster mutation 전에 interrupt했고, fresh campaign의 F1 pre-injection snapshot으로 runtime 재검증한다.

### 73. Torch 초기화 후 Git revision verifier spawn 경로 보강 — 2026-08-27

- **수정 에이전트**: @Codex
- **증상/문제**: Primary32는 artifact 생성 전 `_verified_git_revision()`의 bare `git status --porcelain --untracked-files=all`가 15초 timeout되어 종료됐다. fault injection·Copilot/AIC·output artifact는 0이다.
- **원인**: ISS-047과 같은 macOS fork/exec 경로가 Git verifier에는 남아 있었다.
- **수정 내용**: Git executable을 absolute path로 resolve하고 `close_fds=False`를 지정해 `posix_spawn` 조건을 만족시킨다. HEAD SHA-256 identity 및 dirty-tree fail-closed 검사는 그대로 유지한다.
- **수정 파일**: `experiments/v2_3/run.py:1`, `tests/test_kubectl_posix_spawn.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: Git/Kubernetes spawn·storage/main wiring 30 PASS, pycompile·diff-check PASS. 전체 회귀와 dry-run 뒤 clean commit으로 fresh campaign을 재시작한다.

### 74. Git verifier의 `cwd` fork 경로 제거 — 2026-08-27

- **수정 에이전트**: @Codex
- **증상/문제**: #73의 absolute Git·`close_fds=False` 보강 뒤에도 `_verified_git_revision()`이 `cwd=project_root`를 전달해 macOS Python의 `posix_spawn` 선택 조건을 만족하지 못했다. Torch native runtime 뒤에는 같은 fork/exec 정체가 재발할 수 있다.
- **수정 내용**: `cwd`를 사용하지 않고 absolute Git command에 `-C <absolute-project-root>`를 넣어 동일한 repository binding과 clean-tree fail-closed 검사를 유지한다. 이로써 Git verifier의 executable absolute path, `close_fds=False`, `cwd=None`을 함께 고정한다.
- **수정 파일**: `experiments/v2_3/run.py:1`, `tests/test_kubectl_posix_spawn.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: Git/Kubernetes spawn·storage/run 29 PASS, `py_compile`·`git diff --check` PASS, Loki `/ready` HTTP 200 재확인. 이전 incomplete artifact는 보존·배제하고 clean commit에서 새 campaign을 시작한다.

### 75. Torch import 이전으로 Git clean-tree verifier 이동 — 2026-08-27

- **수정 에이전트**: @Codex
- **증상/문제**: Primary33은 Git command shape를 #74처럼 고정했음에도 `_verified_git_revision()`의 status가 15초 timeout으로 종료했다. 별도 shell의 같은 status command는 0.20초였고 artifact·fault injection·Copilot·AIC는 0이다.
- **원인**: `run_authorized_main()`이 Git verifier보다 먼저 `KnowledgeRetriever`를 포함한 local live dependency를 import해 Torch native runtime이 초기화될 수 있었다.
- **수정 내용**: authorization revalidate 직후 Git verifier를 모든 live/ML dependency import보다 먼저 실행한다. 기존 `git -C`, absolute executable, `close_fds=False`, full SHA·clean-tree fail-closed 계약은 유지한다.
- **수정 파일**: `experiments/v2_3/main_campaign.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: main wiring 1 PASS, `py_compile`·`git diff --check` PASS. 새 clean commit에서 fresh primary를 재시작해 runtime verifier를 확인한다.

### 76. Torch 초기화 전 GitHub account identity를 봉인 — 2026-08-27

- **수정 에이전트**: @Codex
- **증상/문제**: Primary34는 Git verifier는 통과했지만 `inspect_active_gh_account()`가 Torch 이후 timeout되어 main output store 전에 종료했다. 해당 실행은 artifact·fault injection·Copilot·AIC가 0이다.
- **수정 내용**: expected GitHub login identity probe를 Git revision 직후로 옮겨 모든 live/ML dependency import 전에 실행한다. expected-login fail-closed 및 manifest의 startup active-account provenance는 그대로 유지한다.
- **수정 파일**: `experiments/v2_3/main_campaign.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: main wiring 재검증 및 clean commit 뒤 fresh campaign에서 Git/account preflight를 함께 runtime 확인한다.

### 77. Torch 이후 infra preflight kubectl spawn 경로 보강 — 2026-08-27

- **수정 에이전트**: @Codex
- **증상/문제**: Primary35는 `authorization_verified` 뒤 preflight read-only `kubectl get`가 Torch 이후 fork/exec에서 정체했다. Ctrl-C 전 Flux suspend·fault injection·Copilot·AIC·ledger·result는 0이었고 Flux는 exact unsuspended/Ready였다.
- **수정 내용**: `_run_kubectl_check()`를 absolute executable·`close_fds=False`·direct child `kill()` timeout cleanup으로 바꿔 `posix_spawn` 조건을 충족한다. local port-forward recovery도 shell pipeline을 제거하고 exact listening PID에 SIGTERM 후 absolute `kubectl`을 `close_fds=False`로 시작한다.
- **수정 파일**: `experiments/shared/infra.py:1`, `tests/test_infra.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: infra/main wiring 6 PASS, `py_compile`·`git diff --check` PASS. 새 clean commit의 fresh campaign preflight에서 runtime 재검증한다.

### 78. GitHub identity probe의 fork 경로 제거 — 2026-08-27

- **수정 에이전트**: @Codex
- **증상/문제**: Primary36은 artifact 전 active-account probe가 timeout됐지만 동일 `gh api user` shell command는 1.31초로 성공했다.
- **수정 내용**: read-only `gh` probe에서 process-group 생성 대신 absolute executable·`close_fds=False` 및 direct child timeout cleanup을 사용한다. expected-login identity와 bounded retry/fail-closed semantics는 유지한다.
- **수정 파일**: `experiments/shared/copilot_identity.py:1`, `tests/test_copilot_identity.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: identity/main wiring 7 PASS, `py_compile`·`git diff --check` PASS. clean commit에서 fresh campaign으로 runtime 재검증한다.

### 79. null overage entitlement의 zero-usage SDK session 재시도 — 2026-08-27

- **수정 에이전트**: @Codex
- **증상/문제**: Primary39 F2 t4에서 Copilot SDK 1.0.77이 GitHub CLI의 `quota_snapshots.*.overage_entitlement=null` 응답을 인증 schema 오류로 처리해 model call 전 session.create가 exit 1로 실패했다. 자동 복구는 GREEN이었지만 campaign은 8/60 incidents에서 불완전 종료됐다.
- **원인**: official SDK가 세 overage entitlement field에 number를 요구하지만 business-seat server response가 일시적으로 null을 보냈다. 기존 retry predicate는 session.start/binding/shutdown을 포함한 다른 authentication lifecycle만 허용했다.
- **수정 내용**: 정확히 하나의 `thesis.sdk.error`, schema v1, 그리고 관측된 세-field null message 전체가 일치할 때만 zero-AIC/zero-premium complete-usage receipt로 분류해 1회 재시도한다. extra record·message drift·일반 authentication failure·tool/model/usage event는 재시도하지 않는다.
- **수정 파일**: `experiments/shared/copilot_cli.py:1`, `experiments/shared/copilot_sdk.py:1`, `experiments/v2_3/live_caller.py:1`, `tests/test_copilot_sdk.py:1`, `tests/test_v2_3_live_caller.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: SDK/live-caller targeted 31 PASS, `git diff --check` PASS. Primary39은 append-only artifact로 보존·배제하고, clean revision에서 read-only auth 확인 후 fresh campaign을 시작한다.

### 80. 연속 quota-null session 생성 오류의 bounded backoff — 2026-08-27

- **수정 에이전트**: @Codex
- **증상/문제**: Primary40 F1 t4에서 #79의 exact quota-null pre-session 오류가 두 번 연속 발생해 single retry 후 campaign이 fail-closed됐다. F1 t1–t3의 9 rows/raw·108 validated calls만 commit됐고 campaign은 불완전하다.
- **수정 내용**: `sdk_quota_null_auth_pre_session_zero_usage` 코드만 최대 두 번 재시도하고 1초·2초 backoff를 둔다. exact zero AIC·zero premium·complete-usage receipt 조건과 다른 모든 retry class의 1회 한계는 유지한다.
- **수정 파일**: `experiments/v2_3/live_caller.py:1`, `tests/test_v2_3_live_caller.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: SDK/live-caller 32 PASS, `git diff --check` PASS. Primary40은 보존·배제하고 clean revision의 새 campaign에서 재검증한다.

### 81. 짧은 field-value redaction 표식의 compact scanner 자기-누출 제거 — 2026-08-27

- **수정 에이전트**: @Codex
- **증상/문제**: Primary41 F7 t2는 injection verification 뒤 RAG procedure leakage gate에서 `field_values/compact_substring`으로 fail-closed했다. 해당 incident는 result/raw/call/attempt/charged ledger를 추가하지 않았고 exact Flux/CPU recovery 뒤 GREEN이었다.
- **원인**: `[MASKED]`의 `M`이 인접한 숫자와 scanner compact folding 후 짧은 금지 field value를 재구성했다. 원문 scalar 마스킹 자체가 아니라 redaction placeholder의 lexical collision이다.
- **수정 내용**: marker를 `[REDACTED]`로 교체하고 procedure masker provenance version을 갱신했다. five-minute range 스타일의 short scalar mask 후 scanner clean을 직접 회귀로 검증한다.
- **수정 파일**: `experiments/v2_3/retrieval.py:1`, `tests/test_v2_3_retrieval.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: retrieval/scanner/live-runner 82 PASS, corpus short-value masking 52 matching documents clean, offline dry-run 180 rows/2,160 calls·external/filesystem 0, `git diff --check` PASS. Primary41은 append-only 보존·배제하며 clean commit에서 fresh campaign을 시작한다.

### 82. Primary42 host-reboot 중단을 불완전 artifact로 격리 — 2026-08-28

- **수정 에이전트**: @Codex
- **증상/문제**: Primary42가 F6 t4 `injection_verified` 뒤 terminal event 없이 종료됐다.
- **원인**: 2026-08-28 실행 호스트 재부팅으로 tmux와 parent/SDK child process가 소실됐다. Python exception/recovery failure는 artifact에 기록되지 않았다.
- **수정 내용**: incomplete artifact를 보존·배제하고 ISS-050에 durable event 경계와 재연결 후 클러스터 GREEN 상태를 기록했다. 새 campaign ID로 F1 t1부터 fresh 60-incident run을 재개한다.
- **수정 파일**: `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: nodes 6/6 Ready·DiskPressure/MemoryPressure=False, Boutique 12/12, Flux 5/5, Prometheus/Loki GREEN을 재확인했다.

### 83. Host-reboot 뒤 잔류한 Flux suspend를 exact original로 복구 — 2026-08-28

- **수정 에이전트**: @Codex
- **증상/문제**: Primary43은 F1 t1 전 Flux guard가 `app`·`flux-system`의 stale `spec.suspend=true`를 감지해 fail-closed했다.
- **원인**: Primary42 host-reboot가 F6 t4 후 mandatory Flux restore 이전에 process를 종료했다.
- **수정 내용**: Primary42 receipt의 original absence semantics에 맞춰 두 Kustomization에만 `spec.suspend:null` merge patch 및 reconcile request를 적용했다.
- **수정 파일**: `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: Primary43은 call/result/raw/ledger 0의 pre-injection artifact로 보존·배제한다. app과 flux-system 모두 `suspend=<absent>`, Ready=True이며 app Healthy=True를 확인했다.

### 84. Full reset에서 알려진 F6 crash 잔여 NetworkPolicy를 제거 — 2026-08-28

- **수정 에이전트**: @Codex
- **증상/문제**: Primary44 F1 t1 복구가 host-crash 뒤 남은 `fault-block-dns` 때문에 fail-closed했다.
- **원인**: `kubectl apply`는 original Boutique manifest에 없는 F6 NetworkPolicy를 prune하지 않는다.
- **수정 내용**: full reset이 bounded known F6 policy name 다섯 개만 먼저 삭제하고 manifest를 적용하도록 보강했다.
- **수정 파일**: `scripts/stabilize/recovery.py:1`, `tests/test_health_verify.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: recovery regression 4 PASS, `py_compile`, `git diff --check` PASS. Primary44는 append-only로 보존·배제한다.

### 85. F7-t5 rollout 교락을 main schedule에서 명시 제외 — 2026-08-28

- **수정 에이전트**: @Codex
- **증상/문제**: Primary45는 F1–F6 전체와 F7 t1–t4를 정상 commit한 뒤 F7-t5의 currencyservice CPU 5m rollout이 120초 안에 Ready가 되지 않아 `PilotError`로 중단됐다.
- **원인**: 5m Deployment rollout이 사전 등록된 currency-conversion latency가 아니라 startup/rollout failure를 만들었다. ISS-003에서 이미 확인된 구성 타당성 위협의 재발이다.
- **수정 내용**: F7-t5 unready 상태를 성공으로 재분류하지 않는다. immutable ground truth를 보존한 채 main schedule에서 이 identity만 제외하고, manifest와 analysis CLI가 59 incidents·177 rows·2,124 calls 및 exact exclusion을 명시하게 했다.
- **수정 파일**: `experiments/v2_3/config.py:1`, `experiments/v2_3/main_campaign.py:1`, `experiments/v2_3/analyze.py:1`, `tests/test_v2_3_main_campaign.py:1`, `tests/test_v2_3_analyze.py:1`, `docs/plans/experiment_plan_v2_3.md:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: targeted 29 PASS, `git diff --check` PASS. Primary45는 append-only로 보존·배제하며 clean revision에서 새 59-incident campaign을 시작한다.

### 86. SSH disk health의 posix-spawn 보강과 kubelet fail-closed fallback — 2026-08-28

- **수정 에이전트**: @Codex
- **증상/문제**: Primary46 F2 t3은 injection·모델 평가·Flux restore 뒤 worker disk health marker를 읽지 못해 recovery를 false-RED 처리했고, 7/59 committed incidents에서 중단됐다.
- **원인**: worker SSH 관리 경로가 TCP 연결 뒤 banner/auth 단계에서 timeout됐다. `ssh_node()`도 local ML 초기화 후 fork/exec 경로를 사용할 수 있어 동일 계열 정체 위험이 남아 있었다. standalone SSH도 timeout되어 local spawn 경로만이 이번 인프라 단절의 원인이라고 단정하지 않는다.
- **수정 내용**: SSH executable을 absolute path로 resolve하고 subprocess에 `close_fds=False`를 고정하는 regression을 추가했다. SSH marker를 검증할 수 없을 때만 authenticated kubelet nodefs summary의 node identity·capacity/available·5분 freshness를 검증해 `<80%` gate를 적용한다. stale/malformed/inconsistent kubelet 응답은 pass하지 않으며 F4의 SSH-dependent mutation/recovery는 계속 fail-closed다.
- **수정 파일**: `scripts/fault_inject/base.py`, `scripts/stabilize/health_verify.py`, `tests/test_kubectl_posix_spawn.py`, `tests/test_health_verify.py`, `docs/lab-environment.md`, `docs/issues/experiment_issues_v2_3.md`, `results/experiment_changes_v2_3.md`
- **상태**: targeted 11 PASS, actual worker disk health `[]`, `git diff --check` PASS. Primary46은 append-only 보존·배제하고 clean revision의 fresh 59-incident campaign에서 재검증한다.

### 87. Terra SDK runner의 Torch-after-fork 경로 제거 — 2026-08-28

- **수정 에이전트**: @Codex
- **증상/문제**: Primary47 F1 t1의 첫 Terra 호출 뒤 다음 SDK call이 watchdog timeout되고, 이어지는 recovery `kubectl` mutation도 Python subprocess timeout으로 실패했다.
- **원인**: SDK runner가 Torch/tokenizers 초기화 뒤 `cwd`와 `start_new_session=True`를 사용해 macOS posix_spawn 대신 fork/exec를 강제했다. Node/pipe lifecycle 정체와 같은 실행 구간에서 관측됐다.
- **수정 내용**: sealed request의 `working_directory` binding은 유지하면서 Python runner subprocess의 `cwd`와 `start_new_session`을 제거하고 absolute Node+`close_fds=False`로 launch한다. watchdog cleanup은 직접 소유 runner PID로 한정한다.
- **수정 파일**: `experiments/shared/copilot_sdk.py`, `tests/test_copilot_sdk.py`, `docs/issues/experiment_issues_v2_3.md`, `results/experiment_changes_v2_3.md`
- **상태**: SDK 15 PASS, full V2.3 178 PASS, health/spawn 26 PASS, dry-run 180 rows/2,160 calls·external/filesystem 0, `git diff --check` PASS. Primary47은 append-only 보존·배제하고 clean revision에서 재시작한다.

### 88. GitHub identity probe의 bounded timeout reap — 2026-08-28

- **수정 에이전트**: @Codex
- **증상/문제**: Primary49는 artifact 생성 전 GitHub identity subprocess timeout 뒤 무기한 reap 대기에 머물렀다.
- **원인**: killed direct `gh` child 뒤에도 descendant가 stdout/stderr descriptor를 보유하면 timeout 없는 `communicate()`가 종료되지 않을 수 있었다.
- **수정 내용**: 5초 bounded reap 뒤 pipe를 close하고 원래 timeout을 fail-closed로 전파하도록 변경했다.
- **수정 파일**: `experiments/shared/copilot_identity.py`, `tests/test_copilot_identity.py`, `docs/issues/experiment_issues_v2_3.md`, `results/experiment_changes_v2_3.md`
- **상태**: identity+SDK 22 PASS, full V2.3 178 PASS, `git diff --check` PASS. Primary48/49는 artifact-free 실행으로 보존·배제한다.

### 89. 실제 workload container identity로 F2/F3/F8/F9 patch 및 검증 결합 — 2026-08-29

- **수정 에이전트**: @Codex
- **증상/문제**: Primary52 F8 t4에서 readiness treatment validator가 실패하고 일반 recovery도 GREEN에 도달하지 못했다. 조사 결과 F2 t4 shippingservice에 `exit 1` sidecar가 남아 있었고, 이전 F2 t1 paymentservice에서도 같은 패턴의 과거 ReplicaSet가 확인됐다.
- **원인**: injector가 strategic-merge patch의 `containers[].name`에 deployment/service명(`shippingservice`)을 사용했지만 실제 workload 컨테이너명은 `server`였다. Kubernetes가 기존 container를 mutate하지 않고 새 sidecar를 추가했고, validator도 deployment명 기반 lookup을 사용했다.
- **수정 내용**: base helper가 primary container name/image를 fail-closed로 해석한다. F2/F3/F8-t4/F9는 receipt의 `container_name`과 함께 정확한 container만 patch하며, validator는 receipt-bound container를 검증한다. 긴급 복원 뒤 잔류 shippingservice sidecar를 exact JSON patch로 제거하고 Flux/GitOps 상태를 GREEN으로 수렴시켰다.
- **수정 파일**: `scripts/fault_inject/base.py:1`, `scripts/fault_inject/injector.py:1`, `experiments/v2_3/injection_validator.py:1`, `tests/test_fault_inject_container_identity.py:1`, `docs/issues/experiment_issues_v2_3.md:1`, `results/experiment_changes_v2_3.md:1`
- **상태**: identity regression 5 PASS, full V2.3 178 PASS, `git diff --check` PASS. Primary52는 append-only 보존·배제하고 fresh main campaign으로 처음부터 재시작한다.

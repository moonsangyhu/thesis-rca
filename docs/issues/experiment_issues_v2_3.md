# V2.3 실험 이슈 트래커

## 요약

- 총 이슈: 9건
- 심각(실험 무효화): 7건
- 경고(실행 전 수정): 2건
- 참고(영향 미미): 0건

## 이슈 목록

### [ISS-001] 실행 agent의 nohup child가 executor 종료와 함께 소멸

- **카테고리**: infra
- **심각도**: warning (P2)
- **영향**: V2.3 F7 trial 5 pilot 첫 launch attempt. Python authorization/output-store 진입 전 종료되어 유효 실험 데이터는 생성되지 않음.
- **발생 빈도**: 1회
- **관찰한 사실**: 보고된 PID 48358이 즉시 사라졌고 agent 환경의 nohup log는 0 bytes였다. campaign artifact, result CSV, raw, validated ledger, charged-call ledger는 모두 0개였다. currencyservice CPU limit은 정상 200m였고 5m fault residual은 없었다.
- **근본 원인**: agent execution 환경에서 background child가 command executor 종료 시 유지되지 않은 것으로 추정한다. 0-byte log라 더 구체적인 Python-level 원인은 입증할 수 없다.
- **현재 영향**: Copilot 호출·AIC charge receipt·fault injection 모두 0건. 6/6 nodes Ready, DiskPressure False, Boutique 12 deployments 1/1, Prometheus/Loki Ready, residual policy/quota/limit과 Failed pod 0으로 복구 확인.
- **수정 방안**: agent-side `nohup ... &`를 사용하지 않고 root orchestration 환경의 지속 PTY exec session에서 명령을 실행한다. 새 campaign ID를 사용하고 PID/session ID·log/artifact를 root에서 직접 교차 검증한다. 자동 재시도는 하지 않으며 수정 기록·commit-push 후 한 번만 재실행한다.

### [ISS-002] live launcher의 Python 환경·Chroma 경로 결합 오류

- **카테고리**: code
- **심각도**: warning (P1)
- **영향**: V2.3 F7 trial 5 pilot 두 번째 launch attempt. authorization/output-store 생성 전 import 단계에서 종료되어 유효 실험 데이터는 생성되지 않음.
- **발생 빈도**: 1회
- **관찰한 사실**: 전역 Python 3.11에서 `scripts.fault_inject.base` import 시 `ModuleNotFoundError: No module named 'yaml'`로 종료했다. repo venv에는 PyYAML 6.0.3, ChromaDB 0.5.23, sentence-transformers 3.4.1이 존재했지만, `src.rag` 패키지 import가 `KnowledgeRetriever`의 기본 worktree Chroma 경로를 먼저 고정해 외부 동결 Chroma 경로 override도 적용되지 않았다. artifact/result/raw/ledger/charged receipt는 모두 0개였고 currencyservice는 desired=1, ready=1, CPU limit=200m였다.
- **근본 원인**: launch interpreter를 명시하지 않았고, `KnowledgeRetriever`가 module import 시 고정된 전역 `CHROMA_DIR`만 사용해 V2.3의 명시적 `--chroma-dir`를 안전하게 주입할 수 없었다.
- **현재 영향**: Copilot 호출·AIC charge receipt·fault injection 모두 0건. 실패 log는 `/tmp/v2_3_pilot_20260809_2105.log`에 보존했다.
- **수정 방안**: live launch를 `/Users/yumunsang/thesis-rca/.venv/bin/python`으로 고정하고 `KnowledgeRetriever(chroma_dir=...)` 생성자 경계에서 검증된 디렉터리를 직접 전달한다. targeted unittest 11개와 offline mode의 실제 Chroma 조회 2건을 통과한 뒤에만 새 campaign ID로 실행한다.
- **관련 로그**:
  ```text
  ModuleNotFoundError: No module named 'yaml'
  RuntimeError: ChromaDB not found at /Users/yumunsang/thesis-rca-v2-3-terra/data/chromadb.
  ```

### [ISS-003] F7 5m rollout 교락과 recovery false-GREEN

- **카테고리**: injection / recovery
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-pilot-20260809-2145`의 F7 trial 5 pilot 전체. post-injection validator에서 중단되어 결과 0행이며 primary dataset에 포함할 수 없음.
- **발생 빈도**: 1회
- **관찰한 사실**: currencyservice desired CPU를 5m로 변경한 뒤 새 pod가 120초 동안 Ready가 되지 못하고 4회 재시작했다. old 200m pod만 Ready인 상태라 post-injection validator가 `post-injection live CPU state does not match injector receipt`로 Copilot 호출 전에 차단했다. attempt/charged/pilot ledger와 result는 모두 0개다. recovery는 잘못된 `kubectl rollout restart deployment --all` 오류를 출력했고, campaign event에 `recovery_green`을 기록했지만 실제 Deployment desired CPU는 5m로 남아 있었다.
- **근본 원인**: F7 t5의 5m 처치가 currencyservice readiness와 양립하지 않아 CPU throttling 이외의 rollout/재시작 교락을 만들었다. recovery는 주입 전 CPU 값을 receipt에 보존하지 않고 revision-based undo와 일반 pod health만 사용해, old 정상 pod가 Ready이면 desired-state 잔류를 놓쳤다. Kubernetes 현재 CLI에는 `rollout restart ... --all` flag도 없다.
- **현재 영향**: 수동으로 `deployment/currencyservice`를 정상 revision으로 undo해 desired limit/request 200m/100m, generation=observed, updated/ready/available=1을 확인했다. Boutique 12/12 deployment, 6/6 node Ready, Disk/MemoryPressure False, Flux 5/5 Ready, Prometheus/Loki Ready, residual/Failed pod 0, disk 25–43%로 복구 완료했다. Copilot/AIC 사용은 0이다.
- **수정 방안**: runner가 injector의 target container와 원래 CPU limit/request를 mutation 전에 캡처해 fsync event로 봉인하고, 그 context를 recovery state로 먼저 보유한 뒤에만 주입한다. 따라서 API가 apply 직후 timeout을 내도 원래 상태가 남는다. F7 recovery는 revision undo 대신 해당 값을 명시적으로 복원하고 generation·updated·ready·available·resource exact match가 모두 맞아야 통과한다. namespace-wide restart는 F11/F12에만 제한하고 실제 deployment 목록을 순회하며 F10의 미지원 restart는 제거한다. F7 t5의 5m 처치 자체는 유효한 Ready 상태를 만들지 못했으므로 자동 재시도하지 않고 별도 pilot target/limit 방법론 결정을 거친다.
- **관련 로그**:
  ```text
  kubectl stderr: error: timed out waiting for the condition
  kubectl stderr: error: unknown flag: --all
  experiments.v2_3.live_runner.PilotError: post-injection live CPU state does not match injector receipt
  ```

### [ISS-004] runtime query masker와 scanner n-gram 규칙 불일치

- **카테고리**: data / code
- **심각도**: critical (P1)
- **영향**: campaign `v2-3-pilot-f7t1-20260809-2230` 전체. F7 trial 1 처치 검증은 통과했지만 retrieval query gate에서 중단되어 결과 0행이며 primary dataset에 포함할 수 없음.
- **발생 빈도**: 1회
- **관찰한 사실**: `frontend/server` 10m pod는 Ready=true, restart=0으로 post-injection validator를 통과했다. 이후 `LeakageDetected: forbidden leakage detected: 6 match(es)`가 발생해 Copilot 호출 전에 중단했다. recovery event 이후 frontend limit/request 200m/100m, generation=observed, updated/ready/available=1과 전체 cluster GREEN을 확인했다. attempt/charged/pilot ledger와 result는 모두 0개다.
- **근본 원인**: masker는 긴 canonical label·alias·injection command 전체 문자열만 제거했지만 scanner는 그 문자열의 부분 token n-gram도 차단했다. 또한 masker의 word boundary가 underscore를 word 문자로 취급해 `cpu_throttling`, `F7_t1`을 제거하지 못했다. 반대로 scanner는 2글자 fault ID에 일반 compact-substring을 적용해 SHA/UID 내부의 우연한 `f7`도 차단했다.
- **현재 영향**: Copilot 호출과 AIC 사용 0. 실제 직전 5분 collector 신호를 read-only로 재수집한 replay에서 query pre-scan 12건, 원문 좌표 removal 6개, post-scan 0건을 확인했다. 원문 runtime/정답 문자열은 출력하지 않고 category count만 검증했다.
- **수정 방안**: masker version을 올리고 scanner와 동일한 category별 n-gram을 긴 순서로 원문에서 제거한다. underscore를 separator로 취급하는 Unicode boundary를 사용한다. fault ID는 `F-7`, `F_7`, `F 7`, 전각 변형을 막는 전용 경계 규칙으로 분리하고 hash 내부 substring은 허용한다. fail-closed 예외에는 원문 없이 category count를, campaign event에는 error type만 기록한다. 동일 fault는 자동 재시도하지 않고 전체 검증·독립 리뷰·commit-push 후 다음 실행 checkpoint로 넘긴다.
- **관련 로그**:
  ```text
  experiments.v2_3.scanner.LeakageDetected: forbidden leakage detected: 6 match(es)
  ```

### [ISS-005] Copilot CLI 세션 AIC 최소값과 adapter 상한 불일치

- **카테고리**: code
- **심각도**: critical (P1)
- **영향**: campaign `v2-3-pilot-f7t1-20260809-220152` 전체. F7 trial 1 처치와 retrieval gate는 통과했지만 첫 Copilot subprocess의 option validation에서 중단되어 결과 0행이다.
- **발생 빈도**: 1회
- **관찰한 사실**: CLI 1.0.78은 `--max-ai-credits 10.0`을 거부하며 최소 30 AIC를 요구했다. charged-call receipt 1건에는 exit code 1, actual model·session·AIC가 모두 결측이고, attempt/pilot ledger는 0건이다. 따라서 실제 추론 실행이나 AIC 0을 주장하지 않고 usage uncertain으로 분류한다. recovery 이후 frontend 200m/100m, Boutique 12/12, 노드 6/6, 모니터링과 잔여 리소스가 모두 GREEN이다.
- **근본 원인**: 계획과 adapter가 CLI help의 현재 최소 세션 상한을 사전 검증하지 않고 10.0을 고정했다.
- **현재 영향**: 해당 campaign은 무효이며 자동 재시도하지 않는다. 별도 과금은 관리자 paid-usage disabled와 budget hard-stop으로 차단돼 있으나, included AIC 변화는 UI 사후 관측 전까지 미확정이다.
- **수정 방안**: CLI 세션 상한을 허용 최소 정수 30으로 변경하고, 각 호출 전에 누적 AIC와 다음 세션 최악 상한의 합이 campaign 360 이하인지 검사한다. CLI 최소값 적대 테스트, campaign 사전 예약 테스트, manifest schema와 비용 문서를 함께 갱신한다.
- **관련 로그**:
  ```text
  Invalid value for --max-ai-credits: "10.0". Use at least 30 AI credits.
  ```

### [ISS-006] Flux reconciliation이 F7 처치를 validator 전에 원복

- **카테고리**: injection
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-pilot-f7t1-20260809-221556` 전체. 결과 0행이며 실험 데이터로 사용할 수 없다.
- **발생 빈도**: 1회
- **관찰한 사실**: `recovery_receipt_sealed`와 `injection_started` 뒤 10m frontend ReplicaSet/pod가 생성됐지만, 120초 validator 시점의 Deployment는 다시 limit/request 200m/100m였다. Kubernetes events에는 10m ReplicaSet scale-up과 수 초 뒤 pod 종료/scale-down이 남았고, Flux `app` Kustomization은 interval 10m, suspend=false, Ready=true였다. campaign은 `incident_failed(PilotError)` 후 `recovery_green`으로 끝났고 manifest/events 외 charged·attempt·pilot ledger와 result/raw 파일은 생성되지 않았다.
- **근본 원인**: F7을 live Deployment에 직접 patch했지만 GitOps desired state는 200m/100m여서, 예약된 Flux reconciliation이 fault desired state를 validator 전에 원복했다. 이는 event 시각·reconcile interval과 일치하는 원인 추론이며 controller audit log로 actor를 직접 식별한 것은 아니다.
- **현재 영향**: Copilot subprocess와 AIC 사용은 0건이다. frontend generation=observedGeneration, limit/request 200m/100m, updated/ready/available=1, Boutique 12/12, 노드 6/6, 모니터링·잔여 리소스가 모두 GREEN이다.
- **수정 방안**: 자동 재시도하지 않는다. 다음 설계 checkpoint에서 (A) `flux-system/app` Kustomization의 기존 suspend 상태를 mutation 전에 fsync하고 파일럿 동안만 suspend한 뒤 recovery에서 원래 상태로 복원하거나, (B) fault를 Git desired state로 주입하는 방법 중 하나를 선택한다. RAG-only 단일변수 파일럿에는 A가 최소 변경이지만 GitOps 동작 정지라는 실험 조건을 manifest와 위협요인에 명시해야 한다.
- **상태 (2026-08-10)**: 사용자가 A안을 승인했다. runner는 Flux identity·resourceVersion·원래 suspend field 존재 여부·값을 mutation 전에 fsync하고 CAS suspend 검증 뒤 F7을 주입한다. F7 recovery 실패와 partial suspend 예외에도 Flux 원상복원을 별도로 시도하고, concurrent 변경은 덮어쓰지 않는다. process/SIGKILL 경계에는 sealed receipt를 읽는 독립 idempotent `experiments.v2_3.flux_restore` 명령을 오케스트레이터가 실행한다. exact restore가 아니면 결과 commit과 후속 실험을 금지한다.
- **관련 로그**:
  ```text
  PilotError: post-injection live CPU state does not match injector receipt
  ```

### [ISS-007] 상위 Flux Kustomization이 하위 app suspend를 제거

- **카테고리**: injection / recovery
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-pilot-f7t1-20260810-0648-flux` 전체. 결과 0행이며 실험 데이터로 사용할 수 없다.
- **발생 빈도**: 1회
- **관찰한 사실**: runner는 `flux-system/app`의 suspend=true를 확인한 뒤 F7 t1 10m ReplicaSet을 생성했지만 약 12초 뒤 200m ReplicaSet으로 원복됐다. kustomize-controller 로그에는 상위 `flux-system` Kustomization이 `Kustomization/flux-system/app: configured`를 적용하고 이어 `Deployment/boutique/frontend: configured`를 적용한 고유 reconcile ID가 남았다. validator가 Copilot 전에 차단했고 campaign은 `incident_failed(PilotError)→flux_restored→recovery_green`으로 종료됐다. result/raw/attempt/charged/pilot ledger는 모두 0개다.
- **근본 원인**: `app` Kustomization은 독립 객체가 아니라 상위 `flux-system` Kustomization의 관리 대상이다. child만 suspend하면 root의 다음 server-side apply가 child의 desired manifest에서 absent인 suspend field를 제거하고 app reconciliation을 다시 활성화한다.
- **현재 영향**: frontend/server limit/request 200m/100m, generation=observedGeneration=29, updated/ready/available=1, Flux app suspend absent·Ready, 노드 6/6, Boutique 12/12, Prometheus/Loki, 잔여 리소스와 Failed pod 0으로 GREEN이다. Copilot subprocess와 AIC charge receipt는 0건이다.
- **수정 방안**: root `flux-system`과 child `app`의 identity/resourceVersion/original suspend shape를 하나의 durable hierarchy receipt로 봉인한다. root를 CAS suspend하고 10회 연속 안정 상태를 확인한 뒤 child를 CAS suspend·안정화하고 F7을 주입한다. recovery는 F7 exact restore 후 child→root 역순 exact restore를 수행한다. SIGKILL emergency 경로도 같은 hierarchy receipt를 사용한다.
- **관련 로그**:
  ```text
  Kustomization/flux-system/app: configured
  Deployment/boutique/frontend: configured
  PilotError: post-injection live CPU state does not match injector receipt
  ```

### [ISS-008] Copilot CLI transient tools metadata event 미등록

- **카테고리**: code
- **심각도**: critical (P1)
- **영향**: campaigns `v2-3-pilot-f7t1-20260810-0702-hierarchy`, `v2-3-pilot-f7t1-20260810-0711-metadata` 전체. F7 처치·수집·retrieval을 통과했지만 각각 첫 generator call session metadata parse에서 중단되어 결과 0행이다.
- **발생 빈도**: 2회
- **관찰한 사실**: root/app hierarchy suspend 뒤 frontend/server 10m/10m, generation=observedGeneration, updated/ready/available=1이 120초 유지되어 injection validator를 통과했다. 첫 Copilot subprocess는 exit 0, actual model `gpt-5.6-terra`, session ID, output 179 tokens, included AIC 1.9994를 durable receipt에 남겼다. strict parser가 `session.tools_updated`를 unrecognized로 거부해 정상/attempt/pilot ledger와 result/raw는 0건이다. 이후 F7 200m/100m와 app→root exact restore, `recovery_green`을 확인했다.
- **근본 원인**: CLI 1.0.78의 로컬 공식 SDK schema는 `session.tools_updated`와 `session.skills_loaded`를 각각 resolved tool/skill metadata를 알리는 ephemeral session event로 정의하지만 adapter allowlist는 assistant/result/usage 세 이벤트만 허용했다. 또한 빈 `COPILOT_SKILLS_DIRS`는 discovery 경로를 대체하지 않고 추가할 뿐이어서 builtin skill까지 사전 격리하지 못했다. 이 metadata는 실제 `tool.*`/skill invocation과 다르지만, skill이 enabled인 상태도 실험 입력 오염 가능성이 있어 허용할 수 없다.
- **현재 영향**: 두 campaign은 무효다. included AIC 1.9994 + 2.02915 = 4.02855가 사용됐으며 actual balance의 UI 사후 확인은 아직 하지 않았다. 관리자 paid usage disabled와 budget hard stop 때문에 별도 과금 경로는 차단돼 있다. cluster는 GREEN이다.
- **수정 방안**: `session.tools_updated`는 로컬 SDK의 exact schema(UUIDv4, timezone timestamp, parentId, ephemeral=true, root event, data model=Terra)일 때만 metadata로 허용한다. skill은 매 inference 전 mode-0700 임시 cwd와 격리 `COPILOT_HOME`에서 공식 `skill list --json`으로 두 번 검증한다. 첫 목록은 builtin-only여야 하며, 이를 공식 `disabledSkills` 설정(mode 0600)에 전부 기록한 뒤 두 번째 목록에서 같은 집합이 모두 disabled인지 확인한다. discovery drift·project/personal/plugin/custom skill은 모델 subprocess 전에 중단한다. `session.skills_loaded`도 exact envelope, builtin-only, exact preflight 집합, `enabled=false`일 때만 허용한다. agentId·추가 field·model drift·malformed payload, skill invocation, `tool.*`, MCP/remote/custom event와 assistant tool request는 계속 fail-closed한다. 적대 테스트·전체 검증·독립 리뷰 후 새 campaign만 실행한다.
- **관련 로그**:
  ```text
  RuntimeError: unrecognized Copilot event type: session.tools_updated
  LiveCallerError: Copilot CLI call failed after durable charge receipt
  RuntimeError: unrecognized Copilot event type: session.skills_loaded
  ```

### [ISS-009] 빈 tool allowlist를 `none` sentinel로 잘못 전달

- **카테고리**: code
- **심각도**: critical (P1)
- **영향**: campaigns `v2-3-pilot-f7t1-20260810-0730-skillisolated`, `v2-3-pilot-f7t1-20260810-0750-zerotool` 전체. 두 실행 모두 F7 처치·120초 validator·수집·retrieval을 통과했지만 첫 generator call metadata parse에서 중단되어 결과 0행이다.
- **발생 빈도**: 2회
- **관찰한 사실**: 두 실행 모두 root/app hierarchy suspend와 frontend/server 10m/10m Ready 상태가 120초 유지돼 `injection_verified`를 통과했다. 첫 Copilot subprocess는 각각 exit 0, actual `gpt-5.6-terra`, 완전한 usage metadata와 included AIC 2.025/2.0857을 durable charged receipt에 기록했다. 첫 실행은 미등록 `session.info`, 두 번째 실행은 잘못 추정한 exact message 때문에 fail-closed했다. 둘 다 frontend 200m/100m exact recovery, app→root exact restore와 `recovery_green`을 확인했으며 attempt/pilot ledger와 result/raw는 0건이다.
- **근본 원인**: adapter는 0개 tool과 매칭시키기 위해 nonempty allowlist `--available-tools=none`을 사용했다. 이 값은 특별한 sentinel이 아니라 의도적으로 존재하지 않는 실제 이름이므로 filter 결과는 0개지만, CLI가 unknown-name configuration `session.info`를 emit한다. 최초 수정은 이를 `Unknown tool name in the available tools filter: none`으로 추정했으나 pinned CLI 1.0.78 native `sessionPlanToolFilterDiagnosticsForSessionJson`의 실제 출력은 `Unknown tool name in the tool allowlist: "none"`이었다. 반대로 excluded 경로는 `tool excludedlist`로 구분되며, 값 없는 bare option은 CLI 후단에서 `undefined`로 접혀 필터 없음이 되므로 안전한 대안이 아니다.
- **현재 영향**: 두 campaign은 무효다. 지금까지 exact usage가 확인된 무효 파일럿 included AIC는 1.9994 + 2.02915 + 2.025 + 2.0857 = 8.13925다. 실제 UI balance 사후 관측은 아직 하지 않았고, 관리자 paid usage disabled와 budget hard stop으로 별도 과금 경로는 차단돼 있다. cluster는 frontend 200m/100m, Boutique 12/12, node 6/6 Ready, Flux root/app unsuspended·Ready, Prometheus/Loki ready로 재확인했다.
- **수정 방안**: nonempty `--available-tools=none`을 유지해 filter semantics와 0-match를 보존한다. 격리 config에는 startup banner/tip off를 명시한다. 모델 호출 결과에는 공식 UUIDv4/timezone/root/ephemeral envelope, exact `infoType=configuration`, native에서 비과금 재현한 byte-exact `Unknown tool name in the tool allowlist: "none"` metadata를 정확히 1건 필수화해 argv→session filter binding을 증명한다. `tool excludedlist`, 기존 추정 문구, 다른 이름·추가 field·persistent/duplicate/missing sentinel event와 모든 tool request/execution은 계속 거부한다. 부수적인 `Disabled tools: ` summary만 같은 envelope로 허용한다. 적대 테스트·전체 검증·독립 리뷰·commit-push 전 재실행하지 않는다.
- **관련 로그**:
  ```text
  RuntimeError: unrecognized Copilot event type: session.info
  LiveCallerError: Copilot CLI call failed after durable charge receipt
  ```

### [ISS-010] Copilot 서버 quota가 추가 사용 허용으로 변경됨

- **카테고리**: billing / external state
- **심각도**: critical (P0)
- **영향**: 2026-08-12 파일럿 재개 전체. stale billing evidence gate와 새 server quota gate가 Copilot 추론 및 K8s mutation 전에 실행을 차단한다.
- **발생 빈도**: 1회 확인, 매 호출 전 재검증 예정
- **관찰한 사실**: Copilot CLI `/usage`는 entitlement 50,000 AIC 중 34,100 사용, 15,900 잔여, 현재 session 0 AIC를 표시했다. 같은 인증 계정 `moonsangyhu`를 공식 SDK의 비추론 `account.getQuota`로 조회한 결과 `premium_interactions`는 `hasQuota=true`, `overage=0`, `overageEntitlement=0`이지만 `usageAllowedWithExhaustedQuota=true`와 `overageAllowedWithExhaustedQuota=true`였다. 이는 2026-08-09 수동 `paid usage disabled` 확인서와 현재 서버 상태가 충돌함을 뜻한다. stale evidence로 시작한 campaign ID는 authorization 단계에서 artifact 생성·Copilot 호출·K8s mutation 전에 종료됐고 AIC 사용은 0이다.
- **근본 원인**: 관리자 설정이 변경됐거나 과거 수동 증거가 현재 실제 quota policy를 완전히 반영하지 못했다. 현재 증거만으로 어느 쪽인지 단정하지 않는다.
- **현재 영향**: 사용자의 별도 과금 절대 금지 조건 때문에 파일럿과 본실험을 실행할 수 없다. cluster는 frontend 200m/100m, Boutique 12/12, nodes 6/6 Ready, Flux root/app unsuspended·Ready, Prometheus/Loki ready다.
- **수정 방안**: pinned Copilot 공식 SDK의 `account.getCurrentAuth`와 `account.getQuota`를 model inference 없이 실행한다. approved login `moonsangyhu`, GitHub CLI auth, Business plan, `copilot_for_business_seat_quota`, token-based billing을 상호 binding한다. premium-interactions의 두 overage 허용 flag가 모두 false, overage/overage entitlement가 모두 0, token-based quota가 active, 포함 잔여량이 `campaign max + session max` 이상일 때만 K8s import·artifact 생성으로 진행한다. 동일 gate를 각 Copilot subprocess 직전에도 반복하며, schema/필드/SDK/Node 오류는 모두 fail-closed한다. 서버 설정이 false로 바뀌기 전에는 승인 문자열이나 로컬 환경변수로 우회하지 않는다.
- **관련 로그**:
  ```text
  AuthorizationError: billing confirmation is stale
  CopilotQuotaError: Copilot server permits paid/additional usage after included AIC exhaustion
  ```

### [ISS-011] 사용자 결정으로 paid-overage 실행 모드 전환

- **카테고리**: billing / experiment authorization
- **심각도**: info (resolved decision)
- **영향**: ISS-010의 서버 overage=true 차단을 해제하고 F7 trial 1 파일럿을 재개한다.
- **발생 빈도**: 사용자 지시 1회(2026-08-12)
- **관찰한 사실**: 사용자는 회사 과금 정책이 사용을 막는 것이 아니라 추가 과금 허용 때문에 실험기가 중단됐다는 설명을 받은 뒤, 실험을 계속하고 앞으로 해당 조건을 신경 쓰지 말라고 명시했다. 당시 비추론 SDK snapshot은 Business seat, entitlement 50,000 AIC, used 34,100, remaining 15,900, exhausted-quota/overage 허용 flag 모두 true, 실제 overage 0이었다.
- **수정 내용**: authorization을 `zero-overage-evidence`와 `paid-overage-user-authorized` 두 상호 배타적 모드로 분리한다. 후자는 전용 CLI/process gate를 요구하고 서버 정책을 차단 대신 provenance로 기록한다. account/Business seat binding, 30 AIC session cap, 360 AIC pilot campaign cap, durable charge receipt, model/tool/skill isolation과 recovery gate는 유지한다.
- **현재 영향**: billing policy는 더 이상 파일럿 blocker가 아니다. clean commit 및 cluster preflight 후 실행 가능하다.

### [ISS-012] Copilot CLI 1.0.78 lifecycle JSONL schema drift

- **카테고리**: code / external interface
- **심각도**: P1 (파일럿 1회 무효, 복구 성공)
- **영향**: campaign `v2-3-pilot-f7t1-20260812-2113-paidoverage`는 F7 injection 검증 뒤 첫 Terra 응답에서 `user.message`를 인식하지 못해 결과 commit 전에 중단됐다.
- **발생 빈도**: 무효 파일럿 1회, schema 진단 호출 11회
- **관찰한 사실**: 첫 파일럿 호출은 actual model `gpt-5.6-terra`, exit 0, 1.91085 AIC였고 durable charged ledger 1건에 기록됐다. pilot/attempt/result/raw는 모두 0이다. runner는 frontend/server를 200m/100m로 복구하고 Flux app→root를 원래 absent suspend field로 CAS 복원한 뒤 `recovery_green`을 기록했다. 공식 로컬 schema와 실제 JSONL에는 `user.message`, turn/model-call/message streaming, optional reasoning, usage, idle lifecycle가 포함된다. schema 진단 11회는 총 11.00435 AIC를 사용했다.
- **근본 원인**: 기존 strict parser가 tool/skill metadata 변화는 추적했지만 새 정상 lifecycle event를 allowlist에 포함하지 않았다.
- **수정 내용**: 제출 prompt의 byte-exact `user.message` binding, UUIDv4/timezone/root/empty-attachment 검증, turn/model/message ID와 interaction ID 교차결합, delta→final content 일치, optional reasoning delta/final 결합, lifecycle singleton/incomplete gate를 추가했다. subagent/source/attachment/steering/parent-tool/unknown extra field는 계속 거부하며 reasoning content는 결과 provenance에 저장하지 않는다.
- **현재 영향**: 실제 Terra smoke call이 strict parser를 통과했고 전체 181개 테스트와 180행/2,160호출 dry-run이 통과했다. clean commit에서 새 campaign 재실행 가능하다.
- **관련 로그**:
  ```text
  LiveCallerError: unrecognized Copilot event type: user.message
  authorization_verified → injection_verified → incident_failed → flux_restored → recovery_green
  ```

### [ISS-013] 파일럿 전용 runner와 cluster-resource 관측 공백

- **카테고리**: code / data / recovery
- **심각도**: P0 (본실험 시작 전 차단, live 영향 없음)
- **영향**: 기존 구현은 F7 trial 1 한 incident만 허용하고 F7 CPU 상태만 독립 검증했다. F5 storage 및 F10 quota의 cluster-scoped 상태는 boutique 전용 collector에 포함되지 않았고, 강제종료 비상복구도 단일 F7 receipt만 처리했다.
- **발생 빈도**: 본실험 실행 전 정적 검토 1회. Copilot 호출·K8s mutation·AIC 사용은 0이다.
- **근본 원인**: Step 4a 파일럿 안전 경계를 먼저 완성하면서 Step 4b의 60-incident lifecycle, 전 fault treatment validator, 반복 receipt 선택을 구현하지 않았다. 기존 F5 trial 2의 500Gi local-path PVC는 provisioner가 실제 용량을 예약하지 않아 bind될 수 있고, trial 3/5는 실패를 소비하는 probe가 없어 처치가 runtime evidence에 드러나지 않을 수 있었다.
- **수정 내용**: fresh `artifacts/v2_3_main/<campaign>` 저장소, 60-incident 고정 루프, paid-overage unbounded campaign mode와 30 AIC session guard, F1–F12 live-state validator를 추가했다. injector는 모든 fault의 pre-mutation recovery identity를 봉인한다. emergency restore는 마지막 `recovery_green` 이후 active receipt만 선택해 해당 fault/trial을 복구한 뒤 Flux app→root를 복원한다. collector는 bounded cluster PVC/PV/quota/LimitRange/NetworkPolicy 및 non-boutique unhealthy pod를 항상 수집한다. F5 trial 2는 1Gi available PV 대비 500Gi claim, trial 3은 provisioner-down probe PVC, trial 5는 bad-affinity PVC 소비 pod로 처치를 결정적으로 관측한다.
- **현재 영향**: 코드·dry-run·적대 unit 검증 후 변경된 collector commit에서 36-call F7 t1 파일럿을 다시 수행해야 한다. 새 파일럿이 GREEN일 때만 본실험을 시작한다.

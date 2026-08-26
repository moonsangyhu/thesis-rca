# V2.3 실험 이슈 트래커

## 요약

- 총 이슈: 48건
- 심각(실험 무효화): 42건
- 경고(실행 전 수정): 5건
- 참고(영향 미미): 1건

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

### [ISS-014] Flux root 안정화 중 app resourceVersion drift로 본실험 중단

- **카테고리**: recovery / code
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260812-primary1`은 F1 trial 1–4만 12행·12 raw·144 call을 commit한 뒤 F1 trial 5의 모델 호출 전에 중단됐다. 불완전 캠페인이므로 V2.3 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 1회, 결정적 적대 unit 재현 1회
- **관찰한 사실**: F1 t5는 `incident_scheduled → flux_recovery_receipt_sealed → incident_failed(PilotError) → flux_restored → recovery_green` 순서다. `flux_suspended`, injection receipt/start, charged/attempt/call ledger 증가는 없었다. 복구 결과는 app `already-original`, root `cas-restored`로, root만 suspend된 partial hierarchy 상태와 일치한다. 클러스터는 Flux root/app suspend absent, Boutique 12/12, node 6/6 Ready, 잔여 fault resource 없음으로 GREEN이다.
- **근본 원인**: hierarchy receipt가 root와 app의 resourceVersion을 root mutation 전에 동시에 봉인했다. runner가 root를 suspend한 뒤 10초 안정화하는 동안 app 객체의 resourceVersion이 바뀌면, app CAS는 오래된 receipt를 사용해 실패한다. app version을 root settle 중 20→21로 변경한 적대 unit에서 stale receipt 실패를 재현했다.
- **수정 내용**: root receipt를 먼저 봉인·suspend·안정화한 뒤 app pre-state를 다시 읽는다. identity·원래 suspend field shape/value가 초기 receipt와 동일하고 resourceVersion만 달라졌을 때만 전체 hierarchy receipt를 `flux_app_recovery_receipt_refreshed` event로 fsync한 후 app CAS를 수행한다. runner는 반환 receipt를 이 두 번째 정본과 byte-equivalent하게 검증하고 recovery에도 이를 사용한다. SIGKILL emergency restore는 active incident의 refresh event가 있으면 이를 우선 사용하며 중복·malformed·초기 receipt와의 binding 불일치는 거부한다.
- **현재 영향**: 기존 12행은 operational attrition 증거로 보존한다. 전체 검증과 clean commit 후 새 36-call F7 t1 파일럿을 통과해야만 새 campaign ID로 60-incident 본실험을 처음부터 실행한다.

### [ISS-015] F4 trial 3 stress-ng 의존성 누락과 percentage 할당 과소 주입

- **카테고리**: injection / infra / data
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260815-primary2`은 F1 t1부터 F4 t2까지 17 incidents·51 rows·612 calls를 commit한 뒤 F4 t3에서 중단됐다. 불완전 campaign이므로 V2.3 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 1회, bounded live probe 2회
- **관찰한 사실**: worker03(`yms-proxmox-04`)에는 `stress-ng`가 설치되어 있지 않았다. 기존 background 명령은 stderr를 버리고 parent shell 성공만 반환했다. validator는 180초 뒤 Ready=True·MemoryPressure=False를 관측해 모델 호출 전에 차단했다. `incident_failed(PilotError)→flux_restored→recovery_green`이 기록됐고 F4 t3 결과·raw·call은 0건이다. 6/6 node, Boutique 12/12, Flux, Prometheus/Loki와 실험 잔여물 0을 확인했다.
- **근본 원인**: node-level binary preflight와 durable launch receipt가 없었다. 설치 후 기존 `--vm-bytes 90%` probe는 stress-ng가 당시 가용 7.04 GiB의 90%인 총 6.35 GiB만 할당해 MemAvailable 약 7.1 GiB, Ready=True, MemoryPressure=False에 머물렀다.
- **수정 내용**: worker03에 Debian `stress-ng=0.19.02-1`을 설치했다. injector는 사전 binary/version/기존-process 부재와 root-owned stale receipt/temp/log의 sudo 제거·fsync를 수행하고, 13 GiB 절대 총량, `--vm-keep`, PID·start tick·cmdline hash launch receipt를 강제한다. production timeout 300초는 고정 validation wait 180초보다 길다. 90초 calibration과 production-command lifecycle probe 모두 약 40초 안에 `Ready=Unknown`·SSH timeout을 만들었다. launch identity는 mode-0600 temp file fsync→atomic rename으로 보존하고 preflight receipt와 launch receipt를 반환값에 병합한다. recovery는 동일 process만 재시도 종료하며 receipt가 없거나 stale PID인 crash window도 모든 `stress-ng*` 부재 전 GREEN을 금지한다. 실제 lifecycle probe의 첫 recovery는 병합 전 반환 계약 누락을 fail-closed로 드러냈고, sealed preflight receipt를 사용한 emergency recovery는 20회 재시도 후 health PASS했다.
- **현재 영향**: 코드·전체 test·dry-run·clean commit-push 후 새 campaign ID로 60 incidents를 처음부터 재실행해야 한다. 기존 51 rows는 operational attrition 증거로만 보존한다.

### [ISS-016] Copilot CLI prompt-mode의 비결정적 skill 비활성화

- **카테고리**: code / external interface / data
- **심각도**: critical (P0)
- **영향**: `primary3`은 F1 t1의 1 incident·3 rows·36 calls 뒤 F1 t2에서 중단됐다. 1회 metadata 재시도를 추가한 `primary4`도 F1 t1에서 11 validated logical attempts·15 charged attempts 뒤 중단됐고 result/raw/call ledger는 0이다. 두 campaign 모두 불완전하므로 V2.3 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 2회. 단순 JSON prompt 진단 82회에서는 재현되지 않았으나, 실제 RCA generator 10회 중 2회와 judge 10회 중 1회에서 builtin 2개가 동시에 `enabled=true`로 재현됐다.
- **관찰한 사실**: primary3의 거부 call은 exit 0·Terra·AIC 2.50295였고, primary4는 15 charged attempts에 21.06225 AIC를 기록했다. primary4의 두 번째 metadata retry도 `enabled_state`로 실패했다. 진단에서 변형된 두 entry는 `customize-cloud-agent`, `github-pr-media`뿐이며 exact builtin schema와 `userInvocable=false`를 유지한 채 둘 다 동시에 `enabled=true`였다. primary4는 `incident_failed(LiveCallerError)→flux_restored→recovery_green` 뒤 6/6 node, Boutique 12/12, Flux 5개, Prometheus/Loki가 GREEN이다.
- **근본 원인**: 로컬 CLI 1.0.78 prompt mode는 session 생성 요청에 `enableSkills=false`를 전달하지 않고, 세션 생성 뒤 `options.update(... disabledSkills ...)`를 호출하며 이 실패도 log만 남기고 계속한다. 실제 RCA prompt에서 전체 builtin 집합이 간헐적으로 enabled로 관측된 사실과 결합하면 post-create 비활성화가 초기 skill load보다 늦어지는 경쟁으로 판단한다. 반면 공식 Copilot SDK `mode="empty"`는 `session.create` 자체에 `enableSkills=false`와 empty tool allowlist를 전달한다.
- **수정 내용**: CLI prompt-mode backend의 재시도에 의존하지 않고 V2.3 live 경로를 공식 Copilot SDK empty-mode backend로 교체한다. 매 call은 격리 home/cwd, `availableTools=[]`, `tools=[]`, `enableSkills=false`, config discovery/custom instructions/MCP/custom agents/remote/session store/file hooks/host git/memory 비활성, 30 AIC session limit을 session creation에 결합한다. native `session.skills_loaded=[]`, `session.tools_updated`의 pinned Terra model, root usage의 `availableToolCount=0`·`numToolCalls=0`, exact model/prompt/usage/session과 해시 고정 runner를 모두 검증하고 charge receipt는 strict parse 전에 보존한다.
- **현재 영향**: 공식 SDK 기능 smoke와 대표 RCA generator 10회·judge 10회가 모두 Terra·skills 0·tools 0·완전 usage로 통과했다. 20회 workload 진단 사용량은 16.1139 AIC다. 전체 회귀검증·독립 리뷰·clean commit-push 후 새 campaign ID로 처음부터 재실행한다.

### [ISS-017] Copilot SDK 대형 prompt의 durable usage checkpoint 미등록

- **카테고리**: code / external interface / data
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260816-primary5`은 F1 t1 injection·수집·retrieval 뒤 첫 generator call에서 중단됐다. result/raw/attempt/call ledger는 0이고 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 1회, 동일 대형 RCA prompt 진단 4회 연속 재현
- **관찰한 사실**: 첫 SDK call은 Terra, skills 0, tool count 0, 완전 usage와 1.56755 AIC를 charged ledger 1건에 보존했다. strict event allowlist가 `session.usage_checkpoint`를 거부했다. 단순 JSON smoke에서는 이 event가 없었으나 5천 token급 RCA prompt에서는 매번 발생했다. native event는 `assistant.usage`와 같은 `totalNanoAiu`·premium 합계, Terra cache expiry/TTL을 담는 persisted root event였다. `incident_failed(LiveCallerError)→flux_restored→recovery_green` 뒤 6/6 node pressure false, Boutique 12/12, Flux 5/5, Prometheus/Loki ready를 확인했다.
- **근본 원인**: 공식 SDK empty-mode 전환 시 live event allowlist에 transient `assistant.usage`와 최종 metrics는 포함했지만, 대형 prompt의 cache/accounting window를 durable하게 기록하는 정상 `session.usage_checkpoint`를 포함하지 않았다. capability 노출이 아니라 billing provenance schema 누락이다.
- **수정 내용**: checkpoint는 최대 1건의 persisted root UUIDv4/timezone event만 허용한다. exact data의 `totalNanoAiu`·`totalPremiumRequests`를 assistant usage와 최종 session metrics에 교차결합하고, model cache state는 pinned Terra·양수 TTL·timezone expiry의 단일 entry만 허용한다. duplicate/extra/malformed/model/usage drift는 fail-closed한다. 또한 KeyboardInterrupt/SystemExit 등 outer interruption에서도 Node와 SDK-spawned CLI process group을 kill/wait한다.
- **현재 영향**: 동일 대형 RCA generator strict smoke가 Terra·정상 schema·완전 receipt로 통과했다. 전체 검증·독립 리뷰·clean commit-push 후 fresh campaign으로 처음부터 재실행한다.

### [ISS-018] 매 호출 전 SDK quota probe의 30초 timeout

- **카테고리**: infra / external interface
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260816-primary6`은 F1 trial 1의 첫 generator를 완료한 뒤 두 번째 호출 직전 quota 확인에서 중단됐다. result/raw/call ledger는 0이므로 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 1회. 실제 비추론 quota 연속 조회 10회는 5.670–28.071초 범위였으며, 30초 경계가 정상 지연 분포에 지나치게 가까웠다.
- **관찰한 사실**: logical attempt와 charged receipt 각 1건에 Terra call 1.76945 AIC가 보존됐다. 두 번째 inference subprocess는 시작되지 않았고 Python `subprocess.TimeoutExpired`가 quota guard에서 발생했다. campaign은 `incident_failed(TimeoutExpired)→flux_restored→recovery_green`으로 종료됐으며 6/6 node pressure false, Boutique 12/12, Flux 5/5, Prometheus/Loki ready를 확인했다.
- **근본 원인**: 각 model call 직전 공식 SDK의 비추론 `account.getQuota`를 새 Node process로 조회하면서 timeout을 30초로 고정했다. 조회 시간 자체가 최대 28초대였고, `subprocess.run`은 timeout 시 SDK가 생성한 자식 process group을 명시적으로 정리하지 않으며 transient timeout 재시도도 없었다.
- **수정 내용**: quota probe를 새 process group에서 실행하고 60초 timeout 시 group 전체를 SIGKILL·wait한다. timeout에만 fresh 임시 home으로 정확히 1회 재시도하며, 두 번째 timeout·nonzero exit·malformed/account drift는 기존처럼 inference 전에 fail-closed한다. timeout/retry 인자는 bool을 포함한 비정상 값을 거부한다.
- **현재 영향**: 비추론 연속 조회 10회가 모두 동일 Business account/quota snapshot으로 통과했다. 전체 test·dry-run·독립 리뷰·clean commit-push 뒤 fresh campaign으로 처음부터 재실행한다.

### [ISS-019] Copilot CLI version probe의 15초 timeout

- **카테고리**: infra / external interface
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260816-primary7`은 최초 quota/account binding 뒤 `copilot --version` 확인에서 중단됐다. inference·K8s mutation·campaign event·result/raw/ledger/charge는 모두 0이고 빈 artifact 디렉터리만 남았다.
- **발생 빈도**: 본실험 1회. 수정 후 실제 version probe 연속 10회는 모두 pinned `GitHub Copilot CLI 1.0.78.`을 반환했다.
- **관찰한 사실**: Python `subprocess.TimeoutExpired`가 15초 version probe에서 발생했다. 종료 직후 6/6 node pressure false, Boutique 12/12, Flux 5/5 Ready·suspend 없음으로 실험 환경이 변경되지 않았음을 확인했다.
- **근본 원인**: quota probe만 60초 timeout과 제한 재시도를 적용했고, 뒤따르는 별도 CLI version provenance 확인은 기존 `subprocess.run(..., timeout=15)`을 유지했다. 외부 CLI 시작 지연에 대한 동일한 process lifecycle 계약이 적용되지 않았다.
- **수정 내용**: version probe도 새 process group에서 실행하고 60초 timeout에만 fresh process로 정확히 1회 재시도한다. timeout/interruption은 group 전체를 SIGKILL·wait하고, 두 번째 timeout과 non-timeout 오류는 inference 전에 `RuntimeError`로 정규화한다. invalid timeout/retry 입력은 거부한다.
- **현재 영향**: targeted storage/run 테스트와 실제 비추론 CLI version 연속 확인을 통과했다. 전체 test·dry-run·독립 리뷰·clean commit-push 뒤 fresh campaign으로 재실행한다.

### [ISS-020] 실행 전 kubectl preflight의 10초 timeout

- **카테고리**: infra
- **심각도**: warning (P1)
- **영향**: primary8 launch 직전 root preflight에서 `kubectl get nodes`가 10초 timeout을 냈다. campaign은 시작하지 않았고 inference·artifact·K8s mutation·AIC 사용은 0이다.
- **발생 빈도**: 실행 전 점검 1회. 직후 직접 조회와 보강된 preflight는 6/6 node, Boutique 12/12, Prometheus/Loki ready로 통과했다.
- **관찰한 사실**: 동일 K8s API가 timeout 직후 6개 node Ready·Disk/MemoryPressure false를 반환해 클러스터 장애가 아니라 일시적인 API/터널 응답 지연으로 확인됐다.
- **근본 원인**: shared preflight의 read-only kubectl 두 호출이 `subprocess.run(..., timeout=10)`에 고정됐고 TimeoutExpired를 bool failure로 정규화하지 않아 실행기 밖으로 raw exception이 누출됐다.
- **수정 내용**: read-only kubectl check를 독립 process group에서 30초간 실행하고 timeout일 때 group kill/wait 후 정확히 1회 재시도한다. 두 번째 timeout·process 생성 실패는 `None`으로 정규화해 preflight가 false로 fail-closed하며 KeyboardInterrupt/SystemExit은 cleanup 뒤 보존한다. 같은 helper를 legacy health check에도 적용한다.
- **현재 영향**: timeout/second-timeout/interruption/invalid-input/preflight-failure 적대 unit 5개와 실제 lab preflight가 통과했다. 전체 검증·독립 리뷰·clean commit-push 후 primary8을 시작한다.

### [ISS-021] paid mode의 per-call SDK quota 조회가 실행 안정성을 지배

- **카테고리**: external interface / experiment harness
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260816-primary8`은 최초 account/quota binding이 60초 timeout 2회로 실패해 시작되지 않았다. artifact·event·inference·K8s mutation·AIC는 모두 0이다.
- **발생 빈도**: primary6의 call 전 30초 timeout 1회와 primary8의 startup 60초 timeout 2회. 앞선 연속 진단 10회는 성공했으므로 지속적인 인증 실패가 아니라 비결정적 SDK account service 지연이다.
- **관찰한 사실**: timeout 뒤 Copilot/Node 잔류 process는 없었고 6/6 node pressure false, Boutique 12/12로 lab은 변경되지 않았다. 동일 active GitHub account는 `gh api user`에서 승인 login으로 확인됐다.
- **근본 원인**: 사용자가 paid-overage를 허용한 뒤에도 본실험이 model call마다 별도의 SDK client를 시작해 `account.getQuota`를 재조회했다. 이 조회는 estimand나 inference isolation과 무관하지만 2,160개 call 각각에 외부 failure surface와 수초~수십초 지연을 추가했다.
- **수정 내용**: paid-overage 본실험에서는 server quota를 실행 gate/provenance로 사용하지 않는다. SDK가 `useLoggedInUser=true`로 사용하는 active GitHub login을 model-free `gh api user`로 campaign 시작 시 확인한다. manifest는 quota 미조회 사유와 active-account provenance를 명시하고 balance를 `null`로 기록한다. 각 model call의 Terra/model/tool/skill/usage/charge receipt 검증과 30 AIC session limit은 유지한다. legacy zero-overage와 별도 pilot의 strict quota gate는 변경하지 않는다.
- **현재 영향**: identity probe unit 5개와 main wiring 통합 1개가 통과했다. 통합 검증은 quota 0회, startup identity 1회, manifest v4의 null billing timestamp/quota 미조회 provenance를 직접 확인한다. 전체 검증·독립 리뷰·clean commit-push 후 fresh campaign으로 재실행한다.

### [ISS-022] CLI `--version` 실행이 provenance gate를 비결정적으로 중단

- **카테고리**: external interface / reproducibility
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260816-primary9`은 active account 확인 뒤 `copilot --version`이 60초 timeout 2회로 실패했다. 빈 artifact directory 외 event/inference/K8s mutation/AIC는 0이다.
- **발생 빈도**: primary7 15초 timeout, primary9 60초 timeout 2회. 중간 실제 진단 10회는 성공해 native CLI process 시작이 비결정적임을 확인했다.
- **관찰한 사실**: 설치 package metadata는 loader `@github/copilot@1.0.77`, native `@github/copilot-darwin-arm64@1.0.77`이며 native binary SHA-256은 로컬에서 결정적으로 계산됐다. CLI self-report는 과거 `1.0.78`이어서 package metadata와도 불일치했다.
- **근본 원인**: 재현성 provenance를 얻기 위해 native CLI를 실행했지만, 이 subprocess 자체가 daemon/network 상태에 영향을 받았다. self-report 문자열은 설치 package version과 불일치해 단독 provenance로도 약했다.
- **수정 내용**: paid main은 CLI를 실행하지 않고 loader/native package JSON의 name/version, 유일한 native binary mapping과 binary SHA-256을 로컬 파일에서 검증한다. manifest v4와 call ledger의 `cli_version`에는 두 package identity와 native hash를 함께 기록하고 source를 `local-package-and-native-sha256`으로 명시한다. 별도 pilot의 기존 runtime version probe는 변경하지 않는다.
- **현재 영향**: local package/native hash unit 2개, main wiring 및 실제 설치 identity 확인을 통과했다. 전체 검증·독립 리뷰·clean commit-push 후 fresh campaign으로 재실행한다.

### [ISS-023] incident별 GitHub account API 재검증의 외부 실패

- **카테고리**: external interface / experiment harness
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260816-primary10`은 startup account·local build·manifest·preflight를 통과한 뒤 첫 incident의 `gh api user`가 nonzero로 실패했다. manifest와 두 startup event 외 result/raw/ledger/charge/K8s mutation은 0이다.
- **발생 빈도**: 본실험 1회. 같은 campaign startup 조회는 정상 login을 반환했으므로 account mismatch가 아니라 반복 REST API의 비결정적 실패다.
- **관찰한 사실**: 종료 시점 campaign event는 `authorization_verified→preflight_green`뿐이며 injection/Flux receipt가 없다. 6/6 node, Boutique 12/12, Flux/monitoring 상태는 startup preflight 그대로다.
- **근본 원인**: billing/account는 estimand가 아니고 사용자도 paid-overage를 차단 사유에서 제외했지만, 60 incident마다 GitHub REST API를 호출해 새로운 외부 failure surface를 추가했다. 실제 SDK 호출은 자체 인증과 strict Terra/usage/receipt 검증을 이미 수행한다.
- **수정 내용**: active GitHub account는 campaign 시작 시 한 번만 확인해 manifest에 봉인한다. incident 경계에서는 process-local authorization만 재검증하고 네트워크 account API는 호출하지 않는다. SDK 인증·Terra/model/tool/skill/usage/charged receipt와 30 AIC session limit은 각 call에서 계속 fail-close한다.
- **현재 영향**: main wiring 통합 테스트가 identity 1회, quota 0회, pre_call_guard 없음과 startup manifest provenance를 검증한다. 전체 검증·독립 리뷰·clean commit-push 후 fresh campaign으로 재실행한다.

### [ISS-024] SDK logged-in session의 추론 전 인증 생성 실패

- **카테고리**: external interface / experiment harness
- **심각도**: critical (P0)
- **영향**: campaigns `v2-3-main-20260816-primary11`과 `primary12`가 각각 F1 trial 1의 네 번째·일곱 번째 SDK subprocess에서 인증 세션 생성 실패로 중단됐다. 두 campaign 모두 result/raw/call ledger 0이므로 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 2회. 각 incident의 앞선 3회·6회 호출은 Terra·exit 0·완전 usage로 성공했다.
- **관찰한 사실**: primary11은 attempt 3건/charged 4건/알려진 1.97535 AIC, primary12는 attempt 6건/charged 7건/알려진 3.5765 AIC다. 두 실패 subprocess 모두 exit 1과 exact `session.error(authentication)`을 냈고 `assistant.usage`·model call 없이 routine `session.shutdown`에서 premium 0, nano-AIU 0, API duration 0, model metrics empty를 기록했다. 초기 수정은 `thesis.sdk.binding`을 첫 event로 가정했지만 실제 stdout에는 그 앞에 persisted `session.start`가 있어 matcher가 안전하게 거부하고 AIC를 unknown으로 유지했다. 두 campaign 모두 `incident_failed(LiveCallerError)→flux_restored→recovery_green`으로 종료됐고 6/6 node, Boutique 12/12, Flux 5/5, Prometheus/Loki가 GREEN이다.
- **근본 원인**: SDK의 `useLoggedInUser=true` 세션 생성이 앞선 정상 호출 뒤 일시적으로 인증 정보를 얻지 못했다. 사용자 계정 전체의 지속 실패는 같은 incident의 직전 성공 3건과 모순되며, 모델 추론·도구 실행·사용량 발생 전 실패라는 점은 shutdown metrics로 직접 확인된다.
- **수정 내용**: exact persisted `session.start`를 binding 앞에 포함해 UUID/session ID, model/reasoning, remote=false, temp cwd context, 30 AIC session limit, timezone start와 schema version을 binding에 교차결합한다. 이어지는 exact empty-mode request binding, byte-exact 인증 오류 2종, routine shutdown의 0 AIC·0 premium·0 API duration·empty model metrics·0 system/conversation/tool token과 model/user/tool event 부재가 모두 맞을 때만 known-zero receipt로 분류한다. lifecycle 순서, required singleton, optional event 최대 1개, 각 optional event의 UUID/timezone/ephemeral/empty-data/parent linkage도 검증한다. 이 failure code만 fresh SDK session으로 최대 1회 재시도한다. 두 번째 동일 실패와 모든 drift는 즉시 campaign을 중단한다.
- **현재 영향**: persisted start prefix의 실제 type/key shape와 안전 필드 값은 K8s와 무관한 최소 진단 2회에서 durable charged receipt 2건·합계 0.0512 AIC로 확인했다. 두 번째 진단은 같은 auth failure와 zero-usage shutdown을 재현해 patched receipt가 known 0.0 AIC로 분류됨을 확인했다. SDK/live-caller targeted 검증과 독립 리뷰·전체 V2.3 회귀·dry-run·clean commit-push 뒤 fresh campaign으로 처음부터 재실행한다.

### [ISS-025] Flux app suspend의 post-refresh resourceVersion 경쟁

- **카테고리**: infra / recovery guard
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260816-primary13`은 F1 trial 1의 Flux root suspend 뒤 app suspend CAS에서 중단됐다. result/raw/attempt/call/charged ledger는 모두 0이며 model inference·AIC 사용·fault injection은 없었다.
- **발생 빈도**: 본실험 1회. 앞선 primary1에서 root settle 중 stale app receipt가 발생한 사례와 달리, 이번에는 root settle 뒤 app receipt를 다시 봉인한 후 실제 patch 직전 resourceVersion이 한 번 더 전진했다.
- **관찰한 사실**: Kubernetes가 `Operation cannot be fulfilled ... object has been modified`를 반환했고 runner는 `Flux suspension CAS did not succeed`로 fail-closed했다. event는 `flux_recovery_receipt_sealed→flux_app_recovery_receipt_refreshed→incident_failed→flux_restored→recovery_green`이며 app은 이미 원래 상태, root는 CAS로 원래 absent suspend field에 복구됐다. 종료 후 6/6 node Ready·pressure false, Boutique 12/12, Flux 5/5, Prometheus/Loki GREEN을 확인했다.
- **근본 원인**: Flux status writer가 post-root refresh와 app merge-patch 사이의 짧은 창에서 app Kustomization의 resourceVersion을 갱신했다. UID와 원래 suspend field shape/value는 바뀌지 않았지만 단일 CAS 시도만 허용해 안전한 transient race도 campaign 전체 실패가 됐다.
- **수정 내용**: UID·original suspend shape/value뿐 아니라 전체 pre-mutation spec의 canonical SHA-256이 동일하고 resourceVersion만 전진한 경우에 한해 app pre-state를 다시 읽어 event journal에 fsync하고 최대 3회 CAS를 재시도한다. 각 시도의 full hierarchy receipt를 독립 봉인하며 정상 runner의 recovery context도 fsync 직후 마지막 receipt로 교체하고 SIGKILL emergency restore 역시 검증된 마지막 receipt를 사용한다. unrelated spec 변경, mutation 성공 여부가 불명확한 suspend=true, malformed/비결합 receipt, 중복·역행 resourceVersion, 3회 초과 경쟁은 계속 fail-closed한다.
- **현재 영향**: 실제 empty patch response와 resourceVersion 전진 재현, unrelated interval drift 거부, 2회 경쟁 뒤 성공, 연속 경쟁 상한, normal failure recovery의 최신 receipt 결합, 다중 durable receipt의 마지막 정본 복구와 중복·역행·상한 초과 거부를 unit으로 검증한다. 전체 회귀·dry-run·독립 리뷰·clean commit-push 뒤 fresh campaign으로 처음부터 재실행한다.

### [ISS-026] F4 trial 3의 300초 memory stress가 node 복구 경계를 초과

- **카테고리**: injection / recovery / infra
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260816-primary14`은 F1 t1부터 F4 t2까지 17 incidents·51 rows/raw·612 validated calls를 commit한 뒤 F4 t3 recovery에서 중단됐다. F4 t3의 36 model calls는 attempt/charged ledger에만 존재하고 incident/result/call ledger에는 commit되지 않았다. 불완전 campaign 전체는 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 1회. 13 GiB/90초 선행 lifecycle probe는 약 99초에 자율 복구됐지만 13 GiB/300초 production 처치는 host SSH와 kubelet 응답을 장시간 고갈시켰다.
- **관찰한 사실**: F4 t3는 180초 뒤 `Ready=Unknown`과 node-unreachable process probe로 injection validation을 통과했고 36회 Terra 호출까지 완료했다. recovery 30회와 sealed-receipt emergency recovery 30회가 모두 SSH banner timeout으로 실패했으며 yms-proxmox-04는 약 32분 뒤에야 Ready/SSH 응답을 자율 회복했다. 두 번째 emergency restore는 첫 시도에 exact process cleanup을 확인했다. 최종 artifact는 rows/raw/call=51/51/612, attempt/charged=648/648, 알려진 누적 AIC 306.7476이며 event는 `recovery_failed→flux_emergency_restore_failed→flux_emergency_restored`로 끝난다. 최종 6/6 node pressure false, Boutique 12/12, Flux 5/5, Prometheus/Loki ready와 stress receipt/log/process 부재를 확인했다.
- **근본 원인**: injection validation에 필요한 약 40초의 disruption보다 300초 stress duration이 과도했다. 16 GiB node에서 13 GiB `--vm-keep`을 5분 유지하면서 sshd와 kubelet이 exact recovery의 최대 약 6.5분 retry window 안에도 응답하지 못했고, 실험 종료 후 node가 장시간 비정상 상태로 남았다.
- **수정 내용**: F4 t3의 stress timeout을 180초로 줄이고 15 GiB 총 처치량을 worker 1개에 결합한다. validator는 public result의 observation deadline=120과 timeout=180을 bool 제외 exact int로 검증하고 `Ready!=True`를 필수로 요구한다. runner는 40–120초를 2초 간격으로 관측해 최초 NotReady를 latch하고, injection 시작부터 full collector 완료까지 monotonic elapsed가 175초 미만임을 `evidence_collection_verified` event로 봉인한다. recovery command identity는 exact `--vm 1 --vm-bytes 15G --timeout 180s` process만 종료한다. 다른 F4 trial의 180초 wait는 변경하지 않는다.
- **현재 영향**: 모든 calibration/probe에는 Copilot 호출·AIC·result 파일 쓰기가 없었다. exact worker/wait/timeout type 변조, Ready=True+MemoryPressure=True, observation window deadline, evidence deadline, 다른 F4 trial wait 누출을 적대 unit으로 검증한다. 전체 회귀·독립 리뷰·clean commit-push 뒤 production window 코드로 model-free full lifecycle probe를 한 번 더 통과해야 fresh main campaign을 시작한다.

### [ISS-027] stress-ng vm-bytes의 worker별 의미로 총 처치량이 이중 요청됨

- **카테고리**: injection / code
- **심각도**: critical (P0)
- **영향**: 14 GiB/180초 model-free full probe는 60초에 `Ready=True`여서 inference 전에 거부됐고, 이어진 polling probe도 25–123초 내내 Ready=True·MemoryPressure=False였다. 두 probe 모두 exact recovery GREEN이며 Copilot 호출·AIC·result 쓰기는 0이다.
- **발생 빈도**: `--vm 2`의 14 GiB/180초 무모델 probe 2회. 앞선 동일 worker 구성의 14 GiB/90초 calibration은 52.034초에 일시적 NotReady를 보였다.
- **관찰한 사실**: worker03의 설치된 `stress-ng 0.19.02` 도움말은 `--vm-bytes N`을 `allocate N bytes per vm worker`로 정의한다. 기존 command는 `--vm 2 --vm-bytes 14G`여서 16 GiB node에 총 14 GiB가 아니라 worker별 14 GiB, 최대 28 GiB를 요청했다. probe 직전 node available memory는 14,730,600,448 bytes였다.
- **근본 원인**: 절대 byte 값만 receipt에 결합하고 vm worker 수와 stress-ng의 per-worker 의미를 총 처치량 계약에 포함하지 않았다. 과다 요청과 child worker OOM/restart가 일시적 Ready 변화에 기여했다는 해석은 관측과 일치하지만 process별 RSS 원자료는 보존하지 않아 직접 입증된 것은 아니다.
- **수정 내용**: `F4_T3_STRESS_VM_WORKERS=1`을 shared constant로 추가해 launch를 exact `--vm 1 --vm-bytes 14G`로 고정한다. sealed preflight/result receipt, validator, recovery command identity에 worker 수를 bool 제외 exact int로 결합하고 missing/0/2/bool/float/string 변조를 거부한다.
- **현재 영향**: worker 1개 구성은 51.191초에 NotReady와 live process identity를 재현했고 full collector를 52.685초에 끝냈다. worker-count contract와 별도로 60초 단일 샘플링 문제는 ISS-028에서 추적한다.

### [ISS-028] F4-t3의 60초 단일 관측점이 transient NotReady를 놓침

- **카테고리**: injection / measurement
- **심각도**: critical (P0)
- **영향**: worker 1개·14 GiB/180초 production-path full probe는 60초에 `Ready=True`를 읽어 inference 전에 거부됐다. 동일 구성의 후속 latch probe는 51.191초에 `Ready=False`를 관측해 처치가 실제 성립했음을 보였다.
- **발생 빈도**: 고정 60초 probe 1회 실패, bounded latch probe 1회 성공.
- **관찰한 사실**: 성공 수동 latch probe에서 PID/start/hash process identity는 live였고 observability-only full collector는 injection 후 52.685초에 끝나 175초 evidence deadline을 충족했다. exact recovery는 7회 만에 GREEN이었다. 첫 fixed probe는 recovery 11회 GREEN이었다. production-window helper probe는 첫 poll 뒤 다음 poll 전에 60초 deadline을 넘어 fail-closed했고 recovery 8회 GREEN이었다. 세 probe 모두 model/AIC/result write 0이다. 복구 뒤 같은 named-node 조회는 0.03–0.04초였으므로 지속 장애가 아닌 bounded read 지연이다.
- **근본 원인**: Node Ready 변화가 단조 상태가 아닌데도 최초 runner는 정확히 60초 한 점만 읽었다. 이후 helper는 named-node 조회의 기존 최대 60초 timeout을 그대로 사용해 단일 transient read가 20초 window를 소진할 수 있었다. 또한 빈 `{}` 응답의 Ready=None을 disruption으로 해석할 수 있는 별도 fail-open schema 공백이 있었다.
- **수정 내용**: F4-t3만 40초부터 120초까지 2초 간격으로 validator를 실행한다. receipt node는 shared `yms-proxmox-04`와 load/SSH 전에 결합하고 해당 named-node read만 5초로 제한하며 exact timeout과 `F4DisruptionNotObserved`만 재시도한다. 각 attempt의 시작·완료·enum outcome은 retryable·fatal·invalid-result·verified를 포함해 반환/재시도 전에 event journal에 fsync한다. Node kind/name/nonempty UID/conditions list/유일한 Ready/허용 status가 정확하지 않은 빈·오염 응답, malformed receipt, SSH identity 및 다른 validator 오류는 즉시 fail-closed한다. 성공 event에는 poll 시작과 validation 완료 elapsed를 모두 기록하고 완료가 120초를 넘으면 성공 응답도 거부한다.
- **현재 영향**: 15 GiB/180초 calibration 2회는 각각 45.079초·65.334초에 NotReady, 46.475초·66.833초에 full collector<175, exact recovery 3회·4회 GREEN을 재현했다. 120초 deadline, exact timeout retry/audit, event fsync failure abort, wrong receipt node의 load/SSH 전 거부, empty/wrong/duplicate Ready schema 거부, fatal/invalid-result provenance, 121초 late start와 119→125초 slow-success 거부를 deterministic unit으로 검증한다. 전체 회귀·독립 리뷰·clean commit-push 뒤 정본 15G/120 production window 코드의 model-free live lifecycle probe가 실행 gate다.

### [ISS-029] F4-t3 NotReady 처치의 run 간 비재현성과 vm-bytes 의미 정정

- **카테고리**: injection / measurement validity
- **심각도**: critical (P0)
- **영향**: commit `1bbe2c1`의 정본 15G·worker1·40–120초 probe는 39회 모두 Ready=True라 inference 전에 중단됐다. `--page-in`, worker1 16G, worker2 8G/15G/16G, worker1 15G·170초 후보도 NotReady를 재현하지 못했다. 모든 probe는 model/AIC/result 0, exact recovery 2–4회와 comprehensive health GREEN이었다.
- **발생 빈도**: 기존 성공 2회 뒤 정본 및 calibration 6회 연속 NotReady 미관측.
- **관찰한 사실**: 설치된 0.19.02 상세 man page는 `--vm-bytes N`을 worker 전체에 공유되는 총량으로 설명한다. 2-worker 8G probe에서 node-exporter `MemAvailable`이 baseline 약 14.7GB에서 약 6.1GB로 감소해 총 8G 의미와 일치했다. 2-worker 15G 진단은 15초에 host `MemAvailable=1,659,895,808 bytes`, stress parent/children `oom_score_adj=-1000`과 exact process identity를 확인했지만 Node Ready=True·MemoryPressure=False였다. 따라서 ISS-027의 28 GiB 해석은 정정되어야 한다.
- **근본 원인**: memory exhaustion은 실제로 성립하지만 kubelet lease/Ready 전환은 노드의 순간 workload와 kernel reclaim/OOM scheduling에 의존해 단조롭거나 재현 가능한 종점이 아니다. NotReady만 gate로 강제하면 실재하는 극심한 low-memory 처치를 거부하고, 더 강한 처치나 kubelet 강제 중단은 안전성과 단일 원인 타당성을 훼손한다.
- **수정 내용**: 총량 15G와 timeout180을 유지하고 worker 2개로 동시에 touch한다. 10–120초 polling에서 exact PID/start/hash live identity와 `Ready!=True` 또는 같은 host probe의 `/proc/meminfo MemAvailable<=2 GiB`를 요구한다. Ready=True+low-memory는 `node_disrupted=false`, `memavailable-threshold` precursor로 명시한다. Node가 이미 NotReady라 SSH가 timeout인 경우에만 sealed launch receipt와 독립 Node 상태를 근거로 허용하되 identity/memory를 관측한 것으로 기록하지 않는다. 원격 identity command는 `set -eu`로 marker 전 모든 test를 fail-closed하며 malformed/duplicate/negative memory 값과 Ready=True SSH timeout은 retry/거부한다.
- **현재 영향**: clean commit `6efd23b`의 exact production-helper probe는 66.237초에 live PID/start/hash와 `MemAvailable=757,661,696 bytes`, Ready=True를 관측해 `node_disrupted=false`, `memavailable-threshold`로 PASS했다. full collector는 105.737초<175였고 pressure 중 Loki error query 한 건이 30초 timeout으로 남았다. exact recovery 3회는 recovery health gate를 통과했다. 별도 post-check의 첫 Loki readiness 5초는 timeout됐지만 즉시 10초 재시도에서 HTTP 200·Loki pod 2/2를 확인했고, 최종 nodes 6/6·Boutique 12/12·Flux 5/5·Prometheus/Loki GREEN이었다. model/AIC/result write는 0이다. primary 60 paired incidents는 유지하되 F4-t3 제외 59-incident paired sensitivity를 의무 보고해 endpoint 완화의 영향을 분리한다. 이 gate 통과 뒤 fresh main campaign을 시작할 수 있다.

### [ISS-030] F4-t4 diskfill이 tmpfs에 배치되고 원격 실패가 누락됨

- **카테고리**: injection / measurement validity
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260816-primary15`는 F1 t1부터 F4 t3까지 18 incidents·54 rows/raw·648 validated calls를 commit한 뒤 F4 t4 injection validation에서 중단됐다. 불완전 campaign 전체는 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 1회. F4 t4는 model inference 전에 거부됐으므로 해당 trial의 attempt/charged/call/result는 0이다.
- **관찰한 사실**: F4 t4는 yms-proxmox-02에서 root filesystem의 당시 available block 중 95%를 `/tmp/diskfill`에 예약하려 했지만, `/tmp` tmpfs capacity를 초과해 `fallocate`가 실패했다. 원격 nonzero exit가 누락된 채 공용 180초를 기다렸고, validator 시점의 Node는 `Ready=True`, `DiskPressure=False`여서 `PilotError: F4 node disruption was not observed`로 fail-closed했다. event는 `incident_failed→flux_restored(exact original/CAS)→recovery_green`이며 commit boundary는 18/60, rows/raw 54/54, attempt/call/charged 648/648/648, 누적 AIC 295.87545다. 종료 후 `/tmp/diskfill`은 없고 nodes 6/6 Ready·pressure false, Boutique 12/12, Flux 5/5, Prometheus ready다. Loki readiness는 별도 재시도에서도 timeout 상태라 후속 건강 점검 대상으로 남긴다.
- **근본 원인**: yms-proxmox-02에서 `/tmp`는 4,163,809,280-byte `tmpfs`(device 37)지만 kubelet `nodefs`와 `/var/lib/kubelet`은 49,564,815,360-byte `/dev/mapper/vg0-root` ext4(device 64512)다. 기존 명령은 root `/`의 available bytes 중 95%를 계산한 뒤 그보다 훨씬 작은 `/tmp/diskfill`에 `fallocate`했다. 원격 command nonzero exit를 `ssh_node()`가 확인하지 않아 allocation 실패를 injection 성공처럼 진행했고, validator에는 file/filesystem/poststate receipt가 없어 180초 후 Node condition만 읽었다. `evictionPressureTransitionPeriod=5m`은 관찰된 설정이지만 이번 실패의 직접 원인으로 사용하지 않는다.
- **수정 내용**: preflight는 원격 mutation 없이 cryptographic nonce와 kubelet nodefs prestate만 수집하며 이를 local event journal에 먼저 fsync한다. 그 뒤에만 nodefs와 같은 `/var/tmp/v23-f4t4-<nonce>/`를 생성하고, pre-existing path 부재, device/mount, pre/post capacity·available, work/file inode·size·allocated blocks를 exact 결합하는 crash-safe intent/poststate receipt를 fsync·readback한다. 95%-of-current-available 대신 사전 고정한 nodefs 9% available target을 사용하고, live poststate가 8% 이상 10% 미만이며 allocated blocks와 filesystem delta가 요청량을 뒷받침해야 한다. recovery는 file/workdir 부재만으로 GREEN이 아니며 같은 nodefs의 available이 10% 이상 회복돼야 한다. 원격 exit와 marker가 하나라도 어긋나면 inference 전에 거부한다. precursor를 허용할 경우 `node_disrupted=false`, `disk_pressure_observed=false`, `treatment_basis=nodefs-available-threshold`로 기록하고 F4-t4 제외 59건 민감도 분석과 estimand 한계를 의무화한다. 독립 리뷰와 model-free lifecycle probe를 fresh campaign 실행 gate로 둔다.
- **현재 영향**: Primary15는 불완전 operational attrition으로 보존하며 재사용하지 않는다. 실험 프로세스는 종료됐고 F4-t4 결과는 commit되지 않았다. 정지했던 로컬 Loki port-forward만 교체한 뒤 Loki `/ready`가 다시 `ready`를 반환해 nodes 6/6·Boutique 12/12·Flux 5/5·Prometheus/Loki comprehensive health GREEN을 회복했다. 수정·회귀·독립 리뷰·model-free probe 전에는 fresh campaign을 시작하지 않는다.

### [ISS-031] F4-t4 DiskPressure 발현 뒤 GC 반등과 condition 해제 지연

- **카테고리**: injection / recovery / measurement validity
- **심각도**: critical (P0)
- **영향**: clean commit `2d9c6ad` model-free probe는 inference·AIC·result 0 상태에서 실제 `DiskPressure=True`를 만들었지만 validator와 recovery health gate를 통과하지 못했다. fresh main campaign은 시작하지 않았다.
- **발생 빈도**: model-free lifecycle probe 1회.
- **관찰한 사실**: nonce-bound injection 직후 nodefs capacity 49,564,815,360 bytes 중 available 4,460,826,624 bytes(약 9.0%)와 30,747,039,130-byte allocated file을 봉인했고 Node는 `Ready=True`, `DiskPressure=True`가 됐다. 이후 kubelet image GC로 live available이 10% 위, 최종 약 38.17GB까지 반등했지만 DiskPressure condition은 True로 유지됐다. 180초 validator는 ongoing 8–10% gate 때문에 `PilotError`로 중단했다. exact file cleanup은 1회 성공했으나 generic health timeout 동안 condition/taint가 남아 recovery RED였다. 실험 종료 후 exact workdir 부재와 available 38.17GB를 확인하고 kubelet을 1회 재시작하자 DiskPressure=False·taint 없음으로 즉시 회복됐다. pressure 중 Evicted된 monitoring DaemonSet pod 2개를 정확히 삭제한 뒤 replacement를 포함해 nodes 6/6·Boutique 12/12·Flux 5/5·Prometheus/Loki·Failed pod 0을 확인했다.
- **근본 원인**: DiskPressure는 threshold signal의 순간값과 condition lifecycle이 동일하지 않다. 처치가 GC를 유발하면 live available은 threshold 위로 반등해도 condition은 관측 가능한 fault endpoint로 남을 수 있다. 반대로 cleanup만으로는 kubelet의 pressure transition/taint가 generic health timeout 안에 해제되지 않았다.
- **수정 내용**: read-only preflight는 exact Node UID·Ready=True·DiskPressure=False baseline을 local recovery receipt에 함께 봉인한다. validator는 node-local post receipt가 injection 당시 8–10% threshold와 exact file allocation을 입증하고 같은 UID의 live file identity·safety floor가 유지되는 조건에서, 180초의 새 `DiskPressure=True` 또는 `Ready!=True`를 직접 treatment endpoint로 우선한다. ongoing `<10%`는 condition 미발현 precursor branch에서만 필수로 한다. injection post available·allocation·nonce/inode identity와 live threshold는 validation event에 분리해 영속화한다. recovery는 exact cleanup과 `available>=10%`를 확인한 뒤 current Node가 여전히 NotReady/DiskPressure일 때만 kubelet을 invocation당 1회 재시작하고 active marker 뒤 2초 간격 최대 15회 same-UID exact GREEN condition만 poll한다. stale condition으로 restart를 반복하지 않으며 poll 소진 시 fail-close한다. pre-mutation crash에서 이미 GREEN이면 restart하지 않는다. fresh campaign 전 동일 model-free full lifecycle probe와 comprehensive GREEN을 다시 요구한다.
- **현재 영향**: 첫 probe는 invalid calibration으로만 보존한다. cluster는 수동 `$lab-restore` 후 GREEN이며 결과 데이터는 생성·수정되지 않았다.

### [ISS-032] F4-t4 live validator가 root-owned receipt를 읽지 못함

- **카테고리**: injection / validation boundary
- **심각도**: critical (P0)
- **영향**: clean commit `913bfc5` model-free probe는 의도한 DiskPressure를 만들었지만 inference 전 live validation에서 중단됐다. fresh main campaign은 시작하지 않았다.
- **발생 빈도**: model-free lifecycle probe 1회.
- **관찰한 사실**: nodefs capacity 49,564,815,360 bytes 중 injection post available 4,460,826,624 bytes(약 9.0%)와 33,394,947,482-byte allocated file을 exact receipt에 봉인했고, 관측 중 같은 UID 노드는 `Ready=True`, `DiskPressure=True`였다. 180초 validator는 `PilotError: F4 diskfill live probe is malformed`로 중단했다. recovery는 exact cleanup 1회, kubelet restart 1회, condition poll 2회 뒤 health gate GREEN이었다. model/AIC/result는 0이며 artifact는 `/tmp/v23-f4t4-probe-20260817T0108Z/probe_events.jsonl`에 보존했다. pressure로 Evicted된 monitoring DaemonSet pod 2개만 정확히 삭제했고 replacement Ready, nodes 6/6·DiskPressure false·Boutique 12/12·Flux 5/5·Prometheus/Loki Ready·Failed pod 0을 확인했다.
- **근본 원인**: crash receipt 보호를 위해 nonce work directory를 root-owned mode-0700으로 생성했지만, validator의 live receipt/file probe만 일반 SSH 사용자 `debian` 권한으로 실행했다. 원격 command는 directory를 traverse하지 못해 marker 전에 종료됐고, marker 부재가 malformed로 fail-closed됐다.
- **수정 내용**: F4-t4 read-only live probe에만 전체 inner command를 `shlex.quote`한 `sudo sh -c` 경계를 적용한다. root wrapper 내부의 `set -eu` 뒤 receipt schema·nonce·device·work/file inode·size·blocks·capacity·pre/post/live available 검사를 모두 marker 전에 유지한다. 다른 fault validator에는 sudo를 확장하지 않는다.
- **현재 영향**: targeted 67 PASS, py_compile·diff-check와 독립 reviewer APPROVE를 확인했다. 수정 정본을 clean commit한 뒤 동일 model-free full lifecycle probe와 comprehensive GREEN을 다시 통과하기 전에는 fresh main campaign을 시작하지 않는다.
- **검증 후속(append-only)**: clean commit `84eb369`의 동일 helper probe가 injection post available 4,460,826,624 bytes, t180 live available 4,775,100,416 bytes, same-UID `Ready=True`·`DiskPressure=True`, exact allocation/receipt identity를 검증해 `treatment_basis=diskpressure-condition`으로 PASS했다. collector는 181.843초에 14 metric groups·2 log groups·6 kubectl groups를 완료했다. recovery는 exact cleanup 1회, kubelet restart 1회, condition poll 2회, comprehensive health GREEN이었고 `probe_complete`의 model/AIC/result는 0/0/0이다. artifact는 `/tmp/v23-f4t4-probe-20260817T0120Z/probe_events.jsonl`, SHA-256 `f075061b70d5c0f7505ecc6d36e023e7d9725cabe770098c5711ca1479d44c7a`다. Evicted monitoring pod 2개만 exact 삭제한 뒤 replacements 6/6, nodes 6/6·DiskPressure/MemoryPressure false, Boutique 12/12, Flux 5/5, Prometheus/Loki Ready, Failed pod·nonce workdir 0을 확인했다. F4-t4 model-free 실행 gate는 충족됐다.

### [ISS-033] locale stderr가 recovery disk health를 false-RED로 만듦

- **카테고리**: recovery / code / infra provenance
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260817-primary16`은 F1-t1에서 36 Terra calls를 완료했지만 recovery health를 잘못 RED로 판정해 commit 전에 중단됐다. 불완전 campaign은 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 1회.
- **관찰한 사실**: F1-t1 injection과 exact Flux restore는 성공했고 attempt/charged는 36/36, actual model `gpt-5.6-terra`, AIC 합계·final cumulative 17.487로 정렬됐다. result/raw/call ledger는 0/0/0이다. 실제 nodes 6/6 Ready·DiskPressure/MemoryPressure false, Boutique 12/12, Flux root/app Ready·suspend absent, Prometheus/Loki Ready, Failed pod와 experiment residual 0, worker disk 20/25/34/29/44%였다. 그러나 `ssh_node()`가 stdout과 stderr를 합치면서 각 disk 출력이 `20\nbash: warning: setlocale...` 형태가 됐고, `int(raw.strip().replace('%',''))`가 다섯 노드 모두 실패했다. fallback full reset도 존재하지 않는 `/tmp/thesis-rca-work/k8s/app/online-boutique.yaml`을 참조했다.
- **근본 원인**: health check가 원격 출력 전체를 숫자로 간주해 locale stderr와 측정값을 분리하지 않았고, recovery manifest가 optional GitOps scratch clone의 stale 절대경로에 결합돼 있었다.
- **수정 내용**: remote `set -eu`와 `LC_ALL=C df -P /`로 POSIX Use%를 추출해 exact `__V23_DISK_USAGE_PCT__=` marker를 마지막에 1회만 출력한다. Python은 exactly-one digits marker와 0..100만 허용하고 unrelated stderr는 무시한다. missing·duplicate·suffix·101·timeout은 RED이며 기존 `>=80%` gate를 유지한다. `ORIGINAL_MANIFEST`는 현재 checked-out revision의 `k8s/app/online-boutique.yaml`을 `Path(__file__).resolve()`에서 계산해 cwd와 `/tmp` clone 의존을 제거한다.
- **현재 영향**: 새 적대 tests를 포함한 targeted 71 PASS, pycompile·diff-check, actual comprehensive health `(True, [])`, 독립 reviewer APPROVE를 확인했다. 수정 정본 clean commit 뒤 fresh primary campaign으로 재시작한다.

### [ISS-034] F4-t4 실행 command가 누출 lexicon의 비한정 n-gram 확장을 유발

- **카테고리**: code / performance / safety
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260817-primary17`은 F1 t1부터 F4 t3까지 18 incidents·54 rows/raw·648 validated calls를 commit한 뒤 F4 t4에서 모델 호출 전에 정체됐다. 불완전 campaign 전체는 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 1회.
- **관찰한 사실**: F4 t4는 180초 시점에 same-UID `Ready=True`·`DiskPressure=True`, injection post nodefs available 4,460,826,624 bytes, exact diskfill allocation·inode·block identity를 검증했다. 이후 attempt/call/charged ledger는 648에서 9분 이상 증가하지 않았고 Python main process는 CPU 약 100%를 지속 사용했다. 두 차례 macOS stack sample은 Python regex substitution/search, bytearray find와 GC에 집중됐다. 안전상 tmux에 정상 interrupt를 보냈고 `incident_failed(error_type=KeyboardInterrupt)→flux_restored(exact original/CAS)→recovery_green`으로 종료됐다. commit boundary는 18/60, rows/raw 54/54, attempt/call/charged 648/648/648, 누적 AIC 308.46225다.
- **근본 원인**: `build_forbidden_lexicon()`이 F4 t4의 수백 토큰 crash-safe shell `command`와 `ssh_output`을 일반 `field_values`로 포함했다. scanner와 masker는 길이 N term에 대해 full term 외에도 모든 크기 2/3..N의 adjacent n-gram을 생성해 패턴 수와 문자열 생성량이 O(N²), 총 문자열 작업량이 O(N³)으로 증가했다. 프로파일과 해당 실행 경로는 일치한다.
- **수정 내용**: command·ssh/kubectl output은 semantic scalar가 아닌 실행/provenance envelope로 분류해 lexical field value에서 제외하고, nonce·path·nodefs 수치 등 민감한 개별 scalar receipt는 유지한다. full exact term 검사는 유지하되 changed-prefix/suffix 탐지는 가장 작은 충분 adjacent gram(일반 2-token, command 3-token)만 생성해 선형 pattern 수로 제한한다. forbidden term은 최대 128 normalized tokens로 fail-closed한다. synthetic long command envelope와 128/129-token 적대 회귀를 추가한다.
- **현재 영향**: F4 t4 결과와 Copilot 호출·추가 AIC는 생성되지 않았다. exact nonce workdir 부재, target nodefs 19%, kubelet active, nodes 6/6 Ready·pressure false, Boutique 12/12, Flux 5/5, Prometheus/Loki Ready를 확인했다. F4 중 Evicted된 monitoring pod 3개만 exact 삭제했고 replacement 포함 monitoring non-Running pod·cluster Failed pod 0을 확인했다. 수정·전체 회귀·changelog·clean commit-push 뒤 fresh campaign으로 재시작한다.

### [ISS-035] 단독 짧은 fault ID가 runtime 식별자와 충돌해 누출 false-positive 발생

- **카테고리**: data / code / measurement validity
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260817-primary18`은 F1 t1부터 F4 t4까지 19 incidents·57 rows/raw·684 validated calls를 commit한 뒤 F4 t5에서 모델 호출 전에 중단됐다. 불완전 campaign 전체는 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 1회.
- **관찰한 사실**: Primary18은 F4-t3의 NodeNotReady treatment를 44.926523초에 latch하고 full collector를 80.55205초(<175초)에 완료해 exact recovery·commit했다. F4-t4도 injection post nodefs threshold와 `DiskPressure=True`를 검증하고 scanner 정체 없이 36 calls·exact cleanup·commit했다. F4-t5는 yms-proxmox-03의 node disruption을 검증한 직후 1.33초 안에 `LeakageDetected`로 중단됐고 attempt/call/charged는 직전 경계 684/684/684, rows/raw는 57/57로 유지됐다. 당시 exception에는 category·term이 영속화되지 않아 실제 match term은 직접 입증할 수 없다. 자동 `flux_restored(exact original/CAS)→recovery_green` 뒤 프로세스가 종료됐고 최종 nodes 6/6 Ready·DiskPressure/MemoryPressure false, Boutique 12/12, Flux 5/5 Ready·active, Prometheus/Loki ready, Failed pod 0을 확인했다.
- **근본 원인**: production lexicon이 harness marker로 단독 두 글자 `F4`를 사용했고 scanner는 punctuation을 경계로 취급했다. 따라서 UUID·pod/container hash 등에 우연히 독립 토큰으로 나타난 `-f4-`도 fault identity 누출로 판정할 수 있다. 이 false-positive는 synthetic runtime에서 재현했다. 다만 Primary18 당시 원문 scan report가 없으므로 이 경계가 그 실행의 직접 match였다는 것은 유력한 추론이며 확정 사실로 취급하지 않는다. 복구 뒤 새 5분 window replay는 runtime/procedure 모두 match 0이어서 당시 snapshot을 대체하지 못한다.
- **수정 내용**: production harness marker를 단독 `F4`가 아니라 구조가 결합된 `fault_id=F4`, `fault F-4`, scheduled `F4_t5` Unicode/punctuation 변형 regex로 제한한다. `fault injection`과 `experiment marker`는 계속 독립 차단한다. 일반 scanner의 명시적 raw marker 기능은 유지한다. `LeakageDetected`는 stage와 scanner/lexicon/context hash, category/kind, forbidden term SHA-256만 제공하고 원문·term은 제공하지 않으며, runner가 이를 `incident_failed` event에 fsync한 뒤 mandatory recovery를 계속 수행한다. scanner provenance version은 `v2.3-nfkc-alias-ngram-3`으로 올린다.
- **현재 영향**: targeted 77 PASS, 전체 275 PASS, dry-run 180 rows/2,160 calls·external0·filesystem0, pycompile·diff-check를 통과했다. 독립 리뷰·append-only changelog·clean commit-push 후 새 campaign ID로 처음부터 재실행한다.

### [ISS-036] compact label의 separator 변형이 procedure masker를 우회

- **카테고리**: data / code / measurement validity
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260817-primary19`는 F1~F3 전부와 F4 t1~t4까지 19 incidents·57 rows/raw·684 validated calls를 commit한 뒤 F4 t5에서 모델 호출 전에 중단됐다. 불완전 campaign 전체는 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 1회. 해당 incident의 attempt/call/charged 증가는 0이다.
- **관찰한 사실**: F4-t3는 attempt 3의 42.941716초에 live stress identity와 `MemAvailable=1,080,553,472 bytes`를 검증했고 full collector를 104.084429초(<175초)에 완료한 뒤 exact cleanup·commit했다. F4-t4는 injection post available 4,460,826,624 bytes, allocation 32,865,686,938 bytes와 `DiskPressure=True`를 검증해 exact cleanup·commit했다. F4-t5는 yms-proxmox-03의 node disruption을 검증한 뒤 `retrieved_procedure` stage에서 `canonical_labels`와 `aliases`의 동일 normalized term hash `47b8c51c…1cf5bdf0`, kind `compact_substring`으로 fail-closed했다. 이 hash는 ground-truth의 normalized `nodenotready`와 exact 일치한다. event는 `incident_failed→flux_restored(exact original/CAS)→recovery_green`이며 commit boundary는 19/60, rows/raw 57/57, attempt/call/charged 684/684/684, 누적 AIC 330.9618이다.
- **근본 원인**: scanner는 separator를 제거한 compact 비교로 `NodeNotReady`와 `node not ready`를 동일 금지어로 탐지하지만, procedure masker는 single-token `NodeNotReady`를 contiguous form으로만 마스킹했다. 따라서 corpus의 spaced/punctuated serialization이 masker를 통과한 뒤 최종 scanner에서 차단됐다. 이는 실제 ground-truth label 누출을 올바르게 fail-close한 것이며 ISS-035의 짧은 harness-ID false-positive와 다른 원인이다.
- **수정 내용**: masker의 non-regex forbidden term을 scanner와 같은 boundaryless compact semantics로 결합한다. 일반 term은 compact length 4 이상, harness/field value는 2 이상일 때 각 문자 사이 Unicode punctuation/spacing/underscore를 허용하고 접두·접미 문자열 내부에서도 마스킹한다. 동일 normalized term이 여러 category에 있으면 lexicon category 순서로 deterministic precedence를 고정한다. `NodeNotReady`의 spaced/embedded 변형 회귀에서 removed-span provenance, masked procedure hash, 최종 scanner 0건을 함께 검증하고 masker provenance를 `v2.3-procedure-mask-4`로 올린다.
- **현재 영향**: targeted 78 PASS, 전체 276 PASS, dry-run 180 rows/2,160 calls·external0·filesystem0, pycompile·diff-check PASS다. append-only changelog·독립 리뷰·clean commit-push 후 새 campaign ID로 처음부터 재실행한다.

### [ISS-037] F5-t3 local-path provisioner 처치가 Flux infrastructure reconciliation으로 소실

- **카테고리**: injection / GitOps recovery guard
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260817-primary20`은 F1–F4 및 F5 t1–t2의 22 incidents·66 rows/raw·792 validated calls를 commit한 뒤 F5 t3에서 모델 호출 전에 중단됐다. 이 캠페인의 부분 결과는 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 1회.
- **관찰한 사실**: F5 t3은 `injection_started` 뒤 약 90초에 `PilotError: F5 provisioner treatment is absent`로 fail-closed했고, `flux_restored→recovery_green`을 기록했다. 실패 trial은 attempt/charged/call ledger 증가 없이 종료했고, 이후 `local-path-storage/local-path-provisioner` Deployment는 replicas=1이었다. 해당 Deployment에는 `kustomize.toolkit.fluxcd.io/name=infrastructure` 라벨이 있다.
- **근본 원인**: runner는 Flux `flux-system` root와 `app` child만 suspend했다. local-path provisioner는 sibling `infrastructure` Kustomization이 관리하므로, app guard만으로는 `replicas=0` 처치를 validator 시점까지 유지할 수 없었다. controller actor audit은 별도로 보존하지 않아 reconciliation 시점 자체는 라벨·관측 상태에 근거한 추론이다.
- **현재 영향**: 자동 recovery 후 nodes 6/6 Ready, Boutique 12/12 Running, Flux Kustomizations 5/5 Ready를 확인했다. primary20 artifact는 append-only로 보존하며 fresh campaign과 결합하지 않는다.
- **수정 방안**: F5 t3에만 root→`infrastructure` Flux hierarchy guard를 사용하고, recovery/emergency restore는 sealed child receipt의 `flux_name`에서 `app` 또는 `infrastructure` guard를 선택한다. 이외 fault는 기존 root→app guard를 유지한다. targeted tests·clean commit 뒤 fresh campaign으로 처음부터 재실행한다.

### [ISS-038] SDK runner subprocess 대기가 incident recovery 경계를 넘김

- **카테고리**: code / infra
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260817-primary22`의 F1 t2. F1 t1만 3 rows/raw·36 validated calls로 commit됐고 F1 t2는 결과 commit 전에 중단됐다. 이 campaign은 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 1회.
- **관찰한 사실**: F1 t2의 `injection_verified` 뒤 attempt/charged ledger는 50 entries까지 증가했지만 call ledger·result/raw는 F1 t1의 36/3/3에서 진행하지 않았다. 실행 PID는 살아 있으나 campaign event가 더 진행하지 않아 정상 interrupt를 보냈고, `incident_failed(error_type=KeyboardInterrupt)→flux_restored(exact original/CAS)→recovery_green`을 확인했다. traceback은 `CopilotSDKBackend._run_runner()`의 `process.communicate()` 대기에서 발생했다. recovery 뒤 Flux 5/5 Ready·suspend false, nodes 6/6 Ready·DiskPressure false, Boutique 12/12 Running을 확인했다.
- **근본 원인**: Python parent는 `communicate(timeout=210)` 하나에만 liveness를 맡겼다. SDK/CLI process tree가 pipe descriptor를 유지하거나 selector wait가 지연되면 timeout 관찰 자체가 늦어져 fault injection 중 recovery 전환이 보장되지 않는다. 이 실행에서 어떤 SDK child가 descriptor를 유지했는지는 직접 actor audit으로 확정하지 못했다.
- **현재 영향**: primary22 artifact는 append-only로 보존한다. validated result 3행·call ledger 36건만 F1 t1에 대응하며 F1 t2의 14 attempts/charges와 포함 AIC는 campaign 결과에 합산하지 않는다.
- **수정 방안**: SDK parent에 inference deadline+30초 independent watchdog을 두어 process group 전체를 kill하고, timeout 뒤 drain도 15초 상한으로 제한한다. watchdog expiry는 returncode와 무관하게 timeout receipt·charged provenance·incident recovery로 연결한다. process group·watchdog·typed timeout의 unit/regression과 V2.3 dry-run을 통과한 clean revision에서만 fresh campaign을 시작한다.

### [ISS-039] F7-t4 Java startup starvation을 Ready-only validator가 무효화

- **카테고리**: injection / code / data
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260817-primary24`은 F1–F7 t3까지 33 incidents·99 rows/raw·1,188 validated calls를 정상 commit한 뒤 F7 t4에서 Copilot 호출 전 중단됐다. 이 campaign은 불완전하므로 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 1회.
- **관찰한 사실**: F7 t4는 adservice의 CPU limit/request를 5m으로 patch한 뒤 validator 시점에 `PilotError: post-injection live target pod is not Ready with requested CPU`로 fail-closed했다. 해당 incident의 attempt/charged/call ledger 및 result/raw는 모두 직전 commit boundary 1,188/1,188/1,188 및 99/99에 머물렀다. `flux_restored(exact original/CAS)→recovery_green` 뒤 adservice는 1/1 Ready이며 CPU limit 300m/request 200m로 exact restore됐다. nodes 6/6 Ready였다.
- **근본 원인**: F7 validator가 모든 CPU-throttle trial에 Ready pod를 요구했다. 그러나 ground truth의 F7 t4는 Java adservice를 5m으로 제한하여 startup을 수 분 지연시키는 처치이므로, non-ready rollout 자체가 사전 정의된 treatment symptom이다.
- **수정 내용**: deployment desired CPU limit/request와 target/container identity는 계속 exact-bind한다. Ready=false pod는 exact `F7/t4/adservice/5m` 조합에서만 `java-startup-cpu-starvation` basis로 허용하고, 그 밖의 F7 trial 또는 값에는 기존 Ready gate를 유지한다. unready Java branch와 일반 trial 거부 회귀를 추가했다.
- **현재 영향**: Primary24 partial artifact는 append-only로 보존하며 fresh campaign과 결합하지 않는다. 수정 뒤 targeted live-runner 61 PASS, pycompile·diff-check PASS를 확인했다. clean commit 뒤 새 campaign ID에서 처음부터 재시작한다.

### [ISS-040] SDK watchdog cleanup이 host killpg 권한 오류를 전파

- **카테고리**: code / recovery
- **심각도**: critical (P0)
- **영향**: full regression의 real watchdog subprocess test. 본실험 Copilot 호출·클러스터 mutation에는 영향을 주지 않았다.
- **발생 빈도**: 검증 환경 1회.
- **관찰한 사실**: timeout된 local child cleanup에서 `os.killpg(pid, SIGKILL)`가 `PermissionError: [Errno 1] Operation not permitted`를 내며 watchdog test가 실패했다. 이때 직접 runner PID는 아직 실행 중이었다.
- **근본 원인**: production은 `start_new_session=True`로 새 process group을 만들지만, cleanup helper는 host가 group signal을 거부하는 경우의 직접-owned runner fallback을 두지 않았다.
- **수정 내용**: group kill의 `PermissionError`에서 runner PID에 `SIGKILL`을 보내고 process-missing은 무시한다. production 정상 경로의 process-group kill은 유지하며, fallback 호출 적대 회귀를 추가했다.
- **현재 영향**: full 286 tests와 offline dry-run 180 rows/2,160 calls·external/filesystem 0, pycompile·diff-check PASS를 확인했다. clean commit 뒤 fresh campaign에서 처음부터 재시작한다.

### [ISS-041] F1 memory recovery가 rollout history에 의존해 exact pre-state를 잃음

- **카테고리**: recovery / injection
- **심각도**: critical (P0)
- **영향**: Primary25 F1 t1은 32 validated calls 이후 LiveCallerError로 실패했고 recovery는 cartservice 32Mi/32Mi memory state를 남겨 CrashLoopBackOff와 recovery_failed를 유발했다. 결과·raw·logical ledger는 0이다.
- **근본 원인**: F1 injector는 original memory request/container를 receipt에 봉인하지 않았고 recovery는 `rollout undo`만 사용했다. revision history는 exact pre-injection resource state의 정본이 아니다.
- **수정 내용**: F1은 target container와 original memory limit/request를 injection receipt에 봉인한다. recovery는 exact `kubectl set resources` 후 rollout 및 desired resource equality를 검증하며 receipt가 불완전하면 fail-closed한다.
- **현재 영향**: manual restore로 cartservice request 64Mi/limit 128Mi·1/1 Ready와 nodes/Flux GREEN을 확인했다. Primary25는 불완전 artifact로 보존한다.
- **정정·검증 후속(append-only)**: 위의 “32 validated calls”는 정확하지 않다. artifact의 `attempt_call_ledger=32`, `charged_call_ledger=33`이지만 `call_ledger/result/raw=0/0/0`이므로 validated logical call은 0건이다. 마지막 1건은 210.711초 timeout·usage metadata incomplete이며, 알려진 32건 AIC 합계는 15.05945다. exact receipt recovery와 target-container injection을 추가 보강했고, F1 전용 4건을 포함한 전체 290 unittest, offline dry-run 180 rows/2,160 calls·external/filesystem 0, pycompile·diff-check를 통과했다. 새 primary는 model-free F1 lifecycle probe가 GREEN인 clean revision에서만 시작한다.
- **model-free lifecycle 검증 후속(append-only)**: clean `ded79ce`에서 Copilot 호출 없이 F1-t1을 `32Mi`로 주입했다. pane-observed receipt는 `container=server`, original request/limit=`64Mi/128Mi`, wait=120초였다. 120초 뒤 desired resource는 `64Mi/128Mi`, cartservice는 1/1 Running으로 복원됐다. 동일 sealed receipt의 독립 recovery verification은 `{"action":"restore_memory_resources","health_check_passed":true,"target":"cartservice"}`를 반환했고 `comprehensive_health_check(max_retries=1)`도 `(True, [])`였다. 이 probe는 primary 결과·raw·Copilot/AIC를 생성하지 않았다.

### [ISS-042] GitHub identity probe의 단발 503이 primary launch를 사전 중단

- **카테고리**: infra / code
- **심각도**: critical (P0)
- **영향**: `primary26`의 두 launch가 artifact·Copilot call·fault injection 전에 중단됐다.
- **관찰한 사실**: `gh auth status`는 active account `moonsangyhu`를 보였고 공개 GitHub API와 rate-limit API는 정상 응답했지만, 인증된 `gh api user`가 간헐적으로 HTTP 503을 반환했다. 한 번은 identity가 정상화된 뒤에도 15초 `git rev-parse HEAD` timeout으로 사전 중단됐다. 두 경로 모두 output artifact, AIC receipt, K8s mutation 0건이다.
- **근본 원인**: identity verifier는 timeout만 최대 한 번 재시도하고 GitHub의 명시적 transient 503 nonzero 응답은 즉시 실패로 분류했다.
- **수정 내용**: exact GitHub 503 diagnostic에만 timeout과 동일한 최대 한 번 retry를 허용한다. account mismatch·auth failure·다른 process failure는 계속 첫 시도에서 fail-closed한다.
- **현재 영향**: identity unit과 main wiring 7 PASS, full regression·dry-run과 clean commit 뒤 fresh primary26 launch로 재검증한다.

### [ISS-043] Primary25 recovery failure 뒤 Flux suspend 잔여

- **카테고리**: recovery / infra
- **심각도**: critical (P0)
- **영향**: `primary26`은 authorization·preflight 뒤 첫 incident의 Flux receipt preparation에서 중단됐다. Copilot, AIC, fault injection은 0건이다.
- **관찰한 사실**: Primary25 event는 `flux_suspended` 뒤 `recovery_failed`로 끝나고 `flux_restored` event가 없다. 2026-08-26 현재 Flux `app`과 `flux-system`의 `spec.suspend=true`가 남아 있었다. Primary25 sealed receipt는 양쪽의 original suspend field가 absent임을 기록한다.
- **복구 조치**: exact-original semantics로 두 Kustomization의 `spec.suspend`를 merge-patch null로 제거하고 reconcile annotation을 요청했다. 양쪽 모두 new generation=observedGeneration, `Ready=True`, `ReconciliationSucceeded`로 확인했다.
- **현재 영향**: Primary26의 pre-injection artifact는 append-only로 보존하며 primary estimand에 포함하지 않는다. 이후 실행은 새 campaign ID에서 full preflight부터 시작한다.

### [ISS-044] SDK runner의 부분 stdout write가 JSONL record를 절단

- **카테고리**: code / provenance / runtime
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260826-primary27`은 F1–F5 전부와 F6 t1까지 26 incidents·78 rows/raw·936 validated logical calls를 commit한 뒤 F6 t2에서 중단됐다. 이 campaign은 불완전하므로 primary estimand와 분석에 포함하지 않는다.
- **발생 빈도**: 본실험 F6 t2에서 동일 logical call의 최초 시도와 허용된 1회 재시도, 총 2회.
- **관찰한 사실**: F6 t2는 `injection_verified` 뒤 `LiveCallerError: Copilot SDK emitted malformed JSONL`로 fail-closed했다. Python JSON decoder는 line 1 column 65,537에서 `Expecting ',' delimiter`를 보고했다. logical call/result/raw는 직전 boundary 936/78/78에서 증가하지 않았고, attempt/call ledger는 936, durable charged ledger는 938이었다. `flux_restored(exact original/CAS)→recovery_green`을 확인했으며 이후 nodes 6/6 Ready, active Online Boutique replicas 12/12 Running이었다.
- **근본 원인**: Node SDK runner는 `fs.writeSync(stdout, string)`의 반환 byte 수를 무시했다. stdout이 pipe일 때 write는 부분 기록하거나 `EAGAIN`을 낼 수 있으며, 큰 SDK event가 약 64 KiB에서 newline 전에 절단됐다. 기존 parser/retry는 절단을 올바르게 fail-close했지만, 근본 runner write 경계는 보장하지 못했다.
- **수정 내용**: JSONL record를 UTF-8 Buffer로 만들고 offset을 전진시키며 전체 byte가 기록될 때까지 `writeSync`를 반복한다. transient `EAGAIN`은 짧게 대기 후 동일 offset에서 재시도하고, 비정상/0-byte write는 예외로 fail-closed한다. 70,000-byte SDK assistant event가 완전한 JSONL event와 result record로 parse되는 Node runner 회귀를 추가했다.
- **현재 영향**: SDK/live-caller 포함 targeted 29 tests와 전체 292 unittest, `node --check`, `git diff --check`를 통과했다. 새 clean revision에서 F1 t1부터 fresh 60-incident campaign을 실행해야 한다.

### [ISS-045] 주입 관찰 대기 구간의 durable 진행 상태가 없어 operator가 정상 실행을 중단

- **카테고리**: orchestration / observability
- **심각도**: warning (P1)
- **영향**: campaign `v2-3-main-20260827-primary28`은 F1 t1만 1 incident·3 rows/raw·36 validated calls로 commit했고 F1 t2에서 종료됐다. 이 campaign은 불완전하므로 primary estimand와 분석에 포함하지 않는다.
- **발생 빈도**: 본실험 1회, F1 t2.
- **관찰한 사실**: F1 t2는 `injection_started` 후 120초의 사전 정의된 OOM observation wait를 거쳐 `injection_verified`에 도달했다. 그러나 해당 wait의 시작/기한이 event journal에 없어 external monitor가 장기 정지로 오인했고, SDK judge 호출이 시작된 뒤 정상 interrupt를 보냈다. `incident_failed(error_type=KeyboardInterrupt)→flux_restored(exact original/CAS)→recovery_green`을 확인했으며 Boutique 12/12과 nodes/Flux는 복구됐다. F1 t2 call/result/raw는 0이고 F1 t1의 36/3/3만 남았다.
- **근본 원인**: runner는 `injection_started`와 wait 이후의 `injection_verified`만 journal에 남겼다. F1/F2 등 fixed wait fault의 현재 phase·계획된 deadline을 durable하게 알 수 없었다.
- **수정 내용**: injection 결과의 typed/bounded wait interval을 검증한 뒤, blocking wait 이전에 `injection_observation_started` event를 fsync한다. event에는 fault/trial, `wait_seconds`, F4 t3의 `bounded-poll` 또는 기타 fault의 `fixed-wait` mode만 기록한다. event append 실패는 기존 mandatory recovery 경로로 fail-closed한다.
- **현재 영향**: live runner/main campaign 및 SDK/live caller targeted 91 tests와 전체 회귀를 clean revision에서 재확인한 뒤, fresh campaign을 F1 t1부터 시작한다.

### [ISS-046] Terra SDK 호출이 180초 inference deadline을 초과

- **카테고리**: infra / code / execution
- **심각도**: critical (P0)
- **영향**: campaign `v2-3-main-20260827-primary29`은 F1–F2 전체와 F3 t1–t2까지 12 incidents·36 rows/raw·432 validated calls를 commit한 뒤 F3 t3에서 중단됐다. 불완전 campaign 전체는 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 1회, F3 t3 호출 1회.
- **관찰한 사실**: 마지막 성공 호출은 140.236초였고, 다음 SDK subprocess는 229.938초 뒤 `timed_out=true`, `actual_model/AIC=null`, `usage_metadata_complete=false` durable receipt를 남겼다. runner는 `incident_failed(LiveCallerError)` 뒤 Flux root/app exact-original CAS restore와 `recovery_green`을 기록했다. commit boundary는 12/60, 36 rows/raw, attempt/call/charged는 447/432/448이다.
- **근본 원인**: Terra 서비스 지연이 SDK의 180초 inference deadline과 30초 cleanup grace를 넘었다. watchdog과 charged receipt·복구는 의도대로 fail-closed했지만, 현재 실측 지연분포에는 deadline 여유가 부족했다.
- **수정 내용**: 본실험 전용 SDK inference deadline을 300초로 확대하고, manifest schema v5에 `copilot_inference_timeout_seconds=300`을 봉인한다. SDK의 process-group watchdog·30초 cleanup grace, 30 AIC session cap, incomplete-usage hard-stop, model/tool/skill isolation은 유지한다.
- **현재 영향**: Primary29 artifact는 append-only로 보존하고 fresh campaign에서 F1 t1부터 재시작한다. main wiring·SDK·live caller 29 tests와 180-row/2,160-call offline dry-run으로 변경을 검증한다.

### [ISS-047] 로컬 Torch 초기화 후 kubectl fork/exec가 state snapshot에서 정체

- **카테고리**: code / infra / execution
- **심각도**: critical (P0)
- **영향**: `primary30`은 authorization·preflight까지만, `primary31`은 F1 t1 `incident_scheduled`까지만 기록하고 종료됐다. 두 artifact에는 Flux suspend·fault injection·Copilot call·AIC·result/raw/call/attempt/charged ledger가 없다. primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 재시작 2회.
- **관찰한 사실**: local `SentenceTransformerEmbeddingFunction`가 `torch` native import/model load를 수행한 뒤 `StateValidator._kubectl_json()`의 bare `kubectl` subprocess가 `Popen._execute_child()` errpipe read에서 30초씩 timeout됐다. 동일 KUBECONFIG로 shell에서 실행한 `kubectl get pods/rs/deploy -o json`은 각 1초 미만이었다. Flux app/root는 suspend=false였고 injection event는 없었다.
- **근본 원인**: macOS Python 3.11은 bare executable과 기본 `close_fds=True` 조합에서 fork/exec 경로를 사용한다. ML runtime thread가 초기화된 뒤 이 fork 경로의 child exec 준비가 정체될 수 있다. absolute executable과 `close_fds=False`이면 Python의 macOS `posix_spawn` 조건을 만족한다.
- **수정 내용**: fault injector·state validator·kubectl/GitOps collector에서 executable을 절대 경로로 resolve하고 `close_fds=False`를 고정했다. 이는 model, corpus, retrieval query, fault schedule, context condition을 바꾸지 않는다.
- **현재 영향**: 관련 regression 65개·syntax·diff 검사를 통과했다. 실제 Torch-after-spawn read-only smoke는 local import가 장기화되어 Copilot/cluster mutation 전에 interrupt했으므로, clean commit의 fresh campaign에서 F1 t1 pre-injection snapshot이 정상 진행되는지 재검증한다.

- **후속 관찰·수정(append-only)**: spawn 보강 뒤 `primary32`는 artifact 생성 전 `_verified_git_revision()`의 bare `git status --porcelain`에서 같은 fork/exec timeout으로 중단됐다. fault·Copilot·AIC·artifact는 0이다. Git revision verifier도 `/usr/bin/git` 같은 absolute executable과 `close_fds=False`를 사용하도록 보강했고, Git revision의 clean-tree fail-closed 검사는 유지했다. Git/Kubernetes spawn regression 30개를 통과했으며 새 clean revision에서 다시 시작한다.

- **후속 관찰·수정(append-only, 2026-08-27)**: 위 Git 보강에도 verifier가 `cwd=project_root`를 전달해 macOS `posix_spawn` 선택 조건(`cwd is None`)을 만족하지 못함을 확인했다. Git executable과 clean-tree 대상은 유지하되, `cwd`를 제거하고 `git -C <absolute-project-root>`로 repository binding을 명시했다. 따라서 absolute Git·`close_fds=False`·`cwd=None`이 함께 성립한다. `-C` 경로와 `cwd` 부재를 직접 고정한 회귀 및 storage/run 29개가 통과했다. 이는 fresh campaign의 pre-injection Git verifier에서 재검증한다.

- **후속 관찰·수정(append-only, 2026-08-27)**: `primary33`은 위 command-shape 보강 뒤에도 Git status 15초 timeout으로 종료했다. 독립 shell의 동일 Git command는 0.20초였고, main의 import 순서를 확인한 결과 `KnowledgeRetriever`/Torch 의존성을 먼저 import한 뒤 verifier를 호출하고 있었다. Git revision verifier를 모든 live/ML dependency import보다 앞에 이동해 native runtime 전 clean-tree SHA를 봉인한다. main wiring 회귀와 syntax/diff 검사를 통과했으며, 이전 primary33에는 artifact·fault·Copilot·AIC가 없다.

- **후속 관찰·수정(append-only, 2026-08-27)**: `primary34`는 Git verifier는 통과했으나, 이후의 `gh api user` account identity probe가 Torch 이후 60초 timeout으로 fail-closed했다. output store 생성 전이므로 artifact·fault·Copilot·AIC는 0이다. GitHub account identity도 Git revision 직후, 모든 live/ML dependency import 전에 실행해 paid-overage account binding을 native runtime 전 완료하도록 이동한다.

- **후속 관찰·수정(append-only, 2026-08-27)**: `primary35`는 authorization event 뒤 preflight의 read-only `kubectl get`가 Torch 이후 `start_new_session=True` fork 경로에서 정체했다. operator interrupt 전 Flux/처치/Copilot/ledger/result는 0이고 app/root는 exact unsuspended·Ready였다. infra helper의 `kubectl`은 absolute executable·`close_fds=False`·direct child termination으로 바꾸어 macOS `posix_spawn`을 사용한다. local port-forward 재연결도 shell pipeline 없이 absolute `lsof`/`kubectl`과 explicit listener PID SIGTERM으로 보강했다.

- **후속 관찰·수정(append-only, 2026-08-27)**: `primary36`은 artifact 전 active-account `gh api user`가 timeout으로 중단됐으나 독립 shell probe는 1.31초로 정상이었다. helper가 `start_new_session=True`로 fork를 강제한 것이 원인이며, account probe도 absolute `gh`·`close_fds=False`와 direct child kill로 전환했다. 해당 campaign은 artifact·fault·Copilot·AIC가 0이다.

### [ISS-048] Copilot SDK가 null overage entitlement 인증 응답을 거부

- **카테고리**: infra / code / execution
- **심각도**: critical (P0)
- **영향**: `v2-3-main-20260827-primary39`은 F1 t1–t5와 F2 t1–t3의 8 incidents·24 rows/raw·288 validated calls를 commit한 뒤 F2 t4에서 중단됐다. F2 t4의 25 successful attempt와 1 pre-session 실패 attempt는 durable ledgers에 남았으나 result/raw/call ledger에는 commit되지 않았다. 불완전 campaign 전체는 primary estimand에 포함하지 않는다.
- **발생 빈도**: 본실험 1회, F2 t4의 runtime condition 다음 session creation.
- **관찰한 사실**: official SDK의 `session.create`가 모델 호출 전 `quota_snapshots.{chat,completions,premium_interactions}.overage_entitlement: Expected number, received null`로 exit 1을 냈다. 실패 receipt는 `actual_model/AIC/output_tokens=null`, `usage_metadata_complete=false`였고, 이어 `incident_failed(LiveCallerError) → flux_restored(exact original/CAS) → recovery_green`이 기록됐다. nodes 6/6 Ready, Flux 5/5 Ready, Boutique 정상으로 복구됐다.
- **근본 원인**: GitHub CLI가 business-seat 계정의 세 overage entitlement field를 null로 직렬화했고, pinned Copilot SDK 1.0.77이 이를 number-only schema로 검증해 session creation을 거부했다. 이 경로는 session/model/tool/usage event가 생성되기 전이다.
- **수정 내용**: runner의 sole `thesis.sdk.error`가 관측된 완전한 세-field null message와 exact schema에 일치할 때에만 zero-usage receipt로 봉인하고 최대 1회 재시도한다. 추가 event, message drift, 일반 인증 오류, usage/model/tool event가 있으면 기존처럼 fail-closed한다. Live caller는 이 새 failure code에도 zero AIC·zero premium·complete usage가 모두 성립할 때만 재시도한다.
- **현재 영향**: primary39 artifact는 append-only로 보존·배제한다. SDK/live caller regression을 통과하고, read-only quota/auth preflight를 재검증한 clean revision에서 fresh main campaign을 새 ID로 시작한다.

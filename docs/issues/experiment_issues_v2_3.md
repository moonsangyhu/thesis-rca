# V2.3 실험 이슈 트래커

## 요약

- 총 이슈: 21건
- 심각(실험 무효화): 17건
- 경고(실행 전 수정): 3건
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
- **수정 내용**: paid-overage 본실험에서는 server quota를 실행 gate/provenance로 사용하지 않는다. SDK가 `useLoggedInUser=true`로 사용하는 active GitHub login을 model-free `gh api user`로 campaign 시작과 각 incident 경계에서 확인한다. manifest는 quota 미조회 사유와 active-account provenance를 명시하고 balance를 `null`로 기록한다. 각 model call의 Terra/model/tool/skill/usage/charge receipt 검증과 30 AIC session limit은 유지한다. legacy zero-overage와 별도 pilot의 strict quota gate는 변경하지 않는다.
- **현재 영향**: identity probe unit 5개와 main wiring 통합 1개가 통과했다. 통합 검증은 quota 0회, startup+incident identity 2회, manifest v3의 null billing timestamp/quota 미조회 provenance와 durable incident event를 직접 확인한다. 전체 검증·독립 리뷰·clean commit-push 후 fresh campaign으로 재실행한다.

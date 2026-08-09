# V2.3 실험 이슈 트래커

## 요약

- 총 이슈: 4건
- 심각(실험 무효화): 2건
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

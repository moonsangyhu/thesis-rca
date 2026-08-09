# V2.3 실험 이슈 트래커

## 요약

- 총 이슈: 2건
- 심각(실험 무효화): 0건
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

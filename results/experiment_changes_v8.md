# V8 실험 코드 변경 이력

## 구현 일자
2026-04-09

## 가설
F11(NetworkDelay), F12(NetworkLoss) fault에 대응하는 네트워크 메트릭(gRPC latency p95, TCP retransmissions, node network errors)을 추가하면 LLM의 네트워크 fault 분류 정확도가 향상된다.

---

## 수정 사항

### 1. src/rag/config.py — F11/F12 FAULT_TYPES 추가
- F10 뒤에 F11(NetworkDelay), F12(NetworkLoss) 항목 추가
- F11 keywords: delay, latency, timeout, deadline, slow, netem, context deadline exceeded
- F12 keywords: loss, packet, retransmission, reset, broken pipe, EOF, connection refused

### 2. src/collector/prometheus.py — 네트워크 메트릭 4종 추가
- `_collect_request_latency()`: gRPC p95 latency (threshold: > 500ms)
- `_collect_grpc_errors()`: gRPC non-OK 에러율
- `_collect_network_errors()`: 노드 레벨 transmit/receive 에러
- `_collect_tcp_retrans()`: 노드 TCP retransmission rate (threshold: > 1.0/s)
- **리뷰 반영**: rate 윈도우를 `[5m]` → `[2m]`으로 단축 (F11/F12 INJECTION_WAIT 60s에 맞춤)
- **리뷰 반영**: network_drops도 `[5m]` → `[2m]`으로 통일
- collect() 반환값에 4개 신규 키 추가

### 3. src/processor/context_builder.py — 네트워크 메트릭 포맷팅
- `_build_metric_anomalies()`의 network_drops 섹션 뒤에 4개 섹션 추가:
  - High request latency (p95 > 500ms)
  - gRPC errors
  - Node network errors
  - TCP retransmissions

### 4. docs/runbooks/rca-f11-networkdelay.md — 신규 작성
- 증상, F6/F4/F7 감별 기준, 진단 단계, 해결 방법, PromQL/LogQL 쿼리 포함

### 5. docs/runbooks/rca-f12-networkloss.md — 신규 작성
- 증상, F6/F11/F2 감별 기준, 진단 단계, 해결 방법, PromQL/LogQL 쿼리 포함

### 6. experiments/v8/ — V7 복사 + v8 변경
- V7 디렉토리 복사
- config.py: CSV path → `experiment_results_v8.csv`, raw dir → `raw_v8`
- run.py: import/log 경로, argparse 설명 v8으로 변경
- engine.py: 클래스명 `RCAEngineV7` → `RCAEngineV8`, docstring 업데이트
- __init__.py: export 클래스명 변경
- prompts.py: V7과 동일 유지 (SOP 프롬프트 변경 없음)

### 7. scripts/stabilize/recovery.py — 복구 강화
- `recover()`: fault 복구 후 `_restart_all_deployments()` 호출 추가 (tc netem 잔여물 플러시)
- `_restart_all_deployments()`: `kubectl rollout restart deployment --all -n boutique` 신규 메서드
- `_verify_endpoints()`: 모든 service의 endpoint subsets > 0 검증 신규 메서드
  - 실패 시 30s 대기 후 재시도, 최종 실패는 WARNING 레벨 로그 (실험 중단하지 않음)

### 8. docs/experiment-versions.md — V6/V7/V8 항목 추가
- 기존 손상된 V5 라인 수정 + V6, V7, V8 행 추가

---

## 미해결/추후 확인 사항

- Loki 500 오류: 기존부터 있던 Loki 서버 문제. 실험 코드와 무관, 실험 중 그라파나에서 Loki 재시작 필요
- dry-run 결과: `metrics: 3/14 fields populated` — 클러스터 정상 상태라 네트워크 메트릭이 threshold 이하 (정상)
- F11/F12 ground_truth.csv 항목 확인 필요: V8 실험 전 60 entries 중 F11/F12 trial 포함 여부 검증

---

## dry-run 결과
```
v8 experiment: 60 trials (['F1', 'F2', 'F3', 'F4', 'F5', 'F6', 'F7', 'F8', 'F9', 'F10', 'F11', 'F12'] × [1, 2, 3, 4, 5])
Signal collection complete
[DRY RUN] System A context length: 1317 chars
[DRY RUN] System B context length: 1921 chars
metrics: 3/14 fields populated
kubectl: 5/5 fields populated
```

### [1]. Claude Code 운영 환경의 Codex-native 이식 — 2026-08-09

- **수정 에이전트**: Codex
- **증상/문제**: 저장소의 연구·실험 workflow가 `.claude/settings.json`, Claude slash skills, Claude subagents에만 연결되어 Codex에서는 동일한 자동 발견·hook 강제·역할 분리가 보장되지 않았다.
- **원인**: Codex는 repo skill을 `.agents/skills`, custom agent를 `.codex/agents/*.toml`, lifecycle hook을 `.codex/hooks.json`에서 읽으며, `apply_patch` hook payload도 Claude Write/Edit payload와 다르다.
- **수정 내용**: Codex 운영 계약, Claude skill 호환 wrapper 10개, custom agent 5개, PreToolUse payload adapter, project config를 추가했다. 공식 `superpowers@openai-curated` plugin을 설치하고 skill discovery·guard allow/deny·새 Codex process startup을 검증했다.
- **수정 파일**: `AGENTS.md`, `hooks/agent-model-guard.sh`, `.codex/config.toml`, `.codex/hooks.json`, `.codex/hooks/pretool_guard.py`, `.codex/agents/*.toml`, `.agents/skills/{changelog,commit-push,deep-analysis,experiment-issues,experiment-status,lab-restore,lab-tunnel,paper-reader,paper-survey,pr-merge}/{SKILL.md,agents/openai.yaml}`, `results/experiment_changes_v8.md`
- **상태**: 수정됨 — project hook 정의를 Codex TUI에서 검토·신뢰했고, 우회 옵션 없는 새 ephemeral session에서 실제 shell 호출이 통과함을 확인했다.

# V2 실험 변경 이력 및 교훈

## 실험 개요

- **버전**: v2 (힌트 제거 + Chain-of-Thought)
- **모델**: gpt-4o-mini (OpenAI)
- **수행 일시**: 2026-04-07
- **진행 상태**: F1 t1~t4, F2 t1 완료 후 중단 (F1 t5 스킵)

---

## 발생한 문제

### 1. F1 t5 — Prometheus 포트포워드 실패로 스킵

- **증상**: F1 t4 recovery 후 Prometheus 접속 불가 → health_check 2회 실패 → trial 스킵
- **원인**: `_restart_port_forward()`가 loki pod 대상으로만 재시작 시도. svc 대상 port-forward가 recovery 과정에서 끊어짐
- **상태**: 미해결 — health_check 자동 재시작 로직은 있으나 불안정

### 2. F2 t1 — 양 시스템 모두 correctness_score 0.0

- **증상**: System A, B 모두 "OOMKill"로 진단 (F2는 CrashLoopBackOff)
- **원인**: F1 recovery 후 Error/Evicted 상태 pod가 대량 잔존하여 F2 진단 시 OOM 관련 증상이 잔류. LLM이 잔여 OOM 증상을 F2의 CrashLoop 증상보다 우선 인식
- **상태**: 미해결 — fault 전환 시 클러스터 완전 정상화 필요

### 3. Error/Evicted 파드 1731개 누적

- **증상**: boutique 네임스페이스에 Running 13개 외 Error/Evicted/ContainerStatusUnknown 상태 파드 1718개 잔존
- **원인**: `recovery.py`가 `rollout undo`만 수행하고 실패 파드를 삭제하지 않음. 반복 trial에서 Error pod가 계속 누적
- **상태**: **수정됨** — `_wait_for_healthy()`에 Failed pod 삭제 로직 추가

### 4. 복구 후 파드 수 검증 불충분

- **증상**: recovery 후 Running pod가 12개 미만인 상태에서 다음 trial 진행
- **원인**: `_wait_for_healthy()`가 deployment Available 상태만 확인하고 Running pod 수를 검증하지 않았음
- **상태**: **수정됨** — `_wait_for_healthy(timeout, min_pods=12)` 파라미터 추가, Running pod count >= min_pods 검증

### 5. CSV 기록 검증 없음

- **증상**: CSV에 결과가 기록되었는지 확인 없이 다음 trial 진행
- **원인**: `append_result()` 호출 후 검증 로직 없었음
- **상태**: **수정됨** — `runner.py`에 before/after row count 비교 검증 추가

### 6. Trial 간 안정화 부족

- **증상**: 60초 쿨다운만으로 클러스터가 완전히 안정화되지 않음
- **원인**: `run.py`에 trial 간 cooldown 후 health_check 없이 바로 다음 trial 시작
- **상태**: **수정됨** — post-trial health check 루프 추가 (3회 × 30초 대기)

---

## 수정 완료 사항

| 파일 | 수정 내용 | 날짜 |
|------|----------|------|
| `scripts/stabilize/recovery.py` | `_wait_for_healthy()`에 min_pods 검증 + Running pod count 확인 | 2026-04-07 |
| `experiments/shared/runner.py` | CSV 기록 후 row count 검증 + `_count_csv_rows()` 헬퍼 추가 | 2026-04-07 |
| `experiments/v2/run.py` | dotenv 로드 추가, trial 간 health check 루프 (3회 × 30초) | 2026-04-07 |

---

## 추가 수정 필요 사항

### A. recovery.py — Error/Evicted 파드 정리

recovery 완료 후 `kubectl delete pods --field-selector=status.phase=Failed` 실행하여 실패 pod를 삭제해야 함. 현재는 rollout undo만 수행하므로 Error/Evicted pod가 계속 쌓임.

### B. infra.py — health_check에 pod count 확인 추가

현재 health_check()는 Prometheus/Loki port-forward만 확인. Running pod >= 12 검증을 추가하여 클러스터 정상 상태를 보장해야 함.

### C. run.py — fault 전환 시 완전 정상화 게이트

fault 간 전환(예: F1→F2) 시 단순 cooldown(900초)이 아닌:
1. Error/Evicted pod 삭제
2. Running pod >= 12 확인
3. Prometheus/Loki 접속 확인
4. 최소 120초 안정화 대기

---

## 재실행 권장 trial

| Trial | 이유 | 우선순위 |
|-------|------|---------|
| F1 t5 | Prometheus 불통으로 스킵됨 | 필수 |
| F2 t1 | F1 잔여 증상으로 오진 (0.0점) | 필수 |
| F1 t3, t4 | CSV에 미기록 (코드는 실행됨) | 확인 필요 |
| F2 전체 | F1 잔여 영향 가능성 | 권장 |

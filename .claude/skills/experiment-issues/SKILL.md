---
name: experiment-issues
description: 실험 이슈 기록 스킬. 실험 진행 중 발견된 문제를 구조화하여 기록. experiment-status 호출 시 자동으로 함께 실행된다.
---

# Experiment Issues — 실험 이슈 추적 및 기록

> **Superpowers 흐름 위치**: `/experiment-status`(executing-plans review checkpoint)에서 자동 호출되어, 발견된 이슈가 `superpowers:systematic-debugging` Phase 1(Root Cause Investigation)의 입력으로 흐른다. systematic-debugging Phase 4(Verify the fix) 직전엔 `/changelog`를 호출한다(`rules/agents.md`의 흡수 룰).

실험 진행 중 발견된 모든 문제(인프라, 코드, 프롬프트, 데이터)를 구조화하여 `docs/issues/experiment_issues_v{N}.md`에 기록한다. 다음 실험 계획 시 이 문서를 참고하여 동일 문제 재발을 방지한다.

## 트리거

- `/experiment-status` 또는 `/실험상황` 호출 시 **자동으로 함께 실행**
- `/experiment-issues` 또는 "이슈 기록" 으로 직접 호출 가능

## Workflow

### 1. 현재 실험 버전 파악

가장 최근 수정된 실험 결과 CSV에서 버전을 식별한다:
```bash
ls -t results/experiment_results_v*.csv | head -1
```

### 2. 로그에서 이슈 추출

실험 로그에서 ERROR, WARNING, CRITICAL, FAILED, SKIP 패턴을 추출한다:

```bash
VERSION=v7  # 현재 실험 버전
grep -E "(ERROR|WARNING|CRITICAL|FAILED|SKIP)" results/experiment_${VERSION}_nohup.log | \
    grep -v "tokenizers\|telemetry\|chromadb" | \
    sort | uniq -c | sort -rn | head -30
```

### 3. 이슈 분류

추출된 이슈를 아래 카테고리로 분류한다:

#### 카테고리

| 카테고리 | 설명 | 예시 |
|----------|------|------|
| **infra** | 클러스터/네트워크/디스크/SSH 문제 | DiskPressure, SSH Permission denied, port-forward 끊김 |
| **recovery** | 복구 실패, health check 미통과 | endpoint 미복원, pod 미정상화, 잔여물 |
| **injection** | fault injection 실패/예상과 다른 동작 | netem 미적용, rollout undo 실패 |
| **prompt** | LLM 진단 패턴 문제 | Step 3 흡수, 조기 확정, 오분류 패턴 |
| **data** | CSV/ground truth/데이터 문제 | SKIP된 trial, 누락 데이터, 파싱 오류 |
| **code** | 실험 코드 버그 | import 오류, config 불일치, 타입 에러 |

### 4. 이슈 문서 작성/업데이트

`docs/issues/experiment_issues_v{N}.md` 파일을 작성하거나 업데이트한다:

```markdown
# V{N} 실험 이슈 트래커

## 요약
- 총 이슈: N건
- 심각(실험 무효화): N건
- 경고(다음 실험 시 수정): N건  
- 참고(영향 미미): N건

## 이슈 목록

### [ISS-001] {제목}
- **카테고리**: infra | recovery | injection | prompt | data | code
- **심각도**: critical | warning | info
- **영향**: {어떤 trial/fault에 영향을 미쳤는지}
- **발생 빈도**: {몇 회 발생했는지}
- **근본 원인**: {왜 발생했는지}
- **현재 영향**: {실험 결과에 어떤 영향을 미치는지}
- **수정 방안**: {다음 실험 전 어떻게 수정할지}
- **관련 로그**:
  ```
  {에러 로그 발췌}
  ```
```

### 5. 이슈별 수정 우선순위

이슈를 심각도 + 빈도로 정렬하여 수정 우선순위를 매긴다:

| 우선순위 | 기준 |
|----------|------|
| **P0** | 실험 결과를 무효화하는 이슈 (예: 모든 trial에서 동일 오류) |
| **P1** | 다수 trial에 영향을 미치는 이슈 (예: health check 항상 실패) |
| **P2** | 일부 trial에 영향 (예: 특정 fault 복구 실패) |
| **P3** | 영향 미미, 다음 실험 시 개선 권장 (예: 불필요한 경고 로그) |

### 6. 진단 패턴 분석 (prompt 카테고리)

CSV에서 오답 패턴을 분석하여 프롬프트 개선점을 도출한다:

```python
# 오답에서 가장 빈번한 identified_fault_type 패턴
import csv
with open('results/experiment_results_v{N}.csv') as f:
    for r in csv.reader(f):
        if r[0] == 'timestamp': continue
        if r[5] == '0':  # incorrect
            print(f'{r[1]} t{r[2]} {r[3]}: predicted={r[4]}, expected={r[1]}')
```

반복되는 오분류 패턴을 기록한다 (예: "F6 → Service Endpoint로 오분류 5/5").

### 7. 이전 버전 이슈 해결 확인

이전 버전 이슈 문서가 있으면 (`docs/issues/experiment_issues_v{N-1}.md`), 각 이슈가 현재 버전에서 해결되었는지 확인하고 상태를 업데이트한다:
- ✅ 해결됨
- ⚠️ 부분 해결
- ❌ 미해결 (재발)

## Rules

- 이슈 문서는 **append-only** — 이전 이슈를 삭제하지 않고 상태만 업데이트
- 실험 결과 CSV/raw 데이터는 절대 수정하지 않음
- 이슈 번호(ISS-NNN)는 버전 내에서 순차 부여
- 실험 진행 중에도 이슈 기록 가능 (중간 점검)
- 실험 완료 후 최종 정리 수행

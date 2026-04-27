---
name: changelog
description: 변경 이력 기록 스킬. 코드나 문서 수정 후 "/changelog" 또는 "변경 기록"이라고 말할 때 사용. 모든 에이전트가 수정 작업 완료 시 반드시 호출.
---

# Changelog — 변경 이력 기록

> **Superpowers 흐름 위치**: 모든 코드·문서 수정 직후 호출되며, 특히 (1) `superpowers:systematic-debugging` Phase 4(Verify the fix) 직전, (2) `superpowers:finishing-a-development-branch` 옵션 선택 직전, (3) Step 5 verification 게이트 통과 직전에 마지막으로 호출된다.

에이전트가 코드·문서·설정을 수정한 후 변경 이력을 마크다운 문서에 기록한다.

## Workflow

### 1. 변경 사항 파악

```bash
git diff --stat
git diff --cached --stat
```

변경된 파일 목록과 diff를 확인한다.

### 2. 기존 changelog 확인

`results/` 디렉토리에서 현재 실험 버전에 해당하는 changelog 파일을 확인한다:

```bash
ls results/experiment_changes_*.md 2>/dev/null
```

- 파일이 있으면 기존 파일에 **추가**
- 없으면 새로 생성

### 3. 변경 이력 기록

changelog 파일(`results/experiment_changes_<version>.md`)에 아래 형식으로 기록:

```markdown
### [N]. [변경 제목] — [날짜]

- **수정 에이전트**: @에이전트명
- **증상/문제**: 무엇이 문제였는가
- **원인**: 왜 발생했는가
- **수정 내용**: 어떻게 고쳤는가
- **수정 파일**: `파일경로:라인` (변경된 파일 모두 나열)
- **상태**: 수정됨 / 부분 수정 / 미해결
```

### 4. 기록 검증

기록이 정상적으로 추가되었는지 확인:

```bash
tail -20 results/experiment_changes_<version>.md
```

## Rules

- **모든 에이전트**는 코드·문서·설정을 수정한 후 반드시 이 스킬을 호출해야 한다
- 실험 데이터(CSV/JSON) 수정은 기록 대상이 아님 (수정 자체가 금지)
- changelog 파일의 기존 내용을 삭제하지 않는다 — 항상 **추가만**
- 버전을 모르면 가장 최근 changelog 파일에 추가한다
- 사소한 변경(오타 수정, 포맷팅)도 기록한다 — 실험 재현성을 위해

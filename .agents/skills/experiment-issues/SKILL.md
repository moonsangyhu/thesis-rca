---
name: experiment-issues
description: thesis-rca 실험 로그에서 infra·recovery·injection·prompt·data·code 이슈를 추출해 append-only tracker에 기록한다. experiment-status 실행 중 또는 이슈 기록 요청에 사용한다.
---

# Experiment-issues compatibility wrapper

1. `.claude/skills/experiment-issues/SKILL.md`를 처음부터 끝까지 읽고 canonical workflow로 실행한다.
2. `/experiment-issues`는 `$experiment-issues`로 해석하고 Claude 전용 도구명은 Codex 도구로 바꾼다.
3. CSV/raw JSON은 읽기 전용이다. tracker는 기존 이슈를 삭제하지 않고 새 이슈 추가 또는 상태·빈도 갱신만 한다.
4. 로그와 파일에서 확인한 사실과 추론을 구분하고, 존재하지 않는 이슈·빈도·원인을 만들지 않는다.

---
name: changelog
description: thesis-rca 변경 이력을 기록한다. 코드·문서·설정 수정 후, 사용자가 changelog·변경 기록을 요청할 때, 또는 다른 repo workflow가 변경 기록을 요구할 때 사용한다.
---

# Changelog compatibility wrapper

1. 저장소 루트의 `.claude/skills/changelog/SKILL.md`를 처음부터 끝까지 읽고 이를 canonical domain workflow로 실행한다.
2. Claude 전용 도구명은 현재 Codex의 동등 도구로 바꾼다: Read/Glob/Grep은 파일 읽기와 `rg`, Bash는 shell execution, Write/Edit은 `apply_patch`다.
3. `/changelog` 표기는 Codex의 `$changelog` 호출과 같은 의미로 해석한다.
4. `AGENTS.md`, 현재 사용자 지시, Codex 안전 정책, `.codex/hooks.json`이 canonical workflow보다 우선한다.
5. 원본 실험 데이터는 수정하지 않고 changelog는 append-only로 유지한다.

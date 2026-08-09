---
name: commit-push
description: thesis-rca feature branch의 변경을 의도적으로 stage·commit·push한다. 사용자가 commit, push, commit-push, 중간 커밋을 요청할 때 사용하며 main 직접 push에는 사용하지 않는다.
---

# Commit-push compatibility wrapper

1. `.claude/skills/commit-push/SKILL.md`를 처음부터 끝까지 읽고 canonical workflow로 실행한다.
2. `/commit-push`는 `$commit-push`와 같은 의미다. Claude 도구명은 현재 Codex 도구로 바꾼다.
3. Claude/Anthropic attribution 예시는 복사하지 않는다. 사용자가 요구하지 않는 한 AI 공동저자 trailer를 추가하지 않는다.
4. 커밋 메시지는 저장소 규칙대로 한국어로 작성하고, 파일을 경로별로 명시해 stage한다.
5. main 직접 push, force push, hook 우회, amend는 금지한다. `AGENTS.md`와 Codex 훅이 항상 우선한다.

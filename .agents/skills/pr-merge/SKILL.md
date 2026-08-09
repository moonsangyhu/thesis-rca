---
name: pr-merge
description: thesis-rca 변경을 feature branch에서 한국어 PR로 만들고, 사용자의 명시적 승인 후 rebase merge한다. pr-merge, PR 생성, PR 날려, PR 머지 요청에 사용한다.
---

# PR-merge compatibility wrapper

1. `.claude/skills/pr-merge/SKILL.md`를 처음부터 끝까지 읽고 canonical workflow로 실행한다.
2. `/pr-merge`는 `$pr-merge`로 번역하고 GitHub connector가 있으면 PR metadata/생성에 우선 사용하며 부족한 부분만 `gh`를 쓴다.
3. Claude/Anthropic attribution과 링크는 복사하지 않는다. 사용자가 요구하지 않는 한 AI attribution을 추가하지 않는다.
4. main 직접 수정·push, force, `--no-verify`, `--admin`은 금지한다. stage 대상은 파일별로 명시하고 제목·본문·커밋은 한국어로 작성한다.
5. PR URL과 check 상태를 보고한 뒤 사용자의 명시적 승인 전에는 merge하지 않는다.

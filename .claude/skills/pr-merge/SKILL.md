---
name: pr-merge
description: Worktree → main PR 머지 전담 워크플로우. "/pr-merge", "pr 머지", "pr 날려", "pr-merge"라고 말할 때 사용. 현재 워크트리의 변경사항을 feature 브랜치로 커밋·푸시하고, 한글 제목·본문으로 gh pr을 생성한 뒤 사용자 승인 시 rebase 머지를 수행한다. main 브랜치 직접 수정은 절대 허용되지 않는다.
---

# /pr-merge — PR 기반 main 머지 전담 스킬

> 본 레포는 **모든 워크트리의 수정사항이 PR을 거쳐서만 main에 머지**되도록 강제한다.
> 이 스킬은 그 유일한 정규 경로이며, 모든 PR 제목·본문·커밋 메시지는 **한국어**로 작성한다.

> **Superpowers 흐름 위치**: `superpowers:finishing-a-development-branch`의 옵션 2(Push and create a Pull Request)를 선택하면 본 스킬로 이행한다. 옵션 1(local merge)은 PR-only 정책에 따라 사용 금지.

## 사전 조건

- `gh` CLI가 설치되어 있고 `gh auth status`가 통과해야 한다.
- 현재 워크트리의 `git remote -v`에 `origin`이 있어야 한다.
- `hooks/pr-only-guard.sh`가 활성화되어 있다(훅이 아래 위반을 2차로 막아준다).

## 절대 금지

- `git push origin main`, `git push … HEAD:main`, `… :main` refspec — 어떤 형태로든 main으로의 직접 push.
- main 브랜치 체크아웃 상태에서의 `git commit/merge/rebase/cherry-pick/revert/reset/restore`.
- `--force`, `--force-with-lease`, `-f` 푸시.
- `--no-verify`, `--no-gpg-sign`, `commit.gpgsign=false`.
- `gh pr merge --admin`(CI·리뷰 우회).
- 영문 PR 제목·본문.

## 워크플로우 (순서 고정)

### 1. 상태 점검 (병렬 실행)

```bash
git status
git branch --show-current
git worktree list
git log --oneline -5
git remote -v
```

변경 파일·현재 브랜치·원격을 확인한다. 변경이 없으면 즉시 중단한다.

### 2. 브랜치 결정

- 현재 브랜치가 `main`이면 **즉시 중단**하고 사용자에게 feature 브랜치 이름(예: `feat/<topic>`, `fix/<topic>`, `docs/<topic>`)을 제안한 뒤 승인받아 `git switch -c <branch>`.
- 현재 브랜치가 `main`이 아니면 그대로 사용(예: `claude-config`, `planning-only`, `worktree-thesis-experiments`).

### 3. 스테이지 & 커밋

- `git add`는 **파일 경로를 명시**해 수행(`git add -A`/`git add .` 금지).
- `.env`, 자격증명, 비밀키, 대용량 바이너리는 스테이지하지 않는다. 눈에 띄면 사용자에게 경고.
- 커밋 메시지는 한국어. 기존 repo 스타일(`feat(scope): …`, `fix: …`, `docs: …`)을 따른다. HEREDOC 사용:

```bash
git commit -m "$(cat <<'EOF'
feat(scope): 한 줄 요약

변경 배경·이유(왜)를 1~2 문장.

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

### 4. Push

```bash
git push -u origin <branch>
```

main으로의 push는 시도조차 하지 않는다(훅이 차단).

### 5. PR 생성 (한글)

```bash
gh pr create \
  --base main \
  --head <branch> \
  --title "<한글 제목 70자 이내>" \
  --body "$(cat <<'EOF'
## 요약

- 무엇을·왜 바꿨는지 1~3 bullet

## 변경 내역

- 핵심 파일과 핵심 diff 요약

## 검증

- [ ] 로컬 테스트/실행 확인
- [ ] 훅 동작 확인(필요 시)
- [ ] 문서/룰 갱신 확인(필요 시)

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

제목·본문이 한국어인지 다시 한 번 확인한다.

### 6. PR URL 제시 & 사용자 승인 대기

```bash
gh pr view --web
gh pr view --json number,url,title,state,mergeable,statusCheckRollup
```

사용자에게 PR URL과 CI 상태를 제시한 뒤 **"머지 진행할까요?" 한 줄로 명시적 승인을 요청**한다. 승인 전에는 절대 머지하지 않는다.

### 7. Rebase 머지 (사용자 승인 후)

```bash
gh pr merge <PR#> --rebase --delete-branch
```

- `--admin` 플래그 금지.
- CI 실패, conflict, mergeable=false면 즉시 중단하고 사용자에게 보고. 재시도는 사용자 재승인 후.
- 머지 성공 시 현재 워크트리 브랜치가 원격에서 삭제된다. 로컬 브랜치 정리는 사용자 지시가 있을 때만 수행(`git branch -D <branch>`).

### 8. 동기화 (선택)

현재 워크트리가 main을 추적하지 않는다면 해당 워크트리에서는 별도 동기화 불필요. main을 추적하는 워크트리(`thesis-rca`)에서 작업을 이어가려면:

```bash
git -C /Users/yumunsang/Documents/thesis-rca fetch origin
git -C /Users/yumunsang/Documents/thesis-rca pull --rebase origin main
```

## 체크리스트 (완료 전 반드시 확인)

- [ ] 현재 브랜치가 main이 아니다.
- [ ] 스테이지된 파일에 시크릿/자격증명이 없다.
- [ ] 커밋·PR 제목·PR 본문이 모두 한국어다.
- [ ] `gh pr create --base main --head <branch>`로 PR이 생성되었고 URL을 사용자에게 제시했다.
- [ ] 사용자 승인을 받은 후에만 `gh pr merge --rebase --delete-branch`를 실행했다.
- [ ] `--force`, `--no-verify`, `--admin`을 쓰지 않았다.

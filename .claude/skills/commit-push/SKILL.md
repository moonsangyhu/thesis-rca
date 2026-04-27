---
name: commit-push
description: Git commit and push workflow. Use when the user asks to commit and push changes, or says "commit-push", "/commit-push". Stages changed files, creates a descriptive commit, and pushes to the current remote branch.
---

# Commit & Push

> **Superpowers 흐름 위치**: **feature 브랜치에서의 중간 커밋 전용**. main 브랜치로의 push는 절대 시도하지 않는다(pr-only-guard가 차단). 작업 최종 완료(=main 반영)는 `superpowers:finishing-a-development-branch` 옵션 2 선택 후 `/pr-merge` 스킬로 이행한다.

## Workflow

1. **Inspect changes** — run in parallel:
   - `git status` (never use `-uall`)
   - `git diff` and `git diff --cached` to see all changes
   - `git log --oneline -5` for commit message style

2. **Stage files** — add relevant changed/untracked files by name (avoid `git add -A`). Never stage `.env`, credentials, or secrets.

3. **Draft commit message** — summarize the "why" in 1-2 sentences. Match the repo's existing style (from git log). Use Korean if the repo convention is Korean.

4. **Commit** using HEREDOC format:
   ```bash
   git commit -m "$(cat <<'EOF'
   Commit message here.

   Co-Authored-By: Claude Opus 4.6 (1M context) <noreply@anthropic.com>
   EOF
   )"
   ```

5. **Push** to the current branch:
   ```bash
   git push
   ```
   If no upstream is set, use `git push -u origin <branch>`.

6. **Verify** — run `git status` after push to confirm clean state.

## Rules

- Never force push (`--force`)
- Never skip hooks (`--no-verify`)
- Never amend unless explicitly asked
- Warn if staging files that look like secrets
- If there are no changes, do not create an empty commit

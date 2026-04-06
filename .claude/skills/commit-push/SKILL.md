---
name: commit-push
description: Git commit and push workflow. Use when the user asks to commit and push changes, or says "commit-push", "/commit-push". Stages changed files, creates a descriptive commit, and pushes to the current remote branch.
---

# Commit & Push

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

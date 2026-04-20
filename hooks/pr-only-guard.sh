#!/usr/bin/env python3
#
# PreToolUse Hook: PR-only Guard (Bash)
# 모든 워크트리에서 main 브랜치 직접 수정을 차단하고 PR 워크플로우(/pr-merge)를 강제한다.
# 토큰 경계 기반 검사(shlex)로 커밋 메시지 내부 문자열 false-positive 방지.
# Exit codes: 0 = allowed, 2 = blocked
# 파일 확장자는 .sh지만 shebang으로 python3 실행.
#
import json
import shlex
import subprocess
import sys

RED = "\033[0;31m"
YELLOW = "\033[1;33m"
NC = "\033[0m"


def block(cmd: str, reason: str) -> None:
    print(f"{RED}🚫 BLOCKED: PR-only 정책 위반{NC}", file=sys.stderr)
    print(f"{RED}명령: {cmd}{NC}", file=sys.stderr)
    print(f"{RED}사유: {reason}{NC}", file=sys.stderr)
    print(
        f"{YELLOW}해결: /pr-merge 스킬로 feature 브랜치 → PR → rebase 머지 플로우를 사용하세요.{NC}",
        file=sys.stderr,
    )
    sys.exit(2)


try:
    data = json.load(sys.stdin)
except Exception:
    sys.exit(0)

cmd = (data.get("tool_input", {}) or {}).get("command", "") or ""
if not cmd.strip():
    sys.exit(0)

# 쿼트 내부(커밋 메시지 본문 등)는 하나의 토큰으로 묶여 false-positive 방지됨.
# 쿼트가 불균형한 드문 경우 fallback: 공백 split.
try:
    toks = shlex.split(cmd, posix=True)
except ValueError:
    toks = cmd.split()

branch = ""
try:
    root = subprocess.check_output(
        ["git", "rev-parse", "--show-toplevel"],
        text=True, stderr=subprocess.DEVNULL,
    ).strip()
    branch = subprocess.check_output(
        ["git", "-C", root, "rev-parse", "--abbrev-ref", "HEAD"],
        text=True, stderr=subprocess.DEVNULL,
    ).strip()
except Exception:
    pass

MOD_SUBCMDS = {
    "commit", "merge", "rebase", "cherry-pick", "revert",
    "reset", "restore", "am", "apply",
}


def find_git_invocations(toks):
    """Return list of (git_idx, subcmd_idx, subcmd, rest_args). 전역 옵션(-c, -C, --git-dir=…) 건너뜀."""
    out = []
    i = 0
    while i < len(toks):
        if toks[i] == "git":
            j = i + 1
            while j < len(toks):
                t = toks[j]
                if t in ("-c", "-C"):
                    j += 2
                    continue
                if t.startswith("--git-dir") or t.startswith("--work-tree") or t.startswith("--namespace"):
                    j += 1 if "=" in t else 2
                    continue
                if t.startswith("-"):
                    j += 1
                    continue
                break
            if j < len(toks):
                out.append((i, j, toks[j], toks[j + 1 :]))
            i = j + 1
        else:
            i += 1
    return out


git_calls = find_git_invocations(toks)

# 1) main 체크아웃 상태에서의 수정 명령 전면 차단
if branch == "main":
    for _, _, sub, rest in git_calls:
        if sub in MOD_SUBCMDS:
            block(cmd, "main 브랜치에서 직접 수정 금지. feature 브랜치로 전환 후 /pr-merge 사용.")
        if sub == "checkout" and "--" in rest:
            block(cmd, "main 브랜치에서 working tree 덮어쓰기 금지.")

# 2) git push — main target 및 force 차단
for _, _, sub, rest in git_calls:
    if sub != "push":
        continue
    for t in rest:
        if t in ("--force", "-f", "--force-with-lease") or t.startswith("--force-with-lease="):
            block(cmd, "force push 금지. 충돌은 rebase로 해결하세요.")
    non_flag = [t for t in rest if not t.startswith("-")]
    refspecs = non_flag[1:] if len(non_flag) >= 2 else non_flag
    for r in refspecs:
        base = r.lstrip("+")
        target = base.split(":", 1)[1] if ":" in base else base
        if target.startswith("refs/heads/"):
            target = target[len("refs/heads/") :]
        if target == "main":
            block(cmd, "main 브랜치로의 직접 push 금지.")

# 3) 훅·서명 우회 토큰 (git 호출 범위에서만)
for start, subcmd_idx, sub, rest in git_calls:
    pre_opts = toks[start + 1 : subcmd_idx]
    for t in pre_opts + rest:
        if t == "--no-verify":
            block(cmd, "--no-verify로 훅 우회 금지.")
        if t == "--no-gpg-sign":
            block(cmd, "GPG 서명 우회 금지.")
        if t == "commit.gpgsign=false":
            block(cmd, "GPG 서명 우회 금지(-c commit.gpgsign=false).")

# 4) gh pr merge --admin
i = 0
while i < len(toks) - 2:
    if toks[i] == "gh" and toks[i + 1] == "pr" and toks[i + 2] == "merge":
        if "--admin" in toks[i + 3 :]:
            block(cmd, "gh pr merge --admin(bypass) 금지.")
        i += 3
    else:
        i += 1

sys.exit(0)

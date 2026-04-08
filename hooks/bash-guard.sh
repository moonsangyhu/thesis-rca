#!/bin/bash
#
# PreToolUse Hook: Bash Guard
# Blocks destructive or hard-to-reverse shell commands
# Exit codes: 0 = allowed, 2 = blocked
#

RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Parse command from stdin JSON (tool_input.command)
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('command',''))" \
  2>/dev/null || echo "")

if [[ -z "$COMMAND" ]]; then
  exit 0
fi

block() {
  local reason="$1"
  echo -e "${RED}🚫 BLOCKED: $reason${NC}" >&2
  echo -e "${RED}Command: $COMMAND${NC}" >&2
  echo -e "${YELLOW}안전한 대안을 사용하거나 사용자에게 직접 확인을 요청하세요.${NC}" >&2
  exit 2
}

# --- Destructive file system operations ---
if echo "$COMMAND" | grep -qE 'rm\s+.*-[a-z]*r[a-z]*f[a-z]*\s+/\s*$'; then
  block "rm -rf / is not allowed"
fi
if echo "$COMMAND" | grep -qE 'rm\s+.*-[a-z]*r[a-z]*f[a-z]*\s+/\*'; then
  block "rm -rf /* is not allowed"
fi
CRITICAL_DIRS='(/(etc|usr|bin|sbin|lib|lib64|boot|home|root|var|sys|proc|dev)(/|$|\s))'
if echo "$COMMAND" | grep -qE "rm\s+.*-[a-z]*r[a-z]*f[a-z]*\s+$CRITICAL_DIRS"; then
  block "rm -rf on critical system directory is not allowed"
fi

# --- Git force operations ---
if echo "$COMMAND" | grep -qE 'git\s+push\s+.*-(-force|-f)\b'; then
  if echo "$COMMAND" | grep -qE '(main|master)'; then
    block "git push --force to main/master is not allowed"
  fi
fi

if echo "$COMMAND" | grep -qE 'git\s+reset\s+--hard'; then
  UNCOMMITTED=$(git diff --name-only 2>/dev/null; git diff --cached --name-only 2>/dev/null)
  COUNT=$(echo "$UNCOMMITTED" | grep -c . 2>/dev/null || echo 0)
  if [[ "$COUNT" -gt 0 ]]; then
    block "git reset --hard with $COUNT uncommitted change(s) — commit or stash first"
  fi
fi

if echo "$COMMAND" | grep -qE 'git\s+clean\s+.*-[a-z]*f'; then
  block "git clean -f is not allowed (would delete untracked files)"
fi

# --- Database destruction ---
if echo "$COMMAND" | grep -qiE '(DROP\s+(TABLE|DATABASE|SCHEMA)|TRUNCATE\s+TABLE)'; then
  block "Destructive SQL DDL (DROP/TRUNCATE) is not allowed via Bash hook"
fi

exit 0

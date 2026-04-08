#!/bin/bash
#
# PreToolUse Hook: Experiment Guard
# Blocks git operations while an experiment is actively running
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

# Only check git commands that could disrupt experiments
if ! echo "$COMMAND" | grep -qE 'git\s+(commit|push|checkout|switch|merge|rebase|stash)'; then
  exit 0
fi

# Check for running experiment PIDs
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo ".")
EXPERIMENT_RUNNING=false

for pid_file in "$PROJECT_ROOT"/results/experiment_v*.pid; do
  [[ -f "$pid_file" ]] || continue
  PID=$(cat "$pid_file" 2>/dev/null)
  if [[ -n "$PID" ]] && ps -p "$PID" > /dev/null 2>&1; then
    EXPERIMENT_RUNNING=true
    break
  fi
done

if [[ "$EXPERIMENT_RUNNING" == true ]]; then
  echo -e "${RED}🚫 BLOCKED: 실험 실행 중 git 작업 금지${NC}" >&2
  echo -e "${RED}Command: $COMMAND${NC}" >&2
  echo -e "${YELLOW}실험을 먼저 중단한 후 수정 → /changelog → /commit-push → 실험 재개 순서를 따르세요.${NC}" >&2
  echo -e "${YELLOW}(rules/data-safety.md 참조)${NC}" >&2
  exit 2
fi

exit 0

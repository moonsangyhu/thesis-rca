#!/bin/bash
#
# PreToolUse Hook: Claude Config Guard
# 이 워크트리에서는 Claude 설정 관련 경로 외 Write/Edit/MultiEdit를 차단한다.
# Exit codes: 0 = allowed, 2 = blocked
#

RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" \
  2>/dev/null || echo "")

if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

# 이 가드는 claude-config 워크트리(claude-config 브랜치) 전용이다.
# 다른 브랜치(main, experiment, feature/*)에서는 도메인 파일 수정을 허용한다.
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
if [[ "$CURRENT_BRANCH" != "claude-config" ]]; then
  exit 0
fi

# 홈 하위 Claude 메타 경로는 Claude 관련 자산이므로 허용
if [[ "$FILE_PATH" == /Users/*/.claude/* ]]; then exit 0; fi
if [[ "$FILE_PATH" == /Users/*/.claude/plans/* ]]; then exit 0; fi
if [[ "$FILE_PATH" == /Users/*/.claude/projects/*/memory/* ]]; then exit 0; fi

PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
REL_PATH="$FILE_PATH"
if [[ -n "$PROJECT_ROOT" && "$FILE_PATH" == "$PROJECT_ROOT"/* ]]; then
  REL_PATH="${FILE_PATH#$PROJECT_ROOT/}"
fi

allow=0
case "$REL_PATH" in
  .claude/*|\
  CLAUDE.md|\
  rules/agents.md|\
  hooks/claude-config-guard.sh|\
  hooks/pr-only-guard.sh|\
  hooks/agent-model-guard.sh|\
  .gitignore)
    allow=1
    ;;
esac

if [[ "$allow" -eq 1 ]]; then
  exit 0
fi

echo -e "${RED}🚫 BLOCKED: claude-config 워크트리는 Claude 설정 파일만 수정할 수 있습니다.${NC}" >&2
echo -e "${RED}File: $FILE_PATH${NC}" >&2
echo -e "${YELLOW}허용 경로: .claude/**, CLAUDE.md, rules/agents.md, hooks/claude-config-guard.sh, hooks/pr-only-guard.sh, hooks/agent-model-guard.sh, .gitignore${NC}" >&2
echo -e "${YELLOW}다른 경로를 수정하려면 메인 워크트리(main 브랜치)로 전환하세요.${NC}" >&2
exit 2

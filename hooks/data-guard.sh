#!/bin/bash
#
# PreToolUse Hook: Data Guard
# Blocks writes to immutable experiment result files
# Exit codes: 0 = allowed, 2 = blocked
#

RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Parse file_path from stdin JSON (tool_input.file_path)
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path',''))" \
  2>/dev/null || echo "")

if [[ -z "$FILE_PATH" ]]; then
  exit 0
fi

block() {
  local reason="$1"
  echo -e "${RED}🚫 BLOCKED: $reason${NC}" >&2
  echo -e "${RED}File: $FILE_PATH${NC}" >&2
  echo -e "${YELLOW}원본 실험 데이터는 수정·삭제가 금지됩니다. (rules/data-safety.md 참조)${NC}" >&2
  exit 2
}

# Normalize to relative path from project root
REL_PATH="$FILE_PATH"
PROJECT_ROOT=$(git rev-parse --show-toplevel 2>/dev/null || echo "")
if [[ -n "$PROJECT_ROOT" && "$FILE_PATH" == "$PROJECT_ROOT"* ]]; then
  REL_PATH="${FILE_PATH#$PROJECT_ROOT/}"
fi

# Block: results/*.csv (experiment result CSVs)
if echo "$REL_PATH" | grep -qE '^results/[^/]+\.csv$'; then
  # Allow experiment_changes_v*.md (not CSV, but just in case of future .csv changes logs)
  block "실험 결과 CSV 파일 수정 금지 (results/*.csv)"
fi

# Block: results/raw_v*/*.json (raw experiment data)
if echo "$REL_PATH" | grep -qE '^results/raw_v[0-9]+/.*\.json$'; then
  block "Raw 실험 데이터 수정 금지 (results/raw_v*/*.json)"
fi

# Block: results/ground_truth.csv
if echo "$REL_PATH" | grep -qE '^results/ground_truth\.csv$'; then
  block "Ground truth 데이터 수정 금지"
fi

exit 0

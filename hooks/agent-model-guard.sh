#!/usr/bin/env bash
# hooks/agent-model-guard.sh
# Enforce: 계획=opus / 수행=sonnet. Agent 도구의 model 오버라이드가 매핑을 위반하면 차단.

set -euo pipefail
INPUT=$(cat)

SUBAGENT=$(printf '%s' "$INPUT" | jq -r '.tool_input.subagent_type // empty')
MODEL=$(printf '%s' "$INPUT" | jq -r '.tool_input.model // empty')

case "$SUBAGENT" in
  experiment-planner|hypothesis-reviewer|paper-writer) REQUIRED=opus ;;
  experiment|code-reviewer|experiment-modifier|results-writer) REQUIRED=sonnet ;;
  *) exit 0 ;;
esac
[[ -z "$MODEL" ]] && exit 0
[[ "$MODEL" == "$REQUIRED" ]] && exit 0

cat >&2 <<EOF
BLOCKED by agent-model-guard: @${SUBAGENT}은(는) model='${REQUIRED}'만 허용됩니다 (요청된 값: '${MODEL}').
원칙: 계획·리뷰·저술=opus / 수행·코드·분석=sonnet. rules/agents.md 참고.
model 파라미터를 생략하면 프론트매터(${REQUIRED})가 그대로 적용됩니다.
EOF
exit 2

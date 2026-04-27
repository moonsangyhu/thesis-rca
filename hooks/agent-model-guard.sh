#!/usr/bin/env bash
# hooks/agent-model-guard.sh
# 모델 권장 가이드: 계획·저술=opus / 수행=sonnet.
# 위반 시 stderr 경고만 출력하고 통과(exit 0). 강제 차단으로 되돌리려면 마지막 줄을 'exit 0' → 'exit 2'로.

set -euo pipefail
INPUT=$(cat)

SUBAGENT=$(printf '%s' "$INPUT" | jq -r '.tool_input.subagent_type // empty')
MODEL=$(printf '%s' "$INPUT" | jq -r '.tool_input.model // empty')

case "$SUBAGENT" in
  experiment-planner|paper-writer) REQUIRED=opus ;;
  experiment) REQUIRED=sonnet ;;
  *) exit 0 ;;
esac
[[ -z "$MODEL" ]] && exit 0
[[ "$MODEL" == "$REQUIRED" ]] && exit 0

cat >&2 <<EOF
WARNING (not blocking) by agent-model-guard: @${SUBAGENT}은(는) model='${REQUIRED}' 권장입니다 (요청된 값: '${MODEL}').
원칙: 계획·저술=opus / 수행=sonnet. rules/agents.md 참고.
강제 차단으로 되돌리려면 hooks/agent-model-guard.sh의 마지막 'exit 0'을 'exit 2'로 변경하세요.
EOF
exit 0

#!/bin/bash
#
# PreToolUse Hook: Secret Scanner
# Detects sensitive patterns before writing/editing files
# Exit codes: 0 = safe, 2 = blocked (sensitive data detected)
#

set -e

RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Pattern definitions (20+ sensitive patterns)
PATTERNS=(
  # AWS
  'AKIA[0-9A-Z]{16}'

  # API Keys
  'sk-[a-zA-Z0-9]{48}'  # OpenAI
  'ghp_[a-zA-Z0-9]{36}' # GitHub PAT
  'AIza[0-9A-Za-z_-]{35}'  # Google API Key
  'sk_live_[0-9a-zA-Z]{24}'  # Stripe Secret Key

  # Bot Tokens
  'xoxb-[0-9A-Za-z-]+'  # Slack Bot
  'xoxp-[0-9A-Za-z-]+'  # Slack User

  # Private Keys
  '-----BEGIN .* PRIVATE KEY-----'
  '-----BEGIN .* CERTIFICATE-----'

  # Database URLs with credentials
  '(postgres|mysql|mongodb|redis)://[^:]+:[^@]+@'

  # JWT Tokens
  'eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.'

  # Generic secrets (password/token/secret assignments)
  '(?i)(password|secret|token|api_key|auth_token|access_token)\s*[=:]\s*["'"'"'][^"'"'"']{8,}["'"'"']'
  '(?i)(password|secret|token|api_key|auth_token|access_token)\s*[=:]\s*[^"'"'"'[:space:]][^[:space:]]{8,}'

  # Azure
  'DefaultEndpointsProtocol=https;AccountName='

  # Firebase
  'AIza[0-9A-Za-z\-_]{35}'

  # PagerDuty
  'service_key=[0-9a-zA-Z]{32}'
  'routing_key=[0-9a-zA-Z]{32}'

  # SSH/RSA
  'BEGIN RSA PRIVATE KEY'
  'BEGIN EC PRIVATE KEY'
  'BEGIN OPENSSH PRIVATE KEY'

  # NPM Token
  '//registry.npmjs.org/:_authToken='

  # Docker Config
  '"auth"\s*:\s*"[a-zA-Z0-9+/=]{20,}"'
)

# Parse file path and content from stdin JSON
INPUT=$(cat)
FILE_PATH=$(echo "$INPUT" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); print(d.get('tool_input',{}).get('file_path','unknown'))" \
  2>/dev/null || echo "unknown")

# Extract only changed content: Write→content, Edit/MultiEdit→new_string
CONTENT=$(echo "$INPUT" | python3 -c \
  "import sys,json; d=json.load(sys.stdin); ti=d.get('tool_input',{}); \
   print(ti.get('content', ti.get('new_string', '')))" \
  2>/dev/null || echo "$INPUT")

# Check if file is in allowlist (warnings only)
IS_ALLOWLISTED=false
if [[ "$FILE_PATH" == *".env.example" ]] || [[ "$FILE_PATH" == *.test.* ]]; then
  IS_ALLOWLISTED=true
fi

# Check each pattern
MATCHED=false
DETECTED_PATTERNS=()
for pattern in "${PATTERNS[@]}"; do
  if echo "$CONTENT" | grep -E -q -- "$pattern"; then
    MATCHED=true
    DETECTED_PATTERNS+=("$pattern")
  fi
done

# Handle results
if [[ "$MATCHED" == true ]]; then
  if [[ "$IS_ALLOWLISTED" == true ]]; then
    echo -e "${YELLOW}⚠️  WARNING: Sensitive data pattern detected in $FILE_PATH${NC}" >&2
    echo -e "${YELLOW}This file is allowlisted (.env.example, *.test.*), allowing operation with caution.${NC}" >&2
    exit 0
  else
    echo -e "${RED}🚫 BLOCKED: Sensitive data pattern detected in $FILE_PATH${NC}" >&2
    echo -e "${RED}The content appears to contain secrets (API keys, passwords, tokens, etc.)${NC}" >&2
    echo -e "${RED}Please remove sensitive data before proceeding.${NC}" >&2
    echo -e "${RED}${NC}" >&2
    echo -e "${RED}Detected patterns:${NC}" >&2
    for pattern in "${DETECTED_PATTERNS[@]}"; do
      echo -e "${RED}  - $pattern${NC}" >&2
    done
    exit 2
  fi
else
  exit 0
fi

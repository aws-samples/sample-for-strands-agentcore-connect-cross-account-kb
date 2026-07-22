#!/bin/bash

# Generate local, gitignored configuration for the declarative Harness variant.

set -o errexit
set -o nounset
set -o pipefail

usage() {
    echo "Usage: $0 [Required Parameters] [Optional Parameters]"
    echo ""
    echo "Required Parameters:"
    echo "  --agent-account <number>       12-digit account that hosts AgentCore"
    echo "  --agent-kb-account <number>    12-digit account that hosts the KB"
    echo "  --knowledge-base-id <id>       Bedrock Knowledge Base ID"
    echo ""
    echo "Optional Parameters:"
    echo "  --kb-access-role <name>        KB role name (default: bedrock_kb_access_role)"
    echo "  --region <region>              AWS region (default: us-west-2)"
    echo "  --help                         Show this help message"
    exit 1
}

AGENT_ACCOUNT_NUMBER=""
AGENT_KB_ACCOUNT_NUMBER=""
KNOWLEDGE_BASE_ID=""
KB_ACCESS_ROLE_NAME="bedrock_kb_access_role"
REGION="us-west-2"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --agent-account)       AGENT_ACCOUNT_NUMBER="$2"; shift 2 ;;
        --agent-kb-account)    AGENT_KB_ACCOUNT_NUMBER="$2"; shift 2 ;;
        --knowledge-base-id)   KNOWLEDGE_BASE_ID="$2"; shift 2 ;;
        --kb-access-role)      KB_ACCESS_ROLE_NAME="$2"; shift 2 ;;
        --region)              REGION="$2"; shift 2 ;;
        --help)                usage ;;
        *)                     echo "Error: Unknown parameter $1"; usage ;;
    esac
done

[[ "$AGENT_ACCOUNT_NUMBER" =~ ^[0-9]{12}$ ]] \
    || { echo "Error: --agent-account must be a 12-digit AWS account number"; exit 1; }
[[ "$AGENT_KB_ACCOUNT_NUMBER" =~ ^[0-9]{12}$ ]] \
    || { echo "Error: --agent-kb-account must be a 12-digit AWS account number"; exit 1; }
[[ -n "$KNOWLEDGE_BASE_ID" ]] \
    || { echo "Error: --knowledge-base-id is required"; exit 1; }
command -v jq >/dev/null \
    || { echo "Error: jq is required"; exit 1; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR/../harness_variant/strandskbharness"
KB_ROLE_ARN="arn:aws:iam::${AGENT_KB_ACCOUNT_NUMBER}:role/${KB_ACCESS_ROLE_NAME}"
TEMP_FILES=()

cleanup() {
    for temp_file in "${TEMP_FILES[@]-}"; do
        [[ -n "$temp_file" ]] && rm -f "$temp_file"
    done
    return 0
}
trap cleanup EXIT

write_json() {
    local destination="$1"
    local temp_file
    temp_file=$(mktemp)
    TEMP_FILES+=("$temp_file")
    jq '.' > "$temp_file"
    mv "$temp_file" "$destination"
}

jq \
    --arg role_arn "$KB_ROLE_ARN" \
    '(.agentCoreGateways[].targets[].compute.iamPolicy.Statement[]
      | select(.Sid == "AssumeKBAccessRole").Resource) = $role_arn' \
    "$PROJECT_DIR/agentcore/agentcore.json.template" \
    | write_json "$PROJECT_DIR/agentcore/agentcore.json"

jq \
    --arg account "$AGENT_ACCOUNT_NUMBER" \
    --arg region "$REGION" \
    '.[0].account = $account | .[0].region = $region' \
    "$PROJECT_DIR/agentcore/aws-targets.json.template" \
    | write_json "$PROJECT_DIR/agentcore/aws-targets.json"

jq \
    --arg kb_id "$KNOWLEDGE_BASE_ID" \
    --arg role_arn "$KB_ROLE_ARN" \
    --arg region "$REGION" \
    '.KNOWLEDGE_BASE_ID = $kb_id
      | .TARGET_ROLE_ARN = $role_arn
      | .AWS_REGION = $region' \
    "$PROJECT_DIR/tools/kb_query/config.json.template" \
    | write_json "$PROJECT_DIR/tools/kb_query/config.json"

jq '.' "$PROJECT_DIR/app/strands_kb_harness/harness.json.template" \
    | write_json "$PROJECT_DIR/app/strands_kb_harness/harness.json"

echo "Generated local Harness configuration:"
echo "  $PROJECT_DIR/agentcore/agentcore.json"
echo "  $PROJECT_DIR/agentcore/aws-targets.json"
echo "  $PROJECT_DIR/tools/kb_query/config.json"
echo "  $PROJECT_DIR/app/strands_kb_harness/harness.json"
echo ""
echo "These files are gitignored. Deploy Phase 1, then attach the Gateway"
echo "with 'agentcore add tool' as documented in README.md."

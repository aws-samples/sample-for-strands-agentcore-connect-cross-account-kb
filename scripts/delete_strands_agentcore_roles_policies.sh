#!/bin/bash

# Script to delete IAM roles and policies created for Strands Agent + AgentCore
# Usage: ./delete_strands_agentcore_roles_policies.sh [options]

set -o pipefail

usage() {
    echo "Usage: $0 [Required Parameters]"
    echo ""
    echo "Required Parameters:"
    echo "  --agent-profile <profile>         AWS CLI profile for agent account"
    echo "  --agent-kb-profile <profile>      AWS CLI profile for agent-kb account"
    echo "  --agentcore-role <name>           Name of AgentCore execution role to delete"
    echo "  --kb-access-role <name>           Name of KB access role to delete"
    echo "  --kb-access-policy <name>         Name of KB access policy to delete"
    echo "  --agentcore-policy <name>         Name of AgentCore policy to delete"
    echo "  --agent-account <number>          12-digit AWS account number for agent"
    echo "  --agent-kb-account <number>       12-digit AWS account number for agent-kb"
    echo "  --help                            Show this help message"
    echo ""
    echo "Example:"
    echo "  $0 --agent-profile agent \\"
    echo "     --agent-kb-profile agent-kb \\"
    echo "     --agentcore-role strands_agentcore_execution_role \\"
    echo "     --kb-access-role bedrock_kb_access_role \\"
    echo "     --kb-access-policy bedrock_kb_access_policy \\"
    echo "     --agentcore-policy strands_agentcore_sts_policy \\"
    echo "     --agent-account 111122223333 \\"
    echo "     --agent-kb-account 999999999999"
    echo ""
    echo "WARNING: This will permanently delete IAM roles and policies!"
    exit 1
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --agent-profile)       AGENT_PROFILE="$2";       shift 2 ;;
        --agent-kb-profile)    AGENT_KB_PROFILE="$2";    shift 2 ;;
        --agentcore-role)      AGENTCORE_ROLE_NAME="$2";  shift 2 ;;
        --kb-access-role)      KB_ACCESS_ROLE_NAME="$2"; shift 2 ;;
        --kb-access-policy)    KB_ACCESS_POLICY_NAME="$2"; shift 2 ;;
        --agentcore-policy)    AGENTCORE_POLICY_NAME="$2"; shift 2 ;;
        --agent-account)       AGENT_ACCOUNT_NUMBER="$2"; shift 2 ;;
        --agent-kb-account)    AGENT_KB_ACCOUNT_NUMBER="$2"; shift 2 ;;
        --help)                usage ;;
        *)                     echo "Error: Unknown parameter $1"; usage ;;
    esac
done

# Validate required parameters
MISSING_PARAMS=()
[[ -z "$AGENT_PROFILE" ]]       && MISSING_PARAMS+=("--agent-profile")
[[ -z "$AGENT_KB_PROFILE" ]]    && MISSING_PARAMS+=("--agent-kb-profile")
[[ -z "$AGENTCORE_ROLE_NAME" ]]  && MISSING_PARAMS+=("--agentcore-role")
[[ -z "$KB_ACCESS_ROLE_NAME" ]] && MISSING_PARAMS+=("--kb-access-role")
[[ -z "$KB_ACCESS_POLICY_NAME" ]] && MISSING_PARAMS+=("--kb-access-policy")
[[ -z "$AGENTCORE_POLICY_NAME" ]] && MISSING_PARAMS+=("--agentcore-policy")
[[ -z "$AGENT_ACCOUNT_NUMBER" ]] && MISSING_PARAMS+=("--agent-account")
[[ -z "$AGENT_KB_ACCOUNT_NUMBER" ]] && MISSING_PARAMS+=("--agent-kb-account")

if [[ ${#MISSING_PARAMS[@]} -gt 0 ]]; then
    echo "Error: Missing required parameters:"
    for param in "${MISSING_PARAMS[@]}"; do echo "  $param"; done
    echo ""; usage
fi

if [[ ! "$AGENT_ACCOUNT_NUMBER" =~ ^[0-9]{12}$ ]]; then
    echo "Error: --agent-account must be a 12-digit AWS account number"; exit 1
fi
if [[ ! "$AGENT_KB_ACCOUNT_NUMBER" =~ ^[0-9]{12}$ ]]; then
    echo "Error: --agent-kb-account must be a 12-digit AWS account number"; exit 1
fi

echo "=========================================="
echo "Deleting Strands AgentCore Cross-Account Roles"
echo "=========================================="
echo "AgentCore Role:   $AGENTCORE_ROLE_NAME"
echo "KB Access Role:   $KB_ACCESS_ROLE_NAME"
echo "=========================================="
echo ""
echo "WARNING: This will permanently delete the above roles and their policies."
echo ""
read -p "Are you sure you want to continue? (yes/no): " CONFIRM
if [[ "$CONFIRM" != "yes" ]]; then echo "Operation cancelled."; exit 0; fi

# Validate profiles
AGENT_IDENTITY=$(aws sts get-caller-identity --profile "$AGENT_PROFILE" 2>&1)
if [ $? -ne 0 ]; then echo "Failed to validate agent profile. Error: $AGENT_IDENTITY"; exit 1; fi
AGENT_ACTUAL_ACCOUNT=$(echo "$AGENT_IDENTITY" | jq -r '.Account' 2>/dev/null)
if [[ "$AGENT_ACTUAL_ACCOUNT" != "$AGENT_ACCOUNT_NUMBER" ]]; then
    echo "Agent profile account mismatch! Expected: $AGENT_ACCOUNT_NUMBER  Actual: $AGENT_ACTUAL_ACCOUNT"; exit 1
fi

AGENT_KB_IDENTITY=$(aws sts get-caller-identity --profile "$AGENT_KB_PROFILE" 2>&1)
if [ $? -ne 0 ]; then echo "Failed to validate agent-kb profile. Error: $AGENT_KB_IDENTITY"; exit 1; fi
AGENT_KB_ACTUAL_ACCOUNT=$(echo "$AGENT_KB_IDENTITY" | jq -r '.Account' 2>/dev/null)
if [[ "$AGENT_KB_ACTUAL_ACCOUNT" != "$AGENT_KB_ACCOUNT_NUMBER" ]]; then
    echo "Agent-KB profile account mismatch! Expected: $AGENT_KB_ACCOUNT_NUMBER  Actual: $AGENT_KB_ACTUAL_ACCOUNT"; exit 1
fi

echo "Profiles validated. Starting deletion..."
echo ""

# Helper: delete a managed policy after first removing its non-default versions.
# AWS rejects delete-policy when non-default versions exist; without this loop the
# delete fails silently and leaves the policy behind.
delete_iam_policy_with_versions() {
    local policy_arn="$1"
    local profile="$2"
    local non_default
    non_default=$(aws iam list-policy-versions --policy-arn "$policy_arn" --profile "$profile" \
        --query 'Versions[?!IsDefaultVersion].VersionId' --output text 2>/dev/null)
    if [[ -n "$non_default" ]]; then
        for v in $non_default; do
            aws iam delete-policy-version --policy-arn "$policy_arn" --version-id "$v" \
              --profile "$profile" 2>/dev/null
        done
    fi
    aws iam delete-policy --policy-arn "$policy_arn" --profile "$profile" 2>/dev/null
}

# Step 0: Remove inline sts:AssumeRole policy from the calling IAM principal
echo "Step 0: Removing local-testing inline policy from agent account caller..."

AGENT_CALLER_ARN=$(echo "$AGENT_IDENTITY" | jq -r '.Arn' 2>/dev/null)
if echo "$AGENT_CALLER_ARN" | grep -q ":user/"; then
    CALLER_NAME=$(echo "$AGENT_CALLER_ARN" | sed 's/.*:user\///')
    aws iam delete-user-policy --user-name "$CALLER_NAME" --policy-name AllowAssumeKBAccessRole \
      --profile "$AGENT_PROFILE" 2>/dev/null && echo "  Removed inline policy from user/$CALLER_NAME" \
      || echo "  Inline policy may not exist on user/$CALLER_NAME"
elif echo "$AGENT_CALLER_ARN" | grep -q ":role/"; then
    CALLER_NAME=$(echo "$AGENT_CALLER_ARN" | sed 's/.*:role\///' | sed 's/\/.*//')
    aws iam delete-role-policy --role-name "$CALLER_NAME" --policy-name AllowAssumeKBAccessRole \
      --profile "$AGENT_PROFILE" 2>/dev/null && echo "  Removed inline policy from role/$CALLER_NAME" \
      || echo "  Inline policy may not exist on role/$CALLER_NAME"
fi

# Step 1: Detach and delete AgentCore policy + role in agent account
echo "Step 1: Cleaning up AgentCore role in agent account..."

AGENTCORE_POLICY_ARN="arn:aws:iam::${AGENT_ACCOUNT_NUMBER}:policy/${AGENTCORE_POLICY_NAME}"

aws iam detach-role-policy \
  --role-name "$AGENTCORE_ROLE_NAME" \
  --policy-arn "$AGENTCORE_POLICY_ARN" \
  --profile "$AGENT_PROFILE" 2>/dev/null || echo "  AgentCore policy may not be attached"

if aws iam get-policy --policy-arn "$AGENTCORE_POLICY_ARN" --profile "$AGENT_PROFILE" >/dev/null 2>&1; then
    delete_iam_policy_with_versions "$AGENTCORE_POLICY_ARN" "$AGENT_PROFILE"
    if aws iam get-policy --policy-arn "$AGENTCORE_POLICY_ARN" --profile "$AGENT_PROFILE" >/dev/null 2>&1; then
        echo "  Warning: AgentCore policy still exists after delete attempt: $AGENTCORE_POLICY_ARN"
    else
        echo "  Deleted AgentCore policy: $AGENTCORE_POLICY_ARN"
    fi
else
    echo "  AgentCore policy does not exist"
fi

if aws iam get-role --role-name "$AGENTCORE_ROLE_NAME" --profile "$AGENT_PROFILE" >/dev/null 2>&1; then
    aws iam delete-role --role-name "$AGENTCORE_ROLE_NAME" --profile "$AGENT_PROFILE" 2>/dev/null
    echo "  Deleted AgentCore role: $AGENTCORE_ROLE_NAME"
else
    echo "  AgentCore role does not exist"
fi

# Step 2: Detach and delete KB access policy + role in agent-kb account
echo "Step 2: Cleaning up KB access role in agent-kb account..."

KB_ACCESS_POLICY_ARN="arn:aws:iam::${AGENT_KB_ACCOUNT_NUMBER}:policy/${KB_ACCESS_POLICY_NAME}"

aws iam detach-role-policy \
  --role-name "$KB_ACCESS_ROLE_NAME" \
  --policy-arn "$KB_ACCESS_POLICY_ARN" \
  --profile "$AGENT_KB_PROFILE" 2>/dev/null || echo "  KB access policy may not be attached"

if aws iam get-policy --policy-arn "$KB_ACCESS_POLICY_ARN" --profile "$AGENT_KB_PROFILE" >/dev/null 2>&1; then
    delete_iam_policy_with_versions "$KB_ACCESS_POLICY_ARN" "$AGENT_KB_PROFILE"
    if aws iam get-policy --policy-arn "$KB_ACCESS_POLICY_ARN" --profile "$AGENT_KB_PROFILE" >/dev/null 2>&1; then
        echo "  Warning: KB access policy still exists after delete attempt: $KB_ACCESS_POLICY_ARN"
    else
        echo "  Deleted KB access policy: $KB_ACCESS_POLICY_ARN"
    fi
else
    echo "  KB access policy does not exist"
fi

if aws iam get-role --role-name "$KB_ACCESS_ROLE_NAME" --profile "$AGENT_KB_PROFILE" >/dev/null 2>&1; then
    aws iam delete-role --role-name "$KB_ACCESS_ROLE_NAME" --profile "$AGENT_KB_PROFILE" 2>/dev/null
    echo "  Deleted KB access role: $KB_ACCESS_ROLE_NAME"
else
    echo "  KB access role does not exist"
fi

echo ""
echo "=========================================="
echo "Deletion process completed!"
echo "=========================================="
echo ""
echo "Also remember to destroy the AgentCore deployment:"
echo "  agentcore destroy --agent <agent-name> --force"

#!/bin/bash

# All-in-one cleanup script for Strands Agent + AgentCore + cross-account IAM resources.
#
# This script performs a complete teardown:
#   1. Destroys the AgentCore deployment (agent runtime)
#   2. Removes inline sts:AssumeRole policy from the local IAM caller
#   3. Detaches and deletes the AgentCore execution role + policy (agent account)
#   4. Detaches and deletes the KB access role + policy (agent-kb account)
#
# Usage: ./cleanup_all.sh [options]

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AGENT_PROJECT_DIR="$(cd "$SCRIPT_DIR/../strands_agent" && pwd)"

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
    echo ""
    echo "Optional Parameters:"
    echo "  --agent-name <name>               AgentCore agent name (default: strands_kb_query_agent)"
    echo "  --skip-agentcore-destroy          Skip AgentCore destroy step (IAM only)"
    echo "  --yes                             Skip confirmation prompt"
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
    exit 1
}

# Defaults
AGENT_NAME="strands_kb_query_agent"
SKIP_AGENTCORE_DESTROY=false
AUTO_CONFIRM=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --agent-profile)       AGENT_PROFILE="$2";          shift 2 ;;
        --agent-kb-profile)    AGENT_KB_PROFILE="$2";       shift 2 ;;
        --agentcore-role)      AGENTCORE_ROLE_NAME="$2";    shift 2 ;;
        --kb-access-role)      KB_ACCESS_ROLE_NAME="$2";    shift 2 ;;
        --kb-access-policy)    KB_ACCESS_POLICY_NAME="$2";  shift 2 ;;
        --agentcore-policy)    AGENTCORE_POLICY_NAME="$2";  shift 2 ;;
        --agent-account)       AGENT_ACCOUNT_NUMBER="$2";   shift 2 ;;
        --agent-kb-account)    AGENT_KB_ACCOUNT_NUMBER="$2"; shift 2 ;;
        --agent-name)          AGENT_NAME="$2";             shift 2 ;;
        --skip-agentcore-destroy) SKIP_AGENTCORE_DESTROY=true; shift ;;
        --yes)                 AUTO_CONFIRM=true;            shift ;;
        --help)                usage ;;
        *)                     echo "Error: Unknown parameter $1"; usage ;;
    esac
done

# Validate required parameters
MISSING_PARAMS=()
[[ -z "$AGENT_PROFILE" ]]          && MISSING_PARAMS+=("--agent-profile")
[[ -z "$AGENT_KB_PROFILE" ]]       && MISSING_PARAMS+=("--agent-kb-profile")
[[ -z "$AGENTCORE_ROLE_NAME" ]]    && MISSING_PARAMS+=("--agentcore-role")
[[ -z "$KB_ACCESS_ROLE_NAME" ]]    && MISSING_PARAMS+=("--kb-access-role")
[[ -z "$KB_ACCESS_POLICY_NAME" ]]  && MISSING_PARAMS+=("--kb-access-policy")
[[ -z "$AGENTCORE_POLICY_NAME" ]]  && MISSING_PARAMS+=("--agentcore-policy")
[[ -z "$AGENT_ACCOUNT_NUMBER" ]]   && MISSING_PARAMS+=("--agent-account")
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
echo "FULL CLEANUP: AgentCore + IAM Resources"
echo "=========================================="
echo ""
echo "AgentCore Agent:  $AGENT_NAME"
echo "AgentCore Role:   $AGENTCORE_ROLE_NAME (account: $AGENT_ACCOUNT_NUMBER)"
echo "AgentCore Policy: $AGENTCORE_POLICY_NAME"
echo "KB Access Role:   $KB_ACCESS_ROLE_NAME (account: $AGENT_KB_ACCOUNT_NUMBER)"
echo "KB Access Policy: $KB_ACCESS_POLICY_NAME"
echo ""
echo "WARNING: This will permanently delete the above resources!"
echo ""

if [[ "$AUTO_CONFIRM" != "true" ]]; then
    read -p "Are you sure you want to continue? (yes/no): " CONFIRM
    if [[ "$CONFIRM" != "yes" ]]; then echo "Operation cancelled."; exit 0; fi
fi

# =====================================================================
# Validate AWS CLI profiles
# =====================================================================
echo ""
echo "Validating AWS CLI profiles..."

AGENT_IDENTITY=$(aws sts get-caller-identity --profile "$AGENT_PROFILE" 2>&1)
if [ $? -ne 0 ]; then echo "Failed to validate agent profile. Error: $AGENT_IDENTITY"; exit 1; fi
AGENT_ACTUAL_ACCOUNT=$(echo "$AGENT_IDENTITY" | jq -r '.Account' 2>/dev/null)
if [[ "$AGENT_ACTUAL_ACCOUNT" != "$AGENT_ACCOUNT_NUMBER" ]]; then
    echo "Agent profile account mismatch! Expected: $AGENT_ACCOUNT_NUMBER  Actual: $AGENT_ACTUAL_ACCOUNT"; exit 1
fi
echo "  Agent profile validated: $AGENT_ACTUAL_ACCOUNT"

AGENT_KB_IDENTITY=$(aws sts get-caller-identity --profile "$AGENT_KB_PROFILE" 2>&1)
if [ $? -ne 0 ]; then echo "Failed to validate agent-kb profile. Error: $AGENT_KB_IDENTITY"; exit 1; fi
AGENT_KB_ACTUAL_ACCOUNT=$(echo "$AGENT_KB_IDENTITY" | jq -r '.Account' 2>/dev/null)
if [[ "$AGENT_KB_ACTUAL_ACCOUNT" != "$AGENT_KB_ACCOUNT_NUMBER" ]]; then
    echo "Agent-KB profile account mismatch! Expected: $AGENT_KB_ACCOUNT_NUMBER  Actual: $AGENT_KB_ACTUAL_ACCOUNT"; exit 1
fi
echo "  Agent-KB profile validated: $AGENT_KB_ACTUAL_ACCOUNT"

echo ""
echo "Profiles validated. Starting cleanup..."
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

# Track what was cleaned up for summary
DESTROYED_AGENTCORE=false
DELETED_INLINE_POLICY=false
DELETED_AGENTCORE_POLICY=false
DELETED_AGENTCORE_ROLE=false
DELETED_KB_POLICY=false
DELETED_KB_ROLE=false

# =====================================================================
# Step 1: Destroy AgentCore deployment
# =====================================================================
if [[ "$SKIP_AGENTCORE_DESTROY" == "true" ]]; then
    echo "Step 1: SKIPPED (--skip-agentcore-destroy)"
else
    echo "Step 1: Destroying AgentCore deployment '$AGENT_NAME'..."

    if ! command -v agentcore &>/dev/null; then
        echo "  Error: the Python 'agentcore' CLI was not found."
        echo "  Activate the Variant 1 virtual environment or install:"
        echo "    pip3 install 'bedrock-agentcore>=1.7.0'"
        echo "  Use --skip-agentcore-destroy only if the runtime is already gone."
        exit 1
    fi
    # Avoid grep -q here: with pipefail, its early exit can SIGPIPE the CLI and
    # make a valid Python command look like the Node CLI.
    if ! agentcore destroy --help 2>&1 | grep -- "--agent" >/dev/null; then
        echo "  Error: the selected 'agentcore' is not the Python Variant 1 CLI."
        echo "  Activate the Variant 1 virtual environment before cleanup."
        echo "  Refusing to delete shared IAM while the runtime may still exist."
        exit 1
    fi
    if [[ ! -f "$AGENT_PROJECT_DIR/.bedrock_agentcore.yaml" ]]; then
        echo "  Error: $AGENT_PROJECT_DIR/.bedrock_agentcore.yaml was not found."
        echo "  Refusing to delete shared IAM while the runtime may still exist."
        exit 1
    fi

    echo "  Using AWS_PROFILE=$AGENT_PROFILE for agentcore destroy..."
    if (
        cd "$AGENT_PROJECT_DIR" &&
        AWS_PROFILE="$AGENT_PROFILE" agentcore destroy \
            --agent "$AGENT_NAME" --force 2>&1
    ); then
        echo "  AgentCore agent '$AGENT_NAME' destroyed"
        DESTROYED_AGENTCORE=true
    else
        echo "  Error: agentcore destroy failed."
        echo "  Shared IAM cleanup has not started."
        echo "  Resolve the runtime error, or rerun with --skip-agentcore-destroy"
        echo "  only after confirming the runtime no longer exists."
        exit 1
    fi
fi
echo ""

# =====================================================================
# Step 2: Remove inline sts:AssumeRole policy from calling IAM principal
# =====================================================================
echo "Step 2: Removing local-testing inline policy from agent account caller..."

AGENT_CALLER_ARN=$(echo "$AGENT_IDENTITY" | jq -r '.Arn' 2>/dev/null)
INLINE_POLICY_NAME="AllowAssumeKBAccessRole"

if echo "$AGENT_CALLER_ARN" | grep -q ":user/"; then
    CALLER_NAME=$(echo "$AGENT_CALLER_ARN" | sed 's/.*:user\///')
    echo "  Detected caller: user/$CALLER_NAME"
    aws iam delete-user-policy --user-name "$CALLER_NAME" --policy-name "$INLINE_POLICY_NAME" \
      --profile "$AGENT_PROFILE" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "  Removed inline policy '$INLINE_POLICY_NAME' from user/$CALLER_NAME"
        DELETED_INLINE_POLICY=true
    else
        echo "  Inline policy may not exist on user/$CALLER_NAME (OK)"
    fi
elif echo "$AGENT_CALLER_ARN" | grep -q ":role/"; then
    CALLER_NAME=$(echo "$AGENT_CALLER_ARN" | sed 's/.*:role\///' | sed 's/\/.*//')
    echo "  Detected caller: role/$CALLER_NAME"
    aws iam delete-role-policy --role-name "$CALLER_NAME" --policy-name "$INLINE_POLICY_NAME" \
      --profile "$AGENT_PROFILE" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "  Removed inline policy '$INLINE_POLICY_NAME' from role/$CALLER_NAME"
        DELETED_INLINE_POLICY=true
    else
        echo "  Inline policy may not exist on role/$CALLER_NAME (OK)"
    fi
else
    echo "  Could not detect caller type from ARN: $AGENT_CALLER_ARN"
    echo "  You may need to remove the '$INLINE_POLICY_NAME' inline policy manually."
fi
echo ""

# =====================================================================
# Step 3: Detach and delete AgentCore policy + role in agent account
# =====================================================================
echo "Step 3: Cleaning up AgentCore role and policy in agent account..."

AGENTCORE_POLICY_ARN="arn:aws:iam::${AGENT_ACCOUNT_NUMBER}:policy/${AGENTCORE_POLICY_NAME}"

# Detach policy from role
aws iam detach-role-policy \
  --role-name "$AGENTCORE_ROLE_NAME" \
  --policy-arn "$AGENTCORE_POLICY_ARN" \
  --profile "$AGENT_PROFILE" 2>/dev/null && echo "  Detached policy from role" \
  || echo "  Policy may not be attached to role (OK)"

# Delete the policy
if aws iam get-policy --policy-arn "$AGENTCORE_POLICY_ARN" --profile "$AGENT_PROFILE" >/dev/null 2>&1; then
    delete_iam_policy_with_versions "$AGENTCORE_POLICY_ARN" "$AGENT_PROFILE"
    if aws iam get-policy --policy-arn "$AGENTCORE_POLICY_ARN" --profile "$AGENT_PROFILE" >/dev/null 2>&1; then
        echo "  Warning: AgentCore policy still exists after delete attempt. Check for remaining attachments."
    else
        echo "  Deleted AgentCore policy: $AGENTCORE_POLICY_NAME"
        DELETED_AGENTCORE_POLICY=true
    fi
else
    echo "  AgentCore policy does not exist (OK)"
fi

# Delete the role
if aws iam get-role --role-name "$AGENTCORE_ROLE_NAME" --profile "$AGENT_PROFILE" >/dev/null 2>&1; then
    aws iam delete-role --role-name "$AGENTCORE_ROLE_NAME" --profile "$AGENT_PROFILE" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "  Deleted AgentCore role: $AGENTCORE_ROLE_NAME"
        DELETED_AGENTCORE_ROLE=true
    else
        echo "  Warning: Could not delete AgentCore role. Check for remaining attached policies."
    fi
else
    echo "  AgentCore role does not exist (OK)"
fi
echo ""

# =====================================================================
# Step 4: Detach and delete KB access policy + role in agent-kb account
# =====================================================================
echo "Step 4: Cleaning up KB access role and policy in agent-kb account..."

KB_ACCESS_POLICY_ARN="arn:aws:iam::${AGENT_KB_ACCOUNT_NUMBER}:policy/${KB_ACCESS_POLICY_NAME}"

# Detach policy from role
aws iam detach-role-policy \
  --role-name "$KB_ACCESS_ROLE_NAME" \
  --policy-arn "$KB_ACCESS_POLICY_ARN" \
  --profile "$AGENT_KB_PROFILE" 2>/dev/null && echo "  Detached policy from role" \
  || echo "  Policy may not be attached to role (OK)"

# Delete the policy
if aws iam get-policy --policy-arn "$KB_ACCESS_POLICY_ARN" --profile "$AGENT_KB_PROFILE" >/dev/null 2>&1; then
    delete_iam_policy_with_versions "$KB_ACCESS_POLICY_ARN" "$AGENT_KB_PROFILE"
    if aws iam get-policy --policy-arn "$KB_ACCESS_POLICY_ARN" --profile "$AGENT_KB_PROFILE" >/dev/null 2>&1; then
        echo "  Warning: KB access policy still exists after delete attempt. Check for remaining attachments."
    else
        echo "  Deleted KB access policy: $KB_ACCESS_POLICY_NAME"
        DELETED_KB_POLICY=true
    fi
else
    echo "  KB access policy does not exist (OK)"
fi

# Delete the role
if aws iam get-role --role-name "$KB_ACCESS_ROLE_NAME" --profile "$AGENT_KB_PROFILE" >/dev/null 2>&1; then
    aws iam delete-role --role-name "$KB_ACCESS_ROLE_NAME" --profile "$AGENT_KB_PROFILE" 2>/dev/null
    if [ $? -eq 0 ]; then
        echo "  Deleted KB access role: $KB_ACCESS_ROLE_NAME"
        DELETED_KB_ROLE=true
    else
        echo "  Warning: Could not delete KB access role. Check for remaining attached policies."
    fi
else
    echo "  KB access role does not exist (OK)"
fi

# =====================================================================
# Summary
# =====================================================================
echo ""
echo "=========================================="
echo "CLEANUP SUMMARY"
echo "=========================================="
echo ""
echo "AgentCore Deployment:"
if [[ "$SKIP_AGENTCORE_DESTROY" == "true" ]]; then
    echo "  Agent '$AGENT_NAME':        SKIPPED"
elif [[ "$DESTROYED_AGENTCORE" == "true" ]]; then
    echo "  Agent '$AGENT_NAME':        DESTROYED"
else
    echo "  Agent '$AGENT_NAME':        NOT FOUND / ALREADY DESTROYED"
fi
echo ""
echo "Agent Account ($AGENT_ACCOUNT_NUMBER):"
if [[ "$DELETED_INLINE_POLICY" == "true" ]]; then
    echo "  Inline policy:              DELETED"
else
    echo "  Inline policy:              NOT FOUND (OK)"
fi
if aws iam get-policy --policy-arn "$AGENTCORE_POLICY_ARN" --profile "$AGENT_PROFILE" >/dev/null 2>&1; then
    echo "  $AGENTCORE_POLICY_NAME: STILL EXISTS — DELETE FAILED"
elif [[ "$DELETED_AGENTCORE_POLICY" == "true" ]]; then
    echo "  $AGENTCORE_POLICY_NAME: DELETED"
else
    echo "  $AGENTCORE_POLICY_NAME: NOT FOUND (OK)"
fi
if aws iam get-role --role-name "$AGENTCORE_ROLE_NAME" --profile "$AGENT_PROFILE" >/dev/null 2>&1; then
    echo "  $AGENTCORE_ROLE_NAME: STILL EXISTS — DELETE FAILED"
elif [[ "$DELETED_AGENTCORE_ROLE" == "true" ]]; then
    echo "  $AGENTCORE_ROLE_NAME: DELETED"
else
    echo "  $AGENTCORE_ROLE_NAME: NOT FOUND (OK)"
fi
echo ""
echo "Agent-KB Account ($AGENT_KB_ACCOUNT_NUMBER):"
if aws iam get-policy --policy-arn "$KB_ACCESS_POLICY_ARN" --profile "$AGENT_KB_PROFILE" >/dev/null 2>&1; then
    echo "  $KB_ACCESS_POLICY_NAME:  STILL EXISTS — DELETE FAILED"
elif [[ "$DELETED_KB_POLICY" == "true" ]]; then
    echo "  $KB_ACCESS_POLICY_NAME:  DELETED"
else
    echo "  $KB_ACCESS_POLICY_NAME:  NOT FOUND (OK)"
fi
if aws iam get-role --role-name "$KB_ACCESS_ROLE_NAME" --profile "$AGENT_KB_PROFILE" >/dev/null 2>&1; then
    echo "  $KB_ACCESS_ROLE_NAME:    STILL EXISTS — DELETE FAILED"
elif [[ "$DELETED_KB_ROLE" == "true" ]]; then
    echo "  $KB_ACCESS_ROLE_NAME:    DELETED"
else
    echo "  $KB_ACCESS_ROLE_NAME:    NOT FOUND (OK)"
fi
echo ""
echo "=========================================="
echo "Cleanup completed!"
echo "=========================================="
echo ""
echo "REMAINING MANUAL STEPS:"
echo "  - Delete the Redshift Serverless workgroup (agent-kb account console)"
echo "  - Delete the Bedrock Knowledge Base (agent-kb account console)"

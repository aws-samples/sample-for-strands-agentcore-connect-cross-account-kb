#!/bin/bash

# Cleanup script for the AgentCore HARNESS VARIANT (harness_variant/strandskbharness).
#
# The harness variant is a declarative AgentCore project deployed as a single CDK
# CloudFormation stack (default: AgentCore-strandskbharness-default) containing the
# harness, its memory, the Gateway, and the in-repo Lambda tool. This script:
#   1. Tears down that CloudFormation stack (harness + gateway + Lambda + memory).
#   2. Reverts the cross-account trust statement added to the KB access role
#      (the "AllowHarnessLambdaRole" Sid in the agent-kb account).
#
# It does NOT touch the code-based strands_kb_query_agent runtime or the shared
# bedrock_kb_access_role's other trust statements. Use scripts/cleanup_all.sh
# for the code-based deployment after cleaning up this Harness stack.
#
# Usage: ./cleanup_harness_variant.sh [options]

set -o pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEPLOYED_STATE_FILE="$SCRIPT_DIR/../harness_variant/strandskbharness/agentcore/.cli/deployed-state.json"

usage() {
    echo "Usage: $0 [options]"
    echo ""
    echo "Required Parameters:"
    echo "  --agent-profile <profile>      AWS CLI profile for agent account"
    echo "  --agent-kb-profile <profile>   AWS CLI profile for agent-kb account"
    echo "  --agent-account <number>       12-digit AWS account number for agent"
    echo "  --agent-kb-account <number>    12-digit AWS account number for agent-kb"
    echo ""
    echo "Optional Parameters:"
    echo "  --stack-name <name>            CloudFormation stack to delete"
    echo "                                 (default: AgentCore-strandskbharness-default)"
    echo "  --kb-access-role <name>        KB access role to revert trust on"
    echo "                                 (default: bedrock_kb_access_role)"
    echo "  --trust-sid <sid>              Trust statement Sid to remove"
    echo "                                 (default: AllowHarnessLambdaRole)"
    echo "  --region <region>              AWS region (default: us-west-2)"
    echo "  --skip-stack-delete            Skip CloudFormation stack deletion (trust revert only)"
    echo "  --skip-trust-revert            Skip KB trust revert (stack delete only)"
    echo "  --yes                          Skip confirmation prompt"
    echo "  --help                         Show this help message"
    echo ""
    echo "Example:"
    echo "  $0 --agent-profile agent \\"
    echo "     --agent-kb-profile agent-kb \\"
    echo "     --agent-account 111122223333 \\"
    echo "     --agent-kb-account 999999999999"
    exit 1
}

# Defaults
STACK_NAME="AgentCore-strandskbharness-default"
KB_ACCESS_ROLE_NAME="bedrock_kb_access_role"
TRUST_SID="AllowHarnessLambdaRole"
REGION="us-west-2"
SKIP_STACK_DELETE=false
SKIP_TRUST_REVERT=false
AUTO_CONFIRM=false

# Parse arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --agent-profile)     AGENT_PROFILE="$2";           shift 2 ;;
        --agent-kb-profile)  AGENT_KB_PROFILE="$2";        shift 2 ;;
        --agent-account)     AGENT_ACCOUNT_NUMBER="$2";    shift 2 ;;
        --agent-kb-account)  AGENT_KB_ACCOUNT_NUMBER="$2"; shift 2 ;;
        --stack-name)        STACK_NAME="$2";              shift 2 ;;
        --kb-access-role)    KB_ACCESS_ROLE_NAME="$2";     shift 2 ;;
        --trust-sid)         TRUST_SID="$2";               shift 2 ;;
        --region)            REGION="$2";                  shift 2 ;;
        --skip-stack-delete) SKIP_STACK_DELETE=true;       shift ;;
        --skip-trust-revert) SKIP_TRUST_REVERT=true;       shift ;;
        --yes)               AUTO_CONFIRM=true;            shift ;;
        --help)              usage ;;
        *)                   echo "Error: Unknown parameter $1"; usage ;;
    esac
done

# Validate required parameters
MISSING_PARAMS=()
[[ -z "$AGENT_PROFILE" ]]           && MISSING_PARAMS+=("--agent-profile")
[[ -z "$AGENT_KB_PROFILE" ]]        && MISSING_PARAMS+=("--agent-kb-profile")
[[ -z "$AGENT_ACCOUNT_NUMBER" ]]    && MISSING_PARAMS+=("--agent-account")
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
echo "HARNESS VARIANT CLEANUP"
echo "=========================================="
echo ""
echo "CloudFormation Stack: $STACK_NAME (account: $AGENT_ACCOUNT_NUMBER, region: $REGION)"
echo "KB Access Role:       $KB_ACCESS_ROLE_NAME (account: $AGENT_KB_ACCOUNT_NUMBER)"
echo "Trust Sid to remove:  $TRUST_SID"
echo ""
echo "WARNING: This deletes the harness stack (harness, gateway, Lambda, memory)"
echo "         and removes the '$TRUST_SID' trust statement from the KB access role."
echo "         The original agent.py deployment is NOT affected."
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

DELETED_STACK=false
STACK_ABSENT=false
REVERTED_TRUST=false

# =====================================================================
# Step 1: Delete the harness CloudFormation stack
# =====================================================================
if [[ "$SKIP_STACK_DELETE" == "true" ]]; then
    echo "Step 1: SKIPPED (--skip-stack-delete)"
else
    echo "Step 1: Deleting CloudFormation stack '$STACK_NAME'..."

    if aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
         --region "$REGION" --profile "$AGENT_PROFILE" >/dev/null 2>&1; then
        aws cloudformation delete-stack --stack-name "$STACK_NAME" \
          --region "$REGION" --profile "$AGENT_PROFILE" 2>&1
        echo "  Delete initiated. Waiting for stack deletion to complete..."
        aws cloudformation wait stack-delete-complete --stack-name "$STACK_NAME" \
          --region "$REGION" --profile "$AGENT_PROFILE" 2>&1
        if aws cloudformation describe-stacks --stack-name "$STACK_NAME" \
             --region "$REGION" --profile "$AGENT_PROFILE" >/dev/null 2>&1; then
            echo "  Warning: stack still exists after delete. Check the CloudFormation console."
        else
            echo "  Stack '$STACK_NAME' deleted."
            DELETED_STACK=true
            STACK_ABSENT=true
        fi
    else
        echo "  Stack '$STACK_NAME' does not exist (OK)"
        STACK_ABSENT=true
    fi
fi
echo ""

if [[ "$STACK_ABSENT" == "true" && -f "$DEPLOYED_STATE_FILE" ]]; then
    rm -f "$DEPLOYED_STATE_FILE"
    echo "  Removed stale local deployment state: $DEPLOYED_STATE_FILE"
    echo ""
fi

# =====================================================================
# Step 2: Revert the cross-account trust statement on the KB access role
# =====================================================================
if [[ "$SKIP_TRUST_REVERT" == "true" ]]; then
    echo "Step 2: SKIPPED (--skip-trust-revert)"
else
    echo "Step 2: Removing '$TRUST_SID' trust statement from '$KB_ACCESS_ROLE_NAME'..."

    if aws iam get-role --role-name "$KB_ACCESS_ROLE_NAME" --profile "$AGENT_KB_PROFILE" >/dev/null 2>&1; then
        CURRENT_TRUST=$(aws iam get-role --role-name "$KB_ACCESS_ROLE_NAME" \
          --profile "$AGENT_KB_PROFILE" --query 'Role.AssumeRolePolicyDocument' --output json 2>/dev/null)

        if echo "$CURRENT_TRUST" | jq -e --arg sid "$TRUST_SID" \
             '.Statement[] | select(.Sid == $sid)' >/dev/null 2>&1; then
            UPDATED_TRUST=$(echo "$CURRENT_TRUST" | jq --arg sid "$TRUST_SID" \
              '.Statement |= map(select(.Sid != $sid))')
            TRUST_FILE=$(mktemp)
            echo "$UPDATED_TRUST" > "$TRUST_FILE"
            aws iam update-assume-role-policy \
              --role-name "$KB_ACCESS_ROLE_NAME" \
              --policy-document "file://$TRUST_FILE" \
              --profile "$AGENT_KB_PROFILE" 2>/dev/null
            if [ $? -eq 0 ]; then
                echo "  Removed '$TRUST_SID' statement. Remaining statements:"
                aws iam get-role --role-name "$KB_ACCESS_ROLE_NAME" --profile "$AGENT_KB_PROFILE" \
                  --query 'Role.AssumeRolePolicyDocument.Statement[].Sid' --output text 2>/dev/null \
                  | tr '\t' '\n' | sed 's/^/    - /'
                REVERTED_TRUST=true
            else
                echo "  Warning: failed to update trust policy. Revert it manually."
            fi
            rm -f "$TRUST_FILE"
        else
            echo "  Trust statement '$TRUST_SID' not present (OK)"
        fi
    else
        echo "  KB access role '$KB_ACCESS_ROLE_NAME' does not exist (OK)"
    fi
fi

# =====================================================================
# Summary
# =====================================================================
echo ""
echo "=========================================="
echo "HARNESS CLEANUP SUMMARY"
echo "=========================================="
echo ""
if [[ "$SKIP_STACK_DELETE" == "true" ]]; then
    echo "  Stack '$STACK_NAME':  SKIPPED"
elif [[ "$DELETED_STACK" == "true" ]]; then
    echo "  Stack '$STACK_NAME':  DELETED"
else
    echo "  Stack '$STACK_NAME':  NOT FOUND / ALREADY DELETED"
fi
if [[ "$SKIP_TRUST_REVERT" == "true" ]]; then
    echo "  KB trust '$TRUST_SID':  SKIPPED"
elif [[ "$REVERTED_TRUST" == "true" ]]; then
    echo "  KB trust '$TRUST_SID':  REMOVED"
else
    echo "  KB trust '$TRUST_SID':  NOT FOUND (OK)"
fi
echo ""
echo "NOTE: The harness's own memory resource is part of the deleted stack and is"
echo "      removed with it. CloudWatch log groups (/aws/lambda/strandskbharness-*"
echo "      and /aws/bedrock-agentcore/runtimes/*) are retained by default — delete"
echo "      them manually if no longer needed."
echo ""
echo "=========================================="
echo "Harness variant cleanup completed!"
echo "=========================================="

#!/bin/bash

# Script to create IAM roles and policies for Strands Agent + AgentCore
# cross-account knowledge base access.
#
# This replaces the Lambda-based approach. Instead of a Lambda execution role,
# it creates an AgentCore execution role in the agent account that can assume
# a KB access role in the agent-kb account.
#
# Usage: ./create_strands_agentcore_roles_policies.sh [options]

set -o pipefail
set -o nounset

AGENT_PROFILE=""
AGENT_KB_PROFILE=""
AGENTCORE_ROLE_NAME=""
KB_ACCESS_ROLE_NAME=""
KB_ACCESS_POLICY_NAME=""
AGENTCORE_POLICY_NAME=""
KNOWLEDGE_BASE_ID=""
AGENT_ACCOUNT_NUMBER=""
AGENT_KB_ACCOUNT_NUMBER=""
TEMP_FILES=()

cleanup_temp_files() {
    for temp_file in "${TEMP_FILES[@]-}"; do
        [[ -n "$temp_file" ]] && rm -f "$temp_file"
    done
    return 0
}
trap cleanup_temp_files EXIT

update_managed_policy() {
    local policy_arn="$1"
    local policy_document="$2"
    local profile="$3"
    local label="$4"
    local non_default_versions

    non_default_versions=$(aws iam list-policy-versions \
        --policy-arn "$policy_arn" \
        --profile "$profile" \
        --query 'Versions[?!IsDefaultVersion].VersionId' \
        --output text 2>&1)
    if [ $? -ne 0 ]; then
        echo "  Failed to list versions for $label. Error: $non_default_versions"
        return 1
    fi

    for version_id in $non_default_versions; do
        if ! aws iam delete-policy-version \
            --policy-arn "$policy_arn" \
            --version-id "$version_id" \
            --profile "$profile" >/dev/null; then
            echo "  Failed to delete old version $version_id for $label"
            return 1
        fi
    done

    local version_output
    version_output=$(aws iam create-policy-version \
        --policy-arn "$policy_arn" \
        --policy-document "$policy_document" \
        --set-as-default \
        --profile "$profile" 2>&1)
    if [ $? -ne 0 ]; then
        echo "  Failed to update $label. Error: $version_output"
        return 1
    fi
    echo "  Updated $label to a new default policy version"
}

usage() {
    echo "Usage: $0 [Required Parameters]"
    echo ""
    echo "Required Parameters:"
    echo "  --agent-profile <profile>         AWS CLI profile for agent account"
    echo "  --agent-kb-profile <profile>      AWS CLI profile for agent-kb account"
    echo "  --agentcore-role <name>           Name for the AgentCore execution role"
    echo "  --kb-access-role <name>           Name for KB access role in agent-kb account"
    echo "  --kb-access-policy <name>         Name for KB access policy"
    echo "  --agentcore-policy <name>         Name for AgentCore STS policy"
    echo "  --knowledge-base-id <id>          Bedrock Knowledge Base ID"
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
    echo "     --knowledge-base-id YOUR_KB_ID \\"
    echo "     --agent-account 111122223333 \\"
    echo "     --agent-kb-account 999999999999"
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
        --knowledge-base-id)   KNOWLEDGE_BASE_ID="$2";   shift 2 ;;
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
[[ -z "$KNOWLEDGE_BASE_ID" ]]   && MISSING_PARAMS+=("--knowledge-base-id")
[[ -z "$AGENT_ACCOUNT_NUMBER" ]] && MISSING_PARAMS+=("--agent-account")
[[ -z "$AGENT_KB_ACCOUNT_NUMBER" ]] && MISSING_PARAMS+=("--agent-kb-account")

if [[ ${#MISSING_PARAMS[@]} -gt 0 ]]; then
    echo "Error: Missing required parameters:"
    for param in "${MISSING_PARAMS[@]}"; do echo "  $param"; done
    echo ""; usage
fi

# Validate account number format
if [[ ! "$AGENT_ACCOUNT_NUMBER" =~ ^[0-9]{12}$ ]]; then
    echo "Error: --agent-account must be a 12-digit AWS account number"; exit 1
fi
if [[ ! "$AGENT_KB_ACCOUNT_NUMBER" =~ ^[0-9]{12}$ ]]; then
    echo "Error: --agent-kb-account must be a 12-digit AWS account number"; exit 1
fi

for command_name in aws jq uuidgen; do
    if ! command -v "$command_name" >/dev/null; then
        echo "Error: required command '$command_name' was not found"; exit 1
    fi
done

echo "=========================================="
echo "Creating Strands AgentCore Cross-Account Roles"
echo "=========================================="
echo "Agent Profile:       $AGENT_PROFILE"
echo "Agent-KB Profile:    $AGENT_KB_PROFILE"
echo "AgentCore Role:      $AGENTCORE_ROLE_NAME"
echo "KB Access Role:      $KB_ACCESS_ROLE_NAME"
echo "KB Access Policy:    $KB_ACCESS_POLICY_NAME"
echo "AgentCore Policy:    $AGENTCORE_POLICY_NAME"
echo "Knowledge Base ID:   $KNOWLEDGE_BASE_ID"
echo "Agent Account:       $AGENT_ACCOUNT_NUMBER"
echo "Agent-KB Account:    $AGENT_KB_ACCOUNT_NUMBER"
echo "=========================================="

# ---------- Validate AWS CLI profiles ----------
echo "Validating AWS CLI profiles..."

AGENT_IDENTITY=$(aws sts get-caller-identity --profile "$AGENT_PROFILE" 2>&1)
if [ $? -ne 0 ]; then
    echo "Failed to validate agent profile '$AGENT_PROFILE'. Error:"; echo "$AGENT_IDENTITY"; exit 1
fi
AGENT_ACTUAL_ACCOUNT=$(echo "$AGENT_IDENTITY" | jq -r '.Account' 2>/dev/null)
if [[ "$AGENT_ACTUAL_ACCOUNT" != "$AGENT_ACCOUNT_NUMBER" ]]; then
    echo "Agent profile account mismatch! Expected: $AGENT_ACCOUNT_NUMBER  Actual: $AGENT_ACTUAL_ACCOUNT"; exit 1
fi
echo "Agent profile validated: $AGENT_ACTUAL_ACCOUNT"

AGENT_KB_IDENTITY=$(aws sts get-caller-identity --profile "$AGENT_KB_PROFILE" 2>&1)
if [ $? -ne 0 ]; then
    echo "Failed to validate agent-kb profile '$AGENT_KB_PROFILE'. Error:"; echo "$AGENT_KB_IDENTITY"; exit 1
fi
AGENT_KB_ACTUAL_ACCOUNT=$(echo "$AGENT_KB_IDENTITY" | jq -r '.Account' 2>/dev/null)
if [[ "$AGENT_KB_ACTUAL_ACCOUNT" != "$AGENT_KB_ACCOUNT_NUMBER" ]]; then
    echo "Agent-KB profile account mismatch! Expected: $AGENT_KB_ACCOUNT_NUMBER  Actual: $AGENT_KB_ACTUAL_ACCOUNT"; exit 1
fi
echo "Agent-KB profile validated: $AGENT_KB_ACTUAL_ACCOUNT"
echo ""

# =====================================================================
# Step 1: Create AgentCore execution role in agent account
# =====================================================================
echo "Step 1: Creating AgentCore execution role in agent account..."

if aws iam get-role --role-name "$AGENTCORE_ROLE_NAME" --profile "$AGENT_PROFILE" >/dev/null 2>&1; then
    echo "  AgentCore role already exists, getting existing ARN..."
    AGENTCORE_ROLE_ARN=$(aws iam get-role --role-name "$AGENTCORE_ROLE_NAME" --profile "$AGENT_PROFILE" --query 'Role.Arn' --output text)
else
    echo "  Creating new AgentCore execution role..."
    AGENTCORE_ROLE_ARN=$(aws iam create-role \
      --role-name "$AGENTCORE_ROLE_NAME" \
      --assume-role-policy-document '{
        "Version": "2012-10-17",
        "Statement": [
          {
            "Effect": "Allow",
            "Principal": {
              "Service": "bedrock-agentcore.amazonaws.com"
            },
            "Action": "sts:AssumeRole",
            "Condition": {
              "StringEquals": {
                "aws:SourceAccount": "'"$AGENT_ACCOUNT_NUMBER"'"
              }
            }
          }
        ]
      }' \
      --profile "$AGENT_PROFILE" \
      --query 'Role.Arn' \
      --output text 2>&1)

    if [ $? -ne 0 ]; then
        echo "  Failed to create AgentCore role. Error: $AGENTCORE_ROLE_ARN"; exit 1
    fi
fi
echo "  AgentCore role: $AGENTCORE_ROLE_ARN"

# =====================================================================
# Step 2: Create and attach AgentCore policy (sts:AssumeRole + Bedrock)
# =====================================================================
echo "Step 2: Creating AgentCore policy in agent account..."

AGENTCORE_POLICY_DOCUMENT=$(jq -n \
  --arg agent_account "$AGENT_ACCOUNT_NUMBER" \
  --arg kb_role_arn "arn:aws:iam::${AGENT_KB_ACCOUNT_NUMBER}:role/${KB_ACCESS_ROLE_NAME}" \
  '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Sid": "AllowAssumeKBRole",
        "Effect": "Allow",
        "Action": "sts:AssumeRole",
        "Resource": $kb_role_arn
      },
      {
        "Sid": "AllowBedrockInvoke",
        "Effect": "Allow",
        "Action": [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:GetInferenceProfile",
          "bedrock:GetFoundationModel"
        ],
        "Resource": [
          ("arn:aws:bedrock:*:" + $agent_account + ":inference-profile/*"),
          "arn:aws:bedrock:*::foundation-model/*"
        ]
      },
      {
        "Sid": "AllowCloudWatchLogs",
        "Effect": "Allow",
        "Action": [
          "logs:CreateLogGroup",
          "logs:CreateLogStream",
          "logs:PutLogEvents"
        ],
        "Resource": ("arn:aws:logs:*:" + $agent_account + ":log-group:/aws/bedrock-agentcore/*")
      },
      {
        "Sid": "AllowAgentCoreMemory",
        "Effect": "Allow",
        "Action": [
          "bedrock-agentcore:CreateEvent",
          "bedrock-agentcore:ListEvents",
          "bedrock-agentcore:GetEvent",
          "bedrock-agentcore:RetrieveMemories"
        ],
        "Resource": ("arn:aws:bedrock-agentcore:*:" + $agent_account + ":memory/*")
      }
    ]
  }')

EXISTING_AGENTCORE_POLICY_ARN=$(aws iam list-policies --scope Local \
  --query "Policies[?PolicyName=='$AGENTCORE_POLICY_NAME'].Arn" \
  --output text --profile "$AGENT_PROFILE" 2>/dev/null)

if [[ -n "$EXISTING_AGENTCORE_POLICY_ARN" ]]; then
    echo "  AgentCore policy already exists: $EXISTING_AGENTCORE_POLICY_ARN"
    AGENTCORE_POLICY_ARN="$EXISTING_AGENTCORE_POLICY_ARN"
    update_managed_policy \
        "$AGENTCORE_POLICY_ARN" \
        "$AGENTCORE_POLICY_DOCUMENT" \
        "$AGENT_PROFILE" \
        "AgentCore policy" || exit 1
else
    AGENTCORE_POLICY_ARN=$(aws iam create-policy \
      --policy-name "$AGENTCORE_POLICY_NAME" \
      --policy-document "$AGENTCORE_POLICY_DOCUMENT" \
      --profile "$AGENT_PROFILE" \
      --query 'Policy.Arn' \
      --output text 2>&1)

    if [ $? -ne 0 ]; then
        echo "  Failed to create AgentCore policy. Error: $AGENTCORE_POLICY_ARN"; exit 1
    fi
fi
echo "  AgentCore policy: $AGENTCORE_POLICY_ARN"

echo "  Attaching AgentCore policy to AgentCore role..."
if ! aws iam attach-role-policy \
  --role-name "$AGENTCORE_ROLE_NAME" \
  --policy-arn "$AGENTCORE_POLICY_ARN" \
  --profile "$AGENT_PROFILE"; then
    echo "  Failed to attach AgentCore policy to role"; exit 1
fi

# =====================================================================
# Step 3: Create KB access role in agent-kb account
# =====================================================================
echo "Step 3: Creating KB access role in agent-kb account..."

if aws iam get-role --role-name "$KB_ACCESS_ROLE_NAME" --profile "$AGENT_KB_PROFILE" >/dev/null 2>&1; then
    echo "  KB access role already exists, getting existing ARN..."
    KB_ACCESS_ROLE_ARN=$(aws iam get-role --role-name "$KB_ACCESS_ROLE_NAME" --profile "$AGENT_KB_PROFILE" --query 'Role.Arn' --output text)

    # Preserve unrelated statements, including the optional Harness Lambda trust.
    echo "  Updating required trust statements while preserving existing grants..."
    CURRENT_TRUST=$(aws iam get-role \
      --role-name "$KB_ACCESS_ROLE_NAME" \
      --profile "$AGENT_KB_PROFILE" \
      --query 'Role.AssumeRolePolicyDocument' \
      --output json 2>&1)
    if [ $? -ne 0 ]; then
        echo "  Failed to read existing trust policy. Error: $CURRENT_TRUST"; exit 1
    fi
    TRUST_POLICY_FILE=$(mktemp)
    TEMP_FILES+=("$TRUST_POLICY_FILE")
    echo "$CURRENT_TRUST" | jq \
      --arg agentcore_arn "$AGENTCORE_ROLE_ARN" \
      --arg agent_account_root "arn:aws:iam::${AGENT_ACCOUNT_NUMBER}:root" \
      'def scrub_stale_aws_principals:
        if ((.Principal.AWS? | type) == "string"
            and (.Principal.AWS | test("^AROA[A-Z0-9]+$"))) then
          del(.Principal.AWS)
        elif ((.Principal.AWS? | type) == "array") then
          (.Principal.AWS |= map(select(
            (type != "string") or (test("^AROA[A-Z0-9]+$") | not)
          )))
          | if .Principal.AWS == [] then del(.Principal.AWS) else . end
        else
          .
        end;
      .Statement = (
        [.Statement[]
          | select(
              .Sid != "AllowAgentCoreRole"
              and .Sid != "AllowAgentAccountLocalTesting"
            )
          | scrub_stale_aws_principals
          | select(
              (.Principal? | type) != "object"
              or (.Principal | length) > 0
            )
        ] + [
          {
            "Sid": "AllowAgentCoreRole",
            "Effect": "Allow",
            "Principal": { "AWS": $agentcore_arn },
            "Action": "sts:AssumeRole"
          },
          {
            "Sid": "AllowAgentAccountLocalTesting",
            "Effect": "Allow",
            "Principal": { "AWS": $agent_account_root },
            "Action": "sts:AssumeRole"
          }
        ]
      )' > "$TRUST_POLICY_FILE"

    if ! aws iam update-assume-role-policy \
      --role-name "$KB_ACCESS_ROLE_NAME" \
      --policy-document "file://$TRUST_POLICY_FILE" \
      --profile "$AGENT_KB_PROFILE"; then
        echo "  Failed to update KB role trust policy"; exit 1
    fi
    echo "  Trust policy updated successfully"
    rm -f "$TRUST_POLICY_FILE"
else
    echo "  Creating new KB access role..."
    echo "  Waiting 5 seconds for role propagation..."
    sleep 5

    TRUST_POLICY_FILE=$(mktemp)
    TEMP_FILES+=("$TRUST_POLICY_FILE")
    jq -n \
      --arg agentcore_arn "$AGENTCORE_ROLE_ARN" \
      --arg agent_account_root "arn:aws:iam::${AGENT_ACCOUNT_NUMBER}:root" \
      '{
        "Version": "2012-10-17",
        "Statement": [
          {
            "Sid": "AllowAgentCoreRole",
            "Effect": "Allow",
            "Principal": { "AWS": $agentcore_arn },
            "Action": "sts:AssumeRole"
          },
          {
            "Sid": "AllowAgentAccountLocalTesting",
            "Effect": "Allow",
            "Principal": { "AWS": $agent_account_root },
            "Action": "sts:AssumeRole"
          }
        ]
      }' > "$TRUST_POLICY_FILE"

    KB_ACCESS_ROLE_ARN=$(aws iam create-role \
      --role-name "$KB_ACCESS_ROLE_NAME" \
      --assume-role-policy-document "file://$TRUST_POLICY_FILE" \
      --profile "$AGENT_KB_PROFILE" \
      --query 'Role.Arn' \
      --output text 2>&1)

    if [ $? -ne 0 ]; then
        echo "  Failed to create KB access role. Error: $KB_ACCESS_ROLE_ARN"
        rm -f "$TRUST_POLICY_FILE"; exit 1
    fi
    rm -f "$TRUST_POLICY_FILE"
fi
echo "  KB access role: $KB_ACCESS_ROLE_ARN"

# =====================================================================
# Step 4: Create and attach KB access policy in agent-kb account
# =====================================================================
echo "Step 4: Creating KB access policy in agent-kb account..."

KB_ACCESS_POLICY_DOCUMENT=$(jq -n \
  --arg kb_id "$KNOWLEDGE_BASE_ID" \
  --arg kb_account "$AGENT_KB_ACCOUNT_NUMBER" \
  '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Sid": "BedrockRetrieve",
        "Effect": "Allow",
        "Action": "bedrock:Retrieve",
        "Resource": ("arn:aws:bedrock:*:*:knowledge-base/" + $kb_id)
      },
      {
        "Sid": "BedrockInvokeModel",
        "Effect": "Allow",
        "Action": [
          "bedrock:InvokeModel",
          "bedrock:InvokeModelWithResponseStream",
          "bedrock:GetInferenceProfile",
          "bedrock:GetFoundationModel"
        ],
        "Resource": [
          "arn:aws:bedrock:*::foundation-model/*",
          ("arn:aws:bedrock:*:" + $kb_account + ":inference-profile/*")
        ]
      },
      {
        "Sid": "BedrockRetrieveAndGenerate",
        "Effect": "Allow",
        "Action": "bedrock:RetrieveAndGenerate",
        "Resource": ("arn:aws:bedrock:*:*:knowledge-base/" + $kb_id)
      }
    ]
  }')

EXISTING_KB_POLICY_ARN=$(aws iam list-policies --scope Local \
  --query "Policies[?PolicyName=='$KB_ACCESS_POLICY_NAME'].Arn" \
  --output text --profile "$AGENT_KB_PROFILE" 2>/dev/null)

if [[ -n "$EXISTING_KB_POLICY_ARN" ]]; then
    echo "  KB access policy already exists: $EXISTING_KB_POLICY_ARN"
    KB_ACCESS_POLICY_ARN="$EXISTING_KB_POLICY_ARN"
    update_managed_policy \
        "$KB_ACCESS_POLICY_ARN" \
        "$KB_ACCESS_POLICY_DOCUMENT" \
        "$AGENT_KB_PROFILE" \
        "KB access policy" || exit 1
else
    KB_ACCESS_POLICY_ARN=$(aws iam create-policy \
      --policy-name "$KB_ACCESS_POLICY_NAME" \
      --policy-document "$KB_ACCESS_POLICY_DOCUMENT" \
      --profile "$AGENT_KB_PROFILE" \
      --query 'Policy.Arn' \
      --output text 2>&1)

    if [ $? -ne 0 ]; then
        echo "  Failed to create KB access policy. Error: $KB_ACCESS_POLICY_ARN"; exit 1
    fi
fi
echo "  KB access policy: $KB_ACCESS_POLICY_ARN"

echo "  Attaching KB access policy to KB access role..."
if ! aws iam attach-role-policy \
  --role-name "$KB_ACCESS_ROLE_NAME" \
  --policy-arn "$KB_ACCESS_POLICY_ARN" \
  --profile "$AGENT_KB_PROFILE"; then
    echo "  Failed to attach KB access policy to role"; exit 1
fi

# =====================================================================
# Step 5: Grant local IAM caller sts:AssumeRole for local testing
# =====================================================================
echo "Step 5: Granting agent account caller sts:AssumeRole for local testing..."

# Detect the calling IAM principal (user or role) from the agent profile
AGENT_CALLER_ARN=$(echo "$AGENT_IDENTITY" | jq -r '.Arn' 2>/dev/null)
AGENT_CALLER_TYPE=""
AGENT_CALLER_NAME=""

if echo "$AGENT_CALLER_ARN" | grep -q ":user/"; then
    AGENT_CALLER_TYPE="user"
    AGENT_CALLER_NAME=$(echo "$AGENT_CALLER_ARN" | sed 's/.*:user\///')
elif echo "$AGENT_CALLER_ARN" | grep -q ":role/"; then
    AGENT_CALLER_TYPE="role"
    AGENT_CALLER_NAME=$(echo "$AGENT_CALLER_ARN" | sed 's/.*:role\///' | sed 's/\/.*//')
fi

if [[ -n "$AGENT_CALLER_NAME" && -n "$AGENT_CALLER_TYPE" ]]; then
    LOCAL_POLICY_NAME="AllowAssumeKBAccessRole"
    echo "  Detected caller: $AGENT_CALLER_TYPE/$AGENT_CALLER_NAME"
    echo "  Adding inline policy '$LOCAL_POLICY_NAME' for sts:AssumeRole..."

    LOCAL_POLICY_DOC=$(jq -n \
      --arg kb_role_arn "arn:aws:iam::${AGENT_KB_ACCOUNT_NUMBER}:role/${KB_ACCESS_ROLE_NAME}" \
      '{
        "Version": "2012-10-17",
        "Statement": [
          {
            "Effect": "Allow",
            "Action": "sts:AssumeRole",
            "Resource": $kb_role_arn
          }
        ]
      }')

    if [[ "$AGENT_CALLER_TYPE" == "user" ]]; then
        aws iam put-user-policy \
          --user-name "$AGENT_CALLER_NAME" \
          --policy-name "$LOCAL_POLICY_NAME" \
          --policy-document "$LOCAL_POLICY_DOC" \
          --profile "$AGENT_PROFILE" 2>/dev/null
    else
        aws iam put-role-policy \
          --role-name "$AGENT_CALLER_NAME" \
          --policy-name "$LOCAL_POLICY_NAME" \
          --policy-document "$LOCAL_POLICY_DOC" \
          --profile "$AGENT_PROFILE" 2>/dev/null
    fi

    if [ $? -eq 0 ]; then
        echo "  Inline policy attached to $AGENT_CALLER_TYPE/$AGENT_CALLER_NAME"
    else
        echo "  Warning: Could not attach inline policy. You may need to add sts:AssumeRole manually."
    fi
else
    echo "  Warning: Could not detect caller type. Add sts:AssumeRole permission manually."
fi

# =====================================================================
# Step 6: Create AgentCore Memory resource in agent account
# =====================================================================
echo "Step 6: Creating AgentCore Memory resource in agent account..."

MEMORY_NAME="cross_account_kb_memory"
MEMORY_RETENTION_DAYS=30
EXISTING_MEMORY_ID=$(aws bedrock-agentcore-control list-memories \
  --profile "$AGENT_PROFILE" \
  --query "memories[?starts_with(id, '${MEMORY_NAME}-')].id | [0]" \
  --output text 2>/dev/null)

if [[ -n "$EXISTING_MEMORY_ID" && "$EXISTING_MEMORY_ID" != "None" ]]; then
    echo "  AgentCore Memory already exists: $EXISTING_MEMORY_ID"
    AGENTCORE_MEMORY_ID="$EXISTING_MEMORY_ID"
    EXISTING_RETENTION=$(aws bedrock-agentcore-control get-memory \
      --memory-id "$AGENTCORE_MEMORY_ID" \
      --profile "$AGENT_PROFILE" \
      --query 'memory.eventExpiryDuration' \
      --output text 2>/dev/null)
    if [[ "$EXISTING_RETENTION" != "$MEMORY_RETENTION_DAYS" ]]; then
        echo "  Updating memory event retention to $MEMORY_RETENTION_DAYS days..."
        UPDATE_OUTPUT=$(aws bedrock-agentcore-control update-memory \
          --memory-id "$AGENTCORE_MEMORY_ID" \
          --event-expiry-duration "$MEMORY_RETENTION_DAYS" \
          --client-token "$(uuidgen)" \
          --profile "$AGENT_PROFILE" 2>&1)
        if [ $? -ne 0 ]; then
            echo "  Warning: Could not update memory retention. Error: $UPDATE_OUTPUT"
        fi
    fi
else
    echo "  Creating new AgentCore Memory resource..."
    AGENTCORE_MEMORY_ID=$(aws bedrock-agentcore-control create-memory \
      --name "$MEMORY_NAME" \
      --event-expiry-duration "$MEMORY_RETENTION_DAYS" \
      --client-token "$(uuidgen)" \
      --profile "$AGENT_PROFILE" \
      --query 'memory.id' \
      --output text 2>&1)

    if [ $? -ne 0 ]; then
        echo "  Warning: Could not create AgentCore Memory. Error: $AGENTCORE_MEMORY_ID"
        echo "  You can create it manually later and set AGENTCORE_MEMORY_ID in config.json."
        AGENTCORE_MEMORY_ID=""
    else
        echo "  AgentCore Memory created: $AGENTCORE_MEMORY_ID"
    fi
fi

# =====================================================================
# Summary
# =====================================================================
echo ""
echo "=========================================="
echo "SUMMARY - Resources Created"
echo "=========================================="
echo ""
echo "AGENT ACCOUNT ($AGENT_ACCOUNT_NUMBER):"
echo "  AgentCore Role Name:   $AGENTCORE_ROLE_NAME"
echo "  AgentCore Role ARN:    $AGENTCORE_ROLE_ARN"
echo "  AgentCore Policy Name: $AGENTCORE_POLICY_NAME"
echo "  AgentCore Policy ARN:  $AGENTCORE_POLICY_ARN"
echo ""
echo "AGENT-KB ACCOUNT ($AGENT_KB_ACCOUNT_NUMBER):"
echo "  KB Access Role Name:   $KB_ACCESS_ROLE_NAME"
echo "  KB Access Role ARN:    $KB_ACCESS_ROLE_ARN"
echo "  KB Access Policy Name: $KB_ACCESS_POLICY_NAME"
echo "  KB Access Policy ARN:  $KB_ACCESS_POLICY_ARN"
echo ""
echo "CONFIGURATION:"
echo "  Knowledge Base ID:   $KNOWLEDGE_BASE_ID"
echo "  KB Foundation Model: us.anthropic.claude-haiku-4-5-20251001-v1:0"
echo "  AgentCore Memory ID: ${AGENTCORE_MEMORY_ID:-<not created — set manually in config.json>}"
echo ""
echo "=========================================="
echo "All resources created successfully!"
echo "=========================================="

# ---------------------------------------------------------------------------
# Generate strands_agent/config.json so the deployed agent picks up settings
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/../strands_agent/config.json"

CONFIG_TEMP_FILE=$(mktemp)
TEMP_FILES+=("$CONFIG_TEMP_FILE")
jq -n \
  --arg kb_id "$KNOWLEDGE_BASE_ID" \
  --arg role_arn "$KB_ACCESS_ROLE_ARN" \
  --arg memory_id "$AGENTCORE_MEMORY_ID" \
  '{
    "KNOWLEDGE_BASE_ID": $kb_id,
    "TARGET_ROLE_ARN": $role_arn,
    "KB_FOUNDATION_MODEL": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "AGENT_MODEL_ID": "us.amazon.nova-pro-v1:0",
    "AGENT_MAX_TOKENS": "5000",
    "AWS_REGION": "us-west-2",
    "KB_NUM_RESULTS": "5",
    "AGENTCORE_MEMORY_ID": $memory_id
  }' > "$CONFIG_TEMP_FILE"
mv "$CONFIG_TEMP_FILE" "$CONFIG_FILE"
echo ""
echo "Generated agent config: $CONFIG_FILE"

echo ""
echo "NEXT STEPS:"
echo "  1. Deploy the Strands agent to AgentCore:"
echo "     cd strands_agent"
echo "     agentcore configure --entrypoint agent.py --execution-role $AGENTCORE_ROLE_ARN"
echo "     agentcore deploy"
echo ""
echo "  2. Or test locally with Streamlit:"
echo "     export TARGET_ROLE_ARN=$KB_ACCESS_ROLE_ARN"
echo "     export KNOWLEDGE_BASE_ID=$KNOWLEDGE_BASE_ID"
echo "     cd streamlit_app && streamlit run app.py"
echo ""

# JSON output
echo "JSON OUTPUT:"
cat << EOF
{
  "agent_account": {
    "account_number": "$AGENT_ACCOUNT_NUMBER",
    "agentcore_role": {
      "name": "$AGENTCORE_ROLE_NAME",
      "arn": "$AGENTCORE_ROLE_ARN"
    },
    "agentcore_policy": {
      "name": "$AGENTCORE_POLICY_NAME",
      "arn": "$AGENTCORE_POLICY_ARN"
    }
  },
  "agent_kb_account": {
    "account_number": "$AGENT_KB_ACCOUNT_NUMBER",
    "kb_access_role": {
      "name": "$KB_ACCESS_ROLE_NAME",
      "arn": "$KB_ACCESS_ROLE_ARN"
    },
    "kb_access_policy": {
      "name": "$KB_ACCESS_POLICY_NAME",
      "arn": "$KB_ACCESS_POLICY_ARN"
    }
  },
  "configuration": {
    "knowledge_base_id": "$KNOWLEDGE_BASE_ID",
    "kb_foundation_model": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
    "agentcore_memory_id": "$AGENTCORE_MEMORY_ID"
  }
}
EOF

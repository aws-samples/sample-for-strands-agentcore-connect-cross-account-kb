# Declarative AgentCore Harness Variant

This directory contains Variant 2 of the cross-account Knowledge Base sample. AgentCore runs the
agent loop from a declarative Harness definition, while a Gateway-backed Lambda tool assumes the
role in the Knowledge Base account and calls `retrieve_and_generate`.

For the architecture, IAM setup, two-phase deployment explanation, Streamlit integration, and
cleanup order, see the root
[README](../../README.md#variant-2--declarative-harness-managed-agent-loop).

## Components

| Path | Purpose |
| --- | --- |
| `agentcore/*.json.template` | Committed, account-neutral project and target configuration |
| `app/strands_kb_harness/harness.json.template` | Harness model, prompt, memory, and tools |
| `tools/kb_query/` | Python Lambda target for cross-account KB queries |
| `agentcore/cdk/` | AgentCore CLI-managed CDK application |

The generated `agentcore.json`, `aws-targets.json`, `harness.json`, Lambda `config.json`, and
deployment state are gitignored because they contain account IDs or deployed resource ARNs.

## Prerequisites

- Node.js 20 or later
- AWS CLI credentials for the AgentCore and Knowledge Base accounts
- `jq`
- Current `@aws/agentcore` CLI
- Shared IAM resources created by the root setup script

```bash
npm install -g @aws/agentcore
agentcore --version
```

## Configure

From the repository root:

```bash
scripts/configure_harness_variant.sh \
    --agent-account 111122223333 \
    --agent-kb-account 999999999999 \
    --knowledge-base-id YOUR_KB_ID
```

This renders the local deployment files from the committed templates. Rerun it after changing an
account, region, role name, Knowledge Base, or template.

## Validate And Deploy

```bash
cd harness_variant/strandskbharness
agentcore validate

# Phase 1: deploy the Harness, Memory, Gateway, and Lambda target.
AWS_PROFILE=agent agentcore deploy --yes
```

After Phase 1, add the Lambda execution role to the shared KB access role's trust policy as
documented in the root README. Then attach the deployed Gateway and redeploy:

```bash
agentcore add tool \
    --harness strands_kb_harness \
    --type agentcore_gateway \
    --name kb_gateway_tool \
    --gateway-arn <gateway-arn-from-phase-1> \
    --outbound-auth awsIam

AWS_PROFILE=agent agentcore deploy --yes
```

## Invoke

```bash
AWS_PROFILE=agent agentcore invoke \
    --harness strands_kb_harness \
    "What is the total number of customers?"
```

For the Streamlit UI, set `AGENTCORE_HARNESS_ARN`, launch `streamlit_app/app.py`, and open
[Harness mode](http://localhost:8501/?mode=Harness).

## Test

```bash
agentcore validate
cd agentcore/cdk
npm test -- --runInBand
npm run build
```

## Cleanup

Run this before deleting the shared IAM resources used by the code-based variant:

```bash
../../scripts/cleanup_harness_variant.sh \
    --agent-profile agent \
    --agent-kb-profile agent-kb \
    --agent-account 111122223333 \
    --agent-kb-account 999999999999
```

After AWS confirms that the stack is absent, the cleanup script also removes the generated local
deployment state so the next deployment starts without stale resource ARNs or a stale deploy hash.

"""
MCP server that exposes query_knowledge_base as an MCP tool.

Runs as a subprocess (stdio transport) consumed by the Strands agent via MCPClient.
Can also be tested standalone:  python kb_mcp_server.py

All cross-account STS + Bedrock retrieve_and_generate logic lives here,
decoupled from agent orchestration in agent.py.
"""

import logging
import os

try:
    from .configuration import config_value, load_sibling_config
except ImportError:
    from configuration import config_value, load_sibling_config

# ---------------------------------------------------------------------------
# Configuration — mirrors agent.py: environment overrides, config.json fallback
# ---------------------------------------------------------------------------
_file_config = load_sibling_config(__file__)

KNOWLEDGE_BASE_ID = config_value(_file_config, "KNOWLEDGE_BASE_ID", "YOUR_KB_ID")
TARGET_ROLE_ARN = config_value(_file_config, "TARGET_ROLE_ARN", "")
KB_FOUNDATION_MODEL = config_value(
    _file_config,
    "KB_FOUNDATION_MODEL",
    "us.anthropic.claude-haiku-4-5-20251001-v1:0",
)
AWS_REGION = config_value(_file_config, "AWS_REGION", "us-west-2")
KB_NUM_RESULTS = int(config_value(_file_config, "KB_NUM_RESULTS", "5"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cross-account Bedrock client — RefreshableCredentials so botocore handles
# STS token rotation automatically (thread-safe, no manual expiry tracking).
# ---------------------------------------------------------------------------
_bedrock_client = None
_kb_account_id  = None


def _get_kb_account_id() -> str:
    import boto3
    global _kb_account_id
    if _kb_account_id is not None:
        return _kb_account_id
    if TARGET_ROLE_ARN:
        _kb_account_id = TARGET_ROLE_ARN.split(":")[4]
    else:
        _kb_account_id = boto3.client("sts", region_name=AWS_REGION).get_caller_identity()["Account"]
    return _kb_account_id


def _build_model_arn(model_id: str) -> str:
    if model_id.startswith(("us.", "eu.", "ap.")):
        return f"arn:aws:bedrock:{AWS_REGION}:{_get_kb_account_id()}:inference-profile/{model_id}"
    return f"arn:aws:bedrock:{AWS_REGION}::foundation-model/{model_id}"


def _get_bedrock_client():
    import boto3
    global _bedrock_client
    if _bedrock_client is not None:
        return _bedrock_client

    if not TARGET_ROLE_ARN:
        _bedrock_client = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
        logger.info("Created same-account Bedrock client")
        return _bedrock_client

    from botocore.credentials import RefreshableCredentials
    from botocore.session import get_session

    def _refresh():
        sts = boto3.client("sts", region_name=AWS_REGION)
        creds = sts.assume_role(
            RoleArn=TARGET_ROLE_ARN, RoleSessionName="StrandsAgentKBQuery"
        )["Credentials"]
        logger.info("Assumed role (refreshed): %s", TARGET_ROLE_ARN)
        return {
            "access_key":  creds["AccessKeyId"],
            "secret_key":  creds["SecretAccessKey"],
            "token":       creds["SessionToken"],
            "expiry_time": creds["Expiration"].isoformat(),
        }

    refreshable = RefreshableCredentials.create_from_metadata(
        metadata=_refresh(),
        refresh_using=_refresh,
        method="sts-assume-role",
    )
    session = get_session()
    session._credentials = refreshable
    _bedrock_client = boto3.Session(botocore_session=session).client(
        "bedrock-agent-runtime", region_name=AWS_REGION
    )
    logger.info("Created cross-account Bedrock client with auto-refreshing credentials")
    return _bedrock_client


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------
from mcp.server.fastmcp import FastMCP

mcp = FastMCP("kb-query-server")


@mcp.tool()
def query_knowledge_base(query: str) -> str:
    """Query the Amazon Redshift Serverless knowledge base across AWS accounts.

    Assumes an IAM role in the knowledge-base account, then calls Bedrock
    retrieve_and_generate to answer natural-language questions about inventory
    data stored in Amazon Redshift Serverless.

    Args:
        query: A natural language question about the data in Redshift.

    Returns:
        JSON string with answer, citations, and source metadata.
    """
    from botocore.exceptions import ClientError

    try:
        bedrock_agent_runtime = _get_bedrock_client()
        model_arn = _build_model_arn(KB_FOUNDATION_MODEL)
        logger.info(
            "Querying KB %s with model %s (%d results)",
            KNOWLEDGE_BASE_ID, KB_FOUNDATION_MODEL, KB_NUM_RESULTS,
        )

        response = bedrock_agent_runtime.retrieve_and_generate(
            input={"text": query},
            retrieveAndGenerateConfiguration={
                "type": "KNOWLEDGE_BASE",
                "knowledgeBaseConfiguration": {
                    "knowledgeBaseId": KNOWLEDGE_BASE_ID,
                    "modelArn": model_arn,
                    "retrievalConfiguration": {
                        "vectorSearchConfiguration": {
                            "numberOfResults": KB_NUM_RESULTS
                        }
                    },
                },
            },
        )

        generated_text = response.get("output", {}).get("text", "")
        citations = [
            {
                "retrievedReferences": c.get("retrievedReferences", []),
                "generatedResponsePart": c.get("generatedResponsePart", ""),
            }
            for c in response.get("citations", [])
        ]

        logger.info("KB query successful")
        import json

        return json.dumps({
            "answer":    generated_text,
            "citations": citations,
            "query":     query,
            "source":    f"Amazon Redshift Serverless KB: {KNOWLEDGE_BASE_ID}",
        }, default=str)

    except ClientError as exc:
        import json

        logger.error("AWS API error: %s", exc)
        return json.dumps({"error": str(exc), "errorType": type(exc).__name__})
    except Exception as exc:
        import json

        logger.error("Unexpected error: %s", exc)
        return json.dumps({"error": str(exc), "errorType": type(exc).__name__})


if __name__ == "__main__":
    mcp.run()

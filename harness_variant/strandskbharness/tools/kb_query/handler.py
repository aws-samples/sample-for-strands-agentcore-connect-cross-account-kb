"""
AgentCore Gateway Lambda target: cross-account Bedrock Knowledge Base query.

This is the harness-architecture port of strands_agent/kb_mcp_server.py. The same
cross-account logic (STS AssumeRole into the agent-kb account + retrieve_and_generate
against a Redshift-backed Knowledge Base) runs here as a Gateway tool instead of an
MCP stdio subprocess. The declarative harness calls this tool via the Gateway; the
cross-account AssumeRole happens in this Lambda's execution role.

Gateway -> Lambda contract:
  - Tool input arguments arrive as the `event` dict (e.g. {"query": "..."}).
  - context.client_context.custom["bedrockAgentCoreToolName"] == "<target>___<tool>";
    we strip the "___" prefix to dispatch.
  - The handler returns a JSON-serializable object.
"""

import json
import logging
import os

# In Lambda the runtime pre-configures the root logger at WARNING, so basicConfig
# is a no-op and INFO lines are dropped. Set the root level explicitly.
logging.getLogger().setLevel(logging.INFO)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration — bundled config.json (packaged with the Lambda), env overrides.
# Mirrors the config pattern from kb_mcp_server.py. LambdaComputeConfig has no
# env-var field, so config travels in config.json alongside the code.
# ---------------------------------------------------------------------------
def _load_config():
    config = {}
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")
    if os.path.exists(config_path):
        with open(config_path, encoding="utf-8") as f:
            config = json.load(f)
    return config


_file_config = _load_config()


def _config_value(name: str, default=""):
    if name in os.environ:
        return os.environ[name]
    return _file_config.get(name, default)


KNOWLEDGE_BASE_ID = _config_value("KNOWLEDGE_BASE_ID", "YOUR_KB_ID")
TARGET_ROLE_ARN = _config_value("TARGET_ROLE_ARN", "")
KB_FOUNDATION_MODEL = _config_value(
    "KB_FOUNDATION_MODEL", "us.anthropic.claude-haiku-4-5-20251001-v1:0"
)
AWS_REGION = _config_value("AWS_REGION", "us-west-2")
KB_NUM_RESULTS = int(_config_value("KB_NUM_RESULTS", "5"))

# ---------------------------------------------------------------------------
# Cross-account Bedrock client. RefreshableCredentials keeps the cached client safe
# when Lambda reuses a warm execution environment beyond the STS session lifetime.
# ---------------------------------------------------------------------------
_bedrock_client = None
_kb_account_id = None


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

    target_role_arn = TARGET_ROLE_ARN
    region_name = AWS_REGION

    def _refresh():
        sts = boto3.client("sts", region_name=region_name)
        credentials = sts.assume_role(
            RoleArn=target_role_arn,
            RoleSessionName="HarnessKBQuery",
        )["Credentials"]
        logger.info("Assumed cross-account role (refreshed): %s", target_role_arn)
        return {
            "access_key": credentials["AccessKeyId"],
            "secret_key": credentials["SecretAccessKey"],
            "token": credentials["SessionToken"],
            "expiry_time": credentials["Expiration"].isoformat(),
        }

    refreshable = RefreshableCredentials.create_from_metadata(
        metadata=_refresh(),
        refresh_using=_refresh,
        method="sts-assume-role",
    )
    botocore_session = get_session()
    botocore_session._credentials = refreshable
    _bedrock_client = boto3.Session(botocore_session=botocore_session).client(
        "bedrock-agent-runtime",
        region_name=region_name,
    )
    return _bedrock_client


def _query_knowledge_base(query: str) -> dict:
    """Assume the KB-account role and run retrieve_and_generate against the KB."""
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
                    "vectorSearchConfiguration": {"numberOfResults": KB_NUM_RESULTS}
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
    return {
        "answer": generated_text,
        "citations": citations,
        "query": query,
        "source": f"Amazon Redshift Serverless KB: {KNOWLEDGE_BASE_ID}",
    }


def handler(event, context):
    """AgentCore Gateway Lambda entrypoint.

    The Gateway passes the tool's input arguments as `event` and the fully
    qualified tool name as context.client_context.custom["bedrockAgentCoreToolName"]
    in the form "<target>___<tool>".
    """
    from botocore.exceptions import ClientError

    tool_name = ""
    try:
        custom = (getattr(context, "client_context", None) or {}) and context.client_context.custom
        tool_name = (custom or {}).get("bedrockAgentCoreToolName", "")
    except Exception:  # noqa: BLE001 - tolerate missing context shape in local tests
        tool_name = ""

    # Strip the "<target>___" prefix to get the bare tool name.
    short_name = tool_name.split("___", 1)[-1] if "___" in tool_name else tool_name
    logger.info("Invoked tool: %s (short=%s)", tool_name, short_name)

    query = event.get("query") if isinstance(event, dict) else None
    if not query:
        return {"error": "Missing required 'query' argument", "errorType": "ValidationError"}

    try:
        return _query_knowledge_base(query)
    except ClientError as exc:
        logger.error("AWS API error: %s", exc)
        return {"error": str(exc), "errorType": type(exc).__name__}
    except Exception as exc:  # noqa: BLE001 - surface any failure as a tool error
        logger.error("Unexpected error: %s", exc)
        return {"error": str(exc), "errorType": type(exc).__name__}

# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""
Streamlit Chat Interface for the Strands Agent (cross-account KB query).

Supports three invocation modes:
  - Local:     Imports the Strands agent directly (no deployment required).
  - AgentCore: Calls the deployed AgentCore endpoint via boto3.
  - Harness:   Calls the declarative AgentCore harness via boto3.

Usage:
  cd streamlit_app
  pip install -r requirements.txt
  streamlit run app.py
"""

import json
import logging
import os
import sys
import time

import boto3
import streamlit as st

# ---------------------------------------------------------------------------
# Ensure the sibling strands_agent package is importable
# ---------------------------------------------------------------------------
PARENT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from streamlit_app.streaming import (
    extract_text_from_event,
    iter_agentcore_text,
    iter_streaming_body_chunks,
    strip_thinking_stream,
    strip_thinking_text,
)
from strands_agent.configuration import config_value, load_sibling_config
from strands_agent.input_validation import MAX_QUERY_LENGTH, validate_query

logger = logging.getLogger(__name__)
_AGENT_FILE_CONFIG = load_sibling_config(
    os.path.join(PARENT_DIR, "strands_agent", "agent.py")
)


def configured_value(name: str, default: str = "") -> str:
    """Resolve a sidebar default from the environment, agent config, or fallback."""
    return str(config_value(_AGENT_FILE_CONFIG, name, default))

# Pre-validate that strands is importable
try:
    import strands  # noqa: F401
    _STRANDS_AVAILABLE = True
except ImportError as e:
    _STRANDS_AVAILABLE = False
    _STRANDS_IMPORT_ERROR = (
        f"Cannot import strands: {e}\n"
        f"Python executable: {sys.executable}\n"
        f"sys.path: {sys.path}\n"
        "Install with: pip install -r streamlit_app/requirements.txt"
    )

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Redshift KB Agent",
    page_icon="🔍",
    layout="wide",
)

# ---------------------------------------------------------------------------
# Sidebar – configuration
# ---------------------------------------------------------------------------
with st.sidebar:
    st.title("Agent Configuration")

    invocation_modes = ["Local", "AgentCore", "Harness"]
    requested_mode = st.query_params.get("mode", "Local")
    if requested_mode not in invocation_modes:
        requested_mode = "Local"
    mode = st.radio(
        "Invocation mode",
        invocation_modes,
        index=invocation_modes.index(requested_mode),
        help="Local: runs the agent in-process. AgentCore: calls the deployed "
        "agent.py runtime. Harness: calls the declarative harness variant "
        "(Gateway + Lambda) via the InvokeHarness API.",
    )
    if st.query_params.get("mode") != mode:
        st.query_params["mode"] = mode

    st.divider()
    st.subheader("Knowledge Base Settings")
    local_settings_enabled = mode == "Local"
    if not local_settings_enabled:
        st.caption(
            "These Knowledge Base and model values configure Local mode only. "
            "Remote modes use configuration packaged with the deployed resource."
        )

    kb_id = st.text_input(
        "Knowledge Base ID",
        value=configured_value("KNOWLEDGE_BASE_ID"),
        disabled=not local_settings_enabled,
    )
    target_role_arn = st.text_input(
        "Target Role ARN (KB account)",
        value=configured_value("TARGET_ROLE_ARN"),
        help="ARN of the IAM role to assume in the agent-kb account. "
        "Leave blank for same-account access.",
        disabled=not local_settings_enabled,
    )
    kb_model = st.text_input(
        "KB Foundation Model",
        value=configured_value(
            "KB_FOUNDATION_MODEL",
            "us.anthropic.claude-haiku-4-5-20251001-v1:0",
        ),
        disabled=not local_settings_enabled,
    )
    agent_model = st.text_input(
        "Agent Model",
        value=configured_value("AGENT_MODEL_ID", "us.amazon.nova-pro-v1:0"),
        disabled=not local_settings_enabled,
    )
    region = st.text_input(
        "AWS Region",
        value=configured_value("AWS_REGION", "us-west-2"),
    )

    if mode == "AgentCore":
        st.divider()
        st.subheader("AgentCore Settings")
        agentcore_runtime_arn = st.text_input(
            "AgentCore Runtime ARN",
            value=os.environ.get("AGENTCORE_RUNTIME_ARN", ""),
            help="ARN of the deployed AgentCore runtime endpoint.",
        )

    if mode == "Harness":
        st.divider()
        st.subheader("Harness Settings")
        harness_arn = st.text_input(
            "Harness ARN",
            value=os.environ.get("AGENTCORE_HARNESS_ARN", ""),
            help="ARN of the deployed AgentCore harness "
            "(arn:aws:bedrock-agentcore:<region>:<account>:harness/<id>). "
            "Invoked via the InvokeHarness API.",
        )

    st.divider()
    st.subheader("Sample Queries")
    sample_queries = [
        "Who are the top 5 customers in Saudi Arabia?",
        "Who are the top parts suppliers in the United States by volume?",
        "What is the total revenue by region for the year 1998?",
        "Which products generated the highest revenue after discounts?",
        "Show the 100 highest-value orders marked 1-URGENT from October 1 through "
        + "December 31, 1997.",
    ]
    for q in sample_queries:
        if st.button(q, key=q, use_container_width=True):
            st.session_state["prefill"] = q

    st.divider()
    if st.button("New conversation", use_container_width=True):
        for key in (
            "messages",
            "local_agent",
            "local_agent_config_key",
            "agentcore_session_id",
            "harness_session_id",
        ):
            st.session_state.pop(key, None)
        st.rerun()


# ---------------------------------------------------------------------------
# Push settings into env vars so the agent picks them up
# ---------------------------------------------------------------------------
os.environ["KNOWLEDGE_BASE_ID"] = kb_id
os.environ["TARGET_ROLE_ARN"] = target_role_arn
os.environ["KB_FOUNDATION_MODEL"] = kb_model
os.environ["AGENT_MODEL_ID"] = agent_model
os.environ["AWS_REGION"] = region


# ---------------------------------------------------------------------------
# Agent helpers
# ---------------------------------------------------------------------------
def get_local_agent():
    """Return an agent isolated to the current Streamlit browser session."""
    if not _STRANDS_AVAILABLE:
        raise ImportError(_STRANDS_IMPORT_ERROR)
    if os.environ.get("BYPASS_TOOL_CONSENT", "").lower() not in (
        "1",
        "true",
        "yes",
    ):
        raise RuntimeError(
            "Local mode requires explicit BYPASS_TOOL_CONSENT=true configuration."
        )
    from strands_agent.agent import create_agent

    tool_config = {
        "KNOWLEDGE_BASE_ID": kb_id,
        "TARGET_ROLE_ARN": target_role_arn,
        "KB_FOUNDATION_MODEL": kb_model,
        "AWS_REGION": region,
        "KB_NUM_RESULTS": os.environ.get("KB_NUM_RESULTS", "5"),
    }
    config_key = (
        agent_model,
        region,
        tuple(sorted(tool_config.items())),
    )
    if st.session_state.get("local_agent_config_key") != config_key:
        st.session_state.local_agent = create_agent(
            agent_model_id=agent_model,
            region_name=region,
            tool_config=tool_config,
            reuse_agent=False,
        )
        st.session_state.local_agent_config_key = config_key
    return st.session_state.local_agent


def invoke_local(prompt: str) -> str:
    """Invoke the agent locally."""
    agent = get_local_agent()
    result = agent(prompt)
    return str(result)


def stream_agentcore(prompt: str):
    """Generator that yields text tokens from the AgentCore streaming response.

    The AgentCore entrypoint is an async generator (agent.stream_async), so the
    HTTP response body is newline-delimited JSON.  We parse each line and pull
    out the text token.  Non-text events (tool calls, thought traces, etc.) are
    silently skipped so only the final answer text reaches the user.
    """
    import uuid

    from botocore.config import Config

    client = boto3.client(
        "bedrock-agentcore",
        region_name=region,
        config=Config(read_timeout=300, connect_timeout=10),
    )

    if "agentcore_session_id" not in st.session_state:
        st.session_state.agentcore_session_id = str(uuid.uuid4())

    response = client.invoke_agent_runtime(
        agentRuntimeArn=agentcore_runtime_arn,
        runtimeSessionId=st.session_state.agentcore_session_id,
        payload=json.dumps({
            "prompt": prompt,
        }).encode("utf-8"),
    )

    yield from iter_agentcore_text(
        iter_streaming_body_chunks(response["response"])
    )


def stream_harness(prompt: str):
    """Generator that yields text tokens from the deployed harness variant.

    Harness runtimes cannot be called via invoke_agent_runtime — they require
    the InvokeHarness API, which returns a Bedrock Converse-style event stream
    (messageStart / contentBlockDelta / contentBlockStop / messageStop). We pull
    text out of contentBlockDelta frames and skip everything else (tool calls,
    reasoning, metadata). <thinking> blocks are filtered downstream by
    _strip_thinking_stream, same as AgentCore mode.
    """
    import uuid

    from botocore.config import Config

    # Multi-step harness runs chain several cross-account KB calls, each of which
    # can take tens of seconds. Raise the socket read timeout above botocore's
    # 60s default so long streams aren't cut off mid-response.
    client = boto3.client(
        "bedrock-agentcore",
        region_name=region,
        config=Config(read_timeout=300, connect_timeout=10),
    )

    if "harness_session_id" not in st.session_state:
        st.session_state.harness_session_id = str(uuid.uuid4())

    response = client.invoke_harness(
        harnessArn=harness_arn,
        runtimeSessionId=st.session_state.harness_session_id,
        actorId=st.session_state.harness_session_id,
        messages=[{"role": "user", "content": [{"text": prompt}]}],
    )

    for event in response["stream"]:
        if "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get("delta", {})
            text = delta.get("text")
            if text:
                yield text
        elif "internalServerException" in event:
            raise RuntimeError(event["internalServerException"].get("message", "internal server error"))
        elif "validationException" in event:
            raise RuntimeError(event["validationException"].get("message", "validation error"))
        elif "runtimeClientError" in event:
            raise RuntimeError(event["runtimeClientError"].get("message", "runtime client error"))


# ---------------------------------------------------------------------------
# Chat UI
# ---------------------------------------------------------------------------
st.title("Redshift Knowledge Base Agent")
if mode == "Local":
    st.caption(f"Mode: **{mode}** | Region: `{region}` | KB: `{kb_id}`")
else:
    st.caption(
        f"Mode: **{mode}** | Region: `{region}` | "
        "Knowledge Base and model: deployed configuration"
    )

# Initialise chat history
if "messages" not in st.session_state:
    st.session_state.messages = []

# Render chat history
for msg in st.session_state.messages:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])

# Handle prefilled sample query
prefill = st.session_state.pop("prefill", None)

# Chat input
prompt = st.chat_input(
    "Ask a question about your Redshift data...",
    max_chars=MAX_QUERY_LENGTH,
) or prefill

if prompt:
    try:
        prompt = validate_query(prompt)
    except ValueError as exc:
        st.error(str(exc))
        st.stop()

    # Show user message
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    # Get agent response
    with st.chat_message("assistant"):
        try:
            t0 = time.time()
            if mode == "AgentCore":
                # Streaming: tokens appear as they are generated
                response = st.write_stream(strip_thinking_stream(stream_agentcore(prompt)))
            elif mode == "Harness":
                # Streaming via the InvokeHarness API (declarative harness variant)
                response = st.write_stream(strip_thinking_stream(stream_harness(prompt)))
            else:
                # Local: synchronous, show progress spinner
                with st.status("Working...", expanded=True) as status:
                    st.write("Sending query to agent...")
                    response = strip_thinking_text(invoke_local(prompt))
                    elapsed = time.time() - t0
                    status.update(
                        label=f"Done ({elapsed:.1f}s)", state="complete", expanded=False
                    )
                st.markdown(response)
            st.session_state.messages.append(
                {"role": "assistant", "content": response}
            )
        except Exception:
            logger.exception("Invocation failed in %s mode", mode)
            error_msg = "Unable to complete the request. Check application logs."
            st.error(error_msg)
            st.session_state.messages.append(
                {"role": "assistant", "content": error_msg}
            )

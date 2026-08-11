# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import hashlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from strands_agent import agent


class FakeAgent:
    async def stream_async(self, prompt):
        yield {"data": f"answer for {prompt}"}


@unittest.skipUnless(
    hasattr(agent, "invoke_agent"),
    "bedrock-agentcore runtime package is not installed",
)
class AgentEntrypointTests(unittest.IsolatedAsyncioTestCase):
    async def test_memory_actor_comes_from_runtime_session_not_payload(self):
        context = SimpleNamespace(session_id="trusted-runtime-session")
        payload = {
            "prompt": "Show revenue.",
            "actor_id": "caller-selected-namespace",
        }

        with patch.object(agent, "create_agent", return_value=FakeAgent()) as create:
            chunks = [
                chunk async for chunk in agent.invoke_agent(payload, context)
            ]

        self.assertEqual(chunks, ["answer for Show revenue."])
        expected_actor = "runtime-session-" + hashlib.sha256(
            b"trusted-runtime-session"
        ).hexdigest()[:32]
        create.assert_called_once_with(
            session_id="trusted-runtime-session",
            actor_id=expected_actor,
        )

    def test_memory_actor_hashes_runtime_session(self):
        expected_actor = "runtime-session-" + hashlib.sha256(
            b"runtime-session"
        ).hexdigest()[:32]

        self.assertEqual(
            agent._memory_actor_id("runtime-session"),
            expected_actor,
        )

    def test_memory_restores_only_the_latest_user_request(self):
        messages = [
            {"role": "user", "content": [{"text": "Show revenue."}]},
            {"role": "assistant", "content": [{"text": "Stale answer."}]},
            {"role": "user", "content": [{"text": "Now show suppliers."}]},
            {"role": "assistant", "content": [{"text": "Another stale answer."}]},
        ]

        self.assertEqual(
            agent._latest_user_request(messages),
            [{"role": "user", "content": [{"text": "Now show suppliers."}]}],
        )

    def test_memory_with_no_user_request_restores_no_messages(self):
        messages = [
            {"role": "assistant", "content": [{"text": "Stale answer."}]},
        ]

        self.assertEqual(agent._latest_user_request(messages), [])

    async def test_invalid_prompt_is_rejected_before_agent_creation(self):
        with patch.object(agent, "create_agent") as create:
            chunks = [
                chunk
                async for chunk in agent.invoke_agent(
                    {"prompt": "bad\x00query"},
                    SimpleNamespace(session_id="runtime-session"),
                )
            ]

        self.assertEqual(
            chunks,
            [{"error": "Query contains unsupported control characters."}],
        )
        create.assert_not_called()


if __name__ == "__main__":
    unittest.main()

import unittest
from unittest.mock import patch

from strands_agent import kb_mcp_server


class KnowledgeBaseMcpTests(unittest.TestCase):
    def test_builds_cross_region_inference_profile_arn(self):
        with patch.object(kb_mcp_server, "_kb_account_id", "123456789012"):
            self.assertEqual(
                kb_mcp_server._build_model_arn("us.example.model-v1:0"),
                "arn:aws:bedrock:us-west-2:123456789012:"
                "inference-profile/us.example.model-v1:0",
            )

    def test_builds_foundation_model_arn(self):
        self.assertEqual(
            kb_mcp_server._build_model_arn("example.model-v1:0"),
            "arn:aws:bedrock:us-west-2::foundation-model/example.model-v1:0",
        )

    def test_extracts_account_from_target_role(self):
        with (
            patch.object(
                kb_mcp_server,
                "TARGET_ROLE_ARN",
                "arn:aws:iam::123456789012:role/kb-access",
            ),
            patch.object(kb_mcp_server, "_kb_account_id", None),
        ):
            self.assertEqual(kb_mcp_server._get_kb_account_id(), "123456789012")


if __name__ == "__main__":
    unittest.main()

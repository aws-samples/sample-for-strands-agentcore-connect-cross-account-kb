from datetime import datetime, timedelta, timezone
import json
import unittest
from unittest.mock import MagicMock, patch

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

    def test_unexpected_errors_are_not_returned_to_callers(self):
        with patch.object(
            kb_mcp_server,
            "_get_bedrock_client",
            side_effect=RuntimeError("internal account and resource details"),
        ):
            result = json.loads(
                kb_mcp_server.query_knowledge_base("Show revenue.")
            )

        self.assertEqual(result["errorType"], "KnowledgeBaseQueryError")
        self.assertNotIn("internal account", result["error"])

    @patch("boto3.Session")
    @patch("boto3.client")
    @patch("botocore.session.get_session")
    @patch("botocore.credentials.RefreshableCredentials.create_from_metadata")
    def test_assumed_role_session_names_are_unique(
        self,
        create_from_metadata,
        get_session,
        boto3_client,
        boto3_session,
    ):
        expiration = datetime.now(timezone.utc) + timedelta(hours=1)
        sts_client = MagicMock()
        sts_client.assume_role.return_value = {
            "Credentials": {
                "AccessKeyId": "access-key",
                "SecretAccessKey": "secret-key",
                "SessionToken": "token",
                "Expiration": expiration,
            }
        }
        boto3_client.return_value = sts_client
        bedrock_client = MagicMock()
        boto3_session.return_value.client.return_value = bedrock_client

        with (
            patch.object(kb_mcp_server, "_bedrock_client", None),
            patch.object(
                kb_mcp_server,
                "TARGET_ROLE_ARN",
                "arn:aws:iam::123456789012:role/kb-access",
            ),
        ):
            result = kb_mcp_server._get_bedrock_client()

        self.assertIs(result, bedrock_client)
        refresh_callback = create_from_metadata.call_args.kwargs["refresh_using"]
        refresh_callback()
        session_names = []
        for call in sts_client.assume_role.call_args_list:
            self.assertRegex(
                call.kwargs["RoleSessionName"],
                r"^StrandsKB-[0-9a-f]{12}$",
            )
            session_names.append(call.kwargs["RoleSessionName"])
        self.assertEqual(len(set(session_names)), 2)
        boto3_session.assert_called_once_with(botocore_session=get_session.return_value)


if __name__ == "__main__":
    unittest.main()

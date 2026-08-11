# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

from datetime import datetime, timedelta, timezone
import os
import unittest
from unittest.mock import MagicMock, patch

from harness_variant.strandskbharness.tools.kb_query import handler


class HarnessHandlerTests(unittest.TestCase):
    def test_environment_configuration_takes_precedence(self):
        with (
            patch.dict(os.environ, {"TEST_SETTING": "from-env"}, clear=False),
            patch.object(handler, "_file_config", {"TEST_SETTING": "from-file"}),
        ):
            self.assertEqual(handler._config_value("TEST_SETTING"), "from-env")

    def test_empty_environment_configuration_takes_precedence(self):
        with (
            patch.dict(os.environ, {"TEST_SETTING": ""}, clear=False),
            patch.object(handler, "_file_config", {"TEST_SETTING": "from-file"}),
        ):
            self.assertEqual(handler._config_value("TEST_SETTING"), "")

    def test_missing_query_returns_validation_error(self):
        result = handler.handler({}, None)

        self.assertEqual(result["errorType"], "ValidationError")
        self.assertIn("query", result["error"].lower())

    def test_unexpected_errors_are_not_returned_to_callers(self):
        with patch.object(
            handler,
            "_query_knowledge_base",
            side_effect=RuntimeError("internal account and resource details"),
        ):
            result = handler.handler({"query": "Show revenue."}, None)

        self.assertEqual(result["errorType"], "KnowledgeBaseQueryError")
        self.assertNotIn("internal account", result["error"])

    @patch("boto3.Session")
    @patch("boto3.client")
    @patch("botocore.session.get_session")
    @patch("botocore.credentials.RefreshableCredentials.create_from_metadata")
    def test_assumed_role_credentials_are_refreshable(
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
            patch.object(handler, "_bedrock_client", None),
            patch.object(
                handler,
                "TARGET_ROLE_ARN",
                "arn:aws:iam::123456789012:role/kb-access",
            ),
        ):
            result = handler._get_bedrock_client()

        self.assertIs(result, bedrock_client)
        refresh_callback = create_from_metadata.call_args.kwargs["refresh_using"]
        refreshed = refresh_callback()
        self.assertEqual(refreshed["access_key"], "access-key")
        self.assertEqual(sts_client.assume_role.call_count, 2)
        session_names = []
        for call in sts_client.assume_role.call_args_list:
            self.assertEqual(
                call.kwargs["RoleArn"],
                "arn:aws:iam::123456789012:role/kb-access",
            )
            self.assertRegex(
                call.kwargs["RoleSessionName"],
                r"^HarnessKB-[0-9a-f]{12}$",
            )
            session_names.append(call.kwargs["RoleSessionName"])
        self.assertEqual(len(set(session_names)), 2)
        boto3_session.assert_called_once_with(botocore_session=get_session.return_value)


if __name__ == "__main__":
    unittest.main()

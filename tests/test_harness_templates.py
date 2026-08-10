import json
import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
HARNESS_ROOT = PROJECT_ROOT / "harness_variant" / "strandskbharness"
EXACT_SEMVER = re.compile(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


class HarnessTemplateTests(unittest.TestCase):
    def test_templates_do_not_contain_deployment_account_ids_or_arns(self):
        agentcore_template = json.loads(
            (HARNESS_ROOT / "agentcore" / "agentcore.json.template").read_text()
        )
        targets_template = json.loads(
            (HARNESS_ROOT / "agentcore" / "aws-targets.json.template").read_text()
        )
        harness_template = json.loads(
            (
                HARNESS_ROOT
                / "app"
                / "strands_kb_harness"
                / "harness.json.template"
            ).read_text()
        )
        tool_config_template = json.loads(
            (HARNESS_ROOT / "tools" / "kb_query" / "config.json.template").read_text()
        )

        role_resource = (
            agentcore_template["agentCoreGateways"][0]["targets"][0]["compute"]
            ["iamPolicy"]["Statement"][0]["Resource"]
        )
        self.assertIn("000000000000", role_resource)
        self.assertEqual(targets_template[0]["account"], "000000000000")
        self.assertEqual(harness_template["tools"], [])
        self.assertEqual(harness_template["model"]["temperature"], 0)
        self.assertEqual(harness_template["model"]["maxTokens"], 5000)
        query_schema = (
            agentcore_template["agentCoreGateways"][0]["targets"][0]
            ["toolDefinitions"][0]["inputSchema"]["properties"]["query"]
        )
        self.assertEqual(query_schema["maxLength"], 2000)
        self.assertEqual(
            tool_config_template["KNOWLEDGE_BASE_ID"],
            "<your-kb-id>",
        )
        self.assertIn(
            "<agent-kb-account>",
            tool_config_template["TARGET_ROLE_ARN"],
        )

    def test_cdk_direct_dependencies_are_pinned(self):
        package = json.loads(
            (HARNESS_ROOT / "agentcore" / "cdk" / "package.json").read_text()
        )

        for dependency_group in ("dependencies", "devDependencies"):
            for name, version in package[dependency_group].items():
                with self.subTest(group=dependency_group, dependency=name):
                    self.assertRegex(version, EXACT_SEMVER)


if __name__ == "__main__":
    unittest.main()

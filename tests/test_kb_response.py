# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

import unittest

from harness_variant.strandskbharness.tools.kb_query import kb_response as harness_response
from strands_agent import kb_response as agent_response


def response_with_rows(row_count=3):
    references = []
    for index in range(row_count):
        references.append(
            {
                "content": {
                    "type": "ROW",
                    "row": [
                        {
                            "columnName": "rank",
                            "columnValue": str(index + 1),
                            "type": "LONG",
                        },
                        {
                            "columnName": "name",
                            "columnValue": f"item|{index + 1}",
                            "type": "STRING",
                        },
                    ],
                },
                "location": {
                    "type": "SQL",
                    "sqlLocation": {"query": "SELECT rank, name FROM results"},
                },
            }
        )
    return {
        "output": {"text": "Here are three examples."},
        "citations": [{"retrievedReferences": references}],
    }


class KnowledgeBaseResponseTests(unittest.TestCase):
    def test_variants_format_all_rows_identically(self):
        response = response_with_rows()

        agent_result = agent_response.build_tool_response(
            response, "query", "source"
        )
        harness_result = harness_response.build_tool_response(
            response, "query", "source"
        )

        self.assertEqual(agent_result, harness_result)
        self.assertEqual(agent_result["rowCount"], 3)
        self.assertEqual(agent_result["displayedRowCount"], 3)
        self.assertEqual(agent_result["resultFormat"], "markdown_table")
        self.assertIn("Retrieved 3 rows.", agent_result["answer"])
        self.assertIn("item\\|1", agent_result["answer"])
        self.assertIn("item\\|3", agent_result["answer"])
        self.assertNotIn("three examples", agent_result["answer"])
        self.assertEqual(
            agent_result["sql"], "SELECT rank, name FROM results"
        )

    def test_caps_large_tables_and_reports_counts(self):
        result = agent_response.build_tool_response(
            response_with_rows(102), "query", "source"
        )

        self.assertEqual(result["rowCount"], 102)
        self.assertEqual(result["displayedRowCount"], 100)
        self.assertIn("Showing the first 100 rows", result["answer"])
        self.assertIn("item\\|100", result["answer"])
        self.assertNotIn("item\\|101", result["answer"])

    def test_falls_back_to_generated_answer_without_sql_rows(self):
        response = {
            "output": {"text": "Generated answer"},
            "citations": [{"retrievedReferences": [{"content": {"text": "doc"}}]}],
        }

        result = agent_response.build_tool_response(
            response, "query", "source"
        )

        self.assertEqual(result["answer"], "Generated answer")
        self.assertIn("citations", result)
        self.assertNotIn("resultFormat", result)


if __name__ == "__main__":
    unittest.main()

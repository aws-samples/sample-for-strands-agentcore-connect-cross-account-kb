import unittest

from harness_variant.strandskbharness.tools.kb_query import (
    input_validation as harness_validation,
)
from strands_agent import input_validation as agent_validation


class InputValidationTests(unittest.TestCase):
    def test_variants_accept_and_preserve_valid_queries(self):
        query = "Show revenue by region.\nKeep exact wording."

        self.assertEqual(agent_validation.validate_query(query), query)
        self.assertEqual(harness_validation.validate_query(query), query)

    def test_variants_reject_empty_non_string_and_oversized_queries(self):
        invalid_queries = (
            None,
            123,
            " \t\n",
            "x" * (agent_validation.MAX_QUERY_LENGTH + 1),
        )

        for query in invalid_queries:
            with self.subTest(query_type=type(query).__name__):
                with self.assertRaises(ValueError):
                    agent_validation.validate_query(query)
                with self.assertRaises(ValueError):
                    harness_validation.validate_query(query)

    def test_variants_reject_unsupported_control_characters(self):
        for query in ("hello\x00world", "hello\x1fworld", "hello\x7fworld"):
            with self.subTest(query=repr(query)):
                with self.assertRaises(ValueError):
                    agent_validation.validate_query(query)
                with self.assertRaises(ValueError):
                    harness_validation.validate_query(query)


if __name__ == "__main__":
    unittest.main()

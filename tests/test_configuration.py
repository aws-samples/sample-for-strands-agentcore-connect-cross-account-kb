import json
import os
import tempfile
import unittest

from strands_agent.configuration import config_value, load_sibling_config


class ConfigurationTests(unittest.TestCase):
    def test_environment_value_takes_precedence(self):
        file_config = {"SETTING": "from-file"}

        self.assertEqual(
            config_value(file_config, "SETTING", environ={"SETTING": "from-env"}),
            "from-env",
        )

    def test_empty_environment_value_takes_precedence(self):
        self.assertEqual(
            config_value({"SETTING": "from-file"}, "SETTING", environ={"SETTING": ""}),
            "",
        )

    def test_missing_environment_value_falls_back_to_file(self):
        self.assertEqual(
            config_value({"SETTING": "from-file"}, "SETTING", environ={}),
            "from-file",
        )

    def test_loads_config_beside_module(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            module_path = os.path.join(temp_dir, "module.py")
            config_path = os.path.join(temp_dir, "config.json")
            with open(config_path, "w", encoding="utf-8") as config_file:
                json.dump({"SETTING": "value"}, config_file)

            self.assertEqual(load_sibling_config(module_path), {"SETTING": "value"})


if __name__ == "__main__":
    unittest.main()

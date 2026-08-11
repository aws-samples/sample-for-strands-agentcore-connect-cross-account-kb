# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: MIT-0

"""Shared configuration helpers for the code-based agent variant."""

import json
import os
from typing import Mapping


def load_sibling_config(module_file: str, filename: str = "config.json") -> dict:
    """Load a JSON configuration file stored beside a module."""
    config_path = os.path.join(os.path.dirname(os.path.abspath(module_file)), filename)
    if not os.path.exists(config_path):
        return {}
    with open(config_path, encoding="utf-8") as config_file:
        return json.load(config_file)


def config_value(
    file_config: Mapping[str, object],
    name: str,
    default: object = "",
    environ: Mapping[str, str] | None = None,
):
    """Resolve a setting with environment variables taking precedence."""
    environment = os.environ if environ is None else environ
    if name in environment:
        return environment[name]
    return file_config.get(name, default)

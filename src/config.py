"""Factory configuration loader.

Reads factory.yaml for operator settings, target project config,
and per-node model overrides. Secrets stay in .env — this file
contains only non-sensitive, commitable configuration.
"""

from __future__ import annotations

import logging
import os
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = "factory.yaml"


def load_factory_config(path: str = _DEFAULT_CONFIG_PATH) -> dict[str, Any]:
    """Load factory.yaml, returning empty dict if not found.

    Args:
        path: Path to the YAML config file. Defaults to factory.yaml
            in the current working directory.

    Returns:
        Parsed config dict, or empty dict if file doesn't exist.
    """
    if not os.path.isfile(path):
        logger.info("No factory.yaml found at %s — using defaults", path)
        return {}

    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    if not isinstance(config, dict):
        logger.warning("factory.yaml is not a mapping — ignoring")
        return {}

    logger.info("Loaded factory config from %s", path)
    return config


def get_target_dir(config: dict[str, Any], fallback: str = "./target/") -> str:
    """Extract target.dir from config, with fallback."""
    target = config.get("target", {})
    if isinstance(target, dict):
        return target.get("dir", fallback)
    return fallback


def get_model_config(config: dict[str, Any]) -> dict[str, str | None]:
    """Extract models section, mapping null/missing to None.

    Returns a dict suitable for passing to set_model_config()
    and set_epic_model_config().
    """
    models = config.get("models", {})
    if not isinstance(models, dict):
        return {}
    return {k: (v if v else None) for k, v in models.items()}


def get_git_config(config: dict[str, Any]) -> dict[str, str]:
    """Extract git identity settings."""
    git = config.get("git", {})
    if not isinstance(git, dict):
        return {}
    return {k: str(v) for k, v in git.items() if v}


def get_langsmith_project(config: dict[str, Any]) -> str | None:
    """Extract langsmith.project, or None."""
    ls = config.get("langsmith", {})
    if isinstance(ls, dict):
        return ls.get("project")
    return None

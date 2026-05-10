"""Factory configuration loader.

Reads factory.yaml for operator settings, target project config,
and per-node model overrides. Secrets stay in .env — this file
contains only non-sensitive, commitable configuration.
"""

from __future__ import annotations

import logging
import os
import re
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


def get_reviews_config(config: dict[str, Any]) -> dict[str, bool]:
    """Extract reviews section from config.

    Returns:
        Dict with review flags (e.g. ``{"story_level": True}``).
        Missing keys default to True (reviews enabled).
    """
    reviews = config.get("reviews", {})
    if not isinstance(reviews, dict):
        return {}
    return {k: bool(v) for k, v in reviews.items()}


def get_story_batch_size(
    config: dict[str, Any] | None = None,
    fallback: int = 4,
) -> int:
    """Return ``review.story_batch_size`` from factory.yaml.

    Reads the ``review`` (singular) top-level section, distinct from
    the existing ``reviews`` (plural) section that gates story-level
    reviews. ``0`` disables the batch trigger entirely; any positive
    value is the every-N-stories trigger threshold.

    Args:
        config: Pre-loaded config dict. If None, loads factory.yaml
            from the current working directory on each call. Reading
            on every call is intentional: the operator may edit
            factory.yaml mid-run and the next ``route_next_story``
            call should pick up the new value.
        fallback: Default value when the key is missing or unparseable.

    Returns:
        Non-negative integer. Negative values from config are clamped
        to ``0`` (with a warning); non-integer values fall back to
        ``fallback``.
    """
    if config is None:
        config = load_factory_config()
    review = config.get("review", {})
    if not isinstance(review, dict):
        return fallback
    raw = review.get("story_batch_size", fallback)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning(
            "review.story_batch_size is not an integer (%r) — using default %d",
            raw,
            fallback,
        )
        return fallback
    if value < 0:
        logger.warning(
            "review.story_batch_size %d < 0 — clamping to 0 (disabled)",
            value,
        )
        return 0
    return value


def get_ci_config(config: dict[str, Any]) -> dict[str, Any]:
    """Extract ci section from config.

    Returns a heterogeneous dict — boolean flags
    (``story_level``, ``fix_pre_existing_errors``) plus integer
    timeouts (``bash_timeout_seconds``, ``epic_bash_timeout_seconds``).
    Callers should read the keys they need with their own defaults.
    """
    ci = config.get("ci", {})
    if not isinstance(ci, dict):
        return {}
    int_keys = {"bash_timeout_seconds", "epic_bash_timeout_seconds"}
    out: dict[str, Any] = {}
    for k, v in ci.items():
        if k in int_keys:
            try:
                out[k] = int(v)
            except (TypeError, ValueError):
                logger.warning("ci.%s is not an integer (%r) — ignoring", k, v)
        else:
            out[k] = bool(v)
    return out


def save_ci_fix_pre_existing(
    enabled: bool,
    path: str = _DEFAULT_CONFIG_PATH,
) -> None:
    """Persist ``ci.fix_pre_existing_errors`` to factory.yaml in place.

    Rewrites only that single line so inline comments and surrounding
    structure are preserved. If the key is missing, it is inserted
    directly after the ``ci:`` block header.
    """
    if not os.path.isfile(path):
        logger.warning("Cannot save fix_pre_existing_errors — %s missing", path)
        return

    with open(path, encoding="utf-8") as f:
        lines = f.readlines()

    value = "true" if enabled else "false"
    key_re = re.compile(r"^(\s*)fix_pre_existing_errors:\s*\S+(.*)$")
    ci_header_re = re.compile(r"^ci:\s*$")

    for i, line in enumerate(lines):
        m = key_re.match(line)
        if m:
            indent, trailing = m.group(1), m.group(2)
            lines[i] = f"{indent}fix_pre_existing_errors: {value}{trailing}\n"
            break
    else:
        for i, line in enumerate(lines):
            if ci_header_re.match(line):
                lines.insert(i + 1, f"  fix_pre_existing_errors: {value}\n")
                break
        else:
            lines.append(f"\nci:\n  fix_pre_existing_errors: {value}\n")

    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    logger.info("Saved ci.fix_pre_existing_errors=%s to %s", value, path)


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

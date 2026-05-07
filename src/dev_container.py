"""Shared docker-compose dev-stack utilities.

Used by both:

- ``src.multi_agent.orchestrator`` — for the migration gate dispatch into
  the dev backend container (``_ensure_migrations`` /
  ``_process_migration_project``).
- ``src.adapters.django`` and other stack adapters — for autoformat and
  lint-fix dispatch into the container that bind-mounts the adapter's cwd.

These helpers were originally defined in ``orchestrator.py`` and duplicated
into adapter modules to avoid the import cycle between the orchestrator and
the adapter loader. Extracting them into this dependency-free module
removes the duplication.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from typing import Any

import yaml

logger = logging.getLogger(__name__)


_COMPOSE_FILE_CANDIDATES: tuple[str, ...] = (
    "docker/docker-compose.dev.yml",
    "docker/docker-compose.dev.yaml",
    "docker-compose.dev.yml",
    "docker-compose.dev.yaml",
    "docker-compose.yml",
    "docker-compose.yaml",
)


def find_dev_compose_file(working_dir: str | None) -> str | None:
    """Locate the dev docker-compose file by convention. Returns relative path or None."""
    base = working_dir or "."
    for candidate in _COMPOSE_FILE_CANDIDATES:
        if os.path.isfile(os.path.join(base, candidate)):
            return candidate
    return None


def find_compose_service_for_dir(
    compose_path: str,
    target_search_dir: str,
    working_dir: str | None,
) -> str | None:
    """Find which service in ``compose_path`` bind-mounts ``target_search_dir``.

    Parses the compose YAML and returns the service whose ``volumes:`` entry
    has a host-side bind that resolves to the same directory as the search
    target. Returns None if no service matches.
    """
    base = working_dir or "."
    full_compose_path = os.path.join(base, compose_path)
    compose_dir = os.path.dirname(full_compose_path) or base

    try:
        with open(full_compose_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except (OSError, yaml.YAMLError) as e:
        logger.warning("Could not parse compose file %s: %s", full_compose_path, e)
        return None

    if not isinstance(data, dict):
        return None
    services = data.get("services") or {}
    if not isinstance(services, dict):
        return None

    target_real = os.path.realpath(target_search_dir)

    for service_name, spec in services.items():
        if not isinstance(spec, dict):
            continue
        volumes = spec.get("volumes") or []
        if not isinstance(volumes, list):
            continue
        for vol in volumes:
            if not isinstance(vol, str):
                continue
            host_part = vol.split(":", 1)[0]
            if not host_part:
                continue
            # Named volumes are bare identifiers (no path separators) and
            # should be skipped — they don't bind a host directory.
            if "/" not in host_part and "\\" not in host_part and not os.path.isabs(host_part):
                continue
            if os.path.isabs(host_part):
                resolved = os.path.realpath(host_part)
            else:
                resolved = os.path.realpath(os.path.join(compose_dir, host_part))
            if resolved == target_real:
                return str(service_name)
    return None


def docker_service_running(
    compose_path: str,
    service: str,
    working_dir: str | None,
) -> bool:
    """Return True if the named service's container is in 'running' state.

    'Running but unhealthy' still counts — ``docker compose exec`` works on any
    running container, and we don't need the app's HTTP port to apply migrations
    or run formatters.
    """
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", compose_path, "ps", service,
             "--format", "json"],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("docker compose ps failed for %s: %s", service, e)
        return False

    if result.returncode != 0:
        return False

    output = result.stdout.strip()
    if not output:
        return False

    # Compose emits either a JSON array or JSONL depending on version.
    entries: list[Any] = []
    try:
        if output.startswith("["):
            parsed = json.loads(output)
            if isinstance(parsed, list):
                entries = parsed
        else:
            for line in output.splitlines():
                line_stripped = line.strip()
                if line_stripped:
                    entries.append(json.loads(line_stripped))
    except json.JSONDecodeError:
        return False

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        # `Service` is the compose service name; `Name` is the container name.
        # Match either, since ps output shape varies.
        if entry.get("Service") != service and entry.get("Name") != service:
            continue
        if entry.get("State") == "running":
            return True
    return False


def ensure_docker_service_up(
    compose_path: str,
    service: str,
    working_dir: str | None,
    log_prefix: str = "docker",
) -> bool:
    """Ensure the named service is running, bringing it up via compose if needed.

    Returns True if the service is (or becomes) running. Returns False if the
    service can't be started — in which case the caller should decide whether
    to fall back gracefully or fail loud.

    ``log_prefix`` controls the bracketed tag in the bring-up message
    (e.g. ``"migrations"`` or ``"django"``) so console output is routed to
    the right operator-facing context.
    """
    if docker_service_running(compose_path, service, working_dir):
        return True

    print(
        f"    [{log_prefix}] container '{service}' not running — "
        f"starting via 'docker compose up -d {service}'"
    )
    try:
        result = subprocess.run(
            ["docker", "compose", "-f", compose_path, "up", "-d", service],
            cwd=working_dir,
            capture_output=True,
            text=True,
            timeout=240,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        logger.warning("docker compose up failed for %s: %s", service, e)
        return False

    if result.returncode != 0:
        logger.warning(
            "docker compose up returned %s for %s: %s",
            result.returncode, service, (result.stderr or result.stdout)[:500],
        )
        return False

    return docker_service_running(compose_path, service, working_dir)

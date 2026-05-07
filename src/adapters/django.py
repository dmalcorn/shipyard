"""Django adapter.

Auto-format and lint-fix dispatch into the dev container that bind-mounts
this adapter's ``cwd`` (per the docker-compose.dev.yml topology). The host
is used as a fallback only when no container can be discovered or started
— the rationale is that the dev container has the project's pinned tools
already installed, while the host generally doesn't, and we want
"do as much work in the dev container as possible."

Migration handling is intentionally a no-op here — the existing
``orchestrator._ensure_migrations`` already detects ``manage.py`` and
runs ``python manage.py makemigrations --check`` (with a hermetic
settings overlay if available) before each CI cycle. Layering an
additional Django-side hook in ``autogen_migration_if_schema_touched``
would either duplicate that work or fight it; better to leave the
existing marker-file dispatch alone.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Any

from src.dev_container import (
    ensure_docker_service_up,
    find_compose_service_for_dir,
    find_dev_compose_file,
)

logger = logging.getLogger(__name__)


def _run_bash(
    command: list[str],
    timeout: int = 300,
    cwd: str | None = None,
) -> tuple[bool, str]:
    """Local copy of orchestrator._run_bash to avoid circular imports."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
        )
        stdout = result.stdout or ""
        stderr = result.stderr or ""
        output = stdout + ("\n" + stderr if stderr else "")
        if len(output) > 5000:
            total = len(output)
            marker = f"[truncated: showing last 5000 of {total} chars]\n"
            output = marker + output[-(5000 - len(marker)):]
        return result.returncode == 0, output
    except subprocess.TimeoutExpired:
        return False, f"Command timed out after {timeout}s: {' '.join(command)}"
    except Exception as e:
        return False, f"Command execution failed: {e}"


# Tools to use inside the container, in preference order. Modern Python
# projects use ruff for both lint and format; black is the legacy fallback
# for projects that haven't migrated yet. Each is invoked via `python -m`
# so resolution doesn't depend on a CLI shim being on PATH inside the
# container.
_FORMAT_CMD = (
    "if python -c 'import ruff' >/dev/null 2>&1; then "
    "    python -m ruff format . ; "
    "elif python -c 'import black' >/dev/null 2>&1; then "
    "    python -m black . ; "
    "else "
    "    echo 'Neither ruff nor black is installed in this Python env' >&2 ; "
    "    exit 0 ; "
    "fi"
)
_LINT_FIX_CMD = (
    "if python -c 'import ruff' >/dev/null 2>&1; then "
    "    python -m ruff check --fix . ; "
    "else "
    "    echo 'ruff is not installed in this Python env' >&2 ; "
    "    exit 0 ; "
    "fi"
)


@dataclass
class DjangoAdapter:
    """Django backend. ruff (preferred) / black for format, ruff for lint."""

    cwd: str
    target_dir: str = ""
    name: str = "django"

    # ---- Detection --------------------------------------------------

    def detect(self) -> bool:
        return os.path.isfile(os.path.join(self.cwd, "manage.py"))

    # ---- Dependency install ----------------------------------------

    def install_dependencies_if_missing(self) -> None:
        """Conservative no-op. The dev container's image already has the
        project's pinned Python deps installed at build time; we don't
        shell out to `pip install` against the operator's interpreter.
        """
        return

    # ---- Container dispatch helpers ---------------------------------

    def _container_exec(self, bash_command: str, timeout: int) -> tuple[bool, str] | None:
        """Run ``bash_command`` inside the dev container that bind-mounts
        ``self.cwd``. Returns (success, output) on dispatch, or None when
        no container is found/startable — caller falls back to host.
        """
        if not self.target_dir:
            return None
        compose_path = find_dev_compose_file(self.target_dir)
        if not compose_path:
            return None
        service = find_compose_service_for_dir(
            compose_path, self.cwd, self.target_dir,
        )
        if not service:
            return None
        if not ensure_docker_service_up(
            compose_path, service, self.target_dir, log_prefix=self.name,
        ):
            print(
                f"    [{self.name}] WARNING: could not start '{service}' "
                f"for {self.cwd} — falling back to host"
            )
            return None
        return _run_bash(
            ["docker", "compose", "-f", compose_path, "exec", "-T", service,
             "bash", "-c", bash_command],
            cwd=self.target_dir,
            timeout=timeout,
        )

    # ---- Format / lint ---------------------------------------------

    def autoformat(self) -> tuple[bool, str]:
        """Run the project's auto-formatter on ``self.cwd``.

        Tries the dev container first (via docker-compose service that
        bind-mounts cwd); falls back to host when no container is found
        or can't be started.
        """
        result = self._container_exec(_FORMAT_CMD, timeout=120)
        if result is not None:
            return result
        # Host fallback. Use `python -m` form so we don't depend on a
        # bare `ruff` / `black` shim being on PATH; a Python interpreter
        # that has either module installed is enough.
        return _run_bash(
            ["bash", "-c", _FORMAT_CMD],
            cwd=self.cwd,
            timeout=120,
        )

    def lint_fix(self) -> tuple[bool, str]:
        """Run lint --fix on ``self.cwd``. Same dispatch policy as autoformat."""
        result = self._container_exec(_LINT_FIX_CMD, timeout=180)
        if result is not None:
            return result
        return _run_bash(
            ["bash", "-c", _LINT_FIX_CMD],
            cwd=self.cwd,
            timeout=180,
        )

    # ---- Schema-drift protection -----------------------------------

    def autogen_migration_if_schema_touched(
        self,
        task_id: str,
        changed_files: list[str],
        already_added_migration: bool,
    ) -> tuple[bool, str]:
        """No-op. Django migrations are handled by
        ``orchestrator._ensure_migrations`` which runs the migration check
        (with a hermetic settings overlay if available) before every CI
        cycle when ``manage.py`` is detected.
        """
        return True, ""


def make(ctx: dict[str, Any]) -> DjangoAdapter:
    return DjangoAdapter(
        cwd=ctx["cwd"],
        target_dir=ctx.get("target_dir", ""),
    )

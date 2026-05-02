"""Django adapter.

Auto-format with black + ruff, install Python deps from
``requirements.txt`` / ``requirements-dev.txt``.

Migration handling is intentionally a no-op here — the existing
``orchestrator._ensure_migrations`` already detects ``manage.py`` and
runs ``python manage.py makemigrations`` automatically before each CI
cycle. Layering an additional Django-side hook in
``autogen_migration_if_schema_touched`` would either duplicate that
work or fight it; better to leave the existing marker-file dispatch
alone.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass
from typing import Any

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


@dataclass
class DjangoAdapter:
    """Django backend. Black for format, ruff for lint, manage.py for the rest."""

    cwd: str
    name: str = "django"

    # ---- Detection --------------------------------------------------

    def detect(self) -> bool:
        return os.path.isfile(os.path.join(self.cwd, "manage.py"))

    # ---- Dependency install ----------------------------------------

    def install_dependencies_if_missing(self) -> None:
        """Install requirements*.txt if present and the python env
        looks like it might be missing them (heuristic: no .venv and
        a venv-tracked marker is missing).

        Conservative — when in doubt, skip and let pytest/black surface
        the missing-package error themselves so the operator can fix
        their environment. Auto-pip-install on the operator's host
        machine is intrusive.
        """
        # Intentionally minimal: if a .venv exists in this cwd, do
        # nothing (probably already set up). If no .venv, also do
        # nothing — assume the operator manages their own Python env.
        # The Django adapter does NOT shell out to `pip install`
        # against the operator's interpreter without consent.
        return

    # ---- Format / lint ---------------------------------------------

    def autoformat(self) -> tuple[bool, str]:
        return _run_bash(
            ["bash", "-c", "black ."],
            cwd=self.cwd,
            timeout=120,
        )

    def lint_fix(self) -> tuple[bool, str]:
        return _run_bash(
            ["bash", "-c", "ruff check --fix ."],
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
        ``orchestrator._ensure_migrations`` which runs
        ``python manage.py makemigrations`` before every CI cycle
        when ``manage.py`` is detected.
        """
        return True, ""


def make(ctx: dict[str, Any]) -> DjangoAdapter:
    return DjangoAdapter(cwd=ctx["cwd"])

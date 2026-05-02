"""Node + Drizzle adapter.

Extracts the existing chat2diagram-era behavior from orchestrator.py
into a stack adapter. Covers projects using Node/TypeScript with the
Drizzle ORM for database migrations.

Schema-drift protection (autogen_migration_if_schema_touched) is the
distinguishing feature vs a plain Node adapter. Drizzle requires a
manual ``drizzle-kit generate`` to produce a migration SQL file when
``schema.ts`` changes; without protection, the dev agent can edit
schema.ts without generating the matching SQL, and the prod DB silently
falls behind code expectations. This was the cause of the chat2diagram
``enabled_skill_packs`` and ``comparison_jobs`` incidents — see commit
``f7e0b76`` for the original inline implementation this lifts.
"""

from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


def _run_bash(
    command: list[str],
    timeout: int = 300,
    cwd: str | None = None,
) -> tuple[bool, str]:
    """Local copy of orchestrator._run_bash to avoid circular imports.

    Same semantics: returns (success, output_or_error_message).
    """
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
class NodeDrizzleAdapter:
    """Node + TypeScript + Drizzle. The chat2diagram default."""

    cwd: str
    name: str = "node_drizzle"

    # ---- Detection --------------------------------------------------

    def detect(self) -> bool:
        return os.path.isfile(os.path.join(self.cwd, "package.json"))

    def _has_drizzle_config(self) -> bool:
        return any(
            os.path.isfile(os.path.join(self.cwd, f))
            for f in ("drizzle.config.ts", "drizzle.config.js", "drizzle.config.mjs")
        )

    # ---- Dependency install ----------------------------------------

    def install_dependencies_if_missing(self) -> None:
        if (
            os.path.isfile(os.path.join(self.cwd, "package.json"))
            and not os.path.isdir(os.path.join(self.cwd, "node_modules"))
        ):
            print(f"    [{self.name}] node_modules missing — running npm install")
            ok, out = _run_bash(
                ["bash", "-c", "npm install"], cwd=self.cwd, timeout=600,
            )
            if not ok:
                logger.warning(
                    "[%s] npm install failed (non-blocking): %s",
                    self.name, out[:500],
                )

    # ---- Format / lint ---------------------------------------------

    def autoformat(self) -> tuple[bool, str]:
        return _run_bash(
            ["bash", "-c", "npx prettier --write ."],
            cwd=self.cwd,
            timeout=120,
        )

    def lint_fix(self) -> tuple[bool, str]:
        return _run_bash(
            ["bash", "-c", "npx eslint --fix ."],
            cwd=self.cwd,
            timeout=300,
        )

    # ---- Schema-drift protection -----------------------------------

    def autogen_migration_if_schema_touched(
        self,
        task_id: str,
        changed_files: list[str],
        already_added_migration: bool,
    ) -> tuple[bool, str]:
        """If schema.ts was touched but no new drizzle/*.sql was added,
        run ``npx drizzle-kit generate --name=story_<task_id>``.

        ``changed_files`` paths are relative to the repo root; this
        adapter's cwd may be a subdirectory of that root, in which case
        we strip the relative prefix before checking.
        """
        if not self._has_drizzle_config():
            return True, ""

        if already_added_migration:
            return True, "skipped — migration already added by dev agent"

        # Only consider paths within this adapter's cwd
        cwd_rel = self._cwd_relative_prefix()
        scoped = self._scope_paths(changed_files, cwd_rel)

        schema_touched = any(
            f.endswith("schema.ts") and f.startswith("src/")
            for f in scoped
        )
        if not schema_touched:
            return True, ""

        safe_name = re.sub(r"[^a-z0-9_]+", "_", f"story_{task_id}".lower()).strip("_")
        print(
            f"    [{self.name}] schema.ts modified with no new migration — "
            f"running drizzle-kit generate --name={safe_name}",
        )
        ok, out = _run_bash(
            ["bash", "-c", f"npx drizzle-kit generate --name={shlex.quote(safe_name)}"],
            cwd=self.cwd,
            timeout=180,
        )
        if ok:
            print(f"    [{self.name}] drizzle-kit generate succeeded")
        return ok, out

    # ---- Helpers ---------------------------------------------------

    def _cwd_relative_prefix(self) -> str:
        """Return the path prefix this adapter's cwd has within the repo,
        suitable for filtering ``git diff --name-only HEAD`` paths.

        Returns "" when this adapter owns the repo root.
        """
        # Find the repo root by walking up looking for .git
        check = self.cwd
        for _ in range(5):
            if os.path.isdir(os.path.join(check, ".git")):
                rel = os.path.relpath(self.cwd, check)
                return "" if rel == "." else rel.replace(os.sep, "/") + "/"
            parent = os.path.dirname(check)
            if parent == check:
                break
            check = parent
        return ""

    def _scope_paths(
        self,
        repo_relative_paths: list[str],
        cwd_prefix: str,
    ) -> list[str]:
        """Filter and re-base paths so they are relative to this adapter's cwd."""
        if not cwd_prefix:
            return repo_relative_paths
        out = []
        for p in repo_relative_paths:
            if p.startswith(cwd_prefix):
                out.append(p[len(cwd_prefix):])
        return out


def make(ctx: dict[str, Any]) -> NodeDrizzleAdapter:
    """Factory called by the registry. ``ctx`` has at minimum ``cwd``."""
    return NodeDrizzleAdapter(cwd=ctx["cwd"])

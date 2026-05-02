"""Stack adapter protocol.

An adapter encapsulates the stack-specific bits of the factory's pipeline:
which files are 'schema files', how to install dependencies, how to
auto-format and auto-lint-fix code before commit, and how to generate
a missing migration when the story modified schema files but did not
emit the corresponding SQL.

Adapters are *additive*: a multi-stack project (e.g. Django backend +
Next.js frontend in a monorepo) loads multiple adapters and dispatches
to each in sequence within its owned subdirectory.

Pattern: each adapter is a dataclass holding `cwd` (its owned absolute
path) plus a `name` for logging. The factory's git_commit_node iterates
the adapters and calls the methods below; failures are non-blocking.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@runtime_checkable
class StackAdapter(Protocol):
    """Protocol every concrete adapter implements.

    All methods are called with the adapter's ``cwd`` as the working
    directory; adapters never touch paths outside that subtree. The
    return shape ``(success: bool, output: str)`` mirrors
    ``orchestrator._run_bash`` for easy passthrough.
    """

    name: str
    cwd: str

    def detect(self) -> bool:
        """Return True if this adapter's marker files exist in cwd.

        Used by the registry's auto-detect path; can be skipped when
        adapters are explicitly listed in factory.yaml.
        """
        ...

    def install_dependencies_if_missing(self) -> None:
        """Install language-level deps when marker files exist but the
        installed-deps location does not (e.g. ``package.json`` exists
        but ``node_modules/`` is missing).

        Idempotent — safe to call multiple times. Failures log a
        warning; the pipeline continues.
        """
        ...

    def autoformat(self) -> tuple[bool, str]:
        """Auto-format code in cwd. Non-blocking — caller treats
        failures as warnings.

        Examples: ``npx prettier --write .``, ``black .``.
        """
        ...

    def lint_fix(self) -> tuple[bool, str]:
        """Auto-fix lint issues in cwd. Non-blocking.

        Examples: ``npx eslint --fix .``, ``ruff check --fix .``.
        """
        ...

    def autogen_migration_if_schema_touched(
        self,
        task_id: str,
        changed_files: list[str],
        already_added_migration: bool,
    ) -> tuple[bool, str]:
        """Generate a stack-specific migration file when the story
        modified schema files but did not commit a corresponding
        migration.

        ``changed_files`` is paths from ``git diff --name-only HEAD``,
        relative to the repo root (NOT to this adapter's cwd).

        ``already_added_migration`` is True when the dev agent already
        emitted a migration in this commit — adapters MUST skip in that
        case to avoid generating an additional unwanted migration.

        Adapters whose stack handles migrations elsewhere (e.g. Django
        via the existing ``_ensure_migrations`` marker-file dispatch)
        can return ``(True, "")`` unconditionally — this hook is
        primarily for Drizzle-style frameworks where ``schema.ts``
        changes without a manual ``drizzle-kit generate`` would silently
        ship to production with a missing migration.
        """
        ...


@dataclass
class AdapterContext:
    """Shared state passed to adapters at construction time.

    Lets adapters access factory-managed paths and config without
    threading them through every method call.
    """

    target_dir: str  # absolute path to the target repo root
    cwd: str         # absolute path to this adapter's owned subdir
    name: str        # stack name, e.g. "node_drizzle", "django"


def normalize_stacks(raw_stacks: list[object]) -> list[dict[str, str]]:
    """Normalize the ``target.stacks`` config into a uniform list of dicts.

    Accepts either:
      - String form:  ``["node_drizzle"]``  → ``[{"name": "node_drizzle", "dir": "."}]``
      - Dict form:    ``[{"name": "django", "dir": "backend"}]``
      - Mixed:        ``["node_drizzle", {"name": "django", "dir": "backend"}]``

    Always returns a list of ``{name, dir}`` dicts with both keys present.
    """
    out: list[dict[str, str]] = []
    for entry in raw_stacks:
        if isinstance(entry, str):
            out.append({"name": entry, "dir": "."})
        elif isinstance(entry, dict):
            if "name" not in entry:
                raise ValueError(
                    f"stacks entry missing 'name' field: {entry!r}",
                )
            out.append({"name": entry["name"], "dir": entry.get("dir", ".")})
        else:
            raise ValueError(
                f"stacks entry must be a string or dict, got {type(entry).__name__}: {entry!r}",
            )
    return out

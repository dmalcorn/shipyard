"""Tests for project scaffold structure (Story 1.1)."""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


class TestDirectoryStructure:
    """Verify project directory layout matches architecture doc (AC #2)."""

    @pytest.mark.parametrize(
        "directory",
        [
            "src/agent",
            "src/tools",
            "src/multi_agent",
            "src/context",
            "src/audit_log",
            "scripts",
            "tests",
            "tests/test_tools",
            "tests/test_agent",
            "tests/test_multi_agent",
            "tests/test_context",
        ],
    )
    def test_required_directories_exist(self, directory: str) -> None:
        """Each required directory from architecture doc must exist."""
        assert (PROJECT_ROOT / directory).is_dir(), f"Missing directory: {directory}"

    @pytest.mark.parametrize(
        "init_file",
        [
            "src/__init__.py",
            "src/agent/__init__.py",
            "src/tools/__init__.py",
            "src/multi_agent/__init__.py",
            "src/context/__init__.py",
            "src/audit_log/__init__.py",
            "tests/__init__.py",
            "tests/test_tools/__init__.py",
            "tests/test_agent/__init__.py",
            "tests/test_multi_agent/__init__.py",
            "tests/test_context/__init__.py",
        ],
    )
    def test_init_files_exist(self, init_file: str) -> None:
        """Every Python package directory must have __init__.py."""
        assert (PROJECT_ROOT / init_file).is_file(), f"Missing: {init_file}"

    @pytest.mark.parametrize(
        "gitkeep",
        [
            "logs/.gitkeep",
            "reviews/.gitkeep",
            "checkpoints/.gitkeep",
        ],
    )
    def test_runtime_dirs_have_gitkeep(self, gitkeep: str) -> None:
        """Runtime artifact directories must have .gitkeep for clone persistence."""
        assert (PROJECT_ROOT / gitkeep).is_file(), f"Missing: {gitkeep}"


class TestEnvExample:
    """Verify .env.example contains required variables (AC #3)."""

    def test_env_example_exists(self) -> None:
        """The .env.example file must exist."""
        assert (PROJECT_ROOT / ".env.example").is_file()

    @pytest.mark.parametrize(
        "var",
        [
            "ANTHROPIC_API_KEY",
            "LANGCHAIN_TRACING_V2",
            "LANGCHAIN_API_KEY",
            "LANGCHAIN_PROJECT",
        ],
    )
    def test_env_example_contains_variable(self, var: str) -> None:
        """Each required env var must be present in .env.example."""
        content = (PROJECT_ROOT / ".env.example").read_text()
        assert var in content, f"Missing variable in .env.example: {var}"


class TestPyprojectToml:
    """Verify pyproject.toml configuration (AC #4)."""

    def test_pyproject_toml_exists(self) -> None:
        """pyproject.toml must exist at project root."""
        assert (PROJECT_ROOT / "pyproject.toml").is_file()

    def test_ruff_configured(self) -> None:
        """pyproject.toml must configure ruff."""
        content = (PROJECT_ROOT / "pyproject.toml").read_text()
        assert "[tool.ruff]" in content

    def test_mypy_configured(self) -> None:
        """pyproject.toml must configure mypy."""
        content = (PROJECT_ROOT / "pyproject.toml").read_text()
        assert "[tool.mypy]" in content


class TestDockerFiles:
    """Verify Docker configuration files (AC #5)."""

    def test_dockerfile_exists(self) -> None:
        """Dockerfile must exist at project root."""
        assert (PROJECT_ROOT / "Dockerfile").is_file()

    def test_docker_compose_exists(self) -> None:
        """docker-compose.yml must exist at project root."""
        assert (PROJECT_ROOT / "docker-compose.yml").is_file()


class TestRequirements:
    """Verify requirements.txt contains required dependencies (AC #1)."""

    def test_requirements_exists(self) -> None:
        """requirements.txt must exist at project root."""
        assert (PROJECT_ROOT / "requirements.txt").is_file()

    @pytest.mark.parametrize(
        "package",
        [
            "langgraph",
            "langchain-anthropic",
            "langgraph-checkpoint-sqlite",
            "python-dotenv",
            "fastapi",
            "uvicorn",
        ],
    )
    def test_requirements_contains_dependency(self, package: str) -> None:
        """Each required dependency must be listed in requirements.txt."""
        content = (PROJECT_ROOT / "requirements.txt").read_text()
        assert package in content, f"Missing dependency: {package}"

    def test_requirements_dev_exists(self) -> None:
        """requirements-dev.txt must exist for dev-only dependencies."""
        assert (PROJECT_ROOT / "requirements-dev.txt").is_file()

    @pytest.mark.parametrize("package", ["pytest", "ruff", "mypy"])
    def test_dev_dependency_in_dev_requirements(self, package: str) -> None:
        """Dev dependencies must be in requirements-dev.txt, not requirements.txt."""
        content = (PROJECT_ROOT / "requirements-dev.txt").read_text()
        assert package in content, f"Missing dev dependency: {package}"


class TestMainEntry:
    """Verify src/main.py entry point exists."""

    def test_main_py_exists(self) -> None:
        """src/main.py must exist as the entry point."""
        assert (PROJECT_ROOT / "src/main.py").is_file()

    def test_main_py_has_fastapi_app(self) -> None:
        """src/main.py must create a FastAPI app instance."""
        content = (PROJECT_ROOT / "src/main.py").read_text()
        assert "FastAPI" in content

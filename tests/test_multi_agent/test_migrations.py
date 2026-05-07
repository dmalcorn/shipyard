"""Tests for migration helpers in multi_agent.orchestrator.

Covers the move from host-side makemigrations to container-side via
``docker compose exec``, plus the bring-up-if-down logic for the backend
service.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from src.multi_agent import orchestrator
from src.multi_agent.orchestrator import (
    _docker_service_running,
    _ensure_docker_service_up,
    _ensure_migrations,
    _find_compose_service_for_dir,
    _find_dev_compose_file,
)


def _write_pawprint_compose(target_dir: Path) -> Path:
    """Write a compose file that bind-mounts ../backend into pawprint-backend."""
    docker_dir = target_dir / "docker"
    docker_dir.mkdir(parents=True, exist_ok=True)
    compose_path = docker_dir / "docker-compose.dev.yml"
    compose_path.write_text(
        """\
services:
  pawprint-postgres:
    image: postgres:18
    volumes:
      - pgdata:/var/lib/postgresql
  pawprint-backend:
    build:
      context: ..
      dockerfile: docker/Dockerfile.backend
    volumes:
      - ../backend:/app
  pawprint-staff:
    build:
      context: ..
      dockerfile: docker/Dockerfile.staff
    volumes:
      - ../staff:/app
volumes:
  pgdata:
""",
        encoding="utf-8",
    )
    (target_dir / "backend").mkdir(exist_ok=True)
    (target_dir / "backend" / "manage.py").write_text("# stub", encoding="utf-8")
    return compose_path


# ---------------------------------------------------------------------------
# _find_dev_compose_file
# ---------------------------------------------------------------------------


def test_find_dev_compose_file_finds_docker_dir(tmp_path: Path) -> None:
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    (docker_dir / "docker-compose.dev.yml").write_text("services: {}\n", encoding="utf-8")
    assert _find_dev_compose_file(str(tmp_path)) == "docker/docker-compose.dev.yml"


def test_find_dev_compose_file_falls_back_to_root(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    assert _find_dev_compose_file(str(tmp_path)) == "docker-compose.yml"


def test_find_dev_compose_file_prefers_dev_over_plain(tmp_path: Path) -> None:
    (tmp_path / "docker-compose.dev.yml").write_text("services: {}\n", encoding="utf-8")
    (tmp_path / "docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    assert _find_dev_compose_file(str(tmp_path)) == "docker-compose.dev.yml"


def test_find_dev_compose_file_returns_none_when_absent(tmp_path: Path) -> None:
    assert _find_dev_compose_file(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# _find_compose_service_for_dir
# ---------------------------------------------------------------------------


def test_find_compose_service_matches_bind_volume(tmp_path: Path) -> None:
    _write_pawprint_compose(tmp_path)
    service = _find_compose_service_for_dir(
        "docker/docker-compose.dev.yml",
        str(tmp_path / "backend"),
        str(tmp_path),
    )
    assert service == "pawprint-backend"


def test_find_compose_service_skips_named_volumes(tmp_path: Path) -> None:
    """Named volumes like 'pgdata:/var/lib/postgresql' must not match a search dir
    just because the search dir name happens to coincide with the volume name."""
    _write_pawprint_compose(tmp_path)
    # Search a directory that doesn't exist as a bind-mount source — should not match
    # the named volume `pgdata`
    pgdata_dir = tmp_path / "pgdata"
    pgdata_dir.mkdir()
    service = _find_compose_service_for_dir(
        "docker/docker-compose.dev.yml",
        str(pgdata_dir),
        str(tmp_path),
    )
    assert service is None


def test_find_compose_service_returns_none_when_no_match(tmp_path: Path) -> None:
    _write_pawprint_compose(tmp_path)
    other_dir = tmp_path / "unrelated"
    other_dir.mkdir()
    service = _find_compose_service_for_dir(
        "docker/docker-compose.dev.yml",
        str(other_dir),
        str(tmp_path),
    )
    assert service is None


def test_find_compose_service_handles_unparseable_yaml(tmp_path: Path) -> None:
    docker_dir = tmp_path / "docker"
    docker_dir.mkdir()
    (docker_dir / "docker-compose.dev.yml").write_text(
        "this is: not: valid: yaml: at all:\n  - [", encoding="utf-8"
    )
    service = _find_compose_service_for_dir(
        "docker/docker-compose.dev.yml",
        str(tmp_path / "backend"),
        str(tmp_path),
    )
    assert service is None


# ---------------------------------------------------------------------------
# _docker_service_running
# ---------------------------------------------------------------------------


def _mock_run(returncode: int = 0, stdout: str = "", stderr: str = "") -> Any:
    """Build a mock subprocess.CompletedProcess-like object."""
    class _Result:
        pass
    r = _Result()
    r.returncode = returncode
    r.stdout = stdout
    r.stderr = stderr
    return r


def test_docker_service_running_parses_jsonl(tmp_path: Path) -> None:
    output = json.dumps({"Service": "backend", "Name": "x-backend", "State": "running"})
    with patch.object(orchestrator.subprocess, "run", return_value=_mock_run(stdout=output)):
        assert _docker_service_running("docker-compose.yml", "backend", str(tmp_path)) is True


def test_docker_service_running_parses_array_format(tmp_path: Path) -> None:
    output = json.dumps([{"Service": "backend", "State": "running"}])
    with patch.object(orchestrator.subprocess, "run", return_value=_mock_run(stdout=output)):
        assert _docker_service_running("docker-compose.yml", "backend", str(tmp_path)) is True


def test_docker_service_running_false_when_state_not_running(tmp_path: Path) -> None:
    output = json.dumps({"Service": "backend", "State": "exited"})
    with patch.object(orchestrator.subprocess, "run", return_value=_mock_run(stdout=output)):
        assert _docker_service_running("docker-compose.yml", "backend", str(tmp_path)) is False


def test_docker_service_running_false_on_empty_output(tmp_path: Path) -> None:
    with patch.object(orchestrator.subprocess, "run", return_value=_mock_run(stdout="")):
        assert _docker_service_running("docker-compose.yml", "backend", str(tmp_path)) is False


def test_docker_service_running_false_on_nonzero_exit(tmp_path: Path) -> None:
    with patch.object(
        orchestrator.subprocess, "run",
        return_value=_mock_run(returncode=1, stderr="docker error"),
    ):
        assert _docker_service_running("docker-compose.yml", "backend", str(tmp_path)) is False


def test_docker_service_running_false_on_subprocess_error(tmp_path: Path) -> None:
    def raise_oserror(*_args: Any, **_kwargs: Any) -> Any:
        raise OSError("docker CLI not on PATH")

    with patch.object(orchestrator.subprocess, "run", side_effect=raise_oserror):
        assert _docker_service_running("docker-compose.yml", "backend", str(tmp_path)) is False


# ---------------------------------------------------------------------------
# _ensure_docker_service_up
# ---------------------------------------------------------------------------


def test_ensure_docker_service_up_short_circuits_when_running(tmp_path: Path) -> None:
    """If service already running, no `up` invocation should occur."""
    running_output = json.dumps({"Service": "backend", "State": "running"})
    with patch.object(orchestrator.subprocess, "run") as mock_run:
        mock_run.return_value = _mock_run(stdout=running_output)
        ok = _ensure_docker_service_up("docker-compose.yml", "backend", str(tmp_path))
    assert ok is True
    # Only the initial `ps` should have been called — not `up`
    invoked_commands = [tuple(call.args[0]) for call in mock_run.call_args_list]
    assert all("up" not in cmd for cmd in invoked_commands)


def test_ensure_docker_service_up_brings_up_when_down(tmp_path: Path) -> None:
    """If service not running, run `up -d <service>`, then recheck."""
    running_output = json.dumps({"Service": "backend", "State": "running"})

    call_results = [
        _mock_run(stdout=""),               # 1st ps: not running
        _mock_run(returncode=0, stdout=""), # up: success
        _mock_run(stdout=running_output),   # 2nd ps: running
    ]
    with patch.object(orchestrator.subprocess, "run", side_effect=call_results) as mock_run:
        ok = _ensure_docker_service_up("docker-compose.yml", "backend", str(tmp_path))

    assert ok is True
    invoked_commands = [tuple(call.args[0]) for call in mock_run.call_args_list]
    # Second call should be the up command
    assert invoked_commands[1] == (
        "docker", "compose", "-f", "docker-compose.yml", "up", "-d", "backend",
    )


def test_ensure_docker_service_up_returns_false_when_up_fails(tmp_path: Path) -> None:
    call_results = [
        _mock_run(stdout=""),                                      # not running
        _mock_run(returncode=1, stderr="image build failure"),     # up fails
    ]
    with patch.object(orchestrator.subprocess, "run", side_effect=call_results):
        ok = _ensure_docker_service_up("docker-compose.yml", "backend", str(tmp_path))
    assert ok is False


def test_ensure_docker_service_up_returns_false_when_still_down_after_up(tmp_path: Path) -> None:
    """`up` reports success but the service still isn't running afterward."""
    call_results = [
        _mock_run(stdout=""),               # not running
        _mock_run(returncode=0, stdout=""), # up: success
        _mock_run(stdout=""),               # still not running
    ]
    with patch.object(orchestrator.subprocess, "run", side_effect=call_results):
        ok = _ensure_docker_service_up("docker-compose.yml", "backend", str(tmp_path))
    assert ok is False


# ---------------------------------------------------------------------------
# _ensure_migrations integration
# ---------------------------------------------------------------------------


@pytest.fixture
def captured_run_bash(monkeypatch: pytest.MonkeyPatch) -> list[tuple[list[str], str | None]]:
    """Capture every _run_bash invocation. Returns a list of (cmd, cwd) tuples."""
    calls: list[tuple[list[str], str | None]] = []

    def fake_run_bash(
        command: list[str],
        timeout: int = 300,
        cwd: str | None = None,
    ) -> tuple[bool, str]:
        calls.append((command, cwd))
        # The migration check command always passes (so generate isn't triggered)
        return True, ""

    monkeypatch.setattr(orchestrator, "_run_bash", fake_run_bash)
    return calls


def test_ensure_migrations_wraps_in_docker_exec_when_compose_present(
    tmp_path: Path,
    captured_run_bash: list[tuple[list[str], str | None]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_pawprint_compose(tmp_path)

    # Service is treated as already running so no `up` is needed
    running_output = json.dumps({"Service": "pawprint-backend", "State": "running"})
    monkeypatch.setattr(
        orchestrator.subprocess, "run",
        lambda *_a, **_kw: _mock_run(stdout=running_output),
    )

    _ensure_migrations(str(tmp_path))

    # Find the makemigrations check call
    check_calls = [c for c, _cwd in captured_run_bash if "makemigrations" in c]
    assert check_calls, f"expected a makemigrations call, got: {captured_run_bash}"
    cmd = check_calls[0]
    # Command must be wrapped: docker compose -f <file> exec -T <service> python manage.py ...
    assert cmd[:6] == [
        "docker", "compose", "-f", "docker/docker-compose.dev.yml", "exec", "-T",
    ]
    assert cmd[6] == "pawprint-backend"
    assert cmd[7:11] == ["python", "manage.py", "makemigrations", "--check"]


def test_ensure_migrations_falls_back_to_host_when_no_compose(
    tmp_path: Path,
    captured_run_bash: list[tuple[list[str], str | None]],
) -> None:
    # manage.py at backend/, no compose file anywhere
    (tmp_path / "backend").mkdir()
    (tmp_path / "backend" / "manage.py").write_text("# stub", encoding="utf-8")

    _ensure_migrations(str(tmp_path))

    check_calls = [c for c, _cwd in captured_run_bash if "makemigrations" in c]
    assert check_calls
    cmd = check_calls[0]
    # Host-side: command is just python manage.py makemigrations --check ...
    assert cmd[:4] == ["python", "manage.py", "makemigrations", "--check"]


def test_ensure_migrations_brings_up_container_if_down(
    tmp_path: Path,
    captured_run_bash: list[tuple[list[str], str | None]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_pawprint_compose(tmp_path)

    running_output = json.dumps({"Service": "pawprint-backend", "State": "running"})
    call_sequence = [
        _mock_run(stdout=""),                # 1st ps: not running
        _mock_run(returncode=0, stdout=""),  # up: success
        _mock_run(stdout=running_output),    # 2nd ps: running
    ]
    iter_results = iter(call_sequence)
    monkeypatch.setattr(
        orchestrator.subprocess, "run",
        lambda *_a, **_kw: next(iter_results),
    )

    _ensure_migrations(str(tmp_path))

    check_calls = [c for c, _cwd in captured_run_bash if "makemigrations" in c]
    assert check_calls, "migrate should run after successful bring-up"


def test_ensure_migrations_skips_when_bring_up_fails(
    tmp_path: Path,
    captured_run_bash: list[tuple[list[str], str | None]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If we can't start the container, the step is skipped (fail loud, don't
    silently fall back to host)."""
    _write_pawprint_compose(tmp_path)

    call_sequence = [
        _mock_run(stdout=""),                                  # not running
        _mock_run(returncode=1, stderr="postgres unhealthy"),  # up fails
    ]
    iter_results = iter(call_sequence)
    monkeypatch.setattr(
        orchestrator.subprocess, "run",
        lambda *_a, **_kw: next(iter_results),
    )

    _ensure_migrations(str(tmp_path))

    check_calls = [c for c, _cwd in captured_run_bash if "makemigrations" in c]
    assert not check_calls, (
        "expected NO migration command when container won't start; "
        f"got: {captured_run_bash}"
    )


def test_ensure_migrations_skips_ui_only_django_with_no_databases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A UI-only Django (no DATABASES setting) should be detected by the error
    output and skipped — no spurious 'auto-generating' attempt that just
    re-hits the same config error."""
    _write_pawprint_compose(tmp_path)

    # ps reports running; check command returns a Django ImproperlyConfigured
    # error matching what a no-DB Django emits.
    def fake_run(*args: Any, **_kwargs: Any) -> Any:
        cmd = args[0] if args else _kwargs.get("args", [])
        if "ps" in cmd:
            return _mock_run(
                stdout=json.dumps({"Service": "pawprint-backend", "State": "running"})
            )
        return _mock_run(returncode=0)
    monkeypatch.setattr(orchestrator.subprocess, "run", fake_run)

    captured: list[list[str]] = []

    def fake_run_bash(
        command: list[str],
        timeout: int = 300,
        cwd: str | None = None,
    ) -> tuple[bool, str]:
        captured.append(command)
        if "makemigrations" in command and "--check" in command:
            return False, (
                "django.core.exceptions.ImproperlyConfigured: settings.DATABASES "
                "is improperly configured. Please supply the ENGINE value."
            )
        return True, ""

    monkeypatch.setattr(orchestrator, "_run_bash", fake_run_bash)

    _ensure_migrations(str(tmp_path))

    # Only the --check call should have been made; no auto-generate attempt
    generate_calls = [
        c for c in captured
        if "makemigrations" in c and "--check" not in c
    ]
    assert not generate_calls, (
        f"expected NO auto-generate attempt for no-DB Django; "
        f"got: {generate_calls}"
    )


def test_ensure_migrations_handles_monorepo_with_backend_and_staff(
    tmp_path: Path,
    captured_run_bash: list[tuple[list[str], str | None]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two Django projects (backend/ + staff/) both get processed in one pass —
    the orchestrator no longer stops at the first marker file it finds."""
    _write_pawprint_compose(tmp_path)
    # The fixture writes backend/manage.py; add staff/manage.py too
    (tmp_path / "staff").mkdir(exist_ok=True)
    (tmp_path / "staff" / "manage.py").write_text("# stub", encoding="utf-8")

    # `ps <service>` returns a matching running entry; `up` returns success.
    # Reply based on the command being run so each service's check passes.
    def fake_run(*args: Any, **_kwargs: Any) -> Any:
        cmd = args[0] if args else _kwargs.get("args", [])
        if "ps" in cmd:
            # find the requested service name (last positional arg before --format)
            try:
                service = cmd[cmd.index("ps") + 1]
            except (ValueError, IndexError):
                service = "any"
            return _mock_run(
                stdout=json.dumps({"Service": service, "State": "running"})
            )
        # any other command (e.g., 'up') reports success
        return _mock_run(returncode=0, stdout="")
    monkeypatch.setattr(orchestrator.subprocess, "run", fake_run)

    _ensure_migrations(str(tmp_path))

    # Find which service each makemigrations call targeted
    services_seen: set[str] = set()
    for cmd, _cwd in captured_run_bash:
        if "makemigrations" not in cmd:
            continue
        if cmd[:6] != ["docker", "compose", "-f",
                       "docker/docker-compose.dev.yml", "exec", "-T"]:
            continue
        services_seen.add(cmd[6])

    assert services_seen == {"pawprint-backend", "pawprint-staff"}, (
        f"expected both backend and staff to run makemigrations; "
        f"got services: {services_seen}"
    )

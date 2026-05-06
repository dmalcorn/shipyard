"""Tests for src/main.py — alive FastAPI endpoints and CLI dispatch."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client() -> Generator[TestClient]:
    """TestClient against the FastAPI app."""
    from src.main import app

    yield TestClient(app)


class TestHealthEndpoint:
    """GET /health returns ok."""

    def test_health_returns_ok(self, client: TestClient) -> None:
        """Health endpoint responds 200 with status ok."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestCliArgParsing:
    """CLI argument parsing works correctly."""

    def test_no_flag_starts_server(self) -> None:
        """Without --rebuild, uvicorn.run is called."""
        with (
            patch("sys.argv", ["main"]),
            patch("uvicorn.run") as mock_uvicorn,
        ):
            from src.main import main

            main()
            mock_uvicorn.assert_called_once()


class TestRebuildInterveneEndpoint:
    """POST /rebuild/intervene processes interventions correctly."""

    def test_valid_intervention(self, client: TestClient) -> None:
        """Valid intervention returns 200 with logged=True."""
        response = client.post(
            "/rebuild/intervene",
            json={
                "session_id": "test-session",
                "what_broke": "Tests failed",
                "what_developer_did": "Fixed the import",
                "agent_limitation": "Could not resolve import paths",
                "action": "fix",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["session_id"] == "test-session"
        assert data["action"] == "fix"
        assert data["logged"] is True

    def test_skip_action(self, client: TestClient) -> None:
        """Skip action is accepted and returned."""
        response = client.post(
            "/rebuild/intervene",
            json={
                "session_id": "test-session",
                "what_broke": "Flaky test",
                "what_developer_did": "Skipping",
                "agent_limitation": "Non-deterministic output",
                "action": "skip",
            },
        )
        assert response.status_code == 200
        assert response.json()["action"] == "skip"

    def test_abort_action(self, client: TestClient) -> None:
        """Abort action is accepted and returned."""
        response = client.post(
            "/rebuild/intervene",
            json={
                "session_id": "test-session",
                "what_broke": "Critical failure",
                "what_developer_did": "Aborting rebuild",
                "agent_limitation": "Fundamental issue",
                "action": "abort",
            },
        )
        assert response.status_code == 200
        assert response.json()["action"] == "abort"

    def test_missing_session_id_returns_422(self, client: TestClient) -> None:
        """Missing session_id fails validation."""
        response = client.post(
            "/rebuild/intervene",
            json={
                "what_broke": "Tests failed",
                "what_developer_did": "Fixed",
                "agent_limitation": "Limitation",
                "action": "fix",
            },
        )
        assert response.status_code == 422

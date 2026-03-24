"""Tests for src/main.py — FastAPI endpoints, CLI arg parsing, session persistence."""

from __future__ import annotations

from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage, HumanMessage


@pytest.fixture()
def mock_graph() -> MagicMock:
    """Create a mock graph that returns a fake AI response."""
    mock = MagicMock()
    mock.invoke.return_value = {
        "messages": [
            HumanMessage(content="hello"),
            AIMessage(content="I can help with that."),
        ],
    }
    return mock


@pytest.fixture()
def client(mock_graph: MagicMock) -> Generator[TestClient]:
    """TestClient with mocked graph to avoid real LLM calls."""
    with patch("src.main.graph", mock_graph):
        from src.main import app

        yield TestClient(app)


class TestHealthEndpoint:
    """GET /health returns status ok."""

    def test_health_returns_ok(self, client: TestClient) -> None:
        """Health check returns 200 with status ok."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}


class TestInstructEndpoint:
    """POST /instruct processes instructions and returns correct schema."""

    def test_instruct_returns_correct_schema(
        self, client: TestClient, mock_graph: MagicMock
    ) -> None:
        """Response includes session_id, response, and messages_count."""
        response = client.post("/instruct", json={"message": "hello"})
        assert response.status_code == 200
        data = response.json()
        assert "session_id" in data
        assert "response" in data
        assert "messages_count" in data
        assert data["response"] == "I can help with that."
        assert data["messages_count"] == 2

    def test_instruct_generates_session_id(self, client: TestClient, mock_graph: MagicMock) -> None:
        """When no session_id is provided, one is generated."""
        response = client.post("/instruct", json={"message": "hello"})
        data = response.json()
        assert len(data["session_id"]) == 36  # UUID4 format

    def test_instruct_preserves_session_id(self, client: TestClient, mock_graph: MagicMock) -> None:
        """When session_id is provided, it is returned unchanged."""
        response = client.post(
            "/instruct",
            json={"message": "hello", "session_id": "my-session-42"},
        )
        data = response.json()
        assert data["session_id"] == "my-session-42"

    def test_instruct_passes_thread_id_to_graph(
        self, client: TestClient, mock_graph: MagicMock
    ) -> None:
        """Graph is invoked with the correct thread_id config."""
        client.post(
            "/instruct",
            json={"message": "do stuff", "session_id": "sess-1"},
        )
        call_args = mock_graph.invoke.call_args
        config = call_args[1].get("config") or call_args[0][1]
        assert config["configurable"]["thread_id"] == "sess-1"

    def test_session_resumption_increases_message_count(
        self, client: TestClient, mock_graph: MagicMock
    ) -> None:
        """Sending two requests with the same session_id shows increasing messages."""
        # First call returns 2 messages
        mock_graph.invoke.return_value = {
            "messages": [
                HumanMessage(content="first"),
                AIMessage(content="response 1"),
            ],
        }
        resp1 = client.post(
            "/instruct",
            json={"message": "first", "session_id": "persist-session"},
        )

        # Second call returns 4 messages (accumulated)
        mock_graph.invoke.return_value = {
            "messages": [
                HumanMessage(content="first"),
                AIMessage(content="response 1"),
                HumanMessage(content="second"),
                AIMessage(content="response 2"),
            ],
        }
        resp2 = client.post(
            "/instruct",
            json={"message": "second", "session_id": "persist-session"},
        )

        assert resp1.json()["messages_count"] == 2
        assert resp2.json()["messages_count"] == 4
        assert resp2.json()["messages_count"] > resp1.json()["messages_count"]


class TestCliArgParsing:
    """CLI argument parsing works correctly."""

    def test_cli_flag_parsed(self) -> None:
        """--cli flag is recognized by argparse."""
        from src.main import main

        with patch("sys.argv", ["main", "--cli"]), patch("src.main._run_cli") as mock_cli:
            main()
            mock_cli.assert_called_once()

    def test_no_flag_starts_server(self) -> None:
        """Without --cli, uvicorn.run is called."""
        with (
            patch("sys.argv", ["main"]),
            patch("uvicorn.run") as mock_uvicorn,
        ):
            from src.main import main

            main()
            mock_uvicorn.assert_called_once()


class TestExtractResponse:
    """_extract_response pulls the last AI message content."""

    def test_extracts_last_ai_message(self) -> None:
        """Returns content of the last AIMessage."""
        from src.main import _extract_response

        result = {
            "messages": [
                HumanMessage(content="hi"),
                AIMessage(content="first"),
                AIMessage(content="second"),
            ]
        }
        assert _extract_response(result) == "second"

    def test_returns_empty_on_no_ai_message(self) -> None:
        """Returns empty string when no AIMessage is present."""
        from src.main import _extract_response

        result = {"messages": [HumanMessage(content="hi")]}
        assert _extract_response(result) == ""

    def test_returns_empty_on_no_messages(self) -> None:
        """Returns empty string when messages list is empty."""
        from src.main import _extract_response

        assert _extract_response({"messages": []}) == ""

    def test_handles_list_content(self) -> None:
        """AIMessage with list content (multi-modal) is properly extracted."""
        from src.main import _extract_response

        result = {
            "messages": [
                AIMessage(
                    content=[
                        {"type": "text", "text": "Hello"},
                        {"type": "text", "text": "world"},
                    ]
                ),
            ]
        }
        assert _extract_response(result) == "Hello world"

# Story 1.6: Persistent Server & CLI Entry Point

Status: complete

## Story

As a developer,
I want to interact with Shipyard via HTTP API or CLI, with the agent staying alive between instructions,
so that I can send multiple instructions without restarting the agent.

## Acceptance Criteria

1. **Given** the FastAPI server is running **When** I send `POST /instruct` with `{message: str, session_id?: str}` **Then** the agent processes the instruction and returns `{session_id: str, response: str, messages_count: int}`
2. **Given** an existing `session_id` **When** I send another instruction with the same `session_id` **Then** the agent resumes from its checkpointed state with full conversation history
3. **Given** CLI mode is started with `python src/main.py --cli` **When** I type an instruction **Then** the agent processes it using the same `agent.invoke()` path as the HTTP API
4. **Given** either mode **When** I send a second instruction after the first completes **Then** the agent processes it without restarting — persistent loop confirmed

## Tasks / Subtasks

- [x] Task 1: Implement FastAPI server in `src/main.py` (AC: #1, #2, #4)
  - [x] Create FastAPI app instance
  - [x] Define request model: `InstructRequest(message: str, session_id: str | None = None)`
  - [x] Define response model: `InstructResponse(session_id: str, response: str, messages_count: int)`
  - [x] Implement `POST /instruct` endpoint
  - [x] If no `session_id` provided, generate one (uuid4)
  - [x] Call `graph.invoke()` with `config={"configurable": {"thread_id": session_id}}`
  - [x] Extract agent's final response from state messages
  - [x] Return `InstructResponse` with session_id, response text, message count
- [x] Task 2: Implement CLI mode in `src/main.py` (AC: #3, #4)
  - [x] Parse `--cli` argument with `argparse`
  - [x] Enter interactive loop: `while True: input(">>> ")`
  - [x] Use same `graph.invoke()` call as the HTTP endpoint
  - [x] Use a persistent `session_id` for the CLI session
  - [x] Print agent response to stdout
  - [x] Handle `KeyboardInterrupt` and "exit"/"quit" commands gracefully
- [x] Task 3: Implement entry point routing (AC: #3, #4)
  - [x] `if __name__ == "__main__":` block
  - [x] `--cli` flag → run CLI loop
  - [x] No flag → start uvicorn server on port 8000
  - [x] Load `.env` via `python-dotenv` at startup (`load_dotenv()`)
- [x] Task 4: Create graph factory function (AC: #1, #2)
  - [x] Import `create_agent()` from `src/agent/graph.py`
  - [x] Initialize graph once at module level (both CLI and server share the same compiled graph)
  - [x] SQLite checkpointer path: `checkpoints/shipyard.db`
- [x] Task 5: Add health check endpoint (AC: #1)
  - [x] `GET /health` → returns `{"status": "ok"}`
  - [x] Useful for Docker health checks and deployment verification
- [x] Task 6: Write tests (AC: #1-4)
  - [x] Test FastAPI endpoint with `TestClient` from `fastapi.testclient`
  - [x] Test POST /instruct returns correct response schema
  - [x] Test session resumption: send 2 requests with same session_id, verify messages_count increases
  - [x] Test CLI argument parsing

## Dev Notes

- Both FastAPI and CLI call the exact same `graph.invoke()` — the API is a thin wrapper
- Session persistence comes from SQLite checkpointing (Story 1.4) — the `thread_id` in config is the session key
- `load_dotenv()` must run before any LLM calls to ensure `ANTHROPIC_API_KEY` and `LANGCHAIN_*` vars are loaded
- FastAPI request/response models use Pydantic — keep them simple
- The server must stay alive between requests (FastAPI does this naturally)
- CLI mode uses the same compiled graph instance as the server would
- Port 8000 is the default — matches Dockerfile EXPOSE
- Use `uvicorn.run(app, host="0.0.0.0", port=8000)` for programmatic server start

### Project Structure Notes

- `src/main.py` — single entry point for both modes
- Depends on Stories 1.1-1.5 (scaffold, tools, graph, context injection all must exist)
- This is the story that makes the agent end-to-end functional

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#API Boundary (FastAPI)]
- [Source: _bmad-output/planning-artifacts/architecture.md#Development Workflow]
- [Source: _bmad-output/planning-artifacts/architecture.md#Data Flow]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 1.6: Persistent Server & CLI Entry Point]

## Dev Agent Record

### Agent Model Used
claude-opus-4-6

### Debug Log References
N/A

### Completion Notes List
- Rewrote `src/main.py` from basic server stub to full implementation with POST /instruct, CLI mode, graph init, and load_dotenv
- Both FastAPI and CLI share the same module-level compiled graph instance
- `_extract_response()` helper walks messages in reverse to find last AIMessage
- Graph uses existing `create_agent()` from `src/agent/graph.py` with default checkpoints path
- `os.makedirs("checkpoints", exist_ok=True)` ensures directory exists at startup
- 11 new tests in `tests/test_main.py` covering all ACs — graph is mocked to avoid LLM calls
- Pre-existing mypy errors in `src/agent/nodes.py` (not this story) remain unchanged
- All 168 tests pass, ruff clean, mypy clean on story files

### File List
- `src/main.py` — rewritten: FastAPI app, POST /instruct, CLI mode, graph init, entry point routing
- `tests/test_main.py` — new: 11 tests covering health, instruct, session persistence, CLI parsing, response extraction

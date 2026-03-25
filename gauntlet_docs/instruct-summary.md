# POST /instruct — Detailed Summary

## Overview

The `/instruct` endpoint is Shipyard's **single-turn conversational agent**. It takes a natural-language instruction, runs it through a ReAct (Reasoning + Acting) agent loop backed by Claude, and returns the agent's final response. This is the simplest of Shipyard's three main endpoints — it's one user message in, one agent response out.

**Endpoint:** `POST /instruct`
**Request body** (`InstructRequest`): `{ "message": str, "session_id": str | null }`
**Response** (`InstructResponse`): `{ session_id, response, messages_count }`

## Step-by-Step Flow

### 1. Session Setup

- Generates a UUID session ID if none provided
- Creates a **LangSmith trace config** with metadata: `session_id` as thread ID, role `"dev"`, model tier `"sonnet"`, phase `"implementation"` — these feed into observability/tracing
- Starts the pipeline tracker (`start_pipeline`) and advances to stage `"agent_node"`

### 2. Audit Logging

Creates an `AuditLogger` that writes a structured markdown trace file to `logs/session-{session_id}.md`. The audit log captures:

- Session start timestamp and task description
- Agent start events (role + model)
- Every tool call with file path and SUCCESS/ERROR status
- Session completion summary (agent count, script count, files touched)

### 3. Agent Graph Invocation (the core)

Invokes a **compiled LangGraph StateGraph** with the user's message wrapped as a `HumanMessage`. The graph implements a **ReAct loop**:

```
START → agent → should_continue →  tools → agent → should_continue → ... → END
                                ↘  end → END
                                ↘  error → error_handler → END
```

#### Agent Node (`agent_node`)

- Instantiates `ChatAnthropic` with model `claude-sonnet-4-6` and binds 6 tools
- Builds a **role-aware system prompt** via the 3-layer context injection system:
  - **Layer 1 (always present):** Role-specific prompt template (defaults to "dev") + `coding-standards.md` injected as system context
  - **Layer 2 (per-task):** Optional context files (not used in the `/instruct` API path)
  - **Layer 3 (on-demand):** The agent can use tools to read/search files itself
- Prepends the system prompt to the message list if not already there
- Calls the LLM and increments `retry_count`
- On the first turn, logs agent start to the audit logger

#### Should Continue (routing)

After each agent turn, the router decides:

- **`"tools"`** — if the LLM response contains tool calls, route to the tool node
- **`"end"`** — if the LLM response is a final text answer (no tool calls), terminate
- **`"error"`** — if `retry_count >= 50` (MAX_RETRIES), route to error handler

#### Tool Node (`tool_node`)

- Executes the requested tools via LangGraph's `ToolNode`
- Available tools:
  - **`read_file`** — read a file's contents
  - **`edit_file`** — make surgical string-replacement edits
  - **`write_file`** — write/create a file
  - **`list_files`** — glob-based file listing
  - **`search_files`** — content search (grep-like)
  - **`run_command`** — execute a bash command
- Logs each tool call to the audit logger with tool name, file path, and result status
- Returns tool results back to the agent node for the next reasoning turn

#### Error Handler

If the agent exceeds 50 turns, appends an error message and terminates.

### 4. Session Persistence

The graph is compiled with a **SQLite checkpointer** (`checkpoints/shipyard.db`). Using the same `session_id` across multiple `/instruct` calls resumes the conversation — the full message history is restored from the checkpoint, enabling multi-turn sessions.

### 5. Response Extraction

After the graph completes, `_extract_response` walks the message list in reverse to find the last `AIMessage` with content and returns its text. If the content is a list of blocks (multi-modal), it joins the text blocks.

### 6. Pipeline Completion

Marks the pipeline as `completed` (or `failed` if an exception occurred), ends the audit session, and returns the response.

## Key Characteristics

- **Synchronous** — the endpoint blocks until the agent loop finishes (could be many LLM turns)
- **Stateful** — SQLite checkpointing means the same `session_id` gives multi-turn conversation
- **Tool-equipped** — the agent can read, write, edit files, search code, and run shell commands autonomously
- **Capped** — hard limit of 50 agent turns prevents runaway loops
- **Traced** — every call is traced via LangSmith metadata and logged to a markdown audit file

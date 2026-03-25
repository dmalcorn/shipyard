# MVP Demo Script — Project Shipyard

> Walk through each of the 7 MVP hard-gate requirements. ~3–5 minutes total.
> All demos use `sandbox/` files — no production code is touched.

---

## Setup (before recording)

1. Make sure `.env` is configured with `ANTHROPIC_API_KEY` and `LANGSMITH_API_KEY`
2. Activate the venv: `.venv\Scripts\activate`
3. Have two terminals ready — one for the server, one for curl/CLI
4. Have a browser tab open to LangSmith

---

## Demo Flow

### 1. Persistent Loop (Requirement #1)

**What to show:** The agent starts, stays running, and accepts multiple instructions without restarting.

**Terminal 1 — Start the server:**
```bash
uvicorn src.main:app --reload --port 8000
```

**Say:** "Shipyard runs as a FastAPI server. It stays alive between requests — this isn't fire-and-forget. LangGraph checkpoints save state to SQLite, so the agent can resume even if the container restarts."

**Terminal 2 — Health check:**
```bash
curl http://localhost:8000/health
```
Expected: `{"status": "ok"}`

**Say:** "Server is up. Let's send it some work."

---

### 2. Surgical File Editing (Requirement #2)

**What to show:** The agent makes a targeted edit to a specific function without rewriting the whole file.

**First, show the file before editing:**
```bash
cat sandbox/hello.py
```

**Say:** "Here's our sandbox file — three simple functions. I'm going to ask the agent to change just the `greet` function without touching `add` or `fibonacci`."

**Send the instruction:**
```bash
curl -X POST http://localhost:8000/instruct \
  -H "Content-Type: application/json" \
  -d '{"message": "Edit sandbox/hello.py: change the greet function to return \"Ahoy, {name}! Welcome aboard.\" instead of the current greeting. Do not change any other functions."}'
```

**After response, show the file:**
```bash
cat sandbox/hello.py
```

**Say:** "Only the `greet` function changed. `add` and `fibonacci` are untouched. This is anchor-based exact string replacement — the agent found the specific `old_string`, replaced it with `new_string`, and left everything else alone."

---

### 3. Context Injection (Requirement #3)

**What to show:** The agent accepts external context and uses it to guide its work.

**Send an instruction with injected context:**
```bash
curl -X POST http://localhost:8000/instruct \
  -H "Content-Type: application/json" \
  -d '{"message": "Read sandbox/config_sample.yaml. The deployment team has told us the database port must change from 5432 to 5433 and debug must be set to true. Make both changes."}'
```

**Show the result:**
```bash
cat sandbox/config_sample.yaml
```

**Say:** "The agent received external context — the deployment team's requirements — injected right into the instruction. It used that context to make the correct edits. This is Layer 2 context injection: task-specific information provided at runtime."

---

### 4. Persistent Session (Requirement #1 continued)

**What to show:** Same server, second instruction — no restart needed.

**Say:** "Notice I haven't restarted the server. Let me send another instruction to prove the loop is persistent."

**Send a follow-up:**
```bash
curl -X POST http://localhost:8000/instruct \
  -H "Content-Type: application/json" \
  -d '{"message": "Read sandbox/hello.py and tell me what the greet function currently returns."}'
```

**Say:** "The agent responded immediately — same server, same session. It remembered the file it edited earlier. This is continuous operation, not fire-and-forget."

---

### 5. Tracing (Requirement #4)

**What to show:** Two LangSmith trace links with different execution paths.

**Open browser to the two trace links:**

- Trace 1 (normal run): https://smith.langchain.com/public/9d212cc9-7537-4656-8581-f8c4bc190a98/r
- Trace 2 (error recovery): https://smith.langchain.com/public/114ea778-4414-4e01-aa2a-c97d915e5cc6/r

**Say:** "Every agent run is automatically traced to LangSmith. Here's Trace 1 — a normal execution path where the agent reads a file, edits it, and succeeds. And Trace 2 — an error recovery path where the edit failed because of stale context, the agent re-read the file, and retried successfully. You can see every node, every tool call, every input and output."

**Click into a trace and show:**
- The graph node sequence
- A tool call with its input/output
- Token usage

---

### 6. Accessible via GitHub (Requirement #6)

**Show the README:**
```bash
cat README.md
```

**Say:** "The repo is on GitHub. README has clone instructions, environment setup, and three ways to run: CLI, server, or Docker. Another engineer can clone this and be running in under five minutes."

---

### 7. CODEAGENT.md and PRESEARCH.md (Requirements #5 and #7)

**Show the documents exist and have content:**
```bash
head -30 CODEAGENT.md
head -20 gauntlet_docs/PRESEARCH.md
```

**Say:** "PRESEARCH.md has all 13 pre-search questions answered across three phases — open source research, architecture design, and stack decisions. CODEAGENT.md has the four MVP sections complete: Agent Architecture, File Editing Strategy, Multi-Agent Design, and Trace Links."

---

## Wrap-Up

**Say:** "To recap the seven hard-gate items: the agent runs in a persistent loop, makes surgical edits without rewriting files, accepts and uses injected context, has tracing with two different execution paths, PRESEARCH and CODEAGENT docs are submitted, and it's all accessible on GitHub ready to clone and run."

---

## Reset Sandbox After Demo

Restore sandbox files to their original state:

```bash
git checkout sandbox/
```

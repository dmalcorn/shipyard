---
stepsCompleted: [1, 2, 3, 4, 5, 6]
inputDocuments:
  - gauntlet_docs/PRESEARCH.md
  - gauntlet_docs/shipyard_prd.pdf
  - _bmad-output/planning-artifacts/product-brief-shipyard-2026-03-23.md
workflowType: 'research'
lastStep: 6
research_type: 'technical'
research_topic: 'LangGraph Agent Loop Patterns for Autonomous Coding Agent'
research_goals: 'Understand how to wire a persistent agent loop in LangGraph with Claude, implement custom tools, multi-agent coordination, and LangSmith tracing'
user_name: 'Diane'
date: '2026-03-23'
web_research_enabled: true
source_verification: true
status: complete
---

# Technical Research: LangGraph Agent Loop Patterns for Autonomous Coding Agent

**Date:** 2026-03-23
**Author:** Diane
**Research Type:** Technical Implementation Guide

---

## Research Overview

This research covers the specific LangGraph patterns needed to build Shipyard — an autonomous coding agent with persistent loop, surgical file editing, multi-agent coordination, and LangSmith tracing. The focus is on **implementation-ready patterns** with code examples, not conceptual overviews.

**Research questions:**
1. How to wire a persistent agent loop in LangGraph with Claude
2. How to define and execute custom tools (read_file, edit_file) via ChatAnthropic
3. How to implement multi-agent coordination (parallel sub-agents, subgraphs)
4. How to set up LangSmith tracing
5. State management and checkpointing for persistent sessions

---

## 1. Minimal Installation & Setup

### Packages

```bash
pip install langgraph langchain-anthropic langgraph-checkpoint-sqlite python-dotenv
```

- **langgraph** — core graph orchestration framework
- **langchain-anthropic** — ChatAnthropic integration for Claude
- **langgraph-checkpoint-sqlite** — persistent state checkpointing via SQLite
- **python-dotenv** — load .env file for API keys

### Environment Variables (.env)

```bash
ANTHROPIC_API_KEY=sk-ant-...
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_...
LANGCHAIN_PROJECT=shipyard
```

**Critical:** `LANGCHAIN_TRACING_V2=true` is the flag that activates auto-tracing. Without it, all tracing is a no-op. No code changes needed — LangGraph sends traces to LangSmith automatically once this is set.

### Python Version

Python 3.13+ recommended.

---

## 2. The Core Agent Loop Pattern

### Pattern: ReAct Agent (Reason + Act)

The fundamental pattern is a two-node graph: one node calls the LLM, the other executes tools. A conditional edge routes based on whether the LLM returned tool calls.

```python
from typing import Literal
from typing_extensions import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END, MessagesState
from langgraph.checkpoint.sqlite import SqliteSaver
from langchain_anthropic import ChatAnthropic
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool

# 1. Define tools
@tool
def read_file(file_path: str) -> str:
    """Read the contents of a file at the given path."""
    with open(file_path, 'r') as f:
        return f.read()

@tool
def edit_file(file_path: str, old_string: str, new_string: str) -> str:
    """Replace old_string with new_string in the file. Fails if old_string is not found or not unique."""
    with open(file_path, 'r') as f:
        content = f.read()
    count = content.count(old_string)
    if count == 0:
        return f"ERROR: old_string not found in {file_path}. Re-read the file to get current contents."
    if count > 1:
        return f"ERROR: old_string found {count} times in {file_path}. Provide more context to make the match unique."
    new_content = content.replace(old_string, new_string, 1)
    with open(file_path, 'w') as f:
        f.write(new_content)
    return f"SUCCESS: Replaced in {file_path}"

@tool
def write_file(file_path: str, content: str) -> str:
    """Create or overwrite a file with the given content."""
    import os
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, 'w') as f:
        f.write(content)
    return f"SUCCESS: Wrote {file_path}"

@tool
def list_files(directory: str, pattern: str = "*") -> str:
    """List files in a directory matching a glob pattern."""
    import glob
    import os
    matches = glob.glob(os.path.join(directory, pattern), recursive=True)
    return "\n".join(matches) if matches else "No files found."

@tool
def search_files(directory: str, regex_pattern: str) -> str:
    """Search file contents for a regex pattern. Returns matching lines with file paths."""
    import os, re
    results = []
    for root, dirs, files in os.walk(directory):
        for fname in files:
            fpath = os.path.join(root, fname)
            try:
                with open(fpath, 'r', errors='ignore') as f:
                    for i, line in enumerate(f, 1):
                        if re.search(regex_pattern, line):
                            results.append(f"{fpath}:{i}: {line.rstrip()}")
            except:
                continue
    return "\n".join(results[:50]) if results else "No matches found."

@tool
def run_command(command: str) -> str:
    """Execute a shell command and return stdout + stderr."""
    import subprocess
    result = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=120)
    output = result.stdout + result.stderr
    return output[:5000] if output else "(no output)"

# 2. Set up model with tools
tools = [read_file, edit_file, write_file, list_files, search_files, run_command]
tools_by_name = {t.name: t for t in tools}

llm = ChatAnthropic(model="claude-sonnet-4-6", max_tokens=8096)
llm_with_tools = llm.bind_tools(tools)

# 3. Define graph nodes
SYSTEM_PROMPT = """You are an autonomous coding agent. You can read files, edit files surgically using exact string replacement, write new files, search codebases, and run shell commands.

When editing files:
- Always read a file before editing it
- Use edit_file with old_string (exact match) and new_string
- If an edit fails, re-read the file and retry with correct content
- Never rewrite entire files when a surgical edit will do"""

def agent_node(state: MessagesState):
    """Call the LLM with tools bound."""
    messages = [SystemMessage(content=SYSTEM_PROMPT)] + state["messages"]
    response = llm_with_tools.invoke(messages)
    return {"messages": [response]}

def tool_node(state: MessagesState):
    """Execute all tool calls from the last message."""
    results = []
    for tool_call in state["messages"][-1].tool_calls:
        tool_fn = tools_by_name[tool_call["name"]]
        try:
            observation = tool_fn.invoke(tool_call["args"])
        except Exception as e:
            observation = f"ERROR: {str(e)}"
        results.append(
            ToolMessage(content=str(observation), tool_call_id=tool_call["id"])
        )
    return {"messages": results}

def should_continue(state: MessagesState) -> Literal["tools", "__end__"]:
    """Route: if LLM made tool calls, go to tools. Otherwise, end."""
    last_message = state["messages"][-1]
    if last_message.tool_calls:
        return "tools"
    return "__end__"

# 4. Build the graph
graph_builder = StateGraph(MessagesState)
graph_builder.add_node("agent", agent_node)
graph_builder.add_node("tools", tool_node)

graph_builder.add_edge(START, "agent")
graph_builder.add_conditional_edges("agent", should_continue, ["tools", "__end__"])
graph_builder.add_edge("tools", "agent")

# 5. Compile with checkpointer for persistence
checkpointer = SqliteSaver.from_conn_string("./shipyard_checkpoints.db")
agent = graph_builder.compile(checkpointer=checkpointer)
```

### Key Concepts

- **`MessagesState`** is a built-in TypedDict with a `messages` list. Messages accumulate automatically.
- **`should_continue`** is the conditional edge — it checks if the last LLM response contains `tool_calls`. If yes, route to tool execution. If no, the agent is done.
- **The loop:** `agent → should_continue → tools → agent → should_continue → ...` continues until the LLM responds without tool calls (i.e., it has a final answer or completed the task).
- **`SqliteSaver`** persists state after every node. On restart, invoke with the same `thread_id` to resume.

---

## 3. The Persistent Loop (Accepting Multiple Instructions)

The agent loop above handles ONE instruction. For a persistent loop that accepts multiple instructions without restarting, wrap it in a server or CLI loop:

### Option A: Simple CLI Loop

```python
import uuid
from dotenv import load_dotenv
load_dotenv()

thread_id = str(uuid.uuid4())
config = {"configurable": {"thread_id": thread_id}}

print("Shipyard Agent Ready. Type instructions (or 'quit' to exit):")
while True:
    user_input = input("\n> ")
    if user_input.lower() in ("quit", "exit"):
        break

    result = agent.invoke(
        {"messages": [HumanMessage(content=user_input)]},
        config
    )

    # Print the last message (agent's response)
    last_msg = result["messages"][-1]
    print(f"\nAgent: {last_msg.content}")
```

### Option B: FastAPI Server

```python
from fastapi import FastAPI
from pydantic import BaseModel
import uuid

app = FastAPI()
sessions = {}

class Instruction(BaseModel):
    message: str
    session_id: str | None = None

@app.post("/instruct")
async def instruct(req: Instruction):
    session_id = req.session_id or str(uuid.uuid4())
    config = {"configurable": {"thread_id": session_id}}

    result = agent.invoke(
        {"messages": [HumanMessage(content=req.message)]},
        config
    )

    last_msg = result["messages"][-1]
    return {
        "session_id": session_id,
        "response": last_msg.content,
        "messages_count": len(result["messages"])
    }
```

**Why this satisfies "persistent loop":** The agent runs continuously (FastAPI server stays alive), accepts new instructions via HTTP, and maintains state between requests via `thread_id` + SQLite checkpointing. Fire-and-forget invocations don't count — this is a real persistent loop.

---

## 4. The Simpler Path: `create_react_agent`

LangGraph provides a prebuilt function that replaces the entire graph setup above with a single call:

```python
from langgraph.prebuilt import create_react_agent
from langchain_anthropic import ChatAnthropic
from langgraph.checkpoint.sqlite import SqliteSaver

llm = ChatAnthropic(model="claude-sonnet-4-6")
checkpointer = SqliteSaver.from_conn_string("./shipyard_checkpoints.db")

agent = create_react_agent(
    model=llm,
    tools=[read_file, edit_file, write_file, list_files, search_files, run_command],
    prompt="You are an autonomous coding agent. Always read files before editing...",
    checkpointer=checkpointer,
)

# Use it the same way
config = {"configurable": {"thread_id": "session-1"}}
result = agent.invoke(
    {"messages": [HumanMessage(content="Read main.py and fix the bug")]},
    config
)
```

### `create_react_agent` Key Parameters

| Parameter | Type | Description |
|---|---|---|
| `model` | `ChatModel` or `str` | The LLM. Can be `ChatAnthropic(...)` or `"anthropic:claude-sonnet-4-6"` |
| `tools` | `list` | List of tool functions decorated with `@tool` |
| `prompt` | `str` or `Prompt` | System message injected before user messages |
| `checkpointer` | `Checkpointer` | MemorySaver, SqliteSaver, or PostgresSaver for persistence |
| `state_schema` | `TypedDict` | Custom state schema (default: MessagesState) |
| `pre_model_hook` | `Callable` | Runs before each LLM call (e.g., inject context) |
| `post_model_hook` | `Callable` | Runs after each LLM call (e.g., validate output) |

### Trade-off: `create_react_agent` vs. Custom Graph

- **`create_react_agent`**: Faster to set up, less control. Good for MVP.
- **Custom `StateGraph`**: More control over routing, error handling, multi-agent patterns. Needed for the full pipeline.

**Recommendation for Shipyard MVP:** Start with `create_react_agent` to get the core loop working fast. Refactor to custom `StateGraph` when adding multi-agent coordination.

---

## 5. Context Injection

### Via System Prompt (Layer 1 — Always Present)

```python
def build_system_prompt(context_files: list[str] = None) -> str:
    base_prompt = "You are an autonomous coding agent..."

    if context_files:
        for fpath in context_files:
            with open(fpath, 'r') as f:
                base_prompt += f"\n\n--- Context: {fpath} ---\n{f.read()}"

    return base_prompt
```

### Via `pre_model_hook` (Layer 2 — Task-Specific)

```python
def inject_context(state: MessagesState):
    """Pre-model hook to inject task-specific context."""
    # Read any context files referenced in the task
    # Modify state before it reaches the LLM
    return state

agent = create_react_agent(
    model=llm,
    tools=tools,
    prompt=build_system_prompt(),
    pre_model_hook=inject_context,
    checkpointer=checkpointer,
)
```

### Via User Message (Layer 2 — Per-Instruction)

```python
# When sending an instruction, include context inline
context = open("spec.md").read()
instruction = f"""Context:\n{context}\n\nTask: Implement the login handler per the spec above."""

result = agent.invoke(
    {"messages": [HumanMessage(content=instruction)]},
    config
)
```

---

## 6. Multi-Agent Coordination

### Pattern A: Subgraphs (Sequential Agents)

Each agent is its own compiled graph. A parent graph invokes them as nodes with state transformation:

```python
# Define a review agent as a subgraph
review_llm = ChatAnthropic(model="claude-sonnet-4-6")
review_tools = [read_file, list_files, search_files]  # Read-only!

review_agent = create_react_agent(
    model=review_llm,
    tools=review_tools,
    prompt="You are a code review agent. Read the code and write your analysis to a review file. Do NOT edit source code.",
)

# Define the dev agent as a subgraph
dev_agent = create_react_agent(
    model=ChatAnthropic(model="claude-sonnet-4-6"),
    tools=[read_file, edit_file, write_file, run_command],
    prompt="You are a development agent. Implement code changes as instructed.",
)

# Parent graph orchestrates them
class OrchestratorState(TypedDict):
    task: str
    messages: Annotated[list, operator.add]

def run_dev(state: OrchestratorState):
    result = dev_agent.invoke({"messages": [HumanMessage(content=state["task"])]})
    return {"messages": [f"Dev complete: {result['messages'][-1].content}"]}

def run_review(state: OrchestratorState):
    result = review_agent.invoke(
        {"messages": [HumanMessage(content=f"Review the code changes for: {state['task']}")]}
    )
    return {"messages": [f"Review complete: {result['messages'][-1].content}"]}

orchestrator = StateGraph(OrchestratorState)
orchestrator.add_node("dev", run_dev)
orchestrator.add_node("review", run_review)
orchestrator.add_edge(START, "dev")
orchestrator.add_edge("dev", "review")
orchestrator.add_edge("review", END)
pipeline = orchestrator.compile()
```

### Pattern B: Parallel Agents via `Send` API

```python
import operator
from langgraph.types import Send

class ParallelReviewState(TypedDict):
    code_path: str
    reviews: Annotated[list[str], operator.add]

def fan_out_reviews(state: ParallelReviewState):
    """Spawn two review agents in parallel."""
    return [
        Send("reviewer", {"code_path": state["code_path"], "reviewer_id": "1", "reviews": []}),
        Send("reviewer", {"code_path": state["code_path"], "reviewer_id": "2", "reviews": []}),
    ]

def reviewer_node(state):
    """Each reviewer reads code and produces a review."""
    review_agent_instance = create_react_agent(
        model=ChatAnthropic(model="claude-sonnet-4-6"),
        tools=[read_file, write_file],
        prompt=f"You are Review Agent {state['reviewer_id']}. Read the code and write your review.",
    )
    result = review_agent_instance.invoke(
        {"messages": [HumanMessage(content=f"Review code at: {state['code_path']}")]}
    )
    return {"reviews": [result["messages"][-1].content]}

graph = StateGraph(ParallelReviewState)
graph.add_node("reviewer", reviewer_node)
graph.add_conditional_edges(START, fan_out_reviews, ["reviewer"])
graph.add_edge("reviewer", END)
parallel_review = graph.compile()
```

**Key insight:** The `Send` API creates independent execution paths. Each `Send("reviewer", {...})` runs concurrently. Results are merged back via the `Annotated[list, operator.add]` reducer on the `reviews` field.

### Pattern C: Supervisor Pattern

```python
from langgraph.prebuilt import create_react_agent

# Sub-agents are tools the supervisor can call
dev_agent = create_react_agent(model=llm, tools=[read_file, edit_file, write_file, run_command])
review_agent = create_react_agent(model=llm, tools=[read_file, write_file])

@tool
def delegate_to_dev(task: str) -> str:
    """Delegate a development task to the Dev Agent."""
    result = dev_agent.invoke({"messages": [HumanMessage(content=task)]})
    return result["messages"][-1].content

@tool
def delegate_to_reviewer(task: str) -> str:
    """Delegate a review task to the Review Agent."""
    result = review_agent.invoke({"messages": [HumanMessage(content=task)]})
    return result["messages"][-1].content

# Supervisor treats sub-agents as tools
supervisor = create_react_agent(
    model=ChatAnthropic(model="claude-sonnet-4-6"),
    tools=[delegate_to_dev, delegate_to_reviewer, read_file],
    prompt="You are a supervisor agent. Break tasks into subtasks and delegate to the Dev Agent or Review Agent as appropriate.",
    checkpointer=checkpointer,
)
```

---

## 7. LangSmith Tracing (Zero-Config)

### Setup

Just set environment variables. No code changes needed:

```bash
# .env
LANGCHAIN_TRACING_V2=true
LANGCHAIN_API_KEY=lsv2_pt_your_key_here
LANGCHAIN_PROJECT=shipyard
```

### What Gets Traced Automatically

- Every `StateGraph` node execution (input state, output state, duration)
- Every LLM call (prompt, response, token usage, model, latency)
- Every tool call (name, args, result, duration)
- Conditional edge decisions
- Full message history at each step

### Adding Custom Metadata

```python
config = {
    "configurable": {"thread_id": "session-1"},
    "metadata": {
        "agent_role": "dev",
        "task_id": "story-42",
        "model_tier": "sonnet",
    }
}
result = agent.invoke({"messages": [HumanMessage(content="...")]}, config)
```

### Getting Shareable Trace Links

After running the agent, traces appear in the LangSmith dashboard at `smith.langchain.com`. Each run has a unique URL that can be shared — these are the trace links required for the MVP deliverable.

---

## 8. Checkpointing & State Persistence

### MemorySaver (In-Memory, Development Only)

```python
from langgraph.checkpoint.memory import MemorySaver
checkpointer = MemorySaver()
agent = graph.compile(checkpointer=checkpointer)
```

### SqliteSaver (Persistent, MVP Recommended)

```python
from langgraph.checkpoint.sqlite import SqliteSaver
checkpointer = SqliteSaver.from_conn_string("./checkpoints.db")
agent = graph.compile(checkpointer=checkpointer)
```

### Resuming Sessions

```python
# First invocation
config = {"configurable": {"thread_id": "session-abc"}}
agent.invoke({"messages": [HumanMessage(content="Read main.py")]}, config)

# Later invocation — same thread_id, state is restored automatically
agent.invoke({"messages": [HumanMessage(content="Now edit line 42")]}, config)
# Agent has full context of previous messages and tool results
```

### New Session

```python
# Different thread_id = fresh session
config2 = {"configurable": {"thread_id": "session-def"}}
agent.invoke({"messages": [HumanMessage(content="Start fresh task")]}, config2)
```

---

## 9. Recommended MVP Build Order

Based on this research, here's the fastest path to a working MVP:

1. **Set up project** — `pip install`, `.env` with API keys, verify LangSmith tracing works
2. **Define tools** — `read_file`, `edit_file`, `write_file`, `list_files`, `search_files`, `run_command`
3. **Use `create_react_agent`** — single line to get the core agent loop working with Claude + tools + checkpointing
4. **Add CLI persistent loop** — `while True` loop that accepts instructions and invokes the agent with a persistent `thread_id`
5. **Test surgical editing** — give it a real file, ask it to make a targeted edit, verify it uses `edit_file` not `write_file`
6. **Test context injection** — pass context in the system prompt and in user messages, verify it influences behavior
7. **Add multi-agent** — wrap `create_react_agent` as a subgraph tool for a supervisor, or use the `Send` API for parallel reviewers
8. **Generate LangSmith traces** — run two distinct tasks, grab the shareable trace links
9. **Write CODEAGENT.md** — document architecture and file editing strategy

---

## Sources

- [LangGraph Workflows and Agents Docs](https://docs.langchain.com/oss/python/langgraph/workflows-agents)
- [ChatAnthropic Integration](https://docs.langchain.com/oss/python/integrations/chat/anthropic)
- [LangGraph Multi-Agent Workflows Blog](https://blog.langchain.com/langgraph-multi-agent-workflows/)
- [LangGraph Subgraphs](https://docs.langchain.com/oss/python/langgraph/use-subgraphs)
- [LangSmith Tracing Quickstart](https://docs.langchain.com/langsmith/observability-quickstart)
- [LangSmith Environment Variables](https://support.langchain.com/articles/3567245886-how-do-i-set-up-langsmith-api-key-environment-variables)
- [Claude's Agentic Loop Explained](https://dev.to/ajbuilds/claudes-agentic-loop-explained-stopreason-tooluse-and-the-pattern-behind-every-ai-agent-2l61)
- [LangGraph Send API for Parallel Execution](https://dev.to/sreeni5018/leveraging-langgraphs-send-api-for-dynamic-and-parallel-workflow-execution-4pgd)
- [LangGraph Deep Dive: Stateful Multi-Agent Systems](https://www.mager.co/blog/2026-03-12-langgraph-deep-dive/)
- [LangGraph + Claude Agent SDK Guide](https://www.mager.co/blog/2026-03-07-langgraph-claude-agent-sdk-ultimate-guide/)
- [langgraph-checkpoint-sqlite PyPI](https://pypi.org/project/langgraph-checkpoint-sqlite/)
- [LangGraph Cheatsheet](https://sumanmichael.github.io/langgraph-cheatsheet/cheatsheet/getting-started/)

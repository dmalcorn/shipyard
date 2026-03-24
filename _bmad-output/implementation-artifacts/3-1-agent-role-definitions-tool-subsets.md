# Story 3.1: Agent Role Definitions & Tool Subsets

Status: complete

## Story

As a developer,
I want each agent role (Dev, Test, Reviewer, Architect) to have its own system prompt, model tier, and tool permissions,
so that agents are specialized and constrained to their responsibilities.

## Acceptance Criteria

1. **Given** the roles module **When** a Dev Agent is configured **Then** it uses Sonnet, has full tool access (read, edit, write, glob, grep, bash), and follows the Dev Agent prompt template
2. **Given** the roles module **When** a Test Agent is configured **Then** it uses Sonnet, can write test files and read source, and follows the Test Agent prompt template
3. **Given** the roles module **When** a Review Agent is configured **Then** it uses Sonnet, has read-only access to source + tests, can only write to `reviews/` directory, and follows the Review Agent prompt template
4. **Given** the roles module **When** an Architect Agent is configured **Then** it uses Opus, can read review files, can write fix plan files, cannot edit source, and follows the Architect prompt template
5. **Given** a Review Agent **When** it attempts to call `edit_file` on a source file **Then** the tool returns `ERROR: Permission denied: Review agents cannot edit source files. Write to reviews/ directory only.`

## Tasks / Subtasks

- [x] Task 1: Create `src/multi_agent/roles.py` with role configuration dataclass (AC: #1-#4)
  - [x] Define `AgentRole` dataclass/TypedDict with fields: `name`, `model_tier`, `tools`, `system_prompt`, `write_restrictions`
  - [x] Define role constants: `DEV_ROLE`, `TEST_ROLE`, `REVIEWER_ROLE`, `ARCHITECT_ROLE`, `FIX_DEV_ROLE`
  - [x] Map model tiers: Dev=Sonnet, Test=Sonnet, Reviewer=Sonnet, Architect=Opus, Fix Dev=Sonnet
  - [x] Define tool subsets per role (see Dev Notes below)
- [x] Task 2: Create system prompts per role in `src/agent/prompts.py` (AC: #1-#4)
  - [x] Every prompt follows the 4-section template: Role, Constraints, Process, Output (architecture Pattern 2)
  - [x] Dev Agent prompt: full access, implements code changes, writes source files
  - [x] Test Agent prompt: writes tests in `tests/`, reads source for reference, runs pytest
  - [x] Review Agent prompt: read-only source review, writes findings to `reviews/review-agent-{n}.md` only
  - [x] Architect Agent prompt: reads reviews, writes `fix-plan.md`, cannot edit source
  - [x] Fix Dev Agent prompt: reads fix plan, edits source, runs tests — same tools as Dev
- [x] Task 3: Implement path-restricted `write_file` for Review Agents (AC: #5)
  - [x] Add path validation to `write_file` tool: accept an `agent_role` context parameter
  - [x] When `agent_role == "reviewer"`: only allow writes to paths starting with `reviews/`
  - [x] Return `ERROR: Permission denied: Review agents cannot edit source files. Write to reviews/ directory only.` on violation
  - [x] Similarly restrict `edit_file` for reviewer role — must return same error format
- [x] Task 4: Create tool subset builder function (AC: #1-#4)
  - [x] `get_tools_for_role(role: str) -> list[BaseTool]` returns the correct tool list per role
  - [x] Dev/Fix Dev: `[read_file, edit_file, write_file, list_files, search_files, run_command]`
  - [x] Test: `[read_file, write_file, list_files, search_files, run_command]` (write restricted to `tests/`)
  - [x] Reviewer: `[read_file, list_files, search_files, write_file]` (write restricted to `reviews/`)
  - [x] Architect: `[read_file, list_files, search_files, write_file]` (write restricted to `reviews/` and project root for fix-plan.md)
- [x] Task 5: Write tests in `tests/test_multi_agent/test_roles.py` (AC: #1-#5)
  - [x] Test each role returns correct model tier
  - [x] Test each role returns correct tool subset (by tool name)
  - [x] Test Review Agent `write_file` rejects writes outside `reviews/`
  - [x] Test Review Agent `edit_file` rejects edits on source files
  - [x] Test Dev Agent has unrestricted write access
  - [x] Test path validation error message matches exact expected string

## Dev Notes

- **Primary files:** `src/multi_agent/roles.py` (new), update `src/agent/prompts.py` (add role-specific prompts), update tool files for path validation
- **Path validation approach:** The cleanest way is to create wrapper tools per role that add path checks before delegating to the base tool. This avoids polluting the base tool implementations with role-awareness. Alternatively, use a tool factory pattern: `create_write_file(allowed_paths: list[str])` returns a `@tool`-decorated function with the path restriction baked in.
- **Model tier mapping:** Use the model IDs from project-context.md: Haiku = `claude-haiku-4-5-20251001`, Sonnet = `claude-sonnet-4-6`, Opus = `claude-opus-4-6`
- **Tool interface contract:** All tools follow string-in/string-out with `SUCCESS:`/`ERROR:` prefixes per coding-standards.md
- **Agent prompt template** (from architecture Pattern 2):
  ```
  ## Role
  You are a {role} Agent. {one-sentence identity}.

  ## Constraints
  - {what you CAN do}
  - {what you CANNOT do}

  ## Process
  1. {step 1}
  2. {step 2}

  ## Output
  {what you produce and where it goes}
  ```
- **Inter-agent file format:** All files written by agents must use YAML frontmatter with `agent_role`, `task_id`, `timestamp`, `input_files` per coding-standards.md
- **Do NOT use `create_react_agent`** — all agent graphs use custom `StateGraph`
- **Do NOT use relative imports** — use `from src.multi_agent.roles import ...`

### Tool Subsets Reference

| Role | read_file | edit_file | write_file | list_files | search_files | run_command |
|------|-----------|-----------|------------|------------|--------------|-------------|
| Dev | Yes | Yes | Yes | Yes | Yes | Yes |
| Test | Yes | No | Yes (tests/) | Yes | Yes | Yes |
| Reviewer | Yes | No | Yes (reviews/) | Yes | Yes | No |
| Architect | Yes | No | Yes (reviews/, fix-plan) | Yes | Yes | No |
| Fix Dev | Yes | Yes | Yes | Yes | Yes | Yes |

### Dependencies

- **Requires:** Story 1.2 (File Operation Tools) — base tool implementations exist
- **Requires:** Story 1.3 (Search & Execution Tools) — glob, grep, bash tools exist
- **Requires:** Story 1.5 (Context Injection) — prompt building infrastructure exists
- **Feeds into:** Story 3.2 (Sub-Agent Spawning) — roles are consumed when spawning sub-agents

### Project Structure Notes

- `src/multi_agent/roles.py` — new file, follows architecture doc naming (originally `agents.py`, renamed in architecture validation)
- `src/agent/prompts.py` — extend existing file with role-specific prompt templates
- `tests/test_multi_agent/test_roles.py` — new test file mirroring `src/` structure
- Ensure `src/multi_agent/__init__.py` and `tests/test_multi_agent/__init__.py` exist

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 5: Working Directory and Role Isolation]
- [Source: _bmad-output/planning-artifacts/architecture.md#Pattern 2: Agent Prompt Structure]
- [Source: _bmad-output/planning-artifacts/architecture.md#Pattern 6: Trace Metadata Schema — agent_role values]
- [Source: coding-standards.md#Tool Interface Contract]
- [Source: coding-standards.md#File-Based Communication Format]
- [Source: _bmad-output/project-context.md#Model Routing]

## Dev Agent Record

### Agent Model Used
claude-opus-4-6

### Debug Log References
N/A

### Completion Notes List
- AgentRole frozen dataclass with name, model_tier, tools, system_prompt_key, write_restrictions
- Tool factory pattern via src/tools/restricted.py — creates path-restricted write_file/edit_file wrappers
- get_tools_for_role() swaps base tools with restricted wrappers when role has write_restrictions
- FIX_DEV_AGENT_PROMPT added to prompts.py following Pattern 2 template
- 32 new tests added to test_roles.py (43 total), all passing
- ruff + mypy clean

### File List
- src/multi_agent/roles.py (modified — added AgentRole, role constants, get_role, get_tools_for_role)
- src/agent/prompts.py (modified — added FIX_DEV_AGENT_PROMPT, updated _PROMPTS dict)
- src/tools/restricted.py (new — path-restricted tool factories)
- tests/test_multi_agent/test_roles.py (modified — added 32 new tests)

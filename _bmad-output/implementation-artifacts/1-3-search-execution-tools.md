# Story 1.3: Search & Execution Tools (Glob, Grep, Bash)

Status: complete

## Story

As a developer using the agent,
I want the agent to find files by pattern, search file contents, and run shell commands,
so that the agent can explore the codebase and execute build/test/lint operations.

## Acceptance Criteria

1. **Given** a directory with files **When** the agent calls `list_files(pattern)` with a glob pattern **Then** matching file paths are returned as a `SUCCESS:` string
2. **Given** files with content **When** the agent calls `search_files(pattern, path)` with a regex **Then** matching lines with file paths and line numbers are returned
3. **Given** a valid shell command **When** the agent calls `run_command(command)` **Then** the command executes with a configurable timeout and stdout/stderr are returned
4. **Given** a command that exceeds timeout **When** timeout is hit **Then** the tool returns `ERROR:` with the timeout duration
5. **Given** any tool call **When** an exception occurs **Then** the exception is caught and returned as an `ERROR:` string — no exceptions escape

## Tasks / Subtasks

- [x] Task 1: Implement `list_files` in `src/tools/search.py` (AC: #1, #5)
  - [x] Parameters: `pattern: str`, `path: str = "."` → returns `str`
  - [x] Use `pathlib.Path.glob`
  - [x] Return `SUCCESS: {newline-separated file list}`
  - [x] If no matches: `SUCCESS: No files matching '{pattern}' found in {path}`
  - [x] Truncate output at 5000 chars if too many files
  - [x] Catch all exceptions → `ERROR:` string
  - [x] Decorate with `@tool`
- [x] Task 2: Implement `search_files` in `src/tools/search.py` (AC: #2, #5)
  - [x] Parameters: `pattern: str`, `path: str = "."` → returns `str`
  - [x] Walk directory, search each file with `re.search` line-by-line
  - [x] Return format: `{file_path}:{line_num}: {line_content}` per match
  - [x] Return `SUCCESS: {matches}` or `SUCCESS: No matches for '{pattern}' in {path}`
  - [x] Truncate output at 5000 chars
  - [x] Skip binary files, handle encoding errors gracefully
  - [x] Catch all exceptions → `ERROR:` string
  - [x] Decorate with `@tool`
- [x] Task 3: Implement `run_command` in `src/tools/bash.py` (AC: #3, #4, #5)
  - [x] Parameters: `command: str`, `timeout: str = "30"` → returns `str`
  - [x] Use `subprocess.run(command, shell=True, capture_output=True, text=True, timeout=int(timeout))`
  - [x] Return `SUCCESS: {stdout}` (include stderr if present: `\nSTDERR: {stderr}`)
  - [x] On non-zero exit code: `ERROR: Command failed with exit code {code}: {stderr[:500]}`
  - [x] On timeout: `ERROR: Command timed out after {timeout}s. Consider increasing timeout or breaking into smaller steps.`
  - [x] Catch all exceptions → `ERROR:` string
  - [x] Decorate with `@tool`
- [x] Task 4: Write tests in `tests/test_tools/test_search.py` and `tests/test_tools/test_bash.py` (AC: #1-5)
  - [x] Test `list_files` — matching files, no matches, recursive glob, truncation, exception handling
  - [x] Test `search_files` — regex match with line numbers, no matches, binary file skip, invalid regex, truncation
  - [x] Test `run_command` — successful command, stderr, non-zero exit, timeout, invalid timeout, exception
  - [x] Use `tmp_path` fixture for filesystem tests

## Dev Notes

- All tools follow Tool Interface Contract: string in, string out, `SUCCESS:`/`ERROR:` prefix
- `run_command` uses `shell=True` — this is intentional for agent flexibility, but be aware of security implications (acceptable for a dev tool agent)
- `timeout` parameter is a string (LLM-consumable) — parse to int internally
- `search_files` must handle binary files gracefully — skip files that raise `UnicodeDecodeError`
- Large outputs (>5000 chars) must be truncated per the tool contract
- Error messages must include recovery hints per Pattern 5
- All three tools use `@tool` decorator from `langchain_core.tools`

### Project Structure Notes

- `src/tools/search.py` — glob and grep tools
- `src/tools/bash.py` — shell command execution
- `tests/test_tools/test_search.py` and `tests/test_tools/test_bash.py`
- Story 1.1 must be complete (directory structure exists) before this story starts

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Pattern 1: Tool Interface Contract]
- [Source: _bmad-output/planning-artifacts/architecture.md#Pattern 5: Error Message Format]
- [Source: _bmad-output/planning-artifacts/architecture.md#Complete Project Directory Structure — src/tools/]
- [Source: coding-standards.md#Tool Interface Contract]
- [Source: coding-standards.md#Error Messages Must Be Self-Correcting]

## Dev Agent Record

### Agent Model Used
Claude Opus 4.6

### Debug Log References
N/A

### Completion Notes List
- `list_files`: Uses `pathlib.Path.glob` for pattern matching, supports recursive `**/*.ext` patterns
- `search_files`: Line-by-line regex search with `re.search`, skips binary files via `UnicodeDecodeError` catch, validates regex before walking
- `run_command`: `subprocess.run` with `shell=True`, string timeout parsed to int, stderr appended when present on success
- All tools follow Tool Interface Contract: string in/out, `SUCCESS:`/`ERROR:` prefix, 5000-char truncation
- 82 tests passing (all previous + 15 new)

### File List
- `src/tools/search.py` — list_files, search_files tools
- `src/tools/bash.py` — run_command tool
- `tests/test_tools/test_search.py` — 7 list_files tests, 7 search_files tests
- `tests/test_tools/test_bash.py` — 8 run_command tests

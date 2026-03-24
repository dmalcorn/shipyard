# Story 1.2: File Operation Tools (Read, Edit, Write)

Status: review

## Story

As a developer using the agent,
I want the agent to read files, make surgical edits via exact string replacement, and write new files,
so that the agent can modify code precisely without rewriting entire files.

## Acceptance Criteria

1. **Given** a file exists at a specified path **When** the agent calls `read_file(file_path)` **Then** the file contents are returned as a string prefixed with `SUCCESS:` **And** files exceeding 5000 chars are truncated with a note
2. **Given** a file has been read and contains an exact match for `old_string` **When** the agent calls `edit_file(file_path, old_string, new_string)` **Then** only the matched string is replaced and the result starts with `SUCCESS:`
3. **Given** `old_string` does not exist in the file **When** the agent calls `edit_file` **Then** the tool returns `ERROR: old_string not found in {file_path}. Re-read the file to get current contents.`
4. **Given** `old_string` matches multiple locations in the file **When** the agent calls `edit_file` **Then** the tool returns `ERROR: old_string found {count} times in {file_path}. Provide more surrounding context to make the match unique.`
5. **Given** any path **When** the agent calls `write_file(file_path, content)` **Then** the file is created/overwritten and the result starts with `SUCCESS:`
6. **Given** any tool call **When** an exception occurs **Then** the exception is caught and returned as an `ERROR:` string — no exceptions escape

## Tasks / Subtasks

- [x] Task 1: Implement `read_file` in `src/tools/file_ops.py` (AC: #1, #6)
  - [x] Parameter: `file_path: str` → returns `str`
  - [x] Read file contents, return `SUCCESS: {content}`
  - [x] Truncate at 5000 chars: `SUCCESS: {content[:5000]}\n\n(truncated, {n} chars total)`
  - [x] Handle `FileNotFoundError` → `ERROR: File not found: {file_path}. Use list_files to discover available files.`
  - [x] Catch all other exceptions → `ERROR: Failed to read {file_path}: {e}`
  - [x] Decorate with `@tool`
- [x] Task 2: Implement `edit_file` in `src/tools/file_ops.py` (AC: #2, #3, #4, #6)
  - [x] Parameters: `file_path: str`, `old_string: str`, `new_string: str` → returns `str`
  - [x] Read file, count occurrences of `old_string`
  - [x] 0 matches → `ERROR: old_string not found in {file_path}. Re-read the file to get current contents.`
  - [x] >1 matches → `ERROR: old_string found {count} times in {file_path}. Provide more surrounding context to make the match unique.`
  - [x] Exactly 1 match → replace, write file, return `SUCCESS: Edited {file_path}`
  - [x] Catch all exceptions → `ERROR:` string
  - [x] Decorate with `@tool`
- [x] Task 3: Implement `write_file` in `src/tools/file_ops.py` (AC: #5, #6)
  - [x] Parameters: `file_path: str`, `content: str` → returns `str`
  - [x] Create parent directories if they don't exist (`os.makedirs`)
  - [x] Write content to file, return `SUCCESS: Wrote {len(content)} chars to {file_path}`
  - [x] Catch all exceptions → `ERROR:` string
  - [x] Decorate with `@tool`
- [x] Task 4: Write tests in `tests/test_tools/test_file_ops.py` (AC: #1-6)
  - [x] Test `read_file` — success, file not found, truncation at 5000 chars
  - [x] Test `edit_file` — success, no match, multiple matches, exception handling
  - [x] Test `write_file` — success, creates parent dirs, exception handling
  - [x] Use `tmp_path` pytest fixture for temp file operations

## Dev Notes

- All tools follow the Tool Interface Contract from `coding-standards.md` — string in, string out, `SUCCESS:`/`ERROR:` prefix
- Use `@tool` decorator from `langchain_core.tools` — this is how LangGraph binds tools to Claude
- Docstring format: `"""One-line description. Used by: [which agent roles]."""`
- `edit_file` is the most critical tool in the system — it must be fail-loud, never fuzzy
- `edit_file` does NOT support regex — exact string match only
- `write_file` creates parent directories automatically — agents shouldn't need to mkdir first
- All error messages include a recovery hint telling the LLM what to do next
- Type hints required on all function signatures per coding standards
- Import pattern: `from langchain_core.tools import tool`

### Project Structure Notes

- File: `src/tools/file_ops.py` — tools module for file operations
- Test file: `tests/test_tools/test_file_ops.py`
- These tools will be registered in `src/tools/__init__.py` (can create a basic registry or defer to Story 1.4)

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Pattern 1: Tool Interface Contract]
- [Source: _bmad-output/planning-artifacts/architecture.md#Pattern 5: Error Message Format]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision 5: Working Directory and Role Isolation]
- [Source: coding-standards.md#Tool Interface Contract]
- [Source: coding-standards.md#Error Handling]
- [Source: coding-standards.md#Error Messages Must Be Self-Correcting]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6

### Debug Log References

- Installed `langchain-core` dependency (not yet on system)
- Installed `ruff` and `mypy` (not yet on PATH for bash — used `python -m` invocation)
- Removed unused `os` import flagged by ruff
- Applied ruff auto-format to test file

### Completion Notes List

- Implemented `read_file`, `edit_file`, `write_file` in `src/tools/file_ops.py` following Tool Interface Contract
- All three tools use `@tool` decorator from `langchain_core.tools`, return `SUCCESS:`/`ERROR:` prefixed strings
- `read_file`: reads file, truncates at 5000 chars with total char count note, handles FileNotFoundError with recovery hint
- `edit_file`: exact string match only, fail-loud on 0 matches or >1 matches with self-correcting error messages
- `write_file`: auto-creates parent directories via `os.makedirs`, reports chars written
- 16 tests in `tests/test_tools/test_file_ops.py` covering all ACs: success paths, error paths, edge cases, exception handling, and `@tool` decorator verification
- Quality gate: ruff check ✅, ruff format ✅, mypy strict ✅, pytest 60/60 ✅ (zero regressions)

### File List

- `src/tools/file_ops.py` (new) — read_file, edit_file, write_file tool implementations
- `tests/test_tools/test_file_ops.py` (new) — 16 tests covering AC #1-6

### Change Log

- 2026-03-23: Implemented Story 1.2 — File Operation Tools (read_file, edit_file, write_file) with full test coverage

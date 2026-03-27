# POST /intake — Detailed Summary

## Overview

The intake pipeline is a **two-stage LangGraph pipeline** that converts a directory of project specification documents into a structured, prioritized backlog of epics and stories that the rebuild pipeline can later execute.

**Endpoint:** `POST /intake`
**Request body** (`IntakeRequest`): `{ "spec_dir": str, "session_id": str | null, "target_dir": str = "./target/" }`
**Response** (`IntakeResponse`): `{ session_id, pipeline_status, output_dir, error }`

## Step-by-Step Flow

### 1. Session Setup

Generates a UUID session ID if none provided, creates a task ID (`intake-{first 8 chars}`), starts the pipeline tracker.

### 2. Read Specs (`read_specs` node)

Uses `src/intake/spec_reader.py` to recursively scan the `spec_dir` for documentation files. It:

- Supports `.md`, `.txt`, `.py`, `.json`, `.yaml`, `.yml` extensions
- Reads each file's content, truncating any single file at **5,000 characters**
- Concatenates all files with `## File: {relative_path}` headers into one big string
- Skips symlinks and unreadable files
- Fails the pipeline if the directory doesn't exist, isn't a directory, or contains no readable spec files

The result is stored as `raw_specs` in the pipeline state.

### 3. Summarize Specs (`intake_specs` node) — LLM Stage 1

Spawns a **Dev Agent** (via `run_sub_agent`) with the prompt:

> "Read and summarize these project specifications into a structured spec summary. Identify: features, tech stack, architecture, key behaviors, and acceptance criteria."

The raw specs string is appended to this prompt. The agent produces a `spec_summary` — a structured distillation of what the project is and what it needs.

### 4. Generate Backlog (`create_backlog` node) — LLM Stage 2

Spawns a second **Dev Agent** with the spec summary and a prompt that instructs it to produce a prioritized backlog in a **strict markdown format**:

```
## Epic N: {Title}
### Story N.M: {Title}
**As a** {role}, **I want** {goal}, **so that** {benefit}.
**Acceptance Criteria:**
- **Given** {context} **When** {action} **Then** {outcome}
**Technical Notes:**
- {note}
```

This exact format matters because the downstream `src/intake/backlog.py` parser uses regex to extract epics, stories, descriptions, and BDD acceptance criteria from this markdown. If the format is wrong, the rebuild pipeline can't consume it.

### 5. Write Output (`output` node)

Writes two files to the `output_dir` (defaults to `./target/`):

- **`spec-summary.md`** — the structured spec summary from Stage 1
- **`epics.md`** — the formatted epics/stories backlog from Stage 2

Fails if either output is empty or if the write fails.

### 6. Pipeline Completion

Marks the pipeline as `completed` or `failed` in the pipeline tracker and returns the final state.

## Graph Shape

```
START → read_specs → intake_specs → create_backlog → output → END
```

A strictly linear four-node LangGraph — no branching, no retries, no conditional routing. If any node fails, the pipeline status becomes `"failed"` with an error message, but execution still flows through to the end.

## How It Connects to Rebuild

Intake's output (`epics.md` in the target directory) is exactly what `POST /rebuild` reads as its input. The two pipelines form a **two-phase system**: intake converts human specs into a machine-parseable backlog, then rebuild autonomously implements each story via the TDD orchestrator.

## CLI vs API

Both invoke `run_intake_pipeline()` identically. The CLI (`--intake SPEC_DIR`) prints status to stdout; the API returns a JSON response. Neither has intervention support — intake is a fire-and-forget pipeline.

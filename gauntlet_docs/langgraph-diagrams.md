---
title: Shipyard LangGraph Architecture Diagrams
description: High-level overview and detailed per-graph Mermaid diagrams for all 5 LangGraph StateGraphs
author: Paige (Tech Writer Agent)
date: 2026-03-27
---

# Shipyard LangGraph Architecture

Shipyard uses a **4-level hierarchical** LangGraph architecture plus a standalone intake pipeline. Each level invokes the next as a wrapper node, enabling epic-scale autonomous code generation with TDD, review, and CI gates.

## Table of Contents

- [System Overview](#system-overview)
- [1. Intake Pipeline](#1-intake-pipeline)
- [2. Rebuild Graph (Level 1)](#2-rebuild-graph-level-1)
- [3. Epic Graph (Level 2)](#3-epic-graph-level-2)
- [4. Story Orchestrator (Level 3)](#4-story-orchestrator-level-3)
- [5. Core Agent (Inner Loop)](#5-core-agent-inner-loop)

## System Overview

The overview shows how each graph nests inside the one above it. Solid borders are LangGraph StateGraphs; dashed borders are compiled subgraph invocations.

```mermaid
flowchart TD
    subgraph L0["Intake Pipeline"]
        direction LR
        RS[read_specs] --> IS[intake_specs] --> CB[create_backlog] --> OUT[output]
    end

    subgraph L1["Rebuild Graph · Level 1"]
        direction TB
        PF[preflight_check] --> LB[load_backlog] --> IP[init_project]
        IP --> SE[select_epic]
        SE --> RE["run_epic<br/><i>invokes Level 2</i>"]
        RE --> TE[tag_epic] --> WS[write_status]
        WS -->|more epics| AE[advance_epic] --> SE
        WS -->|all done / aborted| WF[write_final]
        WS -->|paused| WP[write_paused]
    end

    subgraph L2["Epic Graph · Level 2"]
        direction TB
        SS[select_story]
        SS --> RUN["run_story<br/><i>invokes Level 3</i>"]
        RUN --> PR[process_result]
        PR -->|success| AS[advance_story]
        AS -->|more stories| SS
        AS -->|epic done| PER["Epic Post-Processing<br/>(review → analyze → fix → CI)"]
    end

    subgraph L3["Story Orchestrator · Level 3"]
        direction TB
        CS[create_story] --> WT[write_tests] --> IM[implement]
        IM --> CR[code_review] --> CI[run_ci]
        CI -->|pass| GC[git_commit]
        CI -->|retry| FX[fix_ci] --> CI
    end

    subgraph CORE["Core Agent · Inner Loop"]
        direction LR
        AG[agent] -->|tool_calls| TL[tools] --> AG
    end

    L0 -.->|"produces epics.md"| L1
    RE -.->|"compiles & invokes"| L2
    RUN -.->|"compiles & invokes"| L3
    L3 -.->|"LLM nodes use"| CORE

    style L0 fill:#e8f4e8,stroke:#2d7a2d
    style L1 fill:#e8ecf4,stroke:#2d4a7a
    style L2 fill:#f4ece8,stroke:#7a4a2d
    style L3 fill:#f4e8f4,stroke:#7a2d7a
    style CORE fill:#f4f4e8,stroke:#7a7a2d
```

## 1. Intake Pipeline

**Source:** `src/intake/pipeline.py`

A linear, no-retry pipeline that reads project specs and produces `spec-summary.md` and `epics.md`. No checkpointing.

```mermaid
flowchart LR
    START((START)) --> RS["read_specs<br/><i>Read spec files</i>"]
    RS --> IS["intake_specs<br/><i>LLM: summarize specs</i>"]
    IS --> CB["create_backlog<br/><i>LLM: generate epics & stories</i>"]
    CB --> OUT["output<br/><i>Write spec-summary.md<br/>+ epics.md</i>"]
    OUT --> END((END))

    style RS fill:#d4edda
    style IS fill:#fff3cd
    style CB fill:#fff3cd
    style OUT fill:#d4edda
```

**Node types:** Green = Bash/IO, Yellow = LLM (spawns Core Agent via `run_sub_agent`)

## 2. Rebuild Graph (Level 1)

**Source:** `src/intake/rebuild_graph.py`
**Checkpointing:** SQLite at `checkpoints/rebuild.db`

Outer loop that iterates through epics. Supports pause/resume via signal handler and `checkpoints/session.json`.

```mermaid
flowchart TD
    START((START)) --> PF[preflight_check]

    PF -->|"failed"| WF
    PF -->|"continue"| LB[load_backlog]

    LB -->|"failed"| WF
    LB -->|"continue"| IP[init_project]

    IP --> SE[select_epic]
    SE --> RE["run_epic<br/><i>→ EpicGraph (L2)</i>"]
    RE --> TE[tag_epic]
    TE --> WS[write_status]

    WS -->|"more_epics"| AE[advance_epic]
    AE --> SE

    WS -->|"aborted"| WF[write_final]
    WS -->|"all_done"| WF
    WS -->|"paused"| WP[write_paused]

    WF --> END((END))
    WP --> END

    style PF fill:#d4edda
    style LB fill:#d4edda
    style IP fill:#d4edda
    style SE fill:#d4edda
    style RE fill:#cce5ff,stroke:#004085
    style TE fill:#d4edda
    style WS fill:#d4edda
    style AE fill:#d4edda
    style WF fill:#d4edda
    style WP fill:#d4edda
```

**Legend:** Blue = wrapper node (invokes subgraph), Green = Bash/logic

**Routing functions:**

- `route_after_load_backlog` — checks `pipeline_status == "failed"` (reused for both preflight and load_backlog)
- `route_after_epic` — checks epic status, pause signal, and remaining epics

## 3. Epic Graph (Level 2)

**Source:** `src/intake/epic_graph.py`
**Special features:** LangGraph `Send` API for parallel fan-out, `interrupt()` for human-in-the-loop

The most complex graph. Two distinct phases: a story iteration loop, then epic-level post-processing with dual-track code review.

```mermaid
flowchart TD
    START((START)) --> SS[select_story]
    SS --> RUN["run_story<br/><i>→ Orchestrator (L3)</i>"]
    RUN --> PR[process_result]

    PR -->|"next_story"| AS[advance_story]
    PR -->|"aborted"| END1((END))

    AS -->|"more_stories"| SS
    AS -->|"paused"| EP[epic_paused]
    AS -->|"epic_done"| PREP[prepare_epic_reviews]

    EP --> END2((END))

    PREP -->|"Send API ×2"| ERN["epic_review_node<br/><i>BMAD reviewer</i>"]
    PREP -->|"Send API ×2"| ERN2["epic_review_node<br/><i>Claude reviewer</i>"]

    ERN --> CER[collect_epic_reviews]
    ERN2 --> CER

    CER --> AR[analyze_reviews]
    AR --> FCA[fix_category_a]

    FCA -->|"has_category_b"| EA[epic_architect]
    FCA -->|"no_category_b"| ECI

    EA -->|"needs_fix"| EF[epic_fix]
    EA -->|"no_fix"| ECI

    EF --> ECI[epic_ci]

    ECI -->|"pass"| EGC[epic_git_commit]
    ECI -->|"error"| EER[epic_error]

    EGC --> EC[epic_complete]
    EC --> END3((END))
    EER --> END4((END))

    style RUN fill:#cce5ff,stroke:#004085
    style ERN fill:#fff3cd
    style ERN2 fill:#fff3cd
    style AR fill:#fff3cd
    style FCA fill:#fff3cd
    style EA fill:#e8d4f4,stroke:#6a0dad
    style EF fill:#fff3cd
    style ECI fill:#d4edda
    style EGC fill:#d4edda
    style EP fill:#f8d7da
```

**Legend:** Blue = wrapper node (invokes subgraph), Yellow = LLM agent, Purple = Architect (Opus model), Green = Bash, Red = terminal/pause

**Routing functions:**

- `route_after_story_result` — completed → next_story, failed → aborted
- `route_next_story` — checks pause signal, remaining stories
- `route_to_epic_reviewers` — returns `Send()` list for parallel fan-out
- `route_after_category_a` — Category B items exist?
- `route_after_epic_architect` — fixes needed?
- `route_after_epic_ci` — pass or error

**Parallel review via Send API:**

```mermaid
flowchart LR
    PREP[prepare_epic_reviews] -->|"Send(bmad)"| R1["epic_review_node<br/>BMAD 3-layer adversarial"]
    PREP -->|"Send(claude)"| R2["epic_review_node<br/>Claude integration review"]
    R1 --> COL[collect_epic_reviews]
    R2 --> COL

    style R1 fill:#fff3cd
    style R2 fill:#fff3cd
```

## 4. Story Orchestrator (Level 3)

**Source:** `src/multi_agent/orchestrator.py`
**Retry limits:** MAX_CI_CYCLES = 4

The per-story TDD pipeline. Each LLM node invokes a specific BMAD agent via `invoke_bmad_agent()`. Bash nodes run tests and CI without LLM involvement.

```mermaid
flowchart TD
    START((START)) --> CS["create_story<br/><i>bmad-create-story</i>"]

    CS -->|"continue"| WT["write_tests<br/><i>bmad-testarch-atdd</i>"]
    CS -->|"error"| ERR

    WT -->|"continue"| IM["implement<br/><i>bmad-dev-story</i>"]
    WT -->|"error"| ERR

    IM -->|"continue"| CR["code_review<br/><i>bmad-dev (CR mode)</i>"]
    IM -->|"error"| ERR

    CR -->|"continue"| CI["run_ci<br/><i>Bash: local_ci.sh<br/>or npm test / pytest</i>"]
    CR -->|"error"| ERR

    CI -->|"pass"| GC["git_commit<br/><i>Bash: git add + commit</i>"]
    CI -->|"retry"| FX["fix_ci<br/><i>bmad-dev (CI fix mode)</i>"]
    CI -->|"error"| ERR

    FX --> CI

    GC --> END((END))
    ERR[error_handler] --> END

    style CS fill:#fff3cd
    style WT fill:#fff3cd
    style IM fill:#fff3cd
    style CR fill:#fff3cd
    style FX fill:#fff3cd
    style CI fill:#d4edda
    style GC fill:#d4edda
    style ERR fill:#f8d7da
```

**Legend:** Yellow = LLM (BMAD agent), Green = Bash (no LLM), Red = error terminal

**Routing functions:**

- `route_after_llm_node` — checks `pipeline_status == "failed"` (reused for all LLM nodes)
- `route_after_ci` — pass / retry (if under MAX_CI_CYCLES) / error

**Tool scoping per phase:**

| Node | BMAD Agent | Tool Set |
|------|-----------|----------|
| create_story | bmad-create-story | TOOLS_SM |
| write_tests | bmad-testarch-atdd | TOOLS_TEA |
| implement | bmad-dev-story | TOOLS_DEV |
| code_review | bmad-dev | TOOLS_CODE_REVIEW |
| fix_ci | bmad-dev | TOOLS_CI_FIX |

## 5. Core Agent (Inner Loop)

**Source:** `src/agent/graph.py`
**Checkpointing:** SQLite at `checkpoints/shipyard.db`

The foundational ReAct loop. Called by BMAD agent invocations in the orchestrator and by `run_sub_agent()` in the intake pipeline.

```mermaid
flowchart TD
    START((START)) --> AG["agent<br/><i>LLM call with<br/>bound tools</i>"]

    AG -->|"tool_calls present"| TL["tools<br/><i>Execute tool calls,<br/>log to audit</i>"]
    AG -->|"no tool_calls"| END((END))
    AG -->|"retry >= 50"| ERR[error_handler]

    TL --> AG

    ERR --> END

    style AG fill:#fff3cd
    style TL fill:#d4edda
    style ERR fill:#f8d7da
```

**Routing function:** `should_continue` — checks for tool_calls (→ tools), retry limit exceeded (→ error), or completion (→ end)

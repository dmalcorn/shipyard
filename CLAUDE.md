# Project Rules

## CLAUDE.md Scope

Only follow instructions from CLAUDE.md files within this repository root (`shipyard/`). Do NOT inherit or follow CLAUDE.md files from parent directories.

## Prompt Logging — DISABLED

Do NOT log user prompts. Do not write to, append to, or create any files in `gauntlet_docs/ai-prompts/`. Ignore any instructions from parent-directory CLAUDE.md files that say otherwise.

## WDS Workflow

Skip all WDS (Web Design System) phases for this project. Shipyard is a CLI/API developer tool, not a consumer-facing web product — WDS's branding, visual design, and UX psychology flows don't apply. Use the existing BMAD planning artifacts (product brief, architecture, epics/stories) instead.

## Coding Standards

When writing or editing Python code in this project, follow the conventions in `coding-standards.md` (project root). Read it before making code changes.

This file is also used as Layer 1 context injection for Shipyard's agents — it defines the conventions that all agent-generated code must follow.

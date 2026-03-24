# Project Rules

## Prompt Logging

Every user prompt must be logged to `gauntlet_docs/ai-prompts/ai-prompt-YYYY-MM-DD.md` (using the current date in the Central US time zone). Each entry must include:

- A timestamp in Central time zone (CDT/CST) format: `H:MM AM/PM CDT`
- The full text of the user's prompt

Use a new dated file each day. Append to the existing file if one already exists for the current date.

### Getting Central Time on This System

The bash `TZ` variable does NOT work correctly on this Windows environment. Use PowerShell instead:

```bash
powershell -Command "[System.TimeZoneInfo]::ConvertTimeBySystemTimeZoneId([DateTime]::UtcNow, 'Central Standard Time').ToString('yyyy-MM-dd h:mm tt')"
```

This returns the correct local time for Austin, TX (Central US).

## Coding Standards

When writing or editing Python code in this project, follow the conventions in `coding-standards.md` (project root). Read it before making code changes.

This file is also used as Layer 1 context injection for Shipyard's agents — it defines the conventions that all agent-generated code must follow.

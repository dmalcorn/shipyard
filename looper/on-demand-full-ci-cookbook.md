# On-Demand Full CI - Cookbook

**Script:** `looper/on-demand-full-ci.sh`

---

## What This Script Does

This script runs the full CI (Continuous Integration) pipeline for PetCompass and **automatically tries to fix any problems it finds**. Think of it as a code quality check that cleans up after itself.

The CI pipeline checks four things:
1. **Lint (ruff)** — code style and formatting issues
2. **Type checking (mypy)** — type annotation errors
3. **Security scan (bandit)** — potential security vulnerabilities
4. **Tests (pytest)** — unit and integration test failures

If any of these fail, the script calls Claude (the AI) to read the errors and fix them automatically. It then re-runs the CI pipeline to verify the fixes worked. It will retry up to **4 times** before giving up.

---

## When to Use This Script

Use this **after making code changes** — especially UI or design changes — to make sure nothing is broken before deploying. Common scenarios:

- You've made changes to the frontend or backend and want to verify everything passes
- You're about to deploy and want a clean bill of health
- You've been editing code and aren't sure if you introduced any issues
- After pulling new code from GitHub to make sure the codebase is healthy

---

## Prerequisites

- **Claude CLI** must be installed and available on your PATH
- **Docker** must be running (the script resets database connections via Docker)
- **`make`** must be available (the CI pipeline is run via `make ci`)
- Run from the **project root directory** (the script auto-detects it, but it's good practice)

---

## How to Run It

```bash
./looper/on-demand-full-ci.sh
```

That's it — no prompts, no options to choose. It just runs.

---

## What You'll See

### Startup

```
  =====================================
  ON-DEMAND FULL CI
  PetCompass CI Pipeline
  =====================================

  Security: Using scoped --allowedTools
```

The "scoped --allowedTools" message means the AI is restricted to only the tools it needs for fixing code — it can't do anything dangerous.

### CI Running

```
[INFO] Starting full CI pipeline (make ci)...
[INFO] Max attempts: 4
[INFO] CI attempt 1 of 4
[DB] Resetting idle database connections...
[DB] Terminated 3 idle connections
```

The database connection reset happens before each attempt. This prevents a common issue where stale connections pile up and cause "too many clients" errors.

### If CI Passes (Best Case)

```
[SUCCESS] CI passed! (2m 15s)

========================================
Full CI pipeline completed successfully!
========================================
```

You're done! Everything is clean.

### If CI Fails

The script shows a summary of what went wrong:

```
=== CI FAILURE SUMMARY ===
Lint Errors (ruff):
  - backend/accounts/views.py:42:1: E302 expected 2 blank lines
  - backend/recipes/serializers.py:15:80: E501 line too long

Test Failures (pytest):
  - FAILED tests/test_profiles.py::test_create_profile

=== END FAILURE SUMMARY ===
```

Then it pauses 15 seconds and calls Claude to fix the issues:

```
[INFO] Pausing 15 seconds before invoking Claude to fix CI issues...
[INFO] Invoking DEV agent to fix CI issues...
```

After Claude makes fixes, it runs CI again:

```
[INFO] CI attempt 2 of 4
```

### If All Attempts Fail

```
[ERROR] CI failed after 4 attempts
[ERROR] ========================================
[ERROR] Full CI pipeline failed. Please investigate.
[ERROR] ========================================
```

This means the problems are too complex for automatic fixing. You'll need to look at the log file or ask for help.

---

## Stopping the Script

Press **Ctrl+C** at any time. The script handles this gracefully — it stops whatever is running and exits cleanly.

```
[INFO] Shutting down On-Demand CI...
[INFO] Log saved to: looper/on-demand-full-ci.log
```

---

## Log File

Everything is logged to:

```
looper/on-demand-full-ci.log
```

This includes timestamps, CI output, failure summaries, and the full output from Claude's fix attempts. If you need to share what happened with someone, this file has the complete history.

---

## Quick Reference

| What | Detail |
|---|---|
| Run it | `./looper/on-demand-full-ci.sh` |
| Stop it | **Ctrl+C** |
| Max retry attempts | 4 |
| Log file | `looper/on-demand-full-ci.log` |
| What it checks | Lint (ruff), types (mypy), security (bandit), tests (pytest) |

---

## Troubleshooting

### "Claude CLI not found"
The Claude CLI needs to be installed. This is the command-line tool that lets scripts call Claude.

### "make not found"
The `make` build tool isn't installed. On most Linux systems: `sudo apt install make`.

### Database connection errors during CI
The script automatically resets idle database connections before each run. If you still get connection errors, make sure the PostgreSQL Docker container is running:
```bash
docker ps | grep petcompass_db
```

### CI keeps failing after 4 attempts
Some issues are too complex for automatic fixing. Check the log file (`looper/on-demand-full-ci.log`) to see what's failing, and fix it manually or ask for help. The failure summary at the end of each attempt tells you exactly which checks failed and why.

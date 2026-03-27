#!/usr/bin/env bash
# Auto-generated CI script (Python project) — customise as needed.
set -euo pipefail

STORY_FILTER=""
QUICK_MODE=false
TEST_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --story)  STORY_FILTER="$2"; shift 2 ;;
        --quick)  QUICK_MODE=true; shift ;;
        --test)   TEST_ONLY=true; shift ;;
        *)        shift ;;
    esac
done

# --- Lint ---
if ! $TEST_ONLY; then
    echo "=== lint ==="
    if command -v ruff &>/dev/null; then
        python -m ruff check .
        python -m ruff format --check .
    fi

    echo "=== typecheck ==="
    if command -v mypy &>/dev/null; then
        python -m mypy .
    fi
fi

# --- Tests ---
echo "=== tests ==="
if [ -n "$STORY_FILTER" ]; then
    PATTERN=$(echo "$STORY_FILTER" | tr '-' '_')
    python -m pytest tests/ -v -k "story_${PATTERN}" || python -m pytest tests/ -v
elif $QUICK_MODE; then
    python -m pytest tests/ -x -q
else
    python -m pytest tests/ -v
fi

echo "=== All checks passed ==="

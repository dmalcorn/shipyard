#!/usr/bin/env bash
# run-shipyard.sh — fresh factory run against a specified target with
# console output mirrored to logs/console/.
#
# Use this for the first run of a new target (or to start fresh on an
# existing target). For resuming an in-flight target, see
# resume-shipyard.sh instead — that script reads the target from
# factory.yaml automatically.
#
# Usage:
#   bash scripts/run-shipyard.sh "C:\path\to\target"
#   bash scripts/run-shipyard.sh "C:\path\to\target" --no-story-reviews
#
# The first argument is the target directory (passed to `--rebuild`).
# Any subsequent arguments are forwarded to `python -m src.main`.
#
# Console output:
#   stdout (live)
#   logs/console/run-<UTC-timestamp>.log (mirrored via tee)
set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Usage: bash scripts/run-shipyard.sh <target-dir> [extra args...]" >&2
    echo "       For an in-flight resume, use scripts/resume-shipyard.sh" >&2
    exit 2
fi

TARGET="$1"
shift

cd "$(dirname "$0")/.."

mkdir -p logs/console
LOG="logs/console/run-$(date -u +%Y%m%d-%H%M%S).log"

echo "Target:      $TARGET"
echo "Console log: $LOG"
echo "------------------------------------------------------------"

# Force UTF-8 stdout — see resume-shipyard.sh for the full rationale.
# Short version: `tee` demotes Python's pipe encoding to the locale
# default (cp1252 on Windows), which crashes on non-ASCII output.
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1

python -m src.main --rebuild "$TARGET" "$@" 2>&1 | tee "$LOG"

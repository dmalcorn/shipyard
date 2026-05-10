#!/usr/bin/env bash
# resume-shipyard.sh — resume the most-recently-set-up factory target with
# console output mirrored to logs/console/.
#
# The target is read from shipyard/factory.yaml's `target.dir`, which is
# rewritten by scripts/preflight.sh on every fresh setup — so this script
# always resumes the target the operator most recently brought online.
#
# Usage:
#   bash scripts/resume-shipyard.sh                    # plain resume
#   bash scripts/resume-shipyard.sh --no-story-reviews # resume with extra flags
#
# Any extra arguments are forwarded to `python -m src.main` after `--resume`.
#
# Console output goes to:
#   stdout (live, as before)
#   logs/console/resume-<UTC-timestamp>.log (mirrored via tee)
#
# logs/ is gitignored at the shipyard root, so capture files never land in
# version control. Expect 200-500MB per multi-day epic build — sweep the
# folder manually when it bothers you.
set -euo pipefail

# Anchor to the shipyard root regardless of where the script is invoked from.
cd "$(dirname "$0")/.."

if [ ! -f factory.yaml ]; then
    echo "ERROR: factory.yaml not found in $(pwd)." >&2
    echo "       Run scripts/preflight.sh against a target first." >&2
    exit 2
fi

# Use Python + PyYAML rather than grep/sed so quoted paths with backslashes
# (Windows: "C:\\alcorn\\...") parse correctly. PyYAML is a hard dependency
# of shipyard (see src/config.py); failure here means the venv isn't set up.
TARGET=$(python -c "import yaml; print(yaml.safe_load(open('factory.yaml'))['target']['dir'])")

if [ -z "$TARGET" ]; then
    echo "ERROR: factory.yaml has no target.dir set." >&2
    exit 2
fi

mkdir -p logs/console
LOG="logs/console/resume-$(date -u +%Y%m%d-%H%M%S).log"

echo "Resuming target: $TARGET"
echo "Console log:    $LOG"
echo "------------------------------------------------------------"

# Force Python's stdout/stderr to UTF-8 regardless of the host locale.
# Without this, on Windows + Git Bash the `tee` pipe demotes Python's
# stdout encoding to cp1252 (the system locale), and any non-ASCII
# character — box-drawing rules, em-dashes, smart quotes — crashes
# the run with UnicodeEncodeError. PYTHONUTF8=1 forces UTF-8 mode for
# the whole interpreter; PYTHONIOENCODING=utf-8 belt-and-suspenders.
export PYTHONIOENCODING=utf-8
export PYTHONUTF8=1
# Disable Python's stdout block-buffering. When stdout is a pipe (which
# `tee` makes it), Python switches from line-buffering (TTY default) to
# 4KB block-buffering — print() output sits in a buffer until flush,
# arriving in the captured log out of chronological order with stderr
# logger output. PYTHONUNBUFFERED=1 keeps both streams flushing per line.
export PYTHONUNBUFFERED=1

# `2>&1` merges stderr (Python logging) into stdout so the tee'd file has
# the same chronological stream the operator sees in their terminal.
# `set -o pipefail` makes the script's exit code reflect Python's, not tee's.
python -m src.main --rebuild "$TARGET" --resume "$@" 2>&1 | tee "$LOG"

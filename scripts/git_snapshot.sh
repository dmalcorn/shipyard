#!/usr/bin/env bash
# Take a git snapshot: stage all changes and commit with the given message.
# Usage: bash scripts/git_snapshot.sh "commit message"
set -euo pipefail

if [ -z "${1:-}" ]; then
    echo "Usage: bash scripts/git_snapshot.sh \"commit message\""
    exit 1
fi

git add -A && git commit -m "$1"

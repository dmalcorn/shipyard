#!/usr/bin/env bash
# Local CI: ruff + mypy + pytest — all must pass before commit.
set -euo pipefail

echo "=== ruff check ==="
python -m ruff check src/ tests/

echo "=== ruff format check ==="
python -m ruff format --check src/ tests/

echo "=== mypy ==="
python -m mypy src/

echo "=== pytest ==="
python -m pytest tests/ -v

echo "=== All checks passed ==="

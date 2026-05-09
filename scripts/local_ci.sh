#!/usr/bin/env bash
# Local CI: ruff + mypy + pytest — all must pass before commit.
set -euo pipefail

echo "=== pytest collect (fast import-error check) ==="
# Fails in <1s if any test module's imports are broken (e.g. a renamed
# symbol the tests still reference). Catches dark-test drift before the
# slower lint/typecheck/full-pytest stages run.
python -m pytest --collect-only -q tests/ > /dev/null

echo "=== ruff check ==="
python -m ruff check src/ tests/

echo "=== ruff format check ==="
python -m ruff format --check src/ tests/

echo "=== mypy ==="
python -m mypy src/

echo "=== pytest ==="
python -m pytest tests/ -v

echo "=== All checks passed ==="

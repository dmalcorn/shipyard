#!/usr/bin/env bash
# Run pytest with verbose output and short tracebacks.
# Adds coverage report if pytest-cov is installed.
set -euo pipefail

if python -c "import pytest_cov" 2>/dev/null; then
    pytest tests/ -v --tb=short --cov=src --cov-report=term-missing
else
    pytest tests/ -v --tb=short
fi

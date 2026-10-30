#!/usr/bin/env bash
# One gate: format check, lint, two strict type checkers, tests. Fails on the first red.
set -e
cd "$(dirname "$0")"
. .venv/bin/activate
ruff format --check src tests scripts
ruff check --no-fix --output-format concise src tests scripts
mypy
pyright
pytest -q -p no:cacheprovider

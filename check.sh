#!/usr/bin/env bash
# The gate is `pixi run -e theory check`: format, lint, strict types, import contracts, tests.
set -e
cd "$(dirname "$0")"
exec pixi run -e theory check

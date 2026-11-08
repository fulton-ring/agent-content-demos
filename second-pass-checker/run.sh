#!/usr/bin/env bash
# One command: build the test set, run the three checkers, score them. Every number comes from the notebooks' code.
# Checker answers are committed in answers/; a run reuses them and only calls a model for an answer that's missing.
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
[ -n "${OPENROUTER_API_KEY:-}" ] || echo "OPENROUTER_API_KEY isn't set: fine while every answer is in answers/"
export PYDANTIC_AI_NO_BANNER=1 PYTHONWARNINGS=ignore

uv run --frozen 1_test_set.py
uv run --frozen 2_checkers.py
uv run --frozen 3_results.py

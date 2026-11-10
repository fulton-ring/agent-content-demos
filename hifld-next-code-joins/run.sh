#!/usr/bin/env bash
# Run the notebook as a script, so every number in outputs/ comes from the code the reader sees.
# By default it scores the saved model answers in outputs/answers.jsonl and calls no model.
# RUN_AGENT=1 (with OPENROUTER_API_KEY) asks the agent again: about $3 on OpenRouter.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
PYDANTIC_AI_NO_BANNER=1 uv run code_joins.py

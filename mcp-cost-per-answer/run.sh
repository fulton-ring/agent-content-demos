#!/usr/bin/env bash
# Run the notebook as a script, so every number in outputs/ comes from the code the reader sees.
# Needs OPENROUTER_API_KEY; a full run spends about $1 on OpenRouter.
# RESCORE=1 ./run.sh rescores the committed runs in outputs/ without calling any model.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
PYDANTIC_AI_NO_BANNER=1 uv run cost_per_answer.py

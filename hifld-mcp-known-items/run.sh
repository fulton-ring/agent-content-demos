#!/usr/bin/env bash
# Run the notebook as a script, so every number in outputs/ comes from the code the reader sees.
# Needs OPENROUTER_API_KEY. The agent part spends about $1 on OpenRouter per full run.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
PYDANTIC_AI_NO_BANNER=1 uv run known_items.py

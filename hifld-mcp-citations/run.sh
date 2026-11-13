#!/usr/bin/env bash
# Run the notebook as a script, so every number in outputs/ comes from the code the reader sees.
# With OPENROUTER_API_KEY set it reruns the agent (about $1.20, 9 minutes); without it, it
# rescores the committed answers and tool responses in outputs/runs.jsonl.gz.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
PYDANTIC_AI_NO_BANNER=1 uv run citations.py

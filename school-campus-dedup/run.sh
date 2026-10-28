#!/usr/bin/env bash
# One command: run the notebook as a script, so every number comes from the code the reader sees.
# Needs OPENROUTER_API_KEY (Jev and the chat model are called through OpenRouter). Downloads go to data/,
# results to output/. Model answers are cached in data/answers/, so a second run makes no paid calls.
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
[ -n "${OPENROUTER_API_KEY:-}" ] || { echo "Set OPENROUTER_API_KEY first."; exit 1; }
uv run campus_dedup.py

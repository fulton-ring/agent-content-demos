#!/usr/bin/env bash
# One command: run the three notebooks as scripts, in order, so every number comes from the code the reader sees.
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }

export PYDANTIC_AI_NO_BANNER=1
uv run 1_documents.py
# Model answers are committed under answers/, so a re-run reuses them and needs no key. A new page or schema needs one.
if [ -z "${OPENROUTER_API_KEY:-}" ]; then echo "OPENROUTER_API_KEY not set: only saved answers can be used"; fi
uv run 2_extraction.py
uv run 3_results.py

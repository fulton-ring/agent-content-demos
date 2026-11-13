#!/usr/bin/env bash
# One command: run the three notebooks as scripts, in order, so every number comes from the code the reader sees.
# First on PacifiCorp's reports (#188), then the same notebooks on AEP's (#223).
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }

export PYDANTIC_AI_NO_BANNER=1
# Model answers are committed under answers/, so a re-run reuses them and needs no key. A new page or schema needs one.
if [ -z "${OPENROUTER_API_KEY:-}" ]; then echo "OPENROUTER_API_KEY not set: only saved answers can be used"; fi
for utility in pacificorp aep; do
  echo "== $utility"
  CCR_UTILITY=$utility uv run 1_documents.py
  CCR_UTILITY=$utility uv run 2_extraction.py
  CCR_UTILITY=$utility uv run 3_results.py
done

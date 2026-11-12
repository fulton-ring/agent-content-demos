#!/usr/bin/env bash
# One command: list and download PJM's supplemental-project decks into data/, then run the notebook as a script.
# Saved model answers in outputs/extractions/ are reused, so a rerun needs no API key; a deck with no saved
# answer needs OPENROUTER_API_KEY. Every number in README.md and outputs/ comes from this run.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
mkdir -p outputs
export PYDANTIC_AI_NO_BANNER=1
uv run withdrawals.py 2>&1 | tee outputs/run_log.txt

#!/usr/bin/env bash
# Runs the notebook as a script. Downloads land in ./data (or $DATA_DIR), results in ./outputs.
# Set AGENT_RUN=1 (and OPENROUTER_API_KEY) to call the agent again instead of rescoring saved answers.
set -euo pipefail
cd "$(dirname "$0")"
uv run hospitals.py

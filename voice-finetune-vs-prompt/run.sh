#!/usr/bin/env bash
# One command: run the notebook as a script, so every number comes from the code the reader sees.
#   ./run.sh                     rescore from the saved answers in output/ (no model calls, no key needed)
#   VOICE_REFRESH=1 ./run.sh     call the models again (needs OPENROUTER_API_KEY and the voice guide, see README)
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
if [ -n "${VOICE_REFRESH:-}" ]; then
  [ -n "${OPENROUTER_API_KEY:-}" ] || { echo "OPENROUTER_API_KEY is needed with VOICE_REFRESH"; exit 1; }
fi
uv run voice.py
echo "Blind pairs: review/pairs.md. Open the notebook with: uv run marimo edit voice.py"

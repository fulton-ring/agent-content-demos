#!/usr/bin/env bash
# One command: run the notebook as a script, so every number comes from the code the reader sees.
#   ./run.sh          downloads the data into data/ (first run only) and writes output/
#   ./run.sh --chips  also draws the imagery chips used for the hand-checked sample (data/chips/, not committed)
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
uv run crosswalk.py
if [ "${1:-}" = "--chips" ]; then
  uv run hand_check_chips.py
fi

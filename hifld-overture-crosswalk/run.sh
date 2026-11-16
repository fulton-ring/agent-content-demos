#!/usr/bin/env bash
# One command: run the notebooks as scripts, so every number comes from the code the reader sees.
#   ./run.sh               downloads the data into data/ (first run only) and writes output/
#   ./run.sh --chips       also draws the imagery chips behind both hand checks (data/, not committed)
#   ./run.sh --registries  runs only registries.py (no Overture buildings pass)
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
if [ "${1:-}" != "--registries" ]; then
  uv run crosswalk.py
fi
uv run registries.py
if [ "${1:-}" = "--chips" ]; then
  uv run hand_check_chips.py
  uv run registry_chips.py
fi

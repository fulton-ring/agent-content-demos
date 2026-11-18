#!/usr/bin/env bash
# One command: run the notebook as a script, so every number comes from the code the reader sees.
# Downloads go to data/ (first run only, ~6 min), results to output/.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
uv run child_care.py
echo "Done: see output/ (counts_by_state.csv, match_rates.csv, found_on_either_map.csv, hand_check_summary.csv)"

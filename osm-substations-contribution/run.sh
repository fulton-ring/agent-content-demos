#!/usr/bin/env bash
# One command: download the public inputs into data/, re-check current OSM, join the hand labels and records,
# and write outputs/. Every number in README.md comes from this run.
#   ./run.sh          runs contribution.py (first run: ~30 min, most of it one Overpass query per point)
#   ./run.sh --chips  also draws the Esri imagery chips we labelled from (data/chips/, not committed)
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
mkdir -p outputs
uv run contribution.py | tee outputs/run_log.txt
if [ "${1:-}" = "--chips" ]; then
  uv run chips.py
fi

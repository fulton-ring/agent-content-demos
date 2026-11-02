#!/usr/bin/env bash
# One command: download the public inputs into data/, read the committed OSM answers, join the labels and records,
# and write outputs/. Every number in README.md comes from this run.
#   ./run.sh          runs contribution.py on the committed Overpass answers (a few minutes, most of it downloads)
#   OSM_RECHECK=1 ./run.sh   re-queries Overpass live first (5.5 h on 2026-11-01; the public mirror 504s often)
#   ./run.sh --chips  also draws the Esri imagery chips we labelled from (data/chips/, not committed)
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
mkdir -p outputs
uv run contribution.py > outputs/run_log.tmp && mv outputs/run_log.tmp outputs/run_log.txt
cat outputs/run_log.txt
if [ "${1:-}" = "--chips" ]; then
  uv run chips.py
fi

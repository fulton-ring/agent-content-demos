#!/usr/bin/env bash
# One command: run the notebook as a script, so every number comes from the code the reader sees.
#   ./run.sh                          downloads the data into data/ (first run only) and writes output/
#   PARCELS=my_parcels.csv ./run.sh   lists the upstream risks for your own parcels instead of the samples
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
uv run supply_chain_risk.py

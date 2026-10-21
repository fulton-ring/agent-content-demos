#!/usr/bin/env bash
# One command: run the notebooks as scripts, so every number comes from the code the reader sees.
#   ./run.sh                          runs both notebooks: Brooklyn (output/) and citywide (output/citywide/)
#   ./run.sh citywide.py              runs one notebook
#   PARCELS=my_parcels.csv ./run.sh   lists the upstream risks for your own parcels instead of the samples (Brooklyn)
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
notebooks=("$@")
[ ${#notebooks[@]} -gt 0 ] || notebooks=(supply_chain_risk.py citywide.py)
for notebook in "${notebooks[@]}"; do
    echo "== $notebook"
    uv run "$notebook"
done

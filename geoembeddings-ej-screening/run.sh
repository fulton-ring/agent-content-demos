#!/usr/bin/env bash
# Run the notebook as a script, so every number in outputs/ comes from the code the reader sees.
# The EJScreen and CEJST GeoParquet files come from ../ej-datasets-hifld-next, run unchanged with
# its download and output folders pointed into data/ej/ (about 1.4 GB and 10 minutes, once).
set -euo pipefail
cd "$(dirname "$0")"
export EJ_DATA_DIR="${EJ_DATA_DIR:-$PWD/data/ej/raw}" EJ_OUT_DIR="${EJ_OUT_DIR:-$PWD/data/ej/out}"
if [[ ! -f "$EJ_OUT_DIR/epa-ejscreen-2024-block-groups.parquet" ]]; then
  ../ej-datasets-hifld-next/run.sh
fi
uv sync --quiet
uv run geoembeddings_ej.py

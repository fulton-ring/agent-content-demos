#!/usr/bin/env bash
# Run the notebook as a script, so every number in outputs/ comes from the code the reader sees.
# Downloads about 1.4 GB into data/ on the first run. Set EJ_PMTILES=1 to also build vector tiles.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
uv run ej_datasets.py

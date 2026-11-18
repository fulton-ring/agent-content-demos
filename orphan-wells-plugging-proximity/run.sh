#!/usr/bin/env bash
# Run the notebook as a script, so every number in outputs/ comes from the code the reader sees.
# The first run downloads about 60 MB into data/.
set -euo pipefail
cd "$(dirname "$0")"
export DATA_DIR="${DATA_DIR:-data}" OUTPUT_DIR="${OUTPUT_DIR:-outputs}"
uv sync --quiet
uv run proximity.py
uv run marimo export html proximity.py -o "$OUTPUT_DIR/proximity.html"

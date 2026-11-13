#!/usr/bin/env bash
# Runs the notebook as a script, so every number in outputs/ comes from the code a reader sees.
set -euo pipefail
cd "$(dirname "$0")"
uv run tiles_vs_geoparquet.py

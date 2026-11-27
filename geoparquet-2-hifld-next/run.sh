#!/usr/bin/env bash
# Runs the notebook as a script, so every number in outputs/ comes from the code a reader sees.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p outputs
uv run geoparquet_2.py 2>&1 | tee outputs/run.log

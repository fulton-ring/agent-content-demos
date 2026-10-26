#!/usr/bin/env bash
# Downloads the extract, imports it into Overpass and PostGIS, benchmarks both,
# applies an hour of diffs, and writes results/. Needs Docker and uv.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
mkdir -p results
uv run benchmark.py 2>&1 | tee results/run.log

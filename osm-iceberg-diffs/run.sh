#!/usr/bin/env bash
# Imports the DC extract into Iceberg and PostGIS, applies hourly diffs to both
# (hourly.py), then replays minutely diffs with and without maintenance
# (replay.py). Writes results/. Needs Docker, Java 17+ and uv.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
mkdir -p results
uv run hourly.py 2>&1 | tee results/hourly.log

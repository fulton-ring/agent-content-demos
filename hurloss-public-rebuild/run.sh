#!/usr/bin/env bash
# One command: download the public inputs, rebuild and score FEMA's HRCN values (the spike),
# then build our own hurricane layer by county and tract and compare it with FEMA's.
set -euo pipefail
cd "$(dirname "$0")"
uv run hurloss-run
uv run hurloss-layer

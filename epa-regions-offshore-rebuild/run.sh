#!/usr/bin/env bash
# One command: download the public inputs, rebuild the layer, score each rule, write outputs/.
# The notebook runs as a script, so the published numbers come from the code a reader sees.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p outputs
uv run rebuild.py 2>&1 | grep -v -e "Measured (M) geometry" -e "return ogr_read" | tee outputs/last-run.txt

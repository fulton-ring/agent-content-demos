#!/usr/bin/env bash
# One command: read every HIFLD Next layer's dates and its source's current date, write outputs/.
# The notebook runs as a script, so the numbers come from the code a reader sees.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p outputs
uv run layer_currency.py | tee outputs/last-run.txt

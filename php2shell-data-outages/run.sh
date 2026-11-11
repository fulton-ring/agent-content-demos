#!/usr/bin/env bash
# One command: query the Wayback Machine CDX index for every endpoint (skipped for endpoints already saved in
# cdx/), check each endpoint live (once per day and network), and write outputs/.
# The notebook runs as a script, so the numbers come from the code a reader sees.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p outputs
uv run outages.py | tee outputs/last-run.txt

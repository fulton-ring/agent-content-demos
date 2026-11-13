#!/usr/bin/env bash
# One command: pull transmitted (IEM) and approved (USGS) flood windows for ~100 gages, compare peaks, write outputs/.
# The notebook runs as a script, so the numbers come from the code a reader sees.
# First run takes 1-3 hours (the IEM archive allows one request at a time); cache/ makes later runs take seconds.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p outputs
uv run peak_revisions.py | tee outputs/last-run.txt

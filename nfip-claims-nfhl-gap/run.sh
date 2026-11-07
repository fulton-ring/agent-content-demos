#!/usr/bin/env bash
# One command: pull the four sources, match every claim, and write results/.
# The notebook runs as a script, so the numbers come from the code a reader sees.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p results
uv run notebook.py | tee results/last-run.txt

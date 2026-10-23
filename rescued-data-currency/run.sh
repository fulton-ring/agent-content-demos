#!/usr/bin/env bash
# One command: re-read every copy, rewrite data/currency.csv, and print what changed.
# The notebook runs as a script, so the numbers come from the code a reader sees.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p results
uv run refresh.py | tee results/last-run.txt

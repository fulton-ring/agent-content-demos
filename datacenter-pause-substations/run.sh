#!/usr/bin/env bash
# One command: download the public inputs into data/ and run the notebook as a script.
# Every number in README.md and outputs/ comes from this run.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
test -f ../us-substations-verified/dataset/us_substations_hifld_only.csv || { echo "Run from a checkout of the whole repo: needs ../us-substations-verified/dataset/"; exit 1; }
mkdir -p outputs
uv run pause_substations.py | tee outputs/run_log.txt

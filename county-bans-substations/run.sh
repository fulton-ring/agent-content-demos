#!/usr/bin/env bash
# One command: download the public inputs into data/ and run the notebook as a script.
# Every number in README.md and outputs/ comes from this run.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
uv run analysis.py | tee outputs/run_log.txt

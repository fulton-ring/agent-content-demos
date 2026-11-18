#!/usr/bin/env bash
# One command: run the notebook as a script, so every number comes from the code the reader sees.
# Downloads go to data/ (reused on later runs), results to output/. First run about 25 minutes, later runs seconds.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
uv run rebuild.py

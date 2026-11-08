#!/usr/bin/env bash
# One command: download the public inputs into data/ and run the notebook as a script.
# Every number in README.md and outputs/ comes from this run.
#   ./run.sh          writes outputs/
#   ./run.sh --chips  also draws the imagery chips behind hand_check.csv (data/chips/, not committed)
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
[ -f ../us-substations-verified/dataset/us_substations.csv ] || { echo "run from a checkout of main that has us-substations-verified/"; exit 1; }
mkdir -p outputs
uv run distance.py | tee outputs/run_log.txt
if [ "${1:-}" = "--chips" ]; then
  uv run hand_check_chips.py
fi

#!/usr/bin/env bash
# One command: download the public inputs into data/ and run the notebook as a script.
# Every number in README.md and outputs/ comes from this run.
#   ./run.sh          writes outputs/ and the map files in map/
#   ./run.sh --chips  also draws the aerial-imagery chips behind hand_check.csv (data/chips/, not committed)
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
mkdir -p outputs
uv run verify.py | tee outputs/run_log.txt
if [ "${1:-}" = "--chips" ]; then
  uv run hand_check_chips.py
fi

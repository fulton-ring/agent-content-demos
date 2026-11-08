#!/usr/bin/env bash
# One command: download the public inputs into data/ (first run only) and run the notebook as a script.
# Every number in README.md and outputs/ comes from this run. Nothing at the level of a substation is written.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
mkdir -p outputs
SECONDS=0
uv run gic_rerun.py 2>&1 | grep -v -E "UserWarning|import pkg_resources|interp_func|weights = |spline|squared residuals|maxit|too small|approximation returned|abs\(fp-s\)" | tee outputs/run_log.txt
echo "Run time: ${SECONDS} s (whole run, including downloads and uv setup)" | tee -a outputs/run_log.txt

#!/usr/bin/env bash
# One command: validate HIFLD Next against Portolan, generate and re-check the fixes, then benchmark the tilers.
# The notebooks run as scripts, so the numbers come from the code a reader sees.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p outputs
command -v tippecanoe >/dev/null || { echo "tippecanoe 2.49.0 is needed for the benchmark; see README" >&2; exit 1; }
uv run portolan_check.py | tee outputs/portolan_check.log
uv run tiling_benchmark.py | tee outputs/tiling_benchmark.log

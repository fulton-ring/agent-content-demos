#!/usr/bin/env bash
# Runs the notebooks as scripts and writes results/. Needs Docker and uv.
#   ./run.sh               both: benchmark.py (#123), then ql_compiler.py (#125)
#   ./run.sh benchmark     only #123's benchmark: Overpass against osm2pgsql/PostGIS
#   ./run.sh ql_compiler   only #125's QL compiler: Underpass-API on PostGIS and DuckDB
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
mkdir -p results/ql_compiler
if [[ "${1:-all}" != "ql_compiler" ]]; then
  uv run benchmark.py 2>&1 | tee results/run.log
fi
if [[ "${1:-all}" != "benchmark" ]]; then
  uv run ql_compiler.py 2>&1 | tee results/ql_compiler/run.log
  uv run pytest -q test_ql_compiler.py
fi

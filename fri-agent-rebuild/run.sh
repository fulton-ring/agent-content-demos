#!/usr/bin/env bash
# Download the inputs, then run each notebook as a script, so every number in results/ comes from
# the code the reader sees. The agent loop is not rerun (it costs money and is not
# deterministic): uv run fri-swarm <hazard>
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
uv run python -m fri_rebuild.data
for notebook in rebuild tracts coastal charleston; do
  echo "== notebooks/$notebook.py"
  uv run python "notebooks/$notebook.py"
done

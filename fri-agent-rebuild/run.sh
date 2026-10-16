#!/usr/bin/env bash
# Download inputs, then run every notebook as a script: the rebuild and its scores, the
# census-tract layer, the coastal forensics, the coastal what-if scenarios and the Charleston
# building pilot. Each notebook writes its own folder under results/. The agent loop is not
# rerun here (it costs money and is not deterministic): uv run fri-swarm <hazard>
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
uv run fri-prepare
for notebook in rebuild tracts coastal_forensics coastal_scenarios charleston_pilot; do
  echo "== notebooks/$notebook.py"
  uv run python "notebooks/$notebook.py"
done

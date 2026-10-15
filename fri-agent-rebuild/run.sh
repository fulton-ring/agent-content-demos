#!/usr/bin/env bash
# Download inputs, run each hazard's final pipeline, score it against FEMA's published county
# values, and build the census-tract output. The agent loop is not rerun here (it costs money and
# is not deterministic); run it with: uv run python -m fri_rebuild.swarm <hazard>
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
uv run python -m fri_rebuild.prepare
uv run python -m fri_rebuild.report
uv run python -m fri_rebuild.downscale "${TRACT_HAZARD:-drought}" "${TRACT_COLUMN:-DRGT_LATE_HIGHER_HM}" \
  "${TRACT_STATE_FIPS:-06}" "${TRACT_STATE:-CA}"

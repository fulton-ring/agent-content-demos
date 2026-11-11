#!/usr/bin/env bash
# One command: run the notebook as a script, so every number in outputs/ comes from the code the reader sees.
# Needs uv, tippecanoe and nginx on PATH (apt install tippecanoe nginx-light, or brew install tippecanoe nginx).
# Downloads about 125 MB of GeoParquet into data/ on the first run. Set CHROMIUM_PATH to use an installed Chromium.
set -euo pipefail
cd "$(dirname "$0")"
for tool in uv tippecanoe nginx; do
  command -v "$tool" >/dev/null || { echo "$tool is needed on PATH (see README)"; exit 1; }
done
uv sync --quiet
if [ -z "${CHROMIUM_PATH:-}" ]; then uv run playwright install chromium; fi
uv run pmtiles_spike.py

#!/usr/bin/env bash
# One command: rebuild California, Colorado and Wyoming, compare each with WaDE's last
# table, write GeoParquet and the summary. The notebooks run as scripts, so the published
# numbers come from the code a reader sees. Re-running refreshes CA and CO from the states.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p outputs
rm -f outputs/*_summary.json outputs/summary.md
for notebook in california colorado wyoming summary; do
  echo "== ${notebook}"
  uv run "${notebook}.py"
done
cat outputs/summary.md

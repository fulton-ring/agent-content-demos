#!/usr/bin/env bash
# One command: rebuild the answer key from public data, then score the saved agent runs.
# The agent itself runs only with RUN_AGENT=1 (it costs about $1.20 on OpenRouter).
# Needs uv and QGIS 3.34 or later with its Python bindings (Ubuntu: apt install qgis python3-qgis).
set -euo pipefail
cd "$(dirname "$0")"
command -v qgis_process >/dev/null || { echo "qgis_process not found: install QGIS (apt install qgis python3-qgis)"; exit 1; }
uv run answer_key.py   # downloads HIFLD Next and FEMA NFHL files (about 700 MB, cached), writes answer_key.json
uv run agent_runs.py   # with RUN_AGENT=1: 60 agent runs into runs/; without it, lists the saved runs
uv run scoring.py      # scores runs/ against answer_key.json, writes results/
git diff --stat -- answer_key.json || true   # a change here means a source dataset changed since the key was committed

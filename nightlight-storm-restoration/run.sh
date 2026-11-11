#!/usr/bin/env bash
# Runs both notebooks as scripts. Downloads land in ./data (or $DATA_DIR), results in ./outputs.
set -euo pipefail
cd "$(dirname "$0")"
uv run restoration.py
uv run comparison.py

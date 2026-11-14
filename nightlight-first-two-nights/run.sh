#!/usr/bin/env bash
# Runs the notebook as a script. Downloads land in ./data (or $DATA_DIR), results in ./outputs.
set -euo pipefail
cd "$(dirname "$0")"
uv run first_two_nights.py

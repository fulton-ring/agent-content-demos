#!/usr/bin/env bash
# One command: run the notebook as a script, so every file in results/ comes from the code a
# reader sees in notebook.py. Downloads are cached in ~/.cache/pge-psps-hifld-facilities
# (or $PSPS_CACHE).
set -euo pipefail
cd "$(dirname "$0")"
uv run notebook.py

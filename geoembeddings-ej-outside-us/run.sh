#!/usr/bin/env bash
# Run the notebook as a script, so every number in outputs/ comes from the code the reader sees.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
uv run ej_outside_us.py

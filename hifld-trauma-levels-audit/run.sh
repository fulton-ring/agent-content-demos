#!/usr/bin/env bash
# Run the notebook as a script, so every number in outputs/ comes from the code the reader sees.
# The first run downloads about 240 MB into data/.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
uv run audit.py

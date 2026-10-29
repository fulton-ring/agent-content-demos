#!/usr/bin/env bash
# Run the notebook as a script, so every number in outputs/ comes from the code the reader sees.
# The first run downloads about 2.6 GB into data/ and builds routing tiles for Maine and New Jersey.
set -euo pipefail
cd "$(dirname "$0")"
command -v osmium >/dev/null || { echo "osmium not found: apt install osmium-tool, or brew install osmium-tool" >&2; exit 1; }
uv sync --quiet
uv run access.py

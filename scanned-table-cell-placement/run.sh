#!/usr/bin/env bash
# One command: rescore the source spike's saved answers. No model calls, no downloads.
set -euo pipefail
cd "$(dirname "$0")"
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
uv run --frozen cell_placement.py

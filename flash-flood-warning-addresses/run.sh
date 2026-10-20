#!/usr/bin/env bash
# One command: run the notebook as a script, so every table and figure in results/ comes from
# the code a reader sees in notebook.py. Downloads are cached in $FFW_CACHE (default ~/.cache).
set -euo pipefail
cd "$(dirname "$0")"
uv run notebook.py

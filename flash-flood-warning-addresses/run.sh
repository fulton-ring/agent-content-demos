#!/usr/bin/env bash
# One command: run the notebook as a script for each town, so every table and figure in results/
# comes from the code a reader sees in notebook.py. Downloads are cached in $FFW_CACHE (default ~/.cache).
set -euo pipefail
cd "$(dirname "$0")"
for site in lanesville corydon; do
  FFW_SITE="$site" uv run notebook.py
done

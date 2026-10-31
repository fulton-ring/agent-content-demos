#!/usr/bin/env bash
# One command: run the notebook as a script for each flood event, so every table and figure in
# results/<event>/ comes from the code a reader sees in notebook.py. Downloads are cached in
# $OFL_CACHE (default ~/.cache). Run one event with OFL_EVENT=taxday uv run notebook.py.
set -euo pipefail
cd "$(dirname "$0")"
for event in harvey taxday; do
  OFL_EVENT="$event" uv run notebook.py
done

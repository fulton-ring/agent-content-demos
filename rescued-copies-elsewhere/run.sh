#!/usr/bin/env bash
# One command: read every copy's metadata, score it against the checklist, write outputs/.
# The notebook runs as a script, so the numbers come from the code a reader sees.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p outputs
uv run copies_currency.py | tee outputs/last-run.txt

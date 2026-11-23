#!/usr/bin/env bash
# One command: archive the eWRIMS list and this week's CalWATRS tables from data.ca.gov,
# then run the crosswalk notebook as a script. The published numbers come from the code a
# reader sees in crosswalk.py; they land in outputs/summary.json.
set -euo pipefail
cd "$(dirname "$0")"
uv run archive.py
uv run crosswalk.py

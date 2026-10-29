#!/usr/bin/env bash
# One command: run the four notebooks in order as scripts, so every number comes from the code the reader sees,
# then export each one, with its outputs, as an HTML report in reports/.
# Needs OPENROUTER_API_KEY (Jev and the chat model are called through OpenRouter). Downloads and cached model
# answers go to data/, results to output/. A second run makes no paid calls.
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
[ -n "${OPENROUTER_API_KEY:-}" ] || { echo "Set OPENROUTER_API_KEY first."; exit 1; }
notebooks=(1_pairs.py 2_rules.py 3_jev.py 4_sites.py)
for notebook in "${notebooks[@]}"; do
  echo "== $notebook"
  uv run "$notebook"
done
mkdir -p reports
for notebook in "${notebooks[@]}"; do
  uv run marimo export html "$notebook" -o "reports/${notebook%.py}.html" -f
done

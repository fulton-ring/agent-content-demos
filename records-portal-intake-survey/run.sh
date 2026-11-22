#!/usr/bin/env bash
# One command: re-fetch every surveyed page once (part 1), then summarize the hand-read survey (part 2).
# Both notebooks run as scripts, so the published numbers come from the code a reader sees.
#   SKIP_FETCH=1 reruns part 2 only, from the committed results/fetch.csv.
set -euo pipefail
cd "$(dirname "$0")"
if [[ "${SKIP_FETCH:-}" != "1" ]]; then
  uv run collect.py
fi
uv run survey.py
uv run marimo export html survey.py -o outputs/survey.html --force
cat results/summary.json

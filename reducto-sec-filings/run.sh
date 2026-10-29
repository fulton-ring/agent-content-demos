#!/usr/bin/env bash
# One command: run the notebook as a script, so every number comes from the code the reader sees.
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
[ -n "${OPENROUTER_API_KEY:-}" ] || { echo "OPENROUTER_API_KEY is needed"; exit 1; }
[ -n "${REDUCTO_API_KEY:-}" ] || echo "REDUCTO_API_KEY isn't set: the Reducto pipelines will be reported as errors"

export PYDANTIC_AI_NO_BANNER=1
uv sync --frozen
# Chromium prints the filings to PDF; this downloads it once if Playwright doesn't have it yet.
uv run --frozen python -c "from playwright.sync_api import sync_playwright as p; b = p().start().chromium; b.launch().close()" 2>/dev/null \
  || uv run --frozen playwright install chromium
uv run --frozen sec_filings.py

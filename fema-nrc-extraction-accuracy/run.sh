#!/usr/bin/env bash
# One command: run the four notebooks as scripts, in order, so every number comes from the code the reader sees.
# Model answers are committed in answers/; a run reuses them and only calls a model for an answer that's missing.
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
command -v tesseract >/dev/null || { echo "Tesseract is needed: apt install tesseract-ocr (or brew install tesseract)"; exit 1; }
[ -n "${OPENROUTER_API_KEY:-}" ] || echo "OPENROUTER_API_KEY isn't set: fine while every answer is in answers/"

# Tesseract's own threads stall on a busy machine; the notebooks run four Tesseracts at once instead.
export OMP_THREAD_LIMIT=1 PYDANTIC_AI_NO_BANNER=1

uv run --frozen 1_ocr_share.py
uv run --frozen 2_long_vs_short.py
uv run --frozen 3_old_nrc_scans.py
uv run --frozen 4_counting.py

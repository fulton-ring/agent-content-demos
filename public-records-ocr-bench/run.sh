#!/usr/bin/env bash
# One command: build the tests, run the pipelines, score them, write the review file, then run olmOCR's own scorer.
# Model outputs are committed in bench/<pipeline>/; a run reuses them and only calls a model for a missing page.
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
command -v tesseract >/dev/null || { echo "Tesseract is needed: apt install tesseract-ocr (or brew install tesseract)"; exit 1; }
[ -n "${OPENROUTER_API_KEY:-}" ] || echo "OPENROUTER_API_KEY isn't set: fine while every model output is in bench/"

export OMP_THREAD_LIMIT=1 PYDANTIC_AI_NO_BANNER=1
start=$(date +%s)
uv run --frozen bench.py
uv run --frozen python -m olmocr.bench.benchmark --dir bench > results/olmocr_benchmark.txt 2>&1 \
  || { tail -20 results/olmocr_benchmark.txt; exit 1; }
tail -25 results/olmocr_benchmark.txt
echo "run took $(( $(date +%s) - start )) s"

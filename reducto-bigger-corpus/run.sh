#!/usr/bin/env bash
# One command: run the three notebooks as scripts, so every number comes from the code the reader sees.
set -euo pipefail
cd "$(dirname "$0")"

command -v tesseract >/dev/null || { echo "Tesseract is needed: apt install tesseract-ocr (or brew install tesseract)"; exit 1; }
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
[ -n "${OPENROUTER_API_KEY:-}" ] || { echo "OPENROUTER_API_KEY is needed"; exit 1; }
[ -n "${REDUCTO_API_KEY:-}" ] || { echo "REDUCTO_API_KEY is needed"; exit 1; }

# Tesseract multithreading can stall for many minutes on a busy machine; one thread per call is fast enough.
export OMP_THREAD_LIMIT=1 PYDANTIC_AI_NO_BANNER=1

uv run --frozen 1_fintabnet.py
uv run --frozen 2_scanned_990s.py
uv run --frozen 3_hard_tail.py

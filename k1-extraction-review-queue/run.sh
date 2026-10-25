#!/usr/bin/env bash
# One command: run the three notebooks as scripts, in order, so every number comes from the code the reader sees.
#   ./run.sh                the whole comparison (needs OPENROUTER_API_KEY; the OCR models also need Modal credentials)
#   ./run.sh --screenshots  also retake screenshots/ from Gemini 3.8 Flash's review screen
#   ./run.sh --gemma-google only Gemma 4 31B with Google's recommended settings, three times (2_extraction.py, 5b)
set -euo pipefail
cd "$(dirname "$0")"

# Docling reads scanned pages with Tesseract, so every run needs it.
command -v tesseract >/dev/null || { echo "Tesseract is needed: apt install tesseract-ocr (or brew install tesseract)"; exit 1; }
command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
[ -n "${OPENROUTER_API_KEY:-}" ] || { echo "OPENROUTER_API_KEY is needed"; exit 1; }

export MODAL_IMAGE_BUILDER_VERSION=2025.06
# Tesseract multithreading can stall for many minutes on a busy machine; one thread per call is fast enough.
export OMP_THREAD_LIMIT=1
if [ "${1:-}" = "--gemma-google" ]; then
  export K1_GEMMA_ONLY=1
fi
if [ "${1:-}" = "--screenshots" ]; then
  export K1_SCREENSHOTS=1
  [ -n "${CHROMIUM_PATH:-}" ] || uv run playwright install chromium
fi
uv run 1_documents.py
uv run 2_extraction.py
uv run 3_results.py

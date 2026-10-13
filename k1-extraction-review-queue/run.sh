#!/usr/bin/env bash
# One command: set up, fetch and make the documents, extract, score, and build the review screen.
#   ./run.sh            everything except the screen recording
#   ./run.sh --record   also click through the review screen and record it (needs Chromium)
#
# Two pipelines run on the same documents and are scored on the same answer keys:
#   output/                 Tesseract and rules (extract.py), no model, no network after the downloads
#   output/qwen3-vl-235b/   Docling + Qwen3-VL 235B through OpenRouter (extract_vlm.py)
#   output/qwen3-vl-30b/    Docling + Qwen3-VL 30B through OpenRouter
# The model pipelines run only when OPENROUTER_API_KEY is set. output/comparison.md puts them side by side.
set -euo pipefail
cd "$(dirname "$0")"
RECORD="${1:-}"

command -v tesseract >/dev/null || { echo "Tesseract is needed: apt install tesseract-ocr (or brew install tesseract)"; exit 1; }
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c "import pytesseract, docling, pydantic_ai" 2>/dev/null; then
  # The CPU build of PyTorch (for Docling's layout model); the default build pulls in CUDA.
  .venv/bin/pip install -q --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
fi
PY=.venv/bin/python

$PY generate.py      # made-up 1120-S and 1041 K-1s and brokerage 1099s, with their answer key
$PY fetch_real.py    # real sample K-1s from the issuers' sites, plus scanned copies
$PY extract.py       # Tesseract pipeline: read every document
$PY evaluate.py      # score against the answer keys
$PY report.py        # output/index.html

if [ -n "${OPENROUTER_API_KEY:-}" ]; then
  $PY layout.py      # Docling: words, box labels and statement tables for every page
  for pair in "qwen/qwen3-vl-235b-a22b-instruct qwen3-vl-235b" "qwen/qwen3-vl-30b-a3b-instruct qwen3-vl-30b"; do
    set -- $pair
    $PY extract_vlm.py "$1"
    $PY evaluate.py "output/$2"
    $PY report.py "output/$2"
  done
  $PY compare.py     # output/comparison.md
else
  echo "OPENROUTER_API_KEY isn't set, so only the Tesseract pipeline ran."
fi

if [ "$RECORD" = "--record" ]; then
  [ -n "${CHROMIUM_PATH:-}" ] || .venv/bin/playwright install chromium
  $PY record.py
fi
echo "Open output/index.html (or output/qwen3-vl-235b/index.html) in a browser."

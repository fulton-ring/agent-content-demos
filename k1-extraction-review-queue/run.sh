#!/usr/bin/env bash
# One command: set up, fetch and make the documents, extract, score, and build the review screen.
#   ./run.sh            everything except the screen recording
#   ./run.sh --record   also click through the review screen and record it (needs Chromium)
set -euo pipefail
cd "$(dirname "$0")"

command -v tesseract >/dev/null || { echo "Tesseract is needed: apt install tesseract-ocr (or brew install tesseract)"; exit 1; }
if [ ! -d .venv ]; then
  python3 -m venv .venv
  .venv/bin/pip install -q -r requirements.txt
fi
PY=.venv/bin/python

$PY generate.py      # made-up 1120-S and 1041 K-1s and brokerage 1099s, with their answer key
$PY fetch_real.py    # real sample K-1s from the issuers' sites, plus scanned copies
$PY extract.py       # read every document
$PY evaluate.py      # score against the answer keys
$PY report.py        # output/index.html

if [ "${1:-}" = "--record" ]; then
  [ -n "${CHROMIUM_PATH:-}" ] || .venv/bin/playwright install chromium
  $PY record.py
fi
echo "Open output/index.html in a browser."

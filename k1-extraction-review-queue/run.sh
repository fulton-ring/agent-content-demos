#!/usr/bin/env bash
# One command: set up, fetch and make the documents, extract with each model, score, and build the review screens.
#   ./run.sh               the model comparison (needs OPENROUTER_API_KEY)
#   ./run.sh --tesseract   also the Tesseract pipelines: OCR and rules, and Qwen3-VL checked by Tesseract (slow on CPU)
#   ./run.sh --record      also click through the review screen and record it (needs Chromium)
#
# Each model reads every document on its own (output/<model>-alone/). pair.py then combines two models' answers,
# accepting a value only when both read the same thing (output/pair-<a>+<b>/). output/comparison.md has them all.
set -euo pipefail
cd "$(dirname "$0")"
FLAGS=" $* "

if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
if ! .venv/bin/python -c "import pytesseract, docling, pydantic_ai" 2>/dev/null; then
  # The CPU build of PyTorch (for Docling's layout model); the default build pulls in CUDA.
  .venv/bin/pip install -q --extra-index-url https://download.pytorch.org/whl/cpu -r requirements.txt
fi
PY=.venv/bin/python
[ -n "${OPENROUTER_API_KEY:-}" ] || { echo "OPENROUTER_API_KEY is needed"; exit 1; }

$PY generate.py      # made-up 1120-S and 1041 K-1s and brokerage 1099s, with their answer key
$PY fetch_real.py    # real sample K-1s from the issuers' sites, plus scanned copies
$PY layout.py        # Docling: words, page types and statement tables for every page

# OpenRouter model id, output folder, extra flags. Qwen 3.8's provider refuses the forced tool call Pydantic AI
# uses for typed output in thinking mode, so it gets the schema in the prompt instead.
MODELS=(
  "google/gemini-3.8-flash gemini-3.8-flash"
  "qwen/qwen3.8-flash qwen3.8-flash --prompted"
  "qwen/qwen3-vl-235b-a22b-instruct qwen3-vl-235b"
  "z-ai/glm-5.3-flash glm-5.3-flash"
  "google/gemma-4-31b-it gemma-4-31b-it"
)
pids=()
for m in "${MODELS[@]}"; do
  set -- $m
  id=$1; name=$2; shift 2
  $PY extract_vlm.py "$id" --model-only "$@" > "output-$name.log" 2>&1 &
  pids+=($!)
done
for p in "${pids[@]}"; do wait "$p" || { echo "a model run failed; see output-*.log"; exit 1; }; done
for m in "${MODELS[@]}"; do
  set -- $m
  $PY evaluate.py "output/$2-alone" > /dev/null
  $PY report.py "output/$2-alone"
done

for pair in "gemini-3.8-flash qwen3.8-flash" "gemini-3.8-flash qwen3-vl-235b"; do
  set -- $pair
  $PY pair.py "output/$1-alone" "output/$2-alone"
  $PY evaluate.py "output/pair-$1+$2" > /dev/null
  $PY report.py "output/pair-$1+$2"
done

if [[ "$FLAGS" == *" --tesseract "* ]]; then
  command -v tesseract >/dev/null || { echo "Tesseract is needed: apt install tesseract-ocr"; exit 1; }
  $PY extract.py && $PY evaluate.py > /dev/null && $PY report.py
  $PY extract_vlm.py qwen/qwen3-vl-235b-a22b-instruct && $PY evaluate.py output/qwen3-vl-235b > /dev/null && $PY report.py output/qwen3-vl-235b
fi

$PY compare.py > /dev/null   # output/comparison.md

if [[ "$FLAGS" == *" --record "* ]]; then
  [ -n "${CHROMIUM_PATH:-}" ] || .venv/bin/playwright install chromium
  $PY record.py
fi
echo "See output/comparison.md, and open output/pair-gemini-3.8-flash+qwen3.8-flash/index.html in a browser."

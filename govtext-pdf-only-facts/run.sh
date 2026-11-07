#!/usr/bin/env bash
# One command: query GovText, match HIFLD Next facilities, list and compare facts, write outputs/.
# The notebook runs as a script, so the numbers come from the code a reader sees. Saved model answers in
# outputs/model_answers.jsonl mean no key or cost is needed unless the sample changes.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p outputs
PYDANTIC_AI_NO_BANNER=1 uv run pdf_only_facts.py | tee outputs/last-run.txt

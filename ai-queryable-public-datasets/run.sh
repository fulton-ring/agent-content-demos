#!/usr/bin/env bash
# Run the notebook as a script, so every number in outputs/ comes from the code the reader sees.
# Needs OPENROUTER_API_KEY; a full run spends well under $1 on OpenRouter and takes about
# 15 minutes (the Future Risk Index XLSX alone takes about 4.5 minutes to read remotely).
# RESCORE=1 ./run.sh reruns the DuckDB and documentation tests and rescores the committed
# agent runs in outputs/ without calling any model.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
# Public S3 buckets need anonymous requests; stray AWS credentials make S3 refuse them.
env -u AWS_ACCESS_KEY_ID -u AWS_SECRET_ACCESS_KEY -u AWS_SESSION_TOKEN \
  PYDANTIC_AI_NO_BANNER=1 uv run datasets.py

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
source config.env
uv sync --locked
uv run --locked gridded.py
uv run --locked notebook.py

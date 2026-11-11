#!/usr/bin/env bash
# Run the notebook as a script, so every number in outputs/ comes from the code the reader sees.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
# The many parallel range reads fragment glibc's per-thread heaps; two arenas keep memory in bounds.
export MALLOC_ARENA_MAX=2
uv run substation_finder.py

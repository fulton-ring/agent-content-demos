#!/usr/bin/env bash
# Run the notebook as a script, so every number in outputs/ comes from the code the reader sees.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
# The parallel range reads run in many threads, and glibc gives each its own heap that keeps freed
# tile buffers; two heaps keep a fresh run's memory close to a cached run's.
export MALLOC_ARENA_MAX=2
uv run substation_finder.py

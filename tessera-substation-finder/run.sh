#!/usr/bin/env bash
# Run the notebook as a script, so every number in outputs/ comes from the code the reader sees.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
# The parallel range reads allocate many multi-megabyte buffers. By default glibc raises its mmap
# threshold and keeps freed buffers in fragmented heaps, which grew a fresh run past 13 GB. A fixed
# 1 MB threshold and two arenas hand big buffers back to the OS.
export MALLOC_ARENA_MAX=2
export MALLOC_MMAP_THRESHOLD_=1048576
uv run substation_finder.py

#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
export UV_CACHE_DIR="${UV_CACHE_DIR:-$PWD/../../uv-cache}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$PWD/../../fri-validation-cache/runtime}"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$PWD/../../fri-validation-cache/config}"
export MPLCONFIGDIR="${MPLCONFIGDIR:-$PWD/../../fri-validation-cache/matplotlib}"
export OMP_NUM_THREADS="${OMP_NUM_THREADS:-1}"
export OPENBLAS_NUM_THREADS="${OPENBLAS_NUM_THREADS:-1}"
uv run --locked python notebook.py

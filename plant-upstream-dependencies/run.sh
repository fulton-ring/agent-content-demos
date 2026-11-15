#!/usr/bin/env bash
# Run the notebook as a script, so every number in outputs/ comes from the code the reader sees,
# then export the same notebook with its outputs to outputs/upstream_dependencies.html.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
uv run upstream_dependencies.py
uv run marimo export html upstream_dependencies.py -o outputs/upstream_dependencies.html --force

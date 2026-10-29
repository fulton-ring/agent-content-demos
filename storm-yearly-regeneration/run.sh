#!/usr/bin/env bash
# One command: regenerate the tracks, validate them, then write the release (dry run).
# Each notebook runs as a script, so every number in results/ comes from code a reader sees.
set -euo pipefail
cd "$(dirname "$0")"
uv run regenerate.py
uv run validate.py
uv run publish.py

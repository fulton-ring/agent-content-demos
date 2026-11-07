#!/usr/bin/env bash
# One command: run the notebook as a script, so every file in results/ comes from the code a
# reader sees in notebook.py. The first run downloads about 13 GB of FWI files.
set -euo pipefail
cd "$(dirname "$0")"
uv run notebook.py

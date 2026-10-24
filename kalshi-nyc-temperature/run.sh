#!/usr/bin/env bash
# One command: fetch the public data (cached after the first run), then run the backtest.
# Both notebooks run as scripts, so results/ comes from the code a reader sees.
set -euo pipefail
cd "$(dirname "$0")"
uv run 1_data.py
uv run 2_backtest.py
uv run 3_favourite.py

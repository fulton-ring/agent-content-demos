#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
uv run backtest.py
uv run position_sizing.py

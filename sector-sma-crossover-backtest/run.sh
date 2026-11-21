#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
uv run backtest.py
uv run position_sizing.py
uv run rotation_momentum.py
uv run real_products.py
uv run volatility_exit.py
uv run vix_episodes.py

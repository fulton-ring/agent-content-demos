#!/usr/bin/env bash
# One command: check HIFLD Next's 50 source endpoints once (appends to log/checks.csv), then run the notebook,
# which reads the PHP2Shell spike's saved archive answers and the monitor log and writes outputs/.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p outputs
{ uv run monitor.py; uv run notice.py; } | tee outputs/last-run.txt

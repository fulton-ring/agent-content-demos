#!/usr/bin/env bash
# One command: download the public inputs, build the event sets, rebuild and score HRCN.
set -euo pipefail
cd "$(dirname "$0")"
uv run hurloss-run

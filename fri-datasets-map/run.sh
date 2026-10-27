#!/usr/bin/env bash
# One command: write the datasets and the map's data from the two rebuilds' committed results,
# then build the map's script from its TypeScript source.
set -euo pipefail
cd "$(dirname "$0")"
uv run datasets.py
cd map
npm ci --silent
npm run --silent check
npm run --silent build
echo "Datasets in data/; map in map/ (serve this folder and open map/index.html)"

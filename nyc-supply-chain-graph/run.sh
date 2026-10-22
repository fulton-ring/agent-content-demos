#!/usr/bin/env bash
# One command for each step; every number comes from the code the reader sees.
#   ./run.sh          run the notebook: compare the stores, write output/ and the app's data
#   ./run.sh app      the same, then build the app and serve it at http://localhost:4173
#   ./run.sh check    the browser check: the app's upstream lists equal #62's for the sample parcels
# Neo4j is measured only when NEO4J_URI (and NEO4J_PASSWORD) point at a running server; see the README.
set -euo pipefail
cd "$(dirname "$0")"

command -v uv >/dev/null || { echo "uv is needed: https://docs.astral.sh/uv/getting-started/installation/"; exit 1; }
step="${1:-notebook}"
case "$step" in
  notebook | app | check) ;;
  *) echo "usage: ./run.sh [notebook|app|check]"; exit 1 ;;
esac

uv run graph_store.py
[ "$step" = notebook ] && exit 0

command -v npm >/dev/null || { echo "Node.js 22 or later is needed for the app: https://nodejs.org"; exit 1; }
cd app
npm ci --no-audit --no-fund
npm run build
if [ "$step" = check ]; then
  [ -n "${CHROMIUM_PATH:-}" ] || npx playwright install chromium
  npx playwright test --reporter=line
else
  echo "Open http://localhost:4173"
  npx vite preview --port 4173 --strictPort
fi

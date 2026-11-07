#!/usr/bin/env bash
# One command: crawl the 100 hosts from this network (part 1), then compare networks and run the assistant check
# (part 2). Both notebooks run as scripts, so the numbers come from the code a reader sees.
#   NETWORK   name for the network you run from (default anthropic-cloud, where the published run was made)
#   NETWORKS  comma-separated networks part 2 compares (default anthropic-cloud,github-actions)
#   SKIP_CRAWL=1 reruns part 2 only, from the committed crawl results.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p results
if [[ "${SKIP_CRAWL:-}" != "1" ]]; then
  NETWORK="${NETWORK:-anthropic-cloud}" uv run crawl.py | tee "results/crawl-${NETWORK:-anthropic-cloud}.log"
fi
uv run analysis.py | tee results/analysis.log
cat results/summary.json

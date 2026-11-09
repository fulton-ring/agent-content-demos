#!/usr/bin/env bash
# One command: read www.epa.gov's sitemaps, crawl every page politely, follow links into
# archive.epa.gov, check data files for live copies, write outputs/.
# The notebook runs as a script, so the numbers come from the code a reader sees.
# The first full crawl takes about 2.5 hours; reruns reuse cache/ and take minutes.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p outputs
uv run epa_live_archive_links.py | tee outputs/last-run.txt

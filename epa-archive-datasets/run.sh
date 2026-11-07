#!/usr/bin/env bash
# One command: download the CDX index and sitemap list, inventory the crawl, check a sample
# of data files for live copies, extract a few datasets from the WARCs, write outputs/.
# The notebook runs as a script, so the numbers come from the code a reader sees.
set -euo pipefail
cd "$(dirname "$0")"
mkdir -p outputs
uv run epa_archive_datasets.py | tee outputs/last-run.txt

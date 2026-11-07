#!/usr/bin/env bash
# Default: rescore the committed run log and output checksums with the notebook. No model calls,
# no pipeline runs; needs only uv and an internet connection for the nf-core answer key.
#
# ./run.sh --live: run the agent again from scratch. Needs OPENROUTER_API_KEY, Java 17+, a running
# Docker daemon and about 1 hour. The log is appended to log/events.jsonl. A person answers
# approval requests with `uv run nfwatch.py approve <id> yes|no "note"`, and if the agent stops
# with a question, continues it with `uv run nfwatch.py run "<answer>"`.
set -euo pipefail
cd "$(dirname "$0")"
uv sync --quiet
if [[ "${1:-}" == "--live" ]]; then
  uv run nfwatch.py prepare
  uv run nfwatch.py run
  uv run nfwatch.py manifest
fi
uv run notebook.py

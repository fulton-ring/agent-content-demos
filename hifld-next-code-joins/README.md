# Do codes that differ between HIFLD Next layers lead an AI agent to wrong joins?

Issue: #194. One marimo notebook, [`code_joins.py`](code_joins.py), reads top to bottom:
an inventory of shared identifier fields across every [HIFLD Next](https://hifld.publicenvirodata.org)
layer, 24 cross-layer questions with a spatial answer key, an AI agent on the HIFLD Next MCP
server answering them, and the same agent again with code descriptions added to the tool
metadata.

## Run it

```bash
./run.sh                                   # scores the saved answers; no model calls, ~2 minutes
RUN_AGENT=1 OPENROUTER_API_KEY=... ./run.sh  # asks the agent again, ~$3 and ~20 minutes
```

To read it with its tables, run `uv run marimo edit code_joins.py`. `run.sh` writes `outputs/`:
`inventory.csv` (one row per layer and field, with format, meaning and examples),
`field_summary.csv`, `answer_key.csv`, `code_notes.md` (the text added to the tool metadata),
`scored.csv` (one row per agent answer) and `summary.json`. `answers.jsonl` and
`transcripts/` are the saved model answers and full agent transcripts, committed so scoring
reruns without calling a model.

Settings are environment variables: `RUN_AGENT`, `AGENT_MODEL` (default
`anthropic/claude-haiku-5.5`), `AGENT_REPEATS` (2), `AGENT_BUDGET_USD` (4) and
`HIFLD_BASE_URL`.

## Where the data comes from

All public and fetched at run time:

- the layer list and schemas: HIFLD Next's STAC API, `/stac/collections`
- the values: each layer's GeoParquet file, read with DuckDB over HTTPS
- counties: HIFLD Next's own `us-county-boundaries-1` layer (Census, with Connecticut's 2022
  planning regions)
- the National Risk Index: FEMA's public ArcGIS service `National_Risk_Index_Counties`
  (the bulk zip on fema.gov answered *Access Denied* on 2026-11-09)
- the agent's tools: the MCP server at `https://hifld.publicenvirodata.org/mcp`, plus a
  `query_nri` SQL tool of ours over the NRI table

RESULTS_PLACEHOLDER

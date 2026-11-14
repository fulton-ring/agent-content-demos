# Which free public datasets can an AI agent or notebook query in place today?

Spike for [issue #197](https://github.com/fulton-ring/agent-content-demos/issues/197)
([proposal card](https://app.notion.com/p/40bcc69045cb81539c5aebc6d6d61dc5)).

AI assistants asked for "AI-ready" public data name machine-learning training sets, portals
and listicles. We expected the real answer to be a short list: datasets published as Parquet or
GeoParquet over plain HTTP, or behind an open API, that an agent can query with no
download-and-clean step. We froze 12 well-known free datasets (`datasets.csv`, committed before
any agent ran) and gave each the same three tests:

1. **DuckDB one-liner:** one SQL statement, core extensions only, against the data where it is
   published, returns the known answer to one real question.
2. **Schema and vintage readable:** column descriptions and a stated date or edition that a
   plain HTTP GET can read as text (not a PDF, not a browser-only page, not a 403).
3. **Agent:** a Pydantic AI agent (Claude Haiku 5.5) with one tool, DuckDB SQL that can also
   fetch any URL as text, starts from the dataset's home page and answers the same question.
   Right means right in two of three runs, with the value visible in a tool result.

## Results

RESULTS_PLACEHOLDER

## Run it

```bash
./run.sh            # needs OPENROUTER_API_KEY; about 15 minutes
RESCORE=1 ./run.sh  # reruns tests 1 and 2, rescores the committed agent runs, no model calls
```

It needs [uv](https://docs.astral.sh/uv/). `run.sh` runs the marimo notebook `datasets.py` as
a script; open it with `uv run marimo edit datasets.py` to read it with its output. Optional:
`AGENT_MODEL`, `AGENT_REPEATS` (default 3), `AGENT_BUDGET_USD` (default 4), and `DC_API_KEY`
to run the Data Commons agent through its MCP server.

## Files

- `datasets.py`: the notebook. Question, datasets, the three tests, results and failures.
- `datasets.csv`: the frozen list: access path, one-liner, question, known answer, how the
  answer was found, and where the schema and vintage are documented.
- `outputs/`: `results.csv` (the table above), `one_liners.csv`, `docs_check.csv`,
  `agent_runs.jsonl` and `transcripts/` (every model call, so a reviewer can rescore without
  paying), `agent_scored.csv`, `failures.csv`, `summary.json`, `data_commons_no_key.txt`.

## Where the data comes from

Everything is read at run time from the publishers; nothing is committed but our small results.
HIFLD Next ([hifld.publicenvirodata.org](https://hifld.publicenvirodata.org)), the Future Risk
Index master datasheet preserved at
[fulton-ring/nri-future-risk](https://github.com/fulton-ring/nri-future-risk), Overture Maps
release 2026-10-21.0, the Census Data API, NOAA NCEI Storm Events bulk CSVs, the
[mnemoraorg/usgs-global-earthquake-catalog](https://huggingface.co/datasets/mnemoraorg/usgs-global-earthquake-catalog)
mirror on Hugging Face, [Portolan NL](https://source.coop/cholmes/portolan-nl) on Source
Cooperative, Google Data Commons, the World Bank Indicators API, NYC TLC trip records, COCO 2017
annotations and OpenFEMA. The answer key's `how_found` column says how each answer was checked
by a route other than the one tested.

## What we looked at first

DuckDB's own readers (httpfs, `hf://`, `read_json`, the excel extension) do every fetch; we
wrote no download code. The agent and scoring follow our earlier
[mcp-cost-per-answer](../mcp-cost-per-answer/) spike. We considered existing "AI-ready"
checkers (llms.txt validators, the HIFLD Next Portolan check) but they test one convention
each, not whether a question gets answered.

## What it doesn't show

- One question per dataset, one model, one runner (a cloud container: nyc.gov and fema.gov's
  web pages answer it with 403, and it can't open github.com pages, so the Future Risk Index
  agent starts from the raw README).
- Free API keys count as failures. The Census API (since 2026) and Data Commons need one from
  a sign-up form, which an agent can't do by itself; a person who registers once gets through.
- The schema and vintage locations are our reading of each publisher's docs (`doc_note`).
- We built HIFLD Next and preserved the Future Risk Index files.

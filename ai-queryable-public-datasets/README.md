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

**5 of 12 datasets pass all three tests**: HIFLD Next Hospitals, Overture Maps, Portolan NL
on Source Cooperative, the World Bank Indicators API and OpenFEMA. **2 of the 6** datasets AI
assistants recommended pass (World Bank, Portolan NL). The short list holds: it isn't "most"
(5 of 12), and it isn't "almost none".

| Dataset | Format and access | DuckDB one-liner | Schema + vintage | Agent right (from this dataset), of 3 | Agent median s | All three |
|---|---|---|---|---|---|---|
| HIFLD Next: Hospitals | GeoParquet over HTTPS | pass, 0.5 s | pass | 3 (3) | 21 | **yes** |
| Future Risk Index county file | XLSX on GitHub | pass, 274 s | fail | 1 (1) | 900 | no |
| Overture Maps: divisions | GeoParquet on S3 | pass, 2.3 s | pass | 3 (3) | 15 | **yes** |
| Census Bureau data API (2020) | JSON API | fail | pass | 2 (0) | 31 | no |
| NOAA Storm Events Database | gzipped CSV over HTTPS | pass, 2.0 s | fail | 3 (3) | 9 | no |
| Hugging Face: USGS earthquake mirror | CSV on the Hub | pass, 1.9 s | fail | 3 (3) | 27 | no |
| Source Cooperative: Portolan NL | GeoParquet over HTTPS | pass, 3.1 s | pass | 3 (3) | 23 | **yes** |
| Google Data Commons (MCP server) | MCP and REST API | fail | fail | 0 (0) | - | no |
| World Bank Indicators API | JSON API | pass, 0.2 s | pass | 3 (3) | 3 | **yes** |
| NYC TLC yellow taxi trips | Parquet over HTTPS | pass, 0.3 s | fail | 3 (3) | 4 | no |
| COCO 2017 annotations | JSON inside a ZIP | fail | fail | 3 (0) | 13 | no |
| OpenFEMA Disaster Declarations | Parquet over HTTPS, JSON API | pass, 50 s | pass | 3 (3) | 14 | **yes** |

By test: the DuckDB one-liner passes for 9 of 12, schema and vintage for 6 of 12, and the agent
for 8 of 12. Seconds are from the `RESCORE` run that produced the committed outputs.

**Model cost:** $0.14 for 33 agent runs (Claude Haiku 5.5 on OpenRouter), $0.004 per run on
average; the most expensive dataset (HIFLD Next, which the agent explored through its API) cost
$0.03 for three runs. Agents are cheap here; the obstacles are formats, keys and docs.

**Why the failures failed** (`outputs/failures.csv` has each one as recorded):

- **Free key walls.** The Census Data API now redirects keyless calls to a "Missing Key" page,
  and Data Commons answers 401 to its MCP server and REST API. Census publishes its variables
  and vintage openly, so it passes the docs test; Data Commons doesn't, without a key.
- **The agent routes around walls, so "right" isn't enough.** Agents answered 30 of 33 runs
  correctly, but only 25 from the dataset under test. Census agents found the 2020 count in a
  separate Census Bureau CSV (one run took the apportionment total, 39,576,757, which includes
  overseas federal staff, and was wrong). All three COCO agents found a Hugging Face Parquet
  mirror instead of the 241 MB ZIP of JSON that cocodataset.org publishes.
- **Slow formats.** The Future Risk Index XLSX does answer in one DuckDB statement, but reading
  it over HTTP takes about 4.5 minutes (half a second locally), so two of three agent runs hit
  the 15-minute limit. OpenFEMA's Parquet also reads slowly (25 to 65 s across our runs); its
  server answers HEAD requests with a zero length, which we suspect makes DuckDB fetch more.
- **Docs an agent can't read.** NOAA's column definitions and TLC's data dictionary are PDFs
  (and nyc.gov answers our cloud runner with 403); COCO's format page renders only in a
  browser; the Future Risk Index README and the Hugging Face card state no as-of date. The
  Hugging Face mirror is also silently missing April 2013 to May 2015.
- **Flaky edges.** In an earlier full run (before we fixed a harness bug where parallel tool
  calls shared one DuckDB connection), CloudFront returned HTTP 202 to the NYC taxi agent and
  all three runs failed; we couldn't reproduce it, and all three pass here.

## Run it

```bash
./run.sh            # needs OPENROUTER_API_KEY; about 35 minutes
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

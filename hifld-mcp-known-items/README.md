# Can an AI agent using the HIFLD Next MCP server find the records we know are there?

A known-item test of [HIFLD Next](https://hifld.publicenvirodata.org), the public infrastructure
data portal we built with Public Environmental Data Partners. We list 82 things we know are in
it (40 whole datasets and 42 individual facilities), ask for each the way a person would, and
count what comes back through two paths: the portal's catalog search alone, and an AI agent
using the portal's MCP server. Issue: #54.

Everything is in one marimo notebook, [`known_items.py`](known_items.py), which reads top to
bottom: the test set, catalog search, the agent, scoring, misses, cost, and what the test can't
see.

## Run it

```bash
export OPENROUTER_API_KEY=...   # the agent's model calls; about $1 a full run
./run.sh                        # runs the notebook as a script, about 30 minutes
```

To read it with its tables, run `uv run marimo edit known_items.py` instead. `run.sh` writes
`outputs/`: `catalog_results.csv`, `agent_results.csv`, `agent_scored.csv` (one row per agent
answer, with its miss type), `summary.json`, and a few full agent transcripts in
`outputs/transcripts/`.

Settings are environment variables: `AGENT_REPEATS` (default 2), `AGENT_BUDGET_USD` (default
3; the run stops starting agent queries past it) and `HIFLD_BASE_URL`.

## Where the data comes from

All public, from HIFLD Next's own endpoints, found from
[fultonring.com/work/hifld-next](https://fultonring.com/work/hifld-next/) and its
[`/api`](https://hifld.publicenvirodata.org/api) bootstrap document:

- catalog search: `GET /api/collections/hifld/datasets?search=…`
- MCP server: `https://hifld.publicenvirodata.org/mcp` (streamable HTTP, listed in
  `/.well-known/mcp/server-card.json`)
- records for the key: the portal's OGC features API, `/features/collections/…/items`

**The key** ([`key.csv`](key.csv)) holds only public HIFLD values plus our questions. With seed
54 we sampled 40 of the catalog's 330 datasets and 7 records from each of six facility layers
(power plants, hospitals, dams, nursing homes, colleges, prisons). We wrote one question per
item; 38 of 82 are paraphrased or colloquial on purpose ("CDL schools" for *Truck Driving
Schools*, "Doctors Community Hospital" for *LUMINIS HEALTH DOCTORS COMMUNITY MEDICAL CTR*).
The notebook re-draws the sample on every run and stops if it no longer matches the key.

## Results

From one clean run on 2026-10-18 (`./run.sh` from a fresh clone, 28 minutes, $2.11 on
OpenRouter). Every number is in `outputs/summary.json`.

**The headline.** An agent on the MCP server (Claude Haiku 5.5) returned 97.5% of the 40
datasets and 93% of the 42 facilities on both runs, and 95% of all its answers (156 of 164)
cited a dataset ID and record ID that check out against the key. The same test with an OpenAI
model (GPT-6 Luna) found **none** of the 42 facilities, because of one defect in the server's
tool schema (below). Catalog search alone put the right dataset first for only half the items.

**Catalog search alone** (rank of the key dataset for the words a person would type):

| | top 1 | top 5 | found at all |
|---|---|---|---|
| 40 datasets | 52.5% | 72.5% | 72.5% |
| 42 facilities (their layer) | 52.4% | 64.3% | 64.3% |
| by phrasing: exact (44) / paraphrase (18) / colloquial (20) | 75% / 33% / 20% | | 93% / 44% / 35% |
| the whole question pasted in (82) | 0% | 0% | 0% |

Search requires every word to match the start of a word in the title, slug, tags or
description, with no stemming: "prisons" doesn't find *Prison Boundaries*, "CDL schools"
doesn't find *Truck Driving Schools*, and a full sentence finds nothing.

**The agent**, two runs each (run 1 / run 2):

| agent | dataset recall (40) | facility record recall (42) | facility answers that trace to the record | errors |
|---|---|---|---|---|
| Claude Haiku 5.5 | 97.5% / 97.5% | 92.9% / 97.6% | 90.5% / 95.2% | 0 / 0 |
| GPT-6 Luna | 82.5% / 82.5% | 0% / 0% | 0% / 0% | 45 / 44 |
| GPT-6 Luna + typed sources (client-side patch) | 95.0% / 92.5% | 95.2% / 97.6% | 92.9% / 95.2% | 0 / 0 |

"Traces" means the cited dataset ID is the key dataset and the cited record ID is the record's
own ID (`PLANT_CODE`, `NIDID`, `IPEDSID`…) or one of its generic IDs. Variance: Haiku gave the
same verdict on both runs for 80 of 82 items; the patched Luna for 80 of 82.

**The schema defect.** `query_parquet` and `read_geoparquet_rows` declare their `sources` /
`source` argument as an object with no properties. Haiku fills in the fields anyway; Luna sends
`{}` every time, the server answers `request validation failed`, and after three retries the
run fails. Copying the typed `source` schema the server already publishes for
`inspect_query_source` onto those two tools, on the client side, takes Luna's record recall from
0% to 95–98%. The fix belongs in the server; it's out of scope here and should be filed on
`hifld-next`.

**Misses by type** (all 492 agent answers; rule-assigned, see the notebook):

| type | count | example |
|---|---|---|
| error (the schema defect above) | 89 | every Luna record query |
| wrong layer ranked first | 6 | "undeveloped coastal barrier areas": CBRS Units or CBRS Prohibitions, not the key's oddly named *Generalized Units* |
| said not found | 6 | "Community Health Care of Gore Sequoyah" is a nursing home; agents searched hospitals |
| chose another layer | 5 | FUDS *Property Boundaries* for "Interim Risk Management project boundaries" |
| naming difference | 4 | "passenger train stations": the IPCD layer, not *Amtrak Stations* |
| record in another layer | 4 | Rasmussen University's Fargo campus cited from *Colleges and Universities Campuses*, same IPEDS ID |
| wrong or missing record ID | 2 | two QHC homes in Humboldt, Iowa; the agent named both and cited neither |

Some "misses" are defensible answers the key doesn't accept (IPCD for train stations, the
campuses layer for Rasmussen). We count them as misses because the key is strict; the misses
table in the notebook lists every one with the agent's answer.

**Cost and time per query** (completed and failed runs):

| agent | $/query | input tokens | tool calls | median s | p90 s |
|---|---|---|---|---|---|
| Claude Haiku 5.5 | 0.0085 | 79,000 | 5.7 | 11.6 | 19.5 |
| GPT-6 Luna | 0.0023 | 31,300 | 4.9 | 22.6 | 32.9 |
| GPT-6 Luna + typed sources | 0.0021 | 49,600 | 6.6 | 20.4 | 29.8 |

Spend across all runs while building this, including an earlier one-model run, an earlier full run and probes: about
$4.40 of the $10 cap.

## What it doesn't show

- Recall on items we chose. A miss we didn't think to ask about is invisible, and 82 items is
  small: one dataset item is 2.5 points.
- The dataset sample is uniform over the catalog, so 16 of the 40 are USACE inland
  navigation-chart layers. Facilities come from six well-kept point layers only.
- Two cheap models. Larger models may do better on the misses; we didn't test them.
- The miss types are rules, not diagnoses. The saved transcripts in `outputs/transcripts/` show
  real reasons for a few.
- We built HIFLD Next, so a good score can read as promotion. The misses and the schema defect
  are the parts to read.

## What we looked at first

Pydantic AI's `MCPToolset` connects to the server and validates the agent's typed answer;
OpenRouter's per-request cost is read from Pydantic AI's usage. Catalog search is called
directly. The only code we wrote is the sampling, the scoring rules and the tables.

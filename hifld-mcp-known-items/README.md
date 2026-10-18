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
item; 36 of 82 are paraphrased or colloquial on purpose ("CDL schools" for *Truck Driving
Schools*, "Doctors Community Hospital" for *LUMINIS HEALTH DOCTORS COMMUNITY MEDICAL CTR*).
The notebook re-draws the sample on every run and stops if it no longer matches the key.

## Results

RESULTS

## What we looked at first

Pydantic AI's `MCPToolset` connects to the server and validates the agent's typed answer;
OpenRouter's per-request cost is read from Pydantic AI's usage. Catalog search is called
directly. The only code we wrote is the sampling, the scoring rules and the tables.

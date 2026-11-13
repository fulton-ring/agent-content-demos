# Can an answer an AI agent gets from HIFLD Next be cited and checked a year later?

An agent connected to [HIFLD Next](https://hifld.publicenvirodata.org)'s MCP server answers 20
questions with known answers (counts, attribute lookups, a sum and a nearest facility). We check
which of six citation fields (layer, version, retrieval date, query URL, source agency, license)
appear in the raw tool responses and in the final answer, then try to reproduce each answer from
the final answer alone. We run it three ways: the server as shipped, the same server plus a
one-line instruction to cite, and a thin proxy that adds a citation block to every data tool
response, plus the same line. Issue: #208. Builds on `hifld-mcp-known-items/` (#54).

Everything is in one marimo notebook, [`citations.py`](citations.py). It reads top to bottom:
the questions and the per-version key, the three agents, field presence, reproduction, cost.

## Run it

```bash
./run.sh                        # no key: rescores the committed answers, about 2 minutes
export OPENROUTER_API_KEY=...   # with a key: reruns all 120 agent answers, about $1.20, 9 minutes
./run.sh
```

To read it with its tables, run `uv run marimo edit citations.py`. `run.sh` writes `outputs/`:
`summary.json` (every number below), `scored.csv` (one row per answer with its verdict and
what the reproducer found), `example_h04.md` (one question answered three ways) and, on a fresh
run, `runs.jsonl.gz` (every final answer and every raw tool response). Settings:
`AGENT_REPEATS` (default 2), `AGENT_BUDGET_USD` (default 4), `AGENT_MODEL`
(default `anthropic/claude-haiku-5.5`), `AGENT_RUN=0` to rescore with a key set, `HIFLD_BASE_URL`.

## Where the data comes from

All public, read at run time: the MCP server at `/mcp`, the catalog API at `/api`, and the OGC
features API at `/features`, which serves every layer version as its own collection
(`hifld~hospitals-3~hospitals-3~v1.0.0`, `…~v1.1.0`). The answer key is computed from the OGC
API on every version of each layer. Reproduction downloads the GeoParquet file a recipe names
into `outputs/cache/` (not committed) and runs the recipe's SQL in DuckDB.

Of 517 versioned layers, only `hospitals-3` has two versions today: v1.0.0 (the archived HIFLD
Open snapshot) and v1.1.0 (issued 2026-04-06), which changed bed counts for 1,421 of 8,340
hospitals. Ten questions are about hospitals; four of their answers differ between versions.

## Results

From one run on 2026-11-12: 120 answers (20 questions × 3 arms × 2 repeats), Claude Haiku 5.5
on OpenRouter, $1.18 in total, 8 minutes 53 seconds wall time. One answer errored (a tool retry
limit, instruction-only arm).

**Fields present** (of 40 answers per arm; instruction only has 39 after the error):

| | layer | version | retrieval date | query URL | source agency | license | all six |
|---|---|---|---|---|---|---|---|
| tool responses, as shipped | 40 | 40 | 0 | 1 | 40 | 26 | 0 |
| tool responses, proxy | 40 | 40 | 39 | 39 | 40 | 39 | 39 |
| final answer, as shipped | 39 | 15 | 0 | 0 | 2 | 0 | 0 |
| final answer, instruction only | 39 | 39 | 0 | 39 | 33 | 20 | 0 |
| final answer, proxy + instruction | 40 | 40 | 39 | 40 | 40 | 39 | 39 |

**Reproduced from the final answer alone** (rubric in the notebook, section 4):

| arm | reproduced | with effort | not reproducible | correct |
|---|---|---|---|---|
| as shipped | 0 | 37 | 3 | 37 |
| instruction only | 0 | 39 | 1 | 39 |
| proxy + instruction | **29** | 10 | 1 | 38 |

**The headline.** As shipped, none of 40 answers could be reproduced from the answer alone, and
none carried all six fields. The server's tool responses already hold the version, the producer
and (for v1.1.0) the license; the agent named the version in 15 of 40 final answers (all 8 of
the bed-count answers, where it matters most), but never a query a reader could run.

**A prompt alone isn't enough.** With the one-line instruction, every answer named a version
and gave SQL, but 0 of 39 could be run: the SQL reads from the server's internal alias (`FROM h`
or `FROM source_0`), not from a file a reader can open, and 23 answers said the tool gave no
retrieval date. The agent can only cite what the server hands it.

**With the proxy**, 39 of 40 answers carried all six fields and 29 reproduced exactly. Of the
other 10, 8 gave a working pinned SQL whose output needs a last step (7 group by status and the
reader adds the rows; 1 lists the 5 stations and the reader counts them), which the rubric
counts as effort; one agent edited the SQL and
dropped its `GROUP BY`; one wrote its SQL against the server's alias instead of the file the
proxy gave it. The one not reproducible
answer searched the wrong layer and said it didn't know.

**Cost and time per answer:**

| arm | $/answer | input tokens | tool calls | median s | p90 s |
|---|---|---|---|---|---|
| as shipped | 0.0100 | 93,100 | 6.4 | 12.2 | 16.1 |
| instruction only | 0.0103 | 92,700 | 6.4 | 14.7 | 19.8 |
| proxy + instruction | 0.0094 | 85,100 | 6.2 | 14.0 | 19.7 |

The citation block costs nothing measurable. Spend while building this, including a 9-answer
smoke test: about $1.30 of the $5 budget.

## What we found in HIFLD Next's metadata

- **The hospital ID column changed between versions.** v1.0.0 calls it `ID`; v1.1.0 calls it
  `source_ID`. v1.1.0's published schema and OGC queryables still say `ID`, and filtering on
  `ID` returns a 500; `source_ID` is rejected as unsupported. SQL written today against v1.1.0
  won't run on v1.0.0, and the same record needs a different pinned URL on each version
  (`OBJECTID` works on v1.1.0 only).
- **v1.1.0 of hospitals names a contractor, not an agency.** Its producer is Niyam IT (who did
  the update) and `hifld:agency` is null; v1.0.0 named Oak Ridge National Laboratory. With the
  proxy, agents dutifully cited "Source agency: Niyam IT".
- **License is `other` on every v1.0.0 layer.** HIFLD Next's rights notice says the archived
  snapshot is public domain (PDM 1.0); the proxy states that, but the layers don't.
- **No retrieval date and no runnable query in any response, and no MCP `instructions`.**

## Making the change in the real server: about 3 days

The proxy is about 60 lines in the notebook and uses only metadata the server already has.
Doing the same in the server (not in this repo): add the citation block to the four data tools'
responses (1 day with tests); give a reader-runnable query, either the SQL rewritten onto the
pinned GeoParquet URL or a GET endpoint that reruns a pinned query, and check its dialect runs
outside the server (1 day); fix the metadata above, set agency and license per layer and add a
citation line to the server's MCP `instructions` and `llms.txt` (1 day). This is our estimate
from the proxy's size, not a measured build.

## What it doesn't show

- "A year later" is simulated. Old versions are preserved today; if the storage paths or the
  per-version OGC collections went away, pinned recipes would break too.
- One cheap model, two repeats, 20 questions. Other agents may drop citations more or less.
- Only one layer has two versions, so version drift is tested on hospitals only.
- The rubric is mechanical and strict: a recipe whose result needs summing counts as effort.
  "With effort" is wide: it covers both "the agent named the layer and version" and "named
  the layer only".
- The proxy runs on the client side as a Pydantic AI `process_tool_call` hook. Other MCP
  clients would need the change in the server.

## What we looked at first

Pydantic AI's `MCPToolset` with its `process_tool_call` hook is the proxy; we didn't need a
separate MCP server. The key comes from HIFLD Next's OGC features API, reproduction uses DuckDB
on the published GeoParquet files. The code we wrote is the questions, the citation block, the
field rules and the reproducer.

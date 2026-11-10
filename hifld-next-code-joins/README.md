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

## Results

From the run on 2026-11-09: the agent's answers (Claude Haiku 5.5 on OpenRouter, $1.77 for
all 96 answers, median 14 s each), then `./run.sh` from a clean checkout to score them.
Every number is in `outputs/summary.json`, `outputs/field_summary.csv` and
`outputs/scored.csv`.

**The inventory.** We checked 9 shared identifier fields (`STATE`, `COUNTY`, `COUNTYFIPS`,
`FIPS`, `FIPS_CODE`, `ZIP`, `NAICS_CODE`, `STATUS`, `TYPE`) in 137 layers (320 layer-field
pairs, reading the real values, not catalog samples). **All 9 change format or meaning
between layers**, and 77 layer-field pairs depart from the common form (`outputs/code_notes.md`
lists each one). The ones that can join to the wrong place:

| field | what we found |
|---|---|
| `STATE` | postal code in 59 layers, full name in 15, FIPS number (`48`) in 13, lowercase in 2; city names in 2 (`dialysis-centers`, `mines-and-mineral-resources`, where columns are shifted by one) |
| `COUNTY` | a name in 46 layers, a 3-digit FIPS (`029`, no state) in 6 |
| `FIPS` | county code in 6 layers, state code in 2, county *name* in 1 |
| county codes, Connecticut | 28 of the 31 county-code layers with Connecticut rows still use the 8 counties abolished in 2022 for some CT rows (`09003` Hartford); the county layer, hospitals, power plants and NRI use the 9 planning regions (`09110` Capitol). The two never match. |
| `private-schools.COUNTYFIPS` | county and state reversed in 75% of rows: Erskine Academy, Maine (`23011`) is stored as `01123`, which is Tallapoosa County, **Alabama** |
| `ncua...COUNTYFIPS`, `FIPS_CODE` | stored as a number (`6019`, leading zero lost) in NCUA; `ME011`-style codes in 5% of EPA TRI rows |
| `STATUS` | operating status in words (`OPEN`), in codes (`OP`, `A`, `1`-`8`), or not status at all: ownership, volcano dating evidence, regulatory stage |

We also found 5,767 FDIC bank offices (7%) at `POINT (0 0)`; out of scope here.

**The agent**, 24 questions × 2 runs per condition:

| condition | answers | correct | no match | wrong match | ran a spatial join |
|---|---|---|---|---|---|
| baseline tool metadata | 48 | 81.3% | 6.3% | **12.5%** (6) | 0 |
| + code notes in metadata | 48 | 89.6% | 4.2% | **6.3%** (3) | 0 |

- **The risk-index questions didn't mis-join.** 11 of the 12 nri questions were correct in
  every run, including Richmond city vs Richmond County, Baltimore city, Connecticut and the reversed
  Erskine Academy code. The agent cross-checked state and name before taking an NRI row, so
  none of those traps bit. The 12th (n05, all 4 runs) was a no match: the quarry's
  name sits in a shifted column, so the agent never found the record.
- **The wrong matches came from layer-to-layer counts**, where a bad code still matched
  something in the right state: private schools in Bexar County (23 of 82, both baseline runs:
  only the rows whose code isn't reversed), public schools near a Danbury credit union (236
  for old Fairfield County vs 148 in today's Western Connecticut region, all 4 runs), and one
  run each of NCUA's numeric codes and Hartford vs the Capitol region.
- **The code notes fixed 3 of 6.** With the notes, the agent padded NCUA's codes, mapped
  Hartford County to the Capitol region, and once counted private schools by county name
  because it saw the reversed codes. It still joined the two Connecticut layers that share
  the old codes (s04): consistent with each other, wrong against today's counties and NRI.
- **No spatial joins.** No transcript has a spatial predicate in its SQL, though the server
  supports `ST_Intersects`. The one answer labeled "spatial" read the county off the facility's town and
  coordinates without a spatial query.
- Cost: $0.017 per baseline answer, $0.019 with the notes (12,800 characters added to one tool
  description). About $0.15 more went on two probe runs while building it.

## What it doesn't show

- The questions are aimed at the problems the inventory found, with three clean controls.
  12.5% is the wrong-match rate on these 24 questions, not on questions people ask at random.
- One cheap model, two runs per question. The key for s04 uses today's Census geography; an
  article should say the agent's answer is right for the county that existed before 2022.
- The NRI tool is ours, and the code notes go into a tool description on the client side. On
  the server they belong in each column's schema entry.
- The notebook is about 1,300 lines, over the 1,000-line target; most of it is marimo cell
  boilerplate and markdown, and every step runs once, in the order you read it.
- The inventory's classes are regular-expression rules. Formats we didn't write a rule for
  show as `other`; `outputs/inventory.csv` has examples for every layer-field pair.

## What we looked at first

Pydantic AI's `MCPToolset` connects to the server, with `prepared` to edit tool descriptions
and typed output for every answer; DuckDB's `httpfs` and `spatial` extensions read GeoParquet
straight from HIFLD Next's storage and do the spatial join. The code we wrote is the format
rules, the questions and the scoring. Reused from `hifld-mcp-known-items/`: the agent setup
and run loop.

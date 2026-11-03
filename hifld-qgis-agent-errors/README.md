# Give an agent HIFLD Next and QGIS and see what it gets wrong

We gave an AI agent two tool servers: the public HIFLD Next MCP server and headless QGIS. Then we
asked it ten flood-exposure questions about real public infrastructure, each with an answer key
we had computed ourselves beforehand. Two cheap models answered each question three times, 60
runs in all, and we logged every tool call. The write-up is the error log. Issue: #181.

**Short answer: the agents got most of it right, and one mistake repeated on every run.** On the
key we committed before any run, 48 of 60 answers are right (Claude Haiku 5.5 22 of 30, GPT-6 Luna
26 of 30). The traps we set mostly didn't catch them: Web Mercator layers, a 500 m distance near a
threshold, and substations HIFLD Next doesn't have. The mistake that did repeat was a filter. The
agents took FEMA's *county* flood map extract to be the county, but it isn't clipped to the county
line. All 6 runs of the transmission-line question over-counted by about 4% that way, just past the ±3% the key allows. All 6 runs of the
fire-station question made the same assumption and were right only because, in Miami-Dade, it
happens not to matter.

## Run it

```bash
./run.sh                 # rebuilds the answer key and rescores the saved runs; no API key needed
RUN_AGENT=1 ./run.sh     # also reruns the 60 agent runs: needs OPENROUTER_API_KEY, about $1.20 and 31 minutes
```

You need `uv` and QGIS 3.34 or later with its Python bindings (`apt install qgis python3-qgis`
on Ubuntu 24.04). The first run downloads about 700 MB, mostly FEMA's NFHL county extracts, into
`$HQAE_CACHE` (default `~/.cache/hifld-qgis-agent-errors`; 1.8 GB once unzipped). After that it
takes about 2 minutes.
Settings: `AGENT_MODELS`, `AGENT_REPEATS` (3), `AGENT_BUDGET_USD` (4.5), `QGIS_PYTHON`.

Three marimo notebooks, each readable on its own (`uv run marimo edit <file>`):

1. [`answer_key.py`](answer_key.py): the questions, the data and the answer key. It was committed
   in its own commit (`57da090`) before any agent ran. Every count is checked against QGIS's own
   *Extract by location*.
2. [`agent_runs.py`](agent_runs.py): the agent, its tools and the runs. Saved runs are in
   `runs/<model>/<question>_<repeat>.json` (full messages plus a tool log with timings).
3. [`scoring.py`](scoring.py): scoring, the error log with quoted transcript lines, accuracy,
   errors by type, cost and time. It writes `results/`.

## Data (all public, downloaded at run time)

| What | Source |
|---|---|
| Hospitals, nursing homes, public schools, fire/EMS stations, power plants, transmission lines, dialysis centers, county boundaries | HIFLD Next GeoParquet, the files its MCP server queries (versions pinned in `answer_key.py`) |
| Flood zones | FEMA NFHL county extracts (`S_FLD_HAZ_AR`) from the Map Service Center: Harris County TX 48201C (dated 2026-05-17), Orleans Parish LA 22071C (2026-10-02), Miami-Dade FL 12086C (2026-01-25), Charleston County SC 45019C (2026-10-25) |

The SFHA is every zone with `SFHA_TF = 'T'`. Answers are computed in each county's UTM zone. Where
a reasonable choice changes an answer (county by boundary or by the `COUNTYFIPS` field, a point
inside or touching a zone), the key accepts each result. For these ten questions those choices
never changed one.

## The agent

Pydantic AI through OpenRouter, with a typed `Answer` output, run on **Claude Haiku 5.5** and
**GPT-6 Luna**. Its tools:

- **HIFLD Next MCP** (`org.publicenvirodata.hifld/dataset-mcp`, reachable from the sandbox), used
  as published. We dropped the six map-widget tools, which only draw maps.
- **QGIS 3.34 headless**: `qgis_process` wrapped as five tools (list algorithms, algorithm help,
  run an algorithm, layer info, read features). *Why not a QGIS MCP server:* jjsantos01/qgis_mcp
  and nkarasiak/qgis-mcp need the QGIS desktop app running a plugin. danielmiranda2017-tech/qgis-mcp
  targets QGIS 4. The sandbox's policy blocked installing BLD933/qgis_mcp_server, the one headless
  server for QGIS 3. So we wrapped QGIS's own command line, using the tool surface those servers
  share.

The agent is told where the four NFHL extracts are on disk and how to download a HIFLD Next file
into QGIS (`native:filedownloader`); everything else it finds itself. Each run gets an empty
working directory, 15 minutes, 40 model requests and $0.25 at most. Tool results longer than
12,000 characters are cut (109 of 1,468 calls).

## Results (from the saved runs; `results/summary.json`)

| Question | Answer key | Haiku right/wrong/unsure | Luna right/wrong/unsure |
|---|---|---|---|
| Q1 Hospitals in the SFHA, Harris County | 11 | 3 / 0 / 0 | 3 / 0 / 0 |
| Q2 Nursing homes in the SFHA, Orleans Parish (names) | 3 names | 1 / 2 / 0 | 3 / 0 / 0 |
| Q3 Public schools in the SFHA, Miami-Dade | 181 | 3 / 0 / 0 | 3 / 0 / 0 |
| Q4 Nursing homes in the 0.2% zone only, Charleston County | 17 | 0 / 3 / 0 | 3 / 0 / 0 |
| Q5 Fire/EMS stations in the SFHA, Miami-Dade (no county field, Web Mercator) | 40 | 3 / 0 / 0 | 3 / 0 / 0 |
| Q6 Operating plants ≥ 100 MW within 500 m of the SFHA, Harris (names) | 5 names | 3 / 0 / 0 | 3 / 0 / 0 |
| Q7 km of ≥ 345 kV line in the SFHA, Harris | 156.6 km ±3% | 0 / 3 / 0 | 0 / 3 / 0 |
| Q8 Beds in open hospitals in the SFHA, Miami-Dade | 3,993 | 3 / 0 / 0 | 2 / 0 / 1 |
| Q9 Substations in the SFHA, Orleans Parish | not in HIFLD Next | 3 / 0 / 0 | 3 / 0 / 0 |
| Q10 % of dialysis centers in the SFHA, Harris | 14.09% ±0.5 | 3 / 0 / 0 | 3 / 0 / 0 |
| **All 60 runs** | | **22 / 8 / 0** | **26 / 3 / 1** |

**Errors by type** (hand-assigned from each transcript in `error_labels.json`; the notebook checks
every quote is in the transcript):

| Type | Runs | Example (quoted from the transcript) |
|---|---|---|
| Wrong join or filter: no county clip | 6 (Q7, all runs, both models) | "clipped the lines to the SFHA, and summed segment lengths: 30 clipped segments totalling 162.49 km." It never clipped to Harris County. FEMA's extract runs past the county line, and our own recount without the county clip gives the same 162.5–162.8 km. |
| Wrong join or filter: narrower reading, defensible | 5 (Haiku, Q2 and Q4) | "the 60 'ASSISTED LIVING' records were excluded". HIFLD's *Nursing Homes* layer is really nursing homes plus assisted living. The agent kept only `TYPE = 'NURSING HOME'`, a fair reading we didn't foresee. |
| Tool failure | 1 (Luna, Q8) | "could not open …/12086C/S_Fld_Haz_Ar.gpkg as a vector layer". It guessed FEMA's documented mixed-case file name; on disk it is `S_FLD_HAZ_AR.shp`, and our tools can't list a folder. |
| CRS or projection, units, invented attribute or value, wrong layer, stale data | 0 | |

A lenient score that also accepts the narrower nursing-home reading gives Haiku 27 of 30. We added
that reading to `answer_key.py` after the runs, in a cell marked as such; the committed key is
unchanged.

**Right for the wrong reason.** A right answer can hide the same mistake. `scoring.py` looks in
each run's tool calls for any county filter: the county boundaries layer, a `COUNTYFIPS` or
`GEOID` filter, or the NFHL's own political areas file. It finds none in all 6 Q5 runs and all 6
Q7 runs; Q7 was wrong every time and Q5 right every time. Haiku said why: "the NFHL extract only
covers Miami-Dade, so this restricts the result to the county." All 6 Q10 runs (dialysis
centers, Harris County) did filter by county.

**What went right that we expected to go wrong.** Every run reprojected to a metric CRS before
measuring: UTM 15N, NAD83 / UTM, or Texas Lambert (EPSG:3081). None buffered in degrees or in Web
Mercator. So Q6 included T H Wharton, a plant 434 m from the SFHA that a Web Mercator buffer
drops. All six Q9
runs said there's no substations layer, with no count invented. No run used HIFLD Next's
misnamed *NFHL / Flood Hazard Zones* file, which holds 720 high water marks. A few Haiku runs looked
for an NFHL dataset in the catalog's OpenFEMA collection, found none, and used FEMA's files on disk.

**Cost and time** (OpenRouter's reported cost; wall time per run):

| | $ per run | median s | p90 s | tool calls per run | failed tool calls (all runs) |
|---|---|---|---|---|---|
| Claude Haiku 5.5 | 0.034 | 57 | 90 | 23.1 | 61 |
| GPT-6 Luna | 0.006 | 74 | 108 | 25.8 | 172 |

Per question, cost ranges from $0.011 a run (Q9) to $0.033 (Q10), and the mean time from 35 s
(Q9) to 161 s (Q3), both models together. Two runs took about 10 minutes. An *Extract by location*
of all 102,268 schools against every Miami-Dade SFHA polygon hit the 600 s tool timeout, and Haiku
recovered by cutting the schools to a bounding box. Luna's run on all 52,057 fire stations took
491 s. The 60-run batch
took 31 minutes, three at a time, for $1.19; with a pilot run, total spend was $1.22 of the $5
budget.

## What it doesn't show

- **Ten questions we wrote.** 60 runs is small: one run is 1.7 points. The errors cluster in two
  questions, so the headline rests on Q7 and on how we worded Q2 and Q4.
- **We handed the agent the flood map.** We gave it FEMA's NFHL files and their location, so it
  never had to find or download flood zones. That removed the wrong-layer trap that HIFLD Next's
  misnamed NFHL file sets. A harder version would give it only the catalog and the web.
- **Our QGIS tools, not a published QGIS MCP server.** A server with a folder-listing tool would
  have avoided the one tool failure; one that keeps layers in a live project would change how the
  agent works.
- **Two cheap models.** Larger models may avoid the county-extract mistake; we didn't test them.
- **The NFHL changes.** The Map Service Center serves only the latest extract. `run.sh` recomputes
  the key, and a later map can move it; `git diff answer_key.json` shows if it did.
- We built HIFLD Next, so a good score can read as promotion; read the error log and the misnamed files.

## What we looked at first

Pydantic AI's `MCPToolset` and usage limits, `qgis_process` and PyQGIS, GeoPandas for the key. We
wrote only the five QGIS tool wrappers, the key cells, the scoring rules and the tables.

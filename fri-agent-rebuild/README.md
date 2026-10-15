# Rebuilding FEMA's Future Risk Index with a swarm of agents

Can agents working from FEMA's published methodology and public data rebuild the Future Risk
Index (FRI) county hazard multipliers, and take them below the county? This folder is the spike
for [issue #15](https://github.com/fulton-ring/agent-content-demos/issues/15)
([proposal card](https://app.notion.com/p/3facc69045cb8004a763e1047da67297)).

**Short answer:**

- **Drought:** yes, almost exactly. Across all four scenarios the rebuilt county multipliers match
  FEMA's on states the agents never saw: 99.6% of counties land in the same projected-loss rating,
  Pearson correlation 0.998, and the median rebuilt/published ratio is 1.000.
- **Wildfire:** close. On held-out states, 96.9% of counties land in the same rating, correlation
  is 0.96, and the mean absolute log error is 0.072, about 7%.
- **Extreme heat:** only partly. The NEX 95th-percentile variant gets 94-96% of counties into the
  same rating, but the 99th-percentile variant runs about 20-30% low and correlates only 0.68-0.78
  with FEMA's values. The agents stalled on heat, and a person stepping in did not unstick them.
- **Below the county:** a census-tract drought layer for California (9,109 tracts) sums back to
  county projected annual loss exactly. Its resolution is bounded by the 25 km climate grid.
- **The agents:** 69 experiments across three hazards for $3.31 of model calls. The loop found
  the two changes that matter most (the Thornthwaite heat index in drought, the shape of the
  wildfire regression). A person had to fix the harness five times and step in once on heat.

![Drought hazard multiplier by census tract, California, late century, higher warming](results/tracts/DRGT_LATE_HIGHER_HM_CA_tracts.png)

## How to run it

```bash
./run.sh
```

`run.sh` needs [uv](https://docs.astral.sh/uv/) and about 30 GB of free disk. It does three
things:

1. Downloads every input into `~/.cache/fri-agent-rebuild` (set `FRI_CACHE` to move it). Nothing
   downloaded goes into the repo.
2. Runs each hazard's final pipeline (`hazards/<hazard>/pipeline.py`) and scores it against
   FEMA's published county values on training and held-out states.
3. Builds the tract-level output.

The first run takes one to two hours, almost all of it the NEX-GDDP-CMIP6 download: 924 global
yearly files of about 250 MB each (about 230 GB transferred), each cut to the CONUS box on this
4-core machine. With the inputs cached, `run.sh` took 18 minutes.

The agent loop is not part of `run.sh`, because it costs money and gives different results each
run. To run it for one hazard (needs `OPENROUTER_API_KEY`):

```bash
uv run python -m fri_rebuild.swarm drought --rounds 8 --agents 3 --budget 3
```

The numbers in this README come from one clean run: a fresh clone of the branch with every cached
input deleted except the already-reduced NEX and FWI arrays. Re-downloading those 230 GB was not
worth another hour or more. Its console output is in `results/clean_run.log`.

## Where the data comes from

| Input | Source | Notes |
|---|---|---|
| Answer key | `NRI_Future_Risk_Master_Datasheet_12052024.xlsx` from [fulton-ring/nri-future-risk](https://github.com/fulton-ring/nri-future-risk) at commit `c5cc0d6` | FEMA's own datasheet, downloaded before the tool was taken down in February 2025. It has county HMs, PAL ratings and the NRI v1.19 EAL each multiplier was applied to. Downloaded at run time. |
| Methodology | *National Risk Index: Future Risk Technical Documentation* (FEMA, December 2024) | [Archived copy at Harvard EELP](https://eelp.law.harvard.edu/wp-content/uploads/2025/03/NRI_Future_Risk_Technical_Document.pdf). Each hazard's `program.md` quotes the relevant section. |
| Drought, extreme heat | [NASA NEX-GDDP-CMIP6](https://registry.opendata.aws/nex-gddp-cmip6/) (AWS open data), MPI-ESM1-2-HR r1i1p1f1, historical, SSP2-4.5, SSP5-8.5 | Daily `tasmin`, `tasmax`, `tas`, `hurs` and `pr` at 0.25 degrees. We take the newest file version per year (mostly v2.0). |
| Wildfire | [NEX-GDDP-CMIP6 Fire Weather Index](https://data.nas.nasa.gov/gddpimpact/FWI/) (NASA "GDDP-IMPACT" portal), yearly multi-model-ensemble files MME25/50/75 | The portal is missing 4-7 of the 30 years in each period, and those years are skipped. MME50 has 122 of 150 years. |
| Fuels | LANDFIRE LF2022 FBFM40, from the [LANDFIRE ImageServer](https://lfps.usgs.gov/arcgis/rest/services/Landfire_LF2022/LF2022_FBFM40_CONUS/ImageServer) | Resampled to 500 m (nearest neighbour), because the 30 m national file is 3.4 GB. |
| NRI tract baseline | NRI v1.19.0 (March 2023) tract table, [Harvard Dataverse snapshot](https://doi.org/10.7910/DVN/JSQ8KZ) (file 10775728) | v1.19 is what the FRI was built on. FEMA no longer serves it, and fema.gov returns 403 from this environment. |
| Boundaries | Census 2020 cartographic boundaries (1:500k), counties and California tracts | Same county set as the datasheet, including the eight pre-2022 Connecticut counties. |

Scope is CONUS: 3,108 counties. FEMA's documentation defines "nationwide" for its climate inputs
as the contiguous US. Alaska and Hawaii have published drought and wildfire multipliers, but we
did not try to rebuild them.

## How it works

- **Answer key and scoring** (`answer_key.py`, `score.py`): we put rebuilt multipliers into
  FEMA's fixed NRI rating bins. The upper edge of each bin is the largest EAL observed in that
  rating, as in Section 3.2 of the technical document. Applied to FEMA's own multipliers, this
  reproduces 100% of the published PAL ratings, so "same rating bin" below means the same thing
  FEMA's map showed.
  - We also report Pearson and Spearman correlation, the mean absolute log error
    (`log_mae` = mean |ln(rebuilt / published)|), and the median rebuilt/published ratio.
  - A county the pipeline leaves blank counts as HM = 1, so leaving hard counties blank can't
    help a score.
- **Train/held-out split** (`split.py`): every fourth state in FIPS order is held out. That is 12
  states and 896 counties: AZ, CT, GA, IA, ME, MN, NE, NM, OH, RI, TX and WA. The agents only ever
  see training-state scores (2,212 counties). Held-out scores are computed after the loop ends.
- **Inputs** (`inputs.py`): a read-only API the pipelines use for climate arrays, county weights
  and the NRI baseline. County values are area-weighted averages of 0.25-degree cells, using exact
  polygon intersections in an equal-area projection.
- **One pipeline file per hazard:** `hazards/<hazard>/pipeline.py` is the only file the agents
  may change. Next to it, `program.md` is the human-written brief: what FEMA's document says, what
  the data looks like, and the open questions, numbered so agents can split them.
- **The loop** (`swarm.py`), modelled on [karpathy/autoresearch](https://github.com/karpathy/autoresearch):
  - Each round, three agents (Pydantic AI, `anthropic/claude-sonnet-5.5` through OpenRouter)
    propose in parallel. Each gets `program.md`, the current best pipeline, its training scores
    (including the worst training states), the full experiment log and notes on earlier
    hypotheses, and returns a complete new file.
  - The harness rejects code that names the answer key, the scorer or the split. It runs each
    candidate in a subprocess and keeps the best one if it beats the current best by more than
    0.002.
  - The loop stops after three rounds with no improvement or when it hits its budget. Every
    proposal is logged in `results/experiments-<hazard>.tsv`, and its code is kept in
    `results/candidates/<hazard>/<id>.py`.

## Results (one clean run)

Mean over the four scenarios. Per-scenario numbers are in `results/scores.csv`; the five largest
misses per column and subset are in `results/largest_differences.csv`.

| Hazard | Subset | Counties | Same rating bin | Pearson | Mean abs log error | Median rebuilt/published |
|---|---|---|---|---|---|---|
| Drought | train | 2,212 | 99.3% | 0.997 | 0.022 | 1.000 |
| Drought | held-out | 896 | 99.6% | 0.998 | 0.021 | 1.000 |
| Wildfire | train | 2,212 | 97.9% | 0.944 | 0.062 | 1.007 |
| Wildfire | held-out | 896 | 96.9% | 0.960 | 0.072 | 0.985 |
| Extreme heat (NEX N95 and N99) | train | 2,212 | 91.3% | 0.869 | 0.207 | 0.855 |
| Extreme heat (NEX N95 and N99) | held-out | 896 | 90.0% | 0.824 | 0.240 | 0.811 |

Extreme heat split by threshold, held-out:

- **N95:** 94-96% same rating bin, Pearson 0.85-0.97, log error 0.09-0.15. Late-century higher
  warming is the best scenario, at 0.973.
- **N99:** 83-87% same rating bin, Pearson 0.68-0.78, log error 0.26-0.38. Rebuilt values run
  about 0.72-0.79 of FEMA's.

### The largest differences and why

- **Drought.** The largest misses are small or coastal counties: Richmond and Kings (NY),
  Jackson (MS), and a few Georgia counties on the held-out side. Even these are off by only 12-21%.
  - These counties overlap one or two 0.25-degree cells, some of them mostly ocean with no land
    data, so area weighting depends on very few cells.
  - FEMA says its drought calculation ran at tract level on its own 0.25-degree polygon grid, so
    exact cell edges matter most here.
- **Wildfire.** The largest misses are northern New England and northern New York: Vermont's
  Orleans, Lamoille and Franklin, Clinton (NY), and Aroostook and Somerset (ME) held out. Our
  values there are about 1.4-1.7x FEMA's.
  - These are cool, wet counties where fire weather is low today, so a small absolute increase is
    a large ratio. The 95th-percentile FWI statistic the agents chose, raised to gamma, amplifies
    it.
  - FEMA computed the multiplier at census-block level, weighted by block EAL. We could not
    reproduce that: we have no block EAL, and the agents' attempts at EAL weighting did not help.
- **Extreme heat, N99.** Oklahoma and northeast Texas come out at about 0.4x FEMA (Oklahoma
  County: 3.4 against 8.8). N95 runs low in the Northeast and Appalachians (0.7-0.8x).
  - We did not find the cause. The likely candidates are how FEMA applied the 298 K heat-index
    filter and how it defined the 99th percentile; its document gives neither the formula nor
    the threshold detail.
  - The agents tested NWS and Steadman heat-index variants, `tas`, `tasmax` and `tasmin` as the
    temperature input, warm-season and calendar-window percentiles, and per-cell vs. per-county
    aggregation. None beat a training log error of 0.207.

### What the agents found (and what they kept)

- **Drought** (training log error 0.152 → 0.022, 24 experiments, $1.42).
  - The decisive change, found in round 4, was computing the Thornthwaite heat index per calendar
    year rather than from the whole-series climatology (0.135 → 0.031). Combined with the
    3-month SPEI, a generalized-logistic fit by unbiased PWMs, the 1950-2010 calibration and the
    −1.6 threshold, this reproduces FEMA's values almost exactly.
  - Smaller kept changes set a 15-day floor on historical drought days for cells with no
    historical drought. That constant was chosen on training states; the held-out score (0.021)
    shows it did not overfit.
- **Wildfire** (0.421 → 0.062, 24 experiments, $0.91).
  - The human baseline (state fixed effects) gave gamma = 0.37, below the "greater than 1" FEMA
    states. Dropping the spatial fixed effects did most of the work (0.265 → 0.113).
  - The agents then moved to the MME75 ensemble and the 95th-percentile FWI statistic, added a
    log-burnable-share control and burnable-share weights. Each step helped on training states.
  - On held-out states, each step after dropping fixed effects improved log error a little
    (0.111 → 0.072) but lowered correlation (0.993 → 0.960). The extra specification search fit
    the training states' levels at some cost to the ranking. `results/kept_pipelines_held_out.csv`
    scores every kept step on held-out states.
- **Extreme heat** (0.347 → 0.207, 21 experiments, $0.92). The one kept change, found in round 1,
  was dividing by the historical number of days over the percentile, without the heat-index
  condition. That matches FEMA's equation 9 more literally. Nothing after it helped.

### Claude Code subagents as the swarm (comparison)

We ran the wildfire loop a second way: three Claude Code subagents (Sonnet), each starting from
the same baseline, given the same rules and `program.md`, and steered to a different open
question. Each ran 6-8 experiments in its own copy (`results/claude-code-subagents/wildfire/`).
Each took about 2-3 minutes and 42-47k tokens.

| Run | Train log error | Held-out log error | Held-out same bin | Held-out Pearson |
|---|---|---|---|---|
| Pydantic AI swarm, final | 0.062 | 0.072 | 96.9% | 0.960 |
| Claude Code agent 1 (FWI statistic) | 0.264 | 0.278 | 91.2% | 0.911 |
| Claude Code agent 2 (Poisson pseudo-ML, FEMA-region fixed effects) | 0.079 | 0.073 | 97.8% | 0.993 |
| Claude Code agent 3 (no fixed effects, no fuel controls) | 0.030 | 0.027 | 99.3% | 0.993 |

Agent 3 found the simplest specification: gamma ≈ 1.30 from a plain log-log regression of
wildfire EAL on historical mean FWI (MME50). It beats everything else on both training and
held-out states. It also drops the fuel-type controls FEMA documents, and the agent flagged that
itself.

We did not swap it in as the final pipeline. The final pipeline is the swarm's, chosen by the
loop's own rule. Agent 3's result points to FEMA's effective gamma being close to what a simple
regression gives.

The Claude Code agents read the code and ran it themselves. That made them more willing to try
structural changes (a different estimator, dropping a control). The Pydantic AI agents only saw
scores and returned whole files, and they made smaller, safer edits.

## The swarm: numbers and every point a person stepped in

| | Extreme heat | Drought | Wildfire |
|---|---|---|---|
| Rounds × agents | 7 × 3 | 8 × 3 | 8 × 3 |
| Experiments run | 21 | 24 | 24 |
| Kept | 1 | 5 | 6 |
| Crashed | 0 | 0 | 0 |
| Pipeline compute (sum of run times) | 75 min | 11 min | 1.5 min |
| Wall clock | 78 min in two runs | 15 min | 5 min |
| Model cost (OpenRouter, logged per response) | $0.92 | $1.42 | $0.91 |

- **Totals:** 69 experiments plus 3 rejected by a harness bug, $3.31 of model calls. Everything
  ran on this machine (4 cores, 16 GB), with no Modal compute. Reducing the climate data took
  about an hour of wall clock and cost nothing.
- **Model:** `anthropic/claude-sonnet-5.5` via OpenRouter at temperature 0.8. The issue's budget
  was $25.

**Harness: Prime Agent was not used.** The issue asked us to try
[Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent). It supports OpenRouter and a
non-interactive `-p` mode, so it would have fit. Its only install route is a downloaded installer
script, and this session's sandbox blocked running it. We built the loop with Pydantic AI instead,
the agent framework this repo prescribes, and compared it with Claude Code subagents.

**Where a person had to step in:**

1. **Prime Agent install blocked** by the sandbox (above).
2. **Modal unreachable.** The Modal client uses gRPC, which this environment's proxy does not
   carry. The NEX reduction ran locally instead, about an hour on 4 cores.
3. **Harness bug: the answer-key guard rejected valid code.** The first wildfire round lost all
   three proposals. The guard banned the text `_HM"]`, which every pipeline writes for its own
   output columns, and banned `STATEABBRV`, which FEMA's state fixed effects need. The person
   removed both patterns and restarted. That run is kept in
   `results/experiments-wildfire-guard-bug.tsv` ($0.06).
4. **Kept code needed tidying.** The final wildfire pipeline left an unused FEMA-region table
   behind, and the kept wildfire and drought pipelines each had one type-check error. The person
   removed the dead code and fixed the types without changing results (re-scored to the same
   metric). The harness does not lint candidates.
5. **Heat stalled, and the person's nudge backfired.** After four rounds with no gain:
   - The person added `tasmax`, which had been skipped to save download time, and a dated note in
     `hazards/extreme_heat/program.md` describing the regional error pattern on training states.
   - In the next round all three agents tried the idea the note pointed at (heat index from
     `tasmax`), which was worse. In the round after, all three submitted byte-identical code.
   - The resumed run found nothing better. Steering the agents with a hint collapsed their
     diversity.
6. **Duplicate proposals.** After round 6 of heat, the person added a check that skips code
   identical to an earlier run. It applies to future runs.
7. **Bookkeeping fixes** in the report: a resume row counted as a proposal, and the best score
   taken over discarded rows.

The agents never tried to reach the answer key. No proposal was rejected by the guard once it was
fixed, and every kept change is a method choice we can read in the diff.

## Below the county: census tracts

`python -m fri_rebuild.downscale drought DRGT_LATE_HIGHER_HM 06 CA` reruns the final drought
pipeline with 2020 California tract polygons in place of county polygons. Each tract's multiplier
is the area-weighted mean of the 0.25-degree cells it overlaps. Tract projected annual loss is
NRI v1.19 tract drought EAL × tract HM. Outputs are in `results/tracts/`.

- **Coverage:** 9,109 tracts in 58 counties, 9,106 of them with NRI drought EAL. Tract
  multipliers run from 4.27 to 8.96. Within a county, the highest tract multiplier is typically
  1.26x the lowest (median).
- **Roll-up check:**
  - NRI tract EAL sums to NRI county EAL to within 5e-10, so the baselines are consistent.
  - Summing tract PAL gives a county PAL whose implied multiplier is EAL-weighted. It differs from
    the area-weighted county multiplier by a median 3.0% and at most 21.6%.
  - Against FEMA's published county values, the area-weighted county pipeline correlates at
    0.985 and the EAL-weighted roll-up at 0.887. FEMA's county multiplier is area-weighted, so
    tract PAL adds up to a slightly different county number than FEMA's HM. The gap comes from
    where the losses sit inside the county.

**What the downscaling assumes:**

- The climate signal is no finer than the NEX grid, 0.25 degrees or about 25 km. Small urban
  tracts inside one cell share its value; what varies between them is NRI's tract EAL.
- Exposure, historic loss ratios and community risk factors stay at today's values, as in the FRI.
- The tract multiplier comes from the same method as the county one, with no tract-level
  calibration. FEMA published no tract multipliers, so the tract values can only be checked by
  the roll-up, not against an answer key.
- **ZIP code or property level is not supported by this data.** Going below the tract would only
  repeat the 25 km cell value. It needs a finer climate product: LOCA2 at 6 km, or the 30
  arc-second data FEMA's document mentions, which we could not find published.

## What failed or wasn't covered

- **Hurricane wind** was not attempted. It depends on Applied Research Associates'
  climate-conditioned landfall rates, which FEMA sends only by email.
- **Coastal flooding** was not attempted. It was optional in the issue, and it needs the
  Interagency Sea Level Rise Task Force 2022 high-tide-flooding frequencies per tide gauge.
- **LOCA2 extreme heat** (`EXHT_L95/L99`) was not attempted. LOCA2 daily `tasmin` for
  MPI-ESM1-2-HR comes as 9-22 GB multi-decade files per scenario.
- **Extreme heat (NEX) is only a partial match.** N99 stays about 25% low with correlation
  0.68-0.78. We could not tell from FEMA's text how its heat-index filter and percentiles work.
- **Alaska, Hawaii and the territories** were not rebuilt.
- **FWI years.** The FWI ensemble files on NASA's portal are missing 4-7 years per period. FEMA
  may have had complete series.
- **Wildfire fit to its own training set.** The agents' wildfire specification search (24
  regressions) improved training levels at some cost to held-out correlation.
- **Selection.** Picking across harnesses with the held-out scores would contaminate them, so we
  did not.

## Files

- `run.sh`: the one command.
- `src/fri_rebuild/`: shared code.
  - Inputs: `nex.py`, `fwi.py`, `landfire.py`, `nri.py`, `geo.py`, `inputs.py`.
  - Scoring: `answer_key.py`, `split.py`, `score.py`, `experiment.py`.
  - The loop: `swarm.py`.
  - Outputs: `report.py`, `downscale.py`; `prepare.py` downloads everything.
- `hazards/<hazard>/program.md` and `pipeline.py`: the human brief and the final pipeline per
  hazard.
- `results/experiments-<hazard>.tsv`: every experiment (id, round, agent, parent, training
  metrics, keep/discard, seconds, cost, description). `results/candidates/` holds the code of
  each one.
- `results/scores.csv`, `results/largest_differences.csv`, `results/swarm_summary.csv`,
  `results/kept_pipelines_held_out.csv`, `results/county_hm_<hazard>.csv`: clean-run outputs.
- `results/tracts/`: the California tract table, the roll-up table and the map.
- `results/claude-code-subagents/wildfire/`: the Claude Code comparison runs.

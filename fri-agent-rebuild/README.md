# Rebuilding FEMA's Future Risk Index with a swarm of agents

Can agents working from FEMA's published methodology and public data rebuild the Future Risk
Index (FRI) county hazard multipliers, and take them below the county? This folder is the spike
for [issue #15](https://github.com/fulton-ring/agent-content-demos/issues/15)
([proposal card](https://app.notion.com/p/3facc69045cb8004a763e1047da67297)).

**Short answer.** The FRI has five hazards and seven sets of published county multipliers. Here
is where each landed on the 12 states the agents never saw:

| Hazard (FRI columns) | Rebuilt? | Same rating bin | Pearson | Typical error |
|---|---|---|---|---|
| Extreme heat, LOCA2 (`EXHT_L95/L99`) | Yes, essentially exactly | 99.7% | 1.000 | about 1% |
| Drought (`DRGT`) | Yes, essentially exactly | 99.6% | 0.998 | about 2% |
| Wildfire (`WFIR`) | Close | 96.9% | 0.960 | about 7% |
| Extreme heat, NEX (`EXHT_N95/N99`) | Partly: N95 good, N99 about 25% low | 90.0% | 0.824 | about 27% |
| Coastal flooding (`CFLD`) | No: levels roughly right, ranking not | 75.0% | 0.279 | about 2x |
| Hurricane (`HRCN`) | Not attempted: FEMA's input is not public | | | |

- **Below the county:** a census-tract drought layer for California (9,109 tracts) sums back to
  county projected annual loss exactly. Its resolution is bounded by the 25 km climate grid.
- **The agents** ran 126 experiments across five hazards for $7.61 of model calls.
  - They found the changes that mattered for drought (the Thornthwaite heat index) and wildfire
    (the shape of the gamma regression).
  - They could not crack coastal flooding or the NEX heat index.
  - A person stepped in eleven times, listed below. Two were notes pointing the agents at an
    idea; the rest were harness fixes, blocked tools and data plumbing.
- **LOCA2 heat is matched by the human baseline alone.** It follows FEMA's text literally, and the
  agents only refined a binning detail. The NEX version follows the same method with the same
  climate model; the only extra step is a heat-index filter, so that filter must be where the NEX
  rebuild goes wrong.

![Drought hazard multiplier by census tract, California, late century, higher warming](results/tracts/DRGT_LATE_HIGHER_HM_CA_tracts.png)

## How to run it

```bash
./run.sh
```

`run.sh` needs [uv](https://docs.astral.sh/uv/) and about 35 GB of free disk. It does three
things:

1. Downloads every input into `~/.cache/fri-agent-rebuild` (set `FRI_CACHE` to move it). Nothing
   downloaded goes into the repo.
2. Runs each hazard's final pipeline (`hazards/<hazard>/pipeline.py`) and scores it against
   FEMA's published county values on training and held-out states.
3. Builds the tract-level output.

The first run takes most of a day, almost all of it climate downloads on this 4-core machine:

- **NEX-GDDP-CMIP6:** 924 global yearly files of about 250 MB each, about 230 GB transferred,
  each cut to the CONUS box. About one to two hours.
- **LOCA2:** about 55 GB of range reads of the days we need, from UCSD's server. It ran at
  roughly an hour per 30-year period, so five to six hours.

With the inputs cached, `run.sh` took 30 minutes.

The agent loop is not part of `run.sh`, because it costs money and gives different results each
run. To run it for one hazard (needs `OPENROUTER_API_KEY`):

```bash
uv run python -m fri_rebuild.swarm drought --rounds 8 --agents 3 --budget 3
```

The numbers in this README come from one clean run: a fresh clone of the branch with every cached
input deleted except the already-reduced NEX, FWI and LOCA2 arrays. Re-downloading those would
have taken several more hours. Its console output is in `results/clean_run.log`.

## Where the data comes from

| Input | Source | Notes |
|---|---|---|
| Answer key | `NRI_Future_Risk_Master_Datasheet_12052024.xlsx` from [fulton-ring/nri-future-risk](https://github.com/fulton-ring/nri-future-risk) at commit `c5cc0d6` | FEMA's own datasheet, downloaded before the tool was taken down in February 2025. It has county HMs, PAL ratings and the NRI v1.19 EAL each multiplier was applied to. Downloaded at run time. |
| Methodology | *National Risk Index: Future Risk Technical Documentation* (FEMA, December 2024) | [Archived copy at Harvard EELP](https://eelp.law.harvard.edu/wp-content/uploads/2025/03/NRI_Future_Risk_Technical_Document.pdf). Each hazard's `program.md` quotes the relevant section. |
| Drought, NEX extreme heat | [NASA NEX-GDDP-CMIP6](https://registry.opendata.aws/nex-gddp-cmip6/) (AWS open data), MPI-ESM1-2-HR r1i1p1f1, historical, SSP2-4.5, SSP5-8.5 | Daily `tasmin`, `tasmax`, `tas`, `hurs` and `pr` at 0.25 degrees. We take the newest file version per year (mostly v2.0). |
| LOCA2 extreme heat | [LOCA2](https://cirrus.ucsd.edu/~pierce/LOCA2/NAmer/MPI-ESM1-2-HR/0p0625deg/r1i1p1f1/) (UCSD), MPI-ESM1-2-HR r1i1p1f1, daily `tasmin` at 1/16 degree | We read only the days of each 30-year period, one gzip chunk per day, over HTTP. For each of the 220,047 cells that overlap a county, we keep a histogram of daily `tasmin` in 0.1 °C bins (`loca2.py`). |
| Wildfire | [NEX-GDDP-CMIP6 Fire Weather Index](https://data.nas.nasa.gov/gddpimpact/FWI/) (NASA "GDDP-IMPACT" portal), yearly multi-model-ensemble files MME25/50/75 | The portal is missing 4-7 of the 30 years in each period, and those years are skipped. MME50 has 122 of 150 years. |
| Fuels | LANDFIRE LF2022 FBFM40, from the [LANDFIRE ImageServer](https://lfps.usgs.gov/arcgis/rest/services/Landfire_LF2022/LF2022_FBFM40_CONUS/ImageServer) | Resampled to 500 m (nearest neighbour), because the 30 m national file is 3.4 GB. |
| Coastal flooding | NOAA CO-OPS [decadal high-tide-flooding projections](https://api.tidesandcurrents.noaa.gov/dpapi/prod/webapi/htf/htf_projection_decadal.json) (110 gauges), observed annual flood counts, flood thresholds; the 2022 Sea Level Rise Technical Report [data files](https://cdn.oceanservice.noaa.gov/oceanserviceprod/hazards/sealevelrise/Sea_Level_Rise_Datasets_2022.zip) | The report's extreme water level table covers exactly the 187 gauges FEMA cites. Its sea level projections cover 126 gauges plus a 1-degree grid. |
| NRI tract baseline | NRI v1.19.0 (March 2023) tract table, [Harvard Dataverse snapshot](https://doi.org/10.7910/DVN/JSQ8KZ) (file 10775728) | v1.19 is what the FRI was built on. FEMA no longer serves it, and fema.gov returns 403 from this environment. |
| Boundaries | Census 2020 cartographic boundaries (1:500k), counties and California tracts | Same county set as the datasheet, including the eight pre-2022 Connecticut counties. |

Scope is CONUS: 3,108 counties. FEMA's documentation defines "nationwide" for its climate inputs
as the contiguous US. Alaska and Hawaii have published drought, wildfire and coastal multipliers,
but we did not try to rebuild them.

## How it works

- **Answer key and scoring** (`answer_key.py`, `score.py`): we put rebuilt multipliers into
  FEMA's fixed NRI rating bins. The upper edge of each bin is the largest EAL observed in that
  rating, as in Section 3.2 of the technical document. Applied to FEMA's own multipliers, this
  reproduces 100% of the published PAL ratings, so "same rating bin" means the same thing FEMA's
  map showed.
  - We also report Pearson and Spearman correlation, the mean absolute log error
    (`log_mae` = mean |ln(rebuilt / published)|), and the median rebuilt/published ratio.
  - A county the pipeline leaves blank counts as HM = 1, so leaving hard counties blank can't
    help a score.
  - Counties whose published HM is exactly 0 cannot be scored in log terms and are left out.
    Only coastal flooding has any: 109 of its 407 CONUS counties.
- **Train/held-out split** (`split.py`): every fourth state in FIPS order is held out. That is 12
  states and 896 counties: AZ, CT, GA, IA, ME, MN, NE, NM, OH, RI, TX and WA. The agents only ever
  see training-state scores (2,212 counties). Held-out scores are computed after the loop ends.
- **Inputs** (`inputs.py`): a read-only API the pipelines use for climate arrays, histograms,
  tide-gauge tables, county weights and the NRI baseline. County values are area-weighted
  averages of grid cells, using exact polygon intersections in an equal-area projection.
- **One pipeline file per hazard:** `hazards/<hazard>/pipeline.py` is the only file the agents
  may change. Next to it, `program.md` is the human-written brief: what FEMA's document says, what
  the data looks like, and the open questions, numbered so agents can split them. Dated notes at
  the end of a brief are where a person stepped in.
- **The loop** (`swarm.py`), modelled on [karpathy/autoresearch](https://github.com/karpathy/autoresearch):
  - Each round, three agents (Pydantic AI, `anthropic/claude-sonnet-5.5` through OpenRouter)
    propose in parallel. Each gets `program.md`, the current best pipeline, its training scores
    (including the worst training states), the full experiment log and notes on earlier
    hypotheses, and returns a complete new file.
  - From the coastal run on, agents can call a read-only `describe_input` tool to see any input
    table's columns and first rows.
  - The harness rejects code that names the answer key, the scorer or the split, and skips code
    identical to an earlier run. It runs each candidate in a subprocess and keeps the best one if
    it beats the current best by more than 0.002.
  - The loop stops after a set number of rounds with no improvement or at its budget. Every
    proposal is logged in `results/experiments-<hazard>.tsv`, and its code is kept in
    `results/candidates/<hazard>/<id>.py`.

## Results (one clean run)

Mean over the four scenarios. Per-scenario numbers are in `results/scores.csv`; the five largest
misses per column and subset are in `results/largest_differences.csv`.

| Hazard | Subset | Counties | Same rating bin | Pearson | Mean abs log error | Median rebuilt/published |
|---|---|---|---|---|---|---|
| Extreme heat, LOCA2 (L95 and L99) | train | 2,212 | 99.4% | 0.996 | 0.013 | 1.000 |
| Extreme heat, LOCA2 (L95 and L99) | held-out | 896 | 99.7% | 1.000 | 0.009 | 1.000 |
| Drought | train | 2,212 | 99.3% | 0.997 | 0.022 | 1.000 |
| Drought | held-out | 896 | 99.6% | 0.998 | 0.021 | 1.000 |
| Wildfire | train | 2,212 | 97.9% | 0.944 | 0.062 | 1.007 |
| Wildfire | held-out | 896 | 96.9% | 0.960 | 0.072 | 0.985 |
| Extreme heat, NEX (N95 and N99) | train | 2,212 | 91.3% | 0.869 | 0.207 | 0.855 |
| Extreme heat, NEX (N95 and N99) | held-out | 896 | 90.0% | 0.824 | 0.240 | 0.811 |
| Coastal flooding | train | 236 | 71.1% | 0.472 | 0.640 | 0.975 |
| Coastal flooding | held-out | 62 | 75.0% | 0.279 | 0.662 | 0.935 |

NEX extreme heat split by threshold, held-out:

- **N95:** 94-96% same rating bin, Pearson 0.85-0.97, log error 0.09-0.15.
- **N99:** 83-87% same rating bin, Pearson 0.68-0.78, log error 0.26-0.38. Rebuilt values run
  about 0.72-0.79 of FEMA's.

### The largest differences and why

- **LOCA2 heat.** Almost every county is within a few percent. The exceptions are small
  Virginia independent cities (Alexandria, Falls Church, Colonial Heights, Manassas, Franklin).
  - FEMA publishes L99 = 1.0 for them; we get 14-21.
  - A likely reason is that FEMA's raster-to-county step gave these few-square-mile cities no
    6 km cell (no events, floored to 1), while we intersect cell polygons exactly.
- **Drought.** The largest misses are small or coastal counties: Richmond and Kings (NY),
  Jackson (MS), and a few Georgia counties on the held-out side. Even these are off by only 12-21%.
  - These counties overlap one or two 0.25-degree cells, some of them mostly ocean with no land
    data, so area weighting depends on very few cells.
- **Wildfire.** The largest misses are northern New England and northern New York (Orleans,
  Lamoille and Franklin in Vermont; Clinton, NY; Aroostook and Somerset in Maine). Our values
  there are about 1.4-1.7x FEMA's.
  - These are cool, wet counties where fire weather is low today, so a small absolute increase is
    a large ratio. The 95th-percentile FWI statistic the agents chose, raised to gamma, amplifies
    it.
  - FEMA computed the multiplier at census-block level, weighted by block EAL, which we cannot
    reproduce without block EAL.
- **NEX extreme heat.** N99 in Oklahoma and northeast Texas comes out at about 0.4x FEMA
  (Oklahoma County: 3.4 against 8.8). N95 runs low in the Northeast and Appalachians (0.7-0.8x).
  - LOCA2 heat, built with the same method and the same climate model but with a fixed
    temperature floor instead of a heat index, matches FEMA almost exactly. That isolates the
    heat-index step as the problem.
  - FEMA cites Lu and Romps (2022) for the 298 K threshold but gives no formula. NEX has only
    daily means of temperature and humidity, so how they were combined is a choice the document
    leaves open.
- **Coastal flooding.** No approach got the ranking right.
  - Some published values are hard to explain from tide-gauge data alone: Fredericksburg, VA, an
    inland city, gets 429 in late century; San Diego gets 254; Galveston, TX gets 33. All
    approaches put these near 5-30.
  - Every approach also overstates some low-risk inland counties. Williamsburg, SC is
    published at 0.5 and we get 28.
  - FEMA weights each flood severity by its share of the county's coastal-flood EAL. NRI does
    not publish that split, and FEMA also clips levee-protected areas. Both are missing from
    public data, and together they would explain a ranking we cannot reproduce.

### What the agents found (and what they kept)

- **Drought** (training log error 0.152 → 0.022, 24 experiments, $1.42).
  - The decisive change, found in round 4, was computing the Thornthwaite heat index per calendar
    year rather than from the whole-series climatology (0.135 → 0.031). Combined with the
    3-month SPEI, a generalized-logistic fit by unbiased PWMs, the 1950-2010 calibration and the
    −1.6 threshold, this reproduces FEMA's values almost exactly.
  - A kept 15-day floor on historical drought days was chosen on training states; the held-out
    score (0.021) shows it did not overfit.
- **Wildfire** (0.421 → 0.062, 24 experiments, $0.91).
  - The human baseline (state fixed effects) gave gamma = 0.37, below the "greater than 1" FEMA
    states. Dropping the spatial fixed effects did most of the work (0.265 → 0.113).
  - The agents then moved to the MME75 ensemble and the 95th-percentile FWI statistic, added a
    log-burnable-share control and burnable-share weights. Each step helped on training states.
    On held-out states those steps lowered correlation (0.993 → 0.960) while improving log error
    a little (0.111 → 0.072). `results/kept_pipelines_held_out.csv` scores every kept step.
- **NEX extreme heat** (0.347 → 0.207, 21 experiments, $0.92). The one kept change was dividing
  by the historical number of days over the percentile, without the heat-index condition. That
  matches FEMA's equation 9 more literally. Nothing after it helped.
- **LOCA2 extreme heat** (0.022 → 0.013, 12 experiments, $0.59).
  - The human baseline already matched FEMA, since it carried over what the NEX run had taught.
  - The agents kept one change: interpolating within the 0.1 °C histogram bins. That removes a
    rounding artifact of our own data reduction.
  - They tested and rejected the alternatives in the brief: applying the 296.22 K floor to the
    denominator too (much worse), per-cell ratios, and county-pooled histograms.
- **Coastal flooding** (1.793 → 0.640, 45 proposals over 15 rounds, $3.71).
  - The agents' biggest step was using the projections' own 2020 decade as "current" frequency,
    rather than observed counts (1.79 → 1.12).
  - After that, they mostly tuned which decade counts as "current" and the weight of each
    flood severity. Training error fell, but held-out correlation never rose above the human
    baseline's 0.32.
  - See below for the 187-gauge route a person pointed them to.

### Claude Code subagents as the swarm (comparison)

We ran two hazards a second way: Claude Code subagents (Sonnet), each starting from the human
baseline with the same rules and `program.md`, and steered to different open questions.

- Each ran 6-10 experiments in its own copy (`results/claude-code-subagents/<hazard>/`).
- Each took 2-3 minutes and 42-62k tokens.
- Unlike the Pydantic AI agents, they could read the data and run code themselves.

| Run | Train log error | Held-out log error | Held-out same bin | Held-out Pearson |
|---|---|---|---|---|
| Wildfire, Pydantic AI swarm (final) | 0.062 | 0.072 | 96.9% | 0.960 |
| Wildfire, Claude Code agent 1 (FWI statistic) | 0.264 | 0.278 | 91.2% | 0.911 |
| Wildfire, Claude Code agent 2 (Poisson pseudo-ML, FEMA-region fixed effects) | 0.079 | 0.073 | 97.8% | 0.993 |
| Wildfire, Claude Code agent 3 (no fixed effects, no fuel controls) | 0.030 | 0.027 | 99.3% | 0.993 |
| Coastal, Pydantic AI swarm (final) | 0.640 | 0.662 | 75.0% | 0.279 |
| Coastal, Claude Code agent 1 (187-gauge return-level route) | 0.790 | 0.764 | 69.8% | 0.311 |
| Coastal, Claude Code agent 2 (CO-OPS projection route) | 0.838 | 0.752 | 69.0% | 0.331 |

- **Wildfire:** Claude Code agent 3 found the simplest specification. A plain log-log regression
  of wildfire EAL on historical mean FWI gives gamma ≈ 1.30, and it beats everything else on
  training and held-out states.
  - It drops the fuel-type controls FEMA documents, and the agent flagged that itself.
  - We did not swap it in; the final pipeline is the one the swarm's own rule chose.
- **Coastal:** no harness got held-out correlation above 0.33.
  - The return-level route is closer to FEMA's 187-gauge description and beats the CO-OPS
    baseline. It does not beat the tuned CO-OPS version.

## The swarm: numbers and every point a person stepped in

| | NEX heat | LOCA2 heat | Drought | Wildfire | Coastal |
|---|---|---|---|---|---|
| Rounds × agents | 7 × 3 | 4 × 3 | 8 × 3 | 8 × 3 | 15 × 3 |
| Proposals (run) | 21 (21) | 12 (11) | 24 (24) | 24 (24) | 45 (43) |
| Kept | 1 | 1 | 5 | 6 | 9 |
| Crashed | 0 | 1 | 0 | 0 | 2 |
| Pipeline compute (sum of run times) | 75 min | 6 min | 11 min | 1.5 min | 2 min |
| Model cost (OpenRouter, logged per response) | $0.92 | $0.59 | $1.42 | $0.91 | $3.71 |

- **Totals:** 126 proposals plus 3 rejected by an early harness bug, $7.61 of model calls. The
  issue's budget was $25.
  - Coastal cost the most per round once agents could call `describe_input`: up to $0.61 per
    proposal, against about $0.03 without the tool.
- **Compute:** everything ran on this machine (4 cores, 16 GB), with no Modal compute.
- **Model:** `anthropic/claude-sonnet-5.5` via OpenRouter at temperature 0.8.

**Harness: Prime Agent was not used.** The issue asked us to try
[Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent). It supports OpenRouter and a
non-interactive `-p` mode, so it would have fit. Its only install route is a downloaded installer
script, and this session's sandbox blocked running it. We built the loop with Pydantic AI instead,
the agent framework this repo prescribes, and compared it with Claude Code subagents.

**Where a person had to step in:**

1. **Prime Agent install blocked** by the sandbox (above).
2. **Modal unreachable.** The Modal client uses gRPC, which this environment's proxy does not
   carry. All data reduction ran locally.
3. **Harness bug: the answer-key guard rejected valid code.** The first wildfire round lost all
   three proposals. The guard banned the text `_HM"]`, which every pipeline writes for its own
   output columns, and banned `STATEABBRV`, which FEMA's state fixed effects need. The person
   removed both patterns and restarted. That run is kept in
   `results/experiments-wildfire-guard-bug.tsv` ($0.06).
4. **Kept code needed tidying.** The final wildfire pipeline left an unused table behind, and two
   kept pipelines each had one type-check error. The person fixed them without changing results.
   The harness does not lint candidates.
5. **NEX heat stalled, and the person's nudge backfired.**
   - After four rounds, the person added `tasmax` and a dated note on the regional error pattern.
   - All three agents then tried the idea the note pointed at, which was worse. In the round
     after, all three submitted byte-identical code.
6. **Duplicate proposals.** The person added a check that skips code identical to an earlier run.
7. **Bookkeeping fixes** in the report: a resume row counted as a proposal, and the best score
   taken over discarded rows.
8. **Coastal: a note pointing to the 187-gauge route.** After ten rounds of tuning with no gain in
   correlation, the person added a dated note to `hazards/coastal_flooding/program.md`. It points
   out that FEMA's 187 gauges are exactly the 2022 report's extreme-water-level gauges, and that
   FEMA's sub-types are return periods.
9. **Coastal: the agents' silent fallbacks.** The next two attempts at that route guessed column
   names wrong, crashed, and silently fell back to the old method inside a `try/except` the agent
   had written, scoring exactly the same as before.
   - The Pydantic AI agents could not look at the data, only at scores.
   - The person added the read-only `describe_input` tool and a rule against fallbacks. After
     that, the route ran (0.826 training error), but no better than tuned CO-OPS.
10. **Data plumbing:** a dropped NEX download and a dropped LOCA2 read each needed retries added,
    and a container restart interrupted the LOCA2 reduction, which resumed from finished pieces.
11. **A dimension the human had chosen.** The person picked the LOCA2 histogram bin width (0.1 °C).
    The agents found and fixed the rounding it caused.

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
- **ZIP code or property level is not supported by the NEX data.** LOCA2 heat, now rebuilt at
  6 km, is the finest hazard here and could support a tract layer about four times finer. We did
  not build one.

## Reverse engineering FEMA's coastal flooding values (answer key open)

The blind rebuild failed for coastal flooding, so we studied FEMA's published coastal multipliers
directly (`python -m fri_rebuild.forensics`, outputs in `results/forensics/`). This part reads
the answer key on purpose; it says what structure produced FEMA's numbers, not whether agents can
find it.

**What the published values show:**

- **Zero means "no projection", and FEMA's own ratings treat it as 1.**
  - 120 counties with real coastal flood losses today are published with HM = 0. They are mostly
    Great Lakes counties, which have no sea-level gauges, plus inland Louisiana and others; East
    Baton Rouge has $1.2M of annual coastal-flood loss.
  - For all 120, FEMA's projected-loss rating equals the rating of today's loss, which is what
    HM = 1 gives. The published HM column says these counties' future coastal losses are zero,
    and the ratings say they are unchanged.
- **17 counties have 0 < HM < 1, which FEMA's documented formula cannot produce.** Examples:
  Effingham, GA at 0.013 for mid-century, Quebradillas, PR at 0.012, Williamsburg, SC at 0.03.
  - Equation 4 is HM = sum of (sub-type frequency factor x sub-type share of EAL). Under rising
    seas, flooding cannot get rarer, and shares that sum to 1 cannot give less than 1.
  - The published values only make sense if the shares often sum to well under 1, e.g. if EAL
    outside the minor/moderate/major flood zones got a factor of 0 instead of 1.
  - Ratings floor HM at 1, so this understatement does not show up in the ratings for these 17.
    It would also pull down counties whose HM stays above 1, and that cannot be checked from the
    published data.
- **The structure itself checks out.** Counties sharing a tide gauge lie exactly in a
  3-dimensional subspace of the four scenario values, as "gauge factor per sub-type x county
  weight" requires:
  - Magueyes Island, PR (14 counties), Astoria, OR (5) and Tacoma, WA (4) all score 0.0000 on
    the rank test.
  - Random groups of the same counties score 0.004-0.020.
  - The fits also show the weights do not sum to a constant.
- **Late century saturates on the Atlantic and Gulf coasts.** For 314 of 356 counties the two
  late-century scenarios (1.0 m and 2.0 m of sea-level rise) give identical multipliers. The 42
  exceptions are on the Pacific coast and in Puerto Rico and the Virgin Islands.
- **The multipliers follow the previous NRI release's coastal flooding footprint.** We compared
  them with NRI v1.18.1 (November 2021), the release before the one they were applied to. Our
  copy is a third-party one, but its coastal flood EAL matches FEMA's v1.18.1 tract layer on
  ArcGIS Online for every county.
  - In the 50 states and DC, all 303 counties with a non-zero multiplier had coastal flood EAL in
    v1.18.1. All 68 counties that gained coastal flood EAL only in v1.19.0 are published at 0;
    every Great Lakes county is among them.
  - The 2023 release changed coastal flooding everywhere. Building values were revalued (median
    1.74x). Frequency went from a handful of regional values to per-county values. The historic
    loss ratio changed by a median factor of 261.
  - The counties below 1 are mostly inland counties where the new method cut frequency and the
    mapped hazard area. These changes come from the method, not from local events.

**The recipe, found by search.**

Three Claude Code subagents searched for a recipe that reproduces FEMA's numbers from public NOAA
data (`python -m fri_rebuild.recipe_score <recipe.py>`). Two of them, starting from different
angles, converged on the same one, saved as `forensics/recipes/noaa_thresholds.py`. The search
logs are `forensics/recipes/agent*.tsv`.

- **Sub-types are NOAA's thresholds, not return periods.** They are NOAA's minor, moderate and
  major flood thresholds at each gauge (about 0.5, 0.8 and 1.2 m above high tide), not the
  1-2, 10-50 and 100-year floods FEMA's documentation names.
- **The frequencies come from the 2022 report's curves.** Each threshold's annual frequency is
  read off the gauge's return-level curve in the 2022 Sea Level Rise Technical Report, today and
  after lowering the threshold by the median relative sea-level rise. The scenarios are 1.0 m
  for the lower case and 2.0 m for the higher, in 2050 and 2100. Frequencies are capped at
  10 a year, the curve's shortest return period.
- **The factor is a ratio.** It is new frequency over today's frequency.
- **How well it fits:**
  - It reproduces 18 of the 42 counties with four distinct values to within 0.1%, with a median
    error of 1.4% across all 42. Before this recipe the best was 17% median error and none exact.
  - It predicts which counties have equal late-century values for 90% of counties.
  - It fits every other county with non-negative weights. The Magueyes Island, PR group fits to
    about 0.01%.
- **What still doesn't fit:**
  - Pacific gauges (Tacoma, Astoria, parts of Oregon and California) are off by 2-40%. They
    behave as if FEMA's cap or sea-level inputs differ there.
  - Some Atlantic gauges have identical mid-century values under both scenarios, which the recipe
    does not produce.
  - A global 6 cm reduction in the rise would cut the median error to 0.24%, but we have no
    physical reason for it, so it is not in the recipe.
- **What the recipe implies about the county weights:**
  - With the factors known, each county's sub-type weights can be solved. For the 279 counties
    fit within 1%, the weights sum to a median of 0.57, and 82% sum to less than 0.95
    (`results/forensics/coastal_weights_threshold_recipe.csv`).
  - NRI v1.19.0 defines five coastal flooding sub-types: NOAA's three high-tide-flooding zones
    plus FEMA's 1% and 0.2% annual-chance floodplains (its Technical Documentation, chapter 7).
  - The Future Risk formula adjusts only the three high-tide sub-types. If the floodplain share of
    EAL was simply left out rather than kept at a factor of 1, that explains the counties below 1.
    It also explains the zeros: Great Lakes counties have floodplain EAL but no tidal flooding.
  - This depends on our "today's frequency" matching FEMA's. A different baseline would rescale
    each sub-type's weights, so we treat the weight sums as strong evidence, not proof.
- **One retraction during the analysis.** An early subspace test seemed to match an uncapped
  return-period recipe to within 0.06°. That recipe produces factors as large as 10^24, which made
  the angle meaningless, so we dropped the test.

### What-if: the floodplain share, and how stale the inputs are

These are scenarios built on FEMA's own numbers (`python -m fri_rebuild.coastal_scenarios`,
`results/forensics/coastal_scenarios_*.csv`). They show how much the dropped floodplain share
could matter. They are not FEMA's values and not forecasts.

For the 279 counties the recipe fits within 1%, we treat the part of each county's weights
missing from 1 as the floodplain share. The variants are:

- **floodplain_kept:** that share keeps today's losses (factor 1).
- **floodplain_1pct:** that share grows the way the 1% annual-chance flood level does under the
  scenario's sea level rise.
- **floodplain_0_2pct:** the same for the 0.2% level, extrapolated past the curve's 100-year end.
  NRI does not publish how the floodplain share splits between the two levels, so the two
  variants bracket it.

| Scenario | Published | Floodplain kept at 1 | Floodplain grows (1% to 0.2% level) |
|---|---|---|---|
| Mid-century, lower | $4.95B/yr | $5.17B/yr (16 ratings change) | $5.98B-6.21B/yr (59-69 ratings change) |
| Mid-century, higher | $9.50B/yr | $9.73B/yr (7) | $12.0B-16.1B/yr (47-61) |
| Late century, lower | $59.0B/yr | $59.2B/yr (4) | $187B-327B/yr (64-81) |
| Late century, higher | $60.1B/yr | $60.3B/yr (4) | $272B-838B/yr (102-117) |

- **What the table shows:**
  - Keeping the floodplain share at today's losses changes little: about 4.6% in mid-century,
    under 1% late.
  - Letting it grow with sea level changes mid-century projected losses by 21-69%.
- **The late-century figures are not credible as estimates.**
  - By 2100, today's 100-year and 500-year flood levels are reached up to 10 times a year under
    these rises, so their frequency factors run into the thousands.
  - The same frequency-ratio method FEMA used for tidal flooding then multiplies today's
    floodplain losses as if every one of those floods did the same damage.
  - Like FEMA's own late-century coastal values, they say more about the method's limits than
    about future losses.
- **Did the flood frequency inputs shift?** Not the thresholds or the curves.
  - NOAA's current flood thresholds still equal its 2018 formula (0.04 x tide range + 0.50 m,
    0.03 x + 0.80 m, 0.04 x + 1.17 m above high tide). Using the formula for every gauge fits
    FEMA's values as well as the published thresholds do: 17 exact against 18, median error 1.4%
    in both, late-century pattern 91% against 90%.
  - The extreme water level curves are the 2022 report's.
- **The NRI baseline did shift.** NRI v1.20 (December 2025) moved coastal flood EAL a long way
  from v1.19.0, the baseline FEMA applied its multipliers to
  (`results/forensics/coastal_baseline_drift_v1_20.csv`):
  - National coastal flood EAL fell from $1.28B to $0.99B a year.
  - 73% of the 463 counties with coastal flood EAL in both releases changed by more than 2x
    either way; the middle half ranges from 0.21x to 2.5x.
  - 29 counties gained coastal flood EAL and 16 lost it. Part of that is Connecticut moving from
    8 counties to 9 planning regions.
  - FEMA's multipliers were never refit to v1.19.0 (see the v1.18.1 footprint above). Applying
    them to v1.20 would widen the mismatch.

## What failed or wasn't covered

- **Hurricane wind** was not attempted. FEMA's input is Applied Research Associates'
  climate-conditioned landfall rates, which FEMA sends only by email. We found no public copy,
  including in the Harvard Dataverse FRI snapshot.
  - Public stand-ins exist, but none matches FEMA's input: STORM synthetic tracks (SSP5-8.5 to
    2050 only), RAFT tracks (SSP5-8.5, late century only), Knutson et al. scaling factors (basin
    scale, not per location), and ARA's own white paper (RCP8.5 2050, as a figure).
  - Building from any of them would be a different method, not a rebuild.
- **Coastal flooding was attempted and not rebuilt** (above). The sub-type EAL split and levee
  clipping FEMA used are not public.
- **NEX extreme heat is only a partial match.** We could not reproduce FEMA's heat-index filter.
- **Alaska, Hawaii and the territories** were not rebuilt.
- **FWI years.** The FWI ensemble files on NASA's portal are missing 4-7 years per period. FEMA
  may have had complete series.
- **Wildfire fit to its own training set.** The agents' wildfire specification search improved
  training levels at some cost to held-out correlation. Coastal shows the same pattern more
  strongly.
- **Selection.** Picking across harnesses with the held-out scores would contaminate them, so we
  did not.

## Files

- `run.sh`: the one command.
- `src/fri_rebuild/`: shared code.
  - Inputs: `nex.py`, `loca2.py`, `fwi.py`, `landfire.py`, `coastal.py`, `nri.py`, `geo.py`,
    `inputs.py`.
  - Scoring: `answer_key.py`, `split.py`, `score.py`, `experiment.py`.
  - Forensics (answer key open): `forensics.py`, `recipe_score.py`; recipes in
    `forensics/recipes/`.
  - The loop: `swarm.py`.
  - Outputs: `report.py`, `downscale.py`; `prepare.py` downloads everything.
- `hazards/<hazard>/program.md` and `pipeline.py`: the human brief (with any dated
  interventions) and the final pipeline, for `extreme_heat` (NEX), `extreme_heat_loca2`,
  `drought`, `wildfire` and `coastal_flooding`.
- `results/experiments-<hazard>.tsv`: every experiment (id, round, agent, parent, training
  metrics, status, seconds, cost, description). `results/candidates/` holds the code of each one.
- `results/scores.csv`, `results/largest_differences.csv`, `results/swarm_summary.csv`,
  `results/kept_pipelines_held_out.csv`, `results/county_hm_<hazard>.csv`: clean-run outputs.
- `results/tracts/`: the California tract table, the roll-up table and the map.
- `results/claude-code-subagents/`: the Claude Code comparison runs for wildfire and coastal
  flooding.

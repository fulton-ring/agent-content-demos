# Which FWI ensemble and statistic match FEMA's wildfire multipliers?

FEMA's Future Risk Index wildfire multiplier is `(FWI_future / FWI_historic) ^ gamma`, from
NASA's NEX-GDDP-CMIP6 Fire Weather Index. FEMA doesn't say which of NASA's ensemble members
(MME25/50/75) or which yearly statistic it used. This spike compares **MME50 vs MME75** and
**annual mean vs 95th percentile (P95)**, and asks which reproduces FEMA's published county
multipliers.

It follows up the [FRI rebuild](../fri-agent-rebuild/), which tried these swaps, but each
on top of a different gamma regression. Here all four combinations run under the same two
regressions:

- **Simple**: OLS of ln(wildfire EAL) on ln(historical FWI), with no controls. This is the
  rebuild's best pipeline (Claude Code agent 3).
- **Swarm**: the rebuild's kept pipeline, which adds LANDFIRE fuel shares and ln(burnable
  share), weighted by burnable share.

## Results

FEMA's published HMs, 3,108 CONUS counties, held-out states (the rebuild's split), mean over
the four scenarios:

| Regression | Ensemble | Statistic | Log error | Same rating bin | Pearson |
|---|---|---|---|---|---|
| Simple | MME50 | mean | **0.027** | **99.3%** | 0.996 |
| Simple | MME75 | mean | 0.035 | 98.9% | 0.977 |
| Simple | MME50 | P95 | 0.059 | 97.5% | 0.977 |
| Simple | MME75 | P95 | 0.094 | 96.7% | 0.956 |
| Swarm | MME50 | mean | 0.036 | 99.0% | **0.997** |
| Swarm | MME75 | mean | 0.039 | 98.8% | 0.978 |
| Swarm | MME50 | P95 | 0.057 | 97.4% | 0.982 |
| Swarm | MME75 | P95 | 0.074 | 96.9% | 0.959 |

- **MME50 + annual mean is the best match under both regressions.** On training states and
  on all counties it ranks the same way (`results/scores.csv`).
- **Every switch away from it is worse on both log error and Pearson**, whatever the other
  choice and the regression. Switching to MME75 adds 0.003-0.036 to log error. Switching to
  P95 adds 0.017-0.059. Pearson drops by about 0.02 either way (`results/switch_effects.csv`).
- **P95 drives the northern New England overshoot.** The late-century, higher-warming median
  ratio of rebuilt to published HM in ME/NH/VT/NY is 0.89-0.91 with MME50 + mean, and
  1.19-1.38 with MME75 + P95. The rest of CONUS barely moves
  (`results/northeast_late_higher.csv`).
- **The rebuild's swarm went the wrong way.** It adopted MME75 and P95 because each helped the
  regression it had at the time. Under its own final regression, MME50 + mean beats MME75 + P95
  (training log error 0.039 vs 0.065).
- Even the best cell runs about 7% under FEMA for late-century, higher warming (median ratio
  0.93). That level gap is not explained here.

**Check against the rebuild.** Two cells are the rebuild's own pipelines. They score 0.0275
here vs 0.0267 there (agent 3), and 0.0738 vs 0.0718 (swarm). The likely cause: NASA's portal
now serves all 30 years per period, while the rebuild got 23-26. The rebuild didn't record
which years it lacked, so we can't confirm.

## Run it

```bash
./run.sh
```

It needs [uv](https://docs.astral.sh/uv/). The first run downloads FEMA's datasheet, Census
counties, LANDFIRE fuels at 500 m, one NEX-GDDP-CMIP6 file for the grid, and 300 yearly FWI
files (about 13 GB transferred, 30-40 minutes). They go into `~/.cache/fri-agent-rebuild`,
shared with the rebuild; set `FRI_CACHE` to move it. Once the files are cached the notebook
runs in under 10 seconds.

Read [`notebook.py`](notebook.py) top to bottom: the question, the data, each step, the
result. To open it interactively: `uv run marimo edit notebook.py`. It reuses the rebuild's
data download and scoring code (`fri_rebuild.data`, `inputs`, `scoring`) unchanged, so scores
are comparable.

## Where the data comes from

All public, downloaded at run time:

- FEMA `NRI_Future_Risk_Master_Datasheet_12052024.xlsx`, from
  [fulton-ring/nri-future-risk](https://github.com/fulton-ring/nri-future-risk). It holds the
  answer key and NRI v1.19 county wildfire EAL.
- [NASA NEX-GDDP-CMIP6 Fire Weather Index](https://data.nas.nasa.gov/gddpimpact/FWI/), yearly
  MME50 and MME75 files.
- LANDFIRE LF2022 FBFM40 fuel models, from the LANDFIRE ImageServer.
- Census 2020 cartographic county boundaries.

## What it doesn't show

- **Which ensemble and statistic FEMA actually used.** It shows only which public files
  reproduce FEMA's numbers best under these two regressions. FEMA's wording, "a MME which
  averages several distinct downscaled results", fits MME50 but doesn't name it.
- MME25 and the other statistics (P25-P75, day counts) are not in this grid. The rebuild's
  `experiments.jsonl` covers them under other regressions, and none beat the annual mean.
- FEMA weighted census blocks by block EAL, which isn't published. Here, county area weights
  stand in.
- The remaining ~7% late-century level gap.

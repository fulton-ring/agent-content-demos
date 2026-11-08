# Does a fuller substation map change where a geomagnetic storm hits the US grid hardest?

Spike for [issue #215](https://github.com/fulton-ring/agent-content-demos/issues/215)
([proposal card](https://app.notion.com/p/406cc69045cb81a2a8e3f4f82af7a142)). We rerun the open C-SWIM storm-loss
model from AGU Advances (Oughton, Bor et al. 2026) on its own grid, then on HIFLD Next transmission lines with our
verified substations (`us-substations-verified/dataset/`), and compare.

**Short answer:** HEADLINE

## Run it

```bash
./run.sh     # needs uv and about 15 GB of free disk on the first run
```

It runs the notebook [`gic_rerun.py`](gic_rerun.py) as a script and writes `outputs/`. To read it with each step's
output beside it: `uv run marimo edit gic_rerun.py`. The first run downloads C-SWIM's 11 GB data release once,
keeps about 1.5 GB of it in `data/` and deletes the rest. **Run time:** RUNTIME. It costs nothing.

## Data (all public, downloaded at run time, nothing downloaded is committed)

| Input | Source |
|---|---|
| Storm catalog (92 storms, 1985 to 2024), observatory magnetic fields, the published grid (10,464 substations), per-line storm voltages, return-period fits, C-SWIM's own Monte Carlo output | C-SWIM data release v5, [Zenodo 20089397](https://zenodo.org/records/20089397) |
| Magnetotelluric transfer functions (EarthScope USArray / USMTArray), 1,611 of C-SWIM's 1,616 sites | C-SWIM data release, [Zenodo 16994602](https://zenodo.org/records/16994602) |
| Transmission lines (after) | [HIFLD Next](https://hifld.publicenvirodata.org/) Transmission Lines v1.0.0 |
| Substations (after) | `us-substations-verified/dataset/us_substations.parquet` (HIFLD-derived plus OpenStreetMap via Overture, ODbL) |
| Population | Census 2020 block-group population centroids |
| Counties | Census 2024 cartographic boundaries, 1:500k |

## How

C-SWIM's code ([github.com/denniesbor/C-SWIM](https://github.com/denniesbor/C-SWIM), MIT) is written for a GPU
workstation with its own data folders, so the notebook rewrites each stage in a few lines, names the C-SWIM function
it follows, and checks it against C-SWIM's published output:

1. **Grid** (`08_p_power_grid.py`, `build_admittance_matrix.py`): substations within 150 m of a 160 kV+ line, lines
   split between neighbouring substations, a high- and low-voltage bus per substation.
2. **Storm voltages** (`calc_storm_maxes.py`): SECS fit to observatory fields ([pysecs](https://github.com/greglucas/pysecs)),
   magnetotelluric impedances ([bezpy](https://github.com/greglucas/bezpy)), integrated along each line, for all 92 storms.
3. **100- and 250-year values** (`stat_analysis.py`): median of 100 bootstrap truncated-lognormal fits per line.
4. **Currents and failures** (`est_gic.py`, `p_gic_files.py`): 1,000 Monte Carlo transformer setups, a sparse network
   solve, effective current per phase, C-SWIM's fragility curve.
5. **People and dollars**: people served = Census block groups nearest each substation; dollars = the paper's own
   rate per affected person (its loss model is linear in affected people).

## Results

RESULTS

## What it doesn't show

CAVEATS

## Outputs

- `outputs/national_totals.csv`: people affected and daily loss for each run (paper, C-SWIM's own Monte Carlo,
  our reproduction, before, after).
- `outputs/state_changes.csv`: substations, people served and expected people affected by state, before and after.
- `outputs/county_changes.csv`: the same by county, for the county grid-exposure index
  ([#199](https://github.com/fulton-ring/agent-content-demos/issues/199)) to reuse. Counties with one or two
  substations in either grid are blanked (`few_substations`), plus one more where a state would otherwise have a
  single blank. Rounded to the nearest 100 people.
- `outputs/headline.txt`, `outputs/state_change.png`, `outputs/run_log.txt`.

No substation coordinates, names or per-site results are written, per the founder's 2026-10-24 rule.

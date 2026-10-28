# Regenerating STORM's hurricane tracks ourselves, every year

Our hurricane layer ([`hurloss-public-rebuild/`](../hurloss-public-rebuild)) runs on STORM
(Bloemendaal et al. 2020): 10,000 years of synthetic North Atlantic tracks resampled from
IBTrACS 1980-2017. Its only host, 4TU.ResearchData, has been unreachable since 2026-10-22, and
STORM is frozen on that record. Can we rerun STORM on the latest IBTrACS each year and publish
the tracks ourselves? This is the spike for
[issue #142](https://github.com/fulton-ring/agent-content-demos/issues/142) (sub-issue of #23).

Three marimo notebooks, each readable on its own:

- [`regenerate.py`](regenerate.py): inputs, STORM's code and our patches to it, preprocessing,
  and the 10,000-year run.
- [`validate.py`](validate.py): basin statistics, US coastal return periods and county
  multipliers, compared with the record, NHC, STORM v4 and Odériz & Losada.
- [`publish.py`](publish.py): GeoParquet, STORM text files, manifest and a Portolan (STAC)
  catalogue for Source Cooperative, as a dry run.

## Short answer

**Yes, we can regenerate STORM ourselves each year from public data, and it is as good a
stand-in for STORM v4 as Odériz & Losada's published rerun. It is not identical: both reruns
put about half as many major hurricanes on the US coast as STORM v4 did, so our layer's
multipliers come out lower.** All numbers below come from `./run.sh` on a clean checkout.

- **It runs end to end from public inputs.** STORM's own code, from its author's GitHub at
  pinned commits, refits every coefficient to IBTrACS 1980-2025 and ERA5, then generates 10,000
  seeded years. It needed four bug fixes and some speed-ups, each listed with its reason in
  `regenerate.py`. One bug hung 2 of our 10 seeds forever.
- **Its inputs match STORM v4's.** Genesis rate 11.4 storms a year (STORM v4: 10.8, on 8 fewer
  seasons). Monthly genesis shares are within 2.3 points, potential intensity within 2.1 hPa,
  genesis pressure within 0.3 hPa. Our ERA5 pressure field is within 0.15 hPa of STORM's at the
  median North Atlantic grid point.
- **Basin-wide it matches the record:**

| Per year | Observed 1980-2025 | Ours | Odériz & Losada | Observed 1980-2021 |
|---|---|---|---|---|
| Storms | 11.7 | 11.4 | 11.2 | 11.6 |
| Hurricanes | 6.6 | 6.0 | 5.5 | 6.5 |
| Major hurricanes | 2.9 | 3.0 | 2.6 | 2.8 |

- **On the US coast it inherits STORM's shortfall, and then some.** Median over NHC's 12 sites,
  as a rate against NHC's HURISK:

| | Hurricanes | Major hurricanes |
|---|---|---|
| Ours | 0.44× | 0.29× |
| Odériz & Losada | 0.44× | 0.35× |
| STORM v4 | 0.52× | 0.50× |
| Observed tracks, 1900-2025 | 1.21× | 0.76× |

  Against STORM v4, ours puts 0.83× the hurricanes and 0.54× the major hurricanes near these
  sites. Odériz & Losada's rerun does the same (0.84×, 0.56×). Two independent reruns agree
  with each other and not with STORM v4, which points at how the v4 files were made. We can't
  check this while 4TU is down.
- **Swapped into the hurricane layer** (Eq. 11-12, Knutson frequency-only, same grid):

| Scenario | County median, ours | STORM v4 | Odériz & Losada | Spearman ours vs v4 | Odériz vs v4 |
|---|---|---|---|---|---|
| Mid-century, lower | 1.006 | 1.031 | 1.015 | 0.47 | 0.47 |
| Mid-century, higher | 1.010 | 1.044 | 1.022 | 0.46 | 0.47 |
| Late century, lower | 1.011 | 1.049 | 1.024 | 0.46 | 0.47 |
| Late century, higher | 1.044 | 1.130 | 1.074 | 0.46 | 0.47 |

  The county ranking moves no more than with any other 10,000-year rerun: ours against Odériz
  & Losada is 0.38-0.39. The level drops because fewer coastal major hurricanes leave less for
  Knutson's Cat 4-5 increase to act on. Knutson's later baseline isn't the cause: on v4's
  1980-2018 baseline our late-higher median is 1.046.

## Publishing it yearly

- **Cost per run on 4 cores:** ERA5 means COST_ERA5; STORM preprocessing COST_PRE; generator
  COST_GEN_PER CPU per 1,000 years, COST_GEN_TOTAL for 10,000 (COST_GEN_WALL wall). Validation
  wind fields: about 55 min more for two catalogues.
- **Disk:** 37 MB of STORM text per 1,000 years (372 MB for 10,000). A release is COST_REL MB:
  GeoParquet points 87 MB, zipped STORM text 107 MB, plus metadata. About 6 GB of cache.
- **Trigger:** a new North Atlantic season appears in IBTrACS with no `PROVISIONAL` tracks.
  That happens once NHC's post-season best tracks (HURDAT2) land, usually in spring. 2025 is
  final today; 2026 is still provisional. A monthly check of IBTrACS's since-1980 file is enough.
- **What's fixed and what isn't:** IBTrACS, ERA5 pressure and SST, and STORM's code are refetched
  every run. STORM's land masks and coastline (from its GitHub) and its hard-coded constants
  (decay parameters, basin edges, potential-intensity floors) stay fixed. Every input,
  checksum, commit and seed goes into `manifest.json`.
- **Layout:** `publish.py` writes a Portolan catalogue (STAC 1.1 plus GeoParquet) with one
  collection per release, `storm-north-atlantic/ibtracs-1980-2025-seed1/`, so old releases stay
  addressable. `portolan check` passes and `portolan push --dry-run` lists 4 files and 1
  version. Its metadata is in `sample_catalogue/`. Nothing was pushed. That needs a bucket, a
  contact address and a founder's yes on the licence (CC-BY-4.0, for ERA5's attribution).

## How to run it

```bash
./run.sh
```

It needs [uv](https://docs.astral.sh/uv/), `git`, 4 cores and about 6 GB of disk. `run.sh` runs
the three notebooks as scripts (`uv run <notebook>.py`), so every table in `results/` comes from
the code a reader sees. To read one with its outputs: `uv run marimo edit validate.py`.

- Everything downloaded or generated goes to `~/.cache/storm-yearly-regeneration`
  (`STORM_CACHE`). The release is written to `STORM_CACHE/publish/fri-storm` (`STORM_PUBLISH`).
- Settings, all optional: `STORM_WORKERS` (default all cores), `STORM_YEARS` (default 10000),
  `STORM_SEED` (default 1), `STORM_LAST_SEASON` (default: the latest season IBTrACS has with no
  provisional tracks), `STORM_RESULTS`, `STORM_CONTACT_EMAIL` (catalogue contact, placeholder
  by default).
- `validate.py` reads the hurricane layer's committed results from
  `../hurloss-public-rebuild/results/layer/`, so run it from a checkout of the whole repo.
- Tests: `uv run pytest` checks that STORM's downloaded pickles are read without running code.
- No model calls and no paid services.

## Where the data comes from

| Input | Source |
|---|---|
| Tracks | NOAA [IBTrACS v04r01](https://www.ncei.noaa.gov/products/international-best-track-archive), since-1980 file, downloaded each run |
| Pressure and SST | ERA5 hourly fields from Google's public [ARCO-ERA5](https://github.com/google-research/arco-era5) store, 8 hours a month averaged per calendar month |
| STORM code | [NBloemendaal/STORM](https://github.com/NBloemendaal/STORM) @ `a9a2b14` and [STORM-preprocessing](https://github.com/NBloemendaal/STORM-preprocessing) @ `a7893ef`, GPL-3.0, downloaded at run time (not committed) |
| STORM v4 check inputs | [Zenodo 6337644](https://zenodo.org/records/6337644) (CC-BY-4.0): STORM v4's fitted inputs and MSLP fields |
| STORM v4 results | `hurloss-public-rebuild/results/layer/` (committed when 4TU was up) |
| Odériz & Losada (2025) | [Zenodo 15097665](https://doi.org/10.5281/zenodo.15097665) (CC-BY-4.0), 1980-2021 climatology, North Atlantic files read out of the zip with range requests |
| NHC return periods | HURISK maps, [nhc.noaa.gov/climo](https://www.nhc.noaa.gov/climo/), as read in `hurloss-public-rebuild` |
| Counties | Census 2020 cartographic boundaries |

Looked at first: the Copernicus CDS monthly-means product (needs an account), NCAR's ERA5 monthly
mirror (its server presented a self-signed certificate from here), NOAA PSL's NCEP reanalysis
(HTTP 403 from here), and a mirror of STORM v4's tracks (none found).

## What it doesn't show

- That our tracks are better than STORM v4's on the coast. Both reruns have fewer coastal
  major hurricanes than v4 and than NHC. Without v4's tracks we can't tell whether v4 used
  different code or inputs.
- STORM v4's basin statistics (storms, categories): they were never saved, and 4TU is down.
- ERA5's official monthly means. We average 8 hourly fields a month from Google's ARCO copy.
  The result is within 0.15 hPa of STORM's field, but it isn't the product STORM used.
- Run-to-run spread. One seed per run. Different seeds would show how much the coastal and
  county numbers move on their own (Odériz & Losada against us is a rough proxy).
- Other basins, future climates (STORM's GCM deltas) and the SQLMesh pipeline. The generator is
  one function over a folder of inputs, so it could become a Python model there later.

## Files

```
regenerate.py        inputs, patches, preprocessing, the 10,000-year run (marimo)
validate.py          checks against the record, NHC, STORM v4, Odériz & Losada (marimo)
publish.py           the yearly release as a Portolan catalogue, dry run (marimo)
generator.py         STORM's master loop, in a module so a process pool can run it
common.py            settings and download helpers shared by the notebooks
tests/               the safe reader for STORM's pickled files
results/             tables and figures from the run
sample_catalogue/    the catalogue's metadata files (STAC, README, versions), without the data
run.sh               the one command
```

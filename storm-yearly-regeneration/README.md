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

RESULTS_PLACEHOLDER

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

DOESNT_PLACEHOLDER

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

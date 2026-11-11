# Does HIFLD Next pass Portolan's checks, and what would it cost to conform?

[Portolan](https://portolan-sdi.org) is the Cloud-Native Geospatial Forum's spec for publishing geospatial data as
plain files in object storage. [HIFLD Next](https://hifld.publicenvirodata.org) was built before it. This spike
runs Portolan's validator over HIFLD Next's whole catalog, generates the fixes as files a pipeline could write,
re-checks them, and rebuilds a sample of HIFLD Next's PMTiles with tylertoo and with tippecanoe. Issue: #205.

Two [marimo](https://marimo.io) notebooks, each readable on its own:

- [`portolan_check.py`](portolan_check.py): validate the published catalog, a data-pass sample and the hosting,
  generate the fixes on a local copy, re-validate, the cost to conform, and what Portolan doesn't cover.
- [`tiling_benchmark.py`](tiling_benchmark.py): tylertoo against HIFLD Next's own tippecanoe command on the same
  GeoParquet.

## Run it

```bash
sudo apt-get install tippecanoe=2.49.0-1build1   # Ubuntu 24.04; the version HIFLD Next's tiles were built with
./run.sh
```

It needs [uv](https://docs.astral.sh/uv/), internet access, about 15 GB of free disk, and no key or account.
`run.sh` runs both notebooks as scripts and writes `outputs/`:

- `validator_published.json`, `validator_live.json`, `validator_data_sample.json`, `validator_fixed.json`: rashid's
  JSON output for each pass;
- `rules_before_after.csv`: findings per rule before and after the fixes;
- `summary.json`: the headline numbers of the first notebook;
- `tiling_benchmark.csv` and `tiling_summary.json`: one row per layer, and totals;
- `*.log`: each notebook's printed output.

`uv run marimo edit portolan_check.py` opens a notebook with its tables. The fixed catalog is written to
`data/fixed/` and is not committed. Validator: rashid 0.3.0, the engine behind portolan-cli 0.9.0, the current
releases on PyPI, pinned in `pyproject.toml` with tylertoo 0.8.0.

## Where the data comes from

All public and read at run time: HIFLD Next's static STAC catalog at
`https://storage.googleapis.com/hifld-next-datasets-prod/catalog.json` (1,383 documents: 330 layers, 857 catalogs,
526 collections), its GeoParquet and PMTiles files, and the site's live endpoints. HIFLD Next's STAC *API* at `/stac`
can't be validated: rashid needs a `catalog.json`, and the API has none (it fails rule PTL-GEN-000). The pipeline
writes the static tree beside it, and that tree is what Portolan describes.

## Results

RESULTS_PLACEHOLDER

## What we looked at first

rashid's own crawler (`rashid.remote.crawl`) makes the local copy. We tried `portolan check --fix --metadata
--dry-run` on that copy first. Its help says it converts files to cloud-native formats and refreshes stale
metadata, and it hadn't finished after 5 minutes, so the fixes here are our own code, listed in the notebook. tylertoo's Python
wheel provides the tiler; tippecanoe comes from Ubuntu's package, the same 2.49.0 recorded in every HIFLD Next
PMTiles file's `generator` field. Building tippecanoe 2.79.0 from source wasn't allowed in this sandbox.

## What it doesn't show

- The data pass read 25 collections' GeoParquet and PMTiles, not the 600 GB of all assets.
- The benchmark is a sample, not every layer; the six layers over 2.1 GB (flood hazard and hydrography) were left
  out. Timings are from a 4-core, 16 GB sandbox, one run each.
- Passing rashid checks Portolan's structure and metadata, not whether a README is useful. HIFLD Next's collection
  READMEs and AGENTS.md files are one line each, and our generated lines don't change that much.
- Nothing was changed in production, and HIFLD Next wasn't registered in Portolan's registry: both are founder calls.

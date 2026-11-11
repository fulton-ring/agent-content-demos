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

It needs [uv](https://docs.astral.sh/uv/), internet access, about 25 GB of free disk (the largest point layer ran out with 11 GB free in our run), and no key or account.
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

From the clean-checkout run of 2026-11-11 (`./run.sh`, about 2 h 15 min). Every number below is in
`outputs/summary.json`, `outputs/rules_before_after.csv` or `outputs/tiling_summary.json`. Cost $0.

**Today, nothing passes.** 0 of 330 layers, 0 of 857 catalogs and 0 of 526 collections are free of errors:
11,019 errors and 1,586 warnings across 16 rules. Most of them come from one pipeline habit. The tree is written
with absolute URLs that point at two copies of the catalog (`releases/<id>/` and the bucket root), so every link
"doesn't resolve" (PTL-LNK-006, 3,812), every object looks orphaned (PTL-LNK-002, 1,382), and the AGENTS.md and
README.md links are rejected (1,361 each). The files do exist next to every object except the root. Real gaps:
mirror metadata (no `updated` 527, no `via` 519), `license: other` with no licence link (523), and no thumbnail,
style or `pmtiles:layers` (about 510 each).

**The data and hosting are fine.** The data pass on 25 sampled collections (1.7 GB of GeoParquet and PMTiles)
found no errors in sizes, GeoParquet layout or tiles. The checksums can't be verified: they're MD5 and Portolan
wants SHA2-256. The live pass found range requests and CORS working. Its only errors are the two missing root files.

**After the generated fixes, 33 errors are left.** 857 of 857 catalogs, 493 of 526 collections and 299 of 330
layers pass. What's left: 27 collections with no thumbnail (no PMTiles, or nothing in their first five zooms),
6 with no source link to put in `via`, and two warnings: 526 collection IDs with slashes and 10 assets with no
checksum. Renaming the IDs would break the API, the MCP server and existing links, so it's a founder call.
The fixes are about 300 lines in the notebook.

**Cost to conform: about 3 to 4 days of pipeline work**, by our estimate (broken down in the notebook), plus
writing READMEs and AGENTS.md files that say more than one line.

**Portolan stops at the files.** HIFLD Next's MCP server, JSON search API, OGC API Features, STAC API, llms.txt
and agent-skills index all answered live. The spec has no rules for any of them, nor for version history.

**tylertoo vs tippecanoe**, on 27 layers (8 seeded per geometry class plus the largest of each under 2.1 GB):

| | tylertoo | tippecanoe 2.49.0 (HIFLD Next's command) |
|---|---|---|
| Layers built | 27 of 27 (8 after reprojecting to EPSG:4326) | 25 of 27 (our FlatGeobuf step failed on 2) |
| Total time, 25 layers both built | 429 s | 2,993 s; 3,073 s with the FlatGeobuf step |
| Median speedup per layer | 5.4x (points 3.1x, lines 6.8x, polygons 5.8x) | |
| Largest: NHD flowlines, 2.7 M lines | 294 s, 9.5 GB peak, 1.1 GB file | 2,349 s, 12.4 GB peak, 4.0 GB file |
| Peak memory higher on | 19 of 25 layers | 6 of 25 |
| Total size | 1.8 GB | 4.6 GB |

The two tools don't build the same tiles. Each picks its own maximum zoom: tylertoo goes deeper on points and
lines and much shallower on small polygon layers (zoom 0 to 5 where tippecanoe goes to 8 to 11). On the 16 layers
where tylertoo went at least as deep, it was still 4.5x faster at the median. 23 of 25 layers differ by more than
5% in features at the finest shared zoom, or in which columns survive: tylertoo drops binary columns, tippecanoe
drops columns that are empty everywhere (checked on one layer). tylertoo can't read EPSG:4269 or 5070 at all, which covers the census and
some hydrography layers. So "several times faster" holds, but its output would need checking layer by layer
before it replaced tippecanoe.

## What we looked at first

rashid's own crawler (`rashid.remote.crawl`) makes the local copy. We tried `portolan check --fix --metadata
--dry-run` on that copy first. Its help says it converts files to cloud-native formats and refreshes stale
metadata, and it hadn't finished after 5 minutes, so the fixes here are our own code, listed in the notebook.
tylertoo's Python wheel provides the tiler. tippecanoe comes from Ubuntu's package: 2.49.0, the version and
command recorded in the `generator` fields of the HIFLD Next PMTiles we checked. Building tippecanoe 2.79.0 from source wasn't allowed in this sandbox.

## What it doesn't show

- The data pass read 25 collections' GeoParquet and PMTiles, not the 600 GB of all assets.
- The benchmark is a sample, not every layer; the six layers over 2.1 GB (flood hazard and hydrography) were left
  out. Timings are from a 4-core, 16 GB sandbox, one run each.
- Two layers have no tippecanoe numbers: our FlatGeobuf step ran out of disk on one and hit rows with no geometry on
  the other. The notebook now handles both, but they weren't re-measured.
- Passing rashid checks Portolan's structure and metadata, not whether a README is useful. HIFLD Next's collection
  READMEs and AGENTS.md files are one line each, and our generated lines don't change that much.
- Nothing was changed in production, and HIFLD Next wasn't registered in Portolan's registry: both are founder calls.

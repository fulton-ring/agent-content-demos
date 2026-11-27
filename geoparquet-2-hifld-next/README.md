# What changes when HIFLD Next's GeoParquet moves to GeoParquet 2.0?

[GeoParquet 2.0](https://cloudnativegeo.org/blog/2026/11/geoparquet-2-0-released/) (released 2026-11-24) stores
geometry in Parquet's native `GEOMETRY` type, with a bounding box per row group in the file's statistics.
[HIFLD Next](https://hifld.publicenvirodata.org) publishes GeoParquet 1.1 with a `bbox` covering column. We
converted a seeded sample of six HIFLD Next layers to 2.0 in ten ways. Then we measured file size, bytes
fetched over HTTP range requests for the same box and attribute queries in DuckDB and GeoPandas, whether the
answers stayed the same, and which readers open the files. Issue:
[#331](https://github.com/fulton-ring/agent-content-demos/issues/331).

**Short answer.** The answers never change: 54 of 54 rewritten files hold byte-identical rows, and 270 of 270
query answers match the published file. Whether queries read fewer bytes depends on **who writes the file and
who reads it**, not on the spec version alone:

- A **DuckDB-written** 2.0 file lets a plain DuckDB `ST_Intersects` box query fetch **3.1 times fewer bytes**
  than the published file (233 MB against 723 MB over six layers). That's the same as DuckDB already gets from the
  published file if you add an explicit filter on its `bbox` column (232 MB). Sorted, with 10,000-row groups,
  it's **8.3 times fewer** (87 MB).
- A **GeoPandas/pyarrow-written** 2.0 file gives DuckDB 2.0.1 **no pruning at all** (685 MB). pyarrow writes
  the geospatial statistics but not the column's ordinary statistics block, and DuckDB then reads every row
  group. GeoPandas reads either writer's statistics.
- Files get **6 to 12% smaller** in total (the `bbox` column is 6.3% of the published bytes), but a point
  layer shrinks to **0.28 to 0.62** of its size.
- **Nothing more than a year old opens a 2.0 file:** DuckDB 1.3.2, GeoPandas 1.0.1/pyarrow 19 and GDAL 3.10.3
  all fail. **polars 2.2.0**, the current release, fails too.

## Run it

```bash
./run.sh    # needs uv and Docker; about 36 minutes; downloads ~690 MB and writes ~6.2 GB into data/
```

`run.sh` runs the marimo notebook [`geoparquet_2.py`](geoparquet_2.py) as a script and writes `outputs/`, so
every number here comes from the code a reader sees. To read it as a notebook: `uv run marimo edit
geoparquet_2.py`. Docker is used only for the two GDAL rows of the reader table, through the official
`ghcr.io/osgeo/gdal:ubuntu-full-3.13.3` and `-3.10.3` images; without Docker those rows say "not run". Set
`DATA_DIR` to put the data elsewhere, `REPEATS` (default 3) for the timing repeats, and `SEED` (default 331)
for another sample.

## Data

All public, read at run time from HIFLD Next's catalog API (`hifld.publicenvirodata.org/api`, 330 datasets,
1,049 layers, 514 distinct GeoParquet files). Candidates are layers with at least 100,000 features and a 10 to
500 MB file. We keep one layer per dataset, and polygons need above-median bytes per feature. Seed 331 drew:

| Class | Layer | Rows | Published | CRS |
|---|---|---:|---:|---|
| points | NFHL nodes | 349,459 | 29.1 MB, 4 row groups | EPSG:4269 |
| points | North American rail network nodes | 250,084 | 13.2 MB, 3 | EPSG:4326 |
| lines | NFHL water lines | 84,431 | 53.0 MB, 1 | EPSG:4269 |
| lines | North American rail network lines | 302,638 | 73.2 MB, 4 | EPSG:4326 |
| polygons | 2020 census blocks, Pennsylvania | 336,985 | 134.5 MB, 4 | EPSG:4269 |
| polygons | Voting districts | 158,444 | 384.3 MB, 9 | EPSG:3857 |

All six are GeoParquet 1.1, WKB, ZSTD, with a `bbox` column. Nothing downloaded is committed.

## How it works

Ten files per layer: the published file, GeoPandas 1.2 rewrites (1.1+bbox as a writer control, 2.0, 2.0+bbox,
each unsorted and Hilbert-sorted, plus a sorted 2.0 file with 10,000-row groups) and two DuckDB 2.0.1 rewrites
(`COPY ... GEOPARQUET_VERSION 'V2'`), all ZSTD 15. A local
[RangeHTTPServer](https://pypi.org/project/rangehttpserver/) serves them and logs each range request and the
bytes sent. Each layer gets a box query (2% of its extent on a side, around a seeded feature) and an attribute
query, and answers are compared by count and a hash of the returned geometries. Rows are compared by a hash of
every attribute plus the stored WKB bytes. The notebook explains each step.

## Results

From the clean-checkout run (`outputs/`). **MB fetched, summed over the six layers**
([`mb_totals.csv`](outputs/mb_totals.csv), per layer in [`mb_by_variant.csv`](outputs/mb_by_variant.csv)):

| Query, reader | published 1.1 | 2.0 | 2.0+bbox | 2.0 DuckDB-written | sorted 2.0 | sorted 2.0, 10k | sorted 2.0, 10k, DuckDB-written |
|---|---:|---:|---:|---:|---:|---:|---:|
| box, DuckDB `ST_Intersects` | 723 | 685 | 736 | **233** | 674 | 699 | **87** |
| box, DuckDB + `bbox` filter | **232** | – | 231 | – | – | – | – |
| box, GeoPandas `bbox=` | 332 | 294 | 323 | 275 | 470 | 124 | **121** |
| attribute, DuckDB | 445 | 446 | 447 | 497 | 446 | 414 | 450 |
| attribute, GeoPandas `filters=` | 744 | 673 | 725 | 650 | 642 | 878 | 787 |

Median time, summed over layers ([`ms_totals.csv`](outputs/ms_totals.csv)), local server, 3 repeats: the DuckDB box
query takes 3.3 s on the published file and 1.7 s on the sorted DuckDB-written file. The GeoPandas box query takes
2.3 s on the published file and **6.2 s on the 2.0 file**, which has no `bbox`: fewer bytes, but slower. File size
([`sizes.csv`](outputs/sizes.csv)), relative to the published file:

| Layer | 2.0 (GeoPandas) | 2.0+bbox | 2.0 (DuckDB) |
|---|---:|---:|---:|
| rail network nodes (points) | 0.33 | 1.00 | 0.28 |
| NFHL nodes (points) | 0.62 | 1.00 | 0.53 |
| rail network lines | 0.88 | 1.00 | 0.79 |
| NFHL water lines | 0.95 | 1.00 | 0.92 |
| census blocks PA (polygons) | 0.94 | 1.00 | 0.79 |
| voting districts (polygons) | 0.99 | 1.00 | 0.97 |
| **all six** (687.2 MB published) | 0.94 | 1.00 | 0.88 |

**Which readers open the files** ([`reader_compatibility.csv`](outputs/reader_compatibility.csv), six layers each):

| Reader | Published 1.1 | 2.0 (GeoPandas- or DuckDB-written, with or without bbox) |
|---|---|---|
| DuckDB 2.0.1 + spatial | ok | ok |
| GeoPandas 1.2.0 / pyarrow 26.0.1 | ok | ok |
| GDAL 3.13.3 | ok | ok |
| pyarrow 26.0.1, no geo library | reads, geometry as binary | reads, geometry as binary |
| polars 2.2.0 | reads, geometry as binary | **fails**: "LogicalType union has no variant set" |
| DuckDB 1.3.2 (a year old) | reads, no CRS | **fails**: "Geoparquet version 2.0.0 is not supported" |
| GeoPandas 1.0.1 / pyarrow 19.0.1 | ok | **fails**: "Thrift LogicalType that is not recognized" |
| GDAL 3.10.3 | ok | **fails**: unable to open |
| geoparquet-validator 0.4.0 | 4 of 6 conformant | 2.0: 6 of 6; 2.0+bbox: 5 of 6 |

The validator failures are in HIFLD Next's data: in NFHL nodes, 8 rows have a `bbox`
value but no geometry (`bbox-column-repetition`), and the voting districts file says `MultiPolygon` but holds Polygons
too. Rewriting with GeoPandas fixes the second. For the two EPSG:4326 layers, GeoPandas leaves the Parquet CRS empty
(Parquet's default, OGC:CRS84, the same coordinates), so DuckDB shows no CRS on the column.

## What this means for HIFLD Next

Converting changes no answers and makes files smaller. The read savings for DuckDB users come only from a
writer DuckDB can prune on, and they match what the published file already gives anyone who adds the `bbox`
filter. The real gain is that users no longer need to know the `bbox` column exists. The cost is every reader
more than about a year old, plus polars today. The release post's advice holds for this catalog: for the widest
audience, 1.1 with `bbox` is still the safer default. Publishing 2.0 alongside costs about 0.9 times the
GeoParquet storage again.

## What didn't work

- **Sorting at the guide's 100,000-row groups made reads worse** for most layers (GeoPandas box 470 MB against
  332 MB). With 2 to 4 groups per file, each sorted group covers a wide area and the box straddles groups. The
  published files are already in a rough spatial order: the box overlaps 1 or 2 of 4 row groups (3 of 9 for
  voting districts) ([`row_group_hits.csv`](outputs/row_group_hits.csv)). Only 10,000-row groups paid off.
- **DuckDB doesn't prune on pyarrow-written 2.0 files** (see above). We didn't look for a workaround. It's an
  interop gap between two current releases, worth reporting to DuckDB.
- The `gdal` wheel on PyPI has no binary and won't build here, and the pyogrio wheel's GDAL 3.12.4 has no
  Parquet driver. So GDAL runs from Docker.
- The catalog says NFHL water lines has 6,130,593 features; the file has 84,431. It got into the sample on the
  wrong count and stays in, as a single-row-group case where nothing can be skipped.
- For an `https://` URL, GeoPandas (through fsspec) first sends a GET without a range and abandons it. Those
  requests are counted (`unranged GETs` in [`queries.csv`](outputs/queries.csv)) but their bytes are not.

## What this doesn't show

- The network: the server is local, so times show reader work. Over the internet, fewer requests matter more.
  DuckDB-written files needed 277 requests against 1,105 for the published files.
- Six layers from the middle of the catalog, one box and one attribute query each. Smaller layers have one row
  group, so a format change can't help them.
- Files written by HIFLD Next's own pipeline, and the readers we didn't test: SedonaDB, Spark, QGIS,
  hyparquet. Nor GEOGRAPHY columns.
- What we used instead of our own code: GeoPandas, pyarrow and DuckDB writers, RangeHTTPServer, the official
  GDAL images, and geoparquet-validator. Our own code is the sampling, the query loop and the row hashes.

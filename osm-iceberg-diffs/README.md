# OSM replication diffs into Iceberg, against PostGIS

Can an [Apache Iceberg](https://iceberg.apache.org/) copy of OpenStreetMap be
kept current from OSM's replication diffs, the way osm2pgsql keeps PostGIS
current? And what does it take to stop Iceberg's metadata and small files from
piling up? This follows [#124](https://github.com/fulton-ring/agent-content-demos/pull/124),
which measured osm2pgsql → PostGIS on the same data.

**Verdict:** RESULTS_VERDICT

## Run it

Needs Docker, Java 17 or later (for Spark) and [uv](https://docs.astral.sh/uv/).
It took about RUN_MINUTES minutes and about 8 GB of disk on a 4-core, 16 GB machine.

```sh
./run.sh                          # = uv run hourly.py, then uv run replay.py
uv run marimo edit hourly.py      # to read either one as a notebook
```

- **`hourly.py`**: imports the extract into Iceberg and PostGIS, applies the
  same hourly diffs to both, and checks answers and geometry on both sides.
- **`replay.py`**: replays 1,000 minutely diffs into two fresh Iceberg copies,
  one left alone and one maintained by Spark every 60 diffs, and tracks
  metadata, files, snapshots and query time.
- **`osm_iceberg.py`**: what both share: the tables, the import, `apply_diff`,
  and the ten queries as DuckDB SQL.
- **`service.py`, `flex.lua`**: copied unchanged from #124's `overpass-modern-stack/`.

Data goes to `data/` (git-ignored), results and logs to `results/`. Optional
settings: `DIFF_HOURS` (default 16), `RUNS` (default 5), `MINUTES` (default
1000), `MAINTAIN_EVERY` (default 60).

## Data

- **Extract:** [BBBike's Washington DC extract](https://download.bbbike.org/osm/bbbike/WashingtonDC/),
  the same file as #124 (snapshot **2026-10-24T00:00Z**; BBBike refreshes it weekly).
- **Diffs:** the planet's hourly and minutely replication files from the
  snapshot on. They are whole-planet files, and both sides take in everything
  in them, as in #124.
- OSM data © OpenStreetMap contributors, [ODbL](https://opendatacommons.org/licenses/odbl/).

## How the Iceberg side works

Three tables in a PyIceberg SQL catalog (SQLite) with a local warehouse:
`nodes` (id, lat, lon, tags), `ways` (id, tags, node list, WKB line, bbox) and
`relations` (id, tags, members, WKB area for named multipolygons and
boundaries, bbox). DuckDB's `ST_ReadOSM` reads the extract. pyosmium reads each
diff and keeps each element's last version. Then `apply_diff` makes one
transaction per table, deleting the old rows and appending the new ones:

1. nodes;
2. ways: the changed ones, plus unchanged ways that use a changed node, with
   their lines rebuilt from current coordinates;
3. relations: the changed ones, plus area relations whose member ways were
   rewritten, with their areas rebuilt (`ST_BuildArea`). As in osm2pgsql, there
   is no area unless every ring closes.

Geometry is built in DuckDB SQL, and the same SQL runs at import and on every
diff. Iceberg commits one table at a time, so a diff is three commits, not one.

## Results

RESULTS_TABLES

## What the tools can do today

| Step | PyIceberg 0.12 | DuckDB 2.0 `iceberg` | Spark 4.1 + Iceberg 1.12 |
|---|---|---|---|
| Read | yes | yes, `iceberg_scan` on a metadata file | yes |
| Append | yes | needs a REST catalog | yes |
| Row-level delete | copy-on-write only; asking for merge-on-read warns and falls back | needs a REST catalog | yes |
| Upsert | `upsert()` (joins on the key) | `MERGE INTO`, REST catalog only | `MERGE INTO` |
| Expire snapshots | `maintenance.expire_snapshots()`, metadata only: the files stay on disk | no | `expire_snapshots`, deletes the files |
| Compact data files | no ("compaction is planned") | no | `rewrite_data_files` |
| Rewrite manifests | no | no | `rewrite_manifests` |
| Old `metadata.json` files | honours `write.metadata.delete-after-commit.enabled` | n/a | same |
| Catalog | SQL (SQLite) | REST only for writes and `ATTACH` | JDBC on the same SQLite file works |

So the pipeline writes with PyIceberg, queries with DuckDB, and needs Spark (or
another JVM engine) for maintenance.

## What we looked at first

We found no tool that keeps an Iceberg (or Delta) copy of OSM current from
diffs. The closest are two Parquet projects:

- **[osm-to-parquet](https://github.com/iandees/osm-to-parquet)** (Ian Dees, September
  2026) writes Parquet with resolved geometry to S3/R2 and "is kept current with
  the minutely replication diffs", re-reading touched parents. Not Iceberg; its
  status page says the planet build hasn't run yet.
- **[ohsome-planet](https://github.com/GIScience/ohsome-planet)** (HeiGIT) writes
  GeoParquet and ingests replication files through a RocksDB store of current
  elements. We couldn't confirm whether it rebuilds parents when a node moves.

Import-only, with no diffs: [QuackOSM](https://github.com/kraina-ai/quackosm),
DuckDB's `ST_ReadOSM`, [osm-parquetizer](https://github.com/adrianulbona/osm-parquetizer),
and Apache Sedona's `osmpbf` reader. Rebuilt in bulk: Daylight (shut down in
2024), Overture's monthly releases, and OSM on AWS's weekly ORC files. Applies
diffs, but not to a table format: [OSM Express](https://github.com/bdon/OSMExpress)
and [osm-live-updates](https://github.com/ad-freiburg/osm-live-updates).

## What didn't work, and what we changed

- **Parsing the extract in Python was slow.** A pyosmium handler took 155 s
  for 6.3 M nodes. DuckDB's `ST_ReadOSM` reads the same file in under a second,
  so the import uses it, and pyosmium only reads diffs.
- **Areas didn't match osm2pgsql at first.** `ST_BuildArea` builds whatever
  closed rings it finds, so relations cut by the extract's edge got partial
  areas that osm2pgsql (libosmium) refuses. Adding libosmium's rule (every way
  end must meet another, and have a location) brought the sets into line.
  What's left is listed under Results.
- **Spark's compacted files made queries slower.** The tables didn't pin a
  Parquet codec, so PyIceberg wrote zstd and Spark wrote gzip, and DuckDB's ten
  queries took about 40% longer after compaction. `oi.TABLE_PROPERTIES` now
  pins zstd.
- **Data file size matters for diffs.** PyIceberg's default target file size is
  512 MB, so the 143 MB `ways` table was one file, and every diff that touched a
  way rewrote all of it. The tables now cap files at 16 MB.
- **Smaller snags:** Spark's procedures read `'osm.t'` as catalog `osm`, table
  `t` when the catalog and namespace share a name, so the calls use `osm.osm.t`.
  Spark's `expire_snapshots` keeps anything newer than 5 days unless
  `older_than` is given. Spark writes a `.crc` file beside every file on a local
  disk; the counts skip them. DuckDB 2.0's `ATTACH` only takes REST catalogs, so
  queries use `iceberg_scan` on the current metadata file. And
  planet.openstreetmap.org dropped a connection mid-download, so downloads retry.

## What this doesn't show

- **One region, one machine, local disk.** On S3 every commit and every file
  read is a network round trip; the metadata cost would matter more there.
- **Planet diffs, not a regional feed.** Both sides store out-of-region
  elements the diffs create, so both tables grow, and both get slower per diff.
- **No concurrent writers.** Maintenance runs between diffs. In production it
  would run alongside, and commits would need conflict retries.
- **No distributed queries.** That was out of scope (see the issue).
- **No minutely PostGIS run.** The minutely replay is Iceberg only.

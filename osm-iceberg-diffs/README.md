# OSM replication diffs into Iceberg, against PostGIS

Can an [Iceberg](https://iceberg.apache.org/) copy of OpenStreetMap be kept current from replication
diffs, as osm2pgsql keeps PostGIS current, and what stops its metadata and small
files piling up? Follows [#124](https://github.com/fulton-ring/agent-content-demos/pull/124) (osm2pgsql → PostGIS, same data).

**Verdict: yes on one machine, if something compacts it every hour.** An hour of
planet diffs took Iceberg a median 7.2 s against PostGIS's 6.3 s, geometry
included, and both sides then gave the same IDs on all ten of #124's queries. A
minutely diff took 1–4 s. Left alone for 300 minutely diffs, though, queries went
from 4.4 s to 13.7 s and diffs from 1.1 s to 13.9 s. PyIceberg can't compact, so
Spark does it every 60 diffs (median 20 s a run). That kept every one of 1,000
diffs under 8 s, though times still crept up as planet data piled in. No
existing tool does this for Iceberg.

## Run it

Needs Docker, Java 17+ (for Spark) and [uv](https://docs.astral.sh/uv/). About 2 h 15 min (8 min for
`hourly.py`) and 5 GB of disk on a 4-core, 16 GB machine.

```sh
./run.sh                          # = uv run hourly.py, then uv run replay.py
uv run marimo edit hourly.py      # to read either one as a notebook
```

- **`hourly.py`**: both imports, the same hourly diffs to both, answers and geometry checked.
- **`replay.py`**: minutely diffs into three Iceberg copies with different maintenance.
- **`osm_iceberg.py`**: shared tables, import, `apply_diff` and the ten queries as DuckDB SQL.
- **`service.py`, `flex.lua`**: copied unchanged from #124's `overpass-modern-stack/`.

Data goes to `data/` (git-ignored), outputs to `results/`. Settings: `DIFF_HOURS` (16), `RUNS` (5),
`MINUTES` (1000), `SHORT_MINUTES` (300), `MAINTAIN_EVERY` (60).

## Data

- **Extract:** [BBBike's Washington DC extract](https://download.bbbike.org/osm/bbbike/WashingtonDC/),
  the same file as #124 (snapshot **2026-10-24T00:00Z**; BBBike refreshes it weekly).
- **Diffs:** planet hourly and minutely replication files from the snapshot on; both sides take in all of them.
- OSM data © OpenStreetMap contributors, [ODbL](https://opendatacommons.org/licenses/odbl/).

## How the Iceberg side works

`nodes`, `ways` (with a WKB line and bbox) and `relations` (with a WKB area for
named multipolygons and boundaries) in a PyIceberg SQL catalog on SQLite and a
local warehouse. DuckDB's `ST_ReadOSM` reads the extract; pyosmium reads each
diff. `apply_diff` then commits nodes, then ways (changed ones plus those using a
changed node, lines rebuilt), then relations (changed ones plus areas whose
member ways changed, rebuilt with `ST_BuildArea` and libosmium's ring rules).
The same geometry SQL runs at import and on every diff. Iceberg commits one table
at a time, so a diff is three commits.

## Results

From one run on a clean checkout. All outputs, including logs, are in `results/`.

### Hourly diffs, Iceberg against PostGIS (`hourly.py`)

| | Iceberg (PyIceberg + DuckDB) | PostGIS (osm2pgsql) |
|---|---:|---:|
| import time | 10 s | 28 s |
| disk after import | 269 MB | 1,263 MB |
| one planet hour of diffs, median of 16 (range) | 7.2 s (3.1–10.6) | 6.3 s (1.8–10.3) |
| changed nodes in the box current after 16 hours | 32 of 32 | 32 of 32 |
| #124's ten queries, same IDs as the other side | 10 of 10 before, 10 of 10 after | |

- **Diff time includes the geometry update:** about 2.3 s reading the file,
  1.0 s nodes, 2.6 s ways, 0.6 s relations (`results/diffs.csv`), rebuilding
  0–100 way lines and 0–4 areas per hour. Both sides slow over the 16 hours,
  since both keep everything the planet diffs create.
- **Derived geometry stays correct.** All 27 changed ways in the box have
  exactly osm2pgsql's line. 1,305 of Iceberg's 1,314 named areas match
  osm2pgsql's 1,311 (1,306 in an earlier run). The rest are DC multipolygons with
  touching outer rings, where `ST_BuildArea` and libosmium disagree, and
  out-of-region relations missing nodes. None changes a query result.
- **Queries are slower on DuckDB** (124–1,012 ms p50 against 3–326 ms): no spatial index; not tuned.

### Minutely replay, with and without maintenance (`replay.py`)

| | left alone | PyIceberg only | PyIceberg + Spark |
|---|---:|---:|---:|
| diffs replayed | 300 | 300 | 1,000 |
| apply time per diff, median of diffs 1–50 | 1.1 s | 1.2 s | 1.1 s |
| ... diffs 251–300 | 13.9 s | 4.5 s | 2.7 s |
| ... diffs 951–1,000 | | | 4.1 s |
| apply time, p99 (max) | 21.6 s (23.5) | 7.4 s (7.9) | 6.8 s (7.8) |
| at diff 300: metadata files / MB | 4,089 / 144 | 3,330 / 20 | 170 / 1.8 |
| at diff 300: live data files / snapshots | 840 / 1,272 | 840 / 3 | 20 / 6 |
| ten queries, start → diff 300 | 4.4 → 13.7 s | 4.5 → 8.2 s | 4.5 → 4.7 s |
| ten queries at diff 1,000 | | | 7.3 s |

- **"PyIceberg only"** (merge manifests on commit, keep 5 `metadata.json`,
  `expire_snapshots` every 60 diffs) cut metadata 7× but not the 840 small data
  files, so queries still nearly doubled. Only compaction fixes those.
- **Spark maintenance** ran 16 times, 16–26 s each (median 20 s), taking live
  data files from about 200 back to 20–26 (`results/replay_maintenance.csv`).
- **Even maintained, times rose** over 17 hours (apply 1.1 → 4.1 s, queries
  4.5 → 7.3 s), most likely from the out-of-region rows the planet diffs keep
  adding. A regional feed should flatten this; we didn't test it.
- **A reasonable schedule:** apply minutely (or in 5–15 minute batches), and
  compact, expire and rewrite manifests hourly.

## What the tools can do today

| Step | PyIceberg 0.12 | DuckDB 2.0 `iceberg` | Spark 4.1 + Iceberg 1.12 |
|---|---|---|---|
| Read / append | yes / yes | `iceberg_scan` / REST catalog only | yes / yes |
| Row-level delete | copy-on-write only; asking for merge-on-read warns and falls back | needs a REST catalog | yes |
| Expire snapshots | `maintenance.expire_snapshots()`, metadata only: the files stay on disk | no | `expire_snapshots`, deletes the files |
| Compact data files | no ("compaction is planned") | no | `rewrite_data_files` |
| Rewrite manifests | no | no | `rewrite_manifests` |
| Old `metadata.json` files | honours `write.metadata.delete-after-commit.enabled` | n/a | same |
| Catalog | SQL (SQLite) | REST only for writes and `ATTACH` | JDBC on the same SQLite file works |

## What we looked at first

No tool we found keeps an Iceberg or Delta copy of OSM current from diffs. Closest:
[osm-to-parquet](https://github.com/iandees/osm-to-parquet) (Parquet on S3/R2,
"kept current with the minutely replication diffs", re-reads touched parents;
planet build not yet run) and [ohsome-planet](https://github.com/GIScience/ohsome-planet)
(GeoParquet fed by replication through RocksDB). Import-only: QuackOSM,
`ST_ReadOSM`, osm-parquetizer, Sedona's `osmpbf` reader. Bulk rebuilds:
Daylight (closed 2024), Overture, OSM on AWS. Diffs but no table format:
OSM Express, osm-live-updates.

## What didn't work, and what we changed

- **Python parsing was slow** (155 s for the extract); `ST_ReadOSM` takes under 1 s.
- **Areas didn't match at first:** `ST_BuildArea` built partial areas for
  relations cut by the extract's edge. libosmium's rule (every way end must meet
  another and have a location) fixed it.
- **Spark's compacted files slowed queries 40%:** Spark wrote gzip, PyIceberg
  zstd. `oi.TABLE_PROPERTIES` now pins zstd.
- **PyIceberg's 512 MB default files** meant rewriting all of `ways` per diff; now 16 MB.
- **The uncompacted copies were too slow for 1,000 diffs** (~5 h each); they stop at 300.
- **Snags:** Spark reads `'osm.t'` as catalog `osm` when catalog and namespace
  share a name (use `osm.osm.t`); its `expire_snapshots` keeps 5 days unless
  `older_than` is set; it writes `.crc` files (not counted); DuckDB only
  `ATTACH`es REST catalogs; OSM's server dropped a download and Maven Central
  rate-limited the Spark jars once, so downloads retry and jars cache in `data/ivy`.

## What this doesn't show

- **One region, one machine, local disk** (on S3 metadata would cost more), planet
  diffs not a regional feed, no concurrent writers, no distributed queries, and
  no minutely PostGIS run.
- **Not a production updater.** The first run fetches 1,000 minutely files at
  once (sequentially, cached). A real updater should use `pyosmium-up-to-date`
  or `osm2pgsql-replication`, catch up daily then hourly, check `state.txt` at
  most once a minute, and send a User-Agent with a contact.

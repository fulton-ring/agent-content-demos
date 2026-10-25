# Overpass on a modern stack

Can tools GIS teams already run answer the queries people send to the
[Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API) for one region,
and stay fresh with OSM's replication diffs? The candidate is **osm2pgsql →
PostGIS behind a 200-line FastAPI service** (`service.py`). The reference is
Overpass from the `wiktorn/overpass-api` Docker image. Both load the same extract
on the same machine, then get the same ten queries and the same diffs.

**Verdict: yes, for common read queries on a region.** All ten returned exactly
the same element IDs as Overpass, before and after the diffs. The candidate was
faster on eight, level on one and slower on one (median 4.0×). It imported 8×
faster (36 s against 287 s), used 37% less disk, and applied an hour of planet
diffs a little faster (8.4 s against 11.5 s). It isn't Overpass QL: it takes a
JSON equivalent of a subset, and 13 groups of QL features are missing.
[Postpass](https://github.com/woodpeck/postpass) already runs this design in
public, so the case for building our own is narrow.

## Run it

Needs Docker and [uv](https://docs.astral.sh/uv/). It took 16–22 minutes and about
6 GB of disk on a 4-core, 16 GB machine.

```sh
./run.sh            # = uv run benchmark.py
uv run marimo edit benchmark.py   # to read it as a notebook
```

`run.sh` downloads the extract and diffs into `data/` (git-ignored), imports
into Overpass then PostGIS, runs the benchmark, writes `results/` and stops both
containers. Optional settings: `EXTRACT_URL` (the queries assume DC), `RUNS`
(timed runs per query, default 7) and `DIFF_HOURS` (default 16).

## Data

- **Extract:** [BBBike's Washington DC extract](https://download.bbbike.org/osm/bbbike/WashingtonDC/):
  65 MB, 6.3 M nodes, 0.96 M ways, covering DC, Arlington, Alexandria and parts
  of Maryland. Our run used the **2026-10-24T00:00Z** snapshot; BBBike refreshes
  it weekly. We'd have used a Geofabrik state extract as the issue suggested, but
  `download.geofabrik.de` reset every connection from our sessions.
- **Diffs:** the planet's hourly replication files, starting at the snapshot.
  BBBike has no regional feed, so each is a whole planet hour (1–9 MB), an upper
  bound on a regional feed's work.
- OSM data © OpenStreetMap contributors, [ODbL](https://opendatacommons.org/licenses/odbl/).

## Results

From one run on a clean checkout. All outputs, including the log, are in `results/`.

| query | elements | same IDs | Overpass p50 ms | candidate p50 ms | speed-up |
|---|---:|:---:|---:|---:|---:|
| tag in bbox (nodes) | 197 | ✓ | 92 | 9 | 10.6× |
| tag in bbox (nodes, ways, relations) | 51 | ✓ | 264 | 243 | 1.1× |
| regex on a tag, whole extract | 151 | ✓ | 1,983 | 426 | 4.7× |
| around a point (500 m) | 29 | ✓ | 63 | 7 | 8.5× |
| area by name (parks in Alexandria) | 119 | ✓ | 1,136 | 209 | 5.4× |
| ways with their nodes | 4,636 | ✓ | 239 | 39 | 6.2× |
| recurse down from relations | 9,963 | ✓ | 496 | 164 | 3.0× |
| recurse up from nodes | 43 | ✓ | 144 | 335 | **0.4×** |
| substations in DC | 40 | ✓ | 725 | 222 | 3.3× |
| hospitals in Arlington County | 1 | ✓ | 525 | 180 | 2.9× |

| | Overpass | candidate |
|---|---:|---:|
| import time | 287 s | 36 s |
| disk | 2,020 MB | 1,263 MB |
| RAM at rest after queries (`docker stats`) | 245 MB | 1,280 MB |
| peak during import, page cache included | 4,605 MB | 3,429 MB |
| one planet hour of diffs, median of 16 (range) | 11.5 s (4.7–28.6) | 8.4 s (2.9–13.0) |

- **Latency:** median of 7 timed runs after a warm-up, over HTTP, default settings.
- **Recurse up** is the one loss. It uses osm2pgsql's bucket index on way node
  lists, which is built for updates; a plain GIN index on `nodes` would likely
  fix it, for more disk.
- **RAM at rest** isn't like for like: PostgreSQL's figure includes its shared
  buffers and active cache; Overpass reads through the OS cache, which
  `docker stats` doesn't count.
- **Freshness:** the 16 hours created or changed 32 nodes inside the extract's
  box (8 of them tagged). All 32 hold their final tags and coordinates on both
  sides, and all ten queries still return identical IDs. Diff times are per
  file in `results/diffs.csv`; the candidate's include the `osmium` step.

## What didn't work, and what we changed

- **Untagged member ways.** The first import missed 4 multipolygon relations in
  the area queries (3 parks, 1 substation): their outer ways carry no tags, and
  osm2pgsql skips those unless the style handles them. `process_untagged_way` in
  `flex.lua` fixed it.
- **A query-builder bug.** An unqualified `geom` in the area subquery bound to
  the area's own geometry, so "hospitals in Arlington" returned every hospital.
- **Overpass's Docker image needed two workarounds.** Its `init` mode only reads
  `.osm.bz2`, so the PBF is re-compressed first, which takes most of the 287 s
  import. With a named volume, `/db` is left readable only by the `overpass`
  user, so every query failed with `Permission denied` until we `chmod 755 /db`.
- **osm2pgsql refused raw planet diffs** ("node id … appears more than once").
  `osmium merge-changes -s` collapses repeated versions first, as
  `osm2pgsql-replication` does.
- **One hour of diffs proved nothing locally.** The hour after the snapshot,
  midnight UTC, had no edits inside DC, so we apply 16 hours.

## What the candidate can't do

13 groups of QL features, listed with costs at the end of the notebook. Five
are small additions on the same tables: role-aware recursion, `is_in`/`area(id)`,
`out count`/CSV, `poly:` and set-based `around`, and untagged nodes in spatial
filters. Five add up to a QL interpreter: the QL text itself, named sets,
`foreach`/`if`/`complete`, `>>`/`<<`, and evaluators. Attic queries (`[date:]`,
`[adiff:]`, `changed`) need a database that keeps history. Output is IDs only
(`out ids`); `body` and `geom` would be cheap from these tables.

## What we looked at first

- **[Postpass](https://github.com/woodpeck/postpass)** (Frederik Ramm, FOSSGIS)
  is this design in production: osm2pgsql flex → PostGIS, SQL over HTTP,
  updated every 5 minutes, queries queued by `EXPLAIN` cost, and supported by
  Overpass Turbo. It does no history and takes SQL, not QL.
- **[QLever](https://wiki.openstreetmap.org/wiki/QLever) + osm2rdf** is a SPARQL
  endpoint for the planet, with `osm-live-updates` for diffs. Qloverleaf, a
  closed proof of concept from June 2026, translates QL to SPARQL and hits the
  same history and imperative-QL limits.
- **[osm2pgsql](https://osm2pgsql.org/doc/manual.html)**'s middle tables (tags,
  way node arrays, relation members) already are Overpass's data model, and
  `osm2pgsql-replication` keeps them current. That's why the candidate is mostly
  configuration, not new code.
- **[OSM Express](https://github.com/bdon/OSMExpress)** applies minutely diffs
  but has no query language. **DuckDB spatial**'s `ST_ReadOSM`, QuackOSM and
  Overture's monthly GeoParquet are rebuild-only, so we didn't build on them.
- **Overpass's [setup guide](https://dev.overpass-api.de/overpass-doc/en/more_info/setup.html)**
  and the [wiktorn image](https://github.com/wiktorn/Overpass-API): 350–400 GB
  for the planet (800 GB–1 TB with attic); the public instance asks users to
  stay under about 10,000 queries and 1 GB a day.

## Worth building?

- **For our own HIFLD Next and substation pulls: yes, as a thin layer.** Run
  osm2pgsql with `osm2pgsql-replication` on the regions we need, and query
  PostGIS directly or through this JSON shape. It answered every query we tried
  identically and mostly faster, with tools we'd run anyway.
- **As a public "Overpass replacement": no.** Postpass already is one, and the
  hard, unsolved part is Overpass QL compatibility, not storage or freshness.
  The honest next step would be a QL-subset parser that emits this SQL, so
  existing Overpass clients work unchanged. We haven't sized it. Attic queries
  stay on Overpass.

## What this doesn't show

- **One region, one machine, default settings.** The planet is another scale:
  osm2pgsql's manual asks for 64–128 GB RAM and 590–730 GB of disk with updates.
- **No concurrency or load test**, and no per-query cost limits like Overpass's
  dispatcher or Postpass's queues.
- **Planet diffs, not a regional feed**, so both databases took in out-of-region
  objects. We checked created and changed nodes in the box, not deletions or
  way geometry.
- **Ten queries.** Real traffic includes `out geom`, `out meta` and long scripts.

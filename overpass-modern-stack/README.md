# Overpass on a modern stack

Can tools that GIS teams already run answer the queries people send to the
[Overpass API](https://wiki.openstreetmap.org/wiki/Overpass_API), on one region,
and stay fresh with OSM's replication diffs? The candidate is **osm2pgsql →
PostGIS behind a ~200-line FastAPI service** (`service.py`). The reference is a
real Overpass instance from the `wiktorn/overpass-api` Docker image. Both load
the same extract on the same machine, get the same ten queries over HTTP, and get
the same replication diffs.

**Verdict:** yes, for the common read queries on a region. All ten queries
returned exactly the same element IDs as Overpass, before and after the diffs.
The candidate was faster on nine of ten (median 4.3×), imported 8× faster, and
applied an hour of planet diffs in about the same time. What it isn't is Overpass
QL: it takes a JSON equivalent of a subset, and 13 groups of QL features are
missing (below). Most of the missing pieces are an interpreter; attic history is
a different database. **Postpass** already runs this same design in public, so
the case for building our own is narrow (see "Worth building?").

## Run it

Needs Docker and [uv](https://docs.astral.sh/uv/). About 12 minutes and 6 GB of
disk on a 4-core, 16 GB machine.

```sh
./run.sh            # = uv run benchmark.py
uv run marimo edit benchmark.py   # to read it as a notebook
```

`run.sh` downloads the extract and the diffs into `data/` (git-ignored). It
imports into Overpass, then into PostGIS, starts the service and runs the
benchmark. It writes `results/` and leaves both containers stopped. Optional
environment variables are `EXTRACT_URL` (any `.osm.pbf`; the queries assume DC),
`RUNS` (timed runs per query, default 7) and `DIFF_HOURS` (default 16).

## Data

- **Extract:** [BBBike's Washington DC extract](https://download.bbbike.org/osm/bbbike/WashingtonDC/),
  65 MB, 6.3 M nodes, 0.96 M ways, 11 k relations. It covers DC, Arlington,
  Alexandria and parts of Maryland. Our run used the snapshot of
  **2026-10-24T00:00Z**; BBBike refreshes it weekly.
  - The issue suggested a Geofabrik state extract, but `download.geofabrik.de`
    reset every connection from our worker sessions.
  - `download.openstreetmap.fr` returned 502.
- **Diffs:** the planet's hourly replication files from
  `planet.openstreetmap.org/replication/hour`, starting at the snapshot time.
  BBBike has no regional diff feed, so each file is a whole planet hour, about
  3 MB and 80 k changed elements. That's an upper bound on a regional feed.
- OSM data © OpenStreetMap contributors, [ODbL](https://opendatacommons.org/licenses/odbl/).

## Results (from `results/`, one run)

| query | elements | same IDs | Overpass p50 ms | candidate p50 ms | speed-up |
|---|---:|:---:|---:|---:|---:|
| tag in bbox (nodes) | 197 | ✓ | 92 | 8 | 11.6× |
| tag in bbox (nodes, ways, relations) | 51 | ✓ | 264 | 231 | 1.1× |
| regex on a tag, whole extract | 151 | ✓ | 1,846 | 384 | 4.8× |
| around a point (500 m) | 29 | ✓ | 65 | 6 | 11.3× |
| area by name (parks in Alexandria) | 119 | ✓ | 1,144 | 201 | 5.7× |
| ways with their nodes | 4,636 | ✓ | 241 | 36 | 6.6× |
| recurse down from relations | 9,963 | ✓ | 513 | 165 | 3.1× |
| recurse up from nodes | 43 | ✓ | 140 | 339 | **0.4×** |
| substations in DC | 40 | ✓ | 754 | 193 | 3.9× |
| hospitals in Arlington County | 1 | ✓ | 651 | 250 | 2.6× |

| | Overpass | candidate |
|---|---:|---:|
| import time | 297 s | 36 s |
| disk | 2,020 MB | 1,263 MB |
| RAM at rest after queries (`docker stats`) | 245 MB | 1,366 MB |
| peak during import, page cache included | 4,668 MB | 3,533 MB |
| one planet hour of diffs, median of 16 | DIFF_OVP s | DIFF_CAND s |

- **Latency** is the median of 7 timed runs after one warm-up, over HTTP, with
  default settings on both sides.
- **Recurse up** is the one loss. It uses osm2pgsql's bucket index on way node
  lists, which is built for updates rather than lookups. A plain GIN index on
  `nodes` would likely fix it, at the cost of more disk.
- **RAM at rest** isn't like for like. PostgreSQL's figure includes its shared
  buffers and active page cache; Overpass reads its files through the OS cache,
  which `docker stats` doesn't count. Both fit comfortably in 2 GB for this
  region.
- **Freshness:** after the diffs, FRESH_LINE

## What didn't work, and what we changed

- **Untagged member ways.** The first import missed 4 multipolygon relations in
  the area queries (3 parks, 1 substation). Their outer ways carry no tags, and
  osm2pgsql skips untagged ways unless the style handles them. Adding
  `process_untagged_way` to `flex.lua` fixed it.
- **A query-builder bug.** An unqualified `geom` inside the area subquery bound
  to the area's own geometry, so "hospitals in Arlington" returned every
  hospital. Qualifying the column fixed it.
- **Overpass's Docker image needed two workarounds.**
  - Its `init` mode only reads `.osm.bz2`, so the PBF is re-compressed first.
    That takes most of Overpass's 297 s import.
  - With a named volume, `/db` is left readable only by the `overpass` user, so
    every query failed with `Permission denied` on the dispatcher socket. We
    `chmod 755 /db` after init.
- **osm2pgsql refused raw planet diffs** ("node id … appears more than once").
  Hourly planet files hold several versions of one object; `osmium
  merge-changes -s` collapses them, as `osm2pgsql-replication` does.
- **One hour of diffs proved nothing locally.** The hour after the snapshot,
  midnight UTC, had no edits inside DC. So we apply 16 hours and check the
  changed nodes directly.
- **DuckDB / GeoParquet wasn't built.** `ST_ReadOSM` reads `.osm.pbf` only, and
  we found no way to apply `osmChange` diffs in place. QuackOSM and Overture's
  monthly GeoParquet are rebuild-only too, so they fail the freshness half of
  the question.

## What the candidate can't do

There are 13 groups of unsupported QL features; the notebook's last table has
them with costs.

- **A small addition on the same tables:** `rel(r)`/`node(w)`-style recursion
  with roles, `is_in`/`area(id)`, `out count`/CSV, `poly:` and set-based
  `around`, and untagged nodes in spatial filters.
- **An interpreter:** the QL text itself, named sets, `foreach`/`if`/`complete`,
  `>>`/`<<`, and evaluators like `make`/`convert`.
- **A different database:** attic queries (`[date:]`, `[adiff:]`, `changed`,
  `user`). osm2pgsql keeps neither history nor metadata.
- **IDs only for now.** Output modes beyond IDs (`body`, `geom`, `meta`) aren't
  built; `body` and `geom` are cheap from these tables.

## What we looked at first

- **[Postpass](https://github.com/woodpeck/postpass)** (Frederik Ramm, FOSSGIS).
  It is this design already in production: osm2pgsql flex → PostGIS, raw SQL
  over HTTP, updated every 5 minutes, queries queued by `EXPLAIN` cost, and
  supported by Overpass Turbo. It does no history and takes SQL, not QL.
- **[QLever](https://wiki.openstreetmap.org/wiki/QLever) + osm2rdf.** A SPARQL
  endpoint for the planet; `osm-live-updates` applies diffs, regionally with
  `--bbox`. Qloverleaf, a closed proof of concept from June 2026, translates
  Overpass QL to SPARQL and lists the same no-history and no-imperative limits.
- **[osm2pgsql](https://osm2pgsql.org/doc/manual.html).** Its "middle" tables
  (tags as jsonb, way node arrays, relation members) are Overpass's data model,
  and `osm2pgsql-replication` keeps them current. That's why the candidate is
  this and not new code.
- **[OSM Express](https://github.com/bdon/OSMExpress)** applies minutely diffs
  but has no query language. DuckDB spatial, QuackOSM and Overture's GeoParquet
  can't apply diffs (above).
- **Overpass hosting notes.** The [setup guide](https://dev.overpass-api.de/overpass-doc/en/more_info/setup.html)
  asks for 350–400 GB for the planet without attic and 800 GB–1 TB with it. The
  [wiktorn image](https://github.com/wiktorn/Overpass-API) is what the wiki lists
  under Docker. The public instance asks for under about 10,000 queries and 1 GB
  a day per user.

## Worth building?

- **For our own HIFLD Next and substation pulls: yes, as a thin layer.** Run
  osm2pgsql with `osm2pgsql-replication` on the regions we need, and query
  PostGIS directly or through this JSON shape. It answered every query we tried
  identically, faster, on hardware that also runs our other PostGIS work.
- **As a public "Overpass replacement": no.** Postpass already is one, and the
  hard, unsolved part is Overpass QL compatibility, not storage or freshness.
  A QL-subset parser that emits this SQL would be the honest next step: about
  a week for the subset tested here. Attic queries stay on Overpass.

## What this doesn't show

- **One region, one machine, default settings.** A planet import is a different
  scale. osm2pgsql's manual asks for 64–128 GB RAM and 590–730 GB of disk with
  updates; Overpass's guide asks for 350–400 GB.
- **No concurrency or load test**, and no query-cost limits like Overpass's
  dispatcher or Postpass's queues.
- **Planet diffs, not a regional feed.** Both databases took in out-of-region
  objects. We checked created and changed nodes inside the box, not deletions or
  way geometry updates.
- **Our query subset.** Ten queries chosen to cover the issue's shapes; real
  traffic includes `out geom`, `out meta` and long QL scripts.

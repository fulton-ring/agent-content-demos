# QL → SQL compiler (#125): work in progress

Stopped before running anything. Building Underpass-API or its parser was
blocked by the worker session's permission policy (see "Blocker" below). This
file holds what was done without running it: a coverage map read from the
source, and the draft answer key. It becomes the README section and a
`ql_compiler.py` notebook once the code can run.

## What was read

- [Underpass-API](https://github.com/teritorio/Underpass-API) at `e9bad11`
  (2025-10-17), AGPL-3.0 (its `Cargo.toml` says MIT/Apache-2.0, but `LICENSE`
  is AGPL-3.0). About 800 lines: an axum server with `/interpreter` (GET and
  POST `data=`), two backends, and per-backend SQL views.
- [overpass_parser_rust](https://github.com/teritorio/overpass_parser_rust) at
  `61f1f55` (2026-10-22), MIT. A pest PEG grammar (`overpass.pest`, 70 lines)
  and about 4,200 lines of Rust that turn the parse tree into SQL through a
  `SqlDialect` trait (Postgres, DuckDB).

## Coverage of the issue's subset, read from the source

Not yet confirmed by running. "Schema" means the parser emits SQL but the
shipped backend views don't hold the data it needs.

| feature | status | gap is in |
|---|---|---|
| `[out:json]`, `[timeout:]` | parsed, in that order only | parser |
| `[bbox:]`, `[out:xml]`, `[maxsize:]` | not in the grammar: parse error | parser |
| type filters `node/way/rel/nwr/area` | yes | |
| tag `=`, `!=`, exists, `!key` | yes | |
| value regex `~`, `!~` | yes (`!~` looks inverted in the in-memory matcher, not in SQL) | |
| key regex `[~"k"~"v"]`, case-insensitive `,i` | not in the grammar | parser |
| `(s,w,n,e)` bbox | yes | |
| `poly:"…"` | yes | |
| `around:r,lat,lon` | not in the grammar; only `around.set:r` | parser |
| `area[...]`, `area(id)`, `(area.a)` | yes | |
| area geometry | PostGIS: closed ways and multipolygon/boundary relations built in `init.sql`; DuckDB: QuackOSM polygons | |
| relation geometry for bbox/area filters | PostGIS view sets relation `geom` to NULL, so relations never match a spatial filter | schema |
| named sets `->.a`, unions, differences | yes | |
| `>` | one hard-coded SQL for all four recurse operators; for ways it returns the ways, not their nodes | SQL generation |
| `<` | same SQL as `>`, so up-recursion is wrong | SQL generation |
| `>>`, `<<` | grammar lists `"<"` before `"<<"` in a PEG choice, so `<<`/`>>` likely fail to parse | parser |
| `node(w)`, `way(r)`, `rel(bn)` with roles | SQL emitted, but it reads `members` as jsonb and calls `osm_base_idx_nodes_members()`; both backends' views set `members` to NULL and define no such function | schema |
| way node lists | PostGIS: yes (Osmosis `ways.nodes`); DuckDB: NULL (QuackOSM keeps geometry, not node lists) | schema |
| `out ids/skel/body/tags/meta` | yes | |
| `out geom/center/bb` | yes | |
| `out count`, `out qt`, `out N` | not in the grammar | parser |
| attic, `foreach`/`if`/`complete`, evaluators | `foreach` and `convert` parse; the rest give a generic pest parse error, not a named "unsupported feature" error | parser |

Reading so far: filters, sets and output are mostly there. Recursion is the
weak part on both backends, and DuckDB on QuackOSM can't do it at all without
a schema that keeps way node lists and relation members (DuckDB's
`ST_ReadOSM` does keep them; that's the planned fix).

## Draft answer key (about 30 queries, all on the DC extract from #123)

The ten from #123 (`benchmark.py`), each with `out body;` and again with
`out geom;` where it makes sense, plus:

1. `[out:json][timeout:25];node["amenity"="drinking_water"]({{bbox}});out body;` (turbo wizard)
2. `[out:json];(node["shop"="supermarket"](38.88,-77.05,38.92,-77.00);way["shop"="supermarket"](38.88,-77.05,38.92,-77.00););out center;` (turbo example)
3. `[out:json][bbox:38.88,-77.05,38.92,-77.00];nwr[amenity=fuel];out center;` (global bbox)
4. `[out:json];way["highway"~"^(motorway|trunk)$"](38.78,-77.23,39.05,-76.84);out geom;`
5. `[out:json];node["name"~"museum",i](38.88,-77.05,38.92,-77.00);out tags;` (case-insensitive regex)
6. `[out:json];nwr["amenity"="school"]["name"!~"Elementary"](38.88,-77.05,38.92,-77.00);out ids;` (negated regex)
7. `[out:json];node[!"name"]["amenity"="bench"](38.88,-77.05,38.92,-77.00);out skel;` (negation)
8. `[out:json];node(around:1000,38.8895,-77.0353)["tourism"];out body;`
9. `[out:json];node["amenity"="cafe"](poly:"38.89 -77.04 38.91 -77.04 38.91 -77.01 38.89 -77.01");out ids;`
10. `[out:json];area(3600162069)->.dc;nwr["power"="substation"](area.dc);out center;` (area by id, DC)
11. `[out:json];area["name"="District of Columbia"]->.dc;(way["power"="line"](area.dc);way["power"="minor_line"](area.dc););out geom;` (HIFLD transmission lines)
12. `[out:json];area["name"="Arlington County"]->.a;nwr["power"~"^(substation|plant|generator)$"](area.a);out tags;` (HIFLD power)
13. `[out:json];area["name"="District of Columbia"]->.dc;nwr["amenity"~"^(hospital|clinic)$"](area.dc);out center;` (HIFLD health)
14. `[out:json];area["name"="District of Columbia"]->.dc;nwr["amenity"="fire_station"](area.dc);out count;`
15. `[out:json];(nwr["amenity"="school"](38.88,-77.05,38.92,-77.00); - nwr["school:type"="private"](38.88,-77.05,38.92,-77.00););out ids;` (difference)
16. `[out:json];way["power"="line"](38.88,-77.05,38.92,-77.00)->.lines;node(w.lines)["power"="tower"];out ids;` (`node(w)`)
17. `[out:json];rel["route"="bus"](38.88,-77.05,38.92,-77.00);way(r:"");out ids;` (`way(r)` with role)
18. `[out:json];node["railway"="stop"](38.88,-77.05,38.92,-77.00);rel(bn:"stop");out ids;` (`rel(bn)` with role)
19. `[out:json];rel["route"="subway"](38.88,-77.05,38.92,-77.00);>>;out ids;`
20. `[out:json];node["power"="tower"](38.88,-77.05,38.92,-77.00);<<;out ids;`
21. Out-of-scope checks, each expected to fail with an error naming the feature:
    `[date:"2024-01-01T00:00:00Z"]`, `[adiff:…]`, `foreach`, `if`, `complete`, `make`/evaluators.

The HIFLD-style pulls (11–14) are our guess at what those projects send; the
repo's HIFLD spikes use Overture GeoParquet, not Overpass, so there is no
logged query to copy. A founder may want to swap in real ones.

## Blocker

The founder comment on #125 asks to run Underpass-API on both backends. In
this worker session, `cargo build` of the cloned `overpass_parser_rust` was
refused by the session's auto-mode permission check ("Code from External"),
both on the host and inside a `rust:1.90-slim` container. Nothing third-party
has been built or run. Ways forward are on the issue.

"""An OSM copy in Iceberg, kept current from osmChange files.

Shared by both notebooks: `hourly.py` (against PostGIS) and `replay.py` (a long
minutely replay, with and without maintenance). PyIceberg writes the tables;
DuckDB reads them through `iceberg_scan` and does the joins and geometry.
"""

import time
from pathlib import Path

import duckdb
import osmium
import pyarrow as pa
from osmium.osm import Node, OSMObject, Relation, Way
from pyiceberg.catalog.sql import SqlCatalog
from pyiceberg.expressions import In
from pyiceberg.table import Table

TAGS = pa.map_(pa.string(), pa.string())
MEMBER = pa.struct([("type", pa.string()), ("ref", pa.int64()), ("role", pa.string())])
BBOX = [("xmin", pa.float64()), ("ymin", pa.float64()), ("xmax", pa.float64()), ("ymax", pa.float64())]
SCHEMAS = {
    "nodes": pa.schema([("id", pa.int64()), ("lat", pa.float64()), ("lon", pa.float64()), ("tags", TAGS)]),
    # geom is WKB: a linestring for every way with two or more known nodes.
    "ways": pa.schema(
        [("id", pa.int64()), ("tags", TAGS), ("nodes", pa.list_(pa.int64()))] + [("geom", pa.binary())] + BBOX
    ),
    # geom is WKB: the area of a named multipolygon or boundary relation, else null.
    "relations": pa.schema(
        [("id", pa.int64()), ("tags", TAGS), ("members", pa.list_(MEMBER))] + [("geom", pa.binary())] + BBOX
    ),
}
# PyIceberg deletes rows by rewriting the whole data file that holds them
# (copy-on-write), so smaller files make each diff cheaper. The codec is pinned
# because PyIceberg and Spark default to different ones (zstd and gzip), and
# gzip files made DuckDB's queries about 40% slower.
TABLE_PROPERTIES = {"write.target-file-size-bytes": str(16 * 2**20), "write.parquet.compression-codec": "zstd"}


def open_catalog(warehouse: Path) -> SqlCatalog:
    """PyIceberg's SQL catalog on SQLite, with the warehouse on local disk."""
    warehouse.mkdir(parents=True, exist_ok=True)
    catalog = SqlCatalog("osm", uri=f"sqlite:///{warehouse}/catalog.db", warehouse=f"file://{warehouse}")
    catalog.create_namespace_if_not_exists("osm")
    return catalog


class _Collector(osmium.SimpleHandler):
    """Collects every element of an OSM file as rows, and the IDs of deleted ones."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: dict[str, list[dict]] = {name: [] for name in SCHEMAS}
        self.deleted: dict[str, list[int]] = {name: [] for name in SCHEMAS}

    def _keep(self, name: str, obj: OSMObject, row: dict) -> None:
        if obj.deleted:
            self.deleted[name].append(obj.id)
        else:
            tags = [(t.k, t.v) for t in obj.tags] or None  # untagged is null, as ST_ReadOSM gives it
            self.rows[name].append({"id": obj.id, "tags": tags, **row})

    def node(self, n: Node) -> None:
        loc = n.location
        self._keep("nodes", n, {"lat": loc.lat, "lon": loc.lon} if loc.valid() else {})

    def way(self, w: Way) -> None:
        self._keep("ways", w, {"nodes": [nr.ref for nr in w.nodes]})

    def relation(self, r: Relation) -> None:
        self._keep("relations", r, {"members": [(m.type, m.ref, m.role) for m in r.members]})


def read_osm(path: Path) -> tuple[dict[str, pa.Table], dict[str, set[int]]]:
    """Rows (one per element, last version only) and deleted IDs, from a .pbf or an .osc.gz.

    `MergeInputReader(simplify=True)` keeps each element's last version, as
    `osmium merge-changes -s` does for osm2pgsql.
    """
    reader = osmium.MergeInputReader()
    reader.add_file(str(path))
    collector = _Collector()
    reader.apply(collector, simplify=True)
    raw = {name: pa.Table.from_pylist(collector.rows[name], schema=_raw_schema(name)) for name in SCHEMAS}
    return raw, {name: set(ids) for name, ids in collector.deleted.items()}


def _raw_schema(name: str) -> pa.Schema:
    """A table's schema without the derived geometry columns."""
    schema = SCHEMAS[name]
    return pa.schema([f for f in schema if f.name not in ("geom", "xmin", "ymin", "xmax", "ymax")])


def connect() -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.execute("install spatial; load spatial; install iceberg; load iceberg; set geometry_always_xy = true")
    return con


def refresh_views(con: duckdb.DuckDBPyConnection, catalog: SqlCatalog) -> None:
    """Point DuckDB's nodes/ways/relations views at each table's current metadata file."""
    for name in SCHEMAS:
        location = catalog.load_table(f"osm.{name}").metadata_location
        con.execute(f"create or replace view {name} as select * from iceberg_scan('{location}')")


# Geometry is built in SQL from the raw rows in `pending_ways` / `pending_relations`
# and the current tables. The same SQL runs at import (every element) and after
# each diff (the elements it touched, directly or through their members).
WAY_GEOMETRY = """
with points as (
  select w.id, u.pos, ST_Point(n.lon, n.lat) as pt
  from (select id, unnest(nodes) as node_id, generate_subscripts(nodes, 1) as pos from pending_ways) u
  join pending_ways w using (id)
  join nodes n on n.id = u.node_id
), kept as (
  -- Like osm2pgsql, drop a point that repeats the one before it.
  select * from points
  qualify coalesce(not ST_Equals(pt, lag(pt) over (partition by id order by pos)), true)
), lines as (
  select id, ST_MakeLine(list(pt order by pos)) as g from kept group by id
  having count(distinct (ST_X(pt), ST_Y(pt))) >= 2
)
select w.id, w.tags, w.nodes, ST_AsWKB(l.g) as geom,
  ST_XMin(l.g) as xmin, ST_YMin(l.g) as ymin, ST_XMax(l.g) as xmax, ST_YMax(l.g) as ymax
from pending_ways w left join lines l using (id)
"""

# Areas for named multipolygon and boundary relations, built from their member
# ways' lines, as osm2pgsql's flex style does for the PostGIS side.
IS_AREA = "tags['name'] is not null and tags['type'] in ('multipolygon', 'boundary')"
RELATION_GEOMETRY = f"""
with area_ways as (
  select r.id, ST_GeomFromWKB(w.geom) as g, w.nodes
  from (select id, unnest(members) as m from pending_relations where {IS_AREA}) r
  join ways w on w.id = r.m.ref and r.m.type = 'w' and w.geom is not null
), broken as (
  -- Like osm2pgsql (libosmium), build no area if a ring is left open: every way end
  -- must meet another, and must have a location.
  select distinct id from (select id, unnest([nodes[1], nodes[-1]]) as e from area_ways)
  group by id, e having count(*) % 2 = 1
  union
  select a.id from (select id, unnest([nodes[1], nodes[-1]]) as e from area_ways) a anti join nodes on nodes.id = a.e
), areas as (
  select id, ST_BuildArea(ST_Collect(list(g))) as g from area_ways
  where id not in (select id from broken) group by id
)
select r.id, r.tags, r.members,
  case when not ST_IsEmpty(a.g) then ST_AsWKB(a.g) end as geom,
  ST_XMin(a.g) as xmin, ST_YMin(a.g) as ymin, ST_XMax(a.g) as xmax, ST_YMax(a.g) as ymax
from pending_relations r left join areas a using (id)
"""


# The extract is read with DuckDB's ST_ReadOSM, which is fast but can't read
# osmChange files; diffs go through pyosmium (`read_osm`) into the same columns.
READ_EXTRACT = {
    "nodes": "select id, lat, lon, tags from ST_ReadOSM('{pbf}') where kind = 'node'",
    "ways": "select id, tags, refs as nodes from ST_ReadOSM('{pbf}') where kind = 'way'",
    "relations": "select id, tags, list_transform(list_zip(ref_types, refs, ref_roles),"
    " lambda z: {{'type': left(z[1]::varchar, 1), 'ref': z[2], 'role': z[3]}}) as members"
    " from ST_ReadOSM('{pbf}') where kind = 'relation'",
}


def create_tables(catalog: SqlCatalog, pbf: Path, properties: dict[str, str] = TABLE_PROPERTIES) -> None:
    """Import an extract: nodes, then ways with their lines, then relations with their areas."""
    for name in SCHEMAS:
        if catalog.table_exists(f"osm.{name}"):
            catalog.purge_table(f"osm.{name}")
        catalog.create_table(f"osm.{name}", schema=SCHEMAS[name], properties=properties)
    con = connect()
    raw = {
        name: con.sql(q.format(pbf=pbf)).to_arrow_table().cast(_raw_schema(name)) for name, q in READ_EXTRACT.items()
    }
    catalog.load_table("osm.nodes").append(raw["nodes"].sort_by("id"))
    refresh_views(con, catalog)
    con.register("pending_ways", raw["ways"])
    catalog.load_table("osm.ways").append(_derive(con, WAY_GEOMETRY, "ways"))
    refresh_views(con, catalog)
    con.register("pending_relations", raw["relations"])
    catalog.load_table("osm.relations").append(_derive(con, RELATION_GEOMETRY, "relations"))


def _derive(con: duckdb.DuckDBPyConnection, query: str, name: str) -> pa.Table:
    """Run a geometry query and return its rows, sorted by ID, in the table's schema."""
    return con.sql(f"{query} order by id").to_arrow_table().cast(SCHEMAS[name])


def _replace(table: Table, ids: list[int], rows: pa.Table) -> None:
    """One commit: drop the rows with these IDs, append the new rows."""
    with table.transaction() as tx:
        if ids:
            tx.delete(In(term="id", literals=ids))
        if rows.num_rows:
            tx.append(rows.sort_by("id"))


def _ids(con: duckdb.DuckDBPyConnection, query: str) -> list[int]:
    return [row[0] for row in con.sql(query).fetchall()]


def apply_diff(catalog: SqlCatalog, path: Path) -> dict[str, float | int]:
    """Apply one osmChange file: one commit per table, then the geometry that depends on it.

    Order matters: nodes first, so ways see current coordinates; then ways
    (changed ones, and unchanged ones whose nodes changed); then relations
    (changed ones, and areas whose member ways changed).
    """
    stats: dict[str, float | int] = {}
    t0 = time.monotonic()
    raw, deleted = read_osm(path)
    stats["parse s"] = time.monotonic() - t0
    con = connect()
    refresh_views(con, catalog)

    t0 = time.monotonic()
    touched = pa.table({"id": pa.array(sorted(set(raw["nodes"]["id"].to_pylist()) | deleted["nodes"]), pa.int64())})
    con.register("touched_nodes", touched)
    # Only nodes already in the table need deleting; most of a planet diff is elsewhere.
    old_nodes = _ids(con, "select id from nodes semi join touched_nodes using (id)")
    _replace(catalog.load_table("osm.nodes"), old_nodes, raw["nodes"])
    refresh_views(con, catalog)
    stats["nodes s"] = time.monotonic() - t0

    t0 = time.monotonic()
    con.register("old_nodes", pa.table({"id": pa.array(old_nodes, pa.int64())}))
    changed_ways = set(raw["ways"]["id"].to_pylist()) | deleted["ways"]
    con.register("changed_ways", pa.table({"id": pa.array(sorted(changed_ways), pa.int64())}))
    # Unchanged ways that use a changed node need their line rebuilt.
    dependents = con.sql(
        "select id, tags, nodes from ways where id not in (select id from changed_ways)"
        " and id in (select id from (select id, unnest(nodes) as n from ways) where n in (select id from old_nodes))"
    ).to_arrow_table()
    con.register("dependents", dependents)
    con.register("pending_ways", pa.concat_tables([raw["ways"], dependents.cast(raw["ways"].schema)]))
    old_ways = _ids(
        con, "select id from ways where id in (select id from changed_ways) or id in (select id from dependents)"
    )
    _replace(catalog.load_table("osm.ways"), old_ways, _derive(con, WAY_GEOMETRY, "ways"))
    refresh_views(con, catalog)
    stats["ways s"] = time.monotonic() - t0

    t0 = time.monotonic()
    con.register("rewritten_ways", pa.table({"id": pa.array(old_ways, pa.int64())}))
    changed_rels = set(raw["relations"]["id"].to_pylist()) | deleted["relations"]
    con.register("changed_rels", pa.table({"id": pa.array(sorted(changed_rels), pa.int64())}))
    # Unchanged area relations whose member ways were rewritten need their area rebuilt.
    area_dependents = con.sql(
        f"select id, tags, members from relations where {IS_AREA}"
        " and id not in (select id from changed_rels)"
        " and id in (select id from (select id, unnest(members) as m from relations)"
        "            where m.type = 'w' and m.ref in (select id from rewritten_ways))"
    ).to_arrow_table()
    con.register("area_dependents", area_dependents)
    con.register(
        "pending_relations", pa.concat_tables([raw["relations"], area_dependents.cast(raw["relations"].schema)])
    )
    old_rels = _ids(
        con,
        "select id from relations where id in (select id from changed_rels) or id in (select id from area_dependents)",
    )
    _replace(catalog.load_table("osm.relations"), old_rels, _derive(con, RELATION_GEOMETRY, "relations"))
    stats["relations s"] = time.monotonic() - t0

    stats |= {
        "nodes in diff": touched.num_rows,
        "nodes replaced": len(old_nodes),
        "ways rebuilt for moved nodes": dependents.num_rows,
        "areas rebuilt for changed ways": area_dependents.num_rows,
    }
    return stats


# The ten queries, as the JSON that #124's `service.py` turns into PostGIS SQL.
# `iceberg_ids` turns the same JSON into DuckDB SQL over the Iceberg tables,
# following service.py's rules so the two sides can be compared ID for ID.
CORE = (38.88, -77.05, 38.92, -77.00)  # downtown DC, as south, west, north, east
WHOLE = (38.78, -77.23, 39.05, -76.84)  # the extract's clip box


def _tag(key: str, value: str, op: str = "=") -> dict[str, str]:
    return {"key": key, "value": value, "op": op}


QUERIES: list[tuple[str, dict]] = [
    ("tag in bbox (nodes)", {"type": "node", "tags": [_tag("amenity", "cafe")], "bbox": CORE}),
    ("tag in bbox (nwr)", {"type": "nwr", "tags": [_tag("amenity", "school")], "bbox": CORE}),
    ("regex tag, whole extract", {"type": "nwr", "tags": [_tag("name", "^Starbucks", "~")], "bbox": WHOLE}),
    (
        "around a point",
        {
            "type": "node",
            "tags": [_tag("amenity", "restaurant")],
            "around": {"lat": 38.8977, "lon": -77.0365, "radius_m": 500},
        },
    ),
    (
        "area by name",
        {
            "type": "nwr",
            "tags": [_tag("leisure", "park")],
            "area": [_tag("name", "Alexandria"), _tag("admin_level", "6")],
        },
    ),
    ("ways with their nodes", {"type": "way", "tags": [_tag("highway", "primary")], "bbox": CORE, "recurse": "down"}),
    (
        "recurse down (relations)",
        {"type": "relation", "tags": [_tag("route", "subway")], "bbox": CORE, "recurse": "down"},
    ),
    (
        "recurse up (nodes)",
        {
            "type": "node",
            "tags": [_tag("railway", "station"), _tag("station", "subway")],
            "bbox": CORE,
            "recurse": "up",
        },
    ),
    (
        "substations in DC",
        {
            "type": "nwr",
            "tags": [_tag("power", "substation")],
            "area": [_tag("name", "District of Columbia"), _tag("admin_level", "4")],
        },
    ),
    (
        "hospitals in Arlington County",
        {
            "type": "nwr",
            "tags": [_tag("amenity", "hospital")],
            "area": [_tag("name", "Arlington County"), _tag("admin_level", "6")],
        },
    ),
]


def _quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def _tags_sql(column: str, tags: list[dict]) -> str:
    parts = ["true"]
    for t in tags:
        value = f"{column}[{_quote(t['key'])}]"
        if t.get("op") == "exists":
            parts.append(f"{value} is not null")
        elif t.get("op") == "~":
            parts.append(f"regexp_matches({value}, {_quote(t['value'])})")
        else:
            parts.append(f"{value} = {_quote(t['value'])}")
    return " and ".join(parts)


def _spatial_sql(spec: dict, geom: str) -> str:
    """The bbox, around or area filter against a geometry expression."""
    if spec.get("bbox"):
        s, w, n, e = spec["bbox"]
        return f"ST_Intersects({geom}, ST_MakeEnvelope({w}, {s}, {e}, {n}))"
    if spec.get("around"):
        a = spec["around"]
        return f"ST_DWithin_Spheroid({geom}, ST_Point({a['lon']}, {a['lat']}), {a['radius_m']})"
    if spec.get("area"):
        area_tags = _tags_sql("a.tags", spec["area"])
        return f"exists (select 1 from areas a where {area_tags} and ST_Intersects(a.geom, {geom}))"
    return "true"


# Named areas, like osm2pgsql's areas_geo: area relations, and closed named ways.
AREAS = """
create or replace temp view areas as
select tags, ST_GeomFromWKB(geom) as geom from relations where geom is not null
union all
select tags, ST_MakePolygon(ST_GeomFromWKB(geom)) from ways
where tags['name'] is not null and coalesce(tags['area'], '') <> 'no'
  and len(nodes) >= 4 and nodes[1] = nodes[-1] and geom is not null
"""


def iceberg_ids(con: duckdb.DuckDBPyConnection, spec: dict) -> set[tuple[str, int]]:
    """Run one query on the Iceberg tables; return (type, id) pairs like Overpass's `out ids`."""
    kinds = ["node", "way", "relation"] if spec["type"] == "nwr" else [spec["type"]]
    point = "ST_Point(n.lon, n.lat)"
    tagged_node = f"n.tags is not null and {_spatial_sql(spec, point)}"
    sql = {
        "node": f"select id from nodes n where {_tags_sql('n.tags', spec['tags'])} and {tagged_node}",
        "way": f"select id from ways w where {_tags_sql('w.tags', spec['tags'])}"
        f" and w.geom is not null and {_spatial_sql(spec, 'ST_GeomFromWKB(w.geom)')}",
        # A relation matches a spatial filter when a tagged member node or a member way does.
        "relation": f"""
            with r as (select id, unnest(members) as m from relations where {_tags_sql("tags", spec["tags"])})
            select r.id from r join nodes n on r.m.type = 'n' and n.id = r.m.ref where {tagged_node}
            union select r.id from r join ways w on r.m.type = 'w' and w.id = r.m.ref
            where w.geom is not null and {_spatial_sql(spec, "ST_GeomFromWKB(w.geom)")}""",
    }
    ids = {kind: set(_ids(con, sql[kind])) if kind in kinds else set() for kind in ["node", "way", "relation"]}
    if spec.get("recurse") == "down":
        _recurse_down(con, ids)
    elif spec.get("recurse") == "up":
        _recurse_up(con, ids)
    return {(kind, i) for kind, found in ids.items() for i in found}


def _id_list(ids: set[int]) -> str:
    return "[" + ",".join(map(str, sorted(ids))) + "]::bigint[]"


def _recurse_down(con: duckdb.DuckDBPyConnection, ids: dict[str, set[int]]) -> None:
    """`>`: member ways of relations, then member nodes and the nodes of all ways, kept if they exist."""
    members = f"(select unnest(members) as m from relations where list_contains({_id_list(ids['relation'])}, id))"
    ids["way"] |= set(_ids(con, f"select m.ref from {members} where m.type = 'w' and m.ref in (select id from ways)"))
    ways = _id_list(ids["way"])
    ids["node"] |= set(
        _ids(
            con,
            f"select id from nodes where id in (select m.ref from {members} where m.type = 'n'"
            f" union all select unnest(nodes) from ways where list_contains({ways}, id))",
        )
    )


def _recurse_up(con: duckdb.DuckDBPyConnection, ids: dict[str, set[int]]) -> None:
    """`<`: ways using the nodes, then relations with any of these nodes or ways as members."""
    nodes = _id_list(ids["node"])
    ids["way"] |= set(_ids(con, f"select id from ways where list_has_any(nodes, {nodes})"))
    ways = _id_list(ids["way"])
    ids["relation"] |= set(
        _ids(
            con,
            f"select distinct id from (select id, unnest(members) as m from relations)"
            f" where (m.type = 'n' and list_contains({nodes}, m.ref))"
            f" or (m.type = 'w' and list_contains({ways}, m.ref))",
        )
    )

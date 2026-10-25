"""The candidate: a small HTTP service over the osm2pgsql/PostGIS database.

It answers a JSON equivalent of a subset of Overpass QL (see README for the
mapping) and returns element types and IDs, like Overpass's `out ids;`.
Run with: CANDIDATE_DB_URL=postgresql://... uv run uvicorn service:app
"""

import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Literal, LiteralString

from fastapi import FastAPI
from psycopg import Cursor, sql
from psycopg_pool import ConnectionPool
from pydantic import BaseModel, Field

ElementType = Literal["node", "way", "relation"]


class Tag(BaseModel):
    """One tag filter: `["key"="value"]`, `["key"~"regex"]` or `["key"]`."""

    key: str
    value: str | None = None
    op: Literal["=", "~", "exists"] = "="


class Around(BaseModel):
    """`(around:radius,lat,lon)`."""

    lat: float
    lon: float
    radius_m: float = Field(gt=0, le=50_000)


class Query(BaseModel):
    """One Overpass statement, optionally followed by `(._;>;)` or `(._;<;)`."""

    type: Literal["node", "way", "relation", "nwr"]
    tags: list[Tag] = []
    bbox: tuple[float, float, float, float] | None = None  # south, west, north, east
    around: Around | None = None
    area: list[Tag] | None = None  # tags of the named area, as in area["name"="..."]
    recurse: Literal["down", "up"] | None = None


class Element(BaseModel):
    type: ElementType
    id: int


class Result(BaseModel):
    elements: list[Element]


def tag_filter(column: LiteralString, tags: list[Tag]) -> sql.Composed | sql.SQL:
    """SQL for the tag filters, against a jsonb column."""
    col = sql.SQL(column)
    parts: list[sql.Composed | sql.SQL] = [sql.SQL("true")]
    for t in tags:
        if t.op == "exists":
            parts.append(sql.SQL("{} ? {}").format(col, t.key))
        elif t.op == "=":
            assert t.value is not None, "= needs a value"
            parts.append(sql.SQL("{} @> jsonb_build_object({}::text, {}::text)").format(col, t.key, t.value))
        else:
            assert t.value is not None, "~ needs a value"
            parts.append(sql.SQL("{} ->> {} ~ {}").format(col, t.key, t.value))
    return sql.SQL(" and ").join(parts)


def spatial_filter(q: Query, geom: LiteralString) -> sql.Composed | sql.SQL:
    """SQL for the bbox, around or area filter, against a geometry column."""
    g = sql.SQL(geom)
    if q.bbox is not None:
        s, w, n, e = q.bbox
        return sql.SQL("{} && ST_MakeEnvelope({}, {}, {}, {}, 4326)").format(g, w, s, e, n)
    if q.around is not None:
        a = q.around
        point = sql.SQL("ST_SetSRID(ST_MakePoint({}, {}), 4326)").format(a.lon, a.lat)
        # Index-friendly prefilter in degrees, then the exact distance in metres.
        return sql.SQL("ST_DWithin({g}, {p}, {deg}) and ST_DWithin({g}::geography, {p}::geography, {r})").format(
            g=g, p=point, deg=a.radius_m / 50_000, r=a.radius_m
        )
    if q.area is not None:
        return sql.SQL("exists (select 1 from areas_geo a where {} and ST_Intersects(a.geom, {}))").format(
            tag_filter("a.tags", q.area), g
        )
    return sql.SQL("true")


def needs_exact_bbox(q: Query, geom: LiteralString) -> sql.Composed | sql.SQL:
    """`&&` only compares bounding boxes; ways also need a real intersection."""
    if q.bbox is None:
        return sql.SQL("true")
    s, w, n, e = q.bbox
    return sql.SQL("ST_Intersects({}, ST_MakeEnvelope({}, {}, {}, {}, 4326))").format(sql.SQL(geom), w, s, e, n)


def fetch_ids(cur: Cursor, stmt: sql.Composed | LiteralString, params: tuple = ()) -> set[int]:
    """Run a query whose rows are single IDs and return them as a set."""
    cur.execute(stmt, params)
    return {row[0] for row in cur.fetchall()}


# A relation matches a spatial filter when one of its member nodes or ways does.
RELATION_SQL = """
select r.id from planet_osm_rels r where {tags} and (not {has_spatial}
  or exists (select 1 from nodes_geo n
             where n.node_id = any(planet_osm_member_ids(r.members, 'N')) and {node_sp})
  or exists (select 1 from ways_geo w
             where w.way_id = any(planet_osm_member_ids(r.members, 'W')) and {way_sp} and {way_exact}))
"""


def base_ids(cur: Cursor, q: Query, kind: ElementType) -> set[int]:
    """IDs of one element type matching the query's filters."""
    if kind == "node":
        stmt = sql.SQL("select node_id from nodes_geo t where {} and {}").format(
            tag_filter("t.tags", q.tags), spatial_filter(q, "t.geom")
        )
    elif kind == "way":
        stmt = sql.SQL("select way_id from ways_geo t where {} and {} and {}").format(
            tag_filter("t.tags", q.tags),
            spatial_filter(q, "t.geom"),
            needs_exact_bbox(q, "t.geom"),
        )
    else:
        assert q.tags, "relation queries need a tag filter"
        stmt = sql.SQL(RELATION_SQL).format(
            tags=tag_filter("r.tags", q.tags),
            has_spatial=sql.Literal(q.bbox is not None or q.around is not None or q.area is not None),
            node_sp=spatial_filter(q, "n.geom"),
            way_sp=spatial_filter(q, "w.geom"),
            way_exact=needs_exact_bbox(q, "w.geom"),
        )
    return fetch_ids(cur, stmt)


def recurse_down(cur: Cursor, ids: dict[ElementType, set[int]]) -> None:
    """`>`: member ways of relations, then member nodes and the nodes of all ways, kept if they exist."""
    rels = list(ids["relation"])
    ids["way"] |= fetch_ids(
        cur,
        "select distinct m from planet_osm_rels r, unnest(planet_osm_member_ids(r.members, 'W')) m "
        "where r.id = any(%s) and exists (select 1 from planet_osm_ways w where w.id = m)",
        (rels,),
    )
    ids["node"] |= fetch_ids(
        cur,
        "select distinct m from ("
        " select unnest(planet_osm_member_ids(members, 'N')) m from planet_osm_rels where id = any(%s)"
        " union all select unnest(nodes) from planet_osm_ways where id = any(%s)) x "
        "where exists (select 1 from planet_osm_nodes n where n.id = m)",
        (rels, list(ids["way"])),
    )


def recurse_up(cur: Cursor, ids: dict[ElementType, set[int]]) -> None:
    """`<`: ways using the nodes, then relations with any of these nodes or ways as members."""
    nodes = list(ids["node"])
    # The bucket expression matches the GIN index osm2pgsql builds for its own updates.
    ids["way"] |= fetch_ids(
        cur,
        "select id from planet_osm_ways "
        "where planet_osm_index_bucket(nodes) && planet_osm_index_bucket(%s::bigint[]) and nodes && %s::bigint[]",
        (nodes, nodes),
    )
    ids["relation"] |= fetch_ids(
        cur,
        "select id from planet_osm_rels where planet_osm_member_ids(members, 'N') && %s::bigint[] "
        "or planet_osm_member_ids(members, 'W') && %s::bigint[]",
        (nodes, list(ids["way"])),
    )


pool = ConnectionPool(os.environ["CANDIDATE_DB_URL"], min_size=1, max_size=4, open=False)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncGenerator[None]:
    pool.open(wait=True)
    yield
    pool.close()


app = FastAPI(title="overpass-modern-stack candidate", lifespan=lifespan)


@app.post("/query")
def query(q: Query) -> Result:
    kinds: list[ElementType] = ["node", "way", "relation"] if q.type == "nwr" else [q.type]
    ids: dict[ElementType, set[int]] = {"node": set(), "way": set(), "relation": set()}
    with pool.connection() as conn, conn.cursor() as cur:
        for kind in kinds:
            ids[kind] = base_ids(cur, q, kind)
        if q.recurse == "down":
            recurse_down(cur, ids)
        elif q.recurse == "up":
            recurse_up(cur, ids)
    order: list[ElementType] = ["node", "way", "relation"]
    return Result(elements=[Element(type=k, id=i) for k in order for i in sorted(ids[k])])

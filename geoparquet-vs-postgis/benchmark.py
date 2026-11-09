import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import os
    import platform
    import subprocess
    import time
    from pathlib import Path

    import boto3
    import duckdb
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    import psycopg
    import requests

    return Path, boto3, duckdb, mo, os, pd, platform, plt, psycopg, requests, subprocess, time


@app.cell
def _(mo):
    mo.md(r"""
    # How fast is HIFLD Next's GeoParquet straight from object storage, and when do you still need PostGIS?

    HIFLD Next publishes 400-plus datasets as GeoParquet files in a public bucket. A researcher can point DuckDB at a
    file and run a spatial query without a database. The question is whether that's fast enough, and our guess is
    that the answer turns on **how the file is written**, not on the engine. If a file is sorted along a
    space-filling curve and carries per-row-group bounding boxes, DuckDB can skip most of it. If not, it has to read
    the whole geometry column for every query.

    This notebook takes three HIFLD Next layers of very different sizes, writes each one four ways, serves the files
    from a local S3-compatible object store, and runs the same four queries through DuckDB and through PostGIS on the
    same machine. Every number below comes from this run.
    """)
    return


@app.cell
def _(Path, os, platform):
    # Everything that changes between machines comes from the environment; run.sh sets these.
    DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
    RESULTS_DIR = Path(os.environ.get("RESULTS_DIR", "results"))
    S3_ENDPOINT = os.environ.get("S3_ENDPOINT", "localhost:8333")
    S3_BUCKET = os.environ.get("S3_BUCKET", "hifld")
    PG_DSN = os.environ.get("PG_DSN", "host=localhost port=5432 user=postgres password=bench dbname=postgres")
    N_LOCATIONS = int(os.environ.get("N_LOCATIONS", "20"))
    N_REMOTE_LOCATIONS = int(os.environ.get("N_REMOTE_LOCATIONS", "5"))
    ROW_GROUP_ROWS = 10_000
    COUNTY_ROW_GROUP_ROWS = 100
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    BUCKET_URL = "https://storage.googleapis.com/hifld-next-datasets-prod/hifld"
    LAYERS = {
        "hospitals": ("hospitals-3/hospitals-3/v1.1.1/geoparquet/hospitals-3.parquet", "source_ID"),
        "transmission_lines": (
            "transmission-lines-1/transmission-lines-1/v1.0.0/geoparquet/transmission-lines-1.parquet",
            "OBJECTID",
        ),
        "epa_frs_facilities": (
            "epa-facility-registry-service-frs-interests/epa-facility-registry-service-frs-interests/v1.0.0"
            "/geoparquet/epa-facility-registry-service-frs-interests.parquet",
            "OBJECTID",
        ),
    }
    COUNTIES = "us-county-boundaries-1/us-county-boundaries-1/v1.0.0/geoparquet/us-county-boundaries-1.parquet"
    MACHINE = f"{platform.system()} {platform.machine()}, {os.cpu_count()} CPUs"
    print("Machine:", MACHINE)
    return (
        BUCKET_URL,
        COUNTIES,
        COUNTY_ROW_GROUP_ROWS,
        DATA_DIR,
        LAYERS,
        MACHINE,
        N_LOCATIONS,
        N_REMOTE_LOCATIONS,
        PG_DSN,
        RESULTS_DIR,
        ROW_GROUP_ROWS,
        S3_BUCKET,
        S3_ENDPOINT,
    )


@app.cell
def _(mo):
    mo.md(r"""
    ## The data

    - **Hospitals**: 8,340 points, a 1 MB file.
    - **Transmission lines**: 94,619 lines, 44 MB.
    - **EPA FRS facilities**: 6.3 million points, 439 MB. HIFLD Next has no substations layer, so this stands in as
      the big layer.
    - **US county boundaries**: 3,235 polygons, used for the county queries.

    All four are downloaded from HIFLD Next's public bucket when the notebook runs. Nothing large is committed.
    """)
    return


@app.cell
def _(BUCKET_URL, COUNTIES, DATA_DIR, LAYERS, requests):
    published_paths = {}
    for _name, _key in [*((n, p) for n, (p, _) in LAYERS.items()), ("counties", COUNTIES)]:
        _dest = DATA_DIR / "published" / f"{_name}.parquet"
        _dest.parent.mkdir(parents=True, exist_ok=True)
        if not _dest.exists():
            with requests.get(f"{BUCKET_URL}/{_key}", stream=True, timeout=600) as _r:
                _r.raise_for_status()
                with open(_dest, "wb") as _f:
                    for _chunk in _r.iter_content(1 << 20):
                        _f.write(_chunk)
        published_paths[_name] = _dest
    {k: f"{v.stat().st_size / 1e6:.1f} MB" for k, v in published_paths.items()}
    return (published_paths,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Four ways to write the same file

    1. **published**: the file as HIFLD Next serves it today. It is GeoParquet 1.1 and already has a `bbox` covering
       column, but rows aren't spatially sorted, and the two smaller layers are a single row group.
    2. **hilbert**: rows sorted along a Hilbert curve by DuckDB, 10,000 rows per row group, GeoParquet 1.0, no `bbox`
       column.
    3. **hilbert_bbox**: the same sort done by [geoparquet-io](https://github.com/geoparquet/geoparquet-io)
       (`gpio sort hilbert --add-bbox`), GeoParquet 1.1 with a `bbox` covering column, 10,000 rows per row group.
    4. **hilbert_native**: the DuckDB sort written with `GEOPARQUET_VERSION 'V2'`, which stores geometry as Parquet's
       native `GEOMETRY` type. Each row group then carries its own bounding box in the Parquet statistics.

    The county file is written the same four ways, with 100 rows per row group so a one-state query can skip most
    of it.
    """)
    return


@app.cell
def _(COUNTY_ROW_GROUP_ROWS, DATA_DIR, RESULTS_DIR, ROW_GROUP_ROWS, duckdb, pd, published_paths, subprocess, time):
    _con = duckdb.connect()
    _con.sql("install spatial; load spatial")
    layout_paths = {}
    _rows = []
    for _name, _src in published_paths.items():
        _rg = COUNTY_ROW_GROUP_ROWS if _name == "counties" else ROW_GROUP_ROWS
        layout_paths[(_name, "published")] = _src
        _rows.append((_name, "published", 0.0, _src.stat().st_size))
        _sorted = (
            f"select * exclude (bbox) from '{_src}' order by "
            f"ST_Hilbert(geometry, (select ST_Extent(ST_Extent_Agg(geometry)) from '{_src}'))"
        )
        for _layout, _version in [("hilbert", "V1"), ("hilbert_native", "V2")]:
            _dest = DATA_DIR / _layout / f"{_name}.parquet"
            _dest.parent.mkdir(exist_ok=True)
            _t = time.perf_counter()
            _con.sql(
                f"copy ({_sorted}) to '{_dest}' "
                f"(format parquet, compression zstd, row_group_size {_rg}, geoparquet_version '{_version}')"
            )
            _rows.append((_name, _layout, time.perf_counter() - _t, _dest.stat().st_size))
            layout_paths[(_name, _layout)] = _dest
        _dest = DATA_DIR / "hilbert_bbox" / f"{_name}.parquet"
        _dest.parent.mkdir(exist_ok=True)
        _t = time.perf_counter()
        _gpio = subprocess.run(
            ["gpio", "sort", "hilbert", "--add-bbox", "--row-group-size", str(_rg), str(_src), str(_dest)],
            capture_output=True,
            text=True,
        )
        assert _gpio.returncode == 0, _gpio.stderr
        _rows.append((_name, "hilbert_bbox", time.perf_counter() - _t, _dest.stat().st_size))
        layout_paths[(_name, "hilbert_bbox")] = _dest

    layouts = pd.DataFrame(_rows, columns=["layer", "layout", "write_seconds", "bytes"])
    layouts["row_groups"] = [
        _con.sql(
            f"select count(distinct row_group_id) from parquet_metadata('{layout_paths[(r.layer, r.layout)]}')"
        ).fetchall()[0][0]
        for r in layouts.itertuples()
    ]
    layouts["MB"] = (layouts["bytes"] / 1e6).round(1)
    print(layouts.drop(columns="bytes").to_string(index=False))
    layouts["write_seconds"] = layouts["write_seconds"].round(1)
    layouts.to_csv(RESULTS_DIR / "layouts.csv", index=False)
    layouts
    return layout_paths, layouts


@app.cell
def _(S3_BUCKET, S3_ENDPOINT, boto3, layout_paths):
    # Put every file in the local object store so DuckDB reads them over S3 range requests, as it would from a cloud
    # bucket. SeaweedFS accepts any key when it runs without an identity config.
    _s3 = boto3.client(
        "s3",
        endpoint_url=f"http://{S3_ENDPOINT}",
        aws_access_key_id="bench",
        aws_secret_access_key="bench",
        region_name="us-east-1",
    )
    if S3_BUCKET not in [b["Name"] for b in _s3.list_buckets()["Buckets"]]:
        _s3.create_bucket(Bucket=S3_BUCKET)
    s3_urls = {}
    for (_name, _layout), _path in layout_paths.items():
        _key = f"{_layout}/{_name}.parquet"
        _s3.upload_file(str(_path), S3_BUCKET, _key)
        s3_urls[(_name, _layout)] = f"s3://{S3_BUCKET}/{_key}"
    print(f"Uploaded {len(s3_urls)} files to s3://{S3_BUCKET} at {S3_ENDPOINT}")
    return (s3_urls,)


@app.cell
def _(mo):
    mo.md(r"""
    ## How we measure a DuckDB query

    DuckDB's HTTP log records every range request it sends, with the byte range. We turn off DuckDB's file and
    metadata caches so each query fetches what it needs, like a fresh serverless reader would. Then we add up the bytes
    and map each range back to the row groups it touched, using the row-group offsets in the Parquet footer.
    """)
    return


@app.cell
def _(S3_ENDPOINT, duckdb, layout_paths, time):
    def connect_duckdb() -> duckdb.DuckDBPyConnection:
        con = duckdb.connect()
        con.sql("install spatial; load spatial; install httpfs; load httpfs")
        con.sql(
            f"create secret (type s3, key_id 'bench', secret 'bench', endpoint '{S3_ENDPOINT}', "
            "url_style 'path', use_ssl false, region 'us-east-1')"
        )
        con.sql("set enable_external_file_cache = false; set enable_http_metadata_cache = false")
        con.sql("set enable_logging = true; set logging_level = 'debug'; set enabled_log_types = 'HTTP'")
        return con

    _meta = duckdb.connect()
    row_group_spans = {}
    for _key, _path in layout_paths.items():
        row_group_spans[_key] = _meta.sql(
            f"select row_group_id, min(coalesce(dictionary_page_offset, data_page_offset)), "
            f"max(data_page_offset + total_compressed_size) from parquet_metadata('{_path}') group by 1"
        ).fetchall()

    def run_duckdb(
        con: duckdb.DuckDBPyConnection, sql: str, layer_url: str, spans: list[tuple[int, int, int]]
    ) -> tuple[list[tuple], float, int, int, int]:
        """Run one query; return its rows, milliseconds, bytes fetched, GET requests and layer row groups read."""
        con.sql("call truncate_duckdb_logs()")
        start = time.perf_counter()
        rows = con.sql(sql).fetchall()
        elapsed_ms = (time.perf_counter() - start) * 1000
        gets = con.sql(
            "select request.url, request.headers['Range'], response.headers['Content-Length']::bigint "
            "from duckdb_logs_parsed('HTTP') where request.type = 'GET'"
        ).fetchall()
        touched = set()
        for url, byte_range, _ in gets:
            if not url.endswith(layer_url.split("/", 3)[-1]) or byte_range is None:
                continue
            first, last = (int(x) for x in byte_range.split("=")[1].split("-"))
            touched |= {rg for rg, start_b, end_b in spans if first < end_b and last >= start_b}
        return rows, elapsed_ms, sum(n or 0 for _, _, n in gets), len(gets), len(touched)

    return connect_duckdb, row_group_spans, run_duckdb


@app.cell
def _(mo):
    mo.md(r"""
    ## The pruning check: does DuckDB skip row groups on its own?

    The DuckDB pull request that added GeoParquet 1.1 bbox pruning was closed unmerged, so we check what the current
    release does. One query, the EPA facilities in a box over lower Manhattan and Brooklyn, run against each layout in
    two forms: with only the spatial predicate (`ST_Intersects`), and with an explicit filter on the `bbox` column
    added, where the file has one.
    """)
    return


@app.cell
def _(RESULTS_DIR, connect_duckdb, duckdb, pd, row_group_spans, run_duckdb, s3_urls):
    _con = connect_duckdb()
    _box = "ST_MakeEnvelope(-74.1, 40.6, -73.9, 40.8)"
    _hint = "bbox.xmin <= -73.9 and bbox.xmax >= -74.1 and bbox.ymin <= 40.8 and bbox.ymax >= 40.6 and "
    _rows = []
    for _layout in ["published", "hilbert", "hilbert_bbox", "hilbert_native"]:
        _url = s3_urls[("epa_frs_facilities", _layout)]
        for _form, _pref in [("spatial predicate only", ""), ("plus bbox column filter", _hint)]:
            if _pref and _layout in ("hilbert", "hilbert_native"):
                continue
            _sql = f"select count(*) from '{_url}' where {_pref} ST_Intersects(geometry, {_box})"
            _r, _ms, _bytes, _gets, _rg = run_duckdb(_con, _sql, _url, row_group_spans[("epa_frs_facilities", _layout)])
            _total = len(row_group_spans[("epa_frs_facilities", _layout)])
            _rows.append((_layout, _form, _r[0][0], round(_ms), round(_bytes / 1e6, 1), f"{_rg} of {_total}"))
    pruning = pd.DataFrame(_rows, columns=["layout", "query form", "facilities", "ms", "MB fetched", "row groups read"])
    pruning["duckdb_version"] = duckdb.__version__
    pruning.to_csv(RESULTS_DIR / "pruning.csv", index=False)
    print(pruning.to_string(index=False))
    pruning
    return (pruning,)


@app.cell
def _(mo, pruning):
    _v = pruning["duckdb_version"].iloc[0]
    mo.md(f"""
    **DuckDB {_v}** skips row groups on its own only for the **native geometry** file: `ST_Intersects` reads the
    Parquet geometry statistics. It doesn't read GeoParquet 1.1's `bbox` covering metadata, so on the published file
    and the geoparquet-io file the spatial predicate alone reads every row group. Those files do prune when the query
    also spells out the filter on the `bbox` column. So for every query below, files with a `bbox` column run in both
    forms.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## PostGIS on the same machine

    PostGIS 17 with PostGIS 3.5 runs in Docker next to the object store. We load each layer's id and geometry
    (DuckDB also reads only those columns), set every layer to SRID 4326 (the NAD83 layers differ from WGS 84 by
    about a metre) and build a GiST index. The load and index time is part of what a database costs.
    """)
    return


@app.cell
def _(LAYERS, PG_DSN, RESULTS_DIR, duckdb, layout_paths, pd, psycopg, time):
    # One table per layer: id and geometry only. DuckDB writes a CSV of id and hex WKB, PostgreSQL COPYs it in.
    _src = duckdb.connect()
    _src.sql("load spatial")
    _rows = []
    with psycopg.connect(PG_DSN, autocommit=True) as _pg:
        _pg.execute("create extension if not exists postgis")
        for _name, _id in [*((n, i) for n, (_, i) in LAYERS.items()), ("counties", "GEOID")]:
            _path = layout_paths[(_name, "published")]
            _csv = _path.with_suffix(".csv")
            _extra = ", STATEFP" if _name == "counties" else ""
            _t = time.perf_counter()
            _pg.execute(f"drop table if exists {_name}")
            _cols = "id text, statefp text, wkb text" if _name == "counties" else "id text, wkb text"
            _pg.execute(f"create table {_name} ({_cols})")
            _src.sql(
                f"copy (select {_id}::varchar{_extra}, ST_AsHEXWKB(geometry) from '{_path}') to '{_csv}' (header false)"
            )
            with _pg.cursor().copy(f"copy {_name} from stdin (format csv)") as _copy, open(_csv, "rb") as _f:
                for _chunk in iter(lambda f=_f: f.read(1 << 20), b""):
                    _copy.write(_chunk)
            _csv.unlink()
            _pg.execute(f"alter table {_name} add column geom geometry")
            _pg.execute(f"update {_name} set geom = ST_SetSRID(ST_GeomFromWKB(decode(wkb, 'hex')), 4326)")
            _pg.execute(f"alter table {_name} drop column wkb")
            _pg.execute(f"create index on {_name} using gist (geom)")
            if _name == "counties":
                _pg.execute("create index on counties (statefp)")
            _pg.execute(f"vacuum analyze {_name}")
            _n = _pg.execute(f"select count(*) from {_name}").fetchall()[0][0]
            _size = _pg.execute(f"select pg_total_relation_size('{_name}')").fetchall()[0][0]
            _rows.append((_name, _n, round(time.perf_counter() - _t, 1), round(_size / 1e6, 1)))
    postgis_load = pd.DataFrame(_rows, columns=["layer", "rows", "load_and_index_seconds", "table_and_index_MB"])
    postgis_load.to_csv(RESULTS_DIR / "postgis_load.csv", index=False)
    print(postgis_load.to_string(index=False))
    postgis_load
    return (postgis_load,)


@app.cell
def _(mo):
    mo.md(r"""
    ## The queries

    We pick 20 query locations at random (fixed seed) from hospitals in the lower 48. For each location:

    - **bounding box**: features in a box 0.2° on a side (about 20 by 15 km) around it.
    - **point in county**: features inside the county polygon that holds the point. The polygon goes into both
      engines as the same literal.
    - **nearest 5**: the five closest features. PostGIS uses its KNN index (`<->`). DuckDB has no index, so it searches
      a window 0.25° out and doubles it, up to four times, until it finds five. Every try counts toward its time.
    - **county join**: features per county for the whole state that holds the point, a spatial join against the
      county file. This one runs for the first five locations' states.

    Distances are planar in degrees in both engines, so the nearest-5 answers can be compared exactly. After each
    query we check that DuckDB and PostGIS returned the same ids.
    """)
    return


@app.cell
def _(N_LOCATIONS, duckdb, layout_paths):
    _con = duckdb.connect()
    _con.sql("load spatial")
    _hospitals = layout_paths[("hospitals", "published")]
    _counties = layout_paths[("counties", "published")]
    locations = _con.sql(
        f"""
        with picked as (
            select ST_X(geometry) x, ST_Y(geometry) y, geometry from '{_hospitals}'
            where ST_X(geometry) between -125 and -66 and ST_Y(geometry) between 24 and 50
            order by hash(source_ID || 'seed-7') limit {N_LOCATIONS}
        )
        select p.x, p.y, c.GEOID, c.STATEFP, ST_AsHEXWKB(c.geometry), ST_XMin(c.geometry), ST_YMin(c.geometry),
               ST_XMax(c.geometry), ST_YMax(c.geometry)
        from picked p join '{_counties}' c on ST_Intersects(ST_SetCRS(p.geometry, 'EPSG:4269'), c.geometry)
        order by hash(p.x)
        """
    ).fetchall()
    state_extent = dict(
        _con.sql(
            f"select STATEFP, [min(ST_XMin(geometry)), min(ST_YMin(geometry)), max(ST_XMax(geometry)), "
            f"max(ST_YMax(geometry))] from '{_counties}' group by 1"
        ).fetchall()
    )
    print(f"{len(locations)} locations in {len({loc[3] for loc in locations})} states")
    return locations, state_extent


@app.cell
def _(LAYERS, state_extent):
    def envelope_sql(env: list[float]) -> str:
        return f"ST_MakeEnvelope({env[0]}, {env[1]}, {env[2]}, {env[3]})"

    def bbox_hint(env: list[float]) -> str:
        return (
            f"bbox.xmin <= {env[2]} and bbox.xmax >= {env[0]} and bbox.ymin <= {env[3]} and bbox.ymax >= {env[1]} and "
        )

    def query_sql(
        engine: str,
        query: str,
        layer: str,
        loc: tuple,
        src: str = "",
        county_src: str = "",
        crs: str = "",
        hint: bool = False,
        half_width: float = 0.25,
    ) -> str:
        """SQL for one query at one location. `src` is the layer file for DuckDB; PostGIS uses the table."""
        x, y, _, statefp, county_hex = loc[:5]
        layer_id = LAYERS[layer][1]
        county_env = list(loc[5:9])
        box = [x - 0.1, y - 0.1, x + 0.1, y + 0.1]
        window = [x - half_width, y - half_width, x + half_width, y + half_width]
        state_env = state_extent[statefp]
        if engine == "postgis":
            return {
                "bounding box": f"select id from {layer} where ST_Intersects(geom, "
                f"ST_MakeEnvelope({', '.join(map(str, box))}, 4326))",
                "point in county": f"select id from {layer} where ST_Intersects(geom, "
                f"ST_GeomFromWKB(decode('{county_hex}', 'hex'), 4326))",
                "nearest 5": f"select id from {layer} "
                f"order by geom <-> ST_SetSRID(ST_Point({x}, {y}), 4326), id limit 5",
                "county join": f"select c.id, count(*) from {layer} l join counties c on ST_Intersects(l.geom, c.geom) "
                f"where c.statefp = '{statefp}' group by 1 order by 1",
            }[query]

        def pref(env: list[float]) -> str:
            return bbox_hint(env) if hint else ""

        return {
            "bounding box": f"select {layer_id}::varchar from '{src}' where {pref(box)} "
            f"ST_Intersects(geometry, {envelope_sql(box)})",
            "point in county": f"select {layer_id}::varchar from '{src}' where {pref(county_env)} "
            f"ST_Intersects(geometry, ST_GeomFromHEXWKB('{county_hex}'))",
            "nearest 5": f"select {layer_id}::varchar from '{src}' where {pref(window)} "
            f"ST_Intersects(geometry, {envelope_sql(window)}) "
            f"order by ST_Distance(geometry, ST_Point({x}, {y})), {layer_id}::varchar limit 5",
            "county join": f"select c.GEOID, count(*) from '{src}' l "
            f"join (select GEOID, ST_SetCRS(geometry, '{crs}') g "
            f"from '{county_src}' where STATEFP = '{statefp}' and {pref(state_env)} "
            f"ST_Intersects(geometry, {envelope_sql(state_env)})) "
            f"c on ST_Intersects(l.geometry, c.g) "
            f"where {pref(state_env)} ST_Intersects(l.geometry, {envelope_sql(state_env)}) "
            "group by 1 order by 1",
        }[query]

    QUERIES = ["bounding box", "point in county", "nearest 5", "county join"]
    return QUERIES, query_sql


@app.cell
def _(LAYERS, PG_DSN, QUERIES, locations, psycopg, query_sql, time):
    # PostGIS first: its answers are the key we check DuckDB against.
    postgis_rows = []
    postgis_answers = {}
    with psycopg.connect(PG_DSN, autocommit=True) as _pg:
        for _layer in LAYERS:
            for _query in QUERIES:
                _locs = locations[:5] if _query == "county join" else locations
                _pg.execute(query_sql("postgis", _query, _layer, _locs[0])).fetchall()  # warm-up
                for _i, _loc in enumerate(_locs):
                    _t = time.perf_counter()
                    _ans = _pg.execute(query_sql("postgis", _query, _layer, _loc)).fetchall()
                    _ms = (time.perf_counter() - _t) * 1000
                    postgis_answers[(_layer, _query, _i)] = sorted(_ans)
                    postgis_rows.append(
                        ("postgis", "table + GiST", "", _layer, _query, _i, _ms, None, None, None, True)
                    )
    print(f"{len(postgis_rows)} PostGIS queries")
    return postgis_answers, postgis_rows


@app.cell
def _(QUERIES, duckdb, postgis_answers, query_sql, row_group_spans, run_duckdb):
    def run_variant(
        con: duckdb.DuckDBPyConnection, layer: str, layout: str, hint: bool, urls: dict, locs: list, engine: str
    ) -> list[tuple]:
        """Every query at every location for one layer, layout and query form, checked against PostGIS."""
        src, county_src = urls[(layer, layout)], urls[("counties", layout)]
        spans = row_group_spans[(layer, layout)]
        crs = con.sql(f"select ST_CRS(geometry) from '{src}' limit 1").fetchall()[0][0] or "OGC:CRS84"
        out = []
        for query in QUERIES:
            q_locs = locs[:5] if query == "county join" else locs
            for i, loc in enumerate(q_locs):
                total_ms, total_bytes, total_gets, rgs, half_width = 0.0, 0, 0, 0, 0.25
                rows: list[tuple] = []
                for _try in range(4 if query == "nearest 5" else 1):
                    sql = query_sql("duckdb", query, layer, loc, src, county_src, crs, hint, half_width)
                    rows, ms, nbytes, gets, rg = run_duckdb(con, sql, src, spans)
                    total_ms, total_bytes, total_gets, rgs = (
                        total_ms + ms,
                        total_bytes + nbytes,
                        total_gets + gets,
                        rgs + rg,
                    )
                    if len(rows) >= 5:
                        break
                    half_width *= 2
                match = sorted(rows) == postgis_answers[(layer, query, i)]
                form = "bbox filter" if hint else "spatial only"
                out.append((engine, layout, form, layer, query, i, total_ms, total_bytes, total_gets, rgs, match))
        return out

    return (run_variant,)


@app.cell
def _(LAYERS, connect_duckdb, locations, run_variant, s3_urls):
    # Each layer, layout and query form, from the local object store. One warm-up query per variant is not counted.
    VARIANTS = [
        ("published", False),
        ("published", True),
        ("hilbert", False),
        ("hilbert_bbox", False),
        ("hilbert_bbox", True),
        ("hilbert_native", False),
    ]
    duckdb_rows = []
    for _layer in LAYERS:
        for _layout, _hint in VARIANTS:
            _con = connect_duckdb()
            run_variant(_con, _layer, _layout, _hint, s3_urls, locations[:1], "warm-up")
            duckdb_rows += run_variant(_con, _layer, _layout, _hint, s3_urls, locations, "duckdb, local S3")
            print(f"done {_layer} {_layout} {'bbox filter' if _hint else 'spatial only'}")
    return (duckdb_rows,)


@app.cell
def _(mo):
    mo.md(r"""
    ## The same files over the internet

    The local object store has almost no latency, which flatters DuckDB. To see what distance costs, we run the
    published files straight from HIFLD Next's public Google Cloud Storage bucket for the first five locations. Only
    the published layout lives there, so this shows how a researcher's query performs today.
    """)
    return


@app.cell
def _(BUCKET_URL, COUNTIES, LAYERS, N_REMOTE_LOCATIONS, connect_duckdb, locations, run_variant):
    _remote_urls = {(n, "published"): f"{BUCKET_URL}/{p}" for n, (p, _) in LAYERS.items()}
    _remote_urls[("counties", "published")] = f"{BUCKET_URL}/{COUNTIES}"
    remote_rows = []
    for _layer in LAYERS:
        for _hint in (False, True):
            _con = connect_duckdb()
            run_variant(_con, _layer, "published", _hint, _remote_urls, locations[:1], "warm-up")
            remote_rows += run_variant(
                _con, _layer, "published", _hint, _remote_urls, locations[:N_REMOTE_LOCATIONS], "duckdb, public GCS"
            )
    print(f"{len(remote_rows)} queries against the public bucket")
    return (remote_rows,)


@app.cell
def _(RESULTS_DIR, duckdb_rows, pd, postgis_rows, remote_rows):
    timings = pd.DataFrame(
        postgis_rows + duckdb_rows + remote_rows,
        columns=[
            "engine",
            "layout",
            "query_form",
            "layer",
            "query",
            "location",
            "ms",
            "bytes",
            "gets",
            "row_groups_read",
            "matches_postgis",
        ],
    )
    timings.to_csv(RESULTS_DIR / "timings.csv", index=False)
    summary = (
        timings.groupby(["layer", "query", "engine", "layout", "query_form"], sort=False)
        .agg(
            median_ms=("ms", "median"),
            p95_ms=("ms", lambda s: s.quantile(0.95)),
            median_MB=("bytes", lambda s: s.median() / 1e6),
            median_gets=("gets", "median"),
            median_row_groups=("row_groups_read", "median"),
            all_match=("matches_postgis", "all"),
            n=("ms", "size"),
        )
        .round(2)
        .reset_index()
    )
    summary.to_csv(RESULTS_DIR / "summary.csv", index=False)
    _duck = timings[timings["engine"] != "postgis"]
    print(f"{(~_duck['matches_postgis']).sum()} of {len(_duck)} DuckDB answers differ from PostGIS")
    summary
    return summary, timings


@app.cell
def _(LAYERS, QUERIES, RESULTS_DIR, plt, summary):
    _local = summary[summary["engine"].isin(["postgis", "duckdb, local S3"])].copy()
    _local["variant"] = _local.apply(
        lambda r: "PostGIS" if r.engine == "postgis" else f"{r.layout}\n{r.query_form}", axis=1
    )
    _variants = list(dict.fromkeys(_local["variant"]))
    _fig, _axes = plt.subplots(1, len(LAYERS), figsize=(15, 5), sharey=True)
    for _ax, _layer in zip(_axes, LAYERS, strict=True):
        _sub = _local[_local["layer"] == _layer]
        _width = 0.8 / len(_variants)
        for _j, _v in enumerate(_variants):
            _vals = [_sub[(_sub["query"] == q) & (_sub["variant"] == _v)]["median_ms"].sum() for q in QUERIES]
            _ax.bar([q + _j * _width for q in range(len(QUERIES))], _vals, _width, label=_v.replace("\n", ", "))
        _ax.set_yscale("log")
        _ax.set_xticks([q + 0.4 - _width / 2 for q in range(len(QUERIES))], QUERIES, rotation=20)
        _ax.set_title(_layer.replace("_", " "))
        _ax.grid(axis="y", alpha=0.3)
    _axes[0].set_ylabel("median ms per query (log scale)")
    _axes[-1].legend(fontsize=7, loc="upper left", bbox_to_anchor=(1, 1))
    _fig.suptitle("DuckDB on GeoParquet from a local object store vs PostGIS, same machine")
    _fig.tight_layout()
    _fig.savefig(RESULTS_DIR / "chart.png", dpi=130)
    _fig
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Cost per thousand queries

    A file in a bucket costs per request and per byte; a database costs per hour whether anyone queries it or not.
    Prices: Google Cloud Storage Class B (read) operations at **$0.0004 per 1,000**, internet egress at **$0.12 per
    GB** for the first tier ([Google's pricing examples](https://cloud.google.com/storage/pricing-examples)); reads
    from a VM in the same region pay no egress. For PostGIS, a GCP **e2-medium** (2 vCPU, 4 GB) at **$0.0553 an
    hour**, about $40 a month on demand in us-central1 ([Spare Cores, observed August 2026](https://sparecores.com/server/gcp/e2-medium)),
    which is ample for these tables. Storage itself is a few cents a month either way and left out.
    """)
    return


@app.cell
def _(RESULTS_DIR, summary):
    CLASS_B_PER_1K = 0.0004
    EGRESS_PER_GB = 0.12
    VM_PER_MONTH = 0.0553 * 730
    _duck = summary[summary["engine"] == "duckdb, local S3"].copy()
    _duck["usd_per_1k_internet"] = (
        _duck["median_gets"] * CLASS_B_PER_1K + _duck["median_MB"] / 1000 * EGRESS_PER_GB * 1000
    ).round(3)
    _duck["usd_per_1k_same_region"] = (_duck["median_gets"] * CLASS_B_PER_1K).round(4)
    costs = _duck[
        [
            "layer",
            "query",
            "layout",
            "query_form",
            "median_MB",
            "median_gets",
            "usd_per_1k_internet",
            "usd_per_1k_same_region",
        ]
    ]
    costs.to_csv(RESULTS_DIR / "costs.csv", index=False)
    postgis_per_1k = {f"{v:,} queries a month": round(VM_PER_MONTH / v * 1000, 3) for v in (10_000, 100_000, 1_000_000)}
    print(f"PostGIS on an e2-medium: ${VM_PER_MONTH:.0f}/month, so per 1,000 queries:", postgis_per_1k)
    costs
    return (postgis_per_1k,)


@app.cell
def _(RESULTS_DIR, pd, summary):
    # For each layer and query: PostGIS against the fastest DuckDB variant on the local store and against the
    # published file read the plain way, which is what a researcher gets today.
    _pg = summary[summary["engine"] == "postgis"].set_index(["layer", "query"])["median_ms"]
    _local = summary[summary["engine"] == "duckdb, local S3"]
    _best = _local.loc[_local.groupby(["layer", "query"], sort=False)["median_ms"].idxmin()].set_index(
        ["layer", "query"]
    )
    _plain = _local[(_local["layout"] == "published") & (_local["query_form"] == "spatial only")].set_index(
        ["layer", "query"]
    )
    headline = pd.DataFrame(
        {
            "postgis_ms": _pg,
            "published_plain_ms": _plain["median_ms"],
            "best_duckdb_ms": _best["median_ms"],
            "best_variant": _best["layout"] + ", " + _best["query_form"],
            "best_MB_fetched": _best["median_MB"],
        }
    ).reset_index()
    headline["best_vs_postgis"] = (headline["best_duckdb_ms"] / headline["postgis_ms"]).round(0)
    headline["published_vs_best"] = (headline["published_plain_ms"] / headline["best_duckdb_ms"]).round(1)
    headline.to_csv(RESULTS_DIR / "headline.csv", index=False)
    print(headline.to_string(index=False))
    headline
    return


@app.cell
def _(mo, timings):
    _duck = timings[timings["engine"] != "postgis"]
    _wrong = _duck[~_duck["matches_postgis"]]
    mo.md(f"""
    ## What didn't work, and what this doesn't show

    - **{len(_wrong)} of {len(_duck)}** DuckDB answers differed from PostGIS in this run.
    - MinIO, which the issue suggested, no longer publishes pullable Docker images (Docker Hub refuses the pull,
      quay.io asks for a login), so the object store is SeaweedFS. Any S3-compatible store serves the same range reads.
    - geoparquet-io 1.2.0 crashes on DuckDB 2.0 (it calls a connection method 2.0 removed), so we pin 0.4.0.
    - DuckDB 2.0 ignores GeoParquet 1.1's `bbox` covering metadata. The published files already have the column, but a
      query only benefits if it filters on `bbox` by hand.
    - DuckDB has no spatial index, so nearest-neighbour search is a widening window, and the county join stays slow
      because it has to test every candidate point against detailed county polygons.
    - The local store has almost no latency. The public-bucket run shows what distance adds, but it went through this
      machine's egress proxy, so treat those numbers as an upper bound for a researcher on a good connection.
    - We ran on one cloud container, not on a laptop and a separate cloud VM, and with one query at a time. PostGIS
      under many concurrent users, or DuckDB from a VM next to the bucket, would each look different.
    """)
    return


if __name__ == "__main__":
    app.run()

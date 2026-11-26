import marimo

__generated_with = "0.26.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import functools
    import hashlib
    import json
    import os
    import random
    import shutil
    import statistics
    import subprocess
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from http.server import ThreadingHTTPServer
    from pathlib import Path

    import duckdb
    import geopandas as gpd
    import httpx
    import marimo as mo
    import numpy as np
    import pandas as pd
    import pyarrow.parquet as pq
    from RangeHTTPServer import RangeRequestHandler

    DATA = Path(os.environ.get("DATA_DIR", "data")).resolve()
    OUT = Path(os.environ.get("OUT_DIR", "outputs")).resolve()
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    SEED = int(os.environ.get("SEED", "331"))
    REPEATS = int(os.environ.get("REPEATS", "3"))
    API = "https://hifld.publicenvirodata.org/api/collections/hifld/datasets"
    http = httpx.Client(timeout=300, follow_redirects=True)
    return (
        API,
        DATA,
        OUT,
        REPEATS,
        RangeRequestHandler,
        SEED,
        ThreadPoolExecutor,
        ThreadingHTTPServer,
        duckdb,
        functools,
        gpd,
        hashlib,
        http,
        json,
        mo,
        np,
        pd,
        pq,
        random,
        shutil,
        statistics,
        subprocess,
        threading,
        time,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # What changes when HIFLD Next's GeoParquet moves to GeoParquet 2.0?

    GeoParquet 2.0 ([released 2026-11-24](https://cloudnativegeo.org/blog/2026/11/geoparquet-2-0-released/))
    stores geometry in Parquet's own `GEOMETRY` type. The CRS travels on the column, and every row group carries
    a bounding box in its statistics, so a reader can skip row groups "with no extra columns". GeoParquet 1.1
    files, which is what [HIFLD Next](https://hifld.publicenvirodata.org) publishes, store WKB in a plain binary
    column and add a `bbox` struct column so readers can skip row groups.

    **The question:** if HIFLD Next converts its files to 2.0, do spatial queries read fewer bytes, do the answers
    stay the same, and which readers break? We expect fewer bytes for filtered queries and identical answers.

    The steps: draw a seeded sample of layers from the catalog, convert each to 2.0 with and without `bbox`,
    check every row survives, serve all the files over HTTP with range requests, run the same box and attribute
    queries in DuckDB and GeoPandas while counting bytes, then open the files in current and year-old readers.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. The sample

    We walk HIFLD Next's catalog API down to the latest version of every layer and read its geometry type,
    feature count and GeoParquet file size. Row-group statistics can only help a file with more than one row
    group, so the candidates are layers with at least 100,000 features and a 10 to 500 MB file. That's the
    middle of the catalog: big enough to filter, small enough to rewrite eight times here. Many datasets are
    series of near-identical layers (50 states of roads, census blocks by state), so we keep one layer per
    dataset before drawing two points, two lines and two polygons with a fixed seed. Polygons are drawn from
    those with above-median bytes per feature, the "large polygons" the issue asks for.
    """)
    return


@app.cell
def _(API, ThreadPoolExecutor, http):
    def latest_collections(dataset: dict) -> list[dict]:
        """Follow a dataset catalog's child layers to each one's latest-version collection.json."""
        found = []
        for _link in dataset["links"]:
            if _link["rel"] != "child":
                continue
            _r = http.get(_link["href"])
            _r.raise_for_status()
            _latest = [x["href"] for x in _r.json()["links"] if x["rel"] == "latest-version"]
            if _latest:
                _c = http.get(_latest[0])
                _c.raise_for_status()
                found.append(_c.json())
        return found

    _datasets = []
    for _offset in range(0, 5000, 50):
        _r = http.get(API, params={"limit": 50, "offset": _offset})
        _r.raise_for_status()
        _page = _r.json()
        _datasets += _page["datasets"]
        if _offset + 50 >= _page["total"]:
            break
    with ThreadPoolExecutor(16) as _ex:
        _collections = [c for cs in _ex.map(latest_collections, _datasets) for c in cs]

    catalog = {}
    for _c in _collections:
        _gp = [a for a in _c["assets"].values() if a.get("type") == "application/vnd.apache.parquet"]
        if _gp:
            catalog[_gp[0]["href"]] = {
                "id": _c["id"],
                "dataset": _c["id"].split("/")[1],
                "geometry_type": _c.get("hifld:geometry_type"),
                "features": _c.get("hifld:feature_count") or 0,
                "bytes": _gp[0]["file:size"],
                "href": _gp[0]["href"],
            }
    print(f"{len(_datasets)} datasets, {len(_collections)} layers, {len(catalog)} distinct GeoParquet files")
    return (catalog,)


@app.cell
def _(SEED, catalog, pd, random, statistics):
    _classes = {
        "points": ("Point",),
        "lines": ("LineString", "MultiLineString"),
        "polygons": ("Polygon", "MultiPolygon"),
    }
    _rng = random.Random(SEED)
    _picked = []
    for _cls, _types in _classes.items():
        _cands = [
            x
            for x in sorted(catalog.values(), key=lambda x: x["href"])
            if x["geometry_type"] in _types and x["features"] >= 100_000 and 10e6 <= x["bytes"] <= 500e6
        ]
        if _cls == "polygons":
            _median = statistics.median(x["bytes"] / x["features"] for x in _cands)
            _cands = [x for x in _cands if x["bytes"] / x["features"] >= _median]
        _by_dataset = {}
        for _x in _cands:
            _by_dataset.setdefault(_x["dataset"], []).append(_x)
        _one_each = [_rng.choice(v) for _, v in sorted(_by_dataset.items())]
        print(f"{_cls}: {len(_cands)} candidate layers in {len(_one_each)} datasets")
        _picked += [{"class": _cls, **x} for x in _rng.sample(_one_each, 2)]
    sample = pd.DataFrame(_picked)
    sample["layer"] = sample["id"].str.split("/").str[2]
    sample[["class", "layer", "geometry_type", "features", "bytes"]]
    return (sample,)


@app.cell
def _(DATA, http, sample):
    published_paths = {}
    for _row in sample.itertuples():
        _path = DATA / _row.layer / "published.parquet"
        _path.parent.mkdir(exist_ok=True)
        if not _path.exists() or _path.stat().st_size != _row.bytes:
            with http.stream("GET", _row.href) as _r, open(_path, "wb") as _f:
                _r.raise_for_status()
                for _chunk in _r.iter_bytes(1 << 20):
                    _f.write(_chunk)
        assert _path.stat().st_size == _row.bytes, f"{_path}: size differs from the catalog"
        published_paths[_row.layer] = _path
    return (published_paths,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. What HIFLD Next publishes today

    Every sampled file is GeoParquet 1.1 with WKB geometry, a `bbox` covering column and ZSTD compression,
    in row groups of about 100,000 rows. The `bbox` column is already the thing 2.0's statistics replace, so
    this is the case where the release post warns the gains may be small.
    """)
    return


@app.cell
def _(json, pd, pq, published_paths):
    _rows = []
    for _layer, _path in published_paths.items():
        _meta = pq.ParquetFile(_path).metadata
        _geo = json.loads(_meta.metadata[b"geo"])
        _col = _geo["columns"][_geo["primary_column"]]
        assert _geo["primary_column"] == "geometry", f"{_layer}: geometry column is {_geo['primary_column']}"
        _crs = _col.get("crs") or {}
        _rows.append(
            {
                "layer": _layer,
                "version": _geo["version"],
                "encoding": _col["encoding"],
                "bbox column": "covering" in _col,
                "crs": f"{_crs.get('id', {}).get('authority', 'OGC')}:{_crs.get('id', {}).get('code', 'CRS84')}",
                "rows": _meta.num_rows,
                "row groups": _meta.num_row_groups,
                "compression": _meta.row_group(0).column(0).compression,
                "MB": round(_path.stat().st_size / 1e6, 1),
            }
        )
    published = pd.DataFrame(_rows).set_index("layer")
    published
    return (published,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Converting to 2.0

    GeoPandas 1.2 writes GeoParquet 2.0 (`to_parquet(schema_version="2.0.0")`) through pyarrow 26, which writes
    the native `GEOMETRY` logical type with per-row-group bounding boxes, and adds the `bbox` covering column
    when asked (`write_covering_bbox=True`). Every rewrite uses the publishing guide's settings: ZSTD level 15
    and 100,000-row row groups. Eight files per layer:

    | Variant | Format | Rows | Why |
    |---|---|---|---|
    | `published` | 1.1 + bbox | as served | the baseline |
    | `1.1+bbox` | 1.1 + bbox | same order | our writer's control: differences from `published` are the writer, not the format |
    | `2.0` | 2.0 native, no bbox | same order | the plain conversion |
    | `2.0+bbox` | 2.0 native + bbox | same order | the conversion keeping the covering column |
    | `sorted 1.1+bbox` | 1.1 + bbox | Hilbert-sorted | is it the sort or the format? |
    | `sorted 2.0` | 2.0 native | Hilbert-sorted | the 2.0 file the guide recommends |
    | `sorted 2.0+bbox` | 2.0 native + bbox | Hilbert-sorted | |
    | `sorted 2.0, 10k groups` | 2.0 native | Hilbert-sorted, 10,000-row groups | what smaller row groups buy |

    While each layer is in memory we also pick its two queries: a box 2% of the layer's extent on a side,
    centred on a seeded random feature, and an attribute filter on the first text column whose most common
    value covers 1 to 30% of rows.
    """)
    return


@app.cell
def _(SEED, gpd, np, published_paths, time):
    VARIANTS = {
        "published": None,
        "1.1+bbox": ("1.1.0", True, False, 100_000),
        "2.0": ("2.0.0", False, False, 100_000),
        "2.0+bbox": ("2.0.0", True, False, 100_000),
        "sorted 1.1+bbox": ("1.1.0", True, True, 100_000),
        "sorted 2.0": ("2.0.0", False, True, 100_000),
        "sorted 2.0+bbox": ("2.0.0", True, True, 100_000),
        "sorted 2.0, 10k groups": ("2.0.0", False, True, 10_000),
    }
    variant_paths = {}
    queries = {}
    _rows = []
    for _layer, _published in published_paths.items():
        _gdf = gpd.read_parquet(_published)
        _sorted = _gdf.iloc[np.argsort(_gdf.hilbert_distance(), kind="stable")]
        for _name, _spec in VARIANTS.items():
            if _spec is None:
                variant_paths[(_layer, _name)] = _published
                continue
            _version, _bbox, _is_sorted, _rg = _spec
            _path = _published.with_name(_name.replace(" ", "_").replace(",", "").replace("+", "_") + ".parquet")
            _start = time.perf_counter()
            (_sorted if _is_sorted else _gdf).to_parquet(
                _path,
                schema_version=_version,
                write_covering_bbox=_bbox,
                row_group_size=_rg,
                compression="zstd",
                compression_level=15,
            )
            _rows.append((_layer, _name, round(time.perf_counter() - _start, 2)))
            variant_paths[(_layer, _name)] = _path

        _rng = np.random.default_rng(SEED)
        _minx, _miny, _maxx, _maxy = _gdf.total_bounds
        _b = _gdf.geometry.iloc[int(_rng.integers(len(_gdf)))].bounds
        _cx, _cy = (_b[0] + _b[2]) / 2, (_b[1] + _b[3]) / 2
        _hw, _hh = (_maxx - _minx) * 0.01, (_maxy - _miny) * 0.01
        _attr = None
        for _col in _gdf.columns:
            if _col != "geometry" and _gdf[_col].dtype == object:
                _counts = _gdf[_col].value_counts(normalize=True)
                if len(_counts) and 0.01 <= _counts.iloc[0] <= 0.30:
                    _attr = (_col, str(_counts.index[0]), round(float(_counts.iloc[0]), 3))
                    break
        assert _attr is not None, f"{_layer}: no text column to filter on"
        queries[_layer] = {"box": (_cx - _hw, _cy - _hh, _cx + _hw, _cy + _hh), "attribute": _attr}
        del _gdf, _sorted
    write_seconds = {(_l, _n): _s for _l, _n, _s in _rows}
    {_l: {"box": [round(v, 4) for v in q["box"]], "attribute": q["attribute"]} for _l, q in queries.items()}
    return VARIANTS, queries, variant_paths, write_seconds


@app.cell
def _(mo):
    mo.md(r"""
    ### File size

    Size of each file, and how much of it is the `bbox` column (its compressed bytes, from the Parquet footer).
    """)
    return


@app.cell
def _(OUT, VARIANTS, pd, pq, published_paths, variant_paths, write_seconds):
    _rows = []
    for (_layer, _name), _path in variant_paths.items():
        _meta = pq.ParquetFile(_path).metadata
        _bbox_bytes = sum(
            _meta.row_group(i).column(j).total_compressed_size
            for i in range(_meta.num_row_groups)
            for j in range(_meta.num_columns)
            if _meta.row_group(i).column(j).path_in_schema.startswith("bbox.")
        )
        _rows.append(
            {
                "layer": _layer,
                "variant": _name,
                "MB": _path.stat().st_size / 1e6,
                "bbox MB": _bbox_bytes / 1e6,
                "row groups": _meta.num_row_groups,
                "write s": write_seconds.get((_layer, _name)),
            }
        )
    sizes = pd.DataFrame(_rows)
    sizes["vs published"] = sizes["MB"] / sizes["layer"].map(
        {_l: _p.stat().st_size / 1e6 for _l, _p in published_paths.items()}
    )
    sizes.to_csv(OUT / "sizes.csv", index=False)
    size_table = sizes.pivot(index="layer", columns="variant", values="vs published")[list(VARIANTS)].round(2)
    print("File size relative to the published file:")
    print(size_table.to_string())
    size_table
    return (sizes,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Do the answers survive the conversion?

    For each file we hash every row (all attribute columns, plus the geometry's WKB bytes exactly as stored)
    and compare the sorted list of hashes with the published file's. Same multiset of hashes means same rows,
    same attributes and byte-identical geometry, in whatever order.
    """)
    return


@app.cell
def _(OUT, hashlib, pd, pq, variant_paths):
    def row_hashes(path) -> list[str]:
        """Sorted per-row hashes of every column except bbox, with geometry as its stored WKB bytes."""
        _table = pq.read_table(path)
        _names = [n for n in _table.column_names if n != "bbox"]
        _geom = _table.column("geometry")
        _wkb = (_geom.storage if hasattr(_geom, "storage") else _geom.cast("binary")).to_pylist()
        _attrs = _table.select([n for n in _names if n != "geometry"]).to_pandas()
        _attr_hash = pd.util.hash_pandas_object(_attrs, index=False).to_numpy()
        return sorted(
            hashlib.sha1(w + int(a).to_bytes(8, "little")).hexdigest() for w, a in zip(_wkb, _attr_hash, strict=True)
        )

    _rows = []
    for _layer in sorted({k[0] for k in variant_paths}):
        _reference = row_hashes(variant_paths[(_layer, "published")])
        for (_l, _name), _path in variant_paths.items():
            if _l != _layer or _name == "published":
                continue
            _h = row_hashes(_path)
            _rows.append((_layer, _name, len(_reference), len(_h), _h == _reference))
    answers_check = pd.DataFrame(_rows, columns=["layer", "variant", "published rows", "rows", "identical"])
    answers_check.to_csv(OUT / "answers_check.csv", index=False)
    print(f"{answers_check['identical'].sum()} of {len(answers_check)} rewritten files identical to the published file")
    answers_check[~answers_check["identical"]] if (~answers_check["identical"]).any() else answers_check.head(3)
    return (answers_check,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Bytes read over HTTP

    All the files are served from a local HTTP server that answers range requests and records each request:
    the range asked for and the bytes it sent. A local server keeps the network out of the timings, so the
    times show the reader's own work. DuckDB 2.0 (with its file and metadata caches off, like a fresh reader)
    and GeoPandas 1.2 (through fsspec, which is what an `https://` URL gets) each run:

    - **box**: features intersecting the box. DuckDB with `ST_Intersects` alone, and again with an explicit
      filter on the `bbox` column where the file has one (DuckDB doesn't read the 1.1 covering metadata by
      itself). GeoPandas with `read_parquet(url, bbox=...)`, which uses the `bbox` column if declared and the
      2.0 row-group statistics otherwise.
    - **attribute**: the geometries of rows where the attribute equals its value.

    Each answer is reduced to a count and a hash of the returned geometries (as normalised WKB), so we can
    check every variant returns the same features. Bytes are the same on every repeat, and time is the median
    of the repeats.
    """)
    return


@app.cell
def _(DATA, RangeRequestHandler, ThreadingHTTPServer, functools, threading):
    request_log = []

    class LoggingRangeHandler(RangeRequestHandler):
        """RangeHTTPServer's handler, recording each response's method, range and bytes sent."""

        def copyfile(self, source, outputfile) -> None:
            _sent = [0]

            class _Counter:
                def write(self, data: bytes) -> int:
                    _n = outputfile.write(data)
                    _sent[0] += len(data)
                    return _n

            try:
                super().copyfile(source, _Counter())
            except (BrokenPipeError, ConnectionResetError):
                pass
            finally:
                request_log.append((self.command, self.headers.get("Range"), _sent[0]))

        def log_message(self, format: str, *args: object) -> None:
            return None

    server = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(LoggingRangeHandler, directory=str(DATA)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    print("serving", DATA, "at", base_url)
    return base_url, request_log


@app.cell
def _(
    DATA,
    REPEATS,
    VARIANTS,
    base_url,
    duckdb,
    gpd,
    hashlib,
    pd,
    queries,
    request_log,
    statistics,
    time,
    variant_paths,
):
    def run_query(con: duckdb.DuckDBPyConnection, sql: str | None, url: str, gpd_kwargs: dict) -> tuple:
        """Run one query with DuckDB (sql) or GeoPandas (gpd_kwargs); return (row count, hash of the geometries)."""
        if sql is not None:
            return tuple(con.sql(sql).fetchall()[0])
        gdf = gpd.read_parquet(url, **gpd_kwargs)
        return len(gdf), hashlib.sha1(b"".join(sorted(gdf.geometry.to_wkb()))).hexdigest()[:12]

    def measure(con: duckdb.DuckDBPyConnection, sql: str | None, url: str, gpd_kwargs: dict) -> tuple:
        """Run a query REPEATS times; return answer, bytes fetched by range, requests, whole-file GETs, median ms."""
        times, answer, log = [], (0, ""), []
        for _ in range(REPEATS):
            request_log.clear()
            start = time.perf_counter()
            answer = run_query(con, sql, url, gpd_kwargs)
            times.append((time.perf_counter() - start) * 1000)
            log = list(request_log)
        ranged = sum(n for method, rng, n in log if method == "GET" and rng)
        unranged = sum(1 for method, rng, n in log if method == "GET" and not rng)
        return answer, ranged, len(log), unranged, statistics.median(times)

    _con = duckdb.connect()
    _con.sql("install spatial; load spatial; install httpfs; load httpfs")
    _con.sql("set enable_external_file_cache = false; set enable_http_metadata_cache = false")
    _sig = "count(*), bit_xor(hash(ST_AsWKB(geometry)))"
    _rows = []
    for (_layer, _name), _path in variant_paths.items():
        _url = f"{base_url}/{_path.relative_to(DATA)}"
        _x0, _y0, _x1, _y1 = queries[_layer]["box"]
        _col, _val, _ = queries[_layer]["attribute"]
        _val_sql = _val.replace("'", "''")
        _box_sql = (
            f"select {_sig} from '{_url}' where ST_Intersects(geometry, ST_MakeEnvelope({_x0}, {_y0}, {_x1}, {_y1}))"
        )
        _hint = f" and bbox.xmin <= {_x1} and bbox.xmax >= {_x0} and bbox.ymin <= {_y1} and bbox.ymax >= {_y0}"
        _runs = {
            ("box", "DuckDB ST_Intersects"): (_box_sql, {}),
            ("attribute", "DuckDB"): (
                f"select {_sig} from '{_url}' where \"{_col}\" = '{_val_sql}'",
                {},
            ),
            ("box", "GeoPandas bbox="): (None, {"bbox": (_x0, _y0, _x1, _y1)}),
            ("attribute", "GeoPandas filters="): (
                None,
                {"columns": ["geometry", _col], "filters": [(_col, "==", _val)]},
            ),
        }
        if VARIANTS[_name] is None or VARIANTS[_name][1]:
            _runs[("box", "DuckDB ST_Intersects + bbox filter")] = (_box_sql + _hint, {})
        for (_query, _reader), (_sql, _kwargs) in _runs.items():
            _answer, _bytes, _requests, _unranged, _ms = measure(_con, _sql, _url, _kwargs)
            _rows.append(
                (_layer, _name, _query, _reader, _answer[0], str(_answer[1]), _bytes, _requests, _unranged, _ms)
            )
    results = pd.DataFrame(
        _rows,
        columns=["layer", "variant", "query", "reader", "rows", "answer", "bytes", "requests", "unranged GETs", "ms"],
    )
    print(f"{len(results)} query measurements")
    return (results,)


@app.cell
def _(OUT, VARIANTS, results):
    _ref = results[results["variant"] == "published"].set_index(["layer", "query", "reader"])["answer"]
    results["same answer"] = [
        a == _ref[(la, q, r)] for la, q, r, a in results[["layer", "query", "reader", "answer"]].itertuples(index=False)
    ]
    results.to_csv(OUT / "queries.csv", index=False)
    _pub = results[results["variant"] == "published"].set_index(["layer", "query", "reader"])["bytes"]
    results["bytes vs published"] = [
        b / _pub[(la, q, r)] if (la, q, r) in _pub.index and _pub[(la, q, r)] else float("nan")
        for la, q, r, b in results[["layer", "query", "reader", "bytes"]].itertuples(index=False)
    ]
    print(f"Same answer as the published file: {results['same answer'].sum()} of {len(results)} measurements")
    mb_table = (
        results.assign(MB=results["bytes"] / 1e6)
        .pivot_table(index=["query", "reader", "layer"], columns="variant", values="MB")[list(VARIANTS)]
        .round(1)
    )
    mb_table.to_csv(OUT / "mb_by_variant.csv")
    mb_table
    return (mb_table,)


@app.cell
def _(mo):
    mo.md(r"""
    ### Summed across the six layers

    Total MB fetched per query type and reader, summed over the six layers, so one big layer doesn't hide
    the rest. Per-layer numbers are in the table above and in `outputs/queries.csv`.
    """)
    return


@app.cell
def _(OUT, VARIANTS, results):
    totals = (
        results.assign(MB=results["bytes"] / 1e6)
        .pivot_table(index=["query", "reader"], columns="variant", values="MB", aggfunc="sum")[list(VARIANTS)]
        .round(1)
    )
    totals.to_csv(OUT / "mb_totals.csv")
    ms_totals = results.pivot_table(index=["query", "reader"], columns="variant", values="ms", aggfunc="sum")[
        list(VARIANTS)
    ].round(0)
    ms_totals.to_csv(OUT / "ms_totals.csv")
    print("MB fetched, summed over layers:")
    print(totals.to_string())
    print("\nMedian ms, summed over layers:")
    print(ms_totals.to_string())
    totals
    return ms_totals, totals


@app.cell
def _(mo):
    mo.md(r"""
    ### Why the row groups rarely get skipped

    A reader can skip a row group only if its bounding box misses the query box. For each file, how many row
    groups the box query's bounding box overlaps, read from the 2.0 statistics (or the `bbox` column's min/max
    statistics for 1.1 files).
    """)
    return


@app.cell
def _(OUT, pd, pq, queries, variant_paths):
    _rows = []
    for (_layer, _name), _path in variant_paths.items():
        _meta = pq.ParquetFile(_path).metadata
        _names = [_meta.schema.column(j).path for j in range(_meta.num_columns)]
        _x0, _y0, _x1, _y1 = queries[_layer]["box"]
        _hit = 0
        for _i in range(_meta.num_row_groups):
            _rg = _meta.row_group(_i)
            _geo = _rg.column(_names.index("geometry")).geo_statistics
            if _geo is not None and _geo.xmin is not None:
                _box = (_geo.xmin, _geo.ymin, _geo.xmax, _geo.ymax)
            else:
                _s = {k: _rg.column(_names.index(f"bbox.{k}")).statistics for k in ("xmin", "ymin", "xmax", "ymax")}
                _box = (_s["xmin"].min, _s["ymin"].min, _s["xmax"].max, _s["ymax"].max)
            _hit += _box[0] <= _x1 and _box[2] >= _x0 and _box[1] <= _y1 and _box[3] >= _y0
        _rows.append((_layer, _name, _hit, _meta.num_row_groups))
    row_group_hits = pd.DataFrame(_rows, columns=["layer", "variant", "row groups the box overlaps", "row groups"])
    row_group_hits.to_csv(OUT / "row_group_hits.csv", index=False)
    row_group_hits.assign(
        hits=row_group_hits["row groups the box overlaps"].astype(str)
        + " of "
        + row_group_hits["row groups"].astype(str)
    ).pivot(index="layer", columns="variant", values="hits")
    return (row_group_hits,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Which readers open the files

    Each reader opens the published 1.1 file, the `2.0` file and the `2.0+bbox` file of every layer, in its
    own environment (`uv run --with` for Python packages, the official GDAL Docker images for GDAL). A reader
    passes a file if it returns every row and recognises the geometry column as geometry (not bytes) with the
    right CRS. "Current" is the latest release; "a year old" is what someone who hasn't upgraded since late
    2025 has: DuckDB 1.3.2, GeoPandas 1.0.1 with pyarrow 19, GDAL 3.10.3.
    """)
    return


@app.cell
def _(DATA, OUT, json, pd, published, shutil, subprocess, variant_paths):
    _PROBES = {
        "duckdb": """
import duckdb, json, sys
con = duckdb.connect()
con.sql("install spatial; load spatial")
for f in sys.argv[1:]:
    try:
        n = con.sql(f"select count(*) from read_parquet('{f}')").fetchall()[0][0]
        t = con.sql(f"select typeof(geometry) from read_parquet('{f}') limit 1").fetchall()[0][0]
        geom = t.upper().startswith("GEOMETRY")
        crs = t[t.find("(") + 1 : t.rfind(")")].strip("'") if "(" in t else None
        print(json.dumps({"file": f, "rows": n, "type": t, "geometry": geom, "crs": crs}))
    except Exception as e:
        print(json.dumps({"file": f, "error": str(e).splitlines()[0][:200]}))
""",
        "geopandas": """
import geopandas, json, sys
for f in sys.argv[1:]:
    try:
        g = geopandas.read_parquet(f)
        crs = g.crs.to_authority() if g.crs is not None else None
        print(json.dumps({"file": f, "rows": len(g), "type": str(g.geometry.dtype), "geometry": True,
                          "crs": ":".join(crs) if crs else None}))
    except Exception as e:
        print(json.dumps({"file": f, "error": str(e).splitlines()[0][:200]}))
""",
        "pyarrow": """
import pyarrow.parquet as pq, json, sys
for f in sys.argv[1:]:
    try:
        t = pq.read_table(f)
        typ = t.schema.field("geometry").type
        name = getattr(typ, "extension_name", None)
        print(json.dumps({"file": f, "rows": t.num_rows, "type": name or str(typ), "geometry": name is not None,
                          "crs": None}))
    except Exception as e:
        print(json.dumps({"file": f, "error": str(e).splitlines()[0][:200]}))
""",
        "polars": """
import polars as pl, json, sys
for f in sys.argv[1:]:
    try:
        d = pl.read_parquet(f)
        print(json.dumps({"file": f, "rows": d.height, "type": str(d.schema["geometry"]), "geometry": False,
                          "crs": None}))
    except Exception as e:
        print(json.dumps({"file": f, "error": str(e).splitlines()[0][:200]}))
""",
    }
    _READERS = [
        ("DuckDB 2.0.1 + spatial", "current", "duckdb", ["duckdb==2.0.1"]),
        ("DuckDB 1.3.2 + spatial", "a year old", "duckdb", ["duckdb==1.3.2"]),
        ("GeoPandas 1.2.0 / pyarrow 26.0.1", "current", "geopandas", ["geopandas==1.2.0", "pyarrow==26.0.1"]),
        ("GeoPandas 1.0.1 / pyarrow 19.0.1", "a year old", "geopandas", ["geopandas==1.0.1", "pyarrow==19.0.1"]),
        ("pyarrow 26.0.1 (no geo library)", "current", "pyarrow", ["pyarrow==26.0.1"]),
        ("polars 2.2.0", "current", "polars", ["polars==2.2.0"]),
    ]
    _files = {(_l, _v): str(_p) for (_l, _v), _p in variant_paths.items() if _v in ("published", "2.0", "2.0+bbox")}
    _by_file = {_f: _k for _k, _f in _files.items()}
    _results = []

    def record(reader: str, age: str, out: dict) -> None:
        _layer, _variant = _by_file[out["file"]]
        _results.append({"reader": reader, "age": age, "layer": _layer, "variant": _variant, **out})

    for _label, _age, _probe, _pins in _READERS:
        _cmd = ["uv", "run", "--no-project", "--quiet"] + [a for p in _pins for a in ("--with", p)]
        _p = subprocess.run(
            _cmd + ["python", "-c", _PROBES[_probe], *_files.values()], capture_output=True, text=True, timeout=1800
        )
        assert _p.returncode == 0, f"{_label}: {_p.stderr[-500:]}"
        for _line in _p.stdout.splitlines():
            record(_label, _age, json.loads(_line))

    _docker_ok = (
        shutil.which("docker") is not None and subprocess.run(["docker", "info"], capture_output=True).returncode == 0
    )
    for _tag, _age in [("3.13.3", "current"), ("3.10.3", "a year old")]:
        for _f in _files.values():
            if not _docker_ok:
                record(f"GDAL {_tag} (ogrinfo)", _age, {"file": _f, "error": "not run: Docker is not available"})
                continue
            _inside = "/data/" + str(_f)[len(str(DATA)) + 1 :]
            _p = subprocess.run(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{DATA}:/data:ro",
                    f"ghcr.io/osgeo/gdal:ubuntu-full-{_tag}",
                    "ogrinfo",
                    "-json",
                    "-so",
                    "-al",
                    _inside,
                ],
                capture_output=True,
                text=True,
                timeout=600,
            )
            if _p.returncode != 0:
                record(
                    f"GDAL {_tag} (ogrinfo)",
                    _age,
                    {"file": _f, "error": (_p.stderr.strip().splitlines() or ["?"])[-1][:200]},
                )
                continue
            _lyr = json.loads(_p.stdout)["layers"][0]
            _gf = (_lyr.get("geometryFields") or [{}])[0]
            _cid = ((_gf.get("coordinateSystem") or {}).get("projjson") or {}).get("id") or {}
            record(
                f"GDAL {_tag} (ogrinfo)",
                _age,
                {
                    "file": _f,
                    "rows": _lyr.get("featureCount"),
                    "type": _gf.get("type", "none"),
                    "geometry": bool(_gf) and _gf.get("type") not in (None, "None", "Unknown"),
                    "crs": f"{_cid['authority']}:{_cid['code']}" if _cid else None,
                },
            )

    _validator = subprocess.run(
        [
            "uv",
            "run",
            "--no-project",
            "--quiet",
            "--with",
            "geoparquet-validator==0.4.0",
            "geoparquet-validator",
            "--version",
        ],
        capture_output=True,
        text=True,
    ).stdout.strip()
    for _f in _files.values():
        _p = subprocess.run(
            [
                "uv",
                "run",
                "--no-project",
                "--quiet",
                "--with",
                "geoparquet-validator==0.4.0",
                "geoparquet-validator",
                "check",
                _f,
            ],
            capture_output=True,
            text=True,
            timeout=600,
        )
        _verdicts = [line.strip() for line in _p.stdout.splitlines() if line.strip().startswith("=>")]
        _fails = [v for v in _verdicts if not v.endswith(": conformant")]
        record(
            f"{_validator} (spec check)",
            "current",
            {
                "file": _f,
                "rows": None,
                "type": "; ".join(_verdicts)[:300],
                "geometry": not _fails and bool(_verdicts),
                "crs": None,
                "validator": True,
            },
        )

    readers = pd.DataFrame(_results)
    _expected_rows = published["rows"]
    _expected_crs = published["crs"]

    def verdict(r: pd.Series) -> str:
        if isinstance(r.get("error"), str):
            return "fails: " + r["error"]
        if r.get("validator") is True:
            return "conformant" if r["geometry"] else "not conformant: " + r["type"]
        if r["rows"] != _expected_rows[r["layer"]]:
            return f"wrong row count {r['rows']}"
        if not r["geometry"]:
            return f"reads, geometry as {r['type']}"
        if r["crs"] not in (None, _expected_crs[r["layer"]]):
            return f"reads, CRS {r['crs']} (expected {_expected_crs[r['layer']]})"
        return "ok"

    readers["verdict"] = readers.apply(verdict, axis=1)
    readers.drop(columns=["file"]).to_csv(OUT / "readers.csv", index=False)
    return (readers,)


@app.cell
def _(OUT, pd, readers):
    def summarise(verdicts: pd.Series) -> str:
        _counts = verdicts.value_counts()
        return "; ".join(
            f"{v} ({n}/{len(verdicts)})" if len(_counts) > 1 or n != len(verdicts) else v for v, n in _counts.items()
        )

    compat = (
        readers.groupby(["reader", "age", "variant"], sort=False)["verdict"]
        .apply(summarise)
        .unstack("variant")[["published", "2.0", "2.0+bbox"]]
    )
    compat.to_csv(OUT / "reader_compatibility.csv")
    print(compat.to_string())
    compat
    return (compat,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Save the headline numbers
    """)
    return


@app.cell
def _(OUT, answers_check, json, results, sizes, totals):
    _s = sizes.groupby("variant")["MB"].sum()
    summary = {
        "layers": int(sizes["layer"].nunique()),
        "total_MB_by_variant": {k: round(float(v), 1) for k, v in _s.items()},
        "rewritten_files_identical": f"{int(answers_check['identical'].sum())} of {len(answers_check)}",
        "query_answers_same_as_published": f"{int(results['same answer'].sum())} of {len(results)}",
        "MB_fetched_summed_over_layers": {
            f"{q} | {r}": {v: float(x) for v, x in row.items() if x == x} for (q, r), row in totals.iterrows()
        },
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What didn't work

    See the README for the write-up; it is filled in from the printed tables above after the run.
    """)
    return


if __name__ == "__main__":
    app.run()

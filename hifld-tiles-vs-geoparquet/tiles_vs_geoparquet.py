import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import gzip
    import json
    import math
    import os
    import time
    from pathlib import Path

    import duckdb
    import httpx
    import mapbox_vector_tile
    import marimo as mo
    import numpy as np
    import pandas as pd
    import shapely
    from pmtiles.tile import deserialize_directory, deserialize_header, tileid_to_zxy, zxy_to_tileid

    DATA = Path(os.environ.get("DATA_DIR", "data"))
    OUT = Path(os.environ.get("OUT_DIR", "outputs"))
    DATA.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)
    API = "https://hifld.publicenvirodata.org/api/collections/hifld/datasets"
    http = httpx.Client(timeout=300, follow_redirects=True)
    return (
        API,
        DATA,
        OUT,
        deserialize_directory,
        deserialize_header,
        duckdb,
        gzip,
        http,
        json,
        mapbox_vector_tile,
        math,
        mo,
        np,
        pd,
        shapely,
        tileid_to_zxy,
        time,
        zxy_to_tileid,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Do HIFLD Next's map tiles give the same answers as its GeoParquet?

    HIFLD Next publishes every layer twice: a **GeoParquet** file for analysis and a **PMTiles**
    file for maps. Tile readers such as Query Farm's vgi-mvt now make a PMTiles file queryable as a
    table, and reading tiles fetches far fewer bytes. So an analyst or an agent may answer a
    question from the tiles. Do they get the same number?

    We ask 21 plain questions of seven layers, answer each with the same SQL over the GeoParquet
    (the answer key) and over the tiles, at three zoom levels and three ways of reading the tiles,
    and measure the error, the bytes read and the time.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. The layers

    Three point layers, one line layer and three polygon layers. `crs` is the coordinate system
    each GeoParquet file declares: two of them are stored in Web Mercator, so the answer key
    reprojects everything to longitude/latitude first. Both files of each layer are found through
    the HIFLD Next catalog API and downloaded once into `data/`.
    """)
    return


@app.cell
def _(API, DATA, http, pd):
    LAYERS = {
        "hospitals": ("hospitals-3", "point"),
        "fire": ("fire-and-emergency-medical-service-ems-stations", "point"),
        "plants": ("power-plants-1", "point"),
        "lines": ("transmission-lines-1", "line"),
        "territories": ("electric-retail-service-territories", "polygon"),
        "counties": ("us-county-boundaries-1", "polygon"),
        "states": ("us-state-boundaries-1", "polygon"),
    }
    _rows = []
    for _name, (_dataset, _shape) in LAYERS.items():
        _record = http.get(f"{API}/{_dataset}/files/{_dataset}")
        _record.raise_for_status()
        _assets = _record.json()["assets"].values()
        _urls = {
            "parquet": next(a["href"] for a in _assets if "parquet" in a["type"]),
            "pmtiles": next(a["href"] for a in _assets if a["type"] == "application/vnd.pmtiles"),
        }
        for _kind, _url in _urls.items():
            _path = DATA / f"{_dataset}.{_kind}"
            if not _path.exists():
                with http.stream("GET", _url) as _download:
                    _download.raise_for_status()
                    with open(_path, "wb") as _f:
                        for _chunk in _download.iter_bytes(1 << 20):
                            _f.write(_chunk)
        _rows.append(
            {
                "layer": _name,
                "dataset": _dataset,
                "shape": _shape,
                "parquet_url": _urls["parquet"],
                "pmtiles_url": _urls["pmtiles"],
                "parquet_mb": round((DATA / f"{_dataset}.parquet").stat().st_size / 1e6, 1),
                "pmtiles_mb": round((DATA / f"{_dataset}.pmtiles").stat().st_size / 1e6, 1),
            }
        )
    layers = pd.DataFrame(_rows).set_index("layer")
    return LAYERS, layers


@app.cell
def _(DATA, LAYERS, deserialize_header, duckdb, gzip, json, layers):
    con_key = duckdb.connect()
    con_key.execute("LOAD spatial; SET geometry_always_xy = true")
    tile_meta = {}
    for _name, (_dataset, _) in LAYERS.items():
        with open(DATA / f"{_dataset}.pmtiles", "rb") as _f:
            _header = deserialize_header(_f.read(127))
            _f.seek(_header["metadata_offset"])
            _meta = json.loads(gzip.decompress(_f.read(_header["metadata_length"])))
        tile_meta[_name] = {"header": _header, "meta": _meta}
        layers.loc[_name, "crs"] = con_key.execute(
            f"SELECT ST_CRS(geometry) FROM '{DATA / _dataset}.parquet' LIMIT 1"
        ).fetchall()[0][0]
        layers.loc[_name, "features"] = con_key.execute(
            f"SELECT count(*) FROM '{DATA / _dataset}.parquet'"
        ).fetchall()[0][0]
        layers.loc[_name, "max_zoom"] = _header["max_zoom"]
    layers[["dataset", "shape", "crs", "features", "parquet_mb", "pmtiles_mb", "max_zoom"]]
    return con_key, tile_meta


@app.cell
def _(mo, tile_meta):
    _options = tile_meta["hospitals"]["meta"]["generator_options"]
    mo.md(f"""
    The tiles were built with tippecanoe 2.49: `{_options.split(" -o ")[0]}`. With `-zg`
    tippecanoe picks the maximum zoom it thinks each layer needs, which is **low**: zoom 5 for
    power plants and 6 for hospitals, where a tile is about 1,250 km and 625 km across. A tile
    stores coordinates on a 4096 × 4096 grid, so at zoom 6 a point can move by up to about 150 m.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Do the tiles carry feature ids?

    A line or polygon that crosses tile edges is stored once per tile, plus a buffer copy in
    each neighbour. Gluing the pieces back into one feature needs an id that is the same in every
    piece. We decode every feature at each layer's top zoom and check: does it have an id, and is
    the id something stable from the source data, such as `OBJECTID`?
    """)
    return


@app.cell
def _(LAYERS, DATA, con_key, pd, read_zoom, tile_meta):
    _rows = []
    _decoder_columns = {"feature_id", "tile_x", "tile_y", "extent", "pixels"}
    for _name, (_dataset, _) in LAYERS.items():
        _pieces = read_zoom(_name, tile_meta[_name]["header"]["max_zoom"], None)["pieces"]
        _first = (
            _pieces.drop_duplicates("feature_id").sort_values("feature_id").reset_index(drop=True)
        )
        _source = con_key.execute(
            f"SELECT * EXCLUDE (geometry, bbox) FROM '{DATA / _dataset}.parquet'"
        ).df()
        _key = next((c for c in ("OBJECTID", "id") if c in _source.columns), None)
        _id_is_row = bool(
            len(_first) > 0
            and (_first.feature_id.to_numpy() < len(_source)).all()
            and _key is not None
            and (
                _source[_key].astype(str).iloc[_first.feature_id].to_numpy()
                == _first[_key].astype(str).to_numpy()
            ).mean()
            > 0.99
        )
        _rows.append(
            {
                "layer": _name,
                "pieces with an id": f"{_pieces.feature_id.notna().mean():.0%}",
                "distinct ids": _pieces.feature_id.nunique(),
                "source features": len(_source),
                "id = GeoParquet row number": _id_is_row,
                "missing at top zoom": len(_source) - _pieces.feature_id.nunique(),
                "only in GeoParquet": ", ".join(
                    sorted(set(_source.columns) - set(_pieces.columns))
                ),
                "only in tiles": ", ".join(
                    sorted(set(_pieces.columns) - set(_source.columns) - _decoder_columns)
                ),
                "id = OBJECTID or id column": bool(
                    _key is not None
                    and (_first.feature_id.astype(str) == _first[_key].astype(str)).mean() > 0.99
                ),
            }
        )
    feature_ids = pd.DataFrame(_rows).set_index("layer")
    feature_ids
    return (feature_ids,)


@app.cell
def _(feature_ids, mo):
    _stable = int(
        (
            feature_ids["id = GeoParquet row number"] | feature_ids["id = OBJECTID or id column"]
        ).sum()
    )
    mo.md(f"""
    Every piece has an id, so pieces can be glued back together inside one tileset, which is all
    the merge below needs. But on {7 - _stable} of 7 layers the id matches **neither** the
    feature's key column nor its row in the GeoParquet: it is a number from the build, not from
    the data. So an id can't be joined back to the GeoParquet, and nothing promises it stays the
    same in the next version. Making ids stable takes one tippecanoe flag,
    `--use-attribute-for-id=OBJECTID`, on layers with an integer key. The MVT spec allows only
    unsigned integer ids, so a layer keyed by a string (fire stations' `GLOBALID`) or with no key
    (power plants) needs an integer key added first.

    Two more things the table shows. The columns differ between the two files of the same
    version: the hospitals tiles call the source key `ID` where the GeoParquet calls it
    `source_ID`, and the fire station tiles lack three columns. So the tiles were not built from
    exactly this GeoParquet, and a query written for one file can fail on the other. And the
    transmission line tiles are missing some lines even at the top zoom (tippecanoe drops lines
    shorter than a grid cell; section 7 measures them).
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Reading the tiles

    We could not install vgi-mvt here (its worker is installed from GitHub, which this machine
    doesn't allow), so we read the tiles with the two libraries vgi-mvt itself is checked against:
    `pmtiles` for the archive's directory and `mapbox-vector-tile` for decoding. `read_zoom` reads
    the directory, picks the tiles at one zoom (all of them, or those under a bounding box), counts
    the bytes a range-request reader would fetch, and decodes each feature into tile-grid
    coordinates. `as_table` then turns the pieces into one table three ways, the same three vgi-mvt
    offers:

    - **raw**: every stored piece, buffer copies included. This is what a naive reader such as
      GDAL's `ST_Read` returns.
    - **clip**: each piece cut to its own tile, so buffer copies vanish. Needs no ids.
    - **merge**: clip, then glue the pieces that share a feature id. vgi-mvt's default.
    """)
    return


@app.cell
def _(
    DATA,
    LAYERS,
    deserialize_directory,
    gzip,
    mapbox_vector_tile,
    math,
    pd,
    shapely,
    tile_meta,
    tileid_to_zxy,
    time,
    zxy_to_tileid,
):
    _read_cache = {}

    def tile_range(z: int, bbox: tuple | None) -> tuple[int, int, int, int]:
        """x and y tile index ranges covering a lon/lat bounding box at zoom z."""
        n = 2**z
        if bbox is None:
            return 0, n - 1, 0, n - 1

        def tx(lon: float) -> int:
            return min(n - 1, max(0, int((lon + 180) / 360 * n)))

        def ty(lat: float) -> int:
            y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n
            return min(n - 1, max(0, int(y)))

        return tx(bbox[0]), tx(bbox[2]), ty(bbox[3]), ty(bbox[1])

    def read_zoom(layer: str, z: int, bbox: tuple | None) -> dict:
        """Decode every feature piece at zoom z under bbox; count the bytes fetched."""
        key = (layer, z, bbox)
        if key in _read_cache:
            return _read_cache[key]
        started = time.perf_counter()
        header = tile_meta[layer]["header"]
        fields = tile_meta[layer]["meta"]["vector_layers"][0]["fields"]
        x0, x1, y0, y1 = tile_range(z, bbox)
        lo, hi = zxy_to_tileid(z, 0, 0), zxy_to_tileid(z + 1, 0, 0)
        fetched = 127 + header["root_length"]
        records = []
        with open(DATA / f"{LAYERS[layer][0]}.pmtiles", "rb") as f:

            def read(offset: int, length: int) -> bytes:
                f.seek(offset)
                return f.read(length)

            root = deserialize_directory(read(header["root_offset"], header["root_length"]))
            entries, fetched_tiles = [], set()
            for i, entry in enumerate(root):  # a PMTiles directory is at most two levels deep
                if entry.run_length > 0:
                    entries.append(entry)
                    continue
                end = root[i + 1].tile_id if i + 1 < len(root) else 2**63
                if end <= lo or entry.tile_id >= hi:
                    continue
                fetched += entry.length
                leaf = read(header["leaf_directory_offset"] + entry.offset, entry.length)
                entries += deserialize_directory(leaf)
            for entry in entries:
                for tile_id in range(entry.tile_id, entry.tile_id + entry.run_length):
                    if not lo <= tile_id < hi:
                        continue
                    _, x, y = tileid_to_zxy(tile_id)
                    if not (x0 <= x <= x1 and y0 <= y <= y1):
                        continue
                    data = read(header["tile_data_offset"] + entry.offset, entry.length)
                    if entry.offset not in fetched_tiles:
                        fetched += entry.length
                        fetched_tiles.add(entry.offset)
                    decoded = mapbox_vector_tile.decode(
                        gzip.decompress(data), default_options={"y_coord_down": True}
                    )
                    for tile_layer in decoded.values():
                        extent = tile_layer["extent"]
                        for feature in tile_layer["features"]:
                            geometry = shapely.affinity.translate(
                                shapely.geometry.shape(feature["geometry"]),
                                x * extent,
                                y * extent,
                            )
                            records.append(
                                {
                                    "feature_id": feature.get("id"),
                                    "tile_x": x,
                                    "tile_y": y,
                                    "extent": extent,
                                    "pixels": geometry,
                                    **feature["properties"],
                                }
                            )
        pieces = pd.DataFrame(records)
        for column, kind in fields.items():
            if column not in pieces:
                pieces[column] = None
            if kind == "Number":
                pieces[column] = pd.to_numeric(pieces[column], errors="coerce")
            else:
                pieces[column] = pieces[column].astype("string")
        result = {"pieces": pieces, "bytes": fetched, "seconds": time.perf_counter() - started}
        _read_cache[key] = result
        return result

    return (read_zoom,)


@app.cell
def _(np, pd, shapely):
    def as_table(pieces: pd.DataFrame, z: int, mode: str) -> pd.DataFrame:
        """Turn decoded pieces into one table: raw, clipped to tiles, or merged by feature id."""
        assert mode in ("raw", "clip", "merge")
        table = pieces.copy()
        geometry = shapely.make_valid(table.pixels.to_numpy())
        if mode != "raw" and len(table):
            x, y, size = table.tile_x.to_numpy(), table.tile_y.to_numpy(), table.extent.to_numpy()
            tiles = shapely.box(x * size, y * size, (x + 1) * size, (y + 1) * size)
            geometry = shapely.make_valid(shapely.intersection(geometry, tiles, grid_size=1))
        table["pixels"] = geometry
        table = table[~shapely.is_empty(table.pixels.to_numpy())]
        if mode == "merge" and len(table):
            # Tile coordinates are integers, so union on the integer grid: GEOS's snap-rounding
            # overlay, which doesn't fail on the slivers that rounding creates.
            merged = table.groupby("feature_id").pixels.agg(
                lambda g: shapely.union_all(g.to_numpy(), grid_size=1)
            )
            table = table.drop_duplicates("feature_id").set_index("feature_id")
            table["pixels"] = merged
            table = table.reset_index()
        world = (table.extent * 2.0**z).to_numpy()

        def to_lonlat(coords: np.ndarray, size: np.ndarray) -> np.ndarray:
            lon = coords[:, 0] / size * 360 - 180
            lat = np.degrees(np.arctan(np.sinh(np.pi * (1 - 2 * coords[:, 1] / size))))
            return np.column_stack([lon, lat])

        table["wkb"] = [
            shapely.to_wkb(shapely.transform(g, lambda c, s=s: to_lonlat(c, s)))
            for g, s in zip(table.pixels, world, strict=True)
        ]
        return table.drop(columns=["pixels", "tile_x", "tile_y", "extent"])

    return (as_table,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. The questions

    Twenty-one questions an analyst or agent would ask, each one SQL statement over tables named
    `hospitals`, `fire`, `plants`, `lines`, `territories`, `counties` and `states`. Every table
    has `geom` in longitude/latitude and `geom_m` in metres (CONUS Albers, EPSG:5070) for lengths,
    areas and distances. The **same SQL** runs against both sources; only the tables differ.

    A question's `bbox` says which tiles a reader needs: none means the whole layer, a box means
    a reader fetches only the tiles under it. The 500 hospital locations in P6 are fixed points
    from the GeoParquet (`probes`), so both sources are asked about the same places.
    """)
    return


@app.cell
def _(pd):
    _houston, _marfa = (-95.3698, 29.7604), (-104.0207, 30.3094)
    _la, _denver = (-118.2437, 34.0522), (-104.9903, 39.7392)
    _columbus, _phoenix = (-82.9988, 39.9612), (-112.074, 33.4484)
    _texas, _cook = (-106.65, 25.84, -93.51, 36.5), (-88.27, 41.47, -87.52, 42.16)

    def near(point: tuple[float, float], metres: float) -> str:
        return (
            f"ST_DWithin(geom_m, ST_Transform(ST_Point({point[0]}, {point[1]}), "
            f"'OGC:CRS84', 'EPSG:5070'), {metres})"
        )

    def box(point: tuple[float, float], degrees: float) -> tuple[float, float, float, float]:
        return (point[0] - degrees, point[1] - degrees, point[0] + degrees, point[1] + degrees)

    questions = pd.DataFrame(
        [
            (
                "C1",
                "count",
                "How many hospitals are there?",
                "SELECT count(*) FROM hospitals",
                {"hospitals": None},
            ),
            (
                "C2",
                "count",
                "How many hospitals are in Texas?",
                "SELECT count(*) FROM hospitals WHERE STATE = 'TX'",
                {"hospitals": None},
            ),
            (
                "C3",
                "count",
                "How many fire and EMS stations are in Cook County, IL?",
                "SELECT count(*) FROM fire f JOIN counties c ON ST_Within(f.geom, c.geom) "
                "WHERE c.GEOID = '17031'",
                {"fire": _cook, "counties": _cook},
            ),
            (
                "C4",
                "count",
                "How many solar power plants are there?",
                "SELECT count(*) FROM plants WHERE PRIM_FUEL = 'SUN'",
                {"plants": None},
            ),
            (
                "C5",
                "count",
                "Total operating capacity of Texas power plants (MW)?",
                "SELECT sum(OPER_CAP) FROM plants WHERE STATE = 'TX' AND OPER_CAP >= 0",
                {"plants": None},
            ),
            (
                "C6",
                "count",
                "How many 345 kV transmission lines are there?",
                "SELECT count(*) FROM lines WHERE VOLTAGE = 345",
                {"lines": None},
            ),
            (
                "C7",
                "count",
                "How many counties are in Texas?",
                "SELECT count(*) FROM counties WHERE STATEFP = '48'",
                {"counties": None},
            ),
            (
                "L1",
                "length",
                "Total km of transmission line?",
                "SELECT sum(ST_Length(geom_m)) / 1000 FROM lines",
                {"lines": None},
            ),
            (
                "L2",
                "length",
                "Km of 345 kV line inside Texas?",
                "SELECT sum(ST_Length(ST_Intersection(l.geom_m, s.geom_m))) / 1000 "
                "FROM lines l JOIN states s ON ST_Intersects(l.geom_m, s.geom_m) "
                "WHERE l.VOLTAGE = 345 AND s.STUSPS = 'TX'",
                {"lines": _texas, "states": _texas},
            ),
            (
                "L3",
                "length",
                "Km of line rated 500 kV or more?",
                "SELECT sum(ST_Length(geom_m)) / 1000 FROM lines WHERE VOLTAGE >= 500",
                {"lines": None},
            ),
            (
                "A1",
                "area",
                "Which electric retail service territory is largest?",
                "SELECT NAME FROM territories ORDER BY ST_Area(geom_m) DESC LIMIT 1",
                {"territories": None},
            ),
            (
                "A2",
                "area",
                "Area of the largest service territory (km²)?",
                "SELECT max(ST_Area(geom_m)) / 1e6 FROM territories",
                {"territories": None},
            ),
            (
                "A3",
                "area",
                "Total area of Texas counties (km²)?",
                "SELECT sum(ST_Area(geom_m)) / 1e6 FROM counties WHERE STATEFP = '48'",
                {"counties": None},
            ),
            (
                "A4",
                "area",
                "Total area served by cooperatives (km²)?",
                "SELECT sum(ST_Area(geom_m)) / 1e6 FROM territories WHERE TYPE = 'COOPERATIVE'",
                {"territories": None},
            ),
            (
                "P1",
                "proximity",
                "Which hospitals are within 10 km of downtown Houston?",
                f"SELECT list_sort(list(NAME)) FROM hospitals WHERE {near(_houston, 10_000)}",
                {"hospitals": box(_houston, 0.2)},
            ),
            (
                "P2",
                "proximity",
                "Which hospital is nearest to Marfa, TX?",
                "SELECT NAME FROM hospitals ORDER BY ST_Distance(geom_m, ST_Transform("
                f"ST_Point({_marfa[0]}, {_marfa[1]}), 'OGC:CRS84', 'EPSG:5070')) LIMIT 1",
                {"hospitals": box(_marfa, 2.0)},
            ),
            (
                "P3",
                "proximity",
                "Which power plants are within 5 km of downtown Los Angeles?",
                f"SELECT list_sort(list(NAME)) FROM plants WHERE {near(_la, 5_000)}",
                {"plants": box(_la, 0.1)},
            ),
            (
                "P4",
                "proximity",
                "Which fire stations are within 5 km of downtown Denver?",
                f"SELECT list_sort(list(NAME)) FROM fire WHERE {near(_denver, 5_000)}",
                {"fire": box(_denver, 0.1)},
            ),
            (
                "P5",
                "proximity",
                "Which utility serves downtown Columbus, OH?",
                f"SELECT list_sort(list(NAME)) FROM territories WHERE ST_Contains(geom, "
                f"ST_Point({_columbus[0]}, {_columbus[1]}))",
                {"territories": box(_columbus, 0.05)},
            ),
            (
                "P6",
                "proximity",
                "Which county is each of 500 hospitals in?",
                "SELECT list_sort(list(p.ID || ':' || c.GEOID)) FROM probes p "
                "JOIN counties c ON ST_Within(p.geom, c.geom)",
                {"counties": None},
            ),
            (
                "P7",
                "proximity",
                "Which transmission lines pass within 2 km of downtown Phoenix?",
                f"SELECT count(*) FROM lines WHERE {near(_phoenix, 2_000)}",
                {"lines": box(_phoenix, 0.05)},
            ),
        ],
        columns=["id", "type", "question", "sql", "bbox"],
    )
    questions[["id", "type", "question"]]
    return (questions,)


@app.cell
def _(mo):
    mo.md(r"""
    P7 counts features rather than listing them, because "how many lines" is the question an
    agent would ask about a site. HIFLD Next has no substations layer, so the issue's "substations
    within 2 km" became power plants within 5 km.

    ## 5. The answer key

    The GeoParquet answers, with DuckDB. Each table is a view over the downloaded file, with the
    geometry reprojected from the file's own CRS. We time the query on the local file, and count
    the bytes DuckDB fetches when it reads the same file from HIFLD Next's bucket instead (its
    HTTP log, with its file cache off).
    """)
    return


@app.cell
def _(DATA, LAYERS, con_key, duckdb, layers, pd, questions, time):
    _crs = layers.crs.str.replace("EPSG:4326", "OGC:CRS84")

    def key_views(con: duckdb.DuckDBPyConnection, source: str) -> None:
        for name, (dataset, _) in LAYERS.items():
            path = layers.loc[name, "parquet_url"] if source == "remote" else DATA / dataset
            path = path if source == "remote" else f"{path}.parquet"
            geom = f"ST_Transform(geometry, '{_crs[name]}', 'OGC:CRS84', true)"
            con.execute(
                f"CREATE OR REPLACE VIEW {name} AS SELECT * EXCLUDE (geometry, bbox), "
                f"{geom} AS geom, ST_Transform(geometry, '{_crs[name]}', 'EPSG:5070', true) "
                f"AS geom_m FROM read_parquet('{path}')"
            )

    key_views(con_key, "local")
    probes = con_key.execute(
        "SELECT OBJECTID::VARCHAR AS ID, ST_AsWKB(geom) AS wkb FROM hospitals "
        "WHERE hash(OBJECTID) % 16 = 0 ORDER BY OBJECTID LIMIT 500"
    ).df()
    con_key.register("_probes", probes)
    con_key.execute(
        "CREATE OR REPLACE TABLE probes AS SELECT ID, ST_GeomFromWKB(wkb) AS geom FROM _probes"
    )

    con_remote = duckdb.connect()
    con_remote.execute(
        "LOAD spatial; SET geometry_always_xy = true; INSTALL httpfs; LOAD httpfs; "
        "SET enable_external_file_cache = false; "
        "CALL enable_logging('HTTP')"
    )
    key_views(con_remote, "remote")
    _rows = []
    for _q in questions.itertuples():
        _started = time.perf_counter()
        _answer = con_key.execute(_q.sql).fetchall()[0][0]
        _seconds = time.perf_counter() - _started
        con_remote.execute("CALL truncate_duckdb_logs()").fetchall()
        if _q.id == "P6":  # probes are fixed points, not a file
            con_remote.register("_probes", probes)
            con_remote.execute(
                "CREATE OR REPLACE TABLE probes AS "
                "SELECT ID, ST_GeomFromWKB(wkb) AS geom FROM _probes"
            ).fetchall()
        con_remote.execute(_q.sql).fetchall()
        _bytes = con_remote.execute(
            "SELECT coalesce(sum(response.headers['Content-Length']::BIGINT), 0) "
            "FROM duckdb_logs_parsed('HTTP') WHERE request.type = 'GET'"
        ).fetchall()[0][0]
        _rows.append({"id": _q.id, "key": _answer, "key_seconds": _seconds, "key_bytes": _bytes})
    answer_key = pd.DataFrame(_rows).set_index("id")
    answer_key.assign(key=answer_key.key.astype(str).str.slice(0, 60))
    return answer_key, probes


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. The same questions from the tiles

    For each question, at each layer's top zoom and two and four zooms below it, and in each of
    the three reading modes, we read the tiles the question needs into DuckDB tables with the same
    column names and run the same SQL. Bytes and seconds are those of the tile reads (directory
    plus tiles, decoding and gluing in Python) plus the query.
    """)
    return


@app.cell
def _(
    answer_key,
    as_table,
    duckdb,
    np,
    pd,
    probes,
    questions,
    read_zoom,
    tile_meta,
    time,
):
    def compare(key: float | str | list, answer: float | str | list | None) -> float:
        """Error in percent: relative for numbers, 100 for a wrong name, 1 - Jaccard for lists."""
        if isinstance(key, list):
            got = set(answer) if isinstance(answer, list) else set()
            union = set(key) | got
            return 0.0 if not union else 100 * (1 - len(set(key) & got) / len(union))
        if isinstance(key, str):
            return 0.0 if key == answer else 100.0
        number = float(answer) if isinstance(answer, int | float) else 0.0
        return 100 * (number - float(key)) / float(key)

    _con = duckdb.connect()
    _con.execute("LOAD spatial; SET geometry_always_xy = true")
    _con.register("_probes", probes)
    _con.execute(
        "CREATE TABLE probes AS SELECT ID, ST_GeomFromWKB(wkb) AS geom FROM _probes"
    ).fetchall()
    _rows, _tables = [], {}
    for _q in questions.itertuples():
        for _offset in (0, 2, 4):
            for _mode in ("raw", "clip", "merge"):
                _bytes, _seconds, _started, _zooms = 0, 0.0, time.perf_counter(), []
                for _layer, _bbox in _q.bbox.items():
                    _z = max(0, tile_meta[_layer]["header"]["max_zoom"] - _offset)
                    _read = read_zoom(_layer, _z, _bbox)  # cached: its time is added below
                    if (_layer, _z, _bbox, _mode) not in _tables:
                        _t0 = time.perf_counter()
                        _tables[_layer, _z, _bbox, _mode] = (
                            as_table(_read["pieces"], _z, _mode),
                            time.perf_counter() - _t0,
                        )
                    _table, _table_seconds = _tables[_layer, _z, _bbox, _mode]
                    _seconds += _table_seconds
                    _con.register("_pieces", _table)
                    _con.execute(
                        f"CREATE OR REPLACE TABLE {_layer} AS SELECT * EXCLUDE (wkb), "
                        "ST_GeomFromWKB(wkb) AS geom, "
                        "ST_Transform(ST_GeomFromWKB(wkb), 'OGC:CRS84', 'EPSG:5070') AS geom_m "
                        "FROM _pieces"
                    ).fetchall()
                    _con.unregister("_pieces")
                    _bytes += _read["bytes"]
                    _seconds += _read["seconds"]
                    _zooms.append(_z)
                _answer = _con.execute(_q.sql).fetchall()[0][0]
                _key = answer_key.loc[_q.id, "key"]
                _rows.append(
                    {
                        "id": _q.id,
                        "type": _q.type,
                        "zoom": f"max-{_offset}" if _offset else "max",
                        "z": "/".join(map(str, _zooms)),
                        "mode": _mode,
                        "key": _key,
                        "tiles": _answer,
                        "error_pct": compare(_key, _answer),
                        "tile_bytes": _bytes,
                        "tile_seconds": _seconds + time.perf_counter() - _started,
                        "key_bytes": answer_key.loc[_q.id, "key_bytes"],
                        "key_seconds": answer_key.loc[_q.id, "key_seconds"],
                    }
                )
    results = pd.DataFrame(_rows)
    results["within_1pct"] = results.error_pct.abs() <= 1
    results["error_pct"] = results.error_pct.round(2)
    _show = results.assign(
        key=results.key.map(lambda v: f"{len(v)} items" if isinstance(v, list) else v),
        tiles=results.tiles.map(
            lambda v: f"{len(v)} items" if isinstance(v, np.ndarray | list) else v
        ),
    )
    _show[(results.zoom == "max")][["id", "mode", "z", "key", "tiles", "error_pct"]]
    return (results,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Results

    **Questions within 1% of the GeoParquet answer**, by question type, zoom and reading mode.
    """)
    return


@app.cell
def _(results):
    within = results.pivot_table(
        index=["type"], columns=["zoom", "mode"], values="within_1pct", aggfunc="sum"
    ).astype(int)
    within.loc["all (of 21)"] = within.sum()
    within = within[["max", "max-2", "max-4"]]
    within
    return (within,)


@app.cell
def _(mo):
    mo.md(r"""
    **Range of error on totals** (the 13 questions with a numeric count, length or area answer), at
    each zoom, reading raw versus merged by feature id. Negative means the tiles under-report.
    """)
    return


@app.cell
def _(results):
    _totals = results[results.type != "proximity"]
    _totals = _totals[_totals.id != "A1"]  # A1 is a name, not a number
    total_errors = (
        _totals.groupby(["zoom", "mode"])
        .error_pct.agg(["min", "median", "max"])
        .round(1)
        .unstack("mode")
    )
    total_errors
    return (total_errors,)


@app.cell
def _(mo):
    mo.md(r"""
    **Every total, at the top zoom**, so the pattern behind the range is visible.
    """)
    return


@app.cell
def _(questions, results):
    _top = results[(results.zoom == "max") & (results.type != "proximity")]
    per_question = _top.pivot_table(
        index="id", columns="mode", values="error_pct", aggfunc="first"
    )[["raw", "clip", "merge"]]
    per_question.insert(0, "question", questions.set_index("id").question)
    per_question
    return


@app.cell
def _(DATA, LAYERS, con_key, feature_ids, mo, read_zoom, tile_meta):
    _invalid, _all = con_key.execute(
        f"SELECT count(*) FILTER (NOT ST_IsValid(geometry)), count(*) "
        f"FROM '{DATA / LAYERS['territories'][0]}.parquet'"
    ).fetchall()[0]
    _naive, _valid = con_key.execute(
        "SELECT ST_Area(geom_m) / 1e6, ST_Area(ST_MakeValid(geom_m)) / 1e6 "
        "FROM territories ORDER BY ST_Area(geom_m) DESC LIMIT 1"
    ).fetchall()[0]
    _in_tiles = read_zoom("lines", tile_meta["lines"]["header"]["max_zoom"], None)["pieces"]
    _cursor = con_key.cursor()
    _cursor.register("_in_tiles", _in_tiles[["OBJECTID"]].drop_duplicates())
    _missing = _cursor.execute(
        "SELECT quantile_cont(ST_Length(geom_m), [0, 0.5, 1]) FROM lines "
        "WHERE OBJECTID::VARCHAR NOT IN (SELECT OBJECTID FROM _in_tiles)"
    ).fetchall()[0][0]
    mo.md(f"""
    Reading the table:

    - **Raw** tiles overcount every total, by 5% to 11% for points (each point near a tile edge
      is stored again in its neighbour's buffer) and by far more for polygons: Texas has 254
      counties, and the raw tiles return a row for every piece of every county in every tile.
    - **Clip** fixes points without needing ids, but a line or polygon is still one row per tile.
    - **Merge by id** gets counts and lengths right to within 0.1%. What's left is real loss:
      the {int(feature_ids.loc["lines", "missing at top zoom"])} transmission lines missing from
      the tiles. They run {_missing[0]:.0f} m to
      {_missing[2]:.0f} m (median {_missing[1]:.0f} m), shorter than the zoom 8 grid cell, so
      lengths barely move but a count of 345 kV lines is short by two.
    - **The biggest-territory area (A2)** is off by more than anything else, and the GeoParquet
      is partly to blame: {_invalid} of its {_all} territory polygons are invalid
      (self-overlapping). DuckDB's `ST_Area` on the largest, WAPA, gives {_naive:,.0f} km²,
      but repaired with `ST_MakeValid` it is {_valid:,.0f} km². The tiles, which tippecanoe
      repaired its own way, land between the two. The answer key is only as good as its
      geometry.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    **Bytes read and query time**, top zoom, merged tiles against the GeoParquet. Proximity
    questions read a handful of tiles; totals read the whole zoom level.
    """)
    return


@app.cell
def _(results):
    _top = results[(results.zoom == "max") & (results["mode"] == "merge")].copy()
    _top["kind"] = _top.type.where(_top.type == "proximity", "total")
    cost = _top.groupby("kind").agg(
        questions=("id", "count"),
        tile_mb=("tile_bytes", lambda s: round(s.median() / 1e6, 2)),
        parquet_mb=("key_bytes", lambda s: round(s.median() / 1e6, 2)),
        tile_seconds=("tile_seconds", lambda s: round(s.median(), 2)),
        parquet_seconds=("key_seconds", lambda s: round(s.median(), 3)),
    )
    cost["parquet_mb / tile_mb"] = (cost.parquet_mb / cost.tile_mb).round(1)
    cost
    return (cost,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. Which file answers which question

    The table a reader keeps, filled in from the results above. A question type gets the tiles
    only if every question of that type was within 1% at the top zoom when merged by id **and**
    the tiles read fewer bytes than the GeoParquet for the median question of that type.
    """)
    return


@app.cell
def _(pd, results):
    _top = results[results.zoom == "max"]
    _merge = _top[_top["mode"] == "merge"].groupby("type").within_1pct.agg(["sum", "count"])
    _raw = _top[_top["mode"] == "raw"].groupby("type").within_1pct.agg(["sum", "count"])
    _low = results[(results.zoom == "max-4") & (results["mode"] == "merge")]
    _low = _low.groupby("type").within_1pct.agg(["sum", "count"])
    _bytes = _top[_top["mode"] == "merge"].groupby("type")[["tile_bytes", "key_bytes"]].median()

    def share(counts: pd.DataFrame) -> pd.Series:
        return counts["sum"].astype(str) + "/" + counts["count"].astype(str)

    guide = pd.DataFrame(
        {
            "within 1%, top zoom, merged": share(_merge),
            "within 1%, top zoom, raw": share(_raw),
            "within 1%, 4 zooms down, merged": share(_low),
            "median tile MB": (_bytes.tile_bytes / 1e6).round(2),
            "median GeoParquet MB": (_bytes.key_bytes / 1e6).round(2),
        }
    )
    guide["use"] = [
        "PMTiles, top zoom, merged by id" if s == c and t < k else "GeoParquet"
        for s, c, t, k in zip(
            _merge["sum"], _merge["count"], _bytes.tile_bytes, _bytes.key_bytes, strict=True
        )
    ]
    guide
    return (guide,)


@app.cell
def _(OUT, cost, feature_ids, guide, json, layers, results, total_errors, within):
    results.assign(key=results.key.astype(str), tiles=results.tiles.astype(str)).to_csv(
        OUT / "results.csv", index=False
    )
    within.to_csv(OUT / "within_1pct.csv")
    total_errors.to_csv(OUT / "total_errors.csv")
    cost.to_csv(OUT / "cost.csv")
    guide.to_csv(OUT / "guide.csv")
    feature_ids.to_csv(OUT / "feature_ids.csv")
    layers.to_csv(OUT / "layers.csv")
    _top = results[results.zoom == "max"]
    _totals = results[(results.type != "proximity") & (results.id != "A1")]
    summary = {
        "questions": int(results.id.nunique()),
        "layers": len(layers),
        "within_1pct_top_zoom_merge": int(_top[_top["mode"] == "merge"].within_1pct.sum()),
        "within_1pct_top_zoom_raw": int(_top[_top["mode"] == "raw"].within_1pct.sum()),
        "total_error_range_pct": {
            f"{z}/{m}": [float(g.error_pct.min()), float(g.error_pct.max())]
            for (z, m), g in _totals.groupby(["zoom", "mode"])
        },
        "tiles_carry_ids": bool((feature_ids["pieces with an id"] == "100%").all()),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    summary
    return


if __name__ == "__main__":
    app.run()

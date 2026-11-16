import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import time
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import shapely
    from rapidfuzz import fuzz

    from shared import (
        DATA,
        HERE,
        LAYERS,
        METRIC,
        OUT,
        OVERTURE,
        OVERTURE_RELEASE,
        QLEVER,
        US_BOXES,
        box_filter,
        fetch_json,
        hifld_files,
        name_score,
        normalise,
        overture_connection,
        qlever_tsv,
        read_hifld,
    )

    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    RUN_STARTED = time.perf_counter()


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Can HIFLD Next facilities be matched to OpenStreetMap and Overture, so each gets a GERS ID?

    **The question.** [HIFLD Next](https://hifld.publicenvirodata.org) preserves the federal HIFLD layers, but its
    point layers have no link to the open maps people actually use. If each HIFLD record can be matched to a
    building or place in [OpenStreetMap](https://www.openstreetmap.org) and [Overture Maps](https://overturemaps.org),
    it gets a stable [GERS ID](https://docs.overturemaps.org/gers/), and the match itself becomes a check on both
    sides. We expected three results:

    1. the match shows which HIFLD records are misplaced, duplicated or gone;
    2. it shows where OSM or Overture is missing facilities we could contribute;
    3. match rates differ sharply by layer.

    **The method.** Five HIFLD Next point layers with an obvious counterpart. For each record we look for a
    candidate of the same kind (a hospital for a hospital) in Overture places and in OSM, within 50 m and 250 m,
    and score the names. Separately, we find the Overture building the point sits in, whatever its kind. Then we
    hand-check 50 unmatched records per layer on aerial imagery.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The data

    Everything is fetched at run time into `data/` (not committed) and reused after that.

    | Source | What we use | Version |
    |---|---|---|
    | HIFLD Next | the five layers below, found through its API | release `1704edb3` |
    | Overture Maps | `places` (by category), `base/infrastructure` power plants, `buildings` | release 2026-09-23.0 |
    | OpenStreetMap | features tagged as each kind, via [QLever](https://qlever.dev) | planet of 2026-09-21 |

    The five layers, and what counts as the same kind of facility on the other side. Overture places has no power
    plant category worth the name (its nearest, `b2b_power_plants_and_power_plant_service`, is companies that
    service plants), so for power plants the Overture side is the `plant` class in `base/infrastructure`, which
    Overture takes from OSM.
    """)
    return


@app.cell
def _():
    layers = LAYERS
    layers[["slug", "version", "id_column", "overture_categories", "osm_tags"]]
    return (layers,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **HIFLD Next through its API.** The API returns each dataset as a STAC catalog; its child is a catalog of
    versions, and each version's collection lists the files. We follow those links to the GeoParquet file, so the
    URL comes from the API rather than being typed in. The code is `hifld_files()` in `shared.py`.
    """)
    return


@app.cell
def _():
    files = hifld_files()
    files[["release", "url"]]
    return (files,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    We keep the 50 states and DC. Each layer also covers some territories, which we drop so that every layer is
    compared on the same ground.
    """)
    return


@app.cell
def _(files, layers):
    _all, hifld = read_hifld(files)
    hifld_counts = pd.DataFrame(
        {"records": _all.groupby("layer").size(), "in 50 states + DC": hifld.groupby("layer").size()}
    ).loc[layers.index]
    mo.ui.table(hifld_counts, selection=None)
    return hifld, hifld_counts


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### Overture

    DuckDB reads Overture's GeoParquet straight from its public S3 bucket and keeps only row groups whose bounding
    boxes fall in the three US boxes. Places are filtered to the categories above, infrastructure to power plants.
    """)
    return


@app.cell
def _(layers):
    places_path = DATA / f"overture-places-{OVERTURE_RELEASE}.parquet"
    _categories = sorted({c for cs in layers["overture_categories"] for c in cs if not c.startswith("infrastructure")})
    _in = ", ".join(f"'{c}'" for c in _categories)
    if not places_path.exists():
        _con = overture_connection()
        _selects = [
            f"""SELECT id, names.primary AS name, basic_category, taxonomy.primary AS category, operating_status,
                       confidence, sources[1].dataset AS source, ST_X(geometry) AS lon, ST_Y(geometry) AS lat
                FROM read_parquet('{OVERTURE}/theme=places/type=place/*')
                WHERE {box_filter(box)} AND (basic_category IN ({_in}) OR taxonomy.primary IN ({_in}))"""
            for box in US_BOXES
        ]
        _con.sql(f"COPY ({' UNION ALL '.join(_selects)}) TO '{places_path}.part' (FORMAT parquet)")
        Path(f"{places_path}.part").rename(places_path)
    places = pd.read_parquet(places_path)
    places["basic_category"].value_counts().head(20)
    return (places,)


@app.cell
def _():
    plants_path = DATA / f"overture-infrastructure-plants-{OVERTURE_RELEASE}.parquet"
    if not plants_path.exists():
        _con = overture_connection()
        _selects = [
            f"""SELECT id, names.primary AS name, sources[1].record_id AS osm_record,
                       ST_X(ST_Centroid(geometry)) AS lon, ST_Y(ST_Centroid(geometry)) AS lat,
                       bbox.xmin AS xmin, bbox.ymin AS ymin, bbox.xmax AS xmax, bbox.ymax AS ymax
                FROM read_parquet('{OVERTURE}/theme=base/type=infrastructure/*')
                WHERE subtype = 'power' AND class = 'plant' AND {box_filter(box)}"""
            for box in US_BOXES
        ]
        _con.sql(f"COPY ({' UNION ALL '.join(_selects)}) TO '{plants_path}.part' (FORMAT parquet)")
        Path(f"{plants_path}.part").rename(plants_path)
    overture_plants = pd.read_parquet(plants_path)
    len(overture_plants)
    return (overture_plants,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Buildings.** Overture has 180 million buildings in the lower 48 alone: 24 GB of GeoParquet, two-thirds of it
    geometry. Reading the footprints for the whole country is too slow to repeat, so we read only each building's
    ID, bounding box, class and source, and treat the point as *in* a building when it falls inside the building's
    bounding box (or within 50 m of it). Where several boxes contain the point, the smallest wins. A bounding box is
    looser than the footprint; the notebook checks that later on a sample.

    To join 200,000 points to 180 million boxes in one pass, both sides get a 0.01° grid cell, and each point is
    copied into its own and its 8 neighbouring cells, so DuckDB can use a hash join.
    """)
    return


@app.cell
def _(hifld):
    # The lower 48 is read in eight strips of longitude, so each query fits in memory and a failed run resumes.
    _edges = np.linspace(US_BOXES[0][0], US_BOXES[0][2], 9)
    _strips = [(a, US_BOXES[0][1], b, US_BOXES[0][3]) for a, b in zip(_edges[:-1], _edges[1:], strict=True)]
    _parts = []
    _con = None
    for _i, _box in enumerate([*_strips, *US_BOXES[1:]]):
        _part = DATA / f"overture-building-candidates-{OVERTURE_RELEASE}-{_i}.parquet"
        _parts.append(_part)
        if _part.exists():
            continue
        _started = time.perf_counter()
        if _con is None:
            _con = overture_connection()
            _points = hifld[["layer", "hifld_id", "lon", "lat"]].copy()
            # 50 m in degrees at each point's latitude.
            _points["dlat"] = 50 / 110_540
            _points["dlon"] = 50 / (111_320 * np.cos(np.radians(_points["lat"])))
            _con.register("points", _points)
            _con.sql("""
                CREATE TABLE cells AS
                SELECT p.*, CAST(floor(lon / 0.01) AS INTEGER) + dx AS cx, CAST(floor(lat / 0.01) AS INTEGER) + dy AS cy
                FROM points p, (SELECT unnest([-1, 0, 1]) AS dx), (SELECT unnest([-1, 0, 1]) AS dy)
            """)
        _con.sql(f"""
            COPY (
                SELECT c.layer, c.hifld_id, b.id AS building_id, b.class AS building_class,
                       b.sources[1].dataset AS building_source, b.sources[1].record_id AS building_record,
                       b.bbox.xmin AS bxmin, b.bbox.xmax AS bxmax, b.bbox.ymin AS bymin, b.bbox.ymax AS bymax
                FROM read_parquet('{OVERTURE}/theme=buildings/type=building/*') b
                JOIN cells c
                  ON c.cx = CAST(floor((b.bbox.xmin + b.bbox.xmax) / 2 / 0.01) AS INTEGER)
                 AND c.cy = CAST(floor((b.bbox.ymin + b.bbox.ymax) / 2 / 0.01) AS INTEGER)
                WHERE {box_filter(_box)}
                  AND c.lon BETWEEN b.bbox.xmin - c.dlon AND b.bbox.xmax + c.dlon
                  AND c.lat BETWEEN b.bbox.ymin - c.dlat AND b.bbox.ymax + c.dlat
            ) TO '{_part}.part' (FORMAT parquet)""")
        Path(f"{_part}.part").rename(_part)
        print(f"buildings, box {_i + 1} of {len(_strips) + 2}: {time.perf_counter() - _started:.0f} s", flush=True)
    # A building straddling two strips can be read twice.
    building_candidates = pd.concat([pd.read_parquet(p) for p in _parts], ignore_index=True).drop_duplicates(
        ["layer", "hifld_id", "building_id"]
    )
    len(building_candidates)
    return (building_candidates,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### OpenStreetMap

    The Overpass API reset or timed out when an earlier spike pulled national OSM layers, so we use
    [QLever](https://qlever.dev), a SPARQL engine over the whole OSM planet. One query per tag returns every node,
    way and relation inside the US boundary (relation 148838) with its name, centroid and bounding box.
    """)
    return


@app.cell
def _(layers):
    osm_build = fetch_json(f"{QLEVER}?cmd=stats")["name-index"]
    _frames = [
        qlever_tsv(_key, _value, DATA / f"osm-{_key}-{_value}.tsv").assign(layer=_layer)
        for _layer, _spec in layers.iterrows()
        for _key, _value in _spec["osm_tags"]
    ]
    osm = pd.concat(_frames, ignore_index=True)
    mo.md(f"OSM source: {osm_build}")
    return osm, osm_build


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Matching

    **Candidates.** For each HIFLD record we take every same-kind Overture place and OSM feature within 2 km. Two
    distances decide a location match: 50 m (the same building or lot) and 250 m (the same campus or block). Many
    OSM features are areas (a hospital campus, a school's grounds, a power plant's fence), so for those we measure to
    the area's bounding box: a point inside the campus is 0 m away. Overture places are points.

    **Names.** We lower-case both names, expand common abbreviations (`elem`, `hosp`, `vfd`...), drop the words
    that only say what kind of facility it is (`school`, `hospital`, `fire station`...), and score what's left with
    [rapidfuzz](https://github.com/rapidfuzz/RapidFuzz)'s token-set ratio, so "Mercy Hospital" and "Mercy Medical
    Center" score high. Two names with different numbers ("Station 5", "Station 12") score 0. A score of 85 or more
    is a name match. Where the generic words are all there is, we compare the full names instead.

    **The best candidate** is the nearest name match within 2 km if there is one, otherwise the nearest candidate.
    A name match between 250 m and 2 km away is a sign that one side has the point in the wrong place.
    """)
    return


@app.cell
def _(hifld, layers, osm, overture_plants, places):
    def as_shapes(frame: pd.DataFrame) -> gpd.GeoDataFrame:
        """Points stay points; OSM areas become their bounding box, so a point inside the campus is 0 m away."""
        boxes = shapely.box(frame["xmin"], frame["ymin"], frame["xmax"], frame["ymax"])
        points = shapely.points(frame["lon"], frame["lat"])
        is_area = (frame["xmax"] > frame["xmin"]) & (frame["ymax"] > frame["ymin"])
        return gpd.GeoDataFrame(frame, geometry=np.where(is_area, boxes, points), crs=4326).to_crs(METRIC)

    _frames = []
    for _layer, _spec in layers.iterrows():
        if _layer == "Power plants":
            _ov = overture_plants.assign(
                category="plant", operating_status=None, confidence=None, source="OpenStreetMap"
            )
        else:
            _cats = _spec["overture_categories"]
            _ov = places[places["basic_category"].isin(_cats) | places["category"].isin(_cats)]
            _ov = _ov.assign(xmin=_ov["lon"], xmax=_ov["lon"], ymin=_ov["lat"], ymax=_ov["lat"])
        _frames.append(
            _ov.assign(layer=_layer, side="Overture")[
                ["layer", "side", "id", "name", "lon", "lat", "xmin", "ymin", "xmax", "ymax"]
                + ["category", "operating_status", "confidence"]
            ]
        )
    _osm = osm.rename(columns={"osm_id": "id"}).assign(
        side="OSM", category=None, operating_status=None, confidence=None
    )
    candidates = as_shapes(pd.concat([*_frames, _osm[_frames[0].columns]], ignore_index=True))
    hifld_points = hifld.to_crs(METRIC)
    candidates.groupby(["layer", "side"]).size().unstack().loc[layers.index]
    return candidates, hifld_points


@app.cell
def _(candidates, hifld_points, layers):
    _started = time.perf_counter()
    _pairs = []
    for _layer in layers.index:
        _h = hifld_points[hifld_points["layer"] == _layer]
        _c = candidates[candidates["layer"] == _layer]
        _j = gpd.sjoin(
            _h[["hifld_id", "name", "geometry"]],
            _c[["side", "id", "name", "category", "operating_status", "geometry"]],
            predicate="dwithin",
            distance=2000,
            lsuffix="h",
            rsuffix="c",
        )
        _j["distance_m"] = _j.geometry.distance(gpd.GeoSeries(_c.geometry.loc[_j["index_c"]].values, index=_j.index))
        _hn = {n: normalise(n) for n in _j["name_h"].unique()}
        _cn = {n: normalise(n) for n in _j["name_c"].fillna("").unique()}
        _j["name_score"] = [
            name_score(_hn[a], _cn[b]) for a, b in zip(_j["name_h"], _j["name_c"].fillna(""), strict=True)
        ]
        _pairs.append(pd.DataFrame(_j.drop(columns="geometry")).assign(layer=_layer))
    pairs = pd.concat(_pairs, ignore_index=True)
    pairs["name_match"] = pairs["name_score"] >= 85
    print(f"{len(pairs):,} candidate pairs within 2 km, scored in {time.perf_counter() - _started:.0f} s")
    return (pairs,)


@app.cell
def _(hifld, pairs):
    # Best candidate per record and side: nearest name match if any, else nearest (ties broken by ID).
    _ranked = pairs.sort_values(["name_match", "distance_m", "id"], ascending=[False, True, True])
    _best = _ranked.drop_duplicates(["layer", "hifld_id", "side"])
    _nearest = pairs.sort_values(["distance_m", "id"]).drop_duplicates(["layer", "hifld_id", "side"])
    matches = hifld[
        ["layer", "hifld_id", "name", "facility_type", "address", "city", "state", "status", "source_date"]
        + ["lon", "lat"]
    ].copy()
    for _side, _prefix in [("Overture", "overture"), ("OSM", "osm")]:
        _b = _best[_best["side"] == _side].set_index(["layer", "hifld_id"])
        _n = _nearest[_nearest["side"] == _side].set_index(["layer", "hifld_id"])["distance_m"]
        _key = pd.MultiIndex.from_frame(matches[["layer", "hifld_id"]])
        matches[f"{_prefix}_id"] = _b["id"].reindex(_key).values
        matches[f"{_prefix}_name"] = _b["name_c"].reindex(_key).values
        matches[f"{_prefix}_distance_m"] = _b["distance_m"].reindex(_key).values.round(1)
        matches[f"{_prefix}_name_score"] = _b["name_score"].reindex(_key).values
        matches[f"{_prefix}_name_match"] = _b["name_match"].reindex(_key).fillna(False).values.astype(bool)
        matches[f"{_prefix}_nearest_m"] = _n.reindex(_key).values
        if _side == "Overture":
            matches["overture_status"] = _b["operating_status"].reindex(_key).values
    matches.head()
    return (matches,)


@app.cell
def _(building_candidates, hifld, matches):
    # Distance from each point to each candidate building's bounding box, in metres; 0 means inside the box.
    _b = building_candidates.merge(hifld[["layer", "hifld_id", "lon", "lat"]], on=["layer", "hifld_id"])
    _kx = 111_320 * np.cos(np.radians(_b["lat"]))
    _dx = np.maximum.reduce([_b["bxmin"] - _b["lon"], np.zeros(len(_b)), _b["lon"] - _b["bxmax"]]) * _kx
    _dy = np.maximum.reduce([_b["bymin"] - _b["lat"], np.zeros(len(_b)), _b["lat"] - _b["bymax"]]) * 110_540
    _b["building_distance_m"] = np.hypot(_dx, _dy).round(1)
    _b["box_area_m2"] = (_b["bxmax"] - _b["bxmin"]) * _kx * (_b["bymax"] - _b["bymin"]) * 110_540
    _best = _b.sort_values(["building_distance_m", "box_area_m2", "building_id"]).drop_duplicates(["layer", "hifld_id"])
    _best = _best[_best["building_distance_m"] <= 50]
    # OSM-sourced buildings carry the OSM element as record_id, for example "w123456@7" (way 123456, version 7).
    _record = _best["building_record"].fillna("").str.extract(r"^([nwr])(\d+)@")
    _best["building_osm_id"] = np.where(
        _best["building_source"] == "OpenStreetMap",
        _record[0].map({"n": "node/", "w": "way/", "r": "relation/"}) + _record[1],
        None,
    )
    _keep = ["building_id", "building_distance_m", "building_class", "building_source", "building_osm_id"]
    crosswalk = matches.merge(_best[["layer", "hifld_id", *_keep]], on=["layer", "hifld_id"], how="left")
    crosswalk.groupby("layer")["building_source"].value_counts(dropna=False).unstack().fillna(0).astype(int)
    return (crosswalk,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Is a bounding box close enough?** We check on Connecticut, small enough to read its full footprints in one
    query: for every CT record matched to a building, is the point inside the actual footprint, or how far from it?
    """)
    return


@app.cell
def _(crosswalk):
    _ct_box = (-73.73, 40.98, -71.78, 42.05)
    _ct = crosswalk[(crosswalk["state"] == "CT") & crosswalk["building_id"].notna()]
    footprints_path = DATA / f"overture-ct-footprints-{OVERTURE_RELEASE}.parquet"
    if not footprints_path.exists():
        _con = overture_connection()
        _con.register("wanted", _ct[["building_id"]].drop_duplicates())
        _con.sql(f"""
            COPY (
                SELECT b.id AS building_id, ST_AsWKB(b.geometry) AS wkb
                FROM read_parquet('{OVERTURE}/theme=buildings/type=building/*') b
                JOIN wanted w ON w.building_id = b.id
                WHERE {box_filter(_ct_box)}
            ) TO '{footprints_path}.part' (FORMAT parquet)""")
        Path(f"{footprints_path}.part").rename(footprints_path)
    _fp = pd.read_parquet(footprints_path)
    _fp = gpd.GeoDataFrame(_fp[["building_id"]], geometry=gpd.GeoSeries.from_wkb(_fp["wkb"]), crs=4326).to_crs(METRIC)
    _pts = gpd.GeoDataFrame(_ct, geometry=gpd.points_from_xy(_ct["lon"], _ct["lat"]), crs=4326).to_crs(METRIC)
    _pts = _pts.merge(pd.DataFrame(_fp).rename(columns={"geometry": "footprint"}), on="building_id")
    _pts["footprint_m"] = _pts.geometry.distance(gpd.GeoSeries(_pts["footprint"], crs=METRIC))
    _inside_box = _pts["building_distance_m"] == 0
    footprint_check = pd.DataFrame(
        {
            "CT records with a building": [len(_pts)],
            "inside the box": [int(_inside_box.sum())],
            "...and inside the footprint": [int((_inside_box & (_pts["footprint_m"] == 0)).sum())],
            "...within 10 m of the footprint": [int((_inside_box & (_pts["footprint_m"] <= 10)).sum())],
            "near the box only: within 50 m of the footprint": [
                int((~_inside_box & (_pts["footprint_m"] <= 50)).sum())
            ],
            "near the box only": [int((~_inside_box).sum())],
        }
    ).T.rename(columns={0: "records"})
    footprint_check.to_csv(OUT / "footprint_check.csv")
    mo.ui.table(footprint_check.reset_index(), selection=None)
    return (footprint_check,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Results

    **Match rates.** For each layer, the share of HIFLD records with a same-kind Overture place or OSM feature
    within 50 m and 250 m, the share whose best candidate within 250 m has a matching name, and the share inside
    (or within 50 m of) an Overture building's bounding box. *Neither* means no same-kind feature on either side
    within 250 m: the HIFLD-only records.
    """)
    return


@app.cell
def _(crosswalk, layers):
    def share(mask: pd.Series) -> float:
        return round(100 * mask.mean(), 1)

    _rows = []
    for _layer in layers.index:
        _x = crosswalk[crosswalk["layer"] == _layer]
        _row = {"layer": _layer, "records": len(_x)}
        for _p, _label in [("overture", "Overture"), ("osm", "OSM")]:
            _row[f"{_label} 50 m %"] = share(_x[f"{_p}_nearest_m"] <= 50)
            _row[f"{_label} 250 m %"] = share(_x[f"{_p}_nearest_m"] <= 250)
            _row[f"{_label} name ≤250 m %"] = share(_x[f"{_p}_name_match"] & (_x[f"{_p}_distance_m"] <= 250))
        _row["either 250 m %"] = share((_x["overture_nearest_m"] <= 250) | (_x["osm_nearest_m"] <= 250))
        _row["in a building box %"] = share(_x["building_distance_m"] == 0)
        _row["building ≤50 m %"] = share(_x["building_distance_m"] <= 50)
        _row["neither (HIFLD-only)"] = int(
            ((_x["overture_nearest_m"] > 250) | _x["overture_nearest_m"].isna())
            .mul((_x["osm_nearest_m"] > 250) | _x["osm_nearest_m"].isna())
            .sum()
        )
        _rows.append(_row)
    match_rates = pd.DataFrame(_rows).set_index("layer")
    match_rates.to_csv(OUT / "match_rates.csv")
    mo.ui.table(match_rates, selection=None)
    return match_rates, share


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Signs of trouble in HIFLD.** Three things the match can flag without anyone looking at imagery:

    - **Possibly misplaced:** no same-kind feature within 250 m, but a name match 250 m–2 km away, on either side.
    - **Possibly closed:** HIFLD's own status says closed (hospitals' `CLOSED`, schools' NCES status 2 "closed",
      power plants' EIA `RE` retired or `CN` cancelled), or the matched Overture place is `permanently_closed`.
      These records are still in the layers.
    - **Possible duplicates:** two records in the same layer within 50 m of each other with matching names.
    """)
    return


@app.cell
def _(crosswalk, hifld_points, layers):
    _far = lambda x, p: (x[f"{p}_nearest_m"] > 250) | x[f"{p}_nearest_m"].isna()  # noqa: E731
    _named_far = lambda x, p: x[f"{p}_name_match"] & (x[f"{p}_distance_m"] > 250)  # noqa: E731
    crosswalk["hifld_only"] = _far(crosswalk, "overture") & _far(crosswalk, "osm")
    crosswalk["possibly_misplaced"] = crosswalk["hifld_only"] & (
        _named_far(crosswalk, "overture") | _named_far(crosswalk, "osm")
    )
    _closed_in_hifld = (
        (crosswalk["status"].str.upper() == "CLOSED")
        | ((crosswalk["layer"] == "Public schools") & (crosswalk["status"] == "2"))
        | ((crosswalk["layer"] == "Power plants") & crosswalk["status"].isin(["RE", "CN"]))
    )
    _closed_in_overture = (crosswalk["overture_status"] == "permanently_closed") & (
        crosswalk["overture_distance_m"] <= 250
    )
    crosswalk["possibly_closed"] = _closed_in_hifld | _closed_in_overture

    _dupes = []
    for _layer in layers.index:
        _h = hifld_points[hifld_points["layer"] == _layer][["hifld_id", "name", "geometry"]]
        _j = gpd.sjoin(_h, _h, predicate="dwithin", distance=50, lsuffix="a", rsuffix="b")
        _j = _j[_j["hifld_id_a"] < _j["hifld_id_b"]]
        # Full names here: two schools on one campus share a distinctive word ("White Oak") but are two records.
        _same = []
        for _a, _b in zip(map(normalise, _j["name_a"]), map(normalise, _j["name_b"]), strict=True):
            _numbers_differ = bool(_a[2] and _b[2] and not (_a[2] & _b[2]))
            _same.append(not _numbers_differ and fuzz.token_sort_ratio(_a[0], _b[0]) >= 90)
        _dupes.append(_j[_same].assign(layer=_layer)[["layer", "hifld_id_a", "name_a", "hifld_id_b", "name_b"]])
    duplicate_pairs = pd.concat(_dupes, ignore_index=True)
    duplicate_pairs.to_csv(OUT / "duplicate_pairs.csv", index=False)
    _in_pair = set(zip(duplicate_pairs["layer"], duplicate_pairs["hifld_id_a"], strict=True)) | set(
        zip(duplicate_pairs["layer"], duplicate_pairs["hifld_id_b"], strict=True)
    )
    crosswalk["possible_duplicate"] = [
        (lay, i) in _in_pair for lay, i in zip(crosswalk["layer"], crosswalk["hifld_id"], strict=True)
    ]

    trouble = crosswalk.groupby("layer")[
        ["hifld_only", "possibly_misplaced", "possibly_closed", "possible_duplicate"]
    ].sum()
    trouble = trouble.loc[layers.index]
    trouble.to_csv(OUT / "trouble_flags.csv")
    mo.ui.table(trouble, selection=None)
    return duplicate_pairs, trouble


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **The other direction: facilities OSM or Overture has and HIFLD doesn't.** A same-kind feature with no HIFLD
    record of that layer within 250 m and no HIFLD name match within 2 km. Overture places include low-confidence
    records from business listings, so we count those with Overture's confidence of 0.8 or more separately. Some of
    these are out of HIFLD's scope by definition (private schools, campus police, fire training sites), so this is a
    ceiling, not a count of what HIFLD is missing.
    """)
    return


@app.cell
def _(candidates, layers, pairs):
    _used = pairs[(pairs["distance_m"] <= 250) | pairs["name_match"]]
    _used_ids = set(zip(_used["layer"], _used["side"], _used["id"], strict=True))
    _c = candidates.copy()
    _c["has_hifld_match"] = [k in _used_ids for k in zip(_c["layer"], _c["side"], _c["id"], strict=True)]
    _rows = []
    for _layer in layers.index:
        _x = _c[_c["layer"] == _layer]
        _ov, _osm = _x[_x["side"] == "Overture"], _x[_x["side"] == "OSM"]
        _rows.append(
            {
                "layer": _layer,
                "Overture features": len(_ov),
                "Overture-only": int((~_ov["has_hifld_match"]).sum()),
                "Overture-only, confidence ≥ 0.8": int(
                    ((~_ov["has_hifld_match"]) & (_ov["confidence"].astype(float) >= 0.8)).sum()
                ),
                "OSM features": len(_osm),
                "OSM-only": int((~_osm["has_hifld_match"]).sum()),
            }
        )
    other_only = pd.DataFrame(_rows).set_index("layer")
    other_only.to_csv(OUT / "other_only.csv")
    mo.ui.table(other_only, selection=None)
    return (other_only,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Facilities we could contribute.** HIFLD records with nothing on that side within 250 m and no name match
    within 2 km. These are candidates only: OSM's
    [import guidelines](https://wiki.openstreetmap.org/wiki/Import/Guidelines) require community discussion and a
    documented plan before any bulk upload, and each needs checking on imagery first (the hand check below says how
    many survive). We propose; we don't upload.
    """)
    return


@app.cell
def _(crosswalk, layers):
    _not_in = lambda p: (  # noqa: E731
        ((crosswalk[f"{p}_nearest_m"] > 250) | crosswalk[f"{p}_nearest_m"].isna()) & ~crosswalk[f"{p}_name_match"]
    )
    crosswalk["missing_from_osm"] = _not_in("osm")
    crosswalk["missing_from_overture"] = _not_in("overture")
    contribute = crosswalk.groupby("layer")[["missing_from_osm", "missing_from_overture"]].sum().loc[layers.index]
    contribute.to_csv(OUT / "missing_from.csv")
    mo.ui.table(contribute, selection=None)
    return (contribute,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Hand check

    A seeded random sample of 50 HIFLD-only records per layer (nothing of the same kind within 250 m on either
    side). `hand_check_chips.py` draws each on Esri World Imagery at two zooms, with the same-kind Overture and OSM
    features around it, and we labelled each in `hand_check.csv`:

    - **exists, unmatched:** the facility is visibly there; OSM and Overture are missing it or have it as another kind;
    - **misplaced:** the HIFLD point is not on the facility, which is nearby (an address-geocoded point on a road,
      a ZIP centroid, or the facility a few blocks away);
    - **closed:** the site is empty, demolished, or clearly something else now;
    - **unclear:** imagery can't tell (an office inside a larger building, a rural point with nothing visible).
    - **not built** (power plants only): a planned or cancelled plant with nothing at the point.

    The labels were made by Claude subagents, one per layer, each viewing all 50 images; we spot-checked some by
    eye. For hospitals and schools, "closed" can come from HIFLD's own status where the building still stands.
    """)
    return


@app.cell
def _(candidates, crosswalk, layers):
    _sample = []
    for _i, _layer in enumerate(layers.index):
        _pool = crosswalk[(crosswalk["layer"] == _layer) & crosswalk["hifld_only"]]
        _sample.append(_pool.sample(n=min(50, len(_pool)), random_state=91 + _i))
    hand_check_sample = pd.concat(_sample, ignore_index=True)
    hand_check_sample[
        [
            "layer",
            "hifld_id",
            "name",
            "address",
            "city",
            "state",
            "status",
            "source_date",
            "lon",
            "lat",
            "overture_nearest_m",
            "osm_nearest_m",
            "overture_name",
            "osm_name",
        ]
    ].to_csv(OUT / "hand_check_sample.csv", index=False)
    candidates.to_parquet(DATA / "candidates.parquet")
    _labels_path = HERE / "hand_check.csv"
    hand_check = pd.read_csv(_labels_path, dtype={"hifld_id": str}) if _labels_path.exists() else pd.DataFrame()
    hand_check_table = (
        pd.crosstab(hand_check["layer"], hand_check["label"]).reindex(layers.index, fill_value=0)
        if len(hand_check)
        else pd.DataFrame()
    )
    mo.ui.table(hand_check_table, selection=None)
    return hand_check, hand_check_table


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Stale or misplaced HIFLD records, estimated.** The hand-checked shares of *closed*, *misplaced* and
    *not built*, applied to each layer's HIFLD-only count, with a 95% Wilson interval from the sample of 50. Records
    that do match can be misplaced too (within 250 m but on the wrong building), so this is a floor. The same
    sample gives the other side: the share that plainly *exists* but is in neither OSM nor Overture, applied to the
    same pool, is the number of real facilities we could propose adding.
    """)
    return


@app.cell
def _(hand_check_table, trouble):
    def wilson(k: int, n: int) -> tuple[float, float]:
        if n == 0:
            return (float("nan"), float("nan"))
        p, z = k / n, 1.96
        centre = (p + z**2 / (2 * n)) / (1 + z**2 / n)
        half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / (1 + z**2 / n)
        return (centre - half, centre + half)

    _rows = []
    for _layer, _labels in hand_check_table.iterrows():
        _n = int(_labels.sum())
        _bad = int(sum(_labels.get(k, 0) for k in ["closed", "misplaced", "not built"]))
        _low, _high = wilson(_bad, _n)
        _pool = int(trouble.loc[_layer, "hifld_only"])
        _rows.append(
            {
                "layer": _layer,
                "checked": _n,
                "closed, misplaced or not built": _bad,
                "HIFLD-only records": _pool,
                "estimated stale or misplaced": round(_pool * _bad / _n) if _n else None,
                "95% range": f"{round(_pool * _low):,}–{round(_pool * _high):,}" if _n else "",
                "exists, missing from both": int(_labels.get("exists, unmatched", 0)),
                "estimated real facilities to contribute": round(_pool * _labels.get("exists, unmatched", 0) / _n)
                if _n
                else None,
            }
        )
    stale_estimate = pd.DataFrame(_rows).set_index("layer") if _rows else pd.DataFrame()
    stale_estimate.to_csv(OUT / "stale_estimate.csv")
    mo.ui.table(stale_estimate, selection=None)
    return (stale_estimate,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The crosswalk

    One row per HIFLD record: its ID, the best Overture place (GERS ID), the Overture building it sits in (GERS
    ID), the best OSM feature, each with distance and name score, and a confidence:

    - **high:** a name match within 250 m on at least one side;
    - **medium:** a same-kind feature within 50 m, but no name match;
    - **low:** a same-kind feature 50–250 m away with no name match;
    - **none:** HIFLD-only.
    """)
    return


@app.cell
def _(crosswalk):
    _name_near = (crosswalk["overture_name_match"] & (crosswalk["overture_distance_m"] <= 250)) | (
        crosswalk["osm_name_match"] & (crosswalk["osm_distance_m"] <= 250)
    )
    _near = (crosswalk["overture_nearest_m"] <= 50) | (crosswalk["osm_nearest_m"] <= 50)
    crosswalk["confidence"] = np.select(
        [_name_near, _near, ~crosswalk["hifld_only"]], ["high", "medium", "low"], default="none"
    )
    _columns = [
        "layer",
        "hifld_id",
        "name",
        "facility_type",
        "state",
        "lon",
        "lat",
        "confidence",
        "overture_id",
        "overture_name",
        "overture_distance_m",
        "overture_name_score",
        "building_id",
        "building_distance_m",
        "building_source",
        "building_osm_id",
        "osm_id",
        "osm_name",
        "osm_distance_m",
        "osm_name_score",
        "possibly_misplaced",
        "possibly_closed",
        "possible_duplicate",
    ]
    _out = crosswalk[_columns].copy()
    # A best candidate beyond 250 m without a name match isn't a match; keep the ID columns for real matches only.
    for _p in ["overture", "osm"]:
        _keep = (_out[f"{_p}_distance_m"] <= 250) | (_out[f"{_p}_name_score"] >= 85)
        _out.loc[~_keep, [f"{_p}_id", f"{_p}_name", f"{_p}_distance_m", f"{_p}_name_score"]] = None
    _out.to_csv(OUT / "crosswalk.csv.gz", index=False, compression="gzip")
    # The full file is ~20 MB and stays out of git; the hospitals slice is committed as a sample.
    _out[_out["layer"] == "Hospitals"].to_csv(OUT / "crosswalk_hospitals.csv", index=False)
    confidence_table = pd.crosstab(_out["layer"], _out["confidence"])[["high", "medium", "low", "none"]]
    confidence_table.to_csv(OUT / "confidence.csv")
    mo.ui.table(confidence_table, selection=None)
    return (confidence_table,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Match by facility type.** HIFLD's `TYPE` field says what kind of facility each record is. Not every record
    in the Hospitals layer is what OSM or Overture would call a hospital: military records include base clinics,
    and psychiatric, rehabilitation and long-term care facilities are often mapped as clinics or care homes. Those
    match less often, which is a category mismatch as much as a missing feature. Fire and EMS Stations has no type.
    """)
    return


@app.cell
def _(confidence_table, crosswalk):
    assert len(confidence_table)  # runs after the cell that sets crosswalk["confidence"]
    _typed = crosswalk[crosswalk["facility_type"].astype(str) != ""]
    by_type = (
        _typed.groupby(["layer", "facility_type"])
        .agg(
            records=("hifld_id", "size"),
            high_confidence_pct=("confidence", lambda c: round(100 * (c == "high").mean(), 1)),
            hifld_only=("hifld_only", "sum"),
            hifld_only_pct=("hifld_only", lambda c: round(100 * c.mean(), 1)),
        )
        .reset_index()
        .sort_values(["layer", "records"], ascending=[True, False])
    )
    by_type.to_csv(OUT / "match_by_type.csv", index=False)
    mo.ui.table(by_type, selection=None)
    return (by_type,)


@app.cell
def _(layers, match_rates):
    _fig, _ax = plt.subplots(figsize=(9, 5))
    _y = np.arange(len(layers.index))
    for _offset, (_column, _label, _colour) in enumerate(
        [
            ("either 250 m %", "same-kind feature within 250 m (either side)", "#4c72b0"),
            ("OSM name ≤250 m %", "OSM name match within 250 m", "#55a868"),
            ("Overture name ≤250 m %", "Overture name match within 250 m", "#c44e52"),
            ("building ≤50 m %", "an Overture building within 50 m", "#8172b2"),
        ]
    ):
        _ax.barh(_y + (_offset - 1.5) * 0.2, match_rates[_column], height=0.2, label=_label, color=_colour)
    _ax.set_yticks(_y, layers.index)
    _ax.invert_yaxis()
    _ax.set_xlim(0, 100)
    _ax.set_xlabel("% of HIFLD records")
    _ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.15), ncol=2, fontsize=8, frameon=False)
    _ax.set_title("HIFLD Next records matched to Overture and OSM")
    _fig.tight_layout()
    _fig.savefig(OUT / "match_rates.png", dpi=120)
    mo.as_html(_fig)
    return


@app.cell
def _():
    run_seconds = time.perf_counter() - RUN_STARTED
    print(f"run time: {run_seconds:.0f} s")
    return (run_seconds,)


if __name__ == "__main__":
    app.run()

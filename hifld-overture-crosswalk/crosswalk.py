import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import json
    import os
    import re
    import time
    import urllib.parse
    import urllib.request
    from pathlib import Path

    import duckdb
    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from rapidfuzz import fuzz

    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("CROSSWALK_DATA_DIR", HERE / "data"))
    OUT = Path(os.environ.get("CROSSWALK_OUTPUT_DIR", HERE / "output"))
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    HIFLD_API = "https://hifld.publicenvirodata.org/api/collections/hifld/datasets"
    OVERTURE_RELEASE = "2026-09-23.0"
    OVERTURE = f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"
    QLEVER = "https://qlever.dev/api/osm-planet"
    # US National Atlas Equal Area: one metric projection for all 50 states, so distances are in metres everywhere.
    METRIC = "EPSG:9311"
    STATES = [
        *"AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY".split(),
        *"NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split(),
    ]
    # Boxes for the lower 48, Alaska (west of the antimeridian is skipped) and Hawaii.
    US_BOXES = [(-125.0, 24.4, -66.8, 49.5), (-180.0, 51.0, -129.0, 71.6), (-161.0, 18.8, -154.7, 22.4)]
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
    | HIFLD Next | Hospitals, Fire and EMS Stations, Local Law Enforcement, Public Schools, Power Plants | release `1704edb3`, found through its API |
    | Overture Maps | `places` (by category), `base/infrastructure` power plants, `buildings` | release 2026-09-23.0 |
    | OpenStreetMap | features tagged as each kind, through the [QLever](https://qlever.dev) SPARQL endpoint | the planet file it was built from (below) |

    The five layers, and what counts as the same kind of facility on the other side. Overture places has no power
    plant category worth the name (its nearest, `b2b_power_plants_and_power_plant_service`, is companies that
    service plants), so for power plants the Overture side is the `plant` class in `base/infrastructure`, which
    Overture takes from OSM.
    """)
    return


@app.cell
def _():
    layers = pd.DataFrame(
        [
            ("Hospitals", "hospitals-3", "v1.1.0", "source_ID", ["hospital", "emergency_department"], [("amenity", "hospital")]),
            (
                "Fire and EMS stations",
                "fire-and-emergency-medical-service-ems-stations",
                "v1.0.0",
                "PERMANENT_",
                ["fire_station", "ambulance_or_ems_service"],
                [("amenity", "fire_station"), ("emergency", "ambulance_station")],
            ),
            (
                "Local law enforcement",
                "local-law-enforcement-locations",
                "v1.0.0",
                "source_ID",
                ["police_station"],
                [("amenity", "police")],
            ),
            (
                "Public schools",
                "public-schools",
                "v1.0.0",
                "NCESID",
                ["elementary_school", "middle_school", "high_school", "school", "public_school", "preschool"],
                [("amenity", "school")],
            ),
            ("Power plants", "power-plants-1", "v1.0.0", "PLANT_CODE", ["infrastructure:plant"], [("power", "plant")]),
        ],
        columns=["layer", "slug", "version", "id_column", "overture_categories", "osm_tags"],
    ).set_index("layer")
    layers[["slug", "version", "id_column", "overture_categories", "osm_tags"]]
    return (layers,)


@app.cell
def _():
    def fetch_json(url: str) -> dict:
        request = urllib.request.Request(url, headers={"User-Agent": "hifld-overture-crosswalk spike"})
        with urllib.request.urlopen(request, timeout=120) as response:
            if response.status != 200:
                raise RuntimeError(f"{url} returned HTTP {response.status}")
            return json.load(response)

    def fetch(url: str, name: str) -> Path:
        """Download url into DATA/name once; later runs reuse the copy."""
        path = DATA / name
        if path.exists():
            return path
        request = urllib.request.Request(url, headers={"User-Agent": "hifld-overture-crosswalk spike"})
        with urllib.request.urlopen(request, timeout=900) as response:
            if response.status != 200:
                raise RuntimeError(f"{url} returned HTTP {response.status}")
            path.write_bytes(response.read())
        return path

    return fetch, fetch_json


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **HIFLD Next through its API.** The API returns each dataset as a STAC catalog; its child is a catalog of
    versions, and each version's collection lists the files. We follow those links to the GeoParquet file, so the
    URL comes from the API rather than being typed in.
    """)
    return


@app.cell
def _(fetch, fetch_json, layers):
    _rows = []
    for _layer, _spec in layers.iterrows():
        _dataset = fetch_json(f"{HIFLD_API}/{_spec['slug']}")
        _versions = fetch_json(next(link["href"] for link in _dataset["links"] if link["rel"] == "child"))
        _collection_url = next(
            link["href"] for link in _versions["links"] if link["rel"] == "child" and f"/{_spec['version']}/" in link["href"]
        )
        _collection = fetch_json(_collection_url)
        _url = next(a["href"] for k, a in _collection["assets"].items() if k.startswith("geoparquet"))
        _release = re.search(r"releases/([0-9a-f]{8})", _collection_url)
        _rows.append((_layer, _url, _release.group(1) if _release else "", fetch(_url, f"{_spec['slug']}.parquet")))
    hifld_files = pd.DataFrame(_rows, columns=["layer", "url", "release", "path"]).set_index("layer")
    hifld_files[["release", "url"]]
    return (hifld_files,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    We keep the 50 states and DC. Each layer also covers some territories, which we drop so that every layer is
    compared on the same ground.
    """)
    return


@app.cell
def _(hifld_files, layers):
    _frames = []
    for _layer, _spec in layers.iterrows():
        _raw = gpd.read_parquet(hifld_files.loc[_layer, "path"])
        _frame = gpd.GeoDataFrame(
            {
                "layer": _layer,
                "hifld_id": _raw[_spec["id_column"]].astype(str),
                "name": _raw["NAME"].astype(str),
                "address": _raw["ADDRESS"].astype(str),
                "city": _raw["CITY"].astype(str),
                "state": _raw["STATE"],
                "status": _raw["STATUS"].astype(str) if "STATUS" in _raw else "",
                "source_date": _raw.get("SOURCEDATE", _raw.get("SOURCE_DATE", _raw.get("LOADDATE"))).astype(str).str[:10],
            },
            geometry=_raw.geometry,
            crs=_raw.crs,
        ).to_crs(4326)
        _frames.append(_frame)
    _all = pd.concat(_frames, ignore_index=True)
    hifld = _all[_all["state"].isin(STATES)].reset_index(drop=True)
    hifld["lon"] = hifld.geometry.x
    hifld["lat"] = hifld.geometry.y
    hifld_counts = pd.DataFrame(
        {"records": _all.groupby("layer").size(), "in 50 states + DC": hifld.groupby("layer").size()}
    ).loc[layers.index]
    hifld_counts
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
def _():
    def overture_connection() -> duckdb.DuckDBPyConnection:
        con = duckdb.connect()
        con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
        # An empty key makes DuckDB read the public bucket anonymously instead of using any AWS credentials around.
        con.sql("CREATE SECRET overture (TYPE s3, KEY_ID '', SECRET '', REGION 'us-west-2')")
        # Reading S3 is bound by request latency, not CPU, so more threads than cores means more reads in flight.
        con.sql("SET threads = 32")
        return con

    def box_filter(box: tuple[float, float, float, float]) -> str:
        xmin, ymin, xmax, ymax = box
        return f"bbox.xmin > {xmin} AND bbox.xmax < {xmax} AND bbox.ymin > {ymin} AND bbox.ymax < {ymax}"

    return box_filter, overture_connection


@app.cell
def _(box_filter, layers, overture_connection):
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
    places.groupby("basic_category").size().sort_values(ascending=False).head(20)
    return (places,)


@app.cell
def _(box_filter, overture_connection):
    plants_path = DATA / f"overture-infrastructure-plants-{OVERTURE_RELEASE}.parquet"
    if not plants_path.exists():
        _con = overture_connection()
        _selects = [
            f"""SELECT id, names.primary AS name, sources[1].record_id AS osm_record,
                       ST_X(ST_Centroid(geometry)) AS lon, ST_Y(ST_Centroid(geometry)) AS lat
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
def _(box_filter, hifld, overture_connection):
    buildings_path = DATA / f"overture-building-candidates-{OVERTURE_RELEASE}.parquet"
    if not buildings_path.exists():
        _started = time.perf_counter()
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
        _selects = [
            f"""SELECT c.layer, c.hifld_id, b.id AS building_id, b.class AS building_class,
                       b.names.primary AS building_name, b.sources[1].dataset AS building_source,
                       b.sources[1].record_id AS building_record,
                       b.bbox.xmin AS bxmin, b.bbox.xmax AS bxmax, b.bbox.ymin AS bymin, b.bbox.ymax AS bymax
                FROM read_parquet('{OVERTURE}/theme=buildings/type=building/*') b
                JOIN cells c
                  ON c.cx = CAST(floor((b.bbox.xmin + b.bbox.xmax) / 2 / 0.01) AS INTEGER)
                 AND c.cy = CAST(floor((b.bbox.ymin + b.bbox.ymax) / 2 / 0.01) AS INTEGER)
                WHERE {box_filter(box)}
                  AND c.lon BETWEEN b.bbox.xmin - c.dlon AND b.bbox.xmax + c.dlon
                  AND c.lat BETWEEN b.bbox.ymin - c.dlat AND b.bbox.ymax + c.dlat"""
            for box in US_BOXES
        ]
        _con.sql(f"COPY ({' UNION ALL '.join(_selects)}) TO '{buildings_path}.part' (FORMAT parquet)")
        Path(f"{buildings_path}.part").rename(buildings_path)
        print(f"building candidates: {time.perf_counter() - _started:.0f} s")
    building_candidates = pd.read_parquet(buildings_path)
    len(building_candidates)
    return (building_candidates,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ### OpenStreetMap

    The Overpass API reset or timed out when an earlier spike pulled national OSM layers, so we use
    [QLever](https://qlever.dev), a SPARQL engine over the whole OSM planet. One query per tag returns every node,
    way and relation inside the US boundary (relation 148838) with its name and centroid.
    """)
    return


@app.cell
def _(fetch_json, layers):
    osm_build = fetch_json(f"{QLEVER}?cmd=stats")["name-index"]
    _frames = []
    for _layer, _spec in layers.iterrows():
        for _key, _value in _spec["osm_tags"]:
            _path = DATA / f"osm-{_key}-{_value}.tsv"
            if not _path.exists():
                _query = f"""
                    PREFIX osmkey: <https://www.openstreetmap.org/wiki/Key:>
                    PREFIX ogc: <http://www.opengis.net/rdf#>
                    PREFIX osmrel: <https://www.openstreetmap.org/relation/>
                    PREFIX geo: <http://www.opengis.net/ont/geosparql#>
                    PREFIX geof: <http://www.opengis.net/def/function/geosparql/>
                    SELECT ?osm ?name ?centroid WHERE {{
                      osmrel:148838 ogc:sfContains ?osm . ?osm osmkey:{_key} "{_value}" .
                      ?osm geo:hasGeometry/geo:asWKT ?wkt . BIND(geof:centroid(?wkt) AS ?centroid)
                      OPTIONAL {{ ?osm osmkey:name ?name }}
                    }}"""
                _request = urllib.request.Request(
                    QLEVER,
                    data=urllib.parse.urlencode({"query": _query}).encode(),
                    headers={"Accept": "text/tab-separated-values", "User-Agent": "hifld-overture-crosswalk spike"},
                )
                with urllib.request.urlopen(_request, timeout=900) as _response:
                    if _response.status != 200:
                        raise RuntimeError(f"QLever returned HTTP {_response.status}")
                    _path.write_bytes(_response.read())
            _tsv = pd.read_csv(_path, sep="\t", quoting=3, dtype=str)
            _xy = _tsv["?centroid"].str.extract(r"POINT\(([-\d.]+) ([-\d.]+)\)").astype(float)
            _frames.append(
                pd.DataFrame(
                    {
                        "layer": _layer,
                        "osm_id": _tsv["?osm"].str.extract(r"org/(\w+/\d+)>")[0],
                        "name": _tsv["?name"].str.strip('"').str.replace(r'"\^\^.*$', "", regex=True),
                        "lon": _xy[0],
                        "lat": _xy[1],
                    }
                )
            )
    osm = pd.concat(_frames, ignore_index=True).dropna(subset=["lon"])
    mo.md(f"OSM source: {osm_build}")
    return osm, osm_build



@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Matching

    **Candidates.** For each HIFLD record we take every same-kind Overture place and OSM feature within 2 km. Two
    distances decide a location match: 50 m (the same building or lot) and 250 m (the same campus or block).

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
def _():
    _abbreviations = {
        "elem": "elementary", "el": "elementary", "sch": "school", "schl": "school", "hs": "high school",
        "ms": "middle school", "es": "elementary school", "jr": "junior", "sr": "senior", "ctr": "center",
        "cntr": "center", "hosp": "hospital", "med": "medical", "reg": "regional", "mem": "memorial",
        "dept": "department", "pd": "police department", "fd": "fire department", "vfd": "volunteer fire department",
        "co": "county", "twp": "township", "mt": "mount", "ft": "fort", "intl": "international", "acad": "academy",
    }
    _generic = set(
        "the of and at school schools elementary middle high junior senior primary secondary academy public "
        "hospital hospitals medical center centre health healthcare clinic regional general memorial community "
        "fire station stations department dept volunteer rescue ems emergency services service company district "
        "police sheriff sheriffs office county city town township village borough state law enforcement agency "
        "power plant generating station energy solar farm wind project facility llc inc".split()
    )

    def normalise(name: str) -> tuple[str, str, frozenset[str]]:
        """Return (full normalised name, its distinctive words, the numbers in it)."""
        words = re.sub(r"[^a-z0-9 ]+", " ", str(name).lower().replace("&", " and ")).split()
        words = " ".join(_abbreviations.get(w, w) for w in words).split()
        distinctive = [w for w in words if w not in _generic and not w.isdigit()]
        return " ".join(words), " ".join(distinctive), frozenset(w for w in words if w.isdigit())

    def name_score(a: tuple[str, str, frozenset[str]], b: tuple[str, str, frozenset[str]]) -> float:
        if not a[0] or not b[0]:
            return 0.0
        if a[2] and b[2] and not (a[2] & b[2]):
            return 0.0
        if a[1] and b[1]:
            return fuzz.token_set_ratio(a[1], b[1])
        return fuzz.token_sort_ratio(a[0], b[0])

    return name_score, normalise


@app.cell
def _(hifld, layers, osm, overture_plants, places):
    def as_points(frame: pd.DataFrame) -> gpd.GeoDataFrame:
        return gpd.GeoDataFrame(frame, geometry=gpd.points_from_xy(frame["lon"], frame["lat"]), crs=4326).to_crs(METRIC)

    _frames = []
    for _layer, _spec in layers.iterrows():
        if _layer == "Power plants":
            _ov = overture_plants.assign(category="plant", operating_status=None, confidence=None, source="OpenStreetMap")
        else:
            _cats = _spec["overture_categories"]
            _ov = places[places["basic_category"].isin(_cats) | places["category"].isin(_cats)]
        _frames.append(_ov.assign(layer=_layer, side="Overture")[["layer", "side", "id", "name", "lon", "lat", "category", "operating_status", "confidence"]])
    _osm = osm.rename(columns={"osm_id": "id"}).assign(side="OSM", category=None, operating_status=None, confidence=None)
    candidates = as_points(pd.concat([*_frames, _osm[_frames[0].columns]], ignore_index=True))
    hifld_points = hifld.to_crs(METRIC)
    candidates.groupby(["layer", "side"]).size().unstack().loc[layers.index]
    return candidates, hifld_points


@app.cell
def _(candidates, hifld_points, layers, name_score, normalise):
    _started = time.perf_counter()
    _pairs = []
    for _layer in layers.index:
        _h = hifld_points[hifld_points["layer"] == _layer]
        _c = candidates[candidates["layer"] == _layer]
        _j = gpd.sjoin(_h[["hifld_id", "name", "geometry"]], _c[["side", "id", "name", "category", "operating_status", "geometry"]], predicate="dwithin", distance=2000, lsuffix="h", rsuffix="c")
        _j["distance_m"] = _j.geometry.distance(_c.geometry.loc[_j["index_c"]].values, align=False)
        _hn = {n: normalise(n) for n in _j["name_h"].unique()}
        _cn = {n: normalise(n) for n in _j["name_c"].fillna("").unique()}
        _j["name_score"] = [name_score(_hn[a], _cn[b]) for a, b in zip(_j["name_h"], _j["name_c"].fillna(""), strict=True)]
        _pairs.append(pd.DataFrame(_j.drop(columns="geometry")).assign(layer=_layer))
    pairs = pd.concat(_pairs, ignore_index=True)
    pairs["name_match"] = pairs["name_score"] >= 85
    print(f"{len(pairs):,} candidate pairs within 2 km, scored in {time.perf_counter() - _started:.0f} s")
    return (pairs,)


@app.cell
def _(hifld, pairs):
    # Best candidate per record and side: nearest name match if any, else nearest.
    _ranked = pairs.sort_values(["name_match", "distance_m"], ascending=[False, True])
    _best = _ranked.drop_duplicates(["layer", "hifld_id", "side"])
    _nearest = pairs.sort_values("distance_m").drop_duplicates(["layer", "hifld_id", "side"])
    matches = hifld[["layer", "hifld_id", "name", "address", "city", "state", "status", "source_date", "lon", "lat"]].copy()
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
    _best = _b.sort_values(["building_distance_m", "box_area_m2"]).drop_duplicates(["layer", "hifld_id"])
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
        _row["neither (HIFLD-only)"] = int(((_x["overture_nearest_m"] > 250) | _x["overture_nearest_m"].isna()).mul(
            (_x["osm_nearest_m"] > 250) | _x["osm_nearest_m"].isna()
        ).sum())
        _rows.append(_row)
    match_rates = pd.DataFrame(_rows).set_index("layer")
    match_rates.to_csv(OUT / "match_rates.csv")
    match_rates
    return match_rates, share


if __name__ == "__main__":
    app.run()

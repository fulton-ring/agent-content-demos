import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import base64
    import hashlib
    import io
    import json
    import os
    import re
    import time
    import urllib.parse
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor
    from dataclasses import dataclass
    from pathlib import Path

    import duckdb
    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import shapely
    from PIL import Image, ImageDraw
    from pydantic import BaseModel, Field
    from pyproj import Transformer
    from rapidfuzz import fuzz
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components

    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("CAMPUS_DATA_DIR", HERE / "data"))
    OUT = Path(os.environ.get("CAMPUS_OUTPUT_DIR", HERE / "output"))
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    HIFLD_API = "https://hifld.publicenvirodata.org/api/collections/hifld/datasets"
    CCD_API = "https://educationdata.urban.org/api/v1/schools/ccd/directory/2022/"
    NYC_LOCATIONS = "https://data.cityofnewyork.us/resource/wg9x-4ke6.json?$limit=5000"
    LAUSD_GIS = "https://maps.lacity.org/lahub/rest/services/LAUSD_Schools/MapServer"
    QLEVER = "https://qlever.dev/api/osm-planet"
    OVERTURE_RELEASE = "2026-10-21.0"
    OVERTURE = f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"
    USGS_IMAGERY = "https://basemap.nationalmap.gov/arcgis/rest/services/USGSImageryOnly/MapServer/export"
    CENSUS_GEOCODER = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
    DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"
    CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
    JEV_MODEL = os.environ.get("JEV_MODEL", "typesafe/jev-1.14")
    CHAT_MODEL = os.environ.get("CHAT_MODEL", "google/gemini-3.8-flash")
    METRIC = "EPSG:9311"
    # A pair is a candidate if its two points are this close, or if the two records give the same street address.
    NEAR_M = 150
    # Precision we ask of an automatic decision, in both directions (merge, keep separate).
    TARGET_PRECISION = 0.97
    # The method whose thresholds turn pairs into sites (chosen from the scoring table below).
    SITE_METHOD = "jev_geocoded"

    @dataclass(frozen=True)
    class Region:
        state_fips: int
        counties: list[str]
        osm_relation: int
        bbox: tuple[float, float, float, float]

    REGIONS = {
        "New York City": Region(
            36, ["36005", "36047", "36061", "36081", "36085"], 175905, (-74.26, 40.49, -73.69, 40.92)
        ),
        "Los Angeles County": Region(6, ["06037"], 396479, (-118.95, 33.30, -117.64, 34.83)),
    }
    RUN_STARTED = time.perf_counter()


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Which co-located school records are one physical site?

    **The question.** Public school point layers, such as HIFLD Next's *Public Schools* (taken from NCES), often
    show several points on one campus: a high school and the small academies that share its buildings, or a charter
    network whose schools share an address. Anyone who counts schools as places (sensitive sites near a pollution
    source, say) wants them merged into one site. Merge by distance alone, though, and a school across the street
    goes too. We ask:

    1. How often do these records share a site, and how wrong is a plain distance cut?
    2. Do building footprints (Overture), school grounds (OpenStreetMap) and aerial imagery decide it better?
    3. Can a decision model, [Jev](https://openrouter.ai/docs/guides/community/jev), give a probability good enough
       to merge the clear cases automatically and send only the unclear ones to a person?

    **Answer keys.** Two places publish which schools share a site: New York City's Department of Education gives
    every school a *building code*, and the Los Angeles Unified School District publishes *campus* polygons. We
    join both to the HIFLD records and score every method against them.
    """)
    return


@app.cell(hide_code=True)
def _():
    def fetch_bytes(url: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 900) -> bytes:
        """GET (or POST data) with up to four tries and a growing pause between them."""
        _headers = {"User-Agent": "school-campus-dedup spike", **(headers or {})}
        for attempt in range(4):
            try:
                with urllib.request.urlopen(
                    urllib.request.Request(url, data=data, headers=_headers), timeout=timeout
                ) as r:
                    if r.status != 200:
                        raise RuntimeError(f"{url} returned HTTP {r.status}")
                    return r.read()
            except (OSError, RuntimeError):
                if attempt == 3:
                    raise
                time.sleep(2 ** (attempt + 1))
        raise AssertionError("unreachable")

    def cached(name: str, url: str, data: bytes | None = None, headers: dict | None = None) -> Path:
        """Download once into DATA/name; later runs reuse the copy."""
        path = DATA / name
        if not path.exists():
            path.write_bytes(fetch_bytes(url, data, headers))
        return path

    def normalise_address(address: str) -> str:
        """House number and street, upper case, without punctuation, room numbers or street-type words."""
        text = re.sub(r"[.,]", " ", str(address).upper())
        text = re.split(r"\s(?:-?RM|ROOM|STE|SUITE|UNIT|BLDG|FL|FLOOR|#)\b|#|-RM", text)[0]
        words = [
            w
            for w in text.split()
            if w
            not in {
                "ST",
                "STREET",
                "AVE",
                "AVENUE",
                "BLVD",
                "BOULEVARD",
                "RD",
                "ROAD",
                "DR",
                "DRIVE",
                "PL",
                "PLACE",
                "WAY",
                "LN",
                "LANE",
            }
        ]
        return " ".join(words)

    return cached, fetch_bytes, normalise_address


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The data

    **HIFLD Next Public Schools**, found through the portal's API (dataset → STAC versions → GeoParquet). We keep
    the 50 states and DC.
    """)
    return


@app.cell
def _(cached):
    _dataset = json.loads(cached("hifld-dataset.json", f"{HIFLD_API}/public-schools").read_text())
    _versions = json.loads(
        urllib.request.urlopen(next(link["href"] for link in _dataset["links"] if link["rel"] == "child")).read()
    )
    _collection_url = [link["href"] for link in _versions["links"] if link["rel"] == "child"][-1]
    _collection = json.loads(urllib.request.urlopen(_collection_url).read())
    hifld_url = next(a["href"] for k, a in _collection["assets"].items() if k.startswith("geoparquet"))
    _release = re.search(r"releases/([0-9a-f]{8})", _collection_url)
    assert _release, f"no release ID in {_collection_url}"
    hifld_release = _release.group(1)
    _raw = gpd.read_parquet(cached("public-schools.parquet", hifld_url))
    schools = (
        _raw[~_raw["STATE"].isin(["PR", "GU", "VI", "AS", "MP", "PW", "FM", "MH"])]
        .to_crs(METRIC)
        .reset_index(drop=True)
    )
    assert schools["NCESID"].is_unique, "NCES IDs repeat: the layer has true duplicate rows"
    mo.md(
        f"HIFLD Next release `{hifld_release}`: **{len(schools):,} records**, and every NCES ID appears once. "
        "So no row is a copy of another: each is a separate school in NCES's directory. The question is only "
        "which ones share a site."
    )
    return hifld_release, schools


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## How big is the problem, nationally?

    A **candidate pair** is two records whose points are within 150 m, or that give the same street address in the
    same city (house number and street, ignoring punctuation, room numbers and words like *St* or *Ave*).
    """)
    return


@app.cell
def _(normalise_address, schools):
    def candidate_pairs(frame: gpd.GeoDataFrame) -> pd.DataFrame:
        """Index pairs (i < j) of records within NEAR_M metres or with the same normalised address and city."""
        _near = gpd.sjoin(frame[["geometry"]], frame[["geometry"]], predicate="dwithin", distance=NEAR_M)
        _near = pd.DataFrame({"i": _near.index, "j": _near["index_right"].to_numpy()})
        _key = frame["ADDRESS"].map(normalise_address) + "|" + frame["CITY"].str.upper()
        _by_key = pd.DataFrame({"key": _key, "i": frame.index})
        _same = _by_key.merge(_by_key, on="key", suffixes=("", "_b")).rename(columns={"i_b": "j"})[["i", "j"]]
        _pairs = pd.concat([_near, _same]).query("i < j").drop_duplicates().reset_index(drop=True)
        _pairs["distance_m"] = (
            frame.geometry.iloc[_pairs["i"]].distance(frame.geometry.iloc[_pairs["j"]], align=False).to_numpy()
        )
        _pairs["same_address"] = _key.iloc[_pairs["i"]].to_numpy() == _key.iloc[_pairs["j"]].to_numpy()
        return _pairs

    national_pairs = candidate_pairs(schools)
    _records = pd.unique(national_pairs[["i", "j"]].to_numpy().ravel())
    _same = national_pairs["same_address"]
    national_summary = pd.DataFrame(
        {
            "pairs": [len(national_pairs), int(_same.sum()), int((~_same).sum())],
            "records involved": [
                len(_records),
                len(pd.unique(national_pairs.loc[_same, ["i", "j"]].to_numpy().ravel())),
                len(pd.unique(national_pairs.loc[~_same, ["i", "j"]].to_numpy().ravel())),
            ],
            "same address, points >150 m apart": [
                int((_same & (national_pairs["distance_m"] > NEAR_M)).sum()),
                int((_same & (national_pairs["distance_m"] > NEAR_M)).sum()),
                0,
            ],
        },
        index=["all candidate pairs", "same address", "within 150 m, different address"],
    )
    national_summary.to_csv(OUT / "national_summary.csv")
    national_summary
    return candidate_pairs, national_pairs


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **The regions with an answer key.** For New York City and Los Angeles County we add three more sources:

    - **NCES's Common Core of Data** directory (2022–23, through the Urban Institute's
      [Education Data API](https://educationdata.urban.org/documentation/)), for each school's state ID and its
      charter flag. The state ID is what joins HIFLD to the two answer keys.
    - **OpenStreetMap school grounds**: every `amenity=school` area in the region, with its full outline, from the
      [QLever](https://qlever.dev) SPARQL endpoint.
    - **Overture buildings**: every footprint in the region's bounding box, read from Overture's public S3 bucket
      with DuckDB.
    """)
    return


@app.cell
def _(cached, fetch_bytes):
    _frames = []
    for _region, _spec in REGIONS.items():
        _path = DATA / f"ccd-2022-{_spec.state_fips}.json"
        if not _path.exists():
            _rows, _url = [], f"{CCD_API}?fips={_spec.state_fips}"
            for _page in range(10):
                _body = json.loads(fetch_bytes(_url))
                _rows += _body["results"]
                _url = _body["next"]
                if not _url:
                    break
            assert not _url, f"CCD for {_region} has more than 10 pages"
            _path.write_text(json.dumps(_rows))
        _frames.append(pd.DataFrame(json.loads(_path.read_text())))
    ccd = pd.concat(_frames, ignore_index=True)[["ncessch", "seasch", "charter", "virtual", "school_name"]]
    # New York's state school ID ends in the 12-digit BEDS code; California's is the 14-digit CDS code with dashes.
    ccd["beds"] = ccd["seasch"].str.split("-").str[-1]
    ccd["cds"] = ccd["seasch"].str.replace("-", "")

    _frames = []
    for _region, _spec in REGIONS.items():
        _query = f"""
            PREFIX osmkey: <https://www.openstreetmap.org/wiki/Key:>
            PREFIX ogc: <http://www.opengis.net/rdf#>
            PREFIX osmrel: <https://www.openstreetmap.org/relation/>
            PREFIX geo: <http://www.opengis.net/ont/geosparql#>
            SELECT ?osm ?name ?wkt WHERE {{
              osmrel:{_spec.osm_relation} ogc:sfContains ?osm . ?osm osmkey:amenity "school" .
              ?osm geo:hasGeometry/geo:asWKT ?wkt .
              FILTER(STRSTARTS(STR(?wkt), "POLYGON") || STRSTARTS(STR(?wkt), "MULTIPOLYGON"))
              OPTIONAL {{ ?osm osmkey:name ?name }}
            }}"""
        _path = cached(
            f"osm-school-areas-{_spec.osm_relation}.tsv",
            QLEVER,
            urllib.parse.urlencode({"query": _query}).encode(),
            {"Accept": "text/tab-separated-values"},
        )
        _tsv = pd.read_csv(_path, sep="\t", quoting=3, dtype=str)
        _frames.append(
            gpd.GeoDataFrame(
                {
                    "region": _region,
                    "osm_id": _tsv["?osm"].str.extract(r"org/(\w+/\d+)>")[0],
                    "osm_name": _tsv["?name"].str.strip('"').str.replace(r'"\^\^.*$', "", regex=True),
                },
                geometry=shapely.from_wkt(_tsv["?wkt"].str.strip('"').str.replace(r'"\^\^.*$', "", regex=True)),
                crs="EPSG:4326",
            )
        )
    osm_areas = pd.concat(_frames, ignore_index=True).to_crs(METRIC)
    osm_build = json.loads(fetch_bytes(f"{QLEVER}?cmd=stats"))["name-index"]
    mo.md(f"CCD: {len(ccd):,} schools in the two states. OSM school areas: {len(osm_areas):,} (QLever `{osm_build}`).")
    return ccd, osm_areas, osm_build


@app.cell
def _():
    _con = duckdb.connect()
    _con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
    # An empty key makes DuckDB read the public bucket anonymously.
    _con.sql("CREATE SECRET overture (TYPE s3, KEY_ID '', SECRET '', REGION 'us-west-2')")
    _con.sql("SET threads = 10")
    _con.sql("SET memory_limit = '4GB'")
    building_files = {}
    for _region, _spec in REGIONS.items():
        _path = DATA / f"overture-buildings-{OVERTURE_RELEASE}-{_spec.osm_relation}.parquet"
        if not _path.exists():
            _x0, _y0, _x1, _y1 = _spec.bbox
            _con.sql(f"""
                COPY (SELECT id, ST_AsWKB(geometry) AS wkb, height, num_floors
                      FROM read_parquet('{OVERTURE}/theme=buildings/type=building/*')
                      WHERE bbox.xmin > {_x0} AND bbox.xmax < {_x1} AND bbox.ymin > {_y0} AND bbox.ymax < {_y1})
                TO '{_path}.part' (FORMAT parquet)""")
            Path(f"{_path}.part").rename(_path)
        building_files[_region] = _path
    building_files
    return (building_files,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Answer key 1, New York City.** The DOE's [2019–20 School Locations](https://data.cityofnewyork.us/d/wg9x-4ke6)
    list each school's BEDS code and `primary_building_code`. Two schools with the same building code share a
    building. The file is four years older than HIFLD's source, so we drop schools whose house number differs
    between the two (they may have moved).

    **Answer key 2, Los Angeles Unified.** The district's GIS publishes
    [school points](https://maps.lacity.org/lahub/rest/services/LAUSD_Schools/MapServer/0) with CDS codes and
    [campus polygons](https://maps.lacity.org/lahub/rest/services/LAUSD_Schools/MapServer/2). A school belongs to
    each campus that contains one of its own points. Two schools share a site if they share a campus. Schools with no
    point on any campus (mostly charters in private buildings) have no answer, so their pairs are left out.
    """)
    return


@app.cell
def _(cached, ccd, normalise_address, schools):
    _nyc = pd.read_json(cached("nyc-school-locations-2019-20.json", NYC_LOCATIONS), dtype=str)
    _nyc = _nyc.merge(ccd[["ncessch", "beds"]], on="beds").merge(
        schools[["NCESID", "ADDRESS"]], left_on="ncessch", right_on="NCESID"
    )
    _house = _nyc["ADDRESS"].map(normalise_address).str.split().str[0]
    _nyc_house = _nyc["primary_address_line_1"].str.split().str[0]
    nyc_key = _nyc.loc[_house == _nyc_house].drop_duplicates("NCESID").set_index("NCESID")["primary_building_code"]

    def arcgis_layer(layer: int) -> gpd.GeoDataFrame:
        """Every feature of one LAUSD map-service layer, 1,000 at a time."""
        _parts = []
        for _page in range(20):
            _url = (
                f"{LAUSD_GIS}/{layer}/query?where=1%3D1&outFields=*&outSR=4326&f=geojson"
                f"&resultOffset={_page * 1000}&resultRecordCount=1000"
            )
            _part = gpd.read_file(cached(f"lausd-{layer}-{_page}.geojson", _url))
            if _part.empty:
                return pd.concat(_parts, ignore_index=True).to_crs(METRIC)
            _parts.append(_part)
        raise AssertionError("LAUSD layer has more than 20,000 features")

    _points = arcgis_layer(0)[["CDSCODE", "geometry"]]
    _campuses = arcgis_layer(2)[["ID", "LABEL", "geometry"]]
    _placed = gpd.sjoin(_points, _campuses, how="left", predicate="within")
    # A point on no campus is a site of its own (a charter in its own building, say), named after its school.
    _placed["site"] = (
        _placed["ID"].map(lambda i: f"campus {int(i)}", na_action="ignore").fillna("own " + _placed["CDSCODE"])
    )
    _placed["NCESID"] = _placed["CDSCODE"].map(ccd.set_index("cds")["ncessch"])
    la_key = _placed.dropna(subset=["NCESID"]).groupby("NCESID")["site"].agg(frozenset)
    mo.md(
        f"NYC key: {len(nyc_key):,} HIFLD schools with a building code. "
        f"LAUSD key: {len(la_key):,} HIFLD schools placed on one of {len(_campuses):,} campuses."
    )
    return la_key, nyc_key


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The evidence for each pair

    For every candidate pair in the two regions we collect what a person checking it would look at: both records'
    names, addresses, phones, grades and enrollment; the distance; whether the two points sit in the same Overture
    building footprint (inside it, or within 10 m of it); and whether they sit in the same OSM school grounds.
    """)
    return


@app.cell
def _(building_files, cached, candidate_pairs, ccd, la_key, normalise_address, nyc_key, osm_areas, schools):
    def nearest_within(points: gpd.GeoDataFrame, shapes: gpd.GeoDataFrame, column: str) -> pd.Series:
        """For each point, `column` of the shape containing it or, failing that, the nearest within 10 m."""
        _hit = gpd.sjoin_nearest(points[["geometry"]], shapes[[column, "geometry"]], max_distance=10, distance_col="d")
        return pd.Series(_hit.sort_values("d").groupby(level=0)[column].first().reindex(points.index))

    def census_geocode(frame: pd.DataFrame, name: str) -> gpd.GeoSeries:
        """Each record's reported address geocoded by the Census Bureau, independently of its HIFLD point."""
        assert len(frame) <= 10_000, "the Census batch geocoder takes at most 10,000 addresses"
        _csv = frame[["NCESID", "ADDRESS", "CITY", "STATE", "ZIP"]].to_csv(index=False, header=False)
        _boundary = "----school-campus-dedup"
        _body = (
            f'--{_boundary}\r\nContent-Disposition: form-data; name="benchmark"\r\n\r\nPublic_AR_Current\r\n'
            f'--{_boundary}\r\nContent-Disposition: form-data; name="addressFile"; filename="a.csv"\r\n'
            f"Content-Type: text/csv\r\n\r\n{_csv}\r\n--{_boundary}--\r\n"
        ).encode()
        _path = cached(
            f"census-geocode-{name}.csv",
            CENSUS_GEOCODER,
            _body,
            {"Content-Type": f"multipart/form-data; boundary={_boundary}"},
        )
        _out = pd.read_csv(_path, header=None, dtype=str, usecols=[0, 2, 5], names=["NCESID", "match", "lonlat"])
        _xy = _out.set_index("NCESID")["lonlat"].str.split(",", expand=True).astype(float)
        _xy = _xy.reindex(frame["NCESID"])
        return gpd.GeoSeries(gpd.points_from_xy(_xy[0], _xy[1]), crs="EPSG:4326").to_crs(METRIC)

    _charter = ccd.set_index("ncessch")["charter"]
    _frames = []
    for _region, _spec in REGIONS.items():
        _local = schools[schools["COUNTYFIPS"].isin(_spec.counties)].reset_index(drop=True)
        _buildings = pd.read_parquet(building_files[_region])
        _buildings = gpd.GeoDataFrame(
            _buildings[["id"]], geometry=shapely.from_wkb(_buildings["wkb"]), crs="EPSG:4326"
        ).to_crs(METRIC)
        _buildings = _buildings.iloc[
            gpd.sjoin(
                _buildings, _local[["geometry"]].set_geometry(_local.buffer(200)), predicate="intersects"
            ).index.unique()
        ]
        _local["building"] = nearest_within(_local, _buildings, "id")
        _local["building_area_m2"] = _local["building"].map(_buildings.set_index("id").area).round()
        _areas = osm_areas[osm_areas["region"] == _region]
        _local["osm_area"] = nearest_within(_local, _areas, "osm_id")
        _local["osm_area_name"] = _local["osm_area"].map(_areas.set_index("osm_id")["osm_name"])
        _local["charter"] = _local["NCESID"].map(_charter)
        _geocoded = census_geocode(_local, str(_spec.osm_relation))
        _pairs = candidate_pairs(_local)
        _a, _b = _local.iloc[_pairs["i"]].reset_index(drop=True), _local.iloc[_pairs["j"]].reset_index(drop=True)
        _pairs["region"] = _region
        _pairs["geocoded_distance_m"] = (
            _geocoded.iloc[_pairs["i"]].distance(_geocoded.iloc[_pairs["j"]], align=False).round().to_numpy()
        )
        for _side, _rows in (("a", _a), ("b", _b)):
            for _column in [
                "NCESID",
                "NAME",
                "ADDRESS",
                "CITY",
                "TELEPHONE",
                "LEVEL_",
                "ST_GRADE",
                "END_GRADE",
                "ENROLLMENT",
                "DISTRICTID",
                "charter",
                "building",
                "building_area_m2",
                "osm_area_name",
            ]:
                _pairs[f"{_side}_{_column.lower()}"] = _rows[_column].to_numpy()
            _lonlat = _rows.geometry.to_crs("EPSG:4326")
            _pairs[f"{_side}_lon"], _pairs[f"{_side}_lat"] = _lonlat.x.to_numpy(), _lonlat.y.to_numpy()
        _pairs["same_building"] = _a["building"].notna().to_numpy() & (
            _a["building"].to_numpy() == _b["building"].to_numpy()
        )
        _pairs["same_osm_grounds"] = _a["osm_area"].notna().to_numpy() & (
            _a["osm_area"].to_numpy() == _b["osm_area"].to_numpy()
        )
        _pairs["same_phone"] = (_a["TELEPHONE"].to_numpy() == _b["TELEPHONE"].to_numpy()) & (
            _a["TELEPHONE"] != "NOT AVAILABLE"
        ).to_numpy()
        _pairs["name_similarity"] = [fuzz.token_set_ratio(x, y) for x, y in zip(_a["NAME"], _b["NAME"], strict=True)]
        _pairs["same_district"] = _a["DISTRICTID"].to_numpy() == _b["DISTRICTID"].to_numpy()
        if _region == "New York City":
            _ka, _kb = _a["NCESID"].map(nyc_key), _b["NCESID"].map(nyc_key)
            _pairs["truth"] = np.where(_ka.notna() & _kb.notna(), _ka == _kb, np.nan)
        else:
            _ka, _kb = (_rec["NCESID"].map(lambda n: la_key.get(n, frozenset())) for _rec in (_a, _b))
            # Two schools that are both off campus could still share a private building, so they get no answer.
            _pairs["truth"] = [
                float(bool(x & y)) if x and y and any(s.startswith("campus") for s in x | y) else np.nan
                for x, y in zip(_ka, _kb, strict=True)
            ]
        _frames.append(_pairs.drop(columns=["i", "j"]))
    pairs = pd.concat(_frames, ignore_index=True)
    pairs["pair_id"] = pairs["a_ncesid"] + "-" + pairs["b_ncesid"]
    # S2 cells, as used to match features between versions of a layer: the deepest level (10-24, about 10 km down to
    # 0.6 m) at which both points fall in the same cell. Cells nest, so counting the shared levels gives the deepest.
    _con = duckdb.connect()
    _con.sql("INSTALL geography FROM community; LOAD geography;")
    _shared = " + ".join(f"(s2_cell_parent(ca, {_l}) = s2_cell_parent(cb, {_l}))::INT" for _l in range(10, 25))
    _con.register("pair_points", pairs[["a_lon", "a_lat", "b_lon", "b_lat"]].reset_index(names="row"))
    pairs["s2_shared_level"] = (
        _con.sql(f"""
        SELECT 9 + {_shared} AS level FROM (
            SELECT row, s2_cellfromlonlat(a_lon, a_lat) AS ca, s2_cellfromlonlat(b_lon, b_lat) AS cb FROM pair_points)
        ORDER BY row
    """)
        .df()["level"]
        .to_numpy()
    )
    # Half of each key picks thresholds, the other half tests them. The split is a hash, so it is stable across runs.
    pairs["half"] = np.where(
        pairs["pair_id"].map(lambda s: int(hashlib.sha256(s.encode()).hexdigest(), 16) % 2), "test", "tune"
    )
    pairs.groupby("region").agg(
        pairs=("pair_id", "size"),
        with_answer=("truth", lambda s: int(s.notna().sum())),
        same_site=("truth", lambda s: int((s == 1).sum())),
        same_address=("same_address", "sum"),
        same_building=("same_building", "sum"),
        same_osm_grounds=("same_osm_grounds", "sum"),
    )
    return (pairs,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## How often does distance get it right?

    The simplest fix is to merge every pair closer than some distance. Here is the share of pairs that the answer
    keys say really share a site, by distance band.
    """)
    return


@app.cell
def _(pairs):
    _known = pairs.dropna(subset=["truth"])
    by_distance = (
        _known.groupby(["region", pd.cut(_known["distance_m"], [-1, 1, 10, 25, 50, 100, 150, 1e6])], observed=True)[
            "truth"
        ]
        .agg(pairs="size", share_same_site="mean")
        .round(2)
        .unstack(0)
    )
    by_distance.to_csv(OUT / "same_site_by_distance.csv")
    by_distance
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Asking Jev

    [Jev](https://openrouter.ai/docs/guides/community/jev) is a *decision model*: it takes a state and a typed
    question and returns a probability, not text. We ask one yes/no ("Noul") question per pair, through OpenRouter's
    Decisions API, in two forms:

    - **text**: the two records and the geometry facts above, as JSON;
    - **text + image**: the same, plus a USGS aerial image of the pair (public domain, from The National Map) with
      point A marked in red and B in blue.

    For comparison we put the same text and image to a cheap chat model and ask it to state a probability. Every
    answer is checked against a schema and cached in `data/answers/`, so a rerun costs nothing.
    """)
    return


@app.cell
def _(fetch_bytes):
    class JevNoul(BaseModel):
        type: str
        noul: float = Field(ge=0, le=1)

    class JevResponse(BaseModel):
        answers: dict[str, JevNoul]
        usage: dict

    class ChatVerdict(BaseModel):
        same_site_probability: float = Field(ge=0, le=1)

    QUESTION = (
        "Do record_a and record_b describe schools at the same physical site, so that a map of school facilities "
        "should show them as one place?"
    )
    CRITERIA = {
        "true": "They share a building or a campus: co-located schools, academies or programs inside a larger "
        "school, or one school listed twice.",
        "false": "They are at separate sites, even if they are close together, belong to the same organization, or "
        "share a phone number or mailing address.",
    }
    # The fourth variant also sees where the Census Bureau geocodes each reported address, and is told why.
    GEOCODED_NOTE = (
        " The map points come from the source layer and are sometimes misplaced by hundreds of metres. The reported "
        "street addresses, and the distance between their independent Census Bureau geocodes, are more reliable."
    )
    to_mercator = Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)

    def pair_state(row: pd.Series, geocoded: bool) -> dict:
        """What a person would look at: both records and the geometry facts (and the address geocodes if asked)."""

        def record(side: str) -> dict:
            return {
                "name": row[f"{side}_name"],
                "address": f"{row[f'{side}_address']}, {row[f'{side}_city']}",
                "phone": row[f"{side}_telephone"],
                "grades": f"{row[f'{side}_st_grade']}-{row[f'{side}_end_grade']}",
                "level": row[f"{side}_level_"],
                "enrollment": int(row[f"{side}_enrollment"]),
                "charter": bool(row[f"{side}_charter"] == 1),
                "district_id": row[f"{side}_districtid"],
                "school_grounds_in_openstreetmap": row[f"{side}_osm_area_name"]
                if isinstance(row[f"{side}_osm_area_name"], str)
                else None,
                "building_footprint_m2": None
                if pd.isna(row[f"{side}_building_area_m2"])
                else int(row[f"{side}_building_area_m2"]),
            }

        _state = {
            "record_a": record("a"),
            "record_b": record("b"),
            "distance_between_points_m": round(float(row["distance_m"])),
            "same_street_address": bool(row["same_address"]),
            "same_building_footprint": bool(row["same_building"]),
            "same_openstreetmap_school_grounds": bool(row["same_osm_grounds"]),
        }
        if geocoded:
            _d = row["geocoded_distance_m"]
            _state["distance_between_geocoded_addresses_m"] = None if pd.isna(_d) else int(_d)
        return _state

    def aerial_chip(row: pd.Series) -> str:
        """A base64 JPEG of the pair on USGS imagery, A in red and B in blue, cached on disk."""
        _path = DATA / "chips" / f"{row['pair_id']}.jpg"
        if not _path.exists():
            _path.parent.mkdir(exist_ok=True)
            _ax, _ay = to_mercator.transform(row["a_lon"], row["a_lat"])
            _bx, _by = to_mercator.transform(row["b_lon"], row["b_lat"])
            _cx, _cy = (_ax + _bx) / 2, (_ay + _by) / 2
            _half = max(150.0, 0.75 * max(abs(_ax - _bx), abs(_ay - _by)) + 80)
            _size = 768
            _url = (
                f"{USGS_IMAGERY}?bbox={_cx - _half},{_cy - _half},{_cx + _half},{_cy + _half}&bboxSR=3857"
                f"&imageSR=3857&size={_size},{_size}&format=jpg&f=image"
            )
            _image = Image.open(io.BytesIO(fetch_bytes(_url))).convert("RGB")
            _draw = ImageDraw.Draw(_image)
            for (_x, _y), _colour in (((_ax, _ay), "red"), ((_bx, _by), "blue")):
                _px, _py = (_x - _cx + _half) / (2 * _half) * _size, (_cy + _half - _y) / (2 * _half) * _size
                _draw.ellipse([_px - 9, _py - 9, _px + 9, _py + 9], outline=_colour, width=4)
            _image.save(_path, quality=85)
        return base64.b64encode(_path.read_bytes()).decode()

    def ask(method: str, row: pd.Series) -> dict:
        """One model answer for one pair: {'p': probability, 'cost': USD}, from the cache when it is there."""
        _path = DATA / "answers" / method / f"{row['pair_id']}.json"
        if _path.exists():
            return json.loads(_path.read_text())
        _state = pair_state(row, geocoded=method == "jev_geocoded")
        _headers = {"Authorization": f"Bearer {os.environ['OPENROUTER_API_KEY']}", "Content-Type": "application/json"}
        if method.startswith("jev"):
            if method == "jev_text_image":
                _state["aerial_image_red_marker_is_a_blue_marker_is_b"] = {
                    "type": "image_url",
                    "image_url": {"url": f"data:image/jpeg;base64,{aerial_chip(row)}"},
                }
            _question = QUESTION + (GEOCODED_NOTE if method == "jev_geocoded" else "")
            _body = {
                "model": JEV_MODEL,
                "state": _state,
                "questions": {"same_site": {"type": "noul", "instructions": _question, "criteria": CRITERIA}},
            }
            _reply = JevResponse.model_validate_json(
                fetch_bytes(DECISIONS_URL, json.dumps(_body).encode(), _headers, 120)
            )
            _answer = {"p": _reply.answers["same_site"].noul, "cost": float(_reply.usage.get("cost", 0))}
        else:
            _prompt = (
                f"{QUESTION}\nYes means: {CRITERIA['true']}\nNo means: {CRITERIA['false']}\n"
                f"The aerial image shows record_a as a red circle and record_b as a blue circle.\n"
                f'{json.dumps(_state)}\nReply with JSON: {{"same_site_probability": <0 to 1>}}'
            )
            _image = {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{aerial_chip(row)}"}}
            _body = {
                "model": CHAT_MODEL,
                "messages": [{"role": "user", "content": [{"type": "text", "text": _prompt}, _image]}],
                "response_format": {"type": "json_object"},
            }
            _reply = json.loads(fetch_bytes(CHAT_URL, json.dumps(_body).encode(), _headers, 180))
            _verdict = ChatVerdict.model_validate_json(_reply["choices"][0]["message"]["content"])
            _answer = {"p": _verdict.same_site_probability, "cost": float(_reply["usage"].get("cost", 0))}
        _path.parent.mkdir(parents=True, exist_ok=True)
        _path.write_text(json.dumps(_answer))
        return _answer

    return aerial_chip, ask


@app.cell
def _(ask, pairs):
    METHODS = ["jev_text", "jev_text_image", "chat_text_image", "jev_geocoded"]
    answers = pairs[["pair_id"]].copy()
    model_runs = []
    for _method in METHODS:
        # The chat model is 25 times dearer, so it only answers the pairs with a key.
        _rows = pairs if _method != "chat_text_image" else pairs.dropna(subset=["truth"])
        _started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=8) as _pool:
            _out = list(_pool.map(ask, [_method] * len(_rows), [r for _, r in _rows.iterrows()]))
        answers.loc[_rows.index, _method] = [o["p"] for o in _out]
        model_runs.append(
            {
                "method": _method,
                "pairs": len(_rows),
                "cost_usd": round(sum(o["cost"] for o in _out), 4),
                "seconds_this_run": round(time.perf_counter() - _started),
            }
        )
    model_runs = pd.DataFrame(model_runs)
    model_runs.to_csv(OUT / "model_runs.csv", index=False)
    model_runs
    return METHODS, answers


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Scoring every method against the keys

    Each method gives every pair a score. For the yes/no rules the score is 0 or 1; for distance it is how close
    the points are; for the models it is their probability. On the *tune* half of each key we pick two thresholds:
    the lowest score above which at least 97% of pairs really share a site (**merge automatically**), and the highest
    score below which at least 97% really don't (**keep apart automatically**). Everything between goes to
    **review**. Then we apply those thresholds to the *test* half and count.

    The useful method is the one that decides the most pairs on the test half while staying near 97% correct.
    """)
    return


@app.cell
def _(METHODS, answers, pairs):
    scored = pairs.join(answers[METHODS])
    scored["near_10m"] = (scored["distance_m"] <= 10).astype(float)
    scored["near_50m"] = (scored["distance_m"] <= 50).astype(float)
    scored["closeness"] = -scored["distance_m"]
    scored["s2_18"] = (scored["s2_shared_level"] >= 18).astype(float)
    scored["s2_20"] = (scored["s2_shared_level"] >= 20).astype(float)
    scored["rules"] = (
        scored[["same_address", "same_building", "same_osm_grounds"]].sum(axis=1) + (scored["distance_m"] <= 25)
    ) / 4
    SCORES = {
        "distance ≤ 10 m": "near_10m",
        "distance ≤ 50 m": "near_50m",
        "distance (any cut)": "closeness",
        "same S2 cell, level 18 (~35 m)": "s2_18",
        "same S2 cell, level 20 (~9 m)": "s2_20",
        "S2 shared level (any level)": "s2_shared_level",
        "same address": "same_address",
        "same Overture building": "same_building",
        "same OSM school grounds": "same_osm_grounds",
        "count of the four signals": "rules",
        "Jev, text": "jev_text",
        "Jev, text + image": "jev_text_image",
        "Jev, text + address geocodes": "jev_geocoded",
        f"{CHAT_MODEL}, text + image": "chat_text_image",
    }

    def thresholds(score: pd.Series, truth: pd.Series) -> tuple[float, float]:
        """(merge_at, apart_at) meeting TARGET_PRECISION on these pairs; inf / -inf when nothing qualifies."""
        _merge_at, _apart_at = np.inf, -np.inf
        for _t in np.unique(score):
            _above, _below = truth[score >= _t], truth[score <= _t]
            if _merge_at == np.inf and len(_above) >= 10 and _above.mean() >= TARGET_PRECISION:
                _merge_at = _t
            if len(_below) >= 10 and 1 - _below.mean() >= TARGET_PRECISION:
                _apart_at = _t
        return _merge_at, _apart_at

    _rows = []
    for _region in REGIONS:
        _known = scored[(scored["region"] == _region) & scored["truth"].notna()]
        _tune, _test = _known[_known["half"] == "tune"], _known[_known["half"] == "test"]
        for _label, _column in SCORES.items():
            _merge_at, _apart_at = thresholds(_tune[_column].astype(float), _tune["truth"])
            _s, _y = _test[_column].astype(float), _test["truth"]
            _merge, _apart = _s >= _merge_at, (_s <= _apart_at) & ~(_s >= _merge_at)
            # A plain yes/no reading of the same score: 0.5 for probabilities and rules, 25 m, S2 level 18.
            _said_yes = _s >= {"closeness": -25, "s2_shared_level": 18}.get(_column, 0.5)
            _rows.append(
                {
                    "region": _region,
                    "method": _label,
                    "test pairs": len(_test),
                    "merged": int(_merge.sum()),
                    "merged wrongly": int((_merge & (_y == 0)).sum()),
                    "kept apart": int(_apart.sum()),
                    "kept apart wrongly": int((_apart & (_y == 1)).sum()),
                    "to review": int((~_merge & ~_apart).sum()),
                    "decided %": round(100 * (_merge | _apart).mean(), 1),
                    "plain precision": round(float(_y[_said_yes].mean()), 3),
                    "plain recall": round(float(_said_yes[_y == 1].mean()), 3),
                }
            )
    triage = pd.DataFrame(_rows)
    triage.to_csv(OUT / "triage.csv", index=False)
    triage
    return scored, thresholds


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Is the probability a probability?** A calibrated model's "0.8" is right 80% of the time. Below, every keyed
    pair (both halves, both regions) is binned by its predicted probability; a perfect model sits on the diagonal.
    The expected calibration error (ECE) is the average gap, weighted by how many pairs fall in each bin. The Brier
    score is the mean squared error of the probability (0 is perfect, 0.25 is a coin flip).
    """)
    return


@app.cell
def _(METHODS, scored):
    _known = scored.dropna(subset=["truth"])
    _fig, _ax = plt.subplots(figsize=(5.5, 5))
    _ax.plot([0, 1], [0, 1], color="#999", lw=1, ls="--")
    _rows = []
    for _method, _colour in zip(METHODS, ["#4c72b0", "#c44e52", "#55a868", "#8172b2"], strict=True):
        _p, _y = _known[_method].astype(float), _known["truth"].astype(float)
        _bins = np.minimum((_p * 10).astype(int), 9)
        _cal = (
            pd.DataFrame({"p": _p, "y": _y, "bin": _bins})
            .groupby("bin")
            .agg(p=("p", "mean"), y=("y", "mean"), n=("y", "size"))
        )
        _ax.plot(_cal["p"], _cal["y"], marker="o", color=_colour, label=_method)
        _order = np.argsort(-_p.to_numpy())
        _ranked = _y.to_numpy()[_order]
        _auc = ((_ranked == 1).cumsum()[_ranked == 0]).sum() / max(1, (_ranked == 1).sum() * (_ranked == 0).sum())
        _rows.append(
            {
                "method": _method,
                "pairs": len(_p),
                "Brier": round(float(((_p - _y) ** 2).mean()), 3),
                "ECE": round(float((abs(_cal["p"] - _cal["y"]) * _cal["n"]).sum() / _cal["n"].sum()), 3),
                "AUC": round(float(_auc), 3),
            }
        )
    _ax.set_xlabel("predicted probability of same site")
    _ax.set_ylabel("share that really are the same site")
    _ax.legend(frameon=False, fontsize=8)
    _fig.tight_layout()
    _fig.savefig(OUT / "calibration.png", dpi=120)
    calibration = pd.DataFrame(_rows)
    calibration.to_csv(OUT / "calibration.csv", index=False)
    mo.vstack([calibration, mo.as_html(_fig)])
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## From pairs to sites

    With Jev's thresholds from the tune half, every pair in the two regions (with or without a key) is merged, kept
    apart, or sent to review. Merged pairs are joined into sites (connected components), so each school record gets
    a `site_id`. The records stay; nothing is deleted. Enrollment is summed per site, because co-located schools
    have separate students.
    """)
    return


@app.cell
def _(scored, schools, thresholds):
    _method = SITE_METHOD
    _rows = []
    _regional = []
    for _region, _spec in REGIONS.items():
        _known = scored[(scored["region"] == _region) & scored["truth"].notna() & (scored["half"] == "tune")]
        _merge_at, _apart_at = thresholds(_known[_method], _known["truth"])
        _all = scored[scored["region"] == _region]
        _decision = np.select(
            [_all[_method] >= _merge_at, _all[_method] <= _apart_at], ["merge", "keep apart"], "review"
        )
        _local = schools[schools["COUNTYFIPS"].isin(_spec.counties)][
            ["NCESID", "NAME", "ADDRESS", "CITY", "ENROLLMENT"]
        ]
        _index = pd.Series(range(len(_local)), index=_local["NCESID"])
        _merged = _all[_decision == "merge"]
        _graph = coo_matrix(
            (np.ones(len(_merged)), (_index[_merged["a_ncesid"]], _index[_merged["b_ncesid"]])),
            shape=(len(_local),) * 2,
        )
        _, _labels = connected_components(_graph, directed=False)
        _local = _local.assign(region=_region, site_id=[f"{_spec.osm_relation}-{s}" for s in _labels])
        _review_ids = set(_all.loc[_decision == "review", ["a_ncesid", "b_ncesid"]].to_numpy().ravel())
        _local["has_pair_to_review"] = _local["NCESID"].isin(_review_ids)
        _regional.append(_local)
        _rows.append(
            {
                "region": _region,
                "records": len(_local),
                "sites": _local["site_id"].nunique(),
                "pairs merged": int((_decision == "merge").sum()),
                "pairs kept apart": int((_decision == "keep apart").sum()),
                "pairs to review": int((_decision == "review").sum()),
                "records with a pair to review": int(_local["has_pair_to_review"].sum()),
                "merge at p ≥": _merge_at,
                "keep apart at p ≤": _apart_at,
            }
        )
        scored.loc[_all.index, "decision"] = _decision
    sites = pd.concat(_regional, ignore_index=True)
    sites.to_csv(OUT / "school_sites.csv", index=False)
    scored.drop(columns=["closeness", "near_10m", "near_50m", "s2_18", "s2_20"]).to_csv(OUT / "pairs.csv", index=False)
    site_summary = pd.DataFrame(_rows)
    site_summary.to_csv(OUT / "site_summary.csv", index=False)
    site_summary
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What the national run would cost

    The footprints, grounds and imagery above exist nationally, but this spike reads them for two regions only. The
    model cost per pair, times the national candidate pairs, says what a national pass would cost.
    """)
    return


@app.cell
def _(METHODS, national_pairs, pairs):
    _runs = pd.read_csv(OUT / "model_runs.csv").set_index("method")
    _per_pair = {
        m: sum(json.loads(p.read_text())["cost"] for p in (DATA / "answers" / m).glob("*.json"))
        / max(1, len(list((DATA / "answers" / m).glob("*.json"))))
        for m in METHODS
    }
    pd.DataFrame(
        {
            "USD per pair": {m: round(v, 6) for m, v in _per_pair.items()},
            "USD for all national candidate pairs": {
                m: round(v * len(national_pairs), 2) for m, v in _per_pair.items()
            },
            "pairs in this run": _runs["pairs"],
        }
    ).assign(**{"national candidate pairs": len(national_pairs), "regional pairs": len(pairs)})
    return


@app.cell
def _():
    run_seconds = time.perf_counter() - RUN_STARTED
    print(f"run time: {run_seconds:.0f} s")
    return


if __name__ == "__main__":
    app.run()

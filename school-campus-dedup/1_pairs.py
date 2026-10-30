import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import hashlib
    import json
    import re
    import urllib.parse
    import urllib.request
    from pathlib import Path

    import duckdb
    import geopandas as gpd
    import marimo as mo
    import numpy as np
    import pandas as pd
    import shapely
    from rapidfuzz import fuzz

    from common import (
        DATA,
        METRIC,
        NEAR_M,
        OUT,
        PAIRS_FILE,
        REGIONS,
        address_unit,
        cached,
        candidate_pairs,
        fetch_bytes,
        load_schools,
        normalise_address,
    )

    HIFLD_API = "https://hifld.publicenvirodata.org/api/collections/hifld/datasets"
    CCD_API = "https://educationdata.urban.org/api/v1/schools/ccd/directory/2022/"
    NYC_LOCATIONS = "https://data.cityofnewyork.us/resource/wg9x-4ke6.json?$limit=5000"
    LAUSD_GIS = "https://maps.lacity.org/lahub/rest/services/LAUSD_Schools/MapServer"
    QLEVER = "https://qlever.dev/api/osm-planet"
    OVERTURE_RELEASE = "2026-10-21.0"
    OVERTURE = f"s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}"
    CENSUS_GEOCODER = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # 1. Which school records might share a site, and what do we know about each pair?

    **The question.** Public school point layers, such as HIFLD Next's *Public Schools* (taken from NCES), often
    show several points on one campus: a high school and the small academies that share its buildings, or a charter
    network whose schools share an address. Anyone who counts schools as places (sensitive sites near a pollution
    source, say) wants them merged into one site. Merge by distance alone, though, and a school across the street
    goes too.

    This notebook builds the table the other three use: every **candidate pair** of records, the evidence a person
    checking it would look at, and, where a published answer key covers it, whether the two really share a site.

    - [2. Rules](2_rules.py): how well distance, S2 cells, footprints and addresses decide it.
    - [3. Jev](3_jev.py): what a decision model makes of the same pairs, and how far to trust its probability.
    - [4. Sites](4_sites.py): from pairs to sites, the cost of a national pass, and what didn't work.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The records

    **HIFLD Next Public Schools**, found through the portal's API (dataset → STAC versions → GeoParquet). We keep
    the 50 states and DC.
    """)
    return


@app.cell
def _():
    _dataset = json.loads(cached("hifld-dataset.json", f"{HIFLD_API}/public-schools").read_text())
    _versions = json.loads(fetch_bytes(next(link["href"] for link in _dataset["links"] if link["rel"] == "child")))
    _collection_url = [link["href"] for link in _versions["links"] if link["rel"] == "child"][-1]
    _collection = json.loads(fetch_bytes(_collection_url))
    _release = re.search(r"releases/([0-9a-f]{8})", _collection_url)
    assert _release, f"no release ID in {_collection_url}"
    cached(
        "public-schools.parquet",
        next(a["href"] for k, a in _collection["assets"].items() if k.startswith("geoparquet")),
    )
    schools = load_schools()
    assert schools["NCESID"].is_unique, "NCES IDs repeat: the layer has true duplicate rows"
    mo.md(
        f"HIFLD Next release `{_release.group(1)}`: **{len(schools):,} records**, and every NCES ID appears once. "
        "So no row is a copy of another: each is a separate school in NCES's directory, with its own enrollment. "
        "The question is only which ones share a site."
    )
    return (schools,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## How big is the problem, nationally?

    A **candidate pair** is two records whose points are within 150 m, or that give the same street address in the
    same city (house number and street, ignoring punctuation, room, floor, annex or trailer, and words like *St*).
    """)
    return


@app.cell
def _(schools):
    national_pairs = candidate_pairs(schools)
    _same = national_pairs["same_address"]
    _far = _same & (national_pairs["distance_m"] > NEAR_M)

    def _records(mask: pd.Series) -> int:
        return len(pd.unique(national_pairs.loc[mask, ["i", "j"]].to_numpy().ravel()))

    national_summary = pd.DataFrame(
        {
            "pairs": [len(national_pairs), int(_same.sum()), int((~_same).sum())],
            "records involved": [_records(_same | ~_same), _records(_same), _records(~_same)],
            "same address, points >150 m apart": [int(_far.sum()), int(_far.sum()), 0],
        },
        index=["all candidate pairs", "same address", "within 150 m, different address"],
    )
    national_summary.to_csv(OUT / "national_summary.csv")
    national_summary
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## More sources, for the two regions with an answer key

    For New York City and Los Angeles County we add:

    - **NCES's Common Core of Data** directory (2022–23, through the Urban Institute's
      [Education Data API](https://educationdata.urban.org/documentation/)): each school's state ID (which joins
      HIFLD to the answer keys), district name, and charter and virtual flags.
    - **OpenStreetMap school grounds**: every `amenity=school` area in the region, with its outline, from the
      [QLever](https://qlever.dev) SPARQL endpoint.
    - **Overture buildings**: every footprint in the region's bounding box, read from Overture's public S3 bucket
      with DuckDB.
    """)
    return


@app.cell
def _():
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
    ccd = pd.concat(_frames, ignore_index=True)[["ncessch", "seasch", "charter", "virtual", "school_name", "lea_name"]]
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
    _osm_build = json.loads(fetch_bytes(f"{QLEVER}?cmd=stats"))["name-index"]
    mo.md(f"CCD: {len(ccd):,} schools in the two states. OSM school areas: {len(osm_areas):,} (QLever `{_osm_build}`).")
    return ccd, osm_areas


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
    ## The answer keys

    **New York City.** The DOE's [2019–20 School Locations](https://data.cityofnewyork.us/d/wg9x-4ke6) list each
    school's BEDS code and `primary_building_code`. Two schools with the same building code share a building. The
    file is three years older than HIFLD's source, so we drop schools whose house number differs between the two
    (they may have moved). The same file places each school, which shows how far off HIFLD's points can be.

    **Los Angeles Unified.** The district's GIS publishes
    [school points](https://maps.lacity.org/lahub/rest/services/LAUSD_Schools/MapServer/0) with CDS codes and
    [campus polygons](https://maps.lacity.org/lahub/rest/services/LAUSD_Schools/MapServer/2). A school belongs to
    each campus that contains one of its own points; a point on no campus is a site of its own. Two schools share a
    site if they share a campus. Pairs where neither school is on a campus get no answer, since two off-campus
    charters could share a private building.
    """)
    return


@app.cell
def _(ccd, schools):
    _nyc = pd.read_json(cached("nyc-school-locations-2019-20.json", NYC_LOCATIONS), dtype=str)
    _nyc = _nyc.merge(ccd[["ncessch", "beds"]], on="beds").merge(
        schools[["NCESID", "ADDRESS", "geometry"]], left_on="ncessch", right_on="NCESID"
    )
    _house = _nyc["ADDRESS"].map(normalise_address).str.split().str[0]
    _same_house = _house == _nyc["primary_address_line_1"].str.split().str[0]
    nyc_key = _nyc.loc[_same_house].drop_duplicates("NCESID").set_index("NCESID")["primary_building_code"]

    _placed_by_doe = _nyc[_same_house & pd.to_numeric(_nyc["latitude"], errors="coerce").notna()]
    _doe = gpd.GeoSeries(
        gpd.points_from_xy(_placed_by_doe["longitude"].astype(float), _placed_by_doe["latitude"].astype(float)),
        crs="EPSG:4326",
    ).to_crs(METRIC)
    _offset = gpd.GeoSeries(_placed_by_doe["geometry"].to_numpy(), crs=METRIC).distance(_doe, align=False)
    _offset.describe(percentiles=[0.5, 0.9, 0.95]).round(1).to_csv(OUT / "hifld_point_offset_nyc.csv")

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

    _campuses = arcgis_layer(2)[["ID", "LABEL", "geometry"]]
    _placed = gpd.sjoin(arcgis_layer(0)[["CDSCODE", "geometry"]], _campuses, how="left", predicate="within")
    _placed["site"] = (
        _placed["ID"].map(lambda i: f"campus {int(i)}", na_action="ignore").fillna("own " + _placed["CDSCODE"])
    )
    _placed["NCESID"] = _placed["CDSCODE"].map(ccd.set_index("cds")["ncessch"])
    la_key = _placed.dropna(subset=["NCESID"]).groupby("NCESID")["site"].agg(frozenset)
    mo.md(
        f"NYC key: {len(nyc_key):,} HIFLD schools with a building code. HIFLD's point is a median "
        f"{_offset.median():.0f} m from the DOE's for the same school; {(_offset > 100).mean():.0%} are more than "
        f"100 m off and {(_offset > 250).mean():.0%} more than 250 m.  \n"
        f"LAUSD key: {len(la_key):,} HIFLD schools placed on one of {len(_campuses):,} campuses or a site of their own."
    )
    return la_key, nyc_key


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The evidence for each pair

    For every candidate pair in the two regions we collect what a person checking it would look at:

    - both records: name, address, phone, website, grades, enrollment, district, school type, charter and virtual;
    - **from HIFLD's points**: the distance, whether both sit in the same Overture building footprint (inside it, or
      within 10 m), whether both sit in the same OSM school grounds, and the S2 level at which they share a cell;
    - **from the addresses**: each one geocoded by the
      [Census Bureau's batch geocoder](https://geocoding.geo.census.gov/geocoder/) (free, no key), independently of
      HIFLD's point; the distance between the two geocodes; the OSM grounds each geocode falls in; and how the two
      addresses relate, in words.
    """)
    return


@app.cell
def _(building_files, ccd, la_key, nyc_key, osm_areas, schools):
    def nearest_within(points: gpd.GeoDataFrame, shapes: gpd.GeoDataFrame, column: str, metres: float) -> pd.Series:
        """For each point, `column` of the shape containing it or, failing that, the nearest within `metres`."""
        _hit = gpd.sjoin_nearest(
            points[["geometry"]], shapes[[column, "geometry"]], max_distance=metres, distance_col="d"
        )
        return pd.Series(_hit.sort_values("d").groupby(level=0)[column].first().reindex(points.index))

    def census_geocode(frame: pd.DataFrame, name: str) -> gpd.GeoDataFrame:
        """Each record's reported address geocoded by the Census Bureau, independently of its HIFLD point."""
        assert len(frame) <= 10_000, "the Census batch geocoder takes at most 10,000 addresses"
        _csv = frame[["NCESID", "ADDRESS", "CITY", "STATE", "ZIP"]].to_csv(index=False, header=False)
        _boundary = "----school-campus-dedup"
        _body = (
            f'--{_boundary}\r\nContent-Disposition: form-data; name="benchmark"\r\n\r\nPublic_AR_Current\r\n'
            f'--{_boundary}\r\nContent-Disposition: form-data; name="addressFile"; filename="a.csv"\r\n'
            f"Content-Type: text/csv\r\n\r\n{_csv}\r\n--{_boundary}--\r\n"
        ).encode()
        _headers = {"Content-Type": f"multipart/form-data; boundary={_boundary}"}
        _path = cached(f"census-geocode-{name}.csv", CENSUS_GEOCODER, _body, _headers)
        _out = pd.read_csv(_path, header=None, dtype=str, usecols=[0, 4, 5], names=["NCESID", "matched", "lonlat"])
        _out = _out.set_index("NCESID").reindex(frame["NCESID"])
        _xy = _out["lonlat"].str.split(",", expand=True).astype(float)
        return gpd.GeoDataFrame(
            {"census_address": _out["matched"].to_numpy()}, geometry=gpd.points_from_xy(_xy[0], _xy[1]), crs="EPSG:4326"
        ).to_crs(METRIC)

    def street_relation(a: pd.Series, b: pd.Series) -> str:
        """How two addresses relate, in words. House number and street come from the Census match when there is one
        (it fixes spellings like COMMONWLTH); only the reported address has the room, floor, annex or trailer."""
        _base = [
            normalise_address(
                r["census_address"].split(",")[0] if isinstance(r["census_address"], str) else r["ADDRESS"]
            )
            for r in (a, b)
        ]
        _units = [address_unit(r["ADDRESS"]) for r in (a, b)]
        _number = [x.split(" ", 1)[0] for x in _base]
        _street = [x.split(" ", 1)[1] if " " in x else "" for x in _base]
        if _base[0] == _base[1] and _units[0] == _units[1]:
            return "identical street address"
        if _base[0] == _base[1]:
            return f"same street address, different unit: '{_units[0] or 'none'}', '{_units[1] or 'none'}'"
        if _street[0] == _street[1] and a["CITY"] == b["CITY"]:
            return f"same street, house numbers {_number[0]} and {_number[1]}"
        return "different streets"

    _ccd = ccd.set_index("ncessch")
    _school_types = {"1": "regular", "2": "special education", "3": "career and technical", "4": "alternative"}
    _virtual = {0: "no", 1: "fully virtual", 2: "virtual with face-to-face options", 3: "supplemental virtual"}
    _columns = ["NCESID", "NAME", "ADDRESS", "CITY", "TELEPHONE", "LEVEL_", "ST_GRADE", "END_GRADE", "ENROLLMENT"]
    _columns += ["DISTRICTID", "WEBSITE", "charter", "district_name", "virtual", "school_type", "building"]
    _columns += ["building_area_m2", "osm_area_name", "census_address", "address_grounds_name"]
    _frames = []
    for _region, _spec in REGIONS.items():
        _local = schools[schools["COUNTYFIPS"].isin(_spec.counties)].reset_index(drop=True)
        _local["charter"] = _local["NCESID"].map(_ccd["charter"])
        _local["district_name"] = _local["NCESID"].map(_ccd["lea_name"])
        _local["virtual"] = _local["NCESID"].map(_ccd["virtual"]).map(_virtual)
        _local["school_type"] = _local["TYPE"].map(_school_types)

        # From HIFLD's point: the building and the school grounds it sits in.
        _raw = pd.read_parquet(building_files[_region])
        _buildings = gpd.GeoDataFrame(_raw[["id"]], geometry=shapely.from_wkb(_raw["wkb"]), crs="EPSG:4326").to_crs(
            METRIC
        )
        _near = gpd.sjoin(_buildings, _local[["geometry"]].set_geometry(_local.buffer(200)), predicate="intersects")
        _buildings = _buildings.iloc[_near.index.unique()]
        _local["building"] = nearest_within(_local, _buildings, "id", 10)
        _local["building_area_m2"] = _local["building"].map(_buildings.set_index("id").area).round()
        _areas = osm_areas[osm_areas["region"] == _region]
        _local["osm_area"] = nearest_within(_local, _areas, "osm_id", 10)
        _local["osm_area_name"] = _local["osm_area"].map(_areas.set_index("osm_id")["osm_name"])

        # From the address: the Census geocode and the grounds it falls in. Census points are interpolated along the
        # street, so they sit just outside the grounds they front; hence 30 m rather than 10.
        _geocoded = census_geocode(_local, str(_spec.osm_relation))
        _local["census_address"] = _geocoded["census_address"].to_numpy()
        _found = _geocoded[~_geocoded.geometry.is_empty & _geocoded.geometry.x.notna()]
        _local["address_grounds_name"] = (
            nearest_within(_found, _areas, "osm_id", 30)
            .map(_areas.set_index("osm_id")["osm_name"])
            .reindex(_local.index)
        )

        _pairs = candidate_pairs(_local)
        _a, _b = _local.iloc[_pairs["i"]].reset_index(drop=True), _local.iloc[_pairs["j"]].reset_index(drop=True)
        _pairs["region"] = _region
        for _side, _rows in (("a", _a), ("b", _b)):
            for _column in _columns:
                _pairs[f"{_side}_{_column.lower()}"] = _rows[_column].to_numpy()
            _lonlat = _rows.geometry.to_crs("EPSG:4326")
            _pairs[f"{_side}_lon"], _pairs[f"{_side}_lat"] = _lonlat.x.to_numpy(), _lonlat.y.to_numpy()
        _g = _geocoded.geometry
        _pairs["geocoded_distance_m"] = (
            _g.iloc[_pairs["i"]].distance(_g.iloc[_pairs["j"]], align=False).round().to_numpy()
        )
        _pairs["same_building"] = _a["building"].notna().to_numpy() & (
            _a["building"].to_numpy() == _b["building"].to_numpy()
        )
        _pairs["same_osm_grounds"] = _a["osm_area"].notna().to_numpy() & (
            _a["osm_area"].to_numpy() == _b["osm_area"].to_numpy()
        )
        _pairs["same_phone"] = (_a["TELEPHONE"].to_numpy() == _b["TELEPHONE"].to_numpy()) & (
            _a["TELEPHONE"] != "NOT AVAILABLE"
        ).to_numpy()
        _pairs["street_relation"] = [street_relation(_a.iloc[k], _b.iloc[k]) for k in range(len(_pairs))]
        _pairs["name_similarity"] = [fuzz.token_set_ratio(x, y) for x, y in zip(_a["NAME"], _b["NAME"], strict=True)]

        if _region == "New York City":
            _ka, _kb = _a["NCESID"].map(nyc_key), _b["NCESID"].map(nyc_key)
            _pairs["truth"] = np.where(_ka.notna() & _kb.notna(), _ka == _kb, np.nan)
        else:
            _ka, _kb = (_rec["NCESID"].map(lambda n: la_key.get(n, frozenset())) for _rec in (_a, _b))
            _pairs["truth"] = [
                float(bool(x & y)) if x and y and any(s.startswith("campus") for s in x | y) else np.nan
                for x, y in zip(_ka, _kb, strict=True)
            ]
        _frames.append(_pairs.drop(columns=["i", "j"]))
    pairs = pd.concat(_frames, ignore_index=True)
    pairs["pair_id"] = pairs["a_ncesid"] + "-" + pairs["b_ncesid"]
    return (pairs,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **S2 cells**, as used to match features between versions of a layer: for each pair, the deepest S2 level
    (10–24, about 10 km down to 0.6 m) at which both points fall in the same cell, from DuckDB's `geography`
    extension. Cells nest, so counting the shared levels gives the deepest.

    **Tune and test halves.** Each answer key is split by a hash of the pair's IDs: thresholds are picked on the
    *tune* half and counted on the *test* half. The hash keeps the split the same on every run.
    """)
    return


@app.cell
def _(pairs):
    _con = duckdb.connect()
    _con.sql("INSTALL geography FROM community; LOAD geography;")
    _shared = " + ".join(f"(s2_cell_parent(ca, {_l}) = s2_cell_parent(cb, {_l}))::INT" for _l in range(10, 25))
    _con.register("pair_points", pairs[["a_lon", "a_lat", "b_lon", "b_lat"]].reset_index(names="row"))
    _levels = _con.sql(f"""
        SELECT 9 + {_shared} AS level FROM (
            SELECT row, s2_cellfromlonlat(a_lon, a_lat) AS ca, s2_cellfromlonlat(b_lon, b_lat) AS cb FROM pair_points)
        ORDER BY row""").df()
    pairs["s2_shared_level"] = _levels["level"].to_numpy()
    pairs["half"] = np.where(
        pairs["pair_id"].map(lambda s: int(hashlib.sha256(s.encode()).hexdigest(), 16) % 2), "test", "tune"
    )
    pairs.to_parquet(PAIRS_FILE, index=False)
    pairs.groupby("region").agg(
        pairs=("pair_id", "size"),
        with_answer=("truth", lambda s: int(s.notna().sum())),
        same_site=("truth", lambda s: int((s == 1).sum())),
        same_address=("same_address", "sum"),
        same_building=("same_building", "sum"),
        same_osm_grounds=("same_osm_grounds", "sum"),
    )
    return


if __name__ == "__main__":
    app.run()

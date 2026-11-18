import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import io
    import json
    import os
    import time
    import zipfile
    from pathlib import Path

    import duckdb
    import geopandas as gpd
    import marimo as mo
    import numpy as np
    import pandas as pd
    import requests
    from rapidfuzz import fuzz

    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("CHILDCARE_DATA_DIR", HERE / "data"))
    OUT = Path(os.environ.get("CHILDCARE_OUTPUT_DIR", HERE / "output"))
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    OVERTURE_RELEASE = "2026-10-21.0"
    # US National Atlas Equal Area: distances in metres in every state.
    METRIC = "EPSG:9311"
    HEADERS = {"User-Agent": "Mozilla/5.0 (child-care-facilities-rebuild spike)"}
    STARTED = time.time()
    return (
        DATA,
        HEADERS,
        METRIC,
        OUT,
        OVERTURE_RELEASE,
        STARTED,
        duckdb,
        fuzz,
        gpd,
        io,
        json,
        mo,
        np,
        pd,
        requests,
        time,
        zipfile,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Can we rebuild a national child care facilities layer?

    HIFLD's Child Care Centers layer is frozen: HIFLD Next carries it only for New York and Washington, from a 2015
    ORNL copy. No federal agency publishes a national list of licensed child care facilities; the Administration for
    Children and Families (ACF) lists Head Start centres only. Licensing is done by the states.

    So the question is whether **state licensing rosters** give an official base, and whether **OpenStreetMap** and
    **Overture Places** can fill the states without one. This notebook measures four things:

    1. how many states publish a roster a script can download (the survey in `rosters.csv`);
    2. how many child care features OSM and Overture have in each state, next to the roster count;
    3. in states with a roster, how many roster facilities the open maps find, and how many open-map features match
       no licensed facility;
    4. a hand check of a seeded sample, and what the licences would mean for a combined layer.

    It's wrong if the open maps find well under the roster counts or most matches disagree.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Which states publish a roster?

    `rosters.csv` is a hand survey of all 50 states and DC (done 2026-11-18): the licensing agency, the roster page,
    whether one unauthenticated request (or a paged API) returns the whole statewide list, its format, whether rows
    carry coordinates or addresses, and the stated update date. Search-only web forms and PDFs count as *not*
    machine-readable: a script can't rebuild a layer from them without scraping.
    """)
    return


@app.cell
def _(pd):
    survey = pd.read_csv("rosters.csv", dtype=str).fillna("")
    _readable = survey["machine_readable"] == "yes"
    survey_summary = pd.DataFrame(
        {
            "states (incl. DC)": [len(survey)],
            "machine-readable roster": [_readable.sum()],
            "… with coordinates": [(_readable & survey["coords"].str.startswith("yes")).sum()],
            "… current (updated in the last 12 months)": [(_readable & (survey["current"] == "yes")).sum()],
            "search form, PDF or form post only": [(~_readable).sum()],
            "compared below": [survey["compared_here"].str.startswith("yes").sum()],
        }
    )
    survey_summary
    return survey, survey_summary


@app.cell
def _(survey):
    survey[
        [
            "state",
            "agency",
            "format",
            "machine_readable",
            "coords",
            "current",
            "record_count",
            "updated",
            "compared_here",
        ]
    ]
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. The open maps and Head Start, everywhere

    - **OpenStreetMap**: every feature in the US tagged `amenity=childcare` or `amenity=kindergarten` (in the US the
      latter is mostly used for preschools), read through [QLever](https://qlever.dev)'s SPARQL endpoint for the OSM
      planet, as in `hifld-overture-crosswalk/`. ODbL 1.0.
    - **Overture Places**: the four child care categories in the release's taxonomy (`child_care_and_day_care`,
      `day_care_preschool`, `preschool`, `kindergarten`), read from the public S3 bucket with DuckDB. Places that
      Overture marks `permanently_closed` are dropped. CDLA-Permissive 2.0.
    - **Head Start**: ACF's centre locator API, one request per state; open centres only. US government.

    Every point is given a state by the Census 2024 cartographic state boundaries, so the counts don't depend on
    each source's own address field.
    """)
    return


@app.cell
def _(DATA, HEADERS, gpd, io, requests, zipfile):
    _path = DATA / "cb_2024_us_state_500k.zip"
    if not _path.exists():
        _r = requests.get(
            "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_state_500k.zip", headers=HEADERS, timeout=300
        )
        _r.raise_for_status()
        _path.write_bytes(_r.content)
    with zipfile.ZipFile(io.BytesIO(_path.read_bytes())) as _z:
        assert any(n.endswith(".shp") for n in _z.namelist()), "Census zip has no shapefile"
    states = gpd.read_file(f"zip://{_path}")[["STUSPS", "geometry"]].rename(columns={"STUSPS": "state"}).to_crs(4326)
    states = states[~states["state"].isin(["PR", "VI", "GU", "MP", "AS"])].reset_index(drop=True)
    assert len(states) == 51, len(states)
    return (states,)


@app.cell
def _(gpd, pd, states):
    def in_state(frame: pd.DataFrame) -> gpd.GeoDataFrame:
        """Points (lon, lat) inside one of the 51 states, with a `state` column from the Census boundaries."""
        points = gpd.GeoDataFrame(frame, geometry=gpd.points_from_xy(frame["lon"], frame["lat"]), crs=4326)
        joined = gpd.sjoin(points.drop(columns="state", errors="ignore"), states, predicate="within", how="inner")
        return joined.drop(columns="index_right").reset_index(drop=True)

    return (in_state,)


@app.cell
def _(DATA, HEADERS, in_state, pd, requests):
    _query = """
    PREFIX osmkey: <https://www.openstreetmap.org/wiki/Key:>
    PREFIX ogc: <http://www.opengis.net/rdf#>
    PREFIX osmrel: <https://www.openstreetmap.org/relation/>
    PREFIX geo: <http://www.opengis.net/ont/geosparql#>
    PREFIX geof: <http://www.opengis.net/def/function/geosparql/>
    SELECT ?osm ?amenity ?name ?centroid WHERE {
      VALUES ?amenity { "childcare" "kindergarten" }
      osmrel:148838 ogc:sfContains ?osm . ?osm osmkey:amenity ?amenity .
      ?osm geo:hasGeometry/geo:asWKT ?wkt . BIND(geof:centroid(?wkt) AS ?centroid)
      OPTIONAL { ?osm osmkey:name ?name }
    } ORDER BY ?osm"""
    _path = DATA / "osm_childcare.tsv"
    if not _path.exists():
        # QLever closes a response after about 5 MB, so read it in pages of 10,000 rows (at most 20 pages).
        _lines: list[str] = []
        for _page in range(20):
            _r = requests.post(
                "https://qlever.dev/api/osm-planet",
                data={"query": f"{_query} LIMIT 10000 OFFSET {_page * 10000}"},
                headers={**HEADERS, "Accept": "text/tab-separated-values"},
                timeout=600,
            )
            _r.raise_for_status()
            _rows = _r.text.splitlines()
            _lines += _rows if _page == 0 else _rows[1:]
            if len(_rows) - 1 < 10000:
                break
        else:
            raise RuntimeError("OSM child care: more than 20 pages")
        _path.write_text("\n".join(_lines) + "\n")
    _tsv = pd.read_csv(_path, sep="\t", quoting=3, dtype=str)
    _xy = _tsv["?centroid"].str.extract(r"POINT\(([-\d.]+) ([-\d.]+)\)").astype(float)
    osm = in_state(
        pd.DataFrame(
            {
                "source_id": _tsv["?osm"].str.extract(r"org/(\w+/\d+)>")[0],
                "kind": _tsv["?amenity"].str.strip('"'),
                "name": _tsv["?name"].fillna("").str.strip('"').str.replace(r'"\^\^.*$', "", regex=True),
                "lon": _xy[0],
                "lat": _xy[1],
            }
        ).dropna(subset=["lon"])
    )
    osm["source"] = "OpenStreetMap"
    osm["licence"] = "ODbL-1.0"
    assert len(osm) > 5000, f"only {len(osm)} OSM features: QLever answer looks truncated"
    return (osm,)


@app.cell
def _(DATA, OVERTURE_RELEASE, duckdb, in_state, pd):
    _path = DATA / f"overture_childcare_{OVERTURE_RELEASE}.parquet"
    if not _path.exists():
        _con = duckdb.connect()
        _con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
        # An empty key reads the public bucket anonymously.
        _con.sql("CREATE SECRET overture (TYPE s3, KEY_ID '', SECRET '', REGION 'us-west-2')")
        _con.sql("SET threads = 10")
        _con.sql(f"""
            COPY (
              SELECT id AS source_id, taxonomy.primary AS kind, names.primary AS name, confidence, operating_status,
                     addresses[1].freeform AS street, addresses[1].locality AS city, addresses[1].postcode AS zip,
                     sources[1].dataset AS overture_source, ST_X(geometry) AS lon, ST_Y(geometry) AS lat
              FROM read_parquet('s3://overturemaps-us-west-2/release/{OVERTURE_RELEASE}/theme=places/type=place/*')
              WHERE bbox.xmin > -180 AND bbox.xmax < -66 AND bbox.ymin > 18 AND bbox.ymax < 72
                AND taxonomy.primary IN ('child_care_and_day_care', 'day_care_preschool', 'preschool', 'kindergarten')
            ) TO '{_path}.part' (FORMAT parquet)""")
        _path.with_suffix(".parquet.part").rename(_path)
    _raw = pd.read_parquet(_path)
    overture_closed = len(in_state(_raw[_raw["operating_status"] == "permanently_closed"]))
    overture = in_state(_raw[_raw["operating_status"] != "permanently_closed"])
    overture["name"] = overture["name"].fillna("")
    overture["source"] = "Overture Places"
    overture["licence"] = "CDLA-Permissive-2.0"
    return overture, overture_closed


@app.cell
def _(DATA, HEADERS, in_state, json, pd, requests, states, time):
    _path = DATA / "head_start_centers.json"
    if not _path.exists():
        _all = []
        for _state in sorted(states["state"]):
            for _attempt in range(4):
                _r = requests.get(
                    "https://headstart.gov/eclkc-apis/locator/center",
                    params={"state": _state},
                    headers=HEADERS,
                    timeout=120,
                )
                if _r.status_code == 200:
                    break
                time.sleep(5 * 2**_attempt)
            _r.raise_for_status()
            _body = _r.json()
            assert _body["results"] == len(_body["documents"]), f"Head Start {_state}: paged answer"
            _all += _body["documents"]
        _path.write_text(json.dumps(_all))
    _docs = pd.DataFrame(json.loads(_path.read_text()))
    _open = _docs[_docs["status"] == "Open"]
    head_start = in_state(
        pd.DataFrame(
            {
                "source_id": _open["cid"].astype(str),
                "kind": "head_start",
                "name": _open["name"].fillna(""),
                "street": _open["addressLineOne"],
                "city": _open["city"],
                "zip": _open["zipFive"],
                "capacity": pd.to_numeric(_open["slots"], errors="coerce"),
                "lon": pd.to_numeric(_open["longitude"], errors="coerce"),
                "lat": pd.to_numeric(_open["latitude"], errors="coerce"),
            }
        ).dropna(subset=["lon", "lat"])
    )
    head_start["source"] = "ACF Head Start"
    head_start["licence"] = "US government work"
    return (head_start,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. The rosters we compare

    Thirteen states have a current roster with coordinates that one request (or a paged API) returns: **CA, DC,
    DE, MA, MD, MI, NJ, NY, PA, TN, VT, WA, WI**. They include the two states HIFLD Next still covers (NY, WA),
    the largest (CA) and a spread of sizes. Arizona and Minnesota have stale layers, Utah's is another agency's
    geocode of a PDF, Kentucky's is the subsidy list, and eight states (CO, CT, FL, ID, IN, MO, SD, TX) have
    addresses but no coordinates; those wait for a sub-issue that geocodes them.

    Each roster is cut to current, licensed (or registered) facilities and every row gets a **kind**:

    - **centre**: child care centres, preschools, school-age programmes and licensed programmes in schools;
    - **home**: family and group child care homes, which are run from a residence.

    The open maps hardly ever list a family home (and several states withhold home addresses), so the comparison
    is about centres; homes are counted so the scale of what open maps can't hold is visible.
    """)
    return


@app.cell
def _(DATA, HEADERS, pd, requests, time):
    def get(url: str, params: dict | None = None) -> requests.Response:
        """GET with four tries and backoff: state GIS servers answer 503 now and then."""
        for attempt in range(4):
            response = requests.get(url, params=params, headers=HEADERS, timeout=600)
            if response.status_code == 200:
                return response
            time.sleep(10 * 2**attempt)
        response.raise_for_status()
        raise RuntimeError(f"{url}: HTTP {response.status_code}")

    def download(url: str, name: str) -> bytes:
        """GET url once into DATA/name; later runs reuse the copy."""
        path = DATA / name
        if not path.exists():
            path.write_bytes(get(url).content)
        return path.read_bytes()

    def arcgis(layer_url: str, name: str) -> pd.DataFrame:
        """Every feature of an ArcGIS layer, 1,000 at a time (at most 100 pages), as attributes plus lon/lat."""
        path = DATA / name
        if not path.exists():
            rows: list[dict] = []
            for page in range(100):
                params = {
                    "where": "1=1",
                    "outFields": "*",
                    "outSR": 4326,
                    "f": "json",
                    "resultOffset": page * 1000,
                    "resultRecordCount": 1000,
                }
                body = get(f"{layer_url}/query", params).json()
                assert "features" in body, f"{layer_url}: {body.get('error')}"
                rows += [
                    {
                        **f["attributes"],
                        "lon": (f.get("geometry") or {}).get("x"),
                        "lat": (f.get("geometry") or {}).get("y"),
                    }
                    for f in body["features"]
                ]
                if not body.get("exceededTransferLimit"):
                    break
            else:
                raise RuntimeError(f"{layer_url}: more than 100 pages")
            pd.DataFrame(rows).to_csv(path, index=False)
        return pd.read_csv(path, dtype=str)

    return arcgis, download


@app.cell
def _(arcgis, download, io, pd):
    def socrata(url: str, name: str) -> pd.DataFrame:
        return pd.read_csv(io.BytesIO(download(url, name)), dtype=str)

    def frame(state: str, raw: pd.DataFrame, kind: pd.Series, **columns: str) -> pd.DataFrame:
        """One roster in the common shape: state, source_id, name, kind, street, city, zip, capacity, lon, lat."""
        out = pd.DataFrame({key: raw[col] for key, col in columns.items()})
        out["state"] = state
        out["kind"] = kind.values
        out["lon"] = pd.to_numeric(out["lon"], errors="coerce")
        out["lat"] = pd.to_numeric(out["lat"], errors="coerce")
        out["capacity"] = pd.to_numeric(out.get("capacity"), errors="coerce")
        return out

    def where(values: pd.Series, centre: set[str], home: set[str]) -> pd.Series:
        """Map a roster's type column to centre / home; anything else is dropped later."""
        clean = values.fillna("").str.strip()
        return clean.map(lambda v: "centre" if v in centre else "home" if v in home else "")

    _parts = []

    _ny = socrata("https://data.ny.gov/resource/cb42-qumz.csv?$limit=100000", "roster_ny.csv")
    _ny = _ny[_ny["facility_status"].isin(["License", "Registration"])]
    _ny["street"] = _ny["street_number"].fillna("") + " " + _ny["street_name"].fillna("")
    _parts.append(
        frame(
            "NY",
            _ny,
            where(_ny["program_type"], {"DCC", "SDCC", "SACC"}, {"FDC", "GFDC"}),
            source_id="facility_id",
            name="facility_name",
            street="street",
            city="city",
            zip="zip_code",
            capacity="total_capacity",
            lon="longitude",
            lat="latitude",
        )
    )
    _nyc = socrata("https://data.cityofnewyork.us/resource/gy3q-4tzp.csv?$limit=100000", "roster_nyc.csv")
    _parts.append(
        frame(
            "NY",
            _nyc,
            where(_nyc["facility_type"], {"GCC", "SBCC"}, set()),
            source_id="dcid",
            name="program_name",
            street="address",
            city="borough",
            zip="zipcode",
            capacity="capacity",
            lon="longitude",
            lat="latitude",
        )
    )

    _ca = download(
        "https://gis.data.chhs.ca.gov/api/download/v1/items/db31b0884a074cff9260facb3f2ade45/csv?layers=0",
        "roster_ca.csv",
    )
    _ca = pd.read_csv(io.BytesIO(_ca), dtype=str)
    _ca = _ca[_ca["STATUS"] == "3"]  # 3 = licensed in CCLD's status codes
    _ca_centres = {"DAY CARE CENTER", "INFANT CENTER", "SINGLE CHILD CARE CE", "SCHOOL-AGE DC CENTER"}
    _parts.append(
        frame(
            "CA",
            _ca,
            where(_ca["FAC_TYPE_DESC"], _ca_centres, set()),
            source_id="FAC_NBR",
            name="NAME",
            street="RES_STREET_ADDR",
            city="RES_CITY",
            zip="RES_ZIP_CODE",
            capacity="CAPACITY",
            lon="FAC_LONGITUDE",
            lat="FAC_LATITUDE",
        )
    )

    _pa = socrata("https://data.pa.gov/resource/ajn5-kaxt.csv?$limit=100000", "roster_pa.csv")
    _pa_xy = _pa["geocoded_column"].str.extract(r"POINT \(([-\d.]+) ([-\d.]+)\)")
    _pa["lon"], _pa["lat"] = _pa_xy[0], _pa_xy[1]
    _parts.append(
        frame(
            "PA",
            _pa,
            where(_pa["provider_type"], {"Child Care Center"}, {"Family Child Care Home", "Group Child Care Home"}),
            source_id="master_provider_index",
            name="facility_name",
            street="facility_address",
            city="facility_city",
            zip="facility_zip_code",
            capacity="capacity",
            lon="lon",
            lat="lat",
        )
    )

    _ma = socrata("https://educationtocareer.data.mass.gov/resource/iyks-y3g6.csv?$limit=100000", "roster_ma.csv")
    _ma = _ma[(_ma["licensed_funded"] == "Licensed") & (_ma["licensed_provider_status"] != "Expired")]
    _parts.append(
        frame(
            "MA",
            _ma,
            where(_ma["program_type"], {"Center-based Care", "Public School", "Private School"}, {"Family Child Care"}),
            source_id="provider_number",
            name="program_name",
            street="program_street_address1",
            city="program_city",
            zip="program_zipcode",
            capacity="licensed_capacity",
            lon="program_longitude",
            lat="program_latitude",
        )
    )

    _mi = download(
        "https://gis-michigan.opendata.arcgis.com/api/download/v1/items/a79c3b0caedf412599085941e2af91d4/csv?layers=5",
        "roster_mi.csv",
    )
    _mi = pd.read_csv(io.BytesIO(_mi), dtype=str)
    _parts.append(
        frame(
            "MI",
            _mi,
            where(_mi["FacilityType"], {"Center"}, {"Family Home (1-6)", "Group Home (7-12)"}),
            source_id="LicenseNumber",
            name="FacilityName",
            street="StreetAddress",
            city="City",
            zip="ZIPCode",
            capacity="Capacity",
            lon="Longitude",
            lat="Latitude",
        )
    )

    _wa = socrata("https://data.wa.gov/resource/was8-3ni8.csv?$limit=100000", "roster_wa.csv")
    _wa = _wa[_wa["latestoperatingstatus"] == "Active"]
    _parts.append(
        frame(
            "WA",
            _wa,
            where(
                _wa["facilitytypegeneric"],
                {"CHILD CARE CENTER", "SCHOOL-AGE PROGRAM", "OUTDOOR NATURE BASED PROGRAM"},
                set(),
            ),
            source_id="wacompassid",
            name="providername",
            street="physicalstreetaddress",
            city="physicalcity",
            zip="physicalzip",
            capacity="licensecapacity",
            lon="physicallongitude",
            lat="physciallatitude",
        )
    )

    _wi = arcgis("https://dhsgis.wi.gov/server/rest/services/DHS_DCF/Child_Care/MapServer/0", "roster_wi.csv")
    _parts.append(
        frame(
            "WI",
            _wi,
            where(
                _wi["CategoryType"],
                {"LICENSED GROUP", "PUBLIC SCHOOL PROGRAM"},
                {"LICENSED FAMILY", "REGULAR CERTIFIED", "PROVISIONAL CERTIFIED"},
            ),
            source_id="OBJECTID",
            name="FacilityName",
            street="LocationLineAddress1",
            city="City",
            zip="ZipCode",
            capacity="Capacity",
            lon="lon",
            lat="lat",
        )
    )

    _tn = arcgis(
        "https://services1.arcgis.com/YuVBSS7Y1of2Qud1/arcgis/rest/services/Active_ChildCare_Locations/FeatureServer/0",
        "roster_tn.csv",
    )
    _parts.append(
        frame(
            "TN",
            _tn,
            where(
                _tn["Child_Care_Type"],
                {"Child Care Center", "Drop-in Child Care Center"},
                {"Group Child Care Home", "Family Child Care Home"},
            ),
            source_id="Provider_ID",
            name="Provider_Name",
            street="Street_Address",
            city="City",
            zip="Zip",
            lon="lon",
            lat="lat",
        )
    )

    _md = arcgis(
        "https://services.arcgis.com/njFNhDsUCentVYJW/arcgis/rest/services/ChildCare_All_Active_Providers_May_20_2024/FeatureServer/0",
        "roster_md.csv",
    )
    _parts.append(
        frame(
            "MD",
            _md,
            where(
                _md["Provider_Type"],
                {"Child Care Center", "School-Age Only", "Public Prekindergarten", "LOC"},
                {"Family Child Care", "Large Family Child Care"},
            ),
            source_id="License_Number",
            name="Facility_Name",
            street="Street_Address",
            city="City",
            zip="Zip_Code",
            lon="Longitude_API",
            lat="Latitude_API",
        )
    )

    _de = socrata("https://data.delaware.gov/resource/iuzd-3dbt.csv?$limit=100000", "roster_de.csv")
    _de_xy = _de["geocoded_location"].str.extract(r"POINT \(([-\d.]+) ([-\d.]+)\)")
    _de["lon"], _de["lat"] = _de_xy[0], _de_xy[1]
    _parts.append(
        frame(
            "DE",
            _de,
            where(
                _de["resource_type"],
                {"Licensed Child Care Center"},
                {"Licensed Family Child Care", "Licensed Large Family Child Care"},
            ),
            source_id="resource_id",
            name="resource_name",
            street="site_street_address",
            city="site_city",
            zip="site_zip_code",
            capacity="capacity",
            lon="lon",
            lat="lat",
        )
    )

    _vt = socrata("https://data.vermont.gov/resource/ctdw-tmfz.csv?$limit=100000", "roster_vt.csv")
    _vt = _vt[_vt["provider_referral_status"] != "Inactive"]
    _parts.append(
        frame(
            "VT",
            _vt,
            where(
                _vt["provider_program_type"],
                {"CBCCPP", "CBCCPP - Non-Recurring", "Afterschool Child Care Program"},
                {"Licensed FCCH", "Registered FCCH"},
            ),
            source_id="provider_id",
            name="provider_name",
            street="address_1",
            city="provider_town",
            zip="zip_code",
            capacity="total_licensed_capacity",
            lon="longitude",
            lat="latitude",
        )
    )

    _dc = arcgis(
        "https://maps2.dcgis.dc.gov/dcgis/rest/services/DCGIS_DATA/Public_Service_WebMercator/MapServer/33",
        "roster_dc.csv",
    )
    _dc = _dc[_dc["LICENSE_TYPE"] != "Expired"]
    _parts.append(
        frame(
            "DC",
            _dc,
            _dc["LICENSE_NUMBER"].str[:3].map({"CDC": "centre", "CDH": "home", "CDX": "home"}),
            source_id="LICENSE_NUMBER",
            name="NAME",
            street="ADDRESS",
            city="ADDRESS",
            zip="ZIPCODE",
            capacity="AUTHORIZED_CAPACITY",
            lon="lon",
            lat="lat",
        )
    )

    _nj = arcgis("https://mapsdep.nj.gov/arcgis/rest/services/Features/Structures/MapServer/4", "roster_nj.csv")
    _parts.append(
        frame(
            "NJ",
            _nj,
            pd.Series("centre", index=_nj.index),
            source_id="center_id",
            name="center_name",
            street="address",
            city="city",
            zip="zip",
            capacity="licensed_capacity",
            lon="lon",
            lat="lat",
        )
    )

    roster_all = pd.concat(_parts, ignore_index=True)
    roster_all["kind"] = roster_all["kind"].fillna("")
    roster_all["name"] = roster_all["name"].fillna("").str.strip()
    assert set(roster_all["state"]) == {"NY", "CA", "PA", "MA", "MI", "WA", "WI", "TN", "MD", "DE", "VT", "DC", "NJ"}
    return (roster_all,)


@app.cell
def _(in_state, pd, roster_all):
    _kept = roster_all[roster_all["kind"] != ""]
    _located = _kept.dropna(subset=["lon", "lat"])
    _placed = in_state(_located.rename(columns={"state": "roster_state"}))
    # A roster point that falls outside its own state (or at 0, 0) is a bad geocode: drop it and count it.
    roster = _placed[_placed["state"] == _placed["roster_state"]].drop(columns="roster_state").reset_index(drop=True)
    roster["source_id"] = roster["state"] + ":" + roster["source_id"].astype(str)
    assert roster["source_id"].duplicated().sum() < 10, "roster IDs aren't unique"
    roster = roster.drop_duplicates("source_id").reset_index(drop=True)
    roster["source"] = "State roster"
    roster["licence"] = (
        roster["state"]
        .map({"DE": "Public domain", "PA": "Public domain", "DC": "CC BY 4.0", "VT": "ODbL-1.0"})
        .fillna("State open data (terms vary, see rosters.csv)")
    )
    roster_losses = (
        pd.DataFrame(
            {
                "rows read": roster_all.groupby("state").size(),
                "other types dropped": roster_all[roster_all["kind"] == ""].groupby("state").size(),
                "no coordinates": _kept[_kept["lon"].isna() | _kept["lat"].isna()].groupby("state").size(),
                "point outside the state": _located.groupby("state").size() - roster.groupby("state").size(),
                "centres kept": roster[roster["kind"] == "centre"].groupby("state").size(),
                "homes kept": roster[roster["kind"] == "home"].groupby("state").size(),
            }
        )
        .fillna(0)
        .astype(int)
    )
    roster_losses
    return roster, roster_losses


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Matching, as in the HIFLD crosswalk

    The matching follows `hifld-overture-crosswalk/`: a pair is the **same facility** when the two points are within
    250 m and their names agree (rapidfuzz token-set ratio of the distinctive words ≥ 85), or within 50 m whatever
    the names say (the same building or lot, where a centre is often listed under its operator's name).
    Child care names are full of generic words, so "Little Sprouts Learning Center" and "Little Sprouts Child
    Care" are compared on "little sprouts". Two names that both carry numbers must share one.

    For each pair of sources in a roster state we count:

    - **found**: roster facilities with a same-facility match on the open map;
    - **agree**: open-map features with a same-facility roster match;
    - **disagree**: open-map features with a roster facility within 250 m but no name match (another
      business, a renamed centre, or a wrong point);
    - **open-map only**: open-map features with no roster facility within 250 m (unlicensed or license-exempt care,
      a closed centre, a misclassified business, or a gap in the roster).
    """)
    return


@app.cell
def _(METRIC, fuzz, gpd, pd):
    import re

    _GENERIC = set(
        "the of and at a an inc llc ltd co corp child children childrens kid kids care childcare daycare day "
        "center centre centers learning early education educational development developmental academy school "
        "preschool pre k pk nursery kindergarten montessori program programs head start family home group "
        "infant toddler house place club before after".split()
    )

    def normalise(name: str) -> tuple[str, str, frozenset[str]]:
        """(full normalised name, its distinctive words, the numbers in it)."""
        words = re.sub(r"[^a-z0-9 ]+", " ", str(name).lower().replace("&", " and ").replace("'", "")).split()
        distinctive = [w for w in words if w not in _GENERIC and not w.isdigit()]
        return " ".join(words), " ".join(distinctive), frozenset(w for w in words if w.isdigit())

    def name_score(a: str, b: str) -> float:
        """0-100 name agreement; 0 when both names carry numbers and share none."""
        na, nb = normalise(a), normalise(b)
        if not na[0] or not nb[0] or (na[2] and nb[2] and not (na[2] & nb[2])):
            return 0.0
        if na[1] and nb[1]:
            return float(fuzz.token_set_ratio(na[1], nb[1]))
        return float(fuzz.token_sort_ratio(na[0], nb[0]))

    def match(left: gpd.GeoDataFrame, right: gpd.GeoDataFrame) -> pd.DataFrame:
        """Every left-right pair within 250 m, with distance, name score and whether it's the same facility."""
        a = left[["source_id", "name", "geometry"]].to_crs(METRIC)
        b = right[["source_id", "name", "geometry"]].to_crs(METRIC)
        pairs = gpd.sjoin(a, b, predicate="dwithin", distance=250, lsuffix="l", rsuffix="r")
        pairs["distance_m"] = pairs.geometry.distance(b.geometry.loc[pairs["index_r"]].set_axis(pairs.index))
        pairs["name_score"] = [name_score(x, y) for x, y in zip(pairs["name_l"], pairs["name_r"], strict=True)]
        pairs["same"] = (pairs["name_score"] >= 85) | (pairs["distance_m"] <= 50)
        return pd.DataFrame(pairs.drop(columns=["geometry", "index_r"]))

    return match, name_score, normalise


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Counts per state

    Every state, with the open-map counts next to Head Start and, in the thirteen roster states, the roster's
    centres and homes. *Open maps, deduplicated* counts OSM and Overture features once when they match each other.
    """)
    return


@app.cell
def _(head_start, match, osm, overture, pd, roster, states, survey):
    _osm_overture = match(osm, overture)
    _osm_in_overture = set(_osm_overture.loc[_osm_overture["same"], "source_id_l"])
    counts = pd.DataFrame(index=sorted(states["state"]))
    counts["OSM childcare"] = osm[osm["kind"] == "childcare"].groupby("state").size()
    counts["OSM kindergarten"] = osm[osm["kind"] == "kindergarten"].groupby("state").size()
    counts["Overture"] = overture.groupby("state").size()
    counts["open maps, deduplicated"] = counts["Overture"].fillna(0) + osm[
        ~osm["source_id"].isin(_osm_in_overture)
    ].groupby("state").size().reindex(counts.index).fillna(0)
    counts["Head Start (open)"] = head_start.groupby("state").size()
    counts["roster centres"] = roster[roster["kind"] == "centre"].groupby("state").size()
    counts["roster homes"] = roster[roster["kind"] == "home"].groupby("state").size()
    counts = counts.fillna(0).astype(int)
    counts.loc["US total"] = counts.sum()
    counts["survey roster rows"] = survey.set_index("state")["record_count"].reindex(counts.index).fillna("")
    counts.index.name = "state"
    counts
    return (counts,)


@app.cell
def _(counts, mo, overture_closed):
    _roster_states = counts[counts["roster centres"] > 0].drop(index="US total")
    _ratio = _roster_states["open maps, deduplicated"].sum() / _roster_states["roster centres"].sum()
    mo.md(f"""
    Across the thirteen roster states the open maps hold **{_roster_states["open maps, deduplicated"].sum():,}**
    child care features against **{_roster_states["roster centres"].sum():,}** licensed centres
    (and {_roster_states["roster homes"].sum():,} licensed homes): {_ratio:.0%} as many features as centres. Raw
    counts flatter the maps, though: section 6 asks how many of those features are the licensed centres.
    Overture places marked permanently closed were dropped first: {overture_closed:,} in the 51 states.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Do the open maps find the licensed centres?

    In each roster state, every open-map feature is matched against all roster facilities (centres and homes, so a
    home listed on a map counts as agreeing), and every roster centre against the open map. *Either map* is a
    roster centre found on OSM or on Overture.
    """)
    return


@app.cell
def _(head_start, match, osm, overture, pd, roster):
    _rows = []
    roster_found: dict[str, set[str]] = {}
    open_only: dict[str, pd.DataFrame] = {}
    pairs_by_map: dict[str, pd.DataFrame] = {}
    for _label, _map in [("OSM", osm), ("Overture", overture)]:
        _sub = _map[_map["state"].isin(roster["state"].unique())]
        _pairs = match(_sub, roster)
        pairs_by_map[_label] = _pairs
        _same = _pairs[_pairs["same"]]
        _centres = set(roster.loc[roster["kind"] == "centre", "source_id"])
        roster_found[_label] = set(_same["source_id_r"]) & _centres
        _near = set(_pairs["source_id_l"])
        _agree = set(_same["source_id_l"])
        open_only[_label] = _sub[~_sub["source_id"].isin(_near)]
        for _state, _g in _sub.groupby("state"):
            _ids = set(_g["source_id"])
            _state_centres = set(roster.loc[(roster["kind"] == "centre") & (roster["state"] == _state), "source_id"])
            _rows.append(
                {
                    "state": _state,
                    "map": _label,
                    "features": len(_ids),
                    "agree": len(_ids & _agree),
                    "disagree": len((_ids & _near) - _agree),
                    "open-map only": len(_ids - _near),
                    "roster centres": len(_state_centres),
                    "centres found": len(_state_centres & roster_found[_label]),
                }
            )
    match_rates = pd.DataFrame(_rows)
    _total = match_rates.groupby("map").sum(numeric_only=True).reset_index().assign(state="all 13")
    match_rates = pd.concat([match_rates, _total], ignore_index=True)
    match_rates["found %"] = (100 * match_rates["centres found"] / match_rates["roster centres"]).round(1)
    match_rates["agree %"] = (100 * match_rates["agree"] / match_rates["features"]).round(1)
    match_rates["disagree % of near"] = (
        100 * match_rates["disagree"] / (match_rates["agree"] + match_rates["disagree"])
    ).round(1)
    match_rates["open-map only %"] = (100 * match_rates["open-map only"] / match_rates["features"]).round(1)

    _centres_by_state = roster[roster["kind"] == "centre"].groupby("state")["source_id"].apply(set)
    _either = roster_found["OSM"] | roster_found["Overture"]
    either_map = pd.DataFrame(
        {
            "roster centres": _centres_by_state.map(len),
            "found on either map": _centres_by_state.map(lambda ids: len(ids & _either)),
        }
    )
    either_map.loc["all 13"] = either_map.sum()
    either_map["found %"] = (100 * either_map["found on either map"] / either_map["roster centres"]).round(1)

    # Head Start centres are federally funded and almost all must hold a state licence, so they test the rosters.
    _hs = head_start[head_start["state"].isin(roster["state"].unique())]
    _hs_pairs = match(_hs, roster)
    _hs_found = set(_hs_pairs.loc[_hs_pairs["same"], "source_id_l"])
    head_start_in_roster = (
        _hs.assign(in_roster=_hs["source_id"].isin(_hs_found)).groupby("state")["in_roster"].agg(["size", "sum"])
    )
    head_start_in_roster.columns = ["Head Start centres", "in the roster"]
    head_start_in_roster.loc["all 13"] = head_start_in_roster.sum()
    head_start_in_roster["%"] = (
        100 * head_start_in_roster["in the roster"] / head_start_in_roster["Head Start centres"]
    ).round(1)
    match_rates
    return either_map, head_start_in_roster, match_rates, open_only, pairs_by_map, roster_found


@app.cell
def _(either_map):
    either_map
    return


@app.cell
def _(head_start_in_roster, mo):
    mo.vstack(
        [
            mo.md(
                "Head Start centres found in the roster (same matching rule). A low share means the roster "
                "leaves out school-run or exempt programmes, or the two disagree on names and points."
            ),
            head_start_in_roster,
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Hand check

    A seeded sample (seed 301) from the roster states, in four groups:

    - 25 **Overture-only** and 25 **OSM-only** features (no roster facility within 250 m): is it a licensed
      child care facility the roster lacks, a licence-exempt programme (public pre-K, a church or school
      programme, a camp), not child care at all, or closed?
    - 25 **roster centres found on neither map**: does the centre exist and operate at that address?
    - 25 **agreeing matches**: is the match the same facility?

    Each was labelled by an AI subagent from web search (the provider's site, the state licence search, listings,
    news), given the record and its source in shuffled order but not its group. Labels and the evidence URL for
    each are in `hand_check.csv` (no OSM names in it); the sample is rebuilt by the cell below, so a rerun checks
    the labels still line up with it.
    """)
    return


@app.cell
def _(OUT, open_only, pairs_by_map, pd, roster, roster_found):
    _seed = 301
    _overture_only = open_only["Overture"].sample(25, random_state=_seed)
    _osm_only = open_only["OSM"].sample(25, random_state=_seed)
    _centres = roster[roster["kind"] == "centre"]
    _missed = _centres[~_centres["source_id"].isin(roster_found["OSM"] | roster_found["Overture"])]
    _missed = _missed.sample(25, random_state=_seed)
    _agreeing = _centres[_centres["source_id"].isin(roster_found["Overture"])].sample(25, random_state=_seed)

    def _rows(frame: pd.DataFrame, group: str) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "group": group,
                "source": frame["source"].values,
                "source_id": frame["source_id"].values,
                "name": frame["name"].values,
                "street": frame.get("street", pd.Series("", index=frame.index)).fillna("").values,
                "city": frame.get("city", pd.Series("", index=frame.index)).fillna("").values,
                "state": frame["state"].values,
                "lat": frame["lat"].round(5).values,
                "lon": frame["lon"].round(5).values,
            }
        )

    _best = (
        pairs_by_map["Overture"][pairs_by_map["Overture"]["same"]]
        .sort_values(["name_score", "distance_m"], ascending=[False, True])
        .drop_duplicates("source_id_r")
        .set_index("source_id_r")
    )
    _agree_rows = _rows(_agreeing, "agree")
    _agree_rows["matched_name"] = _agree_rows["source_id"].map(_best["name_l"])
    _agree_rows["matched_m"] = _agree_rows["source_id"].map(_best["distance_m"]).round()
    hand_sample = pd.concat(
        [
            _rows(_overture_only, "overture_only"),
            _rows(_osm_only, "osm_only"),
            _rows(_missed, "roster_missed"),
            _agree_rows,
        ],
        ignore_index=True,
    )
    # The sample has OSM names, so it is ODbL; it stays in output/ and is not committed.
    hand_sample.to_csv(OUT / "hand_check_sample_osm.csv", index=False)
    return (hand_sample,)


@app.cell
def _(OUT, hand_sample, pd):
    import pathlib

    _labels = pd.read_csv(pathlib.Path(__file__).parent / "hand_check.csv", dtype=str).fillna("")
    hand_check = hand_sample[["group", "source", "source_id"]].merge(
        _labels[["source", "source_id", "label", "same_facility"]], on=["source", "source_id"], how="left"
    )
    assert hand_check["label"].notna().all(), "hand_check.csv doesn't cover the sample: relabel it"
    hand_summary = pd.crosstab(hand_check["group"], hand_check["label"], margins=True)
    hand_summary.to_csv(OUT / "hand_check_summary.csv")
    same_facility = hand_check.loc[hand_check["group"] == "agree", "same_facility"].value_counts()
    hand_summary
    return hand_check, hand_summary, same_facility


@app.cell
def _(mo, same_facility):
    mo.md(f"Agreeing matches judged the same facility: {same_facility.to_dict()}")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. A combined layer, and its licence

    The layer below is what a rebuild would hold today: the thirteen rosters, then Head Start centres no roster
    matches, then Overture places that match neither, then OSM features that match none of the above. Every row
    keeps its source and licence. It's written to `output/child_care_layer.parquet` (GeoParquet) and, without the
    OSM rows, to `output/child_care_layer_no_osm.parquet`. Neither is committed: the first is an ODbL Derivative
    Database.
    """)
    return


@app.cell
def _(OUT, gpd, head_start, match, osm, overture, pd, roster):
    _cols = ["source", "source_id", "name", "kind", "state", "capacity", "licence", "geometry"]

    def _unmatched(frame: gpd.GeoDataFrame, base: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        pairs = match(frame, base)
        return frame[~frame["source_id"].isin(set(pairs.loc[pairs["same"], "source_id_l"]))]

    _hs_new = _unmatched(head_start, roster)
    _base = pd.concat([roster, _hs_new], ignore_index=True)
    _ov_new = _unmatched(overture, gpd.GeoDataFrame(_base, crs=4326))
    _base2 = pd.concat([_base, _ov_new], ignore_index=True)
    _osm_new = _unmatched(osm, gpd.GeoDataFrame(_base2, crs=4326))
    layer = gpd.GeoDataFrame(
        pd.concat([_base2, _osm_new], ignore_index=True).reindex(columns=_cols), geometry="geometry", crs=4326
    )
    layer["capacity"] = pd.to_numeric(layer["capacity"], errors="coerce")
    layer.to_parquet(OUT / "child_care_layer.parquet")
    layer[layer["source"] != "OpenStreetMap"].to_parquet(OUT / "child_care_layer_no_osm.parquet")
    layer_summary = layer.groupby(["source", "licence"]).size().rename("rows").reset_index()
    layer_summary
    return layer, layer_summary


@app.cell
def _(either_map, hand_summary, head_start_in_roster, layer, match_rates, mo, same_facility):
    _all = match_rates[match_rates["state"] == "all 13"].set_index("map")
    _either = either_map.loc["all 13", "found %"]
    _right = same_facility.get("yes", 0) / same_facility.sum()
    _osm_rows = int((layer["source"] == "OpenStreetMap").sum())
    mo.md(f"""
    ## 9. The answer

    **Open maps can't rebuild the layer; rosters can, for about half the states.** Overture finds
    {_all.loc["Overture", "found %"]:.0f}% of licensed centres in the thirteen roster states, OSM
    {_all.loc["OSM", "found %"]:.0f}% and the two together {_either:.0f}%; the hand check judged
    {_right:.0%} of matches the same facility, so the true share is lower still. The centres both maps miss are
    real: {hand_summary.loc["roster_missed", "licensed"]} of 25 sampled were operating licensed centres.
    Of 50 sampled open-map-only features, {
        hand_summary.loc["overture_only", "licensed"] + hand_summary.loc["osm_only", "licensed"]
    } were licensed providers the roster missed or placed more than
    250 m away (mostly family homes), {
        hand_summary.loc["overture_only", "closed"] + hand_summary.loc["osm_only", "closed"]
    } had closed and the rest were exempt or couldn't be confirmed.

    **Licence.** The rosters are public domain or open state data (Vermont's is ODbL, DC's CC BY 4.0). Overture
    Places (CDLA-Permissive 2.0) needs only attribution, so a roster + Head Start + Overture layer can be published
    openly. Adding OSM makes the whole layer an ODbL Derivative Database with share-alike, and buys only
    {_osm_rows:,} extra rows. That's the rights decision HIFLD Next would need to record; this notebook doesn't
    make it.

    **What didn't work or isn't shown.** Name matching across sources is loose: the 50 m rule pairs a roster
    centre with whatever shares its building, which is where the wrong matches come from. Roster type columns
    differ by state, so *centre* and *home* are our mapping (in the roster cell). Head Start centres are found in
    the rosters only {
        head_start_in_roster.loc[
            "all 13", "%"
        ]:.0f}% of the time, low in PA and WA, where school-run and federally run sites sit
    outside the state list or under another name. The hand check labels are AI subagents' calls from
    third-party directories (state search pages mostly refused scripted access), not checked by a person.
    Thirteen states were compared; eight more with addresses only, and the form and PDF states, are in #310.
    """)
    return


@app.cell
def _(OUT, STARTED, counts, either_map, head_start_in_roster, match_rates, mo, survey_summary, time):
    counts.to_csv(OUT / "counts_by_state.csv")
    head_start_in_roster.to_csv(OUT / "head_start_in_roster.csv")
    match_rates.to_csv(OUT / "match_rates.csv", index=False)
    either_map.to_csv(OUT / "found_on_either_map.csv")
    survey_summary.to_csv(OUT / "survey_summary.csv", index=False)
    mo.md(f"Run time: **{(time.time() - STARTED) / 60:.1f} minutes**; cost $0 (public downloads only).")
    return


if __name__ == "__main__":
    app.run()

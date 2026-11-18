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
    survey_summary = pd.DataFrame(
        {
            "states (incl. DC)": [len(survey)],
            "machine-readable roster": [(survey["machine_readable"] == "yes").sum()],
            "… with coordinates": [((survey["machine_readable"] == "yes") & (survey["coords"] == "yes")).sum()],
            "… with street addresses": [((survey["machine_readable"] == "yes") & (survey["address"] == "yes")).sum()],
            "search form or PDF only": [survey["format"].str.contains("search|PDF", case=False).sum()],
        }
    )
    survey_summary
    return survey, survey_summary


@app.cell
def _(survey):
    survey[["state", "agency", "format", "machine_readable", "coords", "address", "record_count", "updated"]]
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
    overture_closed = int((_raw["operating_status"] == "permanently_closed").sum())
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
                    "https://headstart.gov/eclkc-apis/locator/center", params={"state": _state}, headers=HEADERS,
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


if __name__ == "__main__":
    app.run()

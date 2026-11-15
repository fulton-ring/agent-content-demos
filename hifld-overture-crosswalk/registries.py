import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import io
    import time
    import urllib.request
    import zipfile
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import numpy as np
    import pandas as pd
    import shapely

    from shared import (
        DATA,
        HERE,
        LAYERS,
        METRIC,
        OUT,
        OVERTURE,
        OVERTURE_RELEASE,
        US_BOXES,
        USER_AGENT,
        box_filter,
        fetch,
        hifld_files,
        name_score,
        normalise,
        overture_connection,
        qlever_tsv,
        read_hifld,
    )

    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    REVIEW = HERE / "review"
    # Pinned registry releases, so a rerun reads the same data. Newer releases are listed on each source's page.
    CMS_POS_HOSPITALS = (
        "https://data.cms.gov/sites/default/files/2026-10/e5a8afbb-a1f4-4d3b-bdb9-3968e194da0e/"
        "Hospital_and_other.DATA.Q3_2026.csv"
    )
    CMS_POS_IQIES = (
        "https://data.cms.gov/sites/default/files/2026-10/d7e32873-6bf0-4719-9048-376972900d5c/"
        "POS_iQIES.DATA.Q3_2026.csv"
    )
    NCES_CCD = "https://nces.ed.gov/ccd/data/zip/ccd_sch_029_2526_w_0a_050626.zip"
    NCES_EDGE = "https://nces.ed.gov/programs/edge/data/EDGE_GEOCODE_PUBLICSCH_2425.zip"
    EIA_860 = "https://www.eia.gov/electricity/data/eia860/xls/eia8602025.zip"
    USFA_STATIONS = "https://apps.usfa.fema.gov/registry/api/download/station"
    CENSUS_GEOCODER = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
    NEAR = 250  # metres: the same campus or block, as in crosswalk.py
    MATCH = 85  # name score that counts as the same name, as in crosswalk.py
    RUN_STARTED = time.perf_counter()


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Which HIFLD Next facilities should be added or removed, judged against official registries?

    `crosswalk.py` matched five HIFLD Next layers to OpenStreetMap and Overture. A match says a facility is on the
    open maps, not that it is open, or that it is the kind of facility the layer says. This notebook asks the
    agencies that license or count each kind of facility:

    | Layer | Official registry | Join |
    |---|---|---|
    | Hospitals | CMS Provider of Services (POS), hospitals and the iQIES file of other providers | name and address |
    | Public schools | NCES Common Core of Data directory, plus NCES EDGE school locations | HIFLD `NCESID` |
    | Power plants | EIA-860 plants and generators | HIFLD `PLANT_CODE` |
    | Fire and EMS, law enforcement | none with station locations (see below), so OSM and Overture | location and name |

    For every HIFLD record it proposes **keep**, **remove**, **retype** or **move**, and from each registry the
    facilities to **add**. A proposal is final only when the open maps agree with it; every disagreement goes to a
    review queue, one CSV per layer, with a reason code and empty columns for a reviewer's decision. Then a hand
    check on dated NAIP aerial imagery measures how often each kind of proposal is right.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## HIFLD Next and the open maps

    The same five layers and the same OSM planet as `crosswalk.py` (the helpers are in `shared.py`; downloads are
    shared through `data/`).
    """)
    return


@app.cell
def _():
    _files = hifld_files()
    _, hifld = read_hifld(_files)
    hifld.groupby("layer").size().rename("records in 50 states + DC")
    return (hifld,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **OSM**, same-kind features, plus those OSM marks as closed with a
    [lifecycle prefix](https://wiki.openstreetmap.org/wiki/Lifecycle_prefix) (`disused:amenity=hospital`,
    `abandoned:power=plant`...).
    """)
    return


@app.cell
def _():
    _frames = []
    for _layer, _spec in LAYERS.iterrows():
        for _key, _value in _spec["osm_tags"]:
            for _prefix in ["", "disused:", "abandoned:"]:
                _tag = f"{_prefix}{_key}"
                _osm = qlever_tsv(_tag, _value, DATA / f"osm-{_tag.replace(':', '-')}-{_value}.tsv")
                _frames.append(_osm.assign(layer=_layer, osm_tag=f"{_tag}={_value}", osm_closed=bool(_prefix)))
    osm = pd.concat(_frames, ignore_index=True).drop_duplicates(["layer", "osm_id"])
    osm.groupby(["layer", "osm_closed"]).size().unstack()
    return (osm,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The registries

    **Hospitals: CMS Provider of Services, Q3 2026.** Every hospital certified for Medicare, active or terminated,
    with its CMS Certification Number (CCN), subtype and termination code. Since 2026 CMS publishes nursing homes,
    surgery centres, clinics and other providers in a separate iQIES file; we read it to catch HIFLD hospitals
    that CMS knows as something else. The iQIES file gives a numeric provider type without a name; the names below
    follow the CCN ranges each type uses (nursing homes 5000–6499, surgery centres `C`, and so on).
    """)
    return


@app.cell
def _():
    _subtypes = {
        "01": "short-term",
        "02": "long-term",
        "03": "religious non-medical",
        "04": "psychiatric",
        "05": "rehabilitation",
        "06": "children's",
        "07": "distinct-part psychiatric",
        "11": "critical access",
        "20": "transplant",
        "22": "Medicaid-only",
        "23": "Medicaid-only psychiatric",
    }
    _terminations = {
        "00": "active",
        "01": "voluntary: merger or closure",
        "02": "voluntary: reimbursement",
        "03": "voluntary: risk of involuntary termination",
        "04": "voluntary: other",
        "05": "involuntary: health and safety",
        "06": "involuntary: agreement",
        "07": "status change",
    }
    _raw = pd.read_csv(fetch(CMS_POS_HOSPITALS, "cms-pos-hospitals-2026q3.csv"), dtype=str, encoding="latin1")
    _raw = _raw[_raw["PRVDR_CTGRY_CD"] == "01"]
    pos = pd.DataFrame(
        {
            "registry_id": _raw["PRVDR_NUM"],
            "reg_name": _raw["FAC_NAME"],
            "reg_address": _raw["ST_ADR"],
            "reg_city": _raw["CITY_NAME"],
            "reg_state": _raw["STATE_CD"],
            "reg_zip": _raw["ZIP_CD"].str[:5],
            "reg_type": "hospital, " + _raw["PRVDR_CTGRY_SBTYP_CD"].map(_subtypes).fillna("other"),
            "reg_status": np.where(_raw["PGM_TRMNTN_CD"] == "00", "active", "terminated"),
            "reg_status_detail": _raw["PGM_TRMNTN_CD"].map(_terminations).fillna(_raw["PGM_TRMNTN_CD"]),
            "reg_date": pd.to_datetime(_raw["TRMNTN_EXPRTN_DT"], format="%Y%m%d", errors="coerce").dt.date.astype(str),
            # Transplant and religious non-medical records aren't hospitals a map would show on their own.
            "reg_in_scope": ~_raw["PRVDR_CTGRY_SBTYP_CD"].isin(["03", "20"]),
        }
    ).reset_index(drop=True)
    pos["reg_link"] = "https://www.medicare.gov/care-compare/details/hospital/" + pos["registry_id"]

    _types = {
        "3": "home health agency",
        "4": "psychiatric residential treatment facility",
        "5": "portable x-ray supplier",
        "6": "outpatient physical therapy",
        "7": "dialysis facility",
        "8": "intermediate care facility (IID)",
        "9": "rural health clinic",
        "10": "outpatient rehabilitation facility",
        "11": "ambulatory surgical centre",
        "12": "hospice",
        "13": "organ procurement organisation",
        "14": "community mental health centre",
        "15": "federally qualified health centre",
        "20": "nursing home",
    }
    _cols = ["prvdr_num", "fac_name", "st_adr", "city_name", "state_cd", "zip_cd", "prvdr_type_id"]
    _iq = pd.read_csv(
        fetch(CMS_POS_IQIES, "cms-pos-iqies-2026q3.csv"),
        dtype=str,
        encoding="latin1",
        usecols=[*_cols, "fed_crtfctn_stus_name"],
    )
    _iq = _iq[_iq["fed_crtfctn_stus_name"] == "Certified"]
    iqies = pd.DataFrame(
        {
            "iqies_id": _iq["prvdr_num"],
            "iqies_name": _iq["fac_name"],
            "iqies_address": _iq["st_adr"],
            "iqies_state": _iq["state_cd"],
            "iqies_zip": _iq["zip_cd"].str[:5],
            "iqies_type": _iq["prvdr_type_id"].map(_types).fillna("other provider"),
        }
    ).reset_index(drop=True)
    mo.md(
        f"CMS hospitals: {len(pos):,} records, {(pos['reg_status'] == 'active').sum():,} active. "
        f"Other certified providers in iQIES: {len(iqies):,}."
    )
    return iqies, pos


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    POS has addresses but no coordinates, so we geocode the hospitals with the US Census Bureau's free
    [batch geocoder](https://geocoding.geo.census.gov/geocoder/) (10,000 addresses a request). An address-range
    geocode can sit 100 m or more from the building, so a move proposed from a geocoded point always goes to review.
    The same function places the few schools new in 2025–26 that EDGE hasn't located yet.
    """)
    return


@app.cell
def _():
    def geocode(rows: pd.DataFrame, name: str) -> pd.DataFrame:
        """rows has id, street, city, state, zip. Returns id, lon, lat, match type; cached in DATA/name."""
        path = DATA / name
        if not path.exists():
            answers = []
            for start in range(0, len(rows), 5000):
                body = io.StringIO()
                rows.iloc[start : start + 5000].to_csv(body, header=False, index=False)
                boundary = "----spike-geocode"
                payload = (
                    f'--{boundary}\r\nContent-Disposition: form-data; name="benchmark"\r\n\r\nPublic_AR_Current\r\n'
                    f'--{boundary}\r\nContent-Disposition: form-data; name="addressFile"; filename="a.csv"\r\n'
                    f"Content-Type: text/csv\r\n\r\n{body.getvalue()}\r\n--{boundary}--\r\n"
                ).encode()
                request = urllib.request.Request(
                    CENSUS_GEOCODER,
                    data=payload,
                    headers={"Content-Type": f"multipart/form-data; boundary={boundary}", "User-Agent": USER_AGENT},
                )
                with urllib.request.urlopen(request, timeout=1800) as response:
                    if response.status != 200:
                        raise RuntimeError(f"Census geocoder returned HTTP {response.status}")
                    answers.append(response.read().decode())
            path.write_text("".join(answers))
        out = pd.read_csv(path, header=None, dtype=str, names=list(range(8)))
        xy = out[5].str.split(",", expand=True)
        return pd.DataFrame({"id": out[0], "lon": pd.to_numeric(xy[0]), "lat": pd.to_numeric(xy[1]), "geocode": out[3]})

    return (geocode,)


@app.cell
def _(geocode, pos):
    _g = geocode(pos[["registry_id", "reg_address", "reg_city", "reg_state", "reg_zip"]], "census-geocode-cms-pos.csv")
    _g = _g.set_index("id")
    pos["reg_lon"] = pos["registry_id"].map(_g["lon"])
    pos["reg_lat"] = pos["registry_id"].map(_g["lat"])
    pos["reg_location"] = "geocoded address, " + pos["registry_id"].map(_g["geocode"]).fillna("no match").str.lower()
    pos["reg_location"].value_counts()
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Public schools: NCES Common Core of Data, 2025–26 (preliminary).** The directory of every public school
    with its operational status (open, new, closed, inactive, future...) and school type. Coordinates come from
    NCES EDGE's geocodes for 2024–25, the latest published; a school new in 2025–26 is geocoded from its CCD
    location address. A school closed before 2025–26 drops out of the directory, so "not in the registry" is
    itself a sign of closure.
    """)
    return


@app.cell
def _(geocode):
    with zipfile.ZipFile(fetch(NCES_CCD, "nces-ccd-sch-029-2526.zip")) as _z:
        _name = next(n for n in _z.namelist() if n.endswith(".csv"))
        _ccd = pd.read_csv(_z.open(_name), dtype=str, encoding="latin1")
    with zipfile.ZipFile(fetch(NCES_EDGE, "nces-edge-publicsch-2425.zip")) as _z:
        _name = next(n for n in _z.namelist() if n.upper().endswith(".TXT"))
        _edge = pd.read_csv(_z.open(_name), sep="|", header=None, dtype=str, usecols=[0, 12, 13])
    _edge.columns = ["registry_id", "lat", "lon"]
    _edge = _edge.drop_duplicates("registry_id").set_index("registry_id").astype(float)
    _status = {
        "Open": "active",
        "New": "active",
        "Added": "active",
        "Reopened": "active",
        "Changed Boundary/Agency": "active",
        "Closed": "closed",
        "Inactive": "inactive",
        "Future": "future",
    }
    ccd = pd.DataFrame(
        {
            "registry_id": _ccd["NCESSCH"],
            "reg_name": _ccd["SCH_NAME"],
            "reg_address": _ccd["LSTREET1"],
            "reg_city": _ccd["LCITY"],
            "reg_state": _ccd["ST"],
            "reg_zip": _ccd["LZIP"].str[:5],
            "reg_type": _ccd["SCH_TYPE_TEXT"].str.upper().str.removesuffix(" SCHOOL"),
            "reg_status": _ccd["UPDATED_STATUS_TEXT"].map(_status).fillna("other"),
            "reg_status_detail": _ccd["UPDATED_STATUS_TEXT"],
            "reg_date": "2025-26 (effective " + _ccd["EFFECTIVE_DATE"].fillna("?") + ")",
            # Virtual and home-based programmes are in CCD but have no campus a map would show.
            "reg_in_scope": ~_ccd["SCH_NAME"].str.contains(
                r"virtual|online|cyber|e-?school|home ?school|homebound|distance learning", case=False, regex=True
            ),
        }
    )
    ccd["reg_link"] = "https://nces.ed.gov/ccd/schoolsearch/school_detail.asp?ID=" + ccd["registry_id"]
    ccd["reg_lon"] = ccd["registry_id"].map(_edge["lon"])
    ccd["reg_lat"] = ccd["registry_id"].map(_edge["lat"])
    ccd["reg_location"] = np.where(ccd["reg_lon"].notna(), "NCES EDGE 2024-25", "")
    _missing = ccd[ccd["reg_lon"].isna() & (ccd["reg_status"] == "active")]
    _g = geocode(
        _missing[["registry_id", "reg_address", "reg_city", "reg_state", "reg_zip"]], "census-geocode-ccd-new.csv"
    ).set_index("id")
    _fill = ccd["reg_lon"].isna() & ccd["registry_id"].isin(_g.index[_g["lon"].notna()])
    ccd.loc[_fill, "reg_lon"] = ccd.loc[_fill, "registry_id"].map(_g["lon"])
    ccd.loc[_fill, "reg_lat"] = ccd.loc[_fill, "registry_id"].map(_g["lat"])
    ccd.loc[_fill, "reg_location"] = "geocoded address"
    pd.crosstab(ccd["reg_status_detail"], ccd["reg_location"])
    return (ccd,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Power plants: EIA-860, 2025 (final, released September 2026).** Every US plant of 1 MW or more, with
    coordinates, and every generator with its status. We roll generators up to the plant: *operating* if any
    generator is operable (operating, standby or out of service), else *proposed* if any is planned or under
    construction, else *retired* if any is retired, else *cancelled* (cancelled or indefinitely postponed).
    """)
    return


@app.cell
def _():
    with zipfile.ZipFile(fetch(EIA_860, "eia8602025.zip")) as _z:
        _plants = pd.read_excel(_z.open("2___Plant_Y2025.xlsx"), header=1, dtype={"Plant Code": str})
        _sheets = pd.read_excel(_z.open("3_1_Generator_Y2025.xlsx"), sheet_name=None, header=1)
    _plants = _plants[pd.to_numeric(_plants["Plant Code"], errors="coerce").notna()]
    _rank = {"Operable": 0, "Proposed": 1, "Retired and Canceled": 2}
    _gens = pd.concat(
        [
            _g.assign(sheet=_s, rank=_rank[_s] + (_s == "Retired and Canceled") * (_g["Status"] != "RE"))
            for _s, _g in _sheets.items()
        ]
    )
    _gens = _gens[pd.to_numeric(_gens["Plant Code"], errors="coerce").notna()]
    _gens["Plant Code"] = _gens["Plant Code"].astype(int).astype(str)
    _best = _gens.groupby("Plant Code").agg(rank=("rank", "min"), technology=("Technology", "first"))
    _year = _gens[_gens["sheet"] == "Retired and Canceled"].groupby("Plant Code")["Retirement Year"].max()
    _status = _best["rank"].map({0: "active", 1: "proposed", 2: "retired", 3: "cancelled"})
    eia = pd.DataFrame(
        {
            "registry_id": _plants["Plant Code"].astype(str),
            "reg_name": _plants["Plant Name"],
            "reg_address": _plants["Street Address"].astype(str),
            "reg_city": _plants["City"].astype(str),
            "reg_state": _plants["State"],
            "reg_zip": _plants["Zip"].astype(str).str[:5],
            "reg_lon": pd.to_numeric(_plants["Longitude"], errors="coerce"),
            "reg_lat": pd.to_numeric(_plants["Latitude"], errors="coerce"),
            "reg_location": "EIA-860 2025",
            "reg_in_scope": True,
        }
    )
    eia["reg_status"] = eia["registry_id"].map(_status).fillna("no generators")
    eia["reg_type"] = eia["registry_id"].map(_best["technology"]).fillna("")
    eia["reg_status_detail"] = eia["reg_status"]
    eia["reg_date"] = "2025, retired " + eia["registry_id"].map(_year).astype("Int64").astype(str)
    eia.loc[eia["reg_status"] != "retired", "reg_date"] = "2025"
    eia["reg_link"] = "https://www.eia.gov/electricity/data/browser/#/plant/" + eia["registry_id"]
    eia["reg_status"].value_counts()
    return (eia,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Fire/EMS and law enforcement: no registry with station locations.**

    - The [USFA National Fire Department Registry](https://apps.usfa.fema.gov/registry/download) is voluntary and
      lists departments by headquarters address. Its station file (counted below) covers the departments that chose
      to list stations, with street addresses and no coordinates.
    - HIFLD's law enforcement layer was itself built from the BJS Census of State and Local Law Enforcement Agencies
      (its `CSLLEA08ID` is the 2008 census ID). The 2018 census is an agency list, distributed through ICPSR behind
      a sign-in, so it can't be fetched when the notebook runs. It has agencies, not station locations.

    So for these two layers OSM and Overture are the reference, as in `crosswalk.py`, and nothing is removed
    without a person looking.
    """)
    return


@app.cell
def _(hifld):
    _stations = pd.read_csv(fetch(USFA_STATIONS, "usfa-nfdr-stations.csv"), dtype=str, encoding="latin1")
    _stations.columns = _stations.columns.str.strip()
    usfa_coverage = pd.DataFrame(
        {
            "USFA registry stations listed": [len(_stations)],
            "departments listing stations": [_stations["FDID"].nunique()],
            "stations with a street address": [int(_stations["Station Addr1"].notna().sum())],
            "HIFLD fire and EMS stations": [int((hifld["layer"] == "Fire and EMS stations").sum())],
        }
    ).T.rename(columns={0: "count"})
    usfa_coverage.to_csv(OUT / "usfa_coverage.csv")
    mo.ui.table(usfa_coverage.reset_index(), selection=None)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What the open maps say near each point

    For every HIFLD point and every registry point we want the same-kind OSM feature and Overture place nearby,
    and, as the issue asks, the nearest **same-name Overture place of any category** within 250 m (a hospital
    Overture files as a nursing home, a school filed as a church). Overture places in the US are millions of rows,
    so DuckDB reads only those near our points: each point is copied into its own and its eight neighbouring 0.01°
    grid cells, and the places join on their cell, as the buildings pass in `crosswalk.py` does.
    """)
    return


@app.cell
def _(ccd, eia, hifld, osm, pos):
    _seeds = pd.concat(
        [
            hifld[["lon", "lat"]],
            pos[["reg_lon", "reg_lat"]].set_axis(["lon", "lat"], axis=1),
            ccd[["reg_lon", "reg_lat"]].set_axis(["lon", "lat"], axis=1),
            eia[["reg_lon", "reg_lat"]].set_axis(["lon", "lat"], axis=1),
            osm.loc[osm["layer"].isin(["Fire and EMS stations", "Local law enforcement"]), ["lon", "lat"]],
        ]
    ).dropna()
    _cells = (
        pd.DataFrame({"cx": np.floor(_seeds["lon"] / 0.01), "cy": np.floor(_seeds["lat"] / 0.01)})
        .astype(int)
        .drop_duplicates()
    )
    _cells = pd.concat([_cells.assign(cx=_cells.cx + dx, cy=_cells.cy + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)])
    _cells = _cells.drop_duplicates()
    places_path = DATA / f"overture-places-near-points-{OVERTURE_RELEASE}.parquet"
    if not places_path.exists():
        _con = overture_connection()
        _con.register("cells", _cells)
        _selects = [
            f"""SELECT p.id, p.names.primary AS name, p.basic_category, p.taxonomy.primary AS category,
                       p.operating_status, p.confidence, ST_X(p.geometry) AS lon, ST_Y(p.geometry) AS lat
                FROM read_parquet('{OVERTURE}/theme=places/type=place/*') p
                JOIN cells c ON c.cx = CAST(floor(p.bbox.xmin / 0.01) AS INTEGER)
                            AND c.cy = CAST(floor(p.bbox.ymin / 0.01) AS INTEGER)
                WHERE {box_filter(box).replace("bbox.", "p.bbox.")}"""
            for box in US_BOXES
        ]
        _con.sql(f"COPY ({' UNION ALL '.join(_selects)}) TO '{places_path}.part' (FORMAT parquet)")
        Path(f"{places_path}.part").rename(places_path)
    places = pd.read_parquet(places_path).drop_duplicates("id")
    mo.md(f"{len(_cells):,} grid cells; {len(places):,} Overture places in them.")
    return (places,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **One matcher for every comparison.** `best_within` takes points and features, finds every feature within
    a radius, scores names as `crosswalk.py` does, and keeps for each point the nearest name match if there is one,
    else the nearest feature. OSM areas are measured to their bounding box, so a point inside a campus is 0 m away.
    """)
    return


@app.cell
def _():
    def to_metric(frame: pd.DataFrame) -> gpd.GeoDataFrame:
        """Rows with a location, in metres. Rows with a bounding box (OSM areas) become the box."""
        frame = frame[frame["lon"].notna() & frame["lat"].notna()]
        shapes = shapely.points(frame["lon"], frame["lat"])
        if {"xmin", "ymin", "xmax", "ymax"} <= set(frame.columns):
            area = ((frame["xmax"] > frame["xmin"]) & (frame["ymax"] > frame["ymin"])).to_numpy()
            shapes = np.where(area, shapely.box(frame["xmin"], frame["ymin"], frame["xmax"], frame["ymax"]), shapes)
        return gpd.GeoDataFrame(frame, geometry=shapes, crs=4326).to_crs(METRIC)

    def best_within(
        points: gpd.GeoDataFrame, features: gpd.GeoDataFrame, radius: float, prefix: str, keep: list[str]
    ) -> pd.DataFrame:
        """For each point (index kept): the best feature within radius, as columns `{prefix}_*`."""
        assert points.crs == features.crs == METRIC
        columns = [f"{prefix}_{c}" for c in ["id", "name", "distance_m", "name_score", *keep]]
        if len(points) == 0 or len(features) == 0:
            return pd.DataFrame(columns=columns, index=points.index[:0])
        j = gpd.sjoin(
            points[["name", "geometry"]],
            features[["id", "name", *keep, "geometry"]],
            predicate="dwithin",
            distance=radius,
            lsuffix="p",
            rsuffix="f",
        )
        j["distance_m"] = j.geometry.distance(
            gpd.GeoSeries(features.geometry.loc[j["index_f"]].values, index=j.index, crs=METRIC)
        ).round(1)
        names_p = {n: normalise(n) for n in j["name_p"].unique()}
        names_f = {n: normalise(n) for n in j["name_f"].fillna("").unique()}
        j["name_score"] = [
            name_score(names_p[a], names_f[b]) for a, b in zip(j["name_p"], j["name_f"].fillna(""), strict=True)
        ]
        j["is_match"] = j["name_score"] >= MATCH
        j = j.reset_index(names="point").sort_values(["is_match", "distance_m", "id"], ascending=[False, True, True])
        best = j.drop_duplicates("point").set_index("point")
        best = best.rename(columns={"name_f": "name"})[["id", "name", "distance_m", "name_score", *keep]]
        return best.add_prefix(f"{prefix}_")

    return best_within, to_metric


@app.cell
def _(best_within, ccd, eia, hifld, osm, places, pos, to_metric):
    _categories = {
        layer: set(spec["overture_categories"]) for layer, spec in LAYERS.iterrows() if layer != "Power plants"
    }
    _places = places.assign(category=places["category"].fillna(places["basic_category"]))
    _places_m = to_metric(_places)
    _osm_open_m = to_metric(osm[~osm["osm_closed"]].rename(columns={"osm_id": "id"}))
    _osm_closed_m = to_metric(osm[osm["osm_closed"]].rename(columns={"osm_id": "id"}))
    _registries = {"Hospitals": pos, "Public schools": ccd, "Power plants": eia}

    def open_map_evidence(points: pd.DataFrame, layer: str) -> pd.DataFrame:
        """What OSM and Overture have within 250 m of each point (lon, lat, name), same kind and any kind."""
        pts = to_metric(points)
        kind = _places_m[
            _places_m["basic_category"].isin(_categories.get(layer, set()))
            | _places_m["category"].isin(_categories.get(layer, set()))
        ]
        parts = [
            best_within(pts, _osm_open_m[_osm_open_m["layer"] == layer], NEAR, "osm", ["osm_tag"]),
            best_within(pts, _osm_closed_m[_osm_closed_m["layer"] == layer], NEAR, "osm_closed", ["osm_tag"]),
            best_within(pts, kind, NEAR, "ov", ["category", "operating_status"]),
            best_within(pts, _places_m, NEAR, "ov_any", ["category", "operating_status"]),
        ]
        out = pd.DataFrame(index=points.index)
        for part in parts:
            out = out.join(part)
        return out

    _evidence = []
    for _layer in LAYERS.index:
        _h = hifld[hifld["layer"] == _layer]
        _evidence.append(open_map_evidence(_h[["lon", "lat", "name"]], _layer))
    hifld_maps = pd.concat(_evidence)
    registry_maps = {
        _layer: open_map_evidence(
            _reg.rename(columns={"reg_lon": "lon", "reg_lat": "lat", "reg_name": "name"})[["lon", "lat", "name"]],
            _layer,
        )
        for _layer, _reg in _registries.items()
    }
    hifld_maps.notna().groupby(hifld["layer"]).mean().round(2)[["osm_id", "osm_closed_id", "ov_id", "ov_any_id"]]
    return hifld_maps, open_map_evidence, registry_maps


if __name__ == "__main__":
    app.run()

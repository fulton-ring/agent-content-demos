import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import io
    import time
    import zipfile
    from pathlib import Path

    import duckdb
    import geopandas as gpd
    import marimo as mo
    import numpy as np
    import pandas as pd
    import requests
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
    pos_records = pd.DataFrame(
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
    pos_records["reg_link"] = "https://www.medicare.gov/care-compare/details/hospital/" + pos_records["registry_id"]

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
        f"CMS hospitals: {len(pos_records):,} records, {(pos_records['reg_status'] == 'active').sum():,} active. "
        f"Other certified providers in iQIES: {len(iqies):,}."
    )
    return iqies, pos_records


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
            for start in range(0, len(rows), 1000):
                body = io.StringIO()
                rows.iloc[start : start + 1000].to_csv(body, header=False, index=False)
                for attempt in range(4):
                    response = requests.post(
                        CENSUS_GEOCODER,
                        data={"benchmark": "Public_AR_Current"},
                        files={"addressFile": ("addresses.csv", body.getvalue(), "text/csv")},
                        headers={"User-Agent": USER_AGENT},
                        timeout=600,
                    )
                    if response.status_code == 200:
                        break
                    time.sleep(10 * 2**attempt)
                response.raise_for_status()
                answers.append(response.text if response.text.endswith("\n") else response.text + "\n")
            path.write_text("".join(answers))
        out = pd.read_csv(path, header=None, dtype=str, names=list(range(8)))
        xy = out[5].str.split(",", expand=True)
        return pd.DataFrame({"id": out[0], "lon": pd.to_numeric(xy[0]), "lat": pd.to_numeric(xy[1]), "geocode": out[3]})

    return (geocode,)


@app.cell
def _(geocode, pos_records):
    _g = geocode(
        pos_records[["registry_id", "reg_address", "reg_city", "reg_state", "reg_zip"]], "census-geocode-cms-pos.csv"
    ).set_index("id")
    pos = pos_records.assign(
        reg_lon=pos_records["registry_id"].map(_g["lon"]),
        reg_lat=pos_records["registry_id"].map(_g["lat"]),
        reg_location="geocoded address, "
        + pos_records["registry_id"].map(_g["geocode"]).fillna("no match").str.lower(),
    )
    pos["reg_location"].value_counts()
    return (pos,)


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
    _year = pd.to_numeric(_gens["Retirement Year"], errors="coerce").groupby(_gens["Plant Code"]).max()
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
    _kinds = sorted({c for cs in LAYERS["overture_categories"] for c in cs if not c.startswith("infrastructure")})
    _in = ", ".join(f"'{c}'" for c in _kinds)
    _con = duckdb.connect()
    _total = _con.sql(f"SELECT count(*) FROM '{places_path}'").fetchone()
    places = _con.sql(
        f"""SELECT DISTINCT ON (id) id, name, basic_category, coalesce(category, basic_category) AS category,
                   operating_status, lon, lat
            FROM '{places_path}' WHERE basic_category IN ({_in}) OR category IN ({_in})"""
    ).df()
    _n = _total[0] if _total else 0
    mo.md(f"{len(_cells):,} grid cells; {_n:,} Overture places in them, {len(places):,} of them same-kind.")
    return places, places_path


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Same name, any category.** Sixteen million places are too many to compare name by name in memory, so DuckDB
    first pairs each point with the places within 250 m that share a word of its name (one of its distinctive words,
    or any word if it has none), and only those pairs are scored with the same name matcher.
    """)
    return


@app.cell
def _(ccd, eia, hifld, places_path, pos):
    _seeds = [hifld[["lon", "lat", "name"]].assign(key="h" + hifld.index.astype(str))]
    for _layer, _reg in [("Hospitals", pos), ("Public schools", ccd), ("Power plants", eia)]:
        _r = _reg.rename(columns={"reg_lon": "lon", "reg_lat": "lat", "reg_name": "name"})[["lon", "lat", "name"]]
        _seeds.append(_r.assign(key=f"{_layer}:" + _r.index.astype(str)))
    _seeds = pd.concat(_seeds).dropna(subset=["lon", "lat"])
    _norm = {n: normalise(n) for n in _seeds["name"].unique()}
    _seeds["word"] = [(_norm[n][1] or _norm[n][0]).split() for n in _seeds["name"]]
    _seeds = _seeds.explode("word").dropna(subset=["word"])
    _con = duckdb.connect()
    _con.sql("SET memory_limit = '4GB'")
    _con.register("seeds", _seeds[["key", "lon", "lat", "word"]])
    _pairs = _con.sql(f"""
        WITH s AS (
            SELECT key, lon, lat, word, CAST(floor(lon / 0.01) AS INTEGER) + dx AS cx,
                   CAST(floor(lat / 0.01) AS INTEGER) + dy AS cy
            FROM seeds, (SELECT unnest([-1, 0, 1]) AS dx), (SELECT unnest([-1, 0, 1]) AS dy)
        ),
        p AS (
            SELECT id, name, coalesce(category, basic_category) AS category, operating_status, lon, lat,
                   CAST(floor(lon / 0.01) AS INTEGER) AS cx, CAST(floor(lat / 0.01) AS INTEGER) AS cy,
                   unnest(string_split_regex(lower(name), '[^a-z0-9]+')) AS word
            FROM '{places_path}' WHERE name IS NOT NULL
        )
        SELECT DISTINCT s.key, p.id, p.name, p.category, p.operating_status,
               sqrt(pow((p.lon - s.lon) * 111320 * cos(radians(s.lat)), 2) + pow((p.lat - s.lat) * 110540, 2))
                 AS distance_m
        FROM s JOIN p ON s.word = p.word AND s.cx = p.cx AND s.cy = p.cy
        WHERE sqrt(pow((p.lon - s.lon) * 111320 * cos(radians(s.lat)), 2) + pow((p.lat - s.lat) * 110540, 2))
              <= {NEAR}
    """).df()
    _names = dict(zip(_seeds["key"], _seeds["name"], strict=False))
    _pnorm = {n: normalise(n) for n in _pairs["name"].unique()}
    _pairs["name_score"] = [
        name_score(_norm[_names[k]], _pnorm[n]) for k, n in zip(_pairs["key"], _pairs["name"], strict=True)
    ]
    _pairs = _pairs[_pairs["name_score"] >= MATCH].sort_values(["distance_m", "id"])
    ov_any = _pairs.drop_duplicates("key").set_index("key")
    ov_any = ov_any.add_prefix("ov_any_")
    ov_any["ov_any_distance_m"] = ov_any["ov_any_distance_m"].round(1)
    mo.md(f"{len(_pairs):,} same-name pairs within 250 m; {len(ov_any):,} points have one.")
    return (ov_any,)


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
def _(best_within, ccd, eia, hifld, osm, ov_any, places, pos, to_metric):
    _categories = {
        layer: set(spec["overture_categories"]) for layer, spec in LAYERS.iterrows() if layer != "Power plants"
    }
    _places_m = to_metric(places)
    _osm_open_m = to_metric(osm[~osm["osm_closed"]].rename(columns={"osm_id": "id"}))
    _osm_closed_m = to_metric(osm[osm["osm_closed"]].rename(columns={"osm_id": "id"}))
    _registries = {"Hospitals": pos, "Public schools": ccd, "Power plants": eia}

    def open_map_evidence(points: pd.DataFrame, layer: str, keys: pd.Series | None = None) -> pd.DataFrame:
        """What OSM and Overture have within 250 m of each point (lon, lat, name): same kind, and (for points
        with a key) the same-name Overture place of any category."""
        pts = to_metric(points)
        kinds = _categories.get(layer, set())
        kind = _places_m[_places_m["basic_category"].isin(kinds) | _places_m["category"].isin(kinds)]
        parts = [
            best_within(pts, _osm_open_m[_osm_open_m["layer"] == layer], NEAR, "osm", ["osm_tag"]),
            best_within(pts, _osm_closed_m[_osm_closed_m["layer"] == layer], NEAR, "osm_closed", ["osm_tag"]),
            best_within(pts, kind, NEAR, "ov", ["category", "operating_status"]),
        ]
        out = pd.DataFrame(index=points.index)
        for part in parts:
            out = out.join(part)
        if keys is not None:
            out = out.join(ov_any.reindex(keys.values).set_axis(points.index))
        return out

    _evidence = []
    for _layer in LAYERS.index:
        _h = hifld[hifld["layer"] == _layer]
        _evidence.append(open_map_evidence(_h[["lon", "lat", "name"]], _layer, "h" + _h.index.astype(str)))
    hifld_maps = pd.concat(_evidence)
    registry_maps = {}
    for _layer, _reg in _registries.items():
        _r = _reg.rename(columns={"reg_lon": "lon", "reg_lat": "lat", "reg_name": "name"})[["lon", "lat", "name"]]
        registry_maps[_layer] = open_map_evidence(_r, _layer, f"{_layer}:" + _r.index.astype(str))
    hifld_maps.notna().groupby(hifld["layer"]).mean().round(2)[["osm_id", "osm_closed_id", "ov_id", "ov_any_id"]]
    return hifld_maps, open_map_evidence, registry_maps


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Linking each HIFLD record to its registry entry

    - **Schools and power plants** join by ID: HIFLD's `NCESID` is the NCES school ID, its `PLANT_CODE` the EIA
      plant code. We still compare names and locations: a name that doesn't match (score under 60) or a registry
      record with the same name nearer the point than the ID's own record is an **ID conflict**.
    - **Hospitals** have no CMS ID in HIFLD, so we link by name and address: every CMS hospital in the same ZIP
      code or within 2 km of the HIFLD point, scored on name and on street (house number and street name). A link
      is a name match, or the same street address with a name score of 50 or more. An active CMS record wins over a
      terminated one at the same place, because a hospital that converts (to critical access, say) gets a new CCN
      and the old one is terminated with code 07. A name score of 60–84 with nothing else is a **weak** link.
    - A HIFLD hospital with no CMS hospital link is looked up in the iQIES file the same way, to find nursing
      homes, surgery centres and clinics filed as hospitals.
    """)
    return


@app.cell
def _(best_within, ccd, eia, hifld, iqies, pos, to_metric):
    def street_key(address: pd.Series) -> pd.Series:
        """House number and the first word of the street name, e.g. '600 E Alabama Ave' -> '600 ALABAMA'."""
        parts = (
            address.fillna("")
            .str.upper()
            .str.extract(r"^\s*(\d+)[A-Z]?\s+(?:(?:N|S|E|W|NE|NW|SE|SW|NORTH|SOUTH|EAST|WEST)\.?\s+)?([A-Z0-9]+)")
        )
        return (parts[0] + " " + parts[1]).where(parts[0].notna())

    def strict_score(a: str, b: str) -> float:
        """The usual name score, averaged with a word-order-free ratio, so that one shared word ("Longview")
        doesn't make "Longview Rehabilitation Hospital" the same as "Longview Regional Medical Center"."""
        na, nb = normalise(a), normalise(b)
        lenient = name_score(na, nb)
        return (lenient + fuzz.token_sort_ratio(na[1] or na[0], nb[1] or nb[0])) / 2 if lenient else 0.0

    _h = hifld[hifld["layer"] == "Hospitals"].copy()
    _h["street"] = street_key(_h["address"])
    _pos = pos.assign(street=street_key(pos["reg_address"]))
    _byzip = _h.reset_index(names="h").merge(
        _pos, left_on=["state", "zip"], right_on=["reg_state", "reg_zip"], suffixes=("", "_reg")
    )
    _near = gpd.sjoin(
        to_metric(_h)[["geometry"]],
        to_metric(_pos.rename(columns={"reg_lon": "lon", "reg_lat": "lat"}))[["registry_id", "geometry"]],
        predicate="dwithin",
        distance=2000,
    ).reset_index(names="h")[["h", "registry_id"]]
    _near = _near.merge(_h.reset_index(names="h"), on="h").merge(_pos, on="registry_id", suffixes=("", "_reg"))
    _pairs = pd.concat([_byzip, _near[_byzip.columns]]).drop_duplicates(["h", "registry_id"])
    _pairs["link_score"] = [strict_score(a, b) for a, b in zip(_pairs["name"], _pairs["reg_name"], strict=True)]
    _pairs["same_street"] = _pairs["street"].notna() & (_pairs["street"] == _pairs["street_reg"])
    _pairs["strong"] = (_pairs["link_score"] >= MATCH) | (_pairs["same_street"] & (_pairs["link_score"] >= 50))
    _pairs["weak"] = ~_pairs["strong"] & (_pairs["link_score"] >= 60)
    _pairs["active"] = _pairs["reg_status"] == "active"
    _pairs = _pairs[_pairs["strong"] | _pairs["weak"]].sort_values(
        ["strong", "active", "link_score", "registry_id"], ascending=[False, False, False, True]
    )
    _hosp = _pairs.drop_duplicates("h").set_index("h")
    _hosp["link"] = np.where(_hosp["strong"], "name and address", "weak name")

    _iq = iqies.assign(street=street_key(iqies["iqies_address"]))
    _iqp = _h.reset_index(names="h").merge(_iq, left_on=["state", "zip"], right_on=["iqies_state", "iqies_zip"])
    _iqp["score"] = [strict_score(a, b) for a, b in zip(_iqp["name"], _iqp["iqies_name"], strict=True)]
    _same = _iqp["street_x"].notna() & (_iqp["street_x"] == _iqp["street_y"])
    _iqp = _iqp[(_iqp["score"] >= MATCH) | (_same & (_iqp["score"] >= 50))]
    _iq_best = _iqp.sort_values(["score", "iqies_id"], ascending=[False, True]).drop_duplicates("h").set_index("h")

    _reg_cols = [c for c in pos.columns if c.startswith("reg") or c == "registry_id"]
    _frames = [
        _hosp[["link", "link_score", *_reg_cols]].join(_iq_best[["iqies_id", "iqies_name", "iqies_type"]], how="outer")
    ]
    for _layer, _reg in [("Public schools", ccd), ("Power plants", eia)]:
        _x = hifld[hifld["layer"] == _layer]
        _ids = _x["hifld_id"].str.replace(r"\.0$", "", regex=True)
        _ids = _ids.str.zfill(12) if _layer == "Public schools" else _ids
        _joined = (
            pd.DataFrame({"registry_id": _ids}, index=_x.index)
            .merge(_reg, on="registry_id", how="left")
            .set_index(_x.index)
        )
        _joined["link"] = np.where(_joined["reg_name"].notna(), "id", None)
        _names = {n: normalise(n) for n in pd.concat([_x["name"], _joined["reg_name"].fillna("")]).unique()}
        _joined["link_score"] = [
            name_score(_names[a], _names[b]) if isinstance(b, str) else np.nan
            for a, b in zip(_x["name"], _joined["reg_name"], strict=True)
        ]
        # The registry record with a matching name nearest the HIFLD point, whatever its ID.
        _spatial = best_within(
            to_metric(_x[["lon", "lat", "name"]]),
            to_metric(
                _reg.rename(columns={"registry_id": "id", "reg_name": "name", "reg_lon": "lon", "reg_lat": "lat"})
            ),
            NEAR,
            "near",
            [],
        )
        _joined = _joined.join(_spatial[["near_id", "near_name_score"]])
        _frames.append(_joined)
    linked = pd.concat(_frames)
    linked = hifld.join(linked, how="left")
    _h_pts = gpd.GeoSeries.from_xy(linked["lon"], linked["lat"], crs=4326).to_crs(METRIC)
    _r_pts = gpd.GeoSeries.from_xy(linked["reg_lon"], linked["reg_lat"], crs=4326).to_crs(METRIC)
    linked["reg_distance_m"] = _h_pts.distance(_r_pts).round(1)
    linked["id_conflict"] = (
        (linked["near_name_score"] >= MATCH)
        & (linked["near_id"] != linked["registry_id"])
        & ((linked["link_score"].fillna(0) < 60) | (linked["reg_distance_m"].fillna(np.inf) > NEAR))
    )
    # Two HIFLD records linked to one registry entry. A hospital CCN can cover several campuses, so for hospitals
    # only records within 250 m of each other count.
    _ids = linked.loc[linked["link"].notna(), ["layer", "registry_id", "lon", "lat"]].reset_index(names="a")
    _pairs = _ids.merge(_ids, on=["layer", "registry_id"], suffixes=("", "_b"))
    _pairs = _pairs[_pairs["a"] != _pairs["a_b"]]
    _gap = np.hypot(
        (_pairs["lon"] - _pairs["lon_b"]) * 111_320 * np.cos(np.radians(_pairs["lat"])),
        (_pairs["lat"] - _pairs["lat_b"]) * 110_540,
    )
    _pairs = _pairs[(_pairs["layer"] != "Hospitals") | (_gap <= NEAR)]
    linked["duplicate_registry"] = linked.index.isin(_pairs["a"])
    pd.crosstab(linked["layer"], linked["link"].fillna("none"))
    return (linked,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Proposals, and when the sources agree

    Each HIFLD record gets one proposal from its registry entry:

    | Registry says | Proposal |
    |---|---|
    | no entry | **remove** (`not_in_registry`) |
    | terminated, closed, inactive, retired or cancelled | **remove** (`registry_closed`) |
    | proposed or future (not built yet) | **remove** if HIFLD calls it operating (`registry_not_built_yet`) |
    | another kind of facility (iQIES provider, a vet by name, another NCES school type) | **retype** |
    | active, but more than 250 m from the HIFLD point | **move** |
    | active, within 250 m | **keep** |

    Then the open maps vote. *On the maps* means a same-name OSM feature or Overture place (same kind, or any
    category) within 250 m, or a same-kind one within 50 m. *Closed on the maps* means a same-name OSM feature with
    a lifecycle prefix, or a same-name Overture place marked `permanently_closed`.

    - **keep** is final when the facility is on the maps; else it goes to review (`registry_active_not_on_maps`).
    - **remove** is final when the facility is *not* on the maps; else review (`..._but_on_maps`).
    - **retype** is final when no same-kind map feature carries the name; else review. A school-type change is final
      on NCES alone, since neither map records school type.
    - **move** is final when the maps have the name within 250 m of the registry point and not of HIFLD's, and the
      registry point isn't a geocoded address; else review (`location_differs`).
    - These always go to review: a weak name link, an ID whose name doesn't match (`id_name_mismatch`, score under
      60), an ID conflict, and two HIFLD records linked to one registry entry (`duplicate_registry`).
    - **Fire/EMS and police** have no registry: on the maps is a final keep, closed on the maps or absent from them
      is a removal for review. Federal hospitals (military, VA, Indian Health Service) aren't certified by CMS, so
      they're treated the same way.
    """)
    return


@app.cell
def _(ccd, eia, hifld_maps, linked, pos, registry_maps):
    _r = linked.join(hifld_maps)
    # Is the registry's own point on the maps (same name within 250 m)? Used to settle a move.
    _reg_on_maps = {}
    for _layer, _reg in [("Hospitals", pos), ("Public schools", ccd), ("Power plants", eia)]:
        _ev = registry_maps[_layer]
        _named = (_ev[["osm_name_score", "ov_name_score", "ov_any_name_score"]].fillna(0) >= MATCH).any(axis=1)
        _reg_on_maps[_layer] = _named.groupby(_reg.loc[_ev.index, "registry_id"].values).max().to_dict()
    _r["reg_on_maps"] = [
        bool(_reg_on_maps.get(lay, {}).get(rid, False)) for lay, rid in zip(_r["layer"], _r["registry_id"], strict=True)
    ]
    _open = lambda s: s.fillna("") != "permanently_closed"  # noqa: E731
    _named = lambda p: _r[f"{p}_name_score"].fillna(0) >= MATCH  # noqa: E731
    _r["on_maps"] = (
        _named("osm")
        | (_named("ov") & _open(_r["ov_operating_status"]))
        | (_named("ov_any") & _open(_r["ov_any_operating_status"]))
        | (_r["osm_distance_m"] <= 50)
        | (_r["ov_distance_m"] <= 50)
    )
    _r["closed_on_maps"] = _named("osm_closed") | (_named("ov_any") & ~_open(_r["ov_any_operating_status"]))
    _r["same_kind_named"] = _named("osm") | _named("ov")
    _federal = (_r["layer"] == "Hospitals") & (
        (_r["facility_type"] == "MILITARY")
        | _r["name"].str.contains(r"\bVA\b|VETERANS|INDIAN HEALTH|\bIHS\b|PHS INDIAN", case=False, regex=True)
    )
    _vet = (_r["layer"] == "Hospitals") & _r["name"].str.contains(
        r"\bANIMAL\b|VETERINAR|\bPET\b|EQUINE", case=False, regex=True
    )
    _planned_in_hifld = _r["status"].isin(["P", "L", "T", "U", "V", "TS", "OT"])

    def propose(row: pd.Series, federal: bool, vet: bool, planned: bool) -> tuple[str, str, bool]:
        """(proposal, reason, agreed) for one HIFLD record."""
        has_registry = row["layer"] in ("Hospitals", "Public schools", "Power plants") and not federal
        linked_ok = isinstance(row["link"], str)
        if vet:
            return "retype", "veterinary_by_name", not row["same_kind_named"]
        if not has_registry:
            if row["on_maps"] and not row["closed_on_maps"]:
                return "keep", "on_maps", True
            reason = "federal_not_in_cms" if federal else "no_registry"
            reason += "_closed_on_maps" if row["closed_on_maps"] else "_not_on_maps"
            return "remove", reason, False
        if row["layer"] == "Hospitals" and isinstance(row["iqies_type"], str) and row.get("reg_status") != "active":
            return "retype", "registry_other_provider_type", not row["same_kind_named"]
        if not linked_ok:
            return (
                ("remove", "not_in_registry_but_on_maps", False)
                if row["on_maps"]
                else ("remove", "not_in_registry", True)
            )
        status = row["reg_status"]
        if status in ("proposed", "future"):
            if planned:
                return "keep", "registry_not_built_yet_hifld_agrees", True
            return "remove", "registry_not_built_yet", False
        if status != "active":
            if row["on_maps"] and not row["closed_on_maps"]:
                return "remove", "registry_closed_but_on_maps", False
            return "remove", f"registry_{status.replace(' ', '_')}", True
        if (
            row["layer"] == "Public schools"
            and isinstance(row["reg_type"], str)
            and row["reg_type"] != row["facility_type"]
        ):
            return "retype", "school_type_differs", True
        if row["reg_distance_m"] > NEAR:
            if str(row["reg_location"]).startswith("geocoded"):
                return "move", "location_differs_geocoded", False
            if row["layer"] == "Power plants" and any(k in row["facility_type"] for k in ("SOLAR", "WIND")):
                return "move", "location_differs_wind_solar", False
            if row["reg_in_scope"] is False:
                return "move", "location_differs_virtual", False
            if row["reg_on_maps"] and not row["on_maps"]:
                return "move", "location_differs_maps_agree", True
            return "move", "location_differs", False
        if row["closed_on_maps"] and not row["on_maps"]:
            return "keep", "registry_active_closed_on_maps", False
        if not row["on_maps"]:
            return "keep", "registry_active_not_on_maps", False
        return "keep", "registry_active_on_maps", True

    _out = [
        propose(row, f, v, p)
        for (_, row), f, v, p in zip(_r.iterrows(), _federal, _vet, _planned_in_hifld, strict=True)
    ]
    _r["proposal"] = [o[0] for o in _out]
    _r["reason"] = [o[1] for o in _out]
    _r["agreed"] = [o[2] for o in _out]
    # Problems with the link itself send any proposal to review, with that as the reason.
    for _flag, _reason in [
        (_r["link"] == "weak name", "weak_name_match"),
        ((_r["link"] == "id") & (_r["link_score"] < 60), "id_name_mismatch"),
        (_r["id_conflict"].fillna(False).astype(bool), "id_conflict"),
        (_r["duplicate_registry"].fillna(False).astype(bool), "duplicate_registry"),
    ]:
        _r.loc[_flag, "reason"] = _reason
        _r.loc[_flag, "agreed"] = False
    proposals = _r
    pd.crosstab([proposals["layer"], proposals["proposal"]], proposals["agreed"].map({True: "agreed", False: "review"}))
    return (proposals,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Additions

    A registry facility is an **add** when it is active, has no HIFLD record of that layer by ID or link, and no
    HIFLD record of that layer within 250 m with a matching name. It is final when it's on the open maps at the
    registry's location; otherwise it goes to review (`add_not_on_maps`, or `add_no_location` without
    coordinates). Records likely out of HIFLD's scope (virtual schools, transplant centres, religious non-medical
    institutions) are counted but not proposed.

    For fire/EMS and police, an add is a same-kind OSM feature with no HIFLD record within 250 m that Overture also
    has by name within 250 m: two independent maps agreeing. One-sided features aren't proposed (see
    `crosswalk.py`'s `other_only.csv` for those counts).
    """)
    return


@app.cell
def _(best_within, ccd, eia, hifld, open_map_evidence, osm, pos, proposals, registry_maps, to_metric):
    _hifld_m = to_metric(hifld)
    _adds = []
    for _layer, _reg in [("Hospitals", pos), ("Public schools", ccd), ("Power plants", eia)]:
        _taken = set(proposals.loc[proposals["layer"] == _layer, "registry_id"].dropna())
        _cand = _reg[(_reg["reg_status"] == "active") & ~_reg["registry_id"].isin(_taken)].copy()
        _near = best_within(
            to_metric(_cand.rename(columns={"reg_lon": "lon", "reg_lat": "lat", "reg_name": "name"})),
            _hifld_m[_hifld_m["layer"] == _layer].rename(columns={"hifld_id": "id"}),
            NEAR,
            "hifld",
            [],
        )
        _cand = _cand.join(_near).join(registry_maps[_layer])
        _cand = _cand[~(_cand["hifld_name_score"].fillna(0) >= MATCH)]
        _cand["layer"] = _layer
        _adds.append(_cand)
    adds = pd.concat(_adds)
    _named = lambda p: adds[f"{p}_name_score"].fillna(0) >= MATCH  # noqa: E731
    adds["on_maps"] = (
        _named("osm") | _named("ov") | _named("ov_any") | (adds["osm_distance_m"] <= 50) | (adds["ov_distance_m"] <= 50)
    )
    adds["proposal"] = np.where(adds["reg_in_scope"], "add", "out of scope")
    adds["reason"] = np.select(
        [adds["reg_lon"].isna(), adds["on_maps"]], ["add_no_location", "add_on_maps"], "add_not_on_maps"
    )
    adds["agreed"] = adds["reason"] == "add_on_maps"

    _two_maps = []
    for _layer in ["Fire and EMS stations", "Local law enforcement"]:
        _o = osm[(osm["layer"] == _layer) & ~osm["osm_closed"]].rename(columns={"osm_id": "registry_id"})
        _o = _o.join(
            best_within(
                to_metric(_o),
                _hifld_m[_hifld_m["layer"] == _layer].rename(columns={"hifld_id": "id"}),
                NEAR,
                "hifld",
                [],
            )
        )
        _o = _o[_o["hifld_id"].isna()]
        _o = _o.join(
            open_map_evidence(_o[["lon", "lat", "name"]], _layer)[
                ["ov_id", "ov_name", "ov_name_score", "ov_category", "ov_operating_status", "ov_distance_m"]
            ]
        )
        _o = _o[_o["ov_name_score"].fillna(0) >= MATCH]
        _two_maps.append(
            _o.assign(
                layer=_layer,
                reg_name=_o["name"],
                reg_lon=_o["lon"],
                reg_lat=_o["lat"],
                reg_status="on OSM and Overture",
                reg_link="https://www.openstreetmap.org/" + _o["registry_id"],
                osm_id=_o["registry_id"],
                proposal="add",
                reason="add_on_both_maps",
                agreed=True,
            )
        )
    adds = pd.concat([adds, *_two_maps], ignore_index=True)
    pd.crosstab([adds["layer"], adds["proposal"]], adds["agreed"].map({True: "agreed", False: "review"}))
    return (adds,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Review queues

    Every proposal that isn't final goes to `output/review_queue_<layer>.csv`, one row per record, sorted by
    priority (the reasons most likely to be a real error first, then the largest distance). Each row says what
    every source says, the distances, links to the OSM feature, the registry entry and dated imagery (NAIP in the
    Planetary Computer explorer, and Esri Wayback for before/after), and has empty `reviewer_decision` and
    `reviewer_note` columns.

    **Reading decisions back.** Copy a queue into `review/` and fill in `reviewer_decision` with `accept` (the
    proposal stands), `reject` (leave HIFLD as it is), or another action (`keep`, `remove`, `retype`, `move`,
    `add`). On the next run those records leave the queue and the decision goes into the outputs.
    """)
    return


@app.cell
def _(adds, proposals):
    _priority = [
        "registry_closed_but_on_maps",
        "id_conflict",
        "duplicate_registry",
        "location_differs",
        "registry_not_built_yet",
        "not_in_registry_but_on_maps",
        "registry_other_provider_type",
        "veterinary_by_name",
        "registry_active_closed_on_maps",
        "no_registry_closed_on_maps",
        "federal_not_in_cms_closed_on_maps",
        "weak_name_match",
        "id_name_mismatch",
        "location_differs_geocoded",
        "location_differs_wind_solar",
        "location_differs_virtual",
        "registry_active_not_on_maps",
        "add_not_on_maps",
        "add_no_location",
        "federal_not_in_cms_not_on_maps",
        "no_registry_not_on_maps",
    ]
    _h = proposals.assign(record="HIFLD")
    _a = adds[adds["proposal"] == "add"].assign(record="registry", name=adds["reg_name"], hifld_id=None)
    _every = pd.concat([_h, _a], ignore_index=True)
    _every["slug"] = _every["layer"].str.lower().str.replace(r"[^a-z]+", "-", regex=True)
    _lon = _every["lon"].fillna(_every["reg_lon"])
    _lat = _every["lat"].fillna(_every["reg_lat"])
    queue_rows = pd.DataFrame(
        {
            "layer": _every["layer"],
            "slug": _every["slug"],
            "priority": _every["reason"].map({r: i + 1 for i, r in enumerate(_priority)}),
            "record": _every["record"],
            "hifld_id": _every["hifld_id"].fillna("").astype(str),
            "registry_id": _every["registry_id"].fillna("").astype(str),
            "name": _every["name"],
            "state": _every["state"].fillna(_every.get("reg_state")),
            "proposal": _every["proposal"],
            "reason": _every["reason"],
            "agreed": _every["agreed"].astype(bool),
            "hifld_status": _every["status"],
            "hifld_type": _every["facility_type"],
            "hifld_source_date": _every["source_date"],
            "registry_name": _every["reg_name"],
            "registry_status": _every["reg_status"],
            "registry_status_detail": _every["reg_status_detail"],
            "registry_type": _every["reg_type"].fillna(_every.get("iqies_type")),
            "registry_date": _every["reg_date"],
            "registry_location": _every["reg_location"],
            "registry_distance_m": _every["reg_distance_m"],
            "link": _every["link"],
            "link_name_score": _every["link_score"],
            "iqies_id": _every["iqies_id"],
            "iqies_type": _every["iqies_type"],
            "osm_id": _every["osm_id"],
            "osm_tag": _every["osm_tag"],
            "osm_name": _every["osm_name"],
            "osm_distance_m": _every["osm_distance_m"],
            "osm_closed_id": _every["osm_closed_id"],
            "overture_gers_id": _every["ov_id"],
            "overture_name": _every["ov_name"],
            "overture_category": _every["ov_category"],
            "overture_status": _every["ov_operating_status"],
            "overture_distance_m": _every["ov_distance_m"],
            "overture_any_gers_id": _every["ov_any_id"],
            "overture_any_name": _every["ov_any_name"],
            "overture_any_category": _every["ov_any_category"],
            "overture_any_status": _every["ov_any_operating_status"],
            "overture_any_distance_m": _every["ov_any_distance_m"],
            "lon": _lon.round(6),
            "lat": _lat.round(6),
            "osm_link": np.where(
                _every["osm_id"].notna(),
                "https://www.openstreetmap.org/" + _every["osm_id"].astype(str),
                "https://www.openstreetmap.org/#map=18/" + _lat.astype(str) + "/" + _lon.astype(str),
            ),
            "registry_link": _every["reg_link"],
            "naip_link": "https://planetarycomputer.microsoft.com/explore?c="
            + _lon.round(6).astype(str)
            + ","
            + _lat.round(6).astype(str)
            + "&z=18&v=2&d=naip&s=false::100::true",
            "wayback_link": "https://livingatlas.arcgis.com/wayback/#mapCenter="
            + _lon.round(6).astype(str)
            + "%2C"
            + _lat.round(6).astype(str)
            + "%2C18",
        }
    )
    assert queue_rows.loc[~queue_rows["agreed"], "priority"].notna().all(), "a review reason is missing a priority"
    queue_rows.groupby("layer")["agreed"].agg(["size", "sum"])
    return (queue_rows,)


@app.cell
def _(queue_rows):
    _decisions = []
    for _slug in queue_rows["slug"].unique():
        _path = REVIEW / f"review_queue_{_slug}.csv"
        if _path.exists():
            _filled = pd.read_csv(_path, dtype=str)
            _decisions.append(_filled[_filled["reviewer_decision"].fillna("").str.strip() != ""])
    _key = ["layer", "record", "hifld_id", "registry_id", "proposal"]
    decided = queue_rows.copy()
    decided["reviewer_decision"] = ""
    decided["reviewer_note"] = ""
    if _decisions:
        _d = pd.concat(_decisions)[[*_key, "reviewer_decision", "reviewer_note"]].fillna("")
        decided = decided.drop(columns=["reviewer_decision", "reviewer_note"])
        decided = decided.merge(_d.drop_duplicates(_key), on=_key, how="left")
        decided[["reviewer_decision", "reviewer_note"]] = decided[["reviewer_decision", "reviewer_note"]].fillna("")
    _choice = decided["reviewer_decision"].str.strip().str.lower()
    _allowed = {"", "accept", "reject", "keep", "remove", "retype", "move", "add"}
    assert set(_choice) <= _allowed, f"unknown reviewer decisions: {set(_choice) - _allowed}"
    decided["final_action"] = np.select(
        [_choice == "accept", _choice == "reject", _choice != ""],
        [decided["proposal"], np.where(decided["record"] == "HIFLD", "keep", "no change"), _choice],
        decided["proposal"],
    )
    decided["decided_by"] = np.select(
        [_choice != "", decided["agreed"]], ["reviewer", "sources agree"], "waiting for review"
    )
    _queue_columns = [c for c in decided.columns if c not in ("slug", "agreed", "final_action", "decided_by")]
    queue_sizes = {}
    for _slug, _q in decided[decided["decided_by"] == "waiting for review"].groupby("slug"):
        _q = _q.sort_values(
            ["priority", "registry_distance_m", "hifld_id", "registry_id"], ascending=[True, False, True, True]
        )
        _q[_queue_columns].to_csv(OUT / f"review_queue_{_slug}.csv", index=False)
        queue_sizes[_slug] = len(_q)
    mo.md(
        "Records waiting for a person, per layer: "
        + ", ".join(f"{k} {v:,}" for k, v in queue_sizes.items())
        + f". Decisions read back from `review/`: {int((decided['decided_by'] == 'reviewer').sum())}."
    )
    return (decided,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Results

    **Proposals per layer**, split into those the sources agree on and those sent to review.
    """)
    return


@app.cell
def _(decided):
    _status = decided["decided_by"].map(
        {"sources agree": "agreed", "reviewer": "reviewed", "waiting for review": "review"}
    )
    registry_summary = (
        pd.crosstab(decided["layer"], [decided["proposal"], _status]).reindex(LAYERS.index).fillna(0).astype(int)
    )
    registry_summary.columns = [f"{a} {b}" for a, b in registry_summary.columns]
    registry_summary.to_csv(OUT / "registry_summary.csv")
    review_reasons = (
        decided[decided["decided_by"] == "waiting for review"]
        .groupby(["layer", "reason"])
        .size()
        .rename("records sent to a person")
        .reset_index()
        .sort_values(["layer", "records sent to a person"], ascending=[True, False])
    )
    review_reasons.to_csv(OUT / "review_reasons.csv", index=False)
    mo.vstack([mo.ui.table(registry_summary, selection=None), mo.ui.table(review_reasons, selection=None)])
    return (registry_summary,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Changes ready for a founder to approve.** The final additions and removals (sources agree, or a reviewer
    decided), one file per layer, `output/proposed_changes_<layer>.csv`, each with the registry ID, the reason and
    the source. This is a list to approve, not an upload to HIFLD Next or OSM; OSM's
    [import guidelines](https://wiki.openstreetmap.org/wiki/Import/Guidelines) still apply.
    """)
    return


@app.cell
def _(decided):
    _sources = {
        "Hospitals": "CMS Provider of Services 2026 Q3",
        "Public schools": "NCES CCD 2025-26 (preliminary), EDGE 2024-25",
        "Power plants": "EIA-860 2025",
        "Fire and EMS stations": "OSM 2026-09-21 and Overture 2026-09-23.0",
        "Local law enforcement": "OSM 2026-09-21 and Overture 2026-09-23.0",
    }
    _final = decided[decided["final_action"].isin(["add", "remove"]) & (decided["decided_by"] != "waiting for review")]
    _cols = [
        "final_action",
        "hifld_id",
        "registry_id",
        "name",
        "state",
        "lon",
        "lat",
        "reason",
        "registry_status",
        "registry_status_detail",
        "registry_date",
        "decided_by",
        "registry_link",
        "osm_link",
    ]
    for _layer, _x in _final.groupby("layer"):
        _x = _x.assign(source=_sources[_layer]).sort_values(["final_action", "state", "name"])
        _x[[*_cols, "source"]].to_csv(OUT / f"proposed_changes_{_x['slug'].iloc[0]}.csv", index=False)
    pd.crosstab(_final["layer"], _final["final_action"])
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **How stale is each layer?** HIFLD's own source dates against the registry release we compared with.
    """)
    return


@app.cell
def _(hifld):
    _registry_dates = {
        "Hospitals": ("CMS POS 2026 Q3", "2026-07-01"),
        "Public schools": ("NCES CCD 2025-26 preliminary", "2025-10-01"),
        "Power plants": ("EIA-860 2025", "2025-12-31"),
        "Fire and EMS stations": ("OSM planet", "2026-09-21"),
        "Local law enforcement": ("OSM planet", "2026-09-21"),
    }
    _d = pd.to_datetime(hifld["source_date"], errors="coerce")
    _rows = []
    for _layer in LAYERS.index:
        _x = _d[hifld["layer"] == _layer]
        _name, _date = _registry_dates[_layer]
        _rows.append(
            {
                "layer": _layer,
                "HIFLD source date, earliest": _x.min().date(),
                "median": _x.median().date(),
                "latest": _x.max().date(),
                "registry": _name,
                "registry as of": _date,
                "years between median and registry": round((pd.Timestamp(_date) - _x.median()).days / 365.25, 1),
            }
        )
    data_dates = pd.DataFrame(_rows).set_index("layer")
    data_dates.to_csv(OUT / "data_dates.csv")
    mo.ui.table(data_dates, selection=None)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## Hand check on dated imagery

    A seeded sample per layer: 50 removals, 50 additions and 25 keeps (records the registry and the maps both
    match, which `crosswalk.py` never checked). `registry_chips.py` draws each on the latest
    [NAIP](https://planetarycomputer.microsoft.com/dataset/naip) image (USDA, public domain, 0.3–0.6 m, with its
    capture date) and on the earliest NAIP image after 2014, for a dated before/after pair. Each record is labelled
    in `hand_check_registry.csv`, against the proposal:

    - **confirmed:** the imagery supports it (for a removal: no such facility, demolished or plainly something
      else; for an add or a keep: the facility is there);
    - **contradicted:** the imagery shows the opposite;
    - **unclear:** imagery can't tell (a closed hospital whose building still stands, an office in a larger
      building).

    The share confirmed comes with a 95% Wilson interval. The same sample gives the share confirmed for each reason
    code, that is, how often each kind of flag is a real error.
    """)
    return


@app.cell
def _(decided):
    _sample = []
    for _i, _layer in enumerate(LAYERS.index):
        for _list, _n in [("remove", 50), ("add", 50), ("keep", 25), ("move", 25)]:
            _pool = decided[(decided["layer"] == _layer) & (decided["proposal"] == _list)]
            _sample.append(_pool.sample(n=min(_n, len(_pool)), random_state=100 + _i).assign(list=_list))
    hand_sample = pd.concat(_sample, ignore_index=True)
    hand_sample[
        [
            "layer",
            "list",
            "record",
            "hifld_id",
            "registry_id",
            "name",
            "state",
            "lon",
            "lat",
            "proposal",
            "reason",
            "agreed",
            "registry_status",
            "registry_type",
            "hifld_type",
        ]
    ].to_csv(OUT / "registry_hand_check_sample.csv", index=False)
    hand_sample.groupby(["layer", "list"]).size().unstack()
    return (hand_sample,)


@app.cell
def _(hand_sample):
    def wilson(k: int, n: int) -> str:
        if n == 0:
            return ""
        p, z = k / n, 1.96
        centre = (p + z**2 / (2 * n)) / (1 + z**2 / n)
        half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / (1 + z**2 / n)
        return f"{100 * (centre - half):.0f}–{100 * (centre + half):.0f}%"

    _path = HERE / "hand_check_registry.csv"
    _labels = (
        pd.read_csv(_path, dtype=str)
        if _path.exists()
        else pd.DataFrame(columns=["layer", "list", "hifld_id", "registry_id", "label"])
    )
    _key = ["layer", "list", "hifld_id", "registry_id"]
    _checked = hand_sample.merge(_labels[[*_key, "label"]].fillna(""), on=_key, how="inner")

    def confirmed_table(groups: list[str]) -> pd.DataFrame:
        rows = []
        for key, g in _checked.groupby(groups):
            k, n = int((g["label"] == "confirmed").sum()), len(g)
            rows.append(
                {
                    **dict(zip(groups, key if isinstance(key, tuple) else (key,), strict=True)),
                    "checked": n,
                    "confirmed": k,
                    "contradicted": int((g["label"] == "contradicted").sum()),
                    "unclear": int((g["label"] == "unclear").sum()),
                    "confirmed %": round(100 * k / n),
                    "95% interval": wilson(k, n),
                }
            )
        return pd.DataFrame(rows)

    hand_by_list = confirmed_table(["layer", "list", "agreed"]) if len(_checked) else pd.DataFrame()
    hand_by_reason = confirmed_table(["reason"]) if len(_checked) else pd.DataFrame()
    hand_by_list.to_csv(OUT / "registry_hand_check.csv", index=False)
    hand_by_reason.to_csv(OUT / "registry_hand_check_by_reason.csv", index=False)
    mo.vstack([mo.ui.table(hand_by_list, selection=None), mo.ui.table(hand_by_reason, selection=None)])
    return


@app.cell
def _():
    print(f"run time: {time.perf_counter() - RUN_STARTED:.0f} s")
    return


if __name__ == "__main__":
    app.run()

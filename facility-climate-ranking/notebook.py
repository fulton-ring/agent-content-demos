import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import logging
    import os
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    import requests

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log = logging.getLogger("fcr")
    here = Path(mo.notebook_dir() or ".")
    cache = Path(os.environ.get("FCR_CACHE", Path.home() / ".cache" / "facility-climate-ranking"))
    results = Path(os.environ.get("FCR_RESULTS", here / "results"))
    for _d in (cache / "nfhl", results):
        _d.mkdir(parents=True, exist_ok=True)
    started = time.time()

    def fetch(url: str, name: str) -> Path:
        """Download a file once into the cache, with a bounded number of retries."""
        path = cache / name
        if path.exists():
            return path
        for attempt in range(5):
            try:
                response = requests.get(url, timeout=600)
                response.raise_for_status()
                path.write_bytes(response.content)
                return path
            except requests.RequestException as error:
                log.warning("%s attempt %d: %s", url, attempt + 1, error)
                time.sleep(2**attempt)
        raise RuntimeError(f"{url} failed 5 times")

    def get_json(url: str, params: dict, cache_file: Path, attempts: int = 8) -> dict:
        """GET a JSON response, cached on disk, with a bounded number of retries."""
        if cache_file.exists():
            return json.loads(cache_file.read_text())
        for attempt in range(attempts):
            try:
                response = requests.get(url, params=params, timeout=120)
                response.raise_for_status()
                payload = response.json()
                if "error" not in payload:
                    cache_file.write_text(json.dumps(payload))
                    return payload
                log.warning("%s attempt %d: %s", url, attempt + 1, payload["error"])
            except (requests.RequestException, ValueError) as error:
                log.warning("%s attempt %d: %s", url, attempt + 1, error)
            time.sleep(2**attempt)
        raise RuntimeError(f"{url} failed {attempts} times with {params}")

    return (
        ThreadPoolExecutor,
        cache,
        fetch,
        get_json,
        gpd,
        here,
        json,
        log,
        mo,
        pd,
        plt,
        results,
        started,
        time,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Ranking facilities by climate risk: HIFLD Next × FEMA's National Risk Index × the FRI

    **The question.** Can anyone rank hospitals, power plants or other facilities by climate risk
    with free public data and one short notebook? We expect yes: put every facility point in its
    census tract, read FEMA's National Risk Index (NRI) for that tract, scale it by the county's
    Future Risk Index (FRI) multiplier, and sort.

    **It's wrong** if the join can't be made reliably from public data, or if the ranking mostly
    misses places publicly recorded as hit.

    Steps: (1) three HIFLD Next layers, (2) join each point to its NRI tract and its county's FRI
    multipliers and count what fails, (3) rank by hazard today and in the futures, (4) check the
    top of each ranking against known places, (5) for hospitals, compare the tract's flood rating
    with the FEMA flood zone under the building.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. The facilities

    Three [HIFLD Next](https://hifld.publicenvirodata.org) layers people ask about. HIFLD Next has
    **no substations layer**: DHS withdrew HIFLD's substations from public access in 2022, before
    the layers were preserved (see `hifld-grid-gaps/`). Power plants stand in for the grid.

    - **Hospitals** (`hospitals-3` v1.1.0), open ones only.
    - **Power plants** (`power-plants-1` v1.0.0), status `OP` (operating) only.
    - **Wastewater treatment plants** (`icis-wastewater-treatment-plants` v1.0.0, EPA's ICIS
      permits), publicly owned plants (POTW) with an effective or administratively continued
      permit.

    Each layer keeps an ID, a name, the layer's own county FIPS (to check our join against) and a
    point.
    """)
    return


@app.cell
def _(fetch, gpd, pd):
    _hifld = "https://storage.googleapis.com/hifld-next-datasets-prod/hifld"
    _raw = {
        name: gpd.read_parquet(fetch(f"{_hifld}/{path}", f"{name}.parquet")).to_crs("EPSG:4326")
        for name, path in {
            "hospitals": "hospitals-3/hospitals-3/v1.1.0/geoparquet/hospitals-3.parquet",
            "power_plants": "power-plants-1/power-plants-1/v1.0.0/geoparquet/"
            "power-plants-1.parquet",
            "wastewater": "icis-wastewater-treatment-plants/icis-wastewater-treatment-plants/"
            "v1.0.0/geoparquet/icis-wastewater-treatment-plants.parquet",
        }.items()
    }
    _h, _p, _w = _raw["hospitals"], _raw["power_plants"], _raw["wastewater"]
    _w_active = _w.CWP_PERMIT_STATUS_DESC.isin(["Effective", "Admin Continued"]) & (
        _w.CWP_FACILITY_TYPE_INDICATOR == "POTW"
    )
    _frames = [
        _h.assign(
            layer="hospitals", facility_id=_h.source_ID, kind=_h.TYPE, active=_h.STATUS == "OPEN"
        ).rename(columns={"NAME": "name", "CITY": "city", "STATE": "state", "COUNTYFIPS": "cf"}),
        _p.assign(
            layer="power_plants",
            facility_id=_p.PLANT_CODE.astype(str),
            kind=_p.PRIM_FUEL,
            active=_p.STATUS == "OP",
        ).rename(columns={"NAME": "name", "CITY": "city", "STATE": "state", "COUNTYFIPS": "cf"}),
        _w.assign(
            layer="wastewater",
            facility_id=_w.NPDES_ID,
            kind=_w.CWP_MAJOR_MINOR_STATUS,
            active=_w_active,
        ).rename(
            columns={
                "CWP_NAME": "name",
                "CWP_CITY": "city",
                "CWP_STATE": "state",
                "FAC_DERIVED_FIPS": "cf",
            }
        ),
    ]
    _cols = ["layer", "facility_id", "name", "city", "state", "kind", "cf", "active", "geometry"]
    all_facilities = gpd.GeoDataFrame(
        pd.concat([f[_cols] for f in _frames], ignore_index=True), crs="EPSG:4326"
    ).rename(columns={"cf": "county_fips_hifld"})
    assert not all_facilities.duplicated(["layer", "facility_id"]).any(), "IDs must be unique"
    layer_counts = all_facilities.groupby("layer").agg(
        records=("facility_id", "size"), active=("active", "sum")
    )
    layer_counts
    return (all_facilities,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. The join

    **Tract.** NRI v1.20 (December 2025, the last release; FEMA told GAO in May 2026 it plans no
    update) scores 2020 census tracts. FEMA's tract service gives the scores without shapes, so we
    take the shapes from the Census Bureau's 2020 cartographic tract file and join each point to
    the tract polygon it falls in. The tract's own county FIPS (from NRI) becomes the facility's
    county.

    **What we read per hazard.** For inland flooding, coastal flooding, hurricane, wildfire and
    heat wave: the tract's risk rating (`*_RISKR`), its expected annual loss in dollars
    (`*_EALT`) and its **annualized loss rate for buildings** (`*_ALRB`): the share of a
    building's value the hazard is expected to destroy each year in that tract. We rank on the
    loss rate, not the dollar loss, because the dollar loss mostly measures how many buildings a
    tract has, while the rate is the closest NRI comes to "how dangerous is this spot for one
    building". Heat waves do almost no harm to buildings in the NRI (median building loss rate
    of a few billionths, see below) and their harm is to people, so heat is ranked on the
    **population** loss rate (`HWAV_ALRP`) instead.
    """)
    return


@app.cell
def _(cache, fetch, get_json, gpd, pd):
    hazards = {
        "inland_flood": "IFLD",
        "coastal_flood": "CFLD",
        "hurricane": "HRCN",
        "wildfire": "WFIR",
        "heat_wave": "HWAV",
    }
    _fields = ["TRACTFIPS", "STCOFIPS", "RISK_RATNG", "NRI_VER"]
    for _code in hazards.values():
        _fields += [f"{_code}_RISKR", f"{_code}_EALT", f"{_code}_ALRB"]
    _fields.append("HWAV_ALRP")
    _url = (
        "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
        "National_Risk_Index_Census_Tracts/FeatureServer/0/query"
    )
    _rows = []
    for _page in range(60):
        _payload = get_json(
            _url,
            {
                "where": "1=1",
                "outFields": ",".join(_fields),
                "returnGeometry": "false",
                "orderByFields": "OBJECTID",
                "resultOffset": len(_rows),
                "resultRecordCount": 2000,
                "f": "json",
            },
            cache / f"nri_tracts_{_page}.json",
        )
        _rows += [f["attributes"] for f in _payload["features"]]
        if not _payload.get("exceededTransferLimit"):
            break
    else:
        raise RuntimeError("NRI tract table still paging after 60 pages")
    nri = pd.DataFrame(_rows)
    assert nri.TRACTFIPS.is_unique, "one NRI row per tract expected"
    tract_shapes = gpd.read_file(
        fetch(
            "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_tract_500k.zip",
            "cb_2020_us_tract_500k.zip",
        ),
        columns=["GEOID"],
    ).to_crs("EPSG:4326")
    assert len(nri) > 80_000, "NRI tract table looks truncated"
    pd.DataFrame(
        {
            "NRI tracts": [len(nri)],
            "NRI version": [", ".join(sorted(nri.NRI_VER.dropna().unique()))],
            "Census 2020 tract shapes": [len(tract_shapes)],
            "Median building loss rate, inland flood": [nri.IFLD_ALRB.median()],
            "Median building loss rate, heat wave": [nri.HWAV_ALRB.median()],
        }
    )
    return hazards, nri, tract_shapes


@app.cell
def _(mo):
    mo.md(r"""
    **FRI multipliers.** FEMA's FRI multiplied a county's expected annual loss by a hazard
    multiplier for four futures (mid and late century, lower and higher warming). FEMA took it
    down in February 2025; `fri-datasets-map/` publishes FEMA's last values and our rebuild's.
    We download those county files from this repo at a pinned commit. The FRI covers coastal
    flooding, hurricane, wildfire and extreme heat (we use the LOCA2 95th-percentile version for
    heat), but **not inland flooding**, so inland flood is ranked today only. FEMA's multiplier of
    0 means "No Rating" and is treated as missing.
    """)
    return


@app.cell
def _(fetch, pd):
    _repo = (
        "https://raw.githubusercontent.com/fulton-ring/agent-content-demos/"
        "ba506b126ff7cd6e087485048924bd0235340cc0/fri-datasets-map/data"
    )
    _mult = pd.read_csv(
        fetch(f"{_repo}/multipliers_by_county.csv", "fri_multipliers_by_county.csv"),
        dtype={"fips": str},
    )
    _hrcn = pd.read_csv(
        fetch(f"{_repo}/hurricane_by_county.csv", "fri_hurricane_by_county.csv"),
        dtype={"fips": str},
    ).rename(columns={"our_hm": "rebuilt_hm"})
    _hrcn["hazard"] = "HRCN"
    _fri_hazard = {"CFLD": "CFLD", "WFIR": "WFIR", "EXHT_L95": "HWAV", "HRCN": "HRCN"}
    _long = pd.concat([_mult, _hrcn])
    _long = _long[_long.hazard.isin(list(_fri_hazard))]
    _long = _long.assign(nri_hazard=_long.hazard.map(_fri_hazard))
    _long["fema_hm"] = _long.fema_hm.where(_long.fema_hm > 0)
    scenarios = ["MID_LOWER", "MID_HIGHER", "LATE_LOWER", "LATE_HIGHER"]
    fri = _long.pivot_table(
        index="fips",
        columns=["nri_hazard", "scenario"],
        values=["fema_hm", "rebuilt_hm"],
        aggfunc="first",
    )
    fri.columns = [f"{h}_{src.split('_')[0]}_{s}" for src, h, s in fri.columns]
    fri = fri.reset_index().rename(columns={"fips": "county_fips"})
    assert fri.county_fips.is_unique
    pd.DataFrame({"counties with an FRI value": [len(fri)], "columns": [fri.shape[1] - 1]})
    return fri, scenarios


@app.cell
def _(mo):
    mo.md(r"""
    Now the spatial join, and an account of every facility that doesn't make it through. Reasons,
    in order: not active (closed, retired or terminated, dropped by choice), outside every census
    tract (bad coordinates, or a territory such as Palau or Guam with no 2020 tract shapes), in a
    tract NRI doesn't score, or in a county with no FRI multiplier at all.
    """)
    return


@app.cell
def _(all_facilities, fri, gpd, nri, pd, tract_shapes):
    _joined = gpd.sjoin(all_facilities, tract_shapes, how="left", predicate="within")
    _joined = _joined[~_joined.index.duplicated()].drop(columns="index_right")
    facilities = _joined.rename(columns={"GEOID": "tract_fips"}).merge(
        nri, left_on="tract_fips", right_on="TRACTFIPS", how="left"
    )
    facilities = facilities.rename(columns={"STCOFIPS": "county_fips"}).drop(columns="TRACTFIPS")
    facilities = facilities.merge(fri, on="county_fips", how="left")
    _has_fri = facilities[[c for c in fri.columns if c != "county_fips"]].notna().any(axis=1)
    facilities["join_status"] = "joined"
    facilities.loc[~_has_fri, "join_status"] = "county has no FRI value"
    facilities.loc[facilities.NRI_VER.isna(), "join_status"] = "tract not in NRI"
    facilities.loc[facilities.tract_fips.isna(), "join_status"] = "outside every 2020 tract"
    facilities.loc[~facilities.active, "join_status"] = "not active"
    facilities = gpd.GeoDataFrame(facilities, geometry="geometry", crs="EPSG:4326")
    join_report = pd.crosstab(facilities.layer, facilities.join_status, margins=True)
    _active = facilities[facilities.active & facilities.county_fips.notna()]
    _hifld_fips = _active.county_fips_hifld.astype("string").str.zfill(5)
    county_agreement = (
        (_hifld_fips == _active.county_fips).groupby(_active.layer).mean().rename("same county")
    )
    join_report
    return county_agreement, facilities, join_report


@app.cell
def _(county_agreement, facilities, mo):
    _outside = facilities[facilities.join_status == "outside every 2020 tract"]
    _no_nri = facilities[facilities.join_status == "tract not in NRI"]
    _joined = facilities[facilities.join_status == "joined"]
    _mismatch = _joined[
        _joined.county_fips_hifld.astype("string").str.zfill(5) != _joined.county_fips
    ]
    mo.md(f"""
    **Where the misses are.** Outside every tract, by state: {
        _outside.state.value_counts().head(8).to_dict()
    }. In a tract NRI doesn't score, by state: {_no_nri.state.value_counts().head(8).to_dict()}.

    **Is our county the layer's county?** Share of joined facilities whose tract county matches
    the county FIPS the HIFLD layer carries: {
        ", ".join(f"{k} {v:.1%}" for k, v in county_agreement.items())
    }. The mismatches by state: {_mismatch.state.value_counts().head(6).to_dict()}.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. The ranking

    Within each layer, facilities are ranked by the tract loss rate for each hazard, 1 = highest.
    A future loss rate is today's rate times the county's FRI multiplier for that hazard and
    scenario, from FEMA's FRI and, separately, from our rebuild. Where a county has no multiplier
    for a hazard, today's rate carries over unchanged. Many facilities share a tract, so ties are
    broken by facility ID. Only facilities with a rate above zero are ranked.
    """)
    return


@app.cell
def _(facilities, hazards, pd, scenarios):
    def rate_column(code: str) -> str:
        return "HWAV_ALRP" if code == "HWAV" else f"{code}_ALRB"

    ranked = facilities[facilities.join_status.isin(["joined", "county has no FRI value"])].copy()
    _rows = []
    for _hz, _code in hazards.items():
        _rate = ranked[rate_column(_code)].where(ranked[rate_column(_code)] > 0)
        ranked[f"{_hz}_rate"] = _rate
        _futures = {"today": _rate}
        if _code != "IFLD":
            for _src in ("fema", "rebuilt"):
                for _s in scenarios:
                    _m = ranked[f"{_code}_{_src}_{_s}"].fillna(1.0)
                    _futures[f"{_src}_{_s}"] = _rate * _m
        for _name, _values in _futures.items():
            _order = ranked.assign(_v=_values).sort_values(
                ["layer", "_v", "facility_id"], ascending=[True, False, True]
            )
            _order = _order[_order._v.notna()]
            ranked.loc[_order.index, f"{_hz}_rank_{_name}"] = _order.groupby("layer").cumcount() + 1
        for _name in _futures:
            if _name == "today":
                continue
            for _layer, _g in ranked.groupby("layer"):
                _top_now = set(_g.nsmallest(100, f"{_hz}_rank_today").facility_id)
                _top_then = set(_g.nsmallest(100, f"{_hz}_rank_{_name}").facility_id)
                _src, _s = _name.split("_", 1)
                _rows.append(
                    {
                        "layer": _layer,
                        "hazard": _hz,
                        "source": _src,
                        "scenario": _s,
                        "top100_overlap": len(_top_now & _top_then),
                    }
                )
    overlap = pd.DataFrame(_rows)
    overlap.pivot_table(
        index=["layer", "hazard"], columns=["source", "scenario"], values="top100_overlap"
    )
    return overlap, ranked


@app.cell
def _(mo):
    mo.md(r"""
    The table above is how many of today's top 100 stay in the top 100 under each future
    (100 = unchanged). Below: the top five per layer and hazard today, with the late-century,
    higher-warming rank under FEMA's multipliers. Facilities in one tract share a rate, so the top
    of a list is often a handful of tracts.
    """)
    return


@app.cell
def _(hazards, pd, ranked):
    _rows = []
    for _hz in hazards:
        for _layer, _g in ranked.groupby("layer"):
            for _r in _g.nsmallest(5, f"{_hz}_rank_today").itertuples():
                _rows.append(
                    {
                        "layer": _layer,
                        "hazard": _hz,
                        "rank": int(getattr(_r, f"{_hz}_rank_today")),
                        "name": _r.name,
                        "city": _r.city,
                        "state": _r.state,
                        "tract": _r.tract_fips,
                        "loss_rate": getattr(_r, f"{_hz}_rate"),
                        "rank_late_higher_fema": getattr(
                            _r, f"{_hz}_rank_fema_LATE_HIGHER", float("nan")
                        ),
                    }
                )
    top_facilities = pd.DataFrame(_rows)
    top_facilities
    return (top_facilities,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. A check against known places

    Two kinds of place publicly recorded as hit:

    - **Counties with the most NFIP repetitive-loss properties.** FEMA's OpenFEMA
      `NfipMultipleLossProperties` lists every insured property that flooded more than once,
      with its county and block group. The 100 counties with the most are our known flood
      counties, and tracts with 25 or more are our known flood tracts.
    - **Hospitals named as flooded, damaged or evacuated in a named hurricane or wildfire**, from
      after-action reports (Urban Institute on Katrina, Toner et al. on Sandy, HHS ASPR TRACIE),
      the Interior Department, and news and trade press, matched by hand to HIFLD IDs in
      `known_hospitals.csv` (one source per row).

    The test: what share of facilities in known places rank in the top decile of their layer for
    the matching hazard? For flood we count a facility as top decile if it is in the top decile
    of inland *or* coastal flooding, and compare with the same share for all ranked facilities.
    """)
    return


@app.cell
def _(cache, get_json, pd):
    _url = "https://www.fema.gov/api/open/v1/NfipMultipleLossProperties"
    _rows = []
    for _page in range(60):
        _payload = get_json(
            _url,
            {
                "$select": "fipsCountyCode,censusBlockGroup",
                "$top": 10000,
                "$skip": len(_rows),
                "$orderby": "id",
            },
            cache / f"nfip_multiple_loss_{_page}.json",
        )
        _batch = _payload["NfipMultipleLossProperties"]
        _rows += _batch
        if len(_batch) < 10000:
            break
    else:
        raise RuntimeError("NfipMultipleLossProperties still paging after 60 pages")
    repetitive_loss = pd.DataFrame(_rows)
    repetitive_loss["tract_fips"] = repetitive_loss.censusBlockGroup.str[:11]
    known_counties = set(repetitive_loss.fipsCountyCode.value_counts().head(100).index)
    _by_tract = repetitive_loss.tract_fips.value_counts()
    known_tracts = set(_by_tract[_by_tract >= 25].index)
    pd.DataFrame(
        {
            "repetitive-loss properties": [len(repetitive_loss)],
            "known counties (top 100)": [len(known_counties)],
            "share of properties in them": [
                repetitive_loss.fipsCountyCode.isin(known_counties).mean()
            ],
            "known tracts (25+)": [len(known_tracts)],
        }
    )
    return known_counties, known_tracts


@app.cell
def _(hazards, known_counties, known_tracts, pd, ranked):
    def top_decile(frame: pd.DataFrame, hazard: str) -> pd.Series:
        """Whether each facility ranks in its layer's top 10% for a hazard, today."""
        rank = frame[f"{hazard}_rank_today"]
        cutoff = frame.groupby("layer")[f"{hazard}_rank_today"].transform("max") * 0.10
        return (rank <= cutoff).fillna(False)

    for _hz in hazards:
        ranked[f"{_hz}_top_decile"] = top_decile(ranked, _hz)
    ranked["flood_top_decile"] = ranked.inland_flood_top_decile | ranked.coastal_flood_top_decile
    _rows = []
    for _layer, _g in ranked.groupby("layer"):
        for _label, _mask in (
            ("all ranked facilities", pd.Series(True, index=_g.index)),
            ("in a known flood county", _g.county_fips.isin(known_counties)),
            ("in a known flood tract", _g.tract_fips.isin(known_tracts)),
        ):
            _rows.append(
                {
                    "layer": _layer,
                    "group": _label,
                    "facilities": int(_mask.sum()),
                    "flood top decile": _g.flood_top_decile[_mask].mean(),
                }
            )
    flood_check = pd.DataFrame(_rows)
    flood_check
    return (flood_check,)


@app.cell
def _(here, pd, ranked):
    known_hospitals = pd.read_csv(here / "known_hospitals.csv", dtype={"hifld_source_id": str})
    _hosp = ranked[ranked.layer == "hospitals"]
    _flags = ["flood_top_decile", "hurricane_top_decile", "wildfire_top_decile"]
    hospital_check = known_hospitals.merge(
        _hosp[["facility_id", *_flags]],
        left_on="hifld_source_id",
        right_on="facility_id",
        how="left",
    )
    hospital_check["in_ranked_layer"] = hospital_check.facility_id.notna()
    _hit = {
        "flood": hospital_check.flood_top_decile,
        "hurricane": hospital_check.hurricane_top_decile | hospital_check.flood_top_decile,
        "wildfire": hospital_check.wildfire_top_decile,
    }
    hospital_check["top_decile"] = False
    for _hz, _col in _hit.items():
        _rows = hospital_check.hazard == _hz
        hospital_check.loc[_rows, "top_decile"] = _col[_rows].fillna(False).astype(bool)
    hospital_check_summary = (
        hospital_check[hospital_check.in_ranked_layer]
        .groupby("hazard")
        .agg(hospitals=("hospital_name", "size"), in_top_decile=("top_decile", "mean"))
    )
    hospital_check_summary
    return hospital_check, hospital_check_summary


@app.cell
def _(mo):
    mo.md(r"""
    For hospitals hit by a hurricane we accept the top decile of hurricane *or* flood, because
    most of those hospitals were knocked out by water, not wind. A hospital that has closed since
    its event is no longer in the ranked layer and is listed but not scored.

    ## 5. Where it misleads: tract rating against the flood zone under the hospital

    A tract score is not a building's risk. For every ranked hospital we ask FEMA's National
    Flood Hazard Layer which flood zone the point sits in (code copied from
    `data-center-metro-hazard/`; a point FEMA's service fails to answer 8 times in a row is
    kept as "query failed" and counted): **SFHA** (zones A and V, the 1%-a-year floodplain),
    **shaded X** (moderate), **minimal**, **D** (undetermined) or **not mapped**. Then we compare
    with the
    tract's flood rating, taking the higher of its inland and coastal flood ratings.
    """)
    return


@app.cell
def _(ThreadPoolExecutor, cache, get_json, log, pd, ranked, time):
    _nfhl_url = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/28/query"
    _order = ["SFHA", "shaded X", "minimal", "D", "open water", "not mapped"]

    def flood_class(features: list[dict]) -> tuple[str, str]:
        """Group NFHL zone polygons at a point into a hazard class; the highest hazard wins."""
        found = []
        for feature in features:
            zone = (feature["attributes"]["FLD_ZONE"] or "").strip()
            subtype = feature["attributes"]["ZONE_SUBTY"] or ""
            if feature["attributes"]["SFHA_TF"] == "T":
                found.append(("SFHA", zone))
            elif zone == "X" and subtype != "AREA OF MINIMAL FLOOD HAZARD":
                found.append(("shaded X", zone))
            elif zone == "X":
                found.append(("minimal", zone))
            elif zone == "D":
                found.append(("D", zone))
            elif zone == "OPEN WATER":
                found.append(("open water", zone))
        if not found:
            return "not mapped", ""
        return min(found, key=lambda pair: _order.index(pair[0]))

    def query_point(job: tuple[str, float, float]) -> dict:
        facility_id, lat, lon = job
        try:
            payload = get_json(
                _nfhl_url,
                {
                    "geometry": f"{lon:.6f},{lat:.6f}",
                    "geometryType": "esriGeometryPoint",
                    "inSR": "4326",
                    "spatialRel": "esriSpatialRelIntersects",
                    "returnGeometry": "false",
                    "outFields": "FLD_ZONE,ZONE_SUBTY,SFHA_TF",
                    "f": "json",
                },
                cache / "nfhl" / f"{lat:.6f}_{lon:.6f}.json",
            )
        except RuntimeError:
            return {"facility_id": facility_id, "nfhl_flood_class": "query failed", "nfhl_zone": ""}
        flood, zone = flood_class(payload["features"])
        return {"facility_id": facility_id, "nfhl_flood_class": flood, "nfhl_zone": zone}

    _hosp = ranked[ranked.layer == "hospitals"]
    _jobs = list(zip(_hosp.facility_id, _hosp.geometry.y, _hosp.geometry.x, strict=True))
    _t0 = time.time()
    with ThreadPoolExecutor(max_workers=6) as _pool:
        nfhl = pd.DataFrame(list(_pool.map(query_point, _jobs)))
    log.info("%d hospital points queried in NFHL in %.0f s", len(nfhl), time.time() - _t0)
    nfhl.nfhl_flood_class.value_counts()
    return (nfhl,)


@app.cell
def _(nfhl, pd, ranked):
    _levels = ["Very Low", "Relatively Low", "Relatively Moderate", "Relatively High", "Very High"]
    _hosp = ranked[ranked.layer == "hospitals"].merge(nfhl, on="facility_id")

    def level(rating: str) -> int:
        return _levels.index(rating) if rating in _levels else -1

    _best = [
        max(level(a), level(b)) for a, b in zip(_hosp.IFLD_RISKR, _hosp.CFLD_RISKR, strict=True)
    ]
    _hosp["tract_flood_rating"] = [_levels[i] if i >= 0 else "No rating" for i in _best]
    hospitals_sfha = _hosp
    sfha_table = pd.crosstab(
        _hosp.tract_flood_rating, _hosp.nfhl_flood_class, margins=True
    ).reindex([*_levels, "No rating", "All"])
    _mapped = _hosp[_hosp.nfhl_flood_class.isin(["SFHA", "shaded X", "minimal"])]
    _vh = _mapped[_mapped.tract_flood_rating == "Very High"]
    _vl = _mapped[_mapped.tract_flood_rating == "Very Low"]
    disagreement = {
        "very_high_tract_hospitals_mapped": len(_vh),
        "very_high_tract_outside_sfha": float((_vh.nfhl_flood_class != "SFHA").mean()),
        "very_low_tract_hospitals_mapped": len(_vl),
        "very_low_tract_inside_sfha": float((_vl.nfhl_flood_class == "SFHA").mean()),
        "sfha_hospitals": int((_mapped.nfhl_flood_class == "SFHA").sum()),
        "sfha_hospitals_in_flood_top_decile": float(
            _mapped[_mapped.nfhl_flood_class == "SFHA"].flood_top_decile.mean()
        ),
    }
    sfha_table
    return disagreement, hospitals_sfha, sfha_table


@app.cell
def _(hospitals_sfha, plt, results):
    _levels = ["Very Low", "Relatively Low", "Relatively Moderate", "Relatively High", "Very High"]
    _mapped = hospitals_sfha[
        hospitals_sfha.nfhl_flood_class.isin(["SFHA", "shaded X", "minimal"])
        & hospitals_sfha.tract_flood_rating.isin(_levels)
    ]
    _share = (
        _mapped.assign(in_sfha=_mapped.nfhl_flood_class == "SFHA")
        .groupby("tract_flood_rating")
        .in_sfha.mean()
        .reindex(_levels)
    )
    _fig, _ax = plt.subplots(figsize=(7, 3.2))
    _ax.barh(_share.index, _share.to_numpy() * 100, color="#3b6ea5")
    for _y, _v in enumerate(_share.to_numpy()):
        _ax.text(_v * 100 + 0.1, _y, f"{_v:.1%}", va="center", fontsize=9)
    _ax.set_xlabel("Hospitals inside FEMA's 1% floodplain (SFHA), %")
    _ax.set_title("Tract flood rating vs. the flood zone under the hospital", fontsize=10)
    _ax.spines[["top", "right"]].set_visible(False)
    _fig.tight_layout()
    _fig.savefig(results / "hospitals_sfha_by_rating.png", dpi=150)
    _fig
    return


@app.cell
def _(disagreement, mo):
    mo.md(f"""
    Of {disagreement["very_high_tract_hospitals_mapped"]} hospitals in a "Very High" flood tract
    on a digital flood map, **{disagreement["very_high_tract_outside_sfha"]:.0%} sit outside the
    SFHA**. Of {disagreement["very_low_tract_hospitals_mapped"]} in a "Very Low" tract,
    **{disagreement["very_low_tract_inside_sfha"]:.1%} sit inside it**. Of the
    {disagreement["sfha_hospitals"]} hospitals inside the SFHA, only
    {disagreement["sfha_hospitals_in_flood_top_decile"]:.0%} make the flood top decile.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. The files

    One CSV and one GeoParquet per layer in `results/`, described in
    `results/DATA_DICTIONARY.md`, plus the summary tables.
    """)
    return


@app.cell
def _(
    disagreement,
    facilities,
    flood_check,
    hazards,
    hospital_check,
    hospital_check_summary,
    hospitals_sfha,
    join_report,
    json,
    overlap,
    ranked,
    results,
    sfha_table,
    started,
    time,
    top_facilities,
):
    _base = ["layer", "facility_id", "name", "city", "state", "kind", "tract_fips", "county_fips"]
    _base += ["county_fips_hifld", "RISK_RATNG"]
    _cols = list(_base)
    for _hz, _code in hazards.items():
        _cols += [f"{_code}_RISKR", f"{_code}_EALT", f"{_hz}_rate", f"{_hz}_rank_today"]
        _cols += [f"{_hz}_top_decile"]
        if _code != "IFLD":
            _cols += [f"{_code}_fema_LATE_HIGHER", f"{_code}_rebuilt_LATE_HIGHER"]
            _cols += [f"{_hz}_rank_fema_LATE_HIGHER", f"{_hz}_rank_rebuilt_LATE_HIGHER"]
    _out = ranked.merge(
        hospitals_sfha[["facility_id", "layer", "nfhl_flood_class", "nfhl_zone"]],
        on=["layer", "facility_id"],
        how="left",
    )
    _out["lat"], _out["lon"] = _out.geometry.y, _out.geometry.x
    for _layer, _g in _out.groupby("layer"):
        _keep = [*_cols, "lat", "lon"] + (
            ["nfhl_flood_class", "nfhl_zone"] if _layer == "hospitals" else []
        )
        _g = _g.sort_values("inland_flood_rank_today")
        _g[_keep].to_csv(results / f"{_layer}.csv", index=False)
        _g[[*_keep, "geometry"]].to_parquet(results / f"{_layer}.parquet")
    join_report.to_csv(results / "join_report.csv")
    overlap.to_csv(results / "top100_overlap.csv", index=False)
    top_facilities.to_csv(results / "top_facilities.csv", index=False)
    flood_check.to_csv(results / "known_flood_places.csv", index=False)
    hospital_check.to_csv(results / "known_hospitals_check.csv", index=False)
    sfha_table.to_csv(results / "hospitals_tract_vs_sfha.csv")
    _late = overlap[overlap.scenario == "LATE_HIGHER"]
    headline = {
        "facilities_per_layer": facilities.groupby("layer").size().to_dict(),
        "joined_per_layer": ranked.groupby("layer").size().to_dict(),
        "top100_overlap_late_higher": {
            f"{r.layer}/{r.hazard}/{r.source}": int(r.top100_overlap) for r in _late.itertuples()
        },
        "known_hospitals_top_decile": hospital_check_summary.to_dict(),
        "hospital_tract_vs_sfha": disagreement,
        "run_seconds": round(time.time() - started),
    }
    (results / "headline.json").write_text(json.dumps(headline, indent=2, default=str))
    headline
    return


if __name__ == "__main__":
    app.run()

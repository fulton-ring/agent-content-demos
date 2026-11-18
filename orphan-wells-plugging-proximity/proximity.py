import marimo

__generated_with = "0.17.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    import re
    import time
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import requests
    import us
    from sklearn.neighbors import BallTree
    from statsmodels.stats.contingency_tables import StratifiedTable
    from statsmodels.stats.proportion import confint_proportions_2indep, proportion_confint

    START = time.monotonic()
    DATA = Path(os.environ.get("DATA_DIR", "data"))
    OUT = Path(os.environ.get("OUTPUT_DIR", "outputs"))
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    return (
        BallTree,
        DATA,
        OUT,
        Path,
        START,
        StratifiedTable,
        confint_proportions_2indep,
        gpd,
        json,
        mo,
        np,
        pd,
        plt,
        proportion_confint,
        re,
        requests,
        time,
        us,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Are federal well-plugging dollars reaching the orphaned wells closest to hospitals and schools?

    The Infrastructure Investment and Jobs Act (IIJA) gave states about \$4.4 billion to plug orphaned oil and gas
    wells. Through June 30, 2026, Interior counts 13,108 wells plugged with that money, against about 130,000 still
    documented by USGS. **If states were plugging the wells nearest people first, the plugged wells should sit
    closer to hospitals and schools than the wells still waiting.** This notebook checks that, nationally and in
    the five states that have plugged the most.

    It's wrong if plugged wells are as close or closer to hospitals and schools than unplugged ones.

    Meehan, Kang et al. ([SPE 2025, doi 10.2118/227933-ms](https://doi.org/10.2118/227933-ms)) already counted
    hospitals and schools near the 2022 orphaned well inventory. The new part here is plugged versus unplugged.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## The data

    All four inputs are public and downloaded at run time into `DATA_DIR`:

    - **Plugged wells:** Interior's Orphaned Wells Program Office feature service
      [`DOI_BIL_OWP_St_Program_Data`](https://services.arcgis.com/4OV0eRKiLAYkbH2J/ArcGIS/rest/services/DOI_BIL_OWP_St_Program_Data/FeatureServer/0),
      the live table behind the
      [United States Plugged Orphaned Oil and Gas Well Dataset](https://catalog.data.gov/dataset/united-states-plugged-orphaned-oil-and-gas-well-dataset).
      The data.gov record (11,409 wells, through January 31, 2026) lists no download; the feature service holds
      13,108 wells, the same count as Interior's 2026 report to Congress (through June 30, 2026).
    - **Unplugged wells:** the USGS
      [Documented Orphaned Well Database 2026](https://doi.org/10.5066/P13FHBYG) feature service (CC0).
    - **The 2022 inventory:** the USGS
      [2022 Documented Unplugged Orphaned Oil and Gas Well Dataset](https://doi.org/10.5066/P91PJETI), the list
      states were working from when IIJA money started flowing. Used to see which plugged wells came off it.
    - **Facilities:** HIFLD Next `hospitals-3` v1.1.1 (open hospitals only) and `public-schools` v1.0.0
      (NCES status open, new, added, changed agency or reopened).
    """)
    return


@app.cell
def _(DATA, Path, requests, time):
    def fetch(url: str, name: str) -> Path:
        """Download a file once into DATA_DIR and return its path."""
        path = DATA / name
        if path.exists():
            return path
        for attempt in range(4):
            resp = requests.get(url, timeout=300)
            if resp.status_code == 200:
                path.write_bytes(resp.content)
                return path
            time.sleep(2**attempt)
        raise RuntimeError(f"{url} returned {resp.status_code}")

    def arcgis_table(layer_url: str, name: str) -> Path:
        """Page through an ArcGIS feature layer (at most 200 pages of 2,000) and cache it as Parquet."""
        import pandas as pd

        path = DATA / name
        if path.exists():
            return path
        rows, offset = [], 0
        for _page in range(200):
            resp = requests.get(
                f"{layer_url}/query",
                params={
                    "where": "1=1",
                    "outFields": "*",
                    "outSR": 4326,
                    "orderByFields": "OBJECTID",
                    "resultOffset": offset,
                    "resultRecordCount": 2000,
                    "f": "json",
                },
                timeout=300,
            )
            resp.raise_for_status()
            body = resp.json()
            assert "features" in body, body
            for feature in body["features"]:
                geom = feature.get("geometry") or {}
                rows.append({**feature["attributes"], "lon": geom.get("x"), "lat": geom.get("y")})
            offset += len(body["features"])
            if len(body["features"]) < 2000 and not body.get("exceededTransferLimit"):
                break
        else:
            raise RuntimeError(f"{layer_url} has more than 400,000 rows")
        pd.DataFrame(rows).to_parquet(path)
        return path

    return arcgis_table, fetch


@app.cell
def _(arcgis_table, fetch, gpd, pd):
    _hifld = "https://storage.googleapis.com/hifld-next-datasets-prod/hifld"
    plugged_raw = pd.read_parquet(
        arcgis_table(
            "https://services.arcgis.com/4OV0eRKiLAYkbH2J/ArcGIS/rest/services/DOI_BIL_OWP_St_Program_Data/FeatureServer/0",
            "plugged_owpo.parquet",
        )
    )
    unplugged_raw = pd.read_parquet(
        arcgis_table(
            "https://services.arcgis.com/v01gqwM5QqNysAAi/arcgis/rest/services/"
            "US_Documented_Unplugged_Orphaned_Oil_and_Gas_Well_Dataset/FeatureServer/0",
            "dowdb_2026.parquet",
        )
    )
    inventory_2022 = pd.read_csv(
        fetch(
            "https://www.sciencebase.gov/catalog/file/get/62ebd67bd34eacf539724c56"
            "?f=__disk__11%2Fe9%2F27%2F11e927c652d995f46129f282b400063b5d262369",
            "us_orphaned_wells_2022.csv",
        ),
        encoding="utf-8-sig",
        low_memory=False,
    )
    _hosp = gpd.read_parquet(
        fetch(f"{_hifld}/hospitals-3/hospitals-3/v1.1.1/geoparquet/hospitals-3.parquet", "hospitals-3.parquet")
    )
    hospitals = _hosp[_hosp.STATUS == "OPEN"].reset_index(drop=True)
    _sch = gpd.read_parquet(
        fetch(f"{_hifld}/public-schools/public-schools/v1.0.0/geoparquet/public-schools.parquet", "schools.parquet")
    )
    # NCES status codes: 1 open, 3 new, 4 added, 5 changed agency, 8 reopened; 2, 6 and 7 are closed, inactive, future.
    schools = _sch[_sch.STATUS.astype(int).isin([1, 3, 4, 5, 8])].reset_index(drop=True)
    {
        "plugged (OWPO)": len(plugged_raw),
        "unplugged (USGS 2026)": len(unplugged_raw),
        "2022 inventory": len(inventory_2022),
        "open hospitals": len(hospitals),
        "open public schools": len(schools),
    }
    return hospitals, inventory_2022, plugged_raw, schools, unplugged_raw


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 1: one table of wells, with a well ID that matches across sources

    Each source writes well IDs differently: Interior uses dashed API numbers (`15-039-20417-00-02`), USGS 2026
    stores the API as a number (which drops the leading zero of states like Alabama, `01`), and USGS 2022 uses
    `API:01023198330000`. The first 10 API digits identify a well (state, county, well), so that's the match key.
    Where a state reports its own ID instead of an API number (Indiana's IGS ID, Illinois's reference number,
    Arkansas and Kentucky permits), the key is the state plus that number.

    Location quality is flagged two ways, for the sensitivity check later: USGS notes that say it generated the
    point at a PLSS section center, Interior rows marked `Estimated`, and any point shared by three or more wells
    in the same table (a stacked placeholder location).
    """)
    return


@app.cell
def _(re, us):
    def api_key(raw: object) -> str | None:
        """First 10 digits of an API number, restoring a dropped leading zero."""
        digits = re.sub(r"\D", "", str(raw).split(".")[0]) if raw is not None else ""
        if len(digits) < 9:
            return None
        if len(digits) % 2 == 1:
            digits = "0" + digits
        return digits[:10]

    def local_key(state: str, raw: object) -> str | None:
        """A state's own well number, prefixed by the state so numbers can't collide across states."""
        digits = re.sub(r"\D", "", str(raw).split(".")[0]) if raw is not None else ""
        return f"{state}:{int(digits)}" if digits else None

    def abbr(name: str) -> str:
        found = us.states.lookup(name)
        assert found is not None, name
        return found.abbr

    return abbr, api_key, local_key


@app.cell
def _(abbr, api_key, inventory_2022, local_key, pd, plugged_raw, re, unplugged_raw):
    def _plugged_key(row: pd.Series) -> str | None:
        """Nine or more digits is an API number; anything shorter is the state's own well number."""
        _id = str(row.us_well_id or "")
        return api_key(_id) if len(re.sub(r"\D", "", _id)) >= 9 else local_key(row.state, _id)

    plugged = pd.DataFrame(
        {
            "status": "plugged",
            "well_id": plugged_raw.us_well_id,
            "state": plugged_raw.state,
            "county": plugged_raw.county,
            "witness_date": pd.to_datetime(plugged_raw.witness_date, unit="ms"),
            "program": plugged_raw.Program,
            "lon": plugged_raw.lon,
            "lat": plugged_raw.lat,
            "key": plugged_raw.apply(_plugged_key, axis=1),
            "estimated_location": plugged_raw.location_accuracy.eq("Estimated"),
        }
    )

    _st = unplugged_raw.state.map(abbr)
    _is_api = unplugged_raw.primary_identifier_type.eq("API")
    _primary = [
        api_key(v) if a else local_key(s, v)
        for v, a, s in zip(unplugged_raw.primary_identifier, _is_api, _st, strict=True)
    ]
    # Illinois and Arkansas also carry their own reference or permit number in the secondary identifier.
    _secondary = [
        local_key(s, v) if isinstance(v, str) and v.split(":")[0] in ("RefNo", "Permit") else None
        for v, s in zip(unplugged_raw.secondary_identifier, _st, strict=True)
    ]
    unplugged = pd.DataFrame(
        {
            "status": "unplugged",
            "well_id": unplugged_raw.primary_identifier_type
            + ":"
            + unplugged_raw.primary_identifier.astype("Int64").astype(str),
            "state": _st,
            "county": unplugged_raw.county,
            "witness_date": pd.NaT,
            "program": None,
            "lon": unplugged_raw.lon,
            "lat": unplugged_raw.lat,
            "key": _primary,
            "key2": _secondary,
            "estimated_location": unplugged_raw.location_notes.fillna("").str.contains("section center point"),
        }
    )

    _st22 = inventory_2022.State.map(abbr)
    _id22 = inventory_2022["Well identifier"].fillna("")
    keys_2022 = set(
        k
        for k in (
            api_key(i) if i.startswith("API:") else local_key(s, i) if i.startswith("IGSID:") else None
            for i, s in zip(_id22, _st22, strict=True)
        )
        if k
    )
    keys_2026 = set(unplugged.key.dropna()) | set(unplugged.key2.dropna())

    wells = pd.concat([plugged, unplugged.drop(columns="key2")], ignore_index=True)
    wells = wells[wells.lon.notna() & wells.lat.notna()].reset_index(drop=True)
    _stack = wells.groupby(["status", wells.lon.round(5), wells.lat.round(5)]).well_id.transform("size")
    wells["stacked_location"] = _stack >= 3
    wells["location_flag"] = wells.estimated_location | wells.stacked_location
    wells.groupby("status").agg(
        wells=("well_id", "size"),
        with_match_key=("key", lambda s: s.notna().mean().round(3)),
        section_center_or_estimated=("estimated_location", "sum"),
        stacked=("stacked_location", "sum"),
    )
    return keys_2022, keys_2026, wells


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 2: how many plugged wells came off the documented list?

    If most plugged wells were never on the USGS inventory, plugged and unplugged wells are two different
    populations and a straight comparison says less. The 2022 inventory is the right list to check against: a well
    plugged in 2023 should have been on the 2022 list and off the 2026 one.
    """)
    return


@app.cell
def _(keys_2022, keys_2026, pd, wells):
    _p = wells[wells.status == "plugged"].copy()
    _p["on_2022_list"] = _p.key.isin(keys_2022)
    _p["still_on_2026_list"] = _p.key.isin(keys_2026)
    top_states = _p.state.value_counts().head(5).index.tolist()
    match_by_state = (
        _p.assign(state=_p.state.where(_p.state.isin(top_states + ["PA", "OH"]), "other"))
        .groupby("state")
        .agg(
            plugged=("well_id", "size"),
            has_key=("key", lambda s: s.notna().mean()),
            on_2022_list=("on_2022_list", "mean"),
            still_on_2026_list=("still_on_2026_list", "mean"),
        )
        .sort_values("plugged", ascending=False)
    )
    match_national = pd.Series(
        {
            "plugged": len(_p),
            "has_key": _p.key.notna().mean(),
            "on_2022_list": _p.on_2022_list.mean(),
            "still_on_2026_list": _p.still_on_2026_list.mean(),
        },
        name="all states",
    )
    pd.concat([match_by_state, match_national.to_frame().T]).round(3)
    return match_by_state, match_national, top_states


@app.cell
def _(mo):
    mo.md(r"""
    Kansas, the state that has plugged the most, can't match at all: USGS lists its unplugged wells with no API
    number (USGS's own `USGSID` in 2022, no identifier in 2026). Illinois, Indiana and Arkansas report state well
    numbers that match 1% or fewer of USGS's. So "on the 2022 list" is a lower bound. About one plugged well in seven is still listed as
    unplugged in 2026, mostly in California and Texas, where the state files USGS used predate the plugging.

    ## Step 3: distance from every well to the nearest open hospital and school

    A ball tree with the haversine metric gives great-circle distance to the nearest facility for all ~143,000
    wells in a few seconds. Distances are straight-line, not road distance.
    """)
    return


@app.cell
def _(BallTree, hospitals, np, schools, wells):
    _well_rad = np.radians(wells[["lat", "lon"]].to_numpy())
    for _name, _fac in (("hospital", hospitals), ("school", schools)):
        _tree = BallTree(np.radians(np.c_[_fac.geometry.y, _fac.geometry.x]), metric="haversine")
        _dist, _idx = _tree.query(_well_rad, k=1)
        wells[f"km_to_{_name}"] = _dist[:, 0] * 6371.0088
        wells[f"nearest_{_name}"] = _fac.NAME.to_numpy()[_idx[:, 0]]
    for _band in (1, 2):
        wells[f"hospital_{_band}km"] = wells.km_to_hospital <= _band
        wells[f"school_{_band}km"] = wells.km_to_school <= _band
    wells.groupby("status")[["km_to_hospital", "km_to_school"]].median().round(1)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 4: share of wells within 1 km and 2 km, plugged vs unplugged

    Shares get 95% Wilson intervals, and the plugged-minus-unplugged gap gets a Newcombe interval. These treat
    wells as independent; wells cluster in fields, so the true uncertainty is wider than shown.
    """)
    return


@app.cell
def _(confint_proportions_2indep, pd, proportion_confint, top_states, wells):
    _rows = []
    for _area in ["United States"] + top_states + ["PA", "OH"]:
        _w = wells if _area == "United States" else wells[wells.state == _area]
        _p, _u = _w[_w.status == "plugged"], _w[_w.status == "unplugged"]
        for _fac in ("hospital", "school"):
            for _band in (1, 2):
                _col = f"{_fac}_{_band}km"
                _np, _nu = int(_p[_col].sum()), int(_u[_col].sum())
                _row = {
                    "area": _area,
                    "facility": _fac,
                    "band_km": _band,
                    "plugged_n": len(_p),
                    "unplugged_n": len(_u),
                    "plugged_near": _np,
                    "unplugged_near": _nu,
                    "plugged_share": _np / len(_p) if len(_p) else float("nan"),
                    "unplugged_share": _nu / len(_u) if len(_u) else float("nan"),
                }
                if len(_p) and len(_u):
                    _row["plugged_lo"], _row["plugged_hi"] = proportion_confint(_np, len(_p), method="wilson")
                    _row["unplugged_lo"], _row["unplugged_hi"] = proportion_confint(_nu, len(_u), method="wilson")
                    _row["gap_lo"], _row["gap_hi"] = confint_proportions_2indep(
                        _np, len(_p), _nu, len(_u), method="newcomb"
                    )
                _rows.append(_row)
    shares = pd.DataFrame(_rows)
    shares["gap_pts"] = (shares.plugged_share - shares.unplugged_share) * 100
    shares["unplugged_near_per_plugged_near"] = shares.unplugged_near / shares.plugged_near.replace(0, float("nan"))
    shares[shares.band_km == 2][
        [
            "area",
            "facility",
            "plugged_n",
            "unplugged_n",
            "plugged_share",
            "unplugged_share",
            "gap_pts",
            "gap_lo",
            "gap_hi",
        ]
    ].round(3)
    return (shares,)


@app.cell
def _(mo):
    mo.md(r"""
    The national row mixes states: Kansas and Wyoming have plugged thousands of wells but hold few of the
    unplugged ones, while Ohio and Pennsylvania hold a third of the backlog and have plugged a few hundred. So the
    fairer comparison is **within each state**. The table below has every state with at least 30 wells on each
    side; the pooled Mantel-Haenszel odds ratio combines them. Above 1 means plugged wells are more likely to be
    near a facility than unplugged wells in the same state; below 1, less likely. The pooled ratio is shown with
    and without California, whose unplugged wells sit in Los Angeles-area oil fields and dominate the hospital
    numbers.
    """)
    return


@app.cell
def _(StratifiedTable, np, pd, wells):
    _counts = wells.groupby(["state", "status"]).size().unstack(fill_value=0)
    _states = _counts[(_counts.plugged >= 30) & (_counts.unplugged >= 30)].index.tolist()
    by_state = (
        wells[wells.state.isin(_states)]
        .groupby(["state", "status"])[["hospital_2km", "school_2km"]]
        .mean()
        .unstack()
        .mul(100)
        .round(1)
    )
    by_state.columns = [f"{fac.split('_')[0]} {status} %" for fac, status in by_state.columns]
    by_state.insert(0, "unplugged", _counts.unplugged)
    by_state.insert(0, "plugged", _counts.plugged)
    _rows = []
    for _label, _keep in (("all states", _states), ("without CA", [s for s in _states if s != "CA"])):
        for _fac in ("hospital", "school"):
            for _band in (1, 2):
                _col = f"{_fac}_{_band}km"
                _tables = [
                    pd.crosstab(wells[wells.state == _s].status == "plugged", wells[wells.state == _s][_col])
                    .reindex(index=[True, False], columns=[True, False], fill_value=0)
                    .to_numpy()
                    for _s in _keep
                ]
                _st = StratifiedTable(_tables)
                _lo, _hi = _st.oddsratio_pooled_confint()
                _rows.append(
                    {
                        "states": _label,
                        "facility": _fac,
                        "band_km": _band,
                        "within_state_odds_ratio": _st.oddsratio_pooled,
                        "lo": _lo,
                        "hi": _hi,
                    }
                )
    within_state = pd.DataFrame(_rows)
    assert np.isfinite(within_state.within_state_odds_ratio).all()
    _tables_shown = (by_state.sort_values("unplugged", ascending=False), within_state.round(3))
    _tables_shown
    return by_state, within_state


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 5: where the backlog near people sits, and where the plugging happens

    If plugged wells are about as close as unplugged ones inside each state but farther nationally, the gap is
    about **which states** are plugging. This table puts each state's share of the national plugging next to its
    share of the unplugged wells within 2 km of a school or hospital.
    """)
    return


@app.cell
def _(pd, wells):
    _p = wells[wells.status == "plugged"]
    _u = wells[wells.status == "unplugged"]
    _near = _u[_u.school_2km | _u.hospital_2km]
    allocation = pd.DataFrame(
        {
            "plugged": _p.state.value_counts(),
            "share_of_plugging_%": _p.state.value_counts(normalize=True) * 100,
            "unplugged_near_school_or_hospital": _near.state.value_counts(),
            "share_of_near_backlog_%": _near.state.value_counts(normalize=True) * 100,
        }
    ).fillna(0)
    allocation = allocation.sort_values("unplugged_near_school_or_hospital", ascending=False).round(1)
    allocation.head(12)
    return (allocation,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 6: the same question inside one population

    Plugged and unplugged wells come from different lists. A cleaner test uses only wells that were on the 2022
    inventory: those since plugged with IIJA money (matched by ID) against those still on the 2026 list. Same
    starting list, same states, so any gap is about which ones got picked.
    """)
    return


@app.cell
def _(keys_2022, pd, proportion_confint, top_states, wells):
    _w = wells[wells.key.isin(keys_2022)].copy()
    _w = _w.drop_duplicates(["status", "key"])
    _rows = []
    for _area in ["United States"] + [s for s in top_states + ["PA", "OH"]]:
        _a = _w if _area == "United States" else _w[_w.state == _area]
        for _status in ("plugged", "unplugged"):
            _g = _a[_a.status == _status]
            for _fac in ("hospital", "school"):
                _n, _k = len(_g), int(_g[f"{_fac}_2km"].sum())
                _lo, _hi = proportion_confint(_k, _n, method="wilson") if _n else (float("nan"), float("nan"))
                _rows.append(
                    {
                        "area": _area,
                        "status": _status,
                        "facility": _fac,
                        "n": _n,
                        "near_2km": _k,
                        "share": _k / _n if _n else float("nan"),
                        "lo": _lo,
                        "hi": _hi,
                    }
                )
    same_list = pd.DataFrame(_rows)
    same_list.pivot_table(index=["area", "facility"], columns="status", values=["n", "share"]).round(3)
    return (same_list,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 7: does location error change the answer?

    An Oklahoma field study found database well locations off by about 1 km on average, with about 5% placed on
    section centroids. Two checks: drop every flagged location (section center, estimated, or stacked) and
    recompute; and look only at the 2 km band, which a 1 km error moves less.
    """)
    return


@app.cell
def _(pd, top_states, wells):
    _clean = wells[~wells.location_flag]
    _rows = []
    for _label, _w in (("all wells", wells), ("flagged locations dropped", _clean)):
        for _area in ["United States"] + top_states:
            _a = _w if _area == "United States" else _w[_w.state == _area]
            for _band in (1, 2):
                _r = {"wells": _label, "area": _area, "band_km": _band}
                for _status in ("plugged", "unplugged"):
                    _g = _a[_a.status == _status]
                    _r[f"{_status}_n"] = len(_g)
                    _r[f"{_status}_hospital"] = _g[f"hospital_{_band}km"].mean()
                    _r[f"{_status}_school"] = _g[f"school_{_band}km"].mean()
                _rows.append(_r)
    sensitivity = pd.DataFrame(_rows)
    flagged_share = wells.groupby("status").location_flag.mean()
    sensitivity.round(3)
    return flagged_share, sensitivity


@app.cell
def _(OUT, plt, shares, top_states):
    _s = shares[(shares.band_km == 2) & shares.area.isin(["United States"] + top_states + ["PA", "OH"])]
    _areas = ["United States"] + top_states + ["PA", "OH"]
    _fig, _axes = plt.subplots(1, 2, figsize=(11, 4.2), sharey=True)
    for _ax, _fac in zip(_axes, ("hospital", "school"), strict=True):
        _f = _s[_s.facility == _fac].set_index("area").loc[_areas]
        _x = range(len(_areas))
        for _off, _status, _color in ((-0.2, "plugged", "#2b6cb0"), (0.2, "unplugged", "#c05621")):
            _ax.bar(
                [i + _off for i in _x],
                _f[f"{_status}_share"] * 100,
                width=0.4,
                color=_color,
                label=_status,
                yerr=[
                    (_f[f"{_status}_share"] - _f[f"{_status}_lo"]).fillna(0) * 100,
                    (_f[f"{_status}_hi"] - _f[f"{_status}_share"]).fillna(0) * 100,
                ],
                capsize=2,
            )
        _ax.set_xticks(list(_x), ["US"] + _areas[1:], rotation=0)
        _ax.set_title(f"Share of orphaned wells within 2 km of an open {_fac}")
        _ax.set_ylabel("% of wells")
        _ax.legend(frameon=False)
    _fig.tight_layout()
    _fig.savefig(OUT / "share_within_2km.png", dpi=150)
    _fig
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What states say they prioritize

    Read from the states' own scoring documents (links in the README):

    - **Pennsylvania DEP** scores each well on a worksheet worth about 385 points. "Well within 200 feet of
      occupied building or water supply well" is one 10-point line. Up to 165 points go to harm already happening
      to people: gas or brine in an occupied structure, soil gas near a structure, gas in a water supply.
    - **Texas RRC** uses a 155-point system. "Well located within city or town site limits" is worth 10 and
      proximity to a domestic water well or surface water 3 to 5; a leaking well goes straight to Priority 1 and
      a high fluid level scores 50 by itself.
    - **Ohio ODNR** must keep a scoring matrix by law (ORC 1509.071) but doesn't publish its weights. An ODNR
      presentation shows dwellings, land use and public health multiplied by the well's leak score, so nearby
      homes only count when the well is leaking.
    - **Federal law** (42 U.S.C. 15907) lets states rank wells on "public health and safety", environmental harm
      and land use; it doesn't require putting wells near people first. Interior's July 2025 guidance adds
      production-related land use priorities.

    None of the three names schools or hospitals. Proximity to people counts, but as a small term next to
    whether the well is leaking.
    """)
    return


@app.cell
def _(
    OUT,
    allocation,
    by_state,
    flagged_share,
    gpd,
    match_by_state,
    pd,
    match_national,
    same_list,
    sensitivity,
    shares,
    wells,
    within_state,
):
    _layer = gpd.GeoDataFrame(
        wells.drop(columns=["estimated_location"]),
        geometry=gpd.points_from_xy(wells.lon, wells.lat),
        crs="EPSG:4326",
    )
    _layer.to_parquet(OUT / "orphan_wells_facility_distance.parquet")
    shares.to_csv(OUT / "shares.csv", index=False)
    within_state.to_csv(OUT / "within_state_odds_ratio.csv", index=False)
    by_state.to_csv(OUT / "by_state_2km.csv")
    allocation.to_csv(OUT / "allocation.csv")
    same_list.to_csv(OUT / "same_list_2022.csv", index=False)
    sensitivity.to_csv(OUT / "sensitivity.csv", index=False)
    pd.concat([match_by_state, match_national.to_frame().T]).to_csv(OUT / "match_to_inventory.csv")
    {
        "layer_rows": len(_layer),
        "flagged_location_share": flagged_share.round(3).to_dict(),
        "matched": match_national.round(3).to_dict(),
    }
    return


@app.cell
def _(OUT, START, allocation, json, mo, shares, time, top_states, within_state):
    _us = shares[(shares.area == "United States") & (shares.band_km == 2)].set_index("facility")
    _ws = within_state[(within_state.band_km == 2)].set_index(["states", "facility"])
    _top = shares[shares.area.isin(top_states) & (shares.band_km == 2) & (shares.facility == "school")]
    _closer = int((_top.plugged_share >= _top.unplugged_share).sum())
    _big = shares[shares.area.isin(["PA", "OH"]) & (shares.band_km == 2) & (shares.facility == "school")].set_index(
        "area"
    )
    _oh_pa_near = allocation.loc[["OH", "PA"], "share_of_near_backlog_%"].sum()
    _oh_pa_plug = allocation.loc[["OH", "PA"], "share_of_plugging_%"].sum()
    summary = {
        "national_2km_hospital": [_us.loc["hospital", "plugged_share"], _us.loc["hospital", "unplugged_share"]],
        "national_2km_school": [_us.loc["school", "plugged_share"], _us.loc["school", "unplugged_share"]],
        "within_state_or_2km": _ws[["within_state_odds_ratio", "lo", "hi"]].round(3).reset_index().to_dict("records"),
        "top_states_plugged_as_close_to_schools": f"{_closer} of {len(top_states)}",
        "oh_pa_share_of_near_backlog_pct": round(float(_oh_pa_near), 1),
        "oh_pa_share_of_plugging_pct": round(float(_oh_pa_plug), 1),
        "run_seconds": round(time.monotonic() - START),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=float))
    mo.md(
        f"""
    ## Result

    **Nationally, plugged wells are about half as likely as unplugged ones to sit near a hospital or school:**
    {_us.loc["hospital", "plugged_share"]:.1%} of plugged wells are within 2 km of an open hospital against
    {_us.loc["hospital", "unplugged_share"]:.1%} of unplugged wells, and {_us.loc["school", "plugged_share"]:.1%}
    against {_us.loc["school", "unplugged_share"]:.1%} for schools.

    **Inside the states doing the plugging, the gap mostly disappears.** In {_closer} of the
    {len(top_states)} states that have plugged the most, plugged wells are as likely or more likely than
    unplugged ones to be within 2 km of a school. Pooled within states, the odds ratio for a school within 2 km
    is {_ws.loc[("all states", "school"), "within_state_odds_ratio"]:.2f}
    ({_ws.loc[("all states", "school"), "lo"]:.2f} to {_ws.loc[("all states", "school"), "hi"]:.2f}); for a
    hospital it is {_ws.loc[("all states", "hospital"), "within_state_odds_ratio"]:.2f}, which rises to
    {_ws.loc[("without CA", "hospital"), "within_state_odds_ratio"]:.2f} without California.

    **The national gap is about where the money is being spent.** Ohio and Pennsylvania hold
    {_oh_pa_near:.0f}% of the unplugged wells within 2 km of a school or hospital but account for
    {_oh_pa_plug:.0f}% of the reported plugging. In Pennsylvania {_big.loc["PA", "unplugged_near"]:,} unplugged
    wells sit within 2 km of a school against {_big.loc["PA", "plugged_near"]} plugged ones; in Ohio
    {_big.loc["OH", "unplugged_near"]:,} against {_big.loc["OH", "plugged_near"]}.

    Run time: {summary["run_seconds"]} s. Cost: \\$0, no paid services.
    """
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What this doesn't show

    - **Why** a well was plugged. A state can sensibly plug a leaking well in a field before a quiet one near a
      school. This measures where the money went, not whether the order was wrong.
    - **Road distance or who is inside.** Distances are straight-line to the nearest open facility point.
    - **Undocumented wells.** Many plugged wells were never on the USGS list; Kansas can't be matched at all.
    - **Clustered uncertainty.** Intervals treat wells as independent, which they aren't.
    """)
    return


if __name__ == "__main__":
    app.run()

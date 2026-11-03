import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import json
    import os
    import time
    import urllib.parse
    import urllib.request
    import zipfile
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("BATTERIES_DATA_DIR", HERE / "data"))
    OUT = Path(os.environ.get("BATTERIES_OUTPUT_DIR", HERE / "output"))
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    # Distances and spatial joins are done in CONUS Albers (metres).
    ALBERS = "EPSG:5070"
    RUN_STARTED = time.perf_counter()


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # The grid batteries no public map knows about

    **The question.** The US is building grid batteries faster than ever. Public infrastructure maps were built for
    big plants and lines. How much of the battery fleet, operating and coming, is missing from
    [HIFLD Next](https://hifld.publicenvirodata.org)'s energy layers, and how much of the missing storage sits where
    hurricanes and extreme heat stress the grid most?

    **What we expected.** A large and growing share is unmapped, concentrated in Texas, California and Arizona, and a
    good part of it is in counties with high hurricane or heat exposure.

    **What would make it wrong.** The missing share is small once the newest monthly EIA data is in, or missing storage
    is no more exposed than mapped storage.

    **Already done.** [`hifld-grid-gaps/`](../hifld-grid-gaps/) (#50) matched EIA-860 2025's 1,003 operable battery
    generators (43,643 MW) to HIFLD Next: 19% of the MW was missing from the map and 39% wasn't listed as a unit. This
    notebook reuses its matching, on newer and wider data.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## The data

    Everything is public and downloaded on the first run into `data/` (not committed), then reused.

    | Source | What we use | Version |
    |---|---|---|
    | HIFLD Next | Power Plants, Generating Units | layer v1.0.0 (the layers' records are dated 2023-09 and earlier) |
    | EIA-860M | Operating and Planned generators, prime mover `BA` (battery), with coordinates | September 2026 |
    | EIA-860 | Energy Storage schedule, Operable and Proposed | 2025 annual, used only to reconcile with EIA-860M |
    | LBNL *Queued Up* | Complete Queue Data, active requests with a battery | through 2025, May 2026 file, CC BY 4.0 |
    | FEMA National Risk Index | county hurricane and heat-wave risk ratings | December 2025, FEMA's ArcGIS service |
    | Our FRI rebuild | county hurricane and heat multipliers (`fri-datasets-map/data/`) | this repo, commit `4757ebc` |
    | US Census | county shapes: 2024 for NRI (Connecticut's planning regions), 2020 for the FRI | 1:500k |
    """)
    return


@app.cell
def _():
    def fetch(url: str, name: str) -> Path:
        """Download url into DATA/name once; later runs reuse the copy."""
        path = DATA / name
        if path.exists():
            return path
        request = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (grid-batteries-unmapped spike)"})
        with urllib.request.urlopen(request, timeout=600) as response:
            if response.status != 200:
                raise RuntimeError(f"{url} returned HTTP {response.status}")
            path.write_bytes(response.read())
        return path

    return (fetch,)


@app.cell
def _(fetch):
    _hifld = "https://storage.googleapis.com/hifld-next-datasets-prod/hifld"
    _fri = "https://raw.githubusercontent.com/fulton-ring/agent-content-demos/4757ebc134c67908a2ddadb3a395a441fc9b4d87"
    sources = {
        "HIFLD Next Power Plants": (
            f"{_hifld}/power-plants-1/power-plants-1/v1.0.0/geoparquet/power-plants-1.parquet",
            "power-plants.parquet",
        ),
        "HIFLD Next Generating Units": (
            f"{_hifld}/generating-units-1/generating-units-1/v1.0.0/geopackage/generating-units-1-geopackage.gpkg",
            "generating-units.gpkg",
        ),
        "EIA-860M September 2026": (
            "https://www.eia.gov/electricity/data/eia860m/xls/september_generator2026.xlsx",
            "september_generator2026.xlsx",
        ),
        "EIA-860 2025": ("https://www.eia.gov/electricity/data/eia860/xls/eia8602025.zip", "eia8602025.zip"),
        "LBNL Queued Up (through 2025)": (
            "https://eta-publications.lbl.gov/sites/default/files/2026-05/lbnl_ix_queue_data_file_thru2025.xlsx",
            "lbnl_ix_queue_data_file_thru2025.xlsx",
        ),
        "FRI rebuild: heat multipliers": (
            f"{_fri}/fri-datasets-map/data/multipliers_by_county.csv",
            "fri_multipliers_by_county.csv",
        ),
        "FRI rebuild: hurricane multipliers": (
            f"{_fri}/fri-datasets-map/data/hurricane_by_county.csv",
            "fri_hurricane_by_county.csv",
        ),
        "Census counties 2024": (
            "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip",
            "cb_2024_us_county_500k.zip",
        ),
        "Census counties 2020": (
            "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_county_500k.zip",
            "cb_2020_us_county_500k.zip",
        ),
        "Census states 2024": (
            "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_state_20m.zip",
            "cb_2024_us_state_20m.zip",
        ),
    }
    paths = {label: fetch(url, name) for label, (url, name) in sources.items()}
    return paths, sources


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    FEMA no longer offers the NRI county table as a file download (the old link now redirects to a landing page),
    so we read the ratings from FEMA's public ArcGIS service, two pages of 2,000 counties.
    """)
    return


@app.cell
def _():
    nri_url = (
        "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/National_Risk_Index_Counties/FeatureServer/0"
    )
    nri_path = DATA / "nri_counties.csv"
    if not nri_path.exists():
        _fields = "NRI_VER,STCOFIPS,STATEABBRV,COUNTY,HRCN_RISKR,HRCN_EALR,HWAV_RISKR,HWAV_EALR"
        _pages = []
        for _offset in range(0, 10_000, 2000):  # bounded: there are about 3,200 counties
            _query = urllib.parse.urlencode(
                {
                    "where": "1=1",
                    "outFields": _fields,
                    "returnGeometry": "false",
                    "resultOffset": _offset,
                    "resultRecordCount": 2000,
                    "orderByFields": "STCOFIPS",
                    "f": "json",
                }
            )
            with urllib.request.urlopen(f"{nri_url}/query?{_query}", timeout=120) as _response:
                _page = json.load(_response)
            if "error" in _page:
                raise RuntimeError(f"NRI query failed: {_page['error']}")
            _pages.append(pd.DataFrame([f["attributes"] for f in _page["features"]]))
            if not _page.get("exceededTransferLimit"):
                break
        pd.concat(_pages).to_csv(nri_path, index=False)
    nri = pd.read_csv(nri_path, dtype={"STCOFIPS": str})
    assert nri["STCOFIPS"].is_unique and len(nri) > 3000, "expected one row per county"
    return nri, nri_path, nri_url


@app.cell
def _(nri, nri_path, nri_url, paths, sources):
    _rows = [(label, url, paths[label]) for label, (url, _) in sources.items()]
    _rows.append((f"FEMA NRI counties ({nri['NRI_VER'].iloc[0]})", nri_url, nri_path))
    provenance = pd.DataFrame(
        [(lab, url, round(p.stat().st_size / 1e6, 1), p.stat().st_mtime) for lab, url, p in _rows],
        columns=["source", "url", "MB", "mtime"],
    )
    provenance["downloaded (UTC)"] = pd.to_datetime(provenance.pop("mtime"), unit="s").dt.strftime("%Y-%m-%d %H:%M")
    provenance.to_csv(OUT / "provenance.csv", index=False)
    mo.ui.table(provenance, selection=None)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 1. Every battery generator EIA knows about, operating and planned

    **EIA-860M** is EIA's monthly generator inventory. Its September 2026 edition (the latest at the time of the run)
    lists every generator at plants of at least 1 MW, operating or planned, with coordinates. A battery is a
    generator with prime mover `BA`. We keep the 50 states, DC and Puerto Rico. Storage at sites under 1 MW (homes,
    most businesses) is in neither EIA nor HIFLD by design, and we don't count it.

    "Planned" in EIA-860M runs from *planned, no regulatory approval yet* to *built, not yet in commercial
    operation*. We keep EIA's status codes so a reader can cut it either way.
    """)
    return


@app.cell
def _(paths):
    _frames = []
    for _sheet, _stage in [
        ("Operating", "operating"),
        ("Operating_PR", "operating"),
        ("Planned", "planned"),
        ("Planned_PR", "planned"),
    ]:
        _t = pd.read_excel(paths["EIA-860M September 2026"], sheet_name=_sheet, header=2)
        _t = _t[_t["Prime Mover Code"] == "BA"].copy()
        _year = "Operating Year" if _stage == "operating" else "Planned Operation Year"
        _month = "Operating Month" if _stage == "operating" else "Planned Operation Month"
        _frames.append(
            pd.DataFrame(
                {
                    "eia_plant_id": _t["Plant ID"].astype(int),
                    "eia_generator_id": _t["Generator ID"].astype(str).str.strip().str.upper(),
                    "plant_name": _t["Plant Name"],
                    "state": _t["Plant State"],
                    "eia_county": _t["County"],
                    "balancing_authority": _t["Balancing Authority Code"],
                    "stage": _stage,
                    "eia_status": _t["Status"].str.extract(r"^\((\w+)\)", expand=False),
                    "mw": _t["Nameplate Capacity (MW)"].astype(float),
                    "mwh": pd.to_numeric(_t.get("Nameplate Energy Capacity (MWh)"), errors="coerce"),
                    "year_online": _t[_year].astype(int),
                    "month_online": _t[_month].astype(int),
                    "latitude": _t["Latitude"].astype(float),
                    "longitude": _t["Longitude"].astype(float),
                }
            )
        )
    batteries = pd.concat(_frames, ignore_index=True)
    assert batteries["latitude"].notna().all(), "every EIA-860M battery should have coordinates"
    assert not batteries.duplicated(["eia_plant_id", "eia_generator_id"]).any(), "a generator should appear once"
    batteries.groupby("stage").agg(generators=("mw", "size"), MW=("mw", "sum"), plants=("eia_plant_id", "nunique"))
    return (batteries,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Reconciling with EIA-860 2025.** The annual survey is the vetted source; the monthly one is newer. The check
    below asks where each of the annual file's battery generators is in the September 2026 monthly file. An
    operable 2025 battery should still be operating; a proposed one may have come online, still be planned, or be
    gone (cancelled or postponed).
    """)
    return


@app.cell
def _(batteries, paths):
    _zip = zipfile.ZipFile(paths["EIA-860 2025"])
    _annual = []
    for _sheet in ["Operable", "Proposed"]:
        _t = pd.read_excel(_zip.open("3_4_Energy_Storage_Y2025.xlsx"), sheet_name=_sheet, header=1)
        _t = _t[_t["Prime Mover"] == "BA"]
        _annual.append(
            pd.DataFrame(
                {
                    "key": _t["Plant Code"].astype(int).astype(str)
                    + "-"
                    + _t["Generator ID"].astype(str).str.strip().str.upper(),
                    "eia860_2025": _sheet,
                    "mw": _t["Nameplate Capacity (MW)"].astype(float),
                }
            )
        )
    _annual = pd.concat(_annual)
    _monthly = batteries.assign(
        key=batteries["eia_plant_id"].astype(str) + "-" + batteries["eia_generator_id"]
    ).set_index("key")["stage"]
    _annual["in EIA-860M Sep 2026"] = _annual["key"].map(_monthly).fillna("not listed")
    reconciliation = _annual.pivot_table(
        index="eia860_2025", columns="in EIA-860M Sep 2026", values="mw", aggfunc=["size", "sum"], fill_value=0
    ).round(0)
    reconciliation.columns = [f"{'generators' if a == 'size' else 'MW'}, {b}" for a, b in reconciliation.columns]
    reconciliation.to_csv(OUT / "reconciliation_eia860_2025.csv")
    mo.ui.table(reconciliation.reset_index(), selection=None)
    return (reconciliation,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 2. Which of them HIFLD Next has

    The matching is copied from `hifld-grid-gaps/` (#50), in order:

    1. Is the **unit** in Generating Units? HIFLD's unit `ID` is `<plant code>-<generator id>`.
    2. If not, is its **plant** in Power Plants by EIA plant code?
    3. If not, is there **any HIFLD power plant within 1 km** of EIA's coordinates?

    A battery that fails all three is **missing from HIFLD Next** (`in_hifld_next` is false). One that passes only
    2 or 3 has its site on the map but not the battery itself. Generating Units also lists planned units, as of
    2023, so a planned battery can pass step 1.
    """)
    return


@app.cell
def _(batteries, paths):
    plants = gpd.read_parquet(paths["HIFLD Next Power Plants"]).to_crs(ALBERS)
    units = gpd.read_file(paths["HIFLD Next Generating Units"])
    _unit_status = units.assign(key=units["ID"].astype(str).str.upper().str.strip()).drop_duplicates("key")
    _unit_status = _unit_status.set_index("key")["STATUS"]
    matched = batteries.copy()
    _key = matched["eia_plant_id"].astype(str) + "-" + matched["eia_generator_id"]
    matched["hifld_unit_status"] = _key.map(_unit_status)
    _unit_listed = matched["hifld_unit_status"].notna()
    # A few HIFLD plant codes are not numbers (for example "NA919"), so compare codes as text.
    _plant_listed = matched["eia_plant_id"].astype(str).isin(set(plants["PLANT_CODE"].astype(str)))
    _points = gpd.GeoDataFrame(
        index=matched.index, geometry=gpd.points_from_xy(matched["longitude"], matched["latitude"]), crs=4326
    ).to_crs(ALBERS)
    _near = gpd.sjoin_nearest(_points, plants[["geometry"]], distance_col="m")
    matched["m_to_hifld_plant"] = _near.groupby(level=0)["m"].min().round(0)
    matched["match"] = np.select(
        [_unit_listed, _plant_listed, matched["m_to_hifld_plant"] <= 1000],
        ["1 unit in Generating Units", "2 plant code in Power Plants", "3 HIFLD plant within 1 km"],
        default="4 missing from HIFLD Next",
    )
    matched["in_hifld_next"] = matched["match"] != "4 missing from HIFLD Next"
    _hifld_dates = (
        f"{units['SOURCEDATE'].astype(str).str[:10].max()} / {plants['SOURCEDATE'].astype(str).str[:10].max()}"
    )
    mo.md(f"Newest record date, Generating Units / Power Plants: **{_hifld_dates}**.")
    return (matched,)


@app.cell
def _(matched):
    def share_missing(frame: pd.DataFrame, by: list[str]) -> pd.DataFrame:
        """Generators and MW by group, with the MW missing from HIFLD Next and its share."""
        missing_mw = frame["mw"].where(~frame["in_hifld_next"], 0.0)
        table = (
            frame.assign(missing_mw=missing_mw, missing=~frame["in_hifld_next"])
            .groupby(by, observed=True)
            .agg(
                generators=("mw", "size"),
                MW=("mw", "sum"),
                missing_generators=("missing", "sum"),
                MW_missing=("missing_mw", "sum"),
            )
        )
        table["share_MW_missing"] = (table["MW_missing"] / table["MW"]).round(3)
        return table.round({"MW": 0, "MW_missing": 0})

    by_match = (
        matched.groupby(["stage", "match"])
        .agg(generators=("mw", "size"), MW=("mw", "sum"))
        .assign(share_of_stage_MW=lambda t: (t["MW"] / t.groupby(level=0)["MW"].transform("sum")).round(3))
        .round({"MW": 0})
    )
    by_stage = share_missing(matched, ["stage"])
    by_match.to_csv(OUT / "batteries_by_match.csv")
    by_stage.to_csv(OUT / "batteries_by_stage.csv")
    mo.vstack([by_stage, by_match])
    return by_stage, share_missing


@app.cell(hide_code=True)
def _(by_stage, matched):
    _op = by_stage.loc["operating"]
    _pl = by_stage.loc["planned"]
    _op_listed = matched[(matched["stage"] == "operating") & (matched["match"] == "1 unit in Generating Units")]
    mo.md(f"""
    **Operating:** {_op["generators"]:,} battery generators, **{_op["MW"]:,.0f} MW**, of which
    **{_op["MW_missing"]:,.0f} MW ({_op["share_MW_missing"]:.0%}) is missing from HIFLD Next**, against 19% of
    EIA-860 2025's operable batteries in #50. Only {_op_listed["mw"].sum() / _op["MW"]:.0%} of operating battery MW
    is listed as a unit in Generating Units. **Planned:** {_pl["generators"]:,} generators, **{_pl["MW"]:,.0f} MW**,
    {_pl["share_MW_missing"]:.0%} of it missing.
    """)
    return


@app.cell
def _(matched, share_missing):
    by_state = share_missing(matched, ["state", "stage"]).unstack("stage")
    by_state.columns = [f"{stage} {col}" for col, stage in by_state.columns]
    by_state = by_state.fillna(0).sort_values("operating MW_missing", ascending=False)
    by_year = share_missing(matched, ["stage", "year_online"])
    by_state.to_csv(OUT / "batteries_by_state.csv")
    by_year.to_csv(OUT / "batteries_by_year_online.csv")
    mo.vstack(
        [
            mo.md("**By state** (top 15 by operating MW missing)"),
            by_state.head(15),
            mo.md("**By year online**"),
            by_year,
        ]
    )
    return by_state, by_year


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 3. The queue: battery capacity waiting to connect

    LBNL's *Queued Up* compiles the interconnection queues of the seven ISOs and about 50 utilities. Its Excel data
    file (data through the end of 2025) is published under CC BY 4.0, credit to Lawrence Berkeley National Laboratory
    and GridTracker, so we can use and redistribute it. We keep **active** requests and count only the MW on
    battery components: a request's `type_1`, `type_2` or `type_3` equal to `Battery`, with its `mw_1`, `mw_2` or
    `mw_3`. LBNL imputes storage MW for hybrids that don't report it in its report, but leaves those values out of
    this file, so hybrid requests with no battery MW count as zero here.

    The queue lists only a county, no coordinates, and a queued project is by definition not built, so there is
    nothing to match against HIFLD. We use it for the hazard comparison only. Queues are known to hold far more
    than gets built: most requests are withdrawn.
    """)
    return


@app.cell
def _(paths):
    _q = pd.read_excel(paths["LBNL Queued Up (through 2025)"], sheet_name="03. Complete Queue Data", header=1)
    _active = _q[_q["q_status"] == "active"].copy()
    _battery_mw = sum(
        pd.to_numeric(_active[f"mw_{i}"], errors="coerce").fillna(0.0).where(_active[f"type_{i}"] == "Battery", 0.0)
        for i in (1, 2, 3)
    )
    _has_battery = (_active[["type_1", "type_2", "type_3"]] == "Battery").any(axis=1)
    queue = _active.assign(battery_mw=_battery_mw)[_has_battery]
    queue = queue.assign(fips=queue["fips_code"].astype("Int64").astype(str).str.zfill(5).replace("<NA>", pd.NA))
    queue_no_mw = int((queue["battery_mw"] == 0).sum())
    queue_no_county = queue.loc[queue["fips"].isna(), "battery_mw"].sum()
    queue_by_state = (
        queue.groupby("state")
        .agg(requests=("battery_mw", "size"), queued_battery_MW=("battery_mw", "sum"))
        .sort_values("queued_battery_MW", ascending=False)
        .round(0)
    )
    queue_by_state.to_csv(OUT / "queue_battery_by_state.csv")
    mo.vstack(
        [
            mo.md(
                f"**{len(queue):,} active requests include a battery, {queue['battery_mw'].sum():,.0f} MW of it.** "
                f"{queue_no_mw:,} hybrid requests list a battery with no battery MW. "
                f"{queue_no_county:,.0f} MW has no county."
            ),
            queue_by_state.head(15),
        ]
    )
    return queue, queue_by_state


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 4. Hurricane and heat exposure

    Each battery is placed in a county by its EIA coordinates (the nearest county for the few just offshore), then
    given:

    - **FEMA NRI** hurricane and heat-wave risk ratings (`Very High`, `Relatively High`, ... , `No Rating`). "High"
      below means `Very High` or `Relatively High`. NRI's December 2025 release uses Connecticut's 2022 planning
      regions, so this join uses 2024 county shapes.
    - **Our FRI rebuild's** multipliers for mid-century, higher warming (`MID_HIGHER`): extreme heat from LOCA2 at
      the 95th percentile (`EXHT_L95`, the heat column the rebuild reproduced best) and our open hurricane layer's
      central value. The FRI uses 2020 counties, so this join uses 2020 shapes. A multiplier of 1.5 means the
      county's expected annual loss from that hazard grows half again. "High" below means the county is in the top
      fifth of all counties for that multiplier; counties our hurricane layer doesn't cover count as not high.
    """)
    return


@app.cell
def _(matched, nri, paths):
    def county_of(frame: pd.DataFrame, shapes_zip: Path) -> pd.Series:
        """Five-digit county FIPS for each row's coordinates; the nearest county when a point falls in none."""
        counties = gpd.read_file(f"zip://{shapes_zip}")[["GEOID", "geometry"]].to_crs(ALBERS)
        points = gpd.GeoDataFrame(
            index=frame.index, geometry=gpd.points_from_xy(frame["longitude"], frame["latitude"]), crs=4326
        ).to_crs(ALBERS)
        joined = gpd.sjoin_nearest(points, counties, how="left")
        return joined[~joined.index.duplicated()]["GEOID"]

    _fri = pd.read_csv(paths["FRI rebuild: heat multipliers"], dtype={"fips": str})
    _heat = _fri[(_fri["hazard"] == "EXHT_L95") & (_fri["scenario"] == "MID_HIGHER")].set_index("fips")["rebuilt_hm"]
    _hrcn = pd.read_csv(paths["FRI rebuild: hurricane multipliers"], dtype={"fips": str})
    _hrcn = _hrcn[_hrcn["scenario"] == "MID_HIGHER"].set_index("fips")["our_hm"]
    # "High" is the top fifth of counties. Counties without a hurricane value (not covered) are not high.
    heat_cut = float(_heat.quantile(0.8))
    hrcn_cut = float(_hrcn.reindex(_fri["fips"].unique()).fillna(1.0).quantile(0.8))
    _nri = nri.set_index("STCOFIPS")

    exposed = matched.copy()
    exposed["county_fips_2024"] = county_of(exposed, paths["Census counties 2024"])
    exposed["county_fips_2020"] = county_of(exposed, paths["Census counties 2020"])
    for _col in ["HRCN_RISKR", "HRCN_EALR", "HWAV_RISKR", "HWAV_EALR"]:
        exposed[f"nri_{_col.lower()}"] = exposed["county_fips_2024"].map(_nri[_col])
    exposed["fri_heat_hm"] = exposed["county_fips_2020"].map(_heat)
    exposed["fri_hurricane_hm"] = exposed["county_fips_2020"].map(_hrcn)
    _high = {"Very High", "Relatively High"}
    exposed["nri_hurricane_high"] = exposed["nri_hrcn_riskr"].isin(_high)
    exposed["nri_heat_high"] = exposed["nri_hwav_riskr"].isin(_high)
    exposed["fri_heat_high"] = exposed["fri_heat_hm"] >= heat_cut
    exposed["fri_hurricane_high"] = exposed["fri_hurricane_hm"].fillna(1.0) >= hrcn_cut
    assert exposed["nri_hrcn_riskr"].notna().all(), "every battery should land in an NRI county"
    mo.md(f"Top-fifth cut-offs: FRI heat multiplier **{heat_cut:.2f}**, FRI hurricane multiplier **{hrcn_cut:.3f}**.")
    return county_of, exposed, heat_cut, hrcn_cut


@app.cell
def _(exposed, heat_cut, hrcn_cut, nri, paths, queue):
    _flags = {
        "NRI hurricane high": "nri_hurricane_high",
        "NRI heat wave high": "nri_heat_high",
        "FRI hurricane top fifth": "fri_hurricane_high",
        "FRI heat top fifth": "fri_heat_high",
    }
    _rows = []
    for _stage in ["operating", "planned"]:
        for _mapped in [True, False]:
            _sel = exposed[(exposed["stage"] == _stage) & (exposed["in_hifld_next"] == _mapped)]
            _row = {"group": f"{_stage}, {'mapped' if _mapped else 'missing'}", "MW": _sel["mw"].sum()}
            for _label, _col in _flags.items():
                _row[f"MW {_label}"] = _sel.loc[_sel[_col], "mw"].sum()
                _row[f"share {_label}"] = _row[f"MW {_label}"] / _row["MW"]
            _rows.append(_row)

    # The queue joins by its county FIPS. Its FIPS predate Connecticut's planning regions, so they match the FRI's
    # 2020 counties directly; NRI's Connecticut rows don't match and count as not high (Connecticut has little queue).
    _fri = pd.read_csv(paths["FRI rebuild: heat multipliers"], dtype={"fips": str})
    _heat = _fri[(_fri["hazard"] == "EXHT_L95") & (_fri["scenario"] == "MID_HIGHER")].set_index("fips")["rebuilt_hm"]
    _hrcn = pd.read_csv(paths["FRI rebuild: hurricane multipliers"], dtype={"fips": str})
    _hrcn = _hrcn[_hrcn["scenario"] == "MID_HIGHER"].set_index("fips")["our_hm"]
    _nri = nri.set_index("STCOFIPS")
    _q = queue.dropna(subset=["fips"])
    _qflags = {
        "NRI hurricane high": _q["fips"].map(_nri["HRCN_RISKR"]).isin({"Very High", "Relatively High"}),
        "NRI heat wave high": _q["fips"].map(_nri["HWAV_RISKR"]).isin({"Very High", "Relatively High"}),
        "FRI hurricane top fifth": _q["fips"].map(_hrcn).fillna(1.0) >= hrcn_cut,
        "FRI heat top fifth": _q["fips"].map(_heat) >= heat_cut,
    }
    _row = {"group": "queued (active requests)", "MW": _q["battery_mw"].sum()}
    for _label, _flag in _qflags.items():
        _row[f"MW {_label}"] = _q.loc[_flag, "battery_mw"].sum()
        _row[f"share {_label}"] = _row[f"MW {_label}"] / _row["MW"]
    _rows.append(_row)
    exposure = pd.DataFrame(_rows).set_index("group")
    exposure = exposure.round({c: 0 for c in exposure.columns if c.startswith("MW")}).round(3)
    exposure.to_csv(OUT / "exposure_mapped_vs_missing.csv")
    exposure[[c for c in exposure.columns if c == "MW" or c.startswith("share")]]
    return (exposure,)


@app.cell(hide_code=True)
def _(exposure):
    _om, _ox = exposure.loc["operating, mapped"], exposure.loc["operating, missing"]
    _pm, _px = exposure.loc["planned, mapped"], exposure.loc["planned, missing"]
    mo.md(f"""
    **Operating storage missing from HIFLD Next vs. mapped**, share of MW in high-exposure counties:
    NRI hurricane **{_ox["share NRI hurricane high"]:.0%} vs {_om["share NRI hurricane high"]:.0%}**,
    NRI heat wave **{_ox["share NRI heat wave high"]:.0%} vs {_om["share NRI heat wave high"]:.0%}**,
    FRI hurricane **{_ox["share FRI hurricane top fifth"]:.0%} vs {_om["share FRI hurricane top fifth"]:.0%}**,
    FRI heat **{_ox["share FRI heat top fifth"]:.0%} vs {_om["share FRI heat top fifth"]:.0%}**.
    In MW: **{_ox["MW NRI hurricane high"]:,.0f} MW** of missing operating storage is in NRI high-hurricane counties
    and **{_ox["MW NRI heat wave high"]:,.0f} MW** in NRI high-heat-wave counties.
    Planned, missing vs mapped: NRI hurricane {_px["share NRI hurricane high"]:.0%} vs
    {_pm["share NRI hurricane high"]:.0%}, NRI heat wave {_px["share NRI heat wave high"]:.0%} vs
    {_pm["share NRI heat wave high"]:.0%}.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5. The file: every US battery generator, with its map status and exposure

    One row per battery generator in EIA-860M, operating or planned. `output/batteries.csv` and
    `output/batteries.parquet` (GeoParquet, points in WGS84) hold the same rows; `DATA_DICTIONARY.md` explains each
    column. A plant with several battery generators has several rows, all with the same plant ID.
    """)
    return


@app.cell
def _(exposed):
    _columns = [
        "eia_plant_id",
        "eia_generator_id",
        "plant_name",
        "state",
        "eia_county",
        "county_fips_2024",
        "county_fips_2020",
        "balancing_authority",
        "stage",
        "eia_status",
        "mw",
        "mwh",
        "year_online",
        "month_online",
        "latitude",
        "longitude",
        "in_hifld_next",
        "match",
        "hifld_unit_status",
        "m_to_hifld_plant",
        "nri_hrcn_riskr",
        "nri_hrcn_ealr",
        "nri_hwav_riskr",
        "nri_hwav_ealr",
        "fri_hurricane_hm",
        "fri_heat_hm",
        "nri_hurricane_high",
        "nri_heat_high",
        "fri_hurricane_high",
        "fri_heat_high",
    ]
    published = exposed[_columns].sort_values(["state", "eia_plant_id", "eia_generator_id"]).reset_index(drop=True)
    published.to_csv(OUT / "batteries.csv", index=False)
    gpd.GeoDataFrame(
        published, geometry=gpd.points_from_xy(published["longitude"], published["latitude"]), crs=4326
    ).to_parquet(OUT / "batteries.parquet")
    mo.ui.table(published.head(50), selection=None)
    return (published,)


@app.cell
def _(paths, published):
    _states = gpd.read_file(f"zip://{paths['Census states 2024']}")
    _lower48 = _states[~_states["STUSPS"].isin(["AK", "HI", "PR", "VI", "GU", "MP", "AS"])].to_crs(ALBERS)
    _counties = gpd.read_file(f"zip://{paths['Census counties 2024']}")[["GEOID", "STUSPS", "geometry"]]
    _counties = _counties[_counties["STUSPS"].isin(set(_lower48["STUSPS"]))].to_crs(ALBERS)
    _rated = published.drop_duplicates("county_fips_2024").set_index("county_fips_2024")
    _nri = pd.read_csv(DATA / "nri_counties.csv", dtype={"STCOFIPS": str}).set_index("STCOFIPS")
    _exposure = (
        _nri["HRCN_RISKR"].isin({"Very High", "Relatively High"}).astype(int)
        + _nri["HWAV_RISKR"].isin({"Very High", "Relatively High"}).astype(int) * 2
    )
    _counties["exposure"] = _counties["GEOID"].map(_exposure).fillna(0).astype(int)
    _pts = gpd.GeoDataFrame(
        published, geometry=gpd.points_from_xy(published["longitude"], published["latitude"]), crs=4326
    ).to_crs(ALBERS)
    _pts = _pts[(_pts["stage"] == "operating") & _pts.within(_lower48.union_all())]
    _fig, _ax = plt.subplots(figsize=(12, 7.5))
    _palette = {0: "#f4f4f4", 1: "#bcd4e6", 2: "#f6d3a8", 3: "#e6a6a6"}
    _counties.plot(ax=_ax, color=_counties["exposure"].map(_palette), edgecolor="none")
    _lower48.boundary.plot(ax=_ax, color="#999999", linewidth=0.4)
    for _mapped, _color, _label in [
        (True, "#7a8691", "operating, in HIFLD Next"),
        (False, "#b5172e", "operating, missing"),
    ]:
        _sel = _pts[_pts["in_hifld_next"] == _mapped]
        _sel.plot(ax=_ax, markersize=_sel["mw"].clip(2, 500) / 3, color=_color, alpha=0.65, label=_label)
    for _code, _name in [(1, "NRI hurricane high"), (2, "NRI heat wave high"), (3, "both")]:
        _ax.scatter([], [], marker="s", s=80, color=_palette[_code], label=f"county: {_name}")
    _ax.set_axis_off()
    _ax.legend(loc="lower left", frameon=False, fontsize=8)
    _ax.set_title("Operating grid batteries (EIA-860M, Sep 2026) missing from HIFLD Next, over NRI hurricane and heat")
    _fig.tight_layout()
    _fig.savefig(OUT / "map_missing_storage.png", dpi=110)
    mo.as_html(_fig)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 6. Hand check: are the "missing" batteries really there?

    A missing battery could be an EIA coordinate error, or a plant that isn't built. We drew a seeded random sample
    of 30 operating plants whose batteries are all missing from HIFLD Next, and looked at each on dated public
    imagery (`hand_check_chips.py` draws the images; `hand_check.csv` holds our labels):

    - **NAIP**, the USDA's 0.6 m aerial imagery, newest year available from USGS's public NAIP service. Public NAIP
      currently ends in 2022 or 2023 depending on the state, so it predates most of these plants.
    - **Sentinel-2** at 10 m, the clearest 2026 scene from Microsoft's Planetary Computer, for plants built after
      the NAIP year. A battery yard of a few hectares shows as a new bright block of container rows and a fenced pad.

    A plant counts as **confirmed** if either image shows a battery yard or one under construction at or next to
    EIA's coordinates.
    """)
    return


@app.cell
def _(published):
    _missing_plants = (
        published[published["stage"] == "operating"]
        .groupby("eia_plant_id")
        .agg(
            plant_name=("plant_name", "first"),
            state=("state", "first"),
            latitude=("latitude", "first"),
            longitude=("longitude", "first"),
            mw=("mw", "sum"),
            year_online=("year_online", "min"),
            any_mapped=("in_hifld_next", "any"),
        )
    )
    _missing_plants = _missing_plants[~_missing_plants["any_mapped"]].drop(columns="any_mapped")
    hand_sample = _missing_plants.sample(n=30, random_state=183).reset_index()
    hand_sample.to_csv(OUT / "hand_check_sample.csv", index=False)
    mo.md(f"{len(_missing_plants):,} operating plants have only missing batteries; the sample is 30 of them.")
    return (hand_sample,)


@app.cell
def _(hand_sample):
    def wilson(k: int, n: int) -> tuple[float, float]:
        """95% Wilson score interval for k successes in n."""
        z, p = 1.96, k / n
        centre = (p + z**2 / (2 * n)) / (1 + z**2 / n)
        half = z * np.sqrt(p * (1 - p) / n + z**2 / (4 * n**2)) / (1 + z**2 / n)
        return centre - half, centre + half

    _labels_path = HERE / "hand_check.csv"
    hand_result = None
    if not _labels_path.exists():
        _out = mo.md("`hand_check.csv` isn't there yet: run `hand_check_chips.py` and label the images.")
    else:
        _labels = pd.read_csv(_labels_path).merge(hand_sample, on="eia_plant_id", validate="one_to_one")
        assert len(_labels) == len(hand_sample), "labels must match the sample"
        _rows = []
        for _name, _sel in [("all 30", _labels), ("20 MW or more", _labels[_labels["mw"] >= 20])]:
            _k, _n = int(_sel["confirmed"].sum()), len(_sel)
            _low, _high = wilson(_k, _n)
            _rows.append({"sample": _name, "plants": _n, "confirmed": _k, "share": _k / _n, "low": _low, "high": _high})
        hand_result = pd.DataFrame(_rows).set_index("sample").round(3)
        hand_result.to_csv(OUT / "hand_check_result.csv")
        _naip_old = (_labels["year_online"] > 2023).sum()
        _out = mo.vstack(
            [
                hand_result,
                _labels.groupby("label").agg(plants=("mw", "size"), MW=("mw", "sum")).round(0),
                mo.md(
                    f"{_naip_old} of the 30 plants came online after 2023, later than any public NAIP photo of them; "
                    "those were checked on Sentinel-2 alone."
                ),
            ]
        )
    mo.output.replace(_out)
    return (hand_result,)


@app.cell(hide_code=True)
def _(by_state, queue_by_state):
    _top = by_state.head(3).index.tolist()
    _qtop = queue_by_state.head(3).index.tolist()
    mo.md(f"""
    ## What we found, and what didn't work

    - The states with the most operating battery MW missing from HIFLD Next are **{", ".join(_top)}**; the largest
      queues are in **{", ".join(_qtop)}**. See `output/batteries_by_state.csv` and
      `output/queue_battery_by_state.csv`.
    - **NAIP is too old for this question.** The public NAIP services we could reach (USGS's NAIP Plus and Planetary
      Computer) end in 2022-2023, before most of the missing plants were built. Esri's NAIP image service was
      not reachable from our run. We fell back on 10 m Sentinel-2, which can't resolve plants of a few MW.
    - **FEMA's NRI table download moved**; the old `hazards.fema.gov` link redirects to a landing page. FEMA's ArcGIS
      service still serves the December 2025 data.
    - **LBNL's `emp.lbl.gov` blocks scripted downloads** (HTTP 403); the same file on `eta-publications.lbl.gov`
      downloads fine.
    - The queue has county locations only, and hybrid requests without a stated battery MW count as zero.
    - The FRI multipliers are our reconstruction, not FEMA's values (see `fri-datasets-map/`).
    """)
    return


@app.cell
def _():
    _seconds = time.perf_counter() - RUN_STARTED
    pd.DataFrame([{"run_seconds": round(_seconds, 1)}]).to_csv(OUT / "run_time.csv", index=False)
    mo.md(f"Run time: **{_seconds:.0f} s**.")
    return


if __name__ == "__main__":
    app.run()

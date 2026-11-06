import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import itertools
    import os
    import time
    from pathlib import Path

    import duckdb
    import geopandas as gpd
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import requests
    import shapely
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree

    started = time.perf_counter()
    return (
        Path,
        cKDTree,
        connected_components,
        coo_matrix,
        duckdb,
        gpd,
        itertools,
        mo,
        np,
        os,
        pd,
        plt,
        requests,
        shapely,
        started,
        time,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # A county grid-exposure index: high-voltage substations by county and hazard

    **The question.** Can we publish something useful about where the US grid's high-voltage substations meet
    natural hazards, without publishing the substations themselves? The answer we build is one row per county:
    how many substations of 230 kV and up (and 345 kV and up) it holds, and how many of those sit where the
    once-per-century geomagnetic field is high or in a county the Future Risk Index rates high for coastal flood,
    wildfire, heat or hurricane. Counts and shares only. Before anything is written, a suppression rule makes
    sure no row can be used to pin down a single substation, and a test checks it.

    **Steps.** (1) Counties. (2) Rebuild the substations from HIFLD Next transmission lines, exactly as
    `us-substations-verified/` does, and measure how much of OpenStreetMap's 230 kV+ set they miss.
    (3) Rate each substation's geomagnetic hazard. (4) Read each county's FRI and NRI ratings. (5) Count by county.
    (6) Suppress and test. (7) Write the table and answer the card's two questions.

    Every input is public and downloaded into `data/` on the first run. Nothing at the level of a point
    (coordinates, names, site lists) is written to `outputs/`.
    """)
    return


@app.cell
def _(Path, os, requests):
    DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
    OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "outputs"))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def download(url: str, name: str) -> Path:
        """Download url to DATA_DIR/name once; later runs reuse the file."""
        path = DATA_DIR / name
        if path.exists():
            return path
        for attempt in range(3):
            response = requests.get(url, timeout=300)
            if response.ok:
                path.write_bytes(response.content)
                return path
            print(f"{url}: HTTP {response.status_code} (attempt {attempt + 1} of 3)")
        raise RuntimeError(f"Could not download {url}")

    return DATA_DIR, OUTPUT_DIR, download


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Counties

    Census 2024 cartographic boundaries, 1:500k, the 50 states and DC (state FIPS up to 56), in a US equal-area
    projection (EPSG:5070) so distances below are in metres.
    """)
    return


@app.cell
def _(download, gpd):
    _zip = download(
        "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip", "cb_2024_us_county_500k.zip"
    )
    counties = gpd.read_file(_zip)
    counties = counties[counties["STATEFP"].astype(int) <= 56].to_crs(5070)
    counties = counties[["GEOID", "NAME", "STUSPS", "geometry"]].rename(
        columns={"GEOID": "fips", "NAME": "county", "STUSPS": "state"}
    )
    counties = counties.sort_values("fips").reset_index(drop=True)
    print(f"{len(counties):,} counties and county equivalents in the 50 states and DC")
    return (counties,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Substations, rebuilt from HIFLD Next line ends

    HIFLD Next has no substations layer. This cell and the next are copied from `us-substations-verified/verify.py`
    (section 2), which copied them from `county-bans-substations/`: merge transmission-line ends within 100 m into
    nodes, name each node from the `SUB_1`/`SUB_2` names its lines share, drop the `TAP…` nodes, and give each node
    the highest voltage of the lines ending there. The assert checks we get the same 45,779 substations.
    """)
    return


@app.cell
def _(cKDTree, connected_components, coo_matrix, download, gpd, np, pd, shapely):
    lines_path = download(
        "https://storage.googleapis.com/hifld-next-datasets-prod/hifld/transmission-lines-1/transmission-lines-1/v1.0.0/geoparquet/transmission-lines-1.parquet",
        "hifld-next-transmission-lines-v1.0.0.parquet",
    )
    _lines_all = gpd.read_parquet(lines_path)
    _lines = (
        _lines_all[~_lines_all["STATUS"].isin(["INACTIVE", "UNDER CONSTRUCTION"])].to_crs(5070).reset_index(drop=True)
    )
    _lines["kv"] = _lines["VOLTAGE"].astype("float64").where(_lines["VOLTAGE"] > 0)

    _merged = shapely.line_merge(_lines.geometry.values)
    _starts = shapely.get_point(shapely.get_geometry(_merged, 0), 0)
    _ends = shapely.get_point(shapely.get_geometry(_merged, -1), -1)
    _line_ends = pd.DataFrame(
        {
            "line": np.tile(_lines.index.to_numpy(), 2),
            "x": shapely.get_x(np.concatenate([_starts, _ends])),
            "y": shapely.get_y(np.concatenate([_starts, _ends])),
        }
    )
    assert _line_ends[["x", "y"]].notna().all().all(), "A line has no end point"
    _close = cKDTree(_line_ends[["x", "y"]].to_numpy()).query_pairs(r=100, output_type="ndarray")
    _graph = coo_matrix((np.ones(len(_close)), (_close[:, 0], _close[:, 1])), shape=(len(_line_ends), len(_line_ends)))
    _, _line_ends["node"] = connected_components(_graph, directed=False)
    _line_ends = _line_ends.join(_lines[["SUB_1", "SUB_2", "kv"]], on="line")

    # A node's name is the one end name shared by every line that touches it; failing that, the name its
    # line's far end doesn't use. We need the names only to drop taps.
    _candidates = _line_ends.assign(
        names=[{a, b} for a, b in zip(_line_ends["SUB_1"], _line_ends["SUB_2"], strict=True)]
    )
    _shared = _candidates.groupby("node")["names"].agg(lambda sets: set.intersection(*sets))
    _node_name = _shared[_shared.map(len) == 1].map(lambda s: next(iter(s)))
    _far = _line_ends.merge(_line_ends[["line", "node"]], on="line", suffixes=("", "_far"))
    _far = _far[_far["node"] != _far["node_far"]]
    _far["far_name"] = _far["node_far"].map(_node_name)
    _far = _far[_far["far_name"].notna() & ~_far["node"].isin(_node_name.index)]
    _far["name"] = _far["SUB_2"].where(_far["far_name"] == _far["SUB_1"], _far["SUB_1"])
    _node_name = pd.concat([_node_name, _far.groupby("node")["name"].agg(lambda s: s.mode().iloc[0])])

    nodes = _line_ends.groupby("node").agg(x=("x", "first"), y=("y", "first"), kv=("kv", "max"))
    nodes["is_tap"] = _node_name.reindex(nodes.index).fillna("").str.startswith("TAP")
    nodes = gpd.GeoDataFrame(nodes, geometry=gpd.points_from_xy(nodes["x"], nodes["y"]), crs=5070)
    print(f"{len(_lines):,} lines kept; {len(nodes):,} end nodes, {int(nodes['is_tap'].sum()):,} of them taps")
    return (nodes,)


@app.cell
def _(counties, gpd, nodes):
    derived = gpd.sjoin(
        nodes[~nodes["is_tap"]][["kv", "geometry"]], counties[["fips", "geometry"]], predicate="within"
    ).drop(columns="index_right")
    assert len(derived) == 45_779, "The derivation no longer reproduces the 45,779 substations of the earlier spikes"
    hv = derived[derived["kv"] >= 230].copy()
    hv["band"] = hv["kv"].map(lambda kv: "345+" if kv >= 345 else "230-344")
    print(
        f"Derived substations: {len(derived):,}; 230 kV+: {len(hv):,}; 345 kV+: {int((hv['band'] == '345+').sum()):,}"
    )
    return (hv,)


@app.cell
def _(mo):
    mo.md(r"""
    ### How much does the derived set miss? (measured on this run)

    We read OpenStreetMap's substations from Overture Maps (release 2026-09-23.0, the same as
    `us-substations-verified/`) and take each one's highest `voltage` tag value. Two numbers: the share of derived
    230 kV+ substations with an OSM substation within 1 km, and the share of OSM's 230 kV+ substations with no
    derived substation of any voltage within 1 km, as the earlier spike measured them.
    OSM is used only for these two rates; the county table counts derived substations only.
    """)
    return


@app.cell
def _(DATA_DIR, Path, duckdb):
    overture_path = DATA_DIR / "overture-substations-us-2026-09-23.0.parquet"
    if not overture_path.exists():
        _con = duckdb.connect()
        _con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
        # An empty key makes DuckDB read the public bucket anonymously instead of using any AWS credentials around.
        _con.sql("CREATE SECRET overture (TYPE s3, KEY_ID '', SECRET '', REGION 'us-west-2')")
        _con.sql(f"""
            COPY (
                SELECT id, source_tags['voltage'] AS voltage, ST_AsWKB(geometry) AS wkb
                FROM read_parquet(
                    's3://overturemaps-us-west-2/release/2026-09-23.0/theme=base/type=infrastructure/*')
                WHERE subtype = 'power' AND class = 'substation'
                  -- One box over all 50 states lets DuckDB skip the rest of the world (about 5 minutes).
                  AND bbox.xmin > -180 AND bbox.xmax < -66.0 AND bbox.ymin > 18.5 AND bbox.ymax < 72
            ) TO '{overture_path}.part' (FORMAT parquet)
        """)
        # Rename only once the query finishes, so an interrupted run doesn't leave a file later runs would trust.
        Path(f"{overture_path}.part").rename(overture_path)
    return (overture_path,)


@app.cell
def _(counties, gpd, hv, nodes, np, overture_path, pd):
    _raw = pd.read_parquet(overture_path)
    _volts = (
        _raw["voltage"].fillna("").str.findall(r"\d+(?:\.\d+)?").map(lambda vs: max(map(float, vs), default=np.nan))
    )
    # A handful of mappers write kilovolts ("115"); anything under 1,000 is read as kV, the rest as volts.
    _raw["kv"] = np.where(_volts < 1000, _volts, _volts / 1000)
    _osm = gpd.GeoDataFrame(_raw[["kv"]], geometry=gpd.GeoSeries.from_wkb(_raw["wkb"]), crs=4326).to_crs(5070)
    _osm = gpd.sjoin(_osm, counties[["geometry"]], predicate="intersects")
    _osm = _osm[~_osm.index.duplicated()].drop(columns="index_right")
    _osm_hv = _osm[_osm["kv"] >= 230]
    _derived_all = nodes[~nodes["is_tap"]][["geometry"]]

    _d = gpd.sjoin_nearest(hv[["geometry"]], _osm[["geometry"]], distance_col="m")
    _d = _d[~_d.index.duplicated()]
    _o = gpd.sjoin_nearest(_osm_hv[["geometry"]], _derived_all, distance_col="m")
    _o = _o[~_o.index.duplicated()]
    osm_gap = pd.DataFrame(
        {
            "measure": [
                "derived 230 kV+ substations with an OSM substation within 1 km",
                "OSM 230 kV+ substations with no derived substation within 1 km",
            ],
            "count": [int((_d["m"] <= 1000).sum()), int((_o["m"] > 1000).sum())],
            "of": [len(hv), len(_osm_hv)],
        }
    )
    osm_gap["percent"] = (100 * osm_gap["count"] / osm_gap["of"]).round(1)
    osm_gap
    return (osm_gap,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Geomagnetic hazard per substation

    USGS (Lucas et al. 2020, *Space Weather*) estimated the once-per-century geoelectric field at 1,079
    magnetotelluric survey sites, covering about two-thirds of the lower 48. As in `hifld-grid-gaps/`, each
    substation takes the value of its nearest survey site within 100 km and is **unrated** if none is that close
    (all of Alaska and Hawaii, and much of the Southeast, Texas and the southern Plains). **High** means 3 V/km or
    more, where the paper finds induced line voltages in the hundreds of volts.
    """)
    return


@app.cell
def _(download, gpd, hv, pd):
    _sites_csv = download(
        "https://raw.githubusercontent.com/greglucas/GeoelectricHazardPaper2019/"
        "856374c4aa0a96f149915712d5b7cc3e017d1507/code/geoelectric_100year.csv",
        "geoelectric_100year.csv",
    )
    _sites = pd.read_csv(_sites_csv)
    assert len(_sites) == 1_079, f"Expected 1,079 survey sites, got {len(_sites)}"
    _sites = gpd.GeoDataFrame(
        _sites[["E 100-year"]], geometry=gpd.points_from_xy(_sites["longitude"], _sites["latitude"]), crs=4326
    ).to_crs(5070)
    _near = gpd.sjoin_nearest(hv[["geometry"]], _sites, max_distance=100_000, how="left")
    _near = _near[~_near.index.duplicated()]
    rated = hv.assign(e100=_near["E 100-year"])
    rated["geomag"] = "unrated"
    rated.loc[rated["e100"] < 3, "geomag"] = "low"
    rated.loc[rated["e100"] >= 3, "geomag"] = "high"
    rated.groupby(["band", "geomag"]).size().unstack()
    return (rated,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. County hazard ratings: the Future Risk Index, and NRI for inland flood

    FEMA's Future Risk Index (taken down in February 2025) projected each county's National Risk Index risk to
    mid and late century. Its master datasheet, saved in `fulton-ring/nri-future-risk`, has a projected risk rating
    (`PRISKR`: Very Low to Very High) per hazard and scenario. We use **mid-century, higher warming**
    (`MID_HIGHER`, about 2050, RCP 8.5 or SSP5-8.5), roughly the remaining life of a transformer installed today,
    for coastal flooding, wildfire, extreme heat (the LOCA2 95th-percentile version) and hurricane. **High** means
    "Relatively High" or "Very High".

    The FRI has no inland (river and rain) flooding, so "flood" from the FRI alone would mean coastal flood. We add
    today's NRI v1.20 county **inland flooding** risk rating (`IFLD_RISKR`) from FEMA's ArcGIS service, with the same
    definition of high, and a county counts as a high-flood county if either rating is high.

    These are county ratings: every substation in a county shares them, so a county's count in a high-rated county
    is all of its substations or none.
    """)
    return


@app.cell
def _(download, pd, requests):
    _xlsx = download(
        "https://raw.githubusercontent.com/fulton-ring/nri-future-risk/"
        "c5cc0d6686832f809446fc6061a689eff71d09df/public/NRI_Future_Risk_Master_Datasheet_12052024.xlsx",
        "NRI_Future_Risk_Master_Datasheet_12052024.xlsx",
    )
    fri_columns = {
        "coastal_flood": "CFLD_MID_HIGHER_PRISKR",
        "wildfire": "WFIR_MID_HIGHER_PRISKR",
        "heat": "EXHT_L95_MID_HIGHER_PRISKR",
        "hurricane": "HRCN_MID_HIGHER_PRISKR",
    }
    _fri = pd.read_excel(_xlsx, usecols=["STCOFIPS", *fri_columns.values()])
    _fri["fips"] = _fri["STCOFIPS"].astype(int).map("{:05d}".format)
    _fri = _fri.set_index("fips")[list(fri_columns.values())]
    _fri.columns = list(fri_columns)
    assert _fri.index.is_unique and len(_fri) == 3_231, f"FRI datasheet has {len(_fri)} rows, expected 3,231"

    _url = (
        "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
        "National_Risk_Index_Counties/FeatureServer/0/query"
    )
    _rows = []
    for _page in range(10):
        _response = requests.get(
            _url,
            params={
                "where": "1=1",
                "outFields": "STCOFIPS,IFLD_RISKR,NRI_VER",
                "returnGeometry": "false",
                "orderByFields": "OBJECTID",
                "resultOffset": len(_rows),
                "resultRecordCount": 1000,
                "f": "json",
            },
            timeout=120,
        )
        assert _response.ok, f"NRI counties: HTTP {_response.status_code}"
        _payload = _response.json()
        assert "features" in _payload, f"NRI counties: {_payload}"
        _rows += [f["attributes"] for f in _payload["features"]]
        if not _payload.get("exceededTransferLimit"):
            break
    else:
        raise RuntimeError("NRI county table still paging after 10 pages")
    _nri = pd.DataFrame(_rows)
    nri_version = ", ".join(sorted(_nri["NRI_VER"].dropna().unique()))
    assert _nri["STCOFIPS"].is_unique and len(_nri) > 3_200, "NRI county table looks wrong"
    ratings = _fri.join(_nri.set_index("STCOFIPS")["IFLD_RISKR"].rename("inland_flood"), how="outer")
    print(f"FRI rows: {len(_fri):,}; NRI rows: {len(_nri):,} (version {nri_version})")
    ratings.apply(lambda c: c.value_counts()).fillna(0).astype(int)
    return nri_version, ratings


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. One row per county, before suppression

    For each county: 230 kV+ and 345 kV+ counts; for each band, how many are in high, low and unrated geomagnetic
    areas; each hazard rating; and how many 230 kV+ and 345 kV+ substations sit in counties rated high for it.
    This full table stays in memory and is never written.
    """)
    return


@app.cell
def _(counties, pd, rated, ratings):
    _cells = rated.groupby(["fips", "band", "geomag"]).size().unstack(["band", "geomag"], fill_value=0)
    _cells.columns = [f"n_{b}_{g}" for b, g in _cells.columns]
    full = counties[["fips", "county", "state"]].set_index("fips")
    full = full.join(_cells)
    for _b in ["230-344", "345+"]:
        for _g in ["high", "low", "unrated"]:
            _c = f"n_{_b}_{_g}"
            full[_c] = full[_c].fillna(0).astype(int) if _c in full else 0
    full["subs_230kv"] = full.filter(like="n_").sum(axis=1)
    full["subs_345kv"] = full.filter(like="n_345+").sum(axis=1)
    for _g in ["high", "low", "unrated"]:
        full[f"geomag_{_g}_230kv"] = full[f"n_230-344_{_g}"] + full[f"n_345+_{_g}"]
        full[f"geomag_{_g}_345kv"] = full[f"n_345+_{_g}"]

    _r = ratings.reindex(full.index)
    full["fri_rating_missing"] = _r["wildfire"].isna()
    _high = {"Relatively High", "Very High"}
    for _h in ["coastal_flood", "wildfire", "heat", "hurricane", "inland_flood"]:
        full[f"{_h}_rating"] = _r[_h].fillna("no rating row")
        full[f"{_h}_high"] = _r[_h].isin(_high)
    full["flood_high"] = full["coastal_flood_high"] | full["inland_flood_high"]
    for _h in ["coastal_flood", "inland_flood", "flood", "wildfire", "heat", "hurricane"]:
        full[f"{_h}_high_230kv"] = full["subs_230kv"].where(full[f"{_h}_high"], 0)
        full[f"{_h}_high_345kv"] = full["subs_345kv"].where(full[f"{_h}_high"], 0)
    assert full["subs_230kv"].sum() == len(rated)
    _no_row = full[full["fri_rating_missing"]]
    print(
        f"{len(full):,} counties; {int((full['subs_230kv'] > 0).sum()):,} hold a 230 kV+ substation, "
        f"{int((full['subs_345kv'] > 0).sum()):,} a 345 kV+ one. Counties with no FRI row (boundary changes): "
        f"{len(_no_row)} ({', '.join(_no_row['state'].value_counts().index)}), holding "
        f"{int(_no_row['subs_230kv'].sum())} 230 kV+ substations"
    )
    return (full,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. The suppression rule

    A county row must not let anyone pin down a single high-voltage substation. The threat is a small count: "this
    county has one 345 kV substation, and it's in a high geomagnetic area" narrows a search to one site. So:

    > **Every group of substations a reader can count from a published row, directly or by subtracting one
    > published number from another, must have 0 or at least 3 members.**

    Applied in this order:

    1. **Counties with 1 or 2 substations of 230 kV+**: publish only `few_substations = true` ("1 or 2"). Every
       count in the row is blank. Counties with 0 or 3+ publish their 230 kV+ count.
    2. **The 345 kV+ count** is published only if it, and the 230–344 kV remainder, are each 0 or 3+.
    3. **The geomagnetic split** (high, low, unrated) of 230 kV+ is published only if all three are 0 or 3+.
    4. **The geomagnetic split of 345 kV+** is published only if the 345 kV+ count is, its three classes are each
       0 or 3+, and, when step 3 is published too, the three 230–344 kV classes (230 kV+ minus 345 kV+) are each 0 or
       3+.
    5. **Hazard-rating counts** (substations in a county rated high) equal the band count or 0, so they follow the
       band count: blank when it is.

    A blank always blanks a whole split, never one cell of it, because one blank cell can be recovered by
    subtracting the others from the total.
    """)
    return


@app.cell
def _(full, pd):
    def clean(values: pd.Series | pd.DataFrame) -> pd.Series:
        """True where every value is 0 or at least 3 (row-wise for a frame)."""
        frame = values.to_frame() if isinstance(values, pd.Series) else values
        return ((frame == 0) | (frame >= 3)).all(axis=1)

    _classes = ["high", "low", "unrated"]
    _few = full["subs_230kv"].between(1, 2)
    _show_345 = ~_few & clean(full["subs_345kv"]) & clean(full["subs_230kv"] - full["subs_345kv"])
    _show_geo230 = ~_few & clean(full[[f"geomag_{g}_230kv" for g in _classes]])
    _lower = pd.DataFrame({g: full[f"n_230-344_{g}"] for g in _classes})
    _show_geo345 = _show_345 & clean(full[[f"geomag_{g}_345kv" for g in _classes]]) & (~_show_geo230 | clean(_lower))

    published = full[["county", "state"]].copy()
    published["few_substations"] = _few
    published["subs_230kv"] = full["subs_230kv"].where(~_few).astype("Int64")
    published["subs_345kv"] = full["subs_345kv"].where(_show_345).astype("Int64")
    for _g in _classes:
        published[f"geomag_{_g}_230kv"] = full[f"geomag_{_g}_230kv"].where(_show_geo230).astype("Int64")
    for _g in _classes:
        published[f"geomag_{_g}_345kv"] = full[f"geomag_{_g}_345kv"].where(_show_geo345).astype("Int64")
    published["geomag_high_share_230kv"] = (published["geomag_high_230kv"] / published["subs_230kv"]).round(3)
    published["geomag_high_share_345kv"] = (published["geomag_high_345kv"] / published["subs_345kv"]).round(3)
    for _h in ["coastal_flood", "wildfire", "heat", "hurricane", "inland_flood"]:
        published[f"{_h}_rating"] = full[f"{_h}_rating"]
    for _h in ["coastal_flood", "inland_flood", "flood", "wildfire", "heat", "hurricane"]:
        published[f"{_h}_high_230kv"] = full[f"{_h}_high_230kv"].where(~_few).astype("Int64")
        published[f"{_h}_high_345kv"] = full[f"{_h}_high_345kv"].where(_show_345).astype("Int64")

    suppression_report = pd.DataFrame(
        {
            "change": [
                "1 or 2 substations of 230 kV+: whole row blanked, flagged few_substations",
                "345 kV+ count blanked (it or the 230-344 kV remainder is 1 or 2)",
                "230 kV+ geomagnetic split blanked",
                "345 kV+ geomagnetic split blanked (in counties with 3+ substations of 230 kV+)",
                "any change (county rows the rule changed)",
            ],
            "counties": [
                int(_few.sum()),
                int((~_few & ~_show_345).sum()),
                int((~_few & ~_show_geo230).sum()),
                int((~_few & ~_show_geo345).sum()),
                int((_few | ~_show_345 | ~_show_geo230 | ~_show_geo345).sum()),
            ],
        }
    )
    suppression_report.loc[len(suppression_report)] = [
        "counties with 3+ substations of 230 kV+ (for scale)",
        int((full["subs_230kv"] >= 3).sum()),
    ]
    suppression_report
    return published, suppression_report


@app.cell
def _(mo):
    mo.md(r"""
    ### Testing the rule

    The test doesn't trust the rule's logic. For each published row it takes the six innermost groups (two voltage
    bands, 230–344 kV and 345 kV+, by three geomagnetic classes), writes every published count as a sum over them,
    and then checks all 63 possible groupings of those six: if a grouping's total can be worked out from the
    published counts by adding and subtracting (its indicator vector lies in the span of the published ones), its
    true total must be 0 or at least 3. Then it checks the national totals in the README can't be used to recover a
    blanked county: in every count column, at least two counties are blank, or none are.
    """)
    return


@app.cell
def _(full, itertools, np, pd, published):
    _cells = [f"n_{b}_{g}" for b in ["230-344", "345+"] for g in ["high", "low", "unrated"]]
    _subsets = [s for k in range(1, 7) for s in itertools.combinations(range(6), k)]
    _published_sums = {
        "subs_230kv": [0, 1, 2, 3, 4, 5],
        "subs_345kv": [3, 4, 5],
        "geomag_high_230kv": [0, 3],
        "geomag_low_230kv": [1, 4],
        "geomag_unrated_230kv": [2, 5],
        "geomag_high_345kv": [3],
        "geomag_low_345kv": [4],
        "geomag_unrated_345kv": [5],
    }
    _failures = []
    _true = full[_cells].to_numpy()
    _shown = published[list(_published_sums)].notna().to_numpy()
    for _i in range(len(full)):
        _known = [
            np.isin(np.arange(6), idx).astype(float)
            for idx, shown in zip(_published_sums.values(), _shown[_i], strict=True)
            if shown
        ]
        if not _known:
            continue
        _basis = np.vstack(_known)
        _rank = np.linalg.matrix_rank(_basis)
        for _s in _subsets:
            _v = np.isin(np.arange(6), _s).astype(float)
            if np.linalg.matrix_rank(np.vstack([_basis, _v])) == _rank:
                _total = int(_true[_i, list(_s)].sum())
                if 1 <= _total <= 2:
                    _failures.append((full.index[_i], [_cells[j] for j in _s], _total))
    assert not _failures, f"{len(_failures)} derivable groups of 1 or 2, first: {_failures[:3]}"

    _count_cols = [c for c in published.columns if published[c].dtype == "Int64"]
    _blanks = published[_count_cols].isna().sum()
    assert ((_blanks == 0) | (_blanks >= 2)).all(), f"A column with exactly one blank: {_blanks[_blanks == 1]}"
    suppression_test = pd.DataFrame(
        {
            "check": [
                "county rows tested",
                "groupings checked per row",
                "derivable groups of 1 or 2 substations",
                "count columns with exactly one blank county",
            ],
            "result": [len(full), len(_subsets), len(_failures), int((_blanks == 1).sum())],
        }
    )
    suppression_test
    return (suppression_test,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Results

    National totals come from the full table (they're sums over thousands of substations, so they reveal no site).
    Every county-level list comes from the published, suppressed table.
    """)
    return


@app.cell
def _(full, pd, rated):
    _rows = []
    for _band, _col in [("230 kV+", "subs_230kv"), ("345 kV+", "subs_345kv")]:
        _set = rated if _band == "230 kV+" else rated[rated["band"] == "345+"]
        _n = len(_set)
        _rated_n = int((_set["geomag"] != "unrated").sum())
        _rows += [
            (_band, "substations", _n, None),
            (_band, "counties holding one", int((full[_col] > 0).sum()), None),
            (_band, "geomagnetic: rated (survey site within 100 km)", _rated_n, _rated_n / _n),
            (_band, "geomagnetic: high (3 V/km or more)", int((_set["geomag"] == "high").sum()), None),
            (
                _band,
                "geomagnetic: high, share of rated",
                int((_set["geomag"] == "high").sum()),
                (_set["geomag"] == "high").sum() / _rated_n,
            ),
        ]
        for _h, _label in [
            ("flood", "flood (FRI coastal or NRI inland high)"),
            ("coastal_flood", "FRI coastal flood high"),
            ("inland_flood", "NRI inland flood high"),
            ("wildfire", "FRI wildfire high"),
            ("heat", "FRI extreme heat high"),
            ("hurricane", "FRI hurricane high"),
        ]:
            _k = int(full[f"{_h}_high_{_col[5:]}"].sum())
            _rows.append((_band, f"in a county rated {_label}", _k, _k / _n))
    national = pd.DataFrame(_rows, columns=["band", "measure", "substations", "share"])
    national["share"] = national["share"].astype(float).round(3)
    national
    return (national,)


@app.cell
def _(mo):
    mo.md(r"""
    **Which US counties have the most high-voltage substations in flood or wildfire zones?** Counties ranked by
    230 kV+ substations, among counties rated high for flood (FRI coastal or NRI inland) or for FRI wildfire.
    Because the ratings are county-wide, the share in a high-rated county is 100% for every county on these lists.
    """)
    return


@app.cell
def _(pd, published):
    def top(column: str, among: pd.Series, n: int = 10) -> pd.DataFrame:
        """The n counties with the most substations in `column`, among the counties where `among` is true."""
        rows = published[among & published[column].notna() & published[column].gt(0)]
        return rows.sort_values(column, ascending=False).head(n).reset_index()[["fips", "county", "state", column]]

    _high = ["Relatively High", "Very High"]
    _flood = published["coastal_flood_rating"].isin(_high) | published["inland_flood_rating"].isin(_high)
    top_flood = top("subs_230kv", _flood)
    top_wildfire = top("subs_230kv", published["wildfire_rating"].isin(_high))
    top_flood.assign(list="flood").pipe(lambda t: pd.concat([t, top_wildfire.assign(list="wildfire")]))
    return top, top_flood, top_wildfire


@app.cell
def _(mo):
    mo.md(r"""
    **How exposed is the US grid to geomagnetic storms by county?** Counties with the most 230 kV+ substations
    where the once-per-century field is 3 V/km or more, and, among counties with at least 10 of them, the highest
    share.
    """)
    return


@app.cell
def _(pd, published, top):
    top_geomag = top("geomag_high_230kv", published["subs_230kv"].notna())
    _big = published[published["subs_230kv"].ge(10) & published["geomag_high_230kv"].notna()]
    top_geomag_share = (
        _big.sort_values(["geomag_high_share_230kv", "geomag_high_230kv"], ascending=False)
        .head(10)
        .reset_index()[["fips", "county", "state", "subs_230kv", "geomag_high_230kv", "geomag_high_share_230kv"]]
    )
    pd.concat([top_geomag.assign(list="count"), top_geomag_share.assign(list="share")])
    return top_geomag, top_geomag_share


@app.cell
def _(OUTPUT_DIR, counties, plt, published):
    _map = counties.set_index("fips").join(published[["subs_230kv", "geomag_high_230kv", "few_substations"]])
    _map = _map[~_map["state"].isin(["AK", "HI"])]
    _fig, _axes = plt.subplots(1, 2, figsize=(16, 5.5))
    for _ax, _col, _title in [
        (_axes[0], "subs_230kv", "230 kV+ substations per county"),
        (_axes[1], "geomag_high_230kv", "...of which where the 100-year geoelectric field is 3 V/km+"),
    ]:
        _map.plot(ax=_ax, color="#eeeeee", edgecolor="none")
        _map[_map[_col].isna()].plot(ax=_ax, color="#bdbdbd", edgecolor="none")
        _shown = _map[_map[_col].notna() & (_map[_col] > 0)]
        _shown.plot(ax=_ax, column=_shown[_col].astype(float), cmap="viridis_r", legend=True, edgecolor="none")
        _ax.set_title(_title)
        _ax.set_axis_off()
    _fig.suptitle("Published county table, lower 48 (dark grey: suppressed; light grey: 0). No site-level data.")
    _fig.tight_layout()
    _fig.savefig(OUTPUT_DIR / "county_map.png", dpi=110, bbox_inches="tight")
    _fig
    return


@app.cell
def _(
    OUTPUT_DIR,
    national,
    nri_version,
    osm_gap,
    published,
    started,
    suppression_report,
    suppression_test,
    time,
    top_flood,
    top_geomag,
    top_geomag_share,
    top_wildfire,
):
    _table = published.reset_index()
    _table.to_csv(OUTPUT_DIR / "county_grid_exposure.csv", index=False)
    _table.to_parquet(OUTPUT_DIR / "county_grid_exposure.parquet", index=False)
    national.to_csv(OUTPUT_DIR / "national_summary.csv", index=False)
    osm_gap.to_csv(OUTPUT_DIR / "coverage_gaps.csv", index=False)
    suppression_report.to_csv(OUTPUT_DIR / "suppression_report.csv", index=False)
    suppression_test.to_csv(OUTPUT_DIR / "suppression_test.csv", index=False)
    top_flood.to_csv(OUTPUT_DIR / "top_counties_flood.csv", index=False)
    top_wildfire.to_csv(OUTPUT_DIR / "top_counties_wildfire.csv", index=False)
    top_geomag.to_csv(OUTPUT_DIR / "top_counties_geomagnetic.csv", index=False)
    top_geomag_share.to_csv(OUTPUT_DIR / "top_counties_geomagnetic_share.csv", index=False)
    for _name, _frame in [
        ("Coverage gaps", osm_gap),
        ("National summary", national),
        ("Suppression", suppression_report),
        ("Suppression test", suppression_test),
        ("Top flood", top_flood),
        ("Top wildfire", top_wildfire),
        ("Top geomagnetic, count", top_geomag),
        ("Top geomagnetic, share", top_geomag_share),
    ]:
        print(f"\n{_name}\n{_frame.to_string(index=False)}")
    print(f"\nNRI version: {nri_version}. Run time: {time.perf_counter() - started:.0f} s (notebook only)")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What didn't work, and what this doesn't show

    - **County ratings are county-wide.** The FRI and NRI rate whole counties, so "in a high-flood county" is not
      "in a floodplain": a substation on a ridge in a high-flood county counts. A site-level flood answer needs
      FEMA flood zones at each substation, which would mean working with points we don't publish.
    - **The geomagnetic rating is by nearest survey site**, not a gridded field, and leaves unsurveyed areas
      unrated (Alaska, Hawaii, much of the Southeast and Texas). Unrated is not low.
    - **The substations are derived**, not an asset list: they miss the share of OSM's 230 kV+ substations shown in
      section 2, and a few derived points are taps or plant switchyards (`us-substations-verified/hand_check.csv`).
      Voltages are floors: 14% of derived substations have no voltage on any line that ends there.
    - **Suppression protects against counting, not against other sources.** It stops this table from pinning down
      a site. It can't stop someone joining it to a public point layer, including the one in this repo's
      `us-substations-verified/dataset/`.
    """)
    return


if __name__ == "__main__":
    app.run()

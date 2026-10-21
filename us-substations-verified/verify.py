import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    import re
    from pathlib import Path

    import duckdb
    import geopandas as gpd
    import marimo as mo
    import numpy as np
    import pandas as pd
    import requests
    import shapely
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    from scipy.stats import fisher_exact
    from statsmodels.stats.contingency_tables import StratifiedTable

    return (
        Path,
        StratifiedTable,
        cKDTree,
        connected_components,
        coo_matrix,
        duckdb,
        fisher_exact,
        gpd,
        json,
        mo,
        np,
        os,
        pd,
        re,
        requests,
        shapely,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Are the substations we derived from HIFLD Next real?

    HIFLD Next has no substations layer. The county spike (`county-bans-substations/`) derived 45,779
    substations from the ends of HIFLD Next transmission lines and found that counties restricting wind or
    solar are more likely to hold a 230 kV+ substation (59.3% against 50.4%, within-state odds ratio 1.55).
    Two drafts were paused until those substations were checked.

    This notebook checks them against the one other public US substation map, OpenStreetMap (read from
    Overture Maps), and asks:

    1. How many derived 230 kV+ substations have an OSM substation within 250 m or 1 km?
    2. How many OSM substations tagged 230 kV+ does the derived set miss?
    3. What are the derived points that OSM doesn't confirm? (50 checked by eye on aerial imagery.)
    4. Does the county headline hold on substations both sources agree on, and on OSM alone?

    It then writes the combined dataset and the interactive map. Inputs, all public and downloaded on the
    first run into `data/`: HIFLD Next Transmission Lines v1.0.0, Overture `2026-09-23.0` substations, the
    Sabin Center's restriction data and Census 2024 county boundaries.
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
    ## 1. Counties and restrictions

    The same inputs and the same "restricted" definition as the county spike: a county-level wind or solar
    ordinance in effect in the Sabin Center's data (state laws and town or township ordinances set aside).
    """)
    return


@app.cell
def _(DATA_DIR, download, gpd, pd, re, requests):
    report_page = requests.get("https://oppositionreport.org/reports/current/", timeout=120)
    assert report_page.ok, f"Sabin report page: HTTP {report_page.status_code}"
    export_links = re.findall(
        r"https://oppositionreport\.org/wp-load\.php\?security_key=[0-9a-f]+&(?:amp;|#038;)?export_id=7&(?:amp;|#038;)?action=get_data",
        report_page.text,
    )
    assert export_links, "No restriction-data export link on the Sabin report page"
    edition_match = re.search(r"United States:\s*([A-Z][a-z]+ \d{4}) Edition", report_page.text)
    assert edition_match, "No edition name on the Sabin report page"
    sabin_edition = edition_match.group(1)
    export_url = export_links[0].replace("&#038;", "&").replace("&amp;", "&")
    sabin_path = download(export_url, f"sabin-restrictions-{sabin_edition.replace(' ', '-').lower()}.csv")
    sabin = pd.read_csv(sabin_path, encoding="utf-8-sig", dtype=str).fillna("")
    # The export has two columns headed "County": the name, then the FIPS code.
    assert {"County", "County.1"} <= set(sabin.columns), f"Unexpected Sabin columns: {list(sabin.columns)}"
    local = sabin[
        (sabin["Level"] == "Local")
        & (sabin["Status"] == "In effect")
        & sabin["Type"].str.contains("Wind|Solar")
        & (sabin["Municipality"].str.strip() == "")
    ]
    restricted_fips = set(local["County.1"].str.split("|").explode())
    assert all(re.fullmatch(r"\d{5}", f) for f in restricted_fips), "A restriction without a 5-digit county FIPS"

    county_zip = download(
        "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip",
        "cb_2024_us_county_500k.zip",
    )
    counties = gpd.read_file(county_zip)
    counties = counties[counties["STATEFP"].astype(int) <= 56].to_crs(5070)
    counties = (
        counties[["GEOID", "NAME", "STUSPS", "geometry"]].rename(columns={"GEOID": "fips"}).reset_index(drop=True)
    )
    counties["restricted"] = counties["fips"].isin(restricted_fips)
    print(
        f"Sabin Center {sabin_edition}: {len(local)} county-level wind/solar restrictions in effect, "
        f"{int(counties['restricted'].sum())} of {len(counties):,} counties restricted"
    )
    return counties, sabin_edition


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Derived substations (HIFLD Next line ends)

    Rebuilt exactly as in the county spike: merge line ends within 100 m into nodes, name each node from the
    `SUB_1`/`SUB_2` names its lines share, drop the `TAP…` nodes, and give each node the highest voltage of
    the lines ending there. We keep the taps aside, because they matter when we ask what OSM substations the
    derived set misses.
    """)
    return


@app.cell
def _(cKDTree, connected_components, coo_matrix, download, gpd, np, pd, shapely):
    lines_path = download(
        "https://storage.googleapis.com/hifld-next-datasets-prod/hifld/transmission-lines-1/transmission-lines-1/v1.0.0/geoparquet/transmission-lines-1.parquet",
        "hifld-next-transmission-lines-v1.0.0.parquet",
    )
    lines_all = gpd.read_parquet(lines_path)
    lines = lines_all[~lines_all["STATUS"].isin(["INACTIVE", "UNDER CONSTRUCTION"])].to_crs(5070).reset_index(drop=True)
    lines["kv"] = lines["VOLTAGE"].astype("float64").where(lines["VOLTAGE"] > 0)

    merged = shapely.line_merge(lines.geometry.values)
    starts = shapely.get_point(shapely.get_geometry(merged, 0), 0)
    ends = shapely.get_point(shapely.get_geometry(merged, -1), -1)
    line_ends = pd.DataFrame(
        {
            "line": np.tile(lines.index.to_numpy(), 2),
            "x": shapely.get_x(np.concatenate([starts, ends])),
            "y": shapely.get_y(np.concatenate([starts, ends])),
        }
    )
    assert line_ends[["x", "y"]].notna().all().all(), "A line has no end point"
    close = cKDTree(line_ends[["x", "y"]].to_numpy()).query_pairs(r=100, output_type="ndarray")
    graph = coo_matrix((np.ones(len(close)), (close[:, 0], close[:, 1])), shape=(len(line_ends), len(line_ends)))
    _, line_ends["node"] = connected_components(graph, directed=False)
    line_ends = line_ends.join(lines[["SUB_1", "SUB_2", "kv"]], on="line")

    # A node's name is the one end name shared by every line that touches it; failing that, the name its
    # line's far end doesn't use.
    candidates = line_ends.assign(names=[{a, b} for a, b in zip(line_ends["SUB_1"], line_ends["SUB_2"], strict=True)])
    shared = candidates.groupby("node")["names"].agg(lambda sets: set.intersection(*sets))
    node_name = shared[shared.map(len) == 1].map(lambda s: next(iter(s)))
    far = line_ends.merge(line_ends[["line", "node"]], on="line", suffixes=("", "_far"))
    far = far[far["node"] != far["node_far"]]
    far["far_name"] = far["node_far"].map(node_name)
    far = far[far["far_name"].notna() & ~far["node"].isin(node_name.index)]
    far["name"] = far["SUB_2"].where(far["far_name"] == far["SUB_1"], far["SUB_1"])
    node_name = pd.concat([node_name, far.groupby("node")["name"].agg(lambda s: s.mode().iloc[0])])

    nodes = line_ends.groupby("node").agg(
        x=("x", "first"), y=("y", "first"), kv=("kv", "max"), lines=("line", "nunique")
    )
    nodes["name"] = node_name
    nodes["is_tap"] = nodes["name"].fillna("").str.startswith("TAP")
    nodes = gpd.GeoDataFrame(nodes, geometry=gpd.points_from_xy(nodes["x"], nodes["y"]), crs=5070)
    print(f"{len(lines):,} lines kept; {len(nodes):,} end nodes, {int(nodes['is_tap'].sum()):,} of them taps")
    return (nodes,)


@app.cell
def _(counties, gpd, nodes):
    derived = gpd.sjoin(
        nodes[~nodes["is_tap"]].drop(columns=["x", "y", "is_tap"]),
        counties[["fips", "STUSPS", "geometry"]],
        predicate="within",
    ).drop(columns="index_right")
    derived["id"] = "hifld-node-" + derived.index.astype(str)
    print(
        f"Derived substations in the 50 states and DC: {len(derived):,}; "
        f"230 kV+: {int((derived['kv'] >= 230).sum()):,}; no voltage: {int(derived['kv'].isna().sum()):,}"
    )
    assert len(derived) == 45_779, "The derivation no longer reproduces the county spike's 45,779 substations"
    return (derived,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. OpenStreetMap substations (Overture)

    Overture's `base/infrastructure` theme carries OSM's `power=substation` features with their original OSM
    tags in `source_tags`. We read the `voltage` tag: OSM records it in volts, with several values separated
    by `;` when a substation has more than one level (`345000;138000`). A substation's voltage is the highest
    value. A tag with no number (`medium`, blank) gives no voltage. Substations mapped as areas are measured
    to their outline, so a line end anywhere inside the fence is distance 0.
    """)
    return


@app.cell
def _(DATA_DIR, duckdb):
    overture_release = "2026-09-23.0"
    overture_path = DATA_DIR / f"overture-substations-us-{overture_release}.parquet"
    if not overture_path.exists():
        _con = duckdb.connect()
        _con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
        # An empty key makes DuckDB read the public bucket anonymously instead of using any AWS credentials around.
        _con.sql("CREATE SECRET overture (TYPE s3, KEY_ID '', SECRET '', REGION 'us-west-2')")
        _con.sql(f"""
            COPY (
                SELECT id, names.primary AS name, source_tags['voltage'] AS voltage,
                       source_tags['substation'] AS substation_tag, source_tags['operator'] AS operator,
                       sources[1].record_id AS osm_record, ST_AsWKB(geometry) AS wkb
                FROM read_parquet(
                    's3://overturemaps-us-west-2/release/{overture_release}/theme=base/type=infrastructure/*')
                WHERE subtype = 'power' AND class = 'substation' AND (
                    (bbox.xmin > -125.5 AND bbox.xmax < -66.0 AND bbox.ymin > 24.0 AND bbox.ymax < 49.5)
                    OR (bbox.xmin > -180 AND bbox.xmax < -129 AND bbox.ymin > 51 AND bbox.ymax < 72)
                    OR (bbox.xmin > -161 AND bbox.xmax < -154 AND bbox.ymin > 18.5 AND bbox.ymax < 22.5))
            ) TO '{overture_path}' (FORMAT parquet)
        """)
    return overture_path, overture_release


@app.cell
def _(counties, gpd, np, overture_path, pd):
    _raw = pd.read_parquet(overture_path)
    _volts = (
        _raw["voltage"].fillna("").str.findall(r"\d+(?:\.\d+)?").map(lambda vs: max(map(float, vs), default=np.nan))
    )
    # A handful of mappers write kilovolts ("115"); anything under 1,000 is read as kV, the rest as volts.
    _raw["kv"] = np.where(_volts < 1000, _volts, _volts / 1000)
    _osm = gpd.GeoDataFrame(_raw.drop(columns="wkb"), geometry=gpd.GeoSeries.from_wkb(_raw["wkb"]), crs=4326).to_crs(
        5070
    )
    # The query boxes also catch substations in Canada and Mexico; keep those inside a county.
    osm = gpd.sjoin(_osm, counties[["fips", "STUSPS", "geometry"]], predicate="intersects")
    osm = osm[~osm.index.duplicated()].drop(columns="index_right").reset_index(drop=True)
    print(
        f"OSM substations in the 50 states and DC: {len(osm):,}; with a voltage tag: {int(osm['kv'].notna().sum()):,}; "
        f"230 kV+: {int((osm['kv'] >= 230).sum()):,}; mapped as areas: {int((osm.geom_type != 'Point').sum()):,}"
    )
    print("substation= tag:", osm["substation_tag"].fillna("(none)").value_counts().head(8).to_dict())
    return (osm,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Match the two

    For every derived substation, the distance to the nearest OSM substation. For every OSM substation, the
    distance to the nearest derived substation and, separately, the nearest line-end node of any kind (taps
    included), because a line that ends at an OSM substation HIFLD calls a tap still reaches it.
    """)
    return


@app.cell
def _(derived, gpd, nodes, osm, pd):
    def nearest_m(points: gpd.GeoDataFrame, targets: gpd.GeoDataFrame, id_col: str) -> pd.DataFrame:
        """Distance in metres from each row of points to the nearest of targets, and that target's id."""
        joined = gpd.sjoin_nearest(points[["geometry"]], targets[[id_col, "geometry"]], distance_col="m")
        joined = joined[~joined.index.duplicated()]
        return joined[[id_col, "m"]]

    _d = nearest_m(derived, osm, "id").rename(columns={"id": "osm_id", "m": "m_to_osm"})
    derived_m = derived.join(_d)
    _nodes = nodes.assign(node_id=nodes.index)
    _o = nearest_m(osm, derived, "id").rename(columns={"id": "derived_id", "m": "m_to_derived"})
    _a = nearest_m(osm, _nodes, "node_id").rename(columns={"m": "m_to_any_node"})
    osm_m = osm.join(_o).join(_a[["m_to_any_node"]])

    _rows = []
    for _label, _set in [
        ("all derived", derived_m),
        ("derived 230 kV+", derived_m[derived_m["kv"] >= 230]),
        ("derived 345 kV+", derived_m[derived_m["kv"] >= 345]),
        (
            "derived, named (no UNKNOWN / NOT AVAILABLE)",
            derived_m[~derived_m["name"].fillna("UNKNOWN").str.match("UNKNOWN|NOT AVAILABLE")],
        ),
    ]:
        _rows.append(
            {
                "set": _label,
                "substations": len(_set),
                "OSM within 250 m %": round(100 * (_set["m_to_osm"] <= 250).mean(), 1),
                "OSM within 1 km %": round(100 * (_set["m_to_osm"] <= 1000).mean(), 1),
                "OSM farther than 1 km": int((_set["m_to_osm"] > 1000).sum()),
            }
        )
    derived_match = pd.DataFrame(_rows)
    print(derived_match.to_string(index=False))
    return derived_m, derived_match, osm_m


@app.cell
def _(OUTPUT_DIR, derived_match, osm_m, pd):
    _rows = []
    for _label, _set in [
        ("OSM 230 kV+", osm_m[osm_m["kv"] >= 230]),
        ("OSM 345 kV+", osm_m[osm_m["kv"] >= 345]),
        ("OSM 115 to 229 kV", osm_m[(osm_m["kv"] >= 115) & (osm_m["kv"] < 230)]),
        ("OSM, all", osm_m),
    ]:
        _rows.append(
            {
                "set": _label,
                "substations": len(_set),
                "no derived substation within 250 m %": round(100 * (_set["m_to_derived"] > 250).mean(), 1),
                "no derived substation within 1 km %": round(100 * (_set["m_to_derived"] > 1000).mean(), 1),
                "no line end of any kind within 1 km %": round(100 * (_set["m_to_any_node"] > 1000).mean(), 1),
            }
        )
    osm_missed = pd.DataFrame(_rows)
    print(osm_missed.to_string(index=False))
    pd.concat([derived_match.assign(direction="derived → OSM"), osm_missed.assign(direction="OSM → derived")]).to_csv(
        OUTPUT_DIR / "match_rates.csv", index=False
    )
    return (osm_missed,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. What are the derived 230 kV+ points OSM doesn't confirm?

    A random sample of 50 (seed 76) from the derived 230 kV+ substations with no OSM substation within 1 km.
    Each was looked at on Esri World Imagery at two zooms (`./run.sh --chips` redraws the images) and labelled
    **substation** (a fenced switchyard with equipment), **tap** (the line branches or continues, no yard),
    **plant** (a generating plant's switchyard), **error** (nothing there) or **unclear**. The labels are in
    `hand_check.csv`; this cell only counts them.
    """)
    return


@app.cell
def _(OUTPUT_DIR, Path, derived_m, gpd, pd):
    _far = derived_m[(derived_m["kv"] >= 230) & (derived_m["m_to_osm"] > 1000)]
    _sample = _far.sample(n=50, random_state=76)
    _ll = gpd.GeoSeries(_sample.geometry, crs=5070).to_crs(4326)
    hand_sample = pd.DataFrame(
        {
            "id": _sample["id"],
            "name": _sample["name"],
            "kv": _sample["kv"],
            "lines": _sample["lines"],
            "m_to_osm": _sample["m_to_osm"].round(0),
            "lon": _ll.x.round(6),
            "lat": _ll.y.round(6),
        }
    )
    hand_sample.to_csv(OUTPUT_DIR / "hand_check_sample.csv", index=False)
    _labels_path = Path("hand_check.csv")
    if _labels_path.exists():
        _labels = pd.read_csv(_labels_path)
        assert set(_labels["id"]) == set(hand_sample["id"]), "hand_check.csv is for a different sample"
        hand_tally = _labels["label"].value_counts()
        print(f"Unconfirmed derived 230 kV+ substations: {len(_far):,}. Sample of 50 labelled on imagery:")
        print(hand_tally.to_string())
    else:
        hand_tally = pd.Series(dtype=int)
        print("hand_check.csv not found: draw the chips with ./run.sh --chips and label the sample")
    return (hand_tally,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Does the county headline hold?

    The county spike's headline is "holds a 230 kV+ substation": 59.3% of restricted counties against 50.4%
    of unrestricted ones, within-state (Cochran–Mantel–Haenszel) odds ratio 1.55. We re-run that test on four
    substation sets:

    - **derived** (the original, as a check that we reproduce it);
    - **(a) derived, confirmed by OSM**: derived 230 kV+ substations with an OSM substation within 1 km;
    - **(b) OSM 230 kV+**: OSM substations whose voltage tag is 230 kV or more;
    - **either**: a county holds one in the derived set or in OSM.
    """)
    return


@app.cell
def _(StratifiedTable, counties, derived_m, fisher_exact, np, osm_m, pd):
    def headline(holds_fips: set[str], label: str) -> dict[str, object]:
        """Restricted vs unrestricted counties holding a substation in holds_fips: shares, Fisher and CMH."""
        df = counties.assign(holds=counties["fips"].isin(holds_fips))
        r, u = df[df["restricted"]], df[~df["restricted"]]
        odds, p = fisher_exact([[r["holds"].sum(), (~r["holds"]).sum()], [u["holds"].sum(), (~u["holds"]).sum()]])
        informative = df.groupby("STUSPS")["restricted"].transform(lambda s: 0 < s.sum() < len(s))
        tables = [
            np.array(
                [
                    [s.loc[s["restricted"], "holds"].sum(), (~s.loc[s["restricted"], "holds"]).sum()],
                    [s.loc[~s["restricted"], "holds"].sum(), (~s.loc[~s["restricted"], "holds"]).sum()],
                ]
            )
            for _, s in df[informative].groupby("STUSPS")
        ]
        strat = StratifiedTable(tables)
        low, high = strat.oddsratio_pooled_confint()
        return {
            "substations": label,
            "restricted holding %": round(100 * r["holds"].mean(), 1),
            "unrestricted holding %": round(100 * u["holds"].mean(), 1),
            "odds ratio": round(float(odds), 2),
            "Fisher p": float(f"{p:.2g}"),
            "within-state OR": round(float(strat.oddsratio_pooled), 2),
            "95% CI": f"{low:.2f}–{high:.2f}",
            "CMH p": float(f"{strat.test_null_odds().pvalue:.2g}"),
        }

    _d230 = derived_m[derived_m["kv"] >= 230]
    _o230 = osm_m[osm_m["kv"] >= 230]
    headline_table = pd.DataFrame(
        [
            headline(set(_d230["fips"]), "derived 230 kV+ (original)"),
            headline(set(_d230.loc[_d230["m_to_osm"] <= 1000, "fips"]), "(a) derived 230 kV+, OSM within 1 km"),
            headline(set(_o230["fips"]), "(b) OSM 230 kV+"),
            headline(set(_d230["fips"]) | set(_o230["fips"]), "either derived or OSM 230 kV+"),
        ]
    )
    return (headline_table,)


@app.cell
def _(OUTPUT_DIR, headline_table):
    headline_table.to_csv(OUTPUT_DIR / "headline_rerun.csv", index=False)
    print(headline_table.to_string(index=False))
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. The dataset

    One row per substation: every derived substation, and every OSM substation with no derived substation
    within 1 km. A derived substation with an OSM substation within 1 km is **both**; its name falls back to
    the OSM name when HIFLD's is a placeholder, and its voltage is the higher of the two. `outputs/` gets
    GeoParquet and CSV; `DATA_DICTIONARY.md` explains each column and the licences.
    """)
    return


@app.cell
def _(OUTPUT_DIR, counties, derived_m, gpd, np, osm_m, pd):
    _placeholder = derived_m["name"].fillna("UNKNOWN").str.match("UNKNOWN|NOT AVAILABLE")
    _osm_by_id = osm_m.set_index("id")
    _matched = derived_m["m_to_osm"] <= 1000
    _osm_name = derived_m["osm_id"].map(_osm_by_id["name"])
    _osm_kv = derived_m["osm_id"].map(_osm_by_id["kv"])
    _from_derived = pd.DataFrame(
        {
            "id": derived_m["id"],
            "name": derived_m["name"].where(~_placeholder | ~_matched | _osm_name.isna(), _osm_name),
            "max_kv": np.fmax(derived_m["kv"], _osm_kv.where(_matched)),
            "hifld_kv": derived_m["kv"],
            "osm_kv": _osm_kv.where(_matched),
            "source": np.where(_matched, "both", "derived"),
            "osm_id": derived_m["osm_id"].where(_matched),
            "match_m": derived_m["m_to_osm"].round(0),
            "fips": derived_m["fips"],
            "geometry": derived_m.geometry,
        }
    )
    _osm_only = osm_m[osm_m["m_to_derived"] > 1000]
    _from_osm = pd.DataFrame(
        {
            "id": "osm-" + _osm_only["id"],
            "name": _osm_only["name"],
            "max_kv": _osm_only["kv"],
            "hifld_kv": np.nan,
            "osm_kv": _osm_only["kv"],
            "source": "osm",
            "osm_id": _osm_only["id"],
            "match_m": _osm_only["m_to_derived"].round(0),
            "fips": _osm_only["fips"],
            "geometry": _osm_only.geometry.representative_point(),
        }
    )
    substations = gpd.GeoDataFrame(pd.concat([_from_derived, _from_osm], ignore_index=True), crs=5070).to_crs(4326)
    substations = substations.merge(counties[["fips", "STUSPS", "restricted"]], on="fips", how="left").rename(
        columns={"STUSPS": "state", "restricted": "county_restricted"}
    )
    assert substations["id"].is_unique and substations["fips"].notna().all()
    substations.to_parquet(OUTPUT_DIR / "us_substations.parquet")
    substations.assign(lon=substations.geometry.x.round(6), lat=substations.geometry.y.round(6)).drop(
        columns="geometry"
    ).to_csv(OUTPUT_DIR / "us_substations.csv", index=False)
    print(substations["source"].value_counts().to_string())
    print(f"{len(substations):,} rows; 230 kV+ by max_kv: {int((substations['max_kv'] >= 230).sum()):,}")
    return (substations,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. The map

    A static MapLibre page, `map/index.html`, reads two GeoJSON files written here: counties shaded by
    restriction and substations coloured by voltage. Clicking a substation shows its name, voltage and source.
    Coordinates are rounded to about 1 m and county outlines simplified to 200 m to keep the files small.
    """)
    return


@app.cell
def _(Path, counties, json, os, sabin_edition, substations):
    _map_dir = Path(os.environ.get("MAP_DIR", "map"))
    _map_dir.mkdir(exist_ok=True)
    _c = counties[["fips", "NAME", "STUSPS", "restricted", "geometry"]].copy()
    _c["geometry"] = _c.geometry.simplify(200)
    _c = _c.to_crs(4326).rename(columns={"NAME": "name", "STUSPS": "state"})
    _c["restricted"] = _c["restricted"].astype(int)
    (_map_dir / "counties.geojson").write_text(_c.to_json(drop_id=True, coord_precision=4))
    _s = substations[["name", "max_kv", "source", "geometry"]].copy()
    _s["max_kv"] = _s["max_kv"].round(0)
    (_map_dir / "substations.geojson").write_text(_s.to_json(drop_id=True, coord_precision=5, na="drop"))
    (_map_dir / "meta.json").write_text(json.dumps({"sabin_edition": sabin_edition}))
    print({p.name: f"{p.stat().st_size / 1e6:.1f} MB" for p in sorted(_map_dir.glob("*.geojson"))})
    return


@app.cell
def _(derived_m, derived_match, hand_tally, headline_table, mo, osm_m, osm_missed):
    _d = derived_match.set_index("set").loc["derived 230 kV+"]
    _o = osm_missed.set_index("set").loc["OSM 230 kV+"]
    _h = headline_table.set_index("substations")
    _rows = "\n".join(
        f"| {k} | {r['restricted holding %']}% | {r['unrestricted holding %']}% "
        f"| {r['within-state OR']} ({r['95% CI']}) |"
        for k, r in _h.iterrows()
    )
    mo.md(f"""
    ## Result

    - Of **{_d["substations"]:,} derived 230 kV+ substations**, {_d["OSM within 250 m %"]}% have an OSM
      substation within 250 m and {_d["OSM within 1 km %"]}% within 1 km.
    - Of **{_o["substations"]:,} OSM substations tagged 230 kV+**, {_o["no derived substation within 1 km %"]}%
      have no derived substation within 1 km ({_o["no line end of any kind within 1 km %"]}% have no HIFLD line
      end of any kind within 1 km).
    - Hand check of 50 unconfirmed derived 230 kV+ points: {", ".join(f"{v} {k}" for k, v in hand_tally.items())}.
    - Derived {len(derived_m):,}, OSM {len(osm_m):,}.

    | Substations | Restricted holding | Unrestricted holding | Within-state odds ratio (95% CI) |
    |---|---|---|---|
    {_rows}
    """)
    return


if __name__ == "__main__":
    app.run()

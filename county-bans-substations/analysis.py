import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import os
    import re
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import requests
    import shapely
    import statsmodels.formula.api as smf
    from matplotlib.patches import Patch
    from scipy.sparse import coo_matrix
    from scipy.sparse.csgraph import connected_components
    from scipy.spatial import cKDTree
    from scipy.stats import fisher_exact
    from statsmodels.stats.contingency_tables import StratifiedTable

    return (
        Patch,
        Path,
        StratifiedTable,
        cKDTree,
        connected_components,
        coo_matrix,
        fisher_exact,
        gpd,
        mo,
        np,
        os,
        pd,
        plt,
        re,
        requests,
        shapely,
        smf,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Do counties that restrict renewables sit next to high-voltage substations?

    Canary Media and The Daily Yonder reported in September 2026 that nearly one in four US counties had
    a renewable energy ban, moratorium or other impediment in 2025. If restricted counties are more likely
    than other counties to hold or border a high-voltage substation, local restrictions often fall where
    bulk grid connection points already exist.

    This notebook measures **exposure only**. It can't show that substations, spare capacity or tax
    revenue cause anything.

    Three public inputs, all downloaded when it runs:

    1. **Restrictions:** the Sabin Center's *Opposition to Renewable Energy Facilities in the United
       States* restriction data (CSV export from oppositionreport.org), coded to county FIPS.
    2. **Substations:** HIFLD Next has no Electric Substations layer, so we derive substations from the
       HIFLD Next **Transmission Lines** layer: every line ends at a named substation or tap, and a
       substation's voltage is the highest voltage of the lines that end there. HIFLD's original
       substations layer was built the same way, from line endpoints.
    3. **Counties:** Census 2024 cartographic boundary file (1:500k), for county shapes and neighbors.
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
    ## 1. Restrictions (Sabin Center)

    The report page links a CSV export of every state and local restriction. The link carries a
    key that can change, so we read it off the page each run, along with the edition name.
    """)
    return


@app.cell
def _(DATA_DIR, download, pd, re, requests):
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
    sabin = sabin.rename(columns={"County": "county_name", "County.1": "county_fips"})
    print(
        f"Sabin Center, {sabin_edition} edition: {len(sabin)} restrictions in {sabin_path.relative_to(DATA_DIR.parent)}"
    )
    print(sabin.groupby(["Level", "Status"]).size().to_string())
    return sabin, sabin_edition


@app.cell
def _(mo):
    mo.md(r"""
    **Which entries make a county "restricted".** We keep local restrictions that are in effect and
    cover wind or solar (storage-only and transmission-only entries are dropped). The 23 state laws
    are dropped too: they apply statewide, so they would mark whole states rather than counties.

    Sabin also codes town, township and city ordinances, each with the FIPS code of its county. A
    township rule restricts only part of a county, so the **main definition counts only
    county-level ordinances** (no municipality). Two other definitions test how much that matters:

    - **ban:** county-level ordinances that include a ban or moratorium (Sabin's Rule 1);
    - **broad:** any local ordinance in the county, including town and township ones.
    """)
    return


@app.cell
def _(pd, sabin):
    local = sabin[
        (sabin["Level"] == "Local") & (sabin["Status"] == "In effect") & sabin["Type"].str.contains("Wind|Solar")
    ].copy()
    local["fips"] = local["county_fips"].str.split("|")
    local = local.explode("fips")
    local["county_level"] = local["Municipality"].str.strip() == ""
    local["is_ban"] = local["Content"].str.contains(r"Ban\s*/\s*Moratorium")
    bad_fips = local[~local["fips"].str.fullmatch(r"\d{5}")]
    assert bad_fips.empty, f"Restrictions without a 5-digit county FIPS: {bad_fips['Title'].tolist()}"

    restricted_sets = {
        "main": set(local.loc[local["county_level"], "fips"]),
        "ban": set(local.loc[local["county_level"] & local["is_ban"], "fips"]),
        "broad": set(local["fips"]),
    }
    print(
        pd.Series(
            {
                "local wind/solar restrictions in effect": len(local),
                "  of which county-level": int(local["county_level"].sum()),
                "  of which town/township/city (main definition sets aside)": int((~local["county_level"]).sum()),
                "counties, main definition": len(restricted_sets["main"]),
                "counties, ban definition": len(restricted_sets["ban"]),
                "counties, broad definition": len(restricted_sets["broad"]),
            }
        ).to_string()
    )
    return local, restricted_sets


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Counties and their neighbors

    We use the 50 states and DC. Two counties are neighbors if their boundaries touch, corners included.

    Connecticut replaced its counties with nine planning regions in 2022, and Census files use the new
    codes. Sabin still codes Connecticut towns to the old counties, so those entries (all town-level)
    can't be joined; they drop out of the broad definition only.
    """)
    return


@app.cell
def _(download, gpd, local, pd):
    county_zip = download(
        "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip",
        "cb_2024_us_county_500k.zip",
    )
    counties = gpd.read_file(county_zip)
    counties = counties[counties["STATEFP"].astype(int) <= 56].to_crs(5070)
    counties = (
        counties[["GEOID", "NAME", "STUSPS", "ALAND", "geometry"]]
        .rename(columns={"GEOID": "fips"})
        .reset_index(drop=True)
    )
    assert counties["fips"].is_unique

    pairs = gpd.sjoin(
        counties[["fips", "geometry"]],
        counties[["fips", "geometry"]],
        predicate="intersects",
    )
    pairs = pairs[pairs["fips_left"] != pairs["fips_right"]][["fips_left", "fips_right"]]
    neighbor_count = pairs.groupby("fips_left").size()

    unmatched = local[~local["fips"].isin(counties["fips"])]
    print(f"{len(counties)} counties; median {neighbor_count.median():.0f} neighbors each")
    print(f"Restriction rows whose FIPS isn't a 2024 Census county: {len(unmatched)}")
    if not unmatched.empty:
        print(pd.DataFrame(unmatched[["State", "fips", "Title"]]).to_string(index=False))
    return counties, pairs


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Substations from HIFLD Next transmission lines

    Steps:

    1. Keep lines that are in service or have no status; drop the 91 inactive and 25 under construction.
    2. Take both ends of every line and merge ends within 100 m of each other into one **node**.
    3. Name each node. Each line names its two end substations (`SUB_1`, `SUB_2`) but not which end is
       which, so a node shared by several lines takes the one name they all share. A dead-end node then
       takes whichever name its line's far end doesn't use.
    4. Drop **taps** (nodes named `TAP…`): they're splice points on a line, not substations.
    5. Give each substation the highest voltage of the lines ending there. Missing voltages
       (`-999999`) don't count; a substation with only missing-voltage lines has no voltage value.
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
    graph = coo_matrix(
        (np.ones(len(close)), (close[:, 0], close[:, 1])),
        shape=(len(line_ends), len(line_ends)),
    )
    _, line_ends["node"] = connected_components(graph, directed=False)
    line_ends = line_ends.join(lines[["SUB_1", "SUB_2", "kv"]], on="line")
    print(f"{len(lines_all):,} lines; {len(lines):,} kept; {line_ends['node'].nunique():,} end nodes")
    return line_ends, lines


@app.cell
def _(line_ends, pd):
    # A node's name is the one end name shared by every line that touches it.
    candidates = line_ends.assign(names=[{a, b} for a, b in zip(line_ends["SUB_1"], line_ends["SUB_2"], strict=True)])
    shared = candidates.groupby("node")["names"].agg(lambda sets: set.intersection(*sets))
    node_name = shared[shared.map(len) == 1].map(lambda s: next(iter(s)))

    # A node still unnamed takes the name its line's far end doesn't use.
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
    print(
        pd.Series(
            {
                "end nodes": len(nodes),
                "named": int(nodes["name"].notna().sum()),
                "unnamed (kept as substations)": int(nodes["name"].isna().sum()),
                "taps (dropped)": int(nodes["is_tap"].sum()),
            }
        ).to_string()
    )
    return (nodes,)


@app.cell
def _(counties, gpd, nodes, pd):
    VOLTAGE_CUTOFFS = [115, 230, 345]
    subs = nodes[~nodes["is_tap"]].copy()
    subs = gpd.GeoDataFrame(subs, geometry=gpd.points_from_xy(subs["x"], subs["y"]), crs=5070)
    subs = gpd.sjoin(subs, counties[["fips", "geometry"]], predicate="within", how="left").drop(columns="index_right")
    outside = subs["fips"].isna()
    subs = subs[~outside]

    voltage_summary = pd.DataFrame(
        {
            "substations": [len(subs)]
            + [int((subs["kv"] >= cut).sum()) for cut in VOLTAGE_CUTOFFS]
            + [int(subs["kv"].isna().sum())],
        },
        index=["all, in a county"] + [f"{cut} kV and up" for cut in VOLTAGE_CUTOFFS] + ["no voltage value"],
    )
    voltage_summary["share"] = (voltage_summary["substations"] / len(subs)).round(3)
    print(f"Substations outside the 50 states and DC (Canada, Mexico, territories, offshore): {int(outside.sum()):,}")
    print(voltage_summary.to_string())
    return VOLTAGE_CUTOFFS, subs, voltage_summary


@app.cell
def _(mo, voltage_summary):
    _missing = voltage_summary.loc["no voltage value", "share"]
    mo.md(f"""
    **{_missing:.1%} of substations have no voltage value.** Those can't be placed above any cut-off,
    so every "holds a substation of X kV and up" share below is a floor: a county whose only
    substation lacks a voltage counts as not holding one.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Join: restricted counties against substations

    For every county we take the highest substation voltage inside it, and the highest inside it or
    any neighbor. A county **holds** an X kV substation if the first is at least X, and **holds or
    borders** one if the second is.
    """)
    return


@app.cell
def _(VOLTAGE_CUTOFFS, counties, pairs, restricted_sets, subs):
    county_kv = subs.groupby("fips")["kv"].max()
    table = counties.copy()
    table["kv_in"] = table["fips"].map(county_kv)
    neighbor_kv = pairs.assign(kv=pairs["fips_right"].map(county_kv)).groupby("fips_left")["kv"].max()
    table["kv_near"] = table[["kv_in"]].assign(neighbors=table["fips"].map(neighbor_kv)).max(axis=1)
    for _cut in VOLTAGE_CUTOFFS:
        table[f"holds_{_cut}"] = table["kv_in"] >= _cut
        table[f"near_{_cut}"] = table["kv_near"] >= _cut
    for _definition, _fips_set in restricted_sets.items():
        table[f"restricted_{_definition}"] = table["fips"].isin(_fips_set)
    return (table,)


@app.cell
def _(OUTPUT_DIR, VOLTAGE_CUTOFFS, fisher_exact, pd, table):
    def compare(df: pd.DataFrame, group: str) -> pd.DataFrame:
        """Restricted vs unrestricted counties: counts, shares and a Fisher exact test per measure."""
        rows = []
        for cut in VOLTAGE_CUTOFFS:
            for measure, label in [("holds", "holds"), ("near", "holds or borders")]:
                col = f"{measure}_{cut}"
                r, u = df[df[group]], df[~df[group]]
                odds, p = fisher_exact([[r[col].sum(), (~r[col]).sum()], [u[col].sum(), (~u[col]).sum()]])
                rows.append(
                    {
                        "measure": f"{label} {cut} kV+",
                        "restricted": f"{int(r[col].sum())} / {len(r)}",
                        "restricted %": round(100 * r[col].mean(), 1),
                        "unrestricted": f"{int(u[col].sum())} / {len(u)}",
                        "unrestricted %": round(100 * u[col].mean(), 1),
                        "odds ratio": round(float(odds), 2),
                        "Fisher p": float(f"{p:.2g}"),
                    }
                )
        return pd.DataFrame(rows)

    national = compare(table, "restricted_main")
    national.to_csv(OUTPUT_DIR / "national_comparison.csv", index=False)
    print("Main definition: county-level wind or solar restriction in effect")
    print(national.to_string(index=False))
    return compare, national


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Within-state comparison

    Restrictions cluster in a few states (Ohio, Michigan, Indiana, Iowa…), and so does the grid. A
    national gap could just be geography. The Cochran–Mantel–Haenszel test compares restricted and
    unrestricted counties **inside each state** and pools the result. States where every county, or
    no county, is restricted carry no information and drop out. "Holds or borders 115 kV+" is left out:
    almost every county in both groups meets it.
    """)
    return


@app.cell
def _(OUTPUT_DIR, StratifiedTable, VOLTAGE_CUTOFFS, np, pd, table):
    def within_state(df: pd.DataFrame, group: str) -> pd.DataFrame:
        """Mantel–Haenszel pooled odds ratio and test across states with both groups."""
        informative = df.groupby("STUSPS")[group].transform(lambda s: 0 < s.sum() < len(s))
        df = df[informative]
        rows = []
        for cut in VOLTAGE_CUTOFFS:
            for measure, label in [("holds", "holds"), ("near", "holds or borders")]:
                col = f"{measure}_{cut}"
                if col == "near_115":
                    continue  # nearly every county holds or borders 115 kV+, so there's nothing to compare
                tables = []
                for _, state in df.groupby("STUSPS"):
                    r, u = state[state[group]], state[~state[group]]
                    tables.append(
                        np.array(
                            [
                                [r[col].sum(), (~r[col]).sum()],
                                [u[col].sum(), (~u[col]).sum()],
                            ]
                        )
                    )
                strat = StratifiedTable(tables)
                rows.append(
                    {
                        "measure": f"{label} {cut} kV+",
                        "states": len(tables),
                        "counties": len(df),
                        "pooled odds ratio": round(float(strat.oddsratio_pooled), 2),
                        "95% CI": "{:.2f}–{:.2f}".format(*strat.oddsratio_pooled_confint()),
                        "CMH p": float(f"{strat.test_null_odds().pvalue:.2g}"),
                    }
                )
        return pd.DataFrame(rows)

    stratified = within_state(table, "restricted_main")
    stratified.to_csv(OUTPUT_DIR / "within_state_comparison.csv", index=False)
    print(stratified.to_string(index=False))
    return stratified, within_state


@app.cell
def _(OUTPUT_DIR, pd, table):
    by_state = (
        table.groupby("STUSPS")
        .apply(
            lambda s: pd.Series(
                {
                    "counties": len(s),
                    "restricted": int(s["restricted_main"].sum()),
                    "restricted holding 230 kV+ %": round(100 * s.loc[s["restricted_main"], "holds_230"].mean(), 1),
                    "unrestricted holding 230 kV+ %": round(100 * s.loc[~s["restricted_main"], "holds_230"].mean(), 1),
                }
            ),
            include_groups=False,
        )
        .sort_values("restricted", ascending=False)
    )
    by_state.to_csv(OUTPUT_DIR / "by_state_230kv.csv")
    print("The ten states with the most restricted counties (main definition), 230 kV and up")
    print(by_state.head(10).to_string())
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Do the other restriction definitions change the answer?

    The same national and within-state tests at 230 kV, for the narrower **ban** definition and the
    wider **broad** definition that adds town and township ordinances.
    """)
    return


@app.cell
def _(OUTPUT_DIR, compare, pd, table, within_state):
    sensitivity = []
    for _definition in ["main", "ban", "broad"]:
        _group = f"restricted_{_definition}"
        _nat = compare(table, _group).set_index("measure")
        _strat = within_state(table, _group).set_index("measure")
        for _measure in ["holds 230 kV+", "holds or borders 230 kV+"]:
            sensitivity.append(
                {
                    "definition": _definition,
                    "restricted counties": int(table[_group].sum()),
                    "measure": _measure,
                    "restricted %": _nat.loc[_measure, "restricted %"],
                    "unrestricted %": _nat.loc[_measure, "unrestricted %"],
                    "Fisher p": _nat.loc[_measure, "Fisher p"],
                    "within-state OR": _strat.loc[_measure, "pooled odds ratio"],
                    "CMH p": _strat.loc[_measure, "CMH p"],
                }
            )
    sensitivity = pd.DataFrame(sensitivity)
    sensitivity.to_csv(OUTPUT_DIR / "definition_sensitivity.csv", index=False)
    print(sensitivity.to_string(index=False))
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 6b. Is it just bigger counties?

    A larger county has more room for substations, and restricted counties are often rural ones.
    A logistic regression of "holds a substation of X kV and up" on restriction, log land area and a
    fixed effect per state asks whether the gap survives both. Same informative states as above.
    """)
    return


@app.cell
def _(OUTPUT_DIR, VOLTAGE_CUTOFFS, np, pd, smf, table):
    _informative = table.groupby("STUSPS")["restricted_main"].transform(lambda s: 0 < s.sum() < len(s))
    _df = table.loc[
        _informative,
        ["STUSPS", "ALAND", "restricted_main"] + [f"holds_{c}" for c in VOLTAGE_CUTOFFS],
    ]
    _df = _df.assign(log_area=np.log(_df["ALAND"]), restricted=_df["restricted_main"].astype(int))
    _df = _df.astype({f"holds_{c}": int for c in VOLTAGE_CUTOFFS})
    print(
        f"Median land area: restricted {table.loc[table['restricted_main'], 'ALAND'].median() / 1e6:,.0f} km², "
        f"unrestricted {table.loc[~table['restricted_main'], 'ALAND'].median() / 1e6:,.0f} km²"
    )
    area_adjusted = []
    for _cut in VOLTAGE_CUTOFFS:
        # States where every county, or none, holds one say nothing about the gap and stop the fit converging.
        _varies = _df.groupby("STUSPS")[f"holds_{_cut}"].transform(lambda s: 0 < s.sum() < len(s))
        _fit = smf.logit(f"holds_{_cut} ~ restricted + log_area + C(STUSPS)", data=_df[_varies]).fit(
            disp=False, maxiter=200
        )
        assert _fit.mle_retvals["converged"], f"Logit for {_cut} kV did not converge"
        _low, _high = np.exp(_fit.conf_int().loc["restricted"])
        area_adjusted.append(
            {
                "measure": f"holds {_cut} kV+",
                "states": _df.loc[_varies, "STUSPS"].nunique(),
                "odds ratio, state + area adjusted": round(float(np.exp(_fit.params["restricted"])), 2),
                "95% CI": f"{_low:.2f}–{_high:.2f}",
                "p": float(f"{_fit.pvalues['restricted']:.2g}"),
            }
        )
    area_adjusted = pd.DataFrame(area_adjusted)
    area_adjusted.to_csv(OUTPUT_DIR / "area_adjusted.csv", index=False)
    print(area_adjusted.to_string(index=False))
    return (area_adjusted,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Spot check: Bannock County, Idaho and the Populus substation

    Bannock County banned commercial wind and large solar in 2024. Populus, a 345 kV PacifiCorp
    substation, should sit inside it.
    """)
    return


@app.cell
def _(subs, table):
    bannock = table[table["fips"] == "16005"].iloc[0]
    populus = subs[subs["name"] == "POPULUS"]
    print(f"Bannock County restricted (main definition): {bannock['restricted_main']}")
    print(f"Highest substation voltage in Bannock County: {bannock['kv_in']:.0f} kV")
    print(populus[["name", "kv", "lines", "fips"]].to_string(index=False))
    assert bannock["restricted_main"], "Bannock County should be restricted"
    assert (populus["fips"] == "16005").any(), "Populus should be in Bannock County"
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. Map

    Lower 48 only, for legibility. Each county is coloured by whether it has a county-level
    restriction and whether it holds a 230 kV or higher substation.
    """)
    return


@app.cell
def _(OUTPUT_DIR, Patch, plt, sabin_edition, table):
    lower48 = table[~table["STUSPS"].isin(["AK", "HI"])].copy()
    lower48["category"] = lower48["restricted_main"].map({True: "restricted", False: "unrestricted"}) + lower48[
        "holds_230"
    ].map({True: ", holds 230 kV+", False: ", no 230 kV+"})
    colors = {
        "restricted, holds 230 kV+": "#b2182b",
        "restricted, no 230 kV+": "#f4a582",
        "unrestricted, holds 230 kV+": "#bcd6ea",
        "unrestricted, no 230 kV+": "#f0f0f0",
    }
    fig, ax = plt.subplots(figsize=(12, 7.5))
    lower48.plot(ax=ax, color=lower48["category"].map(colors), edgecolor="white", linewidth=0.1)
    ax.set_axis_off()
    ax.set_title(
        f"Counties with a renewable energy restriction (Sabin Center, {sabin_edition})"
        " and 230 kV+ substations (HIFLD Next)",
        fontsize=11,
    )
    counts = lower48["category"].value_counts()
    ax.legend(
        handles=[Patch(color=c, label=f"{k} ({counts.get(k, 0)})") for k, c in colors.items()],
        loc="lower left",
        frameon=False,
    )
    fig.savefig(OUTPUT_DIR / "map_restricted_230kv.png", dpi=150, bbox_inches="tight")
    fig
    return


@app.cell
def _(area_adjusted, mo, national, sabin_edition, stratified, subs, voltage_summary):
    _a = area_adjusted.set_index("measure").loc["holds 230 kV+"]
    _n = national.set_index("measure")
    _s = stratified.set_index("measure")
    _row = _n.loc["holds or borders 230 kV+"]
    _hold = _n.loc["holds 230 kV+"]
    mo.md(f"""
    ## Result

    We derived **{len(subs):,} substations** from HIFLD Next transmission lines,
    {voltage_summary.loc["230 kV and up", "substations"]:,} of them 230 kV and up, and matched them to
    **{_row["restricted"].split(" / ")[1]} counties** with a county-level wind or solar restriction in the
    Sabin Center's {sabin_edition} data.

    - **Holds a 230 kV+ substation:** {_hold["restricted %"]}% of restricted counties against
      {_hold["unrestricted %"]}% of unrestricted ones (Fisher p = {_hold["Fisher p"]}); within states, pooled
      odds ratio {_s.loc["holds 230 kV+", "pooled odds ratio"]} ({_s.loc["holds 230 kV+", "95% CI"]}); adjusted for
      state and land area, {_a["odds ratio, state + area adjusted"]} ({_a["95% CI"]}).
    - **Holds or borders one:** {_row["restricted %"]}% against {_row["unrestricted %"]}%
      (Fisher p = {_row["Fisher p"]}); within states, pooled odds ratio
      {_s.loc["holds or borders 230 kV+", "pooled odds ratio"]} ({_s.loc["holds or borders 230 kV+", "95% CI"]}).

    The tables above give every cut-off. An odds ratio above 1 means restricted counties are more
    likely to hold or border a substation than unrestricted counties in the same state.

    ## What this doesn't show

    - **Spare capacity.** A substation nearby isn't room on the grid; interconnection queues decide that,
      and they aren't in this join.
    - **Cause.** Nothing here says substations or tax revenue drive bans or their reversal.
    - **County energy tax revenue.** Not joined; we found no national county-level table.
    - **Substation completeness.** Substations come from line endpoints, so a substation with no HIFLD
      line ending at it is missed, and those with no voltage on their lines are left out of every cut-off.
    - **Partial-county rules.** The main definition sets aside town and township ordinances; the
      broad definition shows what including them does.
    """)
    return


if __name__ == "__main__":
    app.run()

import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import io
    import os
    import re
    import time
    from datetime import date, timedelta
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import requests
    from scipy.stats import fisher_exact
    from statsmodels.stats.contingency_tables import StratifiedTable

    return (
        Path,
        StratifiedTable,
        date,
        fisher_exact,
        gpd,
        io,
        mo,
        np,
        os,
        pd,
        plt,
        re,
        requests,
        time,
        timedelta,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Do the places that have paused data centers hold a high-voltage substation?

    Hundreds of US cities, towns, townships and counties have put a moratorium on new data centers. If
    pauses follow proposals and proposals follow the grid, paused places should be more likely than
    comparable places to hold a 230 kV or larger substation, and a real share of the high-voltage
    connection points siting teams screen for would now sit inside a paused jurisdiction.

    This measures **exposure only**. Restrictions follow developer activity (Ko, Dolšak & Prakash 2023;
    Lerner 2021), and a nearby substation isn't spare capacity.

    Inputs, all public and downloaded when it runs (except the substations, already on `main`):

    1. **Pauses:** Moratorium Data 2026 local inventory (Michael J. Bommarito, CC BY 4.0), pinned release.
    2. **Check:** the Calyx Intelligence register of pauses in effect. No open license, so it's read at
       run time, used only for counts, and none of its rows are written out.
    3. **Substations:** the 6,469 HIFLD-derived 230 kV+ substations in `../us-substations-verified/`.
    4. **Boundaries and size:** Census 2024 cartographic boundaries (counties, places, county
       subdivisions) and Vintage 2024 population estimates.
    """)
    return


@app.cell
def _(Path, date, os, requests, time):
    DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
    OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "outputs"))
    SUBSTATIONS_DIR = Path(os.environ.get("SUBSTATIONS_DIR", "../us-substations-verified/dataset"))
    BOMMARITO_RELEASE = os.environ.get("BOMMARITO_RELEASE", "v2026.11.11.post13")
    # Pauses are judged "in effect" and "ending soon" against this date, so a rerun gives the same numbers.
    AS_OF = date.fromisoformat(os.environ.get("AS_OF", "2026-11-21"))
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
            time.sleep(5 * (attempt + 1))
        raise RuntimeError(f"Could not download {url}")

    return AS_OF, BOMMARITO_RELEASE, DATA_DIR, OUTPUT_DIR, SUBSTATIONS_DIR, download


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Pauses in effect (Bommarito)

    We keep records with `enacted_status` active or extended and `data_center` among their sectors, as the
    issue asks. Bommarito doesn't confirm each record is in force, so we also drop records whose recorded
    end date has already passed. Where no end date is recorded but a length in days is, we compute it.
    """)
    return


@app.cell
def _(AS_OF, BOMMARITO_RELEASE, download, pd):
    inventory_path = download(
        f"https://raw.githubusercontent.com/mjbommar/moratorium-data-2026/{BOMMARITO_RELEASE}/data/moratorium_inventory.csv",
        f"moratorium_inventory_{BOMMARITO_RELEASE}.csv",
    )
    inventory = pd.read_csv(inventory_path, dtype={"moratorium_id": str})
    assert {"enacted_status", "sectors", "latitude", "longitude", "jurisdiction_type"} <= set(inventory.columns)
    data_center = inventory["sectors"].fillna("").str.contains('"data_center"')
    active = inventory["enacted_status"].isin(["active", "extended"])
    pauses = inventory[data_center & active].copy()

    computed_end = pd.to_datetime(pauses["date_enacted_iso"], errors="coerce") + pd.to_timedelta(
        pauses["duration_days"], unit="D"
    )
    pauses["end_date"] = pd.to_datetime(pauses["current_end_date_iso"], errors="coerce").fillna(computed_end)
    lapsed = pauses["end_date"].notna() & (pauses["end_date"] < pd.Timestamp(AS_OF))
    print(f"Bommarito {BOMMARITO_RELEASE}: {len(inventory)} local records, {data_center.sum()} for data centers")
    print(f"  active or extended, data center: {len(pauses)} in {pauses['state_abbrev'].nunique()} states")
    print(f"  latest enactment date in the selection: {pauses['date_enacted_iso'].max()}")
    print(f"  recorded end date already passed by {AS_OF}: {lapsed.sum()} (dropped)")
    pauses = pauses[~lapsed].reset_index(drop=True)
    print(f"  pauses in effect: {len(pauses)}; with a known end date: {pauses['end_date'].notna().sum()}")
    print(pauses["jurisdiction_type"].value_counts().to_string())
    return (pauses,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Census boundaries and population

    Bommarito's coordinates are a jurisdiction reference point, not a boundary, so we need Census shapes.
    Cities and villages are Census **places**; townships, and towns in New England, New York and the Midwest,
    are **county subdivisions**; counties are counties. Population comes from the Census Vintage 2024
    estimates, which also give us the universe of real governments to compare against: incorporated
    places only (no Census-designated places, which can't pass an ordinance), and functioning towns and
    townships.
    """)
    return


@app.cell
def _(download, gpd, pd):
    census_base = "https://www2.census.gov/geo/tiger/GENZ2024/shp"
    layer_files = {
        "county": "cb_2024_us_county_500k",
        "place": "cb_2024_us_place_500k",
        "cousub": "cb_2024_us_cousub_500k",
    }
    population_path = download(
        "https://www2.census.gov/programs-surveys/popest/datasets/2020-2024/cities/totals/sub-est2024.csv",
        "sub-est2024.csv",
    )
    population = pd.read_csv(population_path, dtype=str, encoding="latin-1")
    population["pop"] = population["POPESTIMATE2024"].astype(int)
    population_keys = {
        "county": population[population["SUMLEV"] == "050"].assign(GEOID=lambda d: d["STATE"] + d["COUNTY"]),
        "place": population[population["SUMLEV"] == "162"].assign(GEOID=lambda d: d["STATE"] + d["PLACE"]),
        "cousub": population[
            (population["SUMLEV"] == "061")
            & (population["FUNCSTAT"] == "A")
            & population["NAME"].str.contains(r"\b(?:town|township)$", regex=True)
        ].assign(GEOID=lambda d: d["STATE"] + d["COUNTY"] + d["COUSUB"]),
    }

    units = {}
    for _level, file in layer_files.items():
        _shapes = gpd.read_file(download(f"{census_base}/{file}.zip", f"{file}.zip"))
        _shapes = _shapes[_shapes["STATEFP"].astype(int) <= 56].to_crs(5070)
        keep = population_keys[_level][["GEOID", "pop"]].drop_duplicates("GEOID")
        _shapes = _shapes.merge(keep, on="GEOID", how="inner")
        units[_level] = _shapes[["GEOID", "NAME", "STUSPS", "STATE_NAME", "ALAND", "pop", "geometry"]].assign(
            level=_level
        )
        print(f"{_level}: {len(units[_level])} governments with a boundary and a population")
    return (units,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Join each pause to its Census unit

    For each record we look, in order, at the levels its type allows (a city: place, then county
    subdivision, then county, for independent cities). A join is **clean** when the reference point falls
    inside a unit whose name matches. If not, we accept a unit of the same name in the same state whose
    edge is within 25 km of the point (**name match nearby**). Anything else stays unjoined and is listed.
    Names are compared after dropping words like "City of", "Charter Township", "County" and
    "Fiscal Court", and spaces. Pennsylvania boroughs and Kentucky's merged governments come typed "Other"
    and are tried at every level; tribal nations and a utility authority have no Census unit here.
    """)
    return


@app.cell
def _(re):
    def normalize_name(name: str) -> str:
        """Lowercase a place name and drop the government-type words, so 'City of Foley' == 'Foley'."""
        text = re.sub(r"\(.*?\)| - .*$", " ", str(name).lower())
        text = re.sub(r"\bst\.?\s", "saint ", text)
        text = re.sub(r"[^a-z ]", " ", text)
        text = re.sub(
            r"\b(?:city|town|village|borough|charter|township|county|parish|of|the|unified|government|"
            r"consolidated|metro|metropolitan|municipality|plantation|and|fiscal|court|unincorporated)\b",
            " ",
            text,
        )
        # Spaces dropped too, so "La Salle" == "LaSalle" and "LeRay" == "Le Ray".
        return "".join(text.split())

    return (normalize_name,)


@app.cell
def _(gpd, normalize_name, pauses, pd, units):
    levels_by_type = {
        "County": ["county"],
        "City": ["place", "cousub", "county"],
        "Town": ["place", "cousub"],
        "Village": ["place", "cousub"],
        "Township": ["cousub"],
        "Other": ["place", "cousub", "county"],
    }
    _points = gpd.GeoDataFrame(
        pauses, geometry=gpd.points_from_xy(pauses["longitude"], pauses["latitude"]), crs=4326
    ).to_crs(5070)
    _points["key"] = _points["jurisdiction"].map(normalize_name)
    joined = pd.DataFrame({"level": pd.Series(dtype=str), "GEOID": pd.Series(dtype=str)}, index=_points.index)
    joined["method"] = "unjoined"

    # Clean joins: the point is inside a _unit with the same name.
    for _level, _unit in units.items():
        _hits = gpd.sjoin(_points[["key", "jurisdiction_type", "geometry"]], _unit, predicate="within")
        _hits = _hits[_hits["key"] == _hits["NAME"].map(normalize_name)]
        _hits = _hits[_hits["jurisdiction_type"].map(lambda t, lv=_level: lv in levels_by_type.get(t, []))]
        for idx, _row in _hits.iterrows():
            current = joined.at[idx, "level"]
            allowed = levels_by_type[_row["jurisdiction_type"]]
            if joined.at[idx, "method"] == "unjoined" or allowed.index(_level) < allowed.index(current):
                joined.loc[idx, ["level", "GEOID", "method"]] = [_level, _row["GEOID"], "clean"]

    # Fallback: a same-name _unit in the same state within 25 km of the point.
    for idx in joined.index[joined["method"] == "unjoined"]:
        point = _points.loc[idx]
        for _level in levels_by_type.get(point["jurisdiction_type"], []):
            _unit = units[_level]
            same = _unit[
                (_unit["STUSPS"] == point["state_abbrev"]) & (_unit["NAME"].map(normalize_name) == point["key"])
            ]
            if same.empty:
                continue
            distance = same.distance(point.geometry)
            if distance.min() <= 25_000:
                joined.loc[idx, ["level", "GEOID", "method"]] = [_level, same.loc[distance.idxmin(), "GEOID"], "nearby"]
                break

    pauses_joined = pauses.join(joined)
    print(pd.crosstab(pauses_joined["jurisdiction_type"], pauses_joined["method"], margins=True).to_string())
    print(pd.crosstab(pauses_joined["level"].fillna("-"), pauses_joined["method"]).to_string())
    return (pauses_joined,)


@app.cell
def _(OUTPUT_DIR, pauses_joined):
    unjoined = pauses_joined[pauses_joined["method"] == "unjoined"]
    unjoined[["moratorium_id", "state_abbrev", "jurisdiction", "jurisdiction_type", "latitude", "longitude"]].to_csv(
        OUTPUT_DIR / "unjoined_records.csv", index=False
    )
    duplicates = pauses_joined.dropna(subset=["GEOID"]).duplicated(["level", "GEOID"]).sum()
    print(f"{len(unjoined)} records unjoined (outputs/unjoined_records.csv); {duplicates} extra records share a unit")
    unjoined[["state_abbrev", "jurisdiction", "jurisdiction_type"]].head(15)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Cross-check against the Calyx register

    Calyx lists each place with a pause in effect, read one document at a time, so it should be a
    subset of Bommarito's census. We read its state tables at run time and match by state and
    normalized name. Only counts leave this cell.
    """)
    return


@app.cell
def _(AS_OF, io, normalize_name, pauses_joined, pd, re, requests, units):
    us_states = dict(zip(units["county"]["STATE_NAME"], units["county"]["STUSPS"], strict=True))
    calyx_response = requests.get("https://register.calyxos.ai/pauses/", timeout=120)
    calyx_rows = []
    if calyx_response.ok:
        # Each state is an <h2>State · N</h2> followed by its table; "not yet in effect" sections are skipped.
        for chunk in calyx_response.text.split("<h2")[1:]:
            heading = re.sub(r"<[^>]+>", "", chunk.split("</h2>")[0].split(">", 1)[-1]).strip()
            state = heading.split(" · ")[0]
            if state not in us_states or "<table" not in chunk:
                continue
            table = pd.read_html(io.StringIO(chunk[chunk.index("<table") :]))[0]
            calyx_rows.append(table.assign(state=us_states[state]))
    else:
        print(f"Calyx register: HTTP {calyx_response.status_code}; cross-check skipped")
    calyx = pd.concat(calyx_rows, ignore_index=True) if calyx_rows else pd.DataFrame(columns=["Place", "Ends", "state"])
    calyx["key"] = calyx["Place"].map(normalize_name)
    title = re.search(r"<title>(.*?)</title>", calyx_response.text or "")
    calyx_title = title.group(1) if title else "Calyx register"

    bommarito_keys = set(
        zip(pauses_joined["state_abbrev"], pauses_joined["jurisdiction"].map(normalize_name), strict=True)
    )
    calyx_keys = set(zip(calyx["state"], calyx["key"], strict=True))
    calyx_ends = pd.to_datetime(
        calyx["Ends"].astype(str).str.extract(r"([A-Z][a-z]{2} \d{1,2}, \d{4})")[0], format="%b %d, %Y"
    )
    _six_months = pd.Timestamp(AS_OF) + pd.DateOffset(months=6)
    calyx_check = {
        "calyx_places": len(calyx_keys),
        "calyx_states": calyx["state"].nunique(),
        "calyx_found_in_bommarito": len(calyx_keys & bommarito_keys),
        "bommarito_places": len(bommarito_keys),
        "bommarito_confirmed_by_calyx": len(bommarito_keys & calyx_keys),
        "calyx_with_end_date": int(calyx_ends.notna().sum()),
        "calyx_ending_within_6_months": int(((calyx_ends >= pd.Timestamp(AS_OF)) & (calyx_ends <= _six_months)).sum()),
    }
    print(calyx_title)
    for name, value in calyx_check.items():
        print(f"  {name}: {value}")
    return (calyx_check,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Substations

    The verified file's HIFLD-only table: substations derived from HIFLD Next line ends, with the voltage
    of the highest line that ends there. We keep 230 kV and up. As a check we rerun on the subset an
    OpenStreetMap substation within 1 km confirms (`source = both` in the combined file).
    """)
    return


@app.cell
def _(SUBSTATIONS_DIR, gpd, pd):
    hifld = pd.read_csv(SUBSTATIONS_DIR / "us_substations_hifld_only.csv", dtype={"fips": str})
    combined = pd.read_csv(SUBSTATIONS_DIR / "us_substations.csv", usecols=["id", "source"])
    hv = hifld[hifld["hifld_kv"] >= 230].merge(combined, on="id", how="left")
    substations = gpd.GeoDataFrame(hv, geometry=gpd.points_from_xy(hv["lon"], hv["lat"]), crs=4326).to_crs(5070)
    print(
        f"{len(substations)} derived substations of 230 kV+, {(substations['source'] == 'both').sum()} confirmed by OSM"
    )
    return (substations,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Does each unit hold a 230 kV+ substation, or sit within 5 miles of one?

    For every county, incorporated place and town or township in the 50 states and DC we count the
    substations inside it, and inside its boundary pushed out 5 miles (8.05 km). A unit is **paused** if a
    pause in effect joined to it.
    """)
    return


@app.cell
def _(gpd, pauses_joined, pd, substations, units):
    joined_ids = pauses_joined.dropna(subset=["GEOID"])
    paused_ids = set(zip(joined_ids["level"], joined_ids["GEOID"], strict=True))
    confirmed = substations[substations["source"] == "both"]
    unit_rows = []
    for _level, _unit in units.items():
        _frame = _unit.copy()
        _frame["paused"] = [(_level, geoid) in paused_ids for geoid in _frame["GEOID"]]
        for column, _points, geometry in [
            ("n_inside", substations, _frame.geometry),
            ("n_inside_confirmed", confirmed, _frame.geometry),
            ("n_within_5mi", substations, _frame.geometry.buffer(8047)),
        ]:
            _shapes = gpd.GeoDataFrame({"GEOID": _frame["GEOID"]}, geometry=geometry, crs=_frame.crs)
            counts = gpd.sjoin(_points[["geometry"]], _shapes, predicate="within").groupby("GEOID").size()
            _frame[column] = _frame["GEOID"].map(counts).fillna(0).astype(int)
        unit_rows.append(_frame)
    all_units = pd.concat(unit_rows, ignore_index=True)
    all_units["holds"] = all_units["n_inside"] > 0
    all_units["holds_confirmed"] = all_units["n_inside_confirmed"] > 0
    all_units["within_5mi"] = all_units["n_within_5mi"] > 0
    print(all_units.groupby(["level", "paused"])[["holds", "within_5mi"]].agg(["sum", "count"]).to_string())
    return (all_units,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Paused vs comparable places

    The comparison group is every unit of the same level, in a state with at least one paused unit of
    that level, that has no pause. Bigger places hold more substations, so "comparable" means the same
    state and the same population quartile (quartiles cut within each level). We report:

    - the raw share for paused and unpaused units, with **Fisher's exact test**;
    - a **comparable share**: what paused units would show if each held a substation at the rate of
      unpaused units in its own state and population quartile;
    - the **within-state, same-size odds ratio** (Cochran–Mantel–Haenszel across state × quartile strata),
      the first spike's within-state test with size added.

    "Local" pools places and towns or townships, with strata split by level too.
    """)
    return


@app.cell
def _(StratifiedTable, all_units, fisher_exact, np, pd):
    def compare(_frame: pd.DataFrame, outcome: str, label: str) -> dict:
        """Raw shares, Fisher test, size-matched comparable share and CMH odds ratio for one outcome."""
        paused, other = _frame[_frame["paused"]], _frame[~_frame["paused"]]
        table = [[paused[outcome].sum(), (~paused[outcome]).sum()], [other[outcome].sum(), (~other[outcome]).sum()]]
        odds, p_fisher = fisher_exact(table)
        rates = other.groupby("stratum")[outcome].mean()
        expected = paused["stratum"].map(rates).dropna()
        tables = []
        for _, group in _frame.groupby("stratum"):
            if group["paused"].nunique() == 2:
                tables.append(
                    pd.crosstab(group["paused"], group[outcome])
                    .reindex(index=[True, False], columns=[True, False], fill_value=0)
                    .to_numpy()
                )
        stratified = StratifiedTable(tables)
        low, high = stratified.oddsratio_pooled_confint()
        return {
            "level": label,
            "measure": outcome,
            "paused_n": len(paused),
            "paused_share": paused[outcome].mean(),
            "comparable_share": expected.mean(),
            "unpaused_n": len(other),
            "unpaused_share": other[outcome].mean(),
            "fisher_or": odds,
            "fisher_p": p_fisher,
            "cmh_or": stratified.oddsratio_pooled,
            "cmh_low": low,
            "cmh_high": high,
            "cmh_p": stratified.test_null_odds(correction=True).pvalue,
            "strata": len(tables),
        }

    in_scope = []
    for _level, _unit in all_units.groupby("level"):
        _states = _unit.loc[_unit["paused"], "STUSPS"].unique()
        _frame = _unit[_unit["STUSPS"].isin(_states)].copy()
        _frame["quartile"] = pd.qcut(np.log1p(_frame["pop"]), 4, labels=False, duplicates="drop")
        _frame["stratum"] = _frame["level"] + "|" + _frame["STUSPS"] + "|" + _frame["quartile"].astype(str)
        in_scope.append(_frame)
    scoped = pd.concat(in_scope, ignore_index=True)
    groups = {
        "county": scoped[scoped["level"] == "county"],
        "place": scoped[scoped["level"] == "place"],
        "town/township": scoped[scoped["level"] == "cousub"],
        "local (place + town/township)": scoped[scoped["level"] != "county"],
    }
    comparison = pd.DataFrame(
        [
            compare(_frame, outcome, label)
            for outcome in ["holds", "within_5mi", "holds_confirmed"]
            for label, _frame in groups.items()
        ]
    )
    comparison.round(4)
    return (comparison, scoped)


@app.cell
def _(OUTPUT_DIR, comparison):
    comparison.to_csv(OUTPUT_DIR / "comparison.csv", index=False)
    for _row in comparison.itertuples():
        print(
            f"{_row.measure:15} {_row.level:30} paused {_row.paused_share:6.1%} of {_row.paused_n:4}  "
            f"comparable {_row.comparable_share:6.1%}  unpaused {_row.unpaused_share:6.1%} of {_row.unpaused_n:5}  "
            f"Fisher OR {_row.fisher_or:4.2f} p={_row.fisher_p:.2g}  "
            f"CMH OR {_row.cmh_or:4.2f} ({_row.cmh_low:.2f}-{_row.cmh_high:.2f}) p={_row.cmh_p:.2g}"
        )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. Substations inside paused places, and when those pauses end

    A substation counts once even if it sits inside both a paused county and a paused town. Its pause
    "ends" on the latest known end date among the pauses covering it; if any covering pause has no known
    end date, we can't say when it lifts.
    """)
    return


@app.cell
def _(AS_OF, all_units, gpd, pauses_joined, pd, substations):
    end_by_unit = (
        pauses_joined.dropna(subset=["GEOID"])
        .groupby(["level", "GEOID"])
        .agg(end_date=("end_date", lambda s: pd.NaT if s.isna().any() else s.max()))
        .reset_index()
    )
    paused_units = all_units[all_units["paused"]].merge(end_by_unit, on=["level", "GEOID"])
    _hits = gpd.sjoin(substations[["id", "name", "hifld_kv", "geometry"]], paused_units, predicate="within")
    per_substation = _hits.groupby("id").agg(
        end_date=("end_date", lambda s: pd.NaT if s.isna().any() else s.max()), levels=("level", "nunique")
    )
    six_months = pd.Timestamp(AS_OF) + pd.DateOffset(months=6)
    ends_soon = per_substation["end_date"] <= six_months
    pauses_ending = pauses_joined["end_date"].between(pd.Timestamp(AS_OF), six_months)
    print(
        f"Pauses in effect with a known end date by {six_months.date()}: {pauses_ending.sum()} of {len(pauses_joined)}"
    )
    share_inside = len(per_substation) / len(substations)
    print(
        f"{len(per_substation)} of {len(substations)} 230 kV+ substations ({share_inside:.1%}) sit inside a paused unit"
    )
    print(f"  inside a paused county: {_hits.loc[_hits['level'] == 'county', 'id'].nunique()}")
    print(f"  inside a paused place or town/township: {_hits.loc[_hits['level'] != 'county', 'id'].nunique()}")
    print(f"  every covering pause has a known end date: {per_substation['end_date'].notna().sum()}")
    print(f"  ...and all end by {six_months.date()}: {ends_soon.sum()}")
    print(f"  no known end date for at least one covering pause: {per_substation['end_date'].isna().sum()}")
    return paused_units, per_substation, six_months


@app.cell
def _(mo):
    mo.md(r"""
    ## 9. The free table

    One row per pause in effect that joined to a Census unit: Bommarito's fields, the unit, its population,
    the substations inside it and within 5 miles, and the end date. Bommarito-derived and HIFLD-derived
    only, so it can be published under CC BY 4.0 with attribution to Moratorium Data 2026.
    """)
    return


@app.cell
def _(OUTPUT_DIR, gpd, pauses_joined, paused_units, pd, substations):
    inside = gpd.sjoin(
        substations[["name", "hifld_kv", "geometry"]], paused_units[["level", "GEOID", "geometry"]], predicate="within"
    )
    inside["label"] = inside["name"].fillna("unnamed") + " (" + inside["hifld_kv"].astype(int).astype(str) + " kV)"
    names = inside.groupby(["level", "GEOID"])["label"].agg(lambda s: "; ".join(sorted(s)))
    free_table = pauses_joined.dropna(subset=["GEOID"]).merge(
        paused_units[["level", "GEOID", "NAME", "pop", "n_inside", "n_within_5mi"]], on=["level", "GEOID"]
    )
    free_table["substations_230kv_inside"] = [
        names.get((lv, g), "") for lv, g in zip(free_table["level"], free_table["GEOID"], strict=True)
    ]
    free_table = free_table.rename(
        columns={
            "NAME": "census_name",
            "GEOID": "census_geoid",
            "level": "census_level",
            "method": "join",
            "n_inside": "n_230kv_inside",
            "n_within_5mi": "n_230kv_within_5mi",
        }
    )
    columns = [
        "moratorium_id",
        "state_abbrev",
        "jurisdiction",
        "jurisdiction_type",
        "enacted_status",
        "date_enacted_iso",
        "end_date",
        "census_level",
        "census_geoid",
        "census_name",
        "join",
        "pop",
        "n_230kv_inside",
        "n_230kv_within_5mi",
        "substations_230kv_inside",
    ]
    free_table["end_date"] = pd.to_datetime(free_table["end_date"]).dt.date
    free_table[columns].sort_values(["state_abbrev", "jurisdiction"]).to_csv(
        OUTPUT_DIR / "paused_places_substations.csv", index=False
    )
    print(f"{len(free_table)} rows -> outputs/paused_places_substations.csv")
    free_table[columns].sort_values("n_230kv_inside", ascending=False).head(10)
    return


@app.cell
def _(OUTPUT_DIR, paused_units, plt, scoped, substations, units):
    _states = units["county"].dissolve("STUSPS")
    lower48 = ~_states.index.isin(["AK", "HI"])
    fig, ax = plt.subplots(figsize=(12, 7.5))
    _states[lower48].boundary.plot(ax=ax, color="#bbbbbb", linewidth=0.4)
    paused_48 = paused_units[~paused_units["STUSPS"].isin(["AK", "HI"])]
    paused_48[paused_48["level"] == "county"].plot(ax=ax, color="#f2c4a0", edgecolor="none")
    paused_48[paused_48["level"] != "county"].plot(ax=ax, color="#c8553d", edgecolor="none")
    substations[substations.within(_states[lower48].union_all())].plot(ax=ax, color="#1f3a5f", markersize=1.2)
    ax.set_axis_off()
    ax.set_title(
        f"Data-center pauses in effect (counties light, cities/towns/townships dark) and {len(substations):,} "
        f"substations of 230 kV+ (dots)\n{len(paused_units):,} paused units of {len(scoped):,} in scope",
        fontsize=10,
    )
    fig.savefig(OUTPUT_DIR / "map_paused_230kv.png", dpi=130, bbox_inches="tight")
    fig
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What didn't work, and limits

    - **Reference points, not boundaries.** A Bommarito point can sit outside the right unit; the "nearby"
      joins catch some of those, and the rest are listed in `outputs/unjoined_records.csv`.
    - **Not confirmed in force.** Bommarito's statuses are model-assisted; Calyx's document-read register
      is the check, and it covers far fewer places by design.
    - **End dates are sparse.** Most Bommarito records carry no end date, so "ends within six months" is a
      floor.
    - **Substations are floors.** About half the derived substations carry placeholder names and 14% have
      no voltage, so some 230 kV+ substations are counted as lower or missed.
    - **Exposure, not capacity.** Proximity is not available capacity; interconnection queues decide that.
    """)
    return


if __name__ == "__main__":
    app.run()

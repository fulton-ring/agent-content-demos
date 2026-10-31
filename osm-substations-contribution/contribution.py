import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    import re
    import time
    from collections import Counter
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import numpy as np
    import pandas as pd
    import requests
    import shapely

    return Counter, Path, gpd, json, mo, np, os, pd, re, requests, shapely, time


@app.cell
def _(mo):
    mo.md(r"""
    # Preparing an OpenStreetMap contribution of the substations OSM is missing

    `us-substations-verified/` found 180 places where HIFLD Next's 230 kV+ transmission lines end but OpenStreetMap
    (as of Overture's September 2026 release) had no substation within 1 km. Its hand check of 50 found about 40%
    were real grid nodes. This notebook turns the 180 into a package a founder could hand to the OSM community:

    1. re-check every point against **current** OSM and drop the ones mapped since;
    2. join our imagery labels (`imagery_labels.csv`, made by hand on Esri World Imagery from `chips.py`);
    3. pull names, operators and voltages from public records, each with a source URL and the quoted value;
    4. propose OSM tags, and write the CSV and the MapRoulette GeoJSON.

    Nothing here edits OSM. Inputs are downloaded into `data/` (not committed); outputs go to `outputs/`.
    """)
    return


@app.cell
def _(Path, os, requests):
    DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
    OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "outputs"))
    POINTS_CSV = os.environ.get(
        "POINTS_CSV",
        "https://raw.githubusercontent.com/fulton-ring/agent-content-demos/main/us-substations-verified/dataset/us_substations.csv",
    )
    EARLIER_LABELS_CSV = os.environ.get(
        "EARLIER_LABELS_CSV",
        "https://raw.githubusercontent.com/fulton-ring/agent-content-demos/main/us-substations-verified/hand_check.csv",
    )
    OVERPASS_URLS = os.environ.get(
        "OVERPASS_URLS",
        "https://overpass-api.de/api/interpreter,https://maps.mail.ru/osm/tools/overpass/api/interpreter",
    ).split(",")
    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    HIFLD_LINES_URL = "https://storage.googleapis.com/hifld-next-datasets-prod/hifld/transmission-lines-1/transmission-lines-1/v1.0.0/geoparquet/transmission-lines-1.parquet"
    EIA860M_URL = "https://www.eia.gov/electricity/data/eia860m/xls/september_generator2026.xlsx"

    def download(url: str, name: str) -> Path:
        """Download url into DATA_DIR once; later runs reuse the file."""
        path = DATA_DIR / name
        if path.exists():
            return path
        response = requests.get(
            url, timeout=600, headers={"User-Agent": "fulton-ring osm-substations-contribution spike"}
        )
        response.raise_for_status()
        path.write_bytes(response.content)
        print(f"downloaded {url} ({len(response.content) / 1e6:.1f} MB)")
        return path

    return DATA_DIR, EARLIER_LABELS_CSV, EIA860M_URL, HIFLD_LINES_URL, OUTPUT_DIR, OVERPASS_URLS, POINTS_CSV, download


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. The 180 points

    They are the rows of `us-substations-verified/dataset/us_substations.csv` with `source == "derived"` (no OSM
    substation within 1 km in September) and a HIFLD voltage of 230 kV or more. We read the file from `main` rather
    than copying it, so this folder doesn't fork that dataset.
    """)
    return


@app.cell
def _(EARLIER_LABELS_CSV, POINTS_CSV, download, pd):
    _all = pd.read_csv(download(POINTS_CSV, "us_substations.csv"))
    _both = _all[(_all["source"] == "both") & (_all["hifld_kv"] >= 230) & (_all["match_m"] == 0)]
    control = _both.sort_values("id").iloc[0][["id", "lon", "lat"]]
    points = _all[(_all["source"] == "derived") & (_all["hifld_kv"] >= 230)][
        ["id", "name", "hifld_kv", "state", "fips", "lon", "lat"]
    ].reset_index(drop=True)
    assert len(points) == 180, f"expected the 180 unconfirmed 230 kV+ points, got {len(points)}"
    earlier_labels = pd.read_csv(download(EARLIER_LABELS_CSV, "earlier_hand_check.csv"))
    assert set(earlier_labels["id"]) <= set(points["id"]), "the earlier 50-point hand check isn't a subset of the 180"
    print(
        f"{len(points)} points in {points['state'].nunique()} states; {int((points['hifld_kv'] >= 345).sum())} at"
        f" 345 kV+"
    )
    return control, earlier_labels, points


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Re-check against current OpenStreetMap

    An Overpass query per point asks for every `power=substation` and `power=plant` within 1 km. Each try goes to
    the next endpoint in `OVERPASS_URLS`: the main `overpass-api.de`, then the maps.mail.ru mirror (the main one
    wasn't reachable from where this ran). Answers are saved in `data/overpass/` with their `timestamp_osm_base`,
    the time of the OSM data they reflect; delete the folder to re-check.
    """)
    return


@app.cell
def _(DATA_DIR, OVERPASS_URLS, control, json, pd, points, requests, time):
    # One query per point: the mirror times out on a union of many `around` clauses. Each answer is cached.
    # A control point, a derived substation that OSM does have, checks the query finds substations at all.
    _cache = DATA_DIR / "overpass"
    _cache.mkdir(exist_ok=True)
    _ctrl = pd.DataFrame([{"id": f"control-{control['id']}", "lon": control["lon"], "lat": control["lat"]}])
    for _r in pd.concat([_ctrl, points[["id", "lon", "lat"]]]).itertuples():
        _path = _cache / f"{_r.id}.json"
        if _path.exists():
            continue
        _query = (
            f'[out:json][timeout:90];(nwr["power"="substation"](around:1000,{_r.lat},{_r.lon});'
            f'nwr["power"="plant"](around:1000,{_r.lat},{_r.lon}););out tags center;'
        )
        for _attempt in range(8):
            _url = OVERPASS_URLS[_attempt % len(OVERPASS_URLS)]
            try:
                _resp = requests.post(_url, data={"data": _query}, timeout=120)
            except requests.RequestException as _err:
                print(f"{_r.id}: {_url} failed ({type(_err).__name__}); retrying")
                time.sleep(min(60, 5 * 2**_attempt))
                continue
            if _resp.status_code == 200 and _resp.text.lstrip().startswith("{"):
                _path.write_text(_resp.text)
                break
            print(f"{_r.id}: {_url} returned HTTP {_resp.status_code}; retrying")
            time.sleep(min(60, 5 * 2**_attempt))
        assert _path.exists(), f"Overpass gave no answer for {_r.id} after 8 tries"
    _control = json.loads((_cache / f"control-{control['id']}.json").read_text())["elements"]
    assert any(e["tags"].get("power") == "substation" for e in _control), "control query found no OSM substation"
    print(
        f"Control {control['id']}: the query finds {sum(e['tags'].get('power') == 'substation' for e in _control)}"
        f" OSM substation(s) there"
    )
    _answers = [json.loads((_cache / f"{i}.json").read_text()) for i in points["id"]]
    overpass = {"elements": [e for a in _answers for e in a["elements"]]}
    _stamps = sorted(a["osm3s"]["timestamp_osm_base"] for a in _answers)
    osm_checked_at = _stamps[0]
    print(
        f"OSM data as of {_stamps[0]} to {_stamps[-1]}: {len(overpass['elements'])} power=substation/plant"
        f" features near the points"
    )
    return osm_checked_at, overpass


@app.cell
def _(gpd, np, overpass, pd, points):
    _rows = []
    for _el in overpass["elements"]:
        _c = _el.get("center", _el)
        _tags = _el.get("tags", {})
        _rows.append(
            {
                "osm": f"{_el['type']}/{_el['id']}",
                "power": _tags.get("power"),
                "osm_name": _tags.get("name", ""),
                "osm_voltage": _tags.get("voltage", ""),
                "lon": _c["lon"],
                "lat": _c["lat"],
            }
        )
    _osm = gpd.GeoDataFrame(
        _rows, geometry=gpd.points_from_xy([r["lon"] for r in _rows], [r["lat"] for r in _rows]), crs=4326
    ).to_crs(5070)
    _pts = gpd.GeoDataFrame(points, geometry=gpd.points_from_xy(points["lon"], points["lat"]), crs=4326).to_crs(5070)

    def nearest(kind: str) -> pd.DataFrame:
        """Nearest OSM feature of this power=* kind to each point, by its centre (Overpass already limited to 1 km)."""
        _sub = _osm[_osm["power"] == kind]
        _j = gpd.sjoin_nearest(
            _pts[["id", "geometry"]],
            _sub[["osm", "osm_name", "osm_voltage", "geometry"]],
            max_distance=1500,
            distance_col="m",
        )
        _j = _j.sort_values("m").drop_duplicates("id").set_index("id")
        return _j[["osm", "osm_name", "osm_voltage", "m"]].add_prefix(f"{kind}_")

    osm_status = points[["id"]].set_index("id").join(nearest("substation")).join(nearest("plant"))
    osm_status["mapped_now"] = osm_status["substation_osm"].notna()
    osm_status["substation_m"] = osm_status["substation_m"].round(0)
    osm_status["plant_m"] = osm_status["plant_m"].round(0)
    print(f"Now mapped in OSM (a substation within 1 km): {int(osm_status['mapped_now'].sum())} of {len(osm_status)}")
    print(f"Inside or next to an OSM power plant: {int(osm_status['plant_osm'].notna().sum())}")
    assert np.isfinite(osm_status.loc[osm_status["mapped_now"], "substation_m"]).all()
    osm_status[osm_status["mapped_now"]]
    return (osm_status,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. What HIFLD's own lines say about each point

    HIFLD Next lines carry `SUB_1`/`SUB_2` (the names of the two ends), `OWNER` and `VOLTAGE`. HIFLD is public
    domain (a US federal dataset), so these values can go to OSM. We take every line with an end within 200 m of
    the point. A name counts only when it isn't one of HIFLD's placeholders (`UNKNOWN…`, `TAP…`, `NOT AVAILABLE`)
    and more lines here name it than any other end (a single line can't say which end is which); an owner only
    when every line that names one has the same one. This is one source, so its
    confidence is **medium**: HIFLD's names come from older EIA filings and imagery, and some are out of date.
    """)
    return


@app.cell
def _(Counter, HIFLD_LINES_URL, download, gpd, pd, points, re, shapely):
    _lines = gpd.read_parquet(download(HIFLD_LINES_URL, "hifld-next-transmission-lines-v1.0.0.parquet"))
    _lines = _lines[~_lines["STATUS"].isin(["INACTIVE", "UNDER CONSTRUCTION"])].to_crs(5070).reset_index(drop=True)
    _merged = shapely.line_merge(_lines.geometry.values)
    _ends = pd.concat(
        [
            gpd.GeoDataFrame(
                {"line": _lines.index, "end": "start"},
                geometry=shapely.get_point(shapely.get_geometry(_merged, 0), 0),
                crs=5070,
            ),
            gpd.GeoDataFrame(
                {"line": _lines.index, "end": "end"},
                geometry=shapely.get_point(shapely.get_geometry(_merged, -1), -1),
                crs=5070,
            ),
        ]
    )
    _pts = gpd.GeoDataFrame(points[["id"]], geometry=gpd.points_from_xy(points["lon"], points["lat"]), crs=4326).to_crs(
        5070
    )
    _hits = gpd.sjoin(
        _pts, gpd.GeoDataFrame(_ends, crs=5070).set_geometry(_ends.geometry.buffer(200)), predicate="within"
    )
    at_point = _hits.drop(columns="geometry").join(
        _lines[["OBJECTID", "SUB_1", "SUB_2", "OWNER", "VOLTAGE", "SOURCE", "SOURCEDATE"]], on="line"
    )
    at_point = at_point.drop_duplicates(["id", "line"])

    def is_placeholder(name: object) -> bool:
        text = str(name or "").strip().upper()
        return text in {"", "NONE", "NAN", "NOT AVAILABLE"} or text.startswith(("UNKNOWN", "TAP"))

    def tidy(name: str) -> str:
        """HIFLD's upper case to title case, keeping acronyms, and dropping company suffixes and 'WAPA--' prefixes."""
        name = re.sub(r"^[A-Z]+--\s*|^THE\s+", "", name.strip())
        words = re.sub(r",?\s+(LLC|INC\.?|CORP\.?|CO\.?|COMPANY)$", "", name).split()
        acronyms = {"PECO", "TVA", "BPA", "WAPA", "PNM", "APS", "SRP"}
        return " ".join(w if w in acronyms or not re.search(r"[AEIOUY]", w) else w.capitalize() for w in words)

    def summarize(group: pd.DataFrame) -> pd.Series:
        # Each line names both its ends, so this end's name is the one that most lines here share, strictly ahead
        # of the next (placeholders count too, so a single line, or a tie with UNKNOWN…, gives no name).
        _counts = Counter(n for a, b in zip(group["SUB_1"], group["SUB_2"], strict=True) for n in {a, b})
        _top = _counts.most_common(2)
        _clear = len(_top) == 1 or _top[1][1] < _top[0][1]
        _name = _top[0][0] if _clear and not is_placeholder(_top[0][0]) and len(group) > 1 else ""
        _owners = {o for o in group["OWNER"] if not is_placeholder(o)}
        _kv = sorted({int(v) for v in group["VOLTAGE"] if v and v > 0}, reverse=True)
        _quote = "; ".join(
            f"OBJECTID {r.OBJECTID}: SUB_1={r.SUB_1!r} SUB_2={r.SUB_2!r} OWNER={r.OWNER!r} VOLTAGE={r.VOLTAGE:g}"
            for r in group.itertuples()
        )
        return pd.Series(
            {
                "hifld_lines": len(group),
                "hifld_name": tidy(_name) if _name else "",
                "hifld_operator": tidy(next(iter(_owners))) if len(_owners) == 1 else "",
                "hifld_owners_all": " | ".join(sorted(_owners)),
                "hifld_voltage": ";".join(str(v * 1000) for v in _kv),
                "hifld_quote": _quote[:1500],
            }
        )

    hifld = at_point.groupby("id")[["OBJECTID", "SUB_1", "SUB_2", "OWNER", "VOLTAGE"]].apply(summarize)
    assert hifld.index.nunique() == len(points), "every point should have at least one HIFLD line end within 200 m"
    print(
        f"HIFLD gives a non-placeholder name for {int((hifld['hifld_name'] != '').sum())}, "
        f"a single owner for {int((hifld['hifld_operator'] != '').sum())}, voltage for"
        f" {int((hifld['hifld_voltage'] != '').sum())}"
    )
    return (hifld,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Power plants nearby, from EIA-860M

    The earlier hand check found a quarter of the points were a power plant's own switchyard. EIA's monthly
    generator inventory (EIA-860M, September 2026, public) gives each plant's coordinates, name and operating
    entity. We attach the nearest operating or retired plant within 1.5 km. For a plant switchyard, EIA names the
    plant and its operator, not the yard; we propose `name` only from HIFLD or a document that names the yard.
    """)
    return


@app.cell
def _(EIA860M_URL, download, gpd, pd, points):
    _path = download(EIA860M_URL, "eia860m-september-2026.xlsx")
    _frames = []
    for _sheet in ["Operating", "Retired"]:
        _df = pd.read_excel(_path, _sheet, header=2)
        _df = _df[pd.to_numeric(_df["Plant ID"], errors="coerce").notna()]
        _g = _df.groupby("Plant ID").agg(
            plant_name=("Plant Name", "first"),
            plant_operator=("Entity Name", "first"),
            plant_mw=("Nameplate Capacity (MW)", "sum"),
            plant_tech=("Technology", lambda s: ", ".join(sorted(set(map(str, s))))),
            lat=("Latitude", "first"),
            lon=("Longitude", "first"),
        )
        _g["plant_status"] = _sheet.lower()
        _frames.append(_g.reset_index())
    _plants = pd.concat(_frames).drop_duplicates("Plant ID")
    _plants["lat"] = pd.to_numeric(_plants["lat"], errors="coerce")
    _plants["lon"] = pd.to_numeric(_plants["lon"], errors="coerce")
    _plants = _plants[_plants["lat"].notna() & _plants["lon"].notna()]
    _plants = gpd.GeoDataFrame(_plants, geometry=gpd.points_from_xy(_plants["lon"], _plants["lat"]), crs=4326).to_crs(
        5070
    )
    _pts = gpd.GeoDataFrame(points[["id"]], geometry=gpd.points_from_xy(points["lon"], points["lat"]), crs=4326).to_crs(
        5070
    )
    _near = gpd.sjoin_nearest(_pts, _plants.drop(columns=["lat", "lon"]), max_distance=1500, distance_col="plant_m_eia")
    eia = _near.sort_values("plant_m_eia").drop_duplicates("id").set_index("id")
    eia = eia[
        ["Plant ID", "plant_name", "plant_operator", "plant_mw", "plant_tech", "plant_status", "plant_m_eia"]
    ].rename(columns={"Plant ID": "eia_plant_id"})
    eia["plant_m_eia"] = eia["plant_m_eia"].round(0)
    print(
        f"Points with an EIA-860M plant within 1.5 km: {len(eia)} ({int((eia['plant_status'] == 'retired').sum())}"
        f" retired)"
    )
    return (eia,)


@app.cell
def _(DATA_DIR, eia, hifld, osm_status, points):
    # The list chips.py draws and we label: every point, so the 50 already labelled get a blind second look.
    _to_label = (
        points.set_index("id").join(osm_status[["mapped_now"]]).join(hifld[["hifld_name"]]).join(eia[["plant_name"]])
    )
    _to_label.reset_index().to_csv(DATA_DIR / "points_to_label.csv", index=False)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Imagery labels

    `imagery_labels.csv` has one row per point, labelled by looking at the chip `chips.py` draws: a ~3 km overview
    and a ~1.2 km detail of Esri World Imagery with a 100 m grid. The labels use the earlier spike's scheme:
    **substation** (a fenced yard with equipment where the lines end), **plant** (a power plant's switchyard),
    **tap** (the line branches or continues, no yard), **error** (nothing there) or **unclear**. `visible` says
    whether a yard is visible; `outline_m` is a rough box around it in metres west, south, east, north of the point.
    The labeller didn't see `us-substations-verified/hand_check.csv`, so the 50 points in both are a blind re-check.
    The imagery date and source come from Esri's metadata service, looked up by `chips.py` into
    `imagery_dates.csv`.
    """)
    return


@app.cell
def _(Path, osm_status, pd, points):
    labels = pd.read_csv(Path("imagery_labels.csv"), dtype={"outline_m": str})
    assert set(labels["id"]) == set(points["id"]), "imagery_labels.csv should have exactly the 180 points"
    assert labels["label"].isin(["substation", "plant", "tap", "error", "unclear"]).all()
    assert labels["visible"].isin(["yes", "no", "unclear"]).all()
    _dates = pd.read_csv(Path("imagery_dates.csv"), dtype=str)
    labels = labels.merge(_dates, on="id", how="left")
    _open = labels[labels["id"].isin(osm_status.index[~osm_status["mapped_now"]])]
    print(f"Imagery verdicts on the {len(_open)} points OSM still lacks:")
    print(_open["visible"].value_counts().to_string())
    print(_open["label"].value_counts().to_string())
    print(
        f"Imagery dates: {_open['imagery_date'].min()} to {_open['imagery_date'].max()}, median"
        f" {_open['imagery_date'].sort_values().iloc[len(_open) // 2]}"
    )
    return (labels,)


@app.cell
def _(mo):
    mo.md(r"""
    ### Agreement with the earlier hand check

    The same 50 points, labelled twice by different people (the earlier spike's labeller and this one), without the
    second seeing the first. "Real grid node" means substation or plant.
    """)
    return


@app.cell
def _(earlier_labels, labels, pd):
    _both = earlier_labels[["id", "label"]].merge(labels[["id", "label"]], on="id", suffixes=("_earlier", "_now"))
    assert len(_both) == len(earlier_labels)
    _real = {"substation", "plant"}
    agreement = {
        "points": len(_both),
        "same label": int((_both["label_earlier"] == _both["label_now"]).sum()),
        "same real-node call": int((_both["label_earlier"].isin(_real) == _both["label_now"].isin(_real)).sum()),
    }
    print(agreement)
    pd.crosstab(_both["label_earlier"], _both["label_now"])
    return (agreement,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Names, operators and voltages from other public records

    HIFLD and EIA are joined automatically above. For the confirmed yards we also searched other public sources by
    hand (ISO/RTO interconnection queues, utility planning reports, state commission filings, county permits),
    timing each point. `records_lookup.csv` has one row per value found, with the URL and a quote;
    `records_search_log.csv` has the time spent per point. A value from a document that isn't public domain is kept
    as corroboration, with `osm_ok = no`, and never proposed as a tag: OSM's Legal FAQ asks for written permission
    for anything that isn't (see `rules.md`).
    """)
    return


@app.cell
def _(Path, pd):
    records = pd.read_csv(Path("records_lookup.csv"))
    search_log = pd.read_csv(Path("records_search_log.csv"))
    assert records["field"].isin(["name", "operator", "voltage"]).all()
    assert records["osm_ok"].isin(["yes", "no"]).all()
    assert records["url"].str.startswith("http").all() and records["quote"].str.len().gt(0).all(), (
        "every value needs a URL and quote"
    )
    print(
        f"Searched {len(search_log)} points by hand: {search_log['minutes'].sum():.0f} minutes, median"
        f" {search_log['minutes'].median():.1f} per point"
    )
    print(f"Found a value for {int(search_log['found_any'].sum())} of them")
    print(records.groupby(["source_type", "field"]).size().unstack(fill_value=0).to_string())
    return records, search_log


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Proposed tags and the package

    Following the OSM wiki's `power=substation` and `Key:substation` pages:

    - `power=substation`, drawn as an **area** (the fence line) whenever a yard is visible;
    - `substation=generation` for a plant's switchyard, `switching` when every line ending there has one voltage,
      `transmission` when they have more than one;
    - `voltage` from HIFLD's line voltages, highest first, in volts;
    - `name` and `operator` only from a public-domain source (HIFLD, or another document marked `osm_ok = yes`),
      never a name with "LLC", "Inc" or the like (one of the objections to the March 2026 attempt), and no name for
      a plant's switchyard, since HIFLD and EIA give the plant's name, not the yard's;
    - nothing where another record contradicts HIFLD (the field says `conflict: not proposed`).

    Confidence is **high** when two independent sources agree, **medium** for one public-domain source, and the
    field is left empty otherwise.
    """)
    return


@app.cell
def _(eia, gpd, hifld, labels, np, osm_checked_at, osm_status, pd, points, re, records, search_log):
    pkg = points.set_index("id").join(osm_status).join(hifld).join(eia).join(labels.set_index("id"))
    pkg = pkg.join(search_log.set_index("id")[["drop_reason", "notes"]].rename(columns={"notes": "records_notes"}))
    pkg[["drop_reason", "records_notes"]] = pkg[["drop_reason", "records_notes"]].fillna("")
    _company = r"\b(LLC|INC|CORP|CO|LP|LTD|COMPANY)\b"

    def norm(text: str) -> str:
        """Letters only, so 'LOWMOOR' matches 'Low Moor Substation' and '&' matches 'and'."""
        text = str(text).upper().replace("PG&E", "PACIFIC GAS AND ELECTRIC").replace("&", "AND")
        text = re.sub(r"\b(SUBSTATION|SWITCHING|STATION|THE|COMPANY|CO|INC|LLC)\b", "", text)
        return re.sub(r"[^A-Z]", "", text)

    def agreeing(row_id: str, field: str, value: str) -> pd.DataFrame:
        """Records rows for this point and field whose value agrees with ours."""
        _r = records[(records["id"] == row_id) & (records["field"] == field)]
        if not value:
            return _r.iloc[0:0]
        return _r.loc[_r["value"].map(lambda v: norm(value) in norm(v) or norm(v) in norm(value)).astype(bool)]

    _rows = []
    for _id, _r in pkg.iterrows():
        _hname = _r["hifld_name"] if not re.search(_company, _r["hifld_name"].upper()) else ""
        _op = _r["hifld_operator"]
        _kv = [int(v) for v in str(_r["hifld_voltage"]).split(";") if v]
        _rec_kv = {
            int(float(m)) * 1000
            for v in records[(records["id"] == _id) & (records["field"] == "voltage")]["value"]
            for m in re.findall(r"\d+(?:\.\d+)?", str(v))
        }
        _kv_conflict = bool(_rec_kv) and bool(_kv) and _kv[0] not in _rec_kv
        # A plant's switchyard often has its own name; HIFLD and EIA give the plant's, so propose none.
        _hname = "" if _r["label"] == "plant" else _hname
        _name, _name_src = _hname, "HIFLD" if _hname else ""
        # A records-only name, when HIFLD has none: public domain only, and never a plant's name for its yard.
        _pd_names = records[(records["id"] == _id) & (records["field"] == "name") & (records["osm_ok"] == "yes")]
        if not _name and len(_pd_names) and _r["label"] != "plant":
            _name, _name_src = str(_pd_names.iloc[0]["value"]), str(_pd_names.iloc[0]["source_type"])
        _name_agree = agreeing(_id, "name", _name)
        _op_agree = agreeing(_id, "operator", _op)
        _op_any = records[(records["id"] == _id) & (records["field"] == "operator")]
        _op_conflict = bool(_op) and len(_op_any) > 0 and len(_op_agree) == 0
        _op = "" if _op_conflict else _op
        _kv_agree = bool(_kv) and _kv[0] in _rec_kv
        _rows.append(
            {
                "id": _id,
                "proposed_substation": "generation"
                if _r["label"] == "plant"
                else ("switching" if len(_kv) == 1 else "transmission"),
                "proposed_voltage": "" if _kv_conflict else ";".join(str(v) for v in _kv),
                "voltage_confidence": "conflict: not proposed"
                if _kv_conflict
                else ("high" if _kv_agree else ("medium" if _kv else "")),
                "proposed_name": _name,
                "name_source": "+".join(dict.fromkeys([_name_src, *sorted(_name_agree["source_type"])]))
                if _name
                else "",
                "name_confidence": ""
                if not _name
                else ("high" if len(_name_agree) > (_name_src != "HIFLD") else "medium"),
                "proposed_operator": _op,
                "operator_source": "+".join(["HIFLD", *sorted(set(_op_agree["source_type"]))]) if _op else "",
                "operator_confidence": "conflict: not proposed"
                if _op_conflict
                else ("" if not _op else ("high" if len(_op_agree) else "medium")),
                "draw_as": "area"
                if _r["visible"] == "yes"
                else ("mapper decides" if _r["visible"] == "unclear" else ""),
            }
        )
    tags = pd.DataFrame(_rows).set_index("id")
    pkg = pkg.join(tags)
    pkg["osm_checked_at"] = osm_checked_at

    def outline(row: pd.Series) -> str:
        """The labeller's rough box (metres W,S,E,N of the point) as a lon/lat polygon, for a founder to eyeball."""
        if not isinstance(row["outline_m"], str) or not row["outline_m"].strip():
            return ""
        w, so, e, n = (float(v) for v in row["outline_m"].split(","))
        dx = 1 / (111_320 * np.cos(np.radians(row["lat"])))
        dy = 1 / 110_540
        xs = [row["lon"] + w * dx, row["lon"] + e * dx]
        ys = [row["lat"] + so * dy, row["lat"] + n * dy]
        corners = [(xs[0], ys[0]), (xs[1], ys[0]), (xs[1], ys[1]), (xs[0], ys[1]), (xs[0], ys[0])]
        return "POLYGON((" + ", ".join(f"{x:.6f} {y:.6f}" for x, y in corners) + "))"

    pkg["outline_wkt"] = pkg.apply(outline, axis=1)
    pkg["osm_status"] = np.where(pkg["mapped_now"], "mapped since (dropped)", "not in OSM")
    pkg["needs_mapper"] = ~pkg["mapped_now"] & pkg["visible"].isin(["yes", "unclear"]) & (pkg["drop_reason"] == "")
    print(f"Dropped because records say there's no yard: {int((pkg['drop_reason'] != '').sum())}")
    # HIFLD sometimes ends lines at two spots in one yard: keep one task per yard (points within 600 m).
    _cand = pkg[pkg["needs_mapper"]].sort_values(["visible", "hifld_lines"], ascending=[False, False])
    _xy = gpd.GeoSeries.from_xy(_cand["lon"], _cand["lat"], crs=4326).to_crs(5070).set_axis(_cand.index)
    pkg["duplicate_of"] = ""
    for _id in _cand.index:
        if pkg.at[_id, "duplicate_of"]:
            continue
        for _other in _xy.index[(_xy.distance(_xy[_id]) < 600) & (_xy.index != _id)]:
            if not pkg.at[_other, "duplicate_of"]:
                pkg.at[_other, "duplicate_of"] = _id
    pkg.loc[pkg["duplicate_of"] != "", "needs_mapper"] = False
    print(f"Merged {int((pkg['duplicate_of'] != '').sum())} points that are a second line end in the same yard")
    _open = pkg[~pkg["mapped_now"] & (pkg["visible"] == "yes") & (pkg["duplicate_of"] == "")]
    print(f"Yards confirmed on imagery and still missing from OSM: {len(_open)} (one per yard)")
    print(
        f"  with a proposed name: {int((_open['proposed_name'] != '').sum())}, operator:"
        f" {int((_open['proposed_operator'] != '').sum())}, voltage: {int((_open['proposed_voltage'] != '').sum())}"
    )
    print(
        f"  name confidence: {_open['name_confidence'].value_counts().to_dict()}; operator:"
        f" {_open['operator_confidence'].value_counts().to_dict()}"
    )
    print(f"MapRoulette tasks (yes or unclear, not in OSM): {int(pkg['needs_mapper'].sum())}")
    return (pkg,)


@app.cell
def _(OUTPUT_DIR, json, pkg):
    _cols = [
        "name",
        "state",
        "fips",
        "lon",
        "lat",
        "osm_status",
        "osm_checked_at",
        "substation_osm",
        "substation_osm_name",
        "substation_m",
        "plant_osm",
        "plant_osm_name",
        "plant_m",
        "label",
        "visible",
        "what_we_saw",
        "outline_m",
        "imagery_date",
        "imagery_source",
        "imagery_resolution_m",
        "proposed_substation",
        "proposed_voltage",
        "proposed_name",
        "name_source",
        "name_confidence",
        "proposed_operator",
        "operator_source",
        "operator_confidence",
        "voltage_confidence",
        "draw_as",
        "needs_mapper",
        "duplicate_of",
        "drop_reason",
        "records_notes",
        "outline_wkt",
        "duplicate_of",
        "hifld_lines",
        "hifld_owners_all",
        "hifld_quote",
        "eia_plant_id",
        "plant_name",
        "plant_operator",
        "plant_status",
        "plant_m_eia",
    ]
    pkg[_cols].rename(columns={"name": "derived_name"}).reset_index().to_csv(
        OUTPUT_DIR / "substations_package.csv", index=False
    )

    _features = []
    for _id, _r in pkg[pkg["needs_mapper"]].iterrows():
        _props = {
            "externalId": _id,
            "hifld_voltage_kv": "/".join(str(int(v) // 1000) for v in str(_r["proposed_voltage"]).split(";") if v),
            "imagery_verdict": {"yes": "yard visible", "unclear": "unclear"}[_r["visible"]]
            + (" (power plant)" if _r["label"] == "plant" else ""),
            "imagery_note": str(_r["what_we_saw"]),
            "imagery_date": str(_r["imagery_date"]),
            "proposed_substation": _r["proposed_substation"],
            "proposed_voltage": _r["proposed_voltage"],
            "proposed_name": _r["proposed_name"],
            "proposed_operator": _r["proposed_operator"],
        }
        _features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [_r["lon"], _r["lat"]]},
                "properties": _props,
            }
        )
    # MapRoulette's preferred line-by-line format: one FeatureCollection per task, each line starting with RS (0x1E).
    with open(OUTPUT_DIR / "maproulette_tasks.geojson", "w") as _f:
        for _feat in _features:
            _f.write("\x1e" + json.dumps({"type": "FeatureCollection", "features": [_feat]}) + "\n")
    print(f"wrote {len(pkg)} rows to substations_package.csv and {len(_features)} tasks to maproulette_tasks.geojson")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. What would become newly public

    HIFLD's lines already end at these coordinates in a public federal dataset. Mapping them in OSM would add:
    that a yard really exists there (confirmed on imagery), its fence outline, its voltage, and a name and operator
    where public records give one. This table is exactly that set, for the founders' security decision.
    """)
    return


@app.cell
def _(OUTPUT_DIR, pkg):
    _new = pkg[pkg["needs_mapper"]]
    newly_public = _new.assign(kv=_new["hifld_kv"].astype(int))[
        [
            "state",
            "kv",
            "label",
            "visible",
            "proposed_substation",
            "proposed_voltage",
            "proposed_name",
            "proposed_operator",
            "lon",
            "lat",
        ]
    ].sort_values(["kv", "state"], ascending=[False, True])
    newly_public.reset_index().to_csv(OUTPUT_DIR / "newly_public.csv", index=False)
    print(
        f"{len(newly_public)} yards would go on the map ({int((newly_public['visible'] == 'yes').sum())} seen, the"
        f" rest unclear)"
    )
    print(newly_public.groupby("kv").size().to_string())
    print(f"States: {newly_public['state'].value_counts().to_dict()}")
    newly_public
    return


if __name__ == "__main__":
    app.run()

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    import time
    from datetime import UTC, datetime
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import numpy as np
    import pandas as pd
    import requests
    import shapely

    return Path, UTC, datetime, gpd, json, mo, np, os, pd, requests, shapely, time


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
        "POINTS_CSV", "https://raw.githubusercontent.com/fulton-ring/agent-content-demos/main/us-substations-verified/dataset/us_substations.csv"
    )
    EARLIER_LABELS_CSV = os.environ.get(
        "EARLIER_LABELS_CSV", "https://raw.githubusercontent.com/fulton-ring/agent-content-demos/main/us-substations-verified/hand_check.csv"
    )
    OVERPASS_URL = os.environ.get("OVERPASS_URL", "https://maps.mail.ru/osm/tools/overpass/api/interpreter")
    DATA_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    HIFLD_LINES_URL = "https://storage.googleapis.com/hifld-next-datasets-prod/hifld/transmission-lines-1/transmission-lines-1/v1.0.0/geoparquet/transmission-lines-1.parquet"
    EIA860M_URL = "https://www.eia.gov/electricity/data/eia860m/xls/september_generator2026.xlsx"

    def download(url: str, name: str) -> Path:
        """Download url into DATA_DIR once; later runs reuse the file."""
        path = DATA_DIR / name
        if path.exists():
            return path
        response = requests.get(url, timeout=600, headers={"User-Agent": "fulton-ring osm-substations-contribution spike"})
        response.raise_for_status()
        path.write_bytes(response.content)
        print(f"downloaded {url} ({len(response.content) / 1e6:.1f} MB)")
        return path

    return DATA_DIR, EARLIER_LABELS_CSV, EIA860M_URL, HIFLD_LINES_URL, OUTPUT_DIR, OVERPASS_URL, POINTS_CSV, download


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
    points = _all[(_all["source"] == "derived") & (_all["hifld_kv"] >= 230)][
        ["id", "name", "hifld_kv", "state", "fips", "lon", "lat"]
    ].reset_index(drop=True)
    assert len(points) == 180, f"expected the 180 unconfirmed 230 kV+ points, got {len(points)}"
    earlier_labels = pd.read_csv(download(EARLIER_LABELS_CSV, "earlier_hand_check.csv"))
    assert set(earlier_labels["id"]) <= set(points["id"]), "the earlier 50-point hand check isn't a subset of the 180"
    print(f"{len(points)} points in {points['state'].nunique()} states; {int((points['hifld_kv'] >= 345).sum())} at 345 kV+")
    return earlier_labels, points


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Re-check against current OpenStreetMap

    An Overpass query per point asks for every `power=substation` and `power=plant` within 1 km. The main
    `overpass-api.de` instance isn't reachable from where this ran, so the default is the public mirror at
    maps.mail.ru (any Overpass endpoint works: set `OVERPASS_URL`). Answers are saved in `data/overpass/` with
    their `timestamp_osm_base`, the time of the OSM data they reflect; delete the folder to re-check.
    """)
    return


@app.cell
def _(DATA_DIR, OVERPASS_URL, json, points, requests, time):
    # One query per point: the mirror times out on a union of many `around` clauses. Each answer is cached.
    _cache = DATA_DIR / "overpass"
    _cache.mkdir(exist_ok=True)
    for _r in points.itertuples():
        _path = _cache / f"{_r.id}.json"
        if _path.exists():
            continue
        _query = (
            f'[out:json][timeout:90];(nwr["power"="substation"](around:1000,{_r.lat},{_r.lon});'
            f'nwr["power"="plant"](around:1000,{_r.lat},{_r.lon}););out tags center;'
        )
        for _attempt in range(5):
            try:
                _resp = requests.post(OVERPASS_URL, data={"data": _query}, timeout=120)
            except requests.RequestException as _err:
                print(f"{_r.id}: {_err}; retrying")
                time.sleep(5 * 2**_attempt)
                continue
            if _resp.status_code == 200 and _resp.text.lstrip().startswith("{"):
                _path.write_text(_resp.text)
                break
            print(f"{_r.id}: Overpass HTTP {_resp.status_code}; retrying")
            time.sleep(5 * 2**_attempt)
        assert _path.exists(), f"Overpass gave no answer for {_r.id} after 5 tries"
    _answers = [json.loads((_cache / f"{i}.json").read_text()) for i in points["id"]]
    overpass = {"elements": [e for a in _answers for e in a["elements"]]}
    _stamps = sorted(a["osm3s"]["timestamp_osm_base"] for a in _answers)
    osm_checked_at = _stamps[0]
    print(f"OSM data as of {_stamps[0]} to {_stamps[-1]}: {len(overpass['elements'])} power=substation/plant features near the points")
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
    _osm = gpd.GeoDataFrame(_rows, geometry=gpd.points_from_xy([r["lon"] for r in _rows], [r["lat"] for r in _rows]), crs=4326).to_crs(5070)
    _pts = gpd.GeoDataFrame(points, geometry=gpd.points_from_xy(points["lon"], points["lat"]), crs=4326).to_crs(5070)

    def nearest(kind: str) -> pd.DataFrame:
        """Nearest OSM feature of this power=* kind to each point, by its centre (Overpass already limited to 1 km)."""
        _sub = _osm[_osm["power"] == kind]
        _j = gpd.sjoin_nearest(_pts[["id", "geometry"]], _sub[["osm", "osm_name", "osm_voltage", "geometry"]], max_distance=1500, distance_col="m")
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
    and every line agrees on it; an owner only when every line has the same one. This is one source, so its
    confidence is **medium**: HIFLD's names come from older EIA filings and imagery, and some are out of date.
    """)
    return


@app.cell
def _(HIFLD_LINES_URL, download, gpd, pd, points, shapely):
    _lines = gpd.read_parquet(download(HIFLD_LINES_URL, "hifld-next-transmission-lines-v1.0.0.parquet"))
    _lines = _lines[~_lines["STATUS"].isin(["INACTIVE", "UNDER CONSTRUCTION"])].to_crs(5070).reset_index(drop=True)
    _merged = shapely.line_merge(_lines.geometry.values)
    _ends = pd.concat(
        [
            gpd.GeoDataFrame({"line": _lines.index, "end": "start"}, geometry=shapely.get_point(shapely.get_geometry(_merged, 0), 0), crs=5070),
            gpd.GeoDataFrame({"line": _lines.index, "end": "end"}, geometry=shapely.get_point(shapely.get_geometry(_merged, -1), -1), crs=5070),
        ]
    )
    _pts = gpd.GeoDataFrame(points[["id"]], geometry=gpd.points_from_xy(points["lon"], points["lat"]), crs=4326).to_crs(5070)
    _hits = gpd.sjoin(_pts, gpd.GeoDataFrame(_ends, crs=5070).set_geometry(_ends.geometry.buffer(200)), predicate="within")
    at_point = _hits.drop(columns="geometry").join(_lines[["OBJECTID", "SUB_1", "SUB_2", "OWNER", "VOLTAGE", "SOURCE", "SOURCEDATE"]], on="line")
    at_point = at_point.drop_duplicates(["id", "line"])

    def is_placeholder(name: object) -> bool:
        text = str(name or "").strip().upper()
        return text in {"", "NONE", "NAN", "NOT AVAILABLE"} or text.startswith(("UNKNOWN", "TAP"))

    def summarize(group: pd.DataFrame) -> pd.Series:
        # The name at this end is the one every line shares (each line names both of its ends).
        _sets = [{a, b} for a, b in zip(group["SUB_1"], group["SUB_2"], strict=True)]
        _shared = set.intersection(*_sets) if len(_sets) > 1 else set()
        _names = [n for n in _shared if not is_placeholder(n)]
        _owners = {o for o in group["OWNER"] if not is_placeholder(o)}
        _kv = sorted({int(v) for v in group["VOLTAGE"] if v and v > 0}, reverse=True)
        _quote = "; ".join(
            f"OBJECTID {r.OBJECTID}: SUB_1={r.SUB_1!r} SUB_2={r.SUB_2!r} OWNER={r.OWNER!r} VOLTAGE={r.VOLTAGE:g}"
            for r in group.itertuples()
        )
        return pd.Series(
            {
                "hifld_lines": len(group),
                "hifld_name": _names[0].title() if len(_names) == 1 else "",
                "hifld_operator": next(iter(_owners)).title() if len(_owners) == 1 else "",
                "hifld_owners_all": " | ".join(sorted(_owners)),
                "hifld_voltage": ";".join(str(v * 1000) for v in _kv),
                "hifld_quote": _quote[:1500],
            }
        )

    hifld = at_point.groupby("id")[["OBJECTID", "SUB_1", "SUB_2", "OWNER", "VOLTAGE"]].apply(summarize)
    assert hifld.index.nunique() == len(points), "every point should have at least one HIFLD line end within 200 m"
    print(
        f"HIFLD gives a non-placeholder name for {int((hifld['hifld_name'] != '').sum())}, "
        f"a single owner for {int((hifld['hifld_operator'] != '').sum())}, voltage for {int((hifld['hifld_voltage'] != '').sum())}"
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
    _plants = _plants[_plants["lat"].notna() & _plants["lon"].notna()]
    _plants = gpd.GeoDataFrame(_plants, geometry=gpd.points_from_xy(_plants["lon"], _plants["lat"]), crs=4326).to_crs(5070)
    _pts = gpd.GeoDataFrame(points[["id"]], geometry=gpd.points_from_xy(points["lon"], points["lat"]), crs=4326).to_crs(5070)
    _near = gpd.sjoin_nearest(_pts, _plants.drop(columns=["lat", "lon"]), max_distance=1500, distance_col="plant_m_eia")
    eia = _near.sort_values("plant_m_eia").drop_duplicates("id").set_index("id")
    eia = eia[["Plant ID", "plant_name", "plant_operator", "plant_mw", "plant_tech", "plant_status", "plant_m_eia"]].rename(
        columns={"Plant ID": "eia_plant_id"}
    )
    eia["plant_m_eia"] = eia["plant_m_eia"].round(0)
    print(f"Points with an EIA-860M plant within 1.5 km: {len(eia)} ({int((eia['plant_status'] == 'retired').sum())} retired)")
    return (eia,)


@app.cell
def _(DATA_DIR, OUTPUT_DIR, eia, hifld, osm_status, points):
    # The list chips.py draws and we label: every point, so the 50 already labelled get a blind second look.
    to_label = points.set_index("id").join(osm_status[["mapped_now", "substation_m", "plant_osm"]]).join(hifld[["hifld_name", "hifld_voltage"]])
    to_label = to_label.join(eia[["plant_name", "plant_m_eia"]])
    to_label.reset_index().to_csv(DATA_DIR / "points_to_label.csv", index=False)
    print(f"wrote {DATA_DIR / 'points_to_label.csv'} for chips.py; outputs go to {OUTPUT_DIR}")
    return


if __name__ == "__main__":
    app.run()

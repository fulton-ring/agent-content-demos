import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import hashlib
    import html
    import json
    import os
    import re
    import time
    from pathlib import Path

    import duckdb
    import geopandas as gpd
    import marimo as mo
    import pandas as pd
    import requests

    started = time.time()
    DATA = Path(os.environ.get("DATA_DIR", "data"))
    OUT = Path(os.environ.get("OUTPUT_DIR", "outputs"))
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    METRE_PER_MILE = 1609.344
    BANDS = [1, 5, 10]
    return (
        BANDS,
        DATA,
        METRE_PER_MILE,
        OUT,
        Path,
        duckdb,
        gpd,
        hashlib,
        html,
        json,
        mo,
        pd,
        re,
        requests,
        started,
        time,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # How far is each planned US data-center campus from a high-voltage substation?

    Announcements give megawatts and dollars. They rarely say whether a 230 kV or higher substation already exists
    nearby, or whether the project also means a new substation and new lines. We expected a real share of the
    site-located gigawatt campuses to have **no 230 kV+ substation within 5 miles**, and we expected distance
    figures computed from HIFLD's 2023 transmission layer to misread some of them.

    The test: take two public site lists, keep only campuses located to a site, and measure the distance from each to
    the nearest 230 kV+ and 345 kV+ substation in our
    [us-substations-verified](../us-substations-verified/) dataset, and to the nearest 230 kV+ line in HIFLD (2023)
    and in OpenStreetMap. If nearly every campus sits within a few miles of a high-voltage substation, the finding is
    the opposite: the buildout follows the grid.

    We publish distances, counts and shares. We do not publish a table joining campus coordinates to substation
    coordinates; the per-campus file in `outputs/` has names and distances only.
    """)
    return


@app.cell
def _(DATA, Path, hashlib, requests, time):
    def download(url: str, name: str, sha256: str | None = None) -> Path:
        """Fetch `url` into data/ once (3 tries), and check its SHA-256 when the publisher gives one."""
        path = DATA / name
        if not path.exists():
            for attempt in range(3):
                response = requests.get(url, timeout=300, headers={"User-Agent": "fulton-ring-spike"})
                if response.ok:
                    path.write_bytes(response.content)
                    break
                print(f"{url}: HTTP {response.status_code} (attempt {attempt + 1} of 3)")
                time.sleep(2**attempt)
            assert path.exists(), f"could not download {url}"
        if sha256:
            actual = hashlib.sha256(path.read_bytes()).hexdigest()
            assert actual == sha256, f"{name}: SHA-256 {actual} is not the published {sha256}"
        return path

    return (download,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 1. The two site lists

    **Malachi.Energy, frozen release 2026-10-03.** 56 hand-researched "mega projects". Every row has a
    `location_basis`; the release's own rule is that only `site` and `address` rows count toward any distance fact,
    so we keep those. The files are checked against the release's published SHA-256s.
    """)
    return


@app.cell
def _(download, pd):
    _base = "https://malachi.energy/data-centers/releases/2026-10-03/"
    _sums = dict(
        line.split()[::-1]
        for line in download(_base + "checksums.sha256", "malachi_checksums.sha256").read_text().splitlines()
    )
    malachi_all = pd.read_csv(
        download(_base + "mega-projects.csv", "malachi_mega-projects.csv", _sums["mega-projects.csv"])
    )
    malachi = malachi_all[malachi_all["location_basis"].isin(["site", "address"])].reset_index(drop=True)
    print(
        f"Malachi.Energy: {len(malachi_all)} projects, {malachi_all['capacity_mw'].sum():,.0f} MW; "
        f"{len(malachi)} site- or address-located, {malachi['capacity_mw'].sum():,.0f} MW"
    )
    return (malachi,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **Data Center Atlas, archive 2026-10-25 (`research-sixtyfourth`, CC BY 4.0).** A global list built from
    filings and disclosures, with a `geometry_use_scope` on every project. We keep US sites where at least one
    project's geometry is a campus, project or reviewed site locator or an official boundary, and drop those located
    only to a locality, a county or an "approximate site", and those whose only status is cancelled. Capacity comes
    from the imported project records: the largest campus-level planned power figure that isn't on-site generation,
    else the typed IT-load figure.
    """)
    return


@app.cell
def _(download, json, pd):
    _base = "https://github.com/kiankyars/datacenter-atlas/releases/download/data-2026-10-25-research-sixtyfourth/"
    _sums = dict(
        line.split()[::-1] for line in download(_base + "SHA256SUMS", "atlas_SHA256SUMS").read_text().splitlines()
    )
    _read = {"keep_default_na": False, "na_values": [""]}
    _sites = pd.read_csv(download(_base + "sites.csv", "atlas_sites.csv", _sums["sites.csv"]), **_read)
    _projects = pd.read_csv(download(_base + "projects.csv", "atlas_projects.csv", _sums["projects.csv"]), **_read)
    _projects = _projects[_projects["country_iso_a2"] == "US"]

    def _planned_mw(row: pd.Series) -> float | None:
        values = [
            m["value"]
            for detail in json.loads(row["project_details_json"] or "[]")
            for m in detail["record"].get("metrics", [])
            if m["metric"] == "power_capacity"
            and m.get("applies_to") == "campus"
            and m["unit"] == "MW"
            and m.get("power_scope") != "onsite_generation"
        ] or [o["base"] for o in json.loads(row["power_observations_json"] or "[]") if o["unit"] == "MW"]
        return max(values) if values else None

    _projects["mw"] = _projects.apply(_planned_mw, axis=1)
    _site_level_scopes = {"campus_locator", "project_locator", "reviewed_site_locator", "official_boundary"}
    _by_site = _projects.groupby("site_id").agg(
        site_level=("geometry_use_scope", lambda s: bool(set(s) & _site_level_scopes)),
        mw=("mw", "max"),
        text=("name", lambda s: " ".join(s)),
        owners=("owner", lambda s: " ".join(s.dropna())),
        operators=("operator", lambda s: " ".join(s.dropna())),
    )
    atlas_us = _sites[_sites["country_iso_a2"] == "US"].join(_by_site, on="site_id").reset_index(drop=True)
    _status = atlas_us["statuses_json"].map(lambda j: set(json.loads(j)))
    atlas_us["cancelled"] = _status.map(lambda st: st == {"cancelled"})
    atlas_us["operational"] = _status.map(lambda st: bool(st) and st <= {"operational", "completed"})
    atlas = atlas_us[atlas_us["site_level"] & ~atlas_us["cancelled"]].reset_index(drop=True)
    print(
        f"Data Center Atlas: {len(_sites)} sites worldwide, {len(atlas_us)} in the US, {len(atlas)} located to a site "
        f"and not cancelled; "
        f"{atlas['mw'].notna().sum()} of those carry a planned MW figure"
    )
    return atlas, atlas_us


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 2. Reconcile the two lists

    The lists don't share an identifier, and the nearest Atlas site is often the wrong campus (Meta Prometheus's
    nearest Atlas site is a Google campus in the same town). So a Malachi project matches an Atlas US site (at any
    precision) within 50 km only when their names, developers and owners share **two distinctive words**, or one
    word and the points are within 5 km. Generic words (data, center, campus, county, project, AI…) don't count.
    The matched pairs are printed so a reader can check every one.
    """)
    return


@app.cell
def _(atlas_us, gpd, malachi, pd, re):
    _stop = set(
        "data center centre centers campus county project the of and ai inc llc digital technology park site "
        "development hyperscale datacenter expansion".split()
    )

    def words(text: str) -> set[str]:
        return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in _stop and len(w) > 2}

    _m = gpd.GeoDataFrame(
        malachi.assign(words=[words(f"{a} {b}") for a, b in zip(malachi["name"], malachi["developer"], strict=True)]),
        geometry=gpd.points_from_xy(malachi["lon"], malachi["lat"]),
        crs=4326,
    ).to_crs(5070)
    _a = gpd.GeoDataFrame(
        atlas_us.assign(words=(atlas_us["name"] + " " + atlas_us["text"] + " " + atlas_us["owners"]).map(words)),
        geometry=gpd.points_from_xy(atlas_us["longitude"], atlas_us["latitude"]),
        crs=4326,
    ).to_crs(5070)
    _pairs = gpd.sjoin(
        _m[["id", "words", "geometry"]].set_geometry(_m.buffer(50_000)),
        _a[["site_id", "name", "words", "site_level", "mw", "geometry"]].assign(apoint=_a.geometry),
        predicate="contains",
    ).reset_index(names="m_row")
    _pairs["shared"] = [a & b for a, b in zip(_pairs["words_left"], _pairs["words_right"], strict=True)]
    _pairs["n"] = _pairs["shared"].map(len)
    _pairs["gap_km"] = (
        _m.geometry.loc[_pairs["m_row"]].reset_index(drop=True).distance(gpd.GeoSeries(_pairs["apoint"], crs=5070))
        / 1000
    )
    _pairs = _pairs[(_pairs["n"] >= 2) | ((_pairs["n"] == 1) & (_pairs["gap_km"] <= 5))]
    _best = _pairs.sort_values(["n", "gap_km"], ascending=[False, True]).drop_duplicates("m_row").set_index("m_row")
    matches = malachi[["id", "name", "capacity_mw"]].join(
        _best[["site_id", "name", "site_level", "mw", "gap_km", "shared"]].rename(
            columns={"name": "atlas_name", "mw": "atlas_mw"}
        )
    )
    matches["shared"] = matches["shared"].map(lambda s: ", ".join(sorted(s)) if isinstance(s, set) else "")
    assert not matches["site_id"].dropna().duplicated().any(), "two Malachi projects matched one Atlas site"
    pd.set_option("display.width", 200)
    matches.round(1)
    return (matches,)


@app.cell
def _(atlas, malachi, matches, mo):
    _m = matches.dropna(subset=["site_id"])
    _both_site = _m[_m["site_level"].astype(bool)]
    _loc = _both_site[_both_site["gap_km"] > 1]
    _cap = _m.dropna(subset=["atlas_mw"])
    _ratio = (_cap["capacity_mw"] / _cap["atlas_mw"]).where(lambda r: r >= 1, lambda r: 1 / r)
    reconcile = {
        "malachi_site_located": len(malachi),
        "atlas_site_located": len(atlas),
        "malachi_found_in_atlas_any_precision": len(_m),
        "in_both_site_located": len(_both_site),
        "malachi_only": len(malachi) - len(_m),
        "atlas_only_site_located": len(atlas) - len(_both_site),
        "location_gap_over_1km": len(_loc),
        "location_gap_over_5km": int((_both_site["gap_km"] > 5).sum()),
        "pairs_with_both_capacities": len(_cap),
        "capacity_differs_by_over_25pct": int((_ratio > 1.25).sum()),
    }
    _cap_rows = _cap.assign(ratio=_ratio)[_ratio > 1.25][["name", "capacity_mw", "atlas_name", "atlas_mw"]]
    mo.vstack(
        [
            mo.md(
                f"""
    Of Malachi's **{len(malachi)}** site-located projects, **{len(_m)}** appear in the Atlas, but only
    **{len(_both_site)}** of those are located to a site there too; the rest the Atlas places at a locality or county.
    **{reconcile["atlas_only_site_located"]}** Atlas site-located US sites aren't in Malachi's list (most are smaller
    or existing campuses; Malachi tracks only mega projects).

    **Location.** For the {len(_both_site)} campuses both lists place at a site, the two coordinates are more than
    1 km apart for **{len(_loc)}** and more than 5 km apart for **{reconcile["location_gap_over_5km"]}**; median gap
    {_both_site["gap_km"].median():.1f} km. (Where the Atlas has only a locality, its point is up to
    {_m["gap_km"].max():.0f} km off, which is a precision gap, not a disagreement.)

    **Capacity.** Both lists give a planned MW for {len(_cap)} matched campuses; they differ by more than 25% for
    **{reconcile["capacity_differs_by_over_25pct"]}**:
    """
            ),
            _cap_rows,
        ]
    )
    return (reconcile,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    **The campuses we measure.** All of Malachi's site-located projects (at Malachi's coordinate), plus the Atlas
    site-located US sites that don't match one of them. For a campus in both lists we also measure from the Atlas
    coordinate, to see whether the location disagreement changes the answer. "Gigawatt" means a planned 1,000 MW or
    more in either list; "not yet operational" drops campuses whose only status is operational or completed.
    """)
    return


@app.cell
def _(atlas, gpd, malachi, matches, pd):
    _atlas_matched = set(matches["site_id"].dropna())
    _rest = atlas[~atlas["site_id"].isin(_atlas_matched)]
    _mw = matches["capacity_mw"].combine(matches["atlas_mw"], lambda a, b: max(a, b) if pd.notna(b) else a)
    campuses = pd.concat(
        [
            pd.DataFrame(
                {
                    "campus": malachi["name"],
                    "list": "Malachi",
                    "mw": malachi["capacity_mw"],
                    "max_mw": _mw,
                    "lon": malachi["lon"],
                    "lat": malachi["lat"],
                    "in_atlas_site": matches["site_level"].fillna(False).astype(bool),
                    "atlas_site_id": matches["site_id"],
                    "operational": malachi["status"] == "operational",
                }
            ),
            pd.DataFrame(
                {
                    "campus": _rest["name"],
                    "list": "Atlas",
                    "mw": _rest["mw"],
                    "max_mw": _rest["mw"],
                    "lon": _rest["longitude"],
                    "lat": _rest["latitude"],
                    "in_atlas_site": True,
                    "atlas_site_id": _rest["site_id"],
                    "operational": _rest["operational"],
                }
            ),
        ],
        ignore_index=True,
    )
    campuses["gigawatt"] = campuses["max_mw"] >= 1000
    assert campuses["lon"].between(-125, -66).all() and campuses["lat"].between(24, 50).all(), "campus outside CONUS"
    campuses = gpd.GeoDataFrame(
        campuses, geometry=gpd.points_from_xy(campuses["lon"], campuses["lat"]), crs=4326
    ).to_crs(5070)
    _alt = atlas.set_index("site_id").loc[campuses["atlas_site_id"].where(campuses["in_atlas_site"]).dropna()]
    atlas_points = gpd.GeoSeries(
        gpd.points_from_xy(_alt["longitude"], _alt["latitude"]),
        index=campuses.index[campuses["in_atlas_site"] & campuses["atlas_site_id"].notna()],
        crs=4326,
    ).to_crs(5070)
    print(
        f"{len(campuses)} campuses: {int((campuses['list'] == 'Malachi').sum())} from Malachi, "
        f"{int((campuses['list'] == 'Atlas').sum())} Atlas-only; {int(campuses['gigawatt'].sum())} gigawatt"
    )
    return atlas_points, campuses


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 3. Distance to the nearest 230 kV+ and 345 kV+ substation

    Substations come from `us-substations-verified/dataset/us_substations.csv` on `main`: 71,625 points, HIFLD Next
    line ends reconciled with OpenStreetMap, each with the highest voltage either source records. Distances are
    straight-line, measured in CONUS Albers (EPSG:5070), whose scale error is about 1% or less, too small to move a
    campus across a 1, 5 or 10-mile line in all but edge cases. We also measure against any substation of
    100 kV or more, since much of the Midwest and South transmits at 115, 138 and 161 kV.
    """)
    return


@app.cell
def _(METRE_PER_MILE, Path, campuses, gpd, pd):
    _subs = pd.read_csv(Path(__file__).parent.parent / "us-substations-verified/dataset/us_substations.csv")
    _subs = gpd.GeoDataFrame(_subs, geometry=gpd.points_from_xy(_subs["lon"], _subs["lat"]), crs=4326).to_crs(5070)
    print(
        f"{len(_subs):,} substations; {(_subs['max_kv'] >= 230).sum():,} at 230 kV+, "
        f"{(_subs['max_kv'] >= 345).sum():,} at 345 kV+"
    )

    def nearest_miles(points: gpd.GeoSeries, targets: gpd.GeoDataFrame) -> pd.Series:
        joined = gpd.sjoin_nearest(gpd.GeoDataFrame(geometry=points), targets[["geometry"]], distance_col="m")
        return joined[~joined.index.duplicated()]["m"] / METRE_PER_MILE

    nearest_subs_230 = _subs[_subs["max_kv"] >= 230]
    distances = pd.DataFrame(
        {
            "sub230_mi": nearest_miles(campuses.geometry, nearest_subs_230),
            "sub345_mi": nearest_miles(campuses.geometry, _subs[_subs["max_kv"] >= 345]),
            "sub100_mi": nearest_miles(campuses.geometry, _subs[_subs["max_kv"] >= 100]),
        }
    )
    return distances, nearest_miles, nearest_subs_230


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 4. Distance to the nearest 230 kV+ line, HIFLD 2023 against OpenStreetMap

    **HIFLD Next Transmission Lines v1.0.0**, the preserved copy of HIFLD's last public layer (most lines dated
    2023): every line with `VOLTAGE` ≥ 230. **GMWID `power_line`**, GeoMermaids' weekly OpenStreetMap build: US
    `line` and `cable` features with `voltage_kv` ≥ 230 that are active. GMWID serves only its latest build, so the
    run records the build it read (its ETag) rather than the 2026-10-11 build the issue names. DuckDB reads only the
    US 230 kV+ rows over HTTP instead of the whole 490 MB file.
    """)
    return


@app.cell
def _(DATA, campuses, distances, download, duckdb, gpd, nearest_miles, pd, requests):
    _hifld = download(
        "https://storage.googleapis.com/hifld-next-datasets-prod/hifld/transmission-lines-1/transmission-lines-1/"
        "v1.0.0/geoparquet/transmission-lines-1.parquet",
        "hifld_transmission_lines.parquet",
    )
    _gmwid_url = "https://parquetry.geomermaids.com/gmwid/latest/power_line.parquet"
    _head = requests.head(_gmwid_url, timeout=60)
    assert _head.ok, f"GMWID power_line: HTTP {_head.status_code}"
    gmwid_etag = _head.headers.get("etag", "unknown")
    _osm_path = DATA / "gmwid_us_power_line_230kv.parquet"
    _con = duckdb.connect()
    _con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
    if not _osm_path.exists():
        _con.sql(
            f"COPY (SELECT osm_id, type, voltage_kv, ST_AsWKB(geometry) AS wkb FROM read_parquet('{_gmwid_url}') "
            "WHERE country = 'US' AND voltage_kv >= 230 AND type IN ('line', 'cable') AND lifecycle = 'active') "
            f"TO '{_osm_path}' (FORMAT parquet)"
        )
    _osm = _con.sql(f"SELECT * FROM read_parquet('{_osm_path}')").df()
    _osm = gpd.GeoDataFrame(_osm, geometry=gpd.GeoSeries.from_wkb(_osm["wkb"].map(bytes)), crs=4326).to_crs(5070)
    _hl = gpd.read_parquet(_hifld, columns=["VOLTAGE", "geometry"])
    _hl = _hl[_hl["VOLTAGE"] >= 230].to_crs(5070)
    print(f"Lines at 230 kV+: HIFLD {len(_hl):,}; OpenStreetMap (GMWID, ETag {gmwid_etag}) {len(_osm):,}")
    lines = pd.DataFrame(
        {
            "line230_hifld_mi": nearest_miles(campuses.geometry, _hl),
            "line230_osm_mi": nearest_miles(campuses.geometry, _osm),
        }
    )
    measured = campuses.join(distances).join(lines)
    return gmwid_etag, measured


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 5. Counts: how many campuses have no high-voltage substation nearby?
    """)
    return


@app.cell
def _(BANDS, measured, pd):
    def none_within(frame: pd.DataFrame, column: str) -> dict[str, int]:
        return {f"none within {b} mi": int((frame[column] > b).sum()) for b in BANDS}

    _groups = {
        "Malachi site-located": measured[measured["list"] == "Malachi"],
        "Atlas site-located": measured[measured["in_atlas_site"]],
        "All campuses": measured,
        "Gigawatt campuses": measured[measured["gigawatt"]],
        "Not yet operational": measured[~measured["operational"]],
    }
    counts = pd.DataFrame(
        [
            {"campuses": name, "n": len(g), "voltage": label, **none_within(g, col)}
            for name, g in _groups.items()
            for label, col in [
                ("230 kV+", "sub230_mi"),
                ("345 kV+", "sub345_mi"),
                ("100 kV+", "sub100_mi"),
            ]
        ]
    )
    counts
    return (counts,)


@app.cell
def _(measured, mo):
    _far = measured[measured["sub230_mi"] > 5]
    _known = measured.dropna(subset=["mw"])
    far_mw = float(_far["mw"].sum())
    _near_line = _far[_far["line230_osm_mi"] <= 1]
    _gw = measured[measured["gigawatt"]]
    mo.md(
        f"""
    **{len(_far)}** of {len(measured)} campuses ({len(_far) / len(measured):.0%}) have no 230 kV+ substation within
    5 miles. They plan **{far_mw:,.0f} MW** of the {_known["mw"].sum():,.0f} MW with a known figure
    ({far_mw / _known["mw"].sum():.0%}). Among the {len(_gw)} gigawatt campuses,
    **{int((_gw["sub230_mi"] > 5).sum())}** have none within 5 miles.

    Distance to a substation isn't distance to the grid: **{len(_near_line)}** of the far campuses have a 230 kV+
    OpenStreetMap line within 1 mile, so what they need is a new substation tapped into an existing line, not miles
    of new line. Median distance to a 230 kV+ substation: {measured["sub230_mi"].median():.1f} miles (all campuses),
    {_gw["sub230_mi"].median():.1f} miles (gigawatt).
    """
    )
    return (far_mw,)


@app.cell
def _(OUT, measured):
    import matplotlib.pyplot as plt

    _fig, _ax = plt.subplots(figsize=(8, 4))
    _groups = [("All campuses", measured), ("Gigawatt", measured[measured["gigawatt"]])]
    for _label, _frame in _groups:
        _miles = _frame["sub230_mi"].sort_values().clip(upper=30)
        _ax.step(_miles, [(i + 1) / len(_miles) for i in range(len(_miles))], where="post", label=_label)
    for _band in [1, 5, 10]:
        _ax.axvline(_band, color="grey", linewidth=0.5)
    _ax.set_xlabel("miles to nearest 230 kV+ substation (capped at 30)")
    _ax.set_ylabel("share of campuses within")
    _ax.legend()
    _fig.tight_layout()
    _fig.savefig(OUT / "distance_to_230kv_substation.png", dpi=150)
    _ax
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 6. Does the line layer change the answer?

    Each campus gets a band (≤1, 1–5, 5–10, >10 miles) for distance to the nearest 230 kV+ line in each layer. A
    campus "changes band" when HIFLD 2023 and OpenStreetMap put it in different bands. We also scrape the
    distance Malachi.Energy publishes on each project page (computed from HIFLD lines "current to September 2023")
    to check that our HIFLD measurement reproduces theirs.
    """)
    return


@app.cell
def _(BANDS, html, measured, pd, re, requests, time):
    def band(miles: pd.Series) -> pd.Series:
        return pd.cut(miles, [0, *BANDS, float("inf")], labels=["≤1", "1–5", "5–10", ">10"], include_lowest=True)

    _hb, _ob = band(measured["line230_hifld_mi"]), band(measured["line230_osm_mi"])
    band_change = pd.crosstab(_hb.rename("HIFLD 2023"), _ob.rename("OpenStreetMap"))
    changed = measured.assign(hifld_band=_hb, osm_band=_ob)[_hb != _ob]

    def malachi_published_miles(url: str) -> float | None:
        for attempt in range(3):
            response = requests.get(url, timeout=60, headers={"User-Agent": "fulton-ring-spike"})
            if response.ok:
                text = html.unescape(re.sub(r"<[^>]+>", " ", response.text))
                found = re.search(r"campus sits (under )?([\d.]+) miles? from the nearest \d+ kV", text)
                return None if found is None else float(found.group(2)) / (2 if found.group(1) else 1)
            time.sleep(2**attempt)
        raise RuntimeError(f"{url}: no page after 3 tries")

    print(band_change.to_string())
    print(f"{len(changed)} of {len(measured)} campuses change band between HIFLD 2023 and OpenStreetMap lines")
    return band, changed, malachi_published_miles


@app.cell
def _(DATA, malachi_published_miles, measured, pd):
    _cache = DATA / "malachi_published_line_miles.csv"
    _m = measured[measured["list"] == "Malachi"]
    if not _cache.exists():
        _urls = pd.read_csv(DATA / "malachi_mega-projects.csv").set_index("name")["url"]
        pd.DataFrame(
            {"campus": _m["campus"], "published_mi": [malachi_published_miles(_urls[c]) for c in _m["campus"]]}
        ).to_csv(_cache, index=False)
    _pub = pd.read_csv(_cache).set_index("campus")["published_mi"]
    reproduce = _m.assign(published_mi=_m["campus"].map(_pub))
    reproduce["diff_mi"] = (reproduce["line230_hifld_mi"] - reproduce["published_mi"]).abs()
    _ok = reproduce["diff_mi"] <= 0.15 + 0.05 * reproduce["published_mi"]
    print(
        f"Malachi's published HIFLD distance parsed for {reproduce['published_mi'].notna().sum()} of {len(reproduce)}; "
        f"ours agrees within rounding for {int(_ok.sum())}; median difference {reproduce['diff_mi'].median():.2f} mi"
    )
    reproduce[~_ok][["campus", "published_mi", "line230_hifld_mi", "line230_osm_mi", "sub230_mi"]].round(1)
    return (reproduce,)


@app.cell
def _(atlas_points, band, measured, nearest_subs_230, nearest_miles):
    _matched = measured.loc[atlas_points.index]
    _matched = _matched[_matched["list"] == "Malachi"]
    _from_atlas = nearest_miles(atlas_points.loc[_matched.index], nearest_subs_230)
    location_band_moves = int((band(_matched["sub230_mi"]) != band(_from_atlas)).sum())
    print(
        f"{len(_matched)} campuses are site-located in both lists; measuring from the Atlas coordinate instead of "
        f"Malachi's moves {location_band_moves} of them to a different 230 kV+ substation band"
    )
    return (location_band_moves,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 7. Hand check of the far campuses

    For every campus more than 5 miles from a 230 kV+ substation we looked at Esri World Imagery (current at the
    time of the check) around the campus and along the nearest lines, for a substation or switchyard under
    construction or one the datasets miss, and searched for a utility filing that names a new substation for the
    campus. The labels are in `hand_check.csv` (campus name, what the imagery shows, label, note, link; no
    coordinates). `hand_check_chips.py` redraws the images we looked at. The imagery is undated and often a year or
    more old, so "undeveloped" means only that it predates construction.

    | label | meaning |
    |---|---|
    | `new_hv_substation_in_filing` | a filing or utility names a new 230 kV+ substation or switching station for it |
    | `new_hv_substation_customer_unnamed` | a new 230 kV+ substation is planned nearby for an unnamed large load |
    | `site_plan_substation_only` | the developer or a site plan says "substation", with no voltage or utility project |
    | `new_lower_voltage_substation`, `new_lower_voltage_tie` | the named new grid work is below 230 kV |
    | `on_site_gas` | the campus is permitted or described as powered by its own gas generation |
    | `existing_lower_voltage` | an existing building already served from a 100-229 kV substation |
    | `nothing_found` | no substation in the imagery and no filing found (or not searched) |
    """)
    return


@app.cell
def _(DATA, duckdb, gpd, measured, nearest_miles):
    _far = measured[measured["sub230_mi"] > 5]
    # Coordinates stay in data/ (not committed): hand_check_chips.py reads them to draw the imagery.
    _far[["campus", "lon", "lat", "sub230_mi"]].to_csv(DATA / "far_campuses_private.csv", index=False)
    _con = duckdb.connect()
    _con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
    _building = _con.sql(
        "SELECT osm_id, lifecycle, voltage_kv, ST_X(ST_Centroid(geometry)) AS lon, ST_Y(ST_Centroid(geometry)) AS lat "
        "FROM read_parquet('https://parquetry.geomermaids.com/gmwid/latest/power_substation.parquet') "
        "WHERE country = 'US' AND lifecycle IN ('construction', 'proposed')"
    ).df()
    _building = gpd.GeoDataFrame(
        _building, geometry=gpd.points_from_xy(_building["lon"], _building["lat"]), crs=4326
    ).to_crs(5070)
    _mi = nearest_miles(_far.geometry, _building)
    print(
        f"OpenStreetMap has {len(_building)} US substations tagged under construction or proposed; "
        f"{int((_mi <= 5).sum())} of the {len(_far)} far campuses have one within 5 miles"
    )
    return


@app.cell
def _(Path, measured, pd):
    _path = Path(__file__).parent / "hand_check.csv"
    _far = measured[measured["sub230_mi"] > 5][["campus", "list", "mw", "sub230_mi", "line230_osm_mi"]]
    hand = pd.read_csv(_path) if _path.exists() else pd.DataFrame(columns=["campus", "label", "note", "link"])
    _missing = sorted(set(_far["campus"]) - set(hand["campus"]))
    print(f"{len(_far)} far campuses; {len(_far) - len(_missing)} hand-checked; not yet checked: {_missing}")
    _labelled = _far.merge(hand, on="campus").merge(measured[["campus", "gigawatt"]], on="campus")
    hand_summary = _labelled["label"].value_counts()
    pd.crosstab(_labelled["label"], _labelled["gigawatt"].map({True: "gigawatt", False: "smaller or unknown MW"}))
    return (hand_summary,)


@app.cell
def _(
    OUT,
    changed,
    counts,
    far_mw,
    gmwid_etag,
    hand_summary,
    json,
    location_band_moves,
    measured,
    reconcile,
    reproduce,
    started,
    time,
):
    measured.drop(columns=["geometry", "lon", "lat", "atlas_site_id"]).round(2).to_csv(
        OUT / "campus_distances.csv", index=False
    )
    counts.to_csv(OUT / "counts.csv", index=False)
    summary = {
        "reconcile": reconcile,
        "campuses": len(measured),
        "far_230kv_5mi": int((measured["sub230_mi"] > 5).sum()),
        "planned_mw_far_230kv_5mi": far_mw,
        "line_band_changes_hifld_vs_osm": len(changed),
        "substation_band_changes_atlas_vs_malachi_coordinate": location_band_moves,
        "malachi_published_distance_reproduced": int(
            (reproduce["diff_mi"] <= 0.15 + 0.05 * reproduce["published_mi"]).sum()
        ),
        "hand_check": hand_summary.to_dict(),
        "gmwid_power_line_etag": gmwid_etag,
        "run_seconds": round(time.time() - started),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## 8. What didn't work, and what this doesn't show

    - **Matching the lists by nearest point** paired the wrong campuses (Meta Prometheus with a Google campus,
      AVAIO Leo with a TierPoint building). Name matching fixed it, but it is a heuristic; every pair is printed.
    - **The Atlas has few capacity figures**: 23 of 130 site-located US sites, so planned MW beyond 5 miles is
      mostly Malachi's numbers, and Atlas-only campuses without a figure count as zero MW.
    - **GMWID's 2026-10-11 build is gone**; only the latest build is served, so the OpenStreetMap line numbers will
      drift from run to run. The ETag of the build used is in `outputs/summary.json`.
    - **OpenStreetMap's construction tags** don't help: 35 US substations are tagged under construction or
      proposed, none within 5 miles of a far campus, while filings name new substations for at least five.
    - **Distance is not capacity.** A substation next door may have no headroom; a far campus may already have a
      utility project under way. Straight-line distance also ignores routing.
    - **230 kV is a regional threshold.** Much of the Midwest and South transmits at 115-161 kV: with any
      100 kV+ substation, almost every campus is within 5 miles.
    """)
    return


if __name__ == "__main__":
    app.run()

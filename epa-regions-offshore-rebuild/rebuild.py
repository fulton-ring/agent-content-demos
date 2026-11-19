import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(r"""
    # Can we rebuild EPA's regions-with-offshore-waters layer from current sources?

    HIFLD Next ships an "EPA Region Boundaries with Exclusive Economic Zone" layer. Its pipeline reads
    `geodata.epa.gov/.../OEI/EPA_Locations/MapServer/4`, an EPA service built in 2012 from 2011 TIGER/Line
    states and NOAA's maritime boundaries. EPA no longer updates it, and publishes no current version that
    reaches offshore. EPA does maintain the onshore regions: "U.S. EPA Regions (DOC & EPA 2023)".

    The question: if we join the 2023 onshore regions to NOAA's current maritime limits and split the
    offshore waters between regions by a simple, written-down rule, how close do we get to the 2012 layer?

    Steps:

    1. Download the three public inputs, plus BOEM's offshore administrative boundaries for one of the rules.
    2. Build a current US EEZ polygon from NOAA's maritime limit lines.
    3. Measure how the 2012 layer drew its region lines out to sea.
    4. Try four rules for splitting the offshore waters and score each per region against 2012 (IoU).
    5. Write the closest rule's layer as GeoParquet, labelled as ours, not EPA's.
    """)
    return (mo,)


@app.cell
def _():
    import json
    import os
    import time
    import zipfile
    from pathlib import Path

    import geopandas as gpd
    import matplotlib
    import numpy as np
    import pandas as pd
    import requests
    import shapely
    import shapely.affinity
    from shapely.ops import polygonize, unary_union

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("DATA_DIR", HERE / "data"))
    OUT = Path(os.environ.get("OUTPUT_DIR", HERE / "outputs"))
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    STARTED = time.time()
    # Equal-area projection centred on the antimeridian, for areas anywhere in the US EEZ.
    EQUAL_AREA = "+proj=cea +lon_0=180 +datum=WGS84"
    NM = 1852.0
    return (
        DATA,
        EQUAL_AREA,
        NM,
        OUT,
        STARTED,
        gpd,
        json,
        np,
        pd,
        plt,
        polygonize,
        requests,
        shapely,
        time,
        unary_union,
        zipfile,
    )


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Inputs

    All four are public and downloaded at run time into `data/` (git-ignored). For each we record where it
    came from, how current it is and its licence, read from the source itself.
    """)
    return


@app.cell
def _(DATA, json, requests, time, zipfile):
    EPA_2012 = "https://geodata.epa.gov/arcgis/rest/services/OEI/EPA_Locations/MapServer/4"
    EPA_2023 = (
        "https://services.arcgis.com/cJ9YHowT8TU7DUyn/arcgis/rest/services/"
        "US_EPA_Regions__DOC___EPA_2023_/FeatureServer/13"
    )
    EPA_2023_ITEM = "https://www.arcgis.com/sharing/rest/content/items/21dfeddb55984d9c957ffad98e7da94e"
    NOAA_ZIP = "https://maritimeboundaries.noaa.gov/downloads/USMaritimeLimitsAndBoundariesSHP.zip"
    BOEM = (
        "https://www.boem.gov/sites/default/files/uploadedFiles/BOEM/Oil_and_Gas_Energy_Program/"
        "Mapping_and_Data/Administrative_Boundaries/"
    )
    BOEM_ZIPS = ["Atl_admn.zip", "gom_admn.zip", "pac_admn.zip"]

    def fetch(url: str, params: dict | None = None) -> requests.Response:
        """GET with a fixed number of retries and backoff; raises on a final failure."""
        for attempt in range(4):
            try:
                resp = requests.get(url, params=params, timeout=120)
                resp.raise_for_status()
                return resp
            except requests.RequestException:
                if attempt == 3:
                    raise
                time.sleep(2**attempt)
        raise AssertionError("unreachable")

    def download_layer(url: str, name: str) -> dict:
        path = DATA / f"{name}.geojson"
        if not path.exists():
            resp = fetch(
                f"{url}/query",
                {"where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson"},
            )
            body = resp.json()
            assert "features" in body and not body.get("exceededTransferLimit"), f"{name}: incomplete download"
            path.write_text(resp.text)
        return fetch(url, {"f": "json"}).json()

    def download_zip(url: str, name: str) -> dict:
        folder = DATA / name
        resp = requests.head(url, timeout=60)
        if not folder.exists():
            zpath = DATA / f"{name}.zip"
            zpath.write_bytes(fetch(url).content)
            with zipfile.ZipFile(zpath) as zf:
                zf.extractall(folder)
        return {"last_modified": resp.headers.get("Last-Modified", "unknown")}

    meta_2012 = download_layer(EPA_2012, "epa_regions_2012")
    meta_2023 = download_layer(EPA_2023, "epa_regions_2023")
    item_2023 = fetch(EPA_2023_ITEM, {"f": "json"}).json()
    noaa_http = download_zip(NOAA_ZIP, "noaa_maritime")
    boem_http = {z: download_zip(BOEM + z, z.removesuffix(".zip")) for z in BOEM_ZIPS}
    print(json.dumps({"noaa": noaa_http, "boem": boem_http}, indent=1))
    return EPA_2012, EPA_2023, NOAA_ZIP, item_2023, meta_2012, meta_2023, noaa_http


@app.cell
def _(DATA, gpd, shapely):
    old = gpd.read_file(DATA / "epa_regions_2012.geojson")
    old["region"] = old["EPAREGION"].str.replace("Region ", "").astype(int)
    new = gpd.read_file(DATA / "epa_regions_2023.geojson")
    new["region"] = new["EPA_REGION"].astype(int)
    noaa = gpd.read_file(next((DATA / "noaa_maritime").rglob("*.shp")))
    boem = gpd.pd.concat(
        [gpd.read_file(p).to_crs(4326)[["geometry"]] for p in sorted(DATA.glob("*_admn/*.shp"))],
        ignore_index=True,
    )
    boem["geometry"] = shapely.force_2d(boem.geometry)
    assert sorted(old.region) == sorted(new.region) == list(range(1, 11)), "expected regions 1-10 in both"
    return boem, new, noaa, old


@app.cell
def _(
    EPA_2012,
    EPA_2023,
    NOAA_ZIP,
    item_2023,
    meta_2012,
    meta_2023,
    mo,
    noaa,
    noaa_http,
    pd,
):
    def ms_date(ms: int | None) -> str:
        return pd.Timestamp(ms, unit="ms").date().isoformat() if ms else "not stated"

    sources = pd.DataFrame(
        [
            {
                "input": "EPA regions with EEZ (2012, reference)",
                "url": EPA_2012,
                "current as of": "built from 2011 TIGER/Line; " + meta_2012["description"].split("based on")[1][:60],
                "licence": "US Government work (EPA)",
            },
            {
                "input": "U.S. EPA Regions (DOC & EPA 2023), onshore",
                "url": EPA_2023,
                "current as of": "data last edited "
                + ms_date(meta_2023.get("editingInfo", {}).get("dataLastEditDate")),
                "licence": "EPA Data Licensing Agreement, public use"
                if "public" in (item_2023.get("licenseInfo") or "")
                else "see item page",
            },
            {
                "input": "NOAA OCS US Maritime Limits and Boundaries",
                "url": NOAA_ZIP,
                "current as of": f"newest line published {noaa.PUB_DATE.max():%Y-%m-%d}; "
                f"file dated {noaa_http['last_modified']}",
                "licence": "US Government work (NOAA), public domain",
            },
        ]
    )
    print(sources.to_string())
    mo.ui.table(sources)
    return


@app.cell
def _(mo):
    mo.md(r"""
    NOAA publishes the maritime limits only as **lines** (territorial sea, contiguous zone, EEZ limit,
    treaty boundaries), not as a polygon. The newest line was published in 2013 and the download is dated
    2020: public and authoritative, but not updated often.

    ## 2. Build a current EEZ polygon from NOAA's lines

    We union NOAA's lines with the 2023 coastline (buffered by 0.02°, about 2 km, so lines that stop at the
    shore meet it) and turn the network into faces. Three fixes were needed to get closed faces:

    - shift longitudes to 0–360°, because NOAA cuts the Aleutian and Hawaiian lines at the antimeridian;
    - snap coordinates to a 1e-5° grid (about 1 m), because many line ends miss each other by ~1e-8°
      (a 1e-6° grid still left southern Alaska open);
    - drop faces more than 195 nm from any US territorial-sea line (no EEZ point is more than 188 nm beyond
      it): NOAA's lines also enclose high-seas pockets, the Bering Sea "Donut Hole" and an Arctic sliver north
      of the US–Russia line. We measure from the 12 nm line, not from land, because the 2023 regions have no
      land for the Pacific Remote Islands (Wake, Johnston, Palmyra, Jarvis, Howland and Baker).
    """)
    return


@app.cell
def _(EQUAL_AREA, NM, gpd, new, noaa, np, polygonize, shapely, unary_union):
    def to_360(geom: shapely.Geometry) -> shapely.Geometry:
        return shapely.transform(
            geom,
            lambda xy: np.column_stack([np.where(xy[:, 0] < 0, xy[:, 0] + 360, xy[:, 0]), xy[:, 1]]),
        )

    def km2(geom: shapely.Geometry) -> float:
        return float(gpd.GeoSeries([geom], crs=4326).to_crs(EQUAL_AREA).area.iloc[0]) / 1e6

    land_by_region = {r: shapely.make_valid(to_360(g)) for r, g in zip(new.region, new.geometry, strict=True)}
    land = unary_union(list(land_by_region.values()))
    pad = land.buffer(0.02)
    _lines = shapely.set_precision(unary_union([to_360(g) for g in noaa.geometry]), 1e-5)
    _faces = gpd.GeoDataFrame(geometry=list(polygonize(unary_union([_lines, pad.boundary]))), crs=4326)
    _faces = _faces[~_faces.representative_point().within(pad)].copy()

    _territorial_sea = shapely.set_precision(unary_union([to_360(g) for g in noaa[noaa.TS == 1].geometry]), 1e-5)

    def nm_to_territorial_sea(point: shapely.Point) -> float:
        """Geodesic distance to the nearest US 12 nm line, measured in a projection centred on the point."""
        lon, lat = point.x, point.y
        near = _territorial_sea.intersection(shapely.box(lon - 20, max(lat - 10, -90), lon + 20, min(lat + 10, 90)))
        if near.is_empty:
            return float("inf")
        aeqd = f"+proj=aeqd +lat_0={lat} +lon_0={lon} +datum=WGS84"
        local = gpd.GeoSeries([point, near], crs=4326).to_crs(aeqd)
        return float(local.iloc[0].distance(local.iloc[1])) / NM

    # A point of the EEZ is at most 200 - 12 = 188 nm beyond the territorial sea; allow a little slack.
    _faces["nm"] = [nm_to_territorial_sea(p) for p in _faces.representative_point()]
    high_seas = _faces[_faces.nm > 195]
    _sea = unary_union(list(_faces[_faces.nm <= 195].geometry))
    # Close the 2 km gap between the faces and the true coast, without spilling along land borders.
    offshore = unary_union([_sea, _sea.buffer(0.03).intersection(pad)]).difference(land)
    eez = unary_union([offshore, land])
    print(
        f"EEZ faces kept {int((_faces.nm <= 195).sum())}, dropped as high seas {len(high_seas)} "
        f"({sum(km2(g) for g in high_seas.geometry):,.0f} km2)"
    )
    print(f"US offshore waters beyond 2023 state lines: {km2(offshore):,.0f} km2")
    return eez, km2, land, land_by_region, offshore, to_360


@app.cell
def _(eez, km2, old, shapely, to_360, unary_union):
    old_by_region = {r: shapely.make_valid(to_360(g)) for r, g in zip(old.region, old.geometry, strict=True)}
    old_all = unary_union(list(old_by_region.values()))
    extent_check = {
        "2012 area missing from rebuilt EEZ + land (km2)": round(km2(old_all.difference(eez))),
        "rebuilt area not in 2012 (km2)": round(km2(eez.difference(old_all))),
        "IoU of outer extent": round(km2(old_all.intersection(eez)) / km2(old_all.union(eez)), 4),
    }
    print(extent_check)
    return extent_check, old_by_region


@app.cell
def _(extent_check, mo):
    mo.md(f"""
    The rebuilt outer extent matches 2012 almost exactly: IoU **{extent_check["IoU of outer extent"]}**,
    with {extent_check["2012 area missing from rebuilt EEZ + land (km2)"]:,} km² of the 2012 layer missing
    and {extent_check["rebuilt area not in 2012 (km2)"]:,} km² new. So whatever differs below comes from how
    the offshore waters are split between regions, not from the EEZ edge.

    ## 3. How did the 2012 layer split the regions at sea?

    For each pair of neighbouring coastal regions, take the line the two 2012 polygons share and keep the
    part offshore of the 2023 coast.
    """)
    return


@app.cell
def _(land, old_by_region, pd, shapely):
    PAIRS = [(1, 2), (2, 3), (3, 4), (4, 6), (9, 10)]
    old_splits = {}
    _rows = []
    for _a, _b in PAIRS:
        _shared = old_by_region[_a].boundary.intersection(old_by_region[_b].boundary).difference(land.buffer(0.01))
        _parts = [g for g in getattr(_shared, "geoms", [_shared]) if g.length > 0.05]
        _seg = max(_parts, key=lambda g: g.length)
        old_splits[(_a, _b)] = _seg
        (_x0, _y0), (_x1, _y1) = _seg.coords[0], _seg.coords[-1]
        _rows.append(
            {
                "regions": f"{_a}/{_b}",
                "vertices": len(_seg.coords),
                "from": f"{_x0 - 360:.3f}, {_y0:.3f}",
                "to": f"{_x1 - 360:.3f}, {_y1:.3f}",
                "latitude change (deg)": round(_y1 - _y0, 3),
                "bearing": "due east/west" if abs(_y1 - _y0) < 0.05 else "oblique",
            }
        )
    old_split_table = pd.DataFrame(_rows)
    print(old_split_table.to_string())
    old_split_table
    return PAIRS, old_splits


@app.cell
def _(mo):
    mo.md(r"""
    Every 2012 split is a **single straight segment** (two vertices) from the coast to the EEZ edge. Three
    run due east or west along a parallel: Regions 2/3 at 38.84°N (Delaware Bay mouth), 3/4 at 36.55°N
    (the Virginia–North Carolina line) and 9/10 at 42°N (California–Oregon). Two are oblique: 1/2 heads
    east-south-east from Block Island Sound, and 4/6 heads south-south-east from the Louisiana–Mississippi
    line. EEZ metadata names no rule for them.

    We also checked BOEM's offshore administrative boundaries (lateral lines between states, computed from
    the national baseline): they are many-vertex lines and match none of the 2012 segments except near
    36.55°N, where the Virginia–North Carolina line happens to run almost due east.

    ## 4. Four rules for splitting the offshore waters

    Every rule starts from the same offshore area (rebuilt EEZ minus 2023 land). Offshore pieces that touch
    only one region's land go to that region (Alaska, Hawaii, Puerto Rico, the Pacific territories). Pieces
    near no region's land (the Pacific Remote Islands, which Census doesn't map as a state or territory) go to
    the nearest region. Only the two pieces shared by several regions, the Atlantic–Gulf coast and the
    Pacific coast of the lower 48, need a rule:

    - **A. Nearest coast:** each point of sea goes to the region whose coast is nearest (an equidistance
      split, as in maritime law).
    - **B. Due seaward:** extend the onshore region line from where it meets the sea due east (Atlantic),
      due west (Pacific) or due south (Gulf).
    - **C. BOEM lines:** cut along BOEM's state-to-state offshore administrative boundaries.
    - **D. Keep EPA's 2012 lines:** reuse the five straight segments measured above as cutters on the
      current EEZ and current coast.

    For B, C and D the cut pieces go to the region whose coast each piece touches most. The BOEM lines and
    the 2012 segments are stretched 0.3° past each end so they reach the current coast and EEZ edge.
    """)
    return


@app.cell
def _(EQUAL_AREA, gpd, land_by_region, offshore, polygonize, shapely, unary_union):
    def pieces_by_coast(area: shapely.Geometry, cutters: list[shapely.Geometry]) -> dict[int, shapely.Geometry]:
        """Cut `area` along `cutters` and give each piece to the region whose coast it touches most."""
        _edges = unary_union([area.boundary, *[c.intersection(area.buffer(1e-6)) for c in cutters]])
        _pieces = [p for p in polygonize(_edges) if area.contains(p.representative_point())]
        _out: dict[int, list[shapely.Geometry]] = {}
        for _p in _pieces:
            _ring = _p.boundary.buffer(0.03)
            _touch = {r: _ring.intersection(g.boundary).length for r, g in land_by_region.items()}
            _best = max(_touch, key=lambda r: _touch[r])
            if _touch[_best] == 0:
                _best = min(land_by_region, key=lambda r: land_by_region[r].distance(_p))
            _out.setdefault(_best, []).append(_p)
        return {r: unary_union(v) for r, v in _out.items()}

    _parts = list(getattr(offshore, "geoms", [offshore]))
    _comp = gpd.GeoDataFrame(geometry=_parts, crs=4326)
    _comp["near_regions"] = [
        tuple(r for r, g in land_by_region.items() if g.buffer(0.03).intersects(p)) for p in _comp.geometry
    ]
    single = {}
    for _p, _t in zip(_comp.geometry, _comp.near_regions, strict=True):
        if len(_t) > 1:
            continue
        _r = _t[0] if _t else min(land_by_region, key=lambda r: land_by_region[r].distance(_p))
        single.setdefault(_r, []).append(_p)
    single = {r: unary_union(v) for r, v in single.items()}
    shared = unary_union([p for p, t in zip(_comp.geometry, _comp.near_regions, strict=True) if len(t) > 1])
    _shared_regions = sorted({r for t in _comp.near_regions if len(t) > 1 for r in t})
    print("regions sharing a coast piece:", _shared_regions)
    print(
        "shared offshore km2:",
        round(float(gpd.GeoSeries([shared], crs=4326).to_crs(EQUAL_AREA).area.iloc[0]) / 1e6),
    )
    return pieces_by_coast, shared, single


@app.cell
def _(gpd, land_by_region, np, shapely, shared, to_360, unary_union):
    # Rule A: Voronoi cells (equal-area US projection) around points every 2 km along each region's coast
    # that faces the shared waters.
    _crs = "EPSG:5070"
    _coast_pts, _labels = [], []
    _near = shared.buffer(0.05)
    for _r, _g in land_by_region.items():
        _coast = _g.boundary.intersection(_near)
        if _coast.is_empty:
            continue
        _c = gpd.GeoSeries([_coast], crs=4326).to_crs(_crs).iloc[0]
        for _line in getattr(_c, "geoms", [_c]):
            for _d in np.arange(0, _line.length, 2000.0):
                _coast_pts.append(_line.interpolate(_d))
                _labels.append(_r)
    _cells = shapely.voronoi_polygons(shapely.MultiPoint(_coast_pts), ordered=True)
    _shared_proj = gpd.GeoSeries([shared], crs=4326).to_crs(_crs).iloc[0]
    _cells_gdf = gpd.GeoDataFrame({"region": _labels}, geometry=list(_cells.geoms), crs=_crs)
    rule_a = {}
    for _r, _grp in _cells_gdf.groupby("region"):
        _piece = shapely.make_valid(unary_union(list(_grp.geometry))).intersection(_shared_proj)
        if not _piece.is_empty:
            rule_a[int(_r)] = to_360(gpd.GeoSeries([_piece], crs=_crs).to_crs(4326).iloc[0]).intersection(shared)
    print("rule A coast points:", len(_coast_pts))
    return (rule_a,)


@app.cell
def _(PAIRS, boem, land_by_region, old_splits, pieces_by_coast, shapely, shared, to_360):
    # Rule B: from the seaward end of each onshore region line, a ray due east, west or south.
    _direction = {
        (1, 2): (1, 0),
        (2, 3): (1, 0),
        (3, 4): (1, 0),
        (4, 6): (0, -1),
        (9, 10): (-1, 0),
    }
    _rays = []
    for _a, _b in PAIRS:
        _line = land_by_region[_a].boundary.intersection(land_by_region[_b].boundary)
        _ends = [shapely.Point(c) for g in getattr(_line, "geoms", [_line]) for c in (g.coords[0], g.coords[-1])]
        _start = min(_ends, key=shared.distance)
        _dx, _dy = _direction[(_a, _b)]
        _rays.append(
            shapely.LineString(
                [
                    (_start.x - _dx * 0.05, _start.y - _dy * 0.05),
                    (_start.x + _dx * 15, _start.y + _dy * 15),
                ]
            )
        )
    rule_b = pieces_by_coast(shared, _rays)

    def stretch(line: shapely.LineString, deg: float = 0.3) -> shapely.LineString:
        """Extend a line `deg` degrees past both ends along its end segments, so it crosses coast and EEZ edge."""
        _xy = list(line.coords)

        def _past(a: tuple, b: tuple) -> tuple:
            _len = ((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2) ** 0.5
            return (
                b[0] + deg * (b[0] - a[0]) / _len,
                b[1] + deg * (b[1] - a[1]) / _len,
            )

        return shapely.LineString([_past(_xy[1], _xy[0]), *_xy, _past(_xy[-2], _xy[-1])])

    # Rule C: BOEM's state-to-state administrative boundaries, stretched like rule D's segments.
    rule_c = pieces_by_coast(shared, [stretch(to_360(g)) for g in boem.geometry])

    # Rule D: EPA's own 2012 segments on the current coast and EEZ.
    rule_d = pieces_by_coast(shared, [stretch(s) for s in old_splits.values()])
    return rule_b, rule_c, rule_d


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Score each rule against 2012

    For each region and rule we report two IoUs (intersection over union of area): the **whole region**
    (land plus sea, what a map user sees) and the **offshore part only** (region minus 2023 land), which is
    where the rules differ. We also report the area that differs in km².
    """)
    return


@app.cell
def _(
    OUT,
    km2,
    land,
    land_by_region,
    old_by_region,
    pd,
    rule_a,
    rule_b,
    rule_c,
    rule_d,
    single,
    unary_union,
):
    rules = {
        "A nearest coast": rule_a,
        "B due seaward": rule_b,
        "C BOEM lines": rule_c,
        "D 2012 lines": rule_d,
    }

    def build(rule: dict) -> dict:
        _sea = {r: unary_union([g for g in (single.get(r), rule.get(r)) if g is not None]) for r in range(1, 11)}
        return {r: unary_union([land_by_region[r], _sea[r]]) for r in range(1, 11)}

    built = {name: build(rule) for name, rule in rules.items()}
    _rows = []
    for _name, _layer in built.items():
        for _r in range(1, 11):
            _o, _n = old_by_region[_r], _layer[_r]
            _o_sea, _n_sea = _o.difference(land), _n.difference(land)
            _sea_union = km2(_o_sea.union(_n_sea))
            # Inland regions keep only slivers offshore (TIGER 2011 vs 2023 coastline); score coastal ones.
            _coastal = km2(_o_sea) > 1000
            _rows.append(
                {
                    "rule": _name,
                    "region": _r,
                    "IoU region": round(km2(_o.intersection(_n)) / km2(_o.union(_n)), 4),
                    "IoU offshore": round(km2(_o_sea.intersection(_n_sea)) / _sea_union, 4) if _coastal else None,
                    "km2 differs": round(km2(_o.symmetric_difference(_n))),
                    "km2 2012 offshore": round(km2(_o_sea)),
                }
            )
    scores = pd.DataFrame(_rows)
    scores.to_csv(OUT / "iou_by_region.csv", index=False)
    summary = (
        scores.groupby("rule")
        .agg(
            min_iou_offshore=("IoU offshore", "min"),
            mean_iou_offshore=("IoU offshore", "mean"),
            min_iou_region=("IoU region", "min"),
            km2_differs=("km2 differs", "sum"),
        )
        .round(4)
    )
    # Each misassigned km2 is counted once in the region that lost it and once in the one that gained it.
    summary["km2_misassigned"] = (summary.pop("km2_differs") / 2).round()
    print(scores.pivot(index="region", columns="rule", values="IoU offshore").to_string())
    print(summary.to_string())
    summary
    return built, scores, summary


@app.cell
def _(OUT, built, gpd, old_by_region, plt, summary):
    # Where each rule disagrees with 2012: areas assigned to a different region, coloured by the 2012 region.
    _fig, _axes = plt.subplots(2, 2, figsize=(14, 10))
    for _ax, _name in zip(_axes.flat, built, strict=True):
        for _r in range(1, 11):
            _diff = old_by_region[_r].difference(built[_name][_r])
            if not _diff.is_empty:
                gpd.GeoSeries([_diff], crs=4326).plot(ax=_ax, color=plt.get_cmap("tab10")(_r - 1))
        gpd.GeoSeries(list(old_by_region.values()), crs=4326).boundary.plot(ax=_ax, color="grey", linewidth=0.3)
        _mis = summary.loc[_name, "km2_misassigned"]
        _ax.set_title(f"{_name}: {_mis:,.0f} km² in a different region than 2012")
        _ax.set_xlim(230, 300)
        _ax.set_ylim(22, 50)
        _ax.set_axis_off()
    _fig.suptitle("Offshore area each rule assigns differently from the 2012 layer (colour = 2012 region)")
    _fig.tight_layout()
    _fig.savefig(OUT / "differences_map.png", dpi=110)
    _fig
    return


@app.cell
def _(built, noaa, old_by_region, pd, to_360):
    # Territories: which region holds each NOAA area in 2012 and in our rebuild.
    # Rule D shown; all rules agree away from the lower 48.
    _rows = []
    for _area, _grp in noaa.groupby("REGION"):
        if _area in ("Atlantic Coast and Gulf of Mexico", "Pacific Coast", "US-Canada"):
            continue
        _probe = to_360(_grp.union_all())
        _in_old = [r for r, g in old_by_region.items() if g.intersects(_probe)]
        _in_new = [r for r, g in built["D 2012 lines"].items() if g.intersects(_probe)]
        _rows.append(
            {
                "NOAA area": _area,
                "2012 region": ",".join(map(str, _in_old)) or "not covered",
                "rebuilt region": ",".join(map(str, _in_new)) or "not covered",
            }
        )
    territories = pd.DataFrame(_rows)
    print(territories.to_string())
    territories
    return (territories,)


@app.cell
def _(OUT, STARTED, built, gpd, km2, shapely, summary, time):
    # Write the closest rule's layer back in -180..180 longitudes, labelled as a derived product.
    best = summary["km2_misassigned"].idxmin()

    def to_180(geom: shapely.Geometry) -> shapely.Geometry:
        _west = geom.intersection(shapely.box(0, -90, 180, 90))
        _east = shapely.affinity.translate(geom.intersection(shapely.box(180, -90, 360, 90)), xoff=-360)
        return shapely.make_valid(shapely.union(_west, _east))

    layer = gpd.GeoDataFrame(
        {
            "region": [f"Region {r}" for r in range(1, 11)],
            "region_number": list(range(1, 11)),
            "area_km2": [round(km2(built[best][r])) for r in range(1, 11)],
            "offshore_rule": best,
            "product": "Fulton Ring derived layer, not an EPA product",
            "sources": "EPA Regions (DOC & EPA 2023); NOAA OCS US Maritime Limits and Boundaries; "
            "offshore split lines measured from EPA's 2012 regions-with-EEZ layer",
        },
        geometry=[to_180(built[best][r]) for r in range(1, 11)],
        crs=4326,
    )
    layer.to_parquet(OUT / "epa_regions_offshore_derived.parquet")
    runtime = round(time.time() - STARTED)
    print(f"wrote epa_regions_offshore_derived.parquet with rule {best!r}; run time {runtime} s; cost $0")
    return best, runtime


@app.cell
def _(best, mo, runtime, summary):
    _d, _b = summary.loc["D 2012 lines"], summary.loc["B due seaward"]
    mo.md(f"""
    ## Result

    - **Yes, with EPA's own lines.** Rule {best!r}, keeping the five straight 2012 split segments and
      rebuilding everything else from the 2023 regions and NOAA, scores offshore IoU of at least
      **{_d.min_iou_offshore:.3f}** in every coastal region, with about {_d.km2_misassigned:,.0f} km² placed
      differently from 2012, mostly coastline changes between the 2011 and 2023 TIGER states.
    - **No simple rule from first principles gets there.** "Due seaward" comes closest (worst region
      {_b.min_iou_offshore:.3f}, about {_b.km2_misassigned:,.0f} km² different) because three of EPA's five
      lines are parallels; it misses the two oblique ones (1/2 and 4/6). Nearest coast and BOEM's
      administrative lines agree with each other but not with EPA: they move the New York Bight and the
      Mid-Atlantic split by up to half of Regions 1–3's offshore area.
    - **Territories:** Puerto Rico and the US Virgin Islands go to Region 2; Hawaii, Guam, the Northern
      Mariana Islands, American Samoa and the Pacific Remote Islands go to Region 9; Alaska to Region 10.
      Same as 2012.
    - **What the layer is:** a derived product. The offshore split lines were drawn by EPA in 2012 with no
      published rule, so we document them as measured from that layer, not as EPA policy.
    - Run time {runtime} s in a 4-core cloud container; cost $0 (public downloads only).
    """)
    return


if __name__ == "__main__":
    app.run()

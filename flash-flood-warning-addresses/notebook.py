import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import logging
    import math
    import os
    import re
    import time
    import zipfile
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import rasterio
    import requests
    from pysheds.grid import Grid
    from pysheds.sview import Raster
    from rasterio.coords import disjoint_bounds
    from rasterio.features import geometry_mask, rasterize
    from rasterio.merge import merge
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds
    from scipy import ndimage
    from shapely.geometry import LineString, Point, Polygon, box, shape
    from shapely.ops import linemerge, unary_union

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log = logging.getLogger("ffw")
    started = time.time()
    default_cache = Path.home() / ".cache" / "flash-flood-warning-addresses"
    cache = Path(os.environ.get("FFW_CACHE", default_cache))
    results = Path(os.environ.get("FFW_RESULTS", Path(mo.notebook_dir() or ".") / "results"))
    cache.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    UTM = "EPSG:26916"  # NAD83 / UTM 16N, the CRS of the 1 m DEM; all distances are in metres
    return (
        Grid,
        Raster,
        disjoint_bounds,
        LineString,
        Point,
        Polygon,
        UTM,
        Window,
        box,
        cache,
        from_bounds,
        geometry_mask,
        gpd,
        json,
        linemerge,
        log,
        math,
        merge,
        mo,
        ndimage,
        np,
        pd,
        plt,
        rasterio,
        rasterize,
        re,
        requests,
        results,
        shape,
        started,
        time,
        transform_bounds,
        unary_union,
        zipfile,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Matching a flash-flood warning to the places that flooded

    On June 9, 2026, NWS Louisville issued flash flood warning LMK FF.W.0021 at 10:22 AM EDT.
    Its polygon covered Lanesville, Indiana, where more than 8 inches of rain fell in a few hours,
    but its list of "locations that will experience flash flooding" named only Louisville-area
    towns.

    **Question.** Could public terrain data have turned that polygon into a ranked list of the
    buildings and road crossings likely to flood first? If so, the places that actually flooded in
    Lanesville should land near the top of the list.

    **Test.** We rank every structure and road–stream crossing in and around Lanesville three ways:

    1. HAND (height above nearest drainage) computed here from the 1 m lidar DEM;
    2. NOAA OWP's precomputed 10 m HAND, the national product behind its flood inundation maps;
    3. plain height above the nearest creek point, in a straight line.

    Then we check where the places seen flooding land. The answer key is the NWS flood survey,
    plus named places from storm reports and news. It records only where flooding *was* seen,
    not where it wasn't. So this measures how many observed places a ranking puts near the top,
    not its overall accuracy.

    Every input is public and is downloaded when the notebook runs. Each one predates the storm.
    """)


@app.cell
def _(log, requests, time):
    def fetch(url: str, path, params: dict | None = None) -> None:
        """Download url to path once, with up to 4 attempts and backoff."""
        if path.exists():
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(4):
            try:
                with requests.get(url, params=params, stream=True, timeout=300) as r:
                    r.raise_for_status()
                    tmp = path.with_suffix(path.suffix + ".part")
                    with open(tmp, "wb") as f:
                        f.writelines(r.iter_content(1 << 20))
                    tmp.rename(path)
                    log.info("downloaded %s", path.name)
                    return
            except requests.RequestException as e:
                log.warning("attempt %d for %s failed: %s", attempt + 1, url, e)
                time.sleep(2 ** (attempt + 1))
        raise RuntimeError(f"could not download {url}")

    def arcgis(layer: str, params: dict) -> dict:
        """POST one ArcGIS REST query, retrying up to 4 times, and fail on an error payload."""
        for attempt in range(4):
            try:
                r = requests.post(f"{layer}/query", data={"f": "json", **params}, timeout=300)
                r.raise_for_status()
                body = r.json()
                if "error" in body:
                    raise RuntimeError(f"{layer}: {body['error']}")
                return body
            except (requests.RequestException, ValueError) as e:
                log.warning("attempt %d for %s failed: %s", attempt + 1, layer, e)
                time.sleep(2 ** (attempt + 1))
        raise RuntimeError(f"query to {layer} failed")

    return arcgis, fetch


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. The warning

    The IEM archive keeps every NWS warning product with its polygon. We take the 10:22 AM
    issuance, the first one people could have acted on.
    """)


@app.cell
def _(UTM, cache, fetch, gpd, json, re, shape):
    _q = "wfo=LMK&year=2026&phenomena=FF&significance=W&etn=21"
    fetch(f"https://mesonet.agron.iastate.edu/json/vtec_event.py?{_q}", cache / "vtec.json")
    fetch(f"https://mesonet.agron.iastate.edu/geojson/vtec_event.py?{_q}&sbw=1", cache / "sbw.json")
    vtec = json.loads((cache / "vtec.json").read_text())
    _sbw = json.loads((cache / "sbw.json").read_text())
    assert _sbw["count"] == 1, "expected exactly one warning polygon"
    warning = shape(_sbw["features"][0]["geometry"])
    _text = vtec["report"]["text"]
    warning_towns = re.search(r"include\.\.\.\s*(.*?)\n\n", _text, re.S).group(1)
    warning_sqmi = gpd.GeoSeries([warning], crs="EPSG:4326").to_crs(UTM).area.iloc[0] / 2.59e6
    print(f"Issued {vtec['utc_issue']}, expires {vtec['utc_expire']}")
    print(f"Polygon area: {warning_sqmi:.0f} sq mi")
    print("Locations named:", " ".join(warning_towns.split()))
    return warning, warning_sqmi, warning_towns


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. The answer key

    The NWS Louisville flood survey KMZ has one point per surveyed flood location. The points
    carry times and an event id but no depths. Thirteen points are tagged `Lanesville2026`.
    One of them sits in Corydon, 13 km west, so we drop it and keep the 12 that are in
    Lanesville.

    We add the named places from local storm reports and news, geocoded to Indiana address
    points:

    - Lanesville United Methodist Church, 2575 St Johns Church Rd NE. The LSR says it "shifted
      off its foundation", and WLKY says its fellowship hall did.
    - Lanesville Jr-Sr High School, 2725 Crestview Ave NE, whose track and ball fields flooded.
      No address exists for the fields themselves, so the school's address point stands in for
      both.
    - State Road 62, "blocked at the Floyd County line" (WDRB). No location was reported, so we
      use where TIGER's SR 62 crosses the county line. That point is computed, not observed.
    """)


@app.cell
def _(Point, arcgis, cache, fetch, gpd, pd, re, zipfile):
    fetch(
        "https://www.weather.gov/source/lmk/DamageKMZ/2026/flood_survey06092026.kmz",
        cache / "survey.kmz",
    )
    with zipfile.ZipFile(cache / "survey.kmz") as _z:
        _kml = _z.read("doc.kml").decode()
    _rows = []
    for _pm in re.findall(r"<Placemark>(.*?)</Placemark>", _kml, re.S):
        _attrs = dict(re.findall(r"<td><b>(.*?)</b></td><td>(.*?)</td>", _pm, re.S))
        _lon, _lat = map(float, re.search(r"<coordinates>(.*?)</coordinates>", _pm).group(1).split(",")[:2])
        _rows.append({"event_id": _attrs["event_id"].strip(), "time": _attrs["Event Date"], "lon": _lon, "lat": _lat})
    survey = gpd.GeoDataFrame(_rows, geometry=[Point(r["lon"], r["lat"]) for r in _rows], crs="EPSG:4326")
    tagged = survey[survey.event_id == "Lanesville2026"]
    # The Lanesville town limits run from about -85.996 to -85.972; anything west of -86.05 is Corydon.
    survey_lanesville = tagged[tagged.lon > -86.05]
    print(f"{len(survey)} survey points; {len(tagged)} tagged Lanesville2026; {len(survey_lanesville)} in Lanesville")

    _addr = "https://gisdata.in.gov/server/rest/services/Hosted/Address_Points_of_Indiana_2025/FeatureServer/0"
    _named = []
    for _label, _where in [
        ("Methodist church", "add_number=2575 AND UPPER(st_name) LIKE '%JOHNS CHURCH%' AND county_fips='18061'"),
        (
            "School track and ball field",
            "add_number=2725 AND UPPER(st_name) LIKE '%CRESTVIEW%' AND county_fips='18061'",
        ),
    ]:
        _hit = arcgis(
            _addr, {"where": _where, "outFields": "geofulladdress,latitude,longitude", "returnGeometry": "false"}
        )
        assert len(_hit["features"]) == 1, f"{_label}: expected one address point"
        _a = _hit["features"][0]["attributes"]
        _named.append({"place": _label, "source": _a["geofulladdress"], "lon": _a["longitude"], "lat": _a["latitude"]})

    fetch("https://www2.census.gov/geo/tiger/TIGER2025/ROADS/tl_2025_18061_roads.zip", cache / "roads_18061.zip")
    fetch("https://www2.census.gov/geo/tiger/TIGER2025/COUNTY/tl_2025_us_county.zip", cache / "counties.zip")
    _counties = gpd.read_file(cache / "counties.zip", where="STATEFP='18' AND COUNTYFP IN ('043','061')")
    _line = (
        _counties[_counties.COUNTYFP == "061"]
        .boundary.iloc[0]
        .intersection(_counties[_counties.COUNTYFP == "043"].boundary.iloc[0])
    )
    _harrison_roads = gpd.read_file(cache / "roads_18061.zip").to_crs(_counties.crs)
    _sr62 = _harrison_roads[_harrison_roads.FULLNAME.isin(["State Rd 62", "Hwy 62 NE", "Hwy 62 NW"])]
    _hits = _sr62.union_all().intersection(_line)
    _cross = min(getattr(_hits, "geoms", [_hits]), key=lambda p: p.distance(Point(-85.98, 38.24)))
    _named.append(
        {"place": "SR 62 at Floyd County line", "source": "computed from TIGER 2025", "lon": _cross.x, "lat": _cross.y}
    )
    named = pd.DataFrame(_named)

    _obs = [
        {"place": f"Survey {r.time[11:16]} UTC", "kind": "survey", "lon": r.lon, "lat": r.lat}
        for r in survey_lanesville.itertuples()
    ] + [{"place": r.place, "kind": "named", "lon": r.lon, "lat": r.lat} for r in named.itertuples()]
    observed = gpd.GeoDataFrame(_obs, geometry=[Point(o["lon"], o["lat"]) for o in _obs], crs="EPSG:4326")
    named
    return observed, survey, survey_lanesville, tagged


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. What sits inside the warning

    We count structures (FEMA/ORNL USA Structures), Indiana address points (IGIO's 2025
    release) and TIGER 2025 road segments inside the polygon, and inside Lanesville's Census
    town boundary. The structure and address counts come from the services' own spatial
    queries. Indiana's address layer stops at the state line, so it leaves out the Jefferson
    County, Kentucky part of the warning, which is most of Louisville.
    """)


@app.cell
def _(Polygon, arcgis, cache, fetch, gpd, json, pd, warning):
    _place = arcgis(
        "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/4",
        {"where": "GEOID='1842048'", "outFields": "NAME", "outSR": "4326"},
    )
    assert len(_place["features"]) == 1, "expected one Lanesville boundary"
    town = Polygon(_place["features"][0]["geometry"]["rings"][0])

    _structures = (
        "https://services2.arcgis.com/FiaPA4ga0iQKduv3/ArcGIS/rest/services/USA_Structures_View/FeatureServer/0"
    )
    _addresses = "https://gisdata.in.gov/server/rest/services/Hosted/Address_Points_of_Indiana_2025/FeatureServer/0"
    for _fips in ["18043", "21111"]:
        fetch(
            f"https://www2.census.gov/geo/tiger/TIGER2025/ROADS/tl_2025_{_fips}_roads.zip", cache / f"roads_{_fips}.zip"
        )
    _roads = pd.concat(
        [gpd.read_file(cache / f"roads_{f}.zip").to_crs("EPSG:4326") for f in ["18061", "18043", "21111"]]
    )

    def _count(layer: str, area) -> int:
        _geom = json.dumps({"rings": [list(area.exterior.coords)], "spatialReference": {"wkid": 4326}})
        _body = arcgis(
            layer,
            {
                "where": "1=1",
                "geometry": _geom,
                "geometryType": "esriGeometryPolygon",
                "inSR": "4326",
                "spatialRel": "esriSpatialRelIntersects",
                "returnCountOnly": "true",
            },
        )
        return int(_body["count"])

    _warning_poly = warning.geoms[0] if hasattr(warning, "geoms") else warning
    inside = pd.DataFrame(
        {
            area: {
                "structures": _count(_structures, poly),
                "address points (Indiana only)": _count(_addresses, poly),
                "road segments": int(_roads.intersects(poly).sum()),
            }
            for area, poly in [("whole warning", _warning_poly), ("Lanesville town", town)]
        }
    )
    inside
    return inside, town


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. The study area and its layers

    We rank everything in a 7 × 6.7 km box around Lanesville: the town plus its surroundings,
    including SR 62 out to the county line. We also rank inside the town limits alone. The
    layers:

    - **Structures:** USA Structures footprints, which come from imagery (production date 2020).
    - **Streams:** NHD High Resolution flowlines for HUC8 05140104 (2023). Indiana's NHD is
      lidar-derived and dense. We keep streams, artificial paths, connectors and ditches, and
      drop "drainageway" swales (FType 468) and underground conduits (420). With the swales
      included, nearly every building sits next to a "stream".
    - **Roads:** TIGER 2025.
    - **Bridges and culverts:** the National Bridge Inventory (BTS NTAD, June 2025).
    """)


@app.cell
def _(UTM, arcgis, box, cache, fetch, gpd, pd, shape, zipfile):
    AREA = (-86.02, 38.21, -85.94, 38.27)
    _env = {
        "geometry": ",".join(map(str, AREA)),
        "geometryType": "esriGeometryEnvelope",
        "inSR": "4326",
        "spatialRel": "esriSpatialRelIntersects",
        "outSR": "4326",
    }

    _layer = "https://services2.arcgis.com/FiaPA4ga0iQKduv3/ArcGIS/rest/services/USA_Structures_View/FeatureServer/0"
    _feats = []
    for _page in range(20):  # 2,000 per page; 20 pages is far more than this box holds
        _body = arcgis(
            _layer,
            {
                **_env,
                "where": "1=1",
                "outFields": "BUILD_ID,OCC_CLS,PRIM_OCC",
                "orderByFields": "OBJECTID",
                "resultOffset": _page * 2000,
                "resultRecordCount": 2000,
            },
        )
        _feats += _body["features"]
        if not _body.get("exceededTransferLimit"):
            break
    structures = gpd.GeoDataFrame(
        [f["attributes"] for f in _feats],
        geometry=[shape({"type": "Polygon", "coordinates": f["geometry"]["rings"]}) for f in _feats],
        crs="EPSG:4326",
    ).to_crs(UTM)

    _nbi = arcgis(
        "https://services.arcgis.com/xOi1kZaI0eWDREZv/arcgis/rest/services/NTAD_National_Bridge_Inventory/FeatureServer/0",
        {
            **_env,
            "where": "1=1",
            "outFields": "STRUCTURE_NUMBER_008,FACILITY_CARRIED_007,FEATURES_DESC_006A,STRUCTURE_TYPE_043B",
        },
    )["features"]
    bridges = gpd.GeoDataFrame(
        [f["attributes"] for f in _nbi],
        geometry=gpd.points_from_xy([f["geometry"]["x"] for f in _nbi], [f["geometry"]["y"] for f in _nbi]),
        crs="EPSG:4326",
    ).to_crs(UTM)
    bridges["culvert"] = bridges.STRUCTURE_TYPE_043B.astype(str).str.strip() == "19"

    fetch(
        "https://prd-tnm.s3.amazonaws.com/StagedProducts/Hydrography/NHD/HU8/GPKG/NHD_H_05140104_HU8_GPKG.zip",
        cache / "nhd_05140104.zip",
    )
    _gpkg = cache / "NHD_H_05140104_HU8_GPKG.gpkg"
    if not _gpkg.exists():
        with zipfile.ZipFile(cache / "nhd_05140104.zip") as _z:
            _z.extract(_gpkg.name, cache)
    _flow = gpd.read_file(_gpkg, layer="NHDFlowline", bbox=AREA)
    streams = _flow[_flow.ftype.isin([460, 558, 334, 336])].to_crs(UTM)
    swales = _flow[_flow.ftype == 468].to_crs(UTM)

    roads = gpd.read_file(cache / "roads_18061.zip", bbox=AREA).to_crs(UTM)
    area_utm = gpd.GeoSeries([box(*AREA)], crs="EPSG:4326").to_crs(UTM).iloc[0]
    print(
        pd.Series(
            {
                "structures": len(structures),
                "stream flowlines": len(streams),
                "drainageway swales dropped": len(swales),
                "road segments": len(roads),
                "NBI structures": len(bridges),
                "NBI culverts": int(bridges.culvert.sum()),
            }
        ).to_string()
    )
    return AREA, area_utm, bridges, roads, streams, structures


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. HAND from the 1 m DEM

    The 3DEP 1 m DEM here comes from Indiana's 2017 statewide QL2 lidar. It's a bare-earth
    model: buildings and bridge decks are removed, but road fill over culverts stays.

    We read the four tiles over the study area straight from USGS's cloud-optimized GeoTIFFs and
    burn the NHD streams 3 m into the DEM. Burning lets water route through road fill that
    hides a culvert. Then pysheds fills depressions, resolves flats, computes D8 flow directions
    and finds, for every cell, the stream cell it drains to. HAND is the cell's elevation minus
    that stream cell's, both taken from the unburned DEM. This step takes about 6 minutes, and
    the result is cached.

    We looked at WhiteboxTools' `ElevationAboveStream` first, but its binary download is
    blocked here. pysheds is pure Python and has `compute_hand`.
    """)


@app.cell
def _(
    AREA,
    Grid,
    Raster,
    UTM,
    cache,
    log,
    merge,
    np,
    rasterio,
    rasterize,
    streams,
    transform_bounds,
):
    _dem_path, _hand_path = cache / "dem_1m.tif", cache / "hand_1m.tif"
    if not _hand_path.exists():
        _base = (
            "/vsicurl/https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/"
            "IN_Indiana_Statewide_LiDAR_2017_B17/TIFF/USGS_1M_16_{0}_IN_Indiana_Statewide_LiDAR_2017_B17.tif"
        )
        _srcs = [rasterio.open(_base.format(t)) for t in ["x58y424", "x59y424", "x58y423", "x59y423"]]
        _bounds = transform_bounds("EPSG:4326", UTM, AREA[0] - 0.01, AREA[1] - 0.005, AREA[2] + 0.01, AREA[3] + 0.005)
        _arr, _tr = merge(_srcs, bounds=_bounds, res=1.0, nodata=-9999.0)
        _prof = {
            "driver": "GTiff",
            "dtype": "float32",
            "count": 1,
            "crs": UTM,
            "transform": _tr,
            "nodata": -9999.0,
            "height": _arr.shape[1],
            "width": _arr.shape[2],
            "compress": "deflate",
            "tiled": True,
            "BIGTIFF": "YES",
        }
        with rasterio.open(_dem_path, "w", **_prof) as _d:
            _d.write(_arr.astype("float32"))
        _raw = _arr[0].astype("float64")
        _stream_mask = rasterize(streams.geometry, out_shape=_raw.shape, transform=_tr, all_touched=True).astype(bool)
        _burned = np.where(_stream_mask & (_raw > -9000), _raw - 3.0, _raw)
        _burn_path = cache / "dem_burned.tif"
        with rasterio.open(_burn_path, "w", **_prof) as _d:
            _d.write(_burned.astype("float32"), 1)
        log.info("conditioning %s cells", _raw.size)
        _grid = Grid.from_raster(str(_burn_path))
        _dem = _grid.read_raster(str(_burn_path))
        _mask = Raster(_stream_mask.astype("float32"), viewfinder=_dem.viewfinder)  # nonzero = channel
        _filled = _grid.resolve_flats(_grid.fill_depressions(_grid.fill_pits(_dem)))
        _fdir = _grid.flowdir(_filled)
        _idx = np.asarray(_grid.compute_hand(_fdir, _dem, _mask, return_index=True)).astype("int64")
        _valid = (_idx >= 0) & (_raw > -9000)
        _hand = np.full(_raw.shape, np.nan, dtype="float32")
        _hand[_valid] = (_raw[_valid] - _raw.ravel()[_idx[_valid]]).astype("float32")
        _depression = (np.asarray(_filled) - _burned).astype("float32")  # depth of closed depressions
        _prof.update(count=2, nodata=np.nan)
        with rasterio.open(_hand_path, "w", **_prof) as _d:
            _d.write(_hand, 1)
            _d.write(np.where(_stream_mask, 0, _depression).astype("float32"), 2)
    with rasterio.open(_dem_path) as _d:
        dem = _d.read(1, masked=True).filled(np.nan)
        dem_transform = _d.transform
    with rasterio.open(_hand_path) as _d:
        hand = _d.read(1)
        depression = _d.read(2)
    print(f"DEM {dem.shape[1]} x {dem.shape[0]} cells; median HAND {np.nanmedian(hand):.1f} m")
    return dem, dem_transform, depression, hand


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. NOAA's 10 m HAND and plain height above the creek

    OWP's HAND rasters sit in a Requester Pays bucket that anonymous users can't read. CIROH
    mirrors them publicly. We use release 4.9.9.0 (April 2026), HUC8 05140104. It's built per
    stream "branch", so for each cell we take the lowest HAND across branches, which is how the
    branches are composited for mapping. This release stores HAND as int16 millimetres. We
    checked that against CIROH's 2024 float32 copy, which reads 5.28 m where 4.9.9.0 reads 4292,
    and divide by 1000.

    The third ranking needs no flow routing at all. It's a building's lowest ground elevation
    minus the elevation of the nearest stream cell in a straight line.
    """)


@app.cell
def _(AREA, Window, disjoint_bounds, from_bounds, np, rasterio, re, requests, transform_bounds):
    _bucket = "https://ciroh-owp-hand-fim.s3.us-east-2.amazonaws.com"
    _r = requests.get(_bucket, params={"list-type": "2", "prefix": "hand_fim_4_9_9_0/05140104/branches/"}, timeout=120)
    _r.raise_for_status()
    _keys = [k for k in re.findall(r"<Key>([^<]+)</Key>", _r.text) if "/rem_zeroed_masked_" in k]
    assert _keys, "no OWP HAND rasters listed"
    owp_layers = []  # (array, transform, crs) per branch, clipped to the study area
    for _k in _keys:
        with rasterio.open(f"/vsicurl/{_bucket}/{_k}") as _s:
            _b = transform_bounds("EPSG:4326", _s.crs, *AREA)
            if disjoint_bounds(_b, _s.bounds):
                continue
            _w = from_bounds(*_b, _s.transform).round_offsets().round_lengths()
            _w = _w.intersection(Window(0, 0, _s.width, _s.height))
            _a = _s.read(1, window=_w, masked=True).astype("float32").filled(np.nan)
            if _s.dtypes[0] == "int16":
                _a /= (
                    1000  # 4.x releases store HAND as int16 millimetres; the 2024 float copy gives the same values in m
                )
            if np.isfinite(_a).any():
                owp_layers.append((_a, _s.window_transform(_w), _s.crs))
    print(f"{len(_keys)} OWP branches listed; {len(owp_layers)} cover the study area")
    return (owp_layers,)


@app.cell
def _(dem, ndimage, np, rasterize, dem_transform, streams):
    _stream = rasterize(streams.geometry, out_shape=dem.shape, transform=dem_transform, all_touched=True).astype(bool)
    _dist, (_ri, _ci) = ndimage.distance_transform_edt(~_stream, return_indices=True)
    above_creek = (dem - dem[_ri, _ci]).astype("float32")
    stream_distance = _dist.astype("float32")
    return above_creek, stream_distance


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Road–stream crossings

    A crossing is any point where a TIGER road meets a kept NHD stream. For each one we record:

    - whether the National Bridge Inventory has a structure within 30 m;
    - whether the bare-earth DEM shows it **blocked**: the ground at the crossing stands more
      than 1 m above the creek bed 15–40 m away on both sides. That is road fill with no opening
      in the DEM, a "digital dam", which is how lidar DEMs hide culverts.

    A crossing's score in each ranking is the highest value within 5 m of the point: the road
    surface over the creek, which water has to rise above to cross the road. Bridge decks aren't
    in a bare-earth DEM, so a bridge scores as the creek bed beneath it.
    """)


@app.cell
def _(
    LineString,
    Point,
    bridges,
    dem,
    dem_transform,
    gpd,
    linemerge,
    np,
    pd,
    roads,
    streams,
    unary_union,
):
    _merged = linemerge(unary_union([g for g in streams.geometry.explode().geometry if isinstance(g, LineString)]))
    _lines = list(getattr(_merged, "geoms", [_merged]))
    _pts = []
    for _road in roads.itertuples():
        for _ln in _lines:
            _x = _road.geometry.intersection(_ln)
            for _p in getattr(_x, "geoms", [_x]):
                if isinstance(_p, Point):
                    _pts.append({"road": _road.FULLNAME, "geometry": _p, "line": _ln})
    crossings = gpd.GeoDataFrame(_pts, crs=streams.crs)
    # One crossing per spot: drop points within 10 m of one already kept.
    _keep, _seen = [], []
    for _i, _p in crossings.geometry.items():
        if all(_p.distance(q) > 10 for q in _seen):
            _keep.append(_i)
            _seen.append(_p)
    crossings = crossings.loc[_keep].reset_index(drop=True)

    _inv = ~dem_transform

    def _z(p: Point) -> float:
        c, r = _inv * (p.x, p.y)
        return float(dem[int(r), int(c)])

    def _blocked(p: Point, line: LineString) -> bool:
        s = line.project(p)
        crest = max(_z(p.buffer(5).boundary.interpolate(f, normalized=True)) for f in np.linspace(0, 1, 16))
        crest = max(crest, _z(p))
        sides = []
        for sign in (-1, 1):
            beds = [_z(line.interpolate(s + sign * d)) for d in range(15, 41, 5) if 0 <= s + sign * d <= line.length]
            if beds:
                sides.append(min(beds))
        return len(sides) == 2 and crest - max(sides) > 1.0

    crossings["blocked_in_dem"] = [_blocked(r.geometry, r.line) for r in crossings.itertuples()]
    crossings["nbi_structure"] = [bool((bridges.distance(p) <= 30).any()) for p in crossings.geometry]
    crossings = crossings.drop(columns="line")
    print(
        pd.Series(
            {
                "crossings": len(crossings),
                "with an NBI structure": int(crossings.nbi_structure.sum()),
                "blocked in the bare-earth DEM": int(crossings.blocked_in_dem.sum()),
            }
        ).to_string()
    )
    return (crossings,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. Scoring every candidate

    A structure's score is the *lowest* value under its footprint, because water reaches a
    building at its lowest side. A crossing's score is the *highest* value within 5 m, the road
    surface. Lower scores rank higher.
    """)


@app.cell
def _(
    above_creek,
    crossings,
    dem_transform,
    from_bounds,
    geometry_mask,
    gpd,
    hand,
    np,
    owp_layers,
    pd,
    structures,
    town,
):
    def zonal(arr, transform, geoms, stat) -> np.ndarray:
        """stat (np.min or np.max) of the finite cells each geometry touches; NaN if none."""
        out = np.full(len(geoms), np.nan)
        for i, g in enumerate(geoms):
            w = from_bounds(*g.bounds, transform).round_offsets(op="floor").round_lengths(op="ceil")
            r0, c0 = max(int(w.row_off), 0), max(int(w.col_off), 0)
            r1, c1 = min(int(w.row_off + w.height) + 1, arr.shape[0]), min(int(w.col_off + w.width) + 1, arr.shape[1])
            if r1 <= r0 or c1 <= c0:
                continue
            sub = arr[r0:r1, c0:c1]
            m = geometry_mask([g], sub.shape, transform * transform.translation(c0, r0), invert=True, all_touched=True)
            v = sub[m]
            v = v[np.isfinite(v)]
            if v.size:
                out[i] = stat(v)
        return out

    _cand = pd.concat(
        [
            gpd.GeoDataFrame(
                {
                    "kind": "structure",
                    "id": structures.BUILD_ID.astype(str),
                    "occupancy": structures.OCC_CLS,
                    "stat": "min",
                },
                geometry=structures.geometry,
            ),
            gpd.GeoDataFrame(
                {"kind": "crossing", "id": crossings.road.fillna("unnamed road"), "occupancy": "", "stat": "max"},
                geometry=crossings.geometry.buffer(5),
            ),
        ],
        ignore_index=True,
    )
    candidates = gpd.GeoDataFrame(_cand, geometry="geometry", crs=structures.crs)
    _is_min = (candidates.stat == "min").to_numpy()
    for _name, _arr in [("hand_1m", hand), ("above_creek", above_creek)]:
        _lo = zonal(_arr, dem_transform, list(candidates.geometry), np.min)
        _hi = zonal(_arr, dem_transform, list(candidates.geometry), np.max)
        candidates[_name] = np.where(_is_min, _lo, _hi)
    _owp = np.full((len(owp_layers), len(candidates)), np.nan)
    for _j, (_a, _t, _crs) in enumerate(owp_layers):
        _g = list(candidates.geometry.to_crs(_crs))
        _owp[_j] = np.where(_is_min, zonal(_a, _t, _g, np.min), zonal(_a, _t, _g, np.max))
    with np.errstate(all="ignore"):
        candidates["hand_owp_10m"] = np.nanmin(_owp, axis=0) if len(owp_layers) else np.nan
    _town_utm = gpd.GeoSeries([town], crs="EPSG:4326").to_crs(candidates.crs).iloc[0]
    candidates["in_town"] = candidates.intersects(_town_utm)
    METHODS = {"hand_1m": "1 m HAND", "hand_owp_10m": "10 m OWP HAND", "above_creek": "Height above creek"}
    print(candidates.groupby("kind")[list(METHODS)].describe().T.round(1).to_string())
    return METHODS, candidates


@app.cell
def _(mo):
    mo.md(r"""
    ## 9. Where the flooded places land

    For each ranking we sort the candidates from lowest to highest score. Ties share their
    average rank, which matters for the 10 m HAND, where many cells are exactly 0. An observed
    place's rank is the best rank of any candidate within 30 m of it. If no structure or
    crossing is within 30 m, it can't be found at all. We count how many places land in the top
    25, 50 and 100 and report the median rank, both for the whole study area and for the town
    alone. The town ranking scores only the places inside the town, which leaves out SR 62 at
    the county line. Candidates with no value (outside the OWP raster's coverage, for example)
    rank last.

    **Random order** is the baseline: the number of places expected in the top *K* if the
    candidates were shuffled. A place with *m* candidates within 30 m, out of *N*, is in the
    top *K* with probability 1 − C(N−m, K) / C(N, K).
    """)


@app.cell
def _(METHODS, UTM, candidates, gpd, math, np, observed, pd, town):
    _obs = observed.to_crs(UTM)
    _town_utm = gpd.GeoSeries([town], crs="EPSG:4326").to_crs(UTM).iloc[0]
    _rows, ranks = [], {}
    for _scope, _cands, _in in [
        ("Lanesville area (7 x 6.7 km)", candidates, np.ones(len(_obs), bool)),
        ("Lanesville town", candidates[candidates.in_town], _obs.within(_town_utm).to_numpy()),
    ]:
        _near = [_cands.index[_cands.distance(p) <= 30] if i else [] for p, i in zip(_obs.geometry, _in)]
        _n = len(_cands)
        _base = {"scope": _scope, "candidates": _n, "places": int(_in.sum())}
        for _m, _label in METHODS.items():
            _rank = _cands[_m].fillna(np.inf).rank(method="average")
            _best = np.array([_rank.loc[n].min() if len(n) else np.nan for n in _near])
            _best[~_in] = np.nan
            ranks[(_scope, _m)] = _best
            _row = {**_base, "ranking": _label}
            for _k in (25, 50, 100):
                _row[f"top {_k}"] = int((_best <= _k).sum())
            _row["no candidate within 30 m"] = int((np.isnan(_best) & _in).sum())
            _row["median rank"] = float(np.nanmedian(_best)) if np.isfinite(_best).any() else np.nan
            _row["candidates with no value"] = int(_cands[_m].isna().sum())
            _row["candidates tied at lowest"] = int((_cands[_m] == _cands[_m].min()).sum())
            _rows.append(_row)
        _row = {**_base, "ranking": "Random order (expected)"}
        for _k in (25, 50, 100):
            _p = [1 - math.comb(_n - len(n), _k) / math.comb(_n, _k) for n in _near if len(n)]
            _row[f"top {_k}"] = round(sum(_p), 1)
        _rows.append(_row)
    scores = pd.DataFrame(_rows)
    scores
    return ranks, scores


@app.cell
def _(mo):
    mo.md(r"""
    ### Each observed place, and why a miss was likely missed

    The reasons below are rules applied to the terrain, not field findings:

    - **no candidate within 30 m**: the point is open ground or a street, not a building or a
      crossing;
    - **in a depression**: the DEM shows a closed low spot at least 0.3 m deep, which suggests
      ponding (pluvial flooding, which NOAA says HAND doesn't represent);
    - **far from a mapped stream**: more than 100 m from any kept NHD stream, so HAND measures
      height above a creek the water didn't come from;
    - **high above drainage**: within reach of a stream but more than 2 m above it, so either
      the water rose that far or it arrived some other way, such as street runoff or a blocked
      culvert.
    """)


@app.cell
def _(
    METHODS,
    UTM,
    candidates,
    dem_transform,
    depression,
    gpd,
    np,
    observed,
    pd,
    ranks,
    stream_distance,
    town,
):
    _obs = observed.to_crs(UTM)
    _town_utm = gpd.GeoSeries([town], crs="EPSG:4326").to_crs(UTM).iloc[0]
    _inv = ~dem_transform
    _rc = [tuple(int(v) for v in (_inv * (p.x, p.y))[::-1]) for p in _obs.geometry]
    _scope = "Lanesville town"
    places = pd.DataFrame({"place": _obs.place, "kind": _obs.kind, "in town": _obs.within(_town_utm)})
    places["area rank, 1 m HAND"] = ranks[("Lanesville area (7 x 6.7 km)", "hand_1m")]
    for _m, _label in METHODS.items():
        places[f"town rank, {_label}"] = ranks[(_scope, _m)]
    _near = [candidates[candidates.in_town & (candidates.distance(p) <= 30)] for p in _obs.geometry]
    places["best 1 m HAND within 30 m (m)"] = [n.hand_1m.min() if len(n) else np.nan for n in _near]
    places["to nearest stream (m)"] = [float(stream_distance[r, c]) for r, c in _rc]
    places["depression depth (m)"] = [float(np.nanmax(depression[r - 3 : r + 4, c - 3 : c + 4])) for r, c in _rc]

    def _reason(row: pd.Series) -> str:
        if not row["in town"]:
            return "outside the town (area ranking only)"
        if row["town rank, 1 m HAND"] <= 100:
            return "caught (top 100)"
        if np.isnan(row["town rank, 1 m HAND"]):
            return "no candidate within 30 m"
        if row["depression depth (m)"] >= 0.3:
            return "in a depression"
        if row["to nearest stream (m)"] > 100:
            return "far from a mapped stream"
        return "high above drainage"

    places["1 m HAND outcome (town)"] = places.apply(_reason, axis=1)
    places.round(1)
    return (places,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 10. Map

    Left: the warning polygon and the Lanesville study area. Right: Lanesville's structures,
    with the 100 that rank first by 1 m HAND in the town ranking shaded dark, the streams, and
    the observed flood places.
    """)


@app.cell
def _(
    AREA,
    UTM,
    area_utm,
    candidates,
    gpd,
    observed,
    plt,
    results,
    streams,
    survey,
    town,
    warning,
):
    _fig, (_a0, _a1) = plt.subplots(1, 2, figsize=(14, 6.5), gridspec_kw={"width_ratios": [1, 1.25]})
    gpd.GeoSeries([warning], crs="EPSG:4326").plot(ax=_a0, facecolor="#fde2e2", edgecolor="#b91c1c")
    _a0.add_patch(plt.Rectangle((AREA[0], AREA[1]), AREA[2] - AREA[0], AREA[3] - AREA[1], fill=False, lw=1.5))
    survey.plot(ax=_a0, color="#1d4ed8", markersize=8)
    _a0.annotate("Lanesville", (AREA[0], AREA[3]), xytext=(0, 4), textcoords="offset points")
    _a0.annotate("Louisville", (-85.76, 38.25))
    _a0.annotate("Corydon", (-86.13, 38.21), xytext=(0, 4), textcoords="offset points")
    _a0.set_title("LMK FF.W.0021, 10:22 AM EDT polygon")

    _town = gpd.GeoSeries([town], crs="EPSG:4326").to_crs(UTM)
    _t = _town.buffer(500).total_bounds
    _tc = candidates[candidates.in_town]
    _top = set(_tc.hand_1m.rank(method="min").loc[lambda s: s <= 100].index)
    _s = candidates[candidates.kind == "structure"]
    _s.plot(ax=_a1, color=["#7f1d1d" if i in _top else "#d6d3d1" for i in _s.index], linewidth=0)
    streams.clip(area_utm).plot(ax=_a1, color="#60a5fa", linewidth=0.8)
    _town.boundary.plot(ax=_a1, color="#444", linewidth=0.8, linestyle="--")
    _o = observed.to_crs(UTM)
    _o[_o.kind == "survey"].plot(ax=_a1, color="#1d4ed8", markersize=40, marker="o", edgecolor="white", zorder=5)
    _o[_o.kind == "named"].plot(ax=_a1, color="#f59e0b", markersize=80, marker="*", edgecolor="black", zorder=5)
    _a1.set_xlim(_t[0], _t[2])
    _a1.set_ylim(_t[1], _t[3])
    _a1.set_title("Lanesville: top 100 by 1 m HAND (dark red), survey points (blue), named places (star)")
    for _ax in (_a0, _a1):
        _ax.set_xticks([])
        _ax.set_yticks([])
    _fig.tight_layout()
    _fig.savefig(results / "map.png", dpi=130)
    _fig


@app.cell
def _(
    METHODS,
    crossings,
    gpd,
    inside,
    json,
    np,
    observed,
    owp_layers,
    places,
    results,
    scores,
    started,
    survey_lanesville,
    tagged,
    time,
    town,
    warning_sqmi,
    warning_towns,
):
    _town_utm = gpd.GeoSeries([town], crs="EPSG:4326").to_crs(crossings.crs).iloc[0]
    _tx = crossings[crossings.intersects(_town_utm)]
    scores.to_csv(results / "ranking_scores.csv", index=False)
    places.round(2).to_csv(results / "observed_places.csv", index=False)
    summary = {
        "warning_sq_mi": round(float(warning_sqmi), 1),
        "warning_named_locations": " ".join(warning_towns.split()),
        "inside_counts": inside.to_dict(),
        "survey_points_tagged_lanesville": len(tagged),
        "survey_points_in_lanesville": len(survey_lanesville),
        "observed_places": len(observed),
        "owp_branches_used": len(owp_layers),
        "crossings_in_area": len(crossings),
        "crossings_with_nbi_structure": int(crossings.nbi_structure.sum()),
        "crossings_blocked_in_dem": int(crossings.blocked_in_dem.sum()),
        "crossings_in_town": len(_tx),
        "town_crossings_with_nbi_structure": int(_tx.nbi_structure.sum()),
        "town_crossings_blocked_in_dem": int(_tx.blocked_in_dem.sum()),
        "scores": scores.replace({np.nan: None}).to_dict(orient="records"),
        "outcomes_1m_hand_town": places["1 m HAND outcome (town)"].value_counts().to_dict(),
        "methods": list(METHODS.values()),
        "run_seconds": round(time.time() - started),
        "cost_usd": 0,
    }
    (results / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps({k: summary[k] for k in summary if k != "scores"}, indent=2))


if __name__ == "__main__":
    app.run()

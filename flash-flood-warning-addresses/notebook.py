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
    from collections.abc import Callable
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
    import whitebox_workflows as wbw
    from affine import Affine
    from rasterio.coords import disjoint_bounds
    from rasterio.features import geometry_mask, rasterize
    from rasterio.merge import merge
    from rasterio.warp import transform_bounds
    from rasterio.windows import Window, from_bounds
    from scipy import ndimage
    from shapely.geometry import LineString, MultiPoint, Point, Polygon, box, shape
    from shapely.ops import linemerge, unary_union

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log = logging.getLogger("ffw")
    started = time.time()
    default_cache = Path.home() / ".cache" / "flash-flood-warning-addresses"
    cache = Path(os.environ.get("FFW_CACHE", default_cache))
    cache.mkdir(parents=True, exist_ok=True)
    UTM = "EPSG:26916"  # NAD83 / UTM 16N, the CRS of the 1 m DEM; all distances are in metres
    return (
        Affine,
        Callable,
        Path,
        disjoint_bounds,
        LineString,
        MultiPoint,
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
        os,
        pd,
        plt,
        rasterio,
        rasterize,
        re,
        requests,
        shape,
        started,
        time,
        transform_bounds,
        unary_union,
        wbw,
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

    **Two towns.** Lanesville has only 11 distinct observed spots, so one cluster of survey points
    moves its totals by three. Corydon, 13 km west and inside the same polygon, is a second test:
    Little Indian Creek carried Lanesville's runoff into its downtown. The notebook runs one
    town at a time, chosen with `FFW_SITE` (`lanesville` by default, or `corydon`), and
    `run.sh` runs both.
    """)


@app.cell
def _(Path, cache, mo, os):
    SITES = {
        "lanesville": {
            "name": "Lanesville",
            "geoid": "1842048",  # Census place "Lanesville town", Indiana
            "area": (-86.02, 38.21, -85.94, 38.27),  # study box, lon/lat
            # Named flood places: an Indiana address-point query each. A query that matches
            # several points (a whole street) makes one place made of all of them.
            "named": [
                ("Methodist church", "add_number=2575 AND UPPER(st_name) LIKE '%JOHNS CHURCH%'"),
                ("School track and ball field", "add_number=2725 AND UPPER(st_name) LIKE '%CRESTVIEW%'"),
            ],
        },
        "corydon": {
            "name": "Corydon",
            "geoid": "1815256",  # Census place "Corydon town", Indiana
            "area": (-86.165, 38.19, -86.085, 38.255),
            "named": [
                ("The Alibi Bar", "add_number=115 AND UPPER(st_name) LIKE '%POPLAR%'"),
                ("Hey Elmer Print and Design", "add_number=133 AND UPPER(st_name) LIKE '%CHESTNUT%'"),
                ("Summit Springs subdivision", "UPPER(st_name)='CRESCENT HILL'"),
            ],
        },
    }
    SITE = os.environ.get("FFW_SITE", "lanesville")
    assert SITE in SITES, f"FFW_SITE must be one of {list(SITES)}"
    site = SITES[SITE]
    site_cache = cache / SITE  # rasters cut to this site's study box
    results = Path(os.environ.get("FFW_RESULTS", Path(mo.notebook_dir() or ".") / "results")) / SITE
    site_cache.mkdir(parents=True, exist_ok=True)
    results.mkdir(parents=True, exist_ok=True)
    mo.md(f"**Site: {site['name']}.** Results go to `{results}`.")
    return SITE, results, site, site_cache


@app.cell
def _(Path, log, requests, time):
    def fetch(url: str, path: Path, params: dict | None = None) -> None:
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
    carry times and an event id but no depths. Its 22 points form two clusters: 12 in
    Lanesville and 10 in downtown Corydon. One of the Corydon points is tagged
    `Lanesville2026`, so we go by location: a town's survey points are the ones inside its
    study box.

    We add named places from local storm reports and news, geocoded to Indiana address points.

    **Lanesville:**

    - Lanesville United Methodist Church, 2575 St Johns Church Rd NE. The LSR says it "shifted
      off its foundation", and WLKY says its fellowship hall did.
    - Lanesville Jr-Sr High School, 2725 Crestview Ave NE, whose track and ball fields flooded.
      No address exists for the fields themselves, so the school's address point stands in for
      both.
    - State Road 62, "blocked at the Floyd County line" (WDRB). No location was reported, so we
      use where TIGER's SR 62 crosses the county line. That point is computed, not observed.

    **Corydon:**

    - The Alibi Bar, 115 E Poplar St, and Hey Elmer Print and Design, 133 E Chestnut St. WDRB
      and WAVE name both as flooded downtown businesses.
    - The Summit Springs subdivision. The LSR reads "Flooding in Summit Springs subdivision in
      Corydon, IN", at a point rounded to 0.01°. Real estate listings place Summit Springs on
      Crescent Hill Dr NE, just north of the town limits, and the Harrison Township Fire
      Department reported rescues "in the Crescent Hill Drive subdivision". The report doesn't
      say which houses flooded, so the place is all 83 address points on that street. It
      counts as found if any of them is. That is generous, and the random baseline below
      allows for it.
    """)


@app.cell
def _(MultiPoint, Point, SITE, arcgis, cache, fetch, gpd, pd, re, site, zipfile):
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
    _w, _s, _e, _n = site["area"]
    survey_site = survey[survey.lon.between(_w, _e) & survey.lat.between(_s, _n)]
    print(f"{len(survey)} survey points; {len(survey_site)} in the {site['name']} study box")
    print(survey_site.event_id.value_counts().to_string())

    _addr = "https://gisdata.in.gov/server/rest/services/Hosted/Address_Points_of_Indiana_2025/FeatureServer/0"
    _named = []
    for _label, _where in site["named"]:
        _hit = arcgis(
            _addr,
            {
                "where": f"{_where} AND county_fips='18061'",
                "outFields": "geofulladdress,latitude,longitude",
                "returnGeometry": "false",
            },
        )["features"]
        assert 1 <= len(_hit) < 1000, f"{_label}: expected address points, got {len(_hit)}"
        _pts = [Point(f["attributes"]["longitude"], f["attributes"]["latitude"]) for f in _hit]
        _named.append(
            {
                "place": _label,
                "source": _hit[0]["attributes"]["geofulladdress"]
                + (f" and {len(_hit) - 1} more" if len(_hit) > 1 else ""),
                "geometry": _pts[0] if len(_pts) == 1 else MultiPoint(_pts),
            }
        )

    if SITE == "lanesville":  # SR 62's closure point was never reported; use the county-line crossing
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
        _named.append({"place": "SR 62 at Floyd County line", "source": "computed from TIGER 2025", "geometry": _cross})
    named = pd.DataFrame(_named)

    _obs = [
        {"place": f"Survey {r.time[11:16]} UTC", "kind": "survey", "geometry": r.geometry}
        for r in survey_site.itertuples()
    ] + [{"place": r.place, "kind": "named", "geometry": r.geometry} for r in named.itertuples()]
    observed = gpd.GeoDataFrame(_obs, geometry="geometry", crs="EPSG:4326")
    named[["place", "source"]]
    return observed, survey, survey_site


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. What sits inside the warning

    We count structures (FEMA/ORNL USA Structures), Indiana address points (IGIO's 2025
    release) and TIGER 2025 road segments inside the polygon, and inside the town's Census
    boundary. Corydon's boundary has two parts, the town and a small detached piece east of it.
    The structure and address counts come from the services' own spatial queries. Indiana's
    address layer stops at the state line, so it leaves out the Jefferson County, Kentucky part
    of the warning, which is most of Louisville.
    """)


@app.cell
def _(Polygon, arcgis, cache, fetch, gpd, json, pd, site, unary_union, warning):
    _place = arcgis(
        "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/Places_CouSub_ConCity_SubMCD/MapServer/4",
        {"where": f"GEOID='{site['geoid']}'", "outFields": "NAME", "outSR": "4326"},
    )
    assert len(_place["features"]) == 1, f"expected one {site['name']} boundary"
    # ArcGIS rings run clockwise for outer boundaries and counter-clockwise for holes.
    _rings = [Polygon(r) for r in _place["features"][0]["geometry"]["rings"]]
    town = unary_union([r for r in _rings if not r.exterior.is_ccw]).difference(
        unary_union([r for r in _rings if r.exterior.is_ccw])
    )

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

    def _count(layer: str, area: Polygon) -> int:
        _parts = getattr(area, "geoms", [area])
        _geom = json.dumps({"rings": [list(p.exterior.coords) for p in _parts], "spatialReference": {"wkid": 4326}})
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
            for area, poly in [("whole warning", _warning_poly), (f"{site['name']} town", town)]
        }
    )
    inside
    return inside, town


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. The study area and its layers

    We rank everything in a box about 7 km across around the town: the town plus its
    surroundings, including SR 62 out to the county line for Lanesville and the Summit Springs
    subdivision for Corydon. We also rank inside the town limits alone. Both towns are in the
    same HUC8 watershed, 05140104 (Blue-Sinking), so they share one NHD file and one set of OWP
    rasters. The layers:

    - **Structures:** USA Structures footprints, which come from imagery (production date 2020).
    - **Streams:** NHD High Resolution flowlines for HUC8 05140104 (2023). Indiana's NHD is
      lidar-derived and dense. We keep streams, artificial paths, connectors and ditches, and
      drop "drainageway" swales (FType 468) and underground conduits (420). With the swales
      included, nearly every building sits next to a "stream".
    - **Roads:** TIGER 2025.
    - **Bridges and culverts:** the National Bridge Inventory (BTS NTAD, June 2025).
    """)


@app.cell
def _(UTM, arcgis, box, cache, fetch, gpd, pd, shape, site, zipfile):
    AREA = site["area"]
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
    _x0, _y0, _x1, _y1 = area_utm.bounds
    area_label = f"{site['name']} area ({(_x1 - _x0) / 1000:.0f} x {(_y1 - _y0) / 1000:.1f} km)"
    print(area_label)
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
    return AREA, area_label, area_utm, bridges, roads, streams, structures


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. HAND from the 1 m DEM

    The 3DEP 1 m DEM here comes from Indiana's 2017 statewide QL2 lidar. It's a bare-earth
    model: buildings and bridge decks are removed, but road fill over culverts stays.

    We read the tiles over the study area straight from USGS's cloud-optimized GeoTIFFs. The
    tiles are 10 km squares named by their UTM corner, so the names follow from the box.
    WhiteboxTools (the `whitebox-workflows` wheel) then conditions the DEM in three steps:

    1. `burn_streams_at_roads` cuts the NHD streams through road embankments, standing in for
       the culverts the DEM can't see;
    2. `breach_depressions_least_cost` lets every cell drain;
    3. `elevation_above_stream` traces each cell's downslope path to the first stream cell and
       reports how far above that cell it sits. That is HAND.

    The same library gives the third ranking, `elevation_above_stream_euclidean`: height above
    the nearest stream cell in a straight line, with no flow routing. It also gives
    `depth_in_sink`, how far a cell sits below the depression-filled surface. The rasters are
    cached, and the step takes about a minute.
    """)
    return


@app.cell
def _(
    AREA,
    UTM,
    log,
    math,
    merge,
    np,
    rasterio,
    rasterize,
    roads,
    site_cache,
    streams,
    transform_bounds,
    wbw,
):
    _dem_path, _out = site_cache / "dem_1m.tif", {n: site_cache / f"{n}.tif" for n in ["hand", "above_creek", "sink"]}
    if not all(p.exists() for p in _out.values()):
        _base = (
            "/vsicurl/https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/1m/Projects/"
            "IN_Indiana_Statewide_LiDAR_2017_B17/TIFF/USGS_1M_16_{0}_IN_Indiana_Statewide_LiDAR_2017_B17.tif"
        )
        _bounds = transform_bounds("EPSG:4326", UTM, AREA[0] - 0.01, AREA[1] - 0.005, AREA[2] + 0.01, AREA[3] + 0.005)
        # Tile xNNyMMM spans easting NN0 km to NN0+10 km, and northing MMM0 km down to MMM0-10 km.
        _xs = range(math.floor(_bounds[0] / 1e4), math.floor(_bounds[2] / 1e4) + 1)
        _ys = range(math.ceil(_bounds[1] / 1e4), math.ceil(_bounds[3] / 1e4) + 1)
        _srcs = [rasterio.open(_base.format(f"x{x}y{y}")) for x in _xs for y in _ys]
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
        }
        with rasterio.open(_dem_path, "w", **_prof) as _d:
            _d.write(_arr.astype("float32"))
        _mask = rasterize(streams.geometry, out_shape=_arr.shape[1:], transform=_tr, all_touched=True)
        with rasterio.open(site_cache / "streams.tif", "w", **{**_prof, "nodata": 0}) as _d:
            _d.write(_mask.astype("float32"), 1)
        for _name, _gdf in [("streams", streams), ("roads", roads)]:
            _flat = _gdf[["geometry"]].explode(ignore_index=True)
            _flat["geometry"] = _flat.geometry.force_2d()
            _flat["FID"] = range(len(_flat))
            _flat.to_file(site_cache / f"{_name}.shp")
        log.info("conditioning the 1 m DEM with WhiteboxTools")
        _wbe = wbw.WbEnvironment()
        _wbe.verbose = False
        _h = _wbe.hydrology
        _raw = _wbe.read_raster(str(_dem_path))
        _stream_raster = _wbe.read_raster(str(site_cache / "streams.tif"))
        _culverts = _h.burn_streams_at_roads(
            dem=_raw,
            streams=_wbe.read_vector(str(site_cache / "streams.shp")),
            roads=_wbe.read_vector(str(site_cache / "roads.shp")),
            road_width=30.0,
        )
        _drained = _h.breach_depressions_least_cost(dem=_culverts, max_dist=100, fill_deps=True)
        _wbe.write_raster(_h.elevation_above_stream(dem=_drained, streams=_stream_raster), str(_out["hand"]))
        _wbe.write_raster(
            _h.elevation_above_stream_euclidean(dem=_raw, streams=_stream_raster), str(_out["above_creek"])
        )
        _wbe.write_raster(_h.depth_in_sink(dem=_raw, zero_background=True), str(_out["sink"]))
    with rasterio.open(_dem_path) as _d:
        dem = _d.read(1, masked=True).filled(np.nan)
        dem_transform = _d.transform
    _layers = {}
    for _name, _path in _out.items():
        with rasterio.open(_path) as _d:
            assert _d.shape == dem.shape and _d.transform == dem_transform, f"{_name} is off the DEM grid"
            _layers[_name] = _d.read(1, masked=True).astype("float32").filled(np.nan)
    hand, above_creek, depression = _layers["hand"], _layers["above_creek"], _layers["sink"]
    print(f"DEM {dem.shape[1]} x {dem.shape[0]} cells; HAND missing for {np.isnan(hand).mean():.1%} of cells")
    return above_creek, dem, dem_transform, depression, hand


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. NOAA's 10 m HAND

    OWP's HAND rasters sit in a Requester Pays bucket that anonymous users can't read. CIROH
    mirrors them publicly. We use release 4.9.9.0 (April 2026), HUC8 05140104. It's built per
    stream "branch", so for each cell we take the lowest HAND across branches, which is how the
    branches are composited for mapping. This release stores HAND as int16 millimetres. We
    checked that against CIROH's 2024 float32 copy, which reads 5.28 m where 4.9.9.0 reads 4292,
    and divide by 1000.
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
                _a /= 1000  # 4.x releases store HAND as int16 millimetres
            if np.isfinite(_a).any():
                owp_layers.append((_a, _s.window_transform(_w), _s.crs))
    print(f"{len(_keys)} OWP branches listed; {len(owp_layers)} cover the study area")
    return (owp_layers,)


@app.cell
def _(dem, dem_transform, ndimage, rasterize, streams):
    _stream = rasterize(streams.geometry, out_shape=dem.shape, transform=dem_transform, all_touched=True).astype(bool)
    stream_distance = ndimage.distance_transform_edt(~_stream).astype("float32")
    return (stream_distance,)


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
    box,
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
    # Road segments run past the DEM's edge; keep crossings whose 40 m creek-bed check fits inside it.
    _x0, _y1 = dem_transform * (0, 0)
    _x1, _y0 = dem_transform * (dem.shape[1], dem.shape[0])
    _inside = crossings.within(box(_x0, _y0, _x1, _y1).buffer(-50))
    print(f"dropped {int((~_inside).sum())} crossings within 50 m of the DEM edge")
    crossings = crossings[_inside].reset_index(drop=True)

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
    Affine,
    Callable,
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
    def zonal(arr: np.ndarray, transform: Affine, geoms: list, stat: Callable[[np.ndarray], float]) -> np.ndarray:
        """stat (np.min or np.max) of the finite cells each geometry touches; NaN if none."""
        out = np.full(len(geoms), np.nan)
        for i, g in enumerate(geoms):
            w = from_bounds(*g.bounds, transform).round_offsets(op="floor").round_lengths(op="ceil")
            r0, c0 = max(int(w.row_off), 0), max(int(w.col_off), 0)
            r1, c1 = min(int(w.row_off + w.height) + 1, arr.shape[0]), min(int(w.col_off + w.width) + 1, arr.shape[1])
            if r1 <= r0 or c1 <= c0:
                continue
            sub = arr[r0:r1, c0:c1]
            m = geometry_mask([g], sub.shape, transform * Affine.translation(c0, r0), invert=True, all_touched=True)
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
    the county line (Lanesville) and the Summit Springs subdivision (Corydon). Candidates with
    no value (outside the OWP raster's coverage, for example) rank last.

    **Random order** is the baseline: the number of places expected in the top *K* if the
    candidates were shuffled. A place with *m* candidates within 30 m, out of *N*, is in the
    top *K* with probability 1 − C(N−m, K) / C(N, K).
    """)


@app.cell
def _(METHODS, UTM, area_label, candidates, gpd, math, np, observed, pd, site, town):
    _obs = observed.to_crs(UTM)
    _town_utm = gpd.GeoSeries([town], crs="EPSG:4326").to_crs(UTM).iloc[0]
    _rows, ranks = [], {}
    for _scope, _cands, _in in [
        (area_label, candidates, np.ones(len(_obs), bool)),
        (f"{site['name']} town", candidates[candidates.in_town], _obs.within(_town_utm).to_numpy()),
    ]:
        _near = [_cands.index[_cands.distance(p) <= 30] if i else [] for p, i in zip(_obs.geometry, _in, strict=True)]
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
    - **high above drainage**: within 100 m of a stream and not in a depression, but too high
      above the stream to rank in the top 100. Either the water rose that far, or it arrived
      some other way, such as street runoff or a blocked culvert.
    """)


@app.cell
def _(
    METHODS,
    area_label,
    UTM,
    candidates,
    dem_transform,
    depression,
    gpd,
    np,
    observed,
    pd,
    ranks,
    roads,
    site,
    stream_distance,
    town,
):
    _obs = observed.to_crs(UTM)
    _town_utm = gpd.GeoSeries([town], crs="EPSG:4326").to_crs(UTM).iloc[0]
    _inv = ~dem_transform
    # Raster measures are taken at a place's centre (for a whole street, the middle of its points).
    _rc = [tuple(int(v) for v in (_inv * (p.centroid.x, p.centroid.y))[::-1]) for p in _obs.geometry]
    _scope = f"{site['name']} town"
    places = pd.DataFrame({"place": _obs.place, "kind": _obs.kind, "in town": _obs.within(_town_utm)})
    places["area rank, 1 m HAND"] = ranks[(area_label, "hand_1m")]
    for _m, _label in METHODS.items():
        places[f"town rank, {_label}"] = ranks[(_scope, _m)]
    _near = [candidates[candidates.in_town & (candidates.distance(p) <= 30)] for p in _obs.geometry]
    places["best 1 m HAND within 30 m (m)"] = [n.hand_1m.min() if len(n) else np.nan for n in _near]
    places["to nearest road (m)"] = [float(roads.distance(p).min()) for p in _obs.geometry]
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

    Left: the warning polygon and the study area. Right: the town's structures, with the 100
    that rank first by 1 m HAND in the town ranking shaded dark, the streams, and the observed
    flood places. A named place made of a whole street is outlined in orange.
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
    site,
    streams,
    survey,
    town,
    warning,
):
    _fig, (_a0, _a1) = plt.subplots(1, 2, figsize=(14, 6.5), gridspec_kw={"width_ratios": [1, 1.25]})
    gpd.GeoSeries([warning], crs="EPSG:4326").plot(ax=_a0, facecolor="#fde2e2", edgecolor="#b91c1c")
    _a0.add_patch(plt.Rectangle((AREA[0], AREA[1]), AREA[2] - AREA[0], AREA[3] - AREA[1], fill=False, lw=1.5))
    survey.plot(ax=_a0, color="#1d4ed8", markersize=8)
    _a0.annotate(site["name"], (AREA[0], AREA[3]), xytext=(0, 4), textcoords="offset points")
    _a0.annotate("Louisville", (-85.76, 38.25))
    _a0.set_title("LMK FF.W.0021, 10:22 AM EDT polygon")

    _town = gpd.GeoSeries([town], crs="EPSG:4326").to_crs(UTM)
    _o = observed.to_crs(UTM)
    _near_town = _o[_o.distance(_town.iloc[0]) < 1500]  # widen the view to take in places just outside town
    _t = gpd.GeoSeries([_town.buffer(500).union_all(), _near_town.buffer(200).union_all()]).total_bounds
    _tc = candidates[candidates.in_town]
    _top = set(_tc.hand_1m.rank(method="min").loc[lambda s: s <= 100].index)
    _s = candidates[candidates.kind == "structure"]
    _s.plot(ax=_a1, color=["#7f1d1d" if i in _top else "#d6d3d1" for i in _s.index], linewidth=0)
    streams.clip(area_utm).plot(ax=_a1, color="#60a5fa", linewidth=0.8)
    _town.boundary.plot(ax=_a1, color="#444", linewidth=0.8, linestyle="--")
    _o[_o.kind == "survey"].plot(ax=_a1, color="#1d4ed8", markersize=40, marker="o", edgecolor="white", zorder=5)
    _single = (_o.kind == "named") & (_o.geom_type == "Point")
    _o[_single].plot(ax=_a1, color="#f59e0b", markersize=80, marker="*", edgecolor="black", zorder=5)
    _street = _o[(_o.kind == "named") & ~_single]
    if len(_street):
        _street.convex_hull.buffer(30).boundary.plot(ax=_a1, color="#f59e0b", linewidth=2, zorder=5)
    _a1.set_xlim(_t[0], _t[2])
    _a1.set_ylim(_t[1], _t[3])
    _a1.set_title(f"{site['name']}: top 100 by 1 m HAND (dark red), survey points (blue), named places (orange)")
    for _ax in (_a0, _a1):
        _ax.set_xticks([])
        _ax.set_yticks([])
        _ax.set_xlabel("")
        _ax.set_ylabel("")
    _fig.tight_layout()
    _fig.savefig(results / "map.png", dpi=130)
    _fig


@app.cell
def _(mo):
    mo.md(r"""
    ## 11. What didn't work, and what this doesn't show

    - **pysheds.** The first HAND build used pysheds' `fill_depressions`, `resolve_flats` and
      `compute_hand`. Its filled flats sat a fraction of a millimetre below their spill points,
      so resolving the flats left pits. Cells draining into a pit got no HAND: 34% of the area
      and 13% of the town's buildings. WhiteboxTools' standalone binary is blocked from
      downloading here, but its `whitebox-workflows` wheel installs from PyPI and assigns HAND
      to every cell in town.
    - **OWP's own bucket** (`noaa-nws-owp-fim`) is Requester Pays and refuses anonymous reads.
      The CIROH mirror has the same files.
    - **NHDPlus HR service.** The NHDPlus HR map service timed out on most queries, so we use the
      NHD HR HU8 file, which has the same flowline geometry without the value-added
      attributes.
    - **The 30 m match.** Four of the town's observed places have no structure or crossing
      within 30 m. They are survey points in streets and yards, so no building- or
      crossing-level ranking can score them.
    - **Locations.** Storm report coordinates are rounded to 0.01°, about 1 km, which is why the
      named places are geocoded from addresses instead. The SR 62 closure point is where SR 62
      meets the county line, not a reported spot.
    - **The answer key** shows only where flooding was seen. A building that ranks high and
      didn't flood can't be told apart from one nobody surveyed, so this measures how many
      observed places rank near the top, not precision.
    - **No hydraulics.** No rainfall, discharge or drainage-structure data goes in. HAND ranks
      places by height above a creek. It doesn't say whether the water reaches them.
    """)
    return


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
    site,
    started,
    survey_site,
    time,
    town,
    warning_sqmi,
    warning_towns,
):
    _town_utm = gpd.GeoSeries([town], crs="EPSG:4326").to_crs(crossings.crs).iloc[0]
    _tx = crossings[crossings.intersects(_town_utm)]
    _sites = []  # several survey points mark the same spot; count spots at least 30 m apart
    for _p in observed.to_crs(crossings.crs).geometry:
        if all(_p.distance(q) > 30 for q in _sites):
            _sites.append(_p)
    scores.to_csv(results / "ranking_scores.csv", index=False)
    places.round(2).to_csv(results / "observed_places.csv", index=False)
    summary = {
        "warning_sq_mi": round(float(warning_sqmi), 1),
        "warning_named_locations": " ".join(warning_towns.split()),
        "inside_counts": inside.to_dict(),
        "site": site["name"],
        "survey_points_in_study_area": len(survey_site),
        "observed_places": len(observed),
        "observed_sites_30m_apart": len(_sites),
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

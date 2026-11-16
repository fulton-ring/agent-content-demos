import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    import shutil
    import subprocess
    import time
    import urllib.error
    import urllib.request
    import zipfile
    from pathlib import Path

    import folium
    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import rasterio
    import rasterio.features
    import rasterio.mask
    import rasterio.warp
    import shapely
    import valhalla
    from mcp import Client

    return (
        Client,
        Path,
        folium,
        gpd,
        json,
        mo,
        np,
        os,
        pd,
        plt,
        rasterio,
        shapely,
        shutil,
        subprocess,
        time,
        urllib,
        valhalla,
        zipfile,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # How much of a wildfire-prone county can a fire engine reach in 10, 20 and 30 minutes?

    In the \$11 million XPRIZE Wildfire competition, all three finalists in the autonomous response track found the
    target fire in Alaska, and none won the grand prize for putting it out. Seeing a fire is only half the job; the
    other half is getting suppression to it. Nobody publishes a map of where fire and EMS stations can get to by road
    in a given number of minutes. This notebook makes one for one county from public data:

    1. pick the county with the highest wildfire risk to homes, by a stated rule;
    2. pull its fire and EMS stations from HIFLD Next through its MCP server, and check them against OpenStreetMap;
    3. drive out from every station on OpenStreetMap roads with the open Valhalla router, for 10, 20 and 30 minutes;
    4. lay the reach bands over USFS Wildfire Hazard Potential and Census 2020 blocks, and count homes, people and
       high-hazard land in each band.

    It measures road reach from a station, nothing else: no turnout time, traffic, staffing, aircraft, hand crews or
    off-road travel.
    """)
    return


@app.cell
def _(Path, os, time):
    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("REACH_DATA_DIR", HERE / "data"))
    OUT = Path(os.environ.get("REACH_OUT_DIR", HERE / "outputs"))
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    MCP_URL = "https://hifld.publicenvirodata.org/mcp"
    BANDS = [10, 20, 30]  # minutes of driving
    MIN_STATIONS = 25  # a county needs this many stations for a reach map to be interesting
    BUFFER_KM = 25  # stations this far outside the county also respond (mutual aid)
    MATCH_M = 300  # a HIFLD and an OSM station closer than this are the same station
    run_started = time.perf_counter()
    stage_seconds = {}
    return (
        BANDS,
        BUFFER_KM,
        DATA,
        MATCH_M,
        MCP_URL,
        MIN_STATIONS,
        OUT,
        run_started,
        stage_seconds,
    )


@app.cell
def _(DATA, Path, urllib):
    def download(url: str, name: str) -> Path:
        """Download url into DATA/name once; later runs reuse the file."""
        path = DATA / name
        if path.exists() and path.stat().st_size > 0:
            return path
        tmp = path.with_suffix(path.suffix + ".part")
        request = urllib.request.Request(url, headers={"User-Agent": "wildfire-reach-time-map demo"})
        with urllib.request.urlopen(request, timeout=600) as response, open(tmp, "wb") as f:
            if response.status != 200:
                raise RuntimeError(f"{url} returned HTTP {response.status}")
            while chunk := response.read(1 << 20):
                f.write(chunk)
        tmp.rename(path)
        return path

    return (download,)


@app.cell
def _(Client, MCP_URL, shapely):
    # HIFLD Next's fire and EMS station layer, as get_dataset_file returns it from the MCP server.
    STATIONS_SOURCE = {
        "alias": "st",
        "collection_slug": "hifld",
        "dataset_slug": "fire-and-emergency-medical-service-ems-stations",
        "file_slug": "fire-and-emergency-medical-service-ems-stations",
        "version": "v1.0.0",
        "asset_key": "geoparquet-65a71a5263c4",
    }

    async def hifld_rows(sql: str, max_pages: int = 50) -> list[dict]:
        """Run one SELECT through the HIFLD Next MCP server's query_parquet tool and page through every row."""
        assert len(sql.encode()) < 8192, "the server rejects SQL over 8 KiB"
        async with Client(MCP_URL) as client:
            args = {"sources": [STATIONS_SOURCE], "sql": sql, "limit": 1000, "result_crs": "EPSG:4326"}
            result = await client.call_tool("query_parquet", args)
            if result.is_error or not result.structured_content:
                raise RuntimeError(f"query_parquet failed: {result.content}")
            page = result.structured_content
            rows = list(page["rows"])
            for _ in range(max_pages):
                if not page.get("has_more"):
                    return rows
                args = {"query_token": page["query_token"], "offset": page["next_offset"], "page_size": 1000}
                result = await client.call_tool("get_query_page", args)
                if result.is_error or not result.structured_content:
                    raise RuntimeError(f"get_query_page failed: {result.content}")
                page = result.structured_content
                rows.extend(page["rows"])
        raise RuntimeError(f"more than {max_pages} pages; raise max_pages")

    def polygon_sql(geom: shapely.Geometry) -> str:
        """A WKB literal for geom, buffered and simplified until the SQL fits the server's 8 KiB limit.

        The buffer means the simplified shape still contains the real one; we filter exactly afterwards.
        """
        for tolerance in [0.001, 0.002, 0.004, 0.008, 0.016]:
            hexwkb = geom.buffer(tolerance * 2).simplify(tolerance).wkb_hex
            if len(hexwkb) < 7000:
                return f"ST_GeomFromHexWKB('{hexwkb}')"
        raise ValueError("polygon too detailed even at 0.016 degrees")

    return hifld_rows, polygon_sql


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Pick the county

    USFS [Wildfire Risk to Communities](https://wildfirerisk.org/download/) publishes, for every county, its national
    rank for **risk to homes** (`RISK_NATIONAL_RANK`, 0 to 1). The rule: walk counties from the highest rank down,
    breaking ties by burn-probability rank, and take the first with at least 25 fire and EMS stations in HIFLD Next.
    We count stations for the top ten so the runners-up are visible.
    Twenty-five stations is enough for the reach bands to have shape; a county with a handful of stations would just
    be a few circles. Station counts come from the MCP server: the county outline goes into the SQL as a WKB literal.
    """)
    return


@app.cell
async def _(MIN_STATIONS, download, gpd, hifld_rows, pd, polygon_sql, shapely, stage_seconds, time):
    _started = time.perf_counter()
    wrc = pd.read_excel(
        download("https://wildfirerisk.org/wp-content/uploads/2026/04/wrc_download_20260415.xlsx", "wrc.xlsx"),
        sheet_name="Counties",
        dtype={"GEOID": str},
    )
    wrc["GEOID"] = wrc["GEOID"].str.zfill(5)
    counties = gpd.read_file(
        download("https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_county_500k.zip", "counties.zip")
    ).set_index("GEOID")
    _ranked = wrc.dropna(subset=["RISK_NATIONAL_RANK"]).sort_values(
        ["RISK_NATIONAL_RANK", "BP_NATIONAL_RANK"], ascending=False
    )
    _checked = []
    for _row in _ranked.head(10).itertuples():
        _outline = counties.loc[_row.GEOID].geometry
        _candidates = await hifld_rows(
            f"SELECT ST_AsHexWKB(geometry) AS g FROM st WHERE ST_Intersects(geometry, {polygon_sql(_outline)})"
        )
        _points = shapely.from_wkb([bytes.fromhex(r["g"]) for r in _candidates])
        _n = int(shapely.contains(_outline, _points).sum()) if _candidates else 0
        _checked.append(
            {
                "county": _row.NAME,
                "GEOID": _row.GEOID,
                "risk_to_homes_rank": _row.RISK_NATIONAL_RANK,
                "burn_probability_rank": _row.BP_NATIONAL_RANK,
                "buildings": int(_row.TOTAL_BUILDINGS),
                "hifld_stations": _n,
            }
        )
    county_choice = pd.DataFrame(_checked)
    _eligible = county_choice[county_choice.hifld_stations >= MIN_STATIONS]
    assert len(_eligible) > 0, "no county in the top 10 has enough stations"
    county_geoid = _eligible.iloc[0]["GEOID"]
    county = counties.loc[county_geoid]
    county_name = _eligible.iloc[0]["county"]
    county_state = wrc.set_index("GEOID").loc[county_geoid, "STATE_NAME"]
    stage_seconds["pick_county"] = time.perf_counter() - _started
    county_choice
    return county, county_choice, county_geoid, county_name, county_state


@app.cell
def _(county_choice, county_geoid, county_name, mo):
    _pick = county_choice.set_index("GEOID").loc[county_geoid]
    mo.md(f"""
    **{county_name}** is the county: risk-to-homes rank {_pick["risk_to_homes_rank"]:.3f}, burn-probability rank
    {_pick["burn_probability_rank"]:.3f}, {_pick["hifld_stations"]} HIFLD stations.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Stations from HIFLD Next, through its MCP server

    HIFLD Next's *Fire and Emergency Medical Service (EMS) Stations* layer is the USGS National Map structures layer
    (feature code 74026, "Fire Station/EMS Station"); fire and EMS stations are one layer, not two. We ask the MCP
    server's `query_parquet` tool for every station inside the county or within 25 km of it, because a station just
    over the line responds too, and page through the result with `get_query_page`.
    """)
    return


@app.cell
async def _(BUFFER_KM, county, gpd, hifld_rows, polygon_sql, shapely, stage_seconds, time):
    _started = time.perf_counter()
    utm = gpd.GeoSeries([county.geometry], crs=4326).estimate_utm_crs()
    county_utm = gpd.GeoSeries([county.geometry], crs=4326).to_crs(utm).iloc[0]
    _reach_area = gpd.GeoSeries([county_utm.buffer(BUFFER_KM * 1000)], crs=utm).to_crs(4326).iloc[0]
    _rows = await hifld_rows(
        "SELECT OBJECTID, NAME, ADDRESS, CITY, STATE, LOADDATE, ST_AsHexWKB(geometry) AS g FROM st "
        f"WHERE ST_Intersects(geometry, {polygon_sql(_reach_area)})"
    )
    stations = gpd.GeoDataFrame(
        [{k: v for k, v in r.items() if k != "g"} for r in _rows],
        geometry=shapely.from_wkb([bytes.fromhex(r["g"]) for r in _rows]),
        crs=4326,
    )
    stations = stations[stations.within(_reach_area)].reset_index(drop=True)
    stations["in_county"] = stations.within(county.geometry)
    stage_seconds["hifld_stations"] = time.perf_counter() - _started
    stations.drop(columns="geometry").groupby(["in_county", "STATE"]).size().rename("stations").reset_index()
    return county_utm, stations, utm


@app.cell
def _(mo):
    mo.md(r"""
    ### Check the station list against OpenStreetMap

    The second source is OpenStreetMap's `amenity=fire_station`, from the same extract we route on (Overpass wasn't
    reachable from the build machine, and the extract is the same data). A HIFLD station and an OSM station within
    300 m of each other count as the same station. Stations on one list and not the other are written to
    `outputs/station_differences.csv`.
    """)
    return


@app.cell
def _(DATA, county, county_geoid, county_state, download, shutil, subprocess, urllib):
    # openstreetmap.fr keeps a daily extract per US state, under a regional folder.
    if not shutil.which("osmium"):
        raise RuntimeError("osmium not found: install osmium-tool (apt install osmium-tool, brew install osmium-tool)")
    _state_slug = county_state.lower().replace(" ", "_")
    _state_url = None
    for _region in ["us-west", "us-south", "us-midwest", "us-northeast"]:
        _url = f"https://download.openstreetmap.fr/extracts/north-america/{_region}/{_state_slug}-latest.osm.pbf"
        try:
            with urllib.request.urlopen(urllib.request.Request(_url, method="HEAD"), timeout=60) as _r:
                if _r.status == 200:
                    _state_url = _url
                    break
        except urllib.error.HTTPError:
            continue
    assert _state_url, f"no openstreetmap.fr extract found for {county_state}"
    state_pbf = download(_state_url, f"{_state_slug}-latest.osm.pbf")
    osm_timestamp = subprocess.run(
        ["osmium", "fileinfo", "-g", "header.option.osmosis_replication_timestamp", str(state_pbf)],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    # Cut a box half a degree around the county so routes and outside stations have their roads.
    _w, _s, _e, _n = county.geometry.bounds
    county_pbf = DATA / f"osm-{county_geoid}.osm.pbf"
    if not county_pbf.exists():
        _box = f"{_w - 0.5},{_s - 0.5},{_e + 0.5},{_n + 0.5}"
        subprocess.run(
            ["osmium", "extract", "--overwrite", "-b", _box, str(state_pbf), "-o", str(county_pbf)], check=True
        )
    _fire_pbf = DATA / f"osm-fire-{county_geoid}.osm.pbf"
    osm_fire_file = DATA / f"osm-fire-{county_geoid}.geojson"
    subprocess.run(
        ["osmium", "tags-filter", "--overwrite", str(county_pbf), "nwr/amenity=fire_station", "-o", str(_fire_pbf)],
        check=True,
    )
    subprocess.run(["osmium", "export", "--overwrite", str(_fire_pbf), "-o", str(osm_fire_file)], check=True)
    osm_timestamp
    return county_pbf, osm_fire_file, osm_timestamp


@app.cell
def _(MATCH_M, OUT, county, gpd, osm_fire_file, pd, stations, utm):
    _osm = gpd.read_file(osm_fire_file)
    _osm = gpd.GeoDataFrame(_osm[["name"]], geometry=_osm.to_crs(utm).geometry.representative_point(), crs=utm)
    _osm = _osm[_osm.to_crs(4326).within(county.geometry)]
    # A station mapped both as a point and as a building comes through twice: merge OSM features within 100 m.
    _clusters = gpd.GeoDataFrame(geometry=gpd.GeoSeries([_osm.buffer(100).union_all()], crs=utm).explode(), crs=utm)
    _osm = _osm.sjoin(_clusters.reset_index(drop=True), predicate="within")
    osm_stations = (
        _osm.sort_values("name").groupby("index_right").first().reset_index(drop=True).set_geometry("geometry")
    ).set_crs(utm)
    _hifld = stations[stations.in_county].to_crs(utm)
    _h2o = gpd.sjoin_nearest(_hifld, osm_stations[["name", "geometry"]], how="left", distance_col="m")
    _h2o = _h2o[~_h2o.index.duplicated()]
    _o2h = gpd.sjoin_nearest(osm_stations, _hifld[["NAME", "geometry"]], how="left", distance_col="m")
    _o2h = _o2h[~_o2h.index.duplicated()]
    station_check = {
        "hifld_in_county": len(_hifld),
        "osm_in_county": len(osm_stations),
        "hifld_with_osm_within_300m": int((_h2o.m <= MATCH_M).sum()),
        "osm_with_hifld_within_300m": int((_o2h.m <= MATCH_M).sum()),
        "hifld_with_osm_within_1km": int((_h2o.m <= 1000).sum()),
        "osm_with_hifld_within_1km": int((_o2h.m <= 1000).sum()),
        "median_offset_m_of_300m_matches": round(float(_h2o.m[_h2o.m <= MATCH_M].median()), 1),
    }
    _differences = pd.concat(
        [
            _h2o[_h2o.m > MATCH_M].assign(
                source="HIFLD only", station=lambda d: d.NAME, nearest_other=lambda d: d.name
            ),
            _o2h[_o2h.m > MATCH_M].assign(source="OSM only", station=lambda d: d.name, nearest_other=lambda d: d.NAME),
        ]
    ).to_crs(4326)
    _differences.assign(
        lon=_differences.geometry.x.round(5),
        lat=_differences.geometry.y.round(5),
        nearest_other_m=_differences.m.round(),
    )[["source", "station", "lon", "lat", "nearest_other", "nearest_other_m"]].to_csv(
        OUT / "station_differences.csv", index=False
    )
    station_check
    return (station_check,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Drive out from every station

    Valhalla (through `pyvalhalla`, which bundles the tile builder and runs in-process) builds routing tiles from the
    extract, then draws a 10, 20 and 30 minute isochrone around each station with its default car costing: free-flow
    road speeds, no traffic, no lights and sirens. The union of every station's isochrone is the reach band.
    """)
    return


@app.cell
def _(DATA, county_geoid, county_pbf, json, shutil, stage_seconds, subprocess, time, valhalla):
    _started = time.perf_counter()
    tile_dir = DATA / f"valhalla-{county_geoid}"
    if not (tile_dir / "done").exists():
        shutil.rmtree(tile_dir, ignore_errors=True)
        tile_dir.mkdir()
        (tile_dir / "config.json").write_text(json.dumps(valhalla.get_config(tile_extract="", tile_dir=tile_dir)))
        subprocess.run(
            ["valhalla_build_tiles", "-c", str(tile_dir / "config.json"), str(county_pbf)],
            check=True,
            capture_output=True,
        )
        (tile_dir / "done").touch()
    stage_seconds["osm_and_tiles"] = time.perf_counter() - _started
    return (tile_dir,)


@app.cell
def _(BANDS, gpd, json, pd, shapely, stage_seconds, stations, tile_dir, time, valhalla):
    _started = time.perf_counter()
    _actor = valhalla.Actor(json.loads((tile_dir / "config.json").read_text()))
    _records = []
    _failed = []
    for _i, _station in stations.iterrows():
        _request = {
            "locations": [{"lat": _station.geometry.y, "lon": _station.geometry.x}],
            "costing": "auto",
            "contours": [{"time": b} for b in BANDS],
            "polygons": True,
        }
        try:
            _response = json.loads(_actor.isochrone(json.dumps(_request)))
        except RuntimeError as error:  # Valhalla raises when no road is near the point
            _failed.append({"station": _station.NAME, "error": str(error)[:120]})
            continue
        for _feature in _response["features"]:
            _records.append(
                {
                    "station": _i,
                    "minutes": int(_feature["properties"]["contour"]),
                    "geometry": shapely.geometry.shape(_feature["geometry"]),
                }
            )
    isochrones = gpd.GeoDataFrame(_records, crs=4326)
    isochrone_failures = pd.DataFrame(_failed, columns=["station", "error"])
    stage_seconds["isochrones"] = time.perf_counter() - _started
    {"stations routed": isochrones.station.nunique(), "failed": len(isochrone_failures)}
    return isochrone_failures, isochrones


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Overlay on homes, people and hazard

    **Homes and people** are Census 2020 blocks (`HOUSING20` housing units and `POP20` people, from the TIGER/Line
    2020 block file), each placed in a band by its internal point.

    **Hazard** is USFS [Wildfire Hazard Potential 2023](https://doi.org/10.2737/RDS-2015-0047-4) (270 m), the
    hazard layer that sits under Wildfire Risk to Communities. "High hazard" means WHP class High or Very High. We
    use WHP's 270 m national file because Wildfire Risk to Communities' own 30 m rasters come as one 11 GB zip for
    California.

    A cell or block is in the *smallest* band that reaches it from *any* station: "within 10" means some station gets
    there in 10 minutes, "10 to 20" means the nearest takes 10 to 20, and "beyond 30" means none gets there in 30.
    """)
    return


@app.cell
def _(BANDS, isochrones, pd, shapely, stations):
    def reach_bands(station_ids: pd.Index) -> dict[int, shapely.Geometry]:
        """Union the isochrones of the given stations into one polygon per band."""
        _subset = isochrones[isochrones.station.isin(station_ids)]
        return {b: shapely.union_all(_subset[_subset.minutes == b].geometry.values) for b in BANDS}

    bands_all = reach_bands(stations.index)
    bands_county_only = reach_bands(stations.index[stations.in_county])
    return bands_all, bands_county_only


@app.cell
def _(county_geoid, download, gpd):
    # The state-wide TIGER 2020 block file carries POP20 and HOUSING20; the per-county PL file does not.
    blocks = gpd.read_file(
        download(
            f"https://www2.census.gov/geo/tiger/TIGER2020/TABBLOCK20/tl_2020_{county_geoid[:2]}_tabblock20.zip",
            f"blocks-{county_geoid[:2]}.zip",
        ),
        where=f"GEOID20 LIKE '{county_geoid}%'",  # OGR's `COUNTYFP20 = '073'` matches nothing in this file
        columns=["GEOID20", "POP20", "HOUSING20", "INTPTLAT20", "INTPTLON20"],
        ignore_geometry=True,
    )
    blocks = gpd.GeoDataFrame(
        blocks[["GEOID20", "POP20", "HOUSING20"]],
        geometry=gpd.points_from_xy(blocks.INTPTLON20.astype(float), blocks.INTPTLAT20.astype(float)),
        crs=4326,
    )
    assert len(blocks) > 0, "no Census blocks read for the county"
    {"blocks": len(blocks), "people": int(blocks.POP20.sum()), "housing units": int(blocks.HOUSING20.sum())}
    return (blocks,)


@app.cell
def _(DATA, county, download, np, rasterio, zipfile):
    _zip = download(
        "https://www.fs.usda.gov/rds/archive/products/RDS-2015-0047-4/RDS-2015-0047-4_Data.zip", "whp2023.zip"
    )
    whp_tif = DATA / "whp2023_cls_conus.tif"
    if not whp_tif.exists():
        with zipfile.ZipFile(_zip) as _z:
            whp_tif.write_bytes(_z.read("Data/whp2023_GeoTIF/whp2023_cls_conus.tif"))
    with rasterio.open(whp_tif) as _src:
        whp_crs = _src.crs
        _shape = rasterio.warp.transform_geom("EPSG:4326", whp_crs, county.geometry.__geo_interface__)
        _data, whp_transform = rasterio.mask.mask(_src, [_shape], crop=True, nodata=255)
    whp = _data[0]
    # Classes: 1 very low, 2 low, 3 moderate, 4 high, 5 very high, 6 non-burnable, 7 water, 255 outside the county.
    assert set(np.unique(whp)) <= {1, 2, 3, 4, 5, 6, 7, 255}, "unexpected WHP class"
    WHP_CELL_KM2 = 0.27 * 0.27
    {int(k): int(v) for k, v in zip(*np.unique(whp, return_counts=True), strict=True)}
    return WHP_CELL_KM2, whp, whp_crs, whp_transform


@app.cell
def _(BANDS, WHP_CELL_KM2, blocks, np, pd, rasterio, shapely, whp, whp_crs, whp_transform):
    BAND_LABELS = {1: "within 10 min", 2: "10 to 20 min", 3: "20 to 30 min", 4: "beyond 30 min"}

    def block_bands(bands: dict) -> np.ndarray:
        """Band code (1 to 4) of each block: the smallest band whose polygon holds its internal point."""
        codes = np.full(len(blocks), 4)
        for k, b in reversed(list(enumerate(BANDS, start=1))):
            codes[shapely.contains_xy(bands[b], blocks.geometry.x.values, blocks.geometry.y.values)] = k
        return codes

    def grid_bands(bands: dict, all_touched: bool = False) -> np.ndarray:
        """Band code of each WHP cell: rasterize the bands widest first, so narrower bands overwrite.

        By default a cell is in a band when its centre is; all_touched counts any cell the band touches.
        """
        shapes = [
            (rasterio.warp.transform_geom("EPSG:4326", whp_crs, bands[b].__geo_interface__), k)
            for k, b in reversed(list(enumerate(BANDS, start=1)))
            if not bands[b].is_empty
        ]
        return rasterio.features.rasterize(
            shapes, out_shape=whp.shape, transform=whp_transform, fill=4, all_touched=all_touched
        )

    def band_table(block_codes: np.ndarray, grid: np.ndarray) -> pd.DataFrame:
        """Homes, people, land and high-hazard land in each reach band."""
        in_county = whp != 255
        high = (whp == 4) | (whp == 5)
        table = pd.DataFrame(
            [
                {
                    "band": label,
                    "housing_units": int(blocks.HOUSING20.values[block_codes == k].sum()),
                    "people": int(blocks.POP20.values[block_codes == k].sum()),
                    "land_km2": float(((grid == k) & in_county).sum() * WHP_CELL_KM2),
                    "high_hazard_km2": float(((grid == k) & high).sum() * WHP_CELL_KM2),
                }
                for k, label in BAND_LABELS.items()
            ]
        )
        for col in ["housing_units", "people", "land_km2", "high_hazard_km2"]:
            table[f"{col}_share"] = table[col] / table[col].sum()
        return table

    return BAND_LABELS, band_table, block_bands, grid_bands


@app.cell
def _(band_table, bands_all, bands_county_only, block_bands, grid_bands, stage_seconds, time):
    _started = time.perf_counter()
    block_codes = block_bands(bands_all)
    grid = grid_bands(bands_all)
    results = band_table(block_codes, grid)
    results_county_only = band_table(block_bands(bands_county_only), grid_bands(bands_county_only))
    stage_seconds["overlay"] = time.perf_counter() - _started
    results.round(3)
    return block_codes, grid, results, results_county_only


@app.cell
def _(mo):
    mo.md(r"""
    Valhalla's isochrones follow the roads: they cover land near a road the car reaches, not the country between
    roads. So "beyond 30 minutes" means *away from every road a station reaches in 30 minutes*. How far away
    matters: land 300 m off a road is a hose lay, land 5 km off is a hike, a dozer line or an aircraft. The table
    below splits the high-hazard land beyond 30 minutes by its straight-line distance to the nearest land that is
    within 30 minutes.
    """)
    return


@app.cell
def _(WHP_CELL_KM2, bands_all, grid, grid_bands, pd, whp):
    from scipy.ndimage import distance_transform_edt

    # Distance from every cell beyond 30 minutes to the nearest cell within 30, in km (cells are 270 m).
    _km_to_reach = distance_transform_edt(grid == 4) * 0.27
    _high_beyond = ((whp == 4) | (whp == 5)) & (grid == 4)
    _high_total = ((whp == 4) | (whp == 5)).sum()
    distance_table = pd.DataFrame(
        [
            {
                "km from 30-minute reach": f"more than {d}",
                "high_hazard_km2": float((_high_beyond & (_km_to_reach > d)).sum() * WHP_CELL_KM2),
                "share_of_all_high_hazard": float((_high_beyond & (_km_to_reach > d)).sum() / _high_total),
            }
            for d in [0, 0.5, 1, 2, 5]
        ]
    )
    # The 30-minute strips are often narrower than a 270 m cell, so how cells are counted matters a little.
    high_beyond_all_touched = float(
        (((whp == 4) | (whp == 5)) & (grid_bands(bands_all, all_touched=True) == 4)).sum() / _high_total
    )
    distance_table.round(3)
    return distance_table, high_beyond_all_touched


@app.cell
def _(block_codes, blocks, np, pd, rasterio, whp, whp_crs, whp_transform):
    # Homes that sit in high-hazard cells, and how many of those no station reaches in 30 minutes.
    _xs, _ys = rasterio.warp.transform("EPSG:4326", whp_crs, blocks.geometry.x.values, blocks.geometry.y.values)
    _rows, _cols = rasterio.transform.rowcol(whp_transform, _xs, _ys)
    _block_high = np.isin(whp[np.clip(_rows, 0, whp.shape[0] - 1), np.clip(_cols, 0, whp.shape[1] - 1)], [4, 5])
    _beyond30 = block_codes == 4
    homes_in_high_hazard = pd.Series(
        {
            "housing_units_in_high_hazard": int(blocks.HOUSING20.values[_block_high].sum()),
            "of_which_beyond_30_min": int(blocks.HOUSING20.values[_block_high & _beyond30].sum()),
            "people_in_high_hazard": int(blocks.POP20.values[_block_high].sum()),
            "people_of_which_beyond_30_min": int(blocks.POP20.values[_block_high & _beyond30].sum()),
        }
    )
    homes_in_high_hazard
    return (homes_in_high_hazard,)


@app.cell
def _(results, results_county_only, mo, pd):
    def _pct(share: pd.Series) -> pd.Series:
        return (100 * share).round(1)

    _side = pd.DataFrame(
        {
            "band": results.band,
            "homes %": _pct(results.housing_units_share),
            "people %": _pct(results.people_share),
            "high-hazard land %": _pct(results.high_hazard_km2_share),
            "all land %": _pct(results.land_km2_share),
            "high-hazard land %, county stations only": _pct(results_county_only.high_hazard_km2_share),
        }
    )
    mo.vstack(
        [
            mo.md(
                "## 5. Result\n\nShare of the county's homes, people and high-hazard land in each reach band. "
                "The last column drops the stations outside the county."
            ),
            _side,
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Maps

    Left, the reach bands at the 270 m grid of the hazard layer. Right, only the high-hazard land, split into what
    a station reaches in 30 minutes and what it doesn't. The HTML map has the bands, the hazard and the stations on
    an OpenStreetMap basemap, and can be zoomed.
    """)
    return


@app.cell
def _(OUT, county, county_name, gpd, grid, np, plt, stations, whp, whp_crs, whp_transform):
    _colors = plt.matplotlib.colors
    _extent = [
        whp_transform.c,
        whp_transform.c + whp.shape[1] * whp_transform.a,
        whp_transform.f + whp.shape[0] * whp_transform.e,
        whp_transform.f,
    ]
    _outline = gpd.GeoSeries([county.geometry], crs=4326).to_crs(whp_crs).boundary
    _in_county = whp != 255
    _high = np.isin(whp, [4, 5])
    _fig, (_left, _right) = plt.subplots(1, 2, figsize=(16, 8))
    _band_colors = ["#08306b", "#4292c6", "#c6dbef", "#bdbdbd"]
    _left.imshow(
        np.ma.masked_where(~_in_county, grid), extent=_extent, cmap=_colors.ListedColormap(_band_colors), vmin=1, vmax=4
    )
    stations[stations.in_county].to_crs(whp_crs).plot(ax=_left, color="#e6550d", markersize=6)
    _left.legend(
        handles=[
            plt.matplotlib.patches.Patch(color=c, label=lab)
            for c, lab in zip(
                _band_colors, ["within 10 min", "10 to 20 min", "20 to 30 min", "beyond 30 min"], strict=True
            )
        ]
        + [plt.matplotlib.lines.Line2D([], [], color="#e6550d", marker="o", lw=0, ms=4, label="HIFLD station")],
        loc="lower left",
    )
    _left.set_title("Drive time from the nearest station")
    _hazard = np.where(_high & (grid < 4), 1, np.where(_high & (grid == 4), 2, 0))
    _right.imshow(
        np.ma.masked_where(_hazard == 0, _hazard),
        extent=_extent,
        cmap=_colors.ListedColormap(["#9ecae1", "#cb181d"]),
        vmin=1,
        vmax=2,
    )
    _right.legend(
        handles=[
            plt.matplotlib.patches.Patch(color="#9ecae1", label="high hazard, within 30 min"),
            plt.matplotlib.patches.Patch(color="#cb181d", label="high hazard, beyond 30 min"),
        ],
        loc="lower left",
    )
    _right.set_title("WHP High and Very High land")
    for _ax in (_left, _right):
        _outline.plot(ax=_ax, color="black", linewidth=0.6)
        _ax.set_axis_off()
    _fig.suptitle(f"{county_name}: road reach of fire and EMS stations over wildfire hazard", fontsize=14)
    _fig.tight_layout()
    _fig.savefig(OUT / "reach_map.png", dpi=120)
    _fig
    return


@app.cell
def _(BANDS, OUT, bands_all, county, folium, np, rasterio, stations, whp, whp_crs, whp_transform):
    _w, _s, _e, _n = county.geometry.bounds
    _map = folium.Map(tiles="OpenStreetMap", control_scale=True)
    _map.fit_bounds([[_s, _w], [_n, _e]])
    # Hazard as an image: reproject the High/Very High cells to web coordinates and colour them.
    _high = np.where(np.isin(whp, [4, 5]), whp, 0).astype("uint8")
    _dst_transform, _width, _height = rasterio.warp.calculate_default_transform(
        whp_crs, "EPSG:4326", whp.shape[1], whp.shape[0], *rasterio.transform.array_bounds(*whp.shape, whp_transform)
    )
    _web = np.zeros((_height, _width), dtype="uint8")
    rasterio.warp.reproject(
        _high, _web, src_transform=whp_transform, src_crs=whp_crs, dst_transform=_dst_transform, dst_crs="EPSG:4326"
    )
    _rgba = np.zeros((*_web.shape, 4), dtype="uint8")
    _rgba[_web == 4] = [244, 162, 89, 170]
    _rgba[_web == 5] = [188, 75, 81, 190]
    _b = rasterio.transform.array_bounds(_height, _width, _dst_transform)
    folium.raster_layers.ImageOverlay(
        _rgba, bounds=[[_b[1], _b[0]], [_b[3], _b[2]]], name="WHP High / Very High"
    ).add_to(_map)
    _colors = {10: "#08306b", 20: "#4292c6", 30: "#c6dbef"}
    for _m in reversed(BANDS):
        folium.GeoJson(
            bands_all[_m].simplify(0.001).__geo_interface__,
            name=f"{_m}-minute drive",
            style_function=lambda _f, c=_colors[_m]: {"color": c, "weight": 1, "fillColor": c, "fillOpacity": 0.35},
        ).add_to(_map)
    _fg = folium.FeatureGroup(name="HIFLD stations")
    for _st in stations.itertuples():
        folium.CircleMarker([_st.geometry.y, _st.geometry.x], radius=3, color="black", tooltip=_st.NAME).add_to(_fg)
    _fg.add_to(_map)
    folium.LayerControl().add_to(_map)
    _map.save(OUT / "reach_map.html")
    return


@app.cell
def _(
    BAND_LABELS,
    BUFFER_KM,
    OUT,
    bands_all,
    county_choice,
    county_name,
    distance_table,
    gpd,
    high_beyond_all_touched,
    homes_in_high_hazard,
    isochrone_failures,
    json,
    osm_timestamp,
    results,
    results_county_only,
    run_started,
    stage_seconds,
    station_check,
    stations,
    time,
):
    results.to_csv(OUT / "reach_bands.csv", index=False)
    distance_table.to_csv(OUT / "high_hazard_distance_to_reach.csv", index=False)
    results_county_only.to_csv(OUT / "reach_bands_county_stations_only.csv", index=False)
    county_choice.to_csv(OUT / "county_choice.csv", index=False)
    stations.drop(columns="geometry").assign(lon=stations.geometry.x.round(5), lat=stations.geometry.y.round(5)).to_csv(
        OUT / "stations.csv", index=False
    )
    gpd.GeoDataFrame(
        {"minutes": list(bands_all)}, geometry=[g.simplify(0.0005) for g in bands_all.values()], crs=4326
    ).to_file(OUT / "reach_bands.geojson", driver="GeoJSON")
    stage_seconds["total"] = time.perf_counter() - run_started
    summary = {
        "county": county_name,
        "osm_data_as_of": osm_timestamp,
        "stations_routed": {
            "in_county": int(stations.in_county.sum()),
            f"within_{BUFFER_KM}_km_outside": int((~stations.in_county).sum()),
            "isochrone_failures": len(isochrone_failures),
        },
        "station_check_vs_osm": station_check,
        "shares": {
            row.band: {
                "housing_units": round(row.housing_units_share, 4),
                "people": round(row.people_share, 4),
                "high_hazard_land": round(row.high_hazard_km2_share, 4),
                "all_land": round(row.land_km2_share, 4),
            }
            for row in results.itertuples()
        },
        "high_hazard_land_share_county_stations_only": dict(
            zip(BAND_LABELS.values(), results_county_only.high_hazard_km2_share.round(4), strict=True)
        ),
        "totals": {
            "housing_units": int(results.housing_units.sum()),
            "people": int(results.people.sum()),
            "high_hazard_km2": round(results.high_hazard_km2.sum()),
            "land_km2": round(results.land_km2.sum()),
        },
        "high_hazard_beyond_30_by_distance_to_reach": {
            row[0]: round(row[2], 4) for row in distance_table.itertuples(index=False)
        },
        "high_hazard_beyond_30_if_any_touched_cell_counts": round(high_beyond_all_touched, 4),
        "homes_in_high_hazard": {k: int(v) for k, v in homes_in_high_hazard.items()},
        "run_seconds": {k: round(v) for k, v in stage_seconds.items()},
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    print(json.dumps(summary, indent=2))
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What didn't work, and what this doesn't show

    - **Two station layers were one.** The issue asked for HIFLD's fire stations and its EMS stations; HIFLD Next
      has a single combined layer from the USGS National Map, with one feature code for both.
    - **The MCP server caps SQL at 8 KiB.** A county outline at full detail is several times that, so the outline is
      buffered and simplified before it goes into the query, and the exact cut happens here afterwards.
    - **Wildfire Risk to Communities' 30 m rasters** come as one 11 GB zip per state for California, so hazard comes
      from the 270 m national WHP file instead. Shares of land are therefore at 270 m resolution.
    - **Isochrones follow roads.** Valhalla's 30-minute polygons are strips along the roads, often narrower than a
      270 m hazard cell, so the share of land "beyond 30 minutes" depends on how far from a road counts as reached.
      That is why the result is also given by distance from reach, and with any touched cell counted.
    - **Census details.** The per-county TIGER/Line PL block file has no population or housing counts (the
      state-wide 2020 block file does), and OGR's `COUNTYFP20 = '073'` filter on that file silently returns nothing,
      so blocks are picked by GEOID prefix.
    - **Neither station list is complete.** A quarter of HIFLD's stations have no OSM station within 300 m, and
      for most of them the nearest OSM station is a different station, so OSM is missing them; only a few are the
      same station plotted in a different spot. OSM in turn has federal (Navy) stations, hotshot crews, academies and
      airport crash crews that HIFLD lacks. See `outputs/station_differences.csv`.
    - **Road reach is not response.** No turnout time, traffic, staffing, engine type, aircraft, staging or travel
      off the road network. Stations across the Mexican border aren't in HIFLD and aren't counted.
    """)
    return


if __name__ == "__main__":
    app.run()

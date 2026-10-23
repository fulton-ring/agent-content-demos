import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import logging
    import os
    import time
    import zipfile
    from datetime import date, timedelta
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
    import xarray as xr
    from rasterio.coords import disjoint_bounds
    from rasterio.merge import merge
    from rasterio.transform import rowcol
    from rasterio.windows import Window, from_bounds
    from scipy.stats import spearmanr
    from sklearn.metrics import roc_auc_score

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log = logging.getLogger("ofl")
    started = time.time()
    cache = Path(os.environ.get("OFL_CACHE", Path.home() / ".cache" / "open-flood-layer-vs-nfhl"))
    cache.mkdir(parents=True, exist_ok=True)
    results = Path(__file__).parent / "results"
    results.mkdir(exist_ok=True)
    ALBERS = "EPSG:5070"  # CONUS Albers, the CRS of OWP's HAND rasters; distances and areas in metres
    COUNTY = "48201"  # Harris County, TX
    HARVEY = ("2017-08-25", "2017-09-05")  # landfall to the last reservoir-release peaks
    BBOX = (-95.97, 29.49, -94.90, 30.18)  # Harris County, lon/lat
    return (
        ALBERS,
        BBOX,
        COUNTY,
        HARVEY,
        Path,
        Window,
        cache,
        date,
        disjoint_bounds,
        from_bounds,
        gpd,
        json,
        log,
        merge,
        mo,
        np,
        pd,
        plt,
        rasterio,
        requests,
        results,
        roc_auc_score,
        rowcol,
        spearmanr,
        started,
        time,
        timedelta,
        wbw,
        xr,
        zipfile,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Can an open flood layer beat FEMA's flood map at finding Harvey's damage?

    FEMA's National Flood Hazard Layer (NFHL) marks the Special Flood Hazard Area (SFHA), the
    land FEMA's studies put inside the 1%-a-year flood. It is what lenders, insurers and planners
    use. It is also slow: Harris County's maps date from 2007, with panels revised in 2013–2019.

    Open data now covers the same ground: NOAA's HAND terrain model of the stream network, the
    National Water Model's flows, USGS 3DEP elevation and NOAA Atlas 14 rainfall. **Does a layer
    built only from those rank places by observed flood damage better than the SFHA does?**

    Public damage data is only good to the census block group, so that is the unit here. The test
    is Harris County, Texas, in Hurricane Harvey (August 2017). Harvey's rain far exceeded the 1%
    event across much of the county, so no 1% map should be expected to contain it. The question is
    only which layer ranks block groups closer to how badly they flooded.

    For each layer we compute, per block group, the share of buildings it flags. We score that share
    against two public answer keys and report Spearman rank correlation and AUC, with the SFHA as
    the baseline.
    """)


@app.cell
def _(Path, json, log, requests, time):
    def get(url: str, params: dict | None = None) -> requests.Response:
        """GET with up to 8 attempts and backoff; FEMA's and NOAA's servers drop connections now and then."""
        for attempt in range(8):
            try:
                r = requests.get(url, params=params, timeout=600)
                r.raise_for_status()
                return r
            except requests.RequestException as e:
                log.warning("attempt %d for %s failed: %s", attempt + 1, url, str(e)[:120])
                time.sleep(min(2 ** (attempt + 1), 60))
        raise RuntimeError(f"GET failed: {url} {params}")

    def fetch(url: str, path: Path, params: dict | None = None) -> Path:
        """Download url to path once, with up to 8 attempts and backoff."""
        if path.exists():
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(8):
            try:
                with requests.get(url, params=params, stream=True, timeout=600) as r:
                    r.raise_for_status()
                    tmp = path.with_suffix(path.suffix + ".part")
                    with open(tmp, "wb") as f:
                        f.writelines(r.iter_content(1 << 20))
                    tmp.rename(path)
                    log.info("downloaded %s (%.0f MB)", path.name, path.stat().st_size / 1e6)
                    return path
            except requests.RequestException as e:
                log.warning("attempt %d for %s failed: %s", attempt + 1, url, e)
                time.sleep(min(2 ** (attempt + 1), 60))
        raise RuntimeError(f"could not download {url}")

    def openfema(entity: str, filter_: str, select: str, path: Path) -> list[dict]:
        """All rows of one OpenFEMA query, 10,000 at a time, cached as JSON.

        OpenFEMA times out on deep pages and on $inlinecount, so callers keep each filter small
        (one day or a few days) and we page until a short page comes back.
        """
        if path.exists():
            return json.loads(path.read_text())
        rows: list[dict] = []
        for page in range(100):  # 1 million rows is far beyond any one filter here
            params = {"$filter": filter_, "$select": select, "$top": 10000, "$skip": page * 10000}
            for attempt in range(8):
                try:
                    r = requests.get(f"https://www.fema.gov/api/open/{entity}", params=params, timeout=300)
                    r.raise_for_status()
                    batch = r.json()[entity.split("/")[-1]]
                    break
                except (requests.RequestException, ValueError, KeyError) as e:
                    log.warning("OpenFEMA attempt %d (%s) failed: %s", attempt + 1, filter_, str(e)[:120])
                    time.sleep(min(2 ** (attempt + 1), 60))
            else:
                raise RuntimeError(f"OpenFEMA query failed: {entity} {filter_}")
            rows += batch
            if len(batch) < 10000:
                break
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rows))
        return rows

    return fetch, get, openfema


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Block groups and buildings

    OpenFEMA tags claims, policies and aid registrations with a 12-digit census block group
    (`censusGeoid`). Aid registrations say they use 2010 block groups. NFIP records turn out to mix
    vintages: every one matches a 2010 or a 2020 block group, but about a sixth match only a 2020
    one. We work in 2010 block groups (dropping water-only ones) and move each 2020-only code to
    the 2010 block group holding most of its buildings.

    Buildings come from the USACE National Structure Inventory (NSI), about 1.45 million points
    in Harris County. Each layer is scored by the share of a block group's NSI buildings it flags,
    so a block group's score doesn't depend on its size.
    """)


@app.cell
def _(ALBERS, COUNTY, cache, fetch, gpd):
    _zip = fetch(
        f"https://www2.census.gov/geo/tiger/TIGER2010/BG/2010/tl_2010_{COUNTY}_bg10.zip",
        cache / f"tl_2010_{COUNTY}_bg10.zip",
    )
    block_groups = gpd.read_file(_zip).to_crs(ALBERS)
    block_groups = block_groups[block_groups.ALAND10 > 0][["GEOID10", "geometry"]].rename(columns={"GEOID10": "bg"})
    _zip20 = fetch("https://www2.census.gov/geo/tiger/TIGER2020/BG/tl_2020_48_bg.zip", cache / "tl_2020_48_bg.zip")
    block_groups_2020 = gpd.read_file(_zip20, where=f"COUNTYFP = '{COUNTY[2:]}'").to_crs(ALBERS)
    block_groups_2020 = block_groups_2020[["GEOID", "geometry"]].rename(columns={"GEOID": "bg2020"})
    print(f"{len(block_groups):,} 2010 block groups with land in Harris County; {len(block_groups_2020):,} in 2020")
    return block_groups, block_groups_2020


@app.cell
def _(ALBERS, COUNTY, block_groups, block_groups_2020, cache, fetch, gpd, pd):
    _parquet = cache / "nsi.parquet"
    if not _parquet.exists():
        _geojson = fetch(f"https://nsi.sec.usace.army.mil/nsiapi/structures?fips={COUNTY}", cache / "nsi.geojson")
        _nsi = gpd.read_file(_geojson, columns=["fd_id", "st_damcat", "occtype", "resunits"], engine="pyogrio")
        _nsi.to_crs(ALBERS).to_parquet(_parquet)
    structures = gpd.read_parquet(_parquet)
    structures = structures.sjoin(block_groups, predicate="within", how="inner").drop(columns="index_right")
    structures = structures.reset_index(drop=True)
    structures["residential"] = structures.st_damcat == "RES"
    _bg2020 = structures[["geometry"]].sjoin(block_groups_2020, predicate="within").bg2020
    _bg2020 = _bg2020[~_bg2020.index.duplicated()]
    # Each 2020 block group goes to the 2010 block group that holds most of its buildings.
    _pairs = pd.DataFrame({"bg2020": _bg2020, "bg": structures.bg.reindex(_bg2020.index)})
    _crosswalk = _pairs.groupby("bg2020").bg.agg(lambda b: b.value_counts().index[0])

    def to_2010(geoid: pd.Series) -> pd.Series:
        """2010 block group for each 12-digit OpenFEMA code; a code that isn't a 2010 one is read as 2020."""
        return geoid.where(geoid.isin(block_groups.bg), geoid.map(_crosswalk))

    print(
        f"{len(structures):,} NSI structures in a land block group, {structures.residential.mean():.0%} residential, "
        f"{structures.resunits.sum():,.0f} housing units"
    )
    return structures, to_2010


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Layer 1, the baseline: FEMA's SFHA

    We download Harris County's NFHL extract (`48201C`) from FEMA's Map Service Center. A building
    is in the **SFHA** if a zone with `SFHA_TF = T` (A, AE, AO, VE) covers it, and in **SFHA + 0.2%**
    if it is in the SFHA or the shaded X zone. This is today's NFHL, not the one in force in August
    2017, so we also count the buildings on map panels that took effect after Harvey.
    """)


@app.cell
def _(ALBERS, COUNTY, cache, fetch, gpd, pd, structures):
    # The Map Service Center redirects to the county's latest NFHL extract (48201C_<date>.zip).
    _zip = fetch(
        "https://msc.fema.gov/portal/downloadProduct",
        cache / f"nfhl_{COUNTY}C.zip",
        {"productTypeID": "NFHL", "productSubTypeID": "NFHL_COUNTY_DATA", "productID": f"NFHL_{COUNTY}C"},
    )
    nfhl_zones = gpd.read_file(f"zip://{_zip}!S_FLD_HAZ_AR.shp").to_crs(ALBERS)
    nfhl_panels = gpd.read_file(f"zip://{_zip}!S_FIRM_PAN.shp").to_crs(ALBERS)
    _sfha = nfhl_zones[nfhl_zones.SFHA_TF == "T"]
    _x02 = nfhl_zones[nfhl_zones.ZONE_SUBTY.fillna("").str.contains("0.2")]
    _in_sfha = structures.sjoin(_sfha[["geometry"]], predicate="within").index.unique()
    _in_x02 = structures.sjoin(_x02[["geometry"]], predicate="within").index.unique()
    _panel = structures[["geometry"]].sjoin(nfhl_panels[["EFF_DATE", "geometry"]], predicate="within")
    _panel = _panel[~_panel.index.duplicated()]
    nfhl_flags = pd.DataFrame(index=structures.index)
    nfhl_flags["sfha"] = structures.index.isin(_in_sfha)
    nfhl_flags["sfha_02"] = nfhl_flags.sfha | structures.index.isin(_in_x02)
    nfhl_flags["panel_after_harvey"] = (pd.to_datetime(_panel.EFF_DATE) > "2017-08-25").reindex(
        structures.index, fill_value=False
    )
    print(
        f"{len(nfhl_zones):,} zones. SFHA flags {nfhl_flags.sfha.mean():.1%} of buildings, "
        f"SFHA + 0.2% {nfhl_flags.sfha_02.mean():.1%}. "
        f"{nfhl_flags.panel_after_harvey.mean():.1%} of buildings sit on panels made effective after Harvey."
    )
    return (nfhl_flags,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Layer 2: NOAA OWP HAND, static and driven by Harvey's flows

    OWP's HAND-FIM 4.9.9.0 (the model behind NWS flood inundation maps, mirrored publicly by
    CIROH) gives every 10 m cell its **height above nearest drainage** and the stream reach it
    drains to. OWP computes HAND per stream "branch"; a cell's HAND is its lowest across branches.

    We read it two ways:

    - **Low HAND**, a static hazard layer: the buildings lowest above their stream, with the cut-off
      set so it flags exactly as many buildings as the SFHA. The two layers then differ only in
      *which* buildings they flag.
    - **HAND-FIM, Harvey flows**: what NWS's flood inundation mapping would have drawn. For each
      reach we take Harvey's peak flow from the National Water Model retrospective (v3.0, public on
      AWS), turn it into a stage with OWP's rating curve for that reach (`hydrotable`), and flag a
      building if its HAND is at or below that stage. This is an event map, not a 1% map: it shows
      what an open model refreshed at the time of the flood would have drawn.

    OWP's own 100-year flows sit in a requester-pays bucket, so a 1%-flow HAND map isn't in this run.
    """)


@app.cell
def _(BBOX, cache, fetch, get, pd):
    _r = get(
        "https://hydro.nationalmap.gov/arcgis/rest/services/wbd/MapServer/4/query",
        params={
            "geometry": ",".join(map(str, BBOX)),
            "geometryType": "esriGeometryEnvelope",
            "inSR": 4326,
            "outFields": "huc8",
            "returnGeometry": "false",
            "f": "json",
        },
    )
    hucs = sorted(f["attributes"]["huc8"] for f in _r.json()["features"])
    owp = "https://ciroh-owp-hand-fim.s3.us-east-2.amazonaws.com/hand_fim_4_9_9_0"
    hydrotable = pd.concat(
        [pd.read_parquet(fetch(f"{owp}/{h}/hydrotable.parquet", cache / "owp" / f"{h}.parquet")) for h in hucs]
    ).reset_index()
    hydrotable = hydrotable[["HUC", "branch_id", "HydroID", "feature_id", "stage", "discharge_cms", "LakeID"]]
    hydrotable = hydrotable.astype({"HydroID": "int64", "feature_id": "int64"})  # stored as strings
    print(f"HUC8s touching the county: {', '.join(hucs)}; {hydrotable.feature_id.nunique():,} NWM reaches")
    return hucs, hydrotable, owp


@app.cell
def _(HARVEY, cache, hydrotable, np, pd, xr):
    _path = cache / "nwm_harvey_peaks.parquet"
    if not _path.exists():
        _ds = xr.open_zarr(
            "https://noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com/CONUS/zarr/chrtout.zarr",
            storage_options={"client_kwargs": {"trust_env": True}},
            consolidated=True,
        )
        _ids = np.sort(hydrotable.feature_id.unique())
        _idx = np.flatnonzero(np.isin(_ds.feature_id.values, _ids))
        _peak = _ds.streamflow.sel(time=slice(*HARVEY)).isel(feature_id=_idx).max("time").compute()
        pd.DataFrame({"feature_id": _peak.feature_id.values, "peak_cms": _peak.values}).to_parquet(_path)
    harvey_peaks = pd.read_parquet(_path)
    print(f"Harvey peak flow for {len(harvey_peaks):,} reaches; median {harvey_peaks.peak_cms.median():.0f} m³/s")
    return (harvey_peaks,)


@app.cell
def _(mo):
    mo.md(r"""
    How good are those simulated flows? NWM links some reaches to USGS gauges, so we compare its
    Harvey peak with each Harris County gauge's observed instantaneous peak.
    """)


@app.cell
def _(BBOX, HARVEY, cache, get, np, pd, results, xr):
    _path = cache / "nwm_vs_usgs.parquet"
    if not _path.exists():
        _ds = xr.open_zarr(
            "https://noaa-nwm-retrospective-3-0-pds.s3.amazonaws.com/CONUS/zarr/chrtout.zarr",
            storage_options={"client_kwargs": {"trust_env": True}},
            consolidated=True,
        )
        _gage = np.char.strip(_ds.gage_id.values.astype(str))
        _lat, _lon = _ds.latitude.values, _ds.longitude.values
        _idx = np.flatnonzero(
            (_gage != "") & (_lon >= BBOX[0]) & (_lon <= BBOX[2]) & (_lat >= BBOX[1]) & (_lat <= BBOX[3])
        )
        _nwm = _ds.streamflow.sel(time=slice(*HARVEY)).isel(feature_id=_idx).max("time").compute()
        _sites = list(_gage[_idx])
        _usgs = get(
            "https://waterservices.usgs.gov/nwis/iv/",
            {
                "format": "json",
                "sites": ",".join(_sites),
                "startDT": HARVEY[0],
                "endDT": HARVEY[1],
                "parameterCd": "00060",
            },
        ).json()["value"]["timeSeries"]
        _obs = {
            t["sourceInfo"]["siteCode"][0]["value"]: (
                t["sourceInfo"]["siteName"],
                max((float(v["value"]) for v in t["values"][0]["value"]), default=np.nan) / 35.3147,
            )
            for t in _usgs
        }
        pd.DataFrame(
            {
                "site": _sites,
                "name": [_obs.get(s, ("", np.nan))[0] for s in _sites],
                "nwm_peak_cms": _nwm.values,
                "usgs_peak_cms": [_obs.get(s, ("", np.nan))[1] for s in _sites],
            }
        ).to_parquet(_path)
    gauges = pd.read_parquet(_path).dropna().query("usgs_peak_cms > 0")
    gauges["nwm_over_usgs"] = gauges.nwm_peak_cms / gauges.usgs_peak_cms
    print(
        f"{len(gauges)} gauged reaches. NWM / observed Harvey peak: median {gauges.nwm_over_usgs.median():.2f}, "
        f"{(gauges.nwm_over_usgs.between(0.5, 2)).mean():.0%} within a factor of 2."
    )
    gauges.sort_values("nwm_over_usgs", ascending=False).round(2).to_csv(results / "nwm_vs_usgs.csv", index=False)
    gauges.sort_values("nwm_over_usgs", ascending=False).round(2)
    return


@app.cell
def _(harvey_peaks, hydrotable, np, pd):
    # Stage at Harvey's peak flow for every (branch, HydroID), from OWP's rating curves.
    _ht = hydrotable.merge(harvey_peaks, on="feature_id").sort_values(["branch_id", "HydroID", "discharge_cms"])
    _stages = []
    for (_branch, _hydroid), _g in _ht.groupby(["branch_id", "HydroID"], sort=False):
        _stages.append((_branch, _hydroid, float(np.interp(_g.peak_cms.iloc[0], _g.discharge_cms, _g.stage))))
    harvey_stage = pd.DataFrame(_stages, columns=["branch_id", "HydroID", "stage"])
    print(f"{len(harvey_stage):,} catchments; median Harvey stage {harvey_stage.stage.median():.1f} m")
    return (harvey_stage,)


@app.cell
def _(
    Window,
    cache,
    disjoint_bounds,
    fetch,
    from_bounds,
    harvey_stage,
    hucs,
    log,
    nfhl_flags,
    np,
    owp,
    pd,
    rasterio,
    rowcol,
    structures,
):
    _x, _y = structures.geometry.x.to_numpy(), structures.geometry.y.to_numpy()
    hand_min = np.full(len(structures), np.inf, dtype="float32")
    hand_fim = np.zeros(len(structures), dtype=bool)
    _stage = harvey_stage.set_index(["branch_id", "HydroID"]).stage
    for _huc in hucs:
        _branches = pd.read_csv(
            fetch(f"{owp}/{_huc}/branch_ids.csv", cache / "owp" / f"{_huc}_branches.csv"), header=None
        )
        for _branch in _branches[1]:
            _base = f"/vsicurl/{owp}/{_huc}/branches/{_branch}"
            _prefix = int(
                fetch(
                    f"{owp}/{_huc}/branches/{_branch}/hydroid_prefix.txt",
                    cache / "owp" / f"{_huc}_{_branch}_prefix.txt",
                ).read_text()
            )
            with (
                rasterio.open(f"{_base}/rem_zeroed_masked_{_branch}.tif") as _hs,
                rasterio.open(f"{_base}/gw_catchments_reaches_filtered_addedAttributes_{_branch}.tif") as _cs,
            ):
                if disjoint_bounds(structures.total_bounds, _hs.bounds):
                    continue
                _win = from_bounds(*structures.total_bounds, _hs.transform).round_offsets().round_lengths()
                _win = _win.intersection(Window(0, 0, _hs.width, _hs.height))
                _t = _hs.window_transform(_win)
                _row, _col = rowcol(_t, _x, _y)
                _row, _col = np.asarray(_row), np.asarray(_col)
                _inside = (_row >= 0) & (_row < _win.height) & (_col >= 0) & (_col < _win.width)
                _hand = _hs.read(1, window=_win)[_row[_inside], _col[_inside]].astype("float32")
                _catch = _cs.read(1, window=_win)[_row[_inside], _col[_inside]].astype("int64")
            _valid = (_hand != 32767) & (_catch > 0)
            _hand_m = np.where(_valid, _hand / 1000, np.inf)  # this release stores HAND in int16 millimetres
            _hydroid = _prefix * 10000 + _catch
            _s = _stage.reindex(pd.MultiIndex.from_arrays([np.full(len(_hydroid), _branch), _hydroid])).to_numpy(
                dtype="float64"
            )
            _idx = np.flatnonzero(_inside)
            hand_min[_idx] = np.minimum(hand_min[_idx], _hand_m)
            hand_fim[_idx] |= _valid & (_hand_m <= np.nan_to_num(_s, nan=-1.0))
            log.info("HUC %s branch %s: %d buildings covered", _huc, _branch, int(_valid.sum()))
    # The static layer flags the same share of buildings as the SFHA, so the two differ only in *which* buildings.
    hand_cut = float(np.quantile(hand_min, nfhl_flags.sfha.mean()))
    hand_flags = pd.DataFrame(
        {"hand_m": hand_min, "hand_low": hand_min <= hand_cut, "hand_fim": hand_fim}, index=structures.index
    )
    print(
        f"HAND covers {np.isfinite(hand_min).mean():.0%} of buildings; {(hand_min <= 1).mean():.1%} sit 1 m or less "
        f"above their stream. HAND ≤ {hand_cut:.2f} m flags the SFHA's share, {hand_flags.hand_low.mean():.1%}. "
        f"HAND-FIM at Harvey flows flags {hand_flags.hand_fim.mean():.1%}."
    )
    return hand_cut, hand_flags


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Layer 3: a pluvial proxy from 3DEP depressions and Atlas 14

    Rain that can't reach a mapped stream pools in low spots. The simplest open proxy fills every
    depression in the 3DEP 1/3 arc-second (about 10 m) DEM with WhiteboxTools and flags a building
    whose ground sits **0.3 m (1 ft) or more below the depression's spill level**.

    Atlas 14 rainfall was meant to say which depressions fill. We sample NOAA's 100-year, 24-hour
    depth across the county to see how much it varies. It turns out nearly flat across the county
    and far below Harvey's totals, so it can't rank one depression above another, and the proxy
    uses depth alone.
    """)


@app.cell
def _(BBOX, get, json, np):
    _lons, _lats = np.linspace(BBOX[0], BBOX[2], 4), np.linspace(BBOX[1], BBOX[3], 3)
    atlas14 = []
    for _lat in _lats:
        for _lon in _lons:
            _r = get(
                "https://hdsc.nws.noaa.gov/cgi-bin/new/cgi_readH5.py",
                params={
                    "lat": f"{_lat:.3f}",
                    "lon": f"{_lon:.3f}",
                    "type": "pf",
                    "data": "depth",
                    "units": "english",
                    "series": "pds",
                },
            )
            # NOAA returns a JavaScript literal; quantiles[duration][return period], row 9 = 24 h, column 6 = 100 yr.
            _q = json.loads(_r.text.split("quantiles = ")[1].split(";")[0].replace("'", '"'))
            atlas14.append(float(_q[9][6]))
    print(
        f"Atlas 14 100-year 24-hour rain across Harris County: {min(atlas14):.1f}–{max(atlas14):.1f} in "
        f"at {len(atlas14)} points. Harvey dropped 30–50 in over four days."
    )
    return (atlas14,)


@app.cell
def _(BBOX, cache, log, merge, rasterio, wbw):
    _dem_path, _sink_path = cache / "dem_13.tif", cache / "depth_in_sink.tif"
    if not _dem_path.exists():
        _tiles = [
            f"/vsicurl/https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current/{t}/USGS_13_{t}.tif"
            for t in ("n30w096", "n31w096", "n30w095", "n31w095")
        ]
        _dem, _transform = merge(_tiles, bounds=BBOX)
        _profile = {
            "driver": "GTiff",
            "dtype": "float32",
            "count": 1,
            "height": _dem.shape[1],
            "width": _dem.shape[2],
            "crs": "EPSG:4269",
            "transform": _transform,
            "nodata": -999999.0,
            "compress": "deflate",
            "tiled": True,
        }
        with rasterio.open(_dem_path, "w", **_profile) as _dst:
            _dst.write(_dem[0].astype("float32"), 1)
        log.info("DEM %s cells", _dem.shape)
    if not _sink_path.exists():
        _wbe = wbw.WbEnvironment()
        _wbe.verbose = False
        _depth = _wbe.hydrology.depth_in_sink(dem=_wbe.read_raster(str(_dem_path)), zero_background=True)
        _wbe.write_raster(_depth, str(_sink_path))
    sink_path = _sink_path
    return (sink_path,)


@app.cell
def _(hand_flags, nfhl_flags, np, pd, rasterio, rowcol, sink_path, structures):
    _pts = structures.geometry.to_crs("EPSG:4269")
    with rasterio.open(sink_path) as _src:
        _row, _col = rowcol(_src.transform, _pts.x.to_numpy(), _pts.y.to_numpy())
        _depth = _src.read(1)[np.asarray(_row), np.asarray(_col)]
    flags = pd.concat([structures[["bg", "resunits"]], nfhl_flags, hand_flags], axis=1)
    flags["sink_m"] = np.where(_depth < 0, 0, _depth)
    flags["sink_30cm"] = flags.sink_m >= 0.3
    flags["hand_fim_or_sink"] = flags.hand_fim | flags.sink_30cm
    flags["hand_low_or_sink"] = flags.hand_low | flags.sink_30cm
    print(
        f"Depressions ≥ 0.3 m flag {flags.sink_30cm.mean():.1%} of buildings; "
        f"HAND-FIM or depression {flags.hand_fim_or_sink.mean():.1%}."
    )
    return (flags,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Answer key 1: NFIP claims per policy

    OpenFEMA's `NfipClaims` v3 tags each claim with its flood event and `causeOfDamage`: **2** is a
    river, stream or lake overflowing, **4** is rainfall accumulating where it fell. We count Harvey
    claims that paid something. The denominator is NFIP policies in force on 25 August 2017 from
    `NfipPolicies` v3, fetched three days of effective dates at a time across Texas (OpenFEMA times
    out filtering the 70-million-row table by county).

    Claims per policy measures how often insured buildings flooded, but insurance is not random:
    the SFHA's mandatory-purchase rule puts most policies inside it, and take-up outside it is low.
    """)


@app.cell
def _(COUNTY, cache, openfema, pd, to_2010):
    _rows = openfema(
        "v3/NfipClaims",
        f"startswith(censusGeoid,'{COUNTY}') and floodEvent eq 'Hurricane Harvey'",
        "censusGeoid,causeOfDamage,amountPaidOnBuildingClaim,amountPaidOnContentsClaim",
        cache / "openfema" / "claims_harvey.json",
    )
    _claims = pd.DataFrame(_rows)
    _claims = _claims[(_claims.amountPaidOnBuildingClaim.fillna(0) + _claims.amountPaidOnContentsClaim.fillna(0)) > 0]
    claims = _claims.assign(bg=to_2010(_claims.censusGeoid.str[:12]))
    print(
        f"{len(_rows):,} Harvey claims in Harris County, {len(claims):,} paid. "
        f"By cause: {claims.causeOfDamage.value_counts().to_dict()}"
    )
    return (claims,)


@app.cell
def _(COUNTY, cache, date, openfema, pd, timedelta, to_2010):
    _frames = []
    _start = date(2016, 8, 26)
    for _i in range(0, 366, 3):
        _a, _b = _start + timedelta(days=_i), _start + timedelta(days=min(_i + 3, 365))
        if _a >= _b:
            break
        _rows = openfema(
            "v3/NfipPolicies",
            f"propertyState eq 'TX' and policyEffectiveDate ge '{_a}' and policyEffectiveDate lt '{_b}'",
            "censusGeoid,policyTerminationDate,cancellationDateOfFloodPolicy",
            cache / "openfema" / "policies" / f"{_a}.json",
        )
        _frames.append(pd.DataFrame(_rows))
    _p = pd.concat(_frames, ignore_index=True)
    _p = _p[_p.censusGeoid.fillna("").str.startswith(COUNTY)]
    _cancel = pd.to_datetime(_p.cancellationDateOfFloodPolicy, utc=True)
    _in_force = (pd.to_datetime(_p.policyTerminationDate, utc=True) > "2017-08-25") & (
        _cancel.isna() | (_cancel > "2017-08-25")
    )
    policies = _p[_in_force].assign(bg=lambda d: to_2010(d.censusGeoid.str[:12]))
    print(f"{len(policies):,} NFIP policies in force in Harris County on 2017-08-25")
    return (policies,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Answer key 2: FEMA aid registrations with flood damage

    Most flooded homes in Harris County had no flood insurance. FEMA's Individuals and Households
    Program registrations for Harvey (DR-4332) cover them: `IndividualsAndHouseholdsProgramValidRegistrations`
    v2 records whether an inspector found **flood damage** (`floodDamage`). We count those per
    block group, fetched one application day at a time.

    These are registrations, not damage measurements: people had to apply, renters register too,
    and inspections weren't uniform.
    """)


@app.cell
def _(COUNTY, cache, date, openfema, pd, timedelta):
    _frames = []
    _start = date(2017, 8, 25)
    for _i in range(310):  # applications for DR-4332 ran into mid-2018
        _day = _start + timedelta(days=_i)
        _rows = openfema(
            "v2/IndividualsAndHouseholdsProgramValidRegistrations",
            f"disasterNumber eq 4332 and appliedDate eq '{_day}' and fips eq '{COUNTY}'",
            "censusGeoid,floodDamage,ownRent",
            cache / "openfema" / "ihp" / f"{_day}.json",
        )
        _frames.append(pd.DataFrame(_rows, columns=["censusGeoid", "floodDamage", "ownRent"]))
    ihp = pd.concat(_frames, ignore_index=True).assign(bg=lambda d: d.censusGeoid.str[:12])
    print(f"{len(ihp):,} valid Harvey registrations in Harris County, {ihp.floodDamage.sum():,} with flood damage")
    return (ihp,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. One row per block group

    Each layer becomes the share of a block group's buildings it flags. Each answer key becomes a
    rate: paid claims per policy (all causes, river and rainfall), paid claims per NSI building,
    and flood-damage registrations per NSI housing unit (renters register too, so an apartment
    building counts once per unit). A rate needs a denominator big enough to mean something, so
    per-policy keys use block groups with at least 25 policies and the others those with at least
    50 buildings or housing units.
    """)


@app.cell
def _(block_groups, claims, flags, ihp, pd, policies):
    LAYERS = {
        "sfha": "FEMA SFHA",
        "sfha_02": "FEMA SFHA + 0.2%",
        "hand_low": "OWP low HAND (SFHA's share)",
        "hand_fim": "OWP HAND-FIM, Harvey flows",
        "sink_30cm": "3DEP depression ≥ 0.3 m",
        "hand_low_or_sink": "Low HAND or depression",
        "hand_fim_or_sink": "HAND-FIM or depression",
    }
    _g = flags.groupby("bg")
    bg = pd.DataFrame({"buildings": _g.size(), "units": _g.resunits.sum()})
    bg = bg.join(_g[list(LAYERS)].mean())
    bg["policies"] = policies.groupby("bg").size()
    bg["claims"] = claims.groupby("bg").size()
    bg["claims_river"] = claims[claims.causeOfDamage == "2"].groupby("bg").size()
    bg["claims_rain"] = claims[claims.causeOfDamage == "4"].groupby("bg").size()
    bg["ihp_flood"] = ihp[ihp.floodDamage.fillna(False).astype(bool)].groupby("bg").size()
    bg = bg.fillna({c: 0 for c in ["policies", "claims", "claims_river", "claims_rain", "ihp_flood"]})
    bg = bg[bg.index.isin(block_groups.bg)]
    _many_policies, _many_buildings = bg.policies >= 25, bg.buildings >= 50
    KEYS = {
        "claims_per_policy": ("Paid claims per policy", bg.claims / bg.policies, _many_policies),
        "river_per_policy": ("River claims (cause 2) per policy", bg.claims_river / bg.policies, _many_policies),
        "rain_per_policy": ("Rainfall claims (cause 4) per policy", bg.claims_rain / bg.policies, _many_policies),
        "claims_per_building": ("Paid claims per NSI building", bg.claims / bg.buildings, _many_buildings),
        "ihp_per_unit": (
            "IHP flood-damage registrations per housing unit",
            bg.ihp_flood / bg.units.clip(lower=1),
            bg.units >= 50,
        ),
    }
    matched = {
        "claims": claims.bg.isin(bg.index).mean(),
        "policies": policies.bg.isin(bg.index).mean(),
        "ihp": ihp.bg.isin(bg.index).mean(),
        "claims_read_as_2020": (claims.censusGeoid.str[:12] != claims.bg).mean(),
        "policies_read_as_2020": (policies.censusGeoid.str[:12] != policies.bg).mean(),
    }
    print(
        f"{len(bg):,} block groups. Share of records placed in a 2010 block group: "
        + ", ".join(f"{k} {v:.1%}" for k, v in matched.items())
    )
    bg.describe().T.round(3)
    return KEYS, LAYERS, bg, matched


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. Score each layer against each key

    **Spearman ρ** asks whether a layer orders block groups the way the damage does. **AUC** asks
    how often a block group in the worst-hit fifth (by that key) gets a higher layer score than one
    outside it; 0.5 is a coin flip. Intervals are the 2.5th–97.5th percentiles of 500 bootstrap
    resamples of block groups. The difference from the SFHA is computed on the same resamples, so
    its interval says whether a layer beats the SFHA, not just whether the two intervals overlap.
    """)


@app.cell
def _(KEYS, LAYERS, bg, np, pd, roc_auc_score, spearmanr):
    _rng = np.random.default_rng(2017)
    _rows = []
    for _key, (_key_label, _rate, _keep) in KEYS.items():
        _y = _rate[_keep].to_numpy()
        _top = _y >= np.quantile(_y, 0.8)
        _boots = [_rng.integers(0, len(_y), len(_y)) for _ in range(500)]
        _sfha_b = None  # the SFHA's bootstrap scores, to take paired differences against
        for _layer, _layer_label in LAYERS.items():  # LAYERS starts with the SFHA
            _x = bg.loc[_keep, _layer].to_numpy()
            _b = np.array([(spearmanr(_x[i], _y[i]).statistic, roc_auc_score(_top[i], _x[i])) for i in _boots])
            _sfha_b = _b if _sfha_b is None else _sfha_b
            _lo, _hi = np.nanpercentile(_b, 2.5, axis=0), np.nanpercentile(_b, 97.5, axis=0)
            _dlo, _dhi = np.nanpercentile(_b - _sfha_b, 2.5, axis=0), np.nanpercentile(_b - _sfha_b, 97.5, axis=0)
            _rows.append(
                {
                    "key": _key_label,
                    "layer": _layer_label,
                    "block groups": len(_y),
                    "rho": spearmanr(_x, _y).statistic,
                    "rho_lo": _lo[0],
                    "rho_hi": _hi[0],
                    "auc": roc_auc_score(_top, _x),
                    "auc_lo": _lo[1],
                    "auc_hi": _hi[1],
                    "rho_vs_sfha_lo": _dlo[0],
                    "rho_vs_sfha_hi": _dhi[0],
                    "auc_vs_sfha_lo": _dlo[1],
                    "auc_vs_sfha_hi": _dhi[1],
                }
            )
    scores = pd.DataFrame(_rows)
    _base = scores[scores.layer == "FEMA SFHA"].set_index("key")
    scores["rho_vs_sfha"] = scores.rho - scores.key.map(_base.rho)
    scores["auc_vs_sfha"] = scores.auc - scores.key.map(_base.auc)
    return (scores,)


@app.cell
def _(results, scores):
    scores.round(3).to_csv(results / "scores.csv", index=False)
    _show = scores.copy()
    _show["Spearman ρ (95% CI)"] = _show.apply(lambda r: f"{r.rho:.2f} ({r.rho_lo:.2f}–{r.rho_hi:.2f})", axis=1)
    _show["AUC (95% CI)"] = _show.apply(lambda r: f"{r.auc:.2f} ({r.auc_lo:.2f}–{r.auc_hi:.2f})", axis=1)
    _show["ρ minus SFHA"] = _show.apply(
        lambda r: f"{r.rho_vs_sfha:+.2f} ({r.rho_vs_sfha_lo:+.2f} to {r.rho_vs_sfha_hi:+.2f})", axis=1
    )
    _show["AUC minus SFHA"] = _show.apply(
        lambda r: f"{r.auc_vs_sfha:+.2f} ({r.auc_vs_sfha_lo:+.2f} to {r.auc_vs_sfha_hi:+.2f})", axis=1
    )
    _show[["key", "layer", "block groups", "Spearman ρ (95% CI)", "AUC (95% CI)", "ρ minus SFHA", "AUC minus SFHA"]]
    return


@app.cell
def _(KEYS, LAYERS, plt, results, scores):
    _fig, _axes = plt.subplots(1, 2, figsize=(13, 5.5), sharey=True)
    _keys = [k[0] for k in KEYS.values()]
    _layers = list(LAYERS.values())
    for _ax, (_m, _label) in zip(_axes, [("rho", "Spearman ρ"), ("auc", "AUC, worst-hit fifth")], strict=True):
        for _j, _layer in enumerate(_layers):
            _s = scores[scores.layer == _layer].set_index("key").loc[_keys]
            _pos = [i + (_j - len(_layers) / 2) * 0.11 for i in range(len(_keys))]
            _ax.errorbar(
                _s[_m],
                _pos,
                xerr=[_s[_m] - _s[f"{_m}_lo"], _s[f"{_m}_hi"] - _s[_m]],
                fmt="o",
                ms=4,
                label=_layer,
                color="black" if _layer == "FEMA SFHA" else None,
            )
        _ax.axvline(0.5 if _m == "auc" else 0, color="grey", lw=0.8)
        _ax.set_xlabel(_label)
        _ax.set_yticks(range(len(_keys)), _keys)
    _axes[0].invert_yaxis()
    _fig.legend(*_axes[0].get_legend_handles_labels(), loc="lower center", ncol=4, fontsize=9)
    _fig.suptitle("Harris County block groups, Hurricane Harvey: each layer's share of flagged buildings vs damage")
    _fig.tight_layout(rect=(0, 0.09, 1, 1))
    _fig.savefig(results / "scores.png", dpi=130)
    _fig
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### Do the cut-offs matter?

    The HAND and depression cut-offs above were fixed before scoring. This sweep shows what other
    cut-offs would have given, against the two per-building keys. No cut-off lets either static
    layer reach the SFHA.
    """)


@app.cell
def _(KEYS, flags, pd, results, spearmanr):
    _rows = []
    _cuts = [("HAND ≤", "hand_m", c) for c in (0.5, 1, 2, 3, 5, 8)] + [
        ("depression ≥", "sink_m", c) for c in (0.01, 0.05, 0.1, 0.3, 0.6)
    ]
    for _name, _col, _cut in _cuts:
        _flag = flags[_col] <= _cut if _col == "hand_m" else flags[_col] >= _cut
        _share = _flag.groupby(flags.bg).mean()
        _row = {"layer": f"{_name} {_cut} m", "buildings flagged": f"{_flag.mean():.1%}"}
        for _key in ("claims_per_building", "ihp_per_unit"):
            _label, _rate, _keep = KEYS[_key]
            _row[f"ρ, {_label}"] = round(spearmanr(_share[_keep], _rate[_keep]).statistic, 3)
        _rows.append(_row)
    _sfha = flags.sfha.groupby(flags.bg).mean()
    _rows.append(
        {"layer": "FEMA SFHA", "buildings flagged": f"{flags.sfha.mean():.1%}"}
        | {
            f"ρ, {KEYS[k][0]}": round(spearmanr(_sfha[KEYS[k][2]], KEYS[k][1][KEYS[k][2]]).statistic, 3)
            for k in ("claims_per_building", "ihp_per_unit")
        }
    )
    _table = pd.DataFrame(_rows)
    _table.to_csv(results / "sensitivity.csv", index=False)
    _table
    return


@app.cell
def _(KEYS, bg, block_groups, plt, results):
    _label, _rate, _keep = KEYS["ihp_per_unit"]
    _m = block_groups.set_index("bg").join(bg[["sfha", "hand_fim", "sink_30cm"]]).assign(key=_rate.where(_keep))
    _fig, _axes = plt.subplots(1, 4, figsize=(18, 4.2))
    for _ax, (_col, _title) in zip(
        _axes,
        [
            ("sfha", "FEMA SFHA: share of buildings"),
            ("hand_fim", "OWP HAND-FIM, Harvey flows"),
            ("sink_30cm", "3DEP depression ≥ 0.3 m"),
            ("key", "IHP flood registrations per housing unit"),
        ],
        strict=True,
    ):
        _m.plot(
            column=_col,
            ax=_ax,
            cmap="Blues",
            vmin=0,
            vmax=_m[_col].quantile(0.97),
            legend=True,
            missing_kwds={"color": "lightgrey"},
            legend_kwds={"shrink": 0.6},
        )
        _ax.set_title(_title, fontsize=10)
        _ax.set_axis_off()
    _fig.suptitle("Harris County 2010 block groups (grey: fewer than 50 buildings)")
    _fig.tight_layout()
    _fig.savefig(results / "maps.png", dpi=110)
    _fig
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 9. Where each layer goes most wrong

    For the key that includes the uninsured (IHP flood registrations per housing unit) we rank block groups by the
    key and by each layer, and list the ones with the biggest gap each way: **missed** (heavy
    damage, layer rates them low) and **false alarm** (layer rates them high, little damage).
    The columns beside them are the clues for why.
    """)


@app.cell
def _(KEYS, LAYERS, bg, block_groups, pd, results):
    _label, _rate, _keep = KEYS["ihp_per_unit"]
    _d = bg[_keep].assign(key=_rate[_keep])
    _cent = block_groups.set_index("bg").geometry.centroid.to_crs("EPSG:4326")
    _d["lat"], _d["lon"] = _cent.y.reindex(_d.index).round(3), _cent.x.reindex(_d.index).round(3)
    _d["key_pct"] = _d.key.rank(pct=True)
    _cols = ["key", "buildings", "units", "policies", "claims_river", "claims_rain", *LAYERS, "lat", "lon"]
    _out = []
    for _layer, _layer_label in LAYERS.items():
        _gap = _d.key_pct - _d[_layer].rank(pct=True)
        for _kind, _idx in [("missed", _gap.nlargest(5).index), ("false alarm", _gap.nsmallest(5).index)]:
            _out.append(_d.loc[_idx, _cols].assign(layer=_layer_label, kind=_kind, gap=_gap[_idx].round(2)))
    worst = pd.concat(_out).rename_axis("block group").reset_index()
    worst.round(3).to_csv(results / "worst_block_groups.csv", index=False)
    worst[worst.layer.isin(["FEMA SFHA", "OWP HAND-FIM, Harvey flows", "3DEP depression ≥ 0.3 m"])].round(2)
    return (worst,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 10. What this shows, and what didn't work

    **No open layer beats the SFHA here.** Read the scores table by its "minus SFHA" columns:
    an interval entirely below zero means the layer ranks block groups worse than FEMA's map.

    - **Static open layers carry almost no signal at block-group level.** Low HAND, at the SFHA's
      share or any other cut-off in the sweep, barely tracks damage. Harris County is flat and
      laced with small NWM channels, so "low above the nearest stream" is everywhere. The 3DEP
      depression proxy is no better. Atlas 14 can't help it, since it varies little across the
      county.
    - **HAND only works once it knows the flow.** Driven by Harvey's simulated peak flows,
      HAND-FIM ties the SFHA on river claims and loses on the rest. That is an event map drawn
      with hindsight flows, not a hazard map anyone could have had in advance.
    - **Its worst misses trace to the flows, not the terrain.** NWM simulated Buffalo Bayou
      below Addicks and Barker at 12–18 times its gauged peak, because the model doesn't hold
      water behind the dams. The false alarms along Buffalo Bayou follow from that. Where NWM
      under-ran the gauges (Vince Bayou at 0.16×), HAND-FIM misses the flooded block groups
      nearby.
    - **The SFHA's own misses are places no 1% riverine map would catch:** neighbourhoods in
      the Addicks reservoir pool, east Houston and the Clear Creek corridor. That is where an
      open layer would have to earn its place.

    **Refresh speed.** Harris County's FIRMs date from 2007, and 26% of today's buildings sit
    on panels revised after Harvey (2019). The county-wide remap (MAAPnext) issued preliminary
    data in February 2026, with appeals scheduled for 2027 and effective maps not expected
    before 2028. The open inputs move faster:

    | Layer | Source cadence | Rebuild cost |
    |---|---|---|
    | FEMA NFHL | Countywide restudy every 10–20 years; LOMRs in between | Engineering study, years |
    | OWP HAND | New HAND-FIM releases each year (4.9.9.0, April 2026) | OWP's open pipeline, per HUC8 |
    | NWM flows | Operational run every hour; here, the 1979–2023 retrospective | Seconds to read Harvey's peaks |
    | 3DEP depressions | When new lidar reaches 3DEP (Harris tiles republished 2026) | About a minute on 4 CPUs |
    | Atlas 14 | Texas volume 11, 2018; Atlas 15 in progress | None; a lookup |

    Faster refresh doesn't help a layer that ranks damage worse, though. On this evidence an
    open layer is a complement to the SFHA, mainly as an event map once flows are known.
    """)


@app.cell
def _(bg, flags, json, matched, results, started, time):
    _summary = {
        "block_groups": int(len(bg)),
        "structures": int(len(flags)),
        "share_after_harvey_panels": round(float(flags.panel_after_harvey.mean()), 4),
        "share_flagged": {
            c: round(float(flags[c].mean()), 4)
            for c in ["sfha", "sfha_02", "hand_low", "hand_fim", "sink_30cm", "hand_fim_or_sink"]
        },
        "records_matched_to_2010_block_groups": {k: round(float(v), 4) for k, v in matched.items()},
        "run_minutes": round((time.time() - started) / 60, 1),
    }
    (results / "summary.json").write_text(json.dumps(_summary, indent=2))
    print(json.dumps(_summary, indent=2))
    return


if __name__ == "__main__":
    app.run()

import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import logging
    import os
    import time
    import zipfile
    from dataclasses import replace
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import numpy as np
    import pandas as pd
    import pathos.pools
    import requests
    from climada.hazard import Centroids, TCTracks, TropCyclone
    from remotezip import RemoteZip
    from requests.adapters import HTTPAdapter
    from scipy import sparse
    from urllib3.util.retry import Retry

    import fri

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log = logging.getLogger("recalibration")
    default_cache = Path.home() / ".cache" / "hurloss-public-rebuild"
    cache = Path(os.environ.get("HURLOSS_CACHE", default_cache))
    results = Path(os.environ.get("HURLOSS_RESULTS", Path(mo.notebook_dir() or ".") / "results"))
    workers = int(os.environ.get("HURLOSS_WORKERS", os.cpu_count() or 1))
    assert workers >= 1, "HURLOSS_WORKERS must be at least 1"
    (results / "recalibration").mkdir(parents=True, exist_ok=True)
    return (
        Centroids,
        HTTPAdapter,
        Path,
        RemoteZip,
        Retry,
        TCTracks,
        TropCyclone,
        cache,
        fri,
        gpd,
        log,
        mo,
        np,
        pathos,
        pd,
        replace,
        requests,
        results,
        sparse,
        time,
        workers,
        zipfile,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Does STORM's undercount of US hurricanes change our multipliers?

    Our hurricane layer (`notebook.py`, section 7) averages two storm catalogues. One of them,
    STORM's 10,000 synthetic years, puts only a half to a third of the hurricanes near the US
    coast that NOAA's National Hurricane Center (NHC) counts. Our projected losses are about
    half of FEMA's, so the question is whether that undercount is part of the reason.

    The test: reweight STORM's storms so its coastal hurricane counts match NHC's, rerun the
    same multiplier (FEMA's Eq. 11-12 with Knutson's changes applied to storm frequencies), and
    compare.

    One thing is settled before running anything. Eq. 11 is a weighted sum of storm
    frequencies, and Knutson's change multiplies those frequencies, so the multiplier is
    projected over today's intensity *in the same catalogue*. Multiply every storm's frequency
    by the same number and both sides scale together: the multiplier can't move. A
    recalibration can only change it by changing the *mix* of storms, either which categories
    or which stretch of coast gains the most. So the test runs three versions:

    1. **Uniform:** every storm × one factor. A check that the code agrees with the algebra.
    2. **By category:** storms bringing hurricane wind to the US get one factor if their
       strongest US wind is Category 3+ and another if it is Category 1-2, set so the 12 NHC
       sites match on average for majors and for all hurricanes.
    3. **By site and category:** the same two classes, with separate factors for each of the
       12 NHC sites. Each storm takes the factors of the site nearest its strongest wind on our
       grid.

    Storms that never bring hurricane wind to our grid keep their weight in versions 2 and 3:
    STORM's basin-wide counts are right, and they don't enter Eq. 11.
    """)
    return


@app.cell
def _(HTTPAdapter, Path, Retry, cache, log, pd, requests, results):
    # The same cache helpers as notebook.py, so both notebooks share one download cache.
    def cached(*parts: str) -> Path:
        """A path in the download cache, with its folder created."""
        path = cache.joinpath(*parts)
        path.parent.mkdir(parents=True, exist_ok=True)
        return path

    def session() -> requests.Session:
        # 429 is 4TU's rate limit; urllib3 waits for the server's Retry-After before retrying.
        retry = Retry(
            total=8,
            backoff_factor=10,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=None,
            respect_retry_after_header=True,
        )
        client = requests.Session()
        client.mount("https://", HTTPAdapter(max_retries=retry))
        return client

    def download(url: str, target: Path) -> Path:
        """Stream `url` to `target` unless it's already there; fail on any HTTP error."""
        if target.exists():
            return target
        partial = target.with_suffix(target.suffix + ".partial")
        with session().get(url, stream=True, timeout=600) as response:
            response.raise_for_status()
            with partial.open("wb") as handle:
                for block in response.iter_content(chunk_size=8 << 20):
                    handle.write(block)
        assert partial.stat().st_size > 0, f"empty download from {url}"
        return partial.rename(target)

    def write(table: pd.DataFrame, name: str, index: bool = False) -> None:
        table.to_csv(results / "recalibration" / name, index=index, float_format="%.6g")
        log.info("wrote %s (%d rows)", name, len(table))

    return cached, download, session, write


@app.cell
def _(mo):
    mo.md(r"""
    ## Inputs

    - **What to compare against** comes from the main notebook's committed results:
      `results/layer/fri_comparison_by_county.csv` (the 2,219 rated counties, their NRI v1.19
      EAL, FEMA's multiplier and rating, and which counties our layer covers) and
      `results/layer/county_multipliers.csv` (the observed-track catalogue's multiplier, which
      this notebook leaves alone). Run `notebook.py` first.
    - **Rating bins** come from FEMA's answer key, as in the main notebook.
    - **Grid and wind** are rebuilt exactly as in the main notebook, under the same cache names,
      so a warm cache from either notebook serves both.
    """)
    return


@app.cell
def _(cached, download, fri, pd, results):
    comparison = pd.read_csv(
        results / "layer" / "fri_comparison_by_county.csv", dtype={"STCOFIPS": str}
    ).set_index("STCOFIPS")
    layer = pd.read_csv(
        results / "layer" / "county_multipliers.csv", dtype={"unit": str}
    ).set_index("unit")
    assert len(comparison) == 4 * comparison.index.nunique(), "comparison isn't 4 scenarios"

    _url = (
        "https://raw.githubusercontent.com/fulton-ring/nri-future-risk/"
        "c5cc0d6686832f809446fc6061a689eff71d09df/public/"
        "NRI_Future_Risk_Master_Datasheet_12052024.xlsx"
    )
    _parquet = cached("answer_key", "hurricane.parquet")
    if not _parquet.exists():
        _sheet = pd.read_excel(
            download(_url, cached("answer_key", "NRI_Future_Risk_Master_Datasheet.xlsx"))
        )
        _sheet["STCOFIPS"] = _sheet["STCOFIPS"].astype(int).map("{:05d}".format)
        _kept = ["STCOFIPS", "STATEABBRV", "COUNTY", "HRCN_EALT", "HRCN_EALR"]
        _hm = [c for c in _sheet.columns if c.startswith("HRCN_") and c not in _kept]
        _sheet[_kept + _hm].to_parquet(_parquet)
    _key = pd.read_parquet(_parquet).set_index("STCOFIPS")
    bounds = fri.rating_bounds(
        _key[~_key["STATEABBRV"].isin(["AK", "HI", "AS", "GU", "MP", "PR", "VI"])]
    )
    return bounds, comparison, layer


@app.cell
def _(cached, download, gpd, np, pd, zipfile):
    # The main notebook's 0.25-degree grid and county mapping (points within 1 km of a county).
    _target = cached("geo", "counties_2020.parquet")
    if not _target.exists():
        _zip = download(
            "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_county_500k.zip",
            cached("geo", "cb_2020_us_county_500k.zip"),
        )
        _folder = cached("geo", "counties_2020", "x").parent
        with zipfile.ZipFile(_zip) as _handle:
            _handle.extractall(_folder)
        gpd.read_file(next(_folder.glob("*.shp"))).to_parquet(_target)
    _shapes = gpd.read_parquet(_target).rename(columns={"GEOID": "fips"}).set_index("fips")
    _shapes = _shapes[["geometry"]].to_crs("EPSG:5070")

    _lat, _lon = np.meshgrid(
        np.arange(24.0, 49.0, 0.25), np.arange(-107.0, -66.5, 0.25), indexing="ij"
    )
    _lat, _lon = _lat.ravel(), _lon.ravel()
    _points = gpd.GeoDataFrame(geometry=gpd.points_from_xy(_lon, _lat), crs="EPSG:4326")
    _points = _points.to_crs("EPSG:5070")
    _in_box = _shapes.cx[_points.total_bounds[0] : _points.total_bounds[2], :]
    _buffered = _in_box.assign(geometry=_in_box.buffer(1000.0)).reset_index(names="fips")
    _inside = gpd.sjoin(_points, _buffered, predicate="within")[["fips"]]
    _empty = _buffered[~_buffered["fips"].isin(_inside["fips"])]
    _nearest = gpd.sjoin_nearest(_empty[["fips", "geometry"]], _points)[["fips", "index_right"]]
    _pairs = pd.concat(
        [
            pd.DataFrame({"point": _inside.index.to_numpy(), "fips": _inside["fips"].to_numpy()}),
            pd.DataFrame({"point": _nearest["index_right"].to_numpy(), "fips": _nearest["fips"]}),
        ]
    )
    _used = np.sort(_pairs["point"].unique())
    _position = pd.Series(np.arange(len(_used)), index=_used)
    grid_lat, grid_lon = _lat[_used], _lon[_used]
    point_county = pd.Series(_pairs["fips"].to_numpy(), index=_position[_pairs["point"]].to_numpy())
    f"{grid_lat.size:,} grid points cover {point_county.nunique():,} counties"
    return grid_lat, grid_lon, point_county


@app.cell
def _(mo):
    mo.md(r"""
    ## STORM's present climate, 10,000 years

    The same ten 1,000-year North Atlantic files and the same CLIMADA wind fields as our layer.
    CLIMADA reads STORM directly (`TCTracks.from_simulations_storm`), converting its 10-minute
    winds to 1-minute by dividing by 0.88, and names each event `<file>-<year>-<storm>`, which
    is how storms are matched to the NHC check below. The wind fields take most of an hour on 4
    cores from an empty cache.
    """)
    return


@app.cell
def _(
    Centroids,
    RemoteZip,
    TCTracks,
    TropCyclone,
    cached,
    fri,
    grid_lat,
    grid_lon,
    log,
    np,
    pathos,
    session,
    sparse,
    time,
    workers,
):
    _url = (
        "https://data.4tu.nl/file/01b2ebc7-7903-42ef-b46b-f43b9175dbf4/"
        "78b72e86-b074-4478-9dc4-7280deb756ab"
    )
    storm_paths = [cached("storm", f"STORM_DATA_IBTRACS_NA_1000_YEARS_{i}.txt") for i in range(10)]
    _missing = [p for p in storm_paths if not p.exists()]
    if _missing:
        with RemoteZip(_url, session=session()) as _archive:
            for _target in _missing:
                _members = [
                    i for i in _archive.infolist() if i.filename.split("/")[-1] == _target.name
                ]
                assert len(_members) == 1, f"{_target.name} not found once in the STORM zip"
                _target.with_suffix(".partial").write_bytes(_archive.read(_members[0]))
                _target.with_suffix(".partial").rename(_target)

    _south, _north = grid_lat.min() - 2, grid_lat.max() + 2
    _west, _east = grid_lon.min() - 2, grid_lon.max() + 2
    _winds, _categories, _basins, _names = [], [], [], []
    for _index, _path in enumerate(storm_paths):
        _cached = cached("hazard", f"storm_present_file{_index}_grid0.25.h5")
        if not _cached.exists():
            _start = time.perf_counter()
            _pool = pathos.pools.ProcessPool(nodes=workers)
            _raw = TCTracks.from_simulations_storm(_path)
            # STORM gives longitude as 0-360; the grid uses -180-180. Keep tracks within 2°.
            _tracks = TCTracks(
                data=[
                    t
                    for t in (r.assign_coords(lon=((r.lon + 180) % 360) - 180) for r in _raw.data)
                    if (
                        (t.lat > _south) & (t.lat < _north) & (t.lon > _west) & (t.lon < _east)
                    ).any()
                ]
            )
            _tracks.equal_timestep(time_step_h=1.0, pool=_pool)
            _hazard = TropCyclone.from_tracks(
                _tracks,
                centroids=Centroids(lat=grid_lat, lon=grid_lon),
                pool=_pool,
                ignore_distance_to_coast=True,
            )
            _pool.close()
            _pool.join()
            _pool.clear()
            _hazard.pool = None
            _hazard.write_hdf5(_cached.with_suffix(".partial.h5"))
            _cached.with_suffix(".partial.h5").rename(_cached)
            log.info(
                "STORM file %d: %d tracks, %.0f s",
                _index,
                _tracks.size,
                time.perf_counter() - _start,
            )
        _hazard = TropCyclone.from_hdf5(_cached)
        assert np.allclose(_hazard.centroids.lat, grid_lat), f"{_cached.name} is on other points"
        _winds.append(sparse.csr_matrix(_hazard.intensity))
        _categories.append(np.asarray(_hazard.category))
        _basins.append(np.asarray(_hazard.basin))
        _names += list(_hazard.event_name)

    storm = fri.Events(
        wind=sparse.csr_matrix(sparse.vstack(_winds)),
        frequency=np.full(len(_names), 1 / 10_000),
        category=np.concatenate(_categories),
        basin=np.concatenate(_basins),
        years=(1980, 2018),
    )
    storm_names = np.array(_names)
    assert len(set(_names)) == len(_names), "STORM event names aren't unique"
    f"{len(_names):,} STORM storms come within 2° of the grid"
    return storm, storm_names, storm_paths


@app.cell
def _(mo):
    mo.md(r"""
    ## What each storm does at the NHC sites

    NHC's HURISK maps give how many years pass, on average, between hurricanes (≥ 64 kt) and
    between major hurricanes (≥ 96 kt) within 50 nautical miles of points on the coast (data
    through 2010, [nhc.noaa.gov/climo](https://www.nhc.noaa.gov/climo/)). These are the same
    12 sites and values, read off NHC's maps by eye, as the main notebook's check. For every
    STORM storm we record whether it passes each site at hurricane and at major strength,
    counted the same way as that check (any 3-hourly fix within 50 nm at that wind).
    """)
    return


@app.cell
def _(np, pd, storm_names, storm_paths):
    sites = pd.DataFrame(
        [
            ("Key West, FL", 24.56, -81.78, 8, 18),
            ("Miami, FL", 25.77, -80.19, 6, 14),
            ("West Palm Beach, FL", 26.71, -80.05, 8, 19),
            ("Tampa, FL", 27.95, -82.46, 9, 29),
            ("Jacksonville, FL", 30.33, -81.66, 10, 36),
            ("Charleston, SC", 32.78, -79.93, 8, 22),
            ("Myrtle Beach, SC", 33.69, -78.89, 8, 23),
            ("Wilmington, NC", 34.21, -77.89, 6, 17),
            ("Cape Hatteras, NC", 35.25, -75.53, 5, 16),
            ("New Orleans, LA", 29.95, -90.07, 8, 25),
            ("Galveston, TX", 29.30, -94.80, 11, 26),
            ("Long Island, NY", 40.80, -72.80, 18, 70),
        ],
        columns=["site", "lat", "lon", "nhc_hurricane_years", "nhc_major_years"],
    )
    _knots = 1.943844
    _row = pd.Series(np.arange(len(storm_names)), index=storm_names)
    passes_hurricane = np.zeros((len(storm_names), len(sites)), dtype=bool)
    passes_major = np.zeros_like(passes_hurricane)
    for _path in storm_paths:
        _raw = pd.read_csv(_path, header=None, usecols=[0, 2, 5, 6, 8])
        _raw.columns = ["year", "tc", "lat", "lon", "wind_ms"]
        _raw["lon"] = ((_raw["lon"] + 180) % 360) - 180
        _raw["wind_kt"] = _raw["wind_ms"] / 0.88 * _knots
        _raw = _raw[_raw["wind_kt"] >= 64.0]
        _event = _path.name + "-" + _raw["year"].astype(str) + "-" + _raw["tc"].astype(str)
        _lat1, _lon1 = np.radians(_raw["lat"].to_numpy()), np.radians(_raw["lon"].to_numpy())
        for _s, _site in sites.iterrows():
            _lat2, _lon2 = np.radians(_site["lat"]), np.radians(_site["lon"])
            _a = (
                np.sin((_lat2 - _lat1) / 2) ** 2
                + np.cos(_lat1) * np.cos(_lat2) * np.sin((_lon2 - _lon1) / 2) ** 2
            )
            _near = 2 * 6371.0 * np.arcsin(np.sqrt(_a)) <= 92.6  # 50 nautical miles
            for _kt, _passes in ((64.0, passes_hurricane), (96.0, passes_major)):
                _hit = _event[_near & (_raw["wind_kt"].to_numpy() >= _kt)].unique()
                assert set(_hit) <= set(_row.index), "a storm passing a site has no wind field"
                _passes[_row[_hit].to_numpy(), _s] = True
    _counts = pd.DataFrame(
        {
            "site": sites["site"],
            "storm_hurricane_years": 10_000 / passes_hurricane.sum(axis=0),
            "nhc_hurricane_years": sites["nhc_hurricane_years"],
            "storm_major_years": 10_000 / passes_major.sum(axis=0),
            "nhc_major_years": sites["nhc_major_years"],
        }
    )
    _counts
    return passes_hurricane, passes_major, sites


@app.cell
def _(mo):
    mo.md(r"""
    ## The three reweightings

    A storm's class comes from its wind on our grid: **major** if it reaches Category 3
    anywhere on the grid, **hurricane** if it reaches only Category 1-2, and **unchanged** if it
    never reaches Category 1 (it adds nothing to Eq. 11). For version 3 a storm's site is the
    NHC site nearest the grid point where its wind peaks.

    Each version's factors are set so STORM's modelled counts at the sites match NHC's:

    - **Uniform:** one factor, total hurricane passes over all 12 sites matched to NHC's total.
    - **By category:** the major factor matches total major passes; the hurricane factor then
      matches total hurricane passes (majors count as hurricanes too).
    - **By site and category:** 24 factors, updated in turn for a fixed 200 rounds, each
      multiplied by NHC's count over the model's at its own site. A storm passing several
      sites counts at each, so the fit is close but not exact; the table below shows how close.
    """)
    return


@app.cell
def _(
    fri, grid_lat, grid_lon, np, passes_hurricane, passes_major, pd, replace, sites, storm, write
):
    _peak = np.asarray(storm.wind.max(axis=1).todense()).ravel()
    _peak_point = np.asarray(storm.wind.argmax(axis=1)).ravel()
    _class = np.where(
        _peak >= fri.CATEGORY_FLOOR_MS[2], 2, np.where(_peak >= fri.CATEGORY_FLOOR_MS[0], 1, 0)
    )
    _dlat = grid_lat[_peak_point][:, None] - sites["lat"].to_numpy()[None, :]
    _dlon = (grid_lon[_peak_point][:, None] - sites["lon"].to_numpy()[None, :]) * np.cos(
        np.radians(grid_lat[_peak_point])
    )[:, None]
    _site = np.argmin(_dlat**2 + _dlon**2, axis=1)
    _missed = int(((passes_hurricane.any(axis=1)) & (_class == 0)).sum())

    _target_h = 1 / sites["nhc_hurricane_years"].to_numpy()
    _target_m = 1 / sites["nhc_major_years"].to_numpy()
    _base = storm.frequency

    def modelled(frequency: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Annual hurricane and major passes per NHC site."""
        return frequency @ passes_hurricane, frequency @ passes_major

    _uniform = _target_h.sum() / modelled(_base)[0].sum()

    _h0, _m0 = modelled(_base)
    _w_major = _target_m.sum() / _m0.sum()
    _from_majors = (_base * (_class == 2) * _w_major) @ passes_hurricane
    _from_rest = (_base * (_class == 1)) @ passes_hurricane
    _left_for_rest = (
        _target_h.sum()
        - _from_majors.sum()
        - (_base * (_class == 0)) @ passes_hurricane.sum(axis=1)
    )
    _w_hurricane = _left_for_rest / _from_rest.sum()
    assert _w_hurricane > 0, "majors alone already exceed NHC's hurricane count"
    _by_category = np.select([_class == 2, _class == 1], [_w_major, _w_hurricane], 1.0)

    _factors = np.ones((len(sites), 3))
    for _round in range(200):
        for _s in range(len(sites)):
            for _c, _passes, _target in (
                (2, passes_major, _target_m),
                (1, passes_hurricane, _target_h),
            ):
                _w = _factors[_site, _class]
                _w[_class == 0] = 1.0
                _model = (_base * _w) @ _passes[:, _s]
                _mine = (_site == _s) & (_class == _c)
                if _model > 0 and _mine.any():
                    _factors[_s, _c] *= _target[_s] / _model
    _by_site = _factors[_site, _class]
    _by_site[_class == 0] = 1.0

    weights = {
        "original": np.ones_like(_base),
        "uniform": np.full_like(_base, _uniform),
        "by_category": _by_category,
        "by_site_category": _by_site,
    }
    recalibrated = {v: replace(storm, frequency=_base * w) for v, w in weights.items()}

    _rows = []
    for _v, _events in recalibrated.items():
        _h, _m = modelled(_events.frequency)
        for _s, _site_row in sites.iterrows():
            _rows.append(
                {
                    "version": _v,
                    "site": _site_row["site"],
                    "hurricane_years": 1 / _h[_s],
                    "nhc_hurricane_years": _site_row["nhc_hurricane_years"],
                    "major_years": 1 / _m[_s],
                    "nhc_major_years": _site_row["nhc_major_years"],
                }
            )
    fit = pd.DataFrame(_rows)
    write(fit, "site_fit.csv")
    write(
        pd.DataFrame(
            {
                "site": sites["site"],
                "factor_hurricane_cat1_2": _factors[:, 1],
                "factor_major_cat3_plus": _factors[:, 2],
                "storms_hurricane": np.bincount(_site[_class == 1], minlength=len(sites)),
                "storms_major": np.bincount(_site[_class == 2], minlength=len(sites)),
            }
        ),
        "site_factors.csv",
    )
    _log_error = (
        fit.assign(
            h=np.log(fit["hurricane_years"] / fit["nhc_hurricane_years"]).abs(),
            m=np.log(fit["major_years"] / fit["nhc_major_years"]).abs(),
        )
        .groupby("version", sort=False)[["h", "m"]]
        .median()
    )
    (
        f"Uniform factor {_uniform:.2f}; by category: majors × {_w_major:.2f}, Cat 1-2 × "
        f"{_w_hurricane:.2f}. Storms passing a site at hurricane strength with no Category 1 "
        f"wind on the grid: {_missed}.",
        np.exp(_log_error).rename(columns={"h": "hurricane_x_off", "m": "major_x_off"}),
    )
    return fit, recalibrated, weights


@app.cell
def _(mo):
    mo.md(r"""
    The second table is the median factor by which a version misses NHC's return period at a
    site (1.00 is exact). `site_fit.csv` has every site.

    ## Multipliers after reweighting

    The same function as our layer: Knutson's median, frequency-only, each scenario, the
    multiplier floored at 1 and set to 1 where STORM has no Category 1 wind. Then the layer's
    central value: the mean of STORM's and the observed-track catalogue's multiplier where
    each has wind, the observed one unchanged from the main notebook.
    """)
    return


@app.cell
def _(bounds, comparison, fri, layer, np, pd, point_county, recalibrated, write):
    _rank = {name: rank for rank, name in enumerate(fri.RATINGS)}
    _original_storm = {}
    _rows, _counties = [], []
    for _v, _events in recalibrated.items():
        _today = fri.county_intensity(_events, point_county)
        for _s in fri.SCENARIOS:
            _p = comparison[comparison["scenario"] == _s].copy()
            _storm_hm = fri.ratio(
                fri.county_intensity(fri.frequency_only(_events, _s), point_county), _today
            ).clip(lower=1.0)
            _storm_hm = _storm_hm.reindex(_p.index)
            _historical = layer[f"{_s}_HM_HISTORICAL"].reindex(_p.index)
            _central = pd.concat([_storm_hm, _historical], axis=1).mean(axis=1).fillna(1.0)
            _p["storm_hm"] = _storm_hm
            _p["recalibrated_hm"] = _central
            _p["recalibrated_pal"] = _p["eal_v1_19"] * _central
            _p["recalibrated_rating"] = fri.rate(_p["recalibrated_pal"], bounds)
            _move = _p["recalibrated_rating"].map(_rank) - _p["fema_rating"].map(_rank)
            if _v == "original":
                _original_storm[_s] = _storm_hm
                # Our layer is rebuilt exactly before any reweighting; fail if it isn't.
                assert np.allclose(_central, _p["our_hm"], rtol=1e-4), "layer not reproduced"
            _cov = _p[_p["our_covered"]]
            _both = _cov[["storm_hm"]].assign(o=_original_storm[_s]).dropna()
            _rows.append(
                {
                    "version": _v,
                    "scenario": _s,
                    "storm_hm_median_covered": _cov["storm_hm"].median(),
                    "layer_hm_median_covered": _cov["recalibrated_hm"].median(),
                    "fema_hm_median_covered": _cov["fema_hm"].median(),
                    "projected_loss_total": _p["recalibrated_pal"].sum(),
                    "fema_projected_loss_total": _p["fema_pal"].sum(),
                    "rating_same_as_fema": float((_move == 0).mean()),
                    "storm_hm_spearman_vs_original": _both["storm_hm"].corr(
                        _both["o"], method="spearman"
                    ),
                    "storm_hm_max_change": float((_both["storm_hm"] - _both["o"]).abs().max()),
                    "layer_hm_spearman_vs_fema": _cov["recalibrated_hm"].corr(
                        _cov["fema_hm"], method="spearman"
                    ),
                }
            )
            _counties.append(
                _p[
                    [
                        "scenario",
                        "state",
                        "county",
                        "fema_hm",
                        "our_hm",
                        "storm_hm",
                        "recalibrated_hm",
                    ]
                ].assign(version=_v)
            )
    summary = pd.DataFrame(_rows)
    write(summary, "summary.csv")
    write(pd.concat(_counties), "county_multipliers.csv", index=True)
    summary.pivot(index="version", columns="scenario", values="layer_hm_median_covered")
    return (summary,)


@app.cell
def _(mo):
    mo.md(r"""
    Median multiplier over the 1,333 counties our layer covers. In full, with national
    projected loss on NRI v1.19 and rating agreement with FEMA (`summary.csv`):
    """)
    return


@app.cell
def _(summary):
    summary.round(3)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Why it moves as little or as much as it does

    Knutson's change is applied by each storm's lifetime peak category: Category 4-5 storms
    take Knutson's Cat 4-5 change (up), the rest take whatever keeps the all-storm change right
    (down). That second number depends on what share of the catalogue's storm rate is Category
    4-5, so a reweighting that raises strong landfalling storms more than weak ones changes it.
    Late century, higher warming, Knutson median:
    """)
    return


@app.cell
def _(fri, np, pd, recalibrated, write):
    _all = fri.knutson_percent("cat05", "LATE_HIGHER", "NA", (1980, 2018)) / 100
    _strong = fri.knutson_percent("cat45", "LATE_HIGHER", "NA", (1980, 2018)) / 100
    _rows = []
    for _v, _events in recalibrated.items():
        _is_strong = np.isin(_events.category, [4, 5])
        _share = _events.frequency[_is_strong].sum() / _events.frequency.sum()
        _rows.append(
            {
                "version": _v,
                "storms_per_year": _events.frequency.sum(),
                "cat4_5_share": _share,
                "cat4_5_change": _strong,
                "other_storms_change": (_all - _strong * _share) / (1 - _share),
            }
        )
    mechanism = pd.DataFrame(_rows)
    write(mechanism, "mechanism_late_higher.csv")
    mechanism.round(4)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What this doesn't show

    - NHC's return periods were read off its maps by eye at 12 sites; a neighbouring circle can
      differ by one class. Coast between sites takes the nearest site's factors.
    - It reweights STORM's storms; it doesn't fix why STORM brings too few to the US coast
      (its tracks, its decay over land, or its intensities). A storm that STORM never generates
      can't be reweighted into existence.
    - The observed-track catalogue, the other half of our layer, already matches or exceeds
      NHC's counts and is left as it is.
    """)
    return


if __name__ == "__main__":
    app.run()

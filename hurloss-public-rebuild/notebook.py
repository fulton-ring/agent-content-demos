import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import logging
    import os
    import time
    import zipfile
    from collections.abc import Callable
    from dataclasses import replace
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import pathos.pools
    import requests
    from climada.hazard import Centroids, TCTracks, TropCyclone
    from matplotlib.colors import LogNorm, Normalize
    from remotezip import RemoteZip
    from requests.adapters import HTTPAdapter
    from scipy import sparse
    from urllib3.util.retry import Retry

    import fri

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log = logging.getLogger("hurloss")
    default_cache = Path.home() / ".cache" / "hurloss-public-rebuild"
    cache = Path(os.environ.get("HURLOSS_CACHE", default_cache))
    results = Path(os.environ.get("HURLOSS_RESULTS", Path(mo.notebook_dir() or ".") / "results"))
    workers = int(os.environ.get("HURLOSS_WORKERS", os.cpu_count() or 1))
    assert workers >= 1, "HURLOSS_WORKERS must be at least 1"
    (results / "layer").mkdir(parents=True, exist_ok=True)
    return (
        Callable,
        Centroids,
        HTTPAdapter,
        LogNorm,
        Normalize,
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
        plt,
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
    # Can public data rebuild the hurricane part of FEMA's Future Risk Index?

    FEMA's Future Risk Index (FRI) scaled each county's hurricane loss by a *hazard multiplier*
    (HM) for four scenarios: mid-century (2050) and late century (2100), under lower (RCP 4.5)
    and higher (RCP 8.5) warming. The input was Applied Research Associates' (ARA)
    climate-conditioned HurLoss runs, which FEMA shares only by email. This notebook asks
    whether public storm tracks and published climate science can stand in for it
    ([issue #23](https://github.com/fulton-ring/agent-content-demos/issues/23)), then builds our
    own hurricane layer from open methods.

    **Short answer: no.** Public inputs rebuild today's hurricane hazard well. They don't
    rebuild FEMA's multipliers, because FEMA's multipliers are about 2.0 almost everywhere and
    no published climate projection comes near 2. Our own layer, on FEMA's documented formula,
    gives 1.04 to 1.15.

    FEMA's method (FRI technical document, Dec 2024, Sec. 7.2-7.3), which `fri.py` implements:

    - At each ARA point, $F_k$ is the annual frequency of wind reaching Saffir-Simpson
      Category $k$.
    - Eq. 11: intensity $= F_1 + 2F_2 + 4F_3 + 8F_4 + 16F_5$. A county's frequencies are the
      mean over points within 1 km of it.
    - Eq. 12: $HM = \max(1, \text{projected intensity} / \text{historical intensity})$.
    - Projected annual loss $=$ NRI hurricane expected annual loss (EAL) $\times$ HM, rated in
      NRI's fixed bins.

    Everything is downloaded at run time into `HURLOSS_CACHE`; tables and figures go to
    `results/`.
    """)
    return


@app.cell
def _(HTTPAdapter, Path, Retry, cache, log, pd, requests, results):
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

    def arcgis(layer: str, where: str, fields: list[str], target: Path, max_pages: int) -> Path:
        """All rows of an NRI ArcGIS feature-service query, cached as parquet."""
        if not target.exists():
            url = (
                "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
                f"{layer}/FeatureServer/0/query"
            )
            rows = []
            for page in range(max_pages):
                params = {
                    "where": where,
                    "outFields": ",".join(fields),
                    "returnGeometry": "false",
                    "resultOffset": page * 2000,
                    "resultRecordCount": 2000,
                    "orderByFields": fields[0],
                    "f": "json",
                }
                response = session().get(url, params=params, timeout=120)
                response.raise_for_status()
                payload = response.json()
                assert "features" in payload, f"{layer} returned no features: {payload}"
                rows += [feature["attributes"] for feature in payload["features"]]
                if len(payload["features"]) < 2000:
                    break
            else:
                raise RuntimeError(f"{layer} has more pages than expected")
            pd.DataFrame(rows).to_parquet(target)
        return target

    def write(table: pd.DataFrame, name: str, index: bool = False) -> None:
        table.to_csv(results / name, index=index, float_format="%.6g")
        log.info("wrote %s (%d rows)", name, len(table))

    return arcgis, cached, download, session, write


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. What FEMA published

    The answer key is FEMA's NRI Future Risk master datasheet, saved before FEMA removed the
    tool in February 2025 and published in
    [fulton-ring/nri-future-risk](https://github.com/fulton-ring/nri-future-risk) (the same
    file as the FRI rebuild in #15). It holds each county's `HRCN_*_HM`, its NRI v1.19
    hurricane EAL and its rating. We keep the contiguous US, since FEMA's hurricane coverage
    there is Atlantic-only.

    Before rebuilding anything, look at what a rebuild has to reproduce.
    """)
    return


@app.cell
def _(cached, download, fri, pd, write):
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
    key = pd.read_parquet(_parquet).set_index("STCOFIPS")
    assert key.index.is_unique, "answer key has duplicate county FIPS"
    key = key[~key["STATEABBRV"].isin(["AK", "HI", "AS", "GU", "MP", "PR", "VI"])]
    bounds = fri.rating_bounds(key)

    _rows = []
    for _s in fri.SCENARIOS:
        _hm = key[f"HRCN_{_s}_HM"]
        _q = _hm[_hm > 0].quantile([0.05, 0.25, 0.5, 0.75, 0.95]).to_numpy()
        _rows.append(
            {
                "scenario": _s,
                "counties": len(_hm),
                "zero": int((_hm == 0).sum()),
                "below_one": int(((_hm > 0) & (_hm < 1)).sum()),
                "at_cap_10": int((_hm == 10).sum()),
                "share_near_2": float(_hm[_hm > 0].between(1.9, 2.1).mean()),
                **dict(zip(["p05", "p25", "median", "p75", "p95"], _q, strict=True)),
            }
        )
    levels = pd.DataFrame(_rows)
    write(levels, "answer_key_levels.csv")
    # FEMA's 0 means "no ARA point"; its ratings treat it as 1.
    _zero = key[(key["HRCN_MID_LOWER_HM"] == 0) & (key["HRCN_EALT"] > 0)]
    _zero_by_state = _zero.groupby("STATEABBRV").agg(
        counties=("HRCN_EALT", "size"), eal_total=("HRCN_EALT", "sum")
    )
    write(_zero_by_state, "answer_key_zero_with_losses.csv", index=True)
    levels
    return bounds, key


@app.cell
def _(mo):
    mo.md(r"""
    In three scenarios, 94-97% of the counties FEMA covers sit between 1.9 and 2.1, in inland
    Vermont as on the Florida coast. No value lies between 1 and 1.25. The capped 10s sit at
    the inland edge of ARA's coverage, where a few rare simulated storms decide the ratio.
    1,529 counties are published as 0 (no ARA point); 640 of them have hurricane losses today.

    ## 2. ARA's own published numbers, through FEMA's formula

    ARA's white paper, *Incorporating Climate Change into a Hurricane Model* (2022,
    [PDF](https://www.ara.com/wp-content/uploads/ARA_ClimateChange_NatCatModels_WhitePaper.pdf)),
    Figure 1, gives landfall rates by region and category for a reference climate (1900-2018
    reanalysis) and CESM RCP 8.5 runs for 2021 and 2050. It shows them only as bars, so these
    values were read off by eye (about ±0.003 storms a year). ARA scales its event weights by
    exactly these ratios, so this is the closest public view of FEMA's input.
    """)
    return


@app.cell
def _(fri, key, np, pd, write):
    # Landfalls per year, Cat 1..5: (reference, RCP 8.5 2021, RCP 8.5 2050).
    ara_figure_1 = {
        "Gulf (TX-AL)": (
            (0.208, 0.188, 0.195, 0.126, 0.016),
            (0.209, 0.201, 0.203, 0.145, 0.024),
            (0.199, 0.196, 0.198, 0.139, 0.030),
        ),
        "Florida": (
            (0.198, 0.134, 0.178, 0.089, 0.028),
            (0.200, 0.136, 0.182, 0.095, 0.045),
            (0.190, 0.139, 0.186, 0.090, 0.057),
        ),
        "SE coast (GA-NC)": (
            (0.114, 0.100, 0.097, 0.028, 0.003),
            (0.111, 0.108, 0.107, 0.031, 0.004),
            (0.112, 0.113, 0.106, 0.034, 0.010),
        ),
        "NE coast (VA-ME)": (
            (0.061, 0.089, 0.082, 0.008, 0.000),
            (0.058, 0.102, 0.093, 0.010, 0.000),
            (0.056, 0.097, 0.086, 0.009, 0.000),
        ),
    }
    # Figure 1's regions, as space-separated state codes.
    ara_states = {
        "Gulf (TX-AL)": "TX LA MS AL",
        "Florida": "FL",
        "SE coast (GA-NC)": "GA SC NC",
        "NE coast (VA-ME)": "VA DC MD DE PA NJ NY CT RI MA NH ME",
    }
    _rows = []
    for _region, _rates in ara_figure_1.items():
        _reference, _now, _future = (np.array(r) @ fri.CATEGORY_WEIGHT for r in _rates)
        _published = key["HRCN_MID_HIGHER_HM"]
        _in_region = key["STATEABBRV"].isin(ara_states[_region].split()) & (_published > 0)
        _rows.append(
            {
                "region": _region,
                "ratio_2050_vs_reference": _future / _reference,
                "ratio_2050_vs_2021": _future / _now,
                "ratio_2021_vs_reference": _now / _reference,
                "published_mid_higher_median": _published[_in_region].median(),
            }
        )
    ara_table = pd.DataFrame(_rows).set_index("region")
    write(ara_table, "ara_white_paper.csv", index=True)
    ara_table
    return ara_figure_1, ara_states


@app.cell
def _(mo):
    mo.md(r"""
    ARA's own conditioning gives 1.06-1.23 for 2050 under RCP 8.5, varying by region. FEMA
    published about 2.0 in every region. (ARA's paper is CESM-only and FEMA's input was a
    multi-model CMIP5 ensemble, so this isn't FEMA's input, but it is ARA's method.)

    ## 3. Wind at every place, from public storm tracks

    ARA's points aren't public, so a regular 0.25° grid stands in. Following FRI Sec. 7.2,
    each county takes the grid points within 1 km of it; a county with none takes its nearest
    point, which ARA's denser points wouldn't need. Boundaries are the Census 2020 counties the
    FRI used.
    """)
    return


@app.cell
def _(cached, download, gpd, np, pd, zipfile):
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
    shapes = gpd.read_parquet(_target).rename(columns={"GEOID": "fips"}).set_index("fips")
    shapes = shapes[["STUSPS", "NAME", "geometry"]].to_crs("EPSG:4326")

    _lat, _lon = np.meshgrid(
        np.arange(24.0, 49.0, 0.25), np.arange(-107.0, -66.5, 0.25), indexing="ij"
    )
    _lat, _lon = _lat.ravel(), _lon.ravel()
    _points = gpd.GeoDataFrame(geometry=gpd.points_from_xy(_lon, _lat), crs="EPSG:4326")
    _points = _points.to_crs("EPSG:5070")
    _shapes = shapes[["geometry"]].to_crs("EPSG:5070")
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
    # Index: grid point position (repeated where a point serves two counties); values: county.
    point_county = pd.Series(_pairs["fips"].to_numpy(), index=_position[_pairs["point"]].to_numpy())
    f"{grid_lat.size:,} grid points cover {point_county.nunique():,} counties"
    return grid_lat, grid_lon, point_county, shapes


@app.cell
def _(mo):
    mo.md(r"""
    Wind fields come from [CLIMADA](https://github.com/CLIMADA-project/climada_python): the
    Holland (2008) profile gives each storm's peak 1-minute sustained wind at 10 m at every
    point, from tracks resampled hourly. It is open-terrain wind with no surface roughness, so
    only rankings and ratios carry over, not loss levels. Tracks with no fix within 2° (about
    220 km) of the grid are dropped first: Cat 1 wind that far from the eye is rare. Each event
    set is cached under a name that says what produced it, so a rerun skips the wind.

    NASA's distance-to-coast raster is blocked from this machine (HTTP 403), so the wind runs
    with `ignore_distance_to_coast=True`, which only drops CLIMADA's 1,000 km inland cut-off.
    """)
    return


@app.cell
def _(
    Callable, Centroids, TCTracks, TropCyclone, cached, fri, log, np, pathos, sparse, time, workers
):
    def near_grid(tracks: TCTracks, lat: np.ndarray, lon: np.ndarray) -> TCTracks:
        """Only tracks with a fix within 2 degrees of the points can put wind on them."""
        south, north, west, east = lat.min() - 2, lat.max() + 2, lon.min() - 2, lon.max() + 2
        kept = [
            t
            for t in tracks.data
            if ((t.lat > south) & (t.lat < north) & (t.lon > west) & (t.lon < east)).any()
        ]
        assert kept, "no track comes near the points"
        return TCTracks(data=kept)

    def wind_events(
        make_tracks: Callable[[pathos.pools.ProcessPool], TCTracks],
        lat: np.ndarray,
        lon: np.ndarray,
        name: str,
        years: tuple[int, int],
        rate: float,
    ) -> fri.Events:
        """CLIMADA wind on the points, cached as `name`; every event gets annual `rate`.

        `make_tracks(pool)` returns hourly tracks; it only runs when the cache is empty.
        """
        target = cached("hazard", f"{name}.h5")
        if not target.exists():
            start = time.perf_counter()
            pool = pathos.pools.ProcessPool(nodes=workers)
            tracks = make_tracks(pool)
            hazard = TropCyclone.from_tracks(
                tracks,
                centroids=Centroids(lat=lat, lon=lon),
                pool=pool,
                ignore_distance_to_coast=True,
            )
            pool.close()
            pool.join()
            pool.clear()
            hazard.pool = None
            hazard.write_hdf5(target.with_suffix(".partial.h5"))
            target.with_suffix(".partial.h5").rename(target)
            log.info("%s: %d tracks, %.0f s", name, tracks.size, time.perf_counter() - start)
        hazard = TropCyclone.from_hdf5(target)
        assert np.allclose(hazard.centroids.lat, lat), f"{name} was cached on other points"
        return fri.Events(
            wind=sparse.csr_matrix(hazard.intensity),
            frequency=np.full(hazard.size, rate),
            category=np.asarray(hazard.category),
            basin=np.asarray(hazard.basin),
            years=years,
        )

    return near_grid, wind_events


@app.cell
def _(mo):
    mo.md(r"""
    Two public storm catalogues, with opposite strengths:

    - **Observed tracks plus perturbed copies.** NOAA
      [IBTrACS v04r01](https://www.ncei.noaa.gov/products/international-best-track-archive),
      North Atlantic, US agency (HURDAT2) winds, 1900-2024, plus 19 copies of each track from
      CLIMADA's random walk with land decay: 2,500 years. Its frequencies match the record by
      construction. CLIMADA's perturbation isn't exactly reproducible on a process pool, even
      with a fixed seed, so numbers built on it move slightly between clean runs.
    - **STORM** (Bloemendaal et al.), 10,000 years of synthetic tracks resampled from IBTrACS
      1980-2018 ([doi:10.4121/12706085.v4](https://doi.org/10.4121/12706085.v4), CC0), and its
      SSP5-8.5 2015-2050 runs for four high-resolution GCMs
      ([doi:10.4121/14237678.v2](https://doi.org/10.4121/14237678.v2)). Each 1,000-year North
      Atlantic file is read out of the published zips with HTTP range requests, so other basins
      are never downloaded. The spike uses 5,000 years per climate; our layer uses all 10,000
      present-climate years.
    """)
    return


@app.cell
def _(TCTracks, cached, download, grid_lat, grid_lon, near_grid, wind_events):
    def observed_tracks() -> TCTracks:
        path = download(
            "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-"
            "stewardship-ibtracs/v04r01/access/netcdf/IBTrACS.NA.v04r01.nc",
            cached("ibtracs", "IBTrACS.NA.v04r01.nc"),
        )
        tracks = TCTracks.from_ibtracs_netcdf(
            provider="usa",
            basin="NA",
            year_range=(1900, 2024),
            estimate_missing=True,
            file_name=str(path),
        )
        assert tracks.size > 0, "IBTrACS returned no tracks"
        return tracks

    def _perturbed(pool: object) -> TCTracks:
        tracks = near_grid(observed_tracks(), grid_lat, grid_lon)
        tracks.equal_timestep(time_step_h=1.0, pool=pool)
        tracks.calc_perturbed_trajectories(
            nb_synth_tracks=19, use_global_decay_params=True, seed=8, pool=pool
        )
        return tracks

    history = wind_events(
        _perturbed,
        grid_lat,
        grid_lon,
        "ibtracs_1900_2024_x20_grid0.25",
        (1900, 2024),
        1 / (125 * 20),
    )
    return history, observed_tracks


@app.cell
def _(
    Path,
    RemoteZip,
    TCTracks,
    cached,
    fri,
    grid_lat,
    grid_lon,
    near_grid,
    np,
    session,
    sparse,
    wind_events,
):
    storm_gcms = {
        "CMCC-CM2-VHR4": "bdc3820c-7b7e-41de-8def-792f50b06c49",
        "CNRM-CM6-1-HR": "3b08e6a8-2824-435f-a141-9509a9922cfe",
        "EC-Earth3P-HR": "2eaeb5f6-40f3-4f94-9f9c-ca7aad3237fc",
        "HadGEM3-GC31-HM": "f35142d6-d858-4874-9a51-2dc08462d45f",
    }

    def storm_files(gcm: str | None, files: int) -> list[Path]:
        """The first `files` 1,000-year North Atlantic files of one climate, cached locally."""
        assert 1 <= files <= 10, f"STORM has 10 files per climate, not {files}"
        if gcm is None:
            names = [f"STORM_DATA_IBTRACS_NA_1000_YEARS_{i}.txt" for i in range(files)]
            url = (
                "https://data.4tu.nl/file/01b2ebc7-7903-42ef-b46b-f43b9175dbf4/"
                "78b72e86-b074-4478-9dc4-7280deb756ab"
            )
        else:
            names = [f"STORM_DATA_{gcm}_NA_1000_YEARS_{i}_IBTRACSDELTA.txt" for i in range(files)]
            url = f"https://data.4tu.nl/file/98900e17-8e01-4d70-b3b6-ca1a1da2f194/{storm_gcms[gcm]}"
        targets = [cached("storm", name) for name in names]
        missing = [t for t in targets if not t.exists()]
        if missing:
            # One zip session per climate, so 4TU sees one directory read, not one per file.
            with RemoteZip(url, session=session()) as archive:
                for target in missing:
                    members = [
                        i for i in archive.infolist() if i.filename.split("/")[-1] == target.name
                    ]
                    assert len(members) == 1, f"{target.name} not found once in the STORM zip"
                    target.with_suffix(".partial").write_bytes(archive.read(members[0]))
                    target.with_suffix(".partial").rename(target)
        return targets

    def storm_events(
        gcm: str | None, lat: np.ndarray, lon: np.ndarray, tag: str, files: int
    ) -> fri.Events:
        """STORM tracks as one event set; `gcm` None is the present climate.

        Each 1,000-year file gets its own wind fields and cache entry, so memory stays bounded
        and a longer catalogue reuses the files a shorter one computed.
        """
        years = (1980, 2018) if gcm is None else (2015, 2050)
        parts = []
        for index, path in enumerate(storm_files(gcm, files)):

            def hourly(pool: object, path: Path = path) -> TCTracks:
                raw = TCTracks.from_simulations_storm(path)
                # STORM gives longitude as 0-360; the grid uses -180-180.
                lon_west = [t.assign_coords(lon=((t.lon + 180) % 360) - 180) for t in raw.data]
                tracks = near_grid(TCTracks(data=lon_west), lat, lon)
                tracks.equal_timestep(time_step_h=1.0, pool=pool)
                return tracks

            name = f"storm_{gcm or 'present'}_file{index}_{tag}"
            parts.append(wind_events(hourly, lat, lon, name, years, 1 / (files * 1000)))
        return fri.Events(
            wind=sparse.csr_matrix(sparse.vstack([p.wind for p in parts])),
            frequency=np.concatenate([p.frequency for p in parts]),
            category=np.concatenate([p.category for p in parts]),
            basin=np.concatenate([p.basin for p in parts]),
            years=years,
        )

    storm_present = storm_events(None, grid_lat, grid_lon, "grid0.25", 5)
    storm_futures = {g: storm_events(g, grid_lat, grid_lon, "grid0.25", 5) for g in storm_gcms}
    return storm_events, storm_files, storm_futures, storm_present


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Is today's hazard right?

    If today's county hazard were wrong, no climate conditioning could fix the multipliers, so
    check it first against NRI v1.20 (December 2025), from FEMA's ArcGIS feature service.
    NRI's hurricane EAL comes from Hazus, so we turn our wind into an expected annual damage
    ratio with the Emanuel (2011) curve at CLIMADA's US parameters and multiply by NRI's own
    exposure. (Importing `climada.entity` needs GDAL bindings this project leaves out, so the
    curve's two parameters are written here.)
    """)
    return


@app.cell
def _(arcgis, cached, fri, history, np, pd, point_county, storm_present, write):
    nri = pd.read_parquet(
        arcgis(
            "National_Risk_Index_Counties",
            "1=1",
            ["STCOFIPS", "NRI_VER", "HRCN_AFREQ", "HRCN_EXPT", "HRCN_EALT"],
            cached("nri", "nri_v1_20_counties_hurricane.parquet"),
            max_pages=5,
        )
    ).set_index("STCOFIPS")
    assert len(nri) >= 3000, f"NRI county table is short: {len(nri)} rows"

    _baseline = []
    for _label, _events in (("historical", history), ("storm_present", storm_present)):
        _damage = _events.wind.copy().astype(float)
        _scaled = np.clip(_damage.data - 25.7, 0, None) / (74.7 - 25.7)
        _damage.data = _scaled**3 / (1 + _scaled**3)
        _storm = (_events.wind >= 17.49).astype(float)  # tropical-storm wind
        _table = pd.DataFrame(
            {
                "damage_ratio": fri.county_mean(
                    np.asarray(_damage.T @ _events.frequency).ravel(), point_county
                ),
                "storm_rate": fri.county_mean(
                    np.asarray(_storm.T @ _events.frequency).ravel(), point_county
                ),
            }
        ).join(nri[["HRCN_EALT", "HRCN_EXPT", "HRCN_AFREQ"]], how="left")
        _table["modelled_eal"] = _table["damage_ratio"] * _table["HRCN_EXPT"]
        _rows = []
        for _ours, _theirs in (("modelled_eal", "HRCN_EALT"), ("storm_rate", "HRCN_AFREQ")):
            _both = _table[[_ours, _theirs]].dropna()
            _both = _both[(_both[_ours] > 0) & (_both[_theirs] > 0)]
            _logs = np.log(_both)
            _log_ratio = _logs[_ours] - _logs[_theirs]
            _rows.append(
                {
                    "ours": _ours,
                    "nri": _theirs,
                    "counties": len(_both),
                    "spearman": _both[_ours].corr(_both[_theirs], method="spearman"),
                    "pearson_log": _logs[_ours].corr(_logs[_theirs]),
                    "median_ratio": float(np.exp(_log_ratio.median())),
                }
            )
        _agreement = pd.DataFrame(_rows).assign(event_set=_label)
        write(_agreement, f"baseline_{_label}.csv")
        _baseline.append(_agreement)
    pd.concat(_baseline)
    return (nri,)


@app.cell
def _(mo):
    mo.md(r"""
    Our modelled EAL ranks counties' NRI hurricane loss with Spearman 0.75 (observed tracks)
    and 0.92 (STORM). Its level runs 35-45 times NRI's, because of open-terrain wind and a
    generic damage curve, so only the ranking means anything. The hazard model isn't the
    problem.

    And how much of FEMA's county pattern is just "where hurricanes hit today"? Very little:
    """)
    return


@app.cell
def _(fri, history, key, nri, pd, point_county, storm_present, write):
    _measures = {
        "historical_intensity_today": fri.county_intensity(history, point_county),
        "storm_intensity_today": fri.county_intensity(storm_present, point_county),
        "nri_v1_20_loss_ratio": nri["HRCN_EALT"] / nri["HRCN_EXPT"],
        "nri_v1_19_eal": key["HRCN_EALT"],
    }
    _rows = []
    for _s in fri.SCENARIOS:
        _published = key[f"HRCN_{_s}_HM"]
        for _name, _values in _measures.items():
            _both = pd.DataFrame({"published": _published[_published > 0], "measure": _values})
            _both = _both.dropna()
            _both = _both[_both["measure"] > 0]
            _rows.append(
                {
                    "scenario": _s,
                    "measure": _name,
                    "counties": len(_both),
                    "spearman": _both["published"].corr(_both["measure"], method="spearman"),
                }
            )
    hazard_level = pd.DataFrame(_rows)
    write(hazard_level, "published_vs_hazard_level.csv")
    hazard_level.pivot(index="measure", columns="scenario", values="spearman")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Four public routes to a climate signal

    Each route gives a county ratio of projected to today's intensity (Eq. 11), before the
    floor at 1:

    - **Knutson frequency-only.** Knutson et al. (2020,
      [doi:10.1175/BAMS-D-18-0194.1](https://doi.org/10.1175/BAMS-D-18-0194.1)) as converted to
      any baseline, year and RCP by Jewson (2021,
      [doi:10.1175/JAMC-D-21-0102.1](https://doi.org/10.1175/JAMC-D-21-0102.1)), shipped with
      CLIMADA, median values. Each storm's rate is rescaled by its peak category; winds don't
      change. Jewson (2022) recommends this, because also changing intensity can double count.
      Against 1900-2024, the North Atlantic medians are −11% to −29% for all storms and +8% to
      +26% for Cat 4-5.
    - **Knutson intensity.** Every wind scaled by Knutson's mean-intensity change (+2% to +7%)
      and every rate by the all-storm change. The variant Jewson warns about, kept because
      ARA's runs change intensity as well as frequency.
    - **STORM SSP5-8.5.** The four GCMs' mean county intensity in 2050 over STORM's present
      climate. Covers mid-century higher only.
    - **ARA Figure 1.** ARA's method on our observed-track catalogue: each storm's rate scaled
      by ARA's 2050 / reference ratio for its region and category. Our stand-in for "landfall"
      is the point where the storm's wind peaks. Mid-century higher only.
    """)
    return


@app.cell
def _(
    ara_figure_1,
    ara_states,
    fri,
    history,
    np,
    pd,
    point_county,
    replace,
    shapes,
    sparse,
    storm_futures,
    storm_present,
    write,
):
    _today = fri.county_intensity(history, point_county)
    _frequency_only, _intensity = {}, {}
    for _s in fri.SCENARIOS:
        _scaled = fri.frequency_only(history, _s)
        _frequency_only[_s] = fri.ratio(fri.county_intensity(_scaled, point_county), _today)
        _speed = np.ones(history.wind.shape[0])
        _rate = history.frequency.copy()
        for _basin in np.unique(history.basin):
            _rows = history.basin == _basin
            _speed[_rows] += fri.knutson_percent("intensity", _s, str(_basin), history.years) / 100
            _rate[_rows] *= 1 + fri.knutson_percent("cat05", _s, str(_basin), history.years) / 100
        _faster = sparse.csr_matrix(history.wind.multiply(_speed[:, None]))
        _scaled = replace(history, wind=_faster, frequency=_rate)
        _intensity[_s] = fri.ratio(fri.county_intensity(_scaled, point_county), _today)

    # GCM ratios against STORM's present climate, then the equal-weight ensemble.
    _storm_today = fri.county_intensity(storm_present, point_county)
    _projected = {g: fri.county_intensity(e, point_county) for g, e in storm_futures.items()}
    _gcm_ratios = {g: fri.ratio(p, _storm_today) for g, p in _projected.items()}
    storm_ratio = fri.ratio(pd.concat(_projected, axis=1).mean(axis=1), _storm_today)
    _gcm_ratios["ensemble"] = storm_ratio
    _spread = pd.DataFrame(_gcm_ratios).describe().T
    write(_spread, "storm_gcm_ratios.csv", index=True)

    # ARA: region of each point (through its first county), category of the storm's peak wind.
    _region_of = {state: r for r, states in ara_states.items() for state in states.split()}
    _first_county = point_county.groupby(level=0).first().sort_index()
    _point_state = shapes["STUSPS"].reindex(_first_county.to_numpy()).to_numpy()
    _point_region = np.array([_region_of.get(s, "") for s in _point_state])
    _peak_point = np.asarray(history.wind.argmax(axis=1)).ravel()
    _peak_wind = np.asarray(history.wind.max(axis=1).toarray()).ravel()
    _category = np.searchsorted(fri.CATEGORY_FLOOR_MS, _peak_wind, side="right") - 1
    _ara_scale = np.ones(history.wind.shape[0])
    for _event in np.flatnonzero(_category >= 0):
        _region = _point_region[_peak_point[_event]]
        if _region:
            _reference, _, _future = (np.array(r) for r in ara_figure_1[_region])
            _c = _category[_event]
            _ara_scale[_event] = _future[_c] / _reference[_c] if _reference[_c] > 0 else 1.0
    _ara = replace(history, frequency=history.frequency * _ara_scale)

    routes = {
        "knutson_frequency": pd.DataFrame(_frequency_only),
        "knutson_intensity": pd.DataFrame(_intensity),
        "storm_ssp585": pd.DataFrame({"MID_HIGHER": storm_ratio}),
        "ara_figure_1": pd.DataFrame(
            {"MID_HIGHER": fri.ratio(fri.county_intensity(_ara, point_county), _today)}
        ),
    }
    _spread
    return routes, storm_ratio


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Scoring against FEMA's values

    Each route goes through Eq. 12 three ways: as FEMA documents it, $\max(1, r)$; `_plus_1`,
    $\max(1, 1 + r)$, as if FEMA's "projected" rate had included the historical one; and
    `_times_2`, $\max(1, 2r)$. The last two are fitted to the answer key's level of 2, not
    taken from FEMA's documentation. Constant multipliers of 1 and 2 are the baselines to beat.

    Scoring follows #15: rebuilt and published projected losses go into FEMA's fixed rating
    bins (each bin's upper edge is the largest EAL FEMA put in it, which reproduces 100% of
    FEMA's hurricane ratings), plus Pearson, Spearman, mean absolute log error and median
    rebuilt/published ratio. A blank counts as 1; FEMA's 0s are left out. Held-out states are
    #15's (every fourth state in FIPS order, from the second); nothing is fitted, so the split
    only keeps the rows comparable with #15. `_covered` scores only counties the route reaches,
    which separates coverage from the climate signal.
    """)
    return


@app.cell
def _(bounds, fri, key, np, pd, routes, write):
    _tables = {
        "constant_1": pd.DataFrame(1.0, index=key.index, columns=list(fri.SCENARIOS)),
        "constant_2": pd.DataFrame(2.0, index=key.index, columns=list(fri.SCENARIOS)),
    }
    for _name, _ratios in routes.items():
        _clean = _ratios.replace([np.inf, -np.inf], np.nan)
        _tables[_name] = _clean.clip(lower=1.0)
        _tables[f"{_name}_times_2"] = (2 * _clean).clip(lower=1.0)
        _tables[f"{_name}_plus_1"] = (1 + _clean).clip(lower=1.0)

    _states = sorted(key.index.str[:2].unique())
    _held_out = set(_states[1::4])
    _subset = pd.Series(key.index.str[:2], index=key.index).map(
        lambda s: "held_out" if s in _held_out else "train"
    )
    _rated = key["HRCN_EALR"].map(fri.rating_name).notna()
    _rows, _details = [], []
    for _method, _table in _tables.items():
        for _s in _table.columns:
            _rebuilt = _table[_s].reindex(key.index)
            for _part, _mask in (
                ("train", _subset == "train"),
                ("held_out", _subset == "held_out"),
                ("train_covered", (_subset == "train") & _rebuilt.notna()),
                ("held_out_covered", (_subset == "held_out") & _rebuilt.notna()),
            ):
                _both = pd.DataFrame(
                    {"published": key[f"HRCN_{_s}_HM"], "rebuilt": _rebuilt.fillna(1.0)}
                )[_mask]
                _both = _both[_both["published"] > 0]
                _eal = key.loc[_both.index, "HRCN_EALT"]
                _bins = _rated[_both.index]
                _published_bin = fri.rate(_eal * _both["published"], bounds)[_bins]
                _rebuilt_bin = fri.rate(_eal * _both["rebuilt"].clip(lower=1.0), bounds)[_bins]
                _log_error = np.log(_both["rebuilt"].clip(lower=1e-6) / _both["published"])
                _rows.append(
                    {
                        "method": _method,
                        "scenario": _s,
                        "subset": _part,
                        "counties": len(_both),
                        "blank": int(_rebuilt[_both.index].isna().sum()),
                        "same_bin": float((_published_bin == _rebuilt_bin).mean()),
                        "pearson": _both["published"].corr(_both["rebuilt"]),
                        "spearman": _both["published"].corr(_both["rebuilt"], method="spearman"),
                        "log_mae": float(_log_error.abs().mean()),
                        "median_ratio": float(np.exp(_log_error.median())),
                    }
                )
                if _part == "held_out":
                    _details.append(_both.assign(method=_method, scenario=_s))
    scores = pd.DataFrame(_rows)
    write(scores, "scores.csv")
    held_out_details = pd.concat(_details)
    scores[scores["subset"].str.startswith("held_out")]
    return held_out_details, scores


@app.cell
def _(mo):
    mo.md(r"""
    What the scores show:

    - **As FEMA documents the formula, every public route is worse than assuming no change.**
      The ratios sit near 1, so after the floor almost every county gets 1 against FEMA's 2.
      A constant 2 matches 95-100% of held-out ratings.
    - **Coverage costs as much as the formula.** In 2,500 and 5,000 years, our catalogues put
      Cat 1 wind on far fewer counties than ARA's 500,000 simulated years reach.
    - **Read as $1 + r$, the level matches and the pattern doesn't.** On covered counties the
      Knutson and ARA routes land within a few percent of FEMA's values and 91-100% share a
      rating bin, but the constant 2 is still as close in three scenarios. $1 + r$ fits the level
      better than $2r$. That fits FEMA's "projected" intensity having included the historical
      one, but it isn't proof.
    - **Rank agreement is weak and depends on which states are scored** (Spearman, covered
      counties, $1 + r$):
    """)
    return


@app.cell
def _(scores):
    _plus_one = scores[
        scores["method"].str.endswith("_plus_1") & scores["subset"].str.endswith("_covered")
    ]
    _plus_one.pivot_table(index=["method", "scenario"], columns="subset", values="spearman")
    return


@app.cell
def _(mo):
    mo.md(r"""
    Knutson frequency-only is the only route that agrees with FEMA's pattern on both state
    sets, most clearly late century under higher warming: both raise multipliers most where
    intense storms already make up much of the wind, in south Florida and on the Gulf coast.
    FEMA's values are so tightly clustered that these statistics are unstable: on the
    perturbed observed tracks, the ARA route's held-out Spearman moved from 0.18 to 0.45
    between two clean runs of the same code. STORM's GCMs disagree with each other too, with
    median county ratios from 0.96 (EC-Earth3P-HR) to 1.55 (CMCC-CM2-VHR4).
    """)
    return


@app.cell
def _(Normalize, Path, pd, plt, shapes):
    def county_maps(
        panels: dict[str, pd.Series], target: Path, norm: Normalize, cmap: str = "viridis"
    ) -> Path:
        """One choropleth per panel on one colour scale; counties without a value in grey."""
        box = shapes.cx[-107.0:-66.5, 24.0:49.0]
        box = box[~box["STUSPS"].isin(["AK", "HI", "PR"])].to_crs("EPSG:5070")
        figure, axes = plt.subplots(1, len(panels), figsize=(6 * len(panels), 4.2), squeeze=False)
        for axis, (title, values) in zip(axes[0], panels.items(), strict=True):
            shaded = box.assign(value=values.reindex(box.index))
            shaded.plot(ax=axis, color="#dddddd", linewidth=0)
            shaded = shaded[shaded["value"] > 0]
            shaded.plot(ax=axis, column="value", cmap=cmap, norm=norm, linewidth=0, legend=True)
            axis.set_title(title, fontsize=10)
            axis.set_axis_off()
        figure.tight_layout()
        figure.savefig(target, dpi=110)
        plt.close(figure)
        return target

    return (county_maps,)


@app.cell
def _(Normalize, county_maps, held_out_details, key, mo, plt, results, routes):
    _published = {
        f"FEMA published, {s}": key[f"HRCN_{s}_HM"] for s in ("MID_HIGHER", "LATE_HIGHER")
    }
    county_maps(_published, results / "map_published.png", Normalize(1.0, 2.6))
    _rebuilt = {
        "Public: STORM SSP5-8.5 2050 ratio": routes["storm_ssp585"]["MID_HIGHER"],
        "Public: Knutson frequency, late higher": routes["knutson_frequency"]["LATE_HIGHER"],
    }
    county_maps(_rebuilt, results / "map_rebuilt_ratio.png", Normalize(0.6, 1.6))

    _pairs = [
        ("storm_ssp585", "MID_HIGHER"),
        ("ara_figure_1", "MID_HIGHER"),
        ("knutson_frequency", "LATE_HIGHER"),
        ("knutson_intensity", "LATE_HIGHER"),
    ]
    _figure, _axes = plt.subplots(1, len(_pairs), figsize=(16, 4))
    for _axis, (_method, _s) in zip(_axes, _pairs, strict=True):
        _part = held_out_details[
            (held_out_details["method"] == _method) & (held_out_details["scenario"] == _s)
        ]
        _axis.scatter(_part["rebuilt"], _part["published"], s=4, alpha=0.4)
        _axis.set(xlabel="rebuilt HM", ylabel="published HM", xlim=(0.9, 4), ylim=(0.9, 4))
        _axis.set_title(f"{_method}\n{_s}", fontsize=9)
    _figure.tight_layout()
    _figure.savefig(results / "scatter_held_out.png", dpi=110)
    plt.close(_figure)
    mo.vstack([mo.image(results / f) for f in ("map_published.png", "scatter_held_out.png")])
    return


@app.cell
def _(mo):
    mo.md(r"""
    **So public inputs can rebuild a credible hurricane multiplier, but not FEMA's.** FEMA's
    numbers are mostly a constant of about 2, plus a county pattern that only partly follows
    the published climate signal. Whatever produces the 2 isn't public. FEMA's technical
    document says the ARA file is available from FEMA-NRI@fema.dhs.gov; we haven't seen it.

    ## 7. Our own hurricane layer

    A founder asked for a layer we could publish instead. It is FEMA's documented Eq. 11-12
    with no factor of 2, on open inputs only:

    - **Today's storms:** both catalogues, STORM at its full 10,000 years. They give the same
      typical multiplier but disagree on which counties rise most, so the central value is
      their mean, and their disagreement counts as uncertainty.
    - **Climate change:** Knutson frequency-only (Jewson's recommended use), each catalogue
      against its own baseline years.
    - **Range:** the lowest and highest value over both catalogues and every published
      Knutson percentile (5th/10th to 90th/95th).
    - A county where neither catalogue has Cat 1 wind gets HM = 1, as FEMA's ratings treat
      its own zeros. Nothing is fitted to FEMA's values or to NRI losses.

    The multiplier is a change factor, not a risk level: what to publish is projected loss,
    NRI's EAL times the multiplier.
    """)
    return


@app.cell
def _(fri, pd):
    def multipliers(events: fri.Events, point_unit: pd.Series) -> pd.DataFrame:
        """HM per unit and scenario: Knutson median, and the low and high over percentiles."""
        today = fri.county_intensity(events, point_unit)
        table = pd.DataFrame({"intensity_today": today, "no_cat1_wind": ~(today > 0)})
        for scenario in fri.SCENARIOS:
            hm = pd.DataFrame(
                {
                    p: fri.ratio(
                        fri.county_intensity(fri.frequency_only(events, scenario, p), point_unit),
                        today,
                    )
                    for p in fri.PERCENTILES
                }
            )
            hm = hm.clip(lower=1.0).fillna(1.0)
            table[f"{scenario}_HM"] = hm["50"]
            table[f"{scenario}_HM_LOW"] = hm.min(axis=1)
            table[f"{scenario}_HM_HIGH"] = hm.max(axis=1)
        return table

    return (multipliers,)


@app.cell
def _(fri, grid_lat, grid_lon, history, multipliers, pd, point_county, storm_events, write):
    storm_10k = storm_events(None, grid_lat, grid_lon, "grid0.25", 10)
    catalogues = {
        "storm": multipliers(storm_10k, point_county),
        "historical": multipliers(history, point_county),
    }
    _units = pd.Index(sorted(set(catalogues["storm"].index) | set(catalogues["historical"].index)))
    _covered = pd.DataFrame(
        {
            c: ~t["no_cat1_wind"].reindex(_units).fillna(True).astype(bool)
            for c, t in catalogues.items()
        }
    )
    ours = pd.DataFrame(index=_units.rename("unit"))
    ours["no_cat1_wind"] = ~_covered.any(axis=1)
    ours["catalogues_with_wind"] = _covered.sum(axis=1)
    for _s in fri.SCENARIOS:
        _columns = {
            sfx: pd.DataFrame(
                {
                    c: t[f"{_s}_{sfx}"].reindex(_units).where(_covered[c])
                    for c, t in catalogues.items()
                }
            )
            for sfx in ("HM", "HM_LOW", "HM_HIGH")
        }
        ours[f"{_s}_HM"] = _columns["HM"].mean(axis=1).fillna(1.0)
        ours[f"{_s}_HM_LOW"] = _columns["HM_LOW"].min(axis=1).fillna(1.0)
        ours[f"{_s}_HM_HIGH"] = _columns["HM_HIGH"].max(axis=1).fillna(1.0)
        for _c in catalogues:
            ours[f"{_s}_HM_{_c.upper()}"] = _columns["HM"][_c]
    write(ours, "layer/county_multipliers.csv", index=True)

    _storm, _hist = catalogues["storm"], catalogues["historical"]
    _both = ~_storm["no_cat1_wind"] & _covered["historical"].reindex(_storm.index)
    _rows = []
    for _s in fri.SCENARIOS:
        _a = _storm.loc[_both, f"{_s}_HM"]
        _b = _hist[f"{_s}_HM"].reindex(_a.index)
        _rows.append(
            {
                "scenario": _s,
                "counties_storm": int((~_storm["no_cat1_wind"]).sum()),
                "counties_historical": int((~_hist["no_cat1_wind"]).sum()),
                "counties_both": int(_both.sum()),
                "storm_median": _a.median(),
                "historical_median": _b.median(),
                "spearman": _a.corr(_b, method="spearman"),
                "median_abs_difference": (_a - _b).abs().median(),
            }
        )
    check_catalogues = pd.DataFrame(_rows)
    write(check_catalogues, "layer/check_catalogues.csv")
    check_catalogues
    return ours, storm_10k


@app.cell
def _(mo):
    mo.md(r"""
    ### Our layer against FEMA's

    The comparison set is the 2,219 CONUS counties with an NRI hurricane rating, with FEMA's
    0s counted as 1. Projected loss is on FEMA's own v1.19 baseline, so differences come from
    the multiplier alone, and also on NRI v1.20.
    """)
    return


@app.cell
def _(bounds, fri, key, nri, ours, pd, write):
    _rated = key[key["HRCN_EALR"].map(fri.rating_name).notna() & (key["HRCN_EALT"] > 0)]
    _rank = {name: rank for rank, name in enumerate(fri.RATINGS)}
    _frames = []
    for _s in fri.SCENARIOS:
        _t = pd.DataFrame(index=_rated.index)
        _t["scenario"] = _s
        _t["state"] = _rated["STATEABBRV"]
        _t["county"] = _rated["COUNTY"]
        _t["eal_v1_19"] = _rated["HRCN_EALT"]
        _t["eal_v1_20"] = nri["HRCN_EALT"].reindex(_rated.index)
        _fema = _rated[f"HRCN_{_s}_HM"]
        _t["fema_hm"] = _fema.where(_fema > 0, 1.0).clip(lower=1.0)
        for _column in ("HM", "HM_LOW", "HM_HIGH"):
            _t[f"our_{_column.lower()}"] = ours[f"{_s}_{_column}"].reindex(_rated.index).fillna(1.0)
        _t["our_covered"] = ~ours["no_cat1_wind"].reindex(_rated.index).fillna(True).astype(bool)
        _t["fema_pal"] = _t["eal_v1_19"] * _t["fema_hm"]
        _t["our_pal_v1_19"] = _t["eal_v1_19"] * _t["our_hm"]
        _t["our_pal_v1_20"] = _t["eal_v1_20"] * _t["our_hm"]
        _t["fema_rating"] = fri.rate(_t["fema_pal"], bounds)
        _t["our_rating_v1_19"] = fri.rate(_t["our_pal_v1_19"], bounds)
        _t["our_rating_v1_20"] = fri.rate(_t["our_pal_v1_20"].fillna(0.0), bounds)
        _t["rating_move"] = _t["our_rating_v1_19"].map(_rank) - _t["fema_rating"].map(_rank)
        _t["fema_within_our_range"] = _t["fema_hm"].between(_t["our_hm_low"], _t["our_hm_high"])
        _frames.append(_t)
    comparison = pd.concat(_frames)
    write(comparison, "layer/fri_comparison_by_county.csv", index=True)

    _rows = []
    for _s, _p in comparison.groupby("scenario", sort=False):
        _covered = _p[_p["our_covered"]]
        _rows.append(
            {
                "scenario": _s,
                "counties": len(_p),
                "fema_hm_median": _p["fema_hm"].median(),
                "our_hm_median": _p["our_hm"].median(),
                "counties_covered": len(_covered),
                "fema_within_our_range_covered": _covered["fema_within_our_range"].mean(),
                "our_hm_median_covered": _covered["our_hm"].median(),
                "eal_v1_19_total": _p["eal_v1_19"].sum(),
                "fema_pal_total": _p["fema_pal"].sum(),
                "our_pal_v1_19_total": _p["our_pal_v1_19"].sum(),
                "our_pal_v1_20_total": _p["our_pal_v1_20"].sum(),
                "rating_same": float((_p["rating_move"] == 0).mean()),
                "rating_down_1": float((_p["rating_move"] == -1).mean()),
                "rating_down_2_plus": float((_p["rating_move"] <= -2).mean()),
                "spearman_pal_v1_19": _p["our_pal_v1_19"].corr(_p["fema_pal"], method="spearman"),
            }
        )
    comparison_summary = pd.DataFrame(_rows)
    write(comparison_summary, "layer/fri_comparison_summary.csv")
    comparison_summary.set_index("scenario").T
    return (comparison,)


@app.cell
def _(mo):
    mo.md(r"""
    In the 1,333 covered counties our central multipliers are 1.04, 1.05, 1.06 and 1.15 (mid
    lower, mid higher, late lower, late higher). FEMA's value lies outside our whole range in
    97-98% of them, except late century under higher warming, which reaches FEMA's level only
    at the top Knutson percentile. National projected loss halves, 16-18% of counties drop one
    rating bin and none drop two, but the county ranking barely moves: FEMA's doubling changed
    levels, not order.

    **Cross-check.** STORM's own 2050 SSP5-8.5 GCM storms are an independent route, from
    climate-model tracks rather than an assessment:
    """)
    return


@app.cell
def _(ours, pd, storm_ratio, write):
    _both = pd.DataFrame(
        {
            "storm_hm": storm_ratio.clip(lower=1.0),
            "our_hm": ours["MID_HIGHER_HM"],
            "low": ours["MID_HIGHER_HM_LOW"],
            "high": ours["MID_HIGHER_HM_HIGH"],
        }
    ).dropna()
    storm_check = pd.DataFrame(
        [
            {
                "counties": len(_both),
                "storm_hm_median": _both["storm_hm"].median(),
                "our_hm_median": _both["our_hm"].median(),
                "storm_within_knutson_range": _both["storm_hm"]
                .between(_both["low"], _both["high"])
                .mean(),
                "storm_above_range": (_both["storm_hm"] > _both["high"]).mean(),
                "spearman": _both["storm_hm"].corr(_both["our_hm"], method="spearman"),
                "median_storm_over_ours": (_both["storm_hm"] / _both["our_hm"]).median(),
            }
        ]
    )
    write(storm_check, "layer/storm_check.csv")
    storm_check
    return


@app.cell
def _(mo):
    mo.md(r"""
    Both routes put the change far below FEMA's 2; they disagree on its size and where it
    falls, which is why the range is published with the central value.

    ### Is it believable?

    The worry: someone sees 1.05 for Miami and concludes Miami isn't at high risk. First, the
    places people check first, mid-century higher, ranked by projected loss:
    """)
    return


@app.cell
def _(comparison, write):
    _places = {
        "12086": "Miami-Dade, FL",
        "12011": "Broward, FL",
        "12099": "Palm Beach, FL",
        "12087": "Monroe (Keys), FL",
        "12057": "Hillsborough (Tampa), FL",
        "45019": "Charleston, SC",
        "45051": "Horry (Myrtle Beach), SC",
        "45013": "Beaufort, SC",
        "37129": "New Hanover (Wilmington), NC",
        "37019": "Brunswick, NC",
        "37031": "Carteret, NC",
        "37055": "Dare (Outer Banks), NC",
        "22071": "Orleans, LA",
        "48201": "Harris (Houston), TX",
        "48167": "Galveston, TX",
    }
    _by_scenario = comparison.groupby("scenario")
    _ranked = comparison.assign(
        our_pal_rank_v1_20=_by_scenario["our_pal_v1_20"].rank(ascending=False, method="min"),
        fema_pal_rank=_by_scenario["fema_pal"].rank(ascending=False, method="min"),
    )
    _picked = _ranked[_ranked.index.isin(list(_places))].copy()
    _picked.insert(0, "place", _picked.index.map(_places))
    _columns = "place scenario eal_v1_19 eal_v1_20 fema_hm our_hm our_hm_low our_hm_high"
    _columns += " fema_rating our_rating_v1_19 our_rating_v1_20 fema_pal_rank our_pal_rank_v1_20"
    _picked = _picked[_columns.split()].sort_values(["scenario", "place"])
    write(_picked, "layer/check_places.csv")
    _picked[_picked["scenario"] == "MID_HIGHER"].sort_values("our_pal_rank_v1_20")
    return


@app.cell
def _(mo):
    mo.md(r"""
    Southeast Florida, coastal South Carolina, Houston and New Orleans stay Very High and near
    the top. Where a rating drops, it is either FEMA's ×2 having pushed a county over a bin
    edge (Monroe, Brunswick, Carteret) or NRI v1.20 itself cutting today's loss (Galveston
    from $132M to $42M a year), which happens with or without our multiplier.

    Second, today's storms against the record. NHC publishes how often a hurricane (≥ 64 kt)
    and a major hurricane (≥ 96 kt) passes within 50 nautical miles of points on the coast
    (HURISK, data through 2010, [nhc.noaa.gov/climo](https://www.nhc.noaa.gov/climo/)). We
    read NHC's values off its two maps by eye (a neighbouring circle can differ by one class)
    and count the same thing in STORM's 10,000 years and the observed 1900-2024 tracks. STORM
    winds are 10-minute; STORM's own factor of 1/0.88 converts them to 1-minute.
    """)
    return


@app.cell
def _(np, observed_tracks, pd, storm_files, write):
    # Name, lat, lon, NHC years between hurricanes and between major hurricanes within 50 nm.
    _sites = [
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
    ]
    _knots = 1.943844
    _storm = []
    for _index, _path in enumerate(storm_files(None, 10)):
        _raw = pd.read_csv(_path, header=None, usecols=[0, 2, 5, 6, 8])
        _raw.columns = ["year", "tc", "lat", "lon", "wind_ms"]
        _storm.append(
            pd.DataFrame(
                {
                    "storm": _index * 10_000_000 + _raw["year"] * 1000 + _raw["tc"],
                    "lat": _raw["lat"],
                    "lon": ((_raw["lon"] + 180) % 360) - 180,
                    "wind_kt": _raw["wind_ms"] / 0.88 * _knots,
                }
            )
        )
    _observed = [
        pd.DataFrame(
            {
                "storm": n,
                "lat": t.lat.to_numpy(),
                "lon": t.lon.to_numpy(),
                "wind_kt": t.max_sustained_wind.to_numpy(),
            }
        )
        for n, t in enumerate(observed_tracks().data)
    ]
    _fixes = {"storm": (pd.concat(_storm), 10_000), "observed": (pd.concat(_observed), 125)}
    _rows = []
    for _name, _lat, _lon, _nhc_hurricane, _nhc_major in _sites:
        _row: dict[str, object] = {"site": _name}
        for _label, (_f, _years) in _fixes.items():
            _lat1, _lon1 = np.radians(_f["lat"].to_numpy()), np.radians(_f["lon"].to_numpy())
            _lat2, _lon2 = np.radians(_lat), np.radians(_lon)
            _a = (
                np.sin((_lat2 - _lat1) / 2) ** 2
                + np.cos(_lat1) * np.cos(_lat2) * np.sin((_lon2 - _lon1) / 2) ** 2
            )
            _near = 2 * 6371.0 * np.arcsin(np.sqrt(_a)) <= 92.6  # 50 nautical miles
            for _kind, _kt in (("hurricane", 64.0), ("major", 96.0)):
                _count = _f.loc[_near & (_f["wind_kt"].to_numpy() >= _kt), "storm"].nunique()
                _row[f"{_label}_{_kind}_years"] = _years / _count if _count else np.inf
                if _label == "observed":
                    _row[f"observed_{_kind}_count"] = _count
        _row["nhc_hurricane_years"] = _nhc_hurricane
        _row["nhc_major_years"] = _nhc_major
        _rows.append(_row)
    return_periods = pd.DataFrame(_rows)
    write(return_periods, "layer/check_return_periods.csv")
    return_periods
    return


@app.cell
def _(mo):
    mo.md(r"""
    **STORM puts about a half to a third of the observed hurricanes near the US coast**, even
    against the 1980-2018 record it is built from, though its basin-wide counts are right. That
    is why the layer averages it with the observed-track catalogue. It matters less than it
    looks: a multiplier is a ratio of future to today's storms in the same catalogue, so a
    catalogue that is too quiet overall cancels out, and absolute risk comes from NRI's EAL,
    not from STORM.
    """)
    return


@app.cell
def _(LogNorm, Normalize, comparison, county_maps, key, mo, ours, results):
    _panels = {}
    for _s in ("MID_HIGHER", "LATE_HIGHER"):
        _panels[f"FEMA, {_s}"] = key[f"HRCN_{_s}_HM"]
        _panels[f"Ours (Knutson median), {_s}"] = ours[f"{_s}_HM"]
    county_maps(_panels, results / "layer" / "map_fema_vs_ours.png", Normalize(1.0, 2.2))
    _mid = comparison[comparison["scenario"] == "MID_HIGHER"]
    _loss = {
        "FEMA: v1.19 EAL x FEMA HM, mid-century higher ($/yr)": _mid["fema_pal"],
        "Ours: v1.20 EAL x our HM, mid-century higher ($/yr)": _mid["our_pal_v1_20"],
    }
    county_maps(_loss, results / "layer" / "map_projected_loss.png", LogNorm(1e5, 1e9), "magma_r")
    mo.image(results / "layer" / "map_projected_loss.png")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### Can we go below the county?

    Yes, for projected loss. We publish tract projected loss: NRI v1.20 tract hurricane EAL,
    which already models buildings and exposure by tract, times its county's multiplier and
    range, for every state with a covered county.
    """)
    return


@app.cell
def _(arcgis, cached, fri, log, ours, pd, results, shapes):
    _covered = ours.index[~ours["no_cat1_wind"]]
    _states = sorted(set(shapes.loc[shapes.index.isin(_covered), "STUSPS"]))
    _frames = []
    for _state in _states:
        _nri = pd.read_parquet(
            arcgis(
                "National_Risk_Index_Census_Tracts",
                f"STATEABBRV='{_state}'",
                ["TRACTFIPS", "STCOFIPS", "NRI_VER", "HRCN_EALT", "HRCN_EXPT"],
                cached("tracts", f"nri_v1_20_{_state}.parquet"),
                max_pages=20,
            )
        ).set_index("TRACTFIPS")
        assert _nri.index.is_unique and not _nri.empty, f"bad NRI tract table for {_state}"
        _t = pd.DataFrame(index=_nri.index)
        _t["county"] = _nri["STCOFIPS"].astype(str).str.zfill(5)
        _t["eal_v1_20"] = _nri["HRCN_EALT"]
        for _s in fri.SCENARIOS:
            for _sfx in ("HM", "HM_LOW", "HM_HIGH"):
                _hm = ours[f"{_s}_{_sfx}"].reindex(_t["county"]).fillna(1.0)
                _t[f"{_s}_{_sfx}"] = _hm.to_numpy()
            _t[f"{_s}_PAL"] = _t["eal_v1_20"] * _t[f"{_s}_HM"]
        _frames.append(_t)
    tract_loss = pd.concat(_frames)
    tract_loss.to_csv(results / "layer" / "tract_projected_loss.csv.gz", float_format="%.6g")
    log.info("tract projected loss: %d tracts in %d states", len(tract_loss), len(_states))
    f"{len(tract_loss):,} tracts in {len(_states)} states"
    return (tract_loss,)


@app.cell
def _(mo):
    mo.md(r"""
    Why not a multiplier per tract? Parametric wind can be evaluated at any point, unlike the
    25 km climate grids behind the other FRI hazards, so the Florida pilot computes STORM's
    10,000 years of wind at every tract's population-weighted centre (Census CenPop2020) and
    runs the county method on each.
    """)
    return


@app.cell
def _(cached, download, fri, multipliers, np, ours, pd, storm_events, tract_loss, write):
    _centroids = pd.read_csv(
        download(
            "https://www2.census.gov/geo/docs/reference/cenpop2020/tract/CenPop2020_Mean_TR12.txt",
            cached("tracts", "cenpop_12.txt"),
        ),
        dtype={"STATEFP": str, "COUNTYFP": str, "TRACTCE": str},
    ).rename(columns=str.lower)
    _centroids.index = _centroids["statefp"] + _centroids["countyfp"] + _centroids["tractce"]
    assert _centroids.index.is_unique, "duplicate tract centroids"
    _lat = _centroids["latitude"].to_numpy(dtype=float)
    _lon = _centroids["longitude"].to_numpy(dtype=float)
    _point_tract = pd.Series(_centroids.index.to_numpy(), index=np.arange(len(_centroids)))
    _events = storm_events(None, _lat, _lon, "tracts12", 10)
    tracts_fl = multipliers(_events, _point_tract).join(_centroids[["latitude", "longitude"]])
    tracts_fl["county"] = tracts_fl.index.str[:5]
    tracts_fl["eal_v1_20"] = tract_loss["eal_v1_20"].reindex(tracts_fl.index)
    for _s in fri.SCENARIOS:
        tracts_fl[f"county_{_s}_HM"] = ours[f"{_s}_HM"].reindex(tracts_fl["county"]).to_numpy()
    write(tracts_fl, "layer/tract_multipliers_FL.csv", index=True)

    _rows = []
    for _s in fri.SCENARIOS:
        _tract, _county = f"{_s}_HM", f"county_{_s}_HM"
        _spread = tracts_fl.groupby("county")[_tract].agg(["min", "max"])
        _spread = _spread[_spread["min"] > 0]
        _within = _spread["max"] / _spread["min"]
        _valid = tracts_fl.dropna(subset=["eal_v1_20", _county])
        _rows.append(
            {
                "scenario": _s,
                "tracts": len(tracts_fl),
                "tract_hm_median": tracts_fl[_tract].median(),
                "within_county_max_over_min_median": _within.median(),
                "within_county_max_over_min_max": _within.max(),
                "spearman_tract_vs_county": tracts_fl[_tract].corr(
                    tracts_fl[_county], method="spearman"
                ),
                "rollup_tract_pal_over_county_pal": (_valid["eal_v1_20"] * _valid[_tract]).sum()
                / (_valid["eal_v1_20"] * _valid[_county]).sum(),
            }
        )
    tract_summary = pd.DataFrame(_rows)
    write(tract_summary, "layer/tract_summary_FL.csv")
    tract_summary
    return (tracts_fl,)


@app.cell
def _(gpd, plt, results, shapes, tracts_fl):
    _outline = shapes[shapes["STUSPS"] == "FL"].to_crs("EPSG:5070")
    _xy = gpd.points_from_xy(tracts_fl["longitude"], tracts_fl["latitude"])
    _points = gpd.GeoDataFrame(tracts_fl[["LATE_HIGHER_HM"]], geometry=_xy, crs="EPSG:4326")
    _figure, _axis = plt.subplots(figsize=(7, 7))
    _outline.boundary.plot(ax=_axis, color="#999999", linewidth=0.4)
    _points.to_crs("EPSG:5070").plot(
        ax=_axis, column="LATE_HIGHER_HM", cmap="viridis", markersize=3, legend=True
    )
    _axis.set_title("Tract HM, late century higher (Knutson median), FL", fontsize=10)
    _axis.set_axis_off()
    _figure.tight_layout()
    _figure.savefig(results / "layer" / "map_tracts_FL.png", dpi=110)
    plt.close(_figure)
    return


@app.cell
def _(mo):
    mo.md(r"""
    Inside a Florida county, the highest tract multiplier is a median 0.5% above the lowest
    (1.5% for late century, higher warming). That is less than the two catalogues disagree by,
    so a tract-level climate multiplier would be false precision; the climate part stays at
    county level and the detail inside a county comes from NRI.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. What didn't work, and what this doesn't show

    - **FEMA's values were not reproduced** by any public route as FEMA documents the formula.
      Whatever produces FEMA's level of 2 isn't public; the $1 + r$ and $2r$ readings are fits.
    - **No route matches FEMA's county pattern consistently.** Knutson frequency-only comes
      closest, and rank statistics on FEMA's tightly clustered values are unstable.
    - **Inland coverage:** 2,500 and 5,000 synthetic years reach far fewer counties than ARA's
      500,000. Ten times the STORM years would make the run about ten times longer.
    - **CLIMADA needed two workarounds.** Its GDAL dependency has no wheels, so
      `pyproject.toml` overrides it out (hence the Emanuel curve written out above); and CLIMADA
      6.1 breaks on NumPy 2.4, so NumPy is pinned below it.
    - **Blocked downloads:** NASA's distance-to-coast raster and the AMS journal site (HTTP
      403); the Knutson numbers come from CLIMADA's packaged tables. STORM's host, 4TU,
      rate-limits repeated range reads (HTTP 429); downloads retry with backoff, and a rerun
      resumes from the cache.
    - **Not covered:** storm surge and rain (the FRI is wind only); terrain and buildings (they
      live in NRI's EAL); climate-driven changes in tracks (Knutson is basin-wide); late-century
      simulated tracks (RAFT, #24); Connecticut's v1.20 planning regions, which don't match the
      2020 county codes; Alaska, Hawaii and the territories.
    - **Looked at and not used:** HURSAT (satellite imagery with no wind field), ASCE 7 wind
      maps (no scenario component), RAFT (13 GB with a bias correction; split off as #24).
    """)
    return


if __name__ == "__main__":
    app.run()

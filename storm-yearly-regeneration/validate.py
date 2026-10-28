import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
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
    import pathos.pools
    import xarray as xr
    from climada.hazard import Centroids, TCTracks, TropCyclone
    from climada.hazard.tc_clim_change import get_knutson_scaling_factor
    from remotezip import RemoteZip
    from scipy import sparse

    from common import HERE, RESULTS, WORKERS, cached, download, log, session, write

    return (
        Centroids,
        HERE,
        Path,
        RESULTS,
        RemoteZip,
        TCTracks,
        TropCyclone,
        WORKERS,
        cached,
        download,
        get_knutson_scaling_factor,
        gpd,
        json,
        log,
        mo,
        np,
        pathos,
        pd,
        plt,
        session,
        sparse,
        time,
        write,
        xr,
        zipfile,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Is our STORM regeneration a stand-in for STORM v4?

    `regenerate.py` reran STORM on IBTrACS through the latest complete season. Here we check
    the tracks against what they should match ([issue #142](https://github.com/fulton-ring/agent-content-demos/issues/142)):

    1. **Basin statistics:** how many storms form a year and how strong they get, against the
       record they were fitted to and against Odériz & Losada's (2025) independent STORM rerun
       on IBTrACS 1980-2021 ([doi:10.5281/zenodo.15097665](https://doi.org/10.5281/zenodo.15097665)).
    2. **The US coast:** how often a hurricane and a major hurricane pass within 50 nautical
       miles of 12 NHC sites, against NHC, the observed tracks, STORM v4 and Odériz & Losada.
    3. **Our hurricane layer:** the county multipliers from `hurloss-public-rebuild`, recomputed
       on our tracks and compared with STORM v4's.

    STORM v4's tracks are on 4TU, which is down, so its side comes from the numbers the
    hurricane layer committed when it ran on them (`hurloss-public-rebuild/results/layer/`).
    Its basin statistics weren't saved, so step 1 compares with the record and Odériz &
    Losada only.
    """)
    return


@app.cell
def _(HERE, Path, RESULTS, json):
    run = json.loads((RESULTS / "run.json").read_text())
    first_season, last_season = run["baseline"]
    track_files = sorted(
        Path(run["track_folder"]).glob("STORM_DATA_IBTRACS_NA_1000_YEARS_*.txt"),
        key=lambda p: int(p.stem.rsplit("_", 1)[1]),
    )
    assert len(track_files) * 1000 == run["years"], "regenerate.py hasn't finished every file"
    layer = HERE.parent / "hurloss-public-rebuild" / "results" / "layer"
    assert layer.exists(), "needs the hurricane layer's committed results next to this folder"
    return first_season, last_season, layer, run, track_files


@app.cell
def _(RemoteZip, cached, session):
    # Odériz & Losada's 1980-2021 climatology: the North Atlantic files out of a 0.7 GB zip,
    # read with HTTP range requests.
    _url = "https://zenodo.org/records/15097665/files/IB1980-2021.zip?download=1"
    oderiz_files = [
        cached("oderiz-losada", f"STORM_DATA_IBTRACS_NA_1000_YEARS_{i}.txt") for i in range(10)
    ]
    if not all(f.exists() for f in oderiz_files):
        with RemoteZip(_url, session=session()) as _archive:
            for _target in oderiz_files:
                _data = _archive.read(f"IB1980-2021/{_target.name}")
                _target.with_suffix(".partial").write_bytes(_data)
                _target.with_suffix(".partial").rename(_target)
    return (oderiz_files,)


@app.cell
def _(np, pd):
    # STORM's text format: one row per 3-hourly fix, 10-minute wind in m/s.
    columns = ["year", "month", "tc", "step", "basin", "lat", "lon", "pressure", "wind_ms"]

    def read_storm(paths: list) -> pd.DataFrame:
        """Fixes from STORM files, with a storm id unique across files and 1-minute knots."""
        parts = []
        for index, path in enumerate(paths):
            raw = pd.read_csv(path, header=None, usecols=range(9), names=columns)
            raw["storm"] = index * 10_000_000 + raw["year"] * 1000 + raw["tc"]
            raw["lon"] = ((raw["lon"] + 180) % 360) - 180
            # STORM's own conversion from 10-minute to 1-minute wind, then m/s to knots.
            raw["wind_kt"] = raw["wind_ms"] / 0.88 * 1.943844
            parts.append(raw[["storm", "month", "lat", "lon", "wind_kt"]])
        return pd.concat(parts, ignore_index=True)

    def saffir_simpson(wind_kt: np.ndarray) -> np.ndarray:
        """Category from 1-minute wind in knots: 0 is a tropical storm."""
        return np.searchsorted([64, 83, 96, 113, 137], wind_kt, side="right")

    return read_storm, saffir_simpson


@app.cell
def _(oderiz_files, read_storm, track_files):
    catalogues = {"ours": read_storm(track_files), "oderiz_losada": read_storm(oderiz_files)}
    catalogue_years = {"ours": 1000 * len(track_files), "oderiz_losada": 10_000}
    {k: f"{v['storm'].nunique():,} storms" for k, v in catalogues.items()}
    return catalogue_years, catalogues


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Basin statistics

    The observed side is exactly what STORM was fitted to: the North Atlantic tracks that
    `regenerate.py`'s preprocessing kept (tropical-storm strength or more, 3-hourly, cut at
    extratropical transition), read back from its own files. Categories use each storm's
    lifetime peak 1-minute wind.
    """)
    return


@app.cell
def _(Path, first_season, last_season, np, pd, run):
    _work = Path(run["track_folder"]).parents[1] / "runs" / f"ibtracs_{first_season}_{last_season}"

    def _read(name: str) -> dict:
        return np.load(_work / f"{name}_INTERP.npy", allow_pickle=True).item()

    _wind, _basin, _year = _read("WINDLIST"), _read("BASINLIST"), _read("YEARLIST")
    _rows = [
        {"year": int(_year[i][0]), "peak_kt": np.nanmax(_wind[i]) / 0.88 * 1.943844}
        for i in _wind
        if len(_wind[i]) > 0 and _basin[i][0] == 1
    ]
    observed_storms = pd.DataFrame(_rows)
    observed_storms.groupby("year").size().describe()
    return (observed_storms,)


@app.cell
def _(
    catalogue_years,
    catalogues,
    first_season,
    last_season,
    np,
    observed_storms,
    pd,
    saffir_simpson,
    write,
):
    def _summary(peaks: np.ndarray, years: float) -> dict:
        category = saffir_simpson(peaks)
        row: dict[str, float] = {"storms_per_year": len(peaks) / years}
        row["hurricanes_per_year"] = (category >= 1).sum() / years
        row["majors_per_year"] = (category >= 3).sum() / years
        for _c in range(6):
            row[f"share_cat{_c}"] = (category == _c).mean()
        return row

    _rows = []
    for _label, (_start, _end) in {
        f"observed {first_season}-{last_season}": (first_season, last_season),
        "observed 1980-2021 (Oderiz & Losada's years)": (1980, 2021),
        "observed 1980-2017 (STORM v4's years)": (1980, 2017),
    }.items():
        _picked = observed_storms[observed_storms["year"].between(_start, _end)]
        _rows.append(
            {"source": _label, **_summary(_picked["peak_kt"].to_numpy(), _end - _start + 1)}
        )
    for _name, _fixes in catalogues.items():
        _peaks = _fixes.groupby("storm")["wind_kt"].max().to_numpy()
        _rows.append({"source": _name, **_summary(_peaks, catalogue_years[_name])})
    # STORM v4's input genesis rate, from the files it shipped on Zenodo (6337644).
    _rows.append({"source": "STORM v4 (fitted genesis rate)", "storms_per_year": 10.8})
    basin_statistics = pd.DataFrame(_rows)
    write(basin_statistics, "basin_statistics.csv")
    basin_statistics
    return (basin_statistics,)


@app.cell
def _(basin_statistics, mo):
    _b = basin_statistics.set_index("source")
    _obs = _b.iloc[0]
    _ours = _b.loc["ours"]
    mo.md(f"""
    Our run forms {_ours["storms_per_year"]:.1f} storms a year against
    {_obs["storms_per_year"]:.1f} observed, as it should, since the Poisson rate is fitted to
    that count. Hurricanes: {_ours["hurricanes_per_year"]:.1f} a year against
    {_obs["hurricanes_per_year"]:.1f}; major hurricanes {_ours["majors_per_year"]:.2f} against
    {_obs["majors_per_year"]:.2f}. Odériz & Losada's run sits beside ours.
    """)
    return


@app.cell
def _(RESULTS, basin_statistics, plt, write):
    _shares = basin_statistics.dropna(subset=["share_cat0"]).set_index("source")
    _shares = _shares[[f"share_cat{c}" for c in range(6)]]
    _fig, _ax = plt.subplots(figsize=(8, 3.5))
    _shares.T.plot.bar(ax=_ax, width=0.8)
    _ax.set_xticklabels(["TS", "Cat 1", "Cat 2", "Cat 3", "Cat 4", "Cat 5"], rotation=0)
    _ax.set_ylabel("share of storms (lifetime peak)")
    _ax.legend(fontsize=7)
    _fig.tight_layout()
    _fig.savefig(RESULTS / "category_shares.png", dpi=130)
    write(_shares.reset_index(), "category_shares.csv")
    _fig
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Return periods on the US coast

    NHC publishes how often a hurricane (≥ 64 kt) and a major hurricane (≥ 96 kt) passes
    within 50 nautical miles of points on the coast (HURISK, [nhc.noaa.gov/climo](https://www.nhc.noaa.gov/climo/)),
    read by eye in `hurloss-public-rebuild`. The same count runs on every catalogue. Observed
    tracks are IBTrACS's US-agency winds, 1900 to the last season. STORM v4's column is the one
    the hurricane layer computed on its 10,000 years.
    """)
    return


@app.cell
def _(
    cached,
    catalogue_years,
    catalogues,
    download,
    last_season,
    layer,
    np,
    pd,
    write,
    xr,
):
    # Name, lat, lon, NHC years between hurricanes and between major hurricanes within 50 nm.
    sites = [
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
    _na = download(
        "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-"
        "stewardship-ibtracs/v04r01/access/netcdf/IBTrACS.NA.v04r01.nc",
        cached("ibtracs", "IBTrACS.NA.v04r01.nc"),
    )
    with xr.open_dataset(_na, decode_times=False) as _data:
        _season = _data["season"].values
        _keep = (_season >= 1900) & (_season <= last_season)
        _shape = _data["usa_lat"].values[_keep].shape
        _observed = pd.DataFrame(
            {
                "storm": np.repeat(np.flatnonzero(_keep), _shape[1]),
                "lat": _data["usa_lat"].values[_keep].ravel(),
                "lon": _data["usa_lon"].values[_keep].ravel(),
                "wind_kt": _data["usa_wind"].values[_keep].ravel(),
            }
        ).dropna()
    _sets = {
        **{k: (v, catalogue_years[k]) for k, v in catalogues.items()},
        "observed": (_observed, last_season - 1900 + 1),
    }
    _rows = []
    for _name, _lat, _lon, _nhc_hurricane, _nhc_major in sites:
        _row: dict[str, object] = {
            "site": _name,
            "nhc_hurricane_years": _nhc_hurricane,
            "nhc_major_years": _nhc_major,
        }
        for _label, (_f, _years) in _sets.items():
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
        _rows.append(_row)
    return_periods = pd.DataFrame(_rows)
    _v4 = pd.read_csv(layer / "check_return_periods.csv").set_index("site")
    return_periods["storm_v4_hurricane_years"] = return_periods["site"].map(
        _v4["storm_hurricane_years"]
    )
    return_periods["storm_v4_major_years"] = return_periods["site"].map(_v4["storm_major_years"])
    write(return_periods, "return_periods.csv")
    return_periods.set_index("site").round(1)
    return (return_periods,)


@app.cell
def _(np, pd, return_periods, write):
    # One number per catalogue and threshold: the median over sites of its rate over NHC's.
    _rows = []
    for _source in ("ours", "oderiz_losada", "storm_v4", "observed"):
        _row: dict[str, object] = {"source": _source}
        for _kind in ("hurricane", "major"):
            _rate_ratio = (
                return_periods[f"nhc_{_kind}_years"] / return_periods[f"{_source}_{_kind}_years"]
            )
            _row[f"{_kind}_rate_vs_nhc_median"] = float(np.median(_rate_ratio))
            _row[f"{_kind}_rate_vs_storm_v4_median"] = float(
                np.median(
                    return_periods[f"storm_v4_{_kind}_years"]
                    / return_periods[f"{_source}_{_kind}_years"]
                )
            )
        _rows.append(_row)
    coastal_summary = pd.DataFrame(_rows)
    write(coastal_summary, "return_periods_summary.csv")
    coastal_summary
    return (coastal_summary,)


@app.cell
def _(coastal_summary, mo):
    _c = coastal_summary.set_index("source")
    mo.md(f"""
    Read as rates, our run puts {_c.loc["ours", "hurricane_rate_vs_storm_v4_median"]:.2f}× STORM
    v4's hurricanes and {_c.loc["ours", "major_rate_vs_storm_v4_median"]:.2f}× its major
    hurricanes near these sites (median over sites), and
    {_c.loc["ours", "hurricane_rate_vs_nhc_median"]:.2f}× and
    {_c.loc["ours", "major_rate_vs_nhc_median"]:.2f}× NHC's. STORM v4 itself was at
    {_c.loc["storm_v4", "hurricane_rate_vs_nhc_median"]:.2f}× and
    {_c.loc["storm_v4", "major_rate_vs_nhc_median"]:.2f}×: the coastal shortfall the hurricane
    layer found is STORM's, and rerunning it on newer data doesn't remove it.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Our hurricane layer on the new tracks

    The layer's multiplier for a county is FEMA's Eq. 11-12: the Saffir-Simpson-weighted
    frequency of hurricane wind, averaged over 0.25° grid points within 1 km of the county,
    with Knutson et al.'s (2020) frequency changes per scenario over today's, floored at 1. The
    code below is the layer's own (`hurloss-public-rebuild/notebook.py` and `fri.py`), copied
    so this folder runs alone: same grid, CLIMADA Holland wind fields from hourly tracks,
    Knutson median. The swap replaces STORM v4 with our tracks, and does the same for Odériz
    & Losada's as a yardstick: two independent STORM runs on almost the same record show how
    much the county numbers move for reasons that aren't ours.
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
    _shapes = gpd.read_parquet(_target).rename(columns={"GEOID": "fips"}).set_index("fips")
    _lat, _lon = np.meshgrid(
        np.arange(24.0, 49.0, 0.25), np.arange(-107.0, -66.5, 0.25), indexing="ij"
    )
    _lat, _lon = _lat.ravel(), _lon.ravel()
    _points = gpd.GeoDataFrame(geometry=gpd.points_from_xy(_lon, _lat), crs="EPSG:4326")
    _points = _points.to_crs("EPSG:5070")
    _counties = _shapes[["geometry"]].to_crs("EPSG:5070")
    _in_box = _counties.cx[_points.total_bounds[0] : _points.total_bounds[2], :]
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
def _(
    Centroids,
    TCTracks,
    TropCyclone,
    WORKERS,
    cached,
    get_knutson_scaling_factor,
    grid_lat,
    grid_lon,
    log,
    np,
    pathos,
    pd,
    sparse,
    time,
):
    from dataclasses import dataclass, replace

    category_floor_ms = np.array([32.92, 42.70, 49.39, 58.13, 70.48])
    category_weight = np.array([1.0, 2.0, 4.0, 8.0, 16.0])
    scenarios = {
        "MID_LOWER": ("4.5", 2050),
        "MID_HIGHER": ("8.5", 2050),
        "LATE_LOWER": ("4.5", 2100),
        "LATE_HIGHER": ("8.5", 2100),
    }

    @dataclass(frozen=True)
    class Events:
        """Peak wind per event and grid point, with each event's annual rate."""

        wind: sparse.csr_matrix
        frequency: np.ndarray
        category: np.ndarray
        basin: np.ndarray
        years: tuple[int, int]

    def wind_events(path: str, name: str, years: tuple[int, int], rate: float) -> Events:
        """CLIMADA wind on the grid for one STORM file, cached as `name`."""
        target = cached("hazard", f"{name}.h5")
        if not target.exists():
            start = time.perf_counter()
            pool = pathos.pools.ProcessPool(nodes=WORKERS)
            raw = TCTracks.from_simulations_storm(path)
            south, north = grid_lat.min() - 2, grid_lat.max() + 2
            west, east = grid_lon.min() - 2, grid_lon.max() + 2
            near = []
            for track in raw.data:
                track = track.assign_coords(lon=((track.lon + 180) % 360) - 180)
                inside = (track.lat > south) & (track.lat < north)
                if (inside & (track.lon > west) & (track.lon < east)).any():
                    near.append(track)
            tracks = TCTracks(data=near)
            tracks.equal_timestep(time_step_h=1.0, pool=pool)
            hazard = TropCyclone.from_tracks(
                tracks,
                centroids=Centroids(lat=grid_lat, lon=grid_lon),
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
        assert np.allclose(hazard.centroids.lat, grid_lat), f"{name} was cached on other points"
        return Events(
            wind=sparse.csr_matrix(hazard.intensity),
            frequency=np.full(hazard.size, rate),
            category=np.asarray(hazard.category),
            basin=np.asarray(hazard.basin),
            years=years,
        )

    def county_intensity(events: Events, point_county: pd.Series) -> pd.Series:
        """Eq. 11 per county: F1 + 2 F2 + 4 F3 + 8 F4 + 16 F5 from the mean over its points."""
        reached = [(events.wind >= floor).astype(float) for floor in category_floor_ms]
        frequency = np.stack([np.asarray(r.T @ events.frequency).ravel() for r in reached], 1)
        values = (frequency @ category_weight)[point_county.index.to_numpy()]
        return pd.Series(values, index=point_county.to_numpy()).groupby(level=0).mean()

    def knutson_percent(variable: str, scenario: str, basin: str, years: tuple[int, int]) -> float:
        rcp, year = scenarios[scenario]
        table = get_knutson_scaling_factor(
            variable=variable, percentile="50", basin=basin, baseline=years, yearly_steps=5
        )
        return float(table.loc[year, rcp])

    def frequency_only(events: Events, scenario: str) -> Events:
        """Knutson's Cat 4-5 change for Cat 4-5 events; the rest keep the all-storm change."""
        frequency = events.frequency.copy()
        strong = np.isin(events.category, [4, 5])
        for basin in np.unique(events.basin):
            rows = events.basin == basin
            all_change = knutson_percent("cat05", scenario, str(basin), events.years) / 100
            strong_change = knutson_percent("cat45", scenario, str(basin), events.years) / 100
            weak_total = frequency[rows & ~strong].sum()
            strong_total = frequency[rows & strong].sum()
            assert weak_total > 0, f"no Cat 0-3 events in basin {basin}"
            weak_change = (
                all_change * (weak_total + strong_total) - strong_change * strong_total
            ) / weak_total
            frequency[rows & strong] *= 1 + strong_change
            frequency[rows & ~strong] *= 1 + weak_change
        assert np.all(frequency >= 0), "climate scaling made a frequency negative"
        return replace(events, frequency=frequency)

    def multipliers(events: Events, point_county: pd.Series) -> pd.DataFrame:
        """HM per county and scenario at the Knutson median; blank where no Cat 1 wind."""
        today = county_intensity(events, point_county)
        table = pd.DataFrame(index=today.index)
        for scenario in scenarios:
            future = county_intensity(frequency_only(events, scenario), point_county)
            table[scenario] = (future / today.where(today > 0)).clip(lower=1.0)
        return table

    return Events, multipliers, scenarios, wind_events


@app.cell
def _(
    Events,
    first_season,
    last_season,
    np,
    oderiz_files,
    sparse,
    track_files,
    wind_events,
):
    def _catalogue(paths: list, tag: str, years: tuple[int, int]) -> Events:
        parts = [
            wind_events(str(p), f"{tag}_file{i}_grid0.25", years, 1 / (1000 * len(paths)))
            for i, p in enumerate(paths)
        ]
        return Events(
            wind=sparse.csr_matrix(sparse.vstack([p.wind for p in parts])),
            frequency=np.concatenate([p.frequency for p in parts]),
            category=np.concatenate([p.category for p in parts]),
            basin=np.concatenate([p.basin for p in parts]),
            years=years,
        )

    wind = {
        "ours": _catalogue(
            track_files, f"ours_{first_season}_{last_season}", (first_season, last_season)
        ),
        "oderiz_losada": _catalogue(oderiz_files, "oderiz_losada_1980_2021", (1980, 2021)),
    }
    return (wind,)


@app.cell
def _(layer, multipliers, pd, point_county, scenarios, wind, write):
    _v4 = pd.read_csv(layer / "county_multipliers.csv", dtype={"unit": str}).set_index("unit")
    county_hm = {name: multipliers(events, point_county) for name, events in wind.items()}
    _rows = []
    for _name, _table in county_hm.items():
        for _s in scenarios:
            _theirs = _v4[f"{_s}_HM_STORM"].dropna()
            _mine = _table[_s].dropna()
            _both = _mine.index.intersection(_theirs.index)
            _rows.append(
                {
                    "catalogue": _name,
                    "scenario": _s,
                    "counties_both": len(_both),
                    "counties_catalogue": len(_mine),
                    "counties_storm_v4": len(_theirs),
                    "median_catalogue": _mine[_both].median(),
                    "median_storm_v4": _theirs[_both].median(),
                    "spearman_vs_storm_v4": _mine[_both].corr(_theirs[_both], method="spearman"),
                    "median_abs_difference": (_mine[_both] - _theirs[_both]).abs().median(),
                    "p90_abs_difference": (_mine[_both] - _theirs[_both]).abs().quantile(0.9),
                }
            )
    multiplier_check = pd.DataFrame(_rows)
    write(multiplier_check, "county_multipliers_vs_storm_v4.csv")
    write(
        pd.concat({k: v for k, v in county_hm.items()}, axis=1).rename_axis("fips"),
        "county_multipliers.csv",
        index=True,
    )
    multiplier_check
    return (multiplier_check,)


@app.cell
def _(mo, multiplier_check):
    _m = multiplier_check.set_index(["catalogue", "scenario"])
    _o, _l = _m.loc["ours"], _m.loc["oderiz_losada"]
    mo.md(f"""
    Across the four scenarios our tracks give a county median of
    {_o["median_catalogue"].min():.3f}-{_o["median_catalogue"].max():.3f} against STORM v4's
    {_o["median_storm_v4"].min():.3f}-{_o["median_storm_v4"].max():.3f}, with Spearman
    {_o["spearman_vs_storm_v4"].min():.2f}-{_o["spearman_vs_storm_v4"].max():.2f}. Odériz &
    Losada's rerun, against the same STORM v4 numbers, gets Spearman
    {_l["spearman_vs_storm_v4"].min():.2f}-{_l["spearman_vs_storm_v4"].max():.2f}. The levels
    agree; the county ranking of a few-percent multiplier is mostly sampling noise between any
    two 10,000-year runs, ours or theirs.
    """)
    return


if __name__ == "__main__":
    app.run()

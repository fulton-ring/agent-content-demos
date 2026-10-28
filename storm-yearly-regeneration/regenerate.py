import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import datetime
    import importlib
    import json
    import os
    import re
    import shutil
    import sys
    import time
    from concurrent.futures import ProcessPoolExecutor, ThreadPoolExecutor
    from pathlib import Path

    import marimo as mo
    import numcodecs
    import numpy as np
    import pandas as pd
    import xarray as xr

    import generator
    from common import (
        CACHE,
        RESULTS,
        SEED,
        WORKERS,
        YEARS,
        cached,
        download,
        log,
        read_pickled_npy,
        session,
        sha256,
        write,
    )

    return (
        CACHE,
        Path,
        ProcessPoolExecutor,
        RESULTS,
        SEED,
        ThreadPoolExecutor,
        WORKERS,
        YEARS,
        cached,
        datetime,
        download,
        importlib,
        generator,
        json,
        log,
        mo,
        np,
        numcodecs,
        os,
        pd,
        re,
        read_pickled_npy,
        session,
        sha256,
        shutil,
        sys,
        time,
        write,
        xr,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Regenerating STORM's North Atlantic tracks from the latest IBTrACS

    Our hurricane layer depends on STORM (Bloemendaal et al. 2020): 10,000 years of synthetic
    tropical cyclone tracks resampled from the IBTrACS record of 1980-2017. Its only host,
    4TU.ResearchData, has been unreachable since 2026-10-22, and STORM itself is frozen on that
    38-year record. **Can we rerun STORM ourselves, on IBTrACS through the latest complete
    season, every year?**

    This notebook does the run ([issue #142](https://github.com/fulton-ring/agent-content-demos/issues/142)):

    1. Download IBTrACS and find the latest complete North Atlantic season.
    2. Download STORM's own code from its author's GitHub, pinned to a commit, and patch the few
       lines that stop it running here.
    3. Rebuild STORM's environmental inputs (monthly mean sea-level pressure and sea-surface
       temperature) from ERA5 over the same years.
    4. Run STORM's preprocessing, which fits every coefficient the generator needs.
    5. Run the generator with a fixed seed: 10 files of 1,000 years, as STORM publishes them.

    `validate.py` checks the tracks against the record, STORM v4 and Odériz & Losada's rerun;
    `publish.py` writes the yearly release.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. IBTrACS and the latest complete season

    STORM's preprocessing reads IBTrACS's global since-1980 file. A season is complete when
    every North Atlantic track in it is a final best track: IBTrACS marks storms still waiting
    for NHC's post-season review as `PROVISIONAL`. `STORM_LAST_SEASON` overrides the choice.
    """)
    return


@app.cell
def _(cached, datetime, download, np, os, pd, sha256, xr):
    _url = (
        "https://www.ncei.noaa.gov/data/international-best-track-archive-for-climate-"
        "stewardship-ibtracs/v04r01/access/netcdf/IBTrACS.since1980.v04r01.nc"
    )
    # IBTrACS is updated weekly, so each day's run keeps its own copy.
    _today = datetime.date.today().isoformat()
    ibtracs_path = download(_url, cached("ibtracs", _today, "IBTrACS.since1980.v04r01.nc"))
    with xr.open_dataset(ibtracs_path, decode_times=False) as _data:
        _na = _data["basin"].values[:, 0] == b"NA"
        _seasons = pd.DataFrame(
            {
                "season": _data["season"].values[_na].astype(int),
                "provisional": _data["track_type"].values[_na] == b"PROVISIONAL",
            }
        )
    _by_season = _seasons.groupby("season").agg(
        storms=("provisional", "size"), provisional=("provisional", "sum")
    )
    _complete = _by_season.index[(_by_season["provisional"] == 0) & (_by_season.index >= 1980)]
    first_season = 1980
    last_season = int(os.environ.get("STORM_LAST_SEASON", _complete.max()))
    assert last_season in _complete, f"season {last_season} is not complete in IBTrACS"
    assert np.array_equal(_complete[_complete <= last_season], np.arange(1980, last_season + 1))
    ibtracs_record = {
        "name": "IBTrACS v04r01 since 1980",
        "url": _url,
        "file": ibtracs_path.name,
        "sha256": sha256(ibtracs_path),
        "bytes": ibtracs_path.stat().st_size,
    }
    _by_season.tail(4)
    return first_season, ibtracs_path, ibtracs_record, last_season


@app.cell
def _(first_season, last_season, mo):
    mo.md(f"""
    The baseline is **{first_season}-{last_season}**, {last_season - first_season + 1} seasons
    against STORM v4's 38.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. STORM's code

    The author's two GitHub repositories, [STORM](https://github.com/NBloemendaal/STORM)
    (generator) and [STORM-preprocessing](https://github.com/NBloemendaal/STORM-preprocessing),
    are GPL-3.0. Zenodo record [6337644](https://zenodo.org/records/6337644) (CC-BY-4.0)
    holds a copy of the same scripts plus STORM v4's fitted inputs, which we use below as a
    check. We download the scripts from GitHub at fixed commits, at run time, so this repository
    holds none of them.

    One file needs care: `coastal_basemap_data.npy` is a pickle, and unpickling a downloaded
    file can run arbitrary code. It is read with an unpickler that accepts only NumPy arrays
    and rewritten as a plain `.npz`.
    """)
    return


@app.cell
def _(cached, download, np, read_pickled_npy, sha256):
    storm_commits = {
        "STORM": "a9a2b142539536ada4581cf9bef25f026cdeae17",
        "STORM-preprocessing": "a7893efbe6b2e270796f57cb0bbaae366e989d98",
    }
    _files = {
        "STORM": [
            "SELECT_BASIN.py",
            "SAMPLE_STARTING_POINT.py",
            "SAMPLE_TC_MOVEMENT.py",
            "SAMPLE_TC_PRESSURE.py",
            "SAMPLE_RMAX.py",
            "coastal_basemap_data.npy",
        ],
        "STORM-preprocessing": [
            "preprocessing.py",
            "coefficients.py",
            "environmental.py",
            "genesis_matrix_python3.py",
            "Land_ocean_mask_NA.txt",
        ],
    }
    storm_sources = {}
    code_records = []
    for _repo, _names in _files.items():
        for _name in _names:
            _url = (
                f"https://raw.githubusercontent.com/NBloemendaal/{_repo}/"
                f"{storm_commits[_repo]}/{_name}"
            )
            _path = download(_url, cached("storm-code", storm_commits[_repo][:7], _name))
            storm_sources[_name] = _path
            code_records.append(
                {
                    "name": f"{_repo}/{_name}",
                    "url": _url,
                    "file": _name,
                    "sha256": sha256(_path),
                    "bytes": _path.stat().st_size,
                }
            )
    _coast = cached("storm-code", "coastal_basemap.npz")
    if not _coast.exists():
        _points = read_pickled_npy(storm_sources["coastal_basemap_data.npy"])
        assert isinstance(_points, dict) and set(_points) == {"lons", "lats"}
        np.savez(_coast, lons=np.asarray(_points["lons"]), lats=np.asarray(_points["lats"]))
    storm_sources["coastal_basemap.npz"] = _coast
    del storm_sources["coastal_basemap_data.npy"]
    return code_records, storm_commits, storm_sources


@app.cell
def _(mo):
    mo.md(r"""
    ### What we change, and why

    The scripts are unmaintained research code. Each change below replaces one exact piece of
    text and fails loudly if that text isn't there exactly as often as expected. Three kinds:

    - **The baseline.** STORM v4 hard-codes 1980-2017 (`years<2018`, and a divide by 38 for
      the yearly genesis rate).
    - **Bugs that stop it running.** `pressure_coefficients` builds its North Atlantic
      longitude bins with `linspace` over 255-354°, which isn't a multiple of 5°, so it fails on
      the first lookup; we use the 5° bins it means. The Python 3 genesis script saves its
      grids with `np.save` under a `.txt` name, which the generator can't read back (the
      "file names need fixing by hand" the Zenodo README warns about). NumPy now needs
      `allow_pickle=True` to read the pickles STORM writes for itself. Every module saves next
      to `sys.argv[0]`, which under a notebook is the notebook's own folder.
    - **Speed, without changing what is simulated.** The generator rereads its input files
      (26 MB of pressure field per storm) and brute-forces the distance to the coast over 1.1
      million points at every 3-hourly step. We cache the reads and use a k-d tree, which gives
      the same nearest distance. It also calls its genesis routine, which draws a whole year of
      random numbers, at every time step only to read the basin's edges; we read the edges
      directly. That changes which random numbers each storm gets, not their distribution.
    """)
    return


@app.cell
def _(first_season, last_season, re):
    _years = last_season - first_season + 1
    _all = [
        "preprocessing.py",
        "coefficients.py",
        "environmental.py",
        "genesis_matrix_python3.py",
        "SELECT_BASIN.py",
        "SAMPLE_STARTING_POINT.py",
        "SAMPLE_TC_MOVEMENT.py",
        "SAMPLE_TC_PRESSURE.py",
        "SAMPLE_RMAX.py",
    ]
    _generator = _all[4:]
    _loaders = "\n".join(
        [
            "import numpy as np",
            "import numpy as _numpy",
            "import functools as _functools",
            "",
            "@_functools.cache",
            "def _load(path, **_ignored):",
            "    # Only ever reads pickles that STORM's own preprocessing wrote in this run.",
            "    return _numpy.load(path, allow_pickle=True, encoding='latin1')",
            "",
            "@_functools.cache",
            "def _loadtxt(path):",
            "    return _numpy.loadtxt(path)",
            "",
        ]
    )
    _old_coast = "\n".join(
        [
            "    D = np.load(fpath,encoding = 'latin1').tolist()",
            "",
            "    lons,lats = D['lons'],D['lats']",
            "",
            "    dists = np.sqrt((lons-lon)**2+(lats-lat)**2)",
            "    mindist=np.min(dists)*degree_in_km",
        ]
    )
    _coast = "\n".join(
        [
            "    from scipy.spatial import cKDTree",
            "    if fpath not in _coast_trees:",
            "        D = np.load(fpath.replace('coastal_basemap_data.npy', 'coastal_basemap.npz'))",
            "        _coast_trees[fpath] = cKDTree(np.column_stack([D['lons'], D['lats']]))",
            "    mindist=_coast_trees[fpath].query([lon,lat])[0]*degree_in_km",
        ]
    )
    _old_bounds = "s,monthdummy,lat0,lat1,lon0,lon1=Basins_WMO(basin)"
    _new_bounds = "lat0,lat1,lon0,lon1=Basin_bounds(basin)"
    _bounds = "\n".join(
        [
            "def Basin_bounds(basin):",
            "    return {'EP':(5,60,180,285),'NA':(5,60,255,359),'NI':(5,60,30,100),",
            "            'SI':(-60,-5,10,135),'SP':(-60,-5,135,240),'WP':(5,60,100,180)}[basin]",
            "",
            "def Basins_WMO(basin):",
        ]
    )
    # (files, old text, new text, times it must occur in each file, kind)
    patches = [
        (
            ["preprocessing.py"],
            "if years[i]<2018:",
            f"if {first_season}<=years[i]<={last_season}:",
            1,
            "baseline",
        ),
        (
            ["preprocessing.py"],
            "round(poisson[idx][0]/38.,1)",
            f"round(poisson[idx][0]/{_years}.,1)",
            1,
            "baseline",
        ),
        (
            ["environmental.py"],
            "            lonbins1=np.linspace(lon0,lon11-5,(lon11-5-lon0)//step+1)",
            "            lonbins1=np.arange(lon0,lon0+int((lon11-lon0)/5)*5,step)",
            1,
            "bug",
        ),
        (
            ["genesis_matrix_python3.py"],
            "np.save(os.path.join(__location__,'GRID_GENESIS_MATRIX_{}_{}.txt'",
            "np.savetxt(os.path.join(__location__,'GRID_GENESIS_MATRIX_{}_{}.txt'",
            1,
            "bug",
        ),
        (["genesis_matrix_python3.py"], "    plt.imshow(grid)\n    plt.show()\n", "", 1, "bug"),
        (
            ["environmental.py"],
            "_INTERP.npy')).item()",
            "_INTERP.npy'),allow_pickle=True).item()",
            5,
            "bug",
        ),
        (
            _all,
            "dir_path=os.path.dirname(os.path.realpath(sys.argv[0]))",
            "dir_path=os.path.dirname(os.path.realpath(__file__))",
            1,
            "bug",
        ),
        (
            ["genesis_matrix_python3.py"],
            "    for basin,idx in zip(['EP','NA','NI','SI','SP','WP'],range(0,6)):",
            "    for basin,idx in [('NA',1)]:",
            1,
            "speed",
        ),
        (
            ["environmental.py"],
            "MSLP=np.loadtxt(os.path.join(__location__,'Monthly_mean_MSLP_'+str(month)+'.txt'))",
            "MSLP=_loadtxt(os.path.join(__location__,'Monthly_mean_MSLP_'+str(month)+'.txt'))",
            1,
            "speed",
        ),
        (["environmental.py"], "import numpy as np\n", _loaders, 1, "speed"),
        (["SAMPLE_TC_PRESSURE.py"], _old_coast, _coast, 1, "speed"),
        (
            ["SAMPLE_TC_PRESSURE.py"],
            "def distance_from_coast(",
            "_coast_trees = {}\n\ndef distance_from_coast(",
            1,
            "speed",
        ),
        (["SELECT_BASIN.py"], "def Basins_WMO(basin):", _bounds, 1, "speed"),
        (["SAMPLE_TC_MOVEMENT.py"], _old_bounds, _new_bounds, 2, "speed"),
        (
            ["SAMPLE_TC_PRESSURE.py", "SAMPLE_STARTING_POINT.py"],
            _old_bounds,
            _new_bounds,
            1,
            "speed",
        ),
        (
            ["SAMPLE_STARTING_POINT.py"],
            "s,monthdummy,lat0_WMO,lat1_WMO,lon0_WMO,lon1_WMO=Basins_WMO(basin)",
            "lat0_WMO,lat1_WMO,lon0_WMO,lon1_WMO=Basin_bounds(basin)",
            1,
            "speed",
        ),
        (
            ["SAMPLE_STARTING_POINT.py", "SAMPLE_TC_MOVEMENT.py", "SAMPLE_TC_PRESSURE.py"],
            "from SELECT_BASIN import Basins_WMO",
            "from SELECT_BASIN import Basins_WMO, Basin_bounds",
            1,
            "speed",
        ),
        (_generator, "import numpy as np\n", _loaders, 1, "speed"),
    ]

    def patch_source(name: str, text: str) -> str:
        """STORM's file `name` with every patch for it applied; fails on any mismatch."""
        text = text.replace("\r\n", "\n")
        for files, old, new, times, _kind in patches:
            if name in files:
                found = text.count(old)
                assert found == times, f"{name}: expected {times} of {old[:60]!r}, found {found}"
                text = text.replace(old, new)
        if name in _generator:
            # After the patches above, every remaining read goes through the cached loaders.
            text = re.sub(r"\bnp\.loadtxt\(", "_loadtxt(", text)
            text = re.sub(r"\bnp\.load\((?!fpath\.replace)", "_load(", text)
        return text

    return patch_source, patches


@app.cell
def _(pd, patches):
    pd.DataFrame(
        [
            {"kind": k, "files": ", ".join(f), "replaces": o.strip().splitlines()[0][:70]}
            for f, o, _n, _t, k in patches
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Environmental fields from ERA5

    STORM's preprocessing needs ERA5 monthly mean sea-level pressure (MSLP) and sea-surface
    temperature (SST) at 0.25°, averaged over the same years as the tracks. MSLP is the
    environmental pressure in the wind-pressure relation and in the generator; SST and MSLP
    together give the maximum potential intensity that caps each storm.

    Copernicus serves monthly means only to registered users, and NCAR's mirror presented an
    invalid certificate from here. Google's public
    [ARCO-ERA5](https://github.com/google-research/arco-era5) store needs no account and is
    updated to within a few months of today, but holds hourly fields. A mean over 8 hours per
    month (days 1, 4, 8, 12, 16, 20, 24 and 28, rotating through 00, 06, 12 and 18 UTC so the
    daily pressure tide cancels) over 46 years is 368 samples per calendar month. Below it is
    checked against the field STORM shipped.
    """)
    return


@app.cell
def _(
    ThreadPoolExecutor,
    cached,
    first_season,
    last_season,
    log,
    np,
    numcodecs,
    session,
    time,
):
    _store = (
        "https://storage.googleapis.com/gcp-public-data-arco-era5/ar/"
        "full_37-1h-0p25deg-chunk-1.zarr-v3"
    )
    _days = (1, 4, 8, 12, 16, 20, 24, 28)
    _hours = (0, 6, 12, 18, 0, 6, 12, 18)
    _client = session()

    def _field(variable: str, hour: int) -> np.ndarray:
        # One chunk is one hour of the whole globe, 721 x 1440, Blosc-compressed float32.
        response = _client.get(f"{_store}/{variable}/{hour}.0.0", timeout=120)
        response.raise_for_status()
        return np.frombuffer(numcodecs.Blosc().decode(response.content), "<f4").reshape(721, 1440)

    era5_means = {}
    _start = time.perf_counter()
    for _variable, _short in (
        ("mean_sea_level_pressure", "MSLP"),
        ("sea_surface_temperature", "SST"),
    ):
        for _month in range(1, 13):
            _target = cached("era5", f"{_short}_{first_season}_{last_season}_{_month}.npy")
            if not _target.exists():
                _index = [
                    int(
                        (
                            np.datetime64(f"{y}-{_month:02d}-{d:02d}T{h:02d}")
                            - np.datetime64("1900-01-01T00")
                        )
                        / np.timedelta64(1, "h")
                    )
                    for y in range(first_season, last_season + 1)
                    for d, h in zip(_days, _hours, strict=True)
                ]
                _total = np.zeros((721, 1440))
                with ThreadPoolExecutor(16) as _pool:
                    for _values in _pool.map(lambda i, v=_variable: _field(v, i), _index):
                        _total += _values
                np.save(_target, _total / len(_index))
                log.info("ERA5 %s month %d: %d samples", _short, _month, len(_index))
            era5_means[(_short, _month)] = np.load(_target)
    era5_seconds = time.perf_counter() - _start
    era5_record = {
        "name": "ERA5 (ARCO, Google Cloud public data)",
        "url": _store,
        "file": f"msl and sst, 8 hours a month, {first_season}-{last_season}",
        "sha256": "",
        "bytes": 0,
    }
    return era5_means, era5_record, era5_seconds


@app.cell
def _(cached, download, era5_means, np, pd, write):
    # STORM's shipped MSLP fields (Zenodo 6337644), in hPa, for the hurricane season.
    _rows = []
    for _month in range(6, 12):
        _shipped = np.loadtxt(
            download(
                f"https://zenodo.org/records/6337644/files/Monthly_mean_MSLP_{_month}.txt?download=1",
                cached("zenodo-6337644", f"Monthly_mean_MSLP_{_month}.txt"),
            )
        )
        # North Atlantic box, 5-60 N and 255-359 E, on the 0.25 degree grid.
        _ours = era5_means[("MSLP", _month)][120:341, 1020:1437] / 100
        _difference = _ours - _shipped[120:341, 1020:1437]
        _rows.append(
            {
                "month": _month,
                "mean_difference_hpa": _difference.mean(),
                "median_abs_difference_hpa": np.median(np.abs(_difference)),
                "p95_abs_difference_hpa": np.percentile(np.abs(_difference), 95),
                "max_abs_difference_hpa": np.abs(_difference).max(),
            }
        )
    mslp_check = pd.DataFrame(_rows)
    write(mslp_check, "inputs_mslp_vs_storm_v4.csv")
    mslp_check
    return (mslp_check,)


@app.cell
def _(mo, mslp_check):
    mo.md(f"""
    Over the North Atlantic in June-November our pressure field is within
    {mslp_check["median_abs_difference_hpa"].max():.2f} hPa of STORM's at the median grid point
    and {mslp_check["max_abs_difference_hpa"].max():.1f} hPa at worst. That gap mixes the extra
    years and our sampling, and is small next to the 10-100 hPa pressure drops it is subtracted
    from. Both fields are therefore reproducible from public data each year.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. STORM's preprocessing

    Everything goes in one folder per baseline: the patched scripts, IBTrACS, the ERA5 fields
    in the text format STORM reads, and every file the preprocessing writes. In order, as in
    STORM's `master_preprocessing.py`:

    - `extract_data`, `TC_variables`: tracks with at least tropical-storm wind (18 m/s,
      10-minute), cut at extratropical transition, at 3-hourly steps; genesis rate, months,
      places and pressures.
    - `track_coefficients`: per 5° latitude band, the regressions for the next step's change in
      latitude and longitude.
    - `wind_pressure_relationship`, `calculate_MPI_fields`, `pressure_coefficients`: per month
      the wind-pressure fit, the SST-based potential-intensity fit, and per 5° box the
      regression for the next change in pressure.
    - `Change_genesis_locations`: per month a 1° grid of genesis density.

    The SST and MSLP monthly-mean functions are skipped: step 3 already wrote their output.
    """)
    return


@app.cell
def _(
    cached,
    era5_means,
    first_season,
    ibtracs_path,
    importlib,
    last_season,
    log,
    np,
    patch_source,
    shutil,
    storm_sources,
    sys,
    time,
    xr,
):
    work = cached("runs", f"ibtracs_{first_season}_{last_season}", "x").parent
    _done = work / "COEFFICIENTS_JM_PRESSURE.npy"
    _start = time.perf_counter()
    if not (_done.exists() and (work / "GRID_GENESIS_MATRIX_1_11.txt").exists()):
        for _name, _path in storm_sources.items():
            if _name.endswith(".py"):
                (work / _name).write_text(patch_source(_name, _path.read_text()))
            else:
                shutil.copy(_path, work / _name)
        shutil.copy(ibtracs_path, work / "IBTrACS.nc")
        for _month in range(1, 13):
            np.savetxt(work / f"Monthly_mean_MSLP_{_month}.txt", era5_means[("MSLP", _month)] / 100)
            np.savetxt(work / f"Monthly_mean_SST_{_month}.txt", era5_means[("SST", _month)])
        # The fitting functions open this file only for the grid's coordinates.
        xr.Dataset(
            coords={"latitude": np.linspace(90, -90, 721), "longitude": np.arange(1440) * 0.25}
        ).to_netcdf(work / "Monthly_mean_SST.nc")

        sys.path.insert(0, str(work))
        # STORM's modules exist only in `work`, downloaded at run time.
        preprocessing = importlib.import_module("preprocessing")
        coefficients = importlib.import_module("coefficients")
        environmental = importlib.import_module("environmental")
        genesis_matrix_python3 = importlib.import_module("genesis_matrix_python3")

        with xr.open_dataset(work / "IBTrACS.nc", decode_times=False) as _ibtracs:
            preprocessing.extract_data(_ibtracs)
        preprocessing.TC_variables()
        coefficients.track_coefficients()
        environmental.wind_pressure_relationship()
        environmental.calculate_MPI_fields()
        environmental.pressure_coefficients()
        genesis_matrix_python3.Change_genesis_locations(None)
        log.info("preprocessing %d-%d done", first_season, last_season)
    preprocessing_seconds = time.perf_counter() - _start
    assert _done.exists(), "preprocessing wrote no pressure coefficients"
    return preprocessing_seconds, work


@app.cell
def _(mo):
    mo.md(r"""
    ### Our coefficients against STORM v4's

    The Zenodo record ships the IBTrACS-based inputs STORM v4 was generated from. If our
    preprocessing is STORM's, the same quantities should come out close, and differ only where
    eight more seasons moved them.
    """)
    return


@app.cell
def _(cached, download, np, pd, read_pickled_npy, work, write):
    from typing import Any

    def _shipped(name: str) -> Any:
        _path = download(
            f"https://zenodo.org/records/6337644/files/{name}?download=1",
            cached("zenodo-6337644", name),
        )
        return np.loadtxt(_path) if name.endswith(".txt") else read_pickled_npy(_path)

    def _ours(name: str) -> Any:
        _path = work / name
        return (
            np.loadtxt(_path) if name.endswith(".txt") else np.load(_path, allow_pickle=True).item()
        )

    _rows = [
        {
            "quantity": "genesis rate (storms a year)",
            "storm_v4": _shipped("POISSON_GENESIS_PARAMETERS.txt")[1],
            "ours": _ours("POISSON_GENESIS_PARAMETERS.txt")[1],
        }
    ]
    _months_v4 = np.asarray(_shipped("GENESIS_MONTHS.npy")[1])
    _months = np.asarray(_ours("GENESIS_MONTHS.npy")[1])
    for _m in range(6, 12):
        _rows.append(
            {
                "quantity": f"share of genesis in month {_m}",
                "storm_v4": (_months_v4 == _m).mean(),
                "ours": (_months == _m).mean(),
            }
        )
    # Zenodo's wind-pressure file holds one basin's months only (5-11), so it isn't compared.
    _mpi_v4 = _shipped("COEFFICIENTS_MPI_PRESSURE_DROP_MONTH_new.npy")[1]
    _mpi = _ours("COEFFICIENTS_MPI_PRESSURE_DROP_MONTH.npy")[1]
    _genesis_v4 = _shipped("DP0_PRES_GENESIS.npy")[1]
    _genesis = _ours("DP0_PRES_GENESIS.npy")[1]
    for _m in (8, 9, 10):
        _rows.append(
            {
                "quantity": f"potential pressure drop at 28 C SST, month {_m} (hPa)",
                "storm_v4": _mpi_v4[_m][0] + _mpi_v4[_m][1] * np.exp(_mpi_v4[_m][2] * -2),
                "ours": _mpi[_m][0] + _mpi[_m][1] * np.exp(_mpi[_m][2] * -2),
            }
        )
        _rows.append(
            {
                "quantity": f"mean genesis pressure, month {_m} (hPa)",
                "storm_v4": _genesis_v4[_m][0],
                "ours": _genesis[_m][0],
            }
        )
    coefficient_check = pd.DataFrame(_rows)
    write(coefficient_check, "inputs_coefficients_vs_storm_v4.csv")
    coefficient_check
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. The generator

    STORM's `MASTER.py` loop, in `generator.py` so a process pool can run it: for each year draw
    the number of storms (Poisson), their months and genesis points, walk each track with the
    latitude-band regressions until it leaves the basin, then evolve its pressure and wind with
    the box regressions, capped by potential intensity and decayed over land. Each 1,000-year
    file gets its own seed, `STORM_SEED × 1000 + file`, so any file can be regenerated alone.
    """)
    return


@app.cell
def _(
    ProcessPoolExecutor,
    SEED,
    WORKERS,
    YEARS,
    cached,
    first_season,
    generator,
    last_season,
    log,
    pd,
    work,
    write,
):
    track_folder = cached("tracks", f"ibtracs_{first_season}_{last_season}_seed{SEED}", "x").parent
    track_files = [
        track_folder / f"STORM_DATA_IBTRACS_NA_1000_YEARS_{i}.txt" for i in range(YEARS // 1000)
    ]
    _todo = [(i, f) for i, f in enumerate(track_files) if not f.exists()]
    _seconds = {}
    with ProcessPoolExecutor(max_workers=min(WORKERS, max(len(_todo), 1))) as _pool:
        _jobs = {
            i: _pool.submit(generator.run_chunk, work, SEED * 1000 + i, 1000, f) for i, f in _todo
        }
        for _i, _job in _jobs.items():
            _seconds[_i] = _job.result()
            log.info("file %d: %.0f s", _i, _seconds[_i])
    run_timing = pd.DataFrame(
        {
            "file": range(len(track_files)),
            "seed": [SEED * 1000 + i for i in range(len(track_files))],
            "seconds_this_run": [_seconds.get(i) for i in range(len(track_files))],
            "megabytes": [f.stat().st_size / 1e6 for f in track_files],
        }
    )
    if _seconds:
        write(run_timing, "run_timing.csv")
    run_timing
    return run_timing, track_files, track_folder


@app.cell
def _(
    RESULTS,
    SEED,
    WORKERS,
    YEARS,
    code_records,
    era5_record,
    era5_seconds,
    first_season,
    ibtracs_record,
    json,
    last_season,
    os,
    pd,
    preprocessing_seconds,
    run_timing,
    storm_commits,
    track_folder,
):
    # What publish.py needs to describe this run; timings are kept from the run that made them.
    _previous = RESULTS / "run.json"
    _old = json.loads(_previous.read_text()) if _previous.exists() else {}
    _same = _old.get("baseline") == [first_season, last_season] and _old.get("seed") == SEED
    _generated = run_timing["seconds_this_run"].notna().all()
    run = {
        "baseline": [first_season, last_season],
        "seed": SEED,
        "years": YEARS,
        "workers": WORKERS,
        "cpu_count": os.cpu_count(),
        "storm_commits": storm_commits,
        "track_folder": str(track_folder),
        "era5_seconds": era5_seconds
        if era5_seconds > 60 or not _same
        else _old.get("era5_seconds"),
        "preprocessing_seconds": preprocessing_seconds
        if preprocessing_seconds > 60 or not _same
        else _old.get("preprocessing_seconds"),
        "generator_cpu_seconds": float(run_timing["seconds_this_run"].sum())
        if _generated or not _same
        else _old.get("generator_cpu_seconds"),
        "track_megabytes": float(run_timing["megabytes"].sum()),
        "inputs": [ibtracs_record, era5_record, *code_records],
    }
    (RESULTS / "run.json").write_text(json.dumps(run, indent=2))
    pd.Series({k: v for k, v in run.items() if k not in ("inputs", "storm_commits")})
    return


if __name__ == "__main__":
    app.run()

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import os
    import subprocess
    import tarfile
    import time
    import warnings
    import zipfile
    from pathlib import Path

    import bezpy
    import geopandas as gpd
    import h5py
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import scipy.sparse as sp
    import xarray as xr
    import zstandard
    from pysecs import SECS
    from scipy.sparse.csgraph import connected_components
    from scipy.sparse.linalg import spsolve
    from scipy.spatial import cKDTree
    from scipy.special import erf, erfinv, log_ndtr
    from shapely.ops import substring

    started = time.perf_counter()
    return (
        Path,
        SECS,
        bezpy,
        cKDTree,
        connected_components,
        erf,
        erfinv,
        gpd,
        h5py,
        log_ndtr,
        mo,
        np,
        os,
        pd,
        plt,
        subprocess,
        sp,
        spsolve,
        started,
        substring,
        tarfile,
        time,
        warnings,
        xr,
        zipfile,
        zstandard,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Does a fuller substation map change where a geomagnetic storm hits the US grid hardest?

    **The question.** The national storm-loss model in AGU Advances this fall (Oughton, Bor et al. 2026, C-SWIM)
    built its grid from HIFLD transmission lines and 10,464 OpenStreetMap substations of 161 kV and up, and says
    Washington and New York came out sparse because its 2024 OpenStreetMap query returned few substations there.
    Its headline: a 100-year storm puts 3.45 million people out of power and costs 1.22 billion USD a day; a
    250-year storm, 5.1 million people and 1.81 billion a day. We rerun the same model on HIFLD Next lines and our
    verified substation file (`us-substations-verified/dataset/`) and measure what moves.

    **Steps.** (1) Download C-SWIM's published data. (2) Build both grids the way C-SWIM does. (3) Turn the 92
    storms of 1985 to 2024 into line voltages and fit the 100- and 250-year values. (4) Solve the induced
    currents in a Monte Carlo over transformer setups, turn them into failure probabilities, people and dollars.
    (5) Check the rerun against the paper. (6) Compare before and after, by state and county.

    **How we run C-SWIM.** C-SWIM's code is open (MIT) but written for a workstation with a GPU and its own data
    folders, so we don't import it. Each step below is a short rewrite of the C-SWIM function named in the cell,
    run on C-SWIM's own published inputs, and each is checked against C-SWIM's published outputs. Only counts and
    totals by state and county are written to `outputs/`; no substation locations or per-site results.
    """)
    return


@app.cell
def _(Path, mo, os, subprocess, time):
    DATA = Path(os.environ.get("DATA_DIR", mo.notebook_dir() / "data"))
    OUT = Path(os.environ.get("OUTPUT_DIR", mo.notebook_dir() / "outputs"))
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)

    def download(url: str, name: str) -> Path:
        """Download url to DATA/name once with curl, resuming after dropped connections (at most 8 tries)."""
        path = DATA / name
        if path.exists():
            return path
        part = path.with_suffix(path.suffix + ".part")
        for attempt in range(8):
            done = subprocess.run(["curl", "-fsSL", "-C", "-", "-o", str(part), url], check=False)
            if done.returncode == 0:
                part.rename(path)
                return path
            print(f"{name}: curl exit {done.returncode} (try {attempt + 1} of 8)")
            time.sleep(2**attempt)
        raise RuntimeError(f"Could not download {url}")

    return DATA, OUT, download


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Data

    | Input | Source |
    |---|---|
    | C-SWIM data release v5 (May 2026): storms, observatory fields, published grid, line voltages, results |
    [Zenodo 20089397](https://zenodo.org/records/20089397), 11 GB; we keep 10 files (1.5 GB) |
    | Magnetotelluric transfer functions (USArray, USMTArray) | C-SWIM's release
    [Zenodo 16994602](https://zenodo.org/records/16994602), 0.9 GB; we keep the XML files |
    | HIFLD Next Transmission Lines v1.0.0 | [HIFLD Next](https://hifld.publicenvirodata.org/) GeoParquet |
    | Our substations | `us-substations-verified/dataset/us_substations.parquet` on `main` (71,625 points) |
    | Population | Census 2020 block-group population centroids |
    | Counties | Census 2024 cartographic boundaries, 1:500k |

    The C-SWIM archive is a single zstd tar, so it has to be downloaded whole once (about 30 minutes).
    """)
    return


@app.cell
def _(DATA, download, tarfile, zstandard):
    CSWIM_FILES = (
        "statistical_analysis/geomagnetic_data_return_periods.h5",
        "storm_maxes/maxV_arr_testing_2.npy",
        "storm_maxes/delaunay_v_gannon.npy",
        "admittance_matrix/substation_info.csv",
        "Electric__Power_Transmission_Lines/Electric__Power_Transmission_Lines.",
        "geomag_data/processed_geomag_data.nc",
        "kp_ap_indices/storm_periods.csv",
        "data/nerc_gdf.geojson",
        "gic_processing_batches/summary_batch_",
        "EMTF/USMTArray_unique_grid_points_1616_sites.txt",
    )
    CSWIM = DATA / "cswim"
    if not (CSWIM / "done").exists():
        _archive = download(
            "https://zenodo.org/records/20089397/files/c-swim-data-v5.tar.zst?download=1", "c-swim-data-v5.tar.zst"
        )
        with (
            open(_archive, "rb") as _f,
            tarfile.open(fileobj=zstandard.ZstdDecompressor().stream_reader(_f), mode="r|") as _tar,
        ):
            for _m in _tar:
                if _m.isfile() and any(w in _m.name for w in CSWIM_FILES):
                    _tar.extract(_m, CSWIM, filter="data")
        (CSWIM / "done").touch()
        _archive.unlink()
    EMTF = DATA / "emtf"
    if not (EMTF / "done").exists():
        _bundle = download(
            "https://zenodo.org/records/16994602/files/data-tl-emtf-storms.tar.gz?download=1",
            "data-tl-emtf-storms.tar.gz",
        )
        with tarfile.open(_bundle, "r:gz") as _tar:
            for _m in _tar:
                if _m.isfile() and "/EMTF/" in _m.name and _m.name.endswith(".xml"):
                    _tar.extract(_m, EMTF, filter="data")
        (EMTF / "done").touch()
        _bundle.unlink()
    CS = CSWIM / "data"
    return CS, EMTF


@app.cell
def _(CS, DATA, download, gpd, mo, pd, zipfile):
    hifld_next = gpd.read_parquet(
        download(
            "https://storage.googleapis.com/hifld-next-datasets-prod/hifld/transmission-lines-1/transmission-lines-1/"
            "v1.0.0/geoparquet/transmission-lines-1.parquet",
            "hifld_next_transmission_lines.parquet",
        )
    )
    hifld_next = hifld_next.rename(columns={"source_ID": "ID"})
    cswim_lines = gpd.read_file(CS / "Electric__Power_Transmission_Lines/Electric__Power_Transmission_Lines.shp")
    ours = gpd.read_parquet(mo.notebook_dir().parent / "us-substations-verified/dataset/us_substations.parquet")
    published_subs = pd.read_csv(CS / "admittance_matrix/substation_info.csv", dtype={"name": str})
    regions = gpd.read_file(CS / "nerc_gdf.geojson")
    _zip = download("https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_county_500k.zip", "counties.zip")
    with zipfile.ZipFile(_zip) as _z:
        _z.extractall(DATA / "counties")
    counties = gpd.read_file(DATA / "counties/cb_2024_us_county_500k.shp")[["GEOID", "STUSPS", "NAME", "geometry"]]
    block_groups = pd.read_csv(
        download(
            "https://www2.census.gov/geo/docs/reference/cenpop2020/blkgrp/CenPop2020_Mean_BG.txt", "cenpop2020_bg.txt"
        ),
        encoding="utf-8-sig",
        dtype={"STATEFP": str},
    )
    _shared = set(cswim_lines.loc[cswim_lines.VOLTAGE >= 160, "ID"].astype(str)) & set(
        hifld_next.loc[hifld_next.VOLTAGE >= 160, "ID"].astype(str)
    )
    print(
        f"Lines of 160 kV+: C-SWIM's HIFLD copy {(cswim_lines.VOLTAGE >= 160).sum():,}, "
        f"HIFLD Next {(hifld_next.VOLTAGE >= 160).sum():,}, same ID in both {len(_shared):,}"
    )
    return block_groups, counties, cswim_lines, hifld_next, ours, published_subs, regions


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Build both grids the way C-SWIM does

    `preprocess/08_p_power_grid.py`: keep lines of 160 kV and up inside a FERC Order 1000 region, snap a
    substation to every line that passes within 150 m of it, order the substations along each line and split the
    line between neighbours. `scripts/build_admittance_matrix.py`: each substation gets a high-voltage bus at its
    highest line voltage and a low-voltage bus at its second highest (or a dummy one if it has a single voltage),
    and only lines that end on those two buses join the network. C-SWIM drops lines that leave the triangulation of
    its magnetotelluric sites (they can't be given a voltage); we do that in step 3.

    The *before* grid uses C-SWIM's HIFLD copy (June 2022) and the 10,464 substations in its published grid.
    The *after* grid uses HIFLD Next and our substation file. The two line files share almost every line, so the
    difference comes from the substations.
    """)
    return


@app.cell
def _(bezpy, gpd, np, pd, substring):
    VOLT_CLASS = {
        345: 345,
        230: 230,
        450: 500,
        500: 500,
        765: 765,
        250: 230,
        400: 345,
        232: 230,
        1000: 765,
        220: 230,
        273: 230,
        218: 230,
        236: 230,
        287: 345,
        238: 230,
        200: 230,
        167: 161,
        169: 161,
        161: 161,
    }
    R_PER_KM = {765: 0.01, 500: 0.0141, 345: 0.0283, 230: 0.0500, 161: 0.0800}

    def build_segments(lines: gpd.GeoDataFrame, subs: gpd.GeoDataFrame, regions: gpd.GeoDataFrame) -> tuple:
        """Line segments between neighbouring substations, and each substation's line voltages."""
        regions = regions.to_crs(4326)
        regions = regions[regions["REGIONS"] != "NotOrder1000"][["geometry"]]
        tl = lines.to_crs(4326).reset_index(drop=True).explode(index_parts=True).reset_index(level=1)
        tl["line_id"] = np.where(
            tl["level_1"] > 0, tl["ID"].astype(str) + "_" + tl["level_1"].astype(str), tl["ID"].astype(str)
        )
        tl = tl[tl["VOLTAGE"] >= 160].copy()
        tl["VOLTAGE"] = tl["VOLTAGE"].map(VOLT_CLASS).fillna(tl["VOLTAGE"])
        tl = gpd.sjoin(tl, regions, predicate="intersects").drop(columns="index_right")
        ss = gpd.sjoin(subs.to_crs(4326), regions, predicate="intersects").drop(columns="index_right")
        tl_p, ss_p = tl.to_crs(5070), ss.to_crs(5070)
        hits = gpd.sjoin(
            tl_p[["line_id", "VOLTAGE", "geometry"]],
            ss_p.set_geometry(ss_p.buffer(150))[["SS_ID", "geometry"]],
            predicate="intersects",
        )
        point, geom = (
            dict(zip(ss_p["SS_ID"], ss_p.geometry, strict=True)),
            dict(zip(tl_p["line_id"], tl_p.geometry, strict=True)),
        )
        volts = dict(zip(tl["line_id"], tl["VOLTAGE"], strict=True))
        sub_volts = hits.groupby("SS_ID")["VOLTAGE"].apply(list).to_dict()
        rows = []
        for lid, ids in hits.groupby("line_id")["SS_ID"].unique().items():
            g = geom[lid]
            order = [s for _, s in sorted((g.project(point[s]), s) for s in ids if g.distance(point[s]) <= 10000)]
            pairs = list(zip(order[:-1], order[1:], strict=True))
            for a, b in pairs:
                da, db = sorted((g.project(point[a]), g.project(point[b])))
                rows.append(
                    (
                        lid if len(pairs) == 1 else f"{lid}_{a}_{b}",
                        volts[lid],
                        a,
                        b,
                        g if len(pairs) == 1 else substring(g, da, db),
                    )
                )
        seg = gpd.GeoDataFrame(rows, columns=["LINE_ID", "kv", "sub_a", "sub_b", "geometry"], crs=5070).to_crs(4326)
        seg = seg[(seg.geometry.geom_type == "LineString") & (seg["kv"] >= 160)]
        seg["kv"] = seg["kv"].astype(int).map(VOLT_CLASS)
        seg = seg.dropna(subset=["kv"]).astype({"kv": int})
        seg["length"] = [bezpy.tl.TransmissionLine(r).length for r in seg.itertuples()]
        seg = seg[seg["length"] > 0].drop_duplicates(subset=["LINE_ID", "sub_a", "sub_b"]).reset_index(drop=True)
        return seg, sub_volts

    def build_grid(seg: pd.DataFrame, sub_volts: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Substation buses (build_substation_buses) and the lines that join them (flatten_substation_dict)."""
        rows = []
        for s in pd.unique(pd.concat([seg["sub_a"], seg["sub_b"]])):
            v = np.unique(np.array(sub_volts[s], dtype=float))[::-1]
            hv = f"{s}_{int(v[0])}"
            rows.append((s, hv, f"{s}_{int(v[1])}" if len(v) > 1 else hv + "lv", v[0], v[1] if len(v) > 1 else 0))
        buses = pd.DataFrame(rows, columns=["sub", "hv_bus", "lv_bus", "hv_kv", "lv_kv"])
        on_bus = set(buses["hv_bus"]) | set(buses.loc[buses["lv_kv"] > 0, "lv_bus"])
        lines = seg.assign(
            from_bus=seg["sub_a"] + "_" + seg["kv"].astype(str), to_bus=seg["sub_b"] + "_" + seg["kv"].astype(str)
        )
        lines = lines[lines["from_bus"].isin(on_bus) & lines["to_bus"].isin(on_bus)].drop_duplicates("LINE_ID")
        lines = lines.assign(R=lines["length"] * 1.03 * lines["kv"].map(R_PER_KM)).reset_index(drop=True)
        return buses, lines

    return build_grid, build_segments


@app.cell
def _(build_segments, cswim_lines, gpd, hifld_next, ours, published_subs, regions):
    _before_subs = gpd.GeoDataFrame(
        {"SS_ID": published_subs["name"]},
        crs=4326,
        geometry=gpd.points_from_xy(published_subs.longitude, published_subs.latitude),
    )
    _after_subs = gpd.GeoDataFrame(
        {"SS_ID": ours["id"].astype(str).values}, geometry=ours.geometry.values, crs=ours.crs
    )
    seg_before, volts_before = build_segments(cswim_lines, _before_subs, regions)
    seg_after, volts_after = build_segments(hifld_next, _after_subs, regions)
    return seg_after, seg_before, volts_after, volts_before


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Storm line voltages and the 100- and 250-year values

    `scripts/calc_storm_maxes.py`: for each of C-SWIM's 92 storms (1985 to 2024), fit spherical elementary current
    systems ([pysecs](https://github.com/greglucas/pysecs)) to the magnetic field at up to 26 observatories, predict
    the field at the magnetotelluric sites, convolve it with each site's impedance tensor
    ([bezpy](https://github.com/greglucas/bezpy)) to get the geoelectric field, and integrate that along each line
    with Delaunay interpolation. A line's voltage is linear in the site fields, so we write it as a sparse matrix
    once and get every line's voltage for every minute of a storm in one product. We keep each line's largest
    |V| per storm.

    Five of C-SWIM's 1,616 sites (KAN01 to KAN05) aren't in the public bundle, so we use the other 1,611.
    One run takes about 20 minutes, so the per-storm maxima are cached in `data/`.
    """)
    return


@app.cell
def _(bezpy, h5py, np, pd, sp):
    def line_matrix(geoms, site_latlon: np.ndarray) -> tuple:
        """Sparse C with V = E.reshape(T, 2 * sites) @ C, in volts; flags lines outside the site triangulation."""
        rows, cols, vals, outside = [], [], [], []
        for j, g in enumerate(geoms):
            tl = bezpy.tl.TransmissionLine(pd.Series({"geometry": g}))
            tl.set_delaunay_weights(site_latlon)
            vtx, wts = tl.delaunay_vtx[:-1], tl.delaunay_wts[:-1]
            outside.append(bool((wts < 0).any()))
            for c in (0, 1):
                rows.append((2 * vtx + c).ravel())
                vals.append((wts * tl.dl[:, c : c + 1] / 1000.0).ravel())
                cols.append(np.full(vtx.size, j))
        C = sp.coo_matrix(
            (np.concatenate(vals), (np.concatenate(rows), np.concatenate(cols))),
            shape=(2 * len(site_latlon), len(geoms)),
        ).tocsr()
        return C, np.array(outside)

    def published_line_values(path, line_ids: pd.Series, dataset: str) -> np.ndarray:
        """Look up a per-line array in C-SWIM's HDF5 by line ID (NaN where the line isn't in its grid)."""
        with h5py.File(path) as f:
            ids = [x.decode() for x in f["sites/transmission_lines/line_ids"][:]]
            values = f[dataset][:]
        return line_ids.map(dict(zip(ids, values, strict=True))).to_numpy(float)

    return line_matrix, published_line_values


@app.cell
def _(CS, EMTF, bezpy, h5py, np):
    with h5py.File(CS / "statistical_analysis/geomagnetic_data_return_periods.h5") as _f:
        _names = [n.decode() for n in _f["sites/mt_sites/names"][:]]
        _latlon = _f["sites/mt_sites/coordinates"][:]
    _xml = {p.name.split(".")[1]: p for p in EMTF.rglob("*.xml")}
    _have = np.array([n in _xml for n in _names])
    site_latlon = _latlon[_have]
    mt_sites = [bezpy.mt.read_xml(str(_xml[n])) for n, h in zip(_names, _have, strict=True) if h]
    print(
        f"Magnetotelluric sites: {len(mt_sites):,} of C-SWIM's {len(_names):,}; "
        f"missing {[n for n, h in zip(_names, _have, strict=True) if not h]}"
    )
    return mt_sites, site_latlon


@app.cell
def _(DATA, line_matrix, np, pd, seg_after, seg_before, site_latlon, sp):
    all_segs = pd.concat([seg_before.assign(grid="before"), seg_after.assign(grid="after")], ignore_index=True)
    if (DATA / "line_matrix.npz").exists():
        C = sp.load_npz(DATA / "line_matrix.npz")
        outside = np.load(DATA / "line_outside.npy")
    else:
        C, outside = line_matrix(all_segs.geometry.values, site_latlon)
        sp.save_npz(DATA / "line_matrix.npz", C)
        np.save(DATA / "line_outside.npy", outside)
    return C, all_segs, outside


@app.cell
def _(C, CS, DATA, SECS, mt_sites, np, pd, site_latlon, time, xr):
    _storms = pd.read_csv(CS / "kp_ap_indices/storm_periods.csv", parse_dates=["Start", "End"])
    _mag = xr.open_dataset(CS / "geomag_data/processed_geomag_data.nc").load()
    _R = 6371e3
    _lat, _lon = np.meshgrid(np.linspace(15, 85, 36), np.linspace(-175, -25, 76), indexing="ij")
    _secs_grid = np.column_stack([_lat.ravel(), _lon.ravel(), np.full(_lat.size, _R + 110e3)])
    _pred = np.column_stack([site_latlon, np.full(len(site_latlon), _R)])

    def _observatories(t0: pd.Timestamp, t1: pd.Timestamp) -> tuple[np.ndarray, np.ndarray]:
        """Observatories with no gaps in the window (build_common_stack_from_obsdict), less GUA and HON."""
        w = _mag.sel(time=slice(t0, t1))
        keep = [s for s in w.site.values if s.upper() not in ("GUA", "HON") and not np.isnan(w["B"].sel(site=s)).any()]
        w = w.sel(site=keep)
        return w["B"].values, np.column_stack([w["latitude"].values, w["longitude"].values, np.full(len(keep), _R)])

    (DATA / "storms").mkdir(exist_ok=True)
    _Z = {}
    _t = time.perf_counter()
    for _i, _s in _storms.iterrows():
        _out = DATA / "storms" / f"max_{_i:02d}.npy"
        if _out.exists():
            continue
        _pad = pd.Timedelta(hours=6)
        _B, _obs = _observatories(_s.Start - _pad, _s.End + _pad)
        _padded = _B.shape[0] >= 6 * 60 * 2 + 10
        if not _padded:
            _B, _obs = _observatories(_s.Start, _s.End)
        _std = np.ones(_B.shape)
        _std[..., 2] = np.inf
        _Bp = SECS(sec_df_loc=_secs_grid).fit(obs_loc=_obs, obs_B=_B, obs_std=_std, epsilon=0.05).predict_B(_pred)
        # bezpy's Site.convolve_fft for all sites at once; the impedances are interpolated once per FFT length
        _n0 = _Bp.shape[0]
        _n = 2 ** (int(np.log2(_n0)) + 2)
        if _n not in _Z:
            _Z[_n] = np.stack([s.calcZ(np.fft.rfftfreq(_n, d=60)) for s in mt_sites], axis=1)  # (4, sites, f)
        _X, _Y = np.fft.rfft(_Bp[:, :, 0], n=_n, axis=0).T, np.fft.rfft(_Bp[:, :, 1], n=_n, axis=0).T
        _E = np.stack(
            [
                np.fft.irfft(_Z[_n][0] * _X + _Z[_n][1] * _Y, axis=1)[:, :_n0].T,
                np.fft.irfft(_Z[_n][2] * _X + _Z[_n][3] * _Y, axis=1)[:, :_n0].T,
            ],
            axis=2,
        )
        if _padded:
            _E = _E[360:-360]
        _V = np.asarray(C.T @ np.nan_to_num(_E, nan=0.0, posinf=0.0, neginf=0.0).reshape(len(_E), -1).T).T
        np.save(_out, np.abs(_V).max(axis=0))
        if _s.Start.year == 2024 and _s.Start.month == 5:
            np.save(DATA / "storms" / "v_gannon.npy", _V.astype(np.float32))
        print(f"storm {_i + 1} of {len(_storms)}: {_V.shape[0]} minutes, {time.perf_counter() - _t:.0f} s so far")
    storm_max = np.column_stack([np.load(DATA / "storms" / f"max_{_i:02d}.npy") for _i in range(len(_storms))])
    v_gannon = np.load(DATA / "storms" / "v_gannon.npy")
    return storm_max, v_gannon


@app.cell
def _(mo):
    mo.md(r"""
    `scripts/stat_analysis.py`: for each line, draw 100 bootstrap samples of 39 storm maxima (one per year of
    the catalog), fit a lognormal truncated below at the sample's 1st percentile (what `powerlaw.Fit(...).lognormal`
    does), read off the 100- and 250-year level, and keep the median. We fit all lines of both grids at once in
    numpy instead of 3.5 million `powerlaw` fits, which takes about 10 minutes.
    """)
    return


@app.cell
def _(erf, erfinv, log_ndtr, np):
    def nll(mu: np.ndarray, ls: np.ndarray, y: np.ndarray, a: np.ndarray, w: np.ndarray) -> np.ndarray:
        """Negative log-likelihood of a normal in y = ln x truncated below at a (w marks the points used)."""
        n = w.sum(-1)
        z = (y - mu[..., None]) / np.exp(ls)[..., None]
        return n * ls + 0.5 * (w * z**2).sum(-1) + n * log_ndtr((mu - a) / np.exp(ls))

    def return_levels(
        maxima: np.ndarray, periods: tuple = (100, 250), n_years: int = 39, n_boot: int = 100, seed: int = 0
    ) -> np.ndarray:
        """Median bootstrap return level per line (rows of maxima are lines, columns storms)."""
        rng = np.random.default_rng(seed)
        out = np.full((len(maxima), len(periods)), np.nan)
        for lo in range(0, len(maxima), 2000):
            m = np.abs(maxima[lo : lo + 2000])
            x = np.sort(
                np.take_along_axis(m[:, None, :], rng.integers(0, m.shape[1], (len(m), n_boot, n_years)), axis=2),
                axis=2,
            )
            x = np.where(x > 1e-12, x, np.nan)
            xmin = np.maximum(np.nanmin(x, -1), np.nanpercentile(x, 1.0, axis=-1))
            w = (x >= xmin[..., None]).astype(float)
            y, a, n = np.log(np.where(w > 0, x, 1.0)), np.log(xmin), w.sum(-1)
            d = (y, a, w)

            mu = (w * y).sum(-1) / n
            ls = np.log(np.sqrt((w * (y - mu[..., None]) ** 2).sum(-1) / n) + 1e-6)
            h = 1e-4
            for _ in range(60):  # Newton steps on (mu, log sigma) with finite differences
                f0, fmp, fmm = nll(mu, ls, *d), nll(mu + h, ls, *d), nll(mu - h, ls, *d)
                fsp, fsm = nll(mu, ls + h, *d), nll(mu, ls - h, *d)
                gm, gs = (fmp - fmm) / (2 * h), (fsp - fsm) / (2 * h)
                hmm, hss = (fmp - 2 * f0 + fmm) / h**2, (fsp - 2 * f0 + fsm) / h**2
                hms = (nll(mu + h, ls + h, *d) - fmp - fsp + f0) / h**2
                det = hmm * hss - hms**2
                ok = (det > 0) & (hmm > 0)
                det = np.where(ok, det, 1.0)
                mu = mu - np.clip(np.where(ok, (hss * gm - hms * gs) / det, 0.1 * gm), -1, 1)
                ls = ls - np.clip(np.where(ok, (hmm * gs - hms * gm) / det, 0.1 * gs), -0.5, 0.5)
            sig = np.exp(ls)
            levels = []
            for p in periods:  # lognormal_ppf and calc_return_period
                q = np.clip(n_years / (p * n), 1e-12, 1 - 1e-12)
                arg = np.clip(erf((a - mu) / (np.sqrt(2) * sig)) * q - q + 1, -1 + 1e-12, 1 - 1e-12)
                levels.append(np.exp(np.clip(mu + np.sqrt(2) * sig * erfinv(arg), -27.6, 700)))
            out[lo : lo + 2000] = np.nanmedian(np.stack(levels, -1), axis=1)
        return out

    def polarity(v: np.ndarray) -> np.ndarray:
        """Sign of each line's voltage near its May 2024 peak (est_gic.v_direction)."""
        a = np.abs(v)
        top = a >= np.nanpercentile(a, 95, axis=0)[None]
        s = np.sign(np.nanmedian(np.where(top, v, np.nan), axis=0))
        return np.where(np.isfinite(s) & (s != 0), s, 1.0)

    return polarity, return_levels


@app.cell
def _(
    CS, DATA, all_segs, h5py, np, outside, polarity, published_line_values, return_levels, storm_max, v_gannon, warnings
):
    if (DATA / "return_levels.npy").exists():
        v_rp = np.load(DATA / "return_levels.npy")
    else:
        with warnings.catch_warnings():  # lines with no storm voltage (outside the sites) give all-NaN fits
            warnings.simplefilter("ignore", RuntimeWarning)
            v_rp = return_levels(storm_max)
        np.save(DATA / "return_levels.npy", v_rp)
    _sign = polarity(v_gannon)
    segs = all_segs.assign(v100=v_rp[:, 0] * _sign, v250=v_rp[:, 1] * _sign, outside=outside)
    # Checks against C-SWIM's published numbers, on the lines both runs share
    _h5 = CS / "statistical_analysis/geomagnetic_data_return_periods.h5"
    _pub_max = np.load(CS / "storm_maxes/maxV_arr_testing_2.npy", allow_pickle=False)
    _pub_v100 = published_line_values(_h5, all_segs["LINE_ID"], "predictions/V/100_year")
    _shared = (segs["grid"] == "before").to_numpy() & np.isfinite(_pub_v100) & ~outside
    _fit_on_theirs = return_levels(_pub_max[:3000])[:, 0]
    with h5py.File(_h5) as _f:
        _fit_ratio = _fit_on_theirs / _f["predictions/V/100_year"][:3000]
        _ids = {x.decode(): i for i, x in enumerate(_f["sites/transmission_lines/line_ids"][:])}
    _rows = segs.loc[_shared, "LINE_ID"].map(_ids).to_numpy()
    _storm_ratio = storm_max[_shared] / _pub_max[_rows]
    _v_ratio = np.abs(segs.loc[_shared, "v100"].to_numpy()) / _pub_v100[_shared]
    field_checks = {
        "lines shared with C-SWIM's grid": int(_shared.sum()),
        "our fit on C-SWIM's storm maxima / C-SWIM's 100-year V, median (first 3,000 lines)": np.nanmedian(_fit_ratio),
        "our storm maxima / C-SWIM's, median": np.nanmedian(_storm_ratio),
        "our storm maxima / C-SWIM's, 10th to 90th percentile": np.nanpercentile(_storm_ratio, [10, 90]).round(2),
        "our 100-year V / C-SWIM's, median": np.nanmedian(_v_ratio),
        "our 100-year V / C-SWIM's, 10th to 90th percentile": np.nanpercentile(_v_ratio, [10, 90]).round(2),
        "correlation of log 100-year V": np.corrcoef(
            np.log(np.abs(segs.loc[_shared, "v100"])), np.log(_pub_v100[_shared])
        )[0, 1],
    }
    for _k, _v in field_checks.items():
        print(f"{_k}: {_v:.3f}" if isinstance(_v, float) else f"{_k}: {_v}")
    return field_checks, segs


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Induced currents, failures, people and dollars

    `scripts/est_gic.py` with `build_admittance_matrix.py`: for each Monte Carlo draw, give every substation 1 or 2
    GY-D transformers if it has one voltage, else 1 to 3 picked from GY-GY, GY-GY-D and autotransformers; draw its
    earthing resistance from 0.1 to 0.2 ohm, with 1% left open; block 1% of lines. Put each line's voltage in as a
    current source V/R, solve the network (we use a sparse solver where C-SWIM uses a dense one), and take each
    transformer's effective current per phase (`postprocess/03_calc_eff_gic.py`). A substation's current is its
    largest transformer's.

    `econ/preprocess/p_gic_files.py`: the failure probability is a lognormal fragility around 75 A per phase,
    lowered for older transformers, with its spread, age and a penalty factor drawn at random. We average that over
    400,000 draws once into a curve. The people a substation serves are the Census 2020 block groups nearest to it
    (C-SWIM uses Voronoi cells around the substations, which is the same nearest-substation rule, with ZIP-level
    population spread over developed land). Affected people = sum of people x failure probability.

    `econ/scripts/econ_analysis.py`: the paper's loss is a Leontief model driven by the affected share of the
    population applied to national household and government spending, so it is a fixed number of dollars per
    affected person. We take that rate from the paper's own pairs (1.22 billion / 3.45 million and 1.81 billion /
    5.1 million) rather than rebuild the BEA tables.
    """)
    return


@app.cell
def _(connected_components, np, pd, sp, spsolve):
    WINDING = {"GY-GY-D": (0.2, 0.1), "GY-GY": (0.04, 0.06), "Auto": (0.04, 0.06), "GY-D": (0.05, np.inf)}

    def substation_currents(
        buses: pd.DataFrame, lines: pd.DataFrame, v: np.ndarray, n_draws: int, seed: int = 42
    ) -> np.ndarray:
        """Effective GIC (A/phase) per substation, per draw, per voltage column: shape (draws, subs, columns)."""
        rng = np.random.default_rng(seed)
        names = pd.unique(pd.concat([buses["hv_bus"], buses["lv_bus"]]))
        node = pd.Series(np.arange(len(names)), index=names)
        n_sub, n = len(buses), len(names) + len(buses)
        hv, lv = node[buses["hv_bus"]].to_numpy(), node[buses["lv_bus"]].to_numpy()
        neu = len(names) + np.arange(n_sub)
        single = (buses["lv_kv"] == 0).to_numpy()
        ratio = np.where(single, 1.0, buses["lv_kv"] / buses["hv_kv"])
        f, t, R = node[lines["from_bus"]].to_numpy(), node[lines["to_bus"]].to_numpy(), lines["R"].to_numpy()
        out = np.zeros((n_draws, n_sub, v.shape[1]))
        for d in range(n_draws):
            count = np.where(single, rng.integers(1, 3, n_sub), rng.integers(1, 4, n_sub))
            sub = np.repeat(np.arange(n_sub), count)
            kind = np.where(single[sub], "GY-D", np.array(["GY-GY", "GY-GY-D", "Auto"])[rng.integers(0, 3, len(sub))])
            w1, w2 = np.array([WINDING[k][0] for k in kind]), np.array([WINDING[k][1] for k in kind])
            b1 = np.where(kind == "Auto", lv[sub], neu[sub])  # autotransformer series winding runs HV to LV
            has2 = np.isfinite(w2)
            ok = rng.random(len(R)) >= 0.01
            a = np.concatenate([hv[sub], lv[sub][has2], f[ok]])
            b = np.concatenate([b1, neu[sub][has2], t[ok]])
            g = np.concatenate([1 / w1, 1 / w2[has2], 1 / R[ok]])
            Y = sp.coo_matrix((np.r_[g, g, -g, -g], (np.r_[a, b, a, b], np.r_[a, b, b, a])), shape=(n, n)).tocsr()
            rg = rng.uniform(0.1, 0.2, n_sub)
            rg[rng.choice(n_sub, n_sub // 100, replace=False)] = np.inf
            ye = np.zeros(n)
            ye[neu] = 1 / (3 * rg)
            _, comp = connected_components(Y, directed=False)
            keep = np.flatnonzero(np.isin(comp, comp[ye > 0]))
            J = np.zeros((n, v.shape[1]))
            np.add.at(J, t[ok], v[ok] / R[ok, None])
            np.add.at(J, f[ok], -v[ok] / R[ok, None])
            A = (Y + sp.diags(ye))[keep][:, keep] + 1e-6 * sp.eye(len(keep))
            V = np.zeros((n, v.shape[1]))
            V[keep] = spsolve(A.tocsc(), J[keep]).reshape(len(keep), -1)
            i1 = (V[hv[sub]] - V[b1]) / w1[:, None]
            i2 = np.where(has2[:, None], (V[lv[sub]] - V[neu[sub]]) / np.where(has2, w2, 1)[:, None], 0.0)
            np.maximum.at(out[d], sub, np.abs(i1 + i2 * ratio[sub][:, None]))
        return out

    return (substation_currents,)


@app.cell
def _(erf, np):
    _rng = np.random.default_rng(42)
    _n = 400_000
    _beta = 0.25 + 0.25 * _rng.random(_n)
    _cpen = 0.60 + 0.40 * _rng.random(_n)
    _age = np.where(_rng.random(_n) < 0.55, 33 + 17 * _rng.random(_n), 1 + 31 * _rng.random(_n))
    _f_age = 1 - np.exp(-((_age / (30 + 20 * _rng.random(_n))) ** (1 + 2 * _rng.random(_n))))
    _theta = 75.0 * (1 - 0.4 * _f_age)
    gic_grid = np.logspace(-2, 4, 601)
    pf_curve = np.array(
        [(0.5 * (1 + erf((np.log(_cpen) + np.log(g) - np.log(_theta)) / _beta / np.sqrt(2)))).mean() for g in gic_grid]
    )
    print(
        f"Mean failure probability at 25, 75 and 200 A/phase: {np.interp([25, 75, 200], gic_grid, pf_curve).round(3)}"
    )
    return gic_grid, pf_curve


@app.cell
def _(block_groups, cKDTree, gic_grid, np, pf_curve, substation_currents):
    PAPER = {
        "100": {"people": 3.45e6, "total": 1.22e9, "direct": 0.66e9},
        "250": {"people": 5.1e6, "total": 1.81e9, "direct": 0.98e9},
    }
    USD_PER_PERSON = {k: np.mean([PAPER[p][k] / PAPER[p]["people"] for p in PAPER]) for k in ("total", "direct")}
    _bg = block_groups[~block_groups["STATEFP"].isin(["02", "15", "72"])]

    def run_model(buses, lines, latlon: np.ndarray, v: np.ndarray, n_draws: int) -> dict:
        """Monte Carlo GIC -> failure probability -> people per substation; national totals per draw."""
        k = np.cos(np.deg2rad(38.0))
        _, nearest = cKDTree(np.c_[latlon[:, 1] * k, latlon[:, 0]]).query(np.c_[_bg.LONGITUDE * k, _bg.LATITUDE])
        people = np.bincount(nearest, weights=_bg.POPULATION, minlength=len(buses))
        gic = substation_currents(buses, lines, v, n_draws)
        pf = np.interp(np.log(np.maximum(gic, 1e-2)), np.log(gic_grid), pf_curve)
        affected = (pf * people[None, :, None]).sum(1)
        return {"people": people, "pf": pf.mean(0), "affected": affected, "gic_median": np.median(gic, axis=(0, 1))}

    return PAPER, USD_PER_PERSON, run_model


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Does the rerun reproduce the paper?

    Three runs on the *before* grid: (a) C-SWIM's own Monte Carlo output in its data release, (b) our solver fed
    C-SWIM's published line voltages and polarities, (c) our solver fed our recomputed voltages. (c) is the
    baseline for the comparison in step 6, so the before/after change uses the same chain end to end.
    """)
    return


@app.cell
def _(CS, build_grid, h5py, np, ours, polarity, published_subs, run_model, segs, time, volts_after, volts_before, xr):
    N_DRAWS = 1000

    def grid_for(name: str, sub_volts: dict) -> tuple:
        """C-SWIM drops lines outside the site triangulation before it builds the buses."""
        return build_grid(segs[(segs["grid"] == name) & ~segs["outside"]], sub_volts)

    buses_b, lines_b = grid_for("before", volts_before)
    buses_a, lines_a = grid_for("after", volts_after)
    _xy_b = published_subs.set_index("name")[["latitude", "longitude"]]
    _xy_a = ours.assign(id=ours["id"].astype(str), lat=ours.geometry.y, lon=ours.geometry.x).set_index("id")[
        ["lat", "lon"]
    ]
    _t = time.perf_counter()
    # (b) C-SWIM's published 100- and 250-year line voltages, signed by its May 2024 storm voltages
    with h5py.File(CS / "statistical_analysis/geomagnetic_data_return_periods.h5") as _f:
        _row = lines_b["LINE_ID"].map({x.decode(): i for i, x in enumerate(_f["sites/transmission_lines/line_ids"][:])})
        _has = _row.notna().to_numpy()
        _r = _row[_has].astype(int).to_numpy()
        _v = np.column_stack([_f["predictions/V/100_year"][:][_r], _f["predictions/V/250_year"][:][_r]])
    _gannon = np.load(CS / "storm_maxes/delaunay_v_gannon.npy", mmap_mode="r", allow_pickle=False)
    _v = _v * polarity(np.asarray(_gannon[:, _r]))[:, None]
    _lines_pub = lines_b[_has]
    _buses_pub = buses_b[buses_b["sub"].isin(set(_lines_pub["sub_a"]) | set(_lines_pub["sub_b"]))]
    run_pub = run_model(_buses_pub, _lines_pub, _xy_b.loc[_buses_pub["sub"]].to_numpy(), _v, N_DRAWS)
    # (c) and the after grid: our recomputed voltages
    run_before = run_model(
        buses_b,
        lines_b,
        _xy_b.loc[buses_b["sub"]].to_numpy(),
        np.nan_to_num(lines_b[["v100", "v250"]].to_numpy()),
        N_DRAWS,
    )
    run_after = run_model(
        buses_a,
        lines_a,
        _xy_a.loc[buses_a["sub"]].to_numpy(),
        np.nan_to_num(lines_a[["v100", "v250"]].to_numpy()),
        N_DRAWS,
    )
    # (a) C-SWIM's own Monte Carlo output (mean affected people per transformer draw)
    _ds = xr.concat(
        [xr.open_dataset(p) for p in sorted((CS / "econ_data/gic_processing_batches").glob("summary_batch_*.nc"))],
        dim="gic_realization",
    )
    cswim_mc = np.column_stack(
        [_ds["mean_pop_affected"].sel(scenario=f"e_{p}-year-hazard A/ph").values for p in ("100", "250")]
    )
    model_seconds = time.perf_counter() - _t
    print(f"Monte Carlo, {N_DRAWS} draws on each of three grids: {model_seconds:.0f} s")
    return N_DRAWS, buses_a, buses_b, cswim_mc, lines_a, lines_b, model_seconds, run_after, run_before, run_pub


@app.cell
def _(PAPER, USD_PER_PERSON, cswim_mc, mo, np, pd, run_after, run_before, run_pub):
    def summary(label: str, affected: np.ndarray) -> list[dict]:
        rows = []
        for j, p in enumerate(("100", "250")):
            a = affected[:, j]
            rows.append(
                {
                    "run": label,
                    "storm": f"{p}-year",
                    "people affected": a.mean(),
                    "5th pct": np.percentile(a, 5),
                    "95th pct": np.percentile(a, 95),
                    "daily loss, billion USD": a.mean() * USD_PER_PERSON["total"] / 1e9,
                    "gap to paper": a.mean() / PAPER[p]["people"] - 1,
                }
            )
        return rows

    totals = pd.DataFrame(
        [
            {
                "run": "paper (AGU Advances 2026)",
                "storm": f"{p}-year",
                "people affected": PAPER[p]["people"],
                "daily loss, billion USD": PAPER[p]["total"] / 1e9,
                "gap to paper": 0.0,
            }
            for p in PAPER
        ]
        + summary("(a) C-SWIM's own Monte Carlo, data release v5", cswim_mc)
        + summary("(b) our solver, C-SWIM's published line voltages", run_pub["affected"])
        + summary("(c) our full rerun, before: C-SWIM's grid", run_before["affected"])
        + summary("after: HIFLD Next + our substations", run_after["affected"])
    )
    mo.vstack(
        [
            mo.md(
                "**National totals.** Mean over Monte Carlo draws, with the 5th to 95th percentile across "
                "draws. Daily loss is people affected x the paper's own dollars per affected person."
            ),
            mo.ui.table(
                totals.round(
                    {
                        "people affected": -3,
                        "5th pct": -3,
                        "95th pct": -3,
                        "daily loss, billion USD": 2,
                        "gap to paper": 3,
                    }
                ),
                selection=None,
            ),
        ]
    )
    return (totals,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Before and after, by state and county

    Each substation is placed in its Census county. A county's expected affected population is the sum over its
    substations of people served x mean failure probability. We publish counts and these sums only. Counties with
    one or two substations in either grid are blanked (and, in any state with exactly one such county, the next
    smallest county too, so state totals can't recover a blanked row).
    """)
    return


@app.cell
def _(buses_a, buses_b, counties, gpd, np, ours, pd, published_subs, run_after, run_before):
    def by_county(buses: pd.DataFrame, latlon: np.ndarray, run: dict, tag: str) -> pd.DataFrame:
        pts = gpd.GeoDataFrame(geometry=gpd.points_from_xy(latlon[:, 1], latlon[:, 0]), crs=4326)
        fips = gpd.sjoin(pts, counties.to_crs(4326), predicate="within")["GEOID"].reindex(pts.index)
        df = pd.DataFrame(
            {
                "fips": fips.to_numpy(),
                f"subs_{tag}": 1,
                f"people_served_{tag}": run["people"],
                f"affected_100_{tag}": run["people"] * run["pf"][:, 0],
                f"affected_250_{tag}": run["people"] * run["pf"][:, 1],
            }
        )
        return df.groupby("fips").sum()

    _xy_a = ours.assign(id=ours["id"].astype(str), lat=ours.geometry.y, lon=ours.geometry.x).set_index("id")
    _xy_b = published_subs.set_index("name")
    county = pd.concat(
        [
            by_county(buses_b, _xy_b.loc[buses_b["sub"], ["latitude", "longitude"]].to_numpy(), run_before, "before"),
            by_county(buses_a, _xy_a.loc[buses_a["sub"], ["lat", "lon"]].to_numpy(), run_after, "after"),
        ],
        axis=1,
    ).fillna(0)
    _names = counties.set_index("GEOID")
    county.insert(0, "state", _names["STUSPS"].reindex(county.index))
    county.insert(1, "county", _names["NAME"].reindex(county.index))
    for _p in ("100", "250"):
        county[f"change_{_p}"] = county[f"affected_{_p}_after"] - county[f"affected_{_p}_before"]
    state = county.drop(columns="county").groupby("state").sum()
    state = state.sort_values("change_100", key=np.abs, ascending=False)
    return county, state


@app.cell
def _(OUT, county, mo, np, pd, state):
    _few = (county[["subs_before", "subs_after"]].replace(0, np.nan).min(axis=1) <= 2).to_numpy().copy()
    for _st, _g in county[_few].groupby("state"):
        if len(_g) == 1:  # one blanked county in a state could be recovered from the state total
            _rest = county[(county["state"] == _st) & ~_few]
            if len(_rest):
                _few[county.index.get_loc(_rest["subs_before"].add(_rest["subs_after"]).idxmin())] = True
    published = county.copy()
    _vals = [c for c in county.columns if c not in ("state", "county")]
    published.loc[_few, _vals] = np.nan
    published.insert(2, "few_substations", _few)
    _people_cols = [c for c in _vals if not c.startswith("subs_")]
    published[_people_cols] = published[_people_cols].round(-2)
    published = published.astype({"subs_before": "Int64", "subs_after": "Int64"})
    published.to_csv(OUT / "county_changes.csv", index_label="fips")
    _people = [c for c in state.columns if not c.startswith("subs_")]
    state.assign(**{c: state[c].round(-2) for c in _people}).astype({"subs_before": int, "subs_after": int}).to_csv(
        OUT / "state_changes.csv"
    )
    _top = published[~_few].sort_values("change_100", key=np.abs, ascending=False).head(15)
    mo.vstack(
        [
            mo.md(
                f"**States that move most** (100-year storm, people). {_few.sum()} of {len(county)} counties blanked."
            ),
            mo.ui.table(
                state.head(12)[
                    [
                        "subs_before",
                        "subs_after",
                        "affected_100_before",
                        "affected_100_after",
                        "change_100",
                        "change_250",
                    ]
                ].round(-2),
                selection=None,
            ),
            mo.md("**Counties that move most** (100-year storm, counties with 3+ substations in both grids)."),
            mo.ui.table(
                pd.DataFrame(
                    _top[
                        [
                            "state",
                            "county",
                            "subs_before",
                            "subs_after",
                            "affected_100_before",
                            "affected_100_after",
                            "change_100",
                        ]
                    ]
                ),
                selection=None,
            ),
        ]
    )
    return (published,)


@app.cell
def _(OUT, plt, state):
    _top = state.head(15).iloc[::-1]
    _fig, _ax = plt.subplots(figsize=(8, 5.5))
    _ax.barh(_top.index, _top["affected_100_before"] / 1e3, color="#9aa5b1", label="before: C-SWIM's grid")
    _ax.barh(
        _top.index,
        _top["affected_100_after"] / 1e3,
        color="none",
        edgecolor="#c2410c",
        linewidth=1.6,
        label="after: HIFLD Next + our substations",
    )
    _ax.set_xlabel("Expected people without power, 100-year storm (thousands)")
    _ax.set_title("The 15 states whose 100-year storm exposure moves most")
    _ax.legend(loc="lower right", frameon=False)
    _ax.spines[["top", "right"]].set_visible(False)
    _fig.tight_layout()
    _fig.savefig(OUT / "state_change.png", dpi=150)
    _fig
    return


@app.cell
def _(
    N_DRAWS,
    OUT,
    buses_a,
    buses_b,
    field_checks,
    lines_a,
    lines_b,
    mo,
    model_seconds,
    np,
    segs,
    started,
    time,
    totals,
    state,
    published,
    ours,
):
    _net = {
        "substations": (len(buses_b), len(buses_a)),
        "line segments inside the site triangulation (paper: 16,256)": tuple(
            int(((segs["grid"] == g) & ~segs["outside"]).sum()) for g in ("before", "after")
        ),
        "lines in the admittance network": (len(lines_b), len(lines_a)),
    }
    _t = totals.set_index(["run", "storm"])["people affected"]
    _b, _a = "(c) our full rerun, before: C-SWIM's grid", "after: HIFLD Next + our substations"
    _lines = [f"{k}: before {b:,}, after {a:,} (+{a - b:,}, {a / b - 1:+.1%})" for k, (b, a) in _net.items()]
    for _p in ("100-year", "250-year"):
        _lines.append(
            f"{_p} people affected: before {_t[(_b, _p)]:,.0f}, after {_t[(_a, _p)]:,.0f} "
            f"({_t[(_a, _p)] / _t[(_b, _p)] - 1:+.1%})"
        )
    for _p in ("100", "250"):
        _change = state[f"change_{_p}"].sum()
        _ny = state.loc["NY", f"change_{_p}"]
        _lines.append(
            f"{_p}-year change: {_change:,.0f} people; New York {_ny:+,.0f} ({_ny / _change:.0%} of it); "
            f"all other states together {_change - _ny:+,.0f}"
        )
    _c = published[~published["few_substations"]].sort_values("change_100", key=np.abs, ascending=False)
    _lines.append(
        "Counties that move most (100-year, blanked counties left out): "
        + "; ".join(f"{r.county}, {r.state} {r.change_100:+,.0f}" for r in _c.head(6).itertuples())
    )
    _lines.append(
        f"Washington (100-year): {state.loc['WA', 'affected_100_before']:,.0f} -> "
        f"{state.loc['WA', 'affected_100_after']:,.0f} with {int(state.loc['WA', 'subs_after'])} substations"
    )
    _src = buses_a["sub"].map(dict(zip(ours["id"].astype(str), ours["source"], strict=True))).value_counts()
    _lines.append(
        "After-grid substations by source in our file: "
        + ", ".join(f"{k} {v:,}" for k, v in _src.items())
        + " (both = HIFLD-derived with OSM within 1 km; osm = OSM only; derived = HIFLD-derived only)"
    )
    _lines += [f"{k}: {v}" for k, v in field_checks.items()]
    _lines += [
        f"Monte Carlo draws per grid: {N_DRAWS}",
        f"Monte Carlo time: {model_seconds:.0f} s",
        f"Notebook run time: {time.perf_counter() - started:.0f} s",
    ]
    totals.round(4).to_csv(OUT / "national_totals.csv", index=False)
    (OUT / "headline.txt").write_text("\n".join(_lines) + "\n")
    print("\n".join(_lines))
    mo.md("\n".join(f"- {line}" for line in _lines))
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What this doesn't show, and what didn't work

    - **The paper's exact figures aren't in its data release.** C-SWIM's own Monte Carlo output in release v5
      gives more people affected than the AGU paper (row (a)); the paper's numbers come from a later run. We
      report the gap to both.
    - **Five magnetotelluric sites are missing** from the public bundle (KAN01 to KAN05), so our field step uses
      1,611 of 1,616 sites.
    - **People are allocated to the nearest substation by Census block group**, not by C-SWIM's land-cover
      weighted ZIP-code areal interpolation.
    - **Dollars are a fixed rate per affected person**, taken from the paper; they move exactly with people.
    - **Monte Carlo draws** are fewer than C-SWIM's 2,039 (see the totals table for the spread across draws).
    - **Most of the gain is current OpenStreetMap, not HIFLD.** Our file merges HIFLD-derived line ends with
      OpenStreetMap (via Overture, 2026). Only a few hundred after-grid substations are HIFLD-derived alone (see
      the source line above). C-SWIM's own code switched to current OpenStreetMap in August 2026, after the paper,
      so the authors' next run may close much of this gap themselves.
    - **Service areas are coarse.** A substation's people are everyone nearer to it than to any other 161 kV+
      substation. Where few such substations serve a dense place (Long Island, New York City), one substation can
      stand for a million people, so adding or removing a handful of substations moves the total a lot. That is a
      property of C-SWIM's method, and it is the main reason the totals move.
    - Like the paper, this counts transformer heating only, with random transformer types, earthing and ages; it
      says where the modelled risk moves, not which real substation would fail.
    """)
    return


if __name__ == "__main__":
    app.run()

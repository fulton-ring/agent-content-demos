import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    import time
    from collections.abc import Callable
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import geopandas as gpd
    import httpx
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import rasterio
    from rasterio.features import rasterize
    from rasterio.io import DatasetReader
    from rasterio.transform import Affine
    from rasterio.windows import Window
    from scipy.sparse import csr_matrix
    from scipy.spatial import KDTree
    from sklearn.ensemble import HistGradientBoostingRegressor
    from sklearn.metrics import r2_score, roc_auc_score
    from sklearn.model_selection import GroupKFold

    return (
        Affine,
        Callable,
        DatasetReader,
        GroupKFold,
        HistGradientBoostingRegressor,
        Path,
        ThreadPoolExecutor,
        Window,
        KDTree,
        csr_matrix,
        gpd,
        httpx,
        json,
        mo,
        np,
        os,
        pd,
        plt,
        r2_score,
        rasterio,
        rasterize,
        roc_auc_score,
        time,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Can satellite embeddings find high-burden communities the EJ indexes miss?

    A geoembedding is a vector a pretrained Earth-observation model gives each patch of
    ground, summarising what it looks like across a year of satellite images. Places that
    look alike get vectors that point the same way. Google DeepMind's
    [AlphaEarth Foundations](https://deepmind.google/discover/blog/alphaearth-foundations-helps-map-our-planet-in-unprecedented-detail/)
    model publishes one 64-number vector for every 10 m pixel on land, every year.

    The question is whether those vectors can stand in for, or add to, EPA's EJScreen
    block-group indicators in Louisiana and Texas. We expect them to predict the
    indicators that follow land use (traffic, nearness to industrial and hazardous-waste
    sites) well, and the modelled air quality and demographic ones poorly. This notebook
    tests that in three steps:

    1. **Prediction.** For each EJScreen indicator, how well do embeddings predict it in
       counties the model never saw, compared with plain NLCD land-cover shares?
    2. **Look-alikes.** Starting from four well-known fenceline communities, which block
       groups elsewhere look most like them, how many are already flagged by EJScreen or
       CEJST, and are the unflagged ones real?
    3. **Health.** Do embeddings add anything to the EJ indicators for CDC PLACES asthma
       estimates, or only restate them?
    """)
    return


@app.cell
def _(Path, os, time):
    t_start = time.perf_counter()
    HERE = Path(__file__).parent
    DATA_DIR = Path(os.environ.get("GEO_DATA_DIR", HERE / "data"))
    OUT_DIR = Path(os.environ.get("GEO_OUT_DIR", HERE / "outputs"))
    for _d in (DATA_DIR / "aef", DATA_DIR / "nlcd", DATA_DIR / "naip", OUT_DIR / "naip"):
        _d.mkdir(parents=True, exist_ok=True)

    STATES = {"22": "LA", "48": "TX"}
    # EJScreen 2024's environmental indicators mostly describe 2020-2022, so the embeddings
    # and land cover are from 2022 too.
    YEAR = 2022
    AEF_BASE = "https://data.source.coop/tge-labs/aef/v1/annual"
    NLCD_URL = (
        "https://data.source.coop/kylebarron/usgs-landcover/annual-nlcd/c1/v1/cu/mosaic/"
        f"Annual_NLCD_LndCov_{YEAR}_CU_C1V1.tif"
    )
    PLACES_URL = "https://data.cdc.gov/resource/yjkw-uj5s.csv"
    HIFLD = "https://storage.googleapis.com/hifld-next-datasets-prod/hifld"
    FACILITY_LAYERS = {
        "refinery": "petroleum-refineries/petroleum-refineries",
        "rmp": "epa-emergency-response-rmp-facilities/epa-emergency-response-rmp-facilities",
        "tri": "epa-frs-toxic-release-inventory/epa-frs-toxic-release-inventory",
        "tsdf": "epa-rcra-treatment-storage-and-disposal-facilities/"
        "epa-rcra-treatment-storage-and-disposal-facilities",
        "superfund": "epa-superfund-enterprise-management-system-sems-sites-1/"
        "epa-superfund-enterprise-management-system-sems-sites-1",
        "terminal": "petroleum-product-terminals/petroleum-product-terminals",
        "power_plant": "power-plants-1/power-plants-1",
    }
    # The EJ block-group files are built by the sibling project; run.sh builds them here.
    EJ_DIR = Path(os.environ.get("EJ_OUT_DIR", DATA_DIR / "ej" / "out"))
    ALBERS = "EPSG:5070"
    HAND_CHECK = HERE / "hand_check.csv"
    GDAL_ENV = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "GDAL_HTTP_MAX_RETRY": "5",
        "GDAL_HTTP_RETRY_DELAY": "2",
        "CPL_VSIL_CURL_CHUNK_SIZE": "1048576",
    }
    return (
        AEF_BASE,
        ALBERS,
        DATA_DIR,
        EJ_DIR,
        FACILITY_LAYERS,
        GDAL_ENV,
        HAND_CHECK,
        HIFLD,
        NLCD_URL,
        OUT_DIR,
        PLACES_URL,
        STATES,
        YEAR,
        t_start,
    )


@app.cell
def _(Callable, DATA_DIR, DatasetReader, GDAL_ENV, Path, httpx, rasterio, time):
    def read_remote[T](url: str, read: Callable[[DatasetReader], T], overview: int = -1) -> T:
        """Open a remote raster over HTTP range requests and return read(dataset).

        Source Cooperative now and then answers a range request with a bad body. GDAL caches
        what it got for that URL, so each retry adds a dummy query string to start afresh.
        """
        kwargs = {"overview_level": overview} if overview >= 0 else {}
        for attempt in range(4):
            href = url if attempt == 0 else f"{url}?retry={attempt}"
            try:
                with rasterio.Env(**GDAL_ENV), rasterio.open(f"/vsicurl/{href}", **kwargs) as src:
                    return read(src)
            except rasterio.errors.RasterioIOError:
                if attempt == 3:
                    raise
                time.sleep(5 * 2**attempt)
        raise AssertionError("unreachable")

    def fetch(url: str, name: str) -> Path:
        """Download a file once into data/ and return its path."""
        path = DATA_DIR / name
        if path.exists():
            return path
        tmp = path.with_suffix(path.suffix + ".part")
        with httpx.stream("GET", url, follow_redirects=True, timeout=300) as response:
            response.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in response.iter_bytes(1 << 20):
                    f.write(chunk)
        tmp.rename(path)
        return path

    def rx_bytes() -> int:
        """Bytes received from outside the machine, to measure what each step downloads.

        Loopback is left out: behind a local proxy every byte would otherwise count twice.
        """
        lines = Path("/proc/net/dev").read_text().splitlines()[2:]
        rows = [line.split(":") for line in lines]
        return sum(int(stats.split()[0]) for name, stats in rows if name.strip() != "lo")

    return fetch, read_remote, rx_bytes


@app.cell
def _(mo):
    mo.md(r"""
    ## The block groups and their EJScreen indicators

    The indicators come from EPA's last EJScreen release (2024, ACS 2018–2022), as rebuilt
    into GeoParquet by `ej-datasets-hifld-next/`. We predict each indicator's **national
    percentile** (EPA's `P_` columns, 0 to 100), so every indicator is on the same scale
    and skewed ones like proximity scores don't need transforming. A block group counts as
    **flagged** if EPA's own screening rule fires: at least one of its 13 EJ indexes at or
    above the 80th national percentile (`EXCEED_COUNT_80 > 0`). CEJST's v2.0
    "disadvantaged" tracts (2010 boundaries, joined by each block group's interior point)
    are the second index we check against.
    """)
    return


@app.cell
def _(ALBERS, EJ_DIR, STATES, gpd, pd):
    ENV = [
        "pm25",
        "ozone",
        "no2",
        "dslpm",
        "rsei_air",
        "ptraf",
        "ldpnt",
        "pnpl",
        "prmp",
        "ptsdf",
        "ust",
        "pwdis",
        "dwater",
    ]
    DEMOG = [
        "peopcolorpct",
        "lowincpct",
        "lingisopct",
        "lesshspct",
        "unemppct",
        "under5pct",
        "over64pct",
        "lifeexppct",
        "demogidx_2",
    ]
    _cols = ["geoid", "st_abbrev", "cnty_name", "acstotpop", "exceed_count_80", "geometry"]
    _cols += [f"p_{c}" for c in ENV + DEMOG]
    bg = gpd.read_parquet(EJ_DIR / "epa-ejscreen-2024-block-groups.parquet", columns=_cols)
    bg = bg[bg["geoid"].str[:2].isin(list(STATES)) & bg.geometry.notna()].to_crs(ALBERS)
    bg = bg.sort_values("geoid").reset_index(drop=True)
    bg["county"] = bg["geoid"].str[:5]
    bg["flag_ejscreen"] = bg["exceed_count_80"].fillna(0) > 0
    bg["point"] = bg.geometry.representative_point()
    # Each block group's embedding comes from the UTM zone of its interior point.
    bg["zone"] = ((bg["point"].to_crs("EPSG:4326").x + 180) // 6 + 1).astype(int).astype(str)
    bg["zone"] += "N"

    _cejst = gpd.read_parquet(
        EJ_DIR / "cejst-v2-census-tracts.parquet",
        columns=["geoid", "identified_as_disadvantaged", "geometry"],
    )
    _cejst = _cejst[_cejst["geoid"].str[:2].isin(list(STATES))].to_crs(ALBERS)
    _joined = gpd.sjoin(
        gpd.GeoDataFrame(geometry=bg["point"], crs=ALBERS), _cejst, how="left", predicate="within"
    )
    _joined = _joined[~_joined.index.duplicated()]
    bg["flag_cejst"] = _joined["identified_as_disadvantaged"].astype("boolean").fillna(False)
    bg["flag_any"] = bg["flag_ejscreen"] | bg["flag_cejst"]
    pd.DataFrame(
        {
            "block groups": bg.groupby("st_abbrev").size(),
            "flagged by EJScreen": bg.groupby("st_abbrev")["flag_ejscreen"].mean().round(3),
            "flagged by CEJST": bg.groupby("st_abbrev")["flag_cejst"].mean().round(3),
        }
    )
    return DEMOG, ENV, bg


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 1: embeddings for every block group

    The embeddings come from the
    [Source Cooperative copy](https://source.coop/tge-labs/aef) of AlphaEarth's annual
    Satellite Embedding dataset (CC-BY 4.0, no account needed; "The AlphaEarth Foundations
    Satellite Embedding dataset is produced by Google and Google DeepMind"). Each file is
    an 8192 × 8192 tile of 10 m pixels, 3.2 GB at full resolution. Pulling Louisiana and
    Texas at 10 m would be hundreds of gigabytes, but every file carries overviews whose
    pixels are the **normalised mean of the 10 m embeddings beneath them**, which is exactly
    the averaging we want. We read the 512 × 512 overview (160 m pixels) of each tile over
    the two states, with HTTP range requests.

    For each tile we burn block-group ids onto its 160 m grid and sum the embedding of
    every pixel inside each block group. Each block group is counted in one UTM zone only
    (the zone of its interior point), so the overlap between zones isn't counted twice.
    Block groups smaller than a pixel get the pixel under their interior point. Two
    quirks of these files: they are stored bottom-up, so rows are flipped, and values are
    int8 that are dequantised as `(v / 127.5)² · sign(v)` with -128 as no-data.
    """)
    return


@app.cell
def _(
    AEF_BASE,
    ALBERS,
    Affine,
    DATA_DIR,
    ThreadPoolExecutor,
    YEAR,
    bg,
    fetch,
    gpd,
    np,
    pd,
    rasterize,
    read_remote,
    rx_bytes,
    time,
):
    _t, _rx = time.perf_counter(), rx_bytes()
    _index = gpd.read_parquet(fetch(f"{AEF_BASE}/aef_index.parquet", "aef_index.parquet"))
    _states = gpd.GeoDataFrame(geometry=[bg.union_all().buffer(2000)], crs=ALBERS)
    _index = _index[_index["year"] == YEAR].set_geometry("geom").to_crs(ALBERS)
    tiles = _index[_index.intersects(_states.geometry.iloc[0])].reset_index(drop=True)

    def tile_sums(tile: dict) -> dict:
        """Sum the 160 m embedding pixels inside each block group of one tile."""
        name = tile["path"].rsplit("/", 1)[1].removesuffix(".tiff")
        cache = DATA_DIR / "aef" / f"{YEAR}-{tile['utm_zone']}-{name}.npz"
        if cache.exists():
            return dict(np.load(cache))
        url = AEF_BASE + tile["path"].split("/v1/annual", 1)[1]
        raw, transform = read_remote(url, lambda r: (r.read(), r.transform), overview=3)
        res, west, south = transform.a, transform.c, transform.f
        assert transform.e > 0, "expected a bottom-up file"
        raw = raw[:, ::-1, :]
        n_rows, n_cols = raw.shape[1:]
        top_down = Affine(res, 0, west, 0, -res, south + res * n_rows)
        zone_bgs = bg[bg["zone"] == tile["utm_zone"]].to_crs(tile["crs"])
        ids = rasterize(
            ((geom, i + 1) for i, geom in zip(zone_bgs.index, zone_bgs.geometry, strict=True)),
            out_shape=(n_rows, n_cols),
            transform=top_down,
            fill=0,
            dtype="int32",
        )
        valid = (raw[0] != -128) & (ids > 0)
        values = raw[:, valid].astype(np.float32)
        values = (values / 127.5) ** 2 * np.sign(values)
        which = ids[valid] - 1
        uniq, inverse = np.unique(which, return_inverse=True)
        sums = np.zeros((len(uniq), 64), np.float32)
        np.add.at(sums, inverse, values.T)
        counts = np.bincount(inverse, minlength=len(uniq))
        # Interior-point pixel for block groups too small to cover a pixel centre.
        pts = zone_bgs["point"].to_crs(tile["crs"])
        cols = np.floor((pts.x - west) / res).astype(int)
        rows = np.floor((top_down.f - pts.y) / res).astype(int)
        inside = (cols >= 0) & (cols < n_cols) & (rows >= 0) & (rows < n_rows)
        pv = raw[:, rows[inside], cols[inside]].astype(np.float32)
        ok = pv[0] != -128
        pv = (pv / 127.5) ** 2 * np.sign(pv)
        # Keyed by GEOID, so the cache stays valid if the block-group table changes.
        geoids = bg["geoid"].to_numpy().astype("U12")
        out = {
            "geoids": geoids[uniq],
            "sums": sums,
            "counts": counts,
            "pt_geoids": geoids[zone_bgs.index[inside][ok]],
            "pt_values": pv[:, ok].T,
        }
        np.savez(cache, **out)
        return out

    with ThreadPoolExecutor(8) as _pool:
        _parts = list(_pool.map(tile_sums, tiles.to_dict("records")))

    aef_sum = np.zeros((len(bg), 64), np.float64)
    aef_count = np.zeros(len(bg), np.int64)
    _point = np.full((len(bg), 64), np.nan)
    _rows = pd.Index(bg["geoid"])
    for _p in _parts:
        _r = _rows.get_indexer(_p["geoids"])
        np.add.at(aef_sum, _r, _p["sums"])
        np.add.at(aef_count, _r, _p["counts"])
        _point[_rows.get_indexer(_p["pt_geoids"])] = _p["pt_values"]
    _small = aef_count == 0
    aef_sum[_small] = np.nan_to_num(_point[_small])
    aef_count[_small] = (~np.isnan(_point[_small, 0])).astype(int)
    aef_stats = {
        "tiles": len(tiles),
        "seconds": round(time.perf_counter() - _t),
        "downloaded_mb": round((rx_bytes() - _rx) / 1e6),
        "block_groups_with_pixels": int((~_small).sum()),
        "block_groups_point_only": int((_small & (aef_count > 0)).sum()),
        "block_groups_missing": int((aef_count == 0).sum()),
        "median_pixels_per_block_group": int(np.median(aef_count[aef_count > 0])),
    }
    aef_stats
    return aef_count, aef_stats, aef_sum


@app.cell
def _(mo):
    mo.md(r"""
    ## The baseline: NLCD land-cover shares

    The baseline is the cheapest thing a GIS analyst would try first: the share of each
    block group in each of NLCD's 16 land-cover classes (2022, 30 m), read from the
    [Source Cooperative mirror](https://source.coop/kylebarron/usgs-landcover) of USGS's
    Annual NLCD Collection 1 COG with range requests over the two states only. Here
    every 30 m pixel is counted, so the shares are exact.
    """)
    return


@app.cell
def _(
    DATA_DIR,
    NLCD_URL,
    ThreadPoolExecutor,
    Window,
    bg,
    np,
    pd,
    rasterio,
    rasterize,
    read_remote,
    rx_bytes,
    time,
):
    NLCD_CLASSES = [11, 12, 21, 22, 23, 24, 31, 41, 42, 43, 52, 71, 81, 82, 90, 95]
    _lookup = np.full(256, len(NLCD_CLASSES), np.int64)
    _lookup[NLCD_CLASSES] = np.arange(len(NLCD_CLASSES))
    _cache = DATA_DIR / "nlcd" / f"{NLCD_URL.rsplit('/', 1)[1]}.counts.npy"
    _t, _rx = time.perf_counter(), rx_bytes()
    if _cache.exists():
        nlcd_counts = np.load(_cache)
    else:
        _crs, _src_transform = read_remote(NLCD_URL, lambda r: (r.crs, r.transform))
        _bg = bg.to_crs(_crs)
        _full = rasterio.windows.from_bounds(*_bg.total_bounds, transform=_src_transform)
        _full = _full.round_offsets().round_lengths()
        _step = 4096
        _windows = [
            Window(
                c,
                r,
                min(_step, _full.col_off + _full.width - c),
                min(_step, _full.row_off + _full.height - r),
            )
            for r in range(_full.row_off, _full.row_off + _full.height, _step)
            for c in range(_full.col_off, _full.col_off + _full.width, _step)
        ]

        def window_counts(window: Window) -> np.ndarray:
            """Count NLCD pixels per (block group, class) in one window."""
            transform = rasterio.windows.transform(window, _src_transform)
            minx, maxy = transform * (0, 0)
            maxx, miny = transform * (window.width, window.height)
            near = _bg.cx[minx:maxx, miny:maxy]
            k = len(NLCD_CLASSES) + 1
            if near.empty:
                return np.zeros((len(bg), k), np.int64)
            ids = rasterize(
                ((g, i + 1) for i, g in zip(near.index, near.geometry, strict=True)),
                out_shape=(window.height, window.width),
                transform=transform,
                fill=0,
                dtype="int32",
            )
            if not ids.any():
                return np.zeros((len(bg), k), np.int64)
            classes = _lookup[read_remote(NLCD_URL, lambda r: r.read(1, window=window))]
            inside = ids > 0
            flat = (ids[inside].astype(np.int64) - 1) * k + classes[inside]
            return np.bincount(flat, minlength=len(bg) * k).reshape(len(bg), k)

        nlcd_counts = np.zeros((len(bg), len(NLCD_CLASSES) + 1), np.int64)
        with ThreadPoolExecutor(6) as _pool:
            for _c in _pool.map(window_counts, _windows):
                nlcd_counts += _c
        np.save(_cache, nlcd_counts)
    nlcd_stats = {
        "seconds": round(time.perf_counter() - _t),
        "downloaded_mb": round((rx_bytes() - _rx) / 1e6),
        "block_groups_without_pixels": int((nlcd_counts.sum(1) == 0).sum()),
    }
    _shares = nlcd_counts[:, :-1] / np.maximum(nlcd_counts[:, :-1].sum(1, keepdims=True), 1)
    nlcd_share = pd.DataFrame(_shares, columns=[f"nlcd_{c}" for c in NLCD_CLASSES])
    nlcd_stats
    return nlcd_counts, nlcd_share, nlcd_stats


@app.cell
def _(mo):
    mo.md(r"""
    ## Neighbourhood context

    EJScreen's proximity indicators count facilities and traffic within a few kilometres,
    not just inside the block group, so both feature sets get a second half: the same
    average taken over every block group whose interior point is within 5 km. For
    embeddings that is the mean of all their pixels, renormalised; for NLCD, the pooled
    class shares. Embedding vectors are normalised to unit length, as AlphaEarth's own
    overviews are.
    """)
    return


@app.cell
def _(aef_count, aef_sum, bg, KDTree, csr_matrix, nlcd_counts, np, pd):
    _xy = np.c_[bg["point"].x, bg["point"].y]
    _pairs = KDTree(_xy).query_pairs(5000, output_type="ndarray")
    _n = len(bg)
    _r = np.r_[_pairs[:, 0], _pairs[:, 1], np.arange(_n)]
    _c = np.r_[_pairs[:, 1], _pairs[:, 0], np.arange(_n)]
    neighbours = csr_matrix((np.ones(len(_r)), (_r, _c)), shape=(_n, _n))

    def unit(m: np.ndarray) -> np.ndarray:
        """Normalise rows to unit length, leaving all-zero rows at zero."""
        norm = np.linalg.norm(m, axis=1, keepdims=True)
        return np.divide(m, norm, out=np.zeros_like(m), where=norm > 0)

    _own = unit(aef_sum)
    _ctx = unit(neighbours @ aef_sum)
    aef = pd.DataFrame(
        np.c_[_own, _ctx],
        columns=[f"aef_{i:02d}" for i in range(64)] + [f"aef5k_{i:02d}" for i in range(64)],
    )
    aef[aef_count == 0] = np.nan
    _ctx_counts = neighbours @ nlcd_counts[:, :-1]
    nlcd_ctx = pd.DataFrame(
        _ctx_counts / np.maximum(_ctx_counts.sum(1, keepdims=True), 1),
        columns=[f"nlcd5k_{i:02d}" for i in range(_ctx_counts.shape[1])],
    )
    {"median_neighbours_within_5km": int(np.median(np.diff(neighbours.indptr)))}
    return aef, nlcd_ctx, unit


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 2: how well each feature set predicts each indicator

    The same model (scikit-learn's histogram gradient boosting, default settings) is fitted
    on four feature sets: NLCD shares, embeddings, both, and, as a check on what the
    embeddings are really carrying, nothing but the block group's coordinates. Scores are
    on held-out **counties**: five folds of whole counties, so a model never sees the
    block groups around the one it is scoring. A second, harder test trains on Texas only
    and scores Louisiana. We report R² of the predicted national percentile, and the AUC
    for picking out the top decile of block groups in the two states.
    """)
    return


@app.cell
def _(
    DEMOG,
    ENV,
    GroupKFold,
    HistGradientBoostingRegressor,
    aef,
    bg,
    nlcd_ctx,
    nlcd_share,
    np,
    pd,
    r2_score,
    roc_auc_score,
    time,
):
    _t = time.perf_counter()
    feature_sets = {
        "nlcd": pd.concat([nlcd_share, nlcd_ctx], axis=1),
        "embeddings": aef,
        "both": pd.concat([nlcd_share, nlcd_ctx, aef], axis=1),
        "location": pd.DataFrame({"x": bg["point"].x, "y": bg["point"].y}),
    }
    _folds = list(GroupKFold(n_splits=5).split(bg, groups=bg["county"]))
    _tx, _la = (bg["st_abbrev"] == "TX").to_numpy(), (bg["st_abbrev"] == "LA").to_numpy()

    def model() -> HistGradientBoostingRegressor:
        return HistGradientBoostingRegressor(random_state=0)

    _rows = []
    for _target in ENV + DEMOG:
        _y = bg[f"p_{_target}"].to_numpy(float)
        _has = ~np.isnan(_y)
        for _name, _X in feature_sets.items():
            _X = _X.to_numpy()
            _pred = np.full(len(bg), np.nan)
            for _train, _test in _folds:
                _train, _test = _train[_has[_train]], _test[_has[_test]]
                _pred[_test] = model().fit(_X[_train], _y[_train]).predict(_X[_test])
            _top = _y[_has] >= np.nanpercentile(_y, 90)
            _fit = model().fit(_X[_tx & _has], _y[_tx & _has])
            _rows.append(
                {
                    "indicator": _target,
                    "kind": "environment" if _target in ENV else "demographic",
                    "features": _name,
                    "r2_county_cv": r2_score(_y[_has], _pred[_has]),
                    "auc_top10_county_cv": roc_auc_score(_top, _pred[_has])
                    if 0 < _top.mean() < 1
                    else np.nan,
                    "share_top10": _top.mean(),
                    "r2_train_tx_test_la": r2_score(_y[_la & _has], _fit.predict(_X[_la & _has])),
                }
            )
    scores = pd.DataFrame(_rows)
    fit_seconds = round(time.perf_counter() - _t)
    return feature_sets, fit_seconds, scores


@app.cell
def _(OUT_DIR, scores):
    scores.round(3).to_csv(OUT_DIR / "prediction_scores.csv", index=False)
    score_table = scores.pivot(
        index=["kind", "indicator"], columns="features", values="r2_county_cv"
    )[["location", "nlcd", "embeddings", "both"]]
    score_table["gain"] = score_table["embeddings"] - score_table["nlcd"]
    score_table.sort_values(["kind", "embeddings"], ascending=[False, False]).round(2)
    return (score_table,)


@app.cell
def _(OUT_DIR, plt, score_table):
    _t = score_table.sort_values("embeddings")
    _fig, _ax = plt.subplots(figsize=(7, 6.5))
    _y = range(len(_t))
    _ax.hlines(_y, _t["nlcd"], _t["embeddings"], color="#bbb", lw=2)
    _ax.scatter(_t["nlcd"], _y, color="#8a8a8a", label="NLCD land-cover shares", zorder=3)
    _ax.scatter(_t["embeddings"], _y, color="#2b6cb0", label="AlphaEarth embeddings", zorder=3)
    _ax.scatter(
        _t["location"], _y, color="#d69e2e", marker="|", s=120, label="coordinates only", zorder=2
    )
    _ax.set_yticks(list(_y), [f"{i} ({k[:4]}.)" for k, i in _t.index])
    _ax.set_xlabel("R² of national percentile, held-out counties (LA + TX)")
    _ax.axvline(0, color="#ddd", lw=1)
    _ax.set_xlim(-0.3, 1)
    _ax.legend(loc="lower right", frameon=False)
    _ax.set_title("How well each feature set predicts EJScreen 2024 indicators")
    _fig.tight_layout()
    _fig.savefig(OUT_DIR / "prediction_r2.png", dpi=150)
    _fig
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 3: find places like these

    Four seed block groups, each the one containing a well-known spot on the fenceline:
    Reserve in St. John the Baptist Parish (next to the Denka neoprene plant), Convent in
    St. James Parish, and Manchester and Galena Park on the Houston Ship Channel. Every
    other block group gets a similarity score: the highest cosine similarity between its
    embedding (own and 5 km context) and any seed's. The top 250 are the look-alikes.
    Look-alikes within 10 km of a seed are the seed's own neighbourhood, so we count them
    apart.

    As a check that the search finds what it should, we also look up where five other
    known fenceline places rank, none of them used as seeds: north Baton Rouge by the
    ExxonMobil refinery, Mossville/Westlake by Lake Charles, Port Arthur's west side,
    Hillcrest in Corpus Christi and Texas City.
    """)
    return


@app.cell
def _(ALBERS, aef, bg, gpd, np, pd, unit):
    _places = pd.DataFrame(
        [
            ("Reserve, LA (Denka)", "seed", -90.5525, 30.0590),
            ("Convent, LA", "seed", -90.8290, 30.0210),
            ("Manchester, Houston", "seed", -95.2620, 29.7240),
            ("Galena Park, TX", "seed", -95.2310, 29.7370),
            ("North Baton Rouge, LA", "check", -91.1700, 30.4930),
            ("Mossville/Westlake, LA", "check", -93.2700, 30.2490),
            ("West Port Arthur, TX", "check", -93.9500, 29.8840),
            ("Hillcrest, Corpus Christi", "check", -97.4180, 27.8070),
            ("Texas City, TX", "check", -94.9100, 29.3940),
        ],
        columns=["place", "role", "lon", "lat"],
    )
    _pts = gpd.GeoDataFrame(
        _places, geometry=gpd.points_from_xy(_places.lon, _places.lat), crs="EPSG:4326"
    ).to_crs(ALBERS)
    _hit = gpd.sjoin(_pts, bg[["geoid", "geometry"]], predicate="within")
    places = _places.assign(geoid=_hit["geoid"], row=_hit["index_right"])
    assert places["row"].notna().all(), "a seed point fell outside every block group"

    _seeds = places[places["role"] == "seed"]["row"].astype(int).to_numpy()
    _vectors = np.nan_to_num(aef.to_numpy())

    def seed_similarity(columns: slice) -> np.ndarray:
        """Cosine similarity of every block group to each seed, on some of the columns."""
        emb = unit(_vectors[:, columns])
        return emb @ emb[_seeds].T

    _sim = seed_similarity(slice(0, 128))
    sim = bg[
        ["geoid", "st_abbrev", "cnty_name", "acstotpop", "flag_ejscreen", "flag_cejst", "flag_any"]
    ].copy()
    sim["similarity"] = _sim.max(1)
    sim["nearest_seed"] = places[places["role"] == "seed"]["place"].to_numpy()[_sim.argmax(1)]
    _seed_xy = np.c_[bg["point"].x, bg["point"].y][_seeds]
    _d = np.hypot(
        bg["point"].x.to_numpy()[:, None] - _seed_xy[:, 0],
        bg["point"].y.to_numpy()[:, None] - _seed_xy[:, 1],
    ).min(1)
    sim["km_to_seed"] = _d / 1000
    sim.loc[_seeds, "similarity"] = np.nan
    sim["rank"] = sim["similarity"].rank(ascending=False, method="first")
    places["rank"] = sim["rank"].to_numpy()[places["row"].astype(int)]

    # Which part of the vector does the work: the block group's own pixels, its 5 km
    # surroundings, or both (the version used above)?
    _rows = {}
    for _label, _cols in [
        ("own block group", slice(0, 64)),
        ("5 km context", slice(64, 128)),
        ("both", slice(0, 128)),
    ]:
        _s = seed_similarity(_cols).max(1)
        _s[_seeds] = np.nan
        _rank = pd.Series(_s).rank(ascending=False, method="first")
        _top = _rank <= 250
        _rows[_label] = {
            "top 250 flagged by either": round(sim["flag_any"][_top].mean(), 3),
            "top 250 within 10 km of a seed": int((sim["km_to_seed"][_top] <= 10).sum()),
            **{
                p: int(_rank.iloc[int(r)])
                for p, r in places[places.role == "check"][["place", "row"]].itertuples(index=False)
            },
        }
    variants = pd.DataFrame(_rows)
    variants
    return places, sim, variants


@app.cell
def _(pd, sim):
    TOP_N = 250
    lookalikes = sim[sim["rank"] <= TOP_N].copy()
    lookalikes["near_seed"] = lookalikes["km_to_seed"] <= 10

    def flag_rates(frame: pd.DataFrame) -> dict:
        return {
            "block groups": len(frame),
            "flagged by EJScreen": round(frame["flag_ejscreen"].mean(), 3),
            "flagged by CEJST": round(frame["flag_cejst"].mean(), 3),
            "flagged by either": round(frame["flag_any"].mean(), 3),
        }

    flag_summary = pd.DataFrame(
        {
            "all block groups, LA + TX": flag_rates(sim),
            "look-alikes": flag_rates(lookalikes),
            "look-alikes within 10 km of a seed": flag_rates(lookalikes[lookalikes.near_seed]),
            "look-alikes farther away": flag_rates(lookalikes[~lookalikes.near_seed]),
            "random 250, same states": flag_rates(sim.sample(TOP_N, random_state=0)),
        }
    ).T
    flag_summary
    return TOP_N, flag_summary, lookalikes


@app.cell
def _(mo):
    mo.md(r"""
    ### Are the look-alikes real?

    First, an automatic check with HIFLD Next's facility layers: what share of block
    groups have a refinery, RMP chemical facility, TRI reporter, hazardous-waste TSDF,
    Superfund site, petroleum terminal or power plant within 3 km of their interior point,
    for look-alikes against all block groups.
    """)
    return


@app.cell
def _(ALBERS, FACILITY_LAYERS, HIFLD, bg, KDTree, fetch, gpd, lookalikes, np, pd, sim):
    _frames = []
    for _kind, _path in FACILITY_LAYERS.items():
        _f = gpd.read_parquet(
            fetch(
                f"{HIFLD}/{_path}/v1.0.0/geoparquet/{_path.rsplit('/', 1)[1]}.parquet",
                f"{_kind}.parquet",
            )
        )
        _f = _f.to_crs(ALBERS)
        _f = _f[_f.geometry.notna() & ~_f.geometry.is_empty]
        _f = gpd.GeoDataFrame(
            {"kind": [_kind] * len(_f)}, geometry=_f.geometry.centroid.values, crs=ALBERS
        )
        _frames.append(_f)
    facilities = pd.concat(_frames, ignore_index=True)
    _area = bg.union_all().buffer(5000)
    facilities = facilities[facilities.within(_area)].reset_index(drop=True)

    _pts = np.c_[bg["point"].x, bg["point"].y]
    for _kind in FACILITY_LAYERS:
        _sub = facilities[facilities["kind"] == _kind]
        _tree = KDTree(np.c_[_sub.geometry.x, _sub.geometry.y])
        sim[f"n_{_kind}_3km"] = [len(i) for i in _tree.query_ball_point(_pts, 3000)]
    _heavy = ["refinery", "rmp", "tsdf", "terminal"]
    sim["heavy_industry_3km"] = sim[[f"n_{k}_3km" for k in _heavy]].sum(axis=1) > 0
    _look = sim.loc[lookalikes.index]
    _cols = [f"n_{k}_3km" for k in FACILITY_LAYERS]
    facility_summary = pd.DataFrame(
        {
            "all block groups": (sim[_cols] > 0).mean(),
            "look-alikes": (_look[_cols] > 0).mean(),
            "unflagged look-alikes": (_look[~_look["flag_any"]][_cols] > 0).mean(),
        }
    ).round(3)
    facility_summary.loc["refinery, RMP, TSDF or terminal"] = [
        sim["heavy_industry_3km"].mean(),
        _look["heavy_industry_3km"].mean(),
        _look[~_look["flag_any"]]["heavy_industry_3km"].mean(),
    ]
    facility_summary.round(3)
    return facilities, facility_summary


@app.cell
def _(mo):
    mo.md(r"""
    Then a hand check. Up to 20 unflagged look-alikes, drawn at random with a fixed seed
    (with fewer than 20, all of them), each get a chip of the newest NAIP aerial photos
    (USDA, public domain, mosaicked from Microsoft's Planetary Computer, which needs no
    account) covering the whole block group plus 1 km, with the block group outlined and
    HIFLD facilities marked. Each chip was looked at and labelled by hand in
    `hand_check.csv`: **yes** if there is heavy industry (a refinery, chemical plant, tank
    farm, port terminal or similar) next to the block group's homes, **partly** for
    lighter industry next to homes, **no** if nothing like that is there. The labels are
    the one part of this notebook that is human judgment (here, the worker agent's); the
    chips are in `outputs/naip/` so anyone can check them.
    """)
    return


@app.cell
def _(ALBERS, GDAL_ENV, OUT_DIR, bg, facilities, gpd, httpx, lookalikes, np, plt, rasterio):
    from rasterio.merge import merge
    from rasterio.vrt import WarpedVRT

    hand_sample = lookalikes[~lookalikes["flag_any"]].sample(
        min(20, int((~lookalikes["flag_any"]).sum())), random_state=0
    )
    _pc = "https://planetarycomputer.microsoft.com/api"
    _token = httpx.get(f"{_pc}/sas/v1/token/naip", timeout=60).raise_for_status().json()["token"]
    _colors = {
        "refinery": "red",
        "rmp": "orange",
        "tri": "yellow",
        "tsdf": "magenta",
        "superfund": "cyan",
        "terminal": "white",
        "power_plant": "lime",
    }
    naip_dates = {}
    for _i, _row in hand_sample.iterrows():
        _png = OUT_DIR / "naip" / f"{_row['geoid']}.png"
        # The chip covers the whole block group plus 1 km, and at least 3 km across.
        _shape = bg.loc[[_i]]
        _x0, _y0, _x1, _y1 = _shape.total_bounds
        _half = max(_x1 - _x0, _y1 - _y0, 1000) / 2 + 1000
        _cx, _cy = (_x0 + _x1) / 2, (_y0 + _y1) / 2
        _ext = (_cx - _half, _cy - _half, _cx + _half, _cy + _half)
        _box = gpd.GeoSeries.from_xy([_ext[0], _ext[2]], [_ext[1], _ext[3]], crs=ALBERS)
        _box = _box.to_crs("EPSG:4326")
        _items = (
            httpx.post(
                f"{_pc}/stac/v1/search",
                json={
                    "collections": ["naip"],
                    "limit": 100,
                    "bbox": [_box.x.min(), _box.y.min(), _box.x.max(), _box.y.max()],
                },
                timeout=60,
            )
            .raise_for_status()
            .json()["features"]
        )
        assert _items, f"no NAIP image for {_row['geoid']}"
        _year = max(f["properties"]["naip:year"] for f in _items)
        _items = [f for f in _items if f["properties"]["naip:year"] == _year]
        _dates = sorted(f["properties"]["datetime"][:10] for f in _items)
        naip_dates[_row["geoid"]] = f"{_dates[0]} to {_dates[-1]}"
        if _png.exists():
            continue
        with rasterio.Env(**GDAL_ENV):
            _srcs = [
                rasterio.open(f"/vsicurl/{f['assets']['image']['href']}?{_token}") for f in _items
            ]
            _vrts = [WarpedVRT(s, crs=ALBERS) for s in _srcs]
            _img, _ = merge(_vrts, bounds=_ext, res=2 * _half / 900, indexes=[1, 2, 3])
            for _d in _vrts + _srcs:
                _d.close()
        _fig, _ax = plt.subplots(figsize=(6, 6))
        _ax.imshow(np.moveaxis(_img, 0, -1), extent=(_ext[0], _ext[2], _ext[1], _ext[3]))
        _shape.boundary.plot(ax=_ax, color="cyan", lw=1.5)
        _f = facilities.cx[_ext[0] : _ext[2], _ext[1] : _ext[3]]
        for _k, _g in _f.groupby("kind"):
            _ax.scatter(_g.geometry.x, _g.geometry.y, s=30, c=_colors[_k], edgecolor="k", label=_k)
        _ax.set_xlim(_ext[0], _ext[2])
        _ax.set_ylim(_ext[1], _ext[3])
        _ax.set_axis_off()
        if len(_f):
            _ax.legend(loc="lower left", fontsize=7)
        _ax.set_title(
            f"{_row['geoid']} {_row['cnty_name']}, {_row['st_abbrev']}, "
            f"{2 * _half / 1000:.0f} km across, NAIP {naip_dates[_row['geoid']]}",
            fontsize=8,
        )
        _fig.tight_layout()
        _fig.savefig(_png, dpi=110)
        plt.close(_fig)
    hand_sample[["geoid", "cnty_name", "st_abbrev", "similarity", "nearest_seed"]].assign(
        naip=[naip_dates[g] for g in hand_sample["geoid"]]
    )
    return hand_sample, naip_dates


@app.cell
def _(HAND_CHECK, hand_sample, pd):
    hand_labels = (
        pd.read_csv(HAND_CHECK, dtype={"geoid": str})
        if HAND_CHECK.exists()
        else (pd.DataFrame(columns=["geoid", "real", "note"]))
    )
    _labelled = hand_labels[hand_labels["geoid"].isin(hand_sample["geoid"])]
    hand_result = {
        "sampled": len(hand_sample),
        "labelled": len(_labelled),
        "real": int(_labelled["real"].eq("yes").sum()),
        "partly": int(_labelled["real"].eq("partly").sum()),
        "unlabelled": sorted(set(hand_sample["geoid"]) - set(_labelled["geoid"])),
    }
    hand_result
    return (hand_result,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 4: do embeddings add anything for asthma?

    CDC PLACES (2025 release) estimates the share of adults with current asthma for every
    census tract. We aggregate block groups to tracts (population-weighted EJScreen
    percentiles; pooled embeddings and land cover) and predict asthma prevalence with
    county-held-out folds from the EJ indicators alone, embeddings alone, and both. If
    embeddings only restate land use, "both" will score no better than EJ indicators
    alone. PLACES is itself a model built partly from ACS demographics, so the
    demographic indicators have a head start here.
    """)
    return


@app.cell
def _(
    DEMOG,
    ENV,
    GroupKFold,
    HistGradientBoostingRegressor,
    PLACES_URL,
    STATES,
    aef_count,
    aef_sum,
    bg,
    fetch,
    nlcd_counts,
    np,
    pd,
    r2_score,
    unit,
):
    _states = ",".join(f"'{s}'" for s in STATES.values())
    _places_csv = fetch(
        f"{PLACES_URL}?$select=tractfips,totalpopulation,casthma_crudeprev"
        f"&$where=stateabbr in({_states})&$limit=50000",
        "places_2025_tracts.csv",
    )
    places_asthma = pd.read_csv(_places_csv, dtype={"tractfips": str})
    places_asthma["tractfips"] = places_asthma["tractfips"].str.zfill(11)

    _tract = bg["geoid"].str[:11]
    _w = bg["acstotpop"].fillna(0).to_numpy()
    _ej_cols = [f"p_{c}" for c in ENV + DEMOG]
    _ej = bg[_ej_cols].multiply(_w, axis=0)
    _ej["w"] = _w
    _ej = _ej.groupby(_tract).sum()
    _ej = _ej[_ej_cols].div(_ej["w"].replace(0, np.nan), axis=0)
    _emb = pd.DataFrame(aef_sum).groupby(_tract.to_numpy()).sum()
    _emb = pd.DataFrame(unit(_emb.to_numpy()), index=_emb.index).add_prefix("aef_")
    _lc = pd.DataFrame(nlcd_counts[:, :-1]).groupby(_tract.to_numpy()).sum()
    _lc = _lc.div(_lc.sum(axis=1).replace(0, np.nan), axis=0).add_prefix("nlcd_")
    _xy = pd.DataFrame({"x": bg["point"].x, "y": bg["point"].y}).groupby(_tract).mean()
    _ok = pd.Series(aef_count).groupby(_tract.to_numpy()).sum() > 0
    tracts = places_asthma.set_index("tractfips").join([_ej, _emb, _lc, _xy], how="inner")[
        lambda d: _ok.reindex(d.index).fillna(False)
    ]
    tracts = tracts.dropna(subset=["casthma_crudeprev"])
    _y = tracts["casthma_crudeprev"].to_numpy(float)
    _groups = tracts.index.str[:5]
    _sets = {
        "EJ indicators": _ej_cols,
        "EJ environmental only": [f"p_{c}" for c in ENV],
        "NLCD": list(_lc.columns),
        "embeddings": list(_emb.columns),
        "EJ indicators + embeddings": _ej_cols + list(_emb.columns),
        "EJ environmental + embeddings": [f"p_{c}" for c in ENV] + list(_emb.columns),
        "EJ indicators + coordinates": _ej_cols + ["x", "y"],
    }
    _rows = []
    for _name, _cols in _sets.items():
        _X = tracts[_cols].to_numpy(float)
        _pred = np.zeros(len(_y))
        for _train, _test in GroupKFold(n_splits=5).split(_X, groups=_groups):
            _m = HistGradientBoostingRegressor(random_state=0).fit(_X[_train], _y[_train])
            _pred[_test] = _m.predict(_X[_test])
        _rows.append({"features": _name, "r2_county_cv": round(r2_score(_y, _pred), 3)})
    asthma_scores = pd.DataFrame(_rows)
    asthma_scores.assign(tracts=len(tracts))
    return asthma_scores, tracts


@app.cell
def _(mo):
    mo.md(r"""
    ## The outputs

    `outputs/similarity_block_groups.csv` has every block group in the two states with
    its similarity score, rank, nearest seed, distance to the nearest seed, EJScreen and
    CEJST flags, and facility counts within 3 km. It joins on `geoid` to the block-group
    GeoParquet files from `ej-datasets-hifld-next/`. The map shows the scores.
    """)
    return


@app.cell
def _(OUT_DIR, TOP_N, bg, facility_summary, places, plt, sim):
    # facility_summary added the facility counts to sim, so this cell runs after it.
    assert len(facility_summary)
    sim.round(4).to_csv(OUT_DIR / "similarity_block_groups.csv", index=False)
    _fig, _axes = plt.subplots(1, 3, figsize=(16, 6), gridspec_kw={"width_ratios": [1.4, 1, 1]})
    _g = bg[["geometry"]].assign(
        similarity=sim["similarity"], rank=sim["rank"], flag=sim["flag_any"]
    )
    _seeds = bg.loc[places[places.role == "seed"]["row"].astype(int), "point"]
    _checks = bg.loc[places[places.role == "check"]["row"].astype(int), "point"]

    def around(x: float, y: float, km: float) -> tuple[float, float, float, float]:
        return (x - km * 1000, x + km * 1000, y - km * 1000, y + km * 1000)

    for _ax, _bounds, _title in (
        (_axes[0], None, "Louisiana and Texas"),
        (_axes[1], around(_seeds.iloc[2].x, _seeds.iloc[2].y, 45), "Houston"),
        (_axes[2], around(_seeds.iloc[0].x, _seeds.iloc[0].y, 45), "Mississippi River parishes"),
    ):
        _g.plot(
            column="similarity",
            ax=_ax,
            cmap="viridis",
            vmin=0.6,
            vmax=1.0,
            linewidth=0,
            legend=_ax is _axes[0],
            legend_kwds={"label": "similarity to nearest seed", "shrink": 0.6},
            missing_kwds={"color": "#f6ad55"},
        )
        _top = _g[_g["rank"] <= TOP_N]
        _top[~_top["flag"]].boundary.plot(ax=_ax, color="red", lw=0.6)
        _top[_top["flag"]].boundary.plot(ax=_ax, color="white", lw=0.4)
        _ax.scatter(_seeds.x, _seeds.y, marker="*", s=120, c="orange", edgecolor="k", zorder=4)
        _ax.scatter(
            _checks.x,
            _checks.y,
            marker="o",
            s=40,
            facecolor="none",
            edgecolor="orange",
            lw=1.5,
            zorder=4,
        )
        if _bounds:
            _ax.set_xlim(_bounds[0], _bounds[1])
            _ax.set_ylim(_bounds[2], _bounds[3])
        _ax.set_axis_off()
        _ax.set_title(_title)
    _fig.suptitle(
        f"Similarity to four fenceline seeds (stars); circles are the five held-out places. "
        f"Top {TOP_N} outlined: white = already flagged by EJScreen or CEJST, red = not flagged"
    )
    _fig.tight_layout()
    _fig.savefig(OUT_DIR / "similarity_map.png", dpi=150)
    _fig
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What it shows, and what didn't work

    - **Prediction.** Embeddings predict the land-use indicators (traffic, NO2, diesel PM,
      hazardous-waste proximity) about as well as plain NLCD shares, not better. They beat
      NLCD on ozone, PM2.5 and toxic air releases, but the block group's coordinates alone
      do better still on those: the embeddings are telling the model *where* a block group
      is, and these indicators are smooth regional fields. Trained on Texas and scored on
      Louisiana, that advantage disappears. Demographics are predicted poorly by everything.
    - **Look-alikes.** The most similar block groups are overwhelmingly ones EJScreen or
      CEJST already flag, and half of them are the seeds' own neighbours. The unflagged
      ones mostly look like the seeds' surroundings (river-parish cane fields and swamp,
      Houston suburbs), not like their industry. The held-out fenceline places rank in the
      thousands. Mean-pooled embeddings describe what most of a block group looks like,
      and in a fenceline community most of it is houses.
    - **Asthma.** Embeddings add to the EJ indicators about what coordinates add, so we
      can't tell them apart from location.

    The numbers are written to `outputs/summary.json`.
    """)
    return


@app.cell
def _(
    OUT_DIR,
    aef_stats,
    asthma_scores,
    facility_summary,
    fit_seconds,
    flag_summary,
    hand_result,
    json,
    lookalikes,
    naip_dates,
    nlcd_stats,
    places,
    score_table,
    t_start,
    time,
    tracts,
    variants,
):
    summary = {
        "embeddings": aef_stats,
        "nlcd": nlcd_stats,
        "model_fit_seconds": fit_seconds,
        "r2_county_cv": score_table.round(3).reset_index().to_dict("records"),
        "lookalikes": {
            "n": len(lookalikes),
            "within_10km_of_seed": int(lookalikes["near_seed"].sum()),
            "flag_rates": flag_summary.to_dict("index"),
            "unflagged": int((~lookalikes["flag_any"]).sum()),
            "check_place_ranks": places[["place", "role", "rank"]].to_dict("records"),
            "variants": variants.to_dict(),
        },
        "facilities_within_3km": facility_summary.round(3).to_dict("index"),
        "hand_check": hand_result,
        "naip_dates": naip_dates,
        "asthma_r2_county_cv": asthma_scores.to_dict("records"),
        "asthma_tracts": len(tracts),
        "run_seconds": round(time.perf_counter() - t_start),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    summary
    return


if __name__ == "__main__":
    app.run()

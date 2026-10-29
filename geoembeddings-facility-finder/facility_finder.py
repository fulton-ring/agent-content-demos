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
    from scipy import ndimage
    from scipy.spatial import KDTree
    from shapely.geometry import box

    return (
        Affine,
        Callable,
        DatasetReader,
        KDTree,
        Path,
        ThreadPoolExecutor,
        Window,
        box,
        gpd,
        httpx,
        json,
        mo,
        ndimage,
        np,
        os,
        pd,
        plt,
        rasterio,
        rasterize,
        time,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Can satellite embeddings find industrial hazards the facility registries miss?

    A [previous spike](../geoembeddings-ej-screening/) averaged Google DeepMind's
    [AlphaEarth Foundations](https://deepmind.google/discover/blog/alphaearth-foundations-helps-map-our-planet-in-unprecedented-detail/)
    embeddings over census block groups. It found they describe a fenceline community's
    houses and fields, not the plant next door. This notebook aims at the plant instead.
    AlphaEarth gives every 10 m pixel a 64-number vector summarising a year of satellite
    images. If refineries, tank farms and chemical plants look distinctive from above,
    a classifier trained on the pixels of **known** facilities should find others, and
    the ones it finds away from any registered facility are either registry gaps or false
    alarms.

    The steps:

    1. Read the 10 m embeddings over the Gulf Coast industrial corridor.
    2. Train a classifier on pixels at registered refineries, RMP chemical facilities,
       petroleum terminals and hazardous-waste TSDFs, against pixels far from any facility.
    3. Scan counties the classifier never saw, group high-scoring pixels into sites, and
       score them against the registries: precision and recall by facility type.
    4. List the sites more than 1 km from any registered facility of those types, and
       hand-check a random sample on NAIP aerial photos.
    5. Count the people living near the confirmed ones, and whether EJScreen or CEJST
       already flags them.
    """)
    return


@app.cell
def _(Path, os, time):
    t_start = time.perf_counter()
    HERE = Path(__file__).parent
    DATA_DIR = Path(os.environ.get("GEO_DATA_DIR", HERE / "data"))
    OUT_DIR = Path(os.environ.get("GEO_OUT_DIR", HERE / "outputs"))
    for _d in (DATA_DIR / "aef", DATA_DIR / "hifld", OUT_DIR / "naip"):
        _d.mkdir(parents=True, exist_ok=True)

    YEAR = 2022
    # The Gulf Coast industrial corridor: Houston and Galveston Bay, Beaumont and Port Arthur,
    # Lake Charles, and the Mississippi river parishes from Baton Rouge to New Orleans.
    COUNTIES = {
        "48201": "Harris",
        "48167": "Galveston",
        "48039": "Brazoria",
        "48071": "Chambers",
        "48245": "Jefferson TX",
        "48361": "Orange",
        "22019": "Calcasieu",
        "22033": "East Baton Rouge",
        "22121": "West Baton Rouge",
        "22047": "Iberville",
        "22005": "Ascension",
        "22093": "St. James",
        "22095": "St. John the Baptist",
        "22089": "St. Charles",
        "22051": "Jefferson LA",
        "22071": "Orleans",
        "22087": "St. Bernard",
    }
    AEF_BASE = "https://data.source.coop/tge-labs/aef/v1/annual"
    HIFLD = "https://storage.googleapis.com/hifld-next-datasets-prod/hifld"
    # The four registries the classifier learns from, in the order a pixel near more than
    # one of them is labelled (a refinery is usually also an RMP facility).
    TRAIN_LAYERS = {
        "refinery": "petroleum-refineries",
        "terminal": "petroleum-product-terminals",
        "tsdf": "epa-rcra-treatment-storage-and-disposal-facilities",
        "rmp": "epa-emergency-response-rmp-facilities",
    }
    # Other registered sites. Negatives are kept away from these too.
    OTHER_LAYERS = {
        "tri": "epa-frs-toxic-release-inventory",
        "power_plant": "power-plants-1",
        "superfund": "epa-superfund-enterprise-management-system-sems-sites-1",
        "gas_processing": "natural-gas-processing-plants-1",
        "lng": "liquified-natural-gas-lng-import-and-export-terminals-1",
    }
    FRS_LAYER = "epa-facility-registry-service-frs-interests"
    EJ_DIR = Path(os.environ.get("EJ_OUT_DIR", DATA_DIR / "ej" / "out"))
    ALBERS = "EPSG:5070"
    HAND_CHECK = HERE / "hand_check.csv"
    BLOCK = 1024  # the files' internal block, 10.24 km at 10 m
    STRIDE = 2  # the scan keeps every second 10 m pixel each way
    POS_RADIUS_M = 30  # training pixels around each facility point
    NEG_MIN_DIST_M = 1000  # background pixels are at least this far from any facility
    NEG_PER_BLOCK = 300
    GDAL_ENV = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "GDAL_HTTP_MAX_RETRY": "5",
        "GDAL_HTTP_RETRY_DELAY": "2",
        "CPL_VSIL_CURL_CHUNK_SIZE": "1048576",
    }
    return (
        AEF_BASE,
        ALBERS,
        BLOCK,
        COUNTIES,
        DATA_DIR,
        EJ_DIR,
        FRS_LAYER,
        GDAL_ENV,
        HAND_CHECK,
        HIFLD,
        NEG_MIN_DIST_M,
        NEG_PER_BLOCK,
        OTHER_LAYERS,
        OUT_DIR,
        POS_RADIUS_M,
        STRIDE,
        TRAIN_LAYERS,
        YEAR,
        t_start,
    )


@app.cell
def _(Callable, DATA_DIR, DatasetReader, GDAL_ENV, HIFLD, Path, httpx, rasterio, time):
    def read_remote[T](url: str, read: Callable[[DatasetReader], T]) -> T:
        """Open a remote raster over HTTP range requests and return read(dataset).

        Source Cooperative now and then answers a range request with a bad body. GDAL caches
        what it got for that URL, so each retry adds a dummy query string to start afresh.
        """
        for attempt in range(4):
            href = url if attempt == 0 else f"{url}?retry={attempt}"
            try:
                with rasterio.Env(**GDAL_ENV), rasterio.open(f"/vsicurl/{href}") as src:
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
        with httpx.stream("GET", url, follow_redirects=True, timeout=600) as response:
            response.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in response.iter_bytes(1 << 20):
                    f.write(chunk)
        tmp.rename(path)
        return path

    def hifld_layer(layer: str) -> Path:
        """Download one HIFLD Next GeoParquet layer (v1.0.0) once."""
        url = f"{HIFLD}/{layer}/{layer}/v1.0.0/geoparquet/{layer}.parquet"
        return fetch(url, f"hifld/{layer}.parquet")

    def rx_bytes() -> int:
        """Bytes received from outside the machine, to measure what each step downloads."""
        lines = Path("/proc/net/dev").read_text().splitlines()[2:]
        rows = [line.split(":") for line in lines]
        return sum(int(stats.split()[0]) for name, stats in rows if name.strip() != "lo")

    return fetch, hifld_layer, read_remote, rx_bytes


@app.cell
def _(mo):
    mo.md(r"""
    ## The study area and the registries

    Reading 10 m embeddings is expensive (next section), so instead of all of Louisiana
    and Texas we take the 17 counties and parishes of the Gulf Coast industrial corridor,
    which hold most of the two states' refineries. Their land is the union of their
    census block groups, from EPA's EJScreen 2024 file as rebuilt by
    `ej-datasets-hifld-next/`; the same file gives the population and EJ flags at the end.

    The facility points come from [HIFLD Next](https://hifld.publicenvirodata.org): EIA's
    petroleum refineries and product terminals, and EPA's RMP chemical facilities and RCRA
    hazardous-waste treatment, storage and disposal facilities (TSDFs). These four are what
    the classifier learns from. Five more layers (TRI reporters, power plants, Superfund
    sites, gas processing plants, LNG terminals) are only used to keep background pixels
    away from anything registered, and to check the candidates at the end.
    """)
    return


@app.cell
def _(ALBERS, COUNTIES, EJ_DIR, OTHER_LAYERS, TRAIN_LAYERS, gpd, hifld_layer, pd):
    _cols = ["geoid", "acstotpop", "exceed_count_80", "geometry"]
    bg = gpd.read_parquet(EJ_DIR / "epa-ejscreen-2024-block-groups.parquet", columns=_cols)
    bg = bg[bg["geoid"].str[:5].isin(list(COUNTIES)) & bg.geometry.notna()].to_crs(ALBERS)
    bg = bg.reset_index(drop=True)
    bg["county"] = bg["geoid"].str[:5]
    bg["flag_ejscreen"] = bg["exceed_count_80"].fillna(0) > 0
    _cejst = gpd.read_parquet(
        EJ_DIR / "cejst-v2-census-tracts.parquet",
        columns=["geoid", "identified_as_disadvantaged", "geometry"],
    )
    _cejst = _cejst[_cejst["geoid"].str[:5].isin(list(COUNTIES))].to_crs(ALBERS)
    _joined = gpd.sjoin(
        gpd.GeoDataFrame(geometry=bg.representative_point(), crs=ALBERS),
        _cejst,
        how="left",
        predicate="within",
    )
    _joined = _joined[~_joined.index.duplicated()]
    bg["flag_cejst"] = _joined["identified_as_disadvantaged"].astype("boolean").fillna(False)
    bg["flag_any"] = bg["flag_ejscreen"] | bg["flag_cejst"]
    counties = bg.dissolve("county")[["geometry"]].reset_index()
    counties["name"] = counties["county"].map(COUNTIES)
    assert len(counties) == len(COUNTIES), "a study county has no block groups"

    _frames = []
    for _kind, _layer in {**TRAIN_LAYERS, **OTHER_LAYERS}.items():
        _f = gpd.read_parquet(hifld_layer(_layer)).to_crs(ALBERS)
        _f = _f[_f.geometry.notna() & ~_f.geometry.is_empty]
        _frames.append(
            gpd.GeoDataFrame(
                {"kind": [_kind] * len(_f)},
                geometry=_f.geometry.centroid.to_numpy(),
                crs=ALBERS,
            )
        )
    facilities = gpd.sjoin(
        pd.concat(_frames, ignore_index=True), counties[["county", "geometry"]], predicate="within"
    ).drop(columns="index_right")
    facilities = facilities.reset_index(drop=True)
    facilities["train"] = facilities["kind"].isin(list(TRAIN_LAYERS))
    _table = facilities.groupby(["county", "kind"]).size().unstack(fill_value=0)
    _table.index = _table.index.map(lambda c: counties.set_index("county").loc[c, "name"])
    _table.loc["total"] = _table.sum()
    _table[list(TRAIN_LAYERS) + list(OTHER_LAYERS)]
    return bg, counties, facilities


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 1: read the 10 m embeddings

    The embeddings come from the [Source Cooperative copy](https://source.coop/tge-labs/aef)
    of AlphaEarth's annual Satellite Embedding dataset (CC-BY 4.0, no account needed; "The
    AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google
    DeepMind"). Each file is an 8192 × 8192 tile of 10 m pixels in its UTM zone. The
    files store each of the 64 bands separately in 1024 × 1024 blocks, so even a single
    pixel costs one compressed block per band: about 40 MB for a 10 km square. Windowed
    reads around each facility would therefore save nothing over reading the whole block,
    so we read every block that touches the study area once, and keep:

    - the 10 m pixels within 30 m of each registered facility point (training positives);
    - 300 random 10 m pixels per block that are more than 1 km from any registered
      facility in all nine layers (training background);
    - every second pixel each way (a 20 m grid of 10 m pixels) for the scan in step 3,
      cached on disk.

    The same quirks as in the previous spike apply: files are stored bottom-up, so rows are
    flipped, and values are int8 that are dequantised as `(v / 127.5)² · sign(v)`, with
    -128 as no-data. The Mississippi river parishes straddle UTM zones 15 and 16; each
    pixel is read from the zone its longitude falls in, so nothing is counted twice.
    """)
    return


@app.cell
def _(
    AEF_BASE,
    ALBERS,
    BLOCK,
    DATA_DIR,
    NEG_MIN_DIST_M,
    NEG_PER_BLOCK,
    POS_RADIUS_M,
    STRIDE,
    TRAIN_LAYERS,
    YEAR,
    Affine,
    KDTree,
    ThreadPoolExecutor,
    Window,
    box,
    counties,
    facilities,
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
    _index = _index[_index["year"] == YEAR].set_geometry("geom")
    _area_wgs = counties.to_crs("EPSG:4326")
    tiles = _index[_index.intersects(_area_wgs.union_all())].reset_index(drop=True)

    # Which blocks of which tile to read: those that touch the study area within the
    # tile's own UTM zone.
    _blocks = []
    for _ti, _tile in tiles.iterrows():
        _zone = int(_tile["utm_zone"][:-1])
        _strip = box(-186 + 6 * _zone, 0, -180 + 6 * _zone, 60)
        _area = _area_wgs.clip(_strip).to_crs(_tile["crs"]).union_all()
        for _bi in range(8192 // BLOCK):
            for _bj in range(8192 // BLOCK):
                _x0 = _tile["utm_west"] + _bj * BLOCK * 10
                _y0 = _tile["utm_south"] + _bi * BLOCK * 10
                if _area.intersects(box(_x0, _y0, _x0 + BLOCK * 10, _y0 + BLOCK * 10)):
                    _blocks.append((_ti, _bi, _bj))

    _priority = {k: i for i, k in enumerate(TRAIN_LAYERS)}
    _county_ids = {c: i for i, c in enumerate(counties["county"])}

    def read_block(job: tuple[int, int, int]) -> dict:
        """Read one 10 km block at 10 m and keep training pixels and the 20 m scan grid."""
        ti, bi, bj = job
        tile = tiles.loc[ti]
        name = tile["path"].rsplit("/", 1)[1].removesuffix(".tiff")
        cache = DATA_DIR / "aef" / f"{YEAR}-{tile['utm_zone']}-{name}-{bi}-{bj}.npz"
        if cache.exists():
            return dict(np.load(cache))
        url = AEF_BASE + tile["path"].split("/v1/annual", 1)[1]
        window = Window(bj * BLOCK, bi * BLOCK, BLOCK, BLOCK)
        raw = read_remote(url, lambda r: r.read(window=window))
        assert raw.shape == (64, BLOCK, BLOCK), raw.shape
        raw = raw[:, ::-1, :]  # bottom-up file; now row 0 is the north edge
        west = tile["utm_west"] + bj * BLOCK * 10
        north = tile["utm_south"] + (bi + 1) * BLOCK * 10
        zone = int(tile["utm_zone"][:-1])
        strip = box(-186 + 6 * zone, 0, -180 + 6 * zone, 60)
        local = counties.to_crs("EPSG:4326").clip(strip).to_crs(tile["crs"])
        # County of each 10 m pixel (-1 outside the study area or in the other zone).
        county = rasterize(
            ((g, _county_ids[c]) for c, g in zip(local["county"], local.geometry, strict=True)),
            out_shape=(BLOCK, BLOCK),
            transform=Affine(10, 0, west, 0, -10, north),
            fill=-1,
            dtype="int16",
        )
        county[raw[0] == -128] = -1

        # Positives: pixels within POS_RADIUS_M of a training facility in this block.
        fac = facilities[facilities["train"]].to_crs(tile["crs"])
        cols = ((fac.geometry.x - west) / 10).to_numpy()
        rows = ((north - fac.geometry.y) / 10).to_numpy()
        r = POS_RADIUS_M / 10
        here = (cols >= -r) & (cols < BLOCK + r) & (rows >= -r) & (rows < BLOCK + r)
        pos = {}
        for fi, c, rr in zip(fac.index[here], cols[here], rows[here], strict=True):
            kind = _priority[facilities.at[fi, "kind"]]
            for pr in range(int(rr - r), int(rr + r) + 1):
                for pc in range(int(c - r), int(c + r) + 1):
                    inside = 0 <= pr < BLOCK and 0 <= pc < BLOCK
                    near = (pr + 0.5 - rr) ** 2 + (pc + 0.5 - c) ** 2 <= r * r
                    if inside and near and county[pr, pc] >= 0:
                        old = pos.get((pr, pc))
                        if old is None or kind < old[0]:
                            pos[(pr, pc)] = (kind, fi)
        pos_rc = np.array(list(pos), dtype=int).reshape(-1, 2)
        pos_kind_fac = np.array(list(pos.values()), dtype=int).reshape(-1, 2)

        # Background: random pixels in the study area far from every registered facility.
        rng = np.random.default_rng([zone, bi, bj, int(tile["utm_west"]), int(tile["utm_south"])])
        cand = np.argwhere(county >= 0)
        cand = cand[rng.choice(len(cand), min(len(cand), 3 * NEG_PER_BLOCK), replace=False)]
        allfac = facilities.to_crs(tile["crs"])
        tree = KDTree(np.c_[allfac.geometry.x, allfac.geometry.y])
        xy = np.c_[west + (cand[:, 1] + 0.5) * 10, north - (cand[:, 0] + 0.5) * 10]
        dist, _ = tree.query(xy)
        neg_rc = cand[dist > NEG_MIN_DIST_M][:NEG_PER_BLOCK]

        out = {
            "grid": raw[:, ::STRIDE, ::STRIDE].copy(),
            "grid_county": county[::STRIDE, ::STRIDE].copy(),
            "origin": np.array([west, north], dtype=np.float64),
            "pos": raw[:, pos_rc[:, 0], pos_rc[:, 1]].T.copy(),
            "pos_kind": pos_kind_fac[:, 0],
            "pos_facility": pos_kind_fac[:, 1],
            "neg": raw[:, neg_rc[:, 0], neg_rc[:, 1]].T.copy(),
            "neg_county": county[neg_rc[:, 0], neg_rc[:, 1]],
        }
        np.savez(cache, **out)
        return out

    # Each block is 64 range requests in a row, so throughput comes from reading many at once.
    with ThreadPoolExecutor(32) as _pool:
        blocks = list(_pool.map(read_block, _blocks))
    block_meta = pd.DataFrame(_blocks, columns=["tile", "bi", "bj"])
    block_meta["utm_zone"] = tiles.loc[block_meta["tile"], "utm_zone"].to_numpy()
    block_meta["crs"] = tiles.loc[block_meta["tile"], "crs"].to_numpy()
    read_stats = {
        "tiles": len(tiles),
        "blocks": len(blocks),
        "seconds": round(time.perf_counter() - _t),
        "downloaded_gb": round((rx_bytes() - _rx) / 1e9, 2),
        "scan_pixels": int(sum((b["grid_county"] >= 0).sum() for b in blocks)),
        "positive_pixels": int(sum(len(b["pos"]) for b in blocks)),
        "background_pixels": int(sum(len(b["neg"]) for b in blocks)),
    }
    read_stats
    return block_meta, blocks, read_stats, tiles


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 2: train a classifier on registered facilities

    Each training pixel is labelled with the type of the facility it sits next to
    (refinery, terminal, TSDF or RMP, in that order of precedence when a pixel is near
    more than one), or background. The model is a multinomial logistic regression on the
    64 embedding values: AlphaEarth's embeddings are made to work with simple linear
    probes, and a linear model can score the hundreds of millions of scan pixels in
    minutes.

    It is scored the way it will be used, on counties it never saw: the 17 counties are
    split into five groups, and each group is scanned by a model trained on the other
    four. First, the pixel-level check: how well does the probability of "any facility
    type" separate each type's pixels from background pixels in held-out counties (AUC)?
    """)
    return


@app.cell
def _(TRAIN_LAYERS, blocks, counties, facilities, np, pd):
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.model_selection import GroupKFold
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    def dequantise(v: np.ndarray) -> np.ndarray:
        """AlphaEarth's int8 storage back to embedding values."""
        f = v.astype(np.float32)
        return (f / 127.5) ** 2 * np.sign(f)

    KINDS = ["background", *TRAIN_LAYERS]
    _pos_fac = np.concatenate([b["pos_facility"] for b in blocks])
    X = dequantise(np.concatenate([b["pos"] for b in blocks] + [b["neg"] for b in blocks]))
    y = np.concatenate(
        [b["pos_kind"] + 1 for b in blocks] + [np.zeros(len(b["neg"]), int) for b in blocks]
    )
    groups = np.concatenate(
        [facilities.loc[_pos_fac, "county"].to_numpy()]
        + [counties["county"].to_numpy()[b["neg_county"]] for b in blocks]
    )
    # Five groups of counties, balanced by training pixels; each county is held out once.
    _gkf = GroupKFold(5)
    fold_of_county = {}
    for _k, (_, _test) in enumerate(_gkf.split(X, y, groups)):
        for _c in np.unique(groups[_test]):
            fold_of_county[_c] = _k
    fold = np.array([fold_of_county[g] for g in groups])

    models = []
    p_held_out = np.zeros((len(y), len(KINDS)))
    for _k in range(5):
        _m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000))
        _m.fit(X[fold != _k], y[fold != _k])
        p_held_out[fold == _k] = _m.predict_proba(X[fold == _k])
        models.append(_m)
    _p_ind = 1 - p_held_out[:, 0]
    pixel_auc = pd.DataFrame(
        {
            kind: {
                "training pixels": int((y == i).sum()),
                "facilities": int(len(np.unique(_pos_fac[y[: len(_pos_fac)] == i]))),
                "held-out AUC vs background": round(
                    roc_auc_score(y[(y == i) | (y == 0)] == i, _p_ind[(y == i) | (y == 0)]), 3
                ),
            }
            for i, kind in enumerate(KINDS)
            if i > 0
        }
    ).T
    pixel_auc.loc["background", "training pixels"] = int((y == 0).sum())
    pixel_auc
    return KINDS, dequantise, fold_of_county, models, pixel_auc


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 3: scan the held-out counties and group pixels into sites

    Every cached 20 m-grid pixel is scored by the model that didn't see its county. A
    pixel is "industrial" when the probability of any facility type is at least the
    threshold below. Industrial pixels are cleaned of single-pixel speckle (a 3 × 3
    opening), joined into connected sites within each tile, and sites smaller than 1 ha
    (25 grid pixels) are dropped. A site's type is the facility class with the highest
    mean probability over its pixels.

    The threshold (0.9) and the operating point for candidates (sites of 5 ha or more,
    about the size of a small tank farm) were set from the held-out registry scores below,
    before any photo was looked at. Small sites are mostly false alarms.

    Each site is then matched against the four training registries: it is **registered**
    if a facility of any of the four types is within 500 m of one of its pixels, and a
    **candidate** (a possible registry gap) if none is within 1 km. A facility is
    **found** if some site comes within 500 m of it.
    """)
    return


@app.cell
def _(
    ALBERS,
    BLOCK,
    KINDS,
    STRIDE,
    block_meta,
    blocks,
    counties,
    dequantise,
    fold_of_county,
    gpd,
    models,
    ndimage,
    np,
    pd,
    tiles,
    time,
):
    THRESHOLD = 0.9
    MIN_PIXELS = 25
    _t = time.perf_counter()
    _fold_of_idx = np.array([fold_of_county.get(c, -1) for c in counties["county"]])
    _g = BLOCK // STRIDE
    _sites, _pixels = [], []
    for _tile, _rows in block_meta.groupby("tile"):
        _n = 8192 // BLOCK
        prob = np.zeros((len(KINDS), _n * _g, _n * _g), np.float32)
        prob[0] = 1
        cnty = np.full((_n * _g, _n * _g), -1, np.int16)
        for _i, _b in _rows.iterrows():
            _blk = blocks[_i]
            # Mosaic rows run north to south, so block row bi sits at mosaic row n-1-bi.
            _r0, _c0 = (_n - 1 - _b["bi"]) * _g, _b["bj"] * _g
            _cc = _blk["grid_county"]
            cnty[_r0 : _r0 + _g, _c0 : _c0 + _g] = _cc
            _ok = np.argwhere(_cc >= 0)
            if not len(_ok):
                continue
            _feat = dequantise(_blk["grid"][:, _ok[:, 0], _ok[:, 1]].T)
            _folds = _fold_of_idx[_cc[_ok[:, 0], _ok[:, 1]]]
            for _k in np.unique(_folds):
                _sel = _folds == _k
                _p = models[_k].predict_proba(_feat[_sel]).T
                prob[:, _r0 + _ok[_sel, 0], _c0 + _ok[_sel, 1]] = _p
        _tile_west = tiles.at[_tile, "utm_west"]
        _tile_north = tiles.at[_tile, "utm_south"] + 8192 * 10
        _mask = ndimage.binary_opening(1 - prob[0] >= THRESHOLD, np.ones((3, 3), bool))
        _lab, _nlab = ndimage.label(_mask, np.ones((3, 3), bool))
        if not _nlab:
            continue
        _rr, _cc2 = np.nonzero(_lab)
        _ids = _lab[_rr, _cc2]
        _sizes = np.bincount(_ids)
        _keep = _sizes[_ids] >= MIN_PIXELS
        _rr, _cc2, _ids = _rr[_keep], _cc2[_keep], _ids[_keep]
        _xy = gpd.GeoSeries.from_xy(
            _tile_west + (_cc2 + 0.5) * 10 * STRIDE,
            _tile_north - (_rr + 0.5) * 10 * STRIDE,
            crs=tiles.at[_tile, "crs"],
        ).to_crs(ALBERS)
        _px = pd.DataFrame(
            {
                "site": [f"{_tile}-{i}" for i in _ids],
                "x": _xy.x.to_numpy(),
                "y": _xy.y.to_numpy(),
                "county_idx": cnty[_rr, _cc2],
            }
        )
        for _j, _kind in enumerate(KINDS):
            _px[f"p_{_kind}"] = prob[_j, _rr, _cc2]
        _pixels.append(_px)
    site_pixels = pd.concat(_pixels, ignore_index=True)
    _agg = {"x": "mean", "y": "mean", "county_idx": lambda s: s.mode().iloc[0]}
    _agg |= {f"p_{k}": "mean" for k in KINDS}
    sites = site_pixels.groupby("site").agg(_agg)
    sites["pixels"] = site_pixels.groupby("site").size()
    sites["area_ha"] = sites["pixels"] * (10 * STRIDE) ** 2 / 1e4
    sites["kind"] = sites[[f"p_{k}" for k in KINDS[1:]]].idxmax(axis=1).str[2:]
    sites["county"] = counties["county"].to_numpy()[sites["county_idx"]]
    sites = sites.drop(columns="county_idx")
    scan_stats = {
        "threshold": THRESHOLD,
        "sites": len(sites),
        "site_pixels": len(site_pixels),
        "seconds": round(time.perf_counter() - _t),
    }
    scan_stats
    return MIN_PIXELS, THRESHOLD, scan_stats, site_pixels, sites


@app.cell
def _(KDTree, TRAIN_LAYERS, facilities, np, pd, site_pixels, sites):
    MATCH_M, CANDIDATE_M = 500, 1000
    MIN_HA = 5  # the operating point for candidates: tank-farm scale and up
    train_fac = facilities[facilities["train"]].copy()
    _xy = site_pixels[["x", "y"]].to_numpy()
    _fac_xy = np.c_[train_fac.geometry.x, train_fac.geometry.y]
    # Distance from each site to the nearest training facility of each type, over its pixels.
    for _kind in TRAIN_LAYERS:
        _f = train_fac[train_fac["kind"] == _kind]
        _d, _ = KDTree(np.c_[_f.geometry.x, _f.geometry.y]).query(_xy)
        sites[f"d_{_kind}"] = pd.Series(_d).groupby(site_pixels["site"].to_numpy()).min()
    sites["d_registry"] = sites[[f"d_{k}" for k in TRAIN_LAYERS]].min(axis=1)
    sites["registered"] = sites["d_registry"] <= MATCH_M
    sites["kept"] = sites["area_ha"] >= MIN_HA
    sites["candidate"] = sites["kept"] & (sites["d_registry"] > CANDIDATE_M)
    _pixel_area = site_pixels["site"].map(sites["area_ha"]).to_numpy()

    def found(min_ha: float) -> np.ndarray:
        """Whether each training facility has a pixel of a site of at least min_ha nearby."""
        d, _ = KDTree(_xy[_pixel_area >= min_ha]).query(_fac_xy)
        return d <= MATCH_M

    by_size = pd.DataFrame(
        {
            f"sites of {_ha} ha or more": {
                "sites": int((sites["area_ha"] >= _ha).sum()),
                "precision": round(sites.loc[sites["area_ha"] >= _ha, "registered"].mean(), 3),
                "recall": round(found(_ha).mean(), 3),
                "candidates (over 1 km)": int(
                    ((sites["area_ha"] >= _ha) & (sites["d_registry"] > CANDIDATE_M)).sum()
                ),
            }
            for _ha in (1, MIN_HA, 20)
        }
    ).T
    train_fac["found"] = found(MIN_HA)
    _kept = sites[sites["kept"]]
    _rows = {}
    for _kind in TRAIN_LAYERS:
        _s = _kept[_kept["kind"] == _kind]
        _f = train_fac[train_fac["kind"] == _kind]
        _rows[_kind] = {
            "facilities": len(_f),
            "recall: found within 500 m": round(_f["found"].mean(), 3),
            "sites typed as this": len(_s),
            "precision: this type within 500 m": round((_s[f"d_{_kind}"] <= MATCH_M).mean(), 3),
            "precision: any of the four within 500 m": round(_s["registered"].mean(), 3),
        }
    _rows["all four"] = {
        "facilities": len(train_fac),
        "recall: found within 500 m": round(train_fac["found"].mean(), 3),
        "sites typed as this": len(_kept),
        "precision: this type within 500 m": np.nan,
        "precision: any of the four within 500 m": round(_kept["registered"].mean(), 3),
    }
    registry_scores = pd.DataFrame(_rows).T
    site_counts = {
        f"sites of {MIN_HA} ha or more": len(_kept),
        "registered (within 500 m)": int(_kept["registered"].sum()),
        "500 m to 1 km": int((~_kept["registered"] & ~_kept["candidate"]).sum()),
        "candidates (over 1 km)": int(_kept["candidate"].sum()),
        "candidate area, ha": round(_kept.loc[_kept["candidate"], "area_ha"].sum()),
    }
    by_size
    return CANDIDATE_M, MATCH_M, MIN_HA, by_size, registry_scores, site_counts, train_fac


@app.cell
def _(registry_scores):
    registry_scores
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 4: the candidates

    A candidate is more than 1 km from every refinery, terminal, TSDF and RMP facility in
    HIFLD Next. That doesn't yet make it unregistered: it may be a TRI reporter, a power
    plant or anything else EPA tracks. So each candidate also gets the distance to the
    other five HIFLD Next layers and to the nearest site in EPA's whole Facility
    Registry Service (FRS, 6.3 million program records, via HIFLD Next), with the program
    interests recorded there within 500 m.
    """)
    return


@app.cell
def _(
    ALBERS,
    CANDIDATE_M,
    FRS_LAYER,
    KDTree,
    MATCH_M,
    OTHER_LAYERS,
    counties,
    facilities,
    gpd,
    hifld_layer,
    np,
    pd,
    site_pixels,
    sites,
):
    _bounds = tuple(counties.to_crs("EPSG:4326").total_bounds)
    frs = gpd.read_parquet(
        hifld_layer(FRS_LAYER),
        columns=["geometry", "REGISTRY_ID", "PRIMARY_NAME", "INTEREST_TYPE"],
        bbox=_bounds,
    ).to_crs(ALBERS)
    frs = frs[frs.geometry.notna() & ~frs.geometry.is_empty]
    _cand_px = site_pixels[site_pixels["site"].isin(sites.index[sites["candidate"]])]
    _xy = _cand_px[["x", "y"]].to_numpy()
    candidates = sites[sites["candidate"]].copy()
    _other = facilities[facilities["kind"].isin(list(OTHER_LAYERS))]
    _d, _ = KDTree(np.c_[_other.geometry.x, _other.geometry.y]).query(_xy)
    candidates["d_other_hifld"] = pd.Series(_d).groupby(_cand_px["site"].to_numpy()).min()
    _frs_tree = KDTree(np.c_[frs.geometry.x, frs.geometry.y])
    _d, _ = _frs_tree.query(_xy)
    candidates["d_frs"] = pd.Series(_d).groupby(_cand_px["site"].to_numpy()).min()
    # FRS program interests within MATCH_M of each candidate's centre or edge.
    _near = _frs_tree.query_ball_point(_xy, MATCH_M)
    _by_site: dict[str, set[int]] = {}
    for _site, _idx in zip(_cand_px["site"], _near, strict=True):
        _by_site.setdefault(_site, set()).update(_idx)
    for _col, _out in (("INTEREST_TYPE", "frs_within_500m"), ("PRIMARY_NAME", "frs_names")):
        candidates[_out] = [
            "; ".join(sorted(set(frs[_col].iloc[sorted(_by_site.get(s, ()))].dropna())))[:300]
            for s in candidates.index
        ]
    _ll = gpd.GeoSeries.from_xy(candidates["x"], candidates["y"], crs=ALBERS).to_crs("EPSG:4326")
    candidates["lon"], candidates["lat"] = _ll.x.round(5).to_numpy(), _ll.y.round(5).to_numpy()
    candidate_registry = {
        "candidates": len(candidates),
        "another HIFLD Next layer within 1 km": int(
            (candidates["d_other_hifld"] <= CANDIDATE_M).sum()
        ),
        "an FRS site within 500 m": int((candidates["d_frs"] <= MATCH_M).sum()),
        "nothing in FRS within 1 km": int((candidates["d_frs"] > CANDIDATE_M).sum()),
    }
    candidate_registry
    return candidate_registry, candidates, frs


@app.cell
def _(mo):
    mo.md(r"""
    ### Hand check

    Thirty candidates, drawn at random with a fixed seed, each get a chip of the newest
    NAIP aerial photos (USDA, public domain, from Microsoft's Planetary Computer, which
    needs no account) with the site's pixels outlined, registered facilities from all
    nine layers marked, and FRS sites as small dots. Each chip was looked at and labelled
    in `hand_check.csv`:

    - **heavy**: the kind of site the classifier was trained on: tank farm, refinery,
      chemical or process plant, waste ponds or a landfill, a bulk terminal;
    - **light**: other industry: warehouses, a factory floor, a rail or container yard,
      a shipyard, a quarry;
    - **no**: nothing industrial: roofs, parking, roads, fields, water.

    The labels are the one part of this notebook that is human judgment (here, the worker
    agent's). The chips are in `outputs/naip/` so anyone can check them.
    """)
    return


@app.cell
def _(
    ALBERS,
    CANDIDATE_M,
    GDAL_ENV,
    OUT_DIR,
    candidates,
    facilities,
    frs,
    gpd,
    httpx,
    np,
    pd,
    plt,
    rasterio,
    site_pixels,
):
    from rasterio.merge import merge
    from rasterio.vrt import WarpedVRT
    from shapely import unary_union
    from shapely.geometry import box as shape_box
    from shapely.geometry import shape

    HAND_N = 30
    hand_sample = candidates.sample(min(HAND_N, len(candidates)), random_state=0)
    hand_sample["random"] = True
    # Also look at every candidate with nothing at all in FRS within 1 km, outside the
    # random sample, since those are the only ones that could be wholly unregistered.
    _extra = candidates[
        (candidates["d_frs"] > CANDIDATE_M) & ~candidates.index.isin(hand_sample.index)
    ]
    hand_sample = pd.concat([hand_sample, _extra.assign(random=False)])
    _pc = "https://planetarycomputer.microsoft.com/api"
    _token = httpx.get(f"{_pc}/sas/v1/token/naip", timeout=60).raise_for_status().json()["token"]
    _colors = {
        "refinery": "red",
        "terminal": "white",
        "tsdf": "magenta",
        "rmp": "orange",
        "tri": "yellow",
        "power_plant": "lime",
        "superfund": "cyan",
        "gas_processing": "blue",
        "lng": "purple",
    }
    naip_dates = {}
    for _site, _row in hand_sample.iterrows():
        _png = OUT_DIR / "naip" / f"{_site}.png"
        _px = site_pixels[site_pixels["site"] == _site]
        _x0, _y0, _x1, _y1 = _px["x"].min(), _px["y"].min(), _px["x"].max(), _px["y"].max()
        _half = max(_x1 - _x0, _y1 - _y0, 500) / 2 + 500
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
        assert _items, f"no NAIP image for {_site}"
        # The newest year whose photos cover the whole chip; a year can graze its edge.
        _need = shape_box(_box.x.min(), _box.y.min(), _box.x.max(), _box.y.max())
        _years = sorted({f["properties"]["naip:year"] for f in _items}, reverse=True)
        _year = next(
            yr
            for yr in _years
            if unary_union(
                [shape(f["geometry"]) for f in _items if f["properties"]["naip:year"] == yr]
            ).covers(_need)
        )
        _items = [f for f in _items if f["properties"]["naip:year"] == _year]
        _dates = sorted(f["properties"]["datetime"][:10] for f in _items)
        naip_dates[_site] = f"{_dates[0]} to {_dates[-1]}"
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
        _ax.scatter(
            _px["x"], _px["y"], s=2, marker="s", facecolors="none", edgecolors="cyan", lw=0.3
        )
        _fr = frs.cx[_ext[0] : _ext[2], _ext[1] : _ext[3]]
        _ax.scatter(_fr.geometry.x, _fr.geometry.y, s=6, c="black", label="FRS site")
        _f = facilities.cx[_ext[0] : _ext[2], _ext[1] : _ext[3]]
        for _k, _g in _f.groupby("kind"):
            _ax.scatter(_g.geometry.x, _g.geometry.y, s=30, c=_colors[_k], edgecolor="k", label=_k)
        _ax.set_xlim(_ext[0], _ext[2])
        _ax.set_ylim(_ext[1], _ext[3])
        _ax.set_axis_off()
        _ax.legend(loc="lower left", fontsize=7)
        _ax.set_title(
            f"{_site}: {_row['area_ha']:.0f} ha, {_row['lat']:.4f}, {_row['lon']:.4f}, "
            f"{2 * _half / 1000:.1f} km across, NAIP {naip_dates[_site]}",
            fontsize=8,
        )
        _fig.tight_layout()
        _fig.savefig(_png, dpi=110)
        plt.close(_fig)
    hand_sample[["county", "area_ha", "kind", "d_registry", "d_frs", "lat", "lon"]].round(0)
    return hand_sample, naip_dates


@app.cell
def _(HAND_CHECK, MATCH_M, candidates, hand_sample, np, pd):
    hand_labels = (
        pd.read_csv(HAND_CHECK)
        if HAND_CHECK.exists()
        else pd.DataFrame(columns=["site", "label", "note"])
    )
    hand = hand_sample.join(hand_labels.set_index("site"), how="left")
    _rand = hand[hand["random"]]
    _n = len(_rand)
    _real = int((_rand["label"] == "heavy").sum())

    def _wilson(k: int, n: int) -> list[float]:
        """95% Wilson interval for a share k / n."""
        z, p = 1.96, k / n
        centre = (p + z * z / (2 * n)) / (1 + z * z / n)
        half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        return [round(centre - half, 3), round(centre + half, 3)]

    _labels = _rand["label"]
    hand_result = {
        "random sample": _n,
        "unlabelled": hand.index[hand["label"].isna()].tolist(),
        "heavy": _real,
        "light": int((_labels == "light").sum()),
        "no": int((_labels == "no").sum()),
        "heavy share, 95% CI": _wilson(_real, _n),
        "heavy or light share, 95% CI": _wilson(int(_labels.isin(["heavy", "light"]).sum()), _n),
        "real (heavy or light) with an FRS site within 500 m": int(
            (_labels.isin(["heavy", "light"]) & (_rand["d_frs"] <= MATCH_M)).sum()
        ),
        "candidates in all": len(candidates),
        "extra: candidates with nothing in FRS within 1 km": hand.loc[
            ~hand["random"], "label"
        ].to_dict(),
    }
    hand_result
    return hand, hand_result


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 5: who lives next to the confirmed ones?

    For each hand-checked site labelled heavy (and, separately, light), we count the
    people within 1 and 3 km of its pixels, by the share of each block group's area inside
    the buffer times its ACS population (EJScreen 2024), and how many of them live in
    block groups flagged by EJScreen (any EJ index at or above the 80th national
    percentile) or CEJST v2.0 (disadvantaged tract).
    """)
    return


@app.cell
def _(ALBERS, bg, gpd, hand, np, pd, site_pixels):
    _rows = []
    for _site, _row in hand[hand["label"].isin(["heavy", "light"])].iterrows():
        _px = site_pixels[site_pixels["site"] == _site]
        _shape = gpd.GeoSeries.from_xy(_px["x"], _px["y"], crs=ALBERS).union_all().convex_hull
        for _km in (1, 3):
            _buf = _shape.buffer(_km * 1000)
            _hit = bg[bg.intersects(_buf)]
            _share = _hit.intersection(_buf).area / _hit.area
            _pop = _hit["acstotpop"].fillna(0) * _share
            _rows.append(
                {
                    "site": _site,
                    "label": _row["label"],
                    "km": _km,
                    "people": _pop.sum(),
                    "in EJScreen-flagged block groups": _pop[_hit["flag_ejscreen"]].sum(),
                    "in CEJST-disadvantaged tracts": _pop[_hit["flag_cejst"].astype(bool)].sum(),
                    "in either": _pop[_hit["flag_any"].astype(bool)].sum(),
                }
            )
    _cols = ["site", "label", "km", "people", "in EJScreen-flagged block groups"]
    _cols += ["in CEJST-disadvantaged tracts", "in either"]
    exposure = pd.DataFrame(_rows, columns=_cols)
    exposure_summary = (
        exposure.groupby(["label", "km"])
        .agg(
            sites=("site", "size"),
            people=("people", "sum"),
            median_people=("people", "median"),
            flagged_ejscreen=("in EJScreen-flagged block groups", "sum"),
            flagged_cejst=("in CEJST-disadvantaged tracts", "sum"),
            flagged_either=("in either", "sum"),
        )
        .round(0)
    )
    exposure_summary["share flagged by either"] = (
        exposure_summary["flagged_either"] / exposure_summary["people"].replace(0, np.nan)
    ).round(3)
    exposure_summary
    return exposure, exposure_summary


@app.cell
def _(OUT_DIR, candidates, counties, hand, plt, sites, train_fac):
    _fig, _axes = plt.subplots(1, 2, figsize=(14, 6), gridspec_kw={"width_ratios": [1.3, 1]})
    for _ax, _states in zip(_axes, (("48",), ("22",)), strict=True):
        _c = counties[counties["county"].str[:2].isin(_states)]
        _c.boundary.plot(ax=_ax, color="grey", lw=0.5)
        _s = sites[sites["county"].str[:2].isin(_states)]
        _ax.scatter(
            _s.loc[_s["registered"], "x"],
            _s.loc[_s["registered"], "y"],
            s=4,
            c="tab:blue",
            label="site near a registered facility",
        )
        _ax.scatter(
            _s.loc[_s["candidate"], "x"],
            _s.loc[_s["candidate"], "y"],
            s=4,
            c="tab:red",
            label="candidate (> 1 km)",
        )
        _f = train_fac[train_fac["county"].str[:2].isin(_states)]
        _ax.scatter(
            _f.geometry.x,
            _f.geometry.y,
            s=3,
            marker="x",
            c="k",
            lw=0.5,
            label="registered facility",
        )
        _h = hand[(hand["label"] == "heavy") & hand["county"].str[:2].isin(_states)]
        _ax.scatter(
            _h["x"],
            _h["y"],
            s=60,
            facecolors="none",
            edgecolors="gold",
            lw=1.5,
            label="hand-checked heavy",
        )
        _ax.set_axis_off()
    _axes[0].set_title("Texas: Houston to Orange")
    _axes[1].set_title("Louisiana: Lake Charles and the river parishes")
    _axes[0].legend(loc="lower right", fontsize=8, markerscale=2)
    _fig.tight_layout()
    _fig.savefig(OUT_DIR / "sites_map.png", dpi=120)
    _cols = [
        "county",
        "lat",
        "lon",
        "area_ha",
        "kind",
        "p_background",
        "d_registry",
        "d_other_hifld",
        "d_frs",
        "frs_within_500m",
        "frs_names",
    ]
    candidates[_cols].sort_values("area_ha", ascending=False).round(3).to_csv(
        OUT_DIR / "candidates.csv"
    )
    _fig
    return


@app.cell
def _(
    OUT_DIR,
    candidate_registry,
    exposure_summary,
    hand_result,
    json,
    naip_dates,
    pixel_auc,
    read_stats,
    registry_scores,
    site_counts,
    t_start,
    time,
):
    summary = {
        "read": read_stats,
        "pixel_auc": pixel_auc.to_dict(orient="index"),
        "registry_scores": registry_scores.to_dict(orient="index"),
        "site_counts": site_counts,
        "candidate_registry": candidate_registry,
        "hand_check": hand_result,
        "exposure": {
            f"{lab} {k} km": v for (lab, k), v in exposure_summary.to_dict(orient="index").items()
        },
        "naip_dates": naip_dates,
        "total_seconds": round(time.perf_counter() - t_start),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    summary["total_seconds"]
    return


if __name__ == "__main__":
    app.run()

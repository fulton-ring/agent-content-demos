import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import duckdb
    import geopandas as gpd
    import httpx
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import torch
    from rasterio.features import rasterize
    from rasterio.transform import Affine
    from scipy import ndimage
    from shapely.geometry import Point, box
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score

    return (
        Affine,
        LogisticRegression,
        Path,
        Point,
        ThreadPoolExecutor,
        box,
        duckdb,
        gpd,
        httpx,
        json,
        mo,
        ndimage,
        np,
        os,
        pd,
        plt,
        rasterize,
        roc_auc_score,
        time,
        torch,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Can open satellite embeddings find electric substations?

    HIFLD Next has no public substation layer: DHS withdrew HIFLD's in 2022 (see
    [`hifld-grid-gaps/`](../hifld-grid-gaps/)), so studies fall back on OpenStreetMap,
    which has gaps. [TESSERA](https://github.com/ucam-eo/tessera) is a free, CC0 model from
    Cambridge that turns a year of Sentinel-1 radar and Sentinel-2 optical images into a
    128-number vector for every 10 m pixel. This notebook asks whether those vectors can
    find substations.

    We expect a partial yes. A 500 kV switchyard covers tens of thousands of square metres
    of gravel, steel and transformers, hundreds of pixels. A distribution substation on a
    street corner is a handful of pixels, blurred by a year of compositing.

    The steps:

    1. Get OpenStreetMap substations with their voltage tags in two regions: Tennessee
       (the core of TVA) and New York.
    2. Read TESSERA 2024 embeddings around each substation and around random points far
       from any, by HTTP range reads from Source Cooperative.
    3. Train two models on part of each region: a linear probe on single pixels and a
       small convolutional network (CNN) on 320 m patches.
    4. Score both on held-out areas: recall by voltage class on held-out substations, then
       a full scan of held-out 0.1° tiles for precision.
    5. Run the CNN where HIFLD Next transmission lines end more than 1 km from any OSM
       substation, and check the top-scoring sites by hand on aerial photos.
    6. Record time, downloads and cost.
    """)
    return


@app.cell
def _(Path, os, time):
    DATA_DIR = Path(os.environ.get("SUBSTATION_DATA_DIR", "data"))
    OUT_DIR = Path(os.environ.get("SUBSTATION_OUT_DIR", "outputs"))
    for _d in (DATA_DIR, OUT_DIR):
        _d.mkdir(parents=True, exist_ok=True)
    YEAR = 2024
    # Source Cooperative's TESSERA v1 store, read anonymously over HTTPS.
    TESSERA = "https://data.source.coop/tessera/tessera/npy/v1"
    REGIONS = {"TN": "Tennessee (TVA)", "NY": "New York"}
    ALBERS = "EPSG:5070"
    PATCH = 32  # pixels, about 320 m across
    SEED = 195
    timings = {}
    run_start = time.time()
    return ALBERS, DATA_DIR, OUT_DIR, PATCH, REGIONS, SEED, TESSERA, YEAR, run_start, timings


@app.cell
def _(Path, httpx):
    def fetch(url: str, path: Path) -> int:
        """Download url to path once; return the bytes downloaded (0 if cached)."""
        if path.exists():
            return 0
        tmp = path.with_suffix(path.suffix + ".part")
        with httpx.stream("GET", url, timeout=600, follow_redirects=True) as r:
            r.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in r.iter_bytes(1 << 20):
                    f.write(chunk)
        tmp.rename(path)
        return path.stat().st_size

    return (fetch,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. The regions and the answer key

    The regions are the states of Tennessee and New York (Census 2024 boundaries).
    Tennessee is the core of the TVA system, where a 2026 George Mason study had to add 24
    synthetic substations to its 84-node backbone because OSM lacked them; New York is one of
    the two states its sister study said had sparse OSM substation coverage.

    The answer key is OpenStreetMap's `power=substation` features, read from
    [Overture Maps](https://docs.overturemaps.org/) `base/infrastructure` with the original OSM
    tags (the same copy as [`us-substations-verified/`](../us-substations-verified/)). OSM's
    `voltage` tag is in volts, `;`-separated when there are several; a substation's class is
    its highest voltage.
    """)
    return


@app.cell
def _(ALBERS, DATA_DIR, REGIONS, fetch, gpd, time, timings):
    _t = time.time()
    _states_zip = DATA_DIR / "cb_2024_us_state_500k.zip"
    downloaded = {
        "census_states": fetch(
            "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_state_500k.zip",
            _states_zip,
        )
    }
    states = gpd.read_file(_states_zip)
    states = states[states["STUSPS"].isin(list(REGIONS))][["STUSPS", "geometry"]]
    states = states.rename(columns={"STUSPS": "region"}).to_crs(ALBERS).reset_index(drop=True)
    timings["states"] = time.time() - _t
    states.assign(km2=states.area / 1e6).drop(columns="geometry")
    return downloaded, states


@app.cell
def _(DATA_DIR, Path, duckdb, states, time, timings):
    _t = time.time()
    overture_release = "2026-09-23.0"
    overture_path = DATA_DIR / f"overture-substations-tn-ny-{overture_release}.parquet"
    _bounds = states.to_crs(4326).bounds.agg(
        {"minx": "min", "miny": "min", "maxx": "max", "maxy": "max"}
    )
    if not overture_path.exists():
        _con = duckdb.connect()
        _con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
        # An empty key makes DuckDB read the public bucket anonymously.
        _con.sql("CREATE SECRET overture (TYPE s3, KEY_ID '', SECRET '', REGION 'us-west-2')")
        _con.sql(f"""
            COPY (
                SELECT id, source_tags['voltage'] AS voltage,
                       source_tags['substation'] AS substation_tag, ST_AsWKB(geometry) AS wkb
                FROM read_parquet(
                    's3://overturemaps-us-west-2/release/{overture_release}/theme=base/type=infrastructure/*')
                WHERE subtype = 'power' AND class = 'substation'
                  AND bbox.xmin > {_bounds.minx} AND bbox.xmax < {_bounds.maxx}
                  AND bbox.ymin > {_bounds.miny} AND bbox.ymax < {_bounds.maxy}
            ) TO '{overture_path}.part' (FORMAT parquet)
        """)
        Path(f"{overture_path}.part").rename(overture_path)
    timings["overture"] = time.time() - _t
    return overture_path, overture_release


@app.cell
def _(ALBERS, gpd, np, overture_path, pd, states):
    _raw = pd.read_parquet(overture_path)
    _volts = (
        _raw["voltage"]
        .fillna("")
        .str.findall(r"\d+(?:\.\d+)?")
        .map(lambda vs: max(map(float, vs), default=np.nan))
    )
    # A few mappers write kilovolts ("115"); under 1,000 is read as kV, the rest as volts.
    _raw["kv"] = np.where(_volts < 1000, _volts, _volts / 1000)
    _osm = gpd.GeoDataFrame(
        _raw.drop(columns="wkb"), geometry=gpd.GeoSeries.from_wkb(_raw["wkb"]), crs=4326
    ).to_crs(ALBERS)
    osm = gpd.sjoin(_osm, states, predicate="intersects")
    osm = osm[~osm.index.duplicated()].drop(columns="index_right").reset_index(drop=True)
    VOLTAGE_CLASSES = ["230 kV+", "100-229 kV", "under 100 kV", "no voltage tag"]
    osm["vclass"] = np.select(
        [osm["kv"] >= 230, osm["kv"] >= 100, osm["kv"] > 0],
        VOLTAGE_CLASSES[:3],
        VOLTAGE_CLASSES[3],
    )
    osm["area_m2"] = np.where(osm.geom_type == "Point", 0.0, osm.area)
    osm_counts = (
        osm.pivot_table(index="vclass", columns="region", values="id", aggfunc="count")
        .reindex(VOLTAGE_CLASSES)
        .fillna(0)
        .astype(int)
    )
    osm_counts.loc["all"] = osm_counts.sum()
    _area = osm.groupby("vclass")["area_m2"].median().reindex(VOLTAGE_CLASSES)
    osm_counts["median fenced area (m²)"] = list(_area.round()) + [round(osm["area_m2"].median())]
    print(f"Mapped as points, not areas: {int((osm.geom_type == 'Point').sum()):,} of {len(osm):,}")
    osm_counts
    return VOLTAGE_CLASSES, osm, osm_counts


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Training and held-out areas, and the samples

    Nearby substations look alike and share land cover, so a random split would leak. We cut
    each state into 0.5° blocks (about 45 × 55 km) and hold out a quarter of the blocks. Every
    number below is scored only on held-out blocks.

    Positives are all 3,922 OSM substations, a patch centred on each one. Negatives are random
    points inside the same state at least 1 km from any OSM substation, as many as there are
    substations in that state.
    """)
    return


@app.cell
def _(ALBERS, SEED, gpd, np, osm, pd, states):
    _rng = np.random.default_rng(SEED)

    def block_of(lon: np.ndarray, lat: np.ndarray) -> np.ndarray:
        return (np.floor(lon * 2).astype(int) * 1000 + np.floor(lat * 2).astype(int)).astype(int)

    _c = osm.geometry.representative_point().to_crs(4326)
    _pos = pd.DataFrame(
        {"lon": _c.x, "lat": _c.y, "region": osm["region"], "osm_row": osm.index, "label": 1}
    )
    _neg = []
    _union = osm.geometry.buffer(1000).union_all()
    for _region, _n in _pos["region"].value_counts().items():
        _shape = states.loc[states["region"] == _region, "geometry"].iloc[0]
        _x0, _y0, _x1, _y1 = _shape.bounds
        _pts = gpd.GeoSeries.from_xy(
            _rng.uniform(_x0, _x1, 8 * _n), _rng.uniform(_y0, _y1, 8 * _n), crs=ALBERS
        )
        _pts = _pts[_pts.within(_shape) & ~_pts.within(_union)].iloc[:_n].to_crs(4326)
        assert len(_pts) == _n, f"not enough negative points in {_region}"
        _neg.append(
            pd.DataFrame(
                {"lon": _pts.x, "lat": _pts.y, "region": _region, "osm_row": -1, "label": 0}
            )
        )
    samples = pd.concat([_pos, *_neg], ignore_index=True)
    samples["block"] = block_of(samples["lon"].to_numpy(), samples["lat"].to_numpy())
    _blocks = np.sort(samples["block"].unique())
    test_blocks = set(_rng.choice(_blocks, size=len(_blocks) // 4, replace=False).tolist())
    samples["split"] = np.where(samples["block"].isin(test_blocks), "test", "train")
    # A tenth of the training rows picks thresholds and stops training; it is never tested on.
    _train = samples.index[samples["split"] == "train"]
    samples.loc[_rng.choice(_train, size=len(_train) // 10, replace=False), "split"] = "val"
    samples.pivot_table(index=["region", "split"], columns="label", values="lon", aggfunc="count")
    return block_of, samples, test_blocks


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Reading TESSERA embeddings

    TESSERA v1 is stored on Source Cooperative as one file per 0.1° tile and year: an int8
    array of shape (rows, columns, 128) and a float32 scale per pixel, about 130 MB a tile
    in EPSG:4326 at about 10 m. The real value is `int8 × scale`. Source Cooperative publishes
    a tile index (`index/tessera_2024.parquet`) with each file's byte offset, shape and
    transform, and a `.npy` is one contiguous row-major buffer, so any band of rows is one
    HTTP range request. A column window needs one request per row, and those come back
    slower in total than reading the whole width of the rows (we measured about 200 small
    requests a second against 30 to 60 MB/s for wide ones), so each patch reads 40 full rows
    and keeps 40 columns. The CNN trains on random 32 × 32 crops of those 40 × 40 patches.
    """)
    return


@app.cell
def _(DATA_DIR, TESSERA, YEAR, downloaded, fetch, np, pd):
    _idx_path = DATA_DIR / f"tessera_{YEAR}_index.parquet"
    downloaded["tessera_index"] = fetch(f"{TESSERA}/index/tessera_{YEAR}.parquet", _idx_path)
    tiles = pd.read_parquet(
        _idx_path,
        columns=[
            "lon",
            "lat",
            "height",
            "width",
            "grid_offset",
            "scales_offset",
            "grid_uri",
            "scales_uri",
            "transform",
        ],
    )
    tiles["key"] = list(zip(tiles["lon"].round(2), tiles["lat"].round(2), strict=True))
    tiles = tiles.set_index("key")

    def tile_key(lon: float, lat: float) -> tuple[float, float]:
        return (round(np.floor(lon * 10) / 10 + 0.05, 2), round(np.floor(lat * 10) / 10 + 0.05, 2))

    def https(uri: str) -> str:
        return TESSERA + uri.split("/npy/v1", 1)[1]

    print(f"TESSERA {YEAR} tiles worldwide: {len(tiles):,}")
    return https, tile_key, tiles


@app.cell
def _(Affine, ThreadPoolExecutor, httpx, https, np, tile_key, tiles, time):
    READ = 40  # pixels read around each point
    range_bytes = [0]  # bytes fetched by range reads this run, for the cost section
    _client = httpx.Client(timeout=120, limits=httpx.Limits(max_connections=32))

    def get_range(url: str, start: int, length: int) -> bytes:
        """One HTTP range request, retried up to 4 times."""
        for attempt in range(4):
            try:
                r = _client.get(url, headers={"Range": f"bytes={start}-{start + length - 1}"})
                if r.status_code == 206 and len(r.content) == length:
                    range_bytes[0] += length
                    return r.content
            except httpx.HTTPError:
                pass
            time.sleep(2**attempt)
        raise RuntimeError(f"range read failed: {url} {start}+{length}")

    def read_rows(key: tuple[float, float], r0: int, n: int) -> tuple[np.ndarray, np.ndarray]:
        """Rows r0..r0+n of one tile: int8 codes (n, W, 128) and scales (n, W)."""
        t = tiles.loc[[key]].iloc[0]
        w = int(t["width"])
        g = get_range(https(t["grid_uri"]), int(t["grid_offset"]) + r0 * w * 128, n * w * 128)
        s = get_range(https(t["scales_uri"]), int(t["scales_offset"]) + r0 * w * 4, n * w * 4)
        return (
            np.frombuffer(g, np.int8).reshape(n, w, 128),
            np.frombuffer(s, np.float32).reshape(n, w),
        )

    def read_patch(
        lon: float, lat: float, size: int = READ
    ) -> tuple[np.ndarray, np.ndarray, Affine]:
        """A size × size window centred on a point, shifted inside its tile at tile edges."""
        key = tile_key(lon, lat)
        t = tiles.loc[[key]].iloc[0]
        c, a, _b, f, _d, e = t["transform"]
        h, w = int(t["height"]), int(t["width"])
        r0 = int(np.clip(round((lat - f) / e) - size // 2, 0, h - size))
        c0 = int(np.clip(round((lon - c) / a) - size // 2, 0, w - size))
        codes, scales = read_rows(key, r0, size)
        return (
            codes[:, c0 : c0 + size].copy(),
            scales[:, c0 : c0 + size].copy(),
            Affine(a, 0, c + c0 * a, 0, e, f + r0 * e),
        )

    def read_patches(
        points: list[tuple[float, float]], size: int = READ
    ) -> tuple[np.ndarray, np.ndarray, list[Affine]]:
        with ThreadPoolExecutor(16) as ex:
            out = list(ex.map(lambda p: read_patch(p[0], p[1], size), points))
        return (
            np.stack([o[0] for o in out]),
            np.stack([o[1] for o in out]),
            [o[2] for o in out],
        )

    return READ, range_bytes, read_patches, read_rows


@app.cell
def _(Affine, DATA_DIR, READ, YEAR, np, read_patches, samples, time, timings):
    _t = time.time()
    _cache = DATA_DIR / f"patches_{YEAR}_{READ}.npz"
    if _cache.exists():
        _z = np.load(_cache)
        codes, scales, _tf = _z["codes"], _z["scales"], _z["transforms"]
    else:
        codes, scales, _aff = read_patches(list(zip(samples["lon"], samples["lat"], strict=True)))
        _tf = np.array([a[:6] for a in _aff])
        np.savez(_cache, codes=codes, scales=scales, transforms=_tf)
    patch_transforms = [Affine(*t) for t in _tf]
    # Water and never-observed pixels carry NaN or infinite scales; treat them as zero vectors.
    scales = np.where(np.isfinite(scales), scales, 0).astype(np.float32)
    timings["read_patches"] = time.time() - _t
    print(
        f"{len(codes):,} patches, {codes.nbytes / 1e9:.1f} GB of codes, "
        f"{timings['read_patches']:.0f} s"
    )
    return codes, patch_transforms, scales


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Model 1: a linear probe on single pixels

    The simplest test of whether the embedding "knows" what a substation is: a logistic
    regression on one pixel's 128 numbers. Positive pixels are those inside a training
    substation's OSM outline (up to 100 per substation, so big yards don't swamp small ones);
    negative pixels are 30 from each negative patch and 10 from each positive patch more than
    60 m outside the outline, so the probe has to tell the yard from the fields and roads
    around it. A patch's score is the highest 3 × 3-smoothed pixel probability in its central
    160 m.
    """)
    return


@app.cell
def _(ALBERS, READ, SEED, codes, np, osm, patch_transforms, rasterize, samples, scales):
    _rng = np.random.default_rng(SEED)
    _outline = osm.to_crs(4326).geometry
    _near = osm.geometry.buffer(60).to_crs(4326)
    inside = np.zeros((len(samples), READ, READ), bool)
    near = np.zeros_like(inside)
    for _i in np.flatnonzero(samples["label"].to_numpy() == 1):
        _row = int(samples.at[_i, "osm_row"])
        _tf = patch_transforms[_i]
        inside[_i] = (
            rasterize([_outline.iloc[_row]], (READ, READ), transform=_tf, all_touched=True) > 0
        )
        near[_i] = rasterize([_near.iloc[_row]], (READ, READ), transform=_tf, all_touched=True) > 0
        if not inside[_i].any():  # a point, or a yard smaller than a pixel
            inside[_i, READ // 2 - 1 : READ // 2 + 1, READ // 2 - 1 : READ // 2 + 1] = True

    def pixels(rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        """Training pixels for the probe from the given sample rows."""
        xs, ys = [], []
        for i in rows:
            if samples.at[i, "label"] == 1:
                pos = np.argwhere(inside[i])
                pos = pos[_rng.permutation(len(pos))[:100]]
                neg = np.argwhere(~near[i])
                neg = neg[_rng.permutation(len(neg))[:10]]
            else:
                pos = np.empty((0, 2), int)
                neg = _rng.integers(0, READ, size=(30, 2))
            for cells, y in ((pos, 1), (neg, 0)):
                xs.append(
                    codes[i, cells[:, 0], cells[:, 1]] * scales[i, cells[:, 0], cells[:, 1], None]
                )
                ys.append(np.full(len(cells), y))
        return np.concatenate(xs).astype(np.float32), np.concatenate(ys)

    probe_x, probe_y = pixels(np.flatnonzero(samples["split"].to_numpy() == "train"))
    print(
        f"Probe training pixels: {int(probe_y.sum()):,} substation, "
        f"{int((probe_y == 0).sum()):,} other"
    )
    assert ALBERS
    return inside, probe_x, probe_y


@app.cell
def _(LogisticRegression, probe_x, probe_y, time, timings):
    _t = time.time()
    probe = LogisticRegression(C=1.0, max_iter=2000, class_weight="balanced")
    probe.fit(probe_x, probe_y)
    timings["train_probe"] = time.time() - _t
    print(f"Probe trained in {timings['train_probe']:.0f} s")
    return (probe,)


@app.cell
def _(READ, codes, ndimage, np, probe, scales):
    def probe_map(c: np.ndarray, s: np.ndarray) -> np.ndarray:
        """Smoothed per-pixel substation probability for one (rows, cols, 128) block."""
        x = (c.reshape(-1, 128) * s.reshape(-1, 1)).astype(np.float32)
        p = probe.predict_proba(x)[:, 1].reshape(c.shape[:2])
        return ndimage.uniform_filter(p, size=3, mode="nearest")

    _lo, _hi = READ // 2 - 8, READ // 2 + 8
    probe_score = np.array(
        [probe_map(codes[i], scales[i])[_lo:_hi, _lo:_hi].max() for i in range(len(codes))]
    )
    return probe_map, probe_score


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Model 2: a small CNN on 320 m patches

    A pixel can't see a yard's shape or the lines leading into it; a CNN can. Ours is four
    convolutions (a 1 × 1 that mixes the 128 bands down to 32, then three 3 × 3 with growing
    dilation, seeing about 150 m around each pixel), a max over the 32 × 32 window, and one
    linear layer. Because the max comes last, the same network scores every window of a whole
    tile in one pass, which is how section 7 scans held-out tiles. It trains on random 32 × 32
    crops of the 40 × 40 patches, flipped and rotated, for up to 15 epochs, keeping the epoch
    with the best validation AUC.
    """)
    return


@app.cell
def _(PATCH, READ, SEED, codes, np, roc_auc_score, samples, scales, time, timings, torch):
    torch.manual_seed(SEED)
    torch.set_num_threads(max(1, torch.get_num_threads()))
    _rng = np.random.default_rng(SEED)
    _train = np.flatnonzero(samples["split"].to_numpy() == "train")
    _val = np.flatnonzero(samples["split"].to_numpy() == "val")
    _y = samples["label"].to_numpy().astype(np.float32)
    # Per-band mean and spread of dequantised training pixels, for input scaling.
    _px = (codes[_train, ::4, ::4] * scales[_train, ::4, ::4, None]).reshape(-1, 128)
    band_mean = torch.tensor(_px.mean(0), dtype=torch.float32).view(1, 128, 1, 1)
    band_std = torch.tensor(_px.std(0) + 1e-6, dtype=torch.float32).view(1, 128, 1, 1)

    class SubstationCNN(torch.nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.features = torch.nn.Sequential(
                torch.nn.Conv2d(128, 32, 1),
                torch.nn.ReLU(),
                torch.nn.Conv2d(32, 32, 3, padding=1),
                torch.nn.ReLU(),
                torch.nn.Conv2d(32, 32, 3, padding=2, dilation=2),
                torch.nn.ReLU(),
                torch.nn.Conv2d(32, 32, 3, padding=4, dilation=4),
                torch.nn.ReLU(),
            )
            self.head = torch.nn.Linear(32, 1)

        def forward(self, x: torch.Tensor) -> torch.Tensor:
            return self.head(self.features(x).amax(dim=(2, 3))).squeeze(1)

    def to_tensor(c: np.ndarray, s: np.ndarray) -> torch.Tensor:
        """(n, rows, cols, 128) codes and (n, rows, cols) scales to a normalised NCHW tensor."""
        x = torch.from_numpy(c).float() * torch.from_numpy(s).unsqueeze(-1)
        return (x.permute(0, 3, 1, 2) - band_mean) / band_std

    def cnn_scores(model: torch.nn.Module, rows: np.ndarray) -> np.ndarray:
        o = (READ - PATCH) // 2
        out = []
        model.eval()
        with torch.no_grad():
            for b in range(0, len(rows), 256):
                r = rows[b : b + 256]
                x = to_tensor(
                    codes[r, o : o + PATCH, o : o + PATCH], scales[r, o : o + PATCH, o : o + PATCH]
                )
                out.append(torch.sigmoid(model(x)).numpy())
        return np.concatenate(out)

    _t = time.time()
    cnn = SubstationCNN()
    _opt = torch.optim.Adam(cnn.parameters(), lr=1e-3, weight_decay=1e-4)
    _best, _best_state, cnn_log = -1.0, None, []
    for _epoch in range(15):
        cnn.train()
        _order = _rng.permutation(_train)
        for _b in range(0, len(_order), 64):
            _r = _order[_b : _b + 64]
            _oy, _ox = _rng.integers(0, READ - PATCH + 1, 2)
            _x = to_tensor(
                codes[_r, _oy : _oy + PATCH, _ox : _ox + PATCH],
                scales[_r, _oy : _oy + PATCH, _ox : _ox + PATCH],
            )
            _x = torch.rot90(_x, int(_rng.integers(4)), dims=(2, 3))
            if _rng.random() < 0.5:
                _x = torch.flip(_x, dims=(3,))
            _loss = torch.nn.functional.binary_cross_entropy_with_logits(
                cnn(_x), torch.from_numpy(_y[_r])
            )
            _opt.zero_grad()
            _loss.backward()
            _opt.step()
        _auc = roc_auc_score(_y[_val], cnn_scores(cnn, _val))
        cnn_log.append(
            {
                "epoch": _epoch + 1,
                "val_auc": round(float(_auc), 4),
                "seconds": round(time.time() - _t),
            }
        )
        print(cnn_log[-1])
        if _auc > _best:
            _best, _best_state = _auc, {k: v.clone() for k, v in cnn.state_dict().items()}
    assert _best_state is not None
    cnn.load_state_dict(_best_state)
    cnn.eval()
    timings["train_cnn"] = time.time() - _t
    cnn_score = cnn_scores(cnn, np.arange(len(samples)))
    return band_mean, band_std, cnn, cnn_log, cnn_score, to_tensor


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Held-out substations: recall by voltage class

    Each model gets one threshold, set on the validation rows so that 1% of random negative
    patches score above it. That is strict on purpose: a scanner that flagged one 320 m patch
    in 20 would bury a reviewer. Recall is the share of held-out OSM substations whose patch
    scores above the threshold. Precision on this sample (one negative per substation) would
    flatter both models, because real land is almost all negative, so we leave precision to
    the tile scan in section 7.
    """)
    return


@app.cell
def _(OUT_DIR, VOLTAGE_CLASSES, cnn_score, np, osm, pd, probe_score, roc_auc_score, samples):
    scored = samples.assign(probe=probe_score, cnn=cnn_score)
    scored["vclass"] = scored["osm_row"].map(
        lambda r: osm.at[r, "vclass"] if r >= 0 else "negative"
    )
    scored["area_m2"] = scored["osm_row"].map(lambda r: osm.at[r, "area_m2"] if r >= 0 else 0.0)
    _val = scored[(scored["split"] == "val") & (scored["label"] == 0)]
    thresholds = {m: float(np.quantile(_val[m], 0.99)) for m in ("probe", "cnn")}
    _test = scored[scored["split"] == "test"]
    _rows = []
    for _m in ("probe", "cnn"):
        for _region in [*sorted(_test["region"].unique()), "both"]:
            _t = _test if _region == "both" else _test[_test["region"] == _region]
            _neg = _t[_t["label"] == 0]
            _row = {
                "model": _m,
                "region": _region,
                "AUC": round(roc_auc_score(_t["label"], _t[_m]), 3),
                "false-positive rate": round(float((_neg[_m] >= thresholds[_m]).mean()), 3),
            }
            for _v in [*VOLTAGE_CLASSES, "all"]:
                _p = _t[(_t["label"] == 1) & ((_t["vclass"] == _v) | (_v == "all"))]
                _row[f"recall {_v}"] = (
                    round(float((_p[_m] >= thresholds[_m]).mean()), 2) if len(_p) else np.nan
                )
                _row[f"n {_v}"] = len(_p)
            _rows.append(_row)
    recall_table = pd.DataFrame(_rows)
    recall_table.to_csv(OUT_DIR / "heldout_recall.csv", index=False)
    print("Thresholds:", {k: round(v, 3) for k, v in thresholds.items()})
    print(recall_table.to_string(index=False))
    return recall_table, scored, thresholds


@app.cell
def _(OUT_DIR, np, pd, plt, scored, thresholds):
    # Recall against fenced area: does the CNN only see the big yards?
    _bins = [0, 1, 500, 2000, 10000, 50000, np.inf]
    _labels = ["point", "<500", "500-2k", "2k-10k", "10k-50k", "50k+"]
    _p = scored[(scored["split"] == "test") & (scored["label"] == 1)].copy()
    _p["area"] = pd.cut(_p["area_m2"], _bins, labels=_labels, right=False)
    recall_by_area = (
        _p.groupby("area", observed=False)
        .agg(
            n=("cnn", "size"),
            probe=("probe", lambda s: (s >= thresholds["probe"]).mean()),
            cnn=("cnn", lambda s: (s >= thresholds["cnn"]).mean()),
        )
        .round(2)
    )
    recall_by_area.to_csv(OUT_DIR / "heldout_recall_by_area.csv")
    _fig, _ax = plt.subplots(figsize=(6, 3.2))
    recall_by_area[["probe", "cnn"]].plot.bar(ax=_ax, rot=0)
    _ax.set_xlabel("OSM fenced area (m²)")
    _ax.set_ylabel("recall, held-out")
    _ax.set_ylim(0, 1)
    _ax.set_title("Held-out recall by substation size (1% false-positive threshold)")
    _fig.tight_layout()
    _fig.savefig(OUT_DIR / "recall_by_area.png", dpi=150)
    print(recall_by_area.to_string())
    _fig
    return (recall_by_area,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Scanning held-out tiles: precision in practice

    Recall on patches centred on known substations says nothing about how often the models
    fire on ordinary land. So we read whole 0.1° tiles (about 100 km² each) drawn at random
    from the held-out blocks, 24 per state, and scan every 320 m window with the CNN (every
    4 pixels) and every pixel with the probe. Neighbouring windows above the threshold are
    joined into one detection. A detection is **correct** if an OSM substation lies within
    300 m of it, and an OSM substation in the tile is **found** if a detection lies within
    300 m. OSM is incomplete, so precision against it is a floor; section 9 checks a sample
    of the "wrong" detections on aerial photos. Detections outside the two states (a border
    tile reaches into Canada or a neighbouring state, where we have no answer key) are dropped.
    """)
    return


@app.cell
def _(Point, SEED, block_of, np, states, test_blocks, tiles):
    _rng = np.random.default_rng(SEED + 1)
    _keys = np.array(list(tiles.index), dtype=float)
    _cand = []
    for _region, _shape in zip(states["region"], states.to_crs(4326).geometry, strict=True):
        _x0, _y0, _x1, _y1 = _shape.bounds
        _k = _keys[
            (_keys[:, 0] > _x0) & (_keys[:, 0] < _x1) & (_keys[:, 1] > _y0) & (_keys[:, 1] < _y1)
        ]
        _k = _k[np.isin(block_of(_k[:, 0], _k[:, 1]), list(test_blocks))]
        _k = np.array([k for k in _k if _shape.contains(Point(*k))])
        _pick = _k[_rng.choice(len(_k), size=24, replace=False)]
        _cand += [(_region, (round(float(a), 2), round(float(b), 2))) for a, b in _pick]
    scan_tiles = _cand
    print(f"{len(scan_tiles)} held-out tiles to scan")
    return (scan_tiles,)


@app.cell
def _(ThreadPoolExecutor, band_mean, band_std, cnn, np, probe_map, read_rows, tiles, torch):
    def read_tile(key: tuple[float, float]) -> tuple[np.ndarray, np.ndarray]:
        """A whole tile, read in bands of 100 rows in parallel."""
        h = int(tiles.loc[[key]].iloc[0]["height"])
        bands = [(r, min(100, h - r)) for r in range(0, h, 100)]
        with ThreadPoolExecutor(8) as ex:
            parts = list(ex.map(lambda b: read_rows(key, *b), bands))
        s = np.concatenate([p[1] for p in parts])
        return np.concatenate([p[0] for p in parts]), np.where(np.isfinite(s), s, 0).astype(
            np.float32
        )

    STRIDE = 4

    def cnn_map(c: np.ndarray, s: np.ndarray) -> np.ndarray:
        """CNN score of every 32 x 32 window at a 4-pixel stride, window (i, j) at (4i, 4j)."""
        with torch.no_grad():
            x = torch.from_numpy(c).float() * torch.from_numpy(s).unsqueeze(-1)
            x = (x.permute(2, 0, 1).unsqueeze(0) - band_mean) / band_std
            f = torch.nn.functional.max_pool2d(cnn.features(x), 32, stride=STRIDE)
            return torch.sigmoid(cnn.head(f[0].permute(1, 2, 0))).squeeze(-1).numpy()

    return STRIDE, cnn_map, probe_map, read_tile


@app.cell
def _(DATA_DIR, YEAR, cnn_map, np, probe_map, read_tile, scan_tiles, tiles, time, timings):
    _t = time.time()
    scan_maps = {}
    for _region, _key in scan_tiles:
        # The raw tile is cached, not the scores, so a rerun always scores with this run's models.
        _cache = DATA_DIR / "tiles" / f"{YEAR}_{_key[0]}_{_key[1]}.npz"
        if not _cache.exists():
            _cache.parent.mkdir(exist_ok=True)
            _c, _s = read_tile(_key)
            np.savez(_cache, codes=_c, scales=_s)
        _z = np.load(_cache)
        _c, _s = _z["codes"], _z["scales"]
        scan_maps[_key] = {
            "region": _region,
            "cnn": cnn_map(_c, _s),
            "probe": probe_map(_c, _s),
            "transform": tiles.loc[[_key]].iloc[0]["transform"],
        }
    timings["scan"] = time.time() - _t
    print(f"Scanned {len(scan_maps)} tiles in {timings['scan']:.0f} s")
    return (scan_maps,)


@app.cell
def _(ALBERS, STRIDE, gpd, ndimage, np, osm, pd, scan_maps, states):
    def detections(threshold: dict[str, float]) -> gpd.GeoDataFrame:
        """Join above-threshold neighbours into detections, one point at each one's peak."""
        rows = []
        for key, m in scan_maps.items():
            c, a, _b, f, _d, e = m["transform"]
            for model, step, off in (("cnn", STRIDE, 16), ("probe", 1, 0)):
                score = m[model]
                lab, n = ndimage.label(score >= threshold[model], structure=np.ones((3, 3)))
                if n == 0:
                    continue
                peaks = ndimage.maximum_position(score, lab, range(1, n + 1))
                for i, j in peaks:
                    rows.append(
                        {
                            "model": model,
                            "tile": key,
                            "region": m["region"],
                            "score": float(score[i, j]),
                            "lon": c + (j * step + off + 0.5) * a,
                            "lat": f + (i * step + off + 0.5) * e,
                        }
                    )
        d = pd.DataFrame(rows, columns=["model", "tile", "region", "score", "lon", "lat"])
        g = gpd.GeoDataFrame(d, geometry=gpd.points_from_xy(d["lon"], d["lat"]), crs=4326).to_crs(
            ALBERS
        )
        # A tile on a border reaches into Canada or a neighbouring state, where we have no OSM.
        return g[g.within(states.union_all())].reset_index(drop=True)

    # OSM substations centred in a scanned tile, more than 160 m (half a window) from its edge.
    _c = osm.geometry.representative_point().to_crs(4326)
    _in = np.zeros(len(osm), bool)
    for _key in scan_maps:
        _in |= (np.abs(_c.x - _key[0]) < 0.05 - 0.0018) & (np.abs(_c.y - _key[1]) < 0.05 - 0.0015)
    scan_osm = osm[_in]
    print(f"OSM substations inside the scanned tiles: {len(scan_osm)}")
    print(scan_osm.groupby(["region", "vclass"]).size().to_string())
    return detections, scan_osm


@app.cell
def _(OUT_DIR, VOLTAGE_CLASSES, detections, np, osm, pd, scan_osm, thresholds):
    MATCH_M = 300

    def score_scan(threshold: dict[str, float]) -> tuple[pd.DataFrame, object]:
        det = detections(threshold)
        det["d_osm"] = det.geometry.apply(lambda g: osm.distance(g).min() if len(osm) else np.inf)
        rows = []
        for model in ("probe", "cnn"):
            d = det[det["model"] == model]
            row = {
                "model": model,
                "threshold": round(threshold[model], 3),
                "detections": len(d),
                "correct": int((d["d_osm"] <= MATCH_M).sum()),
            }
            row["precision"] = round(row["correct"] / max(1, len(d)), 3)
            near = d.geometry.buffer(MATCH_M).union_all() if len(d) else None
            found = (
                scan_osm.geometry.intersects(near)
                if near is not None
                else pd.Series(False, index=scan_osm.index)
            )
            for v in [*VOLTAGE_CLASSES, "all"]:
                sel = (scan_osm["vclass"] == v) | (v == "all")
                row[f"recall {v}"] = round(float(found[sel].mean()), 2) if sel.any() else np.nan
                row[f"n {v}"] = int(sel.sum())
            rows.append(row)
        return pd.DataFrame(rows), det

    scan_table, scan_det = score_scan(thresholds)
    # The same scan at stricter CNN cutoffs, to show the trade-off a reviewer would choose from.
    _strict = [
        score_scan({"probe": thresholds["probe"], "cnn": t})[0].query("model == 'cnn'")
        for t in (0.9, 0.97, 0.99)
    ]
    scan_table = pd.concat([scan_table, *_strict], ignore_index=True)
    scan_table.to_csv(OUT_DIR / "scan_precision_recall.csv", index=False)
    print(scan_table.to_string(index=False))
    return MATCH_M, scan_det, scan_table


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. Where HIFLD Next lines end with no mapped substation

    HIFLD Next's Transmission Lines layer is the public grid map that remains. We take both
    ends of every line in the two states, the same way as [`hifld-grid-gaps/`](../hifld-grid-gaps/),
    and keep the ends more than 1 km from any OSM substation. That spike found most such ends
    nationally are taps, where the line branches off another line, so we also record whether
    an end touches another line within 25 m. Around each end we read a 640 m square and take
    the CNN's highest window score inside it.
    """)
    return


@app.cell
def _(ALBERS, DATA_DIR, downloaded, fetch, gpd, np, osm, states):
    _path = DATA_DIR / "hifld-next-transmission-lines-v1.0.0.parquet"
    downloaded["hifld_lines"] = fetch(
        "https://storage.googleapis.com/hifld-next-datasets-prod/hifld/transmission-lines-1/"
        "transmission-lines-1/v1.0.0/geoparquet/transmission-lines-1.parquet",
        _path,
    )
    _lines = gpd.read_parquet(_path).to_crs(ALBERS)
    _lines = _lines[_lines.intersects(states.union_all())].reset_index(drop=True)
    import shapely

    _first = shapely.get_point(shapely.get_geometry(_lines.geometry.values, 0), 0)
    _last = shapely.get_point(shapely.get_geometry(_lines.geometry.values, -1), -1)
    ends = gpd.GeoDataFrame(
        {
            "line": np.r_[_lines.index, _lines.index],
            "voltage": np.r_[_lines["VOLTAGE"], _lines["VOLTAGE"]],
        },
        geometry=np.r_[_first, _last],
        crs=ALBERS,
    )
    ends = (
        gpd.sjoin(ends, states, predicate="within")
        .drop(columns="index_right")
        .reset_index(drop=True)
    )
    ends["m_to_osm"] = (
        gpd.sjoin_nearest(ends[["geometry"]], osm[["geometry"]], distance_col="m")
        .groupby(level=0)["m"]
        .min()
    )
    _touch = gpd.sjoin(
        gpd.GeoDataFrame(ends[["line"]], geometry=ends.buffer(25), crs=ALBERS),
        _lines[["geometry"]],
        predicate="intersects",
    )
    ends["tap"] = ends.index.isin(_touch[_touch["line"] != _touch["index_right"]].index)
    far_ends = ends[ends["m_to_osm"] > 1000].reset_index(drop=True)
    # Two lines meeting at one far point give two ends; score each place once.
    far_ends = far_ends.loc[~far_ends.geometry.normalize().to_wkb().duplicated()].reset_index(
        drop=True
    )
    print(
        f"HIFLD Next lines in the two states: {len(_lines):,}; ends: {len(ends):,}; "
        f"more than 1 km from OSM: {len(far_ends):,} places "
        f"({int(far_ends['tap'].sum()):,} touch another line)"
    )
    lines = _lines
    return ends, far_ends, lines


@app.cell
def _(Affine, DATA_DIR, STRIDE, YEAR, cnn_map, far_ends, np, read_patches, time, timings):
    _t = time.time()
    # The raw 64 x 64 windows are cached, not the scores, as for the scan tiles.
    _cache = DATA_DIR / f"line_end_windows_{YEAR}.npz"
    if not _cache.exists():
        _ll = far_ends.to_crs(4326)
        _c, _s, _tf = read_patches(list(zip(_ll.geometry.x, _ll.geometry.y, strict=True)), size=64)
        np.savez(_cache, codes=_c, scales=_s, transforms=np.array([a[:6] for a in _tf]))
    _z = np.load(_cache)
    _out = []
    for _i in range(len(_z["codes"])):
        _sc = _z["scales"][_i]
        _m = cnn_map(_z["codes"][_i], np.where(np.isfinite(_sc), _sc, 0).astype(np.float32))
        _r, _q = np.unravel_index(int(_m.argmax()), _m.shape)
        _a = Affine(*_z["transforms"][_i])
        _out.append(
            (_m.max(), _a.c + (_q * STRIDE + 16.5) * _a.a, _a.f + (_r * STRIDE + 16.5) * _a.e)
        )
    _best = np.array(_out)
    far_ends["cnn"], far_ends["peak_lon"], far_ends["peak_lat"] = (
        _best[:, 0],
        _best[:, 1],
        _best[:, 2],
    )
    timings["line_ends"] = time.time() - _t
    return


@app.cell
def _(OUT_DIR, far_ends, np, pd, thresholds):
    far_ends["flagged"] = far_ends["cnn"] >= thresholds["cnn"]
    line_end_table = (
        far_ends.groupby(["region", "tap"])
        .agg(places=("cnn", "size"), flagged=("flagged", "sum"), median_score=("cnn", "median"))
        .reset_index()
    )
    _all = pd.DataFrame(
        [
            {
                "region": "both",
                "tap": "any",
                "places": len(far_ends),
                "flagged": int(far_ends["flagged"].sum()),
                "median_score": far_ends["cnn"].median(),
            }
        ]
    )
    line_end_table = pd.concat([line_end_table, _all], ignore_index=True).round(3)
    line_end_table.to_csv(OUT_DIR / "line_end_flags.csv", index=False)
    print(line_end_table.to_string(index=False))
    assert np.isfinite(far_ends["cnn"]).all()
    return (line_end_table,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 9. Hand check on aerial photos

    Two sets, each drawn on NAIP aerial photos (USDA, public domain, through Microsoft's
    Planetary Computer) 800 m across, centred on where the CNN scored highest:

    - **Line ends:** the 20 highest-scoring places from section 8.
    - **Scan "false positives":** 20 CNN detections from section 7 with no OSM substation
      within 300 m, drawn at random. If many are real substations, OSM's gaps make the
      precision in section 7 look worse than it is.

    The verdicts are in `hand_check.csv`, keyed by a short hash of each place, not its
    location: the issue asks us not to publish a list of unmapped substation sites. The
    chips stay in `data/chips/` and are not committed. Verdicts: **substation** (a fenced
    yard of transformers or switchgear), **plant** (a power plant or its switchyard),
    **other** (something else: say what), **unclear**.
    """)
    return


@app.cell
def _(ALBERS, DATA_DIR, Path, gpd, httpx, lines, np, osm, plt):
    import hashlib

    import rasterio
    from rasterio.merge import merge
    from rasterio.vrt import WarpedVRT
    from shapely.geometry import box as shape_box
    from shapely.geometry import shape
    from shapely.ops import unary_union

    CHIP_DIR = DATA_DIR / "chips"
    CHIP_DIR.mkdir(exist_ok=True)
    _pc = "https://planetarycomputer.microsoft.com/api"

    def place_id(lon: float, lat: float) -> str:
        return hashlib.sha1(f"{lon:.4f},{lat:.4f}".encode()).hexdigest()[:10]

    def draw_chip(
        path: Path, lon: float, lat: float, mark: tuple[float, float] | None, title: str
    ) -> None:
        """An 800 m NAIP chip around (lon, lat) with HIFLD lines, OSM substations and marks."""
        if path.exists():
            return
        c = gpd.GeoSeries.from_xy([lon], [lat], crs=4326).to_crs(ALBERS).iloc[0]
        ext = (c.x - 400, c.y - 400, c.x + 400, c.y + 400)
        bb = gpd.GeoSeries.from_xy([ext[0], ext[2]], [ext[1], ext[3]], crs=ALBERS).to_crs(4326)
        token = httpx.get(f"{_pc}/sas/v1/token/naip", timeout=60).raise_for_status().json()["token"]
        items = (
            httpx.post(
                f"{_pc}/stac/v1/search",
                timeout=60,
                json={
                    "collections": ["naip"],
                    "limit": 100,
                    "bbox": [bb.x.min(), bb.y.min(), bb.x.max(), bb.y.max()],
                },
            )
            .raise_for_status()
            .json()["features"]
        )
        need = shape_box(bb.x.min(), bb.y.min(), bb.x.max(), bb.y.max())
        years = sorted({f["properties"]["naip:year"] for f in items}, reverse=True)
        assert items, f"no NAIP image near {title}"
        # The newest year covering most of the chip; a year can graze its edge.
        cover = {
            y: unary_union(
                [shape(f["geometry"]) for f in items if f["properties"]["naip:year"] == y]
            )
            .intersection(need)
            .area
            / need.area
            for y in years
        }
        year = max(years, key=lambda y: (round(cover[y], 2), y))
        items = [f for f in items if f["properties"]["naip:year"] == year]
        with rasterio.Env(GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR"):
            srcs = [
                rasterio.open(f"/vsicurl/{f['assets']['image']['href']}?{token}") for f in items
            ]
            vrts = [WarpedVRT(src, crs=ALBERS) for src in srcs]
            img, _ = merge(vrts, bounds=ext, res=1.0, indexes=[1, 2, 3])
            for d in vrts + srcs:
                d.close()
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.imshow(np.moveaxis(img, 0, -1), extent=(ext[0], ext[2], ext[1], ext[3]))
        near_lines = lines.cx[ext[0] : ext[2], ext[1] : ext[3]]
        near_osm = osm.cx[ext[0] : ext[2], ext[1] : ext[3]]
        if len(near_lines):
            near_lines.plot(ax=ax, color="yellow", lw=1)
        if len(near_osm):
            near_osm.boundary.plot(ax=ax, color="cyan", lw=1.5)
        ax.add_patch(plt.Rectangle((c.x - 160, c.y - 160), 320, 320, fill=False, ec="red", lw=1.5))
        if mark is not None:
            m = gpd.GeoSeries.from_xy([mark[0]], [mark[1]], crs=4326).to_crs(ALBERS).iloc[0]
            ax.scatter([m.x], [m.y], s=60, c="magenta", marker="x")
        ax.set_xlim(ext[0], ext[2])
        ax.set_ylim(ext[1], ext[3])
        ax.set_axis_off()
        ax.set_title(f"{title} (NAIP {year}, 800 m)", fontsize=8)
        fig.tight_layout()
        fig.savefig(path, dpi=100, pil_kwargs={"quality": 85})
        plt.close(fig)

    return CHIP_DIR, draw_chip, place_id


@app.cell
def _(ALBERS, CHIP_DIR, MATCH_M, SEED, draw_chip, far_ends, gpd, pd, place_id, scan_det):
    # The 20 best peaks at least 500 m apart: nearby ends often share one peak.
    _peaks = gpd.GeoSeries.from_xy(far_ends["peak_lon"], far_ends["peak_lat"], crs=4326).to_crs(
        ALBERS
    )
    _keep: list[int] = []
    for _i in far_ends["cnn"].sort_values(ascending=False).index:
        if all(_peaks[_i].distance(_peaks[_j]) >= 500 for _j in _keep):
            _keep.append(_i)
        if len(_keep) == 20:
            break
    _top = far_ends.loc[_keep].copy()
    _top["set"] = "line end"
    _ll = _top.to_crs(4326).geometry
    _top["mark"] = list(zip(_ll.x, _ll.y, strict=True))
    _top["lon"], _top["lat"] = _top["peak_lon"], _top["peak_lat"]
    _fp = scan_det[(scan_det["model"] == "cnn") & (scan_det["d_osm"] > MATCH_M)]
    _fp = _fp.sample(n=min(20, len(_fp)), random_state=SEED).copy()
    _fp["set"], _fp["mark"], _fp["cnn"], _fp["tap"] = "scan detection", None, _fp["score"], pd.NA
    to_check = pd.concat([_top, _fp])[
        ["set", "region", "tap", "cnn", "lon", "lat", "mark"]
    ].reset_index(drop=True)
    to_check["id"] = [place_id(a, b) for a, b in zip(to_check["lon"], to_check["lat"], strict=True)]
    for _r in to_check.itertuples():
        draw_chip(
            CHIP_DIR / f"{_r.id}.jpg",
            _r.lon,
            _r.lat,
            _r.mark,
            f"{_r.id} {_r.set} {_r.region} CNN {_r.cnn:.3f}",
        )
    to_check.drop(columns=["lon", "lat", "mark"]).to_csv(CHIP_DIR / "to_check.csv", index=False)
    print(f"{len(to_check)} chips in {CHIP_DIR}")
    return (to_check,)


@app.cell
def _(OUT_DIR, Path, pd, to_check):
    _hc_path = Path("hand_check.csv")
    _hc = (
        pd.read_csv(_hc_path)
        if _hc_path.exists()
        else pd.DataFrame(columns=["id", "verdict", "note"])
    )
    hand = to_check.merge(_hc[["id", "verdict", "note"]], on="id", how="left")
    hand["verdict"] = hand["verdict"].fillna("not checked")
    hand_table = (
        hand.pivot_table(index="verdict", columns="set", values="id", aggfunc="count")
        .fillna(0)
        .astype(int)
    )
    hand_table.to_csv(OUT_DIR / "hand_check_tally.csv")
    print(hand_table.to_string())
    return hand, hand_table


@app.cell
def _(mo):
    mo.md(r"""
    ## 10. Time, downloads and cost

    Everything is free and anonymous: no account, key or paid service. The cost is bandwidth
    and CPU time on whatever machine runs this.
    """)
    return


@app.cell
def _(
    DATA_DIR,
    OUT_DIR,
    YEAR,
    cnn_log,
    downloaded,
    hand_table,
    json,
    line_end_table,
    osm_counts,
    overture_release,
    range_bytes,
    READ,
    far_ends,
    samples,
    scan_tiles,
    tile_key,
    tiles,
    recall_by_area,
    recall_table,
    run_start,
    scan_table,
    thresholds,
    time,
    timings,
):
    timings["total"] = time.time() - run_start
    _disk = sum(f.stat().st_size for f in DATA_DIR.rglob("*") if f.is_file())

    # What a run from an empty data/ fetches from TESSERA: every read takes whole rows of 128
    # code bytes and 4 scale bytes a pixel (40 rows a patch, 64 a line end, all of a scan tile).
    def _w(lo: float, la: float) -> int:
        return int(tiles.loc[[tile_key(lo, la)]].iloc[0]["width"])

    _ends = far_ends.to_crs(4326).geometry
    _fresh = 132 * (
        sum(READ * _w(lo, la) for lo, la in zip(samples["lon"], samples["lat"], strict=True))
        + sum(64 * _w(p.x, p.y) for p in _ends)
        + sum(
            int(tiles.loc[[k]].iloc[0]["height"]) * int(tiles.loc[[k]].iloc[0]["width"])
            for _r, k in scan_tiles
        )
    )
    cost = {
        "tessera_GB_fetched_from_empty_data_dir": round(_fresh / 1e9, 1),
        "tessera_range_read_GB_this_run": round(range_bytes[0] / 1e9, 2),
        "other_downloads_MB_this_run": round(sum(downloaded.values()) / 1e6, 1),
        "data_dir_GB": round(_disk / 1e9, 2),
        "seconds": {k: round(v) for k, v in timings.items()},
        "dollars": 0,
    }
    summary = {
        "tessera": f"v1, {YEAR}, Source Cooperative",
        "overture_release": overture_release,
        "osm_substations": osm_counts.reset_index().to_dict("records"),
        "thresholds": thresholds,
        "cnn_training": cnn_log,
        "heldout_recall": recall_table.to_dict("records"),
        "heldout_recall_by_area": recall_by_area.reset_index().astype(str).to_dict("records"),
        "scan": scan_table.to_dict("records"),
        "line_ends": line_end_table.astype(str).to_dict("records"),
        "hand_check": hand_table.reset_index().to_dict("records"),
        "cost": cost,
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(cost, indent=2))
    return


@app.cell
def _(hand, line_end_table, mo, recall_table, scan_table):
    _cnn = recall_table[(recall_table["model"] == "cnn") & (recall_table["region"] == "both")].iloc[
        0
    ]
    _probe = recall_table[
        (recall_table["model"] == "probe") & (recall_table["region"] == "both")
    ].iloc[0]
    _scan = scan_table[scan_table["model"] == "cnn"].iloc[0]
    _le = hand[hand["set"] == "line end"]["verdict"].value_counts()
    _fp = hand[hand["set"] == "scan detection"]["verdict"].value_counts()
    _flagged = int(line_end_table.iloc[-1]["flagged"])
    _places = int(line_end_table.iloc[-1]["places"])
    mo.md(f"""
    ## 11. What this shows, and what didn't work

    **The embeddings know what a substation looks like, but not well enough to search for
    new ones.** On patches centred on held-out OSM substations the CNN finds
    {_cnn["recall all"]:.0%} of them ({_cnn["recall 230 kV+"]:.0%} of 230 kV+ and
    {_cnn["recall 100-229 kV"]:.0%} of 100–229 kV, {_cnn["recall under 100 kV"]:.0%} under
    100 kV) while passing about 1 in 100 random patches. The single-pixel probe finds
    {_probe["recall all"]:.0%}: shape and context matter more than the colour of the gravel.

    **Scanning land is where it breaks.** Over 48 held-out tiles only
    {_scan["precision"]:.0%} of the CNN's {int(_scan["detections"])} detections are near an
    OSM substation, and of 20 "wrong" ones checked on photos, {_fp.get("substation", 0)} were
    substations OSM had missed. They were houses, farms, quarries, schools and factories:
    the CNN learned "developed land with hard surfaces", because random negatives are mostly
    forest and fields. One 1-in-100 false alarm per 320 m patch is about ten per 100 km².

    **Line ends.** Of {_places} places where a HIFLD Next line ends more than 1 km from an
    OSM substation, the CNN flags {_flagged}. Of the 20 highest-scoring places,
    {_le.get("substation", 0)} was an unmapped switchyard, {_le.get("plant", 0)} were hydro
    dams, {_le.get("unclear", 0)} unclear and {_le.get("other", 0)} something else (mostly
    commercial and industrial land). Most far ends are taps on another line, as
    `hifld-grid-gaps/` found, so there is usually nothing to find.

    **What didn't work, or wasn't tried:**

    - Precision. Random negatives are too easy; the model needs hard negatives (industrial
      parks, quarries, parking lots, farmsteads) before a scan is worth a reviewer's time.
    - Per-voltage precision. A detection has no voltage, so precision is overall only;
      recall is per class.
    - Small samples where it matters: the held-out set has only {int(_cnn["n 230 kV+"])}
      substations of 230 kV+, and the scanned tiles hold {int(_scan["n all"])} OSM
      substations, {int(_scan["n 230 kV+"])} of them 230 kV+.
    - Column-window reads. A window needs one HTTP request per row, about 200 requests a
      second through our connection, so we read whole rows instead and fetch 20 to 30 times
      the bytes we keep.
    - TESSERA v2: its beta store on Source Cooperative covers only part of both states, so
      this uses v1 (2024).
    """)
    return


if __name__ == "__main__":
    app.run()

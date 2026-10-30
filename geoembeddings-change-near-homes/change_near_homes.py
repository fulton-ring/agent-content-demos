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
    from rasterio.features import rasterize, shapes
    from rasterio.io import DatasetReader
    from rasterio.transform import Affine
    from scipy import ndimage
    from shapely.geometry import shape

    return (
        Affine,
        Callable,
        DatasetReader,
        Path,
        ThreadPoolExecutor,
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
        shape,
        shapes,
        time,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Can yearly satellite embeddings show new industry going in next to homes?

    Google DeepMind's [AlphaEarth Foundations](https://deepmind.google/discover/blog/alphaearth-foundations-helps-map-our-planet-in-unprecedented-detail/)
    model publishes a 64-number, unit-length vector for every 10 m pixel on land, every
    year since 2017. Google's own documentation suggests comparing two years by the dot
    product of their vectors: 1 means the place looks the same, lower means it changed.
    EJScreen is a frozen snapshot, but these vectors keep coming every year, so the question
    is whether the change between years can flag **new industrial land near housing**
    (plants, tank farms, terminals, large warehouses), and do it earlier and more completely
    than the facility registries record it.

    We expect big changes to catch new construction, and the hard part to be telling
    industry apart from new subdivisions, cleared land and everything else that changes.
    The test is on Gulf Coast counties with known recent industrial growth: the Houston
    Ship Channel counties, Port Arthur and Beaumont, Lake Charles and Cameron Parish, and
    the river parishes between Baton Rouge and New Orleans.

    1. **Change map.** How far each pixel's embedding moved between 2018 and 2024, and the
       large-change areas within 3 km of residential block groups.
    2. **Registries.** What share of the facilities that first appear in EPA's Toxics
       Release Inventory or Risk Management Program records in 2019–2024 sit on a change
       area, and how many new industrial sites the change map finds that aren't registered.
    3. **Hand check.** What a seeded random sample of those areas actually is, from NAIP
       aerial photos before and after and a late-2024 Sentinel-2 image.
    4. **Sorting.** Whether ranking the change areas by how much their 2024 embedding looks
       like existing heavy industry separates industry from other change.
    """)
    return


@app.cell
def _(Path, os, time):
    t_start = time.perf_counter()
    HERE = Path(__file__).parent
    DATA_DIR = Path(os.environ.get("GEO_DATA_DIR", HERE / "data"))
    OUT_DIR = Path(os.environ.get("GEO_OUT_DIR", HERE / "outputs"))
    for _d in (DATA_DIR / "aef", DATA_DIR / "tri", OUT_DIR / "chips"):
        _d.mkdir(parents=True, exist_ok=True)

    COUNTIES = {
        "48201": "Harris, TX",
        "48071": "Chambers, TX",
        "48167": "Galveston, TX",
        "48245": "Jefferson, TX",
        "22019": "Calcasieu, LA",
        "22023": "Cameron, LA",
        "22005": "Ascension, LA",
        "22047": "Iberville, LA",
        "22093": "St. James, LA",
        "22095": "St. John the Baptist, LA",
        "22089": "St. Charles, LA",
    }
    # 2017 was regenerated with extra Sentinel-1 data in version 1.1, so we start a year later.
    BEFORE, AFTER = 2018, 2024
    # Every county here is in UTM zone 15N, so the tiles share one 40 m grid.
    UTM = "EPSG:32615"
    RES = 40
    # Large change: cosine similarity between the two years below this. See the histogram.
    CHANGE_BELOW = 0.6
    MIN_PIXELS = 25  # 25 pixels of 40 m = 4 ha, about one large warehouse
    NEAR_HOMES_M = 3000
    RESIDENTIAL_DENSITY = 200  # people per km², see "Residential block groups"
    MATCH_M = 300  # a facility "sits on" a change area if it is this close to one
    AEF_BASE = "https://data.source.coop/tge-labs/aef/v1/annual"
    TRI_URL = "https://data.epa.gov/efservice/downloads/tri/mv_tri_basic_download/{year}_{st}/csv"
    TRI_YEARS = range(2010, 2025)
    HIFLD = "https://storage.googleapis.com/hifld-next-datasets-prod/hifld"
    RMP_LAYER = "epa-emergency-response-rmp-facilities"
    HEAVY_LAYERS = {
        "refinery": "petroleum-refineries",
        "terminal": "petroleum-product-terminals",
        "tsdf": "epa-rcra-treatment-storage-and-disposal-facilities",
    }
    EJ_DIR = Path(os.environ.get("EJ_OUT_DIR", DATA_DIR / "ej" / "out"))
    HAND_CHECK = HERE / "hand_check.csv"
    GDAL_ENV = {
        "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
        "GDAL_HTTP_MAX_RETRY": "5",
        "GDAL_HTTP_RETRY_DELAY": "2",
        "CPL_VSIL_CURL_CHUNK_SIZE": "1048576",
    }
    return (
        AEF_BASE,
        AFTER,
        BEFORE,
        CHANGE_BELOW,
        COUNTIES,
        DATA_DIR,
        EJ_DIR,
        GDAL_ENV,
        HAND_CHECK,
        HEAVY_LAYERS,
        HIFLD,
        MATCH_M,
        MIN_PIXELS,
        NEAR_HOMES_M,
        OUT_DIR,
        RES,
        RESIDENTIAL_DENSITY,
        RMP_LAYER,
        TRI_URL,
        TRI_YEARS,
        UTM,
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
            href = url if attempt == 0 else f"{url}{'&' if '?' in url else '?'}retry={attempt}"
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
        for attempt in range(4):
            try:
                with httpx.stream("GET", url, follow_redirects=True, timeout=300) as response:
                    response.raise_for_status()
                    with tmp.open("wb") as f:
                        for chunk in response.iter_bytes(1 << 20):
                            f.write(chunk)
                break
            except httpx.TransportError:
                if attempt == 3:
                    raise
                time.sleep(5 * 2**attempt)
        tmp.rename(path)
        return path

    def rx_bytes() -> int:
        """Bytes received from outside the machine, to measure what each step downloads."""
        lines = Path("/proc/net/dev").read_text().splitlines()[2:]
        rows = [line.split(":") for line in lines]
        return sum(int(stats.split()[0]) for name, stats in rows if name.strip() != "lo")

    return fetch, read_remote, rx_bytes


@app.cell
def _(mo):
    mo.md(r"""
    ## Residential block groups

    "Near homes" needs a definition. We use EPA's EJScreen 2024 block groups (ACS
    2018–2022 population, rebuilt into GeoParquet by `ej-datasets-hifld-next/`) and call a
    block group **residential** if it has at least 200 people per km². That keeps towns and
    suburbs and drops block groups that are mostly marsh, cane fields or plant property,
    while keeping small river towns such as Convent and Reserve. A change area is near
    homes if any of its pixels is within 3 km of a residential block group.
    """)
    return


@app.cell
def _(COUNTIES, EJ_DIR, RESIDENTIAL_DENSITY, UTM, gpd, pd):
    bg = gpd.read_parquet(
        EJ_DIR / "epa-ejscreen-2024-block-groups.parquet",
        columns=["geoid", "cnty_name", "st_abbrev", "acstotpop", "exceed_count_80", "geometry"],
    )
    bg = bg[bg["geoid"].str[:5].isin(list(COUNTIES)) & bg.geometry.notna()].to_crs(UTM)
    bg = bg.sort_values("geoid").reset_index(drop=True)
    bg["county"] = bg["geoid"].str[:5].map(COUNTIES)
    bg["density"] = bg["acstotpop"] / (bg.area / 1e6)
    bg["residential"] = bg["density"] >= RESIDENTIAL_DENSITY
    bg["flag_ejscreen"] = bg["exceed_count_80"].fillna(0) > 0
    study_area = bg.dissolve("county")[["geometry"]]
    pd.DataFrame(
        {
            "block groups": bg.groupby("county").size(),
            "residential": bg.groupby("county")["residential"].sum(),
            "people": bg.groupby("county")["acstotpop"].sum(),
            "share of people in residential": bg[bg["residential"]]
            .groupby("county")["acstotpop"]
            .sum()
            / bg.groupby("county")["acstotpop"].sum(),
            "km²": (study_area.area / 1e6).round(),
        }
    ).round(3)
    return bg, study_area


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 1: the change map

    The embeddings come from the [Source Cooperative copy](https://source.coop/tge-labs/aef)
    of AlphaEarth's annual Satellite Embedding dataset (CC-BY 4.0, no account; "The
    AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google
    DeepMind"). Each file is an 8192 × 8192 tile of 10 m pixels. Its overviews hold the
    normalised mean of the 10 m vectors beneath them, so we read the **40 m overview**
    (2048 × 2048, about 190 MB a tile-year) instead of the 3.2 GB full tile. A new plant,
    tank farm or warehouse covers dozens of 40 m pixels. Tiles of the same place line up
    exactly from year to year.

    For each pixel, the change score is the cosine similarity between its 2018 and 2024
    vectors (the overview vectors are unit length to within 0.5%, so this is Google's dot
    product). The files are stored bottom-up, so rows are flipped, and values are int8,
    dequantised as `(v / 127.5)² · sign(v)` with -128 as no-data.

    We also keep each changed pixel's 2024 vector, and the 2024 vector under each existing
    refinery, petroleum terminal, hazardous-waste facility and RMP chemical facility, for
    step 4.
    """)
    return


@app.cell
def _(
    AEF_BASE,
    AFTER,
    BEFORE,
    CHANGE_BELOW,
    DATA_DIR,
    HEAVY_LAYERS,
    HIFLD,
    RMP_LAYER,
    UTM,
    fetch,
    gpd,
    pd,
    study_area,
):
    _index = gpd.read_parquet(fetch(f"{AEF_BASE}/aef_index.parquet", "aef_index.parquet"))
    _lonlat = study_area.to_crs("EPSG:4326").total_bounds
    _index = _index[
        (_index["wgs84_east"] > _lonlat[0])
        & (_index["wgs84_west"] < _lonlat[2])
        & (_index["wgs84_north"] > _lonlat[1])
        & (_index["wgs84_south"] < _lonlat[3])
    ]
    _index = _index.set_geometry("geom").to_crs(UTM)
    _index = _index[_index.intersects(study_area.union_all()) & (_index["utm_zone"] == "15N")]
    tile_pairs = (
        _index[_index["year"] == BEFORE][["utm_west", "utm_north", "path"]]
        .merge(
            _index[_index["year"] == AFTER][["utm_west", "utm_north", "path"]],
            on=["utm_west", "utm_north"],
            suffixes=("_before", "_after"),
        )
        .sort_values(["utm_north", "utm_west"], ascending=[False, True])
        .reset_index(drop=True)
    )
    assert len(tile_pairs) == (_index["year"] == AFTER).sum(), "a tile is missing a year"

    # Existing heavy industry, as the reference for step 4: refineries, petroleum terminals
    # and hazardous-waste TSDFs from HIFLD Next, plus RMP facilities registered before 2018.
    def hifld(layer: str) -> gpd.GeoDataFrame:
        url = f"{HIFLD}/{layer}/{layer}/v1.0.0/geoparquet/{layer}.parquet"
        frame = gpd.read_parquet(fetch(url, f"{layer}.parquet")).to_crs(UTM)
        frame = frame[frame.geometry.notna() & ~frame.geometry.is_empty]
        frame = frame.set_geometry(frame.geometry.centroid)
        return frame[frame.within(study_area.union_all())]

    rmp = hifld(RMP_LAYER)
    rmp["first_year"] = pd.to_datetime(rmp["CREATE_DATE"], errors="coerce", utc=True).dt.year
    _ref = [hifld(layer)[["geometry"]].assign(kind=k) for k, layer in HEAVY_LAYERS.items()]
    _ref.append(rmp.loc[rmp["first_year"] < BEFORE, ["geometry"]].assign(kind="rmp"))
    heavy_ref = gpd.GeoDataFrame(pd.concat(_ref, ignore_index=True), crs=UTM)
    (DATA_DIR / "aef" / f"below-{CHANGE_BELOW}").mkdir(exist_ok=True)
    {
        "tile pairs": len(tile_pairs),
        "heavy-industry reference sites": heavy_ref["kind"].value_counts(),
    }
    return heavy_ref, rmp, tile_pairs


@app.cell
def _(
    AEF_BASE,
    AFTER,
    CHANGE_BELOW,
    DATA_DIR,
    RES,
    ThreadPoolExecutor,
    heavy_ref,
    np,
    read_remote,
    rx_bytes,
    tile_pairs,
    time,
):
    def dequantise(raw: np.ndarray) -> np.ndarray:
        values = raw.astype(np.float32) / 127.5
        return values * np.abs(values)

    def read_40m(path: str) -> np.ndarray:
        url = AEF_BASE + path.split("/v1/annual", 1)[1]
        raw, transform = read_remote(url, lambda r: (r.read(), r.transform), overview=1)
        assert transform.e > 0 and transform.a == RES, "expected a bottom-up 40 m overview"
        return raw[:, ::-1, :]

    def tile_change(pair: dict) -> dict:
        """Cosine similarity between the two years for one tile, and the 2024 vectors kept."""
        cache = (
            DATA_DIR / "aef" / f"below-{CHANGE_BELOW}" / f"{pair['utm_west']:.0f}-"
            f"{pair['utm_north']:.0f}.npz"
        )
        if cache.exists():
            return dict(np.load(cache))
        before, after = read_40m(pair["path_before"]), read_40m(pair["path_after"])
        cosine = np.empty(after.shape[1:], np.float32)
        for r in range(0, after.shape[1], 256):  # in strips, to bound memory
            b, a = dequantise(before[:, r : r + 256]), dequantise(after[:, r : r + 256])
            norms = np.linalg.norm(a, axis=0) * np.linalg.norm(b, axis=0)
            cosine[r : r + 256] = np.einsum("bij,bij->ij", a, b) / norms
        cosine[(before[0] == -128) | (after[0] == -128)] = np.nan
        changed = np.flatnonzero(cosine < CHANGE_BELOW)
        # Reference sites inside this tile: the 2024 vector of the pixel under each.
        n = after.shape[1]
        cols = ((heavy_ref.geometry.x - pair["utm_west"]) // RES).astype(int).to_numpy()
        rows = ((pair["utm_north"] - heavy_ref.geometry.y) // RES).astype(int).to_numpy()
        inside = (cols >= 0) & (cols < n) & (rows >= 0) & (rows < n)
        out = {
            "cosine": cosine.astype(np.float16),
            "changed": changed.astype(np.int32),
            "after": after.reshape(64, -1)[:, changed].T.copy(),
            "ref_rows": np.flatnonzero(inside),
            "ref_after": after[:, rows[inside], cols[inside]].T.copy(),
        }
        np.savez(cache, **out)
        return out

    _t, _rx = time.perf_counter(), rx_bytes()
    with ThreadPoolExecutor(3) as _pool:
        tile_parts = list(_pool.map(tile_change, tile_pairs.to_dict("records")))
    aef_stats = {
        "tile_pairs": len(tile_pairs),
        "seconds": round(time.perf_counter() - _t),
        "downloaded_mb": round((rx_bytes() - _rx) / 1e6),
        "year": AFTER,
    }
    aef_stats
    return aef_stats, dequantise, tile_parts


@app.cell
def _(mo):
    mo.md(r"""
    The tiles go into one 40 m mosaic, clipped to the eleven counties. Every pixel outside
    them is left blank.
    """)
    return


@app.cell
def _(
    Affine,
    RES,
    UTM,
    dequantise,
    heavy_ref,
    np,
    rasterize,
    study_area,
    tile_pairs,
    tile_parts,
):
    _west, _north = tile_pairs["utm_west"].min(), tile_pairs["utm_north"].max()
    _n = 2048
    _cols = int((tile_pairs["utm_west"].max() - _west) / RES) + _n
    _rows = int((_north - tile_pairs["utm_north"].min()) / RES) + _n
    grid = Affine(RES, 0, _west, 0, -RES, _north)
    cosine = np.full((_rows, _cols), np.nan, np.float32)
    _flats, _vecs = [], []  # 2024 vectors of changed pixels, by flat mosaic index
    _ref = np.full((len(heavy_ref), 64), np.nan, np.float32)
    for _pair, _part in zip(tile_pairs.to_dict("records"), tile_parts, strict=True):
        _r0 = int((_north - _pair["utm_north"]) / RES)
        _c0 = int((_pair["utm_west"] - _west) / RES)
        cosine[_r0 : _r0 + _n, _c0 : _c0 + _n] = _part["cosine"].reshape(_n, _n)
        _r, _c = np.divmod(_part["changed"], _n)
        _flat = (_r + _r0) * _cols + (_c + _c0)
        _flats.append(_flat)
        _vecs.append(_part["after"])
        _ref[_part["ref_rows"]] = dequantise(_part["ref_after"])
    _inside = rasterize(
        [(g, 1) for g in study_area.geometry], out_shape=cosine.shape, transform=grid, fill=0
    )
    cosine[_inside == 0] = np.nan
    _order = np.argsort(np.concatenate(_flats))
    after_index = np.concatenate(_flats)[_order]
    after_vectors = np.concatenate(_vecs)[_order]
    heavy_vectors = _ref[~np.isnan(_ref[:, 0])]
    assert UTM == "EPSG:32615"
    {
        "mosaic": cosine.shape,
        "pixels in the counties": int(np.isfinite(cosine).sum()),
        "heavy-industry reference vectors": len(heavy_vectors),
    }
    return after_index, after_vectors, cosine, grid, heavy_vectors


@app.cell
def _(mo):
    mo.md(r"""
    ### How much does a pixel move in six years?

    Most pixels barely move: their 2018 and 2024 vectors have a cosine similarity above
    0.9. We call a pixel **changed** if its similarity is below 0.6, which is the lowest
    1.4% of pixels in the eleven counties. The threshold is a choice, not a fit; the
    histogram shows where it sits.
    """)
    return


@app.cell
def _(CHANGE_BELOW, OUT_DIR, cosine, np, plt):
    _vals = cosine[np.isfinite(cosine)]
    change_share = {
        f"below {t}": round(float((_vals < t).mean()), 4) for t in (0.4, 0.5, CHANGE_BELOW, 0.7)
    }
    change_share["percentiles 0.5, 1, 5, 50"] = np.percentile(_vals, [0.5, 1, 5, 50]).round(3)
    _fig, _ax = plt.subplots(figsize=(7, 3))
    _ax.hist(_vals, bins=200, range=(0, 1), color="0.3")
    _ax.axvline(CHANGE_BELOW, color="crimson")
    _ax.set_yscale("log")
    _ax.set_xlabel("cosine similarity of a 40 m pixel, 2018 against 2024")
    _ax.set_ylabel("pixels")
    _fig.tight_layout()
    _fig.savefig(OUT_DIR / "change_histogram.png", dpi=110)
    change_share
    return (change_share,)


@app.cell
def _(mo):
    mo.md(r"""
    ### Change areas

    Neighbouring changed pixels (touching on a side or a corner) form one **change area**.
    We keep areas of at least 25 pixels (4 ha, about the size of one large warehouse), and
    mark those within 3 km of a residential block group as near homes. Each area keeps its
    size, its mean change, its mean 2024 vector and its location.
    """)
    return


@app.cell
def _(
    CHANGE_BELOW,
    COUNTIES,
    MIN_PIXELS,
    NEAR_HOMES_M,
    RES,
    UTM,
    after_index,
    after_vectors,
    bg,
    cosine,
    dequantise,
    gpd,
    grid,
    ndimage,
    np,
    pd,
    rasterize,
):
    _labels, _ = ndimage.label(cosine < CHANGE_BELOW, structure=np.ones((3, 3)))
    _sizes = np.bincount(_labels.ravel())
    _sizes[0] = 0
    _keep = np.flatnonzero(_sizes >= MIN_PIXELS)
    _relabel = np.zeros(len(_sizes), np.int32)
    _relabel[_keep] = np.arange(1, len(_keep) + 1)
    area_labels = _relabel[_labels]

    # Distance from every pixel to the nearest residential block group.
    _homes = rasterize(
        [(g, 1) for g in bg[bg["residential"]].geometry],
        out_shape=cosine.shape,
        transform=grid,
        fill=0,
    )
    _dist = ndimage.distance_transform_edt(_homes == 0) * RES
    _county = rasterize(
        [(g, i + 1) for i, g in enumerate(bg.dissolve("county").geometry)],
        out_shape=cosine.shape,
        transform=grid,
        fill=0,
    )
    _county_names = list(bg.dissolve("county").index)

    _flat = np.flatnonzero(area_labels)
    _lab = area_labels.ravel()[_flat]
    _order = np.argsort(_lab, kind="stable")
    _flat, _lab = _flat[_order], _lab[_order]
    _starts = np.r_[0, np.flatnonzero(np.diff(_lab)) + 1]
    _rows, _cols = np.divmod(_flat, cosine.shape[1])
    _pos = np.searchsorted(after_index, _flat)
    assert (after_index[_pos] == _flat).all(), "a changed pixel has no 2024 vector"
    _vec = dequantise(after_vectors[_pos])
    _n = np.add.reduceat(np.ones(len(_flat)), _starts)
    _mean_vec = np.add.reduceat(_vec, _starts) / _n[:, None]
    _mean_vec /= np.linalg.norm(_mean_vec, axis=1, keepdims=True)
    _x, _y = grid * (_cols + 0.5, _rows + 0.5)
    areas = gpd.GeoDataFrame(
        {
            "area_id": _lab[_starts],
            "pixels": _n.astype(int),
            "hectares": _n * RES**2 / 1e4,
            "mean_cosine": np.add.reduceat(cosine.ravel()[_flat], _starts) / _n,
            "km_to_homes": np.minimum.reduceat(_dist.ravel()[_flat], _starts) / 1000,
            "county": [
                _county_names[c - 1] if c else "edge"
                for c in _county.ravel()[_flat[_starts]].tolist()
            ],
            "row_min": np.minimum.reduceat(_rows, _starts),
            "row_max": np.maximum.reduceat(_rows, _starts),
            "col_min": np.minimum.reduceat(_cols, _starts),
            "col_max": np.maximum.reduceat(_cols, _starts),
        },
        geometry=gpd.points_from_xy(
            np.add.reduceat(np.asarray(_x), _starts) / _n,
            np.add.reduceat(np.asarray(_y), _starts) / _n,
        ),
        crs=UTM,
    )
    areas["near_homes"] = areas["km_to_homes"] <= NEAR_HOMES_M / 1000
    area_vectors = _mean_vec
    assert len(areas) == len(_keep)
    assert set(COUNTIES.values()) >= set(areas["county"]) - {"edge"}
    _all_changed = int((_sizes > 0).sum())
    area_summary = pd.DataFrame(
        {
            "areas": areas.groupby("county").size(),
            "near homes": areas.groupby("county")["near_homes"].sum(),
            "hectares near homes": areas[areas["near_homes"]].groupby("county")["hectares"].sum(),
        }
    ).fillna(0)
    area_summary.loc["all"] = area_summary.sum()
    area_counts = {
        "changed pixel clusters": _all_changed,
        "areas of 4 ha or more": len(areas),
        "near homes": int(areas["near_homes"].sum()),
        "median hectares near homes": round(
            float(areas.loc[areas["near_homes"], "hectares"].median()), 1
        ),
    }
    area_summary.round(0)
    return area_counts, area_labels, area_summary, area_vectors, areas


@app.cell
def _(area_counts):
    area_counts
    return


@app.cell
def _(OUT_DIR, area_labels, areas, bg, cosine, grid, np, plt):
    _fig, _axes = plt.subplots(2, 1, figsize=(12, 7), height_ratios=[1, 1])
    _ext = (grid.c, grid.c + grid.a * cosine.shape[1], grid.f + grid.e * cosine.shape[0], grid.f)
    for _ax, _rng, _title in (
        (_axes[0], slice(None), "1 − cosine similarity, 2018 to 2024"),
        (_axes[1], slice(None), "change areas of 4 ha or more (red: within 3 km of homes)"),
    ):
        _ax.set_axis_off()
        _ax.set_title(_title, fontsize=9)
    _axes[0].imshow(1 - cosine, cmap="magma", vmin=0, vmax=0.6, extent=_ext)
    bg[bg["residential"]].plot(ax=_axes[1], color="0.85", lw=0)
    _mask = np.ma.masked_equal(area_labels > 0, False)
    _axes[1].imshow(_mask, cmap="Greys", vmin=0, vmax=1, extent=_ext, alpha=0.6)
    _near = areas[areas["near_homes"]]
    _axes[1].scatter(
        _near.geometry.x, _near.geometry.y, s=np.sqrt(_near["hectares"]) * 2, c="crimson"
    )
    for _ax in _axes:
        _ax.set_xlim(_ext[0], _ext[1])
        _ax.set_ylim(_ext[2], _ext[3])
    _fig.tight_layout()
    _fig.savefig(OUT_DIR / "change_map.png", dpi=110)
    _fig
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 2: the registries

    Which facilities are new? We use two EPA registries with dates.

    - **Toxics Release Inventory.** EPA's
      [TRI basic data files](https://www.epa.gov/toxics-release-inventory-tri-program/tri-basic-data-files-calendar-years-1987-present)
      list every facility that reported, by year. A facility is **new** if it first
      reports in 2019–2024 and never in 2010–2018. Reporting depends on chemical thresholds,
      so some "new" reporters are old plants that crossed one; the control below allows for
      that.
    - **Risk Management Program.** HIFLD Next's RMP layer (EPA's Facility Registry Service)
      carries the date EPA created each facility's RMP record. **New** means created in
      2019–2024.

    A facility counts as caught if a change area of 4 ha or more lies within 300 m of its
    registered point. The **control** is the same rate for facilities registered before
    2018 that still report: they weren't built in the window, so anything they catch is
    expansion, rebuilding or chance.
    """)
    return


@app.cell
def _(BEFORE, COUNTIES, DATA_DIR, TRI_URL, TRI_YEARS, UTM, fetch, gpd, pd, rmp, study_area):
    _frames = []
    for _st in ("TX", "LA"):
        for _year in TRI_YEARS:
            _path = fetch(TRI_URL.format(year=_year, st=_st), f"tri/{_year}_{_st}.csv")
            _f = pd.read_csv(_path, usecols=[0, 1, 3, 6, 7, 11, 12, 22, 29], dtype=str)
            _f.columns = ["year", "trifd", "name", "county", "st", "lat", "lon", "sector", "naics"]
            _frames.append(_f.drop_duplicates("trifd"))
    _tri = pd.concat(_frames, ignore_index=True)
    _tri["year"] = _tri["year"].astype(int)
    _years = _tri.groupby("trifd")["year"].agg(["min", "max"])
    _tri = _tri.sort_values("year").drop_duplicates("trifd", keep="last").set_index("trifd")
    _tri = _tri.join(_years)
    tri = gpd.GeoDataFrame(
        _tri,
        geometry=gpd.points_from_xy(_tri["lon"].astype(float), _tri["lat"].astype(float)),
        crs="EPSG:4326",
    ).to_crs(UTM)
    tri = tri[tri.within(study_area.union_all())]
    tri["new"] = tri["min"] > BEFORE
    tri["old_active"] = (tri["min"] < BEFORE) & (tri["max"] > BEFORE)
    _cols = ["registry", "key", "name", "sector", "first_year", "new", "old_active", "geometry"]
    _rmp = rmp.assign(
        registry="RMP",
        key="RMP-" + rmp["REGISTRY_ID"].astype(str),
        new=rmp["first_year"].between(BEFORE + 1, 2024),
        old_active=rmp["first_year"] < BEFORE,
        name=rmp["PRIMARY_NAME"],
        sector="RMP",
    )
    registry = pd.concat(
        [
            tri.assign(registry="TRI", key="TRI-" + tri.index, first_year=tri["min"])[_cols],
            _rmp[_cols],
        ],
        ignore_index=True,
    )
    registry = gpd.GeoDataFrame(registry, geometry="geometry", crs=UTM)
    assert DATA_DIR.exists() and len(COUNTIES) == 11
    registry.groupby("registry")[["new", "old_active"]].sum()
    return (registry,)


@app.cell
def _(
    MATCH_M,
    NEAR_HOMES_M,
    RES,
    area_labels,
    areas,
    bg,
    grid,
    ndimage,
    np,
    pd,
    registry,
):
    # Distance from every pixel to the nearest change-area pixel, and which area that is.
    _dist, (_ri, _ci) = ndimage.distance_transform_edt(area_labels == 0, return_indices=True)
    _cols, _rows = ~grid * (registry.geometry.x.to_numpy(), registry.geometry.y.to_numpy())
    _rows, _cols = np.asarray(_rows).astype(int), np.asarray(_cols).astype(int)
    _ok = (_rows >= 0) & (_rows < area_labels.shape[0]) & (_cols >= 0)
    _ok &= _cols < area_labels.shape[1]
    _r, _c = _rows.clip(0, area_labels.shape[0] - 1), _cols.clip(0, area_labels.shape[1] - 1)
    registry["m_to_change"] = np.where(_ok, _dist[_r, _c] * RES, np.inf)
    registry["area_id"] = np.where(_ok, area_labels[_ri[_r, _c], _ci[_r, _c]], 0)
    registry["caught"] = registry["m_to_change"] <= MATCH_M
    _homes = bg[bg["residential"]].union_all()
    registry["near_homes"] = registry.distance(_homes) <= NEAR_HOMES_M

    def rate(frame: pd.DataFrame) -> str:
        return f"{int(frame['caught'].sum())} of {len(frame)} ({frame['caught'].mean():.0%})"

    recall = pd.DataFrame(
        {
            reg: {
                "new 2019–2024, caught": rate(g[g["new"]]),
                "new, near homes, caught": rate(g[g["new"] & g["near_homes"]]),
                "older and still active, caught (control)": rate(g[g["old_active"]]),
            }
            for reg, g in registry.groupby("registry")
        }
    )
    _ids = set(registry.loc[registry["caught"], "area_id"])
    areas["registered_facility_300m"] = areas["area_id"].isin(_ids)
    recall
    return (recall,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 3: what the change areas are

    A random sample of change areas near homes (fixed seed) is checked by eye. Each gets a
    chip with three panels: the NAIP aerial photo before (2018 in Texas, 2017 in Louisiana),
    the newest NAIP photo (2022 in Texas, 2023 in Louisiana), and a cloud-free Sentinel-2
    image from late 2024, since NAIP doesn't reach 2024 yet. The change area is outlined
    and registered TRI and RMP facilities are marked. Each chip is labelled in
    `hand_check.csv` as one of:

    - **industry**: a new or expanded plant, tank farm, terminal, rail yard, large warehouse
      or similar
    - **housing**: a new subdivision or apartments
    - **commercial**: stores, offices, schools, roads
    - **cleared**: land cleared or graded with nothing built yet, or a borrow pit
    - **farm**: crop rotation, fallow or harvested fields, pasture
    - **water**: flooding, marsh change, ponds, shoreline
    - **trees**: forest cut or grown, storm damage
    - **unclear**: no visible change, or can't tell

    The same is done for the top-ranked areas in step 4 and for a sample of new registered
    facilities that the change map missed, to see whether anything was built there.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 4: does the 2024 vector say "industry"?

    A cheap way to sort change areas: compare each area's mean 2024 vector with the mean
    2024 vector under existing heavy industry in these counties (refineries, petroleum
    terminals, hazardous-waste facilities and RMP facilities registered before 2018). The
    higher the cosine similarity, the more the area looks like an existing plant. This is a
    nearest-centroid classifier with one class; the hand check tells us whether it works.
    """)
    return


@app.cell
def _(area_vectors, areas, heavy_vectors, np):
    _centroid = heavy_vectors.mean(0)
    _centroid /= np.linalg.norm(_centroid)
    areas["industry_score"] = area_vectors @ _centroid
    areas["industry_rank"] = (
        areas["industry_score"].where(areas["near_homes"]).rank(ascending=False, method="first")
    )
    areas.loc[areas["near_homes"]].sort_values("industry_rank").head(10)[
        ["area_id", "county", "hectares", "mean_cosine", "industry_score"]
    ]
    return


@app.cell
def _(MATCH_M, NEAR_HOMES_M, areas, registry):
    # The samples to label: random change areas near homes, the 30 that look most like
    # industry, and new registered facilities near homes, caught or not.
    _near = areas[areas["near_homes"]]
    sample_random = _near.sample(min(60, len(_near)), random_state=0)
    sample_top = _near[_near["industry_rank"] <= 30]
    _new = registry[registry["new"] & registry["near_homes"]]
    sample_facilities = _new.sample(min(30, len(_new)), random_state=0)
    assert MATCH_M < NEAR_HOMES_M
    {
        "random areas": len(sample_random),
        "top-ranked areas": len(sample_top),
        "in both": len(set(sample_random["area_id"]) & set(sample_top["area_id"])),
        "new facilities": len(sample_facilities),
    }
    return sample_facilities, sample_random, sample_top


@app.cell
def _(
    GDAL_ENV,
    OUT_DIR,
    UTM,
    area_labels,
    gpd,
    grid,
    httpx,
    np,
    plt,
    rasterio,
    registry,
    shape,
    shapes,
):
    from rasterio.merge import merge
    from rasterio.vrt import WarpedVRT
    from shapely.geometry import box

    _pc = "https://planetarycomputer.microsoft.com/api"

    def pc_token(collection: str) -> str:
        url = f"{_pc}/sas/v1/token/{collection}"
        return httpx.get(url, timeout=60).raise_for_status().json()["token"]

    def stac_search(body: dict) -> list[dict]:
        response = httpx.post(f"{_pc}/stac/v1/search", json=body, timeout=120)
        return response.raise_for_status().json()["features"]

    def mosaic(hrefs: list[str], ext: tuple, size: int) -> np.ndarray:
        """Warp and merge RGB images onto the chip's UTM extent."""
        with rasterio.Env(**GDAL_ENV):
            srcs = [rasterio.open(f"/vsicurl/{h}") for h in hrefs]
            vrts = [WarpedVRT(s, crs=UTM) for s in srcs]
            img, _ = merge(vrts, bounds=ext, res=(ext[2] - ext[0]) / size, indexes=[1, 2, 3])
            for d in vrts + srcs:
                d.close()
        return np.moveaxis(img, 0, -1)

    def naip_pair(ext: tuple, token: str) -> list[tuple[str, np.ndarray]]:
        """The oldest NAIP photo from 2017 on and the newest one, over the extent."""
        lonlat = gpd.GeoSeries([box(*ext)], crs=UTM).to_crs("EPSG:4326").total_bounds
        items = stac_search({"collections": ["naip"], "bbox": list(lonlat), "limit": 200})
        years = sorted({f["properties"]["naip:year"] for f in items})
        years = [y for y in years if int(y) >= 2017]
        assert len(years) >= 2, f"not enough NAIP years over {ext}"
        out = []
        for year in (years[0], years[-1]):
            hrefs = [
                f"{f['assets']['image']['href']}?{token}"
                for f in items
                if f["properties"]["naip:year"] == year
            ]
            out.append((f"NAIP {year}", mosaic(hrefs, ext, 600)))
        return out

    def sentinel_late_2024(ext: tuple, token: str) -> tuple[str, np.ndarray]:
        """The least cloudy Sentinel-2 image from September to December 2024 that covers it."""
        footprint = gpd.GeoSeries([box(*ext)], crs=UTM).to_crs("EPSG:4326").iloc[0]
        items = stac_search(
            {
                "collections": ["sentinel-2-l2a"],
                "bbox": list(footprint.bounds),
                "datetime": "2024-09-01/2024-12-31",
                "query": {"eo:cloud_cover": {"lt": 10}},
                "limit": 100,
            }
        )
        items = [f for f in items if shape(f["geometry"]).contains(footprint)]
        assert items, f"no clear Sentinel-2 image over {ext}"
        best = min(items, key=lambda f: f["properties"]["eo:cloud_cover"])
        img = mosaic([f"{best['assets']['visual']['href']}?{token}"], ext, 300)
        return f"Sentinel-2 {best['properties']['datetime'][:10]}", img

    def outline(area_id: int, ext: tuple) -> list:
        """Polygons of one change area inside the chip extent, from the label raster."""
        c0, r0 = (max(int(v), 0) for v in ~grid * (ext[0], ext[3]))
        c1, r1 = (int(v) + 1 for v in ~grid * (ext[2], ext[1]))
        sub = area_labels[r0:r1, c0:c1]
        transform = grid * grid.translation(c0, r0)
        mask = (sub == area_id).astype(np.uint8)
        return [shape(g) for g, v in shapes(mask, mask=mask > 0, transform=transform) if v]

    def panels(ext: tuple) -> list[tuple[str, np.ndarray]]:
        """NAIP before, NAIP after and Sentinel-2 late 2024. Tokens last an hour, so fetch anew."""
        return naip_pair(ext, pc_token("naip")) + [
            sentinel_late_2024(ext, pc_token("sentinel-2-l2a"))
        ]

    def draw_chip(name: str, ext: tuple, title: str, area_id: int, images: list) -> None:
        """The three panels with the change area outlined and facilities marked, as a JPEG."""
        path = OUT_DIR / "chips" / f"{name}.jpg"
        polys = gpd.GeoSeries(outline(area_id, ext) if area_id else [], crs=UTM)
        near = registry.cx[ext[0] : ext[2], ext[1] : ext[3]]
        fig, axes = plt.subplots(1, 3, figsize=(13, 4.6))
        for ax, (label, img) in zip(axes, images, strict=True):
            ax.imshow(img, extent=(ext[0], ext[2], ext[1], ext[3]))
            if len(polys):
                polys.boundary.plot(ax=ax, color="cyan", lw=1)
            for (reg, new), g in near.groupby(["registry", "new"]):
                ax.scatter(
                    g.geometry.x,
                    g.geometry.y,
                    s=28,
                    marker="o" if reg == "TRI" else "s",
                    c="red" if new else "yellow",
                    edgecolor="k",
                    label=f"{reg} {'new' if new else 'older'}",
                )
            ax.set_xlim(ext[0], ext[2])
            ax.set_ylim(ext[1], ext[3])
            ax.set_axis_off()
            ax.set_title(label, fontsize=9)
        if len(near):
            axes[0].legend(loc="lower left", fontsize=7)
        fig.suptitle(title, fontsize=9)
        fig.tight_layout()
        fig.savefig(path, dpi=90, pil_kwargs={"quality": 85})
        plt.close(fig)

    def extent(x: float, y: float, half: float) -> tuple:
        return (x - half, y - half, x + half, y + half)

    return draw_chip, extent, panels


@app.cell
def _(
    OUT_DIR,
    RES,
    ThreadPoolExecutor,
    draw_chip,
    extent,
    panels,
    pd,
    sample_facilities,
    sample_random,
    sample_top,
    time,
):
    _t = time.perf_counter()
    _jobs = []  # (name, extent, title, area id to outline)
    _areas = pd.concat([sample_random, sample_top]).drop_duplicates("area_id")
    for _, _a in _areas.iterrows():
        _span = max(_a["row_max"] - _a["row_min"], _a["col_max"] - _a["col_min"]) + 1
        _half = max(_span * RES / 2 + 400, 750)
        _jobs.append(
            (
                f"area-{_a['area_id']}",
                extent(_a.geometry.x, _a.geometry.y, _half),
                f"change area {_a['area_id']}, {_a['county']}, {_a['hectares']:.0f} ha, "
                f"mean cosine {_a['mean_cosine']:.2f}, {2 * _half / 1000:.1f} km across",
                int(_a["area_id"]),
            )
        )
    for _, _f in sample_facilities.iterrows():
        _jobs.append(
            (
                f"facility-{_f['key']}",
                extent(_f.geometry.x, _f.geometry.y, 750),
                f"new {_f['registry']} facility {_f['name']} (first {_f['first_year']:.0f}), "
                f"{'caught' if _f['caught'] else 'missed'}, 1.5 km across",
                int(_f["area_id"]) if _f["caught"] else 0,
            )
        )
    _todo = [j for j in _jobs if not (OUT_DIR / "chips" / f"{j[0]}.jpg").exists()]
    # Downloads run in parallel; drawing stays on this thread, since pyplot isn't thread-safe.
    with ThreadPoolExecutor(6) as _pool:
        for _job, _images in zip(_todo, _pool.map(lambda j: panels(j[1]), _todo), strict=True):
            draw_chip(*_job, _images)
    chip_seconds = round(time.perf_counter() - _t)
    {"chips": len(_jobs), "drawn this run": len(_todo), "seconds": chip_seconds}
    return (chip_seconds,)


@app.cell
def _(mo):
    mo.md(r"""
    ## The hand check

    Labels are read from `hand_check.csv`, which the worker agent filled in by looking at
    each chip in `outputs/chips/`. They are the one part of this notebook that is human-style
    judgment, and anyone can re-check them against the chips.
    """)
    return


@app.cell
def _(HAND_CHECK, area_counts, areas, pd, sample_facilities, sample_random, sample_top):
    from scipy.stats import binomtest

    labels = (
        pd.read_csv(HAND_CHECK, dtype={"id": str})
        if HAND_CHECK.exists()
        else pd.DataFrame(columns=["kind", "id", "label", "note"])
    )
    _area_labels = labels[labels["kind"] == "area"].set_index("id")["label"]
    _rand = sample_random.assign(
        label=sample_random["area_id"].astype(str).map(_area_labels).fillna("unlabelled")
    )
    _top = sample_top.assign(
        label=sample_top["area_id"].astype(str).map(_area_labels).fillna("unlabelled")
    )

    def share_with_ci(k: int, n: int) -> str:
        ci = binomtest(k, n).proportion_ci()
        return f"{k} of {n} ({k / n:.0%}, 95% CI {ci.low:.0%}–{ci.high:.0%})"

    hand_shares = (
        pd.DataFrame(
            {
                "random sample": _rand["label"].value_counts(),
                "top 30 by industry score": _top["label"].value_counts(),
            }
        )
        .fillna(0)
        .astype(int)
    )
    _k = int((_rand["label"] == "industry").sum())
    _industry = pd.concat([_rand, _top]).drop_duplicates("area_id")
    _industry = _industry[_industry["label"] == "industry"]
    hand_result = {
        "random sample: industry": share_with_ci(_k, len(_rand)),
        "estimated industry areas near homes": round(_k / len(_rand) * area_counts["near homes"]),
        "top 30: industry": share_with_ci(int((_top["label"] == "industry").sum()), len(_top)),
        "industry areas found in either sample": len(_industry),
        "of those, no TRI or RMP facility within 300 m": int(
            (~_industry["registered_facility_300m"]).sum()
        ),
    }
    _fac = labels[labels["kind"] == "facility"].set_index("id")["label"]
    _f = sample_facilities.assign(built=sample_facilities["key"].map(_fac).fillna("unlabelled"))
    _built = _f[_f["built"] == "built"]
    hand_result["new facilities with visible new construction"] = f"{len(_built)} of {len(_f)}"
    hand_result["of those, caught by the change map"] = (
        share_with_ci(int(_built["caught"].sum()), len(_built)) if len(_built) else "none"
    )
    unregistered = _industry[~_industry["registered_facility_300m"]]
    new_builds = _built
    assert len(areas)
    hand_shares
    return hand_result, hand_shares, labels, new_builds, unregistered


@app.cell
def _(hand_result):
    hand_result
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### Why the new plants were missed

    For each sampled new facility where the photos show new construction, the lowest
    cosine similarity within 300 m of its registered point, and how many pixels there
    are below 0.6. A plant whose site was already cleared and under construction during
    2018 starts the comparison as a construction site, not as woods or pasture.
    """)
    return


@app.cell
def _(MATCH_M, RES, cosine, grid, labels, new_builds, np, pd):
    _notes = labels[labels["kind"] == "facility"].set_index("id")["note"]
    _rows = []
    for _, _f in new_builds.iterrows():
        _c, _r = ~grid * (_f.geometry.x, _f.geometry.y)
        _k = MATCH_M // RES
        _win = cosine[int(_r) - _k : int(_r) + _k + 1, int(_c) - _k : int(_c) + _k + 1]
        _rows.append(
            {
                "facility": _f["name"],
                "first registered": int(_f["first_year"]),
                "lowest cosine within 300 m": round(float(np.nanmin(_win)), 2),
                "pixels below 0.6": int((_win < 0.6).sum()),
                "what the photos show": _notes[_f["key"]],
            }
        )
    missed_builds = pd.DataFrame(_rows)
    missed_builds
    return (missed_builds,)


@app.cell
def _(areas, labels, pd, sample_random, sample_top):
    from sklearn.metrics import roc_auc_score

    # Does the industry score separate industry from other change in the random sample?
    _lab = labels[labels["kind"] == "area"].set_index("id")["label"]
    _r = sample_random.assign(label=sample_random["area_id"].astype(str).map(_lab).fillna(""))
    _y = (_r["label"] == "industry").to_numpy()
    score_check = {
        "AUC of industry score, random sample": (
            round(float(roc_auc_score(_y, _r["industry_score"])), 3)
            if 0 < _y.sum() < len(_y)
            else "needs both classes"
        ),
        "median score, industry vs other (both samples)": pd.concat([_r, sample_top])
        .drop_duplicates("area_id")
        .assign(label=lambda d: d["area_id"].astype(str).map(_lab))
        .assign(is_industry=lambda d: d["label"] == "industry")
        .groupby("is_industry")["industry_score"]
        .median()
        .round(3)
        .to_dict(),
    }
    assert len(areas)
    score_check
    return (score_check,)


@app.cell
def _(mo):
    mo.md(r"""
    ## What it shows, and what didn't work

    - **Large change near homes is mostly suburbs being built.** In the random sample,
      new housing is the biggest group, and the rest is spread over industry, farm
      rotation, commercial building, cleared land, forestry and ponds. A change map alone
      needs a person (or a better classifier) to sort it.
    - **The "industry" it finds is warehouses and industrial parks**, not plants, tank
      farms or terminals. None of the sampled industry areas was heavy industry, and
      almost none has a TRI or RMP facility within 300 m, since warehouses rarely have to
      report. Unregistered, yes; hazardous in the EJ sense, mostly not.
    - **The registries' "new" facilities are mostly not new buildings.** Most sampled
      2019–2024 first-time TRI and RMP registrations near homes sit in plants that were
      already there in 2018. That is why the change map's recall against them is low and
      only a few points above the control rate for old facilities.
    - **The real new plants were missed** for reasons the table above shows: a site
      already cleared or under construction during 2018 doesn't look different enough by
      2024, and a plant built on an already graded lot inside a complex is too small at
      40 m.
    - **The one-class industry score failed.** Ranked by likeness to existing heavy
      industry, the top 30 change areas are almost all new subdivisions: the vector
      seems to say "new, bright and built", not "industrial".
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Outputs

    `outputs/change_areas.csv` lists every change area of 4 ha or more with its size,
    change, distance to homes, county, industry score and coordinates.
    `outputs/summary.json` holds every number quoted in the README.
    """)
    return


@app.cell
def _(
    OUT_DIR,
    aef_stats,
    area_counts,
    area_summary,
    areas,
    change_share,
    chip_seconds,
    hand_result,
    hand_shares,
    json,
    missed_builds,
    recall,
    score_check,
    t_start,
    time,
    unregistered,
):
    _ll = areas.to_crs("EPSG:4326")
    areas.drop(columns="geometry").assign(
        lon=_ll.geometry.x.round(5), lat=_ll.geometry.y.round(5)
    ).round(3).to_csv(OUT_DIR / "change_areas.csv", index=False)
    summary = {
        "embeddings": aef_stats,
        "change_share": {
            k: (v.tolist() if hasattr(v, "tolist") else v) for k, v in change_share.items()
        },
        "areas": area_counts,
        "areas_by_county": area_summary.round(1).to_dict("index"),
        "recall": recall.to_dict(),
        "hand_shares": hand_shares.to_dict(),
        "hand_result": hand_result,
        "unregistered_industry_area_ids": unregistered["area_id"].tolist(),
        "industry_score": score_check,
        "new_builds": missed_builds.drop(columns="what the photos show").to_dict("records"),
        "chip_seconds": chip_seconds,
        "total_seconds": round(time.perf_counter() - t_start),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    summary
    return


if __name__ == "__main__":
    app.run()

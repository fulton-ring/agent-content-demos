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
    import pyogrio
    import rasterio
    from rasterio.features import rasterize
    from rasterio.io import DatasetReader
    from rasterio.transform import Affine
    from rasterio.windows import Window, from_bounds
    from scipy import ndimage
    from scipy.spatial import KDTree
    from shapely.geometry import box
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    return (
        Affine,
        Callable,
        DatasetReader,
        KDTree,
        LogisticRegression,
        Path,
        StandardScaler,
        ThreadPoolExecutor,
        Window,
        box,
        from_bounds,
        gpd,
        httpx,
        json,
        make_pipeline,
        mo,
        ndimage,
        np,
        os,
        pd,
        plt,
        pyogrio,
        rasterio,
        rasterize,
        roc_auc_score,
        time,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Can satellite embeddings screen for industrial burden in a country with no EJ index?

    The [facility finder spike](../geoembeddings-facility-finder/) trained a classifier on
    10 m [AlphaEarth Foundations](https://deepmind.google/discover/blog/alphaearth-foundations-helps-map-our-planet-in-unprecedented-detail/)
    embeddings of registered refineries, terminals, hazardous-waste sites and chemical
    plants on the US Gulf Coast. It turned out to be a good "industrial-looking land"
    finder, but not a type classifier. AlphaEarth covers the whole world every year, and
    most countries have nothing like EJScreen. So the question here is whether that
    classifier can serve as a **first-pass screen for industry near homes somewhere
    else**, and whether a version retrained on local registered sites does better.

    The test country is **the Netherlands**. It has an open register of industrial sites
    (the EU's Industrial Emissions Portal, the successor to E-PRTR) to score against,
    25 cm open aerial photos to hand-check against, and no EJScreen-style index that
    combines pollution with who lives nearby. To keep the download small, we use five
    provinces with very different industry: Zuid-Holland (Rotterdam's port and refineries),
    Noord-Holland (the IJmuiden steelworks and Amsterdam's port), Zeeland (Vlissingen and
    Terneuzen), Limburg (the Chemelot chemical park) and Groningen (Delfzijl and
    Eemshaven).

    The steps:

    1. Rebuild the US classifier from the facility finder, trained on all 17 Gulf Coast
       counties.
    2. Read the 10 m embeddings over the five provinces and label pixels with the Dutch
       register.
    3. Train a local classifier the same way, holding out one province at a time.
    4. Scan the provinces with both models, group the pixels into sites, and score them
       against the register.
    5. Hand-check a random sample of each model's sites on aerial photos.
    6. Count the people who live within 1 and 3 km of what each model finds.
    """)
    return


@app.cell
def _(Path, os, time):
    t_start = time.perf_counter()
    HERE = Path(__file__).parent
    DATA_DIR = Path(os.environ.get("GEO_DATA_DIR", HERE / "data"))
    OUT_DIR = Path(os.environ.get("GEO_OUT_DIR", HERE / "outputs"))
    for _d in ("aef", "hifld", "ghs"):
        (DATA_DIR / _d).mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "chips").mkdir(parents=True, exist_ok=True)

    YEAR = 2022
    # The facility finder's 17 Gulf Coast counties and parishes, where the US model trains.
    US_COUNTIES = [
        "48201", "48167", "48039", "48071", "48245", "48361", "22019", "22033", "22121",
        "22047", "22005", "22093", "22095", "22089", "22051", "22071", "22087",
    ]  # fmt: skip
    # CBS province codes of the five Dutch provinces we scan.
    NL_PROVINCES = {
        "PV20": "Groningen",
        "PV27": "Noord-Holland",
        "PV28": "Zuid-Holland",
        "PV29": "Zeeland",
        "PV31": "Limburg",
    }
    AEF_BASE = "https://data.source.coop/tge-labs/aef/v1/annual"
    HIFLD = "https://storage.googleapis.com/hifld-next-datasets-prod/hifld"
    US_COUNTY_URL = "https://www2.census.gov/geo/tiger/GENZ2022/shp/cb_2022_us_county_500k.zip"
    NL_PROVINCE_URL = (
        "https://api.pdok.nl/cbs/gebiedsindelingen/ogc/v1/collections/"
        "provincie_gegeneraliseerd/items?f=json&limit=20&jaarcode=2022"
    )
    # EEA Industrial Reporting (IED and E-PRTR) site map, version 16, February 2026, CC-BY 4.0.
    # The download is a public Nextcloud share; its token is part of the public link.
    EEA_SITEMAP_URL = "https://sdi.eea.europa.eu/datashare/public.php/webdav/SiteMap.gdb.zip"
    EEA_SHARE = ("WQpi7BEjScefLYL", "")
    GHS_TILE_URL = (
        "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/"
        "GHS_POP_E2020_GLOBE_R2023A_54009_100/V1-0/tiles/"
        "GHS_POP_E2020_GLOBE_R2023A_54009_100_V1_0_R{row}_C{col}.zip"
    )
    PDOK_WMS = "https://service.pdok.nl/hwh/luchtfotorgb/wms/v1_0"
    # The facility finder's four training registries, in its order of precedence.
    US_TRAIN_LAYERS = {
        "refinery": "petroleum-refineries",
        "terminal": "petroleum-product-terminals",
        "tsdf": "epa-rcra-treatment-storage-and-disposal-facilities",
        "rmp": "epa-emergency-response-rmp-facilities",
    }
    US_OTHER_LAYERS = [
        "epa-frs-toxic-release-inventory",
        "power-plants-1",
        "epa-superfund-enterprise-management-system-sems-sites-1",
        "natural-gas-processing-plants-1",
        "liquified-natural-gas-lng-import-and-export-terminals-1",
    ]
    # E-PRTR sectors that match what the US model learned: refineries and power plants,
    # chemicals, metals, cement and glass, and waste. Livestock, food, paper and "other"
    # are left out.
    HEAVY_SECTORS = ["ENERGY", "CHEMICALS", "METALS", "MINERALS", "WASTE AND WASTEWATER"]
    ALBERS, RD = "EPSG:5070", "EPSG:28992"
    HAND_CHECK = HERE / "hand_check.csv"
    BLOCK = 1024  # the files' internal block, 10.24 km at 10 m
    STRIDE = 2  # the scan keeps every second 10 m pixel each way
    POS_RADIUS_M = 30  # training pixels around each facility point
    NEG_MIN_DIST_M = 1000  # background pixels are at least this far from any facility
    NEG_PER_BLOCK = 300
    THRESHOLD = 0.9  # P(industrial) for a scan pixel, as in the facility finder
    MIN_PIXELS = 25  # 1 ha on the 20 m scan grid
    MIN_HA = 5  # the facility finder's operating point
    MATCH_M, CANDIDATE_M = 500, 1000
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
        CANDIDATE_M,
        DATA_DIR,
        EEA_SHARE,
        EEA_SITEMAP_URL,
        GDAL_ENV,
        GHS_TILE_URL,
        HAND_CHECK,
        HEAVY_SECTORS,
        HIFLD,
        MATCH_M,
        MIN_HA,
        MIN_PIXELS,
        NEG_MIN_DIST_M,
        NEG_PER_BLOCK,
        NL_PROVINCES,
        NL_PROVINCE_URL,
        OUT_DIR,
        PDOK_WMS,
        POS_RADIUS_M,
        RD,
        STRIDE,
        THRESHOLD,
        US_COUNTIES,
        US_COUNTY_URL,
        US_OTHER_LAYERS,
        US_TRAIN_LAYERS,
        YEAR,
        t_start,
    )


@app.cell
def _(mo):
    mo.md(r"""
    ## How the embeddings are read

    This is the facility finder's reader, copied here because that folder can't be
    edited. The embeddings come from the [Source Cooperative copy](https://source.coop/tge-labs/aef)
    of AlphaEarth's annual Satellite Embedding dataset (CC-BY 4.0, no account needed; "The
    AlphaEarth Foundations Satellite Embedding dataset is produced by Google and Google
    DeepMind"). Each file is an 8192 × 8192 tile of 10 m pixels in its UTM zone, stored
    as 64 bands in 1024 × 1024 blocks, so the cheapest read is a whole 10 km block.
    From each block that touches a study area we keep:

    - the 10 m pixels within 30 m of each registered facility point (training positives);
    - 300 random 10 m pixels more than 1 km from any registered facility (background);
    - in the Netherlands only, every second pixel each way (a 20 m grid) for the scan.

    Files are stored bottom-up, so rows are flipped, and int8 values are dequantised as
    `(v / 127.5)² · sign(v)`, with -128 as no-data. Each pixel is read from the UTM zone
    its longitude falls in, so nothing is counted twice where zones meet.
    """)
    return


@app.cell
def _(
    AEF_BASE,
    Affine,
    BLOCK,
    Callable,
    DATA_DIR,
    DatasetReader,
    GDAL_ENV,
    HIFLD,
    KDTree,
    NEG_MIN_DIST_M,
    NEG_PER_BLOCK,
    POS_RADIUS_M,
    Path,
    STRIDE,
    Window,
    YEAR,
    box,
    gpd,
    httpx,
    np,
    rasterio,
    rasterize,
    time,
):
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

    def fetch(url: str, name: str, auth: tuple[str, str] | None = None) -> Path:
        """Download a file once into data/ and return its path."""
        path = DATA_DIR / name
        if path.exists():
            return path
        tmp = path.with_suffix(path.suffix + ".part")
        with httpx.stream("GET", url, follow_redirects=True, timeout=600, auth=auth) as response:
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

    def dequantise(v: np.ndarray) -> np.ndarray:
        """AlphaEarth's int8 storage back to embedding values."""
        f = v.astype(np.float32)
        return (f / 127.5) ** 2 * np.sign(f)

    def utm_strip(utm_zone: str) -> object:
        """The longitude strip of a UTM zone such as '15N', as a WGS84 box."""
        zone = int(utm_zone[:-1])
        return box(-186 + 6 * zone, 0, -180 + 6 * zone, 60)

    def block_jobs(regions: gpd.GeoDataFrame, tiles: gpd.GeoDataFrame) -> list:
        """The (tile, block row, block column) of every block that touches the regions."""
        jobs = []
        for ti, tile in tiles.iterrows():
            area = regions.clip(utm_strip(tile["utm_zone"])).to_crs(tile["crs"]).union_all()
            for bi in range(8192 // BLOCK):
                for bj in range(8192 // BLOCK):
                    x0 = tile["utm_west"] + bj * BLOCK * 10
                    y0 = tile["utm_south"] + bi * BLOCK * 10
                    if area.intersects(box(x0, y0, x0 + BLOCK * 10, y0 + BLOCK * 10)):
                        jobs.append((ti, bi, bj))
        return jobs

    def read_block(
        tile: dict,
        bi: int,
        bj: int,
        regions: gpd.GeoDataFrame,
        positives: gpd.GeoDataFrame,
        registered: gpd.GeoDataFrame,
        keep_grid: bool,
    ) -> dict:
        """Read one 10 km block at 10 m; keep training pixels and, if asked, the scan grid.

        regions (WGS84) has one row per region, numbered by position. positives has a
        `label` column (1, 2, ...: smaller wins where facilities overlap). Background
        pixels are kept at least NEG_MIN_DIST_M from every point in registered.
        """
        name = tile["path"].rsplit("/", 1)[1].removesuffix(".tiff")
        cache = DATA_DIR / "aef" / f"{YEAR}-{tile['utm_zone']}-{name}-{bi}-{bj}-{keep_grid:d}.npz"
        if cache.exists():
            return dict(np.load(cache))
        url = AEF_BASE + tile["path"].split("/v1/annual", 1)[1]
        window = Window(bj * BLOCK, bi * BLOCK, BLOCK, BLOCK)
        raw = read_remote(url, lambda r: r.read(window=window))
        assert raw.shape == (64, BLOCK, BLOCK), raw.shape
        raw = raw[:, ::-1, :]  # bottom-up file; now row 0 is the north edge
        west = tile["utm_west"] + bj * BLOCK * 10
        north = tile["utm_south"] + (bi + 1) * BLOCK * 10
        local = regions.clip(utm_strip(tile["utm_zone"])).to_crs(tile["crs"])
        # Region of each 10 m pixel (-1 outside the study area or in the other zone).
        region = rasterize(
            ((g, i) for i, g in zip(local.index, local.geometry, strict=True)),
            out_shape=(BLOCK, BLOCK),
            transform=Affine(10, 0, west, 0, -10, north),
            fill=-1,
            dtype="int16",
        )
        region[raw[0] == -128] = -1

        # Positives: pixels within POS_RADIUS_M of a training facility in this block.
        fac = positives.to_crs(tile["crs"])
        cols = ((fac.geometry.x - west) / 10).to_numpy()
        rows = ((north - fac.geometry.y) / 10).to_numpy()
        r = POS_RADIUS_M / 10
        here = (cols >= -r) & (cols < BLOCK + r) & (rows >= -r) & (rows < BLOCK + r)
        pos = {}
        for kind, c, rr in zip(fac["label"].to_numpy()[here], cols[here], rows[here], strict=True):
            for pr in range(int(rr - r), int(rr + r) + 1):
                for pc in range(int(c - r), int(c + r) + 1):
                    inside = 0 <= pr < BLOCK and 0 <= pc < BLOCK
                    near = (pr + 0.5 - rr) ** 2 + (pc + 0.5 - c) ** 2 <= r * r
                    if inside and near and region[pr, pc] >= 0:
                        pos[(pr, pc)] = min(kind, pos.get((pr, pc), kind))
        pos_rc = np.array(list(pos), dtype=int).reshape(-1, 2)

        # Background: random pixels in the study area far from every registered facility.
        rng = np.random.default_rng([bi, bj, int(tile["utm_west"]), int(tile["utm_south"])])
        cand = np.argwhere(region >= 0)
        cand = cand[rng.choice(len(cand), min(len(cand), 3 * NEG_PER_BLOCK), replace=False)]
        allfac = registered.to_crs(tile["crs"])
        xy = np.c_[west + (cand[:, 1] + 0.5) * 10, north - (cand[:, 0] + 0.5) * 10]
        dist, _ = KDTree(np.c_[allfac.geometry.x, allfac.geometry.y]).query(xy)
        neg_rc = cand[dist > NEG_MIN_DIST_M][:NEG_PER_BLOCK]

        out = {
            "pos": raw[:, pos_rc[:, 0], pos_rc[:, 1]].T.copy(),
            "pos_label": np.array(list(pos.values()), dtype=int),
            "pos_region": region[pos_rc[:, 0], pos_rc[:, 1]],
            "neg": raw[:, neg_rc[:, 0], neg_rc[:, 1]].T.copy(),
            "neg_region": region[neg_rc[:, 0], neg_rc[:, 1]],
        }
        if keep_grid:
            out["grid"] = raw[:, ::STRIDE, ::STRIDE].copy()
            out["grid_region"] = region[::STRIDE, ::STRIDE].copy()
        np.savez(cache, **out)
        return out

    rx_start = rx_bytes()
    return block_jobs, dequantise, fetch, hifld_layer, read_block, rx_bytes, rx_start


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 1: rebuild the US classifier

    The facility finder's model is a multinomial logistic regression on the 64 embedding
    values. It labels each pixel as refinery, petroleum terminal, hazardous-waste TSDF, RMP
    chemical facility or background. The facility points come from
    [HIFLD Next](https://hifld.publicenvirodata.org) v1.0.0, and background pixels are
    kept 1 km from those four layers and five more (TRI reporters, power plants,
    Superfund, gas processing, LNG). Here it is trained once on all 17 counties, since
    the Netherlands is the held-out test. County outlines are the Census Bureau's 2022
    cartographic boundaries instead of the EJScreen block groups the facility finder
    used, so the pixel counts differ slightly from its 21,189 positives and 127,798
    background pixels. Only training pixels are kept on disk; the US is not scanned.
    """)
    return


@app.cell
def _(
    AEF_BASE,
    ThreadPoolExecutor,
    US_COUNTIES,
    US_COUNTY_URL,
    US_OTHER_LAYERS,
    US_TRAIN_LAYERS,
    YEAR,
    block_jobs,
    fetch,
    gpd,
    hifld_layer,
    pd,
    read_block,
    rx_bytes,
    time,
):
    _t, _rx = time.perf_counter(), rx_bytes()
    aef_index = gpd.read_parquet(fetch(f"{AEF_BASE}/aef_index.parquet", "aef_index.parquet"))
    aef_index = aef_index[aef_index["year"] == YEAR].set_geometry("geom")
    us_counties = gpd.read_file(f"zip://{fetch(US_COUNTY_URL, 'us_counties.zip')}")
    us_counties = us_counties[us_counties["GEOID"].isin(US_COUNTIES)].to_crs("EPSG:4326")
    us_counties = us_counties.reset_index(drop=True)
    assert len(us_counties) == len(US_COUNTIES)

    _frames = []
    for _label, _layer in enumerate([*US_TRAIN_LAYERS.values(), *US_OTHER_LAYERS], start=1):
        _f = gpd.read_parquet(hifld_layer(_layer)).to_crs("EPSG:5070")
        _f = _f[_f.geometry.notna() & ~_f.geometry.is_empty]
        _frames.append(
            gpd.GeoDataFrame({"label": [_label] * len(_f)}, geometry=_f.geometry.centroid.values)
        )
    _us_fac = gpd.GeoDataFrame(pd.concat(_frames, ignore_index=True), crs="EPSG:5070")
    _us_fac = gpd.sjoin(_us_fac.to_crs("EPSG:4326"), us_counties[["geometry"]], predicate="within")
    _us_train = _us_fac[_us_fac["label"] <= len(US_TRAIN_LAYERS)]

    _us_tiles = aef_index[aef_index.intersects(us_counties.union_all())].reset_index(drop=True)
    _jobs = block_jobs(us_counties, _us_tiles)

    def _read_us(job: tuple[int, int, int]) -> dict:
        ti, bi, bj = job
        tile = _us_tiles.loc[ti].to_dict()
        return read_block(tile, bi, bj, us_counties, _us_train, _us_fac, keep_grid=False)

    # Each block is 64 range requests in a row, so throughput comes from reading many at once.
    with ThreadPoolExecutor(32) as _pool:
        us_blocks = list(_pool.map(_read_us, _jobs))
    us_read = {
        "blocks": len(us_blocks),
        "training facilities": len(_us_train),
        "positive pixels": int(sum(len(b["pos"]) for b in us_blocks)),
        "background pixels": int(sum(len(b["neg"]) for b in us_blocks)),
        "seconds": round(time.perf_counter() - _t),
        "downloaded GB": round((rx_bytes() - _rx) / 1e9, 2),
    }
    us_read
    return aef_index, us_blocks, us_read


@app.cell
def _(LogisticRegression, StandardScaler, dequantise, make_pipeline, np, us_blocks):
    _X = dequantise(np.concatenate([b["pos"] for b in us_blocks] + [b["neg"] for b in us_blocks]))
    _y = np.concatenate(
        [b["pos_label"] for b in us_blocks] + [np.zeros(len(b["neg"]), int) for b in us_blocks]
    )
    us_model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000))
    us_model.fit(_X, _y)
    assert list(us_model.classes_) == [0, 1, 2, 3, 4]
    return (us_model,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 2: the Dutch provinces and the register

    Province outlines are CBS's generalised 2022 boundaries from PDOK (CC-BY 4.0), which
    follow the coast, so the scan stays on land.

    The register is the EEA's [Industrial Reporting site map](https://sdi.eea.europa.eu/catalogue/srv/api/records/3bbf28cb-70e8-4073-8fe9-8c1d9c513f52),
    version 16 (February 2026, CC-BY 4.0). It holds every site that reported under the
    Industrial Emissions Directive or E-PRTR, one row per site per reporting year. We keep
    Dutch sites that reported in 2021, 2022 or 2023, around the embedding year. A site is
    **heavy** if one of its E-PRTR sectors is energy, chemicals, metals, minerals or waste
    and wastewater. Those are the closest match to the US model's refineries, terminals,
    chemical plants and waste sites. Heavy sites are what the local model trains on and
    what both models are scored against. Every other non-livestock site (food, paper,
    "other" manufacturing) only keeps background pixels away from registered industry. Most
    sites in the register are intensive livestock farms, which are left out entirely.
    """)
    return


@app.cell
def _(
    EEA_SHARE,
    EEA_SITEMAP_URL,
    HEAVY_SECTORS,
    NL_PROVINCES,
    NL_PROVINCE_URL,
    RD,
    fetch,
    gpd,
    pd,
    pyogrio,
):
    provinces = gpd.read_file(fetch(NL_PROVINCE_URL, "nl_provinces_2022.json"))
    provinces = provinces[provinces["statcode"].isin(list(NL_PROVINCES))].reset_index(drop=True)
    provinces = provinces[["statnaam", "geometry"]].rename(columns={"statnaam": "province"})
    assert len(provinces) == len(NL_PROVINCES)

    _gdb = fetch(EEA_SITEMAP_URL, "eea_sitemap_v16.gdb.zip", auth=EEA_SHARE)
    _cols = ["siteName", "InspireSiteId", "Site_reporting_year", "eprtr_sectors"]
    # The filter columns must be read too, or OGR ignores them and matches nothing.
    _cols += ["eea_activities", "x_4258", "y_4258", "countryCode"]
    _sites = pyogrio.read_dataframe(
        f"/vsizip/{_gdb}",
        columns=_cols,
        where="countryCode = 'NL' AND Site_reporting_year IN (2021, 2022, 2023)",
        read_geometry=False,
    )
    _sites = _sites.sort_values("Site_reporting_year").drop_duplicates("InspireSiteId", keep="last")
    _sectors = _sites["eprtr_sectors"].fillna("")
    _sites["heavy"] = _sectors.apply(lambda s: any(h in s.split(",") for h in HEAVY_SECTORS))
    _sites = _sites[_sectors.ne("") & ~_sectors.str.fullmatch(r"(INTENSIVE LIVESTOCK,?)+")]
    register = gpd.GeoDataFrame(
        _sites,
        geometry=gpd.points_from_xy(_sites["x_4258"], _sites["y_4258"]),
        crs="EPSG:4258",
    ).to_crs("EPSG:4326")
    register = gpd.sjoin(register, provinces, predicate="within").drop(columns="index_right")
    register = register.reset_index(drop=True)
    register["label"] = 1
    register_rd = register.to_crs(RD)
    heavy_rd = register_rd[register_rd["heavy"]]
    _counts = register.groupby(["province", "heavy"]).size().unstack(fill_value=0)
    _counts.columns = ["other non-livestock sites", "heavy sites"]
    _counts.loc["total"] = _counts.sum()
    _counts
    return heavy_rd, provinces, register, register_rd


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 3: read the Dutch embeddings and train the local classifier

    The five provinces touch 230 blocks. The local classifier is the same pipeline as
    the US one, but with two classes (heavy site or background), because the Dutch
    register's sectors don't map one to one onto the US types, and the facility finder
    showed the model can't separate types anyway. It is trained five times, each time
    leaving out one province, and each province is scored only by the model that never
    saw it.

    First, the pixel check. How well does each model's probability of "industrial"
    separate pixels at heavy register sites from background pixels? The local score is
    on held-out provinces.
    """)
    return


@app.cell
def _(
    ThreadPoolExecutor,
    aef_index,
    block_jobs,
    pd,
    provinces,
    read_block,
    register,
    rx_bytes,
    time,
):
    _t, _rx = time.perf_counter(), rx_bytes()
    _wgs = provinces.to_crs("EPSG:4326")
    nl_tiles = aef_index[aef_index.intersects(_wgs.union_all())].reset_index(drop=True)
    _jobs = block_jobs(_wgs, nl_tiles)
    _heavy = register[register["heavy"]]

    def _read_nl(job: tuple[int, int, int]) -> dict:
        ti, bi, bj = job
        tile = nl_tiles.loc[ti].to_dict()
        return read_block(tile, bi, bj, _wgs, _heavy, register, keep_grid=True)

    with ThreadPoolExecutor(32) as _pool:
        nl_blocks = list(_pool.map(_read_nl, _jobs))
    nl_block_meta = pd.DataFrame(_jobs, columns=["tile", "bi", "bj"])
    nl_read = {
        "tiles": len(nl_tiles),
        "blocks": len(nl_blocks),
        "scan pixels": int(sum((b["grid_region"] >= 0).sum() for b in nl_blocks)),
        "positive pixels": int(sum(len(b["pos"]) for b in nl_blocks)),
        "background pixels": int(sum(len(b["neg"]) for b in nl_blocks)),
        "seconds": round(time.perf_counter() - _t),
        "downloaded GB": round((rx_bytes() - _rx) / 1e9, 2),
    }
    nl_read
    return nl_block_meta, nl_blocks, nl_read, nl_tiles


@app.cell
def _(
    LogisticRegression,
    StandardScaler,
    dequantise,
    make_pipeline,
    nl_blocks,
    np,
    pd,
    provinces,
    roc_auc_score,
    us_model,
):
    _X = dequantise(np.concatenate([b["pos"] for b in nl_blocks] + [b["neg"] for b in nl_blocks]))
    _y = np.concatenate(
        [np.ones(len(b["pos"]), int) for b in nl_blocks]
        + [np.zeros(len(b["neg"]), int) for b in nl_blocks]
    )
    _region = np.concatenate(
        [b["pos_region"] for b in nl_blocks] + [b["neg_region"] for b in nl_blocks]
    )
    # One local model per held-out province, trained on the other four.
    local_models = []
    _p_local = np.zeros(len(_y))
    for _k in range(len(provinces)):
        _m = make_pipeline(StandardScaler(), LogisticRegression(max_iter=3000))
        _m.fit(_X[_region != _k], _y[_region != _k])
        _p_local[_region == _k] = _m.predict_proba(_X[_region == _k])[:, 1]
        local_models.append(_m)
    _p_us = 1 - us_model.predict_proba(_X)[:, 0]
    _rows = {}
    for _k, _name in enumerate([*provinces["province"], "all five"]):
        _sel = _region == _k if _k < len(provinces) else np.ones(len(_y), bool)
        _rows[_name] = {
            "heavy-site pixels": int(_y[_sel].sum()),
            "background pixels": int((_y[_sel] == 0).sum()),
            "AUC, US model": round(roc_auc_score(_y[_sel], _p_us[_sel]), 3),
            "AUC, local model (held out)": round(roc_auc_score(_y[_sel], _p_local[_sel]), 3),
            "heavy pixels over 0.9, US": round((_p_us[_sel & (_y == 1)] >= 0.9).mean(), 3),
            "heavy pixels over 0.9, local": round((_p_local[_sel & (_y == 1)] >= 0.9).mean(), 3),
            "background over 0.9, US": round((_p_us[_sel & (_y == 0)] >= 0.9).mean(), 4),
            "background over 0.9, local": round((_p_local[_sel & (_y == 0)] >= 0.9).mean(), 4),
        }
    pixel_scores = pd.DataFrame(_rows).T
    pixel_scores
    return local_models, pixel_scores


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 4: scan the provinces and score the sites

    Each model scores every pixel of the 20 m scan grid (the local model is used only on
    the province it didn't see). As in the facility finder, a pixel is "industrial" when
    P(industrial) is at least 0.9. Industrial pixels are cleaned of speckle with a 3 × 3
    opening and joined into connected sites within each tile, and sites under 1 ha are
    dropped. The operating point is **sites of 5 ha or more**, the facility finder's,
    fixed before this scan.

    A site is **registered** if a heavy register site is within 500 m of one of its
    pixels (precision), and a **candidate** if no non-livestock register site at all is
    within 1 km. A heavy register site is **found** if a site comes within 500 m of it
    (recall). The register only lists sites big enough to report under the IED or
    E-PRTR, so precision here is a floor; the hand check in step 5 measures the rest.
    """)
    return


@app.cell
def _(
    BLOCK,
    Callable,
    KDTree,
    MATCH_M,
    CANDIDATE_M,
    MIN_PIXELS,
    RD,
    STRIDE,
    dequantise,
    gpd,
    heavy_rd,
    local_models,
    ndimage,
    nl_block_meta,
    nl_blocks,
    nl_tiles,
    np,
    pd,
    provinces,
    register_rd,
    time,
    us_model,
):
    _n, _g = 8192 // BLOCK, BLOCK // STRIDE

    def probability_mosaics(p_industrial: Callable[[np.ndarray, int], np.ndarray]) -> dict:
        """P(industrial) on the 20 m grid of each tile, from p_industrial(features, region)."""
        mosaics = {}
        for tile, rows in nl_block_meta.groupby("tile"):
            prob = np.zeros((_n * _g, _n * _g), np.float16)
            for i, b in rows.iterrows():
                blk = blocks_by_index[i]
                r0, c0 = (_n - 1 - b["bi"]) * _g, b["bj"] * _g
                for k in np.unique(blk["grid_region"][blk["grid_region"] >= 0]):
                    ok = np.argwhere(blk["grid_region"] == k)
                    feat = dequantise(blk["grid"][:, ok[:, 0], ok[:, 1]].T)
                    prob[r0 + ok[:, 0], c0 + ok[:, 1]] = p_industrial(feat, int(k))
            mosaics[tile] = prob
        return mosaics

    def find_sites(mosaics: dict, threshold: float) -> tuple[pd.DataFrame, pd.DataFrame]:
        """Join pixels over the threshold into sites; return their pixels and a site table."""
        pixels = []
        for tile, prob in mosaics.items():
            mask = ndimage.binary_opening(prob >= threshold, np.ones((3, 3), bool))
            lab, nlab = ndimage.label(mask, np.ones((3, 3), bool))
            if not nlab:
                continue
            rr, cc = np.nonzero(lab)
            ids = lab[rr, cc]
            keep = np.bincount(ids)[ids] >= MIN_PIXELS
            rr, cc, ids = rr[keep], cc[keep], ids[keep]
            west = nl_tiles.at[tile, "utm_west"]
            north = nl_tiles.at[tile, "utm_south"] + 8192 * 10
            xy = gpd.GeoSeries.from_xy(
                west + (cc + 0.5) * 10 * STRIDE,
                north - (rr + 0.5) * 10 * STRIDE,
                crs=nl_tiles.at[tile, "crs"],
            ).to_crs(RD)
            pixels.append(
                pd.DataFrame(
                    {"site": [f"{tile}-{i}" for i in ids], "x": xy.x.values, "y": xy.y.values}
                )
            )
        px = pd.concat(pixels, ignore_index=True)
        sites = px.groupby("site").agg(x=("x", "mean"), y=("y", "mean"), pixels=("x", "size"))
        sites["area_ha"] = sites["pixels"] * (10 * STRIDE) ** 2 / 1e4
        site_of = px["site"].to_numpy()
        _d, _ = heavy_tree.query(px[["x", "y"]].to_numpy())
        sites["d_heavy"] = pd.Series(_d).groupby(site_of).min()
        _d, _ = register_tree.query(px[["x", "y"]].to_numpy())
        sites["d_register"] = pd.Series(_d).groupby(site_of).min()
        sites["registered"] = sites["d_heavy"] <= MATCH_M
        sites["candidate"] = sites["d_register"] > CANDIDATE_M
        _centre = gpd.GeoDataFrame(geometry=gpd.points_from_xy(sites["x"], sites["y"]), crs=RD)
        _prov = gpd.sjoin_nearest(_centre, provinces.to_crs(RD))["province"]
        sites["province"] = _prov[~_prov.index.duplicated()].to_numpy()
        return px, sites

    blocks_by_index = dict(enumerate(nl_blocks))
    heavy_tree = KDTree(np.c_[heavy_rd.geometry.x, heavy_rd.geometry.y])
    register_tree = KDTree(np.c_[register_rd.geometry.x, register_rd.geometry.y])
    _t = time.perf_counter()
    mosaics = {
        "US": probability_mosaics(lambda f, k: 1 - us_model.predict_proba(f)[:, 0]),
        "local": probability_mosaics(lambda f, k: local_models[k].predict_proba(f)[:, 1]),
    }
    scan_seconds = round(time.perf_counter() - _t)
    scan_seconds
    return find_sites, mosaics, scan_seconds


@app.cell
def _(
    KDTree,
    MATCH_M,
    MIN_HA,
    THRESHOLD,
    find_sites,
    heavy_rd,
    mosaics,
    np,
    pd,
):
    def scores(px: pd.DataFrame, sites: pd.DataFrame, min_ha: float) -> dict:
        """Precision, recall and candidate count for sites of at least min_ha."""
        kept = sites[sites["area_ha"] >= min_ha]
        big = px[px["site"].isin(kept.index)]
        d, _ = KDTree(big[["x", "y"]].to_numpy()).query(
            np.c_[heavy_rd.geometry.x, heavy_rd.geometry.y]
        )
        return {
            "sites": len(kept),
            "precision: heavy site within 500 m": round(kept["registered"].mean(), 3),
            "recall: heavy sites found": round((d <= MATCH_M).mean(), 3),
            "candidates: no register site within 1 km": int(kept["candidate"].sum()),
            "site area, km²": round(kept["area_ha"].sum() / 100, 1),
        }

    found = {}
    _rows = []
    for _model in mosaics:
        for _thr in (0.5, THRESHOLD, 0.99):
            _px, _sites = find_sites(mosaics[_model], _thr)
            if _thr == THRESHOLD:
                found[_model] = (_px, _sites)
            for _ha in (1, MIN_HA, 20) if _thr == THRESHOLD else (MIN_HA,):
                _rows.append(
                    {"model": _model, "threshold": _thr, "min ha": _ha} | scores(_px, _sites, _ha)
                )
    score_table = pd.DataFrame(_rows).set_index(["model", "threshold", "min ha"])
    score_table
    return found, score_table, scores


@app.cell
def _(mo):
    mo.md(r"""
    The same scores at the operating point (0.9, sites of 5 ha or more), by province and
    for both models. Each heavy register site counts in the province it lies in.
    """)
    return


@app.cell
def _(KDTree, MATCH_M, MIN_HA, found, heavy_rd, np, pd):
    _rows = []
    for _model, (_px, _sites) in found.items():
        _kept = _sites[_sites["area_ha"] >= MIN_HA]
        _big = _px[_px["site"].isin(_kept.index)]
        _d, _ = KDTree(_big[["x", "y"]].to_numpy()).query(
            np.c_[heavy_rd.geometry.x, heavy_rd.geometry.y]
        )
        _hit = pd.Series(_d <= MATCH_M, index=heavy_rd.index)
        for _prov, _s in _kept.groupby("province"):
            _h = heavy_rd["province"] == _prov
            _rows.append(
                {
                    "model": _model,
                    "province": _prov,
                    "heavy sites": int(_h.sum()),
                    "sites found": len(_s),
                    "precision": round(_s["registered"].mean(), 3),
                    "recall": round(_hit[_h].mean(), 3),
                    "candidates": int(_s["candidate"].sum()),
                }
            )
    province_scores = pd.DataFrame(_rows).set_index(["model", "province"])
    # Recall by register sector, to see which kinds of site carry over.
    _sector = heavy_rd["eea_activities"].fillna("").str.split(",").str[0]
    _by_sector = {}
    for _model, (_px, _sites) in found.items():
        _big = _px[_px["site"].isin(_sites.index[_sites["area_ha"] >= MIN_HA])]
        _d, _ = KDTree(_big[["x", "y"]].to_numpy()).query(
            np.c_[heavy_rd.geometry.x, heavy_rd.geometry.y]
        )
        _by_sector[f"recall, {_model}"] = (
            pd.Series(_d <= MATCH_M, index=heavy_rd.index).groupby(_sector).mean().round(2)
        )
    sector_recall = pd.DataFrame(_by_sector)
    sector_recall.insert(0, "heavy sites", _sector.value_counts())
    sector_recall = sector_recall.sort_values("heavy sites", ascending=False)
    province_scores
    return province_scores, sector_recall


@app.cell
def _(sector_recall):
    sector_recall
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 5: hand check

    Thirty sites of 5 ha or more are drawn at random (seed 0) from each model's
    detections, registered or not. Each gets a chip of PDOK's 2022 25 cm aerial photo
    (Beeldmateriaal Nederland, open data, no account) with the site's pixels outlined
    in cyan, heavy register sites as red dots and other register sites as yellow dots.
    Each chip was looked at and labelled in `hand_check.csv`:

    - **heavy**: the kind of site the classifier was trained on: tank farm, refinery,
      chemical or process plant, steelworks, power station, waste site or landfill, bulk
      terminal;
    - **light**: other industry: warehouses, factory halls, container or rail yards,
      shipyards, quarries;
    - **no**: nothing industrial: greenhouses, roofs, parking, roads, fields, water.

    The labels are the one part of this notebook that is human judgment (here, the
    worker agent's). The chips are in `outputs/chips/` so anyone can check them.
    """)
    return


@app.cell
def _(MIN_HA, OUT_DIR, PDOK_WMS, found, heavy_rd, httpx, np, pd, plt, register_rd, time):
    from io import BytesIO

    from PIL import Image

    HAND_N = 30
    _samples = []
    for _model, (_px, _sites) in found.items():
        _kept = _sites[_sites["area_ha"] >= MIN_HA]
        _s = _kept.sample(min(HAND_N, len(_kept)), random_state=0).copy()
        _s.insert(0, "model", _model)
        _samples.append(_s)
    hand_sample = pd.concat(_samples)
    for (_model, _site), _row in hand_sample.set_index("model", append=True).swaplevel().iterrows():
        _chip = OUT_DIR / "chips" / f"{_model}-{_site}.jpg"
        if _chip.exists():
            continue
        _px = found[_model][0]
        _px = _px[_px["site"] == _site]
        _half = max(_px["x"].max() - _px["x"].min(), _px["y"].max() - _px["y"].min(), 500) / 2
        _half += 400
        _cx, _cy = (_px["x"].min() + _px["x"].max()) / 2, (_px["y"].min() + _px["y"].max()) / 2
        _ext = (_cx - _half, _cy - _half, _cx + _half, _cy + _half)
        # PDOK now and then answers 500 under load; retry a few times with backoff.
        for _attempt in range(4):
            _resp = httpx.get(
                PDOK_WMS,
                params={
                    "service": "WMS",
                    "request": "GetMap",
                    "version": "1.3.0",
                    "layers": "2022_ortho25",
                    "styles": "",
                    "crs": "EPSG:28992",
                    "bbox": ",".join(f"{v:.1f}" for v in _ext),
                    "width": 900,
                    "height": 900,
                    "format": "image/jpeg",
                },
                timeout=120,
            )
            if _resp.status_code < 500:
                break
            time.sleep(5 * 2**_attempt)
        _resp.raise_for_status()
        assert _resp.headers["content-type"].startswith("image/"), _resp.text[:200]
        _img = np.asarray(Image.open(BytesIO(_resp.content)))
        _fig, _ax = plt.subplots(figsize=(6, 6))
        _ax.imshow(_img, extent=(_ext[0], _ext[2], _ext[1], _ext[3]))
        _ax.scatter(
            _px["x"], _px["y"], s=2, marker="s", facecolors="none", edgecolors="cyan", lw=0.3
        )
        _other = register_rd[~register_rd["heavy"]].cx[_ext[0] : _ext[2], _ext[1] : _ext[3]]
        _ax.scatter(_other.geometry.x, _other.geometry.y, s=25, c="yellow", edgecolor="k")
        _heavy = heavy_rd.cx[_ext[0] : _ext[2], _ext[1] : _ext[3]]
        _ax.scatter(_heavy.geometry.x, _heavy.geometry.y, s=40, c="red", edgecolor="k")
        _ax.set_xlim(_ext[0], _ext[2])
        _ax.set_ylim(_ext[1], _ext[3])
        _ax.set_axis_off()
        _ax.set_title(
            f"{_model} {_site}: {_row['area_ha']:.0f} ha, {_row['province']}, "
            f"{2 * _half / 1000:.1f} km across, PDOK 2022",
            fontsize=8,
        )
        _fig.tight_layout()
        _fig.savefig(_chip, dpi=110, pil_kwargs={"quality": 85})
        plt.close(_fig)
    hand_sample[["model", "province", "area_ha", "registered", "candidate", "d_heavy"]].round(0)
    return (hand_sample,)


@app.cell
def _(HAND_CHECK, hand_sample, np, pd):
    _labels = (
        pd.read_csv(HAND_CHECK, dtype={"site": str})
        if HAND_CHECK.exists()
        else pd.DataFrame(columns=["model", "site", "label", "note"])
    )
    hand = hand_sample.reset_index(names="site").merge(_labels, on=["model", "site"], how="left")

    def wilson(k: int, n: int) -> list[float]:
        """95% Wilson interval for a share k / n."""
        z, p = 1.96, k / n
        centre = (p + z * z / (2 * n)) / (1 + z * z / n)
        half = z * np.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
        return [round(centre - half, 3), round(centre + half, 3)]

    hand_result = {}
    for _model, _h in hand.groupby("model"):
        _n = len(_h)
        _real = _h["label"].isin(["heavy", "light"])
        _unreg = ~_h["registered"]
        hand_result[_model] = {
            "sample": _n,
            "unlabelled": int(_h["label"].isna().sum()),
            "heavy": int((_h["label"] == "heavy").sum()),
            "light": int((_h["label"] == "light").sum()),
            "no": int((_h["label"] == "no").sum()),
            "heavy share, 95% CI": wilson(int((_h["label"] == "heavy").sum()), _n),
            "industrial (heavy or light) share, 95% CI": wilson(int(_real.sum()), _n),
            "not near a heavy register site": int(_unreg.sum()),
            "of those, industrial": int((_real & _unreg).sum()),
            "of those, heavy": int(((_h["label"] == "heavy") & _unreg).sum()),
        }
    hand_result
    return hand, hand_result


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 6: who lives near what the models find?

    Population is the JRC's [GHS-POP R2023A](https://human-settlement.emergency.copernicus.eu/ghs_pop2023.php)
    grid for 2020 at 100 m (CC-BY 4.0), available for the whole world. For each model we
    count the people in 100 m cells whose centre is within 1 km and within 3 km of any
    pixel of a detected site of 5 ha or more. Each cell is counted once, however many
    sites are near it, and cells across the border in Belgium and Germany count too.
    The count is split by whether the site is near a heavy register site (already known
    to a regulator) or not, and repeated for the hand-checked sites that turned out to be
    real industry.
    """)
    return


@app.cell
def _(
    GHS_TILE_URL,
    KDTree,
    MIN_HA,
    RD,
    fetch,
    found,
    from_bounds,
    gpd,
    hand,
    np,
    pd,
    provinces,
    rasterio,
):
    # GHS tiles are 1000 km squares in Mollweide (ESRI:54009); these two cover the provinces.
    _bounds = provinces.to_crs("ESRI:54009").total_bounds + np.array([-4000, -4000, 4000, 4000])
    _cells = []
    for _row in (3, 4):
        _url = GHS_TILE_URL.format(row=_row, col=19)
        _zip = fetch(_url, f"ghs/R{_row}_C19.zip")
        _tif = f"/vsizip/{_zip}/{_url.rsplit('/', 1)[1].removesuffix('.zip')}.tif"
        with rasterio.open(_tif) as _src:
            _win = from_bounds(*_bounds, _src.transform).round_offsets().round_lengths()
            _win = _win.intersection(rasterio.windows.Window(0, 0, _src.width, _src.height))
            _pop = _src.read(1, window=_win)
            _tr = _src.window_transform(_win)
        _r, _c = np.nonzero(_pop > 0)
        _xs, _ys = rasterio.transform.xy(_tr, _r, _c)
        _cells.append(pd.DataFrame({"x": _xs, "y": _ys, "pop": _pop[_r, _c]}))
    _cells = pd.concat(_cells, ignore_index=True)
    _xy = gpd.GeoSeries.from_xy(_cells["x"], _cells["y"], crs="ESRI:54009").to_crs(RD)
    pop_xy, pop = np.c_[_xy.x, _xy.y], _cells["pop"].to_numpy()

    def people_near(px: pd.DataFrame, km: float) -> int:
        """People in GHS-POP cells within km of any of the given site pixels."""
        if not len(px):
            return 0
        d, _ = KDTree(px[["x", "y"]].to_numpy()).query(pop_xy, distance_upper_bound=km * 1000)
        return int(round(pop[np.isfinite(d)].sum()))

    _rows = []
    for _model, (_px, _sites) in found.items():
        _kept = _sites[_sites["area_ha"] >= MIN_HA]
        _real = hand[(hand["model"] == _model) & hand["label"].isin(["heavy", "light"])]
        _groups = {
            "all sites of 5 ha or more": _kept.index,
            "near a heavy register site": _kept.index[_kept["registered"]],
            "not near one": _kept.index[~_kept["registered"]],
            "hand-checked industrial, not near one": _real.loc[~_real["registered"], "site"],
        }
        for _name, _ids in _groups.items():
            _sel = _px[_px["site"].isin(_ids)]
            _rows.append(
                {
                    "model": _model,
                    "sites": _name,
                    "count": len(_ids),
                    "people within 1 km": people_near(_sel, 1),
                    "people within 3 km": people_near(_sel, 3),
                }
            )
    exposure = pd.DataFrame(_rows).set_index(["model", "sites"])
    population_total = int(round(pop.sum()))
    exposure
    return exposure, population_total


@app.cell
def _(MIN_HA, OUT_DIR, RD, found, gpd, heavy_rd, pd, plt, provinces):
    _fig, _axes = plt.subplots(1, 2, figsize=(14, 8))
    for _ax, (_model, (_px, _sites)) in zip(_axes, found.items(), strict=True):
        provinces.to_crs(RD).boundary.plot(ax=_ax, color="grey", lw=0.5)
        _k = _sites[_sites["area_ha"] >= MIN_HA]
        _ax.scatter(
            heavy_rd.geometry.x, heavy_rd.geometry.y, s=4, marker="x", c="k", lw=0.5,
            label="heavy register site",
        )  # fmt: skip
        _ax.scatter(
            _k.loc[_k["registered"], "x"], _k.loc[_k["registered"], "y"], s=6, c="tab:blue",
            label="detected, near a heavy site",
        )  # fmt: skip
        _ax.scatter(
            _k.loc[~_k["registered"], "x"], _k.loc[~_k["registered"], "y"], s=6, c="tab:red",
            label="detected, not near one",
        )  # fmt: skip
        _ax.set_title(f"{_model} model: {len(_k)} sites of {MIN_HA} ha or more")
        _ax.set_axis_off()
    _axes[0].legend(loc="upper left", fontsize=8, markerscale=2)
    _fig.tight_layout()
    _fig.savefig(OUT_DIR / "sites_map.png", dpi=110)
    _out = []
    for _model, (_px, _sites) in found.items():
        _k = _sites[_sites["area_ha"] >= MIN_HA].copy()
        _ll = gpd.GeoSeries.from_xy(_k["x"], _k["y"], crs=RD).to_crs("EPSG:4326")
        _k["lat"], _k["lon"] = _ll.y.round(5).to_numpy(), _ll.x.round(5).to_numpy()
        _k.insert(0, "model", _model)
        _out.append(_k.drop(columns=["x", "y"]))
    pd.concat(_out).round(1).to_csv(OUT_DIR / "sites.csv", index_label="site")
    _fig
    return


@app.cell
def _(
    OUT_DIR,
    exposure,
    hand_result,
    json,
    nl_read,
    pixel_scores,
    population_total,
    province_scores,
    rx_bytes,
    rx_start,
    scan_seconds,
    score_table,
    sector_recall,
    t_start,
    time,
    us_read,
):
    summary = {
        "us_read": us_read,
        "nl_read": nl_read,
        "scan_seconds": scan_seconds,
        "pixel_scores": pixel_scores.to_dict(orient="index"),
        "score_table": [
            {"model": m, "threshold": t, "min_ha": h, **v}
            for (m, t, h), v in score_table.to_dict(orient="index").items()
        ],
        "province_scores": [
            {"model": m, "province": p, **v}
            for (m, p), v in province_scores.to_dict(orient="index").items()
        ],
        "sector_recall": sector_recall.reset_index(names="sector").to_dict("records"),
        "hand_check": hand_result,
        "exposure": [
            {"model": m, "sites": s, **v} for (m, s), v in exposure.to_dict(orient="index").items()
        ],
        "population_in_grid_window": population_total,
        "total_seconds": round(time.perf_counter() - t_start),
        "total_downloaded_gb": round((rx_bytes() - rx_start) / 1e9, 2),
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    summary["total_seconds"]
    return


if __name__ == "__main__":
    app.run()

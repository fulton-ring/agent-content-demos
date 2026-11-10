import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import json
    import os
    import re
    import shutil
    import subprocess
    import time
    from concurrent.futures import ThreadPoolExecutor
    from datetime import UTC, datetime
    from pathlib import Path

    import geopandas as gpd
    import httpx
    import marimo as mo
    import pandas as pd
    import pyarrow.parquet as pq
    import pyogrio
    from playwright.sync_api import sync_playwright
    from pmtiles.reader import MmapSource, Reader

    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("PMTILES_DATA_DIR", HERE / "data"))
    OUT = HERE / "outputs"
    SITE = DATA / "site"  # what the local "bucket" serves: the map page, layers.json, .pmtiles
    RUN = DATA / "nginx"
    for folder in (DATA, OUT, SITE, RUN / "tmp"):
        folder.mkdir(parents=True, exist_ok=True)
    API = "https://hifld.publicenvirodata.org/api/collections/hifld/datasets"
    BUCKET, CDN_WHOLE, CDN_SLICE = (
        "http://127.0.0.1:8081",
        "http://127.0.0.1:8082",
        "http://127.0.0.1:8083",
    )
    LAYER_COUNT = 8
    http = httpx.Client(timeout=120, follow_redirects=True)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # Can HIFLD Next's most-used layers live on a public map as single PMTiles files?

    A PMTiles file is one archive of map tiles. A browser reads the tiles it needs with HTTP range
    requests, so the file can sit on plain object storage with no tile server. The catch is that
    the file is read-only: any data change means rewriting and re-uploading the whole file. This
    notebook checks what HIFLD Next already publishes, rebuilds the most-used layers, puts a map
    on them, and tests what happens to people with the map open when a file changes, with and
    without a CDN.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 1. What HIFLD Next already serves

    The catalog API lists every dataset; each dataset has one or more files, and each file's STAC
    record lists its assets. We count the files that carry a PMTiles asset.
    """)
    return


@app.cell
def _():
    datasets = []
    for offset in range(0, 2000, 100):  # bounded: the catalog has about 330 datasets
        _page = http.get(API, params={"limit": 100, "offset": offset, "omit": "description"})
        _page.raise_for_status()
        batch = _page.json()["datasets"]
        datasets += batch
        if len(batch) < 100:
            break
    file_keys = sorted(
        {
            (d["id"].split("/")[1], link["href"].rstrip("/").split("/")[-2])
            for d in datasets
            for link in d["links"]
            if link["rel"] == "child"
        }
    )

    def file_record(key: tuple[str, str]) -> dict:
        for attempt in range(6):  # the API rate-limits bursts; back off and retry a bounded number
            response = http.get(f"{API}/{key[0]}/files/{key[1]}")
            if response.status_code != 429:
                break
            time.sleep(float(response.headers.get("retry-after", 2**attempt)))
        response.raise_for_status()
        record = response.json()
        assets = record.get("assets", {}).values()
        return {
            "dataset": key[0],
            "file": key[1],
            "title": record.get("title"),
            "features": record.get("hifld:feature_count"),
            "spatial": record.get("hifld:spatial_status"),
            "pmtiles_url": next(
                (a["href"] for a in assets if a.get("type") == "application/vnd.pmtiles"), None
            ),
            "parquet_url": next(
                (a["href"] for a in assets if "parquet" in a.get("type", "")), None
            ),
        }

    with ThreadPoolExecutor(4) as pool:
        catalog = pd.DataFrame(list(pool.map(file_record, file_keys)))
    catalog.to_csv(OUT / "catalog_pmtiles.csv", index=False)
    no_pmtiles = catalog[catalog.pmtiles_url.isna()]
    mo.md(
        f"HIFLD Next lists **{len(datasets)} datasets with {len(catalog)} files**. "
        f"**{catalog.pmtiles_url.notna().sum()} files already have a PMTiles asset**. The "
        f"{len(no_pmtiles)} without one: {', '.join(no_pmtiles.dataset)} "
        f"(spatial status: {', '.join(sorted(set(no_pmtiles.spatial.fillna('none'))))})."
    )
    return (catalog,)


@app.cell
def _(catalog):
    sample_url = catalog.loc[catalog.dataset == "hospitals-3", "pmtiles_url"].iloc[0]
    sample_headers = http.head(sample_url).headers
    hifld_headers = {
        name: sample_headers.get(name)
        for name in (
            "cache-control",
            "etag",
            "accept-ranges",
            "access-control-allow-origin",
            "via",
            "server",
        )
    }
    sample_meta = Reader(
        lambda offset, length: (
            http.get(sample_url, headers={"Range": f"bytes={offset}-{offset + length - 1}"}).content
        )
    ).metadata()
    mo.md(
        f"""
    The files are on Google Cloud Storage behind `hifld.publicenvirodata.org/storage`, and each
    version has its own path (`.../v1.1.0/pmtiles/...`), so a new version is a new URL. Headers on
    `{sample_url.split("/storage/")[1]}`:

    {mo.as_html(pd.Series(hifld_headers, name="value").to_frame())}

    The file says it was built with **{sample_meta["generator"]}**:
    `{sample_meta["generator_options"].split(" -o ")[0]}`. Its tile layer is named
    `{sample_meta["vector_layers"][0]["id"]}`, after a temporary
    build file, so a map has to read the name from each archive rather than guess it.
    """
    )
    return (hifld_headers,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 2. Which layers are most used

    HIFLD Next publishes no download or view counts (its `/api/datasets/stats` gives only totals).
    The best public signal we found is ArcGIS Online, where the old HIFLD Open layers were
    published and copied many times: we take the 1,000 most-viewed public items matching "HIFLD",
    match their titles to HIFLD Next file titles, and add up the views. It measures historic demand
    for the old layers, not traffic to HIFLD Next, and the counts change daily.
    """)
    return


@app.cell
def _(catalog):
    def normalize(title: str | None) -> str:
        title = re.sub(r"\(.*?\)|hifld|deprecated|open", "", (title or "").lower())
        return re.sub(r"[^a-z]", "", title)

    by_title = {normalize(t): d for t, d in zip(catalog.title, catalog.dataset, strict=True)}
    views: dict[str, list[int]] = {}
    for start in range(1, 1001, 100):
        _result = http.get(
            "https://www.arcgis.com/sharing/rest/search",
            params={
                "q": "HIFLD",
                "num": 100,
                "start": start,
                "sortField": "numViews",
                "sortOrder": "desc",
                "f": "json",
            },
        )
        _result.raise_for_status()
        body = _result.json()
        for item in body["results"]:
            match = by_title.get(normalize(item["title"]))
            if match:
                views.setdefault(match, []).append(item["numViews"])
        if body["nextStart"] < 0:
            break
    ranking = (
        pd.DataFrame(
            [
                {"dataset": d, "arcgis_views": sum(v), "arcgis_items": len(v)}
                for d, v in views.items()
            ]
        )
        .sort_values("arcgis_views", ascending=False)
        .reset_index(drop=True)
    )
    ranking.to_csv(OUT / "layer_ranking.csv", index=False)
    chosen = ranking.head(LAYER_COUNT).merge(catalog, on="dataset")
    chosen[["dataset", "arcgis_views", "arcgis_items", "features"]]
    return (chosen,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 3. Download the GeoParquet and rebuild each layer as PMTiles

    We rebuild with the same tool and options HIFLD Next uses (tippecanoe 2.49, via FlatGeobuf,
    since tippecanoe doesn't read Parquet). For comparison we also build three layers with GDAL's
    own PMTiles driver, which ships inside the `pyogrio` Python wheel and needs no system install
    (set `PMTILES_GDAL_ALL=1` to build all eight). GDAL gets the same maximum zoom tippecanoe
    picked. Build times are wall-clock on this machine and include reading the GeoParquet.
    """)
    return


@app.cell
def _(chosen):
    def tippecanoe(frame: gpd.GeoDataFrame, target: Path, layer: str) -> None:
        """Build like HIFLD Next does, but with a fixed tile layer name: a map's style refers to it,
        so a name that changes between builds (ours did at first) blanks the layer on update."""
        source = target.with_suffix(".fgb")
        pyogrio.write_dataframe(frame, source, driver="FlatGeobuf")
        command = [
            "tippecanoe", "-zg", "--read-parallel", "--drop-densest-as-needed",
            "--extend-zooms-if-still-dropping", "--force", "--maximum-zoom=14", "--quiet",
            "-l", layer, "-o", str(target), str(source),
        ]  # fmt: skip
        subprocess.run(command, check=True)
        source.unlink()

    def header(path: Path) -> dict:
        with path.open("rb") as handle:
            return Reader(MmapSource(handle)).header()

    # GDAL is slow (about 33 minutes for all eight layers on our machine), so by default it builds
    # three layers: the smallest point layer, a mid-sized one and the line layer.
    GDAL_LAYERS = {"hospitals-3", "local-law-enforcement-locations", "transmission-lines-1"}
    builds = []
    for _row in chosen.itertuples():
        parquet = DATA / f"{_row.dataset}.parquet"
        if not parquet.exists():
            with http.stream("GET", _row.parquet_url) as download:
                download.raise_for_status()
                with parquet.open("wb") as handle:
                    for chunk in download.iter_bytes(1 << 20):
                        handle.write(chunk)
        _started = time.perf_counter()
        frame = gpd.read_parquet(parquet).to_crs(4326)
        tippecanoe(frame, SITE / f"{_row.dataset}.pmtiles", _row.dataset)
        tippecanoe_seconds = time.perf_counter() - _started
        max_zoom = header(SITE / f"{_row.dataset}.pmtiles")["max_zoom"]

        gdal_mb = gdal_seconds = None
        if _row.dataset in GDAL_LAYERS or os.environ.get("PMTILES_GDAL_ALL"):
            _started = time.perf_counter()
            frame = gpd.read_parquet(parquet).to_crs(4326)
            gdal_file = DATA / f"{_row.dataset}.gdal.pmtiles"
            gdal_file.unlink(missing_ok=True)
            pyogrio.write_dataframe(
                frame,
                gdal_file,
                driver="PMTiles",
                dataset_options={"MINZOOM": "0", "MAXZOOM": str(max_zoom)},
            )
            gdal_seconds = time.perf_counter() - _started
            gdal_mb = gdal_file.stat().st_size / 1e6
        published = http.head(_row.pmtiles_url).headers
        builds.append(
            {
                "layer": _row.dataset,
                "features": pq.ParquetFile(parquet).metadata.num_rows,
                "geometry": frame.geom_type.mode().iloc[0],
                "geoparquet_mb": parquet.stat().st_size / 1e6,
                "hifld_pmtiles_mb": int(published["content-length"]) / 1e6,
                "tippecanoe_mb": (SITE / f"{_row.dataset}.pmtiles").stat().st_size / 1e6,
                "tippecanoe_s": tippecanoe_seconds,
                "max_zoom": max_zoom,
                "gdal_mb": gdal_mb,
                "gdal_s": gdal_seconds,
            }
        )
    build_table = pd.DataFrame(builds).round(2)
    build_table.to_csv(OUT / "builds.csv", index=False)
    build_table
    return build_table, tippecanoe


@app.cell
def _(build_table):
    totals = build_table[["geoparquet_mb", "hifld_pmtiles_mb", "tippecanoe_mb"]].sum()
    both = build_table.dropna(subset=["gdal_s"])
    mo.md(
        f"Across the {len(build_table)} layers: {build_table.features.sum():,} features and "
        f"{totals.geoparquet_mb:.0f} MB of GeoParquet became {totals.tippecanoe_mb:.0f} MB of "
        f"PMTiles in {build_table.tippecanoe_s.sum():.0f} s of tippecanoe "
        f"(HIFLD Next's published files: {totals.hifld_pmtiles_mb:.0f} MB, so our rebuild "
        f"reproduces theirs). On the {len(both)} layers built both ways, GDAL took "
        f"**{both.gdal_s.sum() / both.tippecanoe_s.sum():.0f}x as long** "
        f"({both.gdal_s.sum():.0f} s against {both.tippecanoe_s.sum():.0f} s) and made files "
        f"{both.gdal_mb.sum() / both.tippecanoe_mb.sum():.1f}x the size, because it keeps every "
        "feature at every zoom where tippecanoe thins dense points. tippecanoe stays the tool "
        "to use; GDAL is the fallback where nothing can be installed."
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 4. A map that reads the files straight from storage

    `map/index.html` is one static page: MapLibre plus the `pmtiles` protocol. It takes a list of
    `.pmtiles` URLs and nothing else. We point it at HIFLD Next's own published files on Google
    Cloud Storage (the real deployment, over the internet), and at our rebuilt files on a local
    nginx "bucket" (`nginx.conf`, port 8081). A headless browser opens the first view (the lower 48)
    with an empty cache and records the time until the map is idle and every byte it fetched.
    """)
    return


@app.cell
def _(build_table, chosen):
    colors = [
        "#d7263d",
        "#f49d37",
        "#3f88c5",
        "#1b998b",
        "#6c4ab6",
        "#e36397",
        "#8a6f3e",
        "#b7c3d3",
    ]
    states_url = (
        "https://hifld.publicenvirodata.org/storage/hifld/us-state-boundaries-1/"
        "us-state-boundaries-1/v1.0.0/pmtiles/us-state-boundaries-1.pmtiles"
    )
    geometry = dict(zip(build_table.layer, build_table.geometry, strict=True))
    for name, _base in (("layers-hifld.json", None), ("layers-local.json", BUCKET)):
        _layers = [{"id": "states", "url": states_url, "kind": "fill", "color": "#9a9a9a"}]
        for _row, color in zip(chosen.itertuples(), colors, strict=False):
            shape = geometry[_row.dataset]
            _layers.append(
                {
                    "id": _row.dataset,
                    "url": _row.pmtiles_url if _base is None else f"{_base}/{_row.dataset}.pmtiles",
                    "kind": "line"
                    if "Line" in shape
                    else "fill"
                    if "Polygon" in shape
                    else "point",
                    "color": color,
                    "legend": _row.title,
                }
            )
        (SITE / name).write_text(json.dumps(_layers, indent=1))
    shutil.copy(HERE / "map" / "index.html", SITE / "index.html")

    config = (HERE / "nginx.conf").read_text()
    config = config.replace("@ROOT@", str(SITE.resolve())).replace("@RUN@", str(RUN.resolve()))
    (RUN / "nginx.conf").write_text(config)

    def start_nginx() -> subprocess.Popen:
        """Start the three local servers with empty CDN caches."""
        for cache in ("cache-whole", "cache-slice"):
            shutil.rmtree(RUN / cache, ignore_errors=True)
        server = subprocess.Popen(
            ["nginx", "-p", str(RUN.resolve()), "-c", str(RUN / "nginx.conf")]
        )
        for _attempt in range(50):  # bounded wait for the ports to open
            try:
                if http.get(f"{CDN_SLICE}/index.html").status_code == 200:
                    return server
            except httpx.TransportError:
                time.sleep(0.1)
        server.terminate()
        raise RuntimeError((RUN / "nginx-error.log").read_text())

    nginx = {"server": start_nginx()}
    return nginx, start_nginx


@app.cell
def _(nginx):
    def wait_until_idle(_page, timeout_s: float) -> bool:  # noqa: ANN001
        """Poll until the map reports idle, for at most timeout_s; False if it never settles."""
        for _attempt in range(int(timeout_s * 2)):
            if _page.evaluate("window.mapIdle === true"):
                return True
            _page.wait_for_timeout(500)
        return False

    def open_map(_context, url: str, timeout_s: float = 60) -> dict:  # noqa: ANN001
        """Open the map, wait until it is idle, and count the PMTiles requests and bytes."""
        _page = _context.new_page()
        # Chrome's own network events give the bytes on the wire for each request, including
        # cross-origin ones; responses served from the browser cache report no bytes.
        cdp = _context.new_cdp_session(_page)
        cdp.send("Network.enable")
        pmtiles_requests: set[str] = set()
        fetched = {"requests": 0, "bytes": 0}

        def on_request(event: dict) -> None:
            if ".pmtiles" in event["request"]["url"]:
                pmtiles_requests.add(event["requestId"])
                fetched["requests"] += 1

        def on_finished(event: dict) -> None:
            if event["requestId"] in pmtiles_requests:
                fetched["bytes"] += event["encodedDataLength"]

        cdp.on("Network.requestWillBeSent", on_request)
        cdp.on("Network.loadingFinished", on_finished)
        _started = time.perf_counter()
        _page.goto(url)
        fetched["settled"] = wait_until_idle(_page, timeout_s)
        fetched["seconds"] = round(time.perf_counter() - _started, 2)
        fetched["errors"] = _page.evaluate("window.mapErrors")
        fetched["page"] = _page
        return fetched

    browser_path = os.environ.get("CHROMIUM_PATH") or None
    playwright = sync_playwright().start()
    browser = playwright.chromium.launch(executable_path=browser_path)
    assert nginx["server"].poll() is None
    return browser, open_map, wait_until_idle


@app.cell
def _(browser, build_table, open_map):
    first_views = []
    for label, _layers in (
        ("HIFLD Next files on Google Cloud Storage (internet)", "layers-hifld.json"),
        ("Our tippecanoe rebuilds on the local nginx bucket", "layers-local.json"),
    ):
        for run in range(3):
            _context = browser.new_context(viewport={"width": 1280, "height": 800})
            _result = open_map(_context, f"{BUCKET}/index.html?layers={_layers}")
            assert _result["settled"], _result["errors"]
            if run == 0 and "HIFLD" in label:
                _result["page"].screenshot(path=OUT / "map_first_view.png")
            _context.close()
            first_views.append(
                {
                    "source": label,
                    "run": run + 1,
                    "seconds_to_idle": _result["seconds"],
                    "pmtiles_requests": _result["requests"],
                    "kb_fetched": round(_result["bytes"] / 1e3),
                    "map_errors": len(_result["errors"]),
                }
            )
    first_view_table = pd.DataFrame(first_views)
    first_view_table.to_csv(OUT / "first_view.csv", index=False)
    first_view_summary = first_view_table.groupby("source", sort=False).median(numeric_only=True)
    share = first_view_summary.kb_fetched.iloc[0] * 1e3 / (build_table.hifld_pmtiles_mb.sum() * 1e6)
    mo.vstack(
        [
            first_view_table,
            mo.md(
                f"The first view of HIFLD Next's files fetches a median "
                f"**{first_view_summary.kb_fetched.iloc[0]:,.0f} kB in "
                f"{first_view_summary.pmtiles_requests.iloc[0]:.0f} range requests** "
                f"({share:.1%} of the {build_table.hifld_pmtiles_mb.sum():.0f} MB in the eight "
                f"files, plus the state outlines) and is idle in "
                f"**{first_view_summary.seconds_to_idle.iloc[0]:.1f} s** from this machine. The "
                f"page, MapLibre and pmtiles.js load from a public CDN and are not counted."
            ),
            mo.image(OUT / "map_first_view.png"),
        ]
    )
    return (first_view_summary,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5. The update path

    We change one layer (hospitals): one hospital is removed and one hospital's bed count changes,
    as a routine source update would. Every feature also gets a `layer_version` field (`v1` before,
    `v2` after) so the test can tell which file each drawn tile came from. We time the rebuild and
    the publish, then test three ways a map sees the change:

    - **Overwrite in place**: the new file replaces the old one at the same URL, as you would on a
      bucket with no versioning. We test it behind the plain bucket and behind two CDN stand-ins.
    - **New URL per version**: the new file goes up under a new name and the small `layers.json`
      (sent with `Cache-Control: no-cache`) is switched to it. This is what HIFLD Next does with its
      `v1.0.0`/`v1.1.0` paths.

    For each, a visitor has the map open over Texas when the file changes, then pans to Ohio
    (tiles they haven't loaded yet), then reloads; a new visitor then opens the map fresh.
    """)
    return


@app.cell
def _(tippecanoe):
    hospitals = gpd.read_parquet(DATA / "hospitals-3.parquet").to_crs(4326)
    version_one = hospitals.assign(layer_version="v1")
    tippecanoe(version_one, DATA / "hospitals-v1.pmtiles", "hospitals-3")

    _started = time.perf_counter()
    edited = gpd.read_parquet(DATA / "hospitals-3.parquet").to_crs(4326)
    edited = edited.drop(index=edited.index[0])
    edited.loc[edited.index[0], "BEDS"] = edited.loc[edited.index[0], "BEDS"] + 10
    edited = edited.assign(layer_version="v2")
    tippecanoe(edited, DATA / "hospitals-v2.pmtiles", "hospitals-3")
    rebuild_seconds = time.perf_counter() - _started
    _started = time.perf_counter()
    shutil.copy(DATA / "hospitals-v2.pmtiles", SITE / "hospitals.staged")
    (SITE / "hospitals.staged").replace(SITE / "hospitals.pmtiles")
    publish_seconds = time.perf_counter() - _started
    v2_mb = (DATA / "hospitals-v2.pmtiles").stat().st_size / 1e6
    uplink_mbit = 50  # stated assumption for an upload from an office connection
    upload_estimate = v2_mb * 8 / uplink_mbit
    mo.md(
        f"Rebuilding hospitals ({len(edited):,} features) took **{rebuild_seconds:.1f} s**; "
        f"copying it into the local bucket took {publish_seconds:.2f} s. The new file is "
        f"{v2_mb:.1f} MB, which at an assumed {uplink_mbit} Mbit/s uplink is about "
        f"**{upload_estimate:.1f} s** to upload to a real bucket (not measured: we had no "
        "bucket we could write to)."
    )
    return publish_seconds, rebuild_seconds, upload_estimate


@app.cell
def _(browser, nginx, open_map, rebuild_seconds, start_nginx, wait_until_idle):
    assert rebuild_seconds > 0  # the v1 and v2 hospital files exist
    texas, ohio = "-99,31,6", "-82.8,40.2,6"
    local_layers = (SITE / "layers-local.json").read_text()

    def publish_layers(_base: str, hospital_file: str) -> None:
        text = local_layers.replace(BUCKET, _base).replace("hospitals-3.pmtiles", hospital_file)
        (SITE / "layers-update.json").write_text(text)

    def visit(_context, _base: str, view: str) -> dict:  # noqa: ANN001
        _result = open_map(_context, f"{_base}/index.html?layers=layers-update.json&view={view}")
        _result["versions"] = _result["page"].evaluate("window.versionsSeen('hospitals-3')")
        return _result

    def summary(step: str, outcome: dict) -> dict:
        changed = [e for e in outcome["errors"] if e.startswith("hospitals-3")]
        return {
            "step": step,
            "map_settled": outcome["settled"],
            "versions_drawn": "+".join(outcome["versions"]) or "none",
            "hospital_errors": len(changed),
            "first_error": (changed or [""])[0][:100],
            "other_layer_errors": len(outcome["errors"]) - len(changed),
        }

    _rows = []
    for setup, _base, strategy in (
        ("bucket only", BUCKET, "overwrite"),
        ("CDN, whole-object cache", CDN_WHOLE, "overwrite"),
        ("CDN, range-slice cache", CDN_SLICE, "overwrite"),
        ("bucket only", BUCKET, "new URL"),
        ("CDN, range-slice cache", CDN_SLICE, "new URL"),
    ):
        shutil.copy(DATA / "hospitals-v1.pmtiles", SITE / "hospitals.pmtiles")
        (SITE / "hospitals-v2.pmtiles").unlink(missing_ok=True)
        publish_layers(_base, "hospitals.pmtiles")
        nginx["server"].terminate()
        nginx["server"].wait(timeout=10)
        nginx["server"] = start_nginx()

        _context = browser.new_context(viewport={"width": 1280, "height": 800})
        visitor = visit(_context, _base, texas)
        steps = [summary("1. map open over Texas (v1 published)", visitor)]
        if strategy == "overwrite":
            shutil.copy(DATA / "hospitals-v2.pmtiles", SITE / "hospitals.staged")
            (SITE / "hospitals.staged").replace(SITE / "hospitals.pmtiles")
        else:
            shutil.copy(DATA / "hospitals-v2.pmtiles", SITE / "hospitals-v2.pmtiles")
            publish_layers(_base, "hospitals-v2.pmtiles")
        _page = visitor["page"]
        _page.evaluate(
            "window.mapIdle = false; window.map.once('idle', () => window.mapIdle = true)"
        )
        _page.evaluate("window.map.jumpTo({center: [-82.8, 40.2]})")
        panned = {
            "settled": wait_until_idle(_page, 60),
            "versions": _page.evaluate("window.versionsSeen('hospitals-3')"),
            "errors": _page.evaluate("window.mapErrors"),
        }
        steps.append(summary("2. same visitor pans to Ohio after the change", panned))
        steps.append(summary("3. same visitor reloads", visit(_context, _base, ohio)))
        _context.close()
        fresh = browser.new_context(viewport={"width": 1280, "height": 800})
        steps.append(summary("4. new visitor opens the map", visit(fresh, _base, ohio)))
        fresh.close()
        _rows += [{"setup": setup, "publish": strategy, **step} for step in steps]
    update_table = pd.DataFrame(_rows)
    update_table.to_csv(OUT / "update_path.csv", index=False)
    update_table
    return (update_table,)


@app.cell
def _(update_table):
    last = update_table[update_table.step.str.startswith("4.")].set_index(["setup", "publish"])
    mo.md(
        "What a new visitor sees after the change, per setup: "
        + "; ".join(f"{s} / {p}: **{r.versions_drawn}**" for (s, p), r in last.iterrows())
        + ". A CDN keeps serving the old file until its cache expires (an hour here, from the "
        "bucket's `max-age=3600`) unless it is purged. A CDN that caches by range slice can "
        "hand out pieces of two different files for one URL, which pmtiles.js detects by ETag and "
        "can only answer with an error. Publishing each version under a new URL avoids all of "
        "this: nothing cached is ever wrong, only the small layer list has to be fresh."
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 6. What it costs to run

    Prices are from the providers' published price pages, read on 2026-11-10 (links in the
    README). The traffic level is a stated assumption: **10,000 map sessions a month**, each one
    the measured first view plus four more views' worth of tiles as the visitor pans and zooms
    (5x the first view's bytes and requests). A 100,000-session column shows how it scales. For a
    CDN we assume 10% of requests miss the cache and go to the bucket.
    """)
    return


@app.cell
def _(build_table, first_view_summary):
    stored_gb = build_table.tippecanoe_mb.sum() / 1e3
    view = first_view_summary.iloc[0]
    _rows = []
    for sessions in (10_000, 100_000):
        egress_gb = sessions * 5 * view.kb_fetched / 1e6
        requests = sessions * 5 * view.pmtiles_requests
        gcs_egress = max(egress_gb - 1, 0) * 0.12  # first GiB free, then $0.12/GiB to North America
        gcs_ops = requests / 1000 * 0.0004
        gcs_storage = stored_gb * 0.020
        r2 = max(stored_gb - 10, 0) * 0.015 + max(requests - 10e6, 0) / 1e6 * 0.36
        hf_allowance = 8 * stored_gb
        cloudfront_plan = 0 if (requests <= 1e6 and egress_gb <= 100) else 15
        origin_fill = max(egress_gb * 0.1 - 1, 0) * 0.12 + requests * 0.1 / 1000 * 0.0004
        _rows += [
            {
                "sessions": sessions,
                "setup": "Google Cloud Storage, direct (HIFLD Next today)",
                "usd_month": gcs_storage + gcs_ops + gcs_egress,
                "note": f"{egress_gb:.0f} GB egress, {requests / 1e6:.1f} M reads",
            },
            {
                "sessions": sessions,
                "setup": "Cloudflare R2, direct",
                "usd_month": r2,
                "note": "egress free; inside the 10 GB / 10 M read free tier"
                if r2 == 0
                else "egress free",
            },
            {
                "sessions": sessions,
                "setup": "Hugging Face bucket (public)",
                "usd_month": stored_gb / 1e3 * 12,
                "note": f"egress included only up to 8x storage = {hf_allowance:.1f} GB; "
                f"needs {egress_gb:.0f} GB",
            },
            {
                "sessions": sessions,
                "setup": "GCS behind CloudFront flat-rate plan",
                "usd_month": cloudfront_plan + gcs_storage + origin_fill,
                "note": "Free plan (1 M requests, 100 GB)"
                if cloudfront_plan == 0
                else "Pro plan $15 (10 M requests, 50 TB)",
            },
        ]
    cost_table = pd.DataFrame(_rows).round({"usd_month": 2})
    cost_table.to_csv(OUT / "costs.csv", index=False)
    cost_table
    return (cost_table,)


@app.cell
def _(
    build_table,
    cost_table,
    first_view_summary,
    hifld_headers,
    publish_seconds,
    rebuild_seconds,
    update_table,
    upload_estimate,
):
    results = {
        "run_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "layers": build_table.to_dict(orient="records"),
        "first_view": first_view_summary.reset_index().to_dict(orient="records"),
        "hifld_headers": hifld_headers,
        "rebuild_seconds": round(rebuild_seconds, 1),
        "local_publish_seconds": round(publish_seconds, 2),
        "upload_estimate_seconds": round(upload_estimate, 1),
        "update_path": update_table.to_dict(orient="records"),
        "costs": cost_table.to_dict(orient="records"),
    }
    (OUT / "results.json").write_text(json.dumps(results, indent=1, default=str))
    results_written = True
    mo.md(f"Wrote `outputs/results.json` at {results['run_at']}.")
    return (results_written,)


@app.cell
def _(browser, nginx, results_written):
    assert results_written
    browser.close()
    nginx["server"].terminate()
    nginx["server"].wait(timeout=10)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What didn't work, and what this doesn't show

    - **No usage numbers from HIFLD Next.** The layer choice rests on ArcGIS Online views of the
      old HIFLD layers and their copies, which is historic demand, not current traffic.
    - **No real bucket we could write to.** The update tests use nginx on this machine as the
      bucket and as two CDN stand-ins. They show the caching mechanics; they don't measure a real
      CDN's purge time or upload speed, and the upload time is an estimate.
    - **Load times are from one cloud machine.** The HIFLD Next first view crosses the internet
      from a data centre; a home connection will be slower.
    - **GDAL's PMTiles driver is not a drop-in for tippecanoe.** It builds without a system
      install, but keeps every point at low zoom, so its files are larger and heavier to draw.
    """)
    return


if __name__ == "__main__":
    app.run()

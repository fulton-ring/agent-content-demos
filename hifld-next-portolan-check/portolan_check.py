import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(r"""
    # Does HIFLD Next pass Portolan's checks?

    [Portolan](https://portolan-sdi.org) is the Cloud-Native Geospatial Forum's spec for publishing geospatial data
    as plain files in object storage: GeoParquet, PMTiles and COG described by a static STAC catalog, with a
    README and an AGENTS.md beside every catalog and collection. [HIFLD Next](https://hifld.publicenvirodata.org)
    was built before Portolan existed. This notebook asks:

    1. Does HIFLD Next's published catalog pass Portolan's validator today? Which rules fail, and how often?
    2. If we generate the fixes as files a pipeline could write, on a local copy, what still fails?
    3. What does HIFLD Next do that Portolan doesn't describe?

    The validator is [rashid](https://pypi.org/project/rashid/), the engine behind `portolan check`. We call it
    directly because it can read a catalog over HTTPS. Its versions are pinned in `pyproject.toml`.
    Nothing here changes the production catalog. The fixes are written to `data/fixed/`, which is not committed.
    """)
    return (mo,)


@app.cell
def _():
    import collections
    import gzip
    import hashlib
    import io
    import json
    import math
    import os
    import random
    import re
    import shutil
    import subprocess
    import sys
    import time
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path, PurePosixPath

    import mapbox_vector_tile
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    from pmtiles.reader import Reader
    from rashid.registry import CHECKS
    from rashid.remote import crawl, split_catalog_url

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("OUTPUT_DIR", HERE / "outputs"))
    WORK = Path(os.environ.get("WORK_DIR", HERE / "data"))
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    CATALOG_URL = os.environ.get(
        "HIFLD_CATALOG_URL", "https://storage.googleapis.com/hifld-next-datasets-prod/catalog.json"
    )
    SITE = os.environ.get("HIFLD_SITE_URL", "https://hifld.publicenvirodata.org")
    RASHID = str(Path(sys.executable).parent / "rashid")
    SEED = 205
    DATA_SAMPLE = 25
    DATA_SAMPLE_MAX_BYTES = 1_000_000_000
    STARTED = time.time()
    return (
        CATALOG_URL,
        CHECKS,
        OUT,
        Path,
        PurePosixPath,
        RASHID,
        Reader,
        SEED,
        DATA_SAMPLE,
        DATA_SAMPLE_MAX_BYTES,
        SITE,
        STARTED,
        ThreadPoolExecutor,
        WORK,
        collections,
        crawl,
        gzip,
        hashlib,
        io,
        json,
        mapbox_vector_tile,
        math,
        os,
        pd,
        plt,
        random,
        re,
        shutil,
        split_catalog_url,
        subprocess,
        time,
        urllib,
    )


@app.cell
def _(CHECKS, RASHID, collections, mo, subprocess):
    _versions = {
        tool: subprocess.run([RASHID.replace("rashid", tool), "--version"], capture_output=True, text=True, check=True)
        .stdout.strip()
        .split()[-1]
        for tool in ("rashid", "portolan")
    }
    rule_families = collections.Counter(rule_id.split("-")[1] for rule_id in CHECKS)
    print(f"rashid {_versions['rashid']}, portolan-cli {_versions['portolan']}: {len(CHECKS)} rules")
    mo.md(f"""
    ## The validator

    rashid **{_versions["rashid"]}** (behind portolan-cli **{_versions["portolan"]}**) knows **{len(CHECKS)}** rules,
    `PTL-<family>-<n>`. Each cites the spec requirement it enforces. They fall in four passes: metadata (links,
    sidecar files, licence, provenance, visualization), STAC 1.1.0 structure, data (reads asset bytes: checksum, size,
    GeoParquet and PMTiles layout) and live (HTTP range and CORS on the host). Families and rule counts:
    {", ".join(f"{family} {count}" for family, count in sorted(rule_families.items()))}.
    """)
    return


@app.cell
def _(CATALOG_URL, OUT, RASHID, json, mo, subprocess, time):
    mo.md("""
    ## Step 1: validate the published catalog

    HIFLD Next serves a STAC API at `/stac`, and rashid can't read an API: it wants a `catalog.json` to start
    from. Asked for `https://hifld.publicenvirodata.org/stac/catalog.json`, it fails at the first rule (PTL-GEN-000).
    The pipeline also writes a static STAC tree to its storage bucket, and that is what Portolan describes, so we
    validate that tree. rashid follows every link from the root `catalog.json`. This step runs the metadata and
    structural passes over all of it. The byte-level data pass comes in step 3, on a sample.
    """)
    _t = time.time()
    _run = subprocess.run(
        [RASHID, "check", CATALOG_URL, "--no-data", "--no-live", "--json"], capture_output=True, text=True
    )
    assert _run.returncode in (0, 1), _run.stderr[-2000:]
    published = json.loads(_run.stdout)
    published_seconds = time.time() - _t
    (OUT / "validator_published.json").write_text(json.dumps(published, indent=1))
    print(
        f"published catalog: {published['files_checked']} documents, {published['error_count']} errors, "
        f"{published['warning_count']} warnings, {published['info_count']} info in {published_seconds:.0f}s"
    )
    return (published,)


@app.cell
def _(CATALOG_URL, OUT, RASHID, json, mo, subprocess, time):
    _t = time.time()
    _run = subprocess.run(
        [RASHID, "check", CATALOG_URL, "--no-data", "--live", "--json", "--all"], capture_output=True, text=True
    )
    assert _run.returncode in (0, 1), _run.stderr[-2000:]
    live_findings = [f for f in json.loads(_run.stdout)["findings"] if f["rule_id"].startswith("PTL-LIV")]
    (OUT / "validator_live.json").write_text(json.dumps(live_findings, indent=1))
    print(f"live pass: {len(live_findings)} findings in {time.time() - _t:.0f}s")
    for _f in live_findings:
        print(f"  {_f['rule_id']} {_f['severity']}: {_f['message'][:160]}")
    mo.md(f"""
    **Hosting (live pass).** rashid sends a HEAD request to every link target and probes the assets for HTTP range
    support and CORS headers, which browsers and DuckDB need to read files in place. It took
    {time.time() - _t:.0f} s and reported **{len(live_findings)}** live findings, listed above. Range and CORS pass.
    What fails is the two root files that don't exist, and a root `self` link that names the release folder
    rather than the bucket root it is published under.
    """)
    return


@app.cell
def _(CATALOG_URL, WORK, crawl, shutil, split_catalog_url):
    # The same tree on disk: the base for the per-object counts below and for the fixes in step 4.
    PUBLISHED_DIR = WORK / "published"
    shutil.rmtree(PUBLISHED_DIR, ignore_errors=True)
    _base, _root = split_catalog_url(CATALOG_URL)
    _crawl = crawl(_base, PUBLISHED_DIR)
    assert not _crawl.capped and not _crawl.errors, _crawl.errors
    published_docs = sorted(p.relative_to(PUBLISHED_DIR).as_posix() for p in PUBLISHED_DIR.rglob("*.json"))
    missing_sidecars = sorted(url for url, status in _crawl.statuses.items() if status != 200)
    print(f"crawled {len(published_docs)} documents; sidecars that answered non-200: {missing_sidecars}")
    return PUBLISHED_DIR, published_docs


@app.cell
def _(re):
    def layer_of(path: str) -> str | None:
        """The HIFLD layer a document belongs to: the folder after `hifld/`, or None for the two top catalogs."""
        match = re.search(r"(?:^|/)hifld/([^/]+)/", path)
        return match.group(1) if match else None

    def pass_counts(report: dict, docs: list[str]) -> dict[str, tuple[int, int]]:
        """Objects with no error finding, of the total, for catalogs, collections and layers."""
        failing = {f["path"] for f in report["findings"] if f["severity"] == "error"}
        catalogs = [d for d in docs if d.endswith("catalog.json")]
        collections_ = [d for d in docs if d.endswith("collection.json")]
        layers = {layer_of(d) for d in docs} - {None}
        failing_layers = {layer_of(p) for p in failing} - {None}
        return {
            "catalogs": (sum(d not in failing for d in catalogs), len(catalogs)),
            "collections": (sum(d not in failing for d in collections_), len(collections_)),
            "layers": (len(layers - failing_layers), len(layers)),
        }

    return (pass_counts,)


@app.cell
def _(mo, pass_counts, pd, published, published_docs):
    published_counts = pass_counts(published, published_docs)
    published_rules = pd.DataFrame(published["summary"]["by_rule"])[
        ["rule_id", "severity", "count", "file_count", "description"]
    ]
    print("published pass counts (passing, total):", published_counts)
    mo.vstack(
        [
            mo.md(
                "**Objects with no error**, of the total: "
                + "; ".join(f"{k} {p} of {n}" for k, (p, n) in published_counts.items())
                + ". A layer is one HIFLD dataset (330). Each has a catalog, one sub-catalog per file and one "
                "collection per file version."
            ),
            mo.md("**Findings by rule**, published catalog:"),
            published_rules,
        ]
    )
    return published_counts, published_rules


@app.cell
def _(mo):
    mo.md(r"""
    ### What each failure means

    Most of the errors come from one thing. The pipeline writes **absolute** URLs into the tree, and they point at
    two copies of the catalog: `releases/<id>/…` and the bucket root. Portolan wants a self-contained tree with
    relative links. So every child, parent and root link "does not resolve" (PTL-LNK-006), every object looks
    orphaned (PTL-LNK-002), and the AGENTS.md and README.md links that every object has are rejected for being
    absolute (PTL-FIL-002, -003). The files themselves are there: 1,381 of 1,383 objects have both. The root
    catalog has neither, and its relative links to them return 404 (PTL-FIL-001).

    The rest are real metadata gaps. HIFLD Next declares itself a mirror (`portolan:mirror`), and a mirror must
    record a sync time (`updated`) and a `via` link to the original source. 523 collections say `license: other`
    with no link to licence text. Visualization rules want a thumbnail, a MapLibre style and `pmtiles:layers` on
    the PMTiles link. The pipeline already writes all three, but only for the 8 raster collections.
    Collection IDs contain slashes (`hifld/hospitals-3/hospitals-3/v1.0.0`), which is a warning, and the
    collection READMEs are one line that names neither licence nor source, also a warning.
    """)
    return


@app.cell
def _(DATA_SAMPLE, DATA_SAMPLE_MAX_BYTES, PUBLISHED_DIR, SEED, WORK, json, mo, random, shutil):
    mo.md(f"""
    ## Step 2: a sample through the data pass

    The data pass reads every byte of every asset it checks: the checksum and size, then the GeoParquet layout
    (version, row groups, statistics, spatial ordering) and the PMTiles tile sizes. HIFLD Next's assets add up to
    about 600 GB (265 GB of it GeoPackage), too much for this sandbox. So we check the cloud-native assets
    (GeoParquet and PMTiles) of **{DATA_SAMPLE}** collections drawn with seed {SEED} from those whose two files
    together are under {DATA_SAMPLE_MAX_BYTES / 1e9:.0f} GB. Each sampled collection is copied into a small local
    catalog with only those two assets. Their hrefs still point at the live bucket, so rashid reads the published
    bytes.
    """)
    _cloud_types = {"application/vnd.apache.parquet", "application/vnd.pmtiles"}
    _candidates = []
    for _p in sorted(PUBLISHED_DIR.rglob("collection.json")):
        _d = json.loads(_p.read_text())
        _assets = {k: a for k, a in _d["assets"].items() if a.get("type") in _cloud_types}
        _size = sum(a.get("file:size", 0) for a in _assets.values())
        if _assets and _size < DATA_SAMPLE_MAX_BYTES:
            _candidates.append((_d, _assets))
    data_sample = random.Random(SEED).sample(_candidates, DATA_SAMPLE)
    SAMPLE_DIR = WORK / "data-sample"
    shutil.rmtree(SAMPLE_DIR, ignore_errors=True)
    SAMPLE_DIR.mkdir(parents=True)
    _root = {
        "type": "Catalog",
        "id": "hifld-data-sample",
        "stac_version": "1.1.0",
        "description": "Sample of HIFLD Next collections for the data pass",
        "links": [{"rel": "root", "href": "./catalog.json", "type": "application/json"}],
    }
    for _i, (_d, _assets) in enumerate(data_sample):
        _dir = SAMPLE_DIR / f"c{_i:02d}"
        _dir.mkdir()
        _links = [{"rel": "root", "href": "../catalog.json"}, {"rel": "parent", "href": "../catalog.json"}]
        _dir.joinpath("collection.json").write_text(
            json.dumps({**_d, "id": f"c{_i:02d}", "assets": _assets, "links": _links})
        )
        _root["links"].append({"rel": "child", "href": f"./c{_i:02d}/collection.json"})
    SAMPLE_DIR.joinpath("catalog.json").write_text(json.dumps(_root))
    data_sample_bytes = sum(a.get("file:size", 0) for _d, _a in data_sample for a in _a.values())
    print(
        f"data sample: {len(data_sample)} of {len(_candidates)} eligible collections, {data_sample_bytes / 1e9:.2f} GB"
    )
    return SAMPLE_DIR, data_sample


@app.cell
def _(OUT, RASHID, SAMPLE_DIR, data_sample, json, mo, pd, subprocess, time):
    _t = time.time()
    _run = subprocess.run(
        [RASHID, "check", str(SAMPLE_DIR), "--data", "--no-live", "--json", "--all"], capture_output=True, text=True
    )
    assert _run.returncode in (0, 1), _run.stderr[-2000:]
    _report = json.loads(_run.stdout)
    data_findings = [f for f in _report["findings"] if f["rule_id"].startswith("PTL-DAT")]
    (OUT / "validator_data_sample.json").write_text(
        json.dumps(
            {
                "collections": [d["id"] for d, _a in data_sample],
                "seconds": round(time.time() - _t),
                "findings": data_findings,
            },
            indent=1,
        )
    )
    _by_rule = (
        pd.DataFrame(data_findings)
        .groupby(["rule_id", "severity"])
        .agg(count=("path", "size"), collections=("path", "nunique"), example=("message", "first"))
        .reset_index()
        if data_findings
        else pd.DataFrame()
    )
    _clean = len(data_sample) - len({f["path"] for f in data_findings if f["severity"] == "error"})
    print(
        f"data pass: {len(data_findings)} findings; {_clean} of {len(data_sample)} collections with no data error; "
        f"{time.time() - _t:.0f}s"
    )
    mo.vstack(
        [
            mo.md(
                f"**Data pass**: {_clean} of {len(data_sample)} sampled collections have no data error: sizes, "
                "GeoParquet version, row groups, statistics and PMTiles tile sizes all pass. The checksums can't be "
                "verified: the pipeline writes MD5 multihashes (code `0xd5`), and rashid only computes SHA2-256 "
                "(`1220…`). The fix is to hash with SHA2-256 at publish time, which the pipeline already does for "
                "its style and thumbnail files."
            ),
            _by_rule,
        ]
    )
    return (data_findings,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 3: generate the fixes

    Each fix below is something the publishing pipeline could write at build time. Here it runs on the local copy
    in `data/published/` and writes `data/fixed/`. Nothing is edited by hand, and asset hrefs still point at the
    live bucket.

    1. **One tree, relative links.** Drop the `releases/<id>/` prefix, rewrite root, parent and child links as
       paths relative to each file, drop the absolute `self` links, and point `agents`/`describedby` at `./AGENTS.md`
       and `./README.md`.
    2. **Root README.md and AGENTS.md**, generated from the catalog.
    3. **Mirror fields.** `updated` from the pipeline's own `hifld:updated_at`. A `via` link to the source: the
       `Download:` URL in the description when there is one, else the DataLumos archive in `derived_from`.
    4. **Licence.** A `license` link from every `other` collection to a generated `LICENSE.md` at the root, which
       says each layer keeps its source agency's terms. Whether to declare the federal layers public domain
       (`CC-PDM-1.0`, as 3 collections already do) is a founder call, so we don't make it here.
    5. **Visualization.** Read each PMTiles header and metadata over HTTP range requests. Add `pmtiles:layers` to
       the link, write a MapLibre style in `styles/maplibre.json`, and draw a thumbnail from the coarsest zoom's
       tiles, each registered as an asset with size and checksum.
    6. **Collection README** gets a line naming the agency, the source link and the licence.
    """)
    return


@app.cell
def _(PurePosixPath, os, re):
    REL_PREFIX = re.compile(r"^releases/[^/]+/")
    STRUCTURAL = {"root", "parent", "self", "child", "item"}

    def fixed_path(published_path: str) -> str:
        """Where a document of the published tree lives in the single fixed tree."""
        return REL_PREFIX.sub("", published_path)

    def relative_links(doc: dict, published_path: str, base: str) -> list[dict]:
        """The document's links with structural ones made relative to its new place, and absolute self links dropped."""
        here = PurePosixPath(fixed_path(published_path)).parent.as_posix()
        links = []
        for link in doc.get("links", []):
            rel, href = link.get("rel"), link["href"]
            if rel == "agents":
                link = {**link, "href": "./AGENTS.md"}
            elif rel == "describedby":
                link = {**link, "href": "./README.md"}
            elif rel in STRUCTURAL:
                if rel == "self":
                    continue
                if href.startswith(base):
                    target = fixed_path(href[len(base) :])
                else:
                    assert "://" not in href, f"structural link outside the bucket: {href}"
                    target = fixed_path(os.path.normpath(f"{PurePosixPath(published_path).parent}/{href}"))
                link = {**link, "href": "./" + os.path.relpath(target, here).removeprefix("./")}
                if link["href"].startswith("./../"):
                    link["href"] = link["href"][2:]
            links.append(link)
        return links

    return fixed_path, relative_links


@app.cell
def _(Reader, ThreadPoolExecutor, gzip, math, urllib):
    def range_reader(url: str):
        """A PMTiles byte source over HTTP range requests, retried up to 3 times."""

        def get_bytes(offset: int, length: int) -> bytes:
            request = urllib.request.Request(url, headers={"Range": f"bytes={offset}-{offset + length - 1}"})
            for attempt in range(3):
                try:
                    with urllib.request.urlopen(request, timeout=60) as response:
                        assert response.status == 206, f"{url}: HTTP {response.status}"
                        return response.read()
                except OSError:
                    if attempt == 2:
                        raise
            raise AssertionError("unreachable")

        return get_bytes

    def read_pmtiles(url: str) -> dict:
        """Header, layer names and the tiles (at most 16) of the coarsest non-empty zoom of a remote PMTiles file."""
        reader = Reader(range_reader(url))
        header = reader.header()
        layers = [layer["id"] for layer in reader.metadata().get("vector_layers", [])]

        def tile_xy(lon_e7: int, lat_e7: int, n: int) -> tuple[int, int]:
            lat = math.radians(max(min(lat_e7 / 1e7, 85.05), -85.05))
            x = int((lon_e7 / 1e7 + 180) / 360 * n)
            y = int((1 - math.asinh(math.tan(lat)) / math.pi) / 2 * n)
            return min(max(x, 0), n - 1), min(max(y, 0), n - 1)

        # The coarsest zoom can be empty for sparse layers, so step down at most 4 zooms until tiles appear.
        tiles = {}
        for zoom in range(header["min_zoom"], min(header["min_zoom"] + 4, header["max_zoom"]) + 1):
            x0, y0 = tile_xy(header["min_lon_e7"], header["max_lat_e7"], 2**zoom)
            x1, y1 = tile_xy(header["max_lon_e7"], header["min_lat_e7"], 2**zoom)
            for x, y in [(x, y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)][:16]:
                data = reader.get(zoom, x, y)
                if data:
                    tiles[(x, y)] = gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
            if tiles:
                break
        return {"layers": layers, "tiles": tiles}

    def read_all_pmtiles(urls: list[str]) -> dict[str, dict | str]:
        """read_pmtiles for every URL, 16 at a time; a failure is kept as its message."""

        def one(url: str) -> dict | str:
            try:
                return read_pmtiles(url)
            except Exception as error:  # noqa: BLE001 - reported per file, not hidden
                return f"{type(error).__name__}: {error}"

        with ThreadPoolExecutor(16) as pool:
            return dict(zip(urls, pool.map(one, urls), strict=True))

    return (read_all_pmtiles,)


@app.cell
def _(io, mapbox_vector_tile, plt):
    def draw_thumbnail(tiles: dict[tuple[int, int], bytes]) -> bytes:
        """A 256-pixel PNG of the decoded tiles, points, lines and polygons in one colour."""
        figure, axes = plt.subplots(figsize=(2.56, 2.56), dpi=100)
        axes.set_axis_off()
        axes.set_aspect("equal")
        x_min = min(x for x, _y in tiles)
        y_max = max(y for _x, y in tiles)
        for (x, y), data in tiles.items():
            for layer in mapbox_vector_tile.decode(data).values():
                extent = layer.get("extent", 4096)
                dx, dy = (x - x_min) * extent, (y_max - y) * extent
                for feature in layer["features"]:
                    geometry = feature["geometry"]
                    kind, coords = geometry["type"], geometry["coordinates"]
                    if kind == "Point":
                        coords, kind = [coords], "MultiPoint"
                    if kind == "MultiPoint":
                        axes.scatter([c[0] + dx for c in coords], [c[1] + dy for c in coords], s=1, c="#c2410c")
                        continue
                    if kind in ("LineString", "Polygon"):
                        coords = [coords]
                    for part in coords:
                        rings = part if kind.endswith("Polygon") else [part]
                        for ring in rings:
                            xs, ys = [c[0] + dx for c in ring], [c[1] + dy for c in ring]
                            if kind.endswith("Polygon"):
                                axes.fill(xs, ys, color="#c2410c", alpha=0.5, linewidth=0.2)
                            else:
                                axes.plot(xs, ys, color="#c2410c", linewidth=0.5)
        buffer = io.BytesIO()
        figure.savefig(buffer, format="png", bbox_inches="tight", pad_inches=0.02)
        plt.close(figure)
        return buffer.getvalue()

    return (draw_thumbnail,)


@app.cell
def _(PUBLISHED_DIR, json, read_all_pmtiles, time):
    _t = time.time()
    _urls = sorted(
        {
            link["href"]
            for p in PUBLISHED_DIR.rglob("collection.json")
            for link in json.loads(p.read_text())["links"]
            if link["rel"] == "pmtiles"
        }
    )
    pmtiles_info = read_all_pmtiles(_urls)
    pmtiles_failed = {u: e for u, e in pmtiles_info.items() if isinstance(e, str)}
    print(f"read {len(pmtiles_info)} PMTiles headers in {time.time() - _t:.0f}s; failed: {len(pmtiles_failed)}")
    for _u, _e in list(pmtiles_failed.items())[:5]:
        print("  ", _u, _e)
    return (pmtiles_info,)


@app.cell
def _(
    CATALOG_URL,
    PUBLISHED_DIR,
    WORK,
    draw_thumbnail,
    fixed_path,
    hashlib,
    json,
    pmtiles_info,
    re,
    relative_links,
    shutil,
    time,
):
    _t = time.time()
    FIXED_DIR = WORK / "fixed"
    shutil.rmtree(FIXED_DIR, ignore_errors=True)
    _base = CATALOG_URL.rsplit("/", 1)[0] + "/"
    fix_counts = {"via_download": 0, "via_derived_from": 0, "no_via": 0, "license_link": 0, "pmtiles_layers": 0}
    fix_counts |= {"styles": 0, "thumbnails": 0, "no_thumbnail": 0}
    # Collections carry no build time of their own; the release's is on the root catalog.
    _synced = json.loads((PUBLISHED_DIR / "catalog.json").read_text())["hifld:updated_at"].split(".")[0] + "Z"

    def multihash(data: bytes) -> str:
        return "1220" + hashlib.sha256(data).hexdigest()

    def add_file_asset(doc: dict, folder, rel_path: str, data: bytes, role: list[str], media_type: str) -> None:
        folder.joinpath(rel_path).parent.mkdir(parents=True, exist_ok=True)
        folder.joinpath(rel_path).write_bytes(data)
        doc["assets"][role[0]] = {
            "href": f"./{rel_path}",
            "type": media_type,
            "roles": role,
            "title": rel_path.rsplit("/", 1)[-1],
            "file:size": len(data),
            "file:checksum": multihash(data),
        }

    def maplibre_style(title: str, pmtiles_url: str, layers: list[str], geometry_type: str) -> dict:
        kind = "circle" if "Point" in geometry_type else "line" if "Line" in geometry_type else "fill"
        paint = {"circle": {"circle-radius": 3, "circle-color": "#c2410c"}, "line": {"line-color": "#c2410c"}}
        paint["fill"] = {"fill-color": "#c2410c", "fill-opacity": 0.5, "fill-outline-color": "#7c2d12"}
        return {
            "version": 8,
            "name": title,
            "sources": {"data": {"type": "vector", "url": f"pmtiles://{pmtiles_url}"}},
            "layers": [
                {"id": f"{layer}-{kind}", "type": kind, "source": "data", "source-layer": layer, "paint": paint[kind]}
                for layer in layers
            ],
        }

    def fix_collection(doc: dict, folder) -> dict:
        doc["updated"] = doc.get("updated") or _synced
        download = re.search(r"Download:\s*(https?://[^\s ]+)", doc.get("description", ""))
        derived = next((link["href"] for link in doc["links"] if link["rel"] == "derived_from"), None)
        via = download.group(1) if download else derived
        fix_counts["via_download" if download else "via_derived_from" if derived else "no_via"] += 1
        if via:
            doc["links"].append({"rel": "via", "href": via, "type": "text/html"})
        if doc.get("license") == "other":
            depth = len(folder.relative_to(FIXED_DIR).parts)
            doc["links"].append({"rel": "license", "href": "../" * depth + "LICENSE.md", "type": "text/markdown"})
            fix_counts["license_link"] += 1
        for link in doc["links"]:
            info = pmtiles_info.get(link["href"]) if link["rel"] == "pmtiles" else None
            if not isinstance(info, dict) or not info["layers"]:
                continue
            link["pmtiles:layers"] = info["layers"]
            fix_counts["pmtiles_layers"] += 1
            if not any("style" in a.get("roles", []) for a in doc["assets"].values()):
                style = maplibre_style(doc["title"], link["href"], info["layers"], doc.get("hifld:geometry_type") or "")
                add_file_asset(
                    doc,
                    folder,
                    "styles/maplibre.json",
                    json.dumps(style, indent=1).encode(),
                    ["style", "default"],
                    "application/vnd.mapbox.style+json",
                )
                fix_counts["styles"] += 1
            if not any("thumbnail" in a.get("roles", []) for a in doc["assets"].values()) and info["tiles"]:
                add_file_asset(
                    doc, folder, "thumbnail/thumbnail.png", draw_thumbnail(info["tiles"]), ["thumbnail"], "image/png"
                )
                fix_counts["thumbnails"] += 1
        if not any("thumbnail" in a.get("roles", []) for a in doc["assets"].values()):
            fix_counts["no_thumbnail"] += 1
        readme = folder / "README.md"
        readme.write_text(
            readme.read_text().rstrip()
            + f"\n\nSource: {doc.get('hifld:agency') or 'see the via link'}, mirrored by HIFLD Next from {via}.\n"
            + f"License: {doc.get('license')}, see LICENSE.md at the catalog root.\n"
        )
        return doc

    for _md in PUBLISHED_DIR.rglob("*.md"):
        _dest = FIXED_DIR / fixed_path(_md.relative_to(PUBLISHED_DIR).as_posix())
        _dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(_md, _dest)
    for _p in sorted(PUBLISHED_DIR.rglob("*.json")):
        _published_path = _p.relative_to(PUBLISHED_DIR).as_posix()
        _dest = FIXED_DIR / fixed_path(_published_path)
        _dest.parent.mkdir(parents=True, exist_ok=True)
        _doc = json.loads(_p.read_text())
        _doc["links"] = relative_links(_doc, _published_path, _base)
        if _doc["type"] == "Collection":
            _doc = fix_collection(_doc, _dest.parent)
        elif _published_path == "catalog.json":
            _doc["updated"] = _synced
        _dest.write_text(json.dumps(_doc, indent=1))
    fix_seconds = time.time() - _t
    print(f"fixed tree written in {fix_seconds:.0f}s:", fix_counts)
    return FIXED_DIR, fix_counts


@app.cell
def _(FIXED_DIR, fix_counts, json):
    _root = json.loads((FIXED_DIR / "catalog.json").read_text())
    _layers = len(json.loads((FIXED_DIR / "hifld" / "catalog.json").read_text())["links"])
    FIXED_DIR.joinpath("README.md").write_text(
        f"# {_root['title']}\n\n{_root['description']}. {_layers} layers preserved from the federal HIFLD Open "
        "portal, which DHS shut down on 26 August 2025, published by Public Environmental Data Partners at "
        "https://hifld.publicenvirodata.org.\n\n"
        "Each layer is a catalog under `hifld/`, with one sub-catalog per file and one collection per version. "
        "Every collection carries GeoParquet (preferred for analysis), PMTiles (for maps) and the original "
        "formats.\n\nLicense: each layer keeps its source agency's terms; see LICENSE.md.\n"
    )
    FIXED_DIR.joinpath("AGENTS.md").write_text(
        "# Using this catalog\n\n"
        "- Start at `catalog.json` and follow `child` links: `hifld/catalog.json`, then one catalog per layer.\n"
        "- Read GeoParquet over HTTP range requests (DuckDB, GDAL, pyarrow); don't download whole files.\n"
        "- PMTiles are for maps; the collection's `styles/maplibre.json` draws them.\n"
        "- The same metadata is searchable at https://hifld.publicenvirodata.org/api and through the MCP server "
        "at https://hifld.publicenvirodata.org/mcp.\n"
        "- Source and licence: each collection's `via` and `license` links.\n"
    )
    FIXED_DIR.joinpath("LICENSE.md").write_text(
        "# License\n\nHIFLD Next mirrors layers published by U.S. federal agencies and their partners. Each layer "
        "keeps the terms of its source agency, linked from its collection's `via` link. Most are U.S. government "
        "works; check the source before reuse.\n"
    )
    print("generated root README.md, AGENTS.md and LICENSE.md;", fix_counts["license_link"], "collections link it")
    return


@app.cell
def _(FIXED_DIR, OUT, RASHID, json, mo, pass_counts, pd, published_rules, subprocess, time):
    _t = time.time()
    _run = subprocess.run([RASHID, "check", str(FIXED_DIR), "--no-data", "--json"], capture_output=True, text=True)
    assert _run.returncode in (0, 1), _run.stderr[-2000:]
    fixed = json.loads(_run.stdout)
    (OUT / "validator_fixed.json").write_text(json.dumps(fixed, indent=1))
    _docs = sorted(p.relative_to(FIXED_DIR).as_posix() for p in FIXED_DIR.rglob("*.json") if p.name != "maplibre.json")
    fixed_counts = pass_counts(fixed, _docs)
    _after = pd.DataFrame(fixed["summary"]["by_rule"])[["rule_id", "count"]].rename(columns={"count": "after"})
    rule_compare = (
        published_rules.rename(columns={"count": "before"})[["rule_id", "severity", "before", "description"]]
        .merge(_after, on="rule_id", how="outer")
        .fillna({"before": 0, "after": 0})
        .astype({"before": int, "after": int})
    )
    rule_compare.to_csv(OUT / "rules_before_after.csv", index=False)
    print(
        f"fixed tree: {fixed['error_count']} errors, {fixed['warning_count']} warnings, {fixed['info_count']} info "
        f"in {time.time() - _t:.0f}s; pass counts {fixed_counts}"
    )
    mo.vstack(
        [
            mo.md(
                "## Step 4: validate the fixed copy\n\n**Objects with no error after the fixes**: "
                + "; ".join(f"{k} {p} of {n}" for k, (p, n) in fixed_counts.items())
            ),
            rule_compare,
        ]
    )
    return fixed, fixed_counts, rule_compare


@app.cell
def _(fixed, pd):
    _left = pd.DataFrame([f for f in fixed["findings"] if f["severity"] != "info"])
    remaining = (
        _left.groupby(["rule_id", "severity"]).agg(count=("path", "size"), example=("message", "first")).reset_index()
        if len(_left)
        else pd.DataFrame()
    )
    remaining
    return (remaining,)


@app.cell
def _(fixed, mo):
    _count = {r["rule_id"]: r["count"] for r in fixed["summary"]["by_rule"]}
    mo.md(f"""
    ### What is left, and what it would cost

    After the generated fixes, what fails needs a decision or data the metadata doesn't have:

    - **Collection IDs** (PTL-COL-003, warning, {_count.get("PTL-COL-003", 0)}): `hifld/hospitals-3/hospitals-3/v1.0.0`
      would become something like `hospitals-3-v1-0-0`. The STAC API, JSON API, MCP server and every link out there
      use the current IDs, so this is a founder call, not a pipeline fix.
    - **Collections with no source link** (PTL-PRO-001, {_count.get("PTL-PRO-001", 0)}): no `Download:` URL and no
      `derived_from`. Someone has to find each source by hand.
    - **Thumbnails** (PTL-VIZ-001, {_count.get("PTL-VIZ-001", 0)}): geospatial collections with no PMTiles, or whose
      first zooms are empty. These need a renderer that reads GeoParquet.
    - **Checksums** (PTL-AST-003, {_count.get("PTL-AST-003", 0)}): file-geodatabase assets with none. The pipeline
      would compute them at publish time, in SHA2-256 like the rest should be (see step 2).

    **Rough cost to conform, in pipeline days.** These are our estimates from the size of the code above, not
    measured:

    - Relative links, one tree and root files: 1 day, mostly retesting the STAC API and site, which read the same
      files.
    - Mirror fields, licence link and README lines: 0.5 day.
    - Styles, `pmtiles:layers` and thumbnails for vector layers: 1 to 1.5 days, extending the code that already does
      this for rasters.
    - SHA2-256 checksums and a full byte-level data pass: 0.5 day, plus a run on a machine near the bucket.
    - Proper READMEs and AGENTS.md per layer, beyond the one-liners: open-ended.

    That comes to about **3 to 4 days** to reach the remainder above, plus any ID rename.
    """)
    return


@app.cell
def _(SITE, mo, pd, urllib):
    def status(url: str, method: str = "GET") -> int:
        request = urllib.request.Request(url, method=method)
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status
        except urllib.error.HTTPError as error:
            return error.code

    _endpoints = [
        ("MCP server card", "/.well-known/mcp/server-card.json", "Model Context Protocol server for agents"),
        ("JSON API", "/api", "Search, tag filters, paging and saved queries over the catalog"),
        ("OpenAPI for the JSON API", "/api/openapi", "Machine-readable contract for the API"),
        ("STAC API", "/stac", "Standard STAC API Core and Collections"),
        ("OGC API Features", "/features/collections", "Feature-level queries over the data"),
        ("llms.txt", "/llms.txt", "Agent-oriented index of the site"),
        ("Agent skills index", "/.well-known/agent-skills/index.json", "Published skills for agents"),
    ]
    beyond = pd.DataFrame(
        [(name, SITE + path, status(SITE + path), what) for name, path, what in _endpoints],
        columns=["feature", "url", "http_status", "what it does"],
    )
    mo.vstack(
        [
            mo.md(r"""
    ## Step 5: what Portolan doesn't cover

    Portolan describes files in a bucket and how to find and read them. HIFLD Next also runs services on top of
    those files, which the spec says nothing about. Each is checked live below. Version history is the one that
    overlaps: every file is a collection per version (`…/v1.0.0`), and Portolan's catalogs have `versions.json`,
    but the validator has no rule that reads version history, so it neither credits nor faults ours.
    """),
            beyond,
        ]
    )
    return (beyond,)


@app.cell
def _(
    OUT,
    STARTED,
    beyond,
    data_findings,
    fix_counts,
    fixed,
    fixed_counts,
    json,
    published,
    published_counts,
    time,
):
    summary = {
        "catalog_url": "https://storage.googleapis.com/hifld-next-datasets-prod/catalog.json",
        "published": {
            "documents": published["files_checked"],
            "errors": published["error_count"],
            "warnings": published["warning_count"],
            "passing": published_counts,
        },
        "data_sample": {
            "errors": sum(f["severity"] == "error" for f in data_findings),
            "warnings": sum(f["severity"] == "warning" for f in data_findings),
        },
        "fixes": fix_counts,
        "fixed": {"errors": fixed["error_count"], "warnings": fixed["warning_count"], "passing": fixed_counts},
        "beyond_portolan_live": dict(zip(beyond["feature"], beyond["http_status"].astype(int), strict=True)),
        "seconds": round(time.time() - STARTED),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    print(json.dumps(summary, indent=1))
    return


if __name__ == "__main__":
    app.run()

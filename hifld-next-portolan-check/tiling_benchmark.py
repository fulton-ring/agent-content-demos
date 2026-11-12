import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(r"""
    # Is tylertoo faster than tippecanoe on HIFLD Next's tiles?

    HIFLD Next builds its PMTiles with tippecanoe. Each file's metadata records the command:
    `tippecanoe -zg --drop-densest-as-needed --extend-zooms-if-still-dropping --maximum-zoom=14`, run on
    FlatGeobuf chunks converted from the GeoParquet. [tylertoo](https://github.com/geoparquet-io/tylertoo) writes
    PMTiles straight from GeoParquet. Its author says it is "7-10x faster than tippecanoe".

    For each layer in a sample, this notebook builds the tiles both ways from the same GeoParquet. It measures wall
    time and peak memory of each step, file size, zoom range, and what the tiles contain: features at the finest
    zoom both reach, and attribute names. Both tools pick their own maximum zoom (`-zg` and `max_zoom="auto"`),
    as each would in production.
    """)
    return (mo,)


@app.cell
def _():
    import gzip
    import json
    import os
    import random
    import shutil
    import subprocess
    import sys
    import tempfile
    import time
    import urllib.request
    from pathlib import Path

    import mapbox_vector_tile
    import pandas as pd
    import pyarrow.parquet as pq
    from pmtiles.reader import MmapSource, Reader, all_tiles
    from rashid.remote import crawl, split_catalog_url

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("OUTPUT_DIR", HERE / "outputs"))
    WORK = Path(os.environ.get("WORK_DIR", HERE / "data")) / "tiles"
    OUT.mkdir(parents=True, exist_ok=True)
    WORK.mkdir(parents=True, exist_ok=True)
    CATALOG_URL = os.environ.get(
        "HIFLD_CATALOG_URL", "https://storage.googleapis.com/hifld-next-datasets-prod/catalog.json"
    )
    SEED = 205
    PER_CLASS = int(os.environ.get("BENCH_PER_CLASS", "8"))
    INCLUDE_LARGEST = os.environ.get("BENCH_LARGEST", "1") == "1"
    SMALL_MAX_BYTES = 200_000_000
    LARGE_MAX_BYTES = 2_100_000_000
    STEP_TIMEOUT = 3600
    DECODE_TILE_CAP = 5000
    TIPPECANOE = shutil.which("tippecanoe")
    assert TIPPECANOE, "tippecanoe is not on PATH; see README"
    TIPPECANOE_VERSION = subprocess.run([TIPPECANOE, "--version"], capture_output=True, text=True).stderr.strip()
    print(TIPPECANOE_VERSION)
    return (
        CATALOG_URL,
        DECODE_TILE_CAP,
        INCLUDE_LARGEST,
        LARGE_MAX_BYTES,
        MmapSource,
        OUT,
        PER_CLASS,
        Path,
        Reader,
        SEED,
        SMALL_MAX_BYTES,
        STEP_TIMEOUT,
        TIPPECANOE,
        TIPPECANOE_VERSION,
        WORK,
        all_tiles,
        crawl,
        gzip,
        json,
        mapbox_vector_tile,
        os,
        pd,
        pq,
        random,
        shutil,
        split_catalog_url,
        subprocess,
        sys,
        tempfile,
        time,
        urllib,
    )


@app.cell
def _(CATALOG_URL, WORK, crawl, json, shutil, split_catalog_url):
    # The catalog lists every collection's GeoParquet files, their sizes and the geometry type.
    _tree = WORK / "catalog"
    shutil.rmtree(_tree, ignore_errors=True)
    _base, _root = split_catalog_url(CATALOG_URL)
    assert not crawl(_base, _tree).errors
    layers = []
    for _p in sorted(_tree.rglob("collection.json")):
        _d = json.loads(_p.read_text())
        _parquet = [a for a in _d["assets"].values() if a.get("type") == "application/vnd.apache.parquet"]
        _geometry = (_d.get("hifld:geometry_type") or "").replace(" Z", "").replace("Multi", "")
        if _parquet and _geometry in ("Point", "LineString", "Polygon"):
            layers.append(
                {
                    "id": _d["id"].removeprefix("hifld/").removesuffix("/v1.0.0"),
                    "geometry": _geometry,
                    "features": _d.get("hifld:feature_count"),
                    "parquet_urls": sorted(a["href"] for a in _parquet),
                    "parquet_bytes": sum(a.get("file:size", 0) for a in _parquet),
                }
            )
    print(f"{len(layers)} collections with GeoParquet and a known point, line or polygon geometry")
    return (layers,)


@app.cell
def _(INCLUDE_LARGEST, LARGE_MAX_BYTES, PER_CLASS, SEED, SMALL_MAX_BYTES, layers, mo, random):
    _rng = random.Random(SEED)
    sample = []
    for _geometry in ("Point", "LineString", "Polygon"):
        _small = [x for x in layers if x["geometry"] == _geometry and x["parquet_bytes"] < SMALL_MAX_BYTES]
        sample += [{**x, "why": "seeded sample"} for x in _rng.sample(_small, PER_CLASS)]
        if not INCLUDE_LARGEST:
            continue
        _fits = [x for x in layers if x["geometry"] == _geometry and x["parquet_bytes"] < LARGE_MAX_BYTES]
        sample.append({**max(_fits, key=lambda x: x["parquet_bytes"]), "why": "largest that fits"})
    _too_big = sorted((x for x in layers if x["parquet_bytes"] >= LARGE_MAX_BYTES), key=lambda x: -x["parquet_bytes"])
    mo.md(f"""
    ## The sample

    The whole catalog's GeoParquet is about 118 GB. The six largest layers (the flood-hazard and hydrography layers,
    5 to 24 GB each) would take hours each with tippecanoe and don't fit the sandbox's disk alongside their outputs.
    So we take **{PER_CLASS}** layers per geometry class (points, lines, polygons), drawn with seed {SEED} from those
    under {SMALL_MAX_BYTES / 1e6:.0f} MB, plus the **largest layer of each class under
    {LARGE_MAX_BYTES / 1e9:.1f} GB**: {len(sample)} layers. Left out for size: {", ".join(x["id"] for x in _too_big)}.
    """)
    return (sample,)


@app.cell
def _(STEP_TIMEOUT, subprocess, tempfile, time):
    def measured(command: list[str]) -> dict:
        """Run a command; return wall seconds, peak resident memory in MB and whether it succeeded.

        Peak memory is the child's own high-water mark (VmHWM in /proc), read every 20 ms until it exits. The
        rusage from wait4 would not do: a forked child inherits this notebook's high-water mark.
        """
        start = time.perf_counter()
        errors = tempfile.TemporaryFile()  # a file, not a pipe, so a chatty child can't block on a full pipe
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=errors)
        status_file = f"/proc/{process.pid}/status"
        peak_kb = 0
        while process.poll() is None and time.perf_counter() < start + STEP_TIMEOUT:
            try:
                with open(status_file) as handle:
                    line = next((x for x in handle if x.startswith("VmHWM:")), "VmHWM: 0 kB")
                peak_kb = max(peak_kb, int(line.split()[1]))
            except (FileNotFoundError, ProcessLookupError):
                pass
            time.sleep(0.02)
        if process.poll() is None:
            process.kill()
            process.wait()
            return {"seconds": time.perf_counter() - start, "peak_mb": None, "ok": False, "error": "timed out"}
        errors.seek(0)
        stderr = errors.read().decode(errors="replace")
        return {
            "seconds": time.perf_counter() - start,
            "peak_mb": peak_kb / 1024,
            "ok": process.returncode == 0,
            "error": stderr.strip().splitlines()[-1][:300] if process.returncode and stderr.strip() else "",
        }

    return (measured,)


@app.cell
def _(DECODE_TILE_CAP, MmapSource, Reader, all_tiles, gzip, mapbox_vector_tile):
    def describe_pmtiles(path, zoom: int | None = None, only: set | None = None) -> dict:
        """Zoom range, tile count, field names, and features and keys in the tiles at one zoom (capped)."""
        with open(path, "rb") as handle:
            reader = Reader(MmapSource(handle))
            header, metadata = reader.header(), reader.metadata()
            fields = sorted({f for layer in metadata.get("vector_layers", []) for f in layer.get("fields", {})})
            zoom = header["max_zoom"] if zoom is None else zoom
            features, keys, tiles_at_zoom = 0, set(), set()
            for (z, x, y), data in all_tiles(MmapSource(handle)):
                if z != zoom or (only is not None and (x, y) not in only) or len(tiles_at_zoom) >= DECODE_TILE_CAP:
                    continue
                tiles_at_zoom.add((x, y))
                data = gzip.decompress(data) if data[:2] == b"\x1f\x8b" else data
                for layer in mapbox_vector_tile.decode(data).values():
                    features += len(layer["features"])
                    for feature in layer["features"]:
                        keys |= feature["properties"].keys()
        return {
            "min_zoom": header["min_zoom"],
            "max_zoom": header["max_zoom"],
            "tiles": header["addressed_tiles_count"],
            "fields": fields,
            "zoom": zoom,
            "tiles_at_zoom": tiles_at_zoom,
            "features_at_zoom": features,
            "keys_at_zoom": sorted(keys),
        }

    return (describe_pmtiles,)


@app.cell
def _(json, pq):
    def source_crs(path) -> tuple[str, str]:
        """The geometry column and its CRS as AUTHORITY:CODE (GeoParquet's default, when none is named, is CRS84)."""
        geo = json.loads(pq.read_metadata(path).metadata[b"geo"])
        column = geo["columns"][geo["primary_column"]]
        ident = (column.get("crs") or {}).get("id") or {}
        return geo["primary_column"], f"{ident['authority']}:{ident['code']}" if ident else "OGC:CRS84"

    return (source_crs,)


@app.cell
def _(TIPPECANOE, WORK, describe_pmtiles, measured, pq, shutil, source_crs, sys, urllib):
    def benchmark(layer: dict) -> dict:
        """Download one layer's GeoParquet, tile it both ways, and compare the two archives."""
        folder = WORK / layer["id"].replace("/", "__")
        shutil.rmtree(folder, ignore_errors=True)
        folder.mkdir(parents=True)
        files = []
        for i, url in enumerate(layer["parquet_urls"]):
            files.append(folder / f"part-{i:03d}.parquet")
            with urllib.request.urlopen(url, timeout=600) as response, open(files[-1], "wb") as out:
                assert response.status == 200, f"{url}: HTTP {response.status}"
                shutil.copyfileobj(response, out, 16 << 20)
        rows = sum(pq.read_metadata(f).num_rows for f in files)
        geometry, crs = source_crs(files[0])
        drop = ", ".join(c for c in (geometry, "bbox") if c in pq.read_schema(files[0]).names)
        names = [str(f) for f in files]
        tt_out, tc_out, fgb = folder / "tylertoo.pmtiles", folder / "tippecanoe.pmtiles", folder / "input.fgb"
        # tylertoo reads only EPSG:4326 or 3857, so other CRSs (census NAD83, Albers) get a timed reprojection first.
        tylertoo_input = names
        prep = {"seconds": 0.0, "peak_mb": None, "ok": True, "error": ""}
        if crs not in ("EPSG:4326", "OGC:CRS84", "EPSG:3857"):
            tylertoo_input = [str(folder / "input-4326.parquet")]
            prep = measured(
                [
                    sys.executable,
                    "-c",
                    (
                        "import duckdb; c = duckdb.connect(); c.sql('INSTALL spatial'); c.sql('LOAD spatial'); "
                        f'c.sql("""COPY (SELECT * EXCLUDE ({drop}), '
                        f"ST_Transform({geometry}, '{crs}', 'EPSG:4326', always_xy := true) AS geometry "
                        f"FROM read_parquet({names!r}, union_by_name=true)) "
                        f'TO \'{tylertoo_input[0]}\' (FORMAT parquet)""")'
                    ),
                ]
            )
        tylertoo_script = (
            "import sys, tylertoo; "
            f"tylertoo.overview({tylertoo_input!r}, {str(folder / 'overview.parquet')!r}, max_zoom='auto'); "
            f"tylertoo.export_pmtiles({str(folder / 'overview.parquet')!r}, {str(tt_out)!r}, layer_name='layer')"
        )
        reproject = (
            geometry
            if crs in ("EPSG:4326", "OGC:CRS84")
            else (f"ST_Transform({geometry}, '{crs}', 'EPSG:4326', always_xy := true)")
        )
        # FlatGeobuf as tippecanoe 2.49 reads it: one geometry type per file (lines and polygons made Multi, Z
        # dropped) and no binary columns (written as hex text).
        reproject = f"ST_Force2D({reproject})" if layer["geometry"] == "Point" else f"ST_Multi(ST_Force2D({reproject}))"
        geometry_type = {"Point": "", "LineString": ", GEOMETRY_TYPE 'MULTILINESTRING'"}
        geometry_type["Polygon"] = ", GEOMETRY_TYPE 'MULTIPOLYGON'"
        binary = [
            f.name
            for f in pq.read_schema(files[0])
            if str(f.type) in ("binary", "large_binary") and f.name not in (geometry, "bbox")
        ]
        replace = f" REPLACE ({', '.join(f'hex({b}) AS {b}' for b in binary)})" if binary else ""
        convert_script = (
            "import duckdb; c = duckdb.connect(); c.sql('INSTALL spatial'); c.sql('LOAD spatial'); "
            f'c.sql("""COPY (SELECT * EXCLUDE ({drop}){replace}, {reproject} AS geometry '
            f"FROM read_parquet({names!r}, union_by_name=true) WHERE {geometry} IS NOT NULL) TO '{fgb}' "
            f"WITH (FORMAT GDAL, DRIVER 'FlatGeobuf', SRS 'EPSG:4326'{geometry_type[layer['geometry']]})\"\"\")"
        )
        tylertoo = (
            measured([sys.executable, "-c", tylertoo_script])
            if prep["ok"]
            else ({"seconds": None, "peak_mb": None, "ok": False, "error": "reprojection failed"})
        )
        # Free tylertoo's intermediate files first: the largest layers don't fit on disk alongside them.
        for intermediate in (folder / "overview.parquet", folder / "input-4326.parquet"):
            intermediate.unlink(missing_ok=True)
        convert = measured([sys.executable, "-c", convert_script])
        tippecanoe = (
            measured(
                [
                    TIPPECANOE,
                    "-q",
                    "-zg",
                    "--drop-densest-as-needed",
                    "--extend-zooms-if-still-dropping",
                    "--force",
                    "--maximum-zoom=14",
                    "-l",
                    "layer",
                    "-o",
                    str(tc_out),
                    str(fgb),
                ]
            )
            if convert["ok"]
            else {"seconds": None, "peak_mb": None, "ok": False, "error": "conversion failed"}
        )
        row = {
            "layer": layer["id"],
            "geometry": layer["geometry"],
            "why": layer["why"],
            "rows": rows,
            "parquet_mb": layer["parquet_bytes"] / 1e6,
            "crs": crs,
            "reproject_s": prep["seconds"],
            "reproject_peak_mb": prep["peak_mb"],
            "tylertoo_s": tylertoo["seconds"],
            "tylertoo_peak_mb": tylertoo["peak_mb"],
            "convert_s": convert["seconds"],
            "convert_peak_mb": convert["peak_mb"],
            "tippecanoe_s": tippecanoe["seconds"],
            "tippecanoe_peak_mb": tippecanoe["peak_mb"],
            "errors": " | ".join(
                f"{k}: {r['error']}"
                for k, r in (
                    ("reproject", prep),
                    ("tylertoo", tylertoo),
                    ("convert", convert),
                    ("tippecanoe", tippecanoe),
                )
                if r["error"]
            ),
        }
        if tylertoo["ok"] and tippecanoe["ok"]:
            tt, tc = describe_pmtiles(tt_out), describe_pmtiles(tc_out)
            zoom = min(tt["max_zoom"], tc["max_zoom"])
            tt_z, tc_z = describe_pmtiles(tt_out, zoom), describe_pmtiles(tc_out, zoom)
            shared = tt_z["tiles_at_zoom"] & tc_z["tiles_at_zoom"]
            tt_z, tc_z = describe_pmtiles(tt_out, zoom, shared), describe_pmtiles(tc_out, zoom, shared)
            source_fields = set(pq.read_schema(files[0]).names) - {geometry, "bbox"}
            row |= {
                "tylertoo_mb": tt_out.stat().st_size / 1e6,
                "tippecanoe_mb": tc_out.stat().st_size / 1e6,
                "tylertoo_zooms": f"{tt['min_zoom']}-{tt['max_zoom']}",
                "tippecanoe_zooms": f"{tc['min_zoom']}-{tc['max_zoom']}",
                "tylertoo_tiles": tt["tiles"],
                "tippecanoe_tiles": tc["tiles"],
                "compare_zoom": zoom,
                "compare_tiles": len(shared),
                "tylertoo_features": tt_z["features_at_zoom"],
                "tippecanoe_features": tc_z["features_at_zoom"],
                "tylertoo_features_maxzoom": tt["features_at_zoom"],
                "tylertoo_maxzoom_tiles": len(tt["tiles_at_zoom"]),
                "tippecanoe_features_maxzoom": tc["features_at_zoom"],
                "tippecanoe_maxzoom_tiles": len(tc["tiles_at_zoom"]),
                "source_fields": len(source_fields),
                "fields_missing_tylertoo": ";".join(sorted(source_fields - set(tt["fields"]))),
                "fields_missing_tippecanoe": ";".join(sorted(source_fields - set(tc["fields"]))),
            }
        shutil.rmtree(folder)
        return row

    return (benchmark,)


@app.cell
def _(OUT, benchmark, pd, sample, time):
    _t = time.time()
    _rows = []
    for _layer in sample:
        _rows.append(benchmark(_layer))
        _r = _rows[-1]
        # Written after every layer, so a run cut short keeps what it measured.
        pd.DataFrame(_rows).to_csv(OUT / "tiling_benchmark.csv", index=False, float_format="%.3f")
        print(
            f"{_r['layer'][:50]:50} {_r['geometry']:10} "
            f"tylertoo {(_r['reproject_s'] or 0) + (_r['tylertoo_s'] or 0):7.1f}s  "
            f"convert+tippecanoe {(_r['convert_s'] or 0) + (_r['tippecanoe_s'] or 0):7.1f}s  {_r['errors'][:80]}",
            flush=True,
        )
    results = pd.DataFrame(_rows)
    print(f"benchmark finished in {time.time() - _t:.0f}s")
    results
    return (results,)


@app.cell
def _(OUT, TIPPECANOE_VERSION, json, mo, results):
    _ok = results.dropna(subset=["tylertoo_mb"]).copy()
    _ok["tippecanoe_path_s"] = _ok["convert_s"] + _ok["tippecanoe_s"]
    _ok["tylertoo_path_s"] = _ok["reproject_s"] + _ok["tylertoo_s"]
    _ok["speedup_vs_tippecanoe"] = _ok["tippecanoe_s"] / _ok["tylertoo_s"]
    _ok["speedup_vs_path"] = _ok["tippecanoe_path_s"] / _ok["tylertoo_path_s"]
    _ok["feature_ratio"] = _ok["tylertoo_features"] / _ok["tippecanoe_features"]
    _diff = _ok[
        (_ok["fields_missing_tylertoo"] != _ok["fields_missing_tippecanoe"]) | ((_ok["feature_ratio"] - 1).abs() > 0.05)
    ]
    bench_summary = {
        "tippecanoe": TIPPECANOE_VERSION,
        "layers": len(results),
        "both_succeeded": len(_ok),
        "failures": results.loc[results["errors"] != "", ["layer", "errors"]].to_dict("records"),
        "needed_reprojection_for_tylertoo": int((~results["crs"].isin(["EPSG:4326", "OGC:CRS84", "EPSG:3857"])).sum()),
        "total_tylertoo_s": round(_ok["tylertoo_s"].sum(), 1),
        "total_tylertoo_path_s": round(_ok["tylertoo_path_s"].sum(), 1),
        "total_tippecanoe_s": round(_ok["tippecanoe_s"].sum(), 1),
        "total_tippecanoe_path_s": round(_ok["tippecanoe_path_s"].sum(), 1),
        "median_speedup_vs_tippecanoe": round(_ok["speedup_vs_tippecanoe"].median(), 2),
        "median_speedup_vs_path": round(_ok["speedup_vs_path"].median(), 2),
        "max_peak_mb": {
            "tylertoo": round(_ok["tylertoo_peak_mb"].max()),
            "convert": round(_ok["convert_peak_mb"].max()),
            "tippecanoe": round(_ok["tippecanoe_peak_mb"].max()),
        },
        "total_mb": {
            "tylertoo": round(_ok["tylertoo_mb"].sum(), 1),
            "tippecanoe": round(_ok["tippecanoe_mb"].sum(), 1),
        },
        "layers_with_differences": len(_diff),
        "largest": _ok.loc[
            _ok["why"] == "largest that fits",
            ["layer", "tylertoo_s", "tippecanoe_path_s", "tylertoo_peak_mb", "tippecanoe_peak_mb"],
        ]
        .round(1)
        .to_dict("records"),
    }
    (OUT / "tiling_summary.json").write_text(json.dumps(bench_summary, indent=1))
    print(json.dumps(bench_summary, indent=1))
    mo.vstack(
        [
            mo.md(f"""
    ## Result

    Both tools succeeded on **{len(_ok)} of {len(results)}** layers.
    **{bench_summary["needed_reprojection_for_tylertoo"]}** of the {len(results)} are stored in a CRS tylertoo won't
    read (NAD83 for the census layers, Albers for some hydrography). They got a reprojection to EPSG:4326 first,
    counted in tylertoo's time. Over the layers both tools finished, tylertoo took
    **{bench_summary["total_tylertoo_path_s"]:.0f} s** in total.
    tippecanoe took **{bench_summary["total_tippecanoe_s"]:.0f} s**,
    or **{bench_summary["total_tippecanoe_path_s"]:.0f} s** counting the GeoParquet-to-FlatGeobuf step it needs.
    The median layer was **{bench_summary["median_speedup_vs_path"]}x** faster with tylertoo than the full tippecanoe
    path, and **{bench_summary["median_speedup_vs_tippecanoe"]}x** against tippecanoe alone.

    Per-layer differences in features (at the finest zoom both reach, over the tiles both wrote) or in which source
    columns survived: **{len(_diff)}** layers. The table below lists them.
    """),
            _diff[
                [
                    "layer",
                    "geometry",
                    "compare_zoom",
                    "tylertoo_features",
                    "tippecanoe_features",
                    "fields_missing_tylertoo",
                    "fields_missing_tippecanoe",
                    "tylertoo_zooms",
                    "tippecanoe_zooms",
                ]
            ],
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Reading the numbers, and what didn't work

    - **The tools don't build the same tiles.** Each picks its own maximum zoom. tylertoo usually goes deeper on
      points and lines and much shallower on small polygon layers: a handful of regions can stop at zoom 0, where
      tippecanoe goes to zoom 10 or 11. Feature counts at a shared zoom differ for the same reason, since each
      thins features differently. Compare speed per layer with the `*_zooms` columns beside it.
    - **tylertoo only reads EPSG:4326 or 3857.** The census layers (NAD83) and some hydrography (Albers) fail
      outright, so we add a DuckDB reprojection step and count it in tylertoo's time.
    - **tylertoo usually uses more memory**, and its files are larger for points and smaller for big line layers.
    - **Columns.** tylertoo drops binary columns (MVT can't hold them). tippecanoe drops columns that are empty in
      every feature.
    - **Our FlatGeobuf step failed on two layers in the published run:** the disk filled on the 34.8-million-point
      layer, and PAD-US has rows with no geometry. The notebook now frees tylertoo's intermediate files first and
      skips rows with no geometry, but those two layers weren't re-measured.
    """)
    return


if __name__ == "__main__":
    app.run()

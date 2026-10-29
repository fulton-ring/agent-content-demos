import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import importlib.metadata
    import json
    import os
    import platform
    import shutil
    import subprocess
    import zipfile
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import numpy as np
    import pandas as pd

    from common import CACHE, HERE, RESULTS, sha256, write

    return (
        CACHE,
        HERE,
        Path,
        RESULTS,
        gpd,
        importlib,
        json,
        mo,
        np,
        os,
        pd,
        platform,
        sha256,
        shutil,
        subprocess,
        write,
        zipfile,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Publishing a yearly STORM release (dry run)

    The last step of [issue #142](https://github.com/fulton-ring/agent-content-demos/issues/142):
    turn `regenerate.py`'s tracks into files our map and pipelines can read directly, with
    enough metadata that next year's run can be compared with this one. Everything is written
    to a local folder laid out as a [Portolan](https://github.com/portolan-sdi/portolan-cli)
    catalogue, the static STAC-plus-GeoParquet layout Source Cooperative serves. Nothing is
    pushed: `portolan push --dry-run` lists what an upload would send.

    One release holds:

    - `tracks.parquet`: every 3-hourly fix as a GeoParquet point, with STORM's columns.
    - `storm_text.zip`: the ten 1,000-year files in STORM's own text format, which CLIMADA's
      `TCTracks.from_simulations_storm` reads unchanged.
    - `manifest.json`: inputs with URLs and checksums, STORM's commits, package versions, this
      repository's commit, the seed and the outputs' checksums.

    Portolan writes the STAC catalogue, collection and item around them, plus `versions.json`,
    which records each release of the collection with its checksums.
    """)
    return


@app.cell
def _(CACHE, Path, RESULTS, json, os):
    run = json.loads((RESULTS / "run.json").read_text())
    first_season, last_season = run["baseline"]
    track_files = sorted(
        Path(run["track_folder"]).glob("STORM_DATA_IBTRACS_NA_1000_YEARS_*.txt"),
        key=lambda p: int(p.stem.rsplit("_", 1)[1]),
    )
    assert len(track_files) * 1000 == run["years"], "regenerate.py hasn't finished every file"
    catalogue = Path(os.environ.get("STORM_PUBLISH", CACHE / "publish" / "fri-storm"))
    # One item per baseline and seed, inside one collection for the North Atlantic.
    release = f"ibtracs-{first_season}-{last_season}-seed{run['seed']}"
    item = catalogue / "storm-north-atlantic" / release
    item.mkdir(parents=True, exist_ok=True)
    release
    return catalogue, first_season, item, last_season, release, run, track_files


@app.cell
def _(gpd, item, np, pd, track_files):
    _columns = [
        "year",
        "month",
        "storm_in_year",
        "step",
        "basin",
        "lat",
        "lon",
        "pressure_hpa",
        "wind_10min_ms",
        "rmax_km",
        "category",
        "landfall",
        "distance_to_land_km",
    ]
    _parts = []
    for _file, _path in enumerate(track_files):
        _raw = pd.read_csv(_path, header=None, names=_columns)
        _raw.insert(0, "file", _file)
        _parts.append(_raw)
    _fixes = pd.concat(_parts, ignore_index=True)
    for _c in ("file", "year", "month", "storm_in_year", "step", "basin", "category", "landfall"):
        _fixes[_c] = _fixes[_c].astype(np.int32)
    # One id per synthetic storm, stable across releases with the same seed.
    _fixes.insert(
        0,
        "storm_id",
        _fixes["file"].astype(str)
        + "-"
        + _fixes["year"].astype(str).str.zfill(3)
        + "-"
        + _fixes["storm_in_year"].astype(str).str.zfill(2),
    )
    _lon = ((_fixes["lon"] + 180) % 360) - 180
    tracks = gpd.GeoDataFrame(
        _fixes.drop(columns=["lat", "lon"]),
        geometry=gpd.points_from_xy(_lon, _fixes["lat"]),
        crs="EPSG:4326",
    )
    tracks_path = item / "tracks.parquet"
    tracks.to_parquet(tracks_path, compression="zstd", write_covering_bbox=True)
    f"{len(tracks):,} fixes, {tracks['storm_id'].nunique():,} storms"
    return tracks, tracks_path


@app.cell
def _(item, track_files, zipfile):
    text_path = item / "storm_text.zip"
    with zipfile.ZipFile(text_path, "w", compression=zipfile.ZIP_DEFLATED) as _archive:
        for _path in track_files:
            _archive.write(_path, _path.name)
    return (text_path,)


@app.cell
def _(
    HERE,
    importlib,
    item,
    json,
    platform,
    release,
    run,
    sha256,
    subprocess,
    text_path,
    tracks,
    tracks_path,
):
    _git = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=HERE, capture_output=True, text=True, check=False
    )
    _status = subprocess.run(
        ["git", "status", "--porcelain", "."], cwd=HERE, capture_output=True, text=True, check=False
    )
    assert _git.returncode == 0 and _status.returncode == 0, "needs a git checkout"
    _packages = ["numpy", "scipy", "pandas", "xarray", "netcdf4", "cartopy", "shapely", "climada"]
    manifest = {
        "release": release,
        "basin": "NA",
        "baseline_seasons": run["baseline"],
        "synthetic_years": run["years"],
        "seeds": [run["seed"] * 1000 + i for i in range(run["years"] // 1000)],
        "storms": int(tracks["storm_id"].nunique()),
        "fixes": len(tracks),
        "method": "STORM (Bloemendaal et al. 2020, doi:10.1038/s41597-020-0381-2), "
        "preprocessing and generator from the author's GitHub at the commits below, "
        "patched as listed in regenerate.py",
        "storm_commits": run["storm_commits"],
        "inputs": run["inputs"],
        "code": {
            "repository": "https://github.com/fulton-ring/agent-content-demos",
            "folder": "storm-yearly-regeneration",
            "commit": _git.stdout.strip(),
            "uncommitted_changes": bool(_status.stdout.strip()),
        },
        "python": platform.python_version(),
        "packages": {p: importlib.metadata.version(p) for p in _packages},
        "outputs": {
            p.name: {"sha256": sha256(p), "bytes": p.stat().st_size}
            for p in (tracks_path, text_path)
        },
        "units": {
            "wind_10min_ms": "10-minute sustained wind, m/s (divide by 0.88 for 1-minute)",
            "pressure_hpa": "central pressure, hPa",
            "rmax_km": "radius of maximum wind, km",
            "category": "STORM's Saffir-Simpson category from 10-minute wind (0 = tropical storm)",
            "step": "3-hourly step from genesis",
            "year": "synthetic year within its 1,000-year file",
        },
    }
    (item / "manifest.json").write_text(json.dumps(manifest, indent=2))
    manifest["code"]
    return (manifest,)


@app.cell
def _(mo):
    mo.md(r"""
    ## The Portolan catalogue

    `portolan init` once, then per release: write the human metadata (title, licence,
    providers, how it was made), `portolan add` the item folder, regenerate the READMEs and
    `portolan check`. The licence is CC-BY-4.0 because ERA5 (Copernicus) requires attribution;
    IBTrACS is public domain and STORM v4's own data were CC0. The contact is a placeholder
    (`STORM_CONTACT_EMAIL`) a founder sets before a real push.
    """)
    return


@app.cell
def _(catalogue, first_season, json, last_season, os, release, run, subprocess):
    seed = run["seed"]

    def portolan(*args: str) -> str:
        """Run one Portolan CLI command in the catalogue; fail loudly on a non-zero exit."""
        done = subprocess.run(
            ["portolan", *args], cwd=catalogue, capture_output=True, text=True, check=False
        )
        assert done.returncode == 0, (
            f"portolan {' '.join(args)} failed:\n{done.stdout}{done.stderr}"
        )
        return done.stdout

    _log = []
    if not (catalogue / "catalog.json").exists():
        _log.append(
            portolan(
                "init",
                "--auto",
                "--id",
                "fri-storm-tracks",
                "--title",
                "Synthetic hurricane tracks (STORM, regenerated yearly)",
                "--license",
                "CC-BY-4.0",
                ".",
            )
        )
    _email = os.environ.get("STORM_CONTACT_EMAIL", "publisher@example.org")
    _metadata = {
        "title": "STORM synthetic tracks, North Atlantic",
        "description": (
            "10,000 years of synthetic North Atlantic tropical cyclone tracks from STORM, "
            f"refitted to IBTrACS {first_season}-{last_season}. One item per baseline and seed."
        ),
        "contact": {"name": "Fulton Ring", "email": _email},
        "license": "CC-BY-4.0",
        "providers": [
            {
                "name": "Fulton Ring",
                "roles": ["producer", "processor", "host"],
                "url": "https://fultonring.com",
            }
        ],
        "citation": (
            "Bloemendaal, N. et al. (2020). Generation of a global synthetic tropical cyclone "
            "hazard dataset using STORM. Scientific Data 7, 40."
        ),
        "attribution": "Contains modified Copernicus Climate Change Service information (ERA5).",
        "source_url": "https://github.com/fulton-ring/agent-content-demos/tree/main/storm-yearly-regeneration",
        "processing_notes": (
            f"Release {release}: STORM's preprocessing and generator from github.com/NBloemendaal "
            "at pinned commits, refitted to IBTrACS v04r01 and ERA5 monthly means over the same "
            "seasons; see manifest.json."
        ),
        "keywords": ["tropical cyclone", "hurricane", "synthetic tracks", "STORM", "IBTrACS"],
    }
    # Titles and descriptions don't inherit in Portolan, so each level gets its own.
    _release = {
        **_metadata,
        "title": f"STORM North Atlantic, IBTrACS {first_season}-{last_season}, seed {seed}",
        "description": (
            f"10,000 synthetic years refitted to IBTrACS {first_season}-{last_season}. "
            "tracks.parquet has one point per 3-hourly fix; storm_text.zip is the same tracks "
            "in STORM's text format; manifest.json lists inputs, code and checksums."
        ),
    }
    for _folder, _values in (
        (catalogue, {**_metadata, "title": "Fulton Ring synthetic hurricane tracks"}),
        (catalogue / "storm-north-atlantic", _metadata),
        (catalogue / "storm-north-atlantic" / release, _release),
    ):
        (_folder / ".portolan").mkdir(parents=True, exist_ok=True)
        # YAML is a superset of JSON, so the metadata file can be written as JSON.
        (_folder / ".portolan" / "metadata.yaml").write_text(json.dumps(_values, indent=2))
    _log.append(
        portolan("add", "--datetime", f"{last_season}-12-31", f"storm-north-atlantic/{release}")
    )
    _log.append(portolan("readme"))
    _log.append(portolan("check", "--no-data", "--fix"))
    portolan_log = "\n".join(_log)
    print(portolan_log)
    return (portolan,)


@app.cell
def _(portolan):
    check_report = portolan("check", "--no-data")
    push_plan = portolan("push", "s3://example-bucket/fri-storm", "--dry-run")
    print(check_report)
    print(push_plan)
    return


@app.cell
def _(HERE, catalogue, pd, shutil, write):
    # The catalogue's metadata (not its data) is kept in the repo as a sample of the layout.
    _sample = HERE / "sample_catalogue"
    if _sample.exists():
        shutil.rmtree(_sample)
    _rows = []
    for _path in sorted(catalogue.rglob("*")):
        if _path.is_file():
            _relative = _path.relative_to(catalogue)
            _rows.append({"path": str(_relative), "megabytes": _path.stat().st_size / 1e6})
            if _path.suffix in (".json", ".md", ".yaml"):
                (_sample / _relative).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy(_path, _sample / _relative)
    catalogue_files = pd.DataFrame(_rows)
    write(catalogue_files, "catalogue_files.csv")
    catalogue_files
    return (catalogue_files,)


@app.cell
def _(mo):
    mo.md(r"""
    ## What a yearly run costs

    From `run.json` (this run) and the files above. The generator's time is CPU seconds summed
    over the ten files; on `STORM_WORKERS` cores the wall time divides by about that many.
    """)
    return


@app.cell
def _(catalogue_files, pd, run, write):
    _per_thousand = run["generator_cpu_seconds"] / (run["years"] / 1000)
    _published = catalogue_files["megabytes"].sum()
    cost = pd.DataFrame(
        [
            ("ERA5 monthly means (download, s)", run["era5_seconds"]),
            ("STORM preprocessing (s)", run["preprocessing_seconds"]),
            ("generator CPU per 1,000 years (s)", _per_thousand),
            ("generator CPU, all years (s)", run["generator_cpu_seconds"]),
            ("STORM text per 1,000 years (MB)", run["track_megabytes"] / (run["years"] / 1000)),
            ("STORM text, all years (MB)", run["track_megabytes"]),
            ("published release, all files (MB)", _published),
            ("published per 1,000 years (MB)", _published / (run["years"] / 1000)),
        ],
        columns=["quantity", "value"],
    )
    write(cost, "yearly_cost.csv")
    cost
    return


if __name__ == "__main__":
    app.run()

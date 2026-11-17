"""Native-grid rainfall access, interval alignment, and reproducible local snapshots."""

import json
import math
from pathlib import Path
from typing import Any

import icechunk
import marimo
import numpy as np
import pandas as pd
import requests
import xarray as xr

app = marimo.App(width="medium")


def native_subset(ds: xr.Dataset, bounds: tuple[float, float, float, float]) -> xr.Dataset:
    """Select existing grid cells without changing order or longitude convention."""
    south, north, west, east = bounds
    longitude_offset = 360 if float(ds.longitude.min()) >= 0 else 0
    lat = np.flatnonzero((ds.latitude.values >= south) & (ds.latitude.values <= north))
    lon = np.flatnonzero(
        (ds.longitude.values >= west + longitude_offset)
        & (ds.longitude.values <= east + longitude_offset)
    )
    if not len(lat) or not len(lon):
        raise ValueError("Requested bounds contain no native grid cells")
    return ds.isel(latitude=lat, longitude=lon)


def hourly_rain(ds: xr.Dataset, source: str) -> pd.DataFrame:
    """Integrate native intervals, refusing incomplete hours instead of filling zeros."""
    variable = "total_precipitation" if source == "era5" else "precipitation_surface"
    rain = ds[variable]
    expected_units = "m" if source == "era5" else "kg m-2 s-1"
    if rain.attrs.get("units") != expected_units:
        raise ValueError(f"Unexpected {source} units: {rain.attrs.get('units')}")
    lon = -73.99 + (360 if float(ds.longitude.min()) >= 0 else 0)
    point = rain.sel(latitude=40.676, longitude=lon, method="nearest")
    start = pd.DatetimeIndex(point.time.values)
    if source != "imerg":
        start = start - pd.Timedelta(hours=1)
    duration_seconds = 1800 if source == "imerg" else 3600
    factor = 1000 if source == "era5" else duration_seconds
    series = pd.Series(point.values * factor, index=start)
    expected_count = 2 if source == "imerg" else 1
    sums = series.resample("1h").sum(min_count=expected_count)
    result = pd.DataFrame(
        {
            "interval_start": pd.DatetimeIndex(sums.index).tz_localize("UTC"),
            "precipitation_mm": sums.values,
        }
    )
    result["interval_end"] = result.interval_start + pd.Timedelta(hours=1)
    result["source"] = source
    result["latitude"] = float(point.latitude)
    result["longitude"] = float(point.longitude)
    result["source_timestamp_convention"] = (
        "interval_start" if source == "imerg" else "interval_end"
    )
    return result


def round_trip(ds: xr.Dataset, path: Path, group: str) -> dict[str, object]:
    """Persist materialized native values and verify a separately reopened snapshot."""
    repo = icechunk.Repository.open_or_create(icechunk.local_filesystem_storage(str(path)))
    session = repo.writable_session("main")
    clean = ds.copy(deep=True)
    for name in clean.variables:
        clean[name].encoding = {}
    clean.to_zarr(session.store, group=group, mode="a", consolidated=False)
    snapshot = session.commit(f"Native {group} subset")
    reopened_repo = icechunk.Repository.open(icechunk.local_filesystem_storage(str(path)))
    reopened = xr.open_zarr(
        reopened_repo.readonly_session(snapshot_id=snapshot).store,
        group=group,
        chunks=None,
        consolidated=False,
    ).load()
    xr.testing.assert_identical(clean, reopened)
    for name in clean.data_vars:
        np.testing.assert_array_equal(np.isnan(clean[name]), np.isnan(reopened[name]))
    return {"snapshot": snapshot, "round_trip_identical": True}


def fetch_bounded(url: str, budget: dict[str, int]) -> bytes:
    """Count response-body bytes, with a hard aggregate budget and request timeout."""
    parts = []
    with requests.get(url, stream=True, timeout=(10, 45)) as response:
        response.raise_for_status()
        for _index, part in enumerate(response.iter_content(65536)):
            budget["bytes"] += len(part)
            if budget["bytes"] > 64 * 1024 * 1024 or _index > 1024:
                raise ValueError("ERA5 HTTP response budget exceeded")
            parts.append(part)
    return b"".join(parts)


def era5_subset(
    url: str,
    output: Path,
    start: pd.Timestamp,
    hours: int,
    bounds: tuple[float, float, float, float],
) -> tuple[xr.Dataset, dict[str, Any]]:
    """Stage only coordinates and preflighted hourly precipitation chunks."""
    budget = {"bytes": 0}
    metadata = json.loads(fetch_bounded(url + "/.zmetadata", budget))["metadata"]
    root = output / "era5-http-cache"
    root.mkdir(parents=True, exist_ok=True)
    kept = {k: v for k, v in metadata.items() if "/" not in k}
    for name in ["time", "latitude", "longitude", "total_precipitation"]:
        for suffix in [".zarray", ".zattrs"]:
            kept[f"{name}/{suffix}"] = metadata[f"{name}/{suffix}"]
        folder = root / name
        folder.mkdir(exist_ok=True)
        if name == "total_precipitation":
            continue
        shape = metadata[f"{name}/.zarray"]["shape"][0]
        chunk = metadata[f"{name}/.zarray"]["chunks"][0]
        if math.ceil(shape / chunk) > 16:
            raise ValueError("Unexpectedly fragmented ERA5 coordinate")
        for index in range(math.ceil(shape / chunk)):
            (folder / str(index)).write_bytes(fetch_bounded(f"{url}/{name}/{index}", budget))
    (root / ".zmetadata").write_text(json.dumps({"zarr_consolidated_format": 1, "metadata": kept}))
    for key, value in kept.items():
        (root / key).write_text(json.dumps(value))
    ds = xr.open_zarr(str(root), chunks=None, consolidated=True)
    wanted = pd.date_range(start + pd.Timedelta(hours=1), periods=hours, freq="1h")
    indices = pd.DatetimeIndex(ds.time.values).get_indexer(wanted)
    if np.any(indices < 0):
        raise ValueError(f"ERA5 archive does not cover {wanted[0]}..{wanted[-1]}")
    array = metadata["total_precipitation/.zarray"]
    if array["chunks"] != [1, 721, 1440]:
        raise ValueError("Unrecognized ERA5 geometry; refusing an unbounded download")
    decoded_bytes = hours * math.prod(array["chunks"]) * np.dtype(array["dtype"]).itemsize
    for index in indices:
        key = f"total_precipitation/{index}.0.0"
        (root / key).write_bytes(fetch_bounded(f"{url}/{key}", budget))
    selected = native_subset(ds.isel(time=indices), bounds).load()
    return selected, {
        "downloaded_http_bytes": budget["bytes"],
        "touched_chunk_decoded_bytes": decoded_bytes,
        "archive_last_time": str(ds.time.values[-1]),
        "transfer_note": "Six or fewer explicit hourly global chunks, not a global time slab",
    }


def dynamical_subset(
    url: str,
    start: pd.Timestamp,
    hours: int,
    bounds: tuple[float, float, float, float],
    source: str,
) -> tuple[xr.Dataset, dict[str, Any]]:
    collection_response = requests.get(url, timeout=30)
    collection_response.raise_for_status()
    asset = collection_response.json()["assets"]["icechunk-https"]["href"]
    repo = icechunk.Repository.open(icechunk.http_storage(asset))
    session = repo.readonly_session("main")
    ds = xr.open_zarr(session.store, chunks=None, consolidated=False)[["precipitation_surface"]]
    step = 30 if source == "imerg" else 60
    first = start if source == "imerg" else start + pd.Timedelta(hours=1)
    wanted = pd.date_range(first, periods=hours * 60 // step, freq=f"{step}min")
    subset = native_subset(ds.sel(time=wanted), bounds)
    chunks = ds.precipitation_surface.encoding["chunks"]
    touched = 1
    for dim, chunk in zip(ds.precipitation_surface.dims, chunks, strict=True):
        indices = ds.indexes[dim].get_indexer(subset[dim].values)
        touched *= len(np.unique(indices // chunk))
    decoded_bytes = touched * math.prod(chunks) * 4
    if decoded_bytes > 256 * 1024 * 1024:
        raise ValueError("Dynamical selection exceeds 256 MiB decoded chunk budget")
    subset.load()
    return subset, {
        "upstream_snapshot": session.snapshot_id,
        "downloaded_http_bytes": None,
        "touched_chunk_decoded_bytes": decoded_bytes,
        "touched_chunks": touched,
        "transfer_note": "Rust HTTP bytes unavailable; decoded bytes are NOT network bytes",
    }


@app.cell
def introduction() -> tuple[Any, ...]:
    import marimo

    marimo.md("""
    # Can three rainfall archives play nicely together?

    Download a bounded NYC slice, retain each native grid, then reopen local
    Icechunk snapshots and assert identical coordinates, values, and missingness.
    The default is Hurricane Ida, September 2, 2021: WeatherBench's hourly ERA5
    mirror ends January 10, 2023 and cannot supply the September 2023 flood.
    """)
    return (marimo,)


@app.cell
def imports() -> tuple[Any, ...]:
    import json
    import os
    import time
    from pathlib import Path

    import numpy as np
    import pandas as pd

    from gridded import dynamical_subset, era5_subset, hourly_rain, round_trip

    return Path, dynamical_subset, era5_subset, hourly_rain, json, np, os, pd, round_trip, time


@app.cell
def configuration(Path: Any, os: Any, pd: Any) -> tuple[Any, ...]:
    output = Path(os.environ["CLIMATE_OUTPUT"])
    output.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(os.environ["CLIMATE_START"])
    if start.tz is not None:
        start = start.tz_convert("UTC").tz_localize(None)
    hours = int(os.environ["CLIMATE_HOURS"])
    if not 1 <= hours <= 6 or start != start.floor("h"):
        raise ValueError("Use 1..6 whole hours, beginning on an exact UTC hour")
    bounds = tuple(
        float(os.environ[f"CLIMATE_{key}"]) for key in ("LAT_MIN", "LAT_MAX", "LON_MIN", "LON_MAX")
    )
    if len(bounds) != 4 or not (0 < bounds[1] - bounds[0] <= 1 and 0 < bounds[3] - bounds[2] <= 1):
        raise ValueError("Bounds must span no more than one degree per axis")
    return bounds, hours, output, start


@app.cell
def download_and_measure(
    bounds: Any,
    hours: Any,
    output: Any,
    start: Any,
    marimo: Any,
    os: Any,
    time: Any,
    pd: Any,
    np: Any,
    json: Any,
    era5_subset: Any,
    dynamical_subset: Any,
    hourly_rain: Any,
    round_trip: Any,
) -> tuple[Any, ...]:
    marimo.md("""
    ## Read only the needed precipitation

    MRMS labels the **end of the previous hour**; IMERG labels the **start of a
    half-hour**. ERA5 precipitation is metres accumulated over the previous hour.
    Rate integration and a one-hour timestamp shift are essential before joining.
    Native arrays below are not resampled. The derived table uses the nearest
    native cell to 40.676°N, 73.99°W, not three supposedly identical locations.
    """)
    records = []
    tables = []
    for source in ["mrms", "imerg", "era5"]:
        began = time.monotonic()
        if source == "era5":
            native, metrics = era5_subset(
                os.environ["CLIMATE_ERA5_URL"], output, start, hours, bounds
            )
        else:
            native, metrics = dynamical_subset(
                os.environ[f"CLIMATE_{source.upper()}_STAC_URL"], start, hours, bounds, source
            )
        table = hourly_rain(native, source)
        if len(table) != hours or table.interval_start.iloc[0] != start.tz_localize("UTC"):
            raise AssertionError("Hourly integration shifted or lost the requested window")
        local = output / f"{source}.icechunk"
        metrics.update(round_trip(native, local, source))
        payload = int(sum(v.nbytes for v in native.data_vars.values()))
        metrics.update(
            {
                "source": source,
                "start": str(start),
                "hours": hours,
                "shape": dict(native.sizes),
                "numeric_data_bytes": payload,
                "numeric_coordinate_bytes": int(sum(v.nbytes for v in native.coords.values())),
                "storage_bytes": sum(p.stat().st_size for p in local.rglob("*") if p.is_file()),
                "decoded_chunk_amplification": metrics["touched_chunk_decoded_bytes"] / payload,
                "http_transfer_amplification": (
                    metrics["downloaded_http_bytes"] / payload
                    if metrics["downloaded_http_bytes"] is not None
                    else None
                ),
                "nan_count": int(sum(np.isnan(v.values).sum() for v in native.data_vars.values())),
                "source_first_time": str(native.time.values[0]),
                "source_last_time": str(native.time.values[-1]),
                "elapsed_seconds": round(time.monotonic() - began, 3),
            }
        )
        tables.append(table)
        records.append(metrics)
        print(json.dumps(metrics, default=str))
    rainfall = pd.concat(tables, ignore_index=True)
    rainfall.to_parquet(output / "rainfall-hourly.parquet", index=False)
    rainfall.to_csv(output / "rainfall-hourly.csv", index=False)
    (output / "gridded-summary.json").write_text(json.dumps(records, indent=2, default=str) + "\n")
    return rainfall, records


@app.cell
def conclusions(rainfall: Any, records: Any, marimo: Any) -> None:
    marimo.vstack(
        [
            marimo.md("""
        ## What this proves—and doesn't

        Exact local round trips prove formatting, not scientific equivalence.
        IMERG Early is a low-latency satellite product; MRMS is an hourly merged
        radar/gauge estimate; ERA5 is reanalysis, too coarse for street flooding.
        No missing value becomes zero. Incomplete half-hour pairs remain missing.
        Decoded-chunk amplification is not compressed network transfer. Upstream
        Icechunk snapshots are pinned in the summary; subsequent runs may see updates.
        """),
            marimo.ui.table(rainfall),
            marimo.ui.table(records),
        ]
    )
    return


if __name__ == "__main__":
    app.run()

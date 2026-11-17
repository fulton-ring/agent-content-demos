import json
import math
from pathlib import Path
from typing import Any

import icechunk
import numpy as np
import pandas as pd
import requests
import xarray as xr


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

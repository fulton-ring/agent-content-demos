import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")

with app.setup:
    from typing import Any


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

    from gridded_core import dynamical_subset, era5_subset, hourly_rain, round_trip

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

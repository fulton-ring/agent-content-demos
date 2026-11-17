import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import io
    import json
    import os
    import time
    from pathlib import Path

    import marimo as mo
    import matplotlib
    import pandas as pd
    import requests

    from interop import distance_km, download, hourly_depth

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    output = Path(os.environ["CLIMATE_OUTPUT"])
    output.mkdir(parents=True, exist_ok=True)
    start = pd.Timestamp(os.environ["CLIMATE_START"])
    start = start.tz_localize("UTC") if start.tz is None else start.tz_convert("UTC")
    hours = int(os.environ["CLIMATE_HOURS"])
    if not 1 <= hours <= 6 or start != start.floor("h"):
        raise ValueError("Choose 1–6 hours beginning on an exact UTC hour")
    end = start + pd.Timedelta(hours=hours)
    measurements = {}
    started = time.perf_counter()
    return (
        distance_km,
        download,
        end,
        hourly_depth,
        hours,
        io,
        json,
        measurements,
        mo,
        os,
        output,
        pd,
        plt,
        requests,
        start,
        started,
        time,
    )


@app.cell
def _(mo):
    mo.md("""
    # Can NYC climate datasets play nicely together?

    Issue #293. Read `gridded.py` first: it downloads native-grid MRMS, IMERG and ERA5,
    validates a local Icechunk round trip, and produces interval-aware rainfall tables.
    This notebook downloads real point observations and tests a join during Hurricane Ida.
    It does not infer flood causes, forecast hazards, or treat missing observations as dry.

    Source records and array chunks stay in the ignored output folder. FloodNet's linked
    agreement restricts redistribution; only aggregate diagnostics and our chart are published.
    """)
    return


@app.cell
def _(download, end, hours, hourly_depth, json, measurements, os, output, pd, start):
    _body, measurements["floodnet_deployments"] = download(os.environ["CLIMATE_FLOOD_URL"])
    _deployments = json.loads(_body)["deployments"]
    _eligible = [
        d
        for d in _deployments
        if "Hoyt St/5th St" in d["name"]
        and pd.Timestamp(d["date_deployed"], tz="America/New_York") <= start
        and (not d["date_down"] or pd.Timestamp(d["date_down"], tz="America/New_York") >= end)
    ]
    if len(_eligible) != 1:
        raise ValueError("Expected exactly one eligible Hoyt/5th deployment")
    deployment = _eligible[0]
    sensor_lon, sensor_lat = deployment["location"]["coordinates"]
    _body, measurements["floodnet_depth"] = download(
        f"{os.environ['CLIMATE_FLOOD_URL']}/{deployment['deployment_id']}/depth",
        {"start_time": start.isoformat(), "end_time": end.isoformat()},
    )
    depth = pd.DataFrame(json.loads(_body)["depth_data"])
    if depth.empty or "depth_proc_mm" not in depth:
        raise ValueError("FloodNet returned no measurements or changed its schema")
    depth["time"] = pd.to_datetime(depth.time, utc=True)
    depth["depth_proc_mm"] = pd.to_numeric(depth.depth_proc_mm, errors="raise")
    depth = depth.loc[(depth.time >= start) & (depth.time < end)].sort_values("time")
    depth.to_parquet(output / "floodnet-local-only.parquet", index=False)
    pd.testing.assert_frame_equal(depth, pd.read_parquet(output / "floodnet-local-only.parquet"))
    depth_hourly = hourly_depth(depth, start, hours)
    depth_hourly.to_parquet(output / "floodnet-hourly-local-only.parquet")
    return deployment, depth, depth_hourly, sensor_lat, sensor_lon


@app.cell
def _(download, end, io, json, measurements, os, output, pd, start):
    _body, measurements["coops"] = download(
        os.environ["CLIMATE_TIDE_URL"],
        {
            "begin_date": start.strftime("%Y%m%d %H:%M"),
            "end_date": end.strftime("%Y%m%d %H:%M"),
            "station": "8518750",
            "product": "water_level",
            "datum": "NAVD",
            "time_zone": "gmt",
            "units": "metric",
            "format": "json",
            "application": "nyc-climate-icechunk",
        },
    )
    _payload = json.loads(_body)
    if "error" in _payload:
        raise ValueError(_payload["error"])
    tide = pd.DataFrame(_payload["data"])
    tide["time"] = pd.to_datetime(tide.t, utc=True)
    tide["water_level_m_NAVD88"] = pd.to_numeric(tide.v, errors="raise")
    tide = tide.loc[(tide.time >= start) & (tide.time < end)]
    if tide.empty:
        raise ValueError("No tide observations in the event window")
    tide.to_parquet(output / "tide.parquet", index=False)
    _body, measurements["iem_weather"] = download(
        os.environ["CLIMATE_IEM_URL"],
        {
            "station": "JFK",
            "network": "NY_ASOS",
            "data": "all",
            "sts": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "ets": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "tz": "Etc/UTC",
            "format": "onlycomma",
            "latlon": "yes",
            "elev": "no",
            "missing": "M",
            "trace": "T",
            "direct": "no",
            "report_type": 3,
        },
    )
    weather = pd.read_csv(io.BytesIO(_body), na_values=["M"], dtype={"p01i": "string"})
    if weather.empty or "valid" not in weather:
        raise ValueError("IEM returned no weather rows or changed its schema")
    weather["time"] = pd.to_datetime(weather.valid, utc=True)
    weather["precip_trace"] = weather.p01i.eq("T")
    weather["precip_trailing_hour_mm"] = (
        pd.to_numeric(weather.p01i.mask(weather.precip_trace), errors="raise") * 25.4
    )
    weather["temperature_C"] = (pd.to_numeric(weather.tmpf, errors="raise") - 32) / 1.8
    weather.to_parquet(output / "weather.parquet", index=False)
    _body, measurements["nws_recent"] = download(os.environ["CLIMATE_NWS_URL"])
    nws = json.loads(_body)["properties"]
    return nws, tide, weather


@app.cell
def _(download, json, measurements, os, output, requests):
    _body, measurements["gieo_page"] = download(os.environ["CLIMATE_GIEO_URL"])
    _page = _body.decode()
    access_audit = [
        {
            "source": "GIEO",
            "status": "blocked_machine_readable_access",
            "evidence": {
                "plot_images_present": "www.atm.helsinki.fi/pics/" in _page,
                "grafana_link_present": "grafana.atm.helsinki.fi" in _page,
            },
            "next_step": "Request export/API, units, time coverage, QC and redistribution rights",
            "end_to_end_verified": False,
        }
    ]
    for _product in ["M2T1NXSLV", "ECO_L2T_LSTE"]:
        _body, measurements[_product] = download(
            os.environ["CLIMATE_CMR_URL"],
            {
                "short_name": _product,
                "page_size": 1,
                "bounding_box": "-74.1,40.6,-73.7,40.9",
                "temporal": "2021-09-01T00:00:00Z,2021-09-04T00:00:00Z",
            },
        )
        _entries = json.loads(_body)["feed"]["entry"]
        _links = [
            link["href"]
            for entry in _entries
            for link in entry.get("links", [])
            if link.get("rel", "").endswith("/data#") and link["href"].startswith("https://")
        ]
        _probe_status = None
        if _links:
            with requests.get(
                _links[0], headers={"Range": "bytes=0-1023"}, stream=True, timeout=30
            ) as _response:
                _probe_status = _response.status_code
        access_audit.append(
            {
                "source": _product,
                "status": (
                    "blocked_authentication"
                    if _probe_status in (401, 403)
                    else "metadata_only_not_downloaded"
                ),
                "matching_granule_found": bool(_entries),
                "unauthenticated_download_http_status": _probe_status,
                "next_step": "Authenticate with NASA Earthdata and test a bounded granule",
                "end_to_end_verified": False,
            }
        )
    _body, measurements["era5_land_metadata"] = download(os.environ["CLIMATE_CDS_URL"])
    _cds = json.loads(_body)
    access_audit.append(
        {
            "source": "ERA5-Land",
            "status": "metadata_only_not_downloaded",
            "metadata_keys": sorted(_cds)[:8],
            "end_to_end_verified": False,
            "next_step": "CDS account, accepted dataset terms and retrieval credentials",
        }
    )
    _body, measurements["stormwater_metadata"] = download(os.environ["CLIMATE_MAP_URL"])
    _map = json.loads(_body)
    access_audit.append(
        {
            "source": "NYC stormwater scenarios",
            "status": "metadata_only_not_downloaded",
            "dataset_name": _map["name"],
            "end_to_end_verified": False,
            "next_step": "Download scenario geometry separately; never join as observed flooding",
        }
    )
    for _name, _reason in [
        ("AirNow/AQS", "Separate current/archival feeds and API keys; not tested"),
        ("NYC Micronet", "Redistribution permission and possible fees; not accessed"),
    ]:
        access_audit.append(
            {
                "source": _name,
                "status": "not_attempted",
                "next_step": _reason,
                "end_to_end_verified": False,
            }
        )
    (output / "access-audit.json").write_text(json.dumps(access_audit, indent=2) + "\n")
    return (access_audit,)


@app.cell
def _(
    deployment,
    depth,
    depth_hourly,
    distance_km,
    end,
    hours,
    json,
    measurements,
    nws,
    output,
    pd,
    plt,
    sensor_lat,
    sensor_lon,
    start,
    started,
    tide,
    time,
    weather,
):
    rainfall = pd.read_parquet(output / "rainfall-hourly.parquet")
    rainfall["interval_start"] = pd.to_datetime(rainfall.interval_start, utc=True)
    rainfall["interval_end"] = pd.to_datetime(rainfall.interval_end, utc=True)
    if rainfall.duplicated(["source", "interval_start"]).any():
        raise ValueError("Duplicate rainfall intervals")
    if not rainfall.interval_end.sub(rainfall.interval_start).eq(pd.Timedelta(hours=1)).all():
        raise ValueError("Rainfall intervals must be one hour")
    _in_window = rainfall.interval_start.ge(start) & rainfall.interval_end.le(end)
    if not _in_window.all():
        raise ValueError("Rainfall escaped the requested analysis window")
    rain_wide = rainfall.pivot(index="interval_start", columns="source", values="precipitation_mm")
    joined = depth_hourly.join(rain_wide, how="left")
    _tide_hourly = tide.set_index("time").water_level_m_NAVD88.resample("h").mean()
    joined["harbor_level_m_NAVD88_mean"] = _tide_hourly.reindex(joined.index)
    joined.to_parquet(output / "joined-local-only.parquet")
    _distances = {
        str(r.source): round(distance_km(sensor_lat, sensor_lon, r.latitude, r.longitude), 3)
        for r in rainfall.drop_duplicates("source").itertuples()
    }
    _fig, _axes = plt.subplots(3, 1, figsize=(10, 8), sharex=True, layout="constrained")
    rain_wide.plot.bar(ax=_axes[0], width=0.8)
    _axes[0].set_ylabel("Rainfall (mm / UTC hour)")
    _axes[0].set_title("Ida: native-cell rainfall products disagree; grids are not interchangeable")
    _depth_plot = depth.set_index("time").depth_proc_mm.resample("h").max()
    _axes[1].plot(range(hours), _depth_plot.reindex(joined.index), marker="o")
    _axes[1].set_ylabel("Hourly maximum street depth (mm)")
    _axes[2].plot(range(hours), joined.harbor_level_m_NAVD88_mean, marker="o", color="tab:green")
    _axes[2].set_ylabel("Harbor elevation (m NAVD88)")
    _axes[2].set_xticks(range(hours), [t.strftime("%H:%M") for t in joined.index])
    _axes[2].set_xlabel(f"UTC interval start on {start:%Y-%m-%d}; exploratory, not causal")
    _fig.text(
        0.5,
        -0.025,
        "FloodNet (New York University and The City University of New York); "
        "NOAA MRMS / NASA IMERG via dynamical.org; Copernicus ERA5; NOAA CO-OPS.\n"
        "Derived visualization: CC BY-NC-SA 4.0. Not an emergency or navigation product.",
        ha="center",
        fontsize=8,
    )
    _fig.savefig(output / "comparison.png", dpi=160, bbox_inches="tight")
    plt.close(_fig)
    summary = {
        "window_start": start.isoformat(),
        "window_end_exclusive": end.isoformat(),
        "sensor": deployment["name"],
        "depth_rows": len(depth),
        "depth_nonnull": int(depth.depth_proc_mm.notna().sum()),
        "depth_duplicate_timestamps": int(depth.time.duplicated().sum()),
        "depth_median_interval_seconds": float(depth.time.diff().dt.total_seconds().median()),
        "depth_max_gap_seconds": float(depth.time.diff().dt.total_seconds().max()),
        "depth_hourly_valid_counts": joined.valid_readings.tolist(),
        "depth_hours_with_no_valid_measurement": int(joined.valid_readings.eq(0).sum()),
        "tide_rows": len(tide),
        "tide_quality_counts": tide.q.value_counts().to_dict(),
        "weather_rows": len(weather),
        "weather_missing_precip": int(weather.precip_trailing_hour_mm.isna().sum()),
        "weather_minute_offsets": sorted(weather.time.dt.minute.unique().tolist()),
        "nws_latest_in_historical_window": bool(start <= pd.Timestamp(nws["timestamp"]) < end),
        "rainfall_mm_by_source": {
            c: float(rain_wide[c].sum()) if rain_wide[c].notna().sum() == hours else None
            for c in rain_wide
        },
        "rainfall_valid_hours": {c: int(rain_wide[c].notna().sum()) for c in rain_wide},
        "cell_distance_from_sensor_km": _distances,
        "joined_rows": len(joined),
        "measurements": measurements,
        "seconds": round(time.perf_counter() - started, 3),
        "local_parquet_bytes": sum(p.stat().st_size for p in output.glob("*.parquet")),
        "limitations": [
            "MRMS previous-hour and IMERG forward-half-hour windows aligned explicitly",
            "IEM precipitation trailing-hour endpoints are not UTC clock-hour intervals",
            "Raw depth can be noisy; dry/no-data are not interchangeable",
            "This historical sensor returned roughly 250-second spacing, not one-minute data",
            "Harbor datum-referenced elevation cannot be subtracted from local street depth",
            "GIEO starts after the historical event; no full all-source overlap proved",
            "ERA5 mirror is a static archive, not current CDS or ERA5T ingestion",
            "Local Icechunk verified; public object-store/browser deployment not tested",
            "Preliminary IMERG Early is not interchangeable with Final",
        ],
    }
    (output / "sensor-summary.json").write_text(
        json.dumps(summary, indent=2, allow_nan=False) + "\n"
    )
    print(json.dumps(summary, indent=2, allow_nan=False))
    return (summary,)


@app.cell
def _(access_audit, mo, summary):
    mo.md(f"""
    ## Result and boundaries

    The joined analysis has **{summary["joined_rows"]} UTC hours**. Per-source valid-hour counts,
    native-cell distances, measured sizes and transfer times are in `sensor-summary.json`.
    See `comparison.png`: disagreements are evidence to investigate, not values to average away.

    **{sum(not a["end_to_end_verified"] for a in access_audit)} additional sources remain
    unverified end to end.** `access-audit.json` distinguishes metadata discovery, permissions,
    and actual downloads. No successful metadata request counts as a successful data acquisition.
    """)
    return


if __name__ == "__main__":
    app.run()

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import io
    import json
    import logging
    import os
    import time
    import zipfile
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import requests

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log = logging.getLogger("floodnet")
    here = Path(mo.notebook_dir() or ".")
    cache = Path(os.environ.get("FLOODNET_CACHE", Path.home() / ".cache" / "floodnet-street-flooding"))
    results = Path(os.environ.get("FLOODNET_RESULTS", here / "results"))
    for _d in (cache / "tide", cache / "rain", cache / "nfhl", results):
        _d.mkdir(parents=True, exist_ok=True)
    started = time.time()
    session = requests.Session()
    session.headers["User-Agent"] = "floodnet-street-flooding demo (github.com/fulton-ring)"

    def get(url: str, params: dict | None = None, attempts: int = 6) -> requests.Response:
        """GET with a bounded number of retries and backoff; raise if every attempt fails."""
        for attempt in range(attempts):
            try:
                response = session.get(url, params=params, timeout=300)
                response.raise_for_status()
                return response
            except requests.RequestException as error:
                log.warning("%s attempt %d: %s", url, attempt + 1, error)
                time.sleep(min(2**attempt, 30))
        raise RuntimeError(f"{url} failed {attempts} times with {params}")

    def fetch(url: str, name: str) -> Path:
        """Download a file once into the cache."""
        path = cache / name
        if not path.exists():
            path.write_bytes(get(url).content)
        return path

    # In metres, so buffers and distances read in plain units.
    UTM = "EPSG:32618"
    return (
        ThreadPoolExecutor,
        UTM,
        cache,
        fetch,
        get,
        gpd,
        io,
        json,
        log,
        mo,
        np,
        pd,
        plt,
        results,
        started,
        time,
        zipfile,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # What New York's street-level flood sensors can tell us

    FloodNet is a network of cheap ultrasonic sensors, run by NYU and CUNY with city agencies,
    that measures water depth on New York streets every minute. NYC Open Data publishes every
    flood event the sensors have recorded since 2020. This notebook does the analysis a city would
    want from that feed and checks four things:

    1. **The network today**: sensors and events in the feed, against the 87 sensors and 360
       events (October 2020 to May 2023) in the FloodNet team's 2024 paper.
    2. **Rain or tide**: each event checked against NOAA tide gauges and airport rain gauges.
    3. **Mapped risk**: how many flooding sensors and events sit outside FEMA's flood zones and
       outside the city's Stormwater Flood Maps.
    4. **What's nearby**: schools, hospitals, fire and EMS stations, nursing homes and subway
       entrances near the sensors that flood most often.

    It ends with the Hurricane Ida "50 minutes early" claim and what didn't work.

    **What it can't show:** flooding where there is no sensor. FloodNet puts sensors at places
    already known to flood, so these are not a random sample of the city.

    Issue [#213](https://github.com/fulton-ring/agent-content-demos/issues/213). Data:
    FloodNet (New York University and The City University of New York), Mydlarz et al. (2024).
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. The network today

    Two NYC Open Data tables, downloaded fresh on every run: sensor deployment metadata
    (`kb2e-tjy3`) and flood events (`aq7i-eu5q`). FloodNet defines an event as a run of
    readings deeper than 10 mm that its team has checked by hand. Many events are shallow, so we
    also count **floods**: events whose peak reached 4 inches at the sensor, the bottom of the
    "nuisance" tier in the city's Stormwater Flood Maps (a rule we take from Mark Bauer's
    [FloodNet tutorials](https://github.com/mebauer/floodnet-nyc-tutorial)).
    """)
    return


@app.cell
def _(get, io, pd):
    _base = "https://data.cityofnewyork.us/resource"
    sensors = pd.read_csv(
        io.BytesIO(get(f"{_base}/kb2e-tjy3.csv", {"$limit": 50000}).content),
        parse_dates=["date_installed", "date_removed"],
    )
    events = pd.read_csv(io.BytesIO(get(f"{_base}/aq7i-eu5q.csv", {"$limit": 50000}).content))
    assert len(sensors) < 50000 and len(events) < 50000, "raise $limit: a table hit the cap"
    assert sensors.sensor_id.is_unique, "sensor ids must be unique"
    # Times are published in UTC with no offset.
    for _c in ("flood_start_time", "flood_end_time"):
        events[_c] = pd.to_datetime(events[_c], utc=True)
    events = events.merge(
        sensors[["sensor_id", "borough", "tidally_influenced", "latitude", "longitude"]],
        on="sensor_id",
        how="left",
        validate="many_to_one",
    )
    events["flood"] = events.max_depth_inches >= 4
    print(f"{len(sensors)} sensors, {len(events)} events, {events.borough.isna().sum()} unmatched")
    return events, sensors


@app.cell
def _(events, pd, sensors):
    cutoff = events.flood_end_time.max()
    _active = sensors.date_removed.isna() | (sensors.date_removed > cutoff.tz_localize(None))
    _by_sensor = events.groupby("sensor_id").agg(events=("flood", "size"), floods=("flood", "sum"))
    _s = sensors.join(_by_sensor, on="sensor_id").fillna({"events": 0, "floods": 0})
    _s["active"] = _active
    network = (
        _s.groupby("borough")
        .agg(
            sensors_ever=("sensor_id", "size"),
            active_now=("active", "sum"),
            sensors_with_events=("events", lambda e: int((e > 0).sum())),
            events=("events", "sum"),
            floods_4in=("floods", "sum"),
        )
        .astype(int)
    )
    network.loc["All"] = network.sum()
    network["events_per_sensor_with_events"] = (
        network.events / network.sensors_with_events
    ).round(1)

    # The 2024 paper's window: October 2020 to May 2023.
    _paper_end = pd.Timestamp("2023-06-01", tz="UTC")
    paper_window = {
        "events_in_feed_before_june_2023": int((events.flood_start_time < _paper_end).sum()),
        "sensors_installed_before_june_2023": int(
            (sensors.date_installed < _paper_end.tz_localize(None)).sum()
        ),
        "sensors_with_events_before_june_2023": int(
            events[events.flood_start_time < _paper_end].sensor_id.nunique()
        ),
    }
    print(f"Data cutoff {cutoff:%Y-%m-%d}. Paper window in today's feed: {paper_window}")
    network
    return cutoff, network, paper_window


@app.cell
def _(cutoff, mo, network, paper_window):
    _a = network.loc["All"]
    mo.md(f"""
    As of the data cutoff ({cutoff:%Y-%m-%d}), the feed lists **{_a.sensors_ever} sensors**
    ever deployed, **{_a.active_now} still active**, and **{_a.events:,} events** at
    {_a.sensors_with_events} sensors, of which {_a.floods_4in:,} reached 4 inches. The 2024 paper
    counted 87 sensors and 360 events from October 2020 to May 2023. Today's feed has
    {paper_window["events_in_feed_before_june_2023"]} events and
    {paper_window["sensors_installed_before_june_2023"]} sensors installed in that same window,
    so the published record for those years differs from the paper's count (FloodNet reviews and
    republishes events, so a historical count can move).

    Sensors are not spread evenly: compare the boroughs above. A few coastal sensors that flood
    with the tide account for many of the events, which is why the next step splits them out.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Rain or tide?

    FloodNet marks each *sensor* as tidally influenced or not, and Bauer's tutorials split the
    record on that flag. But the flag is per sensor, not per event: a coastal sensor can flood
    in a downpour at low tide. So we check each event against what the water and the sky were
    doing at the time.

    - **When the water peaked.** Each event carries its minute-by-minute depth profile; the peak
      time is the start time plus the offset of the deepest reading.
    - **Tide.** NOAA CO-OPS 6-minute water levels at the nearest of three tide gauges with a
      full record since 2020: the Battery, Kings Point and Sandy Hook, measured against each
      gauge's own Mean High Water (MHW). The tide counts if the water at the gauge was at or above
      MHW within 90 minutes of the peak.
    - **Rain.** Hourly rain at the nearest of four airport weather stations (Central Park,
      LaGuardia, JFK and Newark), from the Iowa Environmental Mesonet's free ASOS archive. Rain
      counts if at least 0.10 inch fell from 3 hours before the event started to the peak.

    That gives four classes: rain only, tide only, both, and neither. The rules are ours. Bauer's
    tutorials use only the sensor flag and flood timing, so the per-event method here is new;
    the thresholds are judgment calls, and a sensitivity table below shows how much they matter.
    """)
    return


@app.cell
def _(events, np, pd):
    def _peak_offset(depths: str, seconds: str) -> float:
        d = np.array(json_list(depths))
        s = np.array(json_list(seconds))
        if len(d) == 0 or len(d) != len(s):
            return np.nan
        return float(s[int(np.argmax(d))])

    def json_list(text: object) -> list[float]:
        """Parse a profile column like '[0.00, 0.43, ...]'; anything else is an empty list."""
        if not isinstance(text, str) or not text.startswith("["):
            return []
        return [float(v) for v in text.strip("[]").split(",") if v.strip()]

    _offset = [
        _peak_offset(d, s)
        for d, s in zip(
            events.flood_profile_depth_inches, events.flood_profile_time_secs, strict=True
        )
    ]
    _fallback = events.onset_time_mins * 60
    events["peak_time"] = events.flood_start_time + pd.to_timedelta(
        pd.Series(_offset, index=events.index).fillna(_fallback), unit="s"
    )
    print(f"Peak time from the profile for {int(np.isfinite(_offset).sum())} of {len(events)}")
    return


@app.cell
def _(cache, cutoff, events, get, io, json, log, pd):
    gauges = pd.DataFrame(
        {
            "gauge": ["8518750", "8516945", "8531680"],
            "gauge_name": ["The Battery", "Kings Point", "Sandy Hook"],
            "lat": [40.7006, 40.8103, 40.4669],
            "lon": [-74.0142, -73.7649, -74.0094],
        }
    )
    _months = pd.period_range(
        events.flood_start_time.min().tz_localize(None).to_period("M"),
        cutoff.tz_localize(None).to_period("M"),
        freq="M",
    )
    _recent = pd.Timestamp.now(tz="UTC").tz_localize(None).to_period("M") - 2
    _frames = []
    for _g in gauges.gauge:
        for _m in _months:
            _path = cache / "tide" / f"{_g}_{_m}.json"
            if _path.exists() and _m < _recent:
                _rows = json.loads(_path.read_text())
            else:
                _payload = get(
                    "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter",
                    {
                        "product": "water_level",
                        "application": "fulton_ring_demo",
                        "begin_date": _m.start_time.strftime("%Y%m%d"),
                        "end_date": _m.end_time.strftime("%Y%m%d"),
                        "datum": "MHW",
                        "station": _g,
                        "time_zone": "gmt",
                        "units": "english",
                        "format": "json",
                    },
                ).json()
                _rows = _payload.get("data", [])
                if not _rows:
                    log.warning("no tide data for %s %s: %s", _g, _m, _payload.get("error"))
                _path.write_text(json.dumps(_rows))
            _frames.append(pd.DataFrame(_rows).assign(gauge=_g))
    tide = pd.concat(_frames, ignore_index=True)
    tide["time"] = pd.to_datetime(tide.t, utc=True)
    tide["ft_above_mhw"] = pd.to_numeric(tide.v, errors="coerce")
    tide = tide.dropna(subset=["ft_above_mhw"])[["gauge", "time", "ft_above_mhw"]]

    stations = pd.DataFrame(
        {
            "station": ["NYC", "LGA", "JFK", "EWR"],
            "lat": [40.7790, 40.7792, 40.6386, 40.6825],
            "lon": [-73.9692, -73.8803, -73.7622, -74.1694],
        }
    )
    _frames = []
    for _st in stations.station:
        for _y in range(events.flood_start_time.min().year, cutoff.year + 1):
            _path = cache / "rain" / f"{_st}_{_y}.csv"
            if not _path.exists() or _y >= cutoff.year:
                _path.write_bytes(
                    get(
                        "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py",
                        {
                            "station": _st,
                            "data": "p01i",
                            "year1": _y,
                            "month1": 1,
                            "day1": 1,
                            "year2": _y + 1,
                            "month2": 1,
                            "day2": 1,
                            "tz": "Etc/UTC",
                            "format": "onlycomma",
                            "report_type": 3,  # routine hourly reports: one-hour totals
                            "missing": "empty",
                            "trace": "0.0001",  # a trace of rain counts as 0.0001 in
                        },
                    ).content
                )
            _frames.append(pd.read_csv(io.BytesIO(_path.read_bytes())))
    rain = pd.concat(_frames, ignore_index=True)
    rain["time"] = pd.to_datetime(rain["valid"], utc=True)
    rain = rain.dropna(subset=["p01i"]).drop_duplicates(["station", "time"])
    print(f"{len(tide):,} tide readings, {len(rain):,} hourly rain reports")
    return gauges, rain, stations, tide


@app.cell
def _(UTM, events, gauges, gpd, np, pd, rain, stations, tide):
    def nearest(points: pd.DataFrame, places: pd.DataFrame, key: str) -> pd.Series:
        """Name of the nearest place (by straight-line distance) for each point."""
        _p = gpd.GeoSeries(gpd.points_from_xy(points.longitude, points.latitude), crs=4326)
        _q = gpd.GeoSeries(gpd.points_from_xy(places.lon, places.lat), crs=4326)
        _d = np.stack([_p.to_crs(UTM).distance(q) for q in _q.to_crs(UTM)], axis=1)
        return pd.Series(places[key].to_numpy()[_d.argmin(axis=1)], index=points.index)

    events["gauge"] = nearest(events, gauges, "gauge")
    events["station"] = nearest(events, stations, "station")

    # Tide: highest water at the gauge within 90 minutes of the peak, per event.
    _t = tide.sort_values("time")
    _tide_max = []
    for _g, _grp in events.groupby("gauge"):
        _series = _t[_t.gauge == _g].set_index("time").ft_above_mhw
        for _i, _peak in _grp.peak_time.items():
            _w = _series.loc[_peak - pd.Timedelta("90min") : _peak + pd.Timedelta("90min")]
            _tide_max.append((_i, _w.max() if len(_w) else np.nan))
    events["tide_ft_above_mhw"] = pd.Series(dict(_tide_max))

    # Rain: total at a station from 3 h before the start to the peak. An hourly report at :51
    # covers the hour before it, so the window's end runs one hour past the peak.
    def rain_total(station_rain: pd.Series, start: pd.Timestamp, peak: pd.Timestamp) -> float:
        _w = station_rain.loc[start - pd.Timedelta("3h") : peak + pd.Timedelta("1h")]
        return float(_w.sum()) if len(_w) else np.nan

    _by_station = {
        s: g.set_index("time").p01i.sort_index() for s, g in rain.groupby("station")
    }
    events["rain_in"] = [
        rain_total(_by_station[s], a, p)
        for s, a, p in zip(events.station, events.flood_start_time, events.peak_time, strict=True)
    ]
    events["rain_any_station_in"] = [
        max(rain_total(r, a, p) for r in _by_station.values())
        for a, p in zip(events.flood_start_time, events.peak_time, strict=True)
    ]
    print(
        f"No tide reading for {events.tide_ft_above_mhw.isna().sum()} events, "
        f"no rain report for {events.rain_in.isna().sum()}"
    )
    return


@app.cell
def _(events, np, pd):
    def classify(
        rain_in: pd.Series, tide_ft: pd.Series, min_rain: float = 0.10, min_tide: float = 0.0
    ) -> pd.Series:
        """Rain only, tide only, both or neither, from a rain total (in) and a tide (ft vs MHW)."""
        _rain = rain_in.fillna(0) >= min_rain
        _tide = tide_ft.fillna(-99) >= min_tide
        return pd.Series(
            np.select(
                [_rain & ~_tide, _tide & ~_rain, _rain & _tide],
                ["rain only", "tide only", "both"],
                "neither",
            ),
            index=rain_in.index,
        )

    events["cause"] = classify(events.rain_in, events.tide_ft_above_mhw)
    _order = ["rain only", "tide only", "both", "neither"]
    causes = pd.DataFrame(
        {
            "all events": events.cause.value_counts(),
            "floods (4 in+)": events[events.flood].cause.value_counts(),
            "at sensors FloodNet flags tidal": events[
                events.tidally_influenced == "Yes"
            ].cause.value_counts(),
            "at sensors FloodNet flags non-tidal": events[
                events.tidally_influenced == "No"
            ].cause.value_counts(),
        }
    ).reindex(_order).fillna(0).astype(int)
    cause_share = (causes / causes.sum() * 100).round(1)
    causes
    return cause_share, causes, classify


@app.cell
def _(cause_share):
    cause_share
    return


@app.cell
def _(mo):
    mo.md(r"""
    Read the two right-hand columns as a check on the method: events at sensors FloodNet flags as
    tidal should come out mostly "tide only" or "both", and events at non-tidal sensors mostly
    "rain only". "Neither" means no gauge saw enough rain and the nearest tide gauge was below
    MHW: a downpour that missed the airport gauges, a sensor glitch, snow, or a tide that runs
    higher or later in a bay than at the gauge (Jamaica Bay has no long-running NOAA gauge).

    **How much do the thresholds matter?** The same counts under looser and stricter rules, and
    with rain taken at whichever of the four stations saw the most:
    """)
    return


@app.cell
def _(classify, events, pd):
    _rows = []
    for _label, _rain_col, _r, _t in [
        ("as above: 0.10 in rain, tide at MHW", "rain_in", 0.10, 0.0),
        ("any rain (0.01 in)", "rain_in", 0.01, 0.0),
        ("heavier rain (0.25 in)", "rain_in", 0.25, 0.0),
        ("tide 0.5 ft below MHW", "rain_in", 0.10, -0.5),
        ("tide 0.5 ft above MHW", "rain_in", 0.10, 0.5),
        ("rain at the wettest of 4 stations", "rain_any_station_in", 0.10, 0.0),
    ]:
        _share = classify(events[_rain_col], events.tide_ft_above_mhw, _r, _t).value_counts(
            normalize=True
        )
        _rows.append({"rule": _label} | (_share * 100).round(1).to_dict())
    sensitivity = pd.DataFrame(_rows).set_index("rule")[["rain only", "tide only", "both", "neither"]]
    sensitivity
    return (sensitivity,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Inside or outside the mapped risk?

    Two kinds of map, made for different floods:

    - **FEMA's National Flood Hazard Layer** maps coastal and river flooding: the 1% annual
      chance floodplain (the Special Flood Hazard Area, SFHA) and the 0.2% zone. It does not
      map flooding from rain overwhelming the sewers. We ask FEMA's live NFHL service which zone
      each sensor sits in (the same `identify` call our `critical-facilities-flood-zones/` spike
      uses).
    - **NYC's Stormwater Flood Maps** model rain flooding of at least 4 inches over at least a
      quarter acre. We use two of the four published scenarios: *Moderate* (2.13 in/hr, current
      sea levels) and the widest, *Extreme* (3.66 in/hr with 2080 sea level rise, which adds a
      "future high tides" layer).

    Sensors hang over sidewalks, while the modeled ponding is mostly in the roadway, so we count
    a sensor as inside a stormwater area if it is within 20 m of one, and report the strict
    point-in-polygon count too.
    """)
    return


@app.cell
def _(ThreadPoolExecutor, cache, get, json, sensors):
    def nfhl_zone(lon: float, lat: float) -> str:
        """FEMA flood zone at a point: 'SFHA', '0.2%', 'outside' or 'unmapped', cached."""
        _path = cache / "nfhl" / f"{lon:.6f}_{lat:.6f}.json"
        if not _path.exists():
            _payload = get(
                "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer/identify",
                {
                    "geometry": f"{lon:.6f},{lat:.6f}",
                    "geometryType": "esriGeometryPoint",
                    "sr": "4326",
                    "layers": "all:28",
                    "tolerance": "0",
                    "mapExtent": f"{lon - 0.001},{lat - 0.001},{lon + 0.001},{lat + 0.001}",
                    "imageDisplay": "400,400,96",
                    "returnGeometry": "false",
                    "f": "json",
                },
            ).json()
            assert "results" in _payload, f"NFHL error at {lon},{lat}: {_payload}"
            _path.write_text(json.dumps([r["attributes"] for r in _payload["results"]]))
        _zones = json.loads(_path.read_text())
        if not _zones:
            return "unmapped"
        if any(z.get("SFHA_TF") == "T" for z in _zones):
            return "SFHA"
        if any("0.2 PCT" in str(z.get("ZONE_SUBTY")) for z in _zones):
            return "0.2%"
        return "outside"

    with ThreadPoolExecutor(8) as _pool:
        sensors["fema"] = list(
            _pool.map(nfhl_zone, sensors.longitude.round(6), sensors.latitude.round(6))
        )
    sensors.fema.value_counts()
    return


@app.cell
def _(UTM, cache, fetch, gpd, sensors, zipfile):
    _zip = fetch("https://data.cityofnewyork.us/download/9i7c-xyvv/application%2Fzip", "stormwater.zip")
    _dir = cache / "stormwater"
    if not _dir.exists():
        with zipfile.ZipFile(_zip) as _z:
            _z.extractall(_dir)
    _gdbs = {
        "moderate": "*Moderate_Flood_2_13_inches_per_hr_with_Current_Sea_Levels.gdb",
        "extreme_2080": "*Extreme_Flood_3_66_inches_per_hr_with_2080_Sea_Level_Rise.gdb",
    }
    sensor_points = gpd.GeoDataFrame(
        sensors[["sensor_id"]],
        geometry=gpd.points_from_xy(sensors.longitude, sensors.latitude),
        crs=4326,
    ).to_crs(UTM)
    for _name, _pattern in _gdbs.items():
        _path = next(_dir.rglob(_pattern))
        _layer = gpd.read_file(_path).to_crs(UTM)
        assert len(_layer) > 0, f"empty stormwater layer {_path.name}"
        _rain_only = _layer[_layer.Flooding_Category.isin([1, 2])].union_all()
        _any = _layer.union_all()
        sensors[f"sw_{_name}_strict"] = sensor_points.within(_any).to_numpy()
        sensors[f"sw_{_name}"] = (sensor_points.distance(_any) <= 20).to_numpy()
        sensors[f"sw_{_name}_rain_only"] = (sensor_points.distance(_rain_only) <= 20).to_numpy()
    sensors[[c for c in sensors.columns if c.startswith("sw_")]].sum()
    return (sensor_points,)


@app.cell
def _(events, pd, sensors):
    _cols = ["sensor_id", "fema", "sw_moderate", "sw_moderate_strict", "sw_extreme_2080"]
    _ev = events.merge(sensors[_cols], on="sensor_id", how="left")

    def outside_share(frame: pd.DataFrame) -> dict[str, float]:
        """Share of rows outside each kind of mapped flood area, in percent."""
        _n = len(frame)
        _no_fema = ~frame.fema.isin(["SFHA", "0.2%"])
        return {
            "n": _n,
            "outside FEMA SFHA": round((frame.fema != "SFHA").mean() * 100, 1),
            "outside FEMA SFHA and 0.2%": round(_no_fema.mean() * 100, 1),
            "outside stormwater moderate (20 m)": round((~frame.sw_moderate).mean() * 100, 1),
            "outside stormwater moderate (strict)": round(
                (~frame.sw_moderate_strict).mean() * 100, 1
            ),
            "outside stormwater extreme 2080 (20 m)": round(
                (~frame.sw_extreme_2080).mean() * 100, 1
            ),
            "outside every map (FEMA 0.2% and extreme 2080)": round(
                (_no_fema & ~frame.sw_extreme_2080).mean() * 100, 1
            ),
        }

    _flooding = sensors[sensors.sensor_id.isin(events[events.flood].sensor_id)]
    outside = pd.DataFrame(
        {
            "all sensors": outside_share(sensors),
            "sensors with a 4 in flood": outside_share(_flooding),
            "all events": outside_share(_ev),
            "floods (4 in+)": outside_share(_ev[_ev.flood]),
            "rain-only floods": outside_share(_ev[_ev.flood & (_ev.cause == "rain only")]),
            "tide-only floods": outside_share(_ev[_ev.flood & (_ev.cause == "tide only")]),
        }
    ).T
    outside["n"] = outside["n"].astype(int)
    outside
    return (outside,)


@app.cell
def _(mo, outside):
    _f = outside.loc["sensors with a 4 in flood"]
    _r = outside.loc["rain-only floods"]
    mo.md(f"""
    Of the {int(_f.n)} sensors that have recorded at least one 4-inch flood,
    **{_f["outside FEMA SFHA"]}% sit outside FEMA's 1% floodplain** and
    {_f["outside stormwater moderate (20 m)"]}% are more than 20 m from the city's moderate
    stormwater flood area. For rain-only floods, {_r["outside FEMA SFHA"]}% happened outside
    the SFHA, which is what you'd expect: FEMA doesn't map rain flooding. The stormwater maps are
    the right comparison for those, and {_r["outside stormwater moderate (20 m)"]}% of rain-only
    floods were more than 20 m from the moderate scenario's mapped areas.

    Remember the selection: FloodNet sites were chosen because people already knew they flood,
    partly from 311 complaints and community input, so this is not an estimate of how much
    flooding the maps miss citywide. It says that at known flood spots, the official maps often
    don't show the flooding the sensors record.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. What's near the sensors that flood most often?

    **Frequently flooding** here means a sensor deployed at least 180 days (Bauer's minimum, so
    one early flood can't make a rate) that averaged at least 4 floods of 4 inches or more a year
    while deployed. Deployment time assumes the sensor was always online, so rates are a lower
    bound. **Nearby** means within 250 m, about one long Manhattan block.

    Facilities come from HIFLD Next (public schools, open hospitals, fire and EMS stations,
    nursing homes), and subway entrances from the MTA's 2024 list on data.ny.gov. All are clipped
    to the five boroughs.
    """)
    return


@app.cell
def _(UTM, cutoff, events, fetch, get, gpd, io, pd, sensor_points, sensors):
    _end = cutoff.tz_localize(None)
    _days = (sensors.date_removed.fillna(_end).clip(upper=_end) - sensors.date_installed).dt.days
    sensors["years_deployed"] = _days / 365.25
    _floods = events[events.flood].groupby("sensor_id").size()
    sensors["floods_4in"] = sensors.sensor_id.map(_floods).fillna(0).astype(int)
    sensors["floods_per_year"] = (sensors.floods_4in / sensors.years_deployed).round(2)
    sensors["frequent"] = (_days >= 180) & (sensors.floods_per_year >= 4)

    boroughs = gpd.read_file(
        io.BytesIO(get("https://data.cityofnewyork.us/resource/gthc-hcne.geojson").content)
    ).to_crs(UTM)
    _nyc = boroughs.union_all()
    _hifld = "https://storage.googleapis.com/hifld-next-datasets-prod/hifld"
    _layers = {
        "public school": "public-schools/public-schools/v1.0.0",
        "hospital": "hospitals-3/hospitals-3/v1.1.1",
        "fire or EMS station": "fire-and-emergency-medical-service-ems-stations/"
        "fire-and-emergency-medical-service-ems-stations/v1.0.0",
        "nursing home": "nursing-homes/nursing-homes/v1.0.0",
    }
    _frames = []
    for _type, _path in _layers.items():
        _name = _path.split("/")[0]
        _g = gpd.read_parquet(fetch(f"{_hifld}/{_path}/geoparquet/{_name}.parquet", f"{_name}.parquet"))
        _g = _g[_g.STATE == "NY"]
        if "STATUS" in _g.columns and _type == "hospital":
            _g = _g[_g.STATUS == "OPEN"]
        _frames.append(gpd.GeoDataFrame({"type": _type, "name": _g.NAME}, geometry=_g.geometry).to_crs(UTM))
    _mta = pd.read_csv(io.BytesIO(get("https://data.ny.gov/resource/i9wp-a4ja.csv", {"$limit": 50000}).content))
    _frames.append(
        gpd.GeoDataFrame(
            {"type": "subway entrance", "name": _mta.stop_name},
            geometry=gpd.points_from_xy(_mta.entrance_longitude, _mta.entrance_latitude),
            crs=4326,
        ).to_crs(UTM)
    )
    facilities = pd.concat(_frames, ignore_index=True)
    facilities = facilities[facilities.within(_nyc)]

    _freq = sensor_points[sensors.frequent.to_numpy()]
    _near = gpd.sjoin(facilities, _freq.set_geometry(_freq.buffer(250)), predicate="within")
    near_facilities = (
        pd.DataFrame(
            {
                "in NYC": facilities.type.value_counts(),
                "within 250 m of a frequent sensor": _near.drop_duplicates(
                    subset=["type", "name", "geometry"]
                ).type.value_counts(),
            }
        )
        .fillna(0)
        .astype(int)
    )
    near_list = (
        _near.merge(sensors[["sensor_id", "sensor_name", "floods_per_year"]], on="sensor_id")
        .sort_values(["type", "floods_per_year"], ascending=[True, False])
        .drop_duplicates(["type", "name"])[["type", "name", "sensor_name", "floods_per_year"]]
    )
    print(f"{int(sensors.frequent.sum())} frequently flooding sensors")
    near_facilities
    return boroughs, near_facilities, near_list


@app.cell
def _(near_list):
    near_list
    return


@app.cell
def _(boroughs, events, plt, results, sensor_points, sensors):
    _main = (
        events[events.flood]
        .groupby("sensor_id")
        .cause.agg(lambda c: c.value_counts().idxmax())
    )
    _pts = sensor_points.assign(
        cause=sensors.sensor_id.map(_main).fillna("no 4 in flood").to_numpy(),
        floods=sensors.floods_4in.to_numpy(),
        frequent=sensors.frequent.to_numpy(),
    )
    _colors = {
        "rain only": "#2a6fdb",
        "tide only": "#13a39b",
        "both": "#8a4fd8",
        "neither": "#e08a1e",
        "no 4 in flood": "#b5b5b5",
    }
    fig, _ax = plt.subplots(figsize=(9, 9))
    boroughs.plot(ax=_ax, color="#f2f2f2", edgecolor="#999999", linewidth=0.5)
    for _cause, _color in _colors.items():
        _p = _pts[_pts.cause == _cause]
        _p.plot(
            ax=_ax,
            color=_color,
            markersize=8 + 4 * _p.floods.clip(upper=40),
            alpha=0.75,
            label=f"{_cause} ({len(_p)})",
        )
    _pts[_pts.frequent].plot(ax=_ax, facecolor="none", edgecolor="black", markersize=120, linewidth=0.8)
    _ax.legend(title="Most common cause of a sensor's 4 in floods", loc="upper left", fontsize=8)
    _ax.set_title("FloodNet sensors: size = floods of 4 in or more; black ring = frequent")
    _ax.set_axis_off()
    fig.savefig(results / "sensor_map.png", dpi=150, bbox_inches="tight")
    fig
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. The Hurricane Ida "50 minutes early" claim

    **Partly verified, with a narrower meaning.** The FloodNet team's own paper (Mydlarz et al.
    2024, section 4.3) says: "During Hurricane Ida (1 Sept 2021), the FloodNet system alerted NYC
    Emergency Management of flooding recorded by the sensors installed in the Gowanus
    neighborhood in Brooklyn 50 min before they received other notifications of the event." So
    the 50 minutes is lead time over other reports reaching NYC Emergency Management, not a
    forecast, and it is the authors' statement: we found no NYC Emergency Management document
    that confirms it. NYU's October 2021 press release was more cautious ("early indications
    that these warnings were received prior to warnings from other city detection systems").
    Safe wording: *according to the FloodNet team, its alerts reached NYC Emergency Management
    50 minutes before other notifications of the Gowanus flooding.*

    What the published feed shows for the Ida evening, in New York time:
    """)
    return


@app.cell
def _(events, pd):
    _ida = events[
        (events.flood_start_time >= pd.Timestamp("2021-09-01 16:00", tz="UTC"))
        & (events.flood_start_time < pd.Timestamp("2021-09-02 12:00", tz="UTC"))
    ].sort_values("flood_start_time")
    ida = pd.DataFrame(
        {
            "sensor": _ida.sensor_name,
            "start (ET)": _ida.flood_start_time.dt.tz_convert("America/New_York").dt.strftime(
                "%b %d %H:%M"
            ),
            "peak (ET)": _ida.peak_time.dt.tz_convert("America/New_York").dt.strftime("%H:%M"),
            "max depth (in)": _ida.max_depth_inches,
            "rain (in)": _ida.rain_in.round(2),
            "cause": _ida.cause,
        }
    )
    ida
    return (ida,)


@app.cell
def _(
    cause_share,
    causes,
    cutoff,
    events,
    ida,
    json,
    near_facilities,
    near_list,
    network,
    outside,
    paper_window,
    results,
    sensitivity,
    sensors,
    started,
    time,
):
    network.to_csv(results / "network_by_borough.csv")
    causes.to_csv(results / "event_causes.csv")
    sensitivity.to_csv(results / "cause_sensitivity.csv")
    outside.to_csv(results / "outside_mapped_zones.csv")
    near_facilities.to_csv(results / "facilities_near_frequent_sensors.csv")
    near_list.to_csv(results / "facilities_near_frequent_sensors_list.csv", index=False)
    ida.to_csv(results / "ida_events.csv", index=False)
    sensors.drop(columns=["location"], errors="ignore").to_csv(results / "sensors.csv", index=False)
    events.drop(columns=["flood_profile_depth_inches", "flood_profile_time_secs"]).to_csv(
        results / "events_classified.csv.gz", index=False
    )
    summary = {
        "data_cutoff": f"{cutoff:%Y-%m-%d}",
        "network": network.loc["All"].to_dict(),
        "paper_window_in_feed": paper_window,
        "cause_share_all_events_pct": cause_share["all events"].to_dict(),
        "cause_share_floods_pct": cause_share["floods (4 in+)"].to_dict(),
        "outside_mapped_zones_pct": outside.to_dict(orient="index"),
        "frequent_sensors": int(sensors.frequent.sum()),
        "facilities_near_frequent_sensors": near_facilities[
            "within 250 m of a frequent sensor"
        ].to_dict(),
        "run_seconds": round(time.time() - started),
    }
    (results / "summary.json").write_text(json.dumps(summary, indent=2, default=float))
    print(json.dumps(summary, indent=2, default=float))
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What didn't work, and what this doesn't show

    - **No sensor, no record.** The analysis covers only places with a sensor, and FloodNet
      chose those places because they were known to flood.
    - **The per-event cause is approximate.** Airport rain gauges miss summer cells that soak
      one neighbourhood, and the three NOAA gauges miss the tidal lag and amplification inside
      Jamaica Bay, where many tidal sensors are. "Neither" collects those misses.
    - **One stormwater scenario would not open.** The *Limited Flood* geodatabase in the city's
      download uses a compressed format GDAL's open driver can't read, so we used *Moderate* and
      *Extreme 2080*.
    - **FEMA's effective NFHL for New York City is the 2007 map.** FEMA's 2015 preliminary maps
      are larger but not in the NFHL service.
    - **Deployment time assumes the sensor was always online.** The feed has no uptime record.
    """)
    return


if __name__ == "__main__":
    app.run()

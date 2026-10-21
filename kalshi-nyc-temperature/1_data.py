import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # 1. The data: Kalshi prices, AI and NOAA forecasts, Central Park sensors

        Can an open AI weather model, corrected with local sensor data, price Kalshi's
        "Highest temperature in NYC" market better than the market does? This notebook
        gathers everything the backtest in `2_backtest.py` needs, all of it public and fetched
        at run time, and saves it as small tables in the cache folder:

        | Table | Source | What it holds |
        |---|---|---|
        | `markets` | Kalshi API, series `KXHIGHNY` | each day's brackets and how they settled |
        | `prices` | Kalshi hourly candlesticks | yes bid and ask at three fixed times |
        | `aifs` | ECMWF AIFS Single open data | the AI model's 2 m temperature |
        | `nbm` | NOAA National Blend of Models | NOAA's max temperature and its spread |
        | `cli` | NWS Daily Climate Report (IEM) | Central Park's official daily high |
        | `obs` | ASOS 1-minute data (IEM) | Central Park's temperature through the day |

        Nothing needs an account or a key. Downloads are cached, so a second run is fast.
        """
    )
    return (mo,)


@app.cell
def _():
    import datetime as dt
    import json
    import os
    import random
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from zoneinfo import ZoneInfo

    import eccodes
    import numpy as np
    import pandas as pd
    import requests

    ET = ZoneInfo("America/New_York")
    START = dt.date.fromisoformat(os.environ.get("BACKTEST_START", "2025-10-20"))
    END = dt.date.fromisoformat(os.environ.get("BACKTEST_END", "2026-10-19"))
    # The model correction looks back 30 days, so forecasts start 40 days before the backtest.
    MODEL_START = START - dt.timedelta(days=40)
    CACHE = Path(
        os.environ.get("KALSHI_NYC_CACHE", Path.home() / ".cache" / "kalshi-nyc-temperature")
    )
    for _sub in ("kalshi", "aifs"):
        (CACHE / _sub).mkdir(parents=True, exist_ok=True)
    # Central Park, where the official NYC high is measured (KNYC).
    LAT, LON = 40.779, -73.969
    print(f"Backtest {START} to {END}; cache {CACHE}")
    return (
        CACHE,
        END,
        ET,
        LAT,
        LON,
        MODEL_START,
        START,
        ThreadPoolExecutor,
        dt,
        eccodes,
        json,
        np,
        pd,
        random,
        requests,
        time,
    )


@app.cell
def _(random, requests, time):
    def get(url: str, params: dict | None = None, headers: dict | None = None) -> requests.Response:
        """GET with a bounded retry: Kalshi rate-limits anonymous reads, and connections drop."""
        for attempt in range(40):
            try:
                resp = requests.get(url, params=params, headers=headers, timeout=60)
            except (
                requests.ConnectionError,
                requests.Timeout,
                requests.exceptions.ChunkedEncodingError,
            ):
                time.sleep(min(2**attempt, 20))
                continue
            if resp.status_code == 429:
                # Anonymous candlestick reads get about one call every 3-5 seconds.
                time.sleep(random.uniform(3, 10))
                continue
            if resp.status_code in (500, 502, 503, 504):
                time.sleep(min(2**attempt, 20))
                continue
            resp.raise_for_status()
            return resp
        raise RuntimeError(f"gave up after 40 tries: {url} {params}")

    return (get,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Kalshi: the markets and how they settled

        Each day is one event, such as `KXHIGHNY-26OCT20`, with six brackets: two tails
        ("64° or below", "73° or above") and four 2-degree ranges. Kalshi moves markets that
        settled before a cutoff date to separate `/historical/` endpoints, so we list the
        series from both. The answer key is Kalshi's own settled value (`expiration_value`).
        The settlement source changed during the period: the NWS Daily Climate Report until
        mid-August 2026, then The Weather Company.
        """
    )
    return


@app.cell
def _(CACHE, END, START, dt, get, json, pd):
    KALSHI = "https://api.elections.kalshi.com/trade-api/v2"
    SERIES = "KXHIGHNY"

    def event_date(ticker: str) -> dt.date:
        return dt.datetime.strptime(ticker.split("-")[1], "%y%b%d").date()

    def listing(path: str, key: str, extra: dict) -> list[dict]:
        found, cursor = [], ""
        for _ in range(100):
            params = {"series_ticker": SERIES, **extra, **({"cursor": cursor} if cursor else {})}
            page = get(f"{KALSHI}{path}", params).json()
            found += page[key]
            cursor = page.get("cursor") or ""
            if not cursor:
                return found
        raise RuntimeError(f"more than 100 pages at {path}")

    _cached = CACHE / "kalshi" / f"markets-{START}-{END}.json"
    if not _cached.exists():
        _live = listing("/markets", "markets", {"status": "settled", "limit": 1000})
        _archived = listing("/historical/markets", "markets", {"limit": 1000})
        for _m in _live:
            _m["archived"] = False
        for _m in _archived:
            _m["archived"] = True
        _cached.write_text(json.dumps(_live + _archived))
    _sources = {
        e["event_ticker"]: (e.get("settlement_sources") or [{}])[0].get("name", "")
        for e in listing("/events", "events", {"limit": 200})
    }

    _rows = []
    for _m in json.loads(_cached.read_text()):
        _day = event_date(_m["event_ticker"])
        if not START <= _day <= END:
            continue
        _rows.append(
            {
                "date": _day,
                "event": _m["event_ticker"],
                "ticker": _m["ticker"],
                "archived": _m["archived"],
                "strike_type": _m["strike_type"],
                "floor": _m.get("floor_strike"),
                "cap": _m.get("cap_strike"),
                "result": _m["result"],
                "settled_high": float(_m["expiration_value"] or "nan"),
                "source": _sources.get(_m["event_ticker"], ""),
            }
        )
    markets = pd.DataFrame(_rows).drop_duplicates("ticker").sort_values("ticker")
    markets.to_parquet(CACHE / "markets.parquet")
    print(f"{markets.date.nunique()} days, {len(markets)} brackets")
    markets.groupby("source").date.nunique()
    return KALSHI, SERIES, markets


@app.cell
def _(mo):
    mo.md(
        """
        ## Kalshi: prices at three fixed times

        We take the market's view at three times, all New York time: **4 pm the day before**
        (about 32 hours before the market closes), **8 am on the day** and **2 pm on the day**,
        when the high is often close to being set. For each we keep the yes bid and yes ask
        at the close of that hourly candle. These are quotes anyone could see, so they are
        what a trader would have had to pay.
        """
    )
    return


@app.cell
def _(CACHE, ET, KALSHI, SERIES, dt, get, json, markets, pd):
    SNAPSHOTS = {"D-1 16:00": (-1, 16), "D 08:00": (0, 8), "D 14:00": (0, 14)}

    def snapshot_time(day: dt.date, name: str) -> dt.datetime:
        offset, hour = SNAPSHOTS[name]
        return dt.datetime.combine(day + dt.timedelta(days=offset), dt.time(hour), ET)

    def dollars(candle: dict, side: str) -> float:
        quote = candle[side]
        value = quote.get("close_dollars", quote.get("close"))
        return float(value) if value is not None else float("nan")

    def event_candles(event: str, day: dt.date, tickers: list[str], archived: bool) -> dict:
        """Hourly candles for each bracket of one day, from the day before 4 pm to 2 pm."""
        path = CACHE / "kalshi" / f"{event}.candles.json"
        if path.exists():
            return json.loads(path.read_text())
        params = {
            "start_ts": int(snapshot_time(day, "D-1 16:00").timestamp()) - 3600,
            "end_ts": int(snapshot_time(day, "D 14:00").timestamp()),
            "period_interval": 60,
        }
        if archived:
            # The archive has no event-level endpoint, so it is one call per bracket.
            found = {
                t: get(f"{KALSHI}/historical/markets/{t}/candlesticks", params).json()[
                    "candlesticks"
                ]
                for t in tickers
            }
        else:
            resp = get(f"{KALSHI}/series/{SERIES}/events/{event}/candlesticks", params).json()
            found = dict(zip(resp["market_tickers"], resp["market_candlesticks"], strict=True))
        path.write_text(json.dumps(found))
        return found

    _rows = []
    for (_event, _day, _archived), _brackets in markets.groupby(["event", "date", "archived"]):
        _all = event_candles(_event, _day, list(_brackets.ticker), _archived)
        for _ticker in _brackets.ticker:
            _by_end = {c["end_period_ts"]: c for c in _all.get(_ticker, [])}
            for _name in SNAPSHOTS:
                _ts = int(snapshot_time(_day, _name).timestamp())
                # The latest candle that ended at or before the snapshot, within two hours.
                _candle = next(
                    (_by_end[t] for t in range(_ts, _ts - 7200, -3600) if t in _by_end), None
                )
                _rows.append(
                    {
                        "date": _day,
                        "ticker": _ticker,
                        "snapshot": _name,
                        "yes_bid": dollars(_candle, "yes_bid") if _candle else float("nan"),
                        "yes_ask": dollars(_candle, "yes_ask") if _candle else float("nan"),
                    }
                )
    prices = pd.DataFrame(_rows)
    prices.to_parquet(CACHE / "prices.parquet")
    prices.groupby("snapshot")[["yes_bid", "yes_ask"]].count()
    return (prices,)


@app.cell
def _(mo):
    mo.md(
        """
        ## ECMWF AIFS: the AI weather model

        AIFS Single is ECMWF's machine-learning forecast model, run four times a day and
        published as open data (CC BY 4.0) with a public archive on AWS. It writes 2 m
        temperature every 6 hours, not a daily maximum, so the best we can do is take the
        warmest of the 6-hourly values over the day. That under-reads the true peak, which is
        exactly the kind of steady bias a local correction should remove.

        For each day D and snapshot we use the latest run a trader could have seen. A run
        lands on AWS about 5.5 hours after it starts, so the 4 pm D-1 snapshot uses the
        12 UTC run of D-1, 8 am uses the 06 UTC run of D, and 2 pm uses the 12 UTC run of D.
        Each GRIB file has an index, so we download only the 2 m temperature field, about
        0.5 MB of an 80 MB file, and read the four grid points around Central Park.
        """
    )
    return


@app.cell
def _(CACHE, END, LAT, LON, MODEL_START, ThreadPoolExecutor, dt, eccodes, get, json, pd):
    AIFS = "https://ecmwf-forecasts.s3.eu-central-1.amazonaws.com"

    def aifs_point(run: dt.date, hour: int, step: int) -> float:
        """2 m temperature (°F) at Central Park from one AIFS run and forecast step."""
        stem = (
            f"{AIFS}/{run:%Y%m%d}/{hour:02d}z/aifs-single/0p25/oper/"
            f"{run:%Y%m%d}{hour:02d}0000-{step}h-oper-fc"
        )
        index = [json.loads(line) for line in get(stem + ".index").text.splitlines()]
        field = next(i for i in index if i["param"] == "2t")
        byte_range = f"bytes={field['_offset']}-{field['_offset'] + field['_length'] - 1}"
        grib = get(stem + ".grib2", headers={"Range": byte_range}).content
        handle = eccodes.codes_new_from_message(grib)
        try:
            near = eccodes.codes_grib_find_nearest(handle, LAT, LON, npoints=4)
        finally:
            eccodes.codes_release(handle)
        weights = [1 / max(p["distance"], 1e-6) for p in near]
        kelvin = sum(w * p["value"] for w, p in zip(weights, near, strict=True)) / sum(weights)
        return (kelvin - 273.15) * 9 / 5 + 32

    # The run each snapshot can see (runs land about 5.5 hours after they start), and the
    # times on day D we read from it, in hours after 00 UTC on D. 6, 12, 18 and 24 UTC are
    # 2 am, 8 am, 2 pm and 8 pm New York daylight time.
    RUNS = {
        "D-1 16:00": (-1, 12, (6, 12, 18, 24)),
        "D 08:00": (0, 6, (6, 12, 18, 24)),
        "D 14:00": (0, 12, (12, 18, 24)),
    }

    def aifs_day(day: dt.date) -> list[dict]:
        path = CACHE / "aifs" / f"{day:%Y%m%d}.json"
        if path.exists():
            return json.loads(path.read_text())
        rows = []
        for snapshot, (offset, hour, valid_hours) in RUNS.items():
            run = day + dt.timedelta(days=offset)
            for valid in valid_hours:
                step = valid - offset * 24 - hour
                rows.append(
                    {
                        "date": str(day),
                        "snapshot": snapshot,
                        "valid_hour": valid,
                        "t2m_f": aifs_point(run, hour, step),
                    }
                )
        path.write_text(json.dumps(rows))
        return rows

    _days = [MODEL_START + dt.timedelta(days=i) for i in range((END - MODEL_START).days + 1)]
    with ThreadPoolExecutor(max_workers=8) as _pool:
        _all = [r for rows in _pool.map(aifs_day, _days) for r in rows]
    aifs = pd.DataFrame(_all)
    aifs["date"] = pd.to_datetime(aifs.date).dt.date
    aifs.to_parquet(CACHE / "aifs.parquet")
    print(f"{aifs.date.nunique()} days of AIFS")
    aifs.head(8)
    return (aifs,)


@app.cell
def _(mo):
    mo.md(
        """
        ## NOAA National Blend of Models: the conventional baseline

        The NBM is NOAA's statistically post-processed blend of many models, issued hourly.
        Its station text product (NBS) gives a daytime maximum for Central Park (`txn`) and
        its standard deviation (`xnd`), so it is already a probability forecast. The Iowa
        Environmental Mesonet (IEM) archives the 01, 07, 13 and 19 UTC runs. At each snapshot
        we use the latest run issued at least an hour earlier.
        """
    )
    return


@app.cell
def _(CACHE, END, MODEL_START, dt, get, pd):
    IEM = "https://mesonet.agron.iastate.edu"
    _frames = []
    _month = MODEL_START.replace(day=1)
    while _month <= END:
        _next = (_month + dt.timedelta(days=32)).replace(day=1)
        _path = CACHE / f"nbm-{_month:%Y%m}.csv"
        if not _path.exists():
            _resp = get(
                f"{IEM}/cgi-bin/request/mos.py",
                {
                    "station": "KNYC",
                    "model": "NBS",
                    "sts": f"{_month - dt.timedelta(days=2)}T00:00Z",
                    "ets": f"{_next}T00:00Z",
                    "format": "csv",
                },
            )
            _path.write_text(_resp.text)
        _frames.append(pd.read_csv(_path, usecols=["runtime", "ftime", "txn", "xnd"]))
        _month = _next
    _raw = pd.concat(_frames).drop_duplicates()
    # The daytime max (7 am-7 pm local) is the txn value on the 00 UTC row after day D.
    _raw["ftime"] = pd.to_datetime(_raw.ftime, utc=True)
    _raw = _raw[(_raw.ftime.dt.hour == 0) & _raw.txn.notna()]
    nbm = pd.DataFrame(
        {
            "runtime": pd.to_datetime(_raw.runtime, utc=True),
            "date": (_raw.ftime - pd.Timedelta(days=1)).dt.date,
            "nbm_max": _raw.txn,
            "nbm_sd": _raw.xnd,
        }
    )
    nbm.to_parquet(CACHE / "nbm.parquet")
    print(f"{nbm.date.nunique()} days of NBM, {nbm.runtime.nunique()} runs")
    return IEM, nbm


@app.cell
def _(mo):
    mo.md(
        """
        ## Local sensors: Central Park's official high and its 1-minute record

        Two IEM archives give the ground truth around the settlement station. The NWS Daily
        Climate Report (CLI) has the official Central Park high for each day; it is what the
        bias correction learns from. The ASOS 1-minute record from the same sensor gives the
        temperature through the day, so at 2 pm we know the high so far and how the afternoon
        compares with the model. We tried the NYS Mesonet too: its Manhattan station is close
        by, but its archive is not open to anonymous download, so it is not used here.
        """
    )
    return


@app.cell
def _(CACHE, END, ET, IEM, MODEL_START, dt, get, pd):
    _cli = []
    for _year in range(MODEL_START.year, END.year + 1):
        _cli += get(f"{IEM}/json/cli.py", {"station": "KNYC", "year": _year}).json()["results"]
    cli = pd.DataFrame(
        {
            "date": pd.to_datetime([r["valid"] for r in _cli]).date,
            "cli_high": [r["high"] for r in _cli],
        }
    )
    cli = cli[(cli.date >= MODEL_START) & (cli.date <= END)]
    cli.to_parquet(CACHE / "cli.parquet")

    _frames = []
    _month = MODEL_START.replace(day=1)
    while _month <= END:
        _next = (_month + dt.timedelta(days=32)).replace(day=1)
        _path = CACHE / f"asos1min-{_month:%Y%m}.csv"
        if not _path.exists():
            _resp = get(
                f"{IEM}/cgi-bin/request/asos1min.py",
                {
                    "station": "NYC",
                    "vars": "tmpf",
                    "sts": f"{_month}T04:00Z",
                    "ets": f"{_next}T05:00Z",
                    "sample": "1min",
                    "what": "download",
                    "tz": "UTC",
                },
            )
            _path.write_text(_resp.text)
        _frames.append(pd.read_csv(_path, usecols=["valid(UTC)", "tmpf"], na_values=["M"]))
        _month = _next
    _raw = pd.concat(_frames).dropna().drop_duplicates().reset_index(drop=True)
    _local = pd.to_datetime(_raw["valid(UTC)"], utc=True).dt.tz_convert(ET)
    obs = pd.DataFrame({"time": _local, "date": _local.dt.date, "tmpf": _raw.tmpf.astype(float)})
    _before_2pm = obs[obs.time.dt.hour < 14]
    obs_day = pd.DataFrame(
        {
            "max_by_2pm": _before_2pm.groupby("date").tmpf.max(),
            "minutes_by_2pm": _before_2pm.groupby("date").tmpf.count(),
            "temp_2pm": obs[(obs.time.dt.hour == 13) & (obs.time.dt.minute >= 50)]
            .groupby("date")
            .tmpf.mean(),
            "max_1min": obs.groupby("date").tmpf.max(),
            "hour_of_max": obs.loc[obs.groupby("date").tmpf.idxmax()]
            .set_index("date")
            .time.dt.hour,
            "minutes": obs.groupby("date").tmpf.count(),
        }
    ).reset_index()
    obs_day.to_parquet(CACHE / "obs.parquet")
    print(f"{len(cli)} CLI days, {len(obs_day)} days of 1-minute data")
    obs_day.describe().round(1)
    return


if __name__ == "__main__":
    app.run()

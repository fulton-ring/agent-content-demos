import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(r"""
    # When governments pulled websites offline for PHP2Shell, which public datasets went dark?

    On October 21, 2026, governments in Europe, Canada and the UK took websites offline as a precaution against
    the PHP2Shell flaws, and CISA told US organizations to take PHP systems they couldn't patch offline. We want
    to know which public data portals and dataset downloads went offline with them, for how long, whether they
    all came back, and whether anyone outside the agency had a copy.

    Nobody published a list of what went down, so we rebuild one from the outside:

    1. **Endpoints.** `endpoints.csv` lists 255 endpoints: the source URLs HIFLD Next's refresh check reads,
       US federal data pages, US state open-data portals, and the national statistics and open-data portals of
       the countries that announced shutdowns. Ten of them, such as Statistics Canada and Overheid.nl, were
       named as offline in news coverage. They are the method's check: if it can't see those go down, it can't
       see anything.
    2. **The archive record.** For each endpoint we ask the Wayback Machine's CDX index for every capture from
       October 14 to November 1, 2026, and save the raw answers in `cdx/`, so the numbers can be rebuilt after
       the archive changes.
    3. **Today.** We request each endpoint now: up, down, or up with its download links broken.

    The notebook reads saved files first and only goes to the network for what's missing, so a rerun gives the
    same numbers.
    """)
    return (mo,)


@app.cell
def _():
    import csv
    import datetime as dt
    import json
    import os
    import re
    import statistics
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path
    from urllib.parse import urljoin

    import pandas as pd
    import requests

    HERE = Path(__file__).parent
    CDX_DIR = Path(os.environ.get("CDX_DIR", HERE / "cdx"))
    LIVE_DIR = Path(os.environ.get("LIVE_DIR", HERE / "live"))
    OUT = Path(os.environ.get("OUTPUT_DIR", HERE / "outputs"))
    for _d in (CDX_DIR, LIVE_DIR, OUT):
        _d.mkdir(parents=True, exist_ok=True)
    CDX_URL = os.environ.get("CDX_URL", "https://web.archive.org/cdx/search/cdx")
    REPLAY_URL = os.environ.get("REPLAY_URL", "https://web.archive.org/web")
    NETWORK = os.environ.get("NETWORK", "local")
    CHECK_DATE = os.environ.get("CHECK_DATE", dt.date.today().isoformat())
    UA = {"User-Agent": "php2shell-data-outages/0.1 (+https://github.com/fulton-ring/agent-content-demos)"}
    return (
        CDX_DIR,
        CDX_URL,
        HERE,
        CHECK_DATE,
        LIVE_DIR,
        NETWORK,
        OUT,
        REPLAY_URL,
        ThreadPoolExecutor,
        UA,
        csv,
        dt,
        json,
        pd,
        re,
        requests,
        statistics,
        time,
        urljoin,
    )


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## The window

    The archive query runs from October 14, a week of normal days before the shutdowns, to November 1. We call
    October 21 00:00 to October 24 00:00 UTC the shutdown days: the first government takedowns were on the
    morning of October 21 in Europe, and CISA updated its alert on October 23. An outage counts as part of the
    shutdowns if it starts in those days. Outages that start in the week before are the background rate:
    government sites fail sometimes for ordinary reasons, and we report that rate next to the shutdown count.
    """)
    return


@app.cell
def _(HERE, dt, pd):
    WINDOW_FROM, WINDOW_TO = "20261014", "20261101"
    SHUTDOWN_START = dt.datetime(2026, 10, 21, tzinfo=dt.UTC)
    SHUTDOWN_END = dt.datetime(2026, 10, 24, tzinfo=dt.UTC)
    BASELINE_START = dt.datetime(2026, 10, 14, tzinfo=dt.UTC)
    endpoints = pd.read_csv(HERE / "endpoints.csv")
    endpoints.groupby(["group", "country"]).size().rename("endpoints").reset_index()
    return BASELINE_START, SHUTDOWN_END, SHUTDOWN_START, WINDOW_FROM, WINDOW_TO, endpoints


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 1: ask the archive

    One CDX query per endpoint lists its captures in the window: time, HTTP status, content type, a hash of the
    content and its length. A second query asks for the endpoint's last good capture before October 21 at any
    date, which tells us whether an outside copy existed when the shutdowns began. Requests go one at a time, two
    seconds apart, with at most three tries each. A query that still fails is left out of `cdx/` and the
    notebook says how many are missing; after five endpoints in a row fail, it stops asking.
    """)
    return


@app.cell
def _(CDX_DIR, CDX_URL, UA, WINDOW_FROM, WINDOW_TO, endpoints, json, requests, time):
    def cdx_get(params: dict[str, str]) -> list[list[str]] | None:
        """One CDX query with a bounded retry; None if it never answered."""
        for attempt in range(3):
            try:
                r = requests.get(CDX_URL, params=params, headers=UA, timeout=45)
                if r.status_code == 200:
                    return json.loads(r.text) if r.text.strip() else []
                if r.status_code not in (429, 500, 502, 503, 504):
                    print(f"CDX answered {r.status_code} for {params['url']}: {r.text[:200]}")
                    return None
            except (requests.RequestException, ValueError):
                pass
            time.sleep(10 * 2**attempt)
        return None

    fields = "timestamp,original,statuscode,mimetype,digest,length"
    missing_cdx = []
    failures_in_row = 0
    for _row in endpoints.itertuples():
        _path = CDX_DIR / f"{_row.id:03d}.json"
        if _path.exists():
            continue
        if failures_in_row >= 5:
            missing_cdx.append(_row.id)  # the archive stopped answering; don't hammer it
            continue
        window = cdx_get({"url": _row.url, "from": WINDOW_FROM, "to": WINDOW_TO, "output": "json", "fl": fields})
        time.sleep(2)
        if window is None:
            missing_cdx.append(_row.id)
            failures_in_row += 1
            continue
        failures_in_row = 0
        before = cdx_get(
            {
                "url": _row.url,
                "to": "20261020",
                "output": "json",
                "fl": fields,
                "filter": "statuscode:200",
                "limit": "-1",
            }
        )
        time.sleep(2)
        _saved = {"url": _row.url, "window": window, "last_good_before": before or [], "before_ok": before is not None}
        _path.write_text(json.dumps(_saved))
    print(f"CDX: {len(endpoints) - len(missing_cdx)} of {len(endpoints)} endpoints saved, {len(missing_cdx)} missing")
    return (missing_cdx,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 2: sort good captures from bad

    A capture is **bad** if the archive's crawler got a server error (5xx) or the page was gone (404 or 410).
    Outages also show up as maintenance pages served with a normal 200 status, or as redirects to one. The CDX
    status can't see those, so for any capture from October 21 on that is a redirect, or a 200 much smaller than
    the endpoint's usual page (under 40% of its median length before October 21), and whose content differs from
    every capture in the week before, we fetch the archived capture itself and look for maintenance wording in
    its redirect target, title or first heading, in English, Dutch, Finnish, French, German and Danish. These
    replays are capped at 300 and saved in `cdx/replays.json`.

    Archive "revisit" records (status `-`) mean the content was identical to an earlier capture, so they take the
    status of the capture with the same content hash.
    """)
    return


@app.cell
def _(CDX_DIR, json, pd):
    _rows = []
    for _path in sorted(CDX_DIR.glob("[0-9][0-9][0-9].json")):
        _saved = json.loads(_path.read_text())
        _window = _saved["window"]
        if not _window:
            continue
        _header = _window[0]
        for _cap in _window[1:]:
            _rows.append({"id": int(_path.stem), **dict(zip(_header, _cap, strict=True))})
    caps = pd.DataFrame(_rows, columns=["id", "timestamp", "original", "statuscode", "mimetype", "digest", "length"])
    caps["time"] = pd.to_datetime(caps["timestamp"], format="%Y%m%d%H%M%S", utc=True)
    caps["length"] = pd.to_numeric(caps["length"], errors="coerce")
    caps = caps.sort_values(["id", "time"]).reset_index(drop=True)
    _status_by_digest = caps[caps["statuscode"] != "-"].groupby(["id", "digest"])["statuscode"].first().to_dict()
    caps["status"] = [
        _status_by_digest.get((i, d), "200") if s == "-" else s
        for i, s, d in zip(caps["id"], caps["statuscode"], caps["digest"], strict=True)
    ]
    caps["status"].value_counts()
    return (caps,)


@app.cell
def _(CDX_DIR, REPLAY_URL, SHUTDOWN_START, UA, caps, json, pd, re, requests, time):
    MAINTENANCE = re.compile(
        r"maintenance|temporarily unavailable|service unavailable|currently unavailable|offline"
        r"|onderhoud|niet beschikbaar|huoltokatko|ei ole saatavilla|tilapäisesti"
        r"|indisponible|momentanément|wartung|nicht verfügbar|vorübergehend|vedligehold|utilgængelig|midlertidigt",
        re.IGNORECASE,
    )

    def headline(html: str, location: str) -> str:
        """Where a maintenance notice shows: the redirect target, the page title and the first heading.
        A banner in the body ("scheduled maintenance on Sunday") doesn't count."""
        parts = re.findall(r"<title[^>]*>(.*?)</title>|<h1[^>]*>(.*?)</h1>", html[:50000], re.I | re.S)[:2]
        return " ".join([location, *(a or b for a, b in parts)])

    _before = caps[caps["time"] < SHUTDOWN_START]
    usual_length = _before[_before["status"] == "200"].groupby("id")["length"].median()
    _seen_before = set(zip(_before["id"], _before["digest"], strict=True))
    _new = pd.Series(
        [(i, d) not in _seen_before for i, d in zip(caps["id"], caps["digest"], strict=True)], index=caps.index
    )
    _small = caps["status"].eq("200") & (caps["length"] < 0.4 * caps["id"].map(usual_length))
    _redirect = caps["status"].str.startswith("3")
    suspects = caps[(_small | _redirect) & _new & (caps["time"] >= SHUTDOWN_START)]

    _replay_path = CDX_DIR / "replays.json"
    replays: dict[str, dict[str, str]] = json.loads(_replay_path.read_text()) if _replay_path.exists() else {}
    _todo = [r for r in suspects.itertuples() if f"{r.id}:{r.timestamp}" not in replays][: max(0, 300 - len(replays))]
    replay_errors = 0
    for _r in _todo:
        if replay_errors >= 5:
            break  # the archive stopped answering; unreplayed captures stay unknown and are retried next run
        try:
            _resp = requests.get(
                f"{REPLAY_URL}/{_r.timestamp}id_/{_r.original}", headers=UA, timeout=60, allow_redirects=False
            )
        except requests.RequestException:
            replay_errors += 1
            time.sleep(2)
            continue
        if _resp.status_code == 429 or _resp.status_code >= 500:
            replay_errors += 1  # the archive is throttling or failing, not answering for the capture
            time.sleep(10)
            continue
        replay_errors = 0
        _text = headline(_resp.text, _resp.headers.get("Location", ""))
        replays[f"{_r.id}:{_r.timestamp}"] = {
            "replay_status": str(_resp.status_code),
            "maintenance": "yes" if MAINTENANCE.search(_text) else "no",
            "excerpt": " ".join(_text.split())[:200],
        }
        time.sleep(2)
    _replay_path.write_text(json.dumps(replays, indent=1, sort_keys=True))

    _keys = [f"{i}:{t}" for i, t in zip(caps["id"], caps["timestamp"], strict=True)]
    caps["maintenance"] = [replays.get(k, {}).get("maintenance") == "yes" for k in _keys]
    caps["bad"] = caps["status"].str.match(r"5\d\d|404|410") | caps["maintenance"]
    print(
        f"{len(suspects)} suspect captures, {len(replays)} replayed, {int(caps['maintenance'].sum())} maintenance pages"
    )
    return MAINTENANCE, headline


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 3: turn captures into outages

    An **outage** is a run of bad captures with a good capture before it. Captures are snapshots, so we can only
    bound how long it lasted: at least from the first bad capture to the last, and at most from the good capture
    before to the good capture after. We report both. An outage with no good capture after it was still bad at
    the end of the window.
    """)
    return


@app.cell
def _(BASELINE_START, SHUTDOWN_END, SHUTDOWN_START, caps, pd):
    _episodes = []
    for _id, _g in caps.groupby("id"):
        _prev_good, _run = None, []
        for _cap in _g.itertuples():
            if _cap.bad:
                _run.append(_cap.time)
                continue
            if _run and _prev_good is not None:
                _episodes.append((_id, _prev_good, _run[0], _run[-1], _cap.time))
            _prev_good, _run = _cap.time, []
        if _run and _prev_good is not None:
            _episodes.append((_id, _prev_good, _run[0], _run[-1], None))
    outages = pd.DataFrame(_episodes, columns=["id", "last_good", "first_bad", "last_bad", "next_good"])
    outages["hours_at_least"] = (outages["last_bad"] - outages["first_bad"]).dt.total_seconds() / 3600
    outages["hours_at_most"] = (outages["next_good"] - outages["last_good"]).dt.total_seconds() / 3600
    outages["period"] = pd.cut(
        outages["first_bad"],
        [BASELINE_START, SHUTDOWN_START, SHUTDOWN_END, pd.Timestamp("2026-11-02", tz="UTC")],
        labels=["baseline week", "shutdown days", "after"],
        right=False,
    )
    outages
    return (outages,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 4: check every endpoint today

    One request per endpoint. **Down** means no answer, a timeout, or a server error. **Gone** means 404 or 410.
    **Blocked** means the site refused our client (401, 403, 429), which tells us nothing about whether it's up.
    A page whose title or first heading is a maintenance notice counts as down. For download pages and APIs that
    answer with HTML, we follow up to three links to data files (CSV, ZIP, XLSX, JSON, GeoJSON, shapefile,
    GeoPackage) and call the endpoint **up without downloads** if every one fails.

    The same response tells us the software behind the page (Drupal, DKAN, WordPress, other PHP, or not PHP as
    far as we can see), from headers and the page's generator tag. We report that only as counts.
    """)
    return


@app.cell
def _(
    CHECK_DATE, LIVE_DIR, MAINTENANCE, NETWORK, ThreadPoolExecutor, UA, endpoints, headline, pd, re, requests, urljoin
):
    DATA_LINK = re.compile(
        r"""href=["']([^"']+\.(?:csv|zip|xlsx?|json|geojson|gpkg|shp|parquet)(?:\?[^"']*)?)["']""", re.I
    )

    def platform(resp: requests.Response) -> str:
        head = " ".join(f"{k}: {v}" for k, v in resp.headers.items()).lower()
        body = resp.text[:200000].lower() if "html" in resp.headers.get("content-type", "") else ""
        if "dkan" in head or "dkan" in body:
            return "DKAN"
        if "drupal" in head or "drupal-settings-json" in body or "/sites/default/files/" in body:
            return "Drupal"
        if "wp-content/" in body or "wordpress" in head:
            return "WordPress"
        if "php" in head or 'content="joomla' in body or 'content="typo3' in body:
            return "other PHP"
        return "not PHP as far as we can see"

    def downloads_ok(resp: requests.Response) -> str:
        found = DATA_LINK.findall(resp.text[:500000])
        links = [urljoin(resp.url, h) for h in found if not re.search(r"feed|manifest|package\.json", h, re.I)][:3]
        if not links:
            return "no links found"
        for link in links:
            try:
                r = requests.get(link, headers=UA, timeout=30, stream=True)
                r.close()
                if r.status_code < 400:
                    return "ok"
            except requests.RequestException:
                continue
        return "all failed"

    def check(row: pd.Series) -> dict[str, str]:
        try:
            resp = requests.get(row["url"], headers=UA, timeout=30)
        except requests.RequestException as e:
            return {"id": row["id"], "http": type(e).__name__, "live": "down", "downloads": "", "platform": "unknown"}
        code, html = resp.status_code, "html" in resp.headers.get("content-type", "")
        live = "up"
        if code >= 500:
            live = "down"
        elif code in (404, 410):
            live = "gone"
        elif code in (401, 403, 429):
            live = "blocked"
        elif html and MAINTENANCE.search(headline(resp.text, "")):
            live = "down"
        downloads = ""
        is_data = row["group"] == "HIFLD Next source" or re.search("download|API|data portal|file", row["type"])
        if live == "up" and html and is_data:
            downloads = downloads_ok(resp)
            live = "up without downloads" if downloads == "all failed" else "up"
        return {"id": row["id"], "http": str(code), "live": live, "downloads": downloads, "platform": platform(resp)}

    _path = LIVE_DIR / f"{CHECK_DATE}-{NETWORK}.csv"
    if _path.exists():
        live = pd.read_csv(_path, dtype=str).fillna("")
    else:
        with ThreadPoolExecutor(8) as _ex:
            live = pd.DataFrame(list(_ex.map(check, [r for _, r in endpoints.iterrows()])))
        live.to_csv(_path, index=False)
    live["id"] = live["id"].astype(int)
    live["live"].value_counts()
    return (live,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Results
    """)
    return


@app.cell
def _(
    CDX_DIR,
    CHECK_DATE,
    OUT,
    SHUTDOWN_END,
    SHUTDOWN_START,
    caps,
    endpoints,
    json,
    live,
    missing_cdx,
    outages,
    pd,
    statistics,
):
    df = endpoints.merge(live, on="id", how="left")
    _n_caps = caps.groupby("id").size()
    _n_shut = caps[(caps["time"] >= SHUTDOWN_START) & (caps["time"] < SHUTDOWN_END)].groupby("id").size()
    _have_cdx = {int(p.stem) for p in CDX_DIR.glob("[0-9][0-9][0-9].json")}
    df["has_cdx"] = df["id"].isin(_have_cdx)
    df["captures_in_window"] = df["id"].map(_n_caps).fillna(0).astype(int)
    df["captures_shutdown_days"] = df["id"].map(_n_shut).fillna(0).astype(int)
    df["can_tell"] = df["captures_shutdown_days"] > 0

    def last_good_before(i: int) -> str:
        p = CDX_DIR / f"{i:03d}.json"
        rows = json.loads(p.read_text())["last_good_before"] if p.exists() else []
        return rows[-1][0] if len(rows) > 1 else ""

    df["archive_copy_before"] = df["id"].map(last_good_before)
    df["outside_copy"] = (df["archive_copy_before"] != "") | (df["group"] == "HIFLD Next source")

    shut = outages[outages["period"] == "shutdown days"]
    base = outages[outages["period"] == "baseline week"]
    df["outage_shutdown_days"] = df["id"].isin(shut["id"])
    df["never_recovered_in_window"] = df["id"].isin(shut.loc[shut["next_good"].isna(), "id"])
    _hit = df[df["outage_shutdown_days"]]
    _named = df["named_offline_in_coverage"].eq("yes")

    def median(s: pd.Series) -> float | None:
        s = s.dropna()
        return round(statistics.median(s), 1) if len(s) else None

    _checked = df[df["has_cdx"]]
    summary = {
        "check_date": CHECK_DATE,
        "endpoints": len(df),
        "endpoints_by_group": df.groupby("group").size().to_dict(),
        "endpoints_by_country": df.groupby("country").size().to_dict(),
        "cdx_saved": int(df["has_cdx"].sum()),
        "cdx_missing": len(missing_cdx),
        "no_captures_in_window": int((_checked["captures_in_window"] == 0).sum()),
        "too_few_captures_to_tell": int((~_checked["can_tell"]).sum()),
        "share_too_few_captures": round(float((~_checked["can_tell"]).mean()), 3) if len(_checked) else None,
        "went_offline_shutdown_days": int(df["outage_shutdown_days"].sum()),
        "named_in_coverage": int(_named.sum()),
        "named_in_coverage_can_tell": int((_named & df["can_tell"]).sum()),
        "named_in_coverage_seen_offline": int((_named & df["outage_shutdown_days"]).sum()),
        "went_offline_by_group": _hit.groupby("group").size().to_dict(),
        "went_offline_by_country": _hit.groupby("country").size().to_dict(),
        "median_outage_hours_at_least": median(shut.groupby("id")["hours_at_least"].sum()),
        "median_outage_hours_at_most": median(shut.groupby("id")["hours_at_most"].sum()),
        "still_bad_at_window_end": int(df["never_recovered_in_window"].sum()),
        "background_outages_baseline_week": int(base["id"].nunique()),
        "offline_had_outside_copy": int(_hit["outside_copy"].sum()),
        "outside_copy_all_endpoints": int(df["outside_copy"].sum()),
        "live_now": df["live"].value_counts().to_dict(),
        "live_now_offline_in_shutdown": _hit["live"].value_counts().to_dict(),
        "platform_counts": df["platform"].value_counts().to_dict(),
        "platform_of_offline": _hit["platform"].value_counts().to_dict(),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    _cols = [
        "id",
        "named_offline_in_coverage",
        "country",
        "group",
        "type",
        "name",
        "url",
        "captures_in_window",
        "captures_shutdown_days",
        "can_tell",
        "outage_shutdown_days",
        "never_recovered_in_window",
        "outside_copy",
        "live",
        "downloads",
    ]
    df[_cols].to_csv(OUT / "endpoint_results.csv", index=False)
    outages.to_csv(OUT / "outages.csv", index=False)
    print(json.dumps(summary, indent=1, default=str))
    return (df,)


@app.cell
def _(df):
    df.groupby(["group"]).agg(
        endpoints=("id", "size"),
        median_captures=("captures_in_window", "median"),
        can_tell=("can_tell", "sum"),
        offline_shutdown_days=("outage_shutdown_days", "sum"),
        outside_copy=("outside_copy", "sum"),
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## What this doesn't show

    - **Pages the archive didn't visit.** An endpoint with no capture during the shutdown days could have been
      down the whole time and we'd never know. The share of those is the method's blind spot, reported above.
    - **How long an outage really lasted.** Captures are snapshots, hours or days apart. The two bounds can be
      far apart, and both are reported.
    - **Why a page failed.** A 503 on October 22 fits a precautionary takedown, but it could be an ordinary
      failure. The baseline week tells you how often these sites fail anyway.
    - **Which endpoints are vulnerable.** We report software platforms only as counts and don't publish a list.
      Taking a vulnerable system offline was sound advice; the question is only what the public lost meanwhile.
    - **Every public dataset.** 255 endpoints is a sample weighted to US federal data and to the main national
      portals of the countries that announced shutdowns, not a census.
    """)
    return


if __name__ == "__main__":
    app.run()

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Who would notice if a public data endpoint went dark for a week?

    During the PHP2Shell shutdowns of October 21 to 23, 2026, the Wayback Machine had no capture of 68% of 255
    public data endpoints ([php2shell-data-outages](../php2shell-data-outages/README.md)). That spike also saw
    the archive's captures of these endpoints fall from about 4,500 a day to 100 to 175 a day. If the archive is
    the only outside record, nobody would notice a week-long outage at most of them.

    This notebook asks three things of the data we already have:

    1. Was the fall in captures about data endpoints, or a change on the archive's side?
    2. In an ordinary week, how often is each endpoint captured, and how many go more than 7 days without one?
    3. What would a monitor of HIFLD Next's 50 sources record? `monitor.py` checks them and appends to
       `log/checks.csv`; `run.sh` runs it once before this notebook.

    The Wayback CDX API resets the connection from the worker's sandbox, so this run makes **no new archive
    queries**. It reads the CDX answers the PHP2Shell spike saved for October 14 to November 1. The four weeks
    either side of the shutdowns, and a control set of popular government pages outside these 255, need new
    queries; see the README.
    """)
    return


@app.cell
def _():
    import json
    import os
    from pathlib import Path

    import pandas as pd

    HERE = Path(__file__).parent
    PREV = Path(os.environ.get("PHP2SHELL_DIR", HERE.parent / "php2shell-data-outages"))
    LOG = Path(os.environ.get("MONITOR_LOG", HERE / "log" / "checks.csv"))
    OUT = Path(os.environ.get("OUTPUT_DIR", HERE / "outputs"))
    OUT.mkdir(parents=True, exist_ok=True)
    assert (PREV / "cdx").is_dir(), f"saved CDX answers not found in {PREV / 'cdx'}"
    endpoints = pd.read_csv(PREV / "endpoints.csv")
    return HERE, LOG, OUT, PREV, endpoints, json, pd


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## The data

    One row per archive capture of the 255 endpoints, October 14 to November 1, from the PHP2Shell spike's saved
    CDX answers (`php2shell-data-outages/cdx/NNN.json`). We count every capture the archive lists, whatever
    its status, because the question here is whether the archive looked, not what it saw.
    """)
    return


@app.cell
def _(PREV, endpoints, json, pd):
    _rows = []
    for _path in sorted((PREV / "cdx").glob("[0-9][0-9][0-9].json")):
        _window = json.loads(_path.read_text())["window"]
        _rows += [{"id": int(_path.stem), "timestamp": _cap[0]} for _cap in _window[1:]]
    caps = pd.DataFrame(_rows)
    caps["time"] = pd.to_datetime(caps["timestamp"], format="%Y%m%d%H%M%S", utc=True)
    caps = caps.merge(endpoints[["id", "group", "url"]], on="id", validate="many_to_one")
    print(f"{len(caps):,} captures of {caps['id'].nunique()} endpoints; {len(endpoints)} endpoints in the list")
    return (caps,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 1: when did captures fall, and of what?

    Captures per day, split into HIFLD Next's 50 sources and everything else, plus how many distinct endpoints
    the archive looked at each day.
    """)
    return


@app.cell
def _(caps, pd):
    caps["day"] = caps["time"].dt.strftime("%Y-%m-%d")
    caps["hifld"] = caps["group"] == "HIFLD Next source"
    per_day = (
        pd.DataFrame(
            {
                "all captures": caps.groupby("day").size(),
                "HIFLD Next sources": caps[caps["hifld"]].groupby("day").size(),
                "other endpoints": caps[~caps["hifld"]].groupby("day").size(),
                "endpoints captured": caps.groupby("day")["id"].nunique(),
            }
        )
        .fillna(0)
        .astype(int)
    )
    per_day
    return (per_day,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    The fall is not in the shutdown days. Which endpoints made up the 4,500 a day, and at what hour did they
    stop?
    """)
    return


@app.cell
def _(caps):
    _before = caps[caps["day"] <= "2026-10-16"]
    top = _before.groupby("url").size().sort_values(ascending=False).head(10).rename("captures Oct 14-16")
    top_share = top.sum() / len(_before)
    print(f"Top 10 endpoints made {top_share:.0%} of the {len(_before):,} captures on October 14 to 16")
    _oct17 = caps[caps["day"].isin(["2026-10-17", "2026-10-18"])]
    hourly = _oct17.groupby(_oct17["time"].dt.strftime("%m-%d %H:00")).size().rename("captures")
    step_hour = hourly[hourly < 50].index[0]
    print(f"First hour under 50 captures: {step_hour} UTC")
    print(hourly.loc["10-17 12:00":"10-17 18:00"].to_string())
    top
    return hourly, step_hour, top_share


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 2: how often does the archive look at each endpoint?

    Two ordinary weeks bracket the shutdowns: October 14 to 20 (before, but it includes the step change) and
    October 25 to 31 (after). For each endpoint: captures per week, and the longest stretch without any
    capture between October 14 and November 2 00:00 UTC, counting the window's edges. An endpoint whose longest
    gap is over 7 days could have been down for a week without the archive recording it.
    """)
    return


@app.cell
def _(caps, endpoints, pd):
    _start, _end = pd.Timestamp("2026-10-14", tz="UTC"), pd.Timestamp("2026-11-02", tz="UTC")

    def weekly(first: str, last: str) -> pd.Series:
        _in = caps[(caps["day"] >= first) & (caps["day"] <= last)]
        return _in.groupby("id").size().reindex(endpoints["id"], fill_value=0)

    def longest_gap_days(times: pd.Series) -> float:
        points = pd.concat([pd.Series([_start]), times.sort_values(), pd.Series([_end])])
        return points.diff().max().total_seconds() / 86400

    _gaps = caps.groupby("id")["time"].apply(longest_gap_days)
    per_endpoint = endpoints[["id", "group", "country", "url"]].set_index("id")
    per_endpoint["week_before"] = weekly("2026-10-14", "2026-10-20")
    per_endpoint["week_after"] = weekly("2026-10-25", "2026-10-31")
    per_endpoint["longest_gap_days"] = _gaps.reindex(per_endpoint.index).fillna((_end - _start).days).round(1)
    per_endpoint["blind_over_7_days"] = per_endpoint["longest_gap_days"] > 7
    per_endpoint["daily_both_weeks"] = (per_endpoint["week_before"] >= 7) & (per_endpoint["week_after"] >= 7)
    per_endpoint.groupby("group").agg(
        endpoints=("url", "size"),
        median_week_before=("week_before", "median"),
        median_week_after=("week_after", "median"),
        blind_over_7_days=("blind_over_7_days", "sum"),
        captured_daily=("daily_both_weeks", "sum"),
    )
    return (per_endpoint,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 3: does anyone else watch them?

    We looked for a public, day-by-day record of whether these endpoints answer (sources checked on
    2026-11-18; details in the README). None covers them:

    | Monitor | What it checks | How often | Covers our endpoints? |
    |---|---|---|---|
    | [data.gov harvester](https://harvest.data.gov/metrics/) | each agency's catalog file (data.json, WAF, CSW) | daily to weekly, some manual | only where the endpoint is itself a catalog feed; not ArcGIS services |
    | [Data Rescue Project status](https://portal.datarescueproject.org/status/) | about 50 datasets marked removed or modified, by hand | when someone notices | no |
    | [dataindex.us](https://www.dataindex.us/terminations-tracker) | verified terminations; its URL up/down tracker gave way to a quarterly checkup | quarterly | no; "does not count temporary takedowns" |
    | [ArcGIS Online status](https://status.arcgis.com/) | Esri's own platform, incidents hitting most users | live, 30 days kept | no; not agencies' own servers or single services |
    | [data.europa.eu quality checks](https://data.europa.eu/mqa/methodology?locale=en) | a HEAD request to each EU distribution URL | every few weeks | by chance only; no outage history |
    | [EDGI Web Tracker](https://envirodatagov.org/federal-environmental-web-tracker-about-page/) | content changes on about 5,000 environmental pages, built on Wayback captures | weekly reports | no; content, not uptime |
    | [PHPocalypse Tracker](https://allixsenos.github.io/phpocalypse-tracker/) | sites reported dark in this event | until about October 30 | partly; built from reports, not a fixed list |
    | Small uptime pages (CapitolTrace govwatch, us-fed-gov-uptime) | a handful of big .gov sites and APIs | every 30 minutes | no; not these endpoints |

    Common Crawl's newest index is from August 2026, and it crawls about once a month.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Step 4: the monitor

    `monitor.py` (60 lines) sends one GET to each of the 50 HIFLD Next source URLs, eight at a time, with one
    retry, and appends a row per endpoint to `log/checks.csv`: time, HTTP status, up / blocked / gone / down, and
    seconds taken. Here is what the log holds.
    """)
    return


@app.cell
def _(LOG, pd):
    assert LOG.exists(), f"no monitor log at {LOG}; run ./run.sh or uv run monitor.py first"
    log = pd.read_csv(LOG, dtype=str)
    _by_run = log.groupby(["run_started", "network"])
    runs = _by_run["status"].value_counts().unstack(fill_value=0)
    _ended = pd.to_datetime(_by_run["checked_at"].max(), utc=True)
    _began = pd.to_datetime(runs.index.get_level_values("run_started"), utc=True)
    runs["run_seconds"] = (_ended.to_numpy() - _began.to_numpy()) / pd.Timedelta(seconds=1)
    runs
    return log, runs


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    What would it have recorded on October 21 to 23? The monitor didn't exist then, so the honest answer comes
    from what the archive saw of the same 50 sources and from the PHP2Shell spike's later live checks.
    """)
    return


@app.cell
def _(PREV, caps, pd):
    _shut = caps[caps["hifld"] & (caps["day"] >= "2026-10-21") & (caps["day"] <= "2026-10-23")]
    hifld_seen = _shut["id"].nunique()
    print(f"Archive captures of HIFLD Next sources on Oct 21-23: {len(_shut)}, of {hifld_seen} of 50 sources")
    _prev = pd.read_csv(PREV / "outputs" / "endpoint_results.csv")
    _h = _prev[_prev["group"] == "HIFLD Next source"]
    print("PHP2Shell spike's verdict for the 50, Oct 21-23:", _h["outage_shutdown_days"].value_counts().to_dict())
    _live = {p.stem: pd.read_csv(p, dtype=str) for p in sorted((PREV / "live").glob("*.csv"))}
    for _name, _df in _live.items():
        _df = _df[_df["id"].astype(int).isin(_h["id"])]
        print(f"Live check {_name}: {_df['live'].value_counts().to_dict()}")
    return (hifld_seen,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Result
    """)
    return


@app.cell
def _(OUT, hifld_seen, json, per_day, per_endpoint, runs, step_hour, top_share):
    _last = runs.reset_index().iloc[-1]
    summary = {
        "captures_per_day_oct14_16_mean": round(float(per_day.loc["2026-10-14":"2026-10-16", "all captures"].mean())),
        "captures_per_day_oct18_nov1_mean": round(float(per_day.loc["2026-10-18":, "all captures"].mean())),
        "hifld_captures_per_day_max": int(per_day["HIFLD Next sources"].max()),
        "top10_share_of_oct14_16_captures": round(float(top_share), 3),
        "first_hour_under_50": step_hour,
        "median_captures_per_endpoint_week_before": float(per_endpoint["week_before"].median()),
        "median_captures_per_endpoint_week_after": float(per_endpoint["week_after"].median()),
        "endpoints_blind_over_7_days": int(per_endpoint["blind_over_7_days"].sum()),
        "endpoints_no_capture_either_week": int((per_endpoint["week_before"] + per_endpoint["week_after"] == 0).sum()),
        "endpoints_captured_daily_both_weeks": int(per_endpoint["daily_both_weeks"].sum()),
        "hifld_blind_over_7_days": int(per_endpoint.query("group == 'HIFLD Next source'")["blind_over_7_days"].sum()),
        "hifld_sources_captured_oct21_23": int(hifld_seen),
        "monitor_last_run": {k: str(v) for k, v in _last.items()},
        "cost_usd": 0,
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2))
    per_endpoint.to_csv(OUT / "endpoint_gaps.csv")
    per_day.to_csv(OUT / "captures_per_day.csv")
    print(json.dumps(summary, indent=2))
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## What this shows and what it doesn't

    - The fall from about 4,500 captures a day was a step on the archive's side on October 17, three days
      before the shutdowns, and it was almost all a few popular national home pages (gov.uk, ons.gov.uk) losing
      a very frequent crawl. HIFLD Next's sources were never captured more than a few times a day in total.
      The PHP2Shell framing ("captures of HIFLD Next's sources fell") was wrong.
    - That makes the shutdown week ordinary for data endpoints, not unusually neglected: in ordinary weeks the
      archive also leaves most of them unseen for more than 7 days.
    - Not shown yet: the four weeks either side, and a control set of popular government pages outside these
      255. Both need new CDX queries, which this sandbox can't make.
    - The monitor checks that an endpoint answers, not that its data is complete or current.
    """)
    return


if __name__ == "__main__":
    app.run()

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # How current are the rescued copies of federal climate data?

        Our article lists 20 federal climate and environmental datasets that went offline,
        stopped updating or lost their app after January 2025, and for each one the newest
        record inside the copy people can still use. A table like that goes stale itself
        unless someone re-reads every copy. This notebook does the re-reading.

        It opens `data/currency.csv`, reads the newest record date in each copy again,
        writes the same file back with today's `date_checked`, and says what changed since
        the last run and which rows a person has to look at.

        The first version of the CSV holds the article's own values, checked by hand on
        2026-10-17, so the first run is also a re-check of the article.
        """
    )
    return (mo,)


@app.cell
def _():
    import calendar
    import datetime as dt
    import html
    import os
    import re
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import pandas as pd
    import requests

    CSV_PATH = Path(os.environ.get("CURRENCY_CSV", Path(__file__).parent / "data" / "currency.csv"))
    TODAY = dt.datetime.now(dt.UTC).date().isoformat()
    return CSV_PATH, TODAY, ThreadPoolExecutor, calendar, dt, html, pd, re, requests, time


@app.cell
def _(CSV_PATH, mo, pd):
    previous = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False)
    assert previous["dataset"].nunique() == 20, "the table should cover the article's 20 datasets"
    assert set(previous["check_kind"]) <= {"date", "marker", "manual"}, "unknown check_kind"
    mo.vstack(
        [
            mo.md(
                f"""
                ## The data

                {len(previous)} rows for {previous["dataset"].nunique()} datasets. A row is one
                copy, so a dataset with two copies (Billion-Dollar Disasters: Climate Central
                and NOAA's frozen archive; EJScreen: the environmental layers and the EJAM
                demographics) has two rows, and the four NCEI satellite records have one row
                each. The first row of each dataset is its main copy; counts by dataset use it.
                """
            ),
            mo.ui.table(previous[["dataset", "copy_name", "newest_record_in_copy", "status"]]),
        ]
    )
    return (previous,)


@app.cell
def _(mo):
    mo.md(
        r"""
        ## How a copy is read

        Every copy publishes its newest date differently: a CSV's last row, a folder
        listing, a file name, an ArcGIS layer's `dataLastEditDate`, an OPeNDAP time axis, a
        line of text on a web page. Rather than write one reader per site, each row says
        where to look (`check_url`, or `copy_url` when that is blank) and gives a regular
        expression (`check_pattern`). There are three kinds of row:

        - **date**: the pattern's named groups (`y`, `m`, `d`, or `ms` for epoch
          milliseconds, or `days_since_YYYYMMDD`) make a date, and the newest match wins.
          This is the newest record in the copy, refreshed with no person involved.
        - **marker**: the copy has no readable date (a finished report, a rebuilt app), so
          the script reads a piece of text that would change if the copy did, such as a
          version string or a release note. If the marker is unchanged the last date stands;
          if it changed, a person has to look.
        - **manual**: nothing to read; the last value is kept and listed for a person.

        A row whose fetch or match fails falls back to manual for that run, keeping its
        last value and date.
        """
    )
    return


@app.cell
def _(calendar, dt, html, re, requests, time):
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "text/html,application/json,text/csv,*/*",
        "Accept-Language": "en-US,en",
    }
    MAX_TRIES = 3

    def fetch(url: str) -> str:
        """The page as text, plus its visible text when it is HTML, so patterns can match either."""
        for attempt in range(1, MAX_TRIES + 1):
            try:
                response = requests.get(url, headers=HEADERS, timeout=60)
                response.raise_for_status()
            except requests.RequestException:
                if attempt == MAX_TRIES:
                    raise
                time.sleep(2**attempt)
                continue
            body = response.text
            if "html" not in response.headers.get("Content-Type", ""):
                return body
            visible = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S)
            visible = html.unescape(re.sub(r"<[^>]+>", " ", visible))
            return body + "\n" + re.sub(r"\s+", " ", visible)
        raise AssertionError("unreachable")

    MONTHS = {name.lower(): number for number, name in enumerate(calendar.month_name) if name}

    def match_to_date(groups: dict[str, str]) -> str:
        """An ISO date at the precision the match gives: YYYY, YYYY-MM or YYYY-MM-DD."""
        if groups.get("ms"):
            stamp = dt.datetime.fromtimestamp(int(groups["ms"]) / 1000, dt.UTC)
            return stamp.date().isoformat()
        for key, value in groups.items():
            if key.startswith("days_since_") and value:
                base = dt.datetime.strptime(key.removeprefix("days_since_"), "%Y%m%d").date()
                return (base + dt.timedelta(days=int(value))).isoformat()
        year, month, day = groups["y"], groups.get("m"), groups.get("d")
        if not month:
            return year
        month_number = MONTHS.get(month.lower()) or int(month)
        if not day:
            return f"{year}-{month_number:02d}"
        return f"{year}-{month_number:02d}-{int(day):02d}"

    def read_copy(kind: str, url: str, pattern: str) -> str:
        """What the script reads from a copy: its newest date, or the marker text."""
        text = fetch(url)
        if kind == "marker":
            found = re.search(pattern, text)
            if found is None:
                raise ValueError(f"marker not found; the response starts {text[:120]!r}")
            return found.group(0)
        dates = [match_to_date(m.groupdict()) for m in re.finditer(pattern, text)]
        if not dates:
            raise ValueError(f"no date matched; the response starts {text[:120]!r}")
        # ISO strings of equal precision sort as dates.
        return max(dates)

    return (read_copy,)


@app.cell
def _(ThreadPoolExecutor, previous, read_copy, time):
    def check(row: dict[str, str]) -> tuple[str, str]:
        """(value read, error), with one of the two empty."""
        if row["check_kind"] == "manual":
            return "", "manual row"
        try:
            url = row["check_url"] or row["copy_url"]
            return read_copy(row["check_kind"], url, row["check_pattern"]), ""
        except Exception as error:  # a failed copy must not stop the others
            return "", f"{type(error).__name__}: {error}"[:200]

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=8) as pool:
        readings = list(pool.map(check, previous.to_dict("records")))
    run_seconds = time.perf_counter() - started
    print(f"Read {len(readings)} copies in {run_seconds:.1f} s")
    return readings, run_seconds


@app.cell
def _(TODAY, previous, readings):
    refreshed = previous.copy()
    flags: list[str] = []
    for _index, (_value, _error) in zip(refreshed.index, readings, strict=True):
        _row = refreshed.loc[_index]
        _url = _row["check_url"] or _row["copy_url"]
        if _error:
            flags.append("manual" if _error == "manual row" else f"failed: {_error}")
            if _error != "manual row":
                refreshed.loc[_index, "how_checked"] = (
                    f"manual: script failed on {TODAY}; value from {_row['date_checked']}"
                )
            continue
        if _row["check_kind"] == "date":
            refreshed.loc[_index, ["newest_record_in_copy", "check_value", "date_checked"]] = [
                _value,
                _value,
                TODAY,
            ]
            refreshed.loc[_index, "how_checked"] = f"script: newest date matched in {_url}"
            flags.append("")
        elif _row["check_value"] and _value != _row["check_value"]:
            refreshed.loc[_index, "check_value"] = _value
            refreshed.loc[_index, "how_checked"] = (
                f"manual: marker changed on {TODAY}; "
                f"date from {_row['date_checked']} needs a person"
            )
            flags.append("marker changed")
        else:
            refreshed.loc[_index, ["check_value", "date_checked"]] = [_value, TODAY]
            refreshed.loc[_index, "how_checked"] = (
                f"script: marker unchanged in {_url}; date stands"
            )
            flags.append("")
    refreshed["flag"] = flags
    return (refreshed,)


@app.cell
def _(mo, pd, previous, refreshed):
    def same_date(a: str, b: str) -> bool:
        """Equal at the coarser precision, so 2024-10 and 2024-10-09 count as the same."""
        return a.startswith(b) or b.startswith(a)

    moved = [
        not same_date(a, b)
        for a, b in zip(
            previous["newest_record_in_copy"], refreshed["newest_record_in_copy"], strict=True
        )
    ]
    marker_moved = (previous["check_value"] != "") & (
        refreshed["check_value"] != previous["check_value"]
    )
    changed = refreshed[pd.Series(moved, index=refreshed.index) | marker_moved]
    print(f"\nChanged since the last run ({previous['date_checked'].max()}): {len(changed)}")
    for _, _change in changed.iterrows():
        _before = previous.loc[_change.name]
        print(
            f"  {_change['copy_name']}: {_before['newest_record_in_copy'] or '-'} -> "
            f"{_change['newest_record_in_copy'] or '-'}"
            + (f" (marker now '{_change['check_value']}')" if _change["flag"] else "")
        )
    needs_person = refreshed[refreshed["flag"] != ""]
    print(f"\nFor a person to check by hand: {len(needs_person)}")
    for _, _row in needs_person.iterrows():
        print(f"  {_row['copy_name']}: {_row['flag']} ({_row['copy_url']})")
    mo.vstack(
        [
            mo.md(f"## What changed since the last run\n\n{len(changed)} rows changed."),
            mo.ui.table(changed[["copy_name", "newest_record_in_copy", "check_value"]]),
            mo.md(f"## For a person\n\n{len(needs_person)} rows need someone to look."),
            mo.ui.table(needs_person[["copy_name", "flag", "copy_url"]]),
        ]
    )
    return


@app.cell
def _(mo, refreshed):
    def against_article(row: dict[str, str]) -> str:
        """Whether the run's value agrees with the article at the article's precision."""
        article, now = row["article_newest"], row["newest_record_in_copy"]
        if row["check_kind"] != "date" or row["flag"]:
            return "not re-read (marker or manual)"
        if not article:
            return "the article had no date"
        if now.startswith(article):
            return "agrees"
        # A live copy moving on is expected; an earlier date means the article was wrong.
        return "newer than the article" if now > article else "earlier than the article"

    refreshed["vs_article"] = [against_article(r) for r in refreshed.to_dict("records")]
    print("\nAgainst the article's 2026-10-17 values:")
    print(refreshed["vs_article"].value_counts().to_string())
    for _, _row in refreshed[refreshed["vs_article"] != "agrees"].iterrows():
        if _row["vs_article"].startswith(("not", "the article")):
            continue
        print(
            f"  {_row['copy_name']}: article {_row['article_newest'] or '-'}, "
            f"run {_row['newest_record_in_copy']}"
        )
    mo.vstack(
        [
            mo.md("## Against the article's 2026-10-17 values"),
            mo.ui.table(
                refreshed[["copy_name", "article_newest", "newest_record_in_copy", "vs_article"]]
            ),
        ]
    )
    return


@app.cell
def _(mo, refreshed, run_seconds):
    main_copies = refreshed.drop_duplicates("dataset")
    by_kind = main_copies["check_kind"].value_counts()
    rows_by_kind = refreshed["check_kind"].value_counts()
    by_status = main_copies["status"].value_counts()
    current = by_status.get("restored", 0) + by_status.get("federal successor current", 0)
    failed = int(refreshed["flag"].str.startswith("failed").sum())
    print(
        f"\nDatasets (main copy): {by_kind.get('date', 0)} dated by the script, "
        f"{by_kind.get('marker', 0)} watched by a marker, {by_kind.get('manual', 0)} manual"
    )
    print(
        f"Rows: {rows_by_kind.get('date', 0)} dated, {rows_by_kind.get('marker', 0)} marker, "
        f"{rows_by_kind.get('manual', 0)} manual; {failed} failed this run"
    )
    print(f"Stale: {by_status.get('stale', 0)} of 20. Current from the agency or a federal")
    print(f"successor: {current} of 20. Run time {run_seconds:.1f} s.")
    print("\nStatus of the 20 datasets:")
    print(by_status.to_string())
    mo.md(
        f"""
        ## The numbers

        - Of the 20 datasets, the script dates {by_kind.get("date", 0)} on its own and watches
          {by_kind.get("marker", 0)} for change; {by_kind.get("manual", 0)} are manual.
        - Across all {len(refreshed)} copies: {rows_by_kind.get("date", 0)} dated,
          {rows_by_kind.get("marker", 0)} watched, {failed} failed this run.
        - Stale: {by_status.get("stale", 0)} of 20. Current data from the agency or a federal
          successor: {current} of 20.
        - The run took {run_seconds:.1f} seconds.

        `status` is a person's call and the script never changes it; the run supplies the
        dates that call rests on.
        """
    )
    return


@app.cell
def _(CSV_PATH, refreshed):
    refreshed.drop(columns=["flag", "vs_article"]).to_csv(CSV_PATH, index=False)
    print(f"\nWrote {CSV_PATH.name}")
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## What this doesn't do

        - A marker row only says "unchanged" or "look at me"; it never dates a copy.
        - A pattern is tied to a page's wording. If a site is redesigned, its row fails
          loudly and falls back to manual rather than reading a wrong date.
        - Some rows read a proxy for the newest record: Climate.us's newest What's New entry,
          the weeks the CDC Heat Tracker's API offers, EPA's web-update date.
        - It doesn't decide `status`, and it doesn't run on a schedule.
        """
    )
    return


if __name__ == "__main__":
    app.run()

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import os
    import re
    from pathlib import Path

    import marimo as mo
    import numpy as np
    import pandas as pd
    import requests

    return Path, mo, np, os, pd, re, requests


@app.cell
def _(mo):
    mo.md(r"""
    # Can the public map find the substations large loads are asking BPA to connect to?

    The Bonneville Power Administration publishes its interconnection queue as a workbook. Its large-load
    requests (connection type `LL`) each name a point of interconnection: a substation, or a tap on a line.
    We take every request that names a substation and ask whether two public maps have it:

    - **HIFLD Next**: the preserved federal grid data. It has no substations layer, so we use the 45,779
      substations derived from the ends of its Transmission Lines layer (`us-substations-verified`'s
      public-domain `us_substations_hifld_only.csv`, with HIFLD's own names).
    - **us-substations-verified**: our dataset that adds OpenStreetMap substations HIFLD lacks
      (`us_substations.parquet`, 71,625 substations).

    The answer key is `hand_check.csv`: every named substation looked up on Esri aerial imagery (`chips.py`
    draws the images), with where it really is and what each source has there. `poi_reading.csv` is our
    reading of each request's point of interconnection. Everything else is downloaded when this runs.
    """)
    return


@app.cell
def _(Path, os, requests):
    DATA_DIR = Path(os.environ.get("DATA_DIR", "data"))
    OUTPUT_DIR = Path(os.environ.get("OUTPUT_DIR", "outputs"))
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    def download(url: str, name: str) -> Path:
        """Download url to DATA_DIR/name once; later runs reuse the file."""
        path = DATA_DIR / name
        if path.exists():
            return path
        for attempt in range(3):
            response = requests.get(url, timeout=300, headers={"User-Agent": "Mozilla/5.0 (research script)"})
            if response.ok:
                path.write_bytes(response.content)
                return path
            print(f"{url}: HTTP {response.status_code} (attempt {attempt + 1} of 3)")
        raise RuntimeError(f"Could not download {url}")

    # BPA overwrites the workbook in place, so a fresh run reads today's queue unless data/ already has a copy.
    queue_path = download(
        "https://www.bpa.gov/-/media/Aep/transmission-media-documents/InterconnectionQueueOutput.xlsx",
        "InterconnectionQueueOutput.xlsx",
    )
    # The verified dataset as published on main (pinned to the commit that last changed it).
    _repo = "https://raw.githubusercontent.com/fulton-ring/agent-content-demos/b48028fa402933bf55423ee552105f5d71d405ac"
    hifld_path = download(
        f"{_repo}/us-substations-verified/dataset/us_substations_hifld_only.csv", "us_substations_hifld_only.csv"
    )
    verified_path = download(
        f"{_repo}/us-substations-verified/dataset/us_substations.parquet", "us_substations.parquet"
    )
    gazetteer_path = download(
        "https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2024_Gazetteer/2024_Gaz_counties_national.zip",
        "2024_Gaz_counties_national.zip",
    )
    return OUTPUT_DIR, hifld_path, queue_path, verified_path, gazetteer_path


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. The requests

    The workbook's date is in its title row. Row 6 holds the column names. We keep connection type `LL`,
    and call a request **live** unless its status is `WITHDRAWN`. Requested MW is the maximum summer
    interconnection service; where that's blank (older requests), the nameplate total. BPA publishes no
    end-use field, so nothing here says which requests are data centers.
    """)
    return


@app.cell
def _(pd, queue_path):
    _title = pd.read_excel(queue_path, header=None, nrows=1)
    workbook_date = pd.Timestamp(_title.iloc[0, 8]).date()
    _queue = pd.read_excel(queue_path, header=5)
    _queue.columns = [" ".join(str(c).split()) for c in _queue.columns]
    loads = _queue[_queue["Connection Type"] == "LL"].rename(
        columns={"Request Number": "request_id", "Status": "status", "State": "state", "County": "county"}
    )
    loads["mw"] = loads["Max Summer Interconnection Service MW"].fillna(loads["Nameplate MW Total"]).fillna(0)
    loads["live"] = loads["status"] != "WITHDRAWN"
    loads["poi_as_filed"] = loads["Point of Interconnection"].fillna("").map(lambda s: " ".join(str(s).split()))
    assert loads["request_id"].is_unique, "duplicate request numbers in the workbook"
    print(
        f"Workbook dated {workbook_date}: {len(loads)} large-load requests on file, {loads['mw'].sum() / 1000:.1f} GW; "
        f"{int(loads['live'].sum())} live, {loads.loc[loads['live'], 'mw'].sum() / 1000:.1f} GW. "
        f"{int((loads['state'].isna()).sum())} have no state filed."
    )
    loads.groupby("status")["mw"].agg(["size", "sum"]).sort_values("size", ascending=False)
    return loads, workbook_date


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. What each request names

    Points of interconnection are free text: "BPA's Longview Substation", "McNary 230kV, Bay 28",
    "Lower Monumental-McNary No. 1 500 kV line". We read all of them by hand into `poi_reading.csv`:
    **substation** (names one, or a substation is the first option offered), **line** (a tap on a named line,
    where a new substation would be built), **planned** (the filing calls the substation planned, proposed or
    new) or **none** (blank or TBD). A request offering "A or B" is read as A.
    """)
    return


@app.cell
def _(loads, pd):
    _reading = pd.read_csv("poi_reading.csv", keep_default_na=False)
    requests_read = loads.merge(_reading, on="request_id", how="left", suffixes=("", "_read"))
    _unread = requests_read["kind"].isna()
    _changed = ~_unread & (requests_read["poi_as_filed"] != requests_read["poi_as_filed_read"])
    print(f"Requests not yet read by hand (new since {len(_reading)} were read): {int(_unread.sum())}")
    print(f"Requests whose point of interconnection changed since it was read: {int(_changed.sum())}")
    requests_read["kind"] = requests_read["kind"].fillna("unread")

    def share_table(frame: pd.DataFrame, column: str) -> pd.DataFrame:
        """Requests and requested MW by `column`, all on file and live only, with shares."""
        live = frame[frame["live"]]
        out = pd.DataFrame(
            {
                "requests": frame.groupby(column).size(),
                "GW": frame.groupby(column)["mw"].sum() / 1000,
                "live requests": live.groupby(column).size(),
                "live GW": live.groupby(column)["mw"].sum() / 1000,
            }
        ).fillna(0)
        for col in list(out.columns):
            out[f"{col} %"] = 100 * out[col] / out[col].sum()
        return out.round(1)

    _kinds = share_table(requests_read, "kind")
    print(_kinds.to_string())
    _kinds
    return requests_read, share_table


@app.cell
def _(mo):
    mo.md(r"""
    About half the requests, and most of the live megawatts, name a line rather than a substation: the
    biggest asks want a new substation cut into a 500 kV line. No map can show those yet. The rest of this
    notebook is about the requests that name a substation.

    ## 3. The automatic join

    First, what anyone would do with code: normalise the name (drop "BPA's", "Substation", voltages,
    punctuation) and look for a point with that name within 100 km of the filed county's centre. Where no
    state is filed, every county of that name in BPA's eight states counts.
    """)
    return


@app.cell
def _(gazetteer_path, hifld_path, np, pd, re, requests_read, verified_path):
    import geopandas as gpd

    STATES = ["WA", "OR", "ID", "MT", "NV", "CA", "WY", "UT"]
    _gaz = pd.read_csv(gazetteer_path, sep="\t", dtype={"GEOID": str})
    _gaz.columns = [c.strip() for c in _gaz.columns]
    counties = _gaz[_gaz["USPS"].isin(STATES)].assign(county=lambda g: g["NAME"].str.replace(" County", ""))

    hifld = pd.read_csv(hifld_path)
    _verified = gpd.read_parquet(verified_path)
    verified = pd.DataFrame(_verified.drop(columns="geometry")).assign(
        lon=_verified.geometry.x, lat=_verified.geometry.y
    )

    def norm(name: object) -> str:
        """Upper-case letters only, without words that every substation name might carry."""
        text = re.sub(r"\b(SUBSTATION|SUB|BPA|PAC|SAINT|ST)\b", " ", str(name).upper())
        return re.sub(r"[^A-Z]", "", text)

    def km(lat: pd.Series, lon: pd.Series, lat0: float, lon0: float) -> np.ndarray:
        """Great-circle distance in km from (lat0, lon0) to each point."""
        lat1, lon1, lat2, lon2 = map(np.radians, (lat, lon, lat0, lon0))
        a = np.sin((lat2 - lat1) / 2) ** 2 + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2
        return 6371 * 2 * np.arcsin(np.sqrt(a))

    for _source in (hifld, verified):
        _source["key"] = _source["name"].map(norm)

    _named = requests_read[requests_read["kind"].isin(["substation", "planned"])].copy()
    _auto_rows = []
    for _row in _named.itertuples():
        _key = norm(str(_row.substation).replace(" (OR)", ""))
        _county = str(_row.county).strip(" ,")
        _here = counties[(counties["county"] == _county) & ((counties["USPS"] == _row.state) | pd.isna(_row.state))]
        _found = {"request_id": _row.request_id}
        for _label, _source in (("hifld", hifld), ("verified", verified)):
            _cands = _source[_source["key"] == _key]
            _best = None
            for _c in _here.itertuples():
                _d = km(_cands["lat"], _cands["lon"], _c.INTPTLAT, _c.INTPTLONG)
                if len(_d) and _d.min() < 100 and (_best is None or _d.min() < _best[0]):
                    _i = int(np.argmin(_d))
                    _best = (_d.min(), _cands["lat"].iloc[_i], _cands["lon"].iloc[_i])
            _found[f"{_label}_auto_lat"] = _best[1] if _best else np.nan
            _found[f"{_label}_auto_lon"] = _best[2] if _best else np.nan
        _auto_rows.append(_found)
    auto = pd.DataFrame(_auto_rows)
    print(
        f"{len(_named)} requests name a substation; automatic join finds a same-name point for "
        f"{int(auto['hifld_auto_lat'].notna().sum())} in HIFLD and {int(auto['verified_auto_lat'].notna().sum())} "
        "in verified"
    )
    return auto, km


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. The hand check

    Each of the 131 named substations was looked up on aerial imagery (`uv run chips.py` redraws the images).
    `hand_check.csv` records where it is, whether it exists, and what each source has within 1 km of it:

    - **found**: a point carrying the substation's name (or an obvious variant: `PAC HARRISBURG`,
      `LONGVIEW1`, `DE MOSS`).
    - **found under another name**: a point at the site, but its name is a placeholder (`UNKNOWN206447`),
      blank or another substation's. It's on the map; a name search won't find it.
    - **misplaced**: the name is in the source but more than 1 km from the yard, with nothing at the yard.
    - **missing**: nothing within 1 km.

    Substations that aren't built yet, that the filing calls planned and we couldn't find, or whose named
    points sit on bare ground with no yard we could locate (`exists` other than `yes`), are left out of the
    shares and counted separately. Ten identifications are marked low confidence, with the reason.
    """)
    return


@app.cell
def _(auto, km, pd, requests_read):
    checks = pd.read_csv("hand_check.csv")
    assert checks["key"].is_unique, "hand_check.csv has a duplicate key"
    joined = requests_read[requests_read["kind"].isin(["substation", "planned"])].merge(
        checks, left_on="substation", right_on="key", how="left", validate="many_to_one"
    )
    assert joined["key"].notna().all(), (
        f"no hand check for {sorted(set(joined.loc[joined['key'].isna(), 'substation']))}"
    )
    joined = joined.merge(auto, on="request_id", how="left", validate="one_to_one")
    for _src in ("hifld", "verified"):
        # The automatic join was right if its point is within 1 km of the yard we found on imagery.
        _d = km(joined[f"{_src}_auto_lat"], joined[f"{_src}_auto_lon"], joined["lat"], joined["lon"])
        joined[f"{_src}_auto_right"] = pd.Series(_d, index=joined.index).lt(1).fillna(False)
    print("Substation-naming requests by whether the substation exists:")
    _exists = (
        joined.groupby("exists").agg(requests=("request_id", "size"), GW=("mw", lambda s: s.sum() / 1000)).round(2)
    )
    print(_exists.to_string())
    _exists
    return checks, joined


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Results: found, misplaced or missing

    Shares of the requests that name an existing substation we confirmed on imagery, by request count and
    by requested MW.
    """)
    return


@app.cell
def _(OUTPUT_DIR, joined, pd, share_table):
    confirmed = joined[joined["exists"] == "yes"]
    _tables = []
    for _src, _label in (("hifld", "HIFLD Next"), ("verified", "us-substations-verified")):
        _t = share_table(confirmed, _src)
        _t.index = pd.MultiIndex.from_product([[_label], _t.index], names=["source", "verdict"])
        _tables.append(_t)
    results = pd.concat(_tables)
    results.to_csv(OUTPUT_DIR / "shares_by_source.csv")
    print(results.to_string())
    results
    return confirmed, results


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Naming problems or real gaps?

    A **naming miss** is a substation that's on the map but that the automatic join didn't land on: the
    name differs, is a placeholder, or matches a different substation of the same name (Benton City for
    BPA's Benton, Victor in Montana for Victor in Idaho). A **real gap** is a substation with no point within
    1 km.
    """)
    return


@app.cell
def _(OUTPUT_DIR, confirmed, pd):
    _rows = []
    for _src, _label in (("hifld", "HIFLD Next"), ("verified", "us-substations-verified")):
        _on_map = confirmed[_src].isin(["found", "found under another name"])
        _kinds = {
            "automatic join right": _on_map & confirmed[f"{_src}_auto_right"],
            "naming miss": _on_map & ~confirmed[f"{_src}_auto_right"],
            "real gap (missing)": confirmed[_src].eq("missing"),
            "misplaced": confirmed[_src].eq("misplaced"),
        }
        for _kind, _mask in _kinds.items():
            _rows.append(
                {
                    "source": _label,
                    "outcome": _kind,
                    "requests": int(_mask.sum()),
                    "MW": round(confirmed.loc[_mask, "mw"].sum()),
                    "live requests": int((_mask & confirmed["live"]).sum()),
                    "live MW": round(confirmed.loc[_mask & confirmed["live"], "mw"].sum()),
                    "substations": confirmed.loc[_mask, "key"].nunique(),
                }
            )
    naming = pd.DataFrame(_rows)
    naming.to_csv(OUTPUT_DIR / "naming_vs_gaps.csv", index=False)
    print(naming.to_string())
    naming
    return (naming,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. The ten substations with the most requested MW

    Live requests only, summed by substation, with the hand-check verdict in each source.
    """)
    return


@app.cell
def _(OUTPUT_DIR, joined):
    _live = joined[joined["live"]]
    top10 = (
        _live.groupby("key")
        .agg(
            live_requests=("request_id", "size"),
            live_MW=("mw", "sum"),
            exists=("exists", "first"),
            hifld=("hifld", "first"),
            verified=("verified", "first"),
        )
        .sort_values("live_MW", ascending=False)
        .head(10)
    )
    top10.to_csv(OUTPUT_DIR / "top10_substations.csv")
    print(top10.to_string())
    top10
    return (top10,)


@app.cell
def _(confirmed, joined, mo, naming, requests_read, results, workbook_date):
    def share(source: str, verdict: str, column: str) -> float:
        """A cell of the results table, 0 when no request got that verdict."""
        return float(results[column].get((source, verdict), 0.0))

    _sub = requests_read[requests_read["kind"].isin(["substation", "planned"])]
    _miss = naming[naming["outcome"] == "naming miss"].set_index("source")
    summary = f"""
    BPA's workbook of {workbook_date} lists {len(requests_read)} large-load requests totaling
    {requests_read["mw"].sum() / 1000:.1f} GW; {int(requests_read["live"].sum())} are live
    ({requests_read.loc[requests_read["live"], "mw"].sum() / 1000:.1f} GW). {len(_sub)} name a substation, and
    {len(confirmed)} of those ({confirmed["mw"].sum() / 1000:.1f} GW) name one we confirmed on imagery;
    {int((joined["exists"] != "yes").sum())} name one that isn't built, wasn't found or couldn't be confirmed.

    Of the confirmed requests, HIFLD Next has no point at the substation for
    {share("HIFLD Next", "missing", "requests %")}% of requests and {share("HIFLD Next", "missing", "GW %")}% of
    requested MW (live: {share("HIFLD Next", "missing", "live requests %")}% and
    {share("HIFLD Next", "missing", "live GW %")}%). us-substations-verified misses
    {share("us-substations-verified", "missing", "requests %")}% of requests and
    {share("us-substations-verified", "missing", "GW %")}% of MW. Requests whose substation either source has
    misplaced by more than 1 km: {int(confirmed["hifld"].eq("misplaced").sum())} (HIFLD),
    {int(confirmed["verified"].eq("misplaced").sum())} (verified).
    Naming misses (on the map, but the automatic join doesn't land on it): HIFLD
    {_miss.loc["HIFLD Next", "requests"]} requests ({_miss.loc["HIFLD Next", "MW"]:,} MW), verified
    {_miss.loc["us-substations-verified", "requests"]} requests ({_miss.loc["us-substations-verified", "MW"]:,} MW).
    """
    print(summary)
    mo.md("## Summary\n" + summary)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What didn't work

    - **Filed county and state are the load's, not the substation's.** Allston is in Oregon; four requests
      file it under Columbia County, WA. Big Eddy requests file Klickitat, WA. One request filed Modoc
      County, CA for a point of interconnection on Canby, Oregon streets. 61 requests have no state at all.
      Matching by county, as the issue proposed, would reject correct matches, so the automatic join
      allows 100 km.
    - **Names collide.** There are two Canbys, two Daytons, two Sullivans, two Victors and a Benton City
      beside BPA's Benton; the nearest same-name point is sometimes the wrong substation.
    - **Six named points sit on bare ground.** Both sources put Christmas Valley, Cedarville Junction,
      Duckabush, East Hills, Gold Beach and Cascade Locks where imagery shows no yard. They may be small pole
      structures; we couldn't find the yards, so they are left out rather than called misplaced.
    - **Voltage didn't help.** Most filings give no voltage, and the derived HIFLD voltages are floors, so
      we used it only to read the filings.
    """)
    return


if __name__ == "__main__":
    app.run()

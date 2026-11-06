import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # How many flood insurance claims can't FEMA's own flood maps place?

        OpenFEMA removes the NFIP Community Layer on November 9, 2026. It is the dataset that
        draws a boundary for every community in the National Flood Insurance Program (NFIP),
        keyed by community ID (CID). Every NFIP claim carries the CID of the community it was
        rated in, so the Community Layer is how people map claims by community.

        The only other public source of NFIP community boundaries is FEMA's National Flood
        Hazard Layer (NFHL), whose Political Jurisdictions layer also carries a CID. So the
        question is: **if you join every NFIP claim to the NFHL by CID instead, how many
        claims have nowhere to go, and why?**

        This notebook pulls everything fresh, matches every claim against three sources, then
        looks at the communities the NFHL can't place: what they are, why the NFHL lacks
        them, and whether a county crosswalk could place their claims without the
        Community Layer.
        """
    )
    return (mo,)


@app.cell
def _():
    import datetime as dt
    import io
    import json
    import os
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import geopandas as gpd
    import pandas as pd
    import pyarrow.parquet as pq
    import requests
    from shapely.geometry import Point

    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("NFIP_GAP_DATA", HERE / "data"))
    RESULTS = Path(os.environ.get("NFIP_GAP_RESULTS", HERE / "results"))
    DATA.mkdir(parents=True, exist_ok=True)
    RESULTS.mkdir(parents=True, exist_ok=True)
    PULL_DATE = dt.datetime.now(dt.UTC).date().isoformat()
    STARTED = time.monotonic()

    OPENFEMA = "https://www.fema.gov/api/open"
    HIFLD = "https://hifld.publicenvirodata.org/storage/openfema/nfip-community-boundaries"
    NFHL = "https://hazards.fema.gov/arcgis/rest/services/public/NFHL/MapServer"

    def get(url: str, params: dict | None = None, timeout: int = 120) -> requests.Response:
        """GET with a bounded retry. FEMA's servers reset connections often."""
        for attempt in range(6):
            try:
                response = requests.get(url, params=params, timeout=timeout)
                if response.status_code == 200:
                    return response
            except requests.RequestException:
                pass
            time.sleep(2**attempt)
        raise RuntimeError(f"gave up on {url} {params}")

    def arcgis_json(url: str, params: dict) -> dict:
        """An ArcGIS REST query; these return HTTP 200 with an error body, so check it."""
        for _attempt in range(4):
            body = get(url, {**params, "f": "json"}).json()
            if "error" not in body:
                return body
            time.sleep(3)
        raise RuntimeError(f"ArcGIS error from {url}: {body['error']}")

    return (
        DATA,
        HIFLD,
        NFHL,
        OPENFEMA,
        PULL_DATE,
        Point,
        RESULTS,
        STARTED,
        ThreadPoolExecutor,
        arcgis_json,
        get,
        gpd,
        io,
        json,
        pd,
        pq,
        time,
    )


@app.cell
def _(mo):
    mo.md("""
    ## The data

    Four public sources, all downloaded at run time into `data/` (not committed). A
    file already pulled today is reused, so a second run the same day is quick.

    1. **NFIP Redacted Claims v3** from the OpenFEMA API: one row per claim since 1978.
       We only need three columns: `nfipRatedCommunityNumber` (the CID), `countyCode`
       and `state`. The bulk file refuses scripted downloads, so we page the API,
       10,000 rows a call.
    2. **The NFIP Community Layer** from HIFLD Next's preserved copy, in two of FEMA's
       three versions: *Comprehensive* (every CID, overlaps allowed) and *No Overlaps
       Whole* (the version FEMA also publishes on ArcGIS Online). This is the copy that
       survives November 9.
    3. **NFHL Political Jurisdictions** (MapServer layer 22): attributes only, every
       polygon's CID, county and map ID.
    4. **FEMA's Community Status Book** from OpenFEMA: every NFIP community, whether it
       participates, and its current effective map date.
    """)
    return


@app.cell
def _(DATA, OPENFEMA, PULL_DATE, ThreadPoolExecutor, get, io, pd):
    _path = DATA / f"claims-{PULL_DATE}.parquet"
    if not _path.exists():
        _url = f"{OPENFEMA}/v3/NfipClaims"
        _total = get(_url, {"$top": 1, "$inlinecount": "allpages", "$select": "id"}).json()
        _total = _total["metadata"]["count"]
        assert 2_000_000 < _total < 5_000_000, f"unexpected claim count {_total}"

        def _page(skip: int) -> pd.DataFrame:
            _params = {
                "$select": "id,nfipRatedCommunityNumber,countyCode,state",
                "$top": 10_000,
                "$skip": skip,
                "$orderby": "id",
                "$format": "csv",
            }
            return pd.read_csv(io.StringIO(get(_url, _params).text), dtype=str)

        with ThreadPoolExecutor(8) as _pool:
            _pages = list(_pool.map(_page, range(0, _total, 10_000)))
        _claims = pd.concat(_pages, ignore_index=True)
        assert _claims["id"].is_unique and len(_claims) == _total, "paging lost or doubled rows"
        _claims.to_parquet(_path)
    claims = pd.read_parquet(_path).rename(columns={"nfipRatedCommunityNumber": "cid"})
    return (claims,)


@app.cell
def _(DATA, HIFLD, get, gpd, pq):
    layer_paths = {}
    for _version in ["comprehensive", "no-overlaps-whole"]:
        _path = DATA / f"{_version}.parquet"
        if not _path.exists():
            _url = f"{HIFLD}/{_version}/v1.0.0/geoparquet/{_version}.parquet"
            _path.write_bytes(get(_url, timeout=600).content)
        layer_paths[_version] = _path
    community_layer_cids = {
        _version: set(pq.read_table(_p, columns=["communityIdNumber"])[0].to_pylist())
        for _version, _p in layer_paths.items()
    }
    community_layer = gpd.read_parquet(
        layer_paths["comprehensive"],
        columns=["communityIdNumber", "communityName", "stateCode", "countyCode", "geometry"],
    )
    return community_layer, community_layer_cids


@app.cell
def _(DATA, NFHL, PULL_DATE, ThreadPoolExecutor, arcgis_json, pd):
    _path = DATA / f"nfhl-political-jurisdictions-{PULL_DATE}.parquet"
    if not _path.exists():
        _url = f"{NFHL}/22/query"
        _total = arcgis_json(_url, {"where": "1=1", "returnCountOnly": "true"})["count"]

        def _page(offset: int) -> pd.DataFrame:
            _body = arcgis_json(
                _url,
                {
                    "where": "1=1",
                    "outFields": "OBJECTID,CID,DFIRM_ID,ST_FIPS,CO_FIPS,POL_NAME1",
                    "returnGeometry": "false",
                    "orderByFields": "OBJECTID",
                    "resultOffset": offset,
                    "resultRecordCount": 2000,
                },
            )
            return pd.DataFrame([_f["attributes"] for _f in _body["features"]])

        with ThreadPoolExecutor(4) as _pool:
            _pages = list(_pool.map(_page, range(0, _total, 2000)))
        _nfhl = pd.concat(_pages, ignore_index=True)
        assert _nfhl["OBJECTID"].is_unique and len(_nfhl) == _total, "paging lost rows"
        _nfhl.to_parquet(_path)
    nfhl = pd.read_parquet(_path)
    nfhl["county_fips"] = nfhl["ST_FIPS"] + nfhl["CO_FIPS"]
    nfhl_cids = set(nfhl["CID"].dropna())
    return nfhl, nfhl_cids


@app.cell
def _(DATA, OPENFEMA, PULL_DATE, get, io, pd):
    _path = DATA / f"community-status-book-{PULL_DATE}.csv"
    if not _path.exists():
        _path.write_bytes(get(f"{OPENFEMA}/v1/NfipCommunityStatusBook.csv").content)
    status_book = pd.read_csv(io.BytesIO(_path.read_bytes()), dtype=str)
    status_book["participating"] = status_book["participatingInNFIP"].isin(["1", "true", "True"])
    return (status_book,)


@app.cell
def _(claims, community_layer_cids, mo, nfhl, nfhl_cids, pd, status_book):
    _rows = [
        ("NFIP claims (OpenFEMA, v3)", len(claims), claims["cid"].nunique()),
        (
            "Community Layer, Comprehensive (HIFLD Next)",
            None,
            len(community_layer_cids["comprehensive"]),
        ),
        (
            "Community Layer, No Overlaps Whole (HIFLD Next)",
            None,
            len(community_layer_cids["no-overlaps-whole"]),
        ),
        ("NFHL Political Jurisdictions (layer 22)", len(nfhl), len(nfhl_cids)),
        ("Community Status Book", len(status_book), status_book["communityIdNumber"].nunique()),
    ]
    sources = pd.DataFrame(_rows, columns=["source", "rows", "distinct CIDs"])
    mo.vstack([mo.md("What came down:"), mo.ui.table(sources, selection=None)])
    return


@app.cell
def _(mo):
    mo.md("""
    ## The match

    For each source, a claim is *placed* if its CID appears in that source. That's the
    join anyone mapping claims by community does. 48 claims have no CID at all and count
    as unplaced everywhere.
    """)
    return


@app.cell
def _(PULL_DATE, RESULTS, claims, community_layer_cids, mo, nfhl_cids, pd):
    _sources = {
        "Community Layer, Comprehensive": community_layer_cids["comprehensive"],
        "Community Layer, No Overlaps Whole": community_layer_cids["no-overlaps-whole"],
        "NFHL Political Jurisdictions": nfhl_cids,
    }
    placement = pd.DataFrame(
        [
            {
                "source": _name,
                "claims placed": int(claims["cid"].isin(_cids).sum()),
                "share placed (%)": round(100 * claims["cid"].isin(_cids).mean(), 2),
                "claims unplaced": int((~claims["cid"].isin(_cids)).sum()),
            }
            for _name, _cids in _sources.items()
        ]
    )
    placement["pull date"] = PULL_DATE
    placement.to_csv(RESULTS / "placement.csv", index=False)
    print(f"Claims pulled {PULL_DATE}: {len(claims):,}")
    print(placement.to_string(index=False))
    mo.ui.table(placement, selection=None)
    return


@app.cell
def _(mo):
    mo.md("""
    ## The communities the NFHL can't place

    Group the claims the NFHL misses by CID and look each CID up in the Community Status
    Book and the Community Layer. Some CIDs are in neither: placeholder `999999`, and
    old CIDs FEMA retired (for example `125098`, 6,524 claims in Miami-Dade County).
    The Community Layer can't place those either, so we split them out and count only
    real communities as the NFHL's gap.
    """)
    return


@app.cell
def _(claims, community_layer, nfhl_cids, pd, status_book):
    _missing = claims[~claims["cid"].isin(nfhl_cids) & claims["cid"].notna()]
    _names = community_layer.drop_duplicates("communityIdNumber").set_index("communityIdNumber")
    _book = status_book.drop_duplicates("communityIdNumber").set_index("communityIdNumber")
    gap = (
        _missing.groupby("cid")
        .agg(
            claims=("id", "size"),
            state=("state", "first"),
            county_fips=("countyCode", lambda s: s.mode().iat[0] if s.notna().any() else None),
        )
        .sort_values("claims", ascending=False)
        .reset_index()
    )
    gap["name"] = (
        gap["cid"].map(_book["communityName"]).fillna(gap["cid"].map(_names["communityName"]))
    )
    gap["in_status_book"] = gap["cid"].isin(_book.index)
    gap["participating"] = gap["cid"].map(_book["participating"]).fillna(False).astype(bool)
    gap["effective_map_date"] = gap["cid"].map(_book["currentlyEffectiveMapDate"])
    gap["in_community_layer"] = gap["cid"].isin(_names.index)
    gap["real_community"] = gap["in_status_book"] | gap["in_community_layer"]
    real_gap = gap[gap["real_community"]]
    gap_summary = pd.DataFrame(
        [
            (
                "real communities (in the Status Book or Community Layer)",
                len(real_gap),
                int(real_gap["claims"].sum()),
            ),
            (
                "retired or placeholder CIDs (in neither)",
                int((~gap["real_community"]).sum()),
                int(gap.loc[~gap["real_community"], "claims"].sum()),
            ),
        ],
        columns=["CIDs the NFHL lacks", "CIDs", "claims"],
    )
    print(gap_summary.to_string(index=False))
    gap_summary
    return gap, real_gap


@app.cell
def _(mo, real_gap):
    mo.vstack(
        [
            mo.md("The 15 real communities with the most claims and no NFHL polygon:"),
            mo.ui.table(
                real_gap.head(15)[["cid", "name", "state", "claims", "effective_map_date"]],
                selection=None,
            ),
        ]
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Why the NFHL lacks them

    A missing CID can mean two different things:

    - **No digital flood map there at all.** The community's current map is an old paper
      FIRM that was never loaded into the NFHL, so no FIRM panel in the NFHL covers its
      land. A claim there can't be put on a digital flood map by any crosswalk.
    - **Mapped under another CID.** The land is on a digital FIRM panel, inside a
      polygon filed under a county, parish or neighboring community. Then the gap is
      bookkeeping: a crosswalk from the missing CID to the one the NFHL uses would place
      the claims.

    To tell them apart, take a point inside each missing community's Community Layer
    polygon (the largest part, for communities in several pieces) and ask the NFHL what
    is there: which Political Jurisdiction polygon (layer 22), and whether any FIRM
    panel (layer 3). Results are cached per pull date, since this is about 3,000 calls
    to a server that drops connections.

    The FIRM panel matters. Our hand check found Slidell's land inside a "Saint Tammany
    Parish" polygon, but that polygon comes from the City of Mandeville's own map
    (DFIRM `220202`), which draws the parish around Mandeville and has no panel over
    Slidell. A political polygon with no panel under it is not a flood map.
    """)
    return


@app.cell
def _(
    DATA,
    NFHL,
    PULL_DATE,
    Point,
    ThreadPoolExecutor,
    arcgis_json,
    community_layer,
    pd,
    real_gap,
):
    _path = DATA / f"point-checks-{PULL_DATE}.csv"
    _done = pd.read_csv(_path, dtype={"cid": str}) if _path.exists() else pd.DataFrame()
    _todo = set(real_gap["cid"]) - set(_done.get("cid", []))
    _shapes = community_layer[community_layer["communityIdNumber"].isin(_todo)]
    _shapes = _shapes.dissolve("communityIdNumber").explode(index_parts=False)
    _shapes["area"] = _shapes.to_crs(5070).geometry.area
    _largest = _shapes.sort_values("area").groupby(level=0).tail(1)
    _points = list(_largest.geometry.representative_point().items())

    def _ask(item: tuple[str, Point]) -> dict | None:
        _cid, _pt = item
        _where = {
            "geometry": f"{_pt.x},{_pt.y}",
            "geometryType": "esriGeometryPoint",
            "inSR": 4326,
            "spatialRel": "esriSpatialRelIntersects",
            "returnGeometry": "false",
        }
        try:
            _jur = arcgis_json(f"{NFHL}/22/query", {**_where, "outFields": "CID,POL_NAME1"})
            _pan = arcgis_json(f"{NFHL}/3/query", {**_where, "outFields": "FIRM_PAN"})
        except RuntimeError:
            return None  # left out of the cache, so the next run asks again
        _hits = [_f["attributes"] for _f in _jur["features"]]
        return {
            "cid": _cid,
            "lon": round(_pt.x, 5),
            "lat": round(_pt.y, 5),
            "nfhl_cid_at_point": ";".join(str(_h["CID"]) for _h in _hits) or None,
            "nfhl_name_at_point": ";".join(str(_h["POL_NAME1"]) for _h in _hits) or None,
            "firm_panel_at_point": len(_pan["features"]) > 0,
        }

    # Ask in chunks and append each chunk to the cache, so a dropped run resumes.
    with ThreadPoolExecutor(6) as _pool:
        for _start in range(0, len(_points), 120):
            _rows = [r for r in _pool.map(_ask, _points[_start : _start + 120]) if r]
            if _rows:
                pd.DataFrame(_rows).to_csv(_path, mode="a", header=not _path.exists(), index=False)
    point_checks = pd.read_csv(_path, dtype={"cid": str, "nfhl_cid_at_point": str})
    _unchecked = int(
        (real_gap["in_community_layer"] & ~real_gap["cid"].isin(point_checks["cid"])).sum()
    )
    print(
        f"Point checks: {len(point_checks):,} communities; NFHL never answered for "
        f"{_unchecked} (rerun to retry them)"
    )
    return (point_checks,)


@app.cell
def _(point_checks, real_gap):
    _COUNTY_WORDS = "COUNTY|PARISH|BOROUGH|MUNICIPIO|CENSUS AREA"
    causes = real_gap.merge(point_checks, on="cid", how="left")
    _polygon = causes["nfhl_cid_at_point"].notna()
    _panel = causes["firm_panel_at_point"].fillna(False).astype(bool)
    _county = causes["nfhl_name_at_point"].fillna("").str.upper().str.contains(_COUNTY_WORDS)
    causes["cause"] = "no map: nothing in the NFHL at the point"
    causes.loc[_polygon & ~_panel, "cause"] = "no map: a neighbor's polygon, but no FIRM panel"
    causes.loc[_panel & ~_polygon, "cause"] = "mapped: FIRM panel, but no political polygon"
    causes.loc[_panel & _polygon & ~_county, "cause"] = "mapped under another community's CID"
    causes.loc[_panel & _polygon & _county, "cause"] = "mapped under the county's or parish's CID"
    causes.loc[causes["in_community_layer"] & causes["lon"].isna(), "cause"] = (
        "NFHL query failed (rerun)"
    )
    causes.loc[~causes["in_community_layer"], "cause"] = "no Community Layer polygon to check"
    cause_table = (
        causes.groupby("cause")
        .agg(communities=("cid", "size"), claims=("claims", "sum"))
        .sort_values("claims", ascending=False)
        .reset_index()
    )
    cause_table["share of gap claims (%)"] = (
        100 * cause_table["claims"] / cause_table["claims"].sum()
    ).round(1)
    print(cause_table.to_string(index=False))
    cause_table
    return (causes,)


@app.cell
def _(mo):
    mo.md("""
    ### The four hand-checked communities

    The issue names Slidell, St. Charles Parish, Beaumont and Port Arthur. Their rows are
    below; `handcheck.md` has what we found when we looked at each one in FEMA's map
    viewer and Map Service Center.
    """)
    return


@app.cell
def _(causes, mo):
    _named = causes[causes["cid"].isin(["220204", "220160", "485457", "485499"])]
    mo.ui.table(
        _named[
            [
                "cid",
                "name",
                "claims",
                "effective_map_date",
                "nfhl_name_at_point",
                "firm_panel_at_point",
                "cause",
            ]
        ],
        selection=None,
    )
    return


@app.cell
def _(mo):
    mo.md("""
    ## Could a county crosswalk place them instead?

    Without the Community Layer, the obvious fallback is the claim's county. Every claim
    with a `countyCode` can go to its county, and the NFHL does draw most counties' own
    unincorporated areas. So the crosswalk is: claim county → the NFHL polygon(s) of that
    county's own CID (a layer 22 polygon in that county whose name says county, parish or
    borough).

    Two counts matter. How many missing claims the crosswalk puts *somewhere* on the NFHL,
    and how many it puts on the *right land*: the point check found the community inside
    that same county polygon. The rest land on the county's unincorporated area, which
    is not where the claim is.
    """)
    return


@app.cell
def _(causes, claims, nfhl, nfhl_cids, pd):
    _county_polys = nfhl[
        nfhl["POL_NAME1"].fillna("").str.upper().str.contains("COUNTY|PARISH|BOROUGH|MUNICIPIO")
    ]
    _county_cid = _county_polys.groupby("county_fips")["CID"].agg(lambda s: set(s.dropna()))
    _gap_claims = claims[claims["cid"].isin(causes["cid"])].merge(
        causes[["cid", "nfhl_cid_at_point"]], on="cid"
    )
    _targets = _gap_claims["countyCode"].map(_county_cid)
    _has_target = _targets.notna()
    _right_land = [
        bool(t) and isinstance(p, str) and bool(set(p.split(";")) & t)
        for t, p in zip(_targets.fillna(""), _gap_claims["nfhl_cid_at_point"], strict=True)
    ]
    crosswalk = pd.DataFrame(
        [
            ("claims in real communities the NFHL lacks", len(_gap_claims)),
            ("  with a county code on the claim", int(_gap_claims["countyCode"].notna().sum())),
            ("  whose county has its own NFHL polygon", int(_has_target.sum())),
            ("  ...and the community lies inside that county polygon", int(sum(_right_land))),
        ],
        columns=["county crosswalk", "claims"],
    )
    crosswalk["share (%)"] = (100 * crosswalk["claims"] / len(_gap_claims)).round(1)
    _recovered = int(sum(_right_land))
    _with_crosswalk = int(claims["cid"].isin(nfhl_cids).sum()) + _recovered
    print(crosswalk.to_string(index=False))
    print(
        f"NFHL plus a county crosswalk, right land only: {_with_crosswalk:,} claims "
        f"({100 * _with_crosswalk / len(claims):.2f}%)"
    )
    crosswalk
    return


@app.cell
def _(mo):
    mo.md("""
    ## Participating communities with no NFHL polygon

    The claims view weights big flood towns. The Status Book view counts every
    community in the NFIP today, flooded or not: how many participating communities
    have no polygon under their own CID in the NFHL, by state.
    """)
    return


@app.cell
def _(RESULTS, mo, nfhl_cids, status_book):
    _participating = status_book[status_book["participating"]]
    _absent = _participating[~_participating["communityIdNumber"].isin(nfhl_cids)]
    by_state = (
        _absent.groupby("state")
        .size()
        .rename("communities without an NFHL polygon")
        .sort_values(ascending=False)
        .reset_index()
    )
    by_state.to_csv(RESULTS / "status-book-no-nfhl-by-state.csv", index=False)
    print(
        f"Participating communities: {len(_participating):,}; "
        f"with no NFHL polygon: {len(_absent):,} ({100 * len(_absent) / len(_participating):.1f}%)"
    )
    print("Top states:", ", ".join(f"{r.state} {r.iloc[1]}" for r in by_state.head(8).itertuples()))
    mo.ui.table(by_state, selection=None)
    return


@app.cell
def _(mo):
    mo.md("""
    ## Is FEMA's ArcGIS Online copy still up?

    FEMA also publishes the Community Layer as an ArcGIS Online feature service,
    *NFIP Community Layer (flattened) 2024v1*, with no stated end date. Each run checks
    that the item still exists and its layer still answers a count query.
    """)
    return


@app.cell
def _(PULL_DATE, get, json):
    _item_id = "4b712b99d43d41cb9328e94891520a63"
    _item = get(f"https://www.arcgis.com/sharing/rest/content/items/{_item_id}", {"f": "json"})
    _item = _item.json()
    agol = {
        "checked": PULL_DATE,
        "item": _item_id,
        "title": _item.get("title"),
        "access": _item.get("access"),
        "item_error": _item.get("error"),
    }
    if "url" in _item:
        _count = get(
            f"{_item['url']}/0/query", {"where": "1=1", "returnCountOnly": "true", "f": "json"}
        ).json()
        agol["feature_count"] = _count.get("count")
        agol["query_error"] = _count.get("error")
    print("ArcGIS Online copy:", json.dumps(agol))
    agol
    return (agol,)


@app.cell
def _(RESULTS, STARTED, agol, causes, gap, json, time):
    gap.merge(
        causes[
            [
                "cid",
                "lon",
                "lat",
                "nfhl_cid_at_point",
                "nfhl_name_at_point",
                "firm_panel_at_point",
                "cause",
            ]
        ],
        on="cid",
        how="left",
    ).to_csv(RESULTS / "gap-by-community.csv", index=False)
    (RESULTS / "arcgis-online-check.json").write_text(json.dumps(agol, indent=2) + "\n")
    print(f"Run time: {time.monotonic() - STARTED:.0f} s")
    return


@app.cell
def _(mo):
    mo.md("""
    ## What didn't work, and what this doesn't show

    - **The bulk claims file refuses scripted downloads** (HTTP 403), so the notebook
      pages the OpenFEMA API instead: about 275 calls, two to three minutes.
    - **FEMA's NFHL server resets connections** on a good share of calls. Every call is
      retried with backoff up to six times; a run that still fails stops rather than
      reporting partial numbers.
    - **One point per community.** The cause check asks the NFHL about one point inside
      each community's largest piece. A community partly on a digital map and partly
      not (Port Arthur is split this way) gets the answer for that one point.
    - **The Community Layer is frozen at December 2024** and FEMA says it "should not be
      considered authoritative." Its boundaries are what we test against, so its errors
      carry into the cause check.
    - **The NFHL changes as new maps go effective**, and claims update monthly. Every
      number here is for the pull date printed above.
    """)
    return


if __name__ == "__main__":
    app.run()

import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")

with app.setup:
    import json
    import os
    import re
    import time
    import urllib.request
    import zipfile
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd
    import shapely
    from pyproj import Geod

    HERE = Path(__file__).parent
    DATA = Path(os.environ.get("FORM1_DATA_DIR", HERE / "data"))
    OUT = Path(os.environ.get("FORM1_OUTPUT_DIR", HERE / "output"))
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    RUN_STARTED = time.perf_counter()


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    # How many lines on the public HIFLD transmission map can be tied to what utilities report spending on them?

    **The question.** The HIFLD Electric Power Transmission Lines layer, preserved in
    [HIFLD Next](https://hifld.publicenvirodata.org), says where the US grid's lines run. FERC Form 1 is the only
    current federal filing that says what individual lines cost, and it names lines only by their end substations.
    In August 2026 Lawrence Berkeley National Laboratory published a file linking the two
    ([OEDI submission 8742](https://data.openei.org/submissions/8742), CC BY 4.0).

    **What we expected.** Joining LBNL's file to HIFLD Next would tie only a minority of HIFLD lines to a Form 1
    record; federal power marketers (BPA, WAPA, TVA) and co-ops would be near zero; and most matched lines would
    still carry no usable cost. **We'd be wrong** if most HIFLD lines match and most matches carry a cost.

    The steps: load both files, join them, measure the match share against the whole layer and against the lines
    Form 1 is meant to cover, count matched lines with a cost, hand-check 20 suspicious matches, check which HIFLD
    vintage LBNL used, and read what FERC's instructions say about blank cost cells.
    """)
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 1. The data

    Six public files, downloaded on the first run into `data/` (not committed):

    | File | Source | Used for |
    |---|---|---|
    | Transmission Lines, layer v1.0.0 | HIFLD Next GeoParquet | the line map |
    | `ferc_eia_transmission_lines_public.csv` | LBNL, OEDI 8742 (CC BY 4.0) | the Form 1 link and costs |
    | Electric Retail Service Territories, v1.0.0 | HIFLD Next GeoParquet | each owner's type |
    | `cb_2023_us_state_20m.zip` | US Census cartographic boundaries | each line's state |
    | Form 1 schedule 422 and utility names | [PUDL](https://catalyst.coop/pudl/) nightly (CC BY 4.0) | totals rows |
    """)
    return


@app.cell
def _():
    _hifld = "https://storage.googleapis.com/hifld-next-datasets-prod/hifld"
    _lines = "transmission-lines-1/transmission-lines-1/v1.0.0/geoparquet/transmission-lines-1.parquet"
    _rst = "electric-retail-service-territories"
    _pudl = "https://s3.us-west-2.amazonaws.com/pudl.catalyst.coop/nightly"
    _sched422 = "core_ferc1__yearly_transmission_lines_sched422"
    _utilities = "core_pudl__assn_ferc1_pudl_utilities"
    sources = {
        "transmission-lines.parquet": f"{_hifld}/{_lines}",
        "ferc_eia_transmission_lines_public.csv": "https://data.openei.org/files/8742/ferc_eia_transmission_lines_public.csv",
        f"{_rst}.parquet": f"{_hifld}/{_rst}/{_rst}/v1.0.0/geoparquet/{_rst}.parquet",
        "cb_2023_us_state_20m.zip": "https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_state_20m.zip",
        f"{_sched422}.parquet": f"{_pudl}/{_sched422}.parquet",
        f"{_utilities}.parquet": f"{_pudl}/{_utilities}.parquet",
    }
    for _name, _url in sources.items():
        _path = DATA / _name
        if _path.exists() and _path.stat().st_size > 0:
            continue
        print(f"downloading {_url}")
        _tmp = _path.with_suffix(".part")
        with urllib.request.urlopen(_url, timeout=600) as _resp:
            assert _resp.status == 200, f"{_url} returned HTTP {_resp.status}"
            _tmp.write_bytes(_resp.read())
        assert zipfile.is_zipfile(_tmp) if _name.endswith(".zip") else _tmp.stat().st_size > 1000, (
            f"bad download {_url}"
        )
        _tmp.rename(_path)
    return (sources,)


@app.cell
def _(sources):
    lines = gpd.read_parquet(DATA / "transmission-lines.parquet")
    lbnl = pd.read_csv(DATA / "ferc_eia_transmission_lines_public.csv", dtype={"GlobalID": str})
    assert lines.crs is not None and lines.crs.to_epsg() == 4326, lines.crs
    assert lines["source_ID"].is_unique and lbnl["GlobalID"].is_unique
    _ = sources
    mo.md(f"""
    HIFLD Next has **{len(lines):,}** transmission line segments. LBNL's file has **{len(lbnl):,}** rows, one per
    matched HIFLD line, each carrying the Form 1 record (report year, respondent, end substations, voltage, length,
    costs, expenses) and a match confidence tier.

    **The join key is not a GlobalID.** LBNL's column is named `GlobalID`, but its values (for example
    `{lbnl["GlobalID"].iloc[0]}`) are HIFLD's numeric line `ID`, which HIFLD Next keeps as `source_ID`. HIFLD Next
    has no GlobalID column at all. So the join below is LBNL `GlobalID` to HIFLD Next `source_ID`.
    """)
    return lbnl, lines


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 2. Preparing the line layer

    Three things the layer doesn't carry directly:

    - **Length in miles.** We measure each segment's geodesic length on the WGS84 ellipsoid.
    - **State.** We place each segment in the state that contains its midpoint.
    - **Owner type.** HIFLD gives an owner name only. We take the type from HIFLD Next's Retail Service Territories
      layer, matching on the owner name after dropping punctuation and suffixes such as "Co" and "LLC". Federal
      agencies, co-ops and public power names that the territories layer doesn't list are caught by keywords. Any
      remaining named owner is counted as investor-owned (mostly investor-owned utilities and independent
      transmission companies; the table in section 3 lists the biggest so you can check). Segments with owner
      `NOT AVAILABLE` stay "owner not recorded".

    HIFLD has no circuit count, so "miles" here are route miles of HIFLD segments, not circuit miles.
    """)
    return


@app.cell
def _(lines):
    hifld = lines.copy()
    _geod = Geod(ellps="WGS84")
    hifld["miles"] = [_geod.geometry_length(_g) / 1609.344 for _g in hifld.geometry]

    _states = gpd.read_file(f"zip://{DATA / 'cb_2023_us_state_20m.zip'}").to_crs(4326)[["STUSPS", "geometry"]]
    _mid = gpd.GeoDataFrame(
        {"source_ID": hifld["source_ID"]},
        geometry=shapely.line_interpolate_point(shapely.line_merge(hifld.geometry.values), 0.5, normalized=True),
        crs=4326,
    )
    _in_state = gpd.sjoin(_mid, _states, predicate="within", how="left").drop_duplicates("source_ID")
    hifld["state"] = _in_state.set_index("source_ID").loc[hifld["source_ID"], "STUSPS"].fillna("outside US").values

    _territories = pd.read_parquet(DATA / "electric-retail-service-territories.parquet", columns=["NAME", "TYPE"])
    _suffixes = r"\b(CO|COMPANY|INC|LLC|CORP|CORPORATION|LP|THE|OF)\b"

    def norm_owner(name: str) -> str:
        name = re.sub(r"\(.*?\)", " ", str(name).upper()).replace("&", " AND ")
        name = re.sub(_suffixes, " ", re.sub(r"[^A-Z0-9 ]", " ", name))
        return " ".join(name.split())

    _type_names = {
        "INVESTOR OWNED": "Investor-owned",
        "COOPERATIVE": "Co-op",
        "MUNICIPAL": "Public power",
        "POLITICAL SUBDIVISION": "Public power",
        "STATE": "Public power",
        "MUNICIPAL MKTG AUTHORITY": "Public power",
        "FEDERAL": "Federal",
    }
    _known = _territories[_territories["TYPE"].isin(_type_names)]
    _by_name = dict(zip(_known["NAME"].map(norm_owner), _known["TYPE"].map(_type_names), strict=True))
    _keywords = [
        (
            "Federal",
            r"BONNEVILLE|WAPA|WESTERN AREA POWER|TENNESSEE VALLEY|POWER ADMINISTRATION|RECLAMATION|CORPS OF ENG",
        ),
        ("Co-op", r"COOP|CO-OP|G ?& ?T|ELECTRIC ASSOCIATION|RURAL ELECTRIC|GEORGIA TRANSMISSION|MEMBERSHIP"),
        ("Public power", r"CITY OF|TOWN OF|VILLAGE OF|MUNICIPAL|DISTRICT|AUTHORITY|AGENCY|\bPUD\b|LADWP|PREPA|AZUSA"),
    ]

    def owner_type(owner: str) -> str:
        if owner == "NOT AVAILABLE":
            return "Owner not recorded"
        if re.search(_keywords[0][1], owner):
            return "Federal"
        if norm_owner(owner) in _by_name:
            return _by_name[norm_owner(owner)]
        for _kind, _pattern in _keywords[1:]:
            if re.search(_pattern, owner):
                return _kind
        return "Investor-owned"

    _owner_types = {_o: owner_type(_o) for _o in hifld["OWNER"].fillna("NOT AVAILABLE").unique()}
    hifld["owner_type"] = hifld["OWNER"].fillna("NOT AVAILABLE").map(_owner_types)
    hifld["hv"] = hifld["VOLTAGE"] >= 132
    mo.md(f"""
    Total: **{hifld["miles"].sum():,.0f}** route miles; **{hifld["hv"].sum():,}** segments
    (**{hifld.loc[hifld["hv"], "miles"].sum():,.0f}** miles) at 132 kV and up. **{(hifld["VOLTAGE"] < 0).sum():,}**
    segments have no voltage (recorded as -999999) and so fall outside the 132 kV+ counts.
    """)
    return (hifld,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 3. How many HIFLD lines get a Form 1 match?

    Form 1 lists individual lines only at 132 kV and up, and only for "major" utilities under FERC's jurisdiction:
    investor-owned utilities and transmission companies. BPA, WAPA, TVA, most co-ops and public power don't file
    it. So we report the match share three ways: the whole layer, lines at 132 kV and up, and the **Form 1-covered
    subset**, investor-owned lines at 132 kV and up. That last one is the fair test.
    """)
    return


@app.cell
def _(hifld, lbnl):
    joined = hifld.merge(
        lbnl.drop(columns=["linestring_coord", "coordinates"]).rename(columns={"state": "state_ferc"}),
        how="left",
        left_on="source_ID",
        right_on="GlobalID",
    )
    assert len(joined) == len(hifld)
    joined["match_tier"] = joined["confidence_tier"].fillna("none")
    joined["matched"] = joined["match_tier"] != "none"
    missing_from_next = int((~lbnl["GlobalID"].isin(hifld["source_ID"])).sum())
    _iou_hv = joined["hv"] & (joined["owner_type"] == "Investor-owned")

    def share(frame: pd.DataFrame) -> dict[str, float]:
        return {
            "segments": len(frame),
            "matched": int(frame["matched"].sum()),
            "share_count": frame["matched"].mean(),
            "miles": frame["miles"].sum(),
            "matched_miles": frame.loc[frame["matched"], "miles"].sum(),
            "share_miles": frame.loc[frame["matched"], "miles"].sum() / frame["miles"].sum(),
        }

    match_overall = pd.DataFrame(
        {
            "Whole layer": share(joined),
            "132 kV and up": share(joined[joined["hv"]]),
            "Form 1-covered (investor-owned, 132 kV+)": share(joined[_iou_hv]),
        }
    ).T
    match_by_owner = pd.DataFrame(
        {_t: share(_g) for _t, _g in joined[joined["hv"]].groupby("owner_type")}
    ).T.sort_values("miles", ascending=False)
    match_overall.to_csv(OUT / "match_overall.csv")
    match_by_owner.to_csv(OUT / "match_by_owner_type_132kv.csv")
    mo.vstack(
        [
            mo.md(f"All **{len(lbnl):,}** LBNL rows join; **{missing_from_next}** are missing from HIFLD Next."),
            mo.md("**Match share, whole layer vs the lines Form 1 is meant to cover**"),
            mo.ui.table(match_overall.round(3), selection=None),
            mo.md("**At 132 kV and up, by owner type**"),
            mo.ui.table(match_by_owner.round(3), selection=None),
        ]
    )
    return joined, match_by_owner, match_overall, missing_from_next


@app.cell
def _(joined):
    _hv = joined[joined["hv"]]
    match_by_state = (
        _hv.groupby("state")
        .apply(
            lambda g: pd.Series(
                {
                    "segments": len(g),
                    "miles": g["miles"].sum(),
                    "share_miles": g.loc[g["matched"], "miles"].sum() / g["miles"].sum(),
                    "iou_miles": g.loc[g["owner_type"] == "Investor-owned", "miles"].sum(),
                }
            ),
            include_groups=False,
        )
        .sort_values("miles", ascending=False)
    )
    match_by_state.to_csv(OUT / "match_by_state_132kv.csv")
    _top_owners = (
        _hv[_hv["owner_type"] == "Investor-owned"]
        .groupby("OWNER")
        .agg(miles=("miles", "sum"), share_miles=("matched", "mean"))
        .sort_values("miles", ascending=False)
        .head(15)
    )
    _zero = match_by_state[(match_by_state["share_miles"] == 0) & (match_by_state["miles"] > 100)].index.tolist()
    mo.vstack(
        [
            mo.md(
                f"""**By state (132 kV+).** Median state match share by miles:
                **{match_by_state["share_miles"].median():.1%}**. States with over 100 miles of 132 kV+ line and no
                match at all: {", ".join(_zero) or "none"}. Full table in `output/match_by_state_132kv.csv`."""
            ),
            mo.ui.table(match_by_state.round(3), selection=None, page_size=10),
            mo.md(
                "**Biggest investor-owned owners (132 kV+)**, to check the owner-type rule; share is by segment count."
            ),
            mo.ui.table(_top_owners.round(3), selection=None),
        ]
    )
    return (match_by_state,)


@app.cell
def _(joined):
    _hv = joined[joined["hv"]]
    _fig, _ax = plt.subplots(figsize=(10, 6))
    for _label, _mask, _color in [
        ("No Form 1 match", ~_hv["matched"], "#c9c9c9"),
        ("Matched, no cost", _hv["matched"] & ~(_hv["total_cost"] > 0), "#e8a33d"),
        ("Matched with a cost", _hv["total_cost"] > 0, "#1f5fa8"),
    ]:
        _hv[_mask].plot(ax=_ax, color=_color, linewidth=0.4, label=_label)
    _ax.set_xlim(-125, -66)
    _ax.set_ylim(24, 50)
    _ax.set_axis_off()
    _ax.legend(loc="lower left", frameon=False)
    _ax.set_title("HIFLD transmission lines at 132 kV and up, by what Form 1 says about them")
    _fig.tight_layout()
    _fig.savefig(OUT / "map_form1_match.png", dpi=150)
    mo.image(src=OUT / "map_form1_match.png")
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 4. How many matched lines carry a cost?

    A match is only useful for cost if Form 1's `total_cost` (land plus construction, at book cost) is filled in. We
    count matched lines with `total_cost` above zero, by tier. Each HIFLD line appears once in LBNL's file, under one
    report year, so we also split by whether that year is 2024 (most rows) or older.
    """)
    return


@app.cell
def _(joined):
    _m = joined[joined["matched"]].copy()
    _m["has_cost"] = _m["total_cost"] > 0
    _m["has_expense"] = _m["total_expenses"] > 0
    _tiers = ["high", "medium", "low"]
    cost_by_tier = pd.DataFrame(
        {
            "Matched lines": _m.groupby("match_tier").size(),
            "With nonzero total cost": _m.groupby("match_tier")["has_cost"].sum(),
            "Share with cost": _m.groupby("match_tier")["has_cost"].mean(),
            "Share with nonzero expenses": _m.groupby("match_tier")["has_expense"].mean(),
        }
    ).loc[_tiers]
    cost_by_tier.loc["all tiers"] = [len(_m), _m["has_cost"].sum(), _m["has_cost"].mean(), _m["has_expense"].mean()]
    cost_by_year = _m.groupby(_m["report_year"] == 2024)["has_cost"].agg(["size", "mean"])
    cost_by_year.index = ["report year before 2024", "report year 2024"]
    cost_by_tier.to_csv(OUT / "cost_by_tier.csv")
    _iou_hv = joined[joined["hv"] & (joined["owner_type"] == "Investor-owned")]
    costed_share = {
        "whole_layer_count": (joined["total_cost"] > 0).mean(),
        "hv_miles": joined.loc[joined["hv"] & (joined["total_cost"] > 0), "miles"].sum()
        / joined.loc[joined["hv"], "miles"].sum(),
        "form1_covered_miles": _iou_hv.loc[_iou_hv["total_cost"] > 0, "miles"].sum() / _iou_hv["miles"].sum(),
        "high_tier_with_cost_hv_miles": joined.loc[
            joined["hv"] & (joined["total_cost"] > 0) & (joined["match_tier"] == "high"), "miles"
        ].sum()
        / joined.loc[joined["hv"], "miles"].sum(),
    }
    mo.vstack(
        [
            mo.ui.table(cost_by_tier.round(3), selection=None),
            mo.ui.table(cost_by_year.round(3), selection=None),
            mo.md(
                f"""Only **{costed_share["hv_miles"]:.1%}** of HIFLD's 132 kV+ miles end up with a Form 1 cost
                (**{costed_share["form1_covered_miles"]:.1%}** of the Form 1-covered miles, and
                **{costed_share["high_tier_with_cost_hv_miles"]:.1%}** if we keep only high-confidence matches)."""
            ),
        ]
    )
    return cost_by_tier, costed_share


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 5. Are the matches right? A hand check of 20 length outliers

    LBNL published no validation. One cheap warning sign is length: the matched HIFLD segment's length against the
    length the utility reported. We draw 20 matches (fixed seed) where HIFLD is four or more times longer or shorter
    than Form 1, and judge each from the end substation names, owner, voltage and lengths on both sides. The
    verdicts are in `hand_check.csv`, written by hand from `output/hand_check_sample.csv`:

    - **right line**: the HIFLD segment is the Form 1 line or one piece of it (Form 1 reports a line end to end,
      HIFLD often splits it at taps).
    - **wrong line**: the ends, owner or voltage point to a different line.
    - **can't tell**: names too generic (taps, unknowns) to decide.

    We also count a second warning sign across all matches: the HIFLD owner names a different utility from the Form
    1 respondent.
    """)
    return


@app.cell
def _(joined):
    _m = joined[joined["matched"]].copy()
    _m["length_ratio"] = _m["total_length"] / _m["total_length_ferc"]
    _outlier = (_m["length_ratio"] >= 4) | (_m["length_ratio"] <= 0.25)
    _cols = [
        "source_ID", "match_tier", "report_year", "respondent_legal_name_ferc", "OWNER", "substation_from_ferc",
        "substation_to_ferc", "SUB_1", "SUB_2", "operating_voltage_ferc", "VOLTAGE", "total_length_ferc",
        "total_length", "length_ratio", "number_of_circuits", "state",
    ]  # fmt: skip
    hand_sample = _m[_outlier].sample(20, random_state=297)[_cols]
    hand_sample.to_csv(OUT / "hand_check_sample.csv", index=False)
    _verdicts = pd.read_csv(HERE / "hand_check.csv", dtype={"source_ID": str})
    assert set(_verdicts["source_ID"]) == set(hand_sample["source_ID"]), "hand_check.csv is for a different sample"
    hand_counts = _verdicts["verdict"].value_counts()
    _wrong_share = hand_counts.get("wrong line", 0) / len(_verdicts)

    _named = _m[_m["OWNER"] != "NOT AVAILABLE"]
    _norm = _named["OWNER"].str.upper().str.replace(r"[^A-Z ]", " ", regex=True)
    _first_word = _named["respondent_legal_name_ferc"].str.upper().str.split().str[0]
    owner_disagree = float((~pd.Series([_w in _o for _w, _o in zip(_first_word, _norm, strict=True)])).mean())
    quality = {
        "outlier_share": float(_outlier.mean()),
        "outliers": int(_outlier.sum()),
        "hand_wrong_share": float(_wrong_share),
        "est_wrong_matches_from_outliers": float(_wrong_share * _outlier.sum()),
        "owner_disagree_share": owner_disagree,
    }
    mo.vstack(
        [
            mo.md(
                f"""**{quality["outliers"]:,}** matches (**{quality["outlier_share"]:.1%}**) are length outliers.
                Hand check: {", ".join(f"{_v}: {_n}" for _v, _n in hand_counts.items())}. Scaled up, that's about
                **{quality["est_wrong_matches_from_outliers"]:,.0f}** wrong matches among the outliers alone.
                Separately, on matches where HIFLD names an owner, **{owner_disagree:.1%}** name a different utility
                from the Form 1 respondent (first word of the respondent's name not found in the HIFLD owner).
                That's an upper bound: it counts renamed utilities (Progress Energy Carolinas filed as Duke Energy
                Progress, Westar as Evergy) and HIFLD owner errors as well as wrong matches."""
            ),
            mo.ui.table(_verdicts, selection=None),
        ]
    )
    return hand_counts, quality


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 6. Which HIFLD vintage did LBNL use?

    Every LBNL ID is in HIFLD Next (section 3). To see whether they are the same lines, we compare each LBNL row's
    own copy of the HIFLD record with HIFLD Next's: its vertices (LBNL keeps at most 200 per line, so we check that
    every LBNL vertex lies on the HIFLD Next line rather than comparing shapes), its voltage and its length.
    """)
    return


@app.cell
def _(hifld, lbnl):
    _ours = hifld.set_index("source_ID").loc[lbnl["GlobalID"]].to_crs(5070)
    _vertices = gpd.GeoSeries([shapely.MultiPoint(json.loads(_c)) for _c in lbnl["linestring_coord"]], crs=4326).to_crs(
        5070
    )
    _points = _vertices.explode(index_parts=False)
    _off_line = (
        pd.Series(shapely.distance(_points.values, _ours.geometry.values[_points.index]), index=_points.index)
        .groupby(level=0)
        .max()
    )
    _voltage = lbnl["operating_voltage"].values != _ours["VOLTAGE"].values
    vintage = {
        "max_vertices_per_lbnl_line": int(_vertices.map(shapely.get_num_coordinates).max()),
        "vertex_off_line_over_1m": int((_off_line > 1).sum()),
        "voltage_differs": int(_voltage.sum()),
        "voltage_differs_where_next_has_none": int((_voltage & (_ours["VOLTAGE"].values < 0)).sum()),
        "length_differs_over_2pct": int((abs(lbnl["total_length"].values / _ours["miles"].values - 1) > 0.02).sum()),
        "newest_sourcedate_matched": str(_ours["SOURCEDATE"].max())[:10],
        "newest_sourcedate_layer": str(hifld["SOURCEDATE"].max())[:10],
    }
    mo.md(
        f"""
        Of {len(lbnl):,} LBNL lines, **{vintage["vertex_off_line_over_1m"]}** have a vertex more than 1 m off the
        HIFLD Next line, and **{vintage["length_differs_over_2pct"]}** differ in length by more than 2%. LBNL keeps at
        most {vintage["max_vertices_per_lbnl_line"]} vertices per line. **{vintage["voltage_differs"]}** differ in
        voltage, {vintage["voltage_differs_where_next_has_none"]} of them where HIFLD Next has no voltage
        (-999999) and LBNL has one, which looks like LBNL filling it from Form 1. The newest `SOURCEDATE` among matched
        lines is {vintage["newest_sourcedate_matched"]}, the same as the whole layer's
        ({vintage["newest_sourcedate_layer"]}). So LBNL used the same HIFLD release that HIFLD Next preserved, or one
        identical to it for these lines.
        """
    )
    return (vintage,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## 7. Does a blank cost mean "reported elsewhere"?

    FERC's Form 1 instructions for the Transmission Line Statistics schedule (pages 422-423 of the
    [blank form](https://www.ferc.gov/sites/default/files/2020-04/form-1.pdf), edition 12-87) say:

    - Instruction 1: "List each transmission line having nominal voltage of 132 kilovolts or greater. Report
      transmission lines below these voltages in group totals only for each voltage."
    - Instruction 6: "Show in column (f) the pole miles of line on structures the cost of which is reported for the
      line designated; conversely, show in column (g) the pole miles of line on structures the cost of which is
      reported for another line. Report pole miles of line on leased or partly owned structures in column (g)."
    - Instruction 7: "Do not report the same transmission line structure twice."
    - Instruction 10: "Base the plant cost figures called for in columns (j) to (l) on the book cost at end of year."

    So a line can properly show no cost of its own when its structures' cost sits on another line (column g) or
    when it is leased. Nothing in the instructions lets a utility leave a line's cost blank otherwise, and nothing
    says costs are rolled up elsewhere. LBNL's file carries `designed_length` (column f) and `additional_length`
    (column g), so we can test the first explanation: how many costless matched lines have all their miles in column
    (g)?
    """)
    return


@app.cell
def _(joined):
    _m = joined[joined["matched"]]
    _no_cost = _m[~(_m["total_cost"] > 0)]
    _col_g_only = (_no_cost["designed_length"].fillna(0) == 0) & (_no_cost["additional_length"].fillna(0) > 0)
    blank_explained = {"matched_no_cost": len(_no_cost), "column_g_only": int(_col_g_only.sum())}
    mo.md(
        f"""Of **{len(_no_cost):,}** matched lines without a cost, **{blank_explained["column_g_only"]:,}**
        (**{_col_g_only.mean():.1%}**) report all their miles in column (g), which the instructions say means their
        structure cost is reported on another line. The rest have no explanation in the schedule itself; a footnote in
        the original filing might give one, which LBNL's file doesn't carry."""
    )
    return (blank_explained,)


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    **Where the costs went.** LBNL's file holds only line rows, but the schedule also has subtotal and total rows.
    PUDL publishes the whole schedule. For report year 2024 we take, for each Form 1 respondent in LBNL's file, the
    rows with no end substation (the voltage subtotals and system totals) and ask whether any of them carries a
    nonzero cost. Respondents are matched to PUDL's utility names after lower-casing and dropping punctuation and
    suffixes such as "Company".
    """)
    return


@app.cell
def _(joined):
    _sched = pd.read_parquet(DATA / "core_ferc1__yearly_transmission_lines_sched422.parquet")
    _names = pd.read_parquet(DATA / "core_pudl__assn_ferc1_pudl_utilities.parquet")
    _sched = _sched[_sched["report_year"] == 2024].merge(_names, on="utility_id_ferc1", how="left")

    def norm_utility(name: str) -> str:
        name = re.sub(r"[^a-z0-9 ]", " ", str(name).lower())
        return " ".join(
            w for w in name.split() if w not in {"company", "co", "inc", "llc", "corp", "corporation", "the", "and"}
        )

    _sched["respondent"] = _sched["utility_name_ferc1"].map(norm_utility)
    _line_rows = _sched["end_point"].notna()
    _per_line = _sched[_line_rows].groupby("respondent")["capex_total"].apply(lambda c: (c > 0).mean())
    _total_rows = _sched[~_line_rows & (_sched["capex_total"] > 0)].groupby("respondent")["capex_total"].max()

    _m = joined[joined["matched"] & (joined["report_year"] == 2024)].copy()
    _m["respondent"] = _m["respondent_legal_name_ferc"].map(norm_utility)
    _m["in_pudl"] = _m["respondent"].isin(_sched["respondent"])
    _m["has_cost"] = _m["total_cost"] > 0
    _m["respondent_has_total"] = _m["respondent"].isin(_total_rows.index)
    _blank = _m[~_m["has_cost"] & _m["in_pudl"]]
    _resp = _m[_m["in_pudl"]].groupby("respondent").agg(lines=("has_cost", "size"), with_cost=("has_cost", "mean"))
    _resp["total_row_cost"] = _total_rows.reindex(_resp.index)
    _resp["pudl_line_rows_with_cost"] = _per_line.reindex(_resp.index)
    _resp = _resp.sort_values("lines", ascending=False)
    _resp.to_csv(OUT / "respondent_cost_reporting_2024.csv")
    totals_check = {
        "matched_2024": len(_m),
        "matched_2024_respondent_found_in_pudl": int(_m["in_pudl"].sum()),
        "blank_2024_in_pudl": len(_blank),
        "blank_2024_with_respondent_total": int(_blank["respondent_has_total"].sum()),
        "respondents_2024": len(_resp),
        "respondents_no_line_cost_but_total": int(((_resp["with_cost"] == 0) & _resp["total_row_cost"].gt(0)).sum()),
        "respondents_no_cost_anywhere": int(((_resp["with_cost"] == 0) & _resp["total_row_cost"].isna()).sum()),
    }
    mo.vstack(
        [
            mo.md(
                f"""Of {totals_check["matched_2024"]:,} matched lines from report year 2024,
                {totals_check["matched_2024_respondent_found_in_pudl"]:,} have a respondent we found in PUDL.
                Of the **{totals_check["blank_2024_in_pudl"]:,}** of those with no cost, **{
                    totals_check["blank_2024_with_respondent_total"]:,}**
                (**{totals_check["blank_2024_with_respondent_total"] / totals_check["blank_2024_in_pudl"]:.0%}**)
                belong to a utility that reported a nonzero cost on a subtotal or total row. Among
                {totals_check["respondents_2024"]} respondents, **{totals_check["respondents_no_line_cost_but_total"]}**
                gave no line a cost but did give a voltage or system total, and
                **{totals_check["respondents_no_cost_anywhere"]}** reported no cost anywhere on the schedule.
                So most blanks are costs reported in aggregate, which the line map can't use, not costs never
                reported."""
            ),
            mo.ui.table(_resp.head(15).round(3), selection=None),
        ]
    )
    return (totals_check,)


@app.cell
def _(joined):
    _keep = [
        "source_ID", "OWNER", "owner_type", "VOLTAGE", "SUB_1", "SUB_2", "state", "miles", "match_tier",
        "report_year", "respondent_legal_name_ferc", "substation_from_ferc", "substation_to_ferc",
        "operating_voltage_ferc", "number_of_circuits", "total_length_ferc", "cost_of_land",
        "construction_and_other_costs", "total_cost", "total_expenses", "geometry",
    ]  # fmt: skip
    _out = OUT / "hifld_lines_form1.parquet"
    joined[_keep].to_parquet(_out, compression="zstd")
    mo.md(
        f"""
        ## 8. The joined layer

        Every HIFLD Next line with its owner type, state and `match_tier` (`high`, `medium`, `low` or `none`), plus
        the Form 1 fields where matched: `output/hifld_lines_form1.parquet`
        ({_out.stat().st_size / 1e6:.1f} MB, not committed; `./run.sh` rebuilds it). Form 1 fields are from LBNL,
        *A Harmonized Geospatial Dataset of U.S. Transmission Lines*, OEDI submission 8742, CC BY 4.0.
        """
    )
    return


@app.cell
def _(
    blank_explained,
    cost_by_tier,
    costed_share,
    hand_counts,
    match_by_owner,
    match_by_state,
    match_overall,
    missing_from_next,
    quality,
    totals_check,
    vintage,
):
    headline = {
        "match_overall": match_overall.to_dict(orient="index"),
        "match_by_owner_type_132kv": match_by_owner[["share_count", "share_miles", "miles"]].to_dict(orient="index"),
        "median_state_share_miles_132kv": float(match_by_state["share_miles"].median()),
        "cost_by_tier": cost_by_tier.to_dict(orient="index"),
        "costed_share": costed_share,
        "match_quality": quality,
        "hand_check": hand_counts.to_dict(),
        "vintage": vintage | {"lbnl_ids_missing_from_hifld_next": missing_from_next},
        "blank_cost": blank_explained | totals_check,
        "run_seconds": round(time.perf_counter() - RUN_STARTED, 1),
        "cost_usd": 0,
    }
    (OUT / "headline.json").write_text(json.dumps(headline, indent=2, default=float))
    _o = match_overall
    _cov = "Form 1-covered (investor-owned, 132 kV+)"
    mo.md(
        f"""
        ## Result

        - **Match share.** {_o.loc["Whole layer", "share_count"]:.1%} of HIFLD Next line segments
          ({_o.loc["Whole layer", "share_miles"]:.1%} of miles) get a Form 1 match. At 132 kV and up:
          {_o.loc["132 kV and up", "share_count"]:.1%} of segments, {_o.loc["132 kV and up", "share_miles"]:.1%} of
          miles. Against the lines Form 1 is meant to cover: {_o.loc[_cov, "share_count"]:.1%} of segments,
          {_o.loc[_cov, "share_miles"]:.1%} of miles.
        - **Cost.** {cost_by_tier.loc["all tiers", "Share with cost"]:.1%} of matches carry a nonzero cost
          ({cost_by_tier.loc["high", "Share with cost"]:.1%} of high-confidence ones). That leaves
          **{costed_share["hv_miles"]:.1%} of HIFLD's 132 kV+ miles with a public Form 1 cost**.
        - **Why blank.** In 2024, {
            totals_check["blank_2024_with_respondent_total"]
            / totals_check["blank_2024_in_pudl"]:.0%} of costless matches
          belong to a utility that reported its cost only as a voltage or system total.
        - **Quality.** {quality["hand_wrong_share"]:.0%} of the 20 hand-checked length outliers are the wrong line.
        - **Vintage.** No LBNL line is missing from HIFLD Next and {vintage["vertex_off_line_over_1m"]} have moved;
          LBNL used the same HIFLD release.

        Run time {headline["run_seconds"]} s, cost $0.
        """
    )
    return


@app.cell(hide_code=True)
def _():
    mo.md(r"""
    ## What didn't work, and what this doesn't show

    - **No circuit miles.** HIFLD has no circuit count, so shares are in route miles of HIFLD segments. Form 1's
      `number_of_circuits` exists only for matched lines, so it can't weight the denominator.
    - **Owner type is approximate.** Owners missing from the Retail Service Territories layer are typed by keyword
      or counted investor-owned by elimination, and HIFLD's owner field has its own errors (Azusa Light & Power, a
      small city utility, is listed on 779 segments). Segments with no owner (`NOT AVAILABLE`)
      can't be placed in the Form 1-covered subset at all, though LBNL matched many of them.
    - **One match per HIFLD segment, one segment per Form 1 line.** Form 1 reports a line end to end; HIFLD splits
      lines at taps. LBNL ties each Form 1 record to a single HIFLD segment, so the rest of a long line counts as
      unmatched here and the cost belongs to the whole line, not the segment.
    - **The hand check is 20 lines from the outliers only**, judged from names and lengths without imagery. It bounds
      the error among outliers; it says little about the matches that look normal.
    """)
    return


if __name__ == "__main__":
    app.run()

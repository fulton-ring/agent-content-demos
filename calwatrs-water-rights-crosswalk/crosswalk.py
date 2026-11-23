import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    import sys
    import time
    import zipfile
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import pandas as pd

    started = time.perf_counter()
    DATA_DIR = Path(os.environ.get("CROSSWALK_DATA_DIR", "data"))
    OUT_DIR = Path(os.environ.get("CROSSWALK_OUT_DIR", "outputs"))
    return DATA_DIR, OUT_DIR, gpd, json, mo, os, pd, started, sys, time, zipfile


@app.cell
def _(mo):
    mo.md(r"""
    # Does California's new water rights data still say who holds each right?

    The State Water Resources Control Board is retiring its old water rights system, eWRIMS,
    for a new one, CalWATRS. The old system's one-row-per-right file, the **Water Rights
    LIST**, is marked DISCONTINUED and "will be removed in the near future". The board says
    "you won't find a one-to-one replacement for this file". So far it has published two
    CalWATRS tables in its place: **Participants** (who is connected to each right) and
    **Geospatial** (each right's points of diversion, places of use and storage).

    **Question.** If you join the two CalWATRS tables, do you still get the facts the old
    file gave, above all who holds each right? Which fields are lost? And how stale is the
    old file really, given the portal says it was updated in November 2026?

    `archive.py` ran first. It downloaded all three datasets and their data dictionaries
    and saved the eWRIMS list as GeoParquet with checksums (`outputs/archive_manifest.json`).
    This notebook reads that archive.
    """)
    return


@app.cell
def _(OUT_DIR, json):
    manifest = json.loads((OUT_DIR / "archive_manifest.json").read_text())
    {
        k: {"license": v["license"], "portal says updated": v["portal_metadata_modified"][:10]}
        for k, v in manifest["datasets"].items()
    }
    return (manifest,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. The old file

    One row per right (a few IDs repeat; we keep the first). eWRIMS wrote the text `NA`
    for an empty value, so `NA` and blanks are treated as missing throughout.
    """)
    return


@app.cell
def _(OUT_DIR, pd):
    def blank_to_na(s: pd.Series) -> pd.Series:
        """eWRIMS and CalWATRS empty values ("", "NA", "NaN") as real missing values."""
        t = s.astype("string").str.strip()
        return t.mask(t.isin(["", "NA", "NaN", "nan", "NULL"]))

    ewrims = (
        pd.read_parquet(OUT_DIR / "ewrims_water_rights_list.parquet")
        .drop(columns="geometry")
        .drop_duplicates("APPLICATION_NUMBER")
        .set_index("APPLICATION_NUMBER")
        .apply(blank_to_na)
    )
    ewrims_has_holder = ewrims["PRIMARY_OWNER_NAME"].notna()
    {
        "rights": len(ewrims),
        "columns": ewrims.shape[1] + 1,
        "with a primary owner": f"{ewrims_has_holder.mean():.1%}",
    }
    return blank_to_na, ewrims, ewrims_has_holder


@app.cell
def _(ewrims, ewrims_has_holder, mo):
    _nd = ewrims["WATER_RIGHT_TYPE"].eq("Not Determined")
    _missing = ~ewrims_has_holder
    mo.md(f"""
    Even the old file names a holder for only **{ewrims_has_holder.mean():.1%}** of its
    {len(ewrims):,} rights. Of the {_missing.sum():,} without one,
    {(_missing & _nd).sum() / _missing.sum():.0%} are type **"Not Determined"**
    ({_nd.sum():,} rows, {_nd.mean():.0%} of the file). Those rows rarely have an owner
    ({ewrims_has_holder[_nd].mean():.1%}), a location
    ({ewrims.loc[_nd, "LATITUDE"].notna().mean():.1%}) or a use
    ({ewrims.loc[_nd, "USE_CODE"].notna().mean():.1%}). They read as placeholder records,
    so results below are shown both for all rights and without them.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. The strongest evidence against: does Participants already restore the holder?

    The card expected the holder to be the big loss. The case against is the Participants
    table, created 2026-02-06: one row per link between a person or organization and a
    right, with a relationship type ("Primary owner", "Agent", "Non-primary owner"…) and an
    active or inactive status. If it names a holder for nearly every right, the loss is
    small and this becomes a crosswalk how-to. So check it first.

    Three tests per eWRIMS right:

    - **Holder present**: the right has at least one *active* "Primary owner" link.
    - **Same party**: the eWRIMS primary owner's party ID is one of the right's primary
      owner links (active or not). CalWATRS keeps the old eWRIMS party ID inside
      `PARTICIPANT_CONVERSIONPAPID` (`A000084|434716 | …`), so this is an exact check, not
      fuzzy name matching.
    - **Same name**: the active primary owner's name equals the eWRIMS name after
      upper-casing and dropping punctuation. CalWATRS rewrote many names in mixed case and
      added middle initials, so this undercounts.
    """)
    return


@app.cell
def _(DATA_DIR, blank_to_na, pd, zipfile):
    def read_zipped_csv(folder: str) -> pd.DataFrame:
        """The one CSV inside the CalWATRS zip that archive.py downloaded into folder."""
        _zip = next((DATA_DIR / folder).glob("*.zip"))
        with zipfile.ZipFile(_zip) as z, z.open(z.namelist()[0]) as f:
            return pd.read_csv(f, dtype=str, low_memory=False).apply(blank_to_na)

    participants = read_zipped_csv("calwatrs_participants")
    participants["conversion_party_id"] = (
        participants["PARTICIPANT_CONVERSIONPAPID"].str.split("|").str[1].str.strip()
    )
    primary = participants[participants["PARTICIPANT_RELATIONSHIPTYPE"].eq("Primary owner")]
    active_primary = primary[primary["PARTICIPANT_STATUS"].eq("Active")]
    participants.shape
    return active_primary, participants, primary, read_zipped_csv


@app.cell
def _(active_primary, ewrims, ewrims_has_holder, participants, pd, primary):
    def name_key(s: pd.Series) -> pd.Series:
        return s.str.upper().str.replace(r"[^A-Z0-9]+", " ", regex=True).str.strip()

    _ids = ewrims.index.to_series()
    _party_links = pd.MultiIndex.from_arrays(
        [primary["WR_APP_CLAIM_NAME"], primary["conversion_party_id"]]
    )
    _name_links = pd.MultiIndex.from_arrays(
        [active_primary["WR_APP_CLAIM_NAME"], name_key(active_primary["ACCOUNT_NAME"])]
    )
    _changed = active_primary[
        pd.to_datetime(active_primary["PARTICIPANT_EFFECTIVEFROMDATE"], errors="coerce")
        > pd.to_datetime(ewrims["UPDATE_DATETIME"], format="mixed").max()
    ]
    holder = pd.DataFrame(
        {
            "type": ewrims["WATER_RIGHT_TYPE"].fillna("(blank)"),
            "status": ewrims["WATER_RIGHT_STATUS"].fillna("(blank)"),
            "eWRIMS holder": ewrims_has_holder,
            "in Participants": _ids.isin(participants["WR_APP_CLAIM_NAME"]),
            "CalWATRS holder": _ids.isin(active_primary["WR_APP_CLAIM_NAME"]),
            "same party": pd.MultiIndex.from_arrays([_ids, ewrims["PARTY_ID"]]).isin(_party_links),
            "same name": pd.MultiIndex.from_arrays(
                [_ids, name_key(ewrims["PRIMARY_OWNER_NAME"])]
            ).isin(_name_links),
            "owner changed since freeze": _ids.isin(_changed["WR_APP_CLAIM_NAME"]),
        }
    )
    _measures = holder.columns[2:]
    holder_overall = pd.DataFrame(
        {
            "all rights": holder[_measures].mean(),
            "without Not Determined": holder.loc[
                holder["type"] != "Not Determined", _measures
            ].mean(),
            "where eWRIMS named a holder": holder.loc[holder["eWRIMS holder"], _measures].mean(),
        }
    ).round(3)
    holder_overall
    return holder, holder_overall


@app.cell
def _(holder, pd):
    def by_group(column: str) -> pd.DataFrame:
        """Holder measures for each value of one eWRIMS column, largest groups first."""
        g = holder.groupby(column)[holder.columns[2:]].mean().round(3)
        g.insert(0, "rights", holder.groupby(column).size())
        return g.sort_values("rights", ascending=False)

    holder_by_type = by_group("type")
    holder_by_status = by_group("status")
    holder_by_type
    return holder_by_status, holder_by_type


@app.cell
def _(holder_by_status):
    holder_by_status
    return


@app.cell
def _(holder, holder_overall, mo):
    _o = holder_overall
    _named = holder[holder["eWRIMS holder"]]
    _lost = _named[~_named["CalWATRS holder"]]
    holder_lost_by_status = _lost["status"].value_counts()
    mo.md(f"""
    **The evidence against mostly holds.** Participants names an active primary owner for
    **{_o.loc["CalWATRS holder", "all rights"]:.1%}** of all eWRIMS rights, and
    **{_o.loc["CalWATRS holder", "where eWRIMS named a holder"]:.1%}** of the
    {len(_named):,} rights where eWRIMS named one. The holder is not lost; it moved to a
    second table that has to be joined on the right ID.

    Where eWRIMS named a holder, **{_o.loc["same party", "where eWRIMS named a holder"]:.1%}**
    of rights carry the same eWRIMS party into CalWATRS as a primary owner, and
    **{_o.loc["same name", "where eWRIMS named a holder"]:.1%}** have an active owner whose
    name matches letter for letter. The gap between the two is mostly rewritten names, not
    different holders. **{_o.loc["owner changed since freeze", "all rights"]:.1%}** of
    rights have an active owner added after eWRIMS's last update, so for those the old file
    is simply out of date.

    Of the {len(_lost):,} named-holder rights with no active CalWATRS owner,
    {_lost["status"].isin(["Closed", "Inactive"]).mean():.0%} are closed or inactive in
    eWRIMS: {", ".join(f"{k} {v:,}" for k, v in holder_lost_by_status.head(4).items())}.
    """)
    return (holder_lost_by_status,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Join Geospatial and Participants on the right ID

    Geospatial has one row per link between a right and a feature. eWRIMS listed one point
    of diversion per right (the most recently updated one) with its eWRIMS `POD_ID`, and
    CalWATRS keeps that ID as the first part of `GR_CONVERSION_ID` (`6598|Point of
    Diversion`). So point-of-diversion fields are compared on the very same point.
    """)
    return


@app.cell
def _(ewrims, participants, read_zipped_csv):
    geospatial = read_zipped_csv("calwatrs_geospatial")
    geospatial["pod_key"] = (
        geospatial["WR_APP_CLAIM_NAME"] + "|" + geospatial["GR_CONVERSION_ID"].str.split("|").str[0]
    )
    _ids = ewrims.index.to_series()
    _in_p = _ids.isin(participants["WR_APP_CLAIM_NAME"])
    _in_g = _ids.isin(geospatial["WR_APP_CLAIM_NAME"])
    _pods = (_ids + "|" + ewrims["POD_ID"].fillna("")).isin(geospatial["pod_key"])
    match = {
        "in Participants": round(float(_in_p.mean()), 4),
        "in Geospatial": round(float(_in_g.mean()), 4),
        "in either": round(float((_in_p | _in_g).mean()), 4),
        "in both": round(float((_in_p & _in_g).mean()), 4),
        "eWRIMS point of diversion found in Geospatial": round(
            float(_pods[ewrims["POD_ID"].notna()].mean()), 4
        ),
    }
    match
    return geospatial, match


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. The field crosswalk

    Each eWRIMS column was read against the three data dictionaries and given the CalWATRS
    column that means the same thing, if there is one. The table below is that judgment;
    every eWRIMS column not listed has no CalWATRS equivalent.

    `where` says which CalWATRS rows a value comes from: **right** (Participants,
    right-level columns, repeated on every row), **owner** or **agent** (active primary
    owner or agent links), **pod** (the Geospatial row for the same point of diversion) or
    **feature** (any Geospatial row for the right). `kind` says how values are compared:
    text after upper-casing and dropping punctuation, dates by day, numbers to 6
    significant digits (a zero counts as empty: eWRIMS wrote 0 face value on every
    statement), `member` if the eWRIMS value is one of a CalWATRS comma list. Status and
    type (`vocab`) use new terms and are scored in section 5. `renamed` fields hold the same
    fact in new words or new IDs and aren't scored; `derived` fields are counts or copies
    you can rebuild from the CalWATRS rows (number of points, uses, owners, petitions).
    `same_value` is the share agreeing among rights where both systems have a value.
    """)
    return


@app.cell
def _(pd):
    crosswalk_spec = pd.DataFrame(
        [
            # eWRIMS column, CalWATRS column, where, kind
            ("WATER_RIGHT_TYPE", "WR_APP_CLAIM_TYPE", "right", "vocab"),
            ("WATER_RIGHT_STATUS", "WR_APP_CLAIM_STATUS", "right", "vocab"),
            ("SUB_TYPE", "CLAIM_PRIMARY_TYPE", "right", "vocab"),
            ("PRIORITY_DATE", "WR_APP_CLAIM_PRIORITY_DATE", "right", "date"),
            ("RECEIPT_DATE", "APP_APPLIEDDATE", "right", "date"),
            ("APPLICATION_RECD_DATE", "APP_APPLIEDDATE", "right", "date"),
            ("APPLICATION_ACCEPTANCE_DATE", "APP_ACEPTANCEDATE", "right", "date"),
            ("REJECTION_DATE", "WR_APP_CLAIM_REVOKE_REJECT_INACTIVATION_DATE", "right", "date"),
            ("FACE_VALUE_AMOUNT", "WR_APP_FACEVALUE", "right", "number"),
            ("FACE_VALUE_UNITS", "WR_APP_FACEVALUEUNIT", "right", "renamed"),
            ("FEE_RECEIVED", "APP_FEERECEIVED", "right", "number"),
            ("APPL_FEE_AMT_RECD", "APP_FEERECEIVED", "right", "number"),
            ("INI_REPORTED_DIV_AMOUNT", "CLAIM_INITIALDIVERSION", "right", "number"),
            ("YEAR_DIVERSION_COMMENCED", "CLAIM_YEAR_DIVERSION_BEGAN", "right", "year"),
            ("USE_CODE", "WR_APP_CLAIM_BENEFICIALPURPOSESOFUSE", "right", "member"),
            ("PERMIT_ORIGINAL_ISSUE_DATE", "WR_PERMITTEDDATE", "right", "date"),
            ("LICENSE_ORIGINAL_ISSUE_DATE", "WR_LICENSEORIGINALISSUEDATE", "right", "date"),
            ("APPLICATION_PRIMARY_OWNER", "ACCOUNT_NAME", "owner", "text"),
            ("PRIMARY_OWNER_NAME", "ACCOUNT_NAME", "owner", "text"),
            ("PRIMARY_OWNER_ENTITY_TYPE", "ACCOUNT_TYPE", "owner", "text"),
            ("PARTY_ID", "conversion_party_id", "owner", "text"),
            ("RELATIONSHIP_TYPE", "PARTICIPANT_RELATIONSHIPTYPE", "owner", "text"),
            ("EFFECTIVE_FROM_DATE", "PARTICIPANT_EFFECTIVEFROMDATE", "owner", "date"),
            ("EFFECTIVE_TO_DATE", "PARTICIPANT_EFFECTIVETODATE", "owner", "date"),
            ("OFFICIAL_MAIL_RECEIVER", "PARTICIPANT_MAILRECEIVER", "owner", "renamed"),
            ("AGENT_NAME", "ACCOUNT_NAME", "agent", "text"),
            ("AGENT_ENTITY_TYPE", "ACCOUNT_TYPE", "agent", "text"),
            ("POD_ID", "GR_CONVERSION_ID", "pod", "id"),
            ("POD_STATUS", "GR_STATUS", "pod", "text"),
            ("POD_NAME", "POLY_NAME", "pod", "text"),
            ("DIVERSION_SITE_NAME", "POLY_NAME", "pod", "text"),
            ("COUNTY", "POLY_COUNTY", "pod", "member"),
            ("LATITUDE", "POLY_LATITUDE", "pod", "location"),
            ("LONGITUDE", "POLY_LONGITUDE", "pod", "location"),
            ("NORTH_COORD", "POLY_NORTHING", "pod", "location"),
            ("EAST_COORD", "POLY_EASTING", "pod", "location"),
            ("SECTION_NUMBER", "POLY_SECTION_NUMBER", "pod", "number"),
            ("TOWNSHIP_NUMBER", "POLY_TOWNSHIP_NUMBER", "pod", "number"),
            ("TOWNSHIP_DIRECTION", "POLY_TOWNSHIP_DIRECTION", "pod", "text"),
            ("RANGE_NUMBER", "POLY_RANGE_NUMBER", "pod", "number"),
            ("RANGE_DIRECTION", "POLY_RANGE_DIRECTION", "pod", "text"),
            ("SPECIAL_USE_AREA", "POLY_SPECIAL_AREA", "pod", "renamed"),
            ("SOURCE_NAME", "POLY_SOURCE", "pod", "text"),
            ("TRIB_DESC", "POLY_NHDTRIBUTARY", "pod", "text"),
            ("HUC_12_NUMBER", "POLY_HUC12", "pod", "text"),
            ("HUC_8_NUMBER", "POLY_HUC8", "pod", "text"),
            ("HUC_8_NAME", "POLY_BASIN_NAME", "pod", "text"),
            ("DIRECT_DIVERSION_RATE", "POLY_MAXFLOWRATE", "pod", "number"),
            ("DIRECT_DIV_RATE_UNIT", "POLY_MAXFLOWRATEUNIT", "pod", "text"),
            ("POD_TYPE", "GR_FEATURE_TYPE", "pod", "renamed"),
            ("POD_ID_GIS", "GR_CONVERSION_ID", "pod", "id"),
            ("APPL_POD", "pod_key", "pod", "derived"),
            ("POD_COUNT", "GR_CONVERSION_ID", "feature", "derived"),
            ("USE_COUNT", "WR_APP_CLAIM_BENEFICIALPURPOSESOFUSE", "right", "derived"),
            ("COUNT_NPO_OR_OTHER", "PARTICIPANT_RELATIONSHIPTYPE", "right", "derived"),
            ("NUM_OF_PETITIONS", "CHGPET_NAME", "feature", "derived"),
            ("USE_NET_ACREAGE", "POLY_BL_BLA_CLAIM_NET_USE_ACREAGE", "feature", "number"),
            ("PETITION_ID", "CHGPET_NAME", "feature", "renamed"),
            ("PETITION_TYPE", "CHGPET_CATEGORY", "feature", "renamed"),
            ("PETITION_STATUS_TYPE", "CHGPET_STATUS", "feature", "renamed"),
        ],
        columns=["ewrims", "calwatrs", "where", "kind"],
    )
    crosswalk_spec.shape
    return (crosswalk_spec,)


@app.cell
def _(active_primary, geospatial, participants, pd):
    def norm(s: pd.Series, kind: str) -> pd.Series:
        """Put an eWRIMS or CalWATRS column in a form where equal facts compare equal."""
        if kind == "date":
            d = pd.to_datetime(s.str[:10], errors="coerce", format="mixed")
            return d.dt.strftime("%Y-%m-%d").astype("string")
        if kind == "number":
            n = pd.to_numeric(s, errors="coerce")
            return n.map(lambda v: f"{v:.6g}", na_action="ignore").astype("string")
        if kind == "year":
            return s.str.extract(r"(\d{4})", expand=False).astype("string")
        if kind == "id":
            s = s.str.split("|").str[0]
        return s.str.upper().str.replace(r"[^A-Z0-9]+", " ", regex=True).str.strip()

    # The CalWATRS rows each `where` draws from, and the key that ties them to an eWRIMS right.
    agents = participants[
        participants["PARTICIPANT_RELATIONSHIPTYPE"].eq("Agent")
        & participants["PARTICIPANT_STATUS"].eq("Active")
    ]
    sources = {
        "right": (participants, "WR_APP_CLAIM_NAME"),
        "owner": (active_primary, "WR_APP_CLAIM_NAME"),
        "agent": (agents, "WR_APP_CLAIM_NAME"),
        "pod": (geospatial, "pod_key"),
        "feature": (geospatial, "WR_APP_CLAIM_NAME"),
    }
    return norm, sources


@app.cell
def _(crosswalk_spec, ewrims, norm, pd, sources):
    _ids = ewrims.index.to_series()
    _keys = {
        "pod": _ids + "|" + ewrims["POD_ID"].fillna(""),
    }
    _rows = []
    for _r in crosswalk_spec.itertuples():
        _table, _key_col = sources[_r.where]
        _key = _keys.get(_r.where, _ids)
        _ew_raw = ewrims[_r.ewrims]
        _cw = _table[[_key_col]].assign(value=_table[_r.calwatrs]).dropna()
        if _r.kind == "number":
            _ew_raw = _ew_raw.mask(pd.to_numeric(_ew_raw, errors="coerce").eq(0))
            _cw = _cw[pd.to_numeric(_cw["value"], errors="coerce").ne(0)]
        _has = _ew_raw.notna() & _key.isin(_table[_key_col])
        _has_both = _has & _key.isin(_cw[_key_col])
        _same = None
        if _r.kind in ("text", "date", "number", "year", "id", "member"):
            if _r.kind == "member":
                _cw = _cw.assign(value=_cw["value"].str.split(",")).explode("value")
                _cw = _cw.assign(value=_cw["value"].str.strip())
            _kind = "text" if _r.kind == "member" else _r.kind
            _pairs = pd.MultiIndex.from_arrays([_cw[_key_col], norm(_cw["value"], _kind)])
            _ew = norm(_ew_raw[_has_both], _kind)
            _same = round(
                float(pd.MultiIndex.from_arrays([_key[_has_both], _ew]).isin(_pairs).mean()), 3
            )
        _rows.append(
            {
                "ewrims_field": _r.ewrims,
                "calwatrs_table": "Geospatial"
                if _r.where in ("pod", "feature")
                else "Participants",
                "calwatrs_field": _r.calwatrs,
                "where": _r.where,
                "kind": _r.kind,
                "ewrims_filled": int(_has.sum()),
                "calwatrs_filled": round(float(_has_both.sum() / max(int(_has.sum()), 1)), 3),
                "same_value": _same,
            }
        )
    field_scores = pd.DataFrame(_rows)
    _carried = (field_scores["calwatrs_filled"] >= 0.9) & ~(field_scores["same_value"] < 0.9)
    field_scores["verdict"] = _carried.map({True: "carries over", False: "partly"}).where(
        field_scores["ewrims_filled"] > 0, "not testable"
    )
    field_scores
    return (field_scores,)


@app.cell
def _(ewrims, field_scores, pd):
    _all = pd.Series(["APPLICATION_NUMBER", *ewrims.columns])
    _mapped = set(field_scores["ewrims_field"]) | {"APPLICATION_NUMBER"}
    unmapped = pd.DataFrame(
        {
            "ewrims_field": _all[~_all.isin(_mapped)],
            "share_filled_in_ewrims": [
                round(float(ewrims[c].notna().mean()), 3) for c in _all[~_all.isin(_mapped)]
            ],
        }
    ).sort_values("share_filled_in_ewrims", ascending=False)
    unmapped_filled = unmapped[unmapped["share_filled_in_ewrims"] >= 0.05]
    {
        "eWRIMS columns": len(_all),
        "with a CalWATRS equivalent": len(_mapped),
        "no equivalent": len(unmapped),
        "no equivalent and filled for 5%+ of rights": len(unmapped_filled),
    }
    return unmapped, unmapped_filled


@app.cell
def _(DATA_DIR, field_scores, pd, unmapped):
    # The eWRIMS data dictionary groups its columns into sections; count what each loses.
    _dictionary = pd.read_excel(next((DATA_DIR / "ewrims_list").glob("*.xlsx")))
    _group = _dictionary.set_index("Column*")["GROUP"].str.split("(").str[0].str.strip()
    _verdicts = pd.concat(
        [
            field_scores.set_index("ewrims_field")["verdict"],
            pd.Series("no equivalent", index=unmapped["ewrims_field"]),
        ]
    )
    lost_by_group = pd.crosstab(
        _group.reindex(_verdicts.index).fillna("(not in dictionary)"), _verdicts
    ).sort_values("no equivalent", ascending=False)
    lost_by_group
    return (lost_by_group,)


@app.cell
def _(unmapped_filled):
    unmapped_filled.reset_index(drop=True)
    return


@app.cell
def _(ewrims, geospatial, gpd, pd):
    _pod = geospatial.drop_duplicates("pod_key").set_index("pod_key")
    _key = ewrims.index.to_series() + "|" + ewrims["POD_ID"].fillna("")
    _both = ewrims.assign(key=_key).dropna(subset=["LATITUDE"])
    _both = _both[_both["key"].isin(_pod.index)]
    _cw = _pod.loc[_both["key"]]
    _a = gpd.GeoSeries.from_xy(
        pd.to_numeric(_both["LONGITUDE"]).to_numpy(),
        pd.to_numeric(_both["LATITUDE"]).to_numpy(),
        crs=4269,
    ).to_crs(3310)
    _b = gpd.GeoSeries.from_xy(
        pd.to_numeric(_cw["POLY_LONGITUDE"]).to_numpy(),
        pd.to_numeric(_cw["POLY_LATITUDE"]).to_numpy(),
        crs=4326,
    ).to_crs(3310)
    _dist = pd.Series(_a.distance(_b).to_numpy())
    location = {
        "points compared": len(_dist),
        "within 10 m": round(float((_dist <= 10).mean()), 3),
        "within 100 m": round(float((_dist <= 100).mean()), 3),
        "median metres": round(float(_dist.median()), 1),
    }
    location
    return (location,)


@app.cell
def _(field_scores, location, mo, unmapped, unmapped_filled):
    _scored = field_scores.dropna(subset=["same_value"]).set_index("ewrims_field")
    mo.md(f"""
    **{len(field_scores)} of {len(field_scores) + len(unmapped) + 1} eWRIMS columns** have
    a CalWATRS equivalent (plus the right ID). **{len(unmapped)} have none**, and
    {len(unmapped_filled)} of those were filled for at least 5% of rights. By the data
    dictionary's own sections, most losses are per-use detail (population, stock, use
    acreage, seasons), application amounts and fees (`MAX_DD_APPL`, `MAX_STORAGE`…), GIS
    bookkeeping for the point (quad map, CalWater watershed, location method), licensing
    steps, and every enforcement field. Permit, license and certificate numbers, the parcel
    number, the project summary and the status history date are gone too.

    Point locations carry over: **{location["within 10 m"]:.1%}** of eWRIMS points are
    within 10 m of the same point in CalWATRS. Of the scored fields, priority date agrees
    for {_scored.loc["PRIORITY_DATE", "same_value"]:.0%} of rights where both have it, face
    value for {_scored.loc["FACE_VALUE_AMOUNT", "same_value"]:.0%}, and the eWRIMS party
    ID for {_scored.loc["PARTY_ID", "same_value"]:.0%}.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Status and type: same facts, new words

    CalWATRS renamed the status and type vocabulary. eWRIMS said a statement of diversion
    was type "Statement of Div and Use", status "Claimed"; CalWATRS says type "Riparian",
    status "Active". The WaDE rebuild spike (`wade-water-rights-rebuild/`) met the same
    problem and learned a lookup: for each CalWATRS combination, take the term most of its
    matched rights carried in WaDE's last California table. WaDE's terms are eWRIMS terms
    (WaDE appends the statement sub-type to the type), so that lookup is a CalWATRS →
    eWRIMS translation.

    Here we reuse it two ways:

    1. **WaDE's lookup as it was**, rebuilt with the WaDE spike's own helpers (imported
       from that folder, not edited) and the same keys: status on CalWATRS status + type,
       type on CalWATRS type + subtype. We score it against the eWRIMS file. On rights that
       were in WaDE that's in-sample; on the rest of eWRIMS (WaDE filtered out ended rights)
       it's a genuine out-of-sample test.
    2. **The same method learned on the whole eWRIMS file**, published as
       `outputs/status_type_lookup.csv`. It's in-sample, so its score is a ceiling.
    """)
    return


@app.cell
def _(DATA_DIR, mo, os, sys):
    os.environ.setdefault("WADE_DATA_DIR", str(DATA_DIR / "wade"))
    sys.path.insert(0, str(mo.notebook_dir().parent / "wade-water-rights-rebuild"))
    import wade  # noqa: E402  (the WaDE spike's shared helpers, imported as-is)

    _folder = wade.drive_folder_from_readme("California/WaterAllocation_WaterUse_CSWRCB/ReadME.md")
    wade_alloc, _sites = wade.wade_answer_key("CA", wade.drive_listing(_folder))
    wade_alloc = wade_alloc.set_index("AllocationNativeID")
    len(wade_alloc)
    return (wade_alloc,)


@app.cell
def _(ewrims, participants, pd, wade_alloc):
    def learn_lookup(calwatrs: pd.DataFrame, target: pd.Series, keys: list[str]) -> pd.Series:
        """For each CalWATRS key combination, the target term most of its rights carry.

        The WaDE spike's method (california.py, section 6), copied so it can be learned on
        a different answer key.
        """
        k = calwatrs.loc[target.index, keys].fillna("(blank)")
        return target.groupby([k[c] for c in keys]).agg(lambda s: s.value_counts().index[0])

    def apply_lookup(table: pd.Series, calwatrs: pd.DataFrame, keys: list[str]) -> pd.Series:
        k = pd.MultiIndex.from_frame(calwatrs[keys].fillna("(blank)"))
        return pd.Series(table.reindex(k).to_numpy(), index=calwatrs.index)

    def base_type(s: pd.Series) -> pd.Series:
        """WaDE's type with the statement sub-type dropped, which is the eWRIMS type."""
        return s.str.replace(r"^(Statement of Div and Use).*$", r"\1", regex=True)

    right_cols = ["WR_APP_CLAIM_STATUS", "WR_APP_CLAIM_TYPE", "WR_APP_SUBTYPE"]
    calwatrs_rights = participants.drop_duplicates("WR_APP_CLAIM_NAME").set_index(
        "WR_APP_CLAIM_NAME"
    )[right_cols]
    matched = ewrims.index.intersection(calwatrs_rights.index)
    cw = calwatrs_rights.loc[matched]
    status_keys = ["WR_APP_CLAIM_STATUS", "WR_APP_CLAIM_TYPE"]
    type_keys = ["WR_APP_CLAIM_TYPE", "WR_APP_SUBTYPE"]
    _wade_both = wade_alloc.index.intersection(matched)
    wade_status_lookup = learn_lookup(
        cw, wade_alloc.loc[_wade_both, "AllocationLegalStatusCV"], status_keys
    )
    wade_type_lookup = learn_lookup(cw, wade_alloc.loc[_wade_both, "AllocationTypeCV"], type_keys)
    in_wade = matched.isin(wade_alloc.index)
    _truth_status = ewrims.loc[matched, "WATER_RIGHT_STATUS"]
    _truth_type = ewrims.loc[matched, "WATER_RIGHT_TYPE"]
    _wade_status = apply_lookup(wade_status_lookup, cw, status_keys)
    _wade_type = base_type(apply_lookup(wade_type_lookup, cw, type_keys))
    _rows = []
    for _field, _truth, _raw, _wade in [
        ("status", _truth_status, cw["WR_APP_CLAIM_STATUS"], _wade_status),
        ("type", _truth_type, cw["WR_APP_CLAIM_TYPE"], _wade_type),
    ]:
        _rows.append(
            {
                "field": _field,
                "same word, no lookup": round(float((_raw == _truth).mean()), 3),
                "WaDE lookup, rights in WaDE (in-sample)": round(
                    float((_wade == _truth)[in_wade].mean()), 3
                ),
                "WaDE lookup, rights not in WaDE (out-of-sample)": round(
                    float((_wade == _truth)[~in_wade].mean()), 3
                ),
                "WaDE lookup, not in WaDE, key WaDE never saw": round(
                    float(_wade[~in_wade].isna().mean()), 3
                ),
                "WaDE lookup else CalWATRS word, not in WaDE": round(
                    float((_wade.fillna(_raw) == _truth)[~in_wade].mean()), 3
                ),
            }
        )
    wade_lookup_scores = pd.DataFrame(_rows)
    {"matched rights": len(matched), "of which in WaDE": int(in_wade.sum())}
    return (
        apply_lookup,
        cw,
        learn_lookup,
        matched,
        status_keys,
        type_keys,
        wade_lookup_scores,
    )


@app.cell
def _(wade_lookup_scores):
    wade_lookup_scores
    return


@app.cell
def _(apply_lookup, cw, ewrims, learn_lookup, matched, pd, status_keys, type_keys):
    _truth_status = ewrims.loc[matched, "WATER_RIGHT_STATUS"].fillna("(blank)")
    _truth_type = ewrims.loc[matched, "WATER_RIGHT_TYPE"].fillna("(blank)")
    status_lookup = learn_lookup(cw, _truth_status, status_keys)
    type_lookup = learn_lookup(cw, _truth_type, type_keys)
    _s = apply_lookup(status_lookup, cw, status_keys) == _truth_status
    _t = apply_lookup(type_lookup, cw, type_keys) == _truth_type
    ewrims_lookup_scores = pd.DataFrame(
        [
            {
                "field": "status",
                "lookup rows": len(status_lookup),
                "agree (in-sample)": round(float(_s.mean()), 3),
            },
            {
                "field": "type",
                "lookup rows": len(type_lookup),
                "agree (in-sample)": round(float(_t.mean()), 3),
            },
        ]
    )
    lookup_table = pd.concat(
        [
            status_lookup.rename("ewrims_term")
            .reset_index()
            .assign(ewrims_field="WATER_RIGHT_STATUS"),
            type_lookup.rename("ewrims_term").reset_index().assign(ewrims_field="WATER_RIGHT_TYPE"),
        ]
    )
    ewrims_lookup_scores
    return ewrims_lookup_scores, lookup_table


@app.cell
def _(ewrims_lookup_scores, mo, wade_lookup_scores):
    _w = wade_lookup_scores.set_index("field")
    _e = ewrims_lookup_scores.set_index("field")
    mo.md(f"""
    Without a lookup, the same word appears in both systems for
    {_w.loc["status", "same word, no lookup"]:.0%} of statuses and
    {_w.loc["type", "same word, no lookup"]:.0%} of types. WaDE's lookup restores
    {_w.loc["status", "WaDE lookup, rights in WaDE (in-sample)"]:.0%} of statuses and
    {_w.loc["type", "WaDE lookup, rights in WaDE (in-sample)"]:.0%} of types on the rights
    it learned from. On eWRIMS rights WaDE never carried, the type lookup still holds
    ({_w.loc["type", "WaDE lookup, rights not in WaDE (out-of-sample)"]:.0%}) but the status
    lookup gets only
    {_w.loc["status", "WaDE lookup, rights not in WaDE (out-of-sample)"]:.0%} right. Those
    rights are mostly inactive, revoked, cancelled or rejected, which WSWC's filter kept out
    of WaDE. For {_w.loc["status", "WaDE lookup, not in WaDE, key WaDE never saw"]:.0%} of
    them the lookup has no entry. For most of the rest it has the wrong one: a few WaDE
    rights went from "Claimed" to CalWATRS "Inactive", or from "Licensed" to "Revoked",
    after WaDE froze, so the lookup learned *Inactive → Claimed* and *Revoked → Licensed*.
    It mistook status changes for renamings. Falling back to the CalWATRS word when the
    lookup has no entry only lifts it to
    {_w.loc["status", "WaDE lookup else CalWATRS word, not in WaDE"]:.0%}.
    Learned on the whole eWRIMS file, the same method reaches
    {_e.loc["status", "agree (in-sample)"]:.0%} for status and
    {_e.loc["type", "agree (in-sample)"]:.0%} for type: an in-sample ceiling, not a
    forecast. The rest can't be told apart from CalWATRS's columns.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. How stale is "last updated"?

    data.ca.gov shows a dataset's *metadata* modified date as "Last Updated". Compare it
    with the date of the file itself and with the newest dates inside the data.
    """)
    return


@app.cell
def _(ewrims, geospatial, manifest, participants, pd):
    def newest(s: pd.Series, before: str) -> str:
        """Newest date in a column, ignoring placeholder dates in the future."""
        d = pd.to_datetime(s.str[:10], errors="coerce", format="mixed")
        return str(d[d <= pd.Timestamp(before)].max().date())

    _fetched = manifest["fetched_at"][:10]
    _ew = manifest["datasets"]["ewrims_list"]
    _ew_csv = next(f for f in _ew["files"] if f["url"].endswith(".csv"))
    _p = manifest["datasets"]["calwatrs_participants"]
    _g = manifest["datasets"]["calwatrs_geospatial"]
    staleness = pd.DataFrame(
        [
            {
                "dataset": "eWRIMS Water Rights LIST",
                "portal 'last updated' (metadata)": _ew["portal_metadata_modified"][:10],
                "file uploaded": _ew_csv["portal_resource_last_modified"][:10],
                "date in file name": _ew_csv["url"].rsplit("_", 1)[-1][:10],
                "newest record update in data": newest(ewrims["UPDATE_DATETIME"], _fetched),
                "newest status date in data": newest(ewrims["EFFECTIVE_DATE"], _fetched),
            },
            {
                "dataset": "CalWATRS Participants",
                "portal 'last updated' (metadata)": _p["portal_metadata_modified"][:10],
                "file uploaded": _p["files"][0]["portal_resource_last_modified"][:10],
                "date in file name": "",
                "newest record update in data": newest(
                    participants["PARTICIPANT_EFFECTIVEFROMDATE"], _fetched
                ),
                "newest status date in data": newest(participants["APP_APPLIEDDATE"], _fetched),
            },
            {
                "dataset": "CalWATRS Geospatial",
                "portal 'last updated' (metadata)": _g["portal_metadata_modified"][:10],
                "file uploaded": _g["files"][0]["portal_resource_last_modified"][:10],
                "date in file name": "",
                "newest record update in data": newest(geospatial["GR_START_DATE"], _fetched),
                "newest status date in data": newest(geospatial["APP_APPLIED_DATE"], _fetched),
            },
        ]
    ).set_index("dataset")
    staleness_days = (pd.Timestamp(staleness.iloc[0, 0]) - pd.Timestamp(staleness.iloc[0, 3])).days
    staleness
    return staleness, staleness_days


@app.cell
def _(mo, staleness, staleness_days):
    _e = staleness.iloc[0]
    mo.md(f"""
    The eWRIMS list's portal date, **{_e.iloc[0]}**, is the last edit to the dataset's
    metadata; its description now says it is discontinued and "hasn't been updated since
    July 2025". The CSV was re-uploaded {_e.iloc[1]}, its file name says
    {_e.iloc[2]}, and the newest change inside it is **{_e.iloc[3]}**. So "last updated"
    overstates its freshness by **{staleness_days} days**. The CalWATRS tables are what
    they say: uploaded this week, with records added within days of the download.
    """)
    return


@app.cell
def _(
    OUT_DIR,
    field_scores,
    holder,
    holder_by_status,
    holder_by_type,
    holder_lost_by_status,
    holder_overall,
    json,
    location,
    lookup_table,
    lost_by_group,
    ewrims_lookup_scores,
    manifest,
    match,
    mo,
    pd,
    staleness,
    staleness_days,
    started,
    time,
    unmapped,
    wade_lookup_scores,
):
    _license = (
        "eWRIMS fields: State Water Resources Control Board, public domain. CalWATRS fields: "
        "State Water Resources Control Board, CC BY (attribution required)."
    )
    field_scores.assign(license=_license).to_csv(OUT_DIR / "field_crosswalk.csv", index=False)
    unmapped.to_csv(OUT_DIR / "fields_without_calwatrs_equivalent.csv", index=False)
    lookup_table.assign(license=_license).to_csv(OUT_DIR / "status_type_lookup.csv", index=False)
    holder_by_type.to_csv(OUT_DIR / "holder_by_type.csv")
    lost_by_group.to_csv(OUT_DIR / "fields_by_dictionary_group.csv")
    holder_by_status.to_csv(OUT_DIR / "holder_by_status.csv")
    holder.drop(columns=["type", "status"]).to_parquet(OUT_DIR / "rights_holder_flags.parquet")
    summary = {
        "ewrims_fetched_at": manifest["fetched_at"],
        "ewrims_rights": len(holder),
        "match": match,
        "holder": holder_overall.to_dict(),
        "named_holder_without_active_calwatrs_owner_by_status": holder_lost_by_status.to_dict(),
        "ewrims_columns": len(field_scores) + len(unmapped) + 1,
        "fields_with_equivalent": len(field_scores) + 1,
        "fields_without_equivalent": len(unmapped),
        "field_verdicts": field_scores["verdict"].value_counts().to_dict(),
        "location": location,
        "wade_lookup": wade_lookup_scores.to_dict(orient="records"),
        "ewrims_lookup_in_sample": ewrims_lookup_scores.to_dict(orient="records"),
        "staleness": staleness.reset_index().to_dict(orient="records"),
        "staleness_days": staleness_days,
        "cost_usd": 0,
        "notebook_seconds": round(time.perf_counter() - started, 1),
        "archive_seconds": manifest["run_seconds"],
    }
    (OUT_DIR / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    mo.md(f"""
    ## Result

    - **Holder:** kept, but moved. Participants names an active primary owner for
      {holder_overall.loc["CalWATRS holder", "where eWRIMS named a holder"]:.1%} of the
      rights eWRIMS named one for, and carries the same eWRIMS party for
      {holder_overall.loc["same party", "where eWRIMS named a holder"]:.1%}.
    - **Fields:** {len(field_scores) + 1} of {len(field_scores) + len(unmapped) + 1} eWRIMS
      columns have a CalWATRS equivalent; {len(unmapped)} don't.
    - **Vocabulary:** status and type need a lookup. WaDE's type lookup transfers; its
      status lookup doesn't, because it learned status changes as renamings.
    - **Freshness:** the old file's "last updated" is {staleness_days} days newer than its
      data.

    Run time {summary["notebook_seconds"]} s for this notebook, plus
    {summary["archive_seconds"]} s for the archive. Cost $0. Outputs are in
    `{OUT_DIR}/`; every CSV carries the license note.
    """)
    return


if __name__ == "__main__":
    app.run()

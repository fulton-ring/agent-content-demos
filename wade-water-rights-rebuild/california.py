import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import time
    import zipfile

    import geopandas as gpd
    import marimo as mo
    import pandas as pd

    import wade

    started = time.perf_counter()
    return gpd, mo, pd, started, time, wade, zipfile


@app.cell
def _(mo):
    mo.md(r"""
    # California: rebuilding WaDE after the state changed systems

    **Question.** Can WaDE's California water rights table be rebuilt from what WSWC left
    behind and kept current from the state's weekly open file?

    California is the case with a weekly feed: the State Water Resources Control Board
    publishes *CalWATRS Water Rights Geospatial Data* on data.ca.gov under CC BY. But WSWC's
    California notebook was written against the older eWRIMS flat files. This notebook
    checks whether those still exist, rebuilds California from CalWATRS with a new mapping,
    and measures how much of WaDE comes back.

    This notebook is also the California refresh script: `uv run california.py` downloads
    the current CalWATRS file and rewrites `outputs/CA_water_rights.parquet`.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. WaDE's last California table (the answer key)

    WSWC's README for California points to a Google Drive folder, still shared. Its
    `ProcessedInputData/waterallocations.csv` is what WSWC loaded into WaDE.
    """)
    return


@app.cell
def _(wade):
    ca_folder = wade.drive_folder_from_readme(
        "California/WaterAllocation_WaterUse_CSWRCB/ReadME.md"
    )
    ca_listing = wade.drive_listing(ca_folder)
    wade_alloc, wade_sites = wade.wade_answer_key("CA", ca_listing)
    wade_alloc = wade_alloc.set_index("AllocationNativeID")
    wade_date = wade_alloc["DataPublicationDate"].iloc[0]
    sorted(ca_listing)
    return ca_listing, wade_alloc, wade_date, wade_sites


@app.cell
def _(mo, wade_alloc, wade_date):
    mo.md(f"""
    WaDE's last California load has **{len(wade_alloc):,} rights**, published {wade_date}.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Can WSWC's own notebook still run?

    WSWC's notebook `1_CSWRCBwrwu_PreProcessDivisionAndWithdrawalSites.ipynb` reads
    `ewrims_flat_file_pod` (the eWRIMS points-of-diversion list) and the eWRIMS water use
    report. Ask data.ca.gov what state those datasets are in now.
    """)
    return


@app.cell
def _(pd, wade):
    def ckan_package(name: str) -> dict:
        r = wade.requests.get(
            "https://data.ca.gov/api/3/action/package_show", params={"id": name}, timeout=60
        )
        r.raise_for_status()
        return r.json()["result"]

    old_inputs = pd.DataFrame(
        [
            {
                "dataset": p["title"],
                "last resource update": max(x["last_modified"] for x in p["resources"])[:10],
            }
            for p in map(
                ckan_package,
                [
                    "california-water-rights-points-of-diversion",
                    "california-water-rights-water-use-reported",
                ],
            )
        ]
    )
    calwatrs = ckan_package("calwatrs-geospatial")
    old_inputs
    return (calwatrs,)


@app.cell
def _(mo):
    mo.md(r"""
    Both inputs are now marked **DISCONTINUED**: the Water Board replaced eWRIMS with
    CalWATRS, and the last eWRIMS files are frozen at October 1, 2026. WSWC's notebook can
    still run against that frozen copy, but it can never be refreshed. To keep California
    current, the mapping has to be rewritten for CalWATRS.

    ## 3. Today's CalWATRS file
    """)
    return


@app.cell
def _(calwatrs, pd, time, wade, zipfile):
    _t = time.perf_counter()
    _res = next(r for r in calwatrs["resources"] if r["format"] == "ZIP")
    _zip = wade.fetch(_res["url"], wade.DATA_DIR / "CA" / "calwatrs-geospatial.zip")
    with zipfile.ZipFile(_zip) as z:
        _name = next(n for n in z.namelist() if n.endswith(".csv"))
        with z.open(_name) as f:
            gr = pd.read_csv(f, low_memory=False)
    download_seconds = round(time.perf_counter() - _t, 1)
    source_updated = _res["last_modified"][:10]
    gr.shape
    return download_seconds, gr, source_updated


@app.cell
def _(mo):
    mo.md(r"""
    Each CalWATRS row links one geospatial feature (a point of diversion, a place of use, a
    point of storage) to one right or claim, so a right with three diversion points has
    three rows. That is a different shape from eWRIMS, and the columns have new names.

    ## 4. A new mapping from CalWATRS to WaDE

    None of WSWC's California code applies, so these choices are ours:

    - **Right ID**: `WR_APP_CLAIM_NAME` (A000016, S014808…), the same IDs eWRIMS used.
    - **Status, type, beneficial uses, priority date**: taken as CalWATRS writes them.
    - **Face value** in acre-feet becomes `AllocationVolume_AF`.
    - **Flow**: the largest `POLY_MAXFLOWRATE` among a right's diversion points,
      converted to CFS with WSWC's own unit factors.
    - **Owner**: CalWATRS's open file has no owner column, so it stays blank.
    - **Rows dropped**: WSWC's California list of non-active statuses
      (Cancelled, Closed, Inactive, Pending, Rejected, Revoked).
    - **Location**: the right's first point of diversion, else its first feature.
    """)
    return


@app.cell
def _(gpd, gr, pd, wade):
    to_cfs = {
        "Cubic Feet per Second": 1.0,
        "Gallons per day": 1 / 646316.883,
        "Acre-feet per year": 1 / 723.968,
        "Gallons per minute": 1 / 448.83117,
    }  # WSWC's factors from 1_CSWRCBwrwu_PreProcess...ipynb
    _rows = gr.assign(
        flow_cfs=gr["POLY_MAXFLOWRATE"] * gr["POLY_MAXFLOWRATEUNIT"].map(to_cfs),
        is_pod=gr["GR_FEATURE_TYPE"].eq("Point of Diversion"),
        applied=pd.to_datetime(gr["APP_APPLIED_DATE"], errors="coerce"),
    ).sort_values("is_pod", ascending=False)
    _rows = _rows[_rows["WR_APP_CLAIM_NAME"].notna()]
    _by_right = _rows.groupby("WR_APP_CLAIM_NAME", sort=False)
    _first = _by_right.first()
    use_terms, use_pairs = wade.primary_use_lookup()
    _uses = _first["WR_APP_CLAIM_BENEFICIALPURPOSESOFUSE"].fillna("")
    rebuilt_all = pd.DataFrame(
        {
            "AllocationOwner": "",
            "AllocationPriorityDate": pd.to_datetime(
                _first["WR_APP_CLAIM_PRIORITYDATE"], errors="coerce"
            ),
            "AllocationLegalStatusCV": _first["WR_APP_CLAIM_STATUS"],
            "AllocationTypeCV": _first["WR_APP_CLAIM_TYPE"],
            "AllocationSubtype": _first["WR_APP_SUBTYPE"],
            "AllocationFlow_CFS": _by_right["flow_cfs"].max(),
            "AllocationVolume_AF": _first["WR_APP_FACEVALUE"],
            "BeneficialUseCategory": _uses,
            "PrimaryBeneficialUseCategory": wade.primary_use(_uses, use_terms, use_pairs),
            "IrrigatedAcreage": _first["POLY_BL_BLA_CLAIM_NET_USE_ACREAGE"],
            "County": _first["POLY_COUNTY"],
            "HUC12": _first["POLY_HUC12"],
            "WaterSourceName": _first["POLY_SOURCE"],
            "Features": _by_right.size(),
            "NewestApplication": _by_right["applied"].max(),
            "Latitude": _first["POLY_LATITUDE"],
            "Longitude": _first["POLY_LONGITUDE"],
        }
    )
    rebuilt_all.index.name = "AllocationNativeID"
    wswc_drop = ["Cancelled", "Closed", "Inactive", "Pending", "Rejected", "Revoked"]
    rebuilt_ca = rebuilt_all[~rebuilt_all["AllocationLegalStatusCV"].isin(wswc_drop)]
    rebuilt_ca = gpd.GeoDataFrame(
        rebuilt_ca,
        geometry=gpd.points_from_xy(rebuilt_ca["Longitude"], rebuilt_ca["Latitude"]),
        crs=4326,
    )
    {"rights in CalWATRS": len(rebuilt_all), "after WSWC's status filter": len(rebuilt_ca)}
    return rebuilt_all, rebuilt_ca, use_terms


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Compare with WaDE

    Match rate is the share of WaDE's right IDs found in the rebuild. Fields are compared
    only where WaDE had a value (see `wade.compare_fields`). Location is the share of
    matched rights whose rebuilt point is within 100 m of WaDE's first site.
    """)
    return


@app.cell
def _(ca_listing, rebuilt_all, rebuilt_ca, wade, wade_alloc, wade_sites):
    ca_match_rate = round(float(wade_alloc.index.isin(rebuilt_ca.index).mean()), 4)
    ca_in_calwatrs = round(float(wade_alloc.index.isin(rebuilt_all.index).mean()), 4)
    ca_fields = wade.compare_fields(wade_alloc, rebuilt_ca)
    ca_location = wade.location_agreement(
        wade.wade_first_site_coords(wade_alloc.reset_index(), wade_sites), rebuilt_ca, 100
    )
    ca_extra = wade.extra_rights(rebuilt_ca, wade_alloc, wade.wade_dropped("CA", ca_listing))
    ca_fields
    return ca_extra, ca_fields, ca_in_calwatrs, ca_location, ca_match_rate


@app.cell
def _(ca_extra, ca_in_calwatrs, ca_location, ca_match_rate, mo, rebuilt_ca, wade_alloc):
    mo.md(f"""
    **{ca_in_calwatrs:.1%}** of WaDE's California right IDs are still in CalWATRS, and
    **{ca_match_rate:.1%}** survive WSWC's status filter. The rebuild has
    {len(rebuilt_ca):,} rights against WaDE's {len(wade_alloc):,}. Of the
    {ca_extra["not_in_wade"]:,} rights WaDE didn't have, {ca_extra["dropped_by_wade_checks"]:,}
    were dropped by WSWC's own error checks; {ca_extra["new_or_unexplained"]:,} are new since
    WaDE's last load or carry statuses WSWC's filter didn't list. Location agrees within
    100 m for **{ca_location:.1%}** of matched rights.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. The hand harmonization, measured

    Status and type are where WaDE and CalWATRS disagree. WaDE's California terms came from
    eWRIMS ("Claimed", "Statement of Div and Use RIPARIAN"); CalWATRS uses new ones
    ("Active", "Riparian"). WSWC's hand work is gone with eWRIMS, but its result isn't:
    WaDE's last table says which WaDE term each surviving right had. So we can learn a
    crosswalk from it: for each CalWATRS combination, take the WaDE term most of its
    matched rights carried. Status is keyed on CalWATRS status and type; type on CalWATRS
    type and subtype.

    The accuracy is in-sample (learned and scored on the same rights), so it is the best a
    lookup table can do, not a forecast.
    """)
    return


@app.cell
def _(pd, rebuilt_ca, wade_alloc):
    _both = wade_alloc.index.intersection(rebuilt_ca.index)
    crosswalks = {
        "AllocationLegalStatusCV": ["AllocationLegalStatusCV", "AllocationTypeCV"],
        "AllocationTypeCV": ["AllocationTypeCV", "AllocationSubtype"],
    }
    learned = {}
    crosswalk_rows = []
    for _field, _keys in crosswalks.items():
        _calwatrs = rebuilt_ca.loc[_both, _keys].fillna("(blank)").astype(str)
        _wade_terms = wade_alloc.loc[_both, _field]
        _table = _wade_terms.groupby([_calwatrs[k] for k in _keys]).agg(
            lambda s: s.value_counts().index[0]
        )
        _predicted = pd.Series(
            _table.reindex(pd.MultiIndex.from_frame(_calwatrs)).to_numpy(), index=_both
        )
        _all_keys = pd.MultiIndex.from_frame(rebuilt_ca[_keys].fillna("(blank)").astype(str))
        learned[_field] = _table
        crosswalk_rows.append(
            {
                "field": _field,
                "lookup rows": len(_table),
                "WaDE values restored": round(float((_predicted == _wade_terms).mean()), 3),
                "rebuilt rights with an unseen key": int((~_all_keys.isin(_table.index)).sum()),
            }
        )
    crosswalk_summary = pd.DataFrame(crosswalk_rows)
    crosswalk_summary
    return crosswalk_summary, learned


@app.cell
def _(learned):
    learned["AllocationTypeCV"].rename("WaDE type").reset_index().head(45)
    return


@app.cell
def _(crosswalk_summary, mo, rebuilt_ca, use_terms, wade):
    ca_unknown = wade.unknown_use_terms(rebuilt_ca["BeneficialUseCategory"], use_terms)
    ca_primary_filled = round(float((rebuilt_ca["PrimaryBeneficialUseCategory"] != "").mean()), 4)
    _s, _t = crosswalk_summary.iloc[0], crosswalk_summary.iloc[1]
    mo.md(f"""
    A {_s["lookup rows"]}-row status lookup restores **{_s["WaDE values restored"]:.0%}**
    of WaDE's status values, and a {_t["lookup rows"]}-row type lookup restores
    **{_t["WaDE values restored"]:.0%}**. The rest can't be told apart from CalWATRS's
    columns: eWRIMS split some CalWATRS categories ("Registered" became both "Certified"
    and "Registered"; "Other" claims became federal claims or statements) on fields the
    open file doesn't carry. {_s["rebuilt rights with an unseen key"]:,} rebuilt rights have
    a status key WaDE never saw and would need a person to map.

    WSWC's hand-built beneficial-use table covers CalWATRS's use names for
    **{ca_primary_filled:.1%}** of rights. {len(ca_unknown)} use names are missing from it:
    {", ".join(ca_unknown.head(6).index)}.
    """)
    return ca_primary_filled, ca_unknown


@app.cell
def _(
    ca_extra,
    ca_fields,
    ca_in_calwatrs,
    ca_location,
    ca_match_rate,
    ca_primary_filled,
    ca_unknown,
    download_seconds,
    crosswalk_summary,
    mo,
    rebuilt_ca,
    source_updated,
    started,
    time,
    wade,
    wade_alloc,
    wade_date,
):
    ca_parquet = wade.write_geoparquet(rebuilt_ca.drop(columns=["Latitude", "Longitude"]), "CA")
    ca_summary = {
        "state": "California",
        "source": "CalWATRS Water Rights Geospatial Data (data.ca.gov, CC BY)",
        "mapping": "new mapping; WSWC inputs (eWRIMS) discontinued",
        "wade_count": len(wade_alloc),
        "wade_published": wade_date,
        "rebuilt_count": len(rebuilt_ca),
        "extra_rights": ca_extra,
        "match_rate": ca_match_rate,
        "ids_still_in_source": ca_in_calwatrs,
        "location_within_100m": ca_location,
        "newest_record": str(rebuilt_ca["NewestApplication"].max().date()),
        "source_updated": source_updated,
        "update_frequency": "Weekly",
        "primary_use_auto_share": ca_primary_filled,
        "unknown_use_terms": int(len(ca_unknown)),
        "crosswalk": wade.records(crosswalk_summary),
        "fields": wade.records(ca_fields),
        "download_seconds": download_seconds,
        "run_seconds": round(time.perf_counter() - started, 1),
        "geoparquet": str(ca_parquet),
    }
    wade.save_summary("CA", ca_summary)
    mo.md(f"""
    ## Result

    Wrote `{ca_parquet}`. The newest application in CalWATRS was filed
    {ca_summary["newest_record"]}; the file was last updated {source_updated} and the Water
    Board updates it weekly. Run time {ca_summary["run_seconds"]} s.

    **What came back:** the rights themselves, their locations, flow and use acreage.
    Priority dates came back and agree where WaDE had one; CalWATRS adds dates for many
    more rights.
    **What didn't:** owner (not in the open file), and WaDE's status and type vocabulary,
    which comes back only through a lookup learned from WaDE's own last table.
    """)
    return


if __name__ == "__main__":
    app.run()

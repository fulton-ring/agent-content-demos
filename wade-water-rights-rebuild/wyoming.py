import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import re
    import time

    import geopandas as gpd
    import marimo as mo
    import pandas as pd

    import wade

    started = time.perf_counter()
    return gpd, mo, pd, re, started, time, wade


@app.cell
def _(mo):
    mo.md(r"""
    # Wyoming: rebuilding WaDE when the source was an email

    **Question.** Can WaDE's Wyoming water rights table be rebuilt from what WSWC left
    behind, and kept current?

    Wyoming is the hard case. WSWC's README says the Wyoming Water Development Office sent
    the point-of-diversion and place-of-use files "via email correspondence", and that the
    links are "no longer available". We found no public bulk download of Wyoming water
    rights to replace them: the State Engineer's e-Permit system lets a person search and
    download a shapefile for a map extent, not the whole state, and the State Water Plan
    GIS layers date from 2001–2007.

    So the only thing left to rebuild from is the raw files WSWC kept in its Google Drive.
    This notebook reruns WSWC's mapping on those files and checks it reproduces WaDE.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. WaDE's last Wyoming table, and the raw files behind it
    """)
    return


@app.cell
def _(wade):
    wy_folder = wade.drive_folder_from_readme("Wyoming/WaterAllocation/ReadMe.md")
    wy_listing = wade.drive_listing(wy_folder)
    wade_alloc, wade_sites = wade.wade_answer_key("WY", wy_listing)
    wade_alloc = wade_alloc.set_index("AllocationNativeID")
    wade_date = wade_alloc["DataPublicationDate"].iloc[0]
    sorted(wy_listing)
    return wade_alloc, wade_date, wade_sites, wy_listing


@app.cell
def _(pd, time, wade, wy_listing):
    _t = time.perf_counter()

    def raw_file(name: str, **read_args: object) -> pd.DataFrame:
        path = wade.drive_file(wy_listing[f"RawInputData/{name}"], wade.DATA_DIR / "WY" / name)
        return pd.read_csv(path, dtype=str, **read_args).fillna("")  # as WSWC read them

    pod_sw = raw_file("POD_SW_DepthI_FC_input.zip")
    pod_gw = raw_file("POD_GW_DepthI_FC_input.zip")
    pou = raw_file(
        "POU_input.zip",
        usecols=[
            "WRNumber",
            "SummaryWRStatus",
            "PriorityDate",
            "Uses",
            "Company",
            "FirstName",
            "LastName",
            "Survey",
            "Acres",
            "Latitude",
            "Longitude",
        ],
    )
    download_seconds = round(time.perf_counter() - _t, 1)
    downloaded = pd.to_datetime(pd.concat([pod_sw, pod_gw])["DateDownloaded"], format="mixed")
    {"surface PODs": len(pod_sw), "groundwater PODs": len(pod_gw), "place-of-use rows": len(pou),
     "state export date": str(downloaded.max().date())}  # fmt: skip
    return download_seconds, downloaded, pod_gw, pod_sw, pou


@app.cell
def _(downloaded, mo, wade_alloc, wade_date):
    mo.md(f"""
    WaDE's last Wyoming load has **{len(wade_alloc):,} rights**, published {wade_date}.
    But the raw files behind it carry a `DateDownloaded` of
    **{downloaded.max():%B %-d, %Y}**: WaDE was republishing a Wyoming export that was
    already seven years old when WaDE went offline.

    ## 2. Rerun WSWC's mapping

    The steps are copied from `Wyoming/WaterAllocation/1_WYwr_PreProcessAllocationData.ipynb`.
    Owner is the company, else "Last, First". Uses are semicolon-separated codes spelled
    out with WSWC's 96-entry dictionary, then stripped of punctuation and title-cased. A
    survey number starting with "Z" adds "Wild and Scenic River". WSWC dropped Incomplete,
    Unadjudicated, Suspended and Rejected rights.
    """)
    return


@app.cell
def _(pd, re):
    ben_use_codes = {
        'AESCNG': 'Coal Bed Natural Gas', 'AESFIS': 'Fish Propagation (Aesthetics)',
        'AESGWR': 'Ground Water Recharge (Aesthetics)', 'AESREC': 'Recreation (Aesthetics)',
        'AESSTK': 'Stock (Aesthetics)', 'AESWET': 'Wetlands (Aesthetics)',
        'AESWIL': 'Wildlife (Aesthetics)', 'AQU': 'Aquaculture', 'BOT': 'Bottling Water',
        'CAG': 'Commercial Agriculture', 'CBM': 'Coal Bed Methane - Ground Water',
        'CHE': 'Chemical', 'CIS': 'Consumptive Instream Flow', 'CMU': 'Combined Uses',
        'CNG_SW': 'Coal Bed Natural Gas', 'COM': 'Commercial', 'CUL': 'Culinary',
        'DAI': 'Dairy', 'DEW': 'Mine Dewatering', 'DOM_GW': 'Domestic - Ground Water',
        'DOM_SW': 'Domestic - Surface Water', 'DPA': 'Domestic (Phase 2 Award)',
        'DRI': 'Drilling', 'DSP': 'Domestic Supply', 'DTA': 'Dust Abatement',
        'ECAP': 'Existing Capacity', 'ERO': 'Erosion Control', 'FIR': 'Fire Protection',
        'FIS': 'Fish Propagation', 'FLO': 'Flood Control', 'FTH': 'Flow Through',
        'GWR': 'Ground Water Recharge', 'HEX': 'Heat Extraction',
        'HWY': 'Highway Construction', 'HYD': 'Hydropower', 'HYT': 'Hydrostatic Testing',
        'ICE': 'Ice Cutting', 'IFA': 'Instream Flow (Phase 2 Award)',
        'IND_GW': 'Industrial - Ground Water', 'IND_SW': 'Industrial - Surface Water',
        'IRR_GW': 'Irrigation - Ground Water', 'IRR_SW': 'Irrigation - Surface Water',
        'ISF': 'Instream Flow', 'LAK': 'Maintain Natural Lake Level (Phase 2 Award)',
        'LAW': 'Large Scale Landscape', 'MAI': 'Maintenance (Equipment Washing)',
        'MAN': 'Manufacturing', 'MEC': 'Mechanical', 'MED': 'Medicinal',
        'MEM': 'Municipal (Emergency)', 'MIL': 'Milling', 'MIN': 'Mining',
        'MIS': 'Miscellaneous - Ground Water', 'MON': 'Monitor',
        'MUN_GW': 'Municipal - Ground Water', 'MUN_SW': 'Municipal - Surface Water',
        'NAT': 'Natural Flow (Phase 2 Award)', 'O&G': 'Oil and Gas Well Drilling',
        'OIL': 'Oil', 'OTH': 'Other', 'OTH_CM': 'Other - Commercial',
        'OTH_IN': 'Other - Industrial', 'OTH_TM': 'Other - Temporary',
        'P&S': 'Potable and Sanitary Supply', 'PCT': 'Pollution Control', 'POW': 'Power',
        'RAI': 'Railroad', 'RDC': 'Road Construction', 'REC': 'Recreation', 'REF': 'Refining',
        'RES': 'Reservoir Supply', 'REW': 'Reclamation Watering', 'S&D': 'Stock and Domestic',
        'SDG': 'Gpm For Domestic or Stock', 'SDU': 'Stock and Domestic',
        'SED': 'Sediment Control', 'SNO': 'Snow Making', 'STE': 'Stream',
        'STK': 'Stock Watering', 'STKNDMS': 'Stock and Domestic', 'STO': 'Stock',
        'STS': 'Stock', 'STW': 'Stock Watering', 'SWD': 'Subdivision',
        'SWP': 'Stock Water Pipeline', 'TEM': 'Temporary', 'TENL': 'Total Enlargement',
        'TRA': 'Transportation', 'TST': 'Test Well', 'TWR': 'Tree Watering',
        'UTL': 'Utilities', 'W&S': 'Wild and Scenic', 'WDR': 'Well Drilling',
        'WET': 'Wetlands', 'WHL': 'Water Hauls', 'WL': 'Wildlife',
    }  # fmt: skip

    def spell_uses(codes: str, survey: str) -> str:
        names = [ben_use_codes.get(c.strip()) for c in codes.split(";")] if codes.strip() else []
        if not names or None in names:
            return ""  # WSWC returned "" when any code was unknown
        text = re.sub(r"[$@<&>.;/\-]", "", ", ".join(n for n in names if n))
        text = text.title().replace("  ", " ").strip()
        return f"Wild and Scenic River, {text}" if str(survey).startswith("Z") else text

    def owner(company: pd.Series, first: pd.Series, last: pd.Series) -> pd.Series:
        return company.str.strip().where(
            company.str.strip() != "", last.str.strip() + ", " + first.str.strip()
        )

    return owner, spell_uses


@app.cell
def _(pd, pod_gw, pod_sw, pou, owner, spell_uses):
    _pods = pd.concat(
        [pod_sw.assign(SupplyKind="Surface Water"), pod_gw.assign(SupplyKind="Groundwater")]
    )
    pod_rows = pd.DataFrame(
        {
            "AllocationNativeID": _pods["WR_Number"],
            "AllocationOwner": owner(_pods["Company"], _pods["FirstName"], _pods["LastName"]),
            "AllocationPriorityDate": _pods["PriorityDate"],
            "AllocationLegalStatusCV": _pods["SummaryWRStatus"].str.strip(),
            "AllocationFlow_CFS": pd.to_numeric(
                _pods["Total_Flow_CFS___Appropriation_GPM_"], errors="coerce"
            ),
            "BeneficialUseCategory": [
                spell_uses(u, s)
                for u, s in zip(
                    _pods["Uses"], _pods["Survey_Type_Survey_Number_Survey_Suffix"], strict=True
                )
            ],
            "IrrigatedAcreage": float("nan"),
            "Latitude": pd.to_numeric(_pods["Latitude_Double"], errors="coerce"),
            "Longitude": pd.to_numeric(_pods["Longitude_Double"], errors="coerce"),
        }
    )
    pou_rows = pd.DataFrame(
        {
            "AllocationNativeID": pou["WRNumber"],
            "AllocationOwner": owner(pou["Company"], pou["FirstName"], pou["LastName"]),
            "AllocationPriorityDate": pou["PriorityDate"],
            "AllocationLegalStatusCV": pou["SummaryWRStatus"].str.strip(),
            "AllocationFlow_CFS": float("nan"),
            "BeneficialUseCategory": [
                spell_uses(u, s) for u, s in zip(pou["Uses"], pou["Survey"], strict=True)
            ],
            "IrrigatedAcreage": pd.to_numeric(pou["Acres"], errors="coerce"),
            "Latitude": pd.to_numeric(pou["Latitude"], errors="coerce"),
            "Longitude": pd.to_numeric(pou["Longitude"], errors="coerce"),
        }
    )
    all_rows = pd.concat([pod_rows, pou_rows], ignore_index=True)
    wswc_drop = ["Incomplete", "Unadjudicated", "Suspended", "Rejected"]
    all_rows = all_rows[~all_rows["AllocationLegalStatusCV"].isin(wswc_drop)]
    all_rows["AllocationPriorityDate"] = pd.to_datetime(
        all_rows["AllocationPriorityDate"], errors="coerce", format="mixed"
    )
    all_rows["AllocationNativeID"].nunique()
    return (all_rows,)


@app.cell
def _(mo):
    mo.md(r"""
    **One row per right.** A right appears once per diversion point and once per
    place-of-use parcel. We keep the first diversion point's values and location, and compute
    the primary use with WSWC's lookup. For acreage we take the largest parcel: summing the
    parcels matched WaDE for only 75% of rights, the largest parcel for all of them, so
    WaDE's Wyoming `IrrigatedAcreage` understates rights with more than one parcel.
    """)
    return


@app.cell
def _(all_rows, gpd, wade):
    use_terms, use_pairs = wade.primary_use_lookup()
    _by_right = all_rows.groupby("AllocationNativeID", sort=False)
    rebuilt_wy = _by_right.first()
    rebuilt_wy["IrrigatedAcreage"] = _by_right["IrrigatedAcreage"].max()
    rebuilt_wy["AllocationTypeCV"] = "Prior Appropriation"
    rebuilt_wy["PrimaryBeneficialUseCategory"] = wade.primary_use(
        rebuilt_wy["BeneficialUseCategory"], use_terms, use_pairs
    )
    rebuilt_wy = gpd.GeoDataFrame(
        rebuilt_wy,
        geometry=gpd.points_from_xy(rebuilt_wy["Longitude"], rebuilt_wy["Latitude"]),
        crs=4326,
    )
    len(rebuilt_wy)
    return rebuilt_wy, use_terms


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Compare with WaDE

    Same comparison as the other two states (see `wade.compare_fields`).
    """)
    return


@app.cell
def _(rebuilt_wy, use_terms, wade, wade_alloc, wade_sites, wy_listing):
    wy_match_rate = round(float(wade_alloc.index.isin(rebuilt_wy.index).mean()), 4)
    wy_fields = wade.compare_fields(wade_alloc, rebuilt_wy)
    wy_location = wade.location_agreement(
        wade.wade_first_site_coords(wade_alloc.reset_index(), wade_sites), rebuilt_wy, 100
    )
    wy_unknown = wade.unknown_use_terms(rebuilt_wy["BeneficialUseCategory"], use_terms)
    wy_primary_filled = round(float((rebuilt_wy["PrimaryBeneficialUseCategory"] != "").mean()), 4)
    wy_extra = wade.extra_rights(rebuilt_wy, wade_alloc, wade.wade_dropped("WY", wy_listing))
    wy_fields
    return wy_extra, wy_fields, wy_location, wy_match_rate, wy_primary_filled, wy_unknown


@app.cell
def _(mo, wy_extra):
    mo.md(f"""
    The rebuild has **{wy_extra["not_in_wade"]:,} rights WaDE didn't**. WSWC's own error
    checks explain {wy_extra["dropped_by_wade_checks"]:,} of them: they are listed in
    `ProcessedInputData/waterallocations_missing.csv`, mostly for
    "{next(iter(wy_extra["top_drop_reasons"]), "")}". So WaDE's Wyoming count was not the
    number of Wyoming rights in the export; it was the number that passed WSWC's checks.
    {wy_extra["new_or_unexplained"]:,} extra rights are unexplained.
    """)
    return


@app.cell
def _(
    download_seconds,
    downloaded,
    mo,
    rebuilt_wy,
    started,
    time,
    wade,
    wade_alloc,
    wade_date,
    wy_fields,
    wy_location,
    wy_match_rate,
    wy_primary_filled,
    wy_extra,
    wy_unknown,
):
    _valid = rebuilt_wy["AllocationPriorityDate"][
        rebuilt_wy["AllocationPriorityDate"] <= downloaded.max()
    ]
    wy_parquet = wade.write_geoparquet(rebuilt_wy.drop(columns=["Latitude", "Longitude"]), "WY")
    wy_summary = {
        "state": "Wyoming",
        "source": "WWDO files emailed to WSWC, kept in WSWC's Google Drive",
        "mapping": "WSWC notebook logic, unchanged; no live source",
        "wade_count": len(wade_alloc),
        "wade_published": wade_date,
        "rebuilt_count": len(rebuilt_wy),
        "extra_rights": wy_extra,
        "match_rate": wy_match_rate,
        "location_within_100m": wy_location,
        "newest_record": str(_valid.max().date()),
        "source_updated": str(downloaded.max().date()),
        "update_frequency": "None (one-off export)",
        "primary_use_auto_share": wy_primary_filled,
        "unknown_use_terms": int(len(wy_unknown)),
        "fields": wade.records(wy_fields),
        "download_seconds": download_seconds,
        "run_seconds": round(time.perf_counter() - started, 1),
        "geoparquet": str(wy_parquet),
    }
    wade.save_summary("WY", wy_summary)
    mo.md(f"""
    ## Result

    **{wy_match_rate:.1%}** of WaDE's Wyoming rights come back from WSWC's raw files, and
    location agrees within 100 m for **{wy_location:.1%}**. Wrote `{wy_parquet}`.
    Run time {wy_summary["run_seconds"]} s.

    The mapping survives as code, but there is nothing live to point it at. The newest
    priority date is {wy_summary["newest_record"]}, the export is dated
    {wy_summary["source_updated"]}, and no public Wyoming feed replaces it. Keeping Wyoming
    current means asking the state for a new export, as WSWC did.
    """)
    return


if __name__ == "__main__":
    app.run()

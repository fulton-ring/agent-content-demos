import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import time

    import geopandas as gpd
    import marimo as mo
    import pandas as pd

    import wade

    started = time.perf_counter()
    return gpd, mo, pd, started, time, wade


@app.cell
def _(mo):
    mo.md(r"""
    # Colorado: rebuilding WaDE from a live CSV

    **Question.** WaDE went offline in October 2026. Can its Colorado water rights table be
    rebuilt from WSWC's published mapping code and today's state data, and how much comes back?

    Colorado is the easy case: the Division of Water Resources publishes one CSV,
    *DWR Water Right – Net Amounts*, on data.colorado.gov and updates it daily. WSWC's
    notebook `Colorado/WaterAllocation/1_COwr_PreProcessAllocationData.ipynb` read the same
    file. If the hand harmonization survives as code anywhere, it should survive here.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. WaDE's last Colorado table (the answer key)

    WSWC's GitHub README for Colorado points to a Google Drive folder. That folder is still
    shared, and its `ProcessedInputData/waterallocations.csv` is exactly what WSWC loaded
    into WaDE. We use it as the answer key.
    """)
    return


@app.cell
def _(wade):
    co_folder = wade.drive_folder_from_readme("Colorado/WaterAllocation/ReadME.md")
    co_listing = wade.drive_listing(co_folder)
    wade_alloc, wade_sites = wade.wade_answer_key("CO", co_listing)
    wade_alloc = wade_alloc.set_index("AllocationNativeID")
    wade_date = wade_alloc["DataPublicationDate"].iloc[0]
    sorted(co_listing)
    return co_listing, wade_alloc, wade_date, wade_sites


@app.cell
def _(mo, wade_alloc, wade_date):
    mo.md(f"""
    WaDE's last Colorado load has **{len(wade_alloc):,} rights**, published {wade_date}.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Today's Colorado source

    Download the full CSV from Socrata, plus its metadata so we know when it last changed.
    """)
    return


@app.cell
def _(pd, time, wade):
    _t = time.perf_counter()
    co_csv = wade.fetch(
        "https://data.colorado.gov/api/views/acsg-f33s/rows.csv?accessType=DOWNLOAD",
        wade.DATA_DIR / "CO" / "net_amounts.csv",
    )
    raw = pd.read_csv(co_csv, low_memory=False)
    meta = wade.requests.get("https://data.colorado.gov/api/views/acsg-f33s.json", timeout=60)
    meta.raise_for_status()
    co_meta = meta.json()
    download_seconds = round(time.perf_counter() - _t, 1)
    source_updated = pd.Timestamp(co_meta["rowsUpdatedAt"], unit="s").date()
    update_frequency = co_meta["metadata"]["custom_fields"]["Data Quality"][
        "Expected Update Frequency"
    ]
    raw.shape
    return download_seconds, raw, source_updated, update_frequency


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Apply WSWC's mapping

    Each step below is copied from WSWC's Colorado notebook, vectorised but with the same
    rules. The dictionaries are theirs: this is the harmonization, written as code.

    **Beneficial use.** Colorado packs decreed uses into a string of one-character codes
    ("18" is irrigation and domestic). WSWC's dictionary spells each one out.
    """)
    return


@app.cell
def _(raw):
    ben_use_codes = {
        "0": "Storage", "1": "Irrigation", "2": "Municipal", "3": "Commercial",
        "4": "Industrial", "5": "Recreation", "6": "Fishery", "7": "Fire", "8": "Domestic",
        "9": "Stock", "A": "Augmentation", "B": "Export from Basin",
        "C": "Cumulative Accretion to River", "D": "Cumulative Depletion from River",
        "E": "Evaporative", "F": "Federal Reserved", "G": "Geothermal",
        "H": "Household Use Only", "K": "Snow Making", "M": "Minimum Streamflow",
        "N": "Net Effect on River", "P": "Power Generation", "Q": "Other", "R": "Recharge",
        "S": "Export from State", "T": "Transmountain Export", "W": "Wildlife",
        "X": "All Beneficial Uses",
    }  # fmt: skip

    def spell_uses(codes: object) -> str:
        chars = [c for c in str(codes).strip() if c.strip()]
        if not chars or str(codes) == "nan" or any(c not in ben_use_codes for c in chars):
            return ""  # WSWC returned "" when any code was unknown
        return ",".join(ben_use_codes[c] for c in chars)

    uses = raw["Decreed Uses"].map(spell_uses)
    uses.value_counts().head(8)
    return (uses,)


@app.cell
def _(mo):
    mo.md(r"""
    **Amounts and legal status.** A Colorado decree is in cubic feet per second (units "C")
    or acre-feet ("A"), absolute or conditional. WSWC took the absolute amount, fell back to
    the conditional amount, and wrote 0 when both were set. They called a right
    *Absolute*, *Conditional* or *Conditional Absolute* from which amounts were non-zero.

    **Right ID.** Colorado has no single right ID, so WSWC joined admin number, order
    number, units and structure WDID. We rebuild the same string so IDs line up.
    """)
    return


@app.cell
def _(pd, raw):
    absolute = raw["Net Absolute"].fillna(0)
    conditional = raw["Net Conditional"].fillna(0)
    units = raw["Decreed Units"].astype(str).str.strip()
    amount = absolute.where(absolute != 0, conditional).where(
        ~((absolute != 0) & (conditional != 0)), 0
    )
    flow_cfs = amount.where(units == "C", 0)
    volume_af = amount.where(units == "A", 0)
    legal_status = pd.Series("Absolute", index=raw.index)
    legal_status[(absolute == 0) & (conditional != 0)] = "Conditional"
    legal_status[(absolute == 0) & (conditional == 0)] = "Conditional Absolute"
    native_id = (
        raw["Admin No"].astype(str).str.strip() + "-" + raw["Order No"].astype(str).str.strip()
        + "-" + raw["Decreed Units"].astype(str) + "-" + raw["WDID"].astype(str).str.strip()
    )  # fmt: skip
    legal_status.value_counts()
    return flow_cfs, legal_status, native_id, volume_af


@app.cell
def _(mo):
    mo.md(r"""
    **Assemble the table.** WSWC hard-coded two Colorado constants: every right is
    *Prior Appropriation* and the owner is blank (the CSV has no owner). They dropped
    *Conditional* rights and kept one row per right ID. The primary use comes from WSWC's
    hand-built lookup of 523 native use names (see `wade.primary_use_lookup`).
    """)
    return


@app.cell
def _(flow_cfs, gpd, legal_status, native_id, pd, raw, uses, volume_af, wade):
    use_terms, use_pairs = wade.primary_use_lookup()
    rebuilt_all = pd.DataFrame(
        {
            "AllocationNativeID": native_id,
            "AllocationOwner": "",
            "AllocationPriorityDate": pd.to_datetime(raw["Appropriation Date"], errors="coerce"),
            "AllocationLegalStatusCV": legal_status,
            "AllocationTypeCV": "Prior Appropriation",
            "AllocationFlow_CFS": flow_cfs,
            "AllocationVolume_AF": volume_af,
            "BeneficialUseCategory": uses,
            "PrimaryBeneficialUseCategory": wade.primary_use(uses, use_terms, use_pairs),
            "IrrigatedAcreage": 0.0,
            "SiteName": raw["Structure Name"],
            "SiteTypeCV": raw["Structure Type"],
            "WaterSourceName": raw["Water Source"],
            "SourceModified": pd.to_datetime(raw["Modified"], errors="coerce", format="mixed"),
            "Latitude": raw["Latitude"],
            "Longitude": raw["Longitude"],
        }
    )
    rebuilt_all = rebuilt_all[rebuilt_all["AllocationLegalStatusCV"] != "Conditional"]
    rebuilt_co = rebuilt_all.drop_duplicates("AllocationNativeID").set_index("AllocationNativeID")
    rebuilt_co = gpd.GeoDataFrame(
        rebuilt_co,
        geometry=gpd.points_from_xy(rebuilt_co["Longitude"], rebuilt_co["Latitude"]),
        crs=4326,
    )
    len(rebuilt_co)
    return rebuilt_co, use_terms


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Compare with WaDE

    **Match rate** is the share of WaDE's right IDs that appear in the rebuild. For matched
    rights, each field WaDE filled in is compared: text after lower-casing, numbers within
    1%, dates by day, beneficial uses as a set. **Location** is the share of matched rights
    whose rebuilt point is within 100 m of the first site WaDE listed.
    """)
    return


@app.cell
def _(co_listing, rebuilt_co, wade, wade_alloc, wade_sites):
    co_matched = wade_alloc.index.isin(rebuilt_co.index)
    co_match_rate = round(float(co_matched.mean()), 4)
    co_fields = wade.compare_fields(wade_alloc, rebuilt_co)
    co_location = wade.location_agreement(
        wade.wade_first_site_coords(wade_alloc.reset_index(), wade_sites), rebuilt_co, 100
    )
    co_extra = wade.extra_rights(rebuilt_co, wade_alloc, wade.wade_dropped("CO", co_listing))
    co_fields
    return co_extra, co_fields, co_location, co_match_rate


@app.cell
def _(co_extra, co_fields, co_location, co_match_rate, mo, rebuilt_co, wade_alloc):
    _lost = wade_alloc.index[~wade_alloc.index.isin(rebuilt_co.index)]
    mo.md(f"""
    **{co_match_rate:.1%}** of WaDE's {len(wade_alloc):,} Colorado rights are in today's
    rebuild of {len(rebuilt_co):,}. {len(_lost):,} WaDE IDs are gone, most likely rights the
    water court has since changed (a new admin number or decree makes a new ID).
    Of the {co_extra["not_in_wade"]:,} rebuilt rights WaDE didn't have,
    {co_extra["dropped_by_wade_checks"]:,} were dropped by WSWC's own error checks and
    {co_extra["new_or_unexplained"]:,} are new decrees since WaDE's last load.
    Location agrees for **{co_location:.1%}** of matched rights.

    Fields that come back at 95% or better:
    {", ".join(co_fields.loc[co_fields.status == "comes back", "field"]) or "none"}.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. What the hand-built lookup misses today

    WSWC's primary-use function stops with an error on any native use name not in its
    spreadsheet. Here we count Colorado's spelled-out use names that aren't in it.
    """)
    return


@app.cell
def _(rebuilt_co, use_terms, wade):
    co_unknown = wade.unknown_use_terms(rebuilt_co["BeneficialUseCategory"], use_terms)
    co_primary_filled = round(float((rebuilt_co["PrimaryBeneficialUseCategory"] != "").mean()), 4)
    co_unknown.head(15)
    return co_primary_filled, co_unknown


@app.cell
def _(
    co_extra,
    co_fields,
    co_location,
    co_match_rate,
    co_primary_filled,
    co_unknown,
    download_seconds,
    mo,
    rebuilt_co,
    source_updated,
    started,
    time,
    update_frequency,
    wade,
    wade_alloc,
    wade_date,
):
    co_parquet = wade.write_geoparquet(rebuilt_co.drop(columns=["Latitude", "Longitude"]), "CO")
    co_summary = {
        "state": "Colorado",
        "source": "DWR Water Right - Net Amounts (data.colorado.gov acsg-f33s)",
        "mapping": "WSWC notebook logic, unchanged",
        "wade_count": len(wade_alloc),
        "wade_published": wade_date,
        "rebuilt_count": len(rebuilt_co),
        "extra_rights": co_extra,
        "match_rate": co_match_rate,
        "location_within_100m": co_location,
        "newest_record": str(rebuilt_co["SourceModified"].max().date()),
        "source_updated": str(source_updated),
        "update_frequency": update_frequency,
        "primary_use_auto_share": co_primary_filled,
        "unknown_use_terms": int(len(co_unknown)),
        "fields": wade.records(co_fields),
        "download_seconds": download_seconds,
        "run_seconds": round(time.perf_counter() - started, 1),
        "geoparquet": str(co_parquet),
    }
    wade.save_summary("CO", co_summary)
    mo.md(f"""
    ## Result

    Wrote `{co_parquet}`. The newest record in the source was modified
    {co_summary["newest_record"]}; Socrata says the table last changed {source_updated}
    and is expected to update {update_frequency.lower()}. Run time {co_summary["run_seconds"]} s.

    **What didn't come back.** Owner was blank in WaDE too: the Net Amounts CSV has no
    owner. Everything else WSWC derived for Colorado is plain code over one public file, so
    for Colorado the harmonization does survive as code.
    """)
    return


if __name__ == "__main__":
    app.run()

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import re
    import time
    from datetime import date, datetime, timedelta, timezone
    from pathlib import Path

    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import polars as pl
    from pypdf import PdfReader
    from shapely.geometry import Point

    import nightlight as nl

    started = time.time()
    outputs = Path(__file__).parent / "outputs"
    outputs.mkdir(exist_ok=True)
    return (
        Point,
        PdfReader,
        date,
        datetime,
        gpd,
        json,
        mo,
        nl,
        np,
        outputs,
        pl,
        plt,
        re,
        started,
        time,
        timedelta,
        timezone,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Can satellite night light check DTE's July 2026 storm restoration report?

    On July 3, 2026 a fast storm cut power to nearly 450,000 DTE Electric customers in
    Southeast Michigan. DTE told the Michigan Public Service Commission (Case U-22156) that
    44% were back within 24 hours, 70% within 48, 88% within 72 and 99% after 4.6 days, and
    that its own smart meters reported for only about 45% of customers at the peak.

    The question: does NASA's Black Marble night light, which anyone can download, show the
    same curve, and does it still see the territory in the hours when DTE's meters went quiet?
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. DTE's own numbers, read from the filing

    We download DTE's report from the MPSC docket and pull the restoration sentence, the
    customer count and the meter-reporting figure out of its text, so every number below
    traces back to the filing.
    """)
    return


@app.cell
def _(PdfReader, nl, re):
    filing_url = (
        "https://mi-psc.my.site.com/sfc/servlet.shepherd/version/download/068cs00002PhWOeAAN"
    )
    filing_path = nl.download(filing_url, nl.cache_dir() / "dte_storm_report_u22156.pdf")
    filing_text = " ".join(page.extract_text() or "" for page in PdfReader(filing_path).pages)
    filing_text = re.sub(r"\s+", " ", filing_text)

    restoration_sentence = re.search(r"Of the total affected customer population,.*?July 9\.", filing_text)
    assert restoration_sentence, "restoration sentence not found in the filing"
    shares = [int(s) for s in re.findall(r"(\d+)% (?:were restored )?(?:within|after)", restoration_sentence[0])]
    assert shares == [44, 70, 88, 99], f"unexpected restoration shares {shares}"

    affected_match = re.search(r"nearly ([\d,]+) customers impacted", filing_text)
    served_match = re.search(r"~([\d.]+) million electric customers", filing_text)
    meters_match = re.search(r"[Mm]eter reporting fell to about (\d+)%", filing_text)
    assert affected_match and served_match and meters_match, "filing figures not found"
    customers_affected = int(affected_match[1].replace(",", ""))
    customers_served = float(served_match[1]) * 1e6
    meter_reporting = int(meters_match[1])

    # Hours after 16:00 EDT on July 3, the filing's own clock (24 h = 16:00 July 4, 99% at
    # 07:00 July 8, the last customers "in the early morning on July 9", taken as 04:00).
    dte_hours = [0, 24, 48, 72, 111, 132]
    dte_restored = [0.0, 0.44, 0.70, 0.88, 0.99, 1.0]
    print(restoration_sentence[0])
    print(f"affected {customers_affected:,}, served {customers_served:,.0f}, meters reporting at peak {meter_reporting}%")
    return customers_affected, customers_served, dte_hours, dte_restored, meter_reporting


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. DTE's territory from HIFLD Next

    HIFLD Next's Electric Retail Service Territories layer has one polygon per utility. DTE's
    polygon turns out to cover far more than DTE serves: it is built from every county where
    DTE reports customers to EIA, so it includes pieces of northern Michigan and the Upper
    Peninsula. We keep the piece that contains Detroit, which is close to DTE's published
    size of about 7,600 square miles (19,700 km²).
    """)
    return


@app.cell
def _(Point, gpd, nl):
    territories_url = (
        "https://hifld.publicenvirodata.org/storage/hifld/electric-retail-service-territories/"
        "electric-retail-service-territories/v1.0.0/geoparquet/electric-retail-service-territories.parquet"
    )
    territories = gpd.read_parquet(nl.download(territories_url, nl.cache_dir() / "territories.parquet"))
    dte_all = territories[territories["NAME"] == "DTE ELECTRIC COMPANY"].to_crs(4326)
    assert len(dte_all) == 1, "expected one DTE polygon"
    dte_parts = dte_all.explode(index_parts=False).reset_index(drop=True)
    detroit = Point(-83.05, 42.33)
    territory = dte_parts[dte_parts.contains(detroit)].reset_index(drop=True)
    assert len(territory) == 1, "no DTE piece contains Detroit"

    hifld_area_km2 = float(dte_all.to_crs(5070).area.sum() / 1e6)
    territory_area_km2 = float(territory.to_crs(5070).area.sum() / 1e6)
    print(f"HIFLD DTE polygon {hifld_area_km2:,.0f} km² in {len(dte_parts)} parts; "
          f"piece with Detroit {territory_area_km2:,.0f} km². HIFLD lists {int(dte_all['CUSTOMERS'].iloc[0]):,} customers.")
    return hifld_area_km2, territory, territory_area_km2


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Counties and census tracts inside the territory

    Census cartographic boundaries (2024). A county counts if at least 10% of it lies in the
    territory and is clipped to it; a tract counts if at least half of it does.
    """)
    return


@app.cell
def _(gpd, nl, territory):
    census = "https://www2.census.gov/geo/tiger/GENZ2024/shp/"
    county_zip = nl.download(census + "cb_2024_us_county_500k.zip", nl.cache_dir() / "cb_2024_us_county_500k.zip")
    tract_zip = nl.download(census + "cb_2024_26_tract_500k.zip", nl.cache_dir() / "cb_2024_26_tract_500k.zip")
    all_counties = gpd.read_file(county_zip).query("STATEFP == '26'").to_crs(4326)
    all_tracts = gpd.read_file(tract_zip).to_crs(4326)

    def inside(zones: gpd.GeoDataFrame, min_share: float) -> gpd.GeoDataFrame:
        zones = zones.copy()
        full_area = zones.to_crs(5070).area
        zones["geometry"] = zones.intersection(territory.geometry.iloc[0])
        share = zones.to_crs(5070).area / full_area
        return zones[share >= min_share].reset_index(drop=True)

    counties = inside(all_counties, 0.10)[["GEOID", "NAME", "geometry"]]
    tracts = inside(all_tracts, 0.50)[["GEOID", "NAMELSADCO", "geometry"]]
    print(f"{len(counties)} counties, {len(tracts)} tracts in the territory")
    return counties, tracts


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Night light, 30 nights before to 30 nights after

    NASA's Black Marble HDF5 files need an Earthdata login. The same product (gap-filled,
    BRDF-corrected radiance, here from NOAA-20, VJ146A2) is public on NASA GIBS as colored
    images; `nightlight.py` turns the colors back into radiance using GIBS's published color
    map. Gap-filled means cloudy pixels are filled with an earlier clear value, so we drop
    every pixel that VIIRS's cloud mask does not rate at least 95% confident clear. Nights are
    UTC dates; NOAA-20 passes over Detroit at about 07:00 UTC, 03:00 EDT.
    """)
    return


@app.cell
def _(date, nl, territory, time, timedelta):
    west, south, east, north = territory.total_bounds
    snap = 1 / nl.PIXELS_PER_DEGREE
    grid = nl.Grid(
        round(west // snap * snap, 6), round(south // snap * snap, 6),
        round(-(-east // snap) * snap, 6), round(-(-north // snap) * snap, 6),
    )
    storm_night = date(2026, 7, 4)  # first overpass after the storm
    nights = [storm_night + timedelta(days=d) for d in range(-31, 30)]
    fetch_started = time.time()
    radiance, clear = nl.nightly_stack("NOAA20", nights, grid)
    fetch_seconds = time.time() - fetch_started
    gibs_bytes = sum(p.stat().st_size for p in (nl.cache_dir() / "gibs").rglob("*.png"))
    print(f"grid {grid.shape}, {len(nights)} nights, {fetch_seconds:.0f} s, GIBS cache {gibs_bytes / 1e6:.0f} MB")
    return clear, fetch_seconds, grid, nights, radiance, storm_night


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Usual brightness and "dark" pixels

    A pixel's usual brightness is its median on the clear nights of the 30 before the storm.
    Lit pixels are those usually at least 5 nW/cm²/sr: streets, homes and businesses rather
    than fields. A lit pixel is dark on a night when it is clear and below half its usual
    brightness. The GIBS color map tops out at 38.2, so for the brightest pixels we only know
    a lower bound; below 19.1 still certainly means below half.
    """)
    return


@app.cell
def _(clear, grid, nights, nl, np, radiance, storm_night, territory):
    pre = np.array([n < storm_night for n in nights])
    usual = nl.usual_brightness(radiance[pre], clear[pre])
    in_territory = nl.zone_index(territory, grid) == 0
    lit = in_territory & (usual >= nl.LIT_RADIANCE)
    dark = nl.dark_pixels(radiance, usual)
    saturated_share = float((usual[lit] >= nl.SATURATION).mean())
    print(f"{lit.sum():,} lit pixels in the territory, {saturated_share:.1%} saturated in the GIBS images")
    return dark, lit, pre, saturated_share, usual


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. The territory night by night, against DTE's curve

    For each night: the share of lit pixels with a clear view, and of those, the share dark.
    DTE's filing gives the share of *affected* customers restored; multiplying the share still
    out by 450,000 / 2.3 million gives the share of all DTE customers still dark at each
    overpass, the number night light should match. The pre-storm nights show how often a
    lit pixel reads dark with nothing wrong (the noise floor).
    """)
    return


@app.cell
def _(
    clear,
    customers_affected,
    customers_served,
    dark,
    datetime,
    dte_hours,
    dte_restored,
    lit,
    nights,
    np,
    pl,
    pre,
    timezone,
):
    storm_time = datetime(2026, 7, 3, 20, 0, tzinfo=timezone.utc)  # 16:00 EDT
    overpass_hour_utc = 7.0
    hours_after = [
        (datetime(n.year, n.month, n.day, tzinfo=timezone.utc) - storm_time).total_seconds() / 3600
        + overpass_hour_utc
        for n in nights
    ]
    clear_lit = (clear & lit).sum(axis=(1, 2))
    dark_lit = (clear & dark & lit).sum(axis=(1, 2))
    clear_share = clear_lit / lit.sum()
    with np.errstate(all="ignore"):
        dark_share = np.where(clear_lit > 0, dark_lit / clear_lit, np.nan)
    dte_out_share = [
        (1 - float(np.interp(h, dte_hours, dte_restored))) * customers_affected / customers_served
        if h >= 0 else 0.0
        for h in hours_after
    ]
    territory_nights = pl.DataFrame({
        "night": nights, "hours_after_storm": np.round(hours_after, 1),
        "clear_share": clear_share, "dark_share": dark_share, "dte_out_share": dte_out_share,
    })
    clear_enough = 0.5
    noise = territory_nights.filter(pl.Series(pre) & (pl.col("clear_share") >= clear_enough))
    noise_floor = float(noise["dark_share"].quantile(0.95))
    noise_median = float(noise["dark_share"].median())
    print(f"normal-night dark share: median {noise_median:.2%}")
    print(f"noise floor: {noise_floor:.2%} of clear lit pixels read dark on a normal night (95th pct of {len(noise)} clear pre-storm nights)")
    territory_nights.filter(pl.col("hours_after_storm") > -30).head(10)
    return clear_enough, hours_after, noise_floor, noise_median, territory_nights


@app.cell
def _(clear_enough, noise_floor, pl, territory_nights):
    after = territory_nights.filter(pl.col("hours_after_storm") > 0)
    first_48h = after.filter(pl.col("hours_after_storm") <= 48)
    first_clear = after.filter(pl.col("clear_share") >= clear_enough).row(0, named=True)
    first_clear_excess = first_clear["dark_share"] - noise_floor
    post_clear_nights = after.filter(pl.col("clear_share") >= clear_enough).height
    print(f"first 48 hours: best clear view {first_48h['clear_share'].max():.1%} of lit pixels")
    print(f"first clear night {first_clear['night']} at {first_clear['hours_after_storm']} h: "
          f"{first_clear['dark_share']:.2%} dark (noise floor {noise_floor:.2%}); DTE implies {first_clear['dte_out_share']:.2%} of customers still out")
    print(f"{post_clear_nights} of {after.height} post-storm nights had at least half the territory clear")
    return first_48h, first_clear, first_clear_excess, post_clear_nights


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. The picture: what the satellite saw over the first five nights

    Raw (not gap-filled) NOAA-20 day/night band radiance from GIBS, same scale for all six
    nights: July 1 before the storm, then each night after. On July 4, 5 and 6 the city lights
    are smeared through cloud.
    """)
    return


@app.cell
def _(date, grid, nl, np, outputs, plt):
    strip_nights = [date(2026, 7, d) for d in (1, 4, 5, 6, 7, 8)]
    radiance_map = nl.load_colormap(nl.RADIANCE_COLORMAP)
    fig_strip, axes_strip = plt.subplots(1, 6, figsize=(18, 4.2))
    for ax_s, n_s in zip(axes_strip, strip_nights):
        raw = nl.decode(nl.fetch_png("VIIRS_NOAA20_DayNightBand_At_Sensor_Radiance", n_s, grid), radiance_map)
        ax_s.imshow(np.log1p(raw), cmap="gray", vmin=0, vmax=np.log1p(38.2))
        ax_s.set_title(n_s.strftime("%b %-d (UTC)"))
        ax_s.axis("off")
    fig_strip.suptitle("NOAA-20 night light over DTE's territory, raw day/night band radiance")
    fig_strip.tight_layout()
    fig_strip.savefig(outputs / "nights_strip.png", dpi=110)
    fig_strip
    return


@app.cell
def _(clear_enough, noise_floor, outputs, pl, plt, territory_nights):
    window = territory_nights.filter(pl.col("hours_after_storm").is_between(-7 * 24, 30 * 24))
    clear_rows = window.filter(pl.col("clear_share") >= clear_enough)
    fig_curve, (ax_top, ax_bottom) = plt.subplots(2, 1, figsize=(10, 6.5), sharex=True, height_ratios=[3, 1])
    ax_top.plot(window["hours_after_storm"] / 24, window["dte_out_share"] * 100, color="black", label="DTE filing: customers still out, % of all DTE customers")
    ax_top.scatter(clear_rows["hours_after_storm"] / 24, clear_rows["dark_share"] * 100, color="tab:orange", zorder=3, label="Night light: lit pixels dark, % of clear lit pixels")
    ax_top.axhline(noise_floor * 100, color="tab:orange", linestyle=":", label="Night light noise floor (normal nights)")
    ax_top.set_ylabel("%")
    ax_top.legend(loc="upper right", fontsize=8)
    ax_top.set_title("DTE Storm 2026004: reported restoration vs. what night light could see")
    ax_bottom.bar(window["hours_after_storm"] / 24, window["clear_share"] * 100, width=0.8, color="tab:blue")
    ax_bottom.set_ylabel("clear view, %")
    ax_bottom.set_xlabel("days after 16:00 EDT, July 3, 2026 (NOAA-20 overpass about 03:00 EDT)")
    for ax_c in (ax_top, ax_bottom):
        ax_c.axvspan(0, 2, color="grey", alpha=0.15)
    ax_top.text(0.05, ax_top.get_ylim()[1] * 0.9, "first 48 h", fontsize=8)
    fig_curve.tight_layout()
    fig_curve.savefig(outputs / "territory_curve.png", dpi=120)
    fig_curve
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. Counties and tracts on the first clear nights

    DTE's filing gives one curve for the whole territory, not county numbers, and EAGLE-I's
    county outage counts for 2026 are not published yet (its public record ends December 31,
    2025). So the county test is weaker than planned: we compare each county's dark share,
    less the noise floor, with DTE's territory-wide share still out, and flag counties that
    were darker than that, which is where restoration may have lagged.
    """)
    return


@app.cell
def _(
    clear,
    clear_enough,
    counties,
    dark,
    first_clear,
    grid,
    lit,
    nights,
    nl,
    noise_floor,
    np,
    pl,
    tracts,
):
    def zone_table(zones, id_col: str, label_col: str) -> pl.DataFrame:
        counts = nl.zone_nights(nl.zone_index(zones, grid), lit, clear, dark)
        rows = []
        for i, night in enumerate(nights):
            with np.errstate(all="ignore"):
                share_clear = counts["clear"][i] / counts["lit"]
                share_dark = counts["dark"][i] / counts["clear"][i]
            rows.append(pl.DataFrame({
                "zone": zones[id_col], "name": zones[label_col], "night": night,
                "lit_pixels": counts["lit"], "clear_share": share_clear, "dark_share": share_dark,
            }))
        return pl.concat(rows).with_columns(
            pl.col("clear_share").fill_nan(None), pl.col("dark_share").fill_nan(None)
        )

    county_nights = zone_table(counties, "GEOID", "NAME")
    tract_nights = zone_table(tracts, "GEOID", "NAMELSADCO")

    def first_clear_night(table: pl.DataFrame, margin: float) -> pl.DataFrame:
        night = table.filter(
            (pl.col("night") == first_clear["night"]) & (pl.col("lit_pixels") >= 20)
        )
        return night.with_columns(
            clear_reading=pl.col("clear_share") >= clear_enough,
            excess_dark=(pl.col("dark_share") - noise_floor).clip(lower_bound=0),
        ).with_columns(
            within_margin=(pl.col("excess_dark") - first_clear["dte_out_share"]).abs() <= margin,
            darker_than_dte=pl.col("excess_dark") > first_clear["dte_out_share"] + margin,
        )

    margin_points = 0.05
    county_first = first_clear_night(county_nights, margin_points)
    tract_first = first_clear_night(tract_nights, margin_points)
    county_nights.write_csv(outputs / "county_nights.csv")
    tract_first.write_csv(outputs / "tracts_first_clear_night.csv")
    county_first.select("name", "lit_pixels", "clear_share", "dark_share", "excess_dark", "within_margin", "darker_than_dte").sort("excess_dark", descending=True)
    return county_first, county_nights, margin_points, tract_first, tract_nights


@app.cell
def _(county_first, first_48h, margin_points, pl, tract_first, tract_nights):
    def counts(table: pl.DataFrame) -> dict[str, int]:
        readable = table.filter(pl.col("clear_reading"))
        return {
            "zones": table.height,
            "clear": readable.height,
            "within": int(readable["within_margin"].sum()),
            "darker": int(readable["darker_than_dte"].sum()),
        }

    county_counts = counts(county_first)
    tract_counts = counts(tract_first)
    tracts_clear_48h = (
        tract_nights.filter(pl.col("night").is_in(first_48h["night"].to_list()) & (pl.col("clear_share") >= 0.5))
        ["zone"].n_unique()
    )
    print(f"counties: {county_counts['within']} of {county_counts['clear']} with a clear reading within {margin_points:.0%} points of DTE ({county_counts['zones']} in territory); {county_counts['darker']} darker")
    print(f"tracts:   {tract_counts['within']} of {tract_counts['clear']} within; {tract_counts['darker']} darker; {tracts_clear_48h} of {tract_counts['zones']} had a clear reading in the first 48 h")
    return county_counts, tract_counts, tracts_clear_48h


@app.cell
def _(outputs, plt, tract_first, tracts):
    tract_map = tracts.merge(tract_first.to_pandas()[["zone", "excess_dark", "clear_reading"]], left_on="GEOID", right_on="zone", how="left")
    fig_map, ax_map = plt.subplots(figsize=(7, 8))
    tract_map[~tract_map["clear_reading"].fillna(False).astype(bool)].plot(ax=ax_map, color="lightgrey")
    tract_map["excess_pct"] = tract_map["excess_dark"] * 100
    tract_map[tract_map["clear_reading"].fillna(False).astype(bool)].plot(
        ax=ax_map, column="excess_pct", cmap="magma_r", vmin=0, vmax=30, legend=True,
        legend_kwds={"label": "lit pixels dark beyond the noise floor, %"},
    )
    ax_map.set_title("First clear night after the storm, by census tract (grey: no clear reading)")
    ax_map.axis("off")
    fig_map.tight_layout()
    fig_map.savefig(outputs / "tracts_first_clear_night.png", dpi=110)
    fig_map
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 9. Numbers for the README

    Written to `outputs/summary_restoration.json` so the README quotes this run.
    """)
    return


@app.cell
def _(
    county_counts,
    county_nights,
    customers_affected,
    customers_served,
    fetch_seconds,
    first_48h,
    first_clear,
    first_clear_excess,
    hifld_area_km2,
    json,
    margin_points,
    meter_reporting,
    nights,
    nl,
    noise_floor,
    noise_median,
    outputs,
    post_clear_nights,
    saturated_share,
    started,
    territory_area_km2,
    time,
    tract_counts,
    tracts_clear_48h,
):
    gibs_mb = sum(p.stat().st_size for p in (nl.cache_dir() / "gibs").rglob("*.png")) / 1e6
    summary = {
        "customers_affected": customers_affected,
        "customers_served": customers_served,
        "meter_reporting_at_peak_pct": meter_reporting,
        "hifld_polygon_km2": round(hifld_area_km2),
        "territory_km2": round(territory_area_km2),
        "nights_fetched": len(nights),
        "first_48h_best_clear_share": round(float(first_48h["clear_share"].max()), 4),
        "first_clear_night": str(first_clear["night"]),
        "first_clear_hours_after_storm": first_clear["hours_after_storm"],
        "first_clear_dark_share": round(first_clear["dark_share"], 4),
        "first_clear_excess_dark": round(first_clear_excess, 4),
        "first_clear_dte_out_share": round(first_clear["dte_out_share"], 4),
        "noise_floor": round(noise_floor, 4),
        "noise_median": round(noise_median, 4),
        "post_storm_nights_half_clear": post_clear_nights,
        "margin_points": margin_points,
        "counties": county_counts,
        "tracts": tract_counts,
        "tracts_clear_first_48h": tracts_clear_48h,
        "county_nights_rows": county_nights.height,
        "saturated_lit_share": round(saturated_share, 4),
        "gibs_megabytes": round(gibs_mb, 1),
        "fetch_seconds": round(fetch_seconds),
        "run_seconds": round(time.time() - started),
        "cost_usd": 0,
    }
    (outputs / "summary_restoration.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What didn't work, and what this doesn't show

    - **The first three nights were cloudy.** VIIRS's cloud mask rates almost none of the
      territory clear on July 4, 5 and 6, and the raw images agree. By the first clear night
      DTE says about 91% of affected customers were already back, so night light cannot check
      the part of the curve that mattered most, the hours when meter reporting fell.
    - **No county answer key.** DTE files one territory curve; EAGLE-I's 2026 county counts
      are not public yet. `comparison.py` tests the same method against EAGLE-I on DTE's
      August 2023 storm and on four other storms instead.
    - **HIFLD's DTE polygon is about 3.5 times too big**, so we keep the piece around Detroit.
    - **GIBS images are not the HDF5 product**: radiance comes in bins and saturates at
      38.2 nW/cm²/sr, and we cannot read Black Marble's own quality flags. With an Earthdata
      login the same notebook could read the HDF5 files instead.
    """)
    return


if __name__ == "__main__":
    app.run()

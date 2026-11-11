import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import time
    from datetime import date, timedelta
    from pathlib import Path

    import duckdb
    import geopandas as gpd
    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import polars as pl

    import nightlight as nl

    started = time.time()
    outputs = Path(__file__).parent / "outputs"
    outputs.mkdir(exist_ok=True)
    return date, duckdb, gpd, json, mo, nl, np, outputs, pl, plt, started, time, timedelta


@app.cell
def _(mo):
    mo.md(r"""
    # How well does night light agree with reported outages in general?

    DTE's July 2026 storm has no county answer key: DTE filed one territory curve, and DOE's
    EAGLE-I county outage counts stop at December 31, 2025. So we test night light where
    EAGLE-I does exist:

    1. **DTE's own August 2023 storm** (FEMA DR-4757), run through exactly the same GIBS
       night-light method as `restoration.py`, county by county against EAGLE-I.
    2. **Five summer storms** in Heimdall Research's Storm Blackout tables (CC BY 4.0), which
       measure night light from the Black Marble HDF5 files with NASA's quality flags. We
       join Heimdall's county nights to EAGLE-I at the satellite's overpass time.
    3. **Every storm in Heimdall's tables**: how often night light had a clear view in the
       first two nights at all.

    EAGLE-I is scraped from utility outage maps, so it is the utilities' own count, not an
    independent one. It is the best public county answer key there is.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## EAGLE-I at the overpass

    EAGLE-I gives customers out per county every 15 minutes, in UTC, and leaves out rows with
    nobody out. NOAA-20 and Suomi NPP cross at about 01:30 local solar time, so each county's
    overpass is 1.5 h + longitude/15 in UTC. We average EAGLE-I's readings within 30 minutes
    of it and divide by EAGLE-I's modeled customers per county (MCC.csv).
    """)
    return


@app.cell
def _(duckdb, gpd, nl, np, pl):
    figshare = "https://ndownloader.figshare.com/files/"
    eaglei_files = {2023: "44574907", 2024: "53581661"}
    mcc = pl.read_csv(
        nl.download(figshare + "42547708", nl.cache_dir() / "eaglei_MCC.csv"), infer_schema_length=0
    )
    mcc = mcc.rename({mcc.columns[0]: "County_FIPS"})  # the file starts with a byte-order mark
    mcc = mcc.select(
        geoid=pl.col("County_FIPS").str.zfill(5), customers=pl.col("Customers").cast(pl.Float64)
    )

    county_zip = nl.download(
        nl.CENSUS + "cb_2024_us_county_500k.zip", nl.cache_dir() / "cb_2024_us_county_500k.zip"
    )
    county_shapes = gpd.read_file(county_zip).to_crs(4326)
    centroid_lon = county_shapes.to_crs(5070).centroid.to_crs(4326).x
    overpass_hours = pl.DataFrame(
        {"geoid": county_shapes["GEOID"], "overpass_utc": 1.5 - centroid_lon.to_numpy() / 15}
    )

    def eaglei_at_overpass(geoids: list[str], nights: list) -> pl.DataFrame:
        """Customers out and share out per county and night, at that county's overpass."""
        years = {n.year for n in nights}
        assert len(years) == 1 and years <= set(eaglei_files), f"no EAGLE-I file for {years}"
        year = years.pop()
        path = nl.download(
            figshare + eaglei_files[year], nl.cache_dir() / f"eaglei_outages_{year}.csv"
        )
        start, end = min(nights), max(nights)
        header = path.open().readline().strip().split(",")
        count_column = "sum" if "sum" in header else "customers_out"  # renamed in 2024
        rows = duckdb.sql(f"""
            SELECT lpad(fips_code, 5, '0') AS geoid, run_start_time AS t, "{count_column}" AS out
            FROM read_csv('{path}', types={{'fips_code': 'VARCHAR', 'run_start_time': 'TIMESTAMP'}})
            WHERE lpad(fips_code, 5, '0') IN ({",".join(f"'{g}'" for g in geoids)})
              AND run_start_time >= DATE '{start}'
              AND run_start_time < DATE '{end}' + INTERVAL 1 DAY
        """).pl()
        grid = pl.DataFrame({"geoid": geoids}).join(pl.DataFrame({"night": nights}), how="cross")
        grid = grid.join(overpass_hours, on="geoid", how="left")
        readings = rows.with_columns(
            night=pl.col("t").dt.date(), hour=pl.col("t").dt.hour() + pl.col("t").dt.minute() / 60
        )
        matched = (
            grid.join(readings, on=["geoid", "night"], how="left")
            .filter((pl.col("hour") - pl.col("overpass_utc")).abs() <= 0.5)
            .group_by("geoid", "night")
            .agg(customers_out=pl.col("out").mean())
        )
        joined = grid.join(matched, on=["geoid", "night"], how="left").join(
            mcc, on="geoid", how="left"
        )
        return (
            joined.with_columns(
                customers_out=pl.col("customers_out").fill_null(0.0),
            )
            .with_columns(out_share=(pl.col("customers_out") / pl.col("customers")).clip(0, 1))
            .drop("overpass_utc")
        )

    assert overpass_hours["overpass_utc"].is_finite().all()
    return county_shapes, eaglei_at_overpass


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. DTE's August 24, 2023 storm, same method as July 2026

    Severe storms and tornadoes hit Southeast Michigan on the evening of August 24, 2023; FEMA
    declared it DR-4757. Same territory, counties, satellite (NOAA-20), cloud mask, usual
    brightness and "dark" rule as `restoration.py`.
    """)
    return


@app.cell
def _(date, nl, np, timedelta):
    territory, _, _ = nl.dte_territory()
    counties, _ = nl.zones_inside(territory)
    grid = nl.grid_for(territory)
    storm_night = date(2023, 8, 25)  # first overpass after the storm (about 03:00 EDT)
    nights = [storm_night + timedelta(days=d) for d in range(-31, 30)]
    radiance, clear = nl.nightly_stack("NOAA20", nights, grid)
    pre = np.array([n < storm_night for n in nights])
    usual = nl.usual_brightness(radiance[pre], clear[pre])
    lit = (nl.zone_index(territory, grid) == 0) & (usual >= nl.LIT_RADIANCE)
    dark = nl.dark_pixels(radiance, usual)
    counts = nl.zone_nights(nl.zone_index(counties, grid), lit, clear, dark)
    print(f"{len(counties)} counties, {lit.sum():,} lit pixels")
    return clear, counties, counts, dark, lit, nights, pre, storm_night


@app.cell
def _(
    clear,
    counties,
    counts,
    dark,
    eaglei_at_overpass,
    lit,
    nights,
    np,
    pl,
    pre,
    storm_night,
    timedelta,
):
    with np.errstate(all="ignore"):
        county_light = pl.concat(
            [
                pl.DataFrame(
                    {
                        "geoid": counties["GEOID"],
                        "name": counties["NAME"],
                        "night": n,
                        "lit_pixels": counts["lit"],
                        "clear_share": counts["clear"][i] / counts["lit"],
                        "dark_share": counts["dark"][i] / counts["clear"][i],
                    }
                )
                for i, n in enumerate(nights)
            ]
        ).with_columns(pl.col("clear_share").fill_nan(None), pl.col("dark_share").fill_nan(None))

    territory_clear = (clear & lit).sum(axis=(1, 2))
    territory_dark = (clear & dark & lit).sum(axis=(1, 2))
    territory_2023 = pl.DataFrame(
        {
            "night": nights,
            "clear_share": territory_clear / lit.sum(),
            "dark_share": np.where(
                territory_clear > 0, territory_dark / np.maximum(territory_clear, 1), np.nan
            ),
        }
    ).with_columns(pl.col("dark_share").fill_nan(None))
    normal = territory_2023.filter(pl.Series(pre) & (pl.col("clear_share") >= 0.5))
    noise_median_2023 = float(normal["dark_share"].median())
    noise_floor_2023 = float(normal["dark_share"].quantile(0.95))

    outages_2023 = eaglei_at_overpass(counties["GEOID"].to_list(), nights)
    dr4757 = county_light.join(outages_2023, on=["geoid", "night"], how="left").with_columns(
        days_after=(pl.col("night") - storm_night).dt.total_days(),
        excess_dark=(pl.col("dark_share") - noise_median_2023).clip(lower_bound=0),
    )
    territory_2023 = (
        territory_2023.join(
            outages_2023.group_by("night").agg(
                pl.col("customers_out").sum(), pl.col("customers").sum()
            ),
            on="night",
        )
        .with_columns(out_share=pl.col("customers_out") / pl.col("customers"))
        .sort("night")
    )
    print(
        f"normal nights: median dark share {noise_median_2023:.2%}, "
        f"95th pct {noise_floor_2023:.2%} ({normal.height} clear nights)"
    )
    territory_2023.filter(
        pl.col("night").is_between(storm_night - timedelta(days=2), storm_night + timedelta(days=6))
    )
    return dr4757, noise_floor_2023, noise_median_2023, territory_2023


@app.cell
def _(dr4757, pl):
    post = dr4757.filter(pl.col("days_after").is_between(0, 6) & (pl.col("lit_pixels") >= 20))
    readable = post.filter(pl.col("clear_share") >= 0.5)
    first_48h_2023 = post.filter(pl.col("days_after") <= 1)
    dr4757_stats = {
        "county_nights": post.height,
        "clear_county_nights": readable.height,
        "first_48h_clear_county_nights": int((first_48h_2023["clear_share"] >= 0.5).sum()),
        "first_48h_county_nights": first_48h_2023.height,
        "spearman": readable.select(pl.corr("excess_dark", "out_share", method="spearman")).item(),
        "within_5_points": int(
            ((readable["excess_dark"] - readable["out_share"]).abs() <= 0.05).sum()
        ),
        "within_10_points": int(
            ((readable["excess_dark"] - readable["out_share"]).abs() <= 0.10).sum()
        ),
        "peak_county_out_share": float(post["out_share"].max()),
    }
    print(dr4757_stats)
    readable.select("name", "night", "clear_share", "dark_share", "excess_dark", "out_share").sort(
        "out_share", descending=True
    ).head(15)
    return dr4757_stats, readable


@app.cell
def _(noise_floor_2023, outputs, pl, plt, readable, storm_night, territory_2023):
    fig_2023, (ax_t, ax_s) = plt.subplots(1, 2, figsize=(13, 4.8))
    window_2023 = territory_2023.with_columns(
        days=(pl.col("night") - storm_night).dt.total_days()
    ).filter(pl.col("days").is_between(-7, 14))
    clear_2023 = window_2023.filter(pl.col("clear_share") >= 0.5)
    ax_t.plot(
        window_2023["days"],
        window_2023["out_share"] * 100,
        color="black",
        marker=".",
        label="EAGLE-I: customers out at overpass, %",
    )
    ax_t.scatter(
        clear_2023["days"],
        clear_2023["dark_share"] * 100,
        color="tab:orange",
        zorder=3,
        label="Night light: lit pixels dark, % (clear nights)",
    )
    ax_t.axhline(
        noise_floor_2023 * 100, color="tab:orange", linestyle=":", label="Night light noise floor"
    )
    ax_t.set_xlabel("nights after the storm (Aug 25, 2023 = 0)")
    ax_t.set_ylabel("% of territory")
    ax_t.set_title("DTE territory, DR-4757")
    ax_t.legend(fontsize=8)
    ax_s.scatter(
        readable["out_share"] * 100,
        readable["excess_dark"] * 100,
        c=readable["days_after"],
        cmap="viridis",
    )
    ax_s.plot([0, 40], [0, 40], color="grey", linestyle="--")
    ax_s.set_xlabel("EAGLE-I customers out, % of county")
    ax_s.set_ylabel("night light: lit pixels dark beyond normal, %")
    ax_s.set_title("County nights with a clear view, nights 0-6 (color: night)")
    fig_2023.tight_layout()
    fig_2023.savefig(outputs / "dr4757_comparison.png", dpi=110)
    fig_2023
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Five summer storms, with Heimdall's night light

    Heimdall's `county_daily` table gives each county's mean radiance per night, its share of
    valid (clear, good-quality) pixels and its ratio to the usual brightness. We keep county
    nights with at least half their pixels valid, take 1 − light ratio as the night-light
    deficit, and compare it with EAGLE-I's share out at the overpass. Heimdall's own score
    over all its storms (AUC, the chance a county with 10%+ out is darker than one with
    under 1% out; 0.5 is a coin flip) comes from its `validation_pooled.csv`. It can't score
    most single storms: they have too few counties with under 1% out.
    """)
    return


@app.cell
def _(nl, pl):
    zenodo = "https://zenodo.org/api/records/23010005/files/"
    heimdall_daily = nl.download(
        zenodo + "data__county_daily.parquet/content",
        nl.cache_dir() / "heimdall_county_daily.parquet",
    )
    heimdall_summary = pl.read_csv(
        nl.download(
            zenodo + "data__county_summary.csv/content",
            nl.cache_dir() / "heimdall_county_summary.csv",
        ),
        infer_schema_length=0,
    )
    heimdall_pooled = pl.read_csv(
        nl.download(
            zenodo + "data__validation_pooled.csv/content",
            nl.cache_dir() / "heimdall_validation_pooled.csv",
        )
    )
    heimdall_auc = heimdall_pooled.filter(pl.col("scope") == "all").select(
        "measure", "n_storms", "n_counties", "auc", "ci_boot_low", "ci_boot_high"
    )
    print("Heimdall's own pooled score, all storms:")
    print(heimdall_auc)
    heimdall_storms = pl.read_csv(
        nl.download(zenodo + "data__storms.csv/content", nl.cache_dir() / "heimdall_storms.csv"),
        infer_schema_length=0,
    )
    comparison_storms = ["DR-4757", "DR-4721", "DR-4728", "AL022024", "DR-4804"]
    heimdall_storms.filter(pl.col("event_id").is_in(comparison_storms)).select(
        "event_id", "name", "landfall", "states", "product"
    )
    return comparison_storms, heimdall_auc, heimdall_daily, heimdall_storms, heimdall_summary


@app.cell
def _(
    comparison_storms,
    duckdb,
    eaglei_at_overpass,
    heimdall_daily,
    heimdall_summary,
    pl,
    timedelta,
):
    storm_rows = []
    storm_pairs = []
    for event in comparison_storms:
        declared = heimdall_summary.filter(
            (pl.col("event_id") == event) & (pl.col("declared") == "True")
        )
        impact = declared.select(pl.col("impact_date").str.to_date()).to_series()
        impact_by_county = declared.select(
            geoid="geoid", impact=pl.col("impact_date").str.to_date()
        )
        nights_e = [impact.min() + timedelta(days=d) for d in range(1, 8)]
        light = (
            duckdb.sql(f"""
            SELECT geoid, date AS night, light_ratio, valid_pixel_share
            FROM read_parquet('{heimdall_daily}')
            WHERE event_id = '{event}' AND declared
        """)
            .pl()
            .with_columns(pl.col("night").cast(pl.Date))
        )
        out = eaglei_at_overpass(declared["geoid"].to_list(), nights_e)
        pairs = (
            light.join(impact_by_county, on="geoid")
            .with_columns(days_after=(pl.col("night") - pl.col("impact")).dt.total_days())
            .filter(pl.col("days_after").is_between(1, 7))
            .join(out, on=["geoid", "night"], how="inner")
            .with_columns(deficit=(1 - pl.col("light_ratio")).clip(0, 1), event_id=pl.lit(event))
        )
        clear_pairs = pairs.filter(pl.col("valid_pixel_share") >= 0.5)
        first_two = pairs.filter(pl.col("days_after") <= 2)
        storm_rows.append(
            {
                "event_id": event,
                "declared_counties": declared.height,
                "county_nights": len(declared) * 7,
                "clear_county_nights": clear_pairs.height,
                "first_48h_clear_share": float(
                    (first_two["valid_pixel_share"] >= 0.5).sum() / max(declared.height * 2, 1)
                ),
                "spearman": clear_pairs.select(
                    pl.corr("deficit", "out_share", method="spearman")
                ).item(),
                "within_10_points": float(
                    ((clear_pairs["deficit"] - clear_pairs["out_share"]).abs() <= 0.10).mean()
                ),
                "mean_out_share": float(clear_pairs["out_share"].mean()),
                "mean_deficit": float(clear_pairs["deficit"].mean()),
            }
        )
        storm_pairs.append(clear_pairs)
    storm_table = pl.DataFrame(storm_rows)
    all_pairs = pl.concat(storm_pairs)
    pooled_spearman = all_pairs.select(pl.corr("deficit", "out_share", method="spearman")).item()
    print(f"pooled Spearman over {all_pairs.height} clear county nights: {pooled_spearman:.2f}")
    storm_table
    return all_pairs, pooled_spearman, storm_table


@app.cell
def _(all_pairs, outputs, plt):
    fig_pairs, ax_p = plt.subplots(figsize=(6.5, 5.5))
    for event_p in all_pairs["event_id"].unique().sort():
        sub = all_pairs.filter(all_pairs["event_id"] == event_p)
        ax_p.scatter(sub["out_share"] * 100, sub["deficit"] * 100, s=10, alpha=0.6, label=event_p)
    ax_p.plot([0, 100], [0, 100], color="grey", linestyle="--")
    ax_p.set_xlabel("EAGLE-I customers out at overpass, % of county")
    ax_p.set_ylabel("Night light deficit (1 - light ratio), %")
    ax_p.set_title("Five storms, clear county nights 1-7 after impact")
    ax_p.legend(fontsize=8)
    fig_pairs.tight_layout()
    fig_pairs.savefig(outputs / "five_storms_scatter.png", dpi=110)
    fig_pairs
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. How often is the first 48 hours visible at all?

    Over every storm in Heimdall's release 1.2: the share of declared county nights, on the
    first and second night after impact, with at least half the county's pixels valid.
    """)
    return


@app.cell
def _(duckdb, heimdall_daily, heimdall_summary):
    impacts = heimdall_summary.filter(heimdall_summary["declared"] == "True").select(
        "event_id", "geoid", "impact_date"
    )
    duckdb.register("impacts", impacts)
    visibility = (
        duckdb.sql(f"""
        WITH first_two AS (
            SELECT i.event_id, i.geoid, n.k
            FROM impacts i, (VALUES (1), (2)) n(k)
        )
        SELECT count(*) AS county_nights,
               count(*) FILTER (WHERE d.valid_pixel_share >= 0.5) AS clear_county_nights,
               count(DISTINCT f.event_id) AS storms
        FROM first_two f
        JOIN impacts i USING (event_id, geoid)
        LEFT JOIN read_parquet('{heimdall_daily}') d
          ON d.event_id = f.event_id AND d.geoid = f.geoid
         AND CAST(d.date AS DATE) = CAST(i.impact_date AS DATE) + f.k
    """)
        .pl()
        .row(0, named=True)
    )
    first_48h_visible = visibility["clear_county_nights"] / visibility["county_nights"]
    print(
        f"{visibility['storms']} storms: {first_48h_visible:.1%} of "
        f"{visibility['county_nights']:,} declared county nights "
        "in the first two nights had a clear reading"
    )
    return first_48h_visible, visibility


@app.cell
def _(
    dr4757_stats,
    first_48h_visible,
    heimdall_auc,
    json,
    nl,
    noise_floor_2023,
    noise_median_2023,
    outputs,
    pooled_spearman,
    started,
    storm_table,
    time,
    visibility,
):
    data_mb = sum(p.stat().st_size for p in nl.cache_dir().rglob("*") if p.is_file()) / 1e6
    comparison_summary = {
        "dr4757": dr4757_stats,
        "dr4757_noise_median": round(noise_median_2023, 4),
        "dr4757_noise_floor": round(noise_floor_2023, 4),
        "storms": storm_table.to_dicts(),
        "pooled_spearman": round(pooled_spearman, 3),
        "heimdall_pooled_auc": heimdall_auc.to_dicts(),
        "all_storms_first_48h_visible": round(first_48h_visible, 4),
        "all_storms_visibility": visibility,
        "data_cache_megabytes": round(data_mb),
        "run_seconds": round(time.time() - started),
        "cost_usd": 0,
    }
    storm_table.write_csv(outputs / "five_storms.csv")
    (outputs / "summary_comparison.json").write_text(
        json.dumps(comparison_summary, indent=2, default=str)
    )
    print(json.dumps(comparison_summary, indent=2, default=str))
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What this shows and doesn't

    - EAGLE-I counts customers out as utilities post them; night light measures brightness.
      A county can be bright with many customers out (streetlights and stores on other
      circuits, generators) or dark with power on (damage, evacuations). The two are related,
      not the same quantity, so "within N points" is a loose test by design.
    - The 2023 DTE storm is a different storm from July 2026; it tells us how the method
      behaves on DTE's territory when the sky is clear, not what July 2026 looked like.
    """)
    return


if __name__ == "__main__":
    app.run()

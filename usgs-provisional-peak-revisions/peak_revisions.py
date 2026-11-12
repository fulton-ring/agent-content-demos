import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(r"""
    # How much do USGS river gage peaks change between real time and approval?

    When a flood crest goes out from a USGS streamgage, the number on the USGS website is provisional. Months
    later a hydrographer reviews the record and USGS publishes the approved value. Prediction markets such as
    Polymarket's river-crest markets settle on the provisional number and ignore later revisions, and flood
    planners read the same live numbers. USGS does not keep the provisional values it showed, so nobody has
    measured how far they sit from the approved ones (USGS SIR 2017-5137).

    The Iowa Environmental Mesonet (IEM) has archived the values gages transmitted through NOAA's HADS system
    since about 2008. This notebook compares, for about 100 flood-prone gages and water years 2009 to the latest
    approved year, the annual peak gage height **as transmitted** (IEM) with the **approved** peak (USGS Water
    Data OGC API v1, `continuous` collection), and the same for discharge where IEM has it (a few gages,
    mostly 2022 onward).

    IEM holds what the gage sent. USGS can edit values after transmission (delete a spike, apply a datum
    correction) before or while they show on its website, and those edits may not reach HADS. So "as
    transmitted" is a proxy for what the website showed, close for most hours but not a copy.
    """)
    return (mo,)


@app.cell
def _():
    import datetime as dt
    import json
    import os
    import random
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import altair as alt
    import httpx
    import polars as pl

    from fetch import iem_hads, usgs_items

    HERE = Path(__file__).parent
    CACHE = Path(os.environ.get("CACHE_DIR", HERE / "cache"))
    OUT = Path(os.environ.get("OUTPUT_DIR", HERE / "outputs"))
    CACHE.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    NWPS = os.environ.get("NWPS_URL", "https://api.water.noaa.gov/nwps/v1")
    IEM_NETWORKS = os.environ.get("IEM_NETWORK_URL", "https://mesonet.agron.iastate.edu/geojson/network")
    FIRST_WY, LAST_WY = 2009, 2026
    PER_STATE = int(os.environ.get("GAGES_PER_STATE", "5"))
    SEED = 263
    STARTED = time.time()
    return (
        CACHE,
        FIRST_WY,
        IEM_NETWORKS,
        LAST_WY,
        NWPS,
        OUT,
        PER_STATE,
        SEED,
        STARTED,
        ThreadPoolExecutor,
        alt,
        dt,
        httpx,
        iem_hads,
        json,
        pl,
        random,
        threading,
        time,
        usgs_items,
    )


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Pick the gages

    We want gages that flood and that have long IEM archives. A gage is a candidate if IEM's archive for it
    starts by the end of 2010 (late 2007 in the Midwest states, November 2010 in most others, so those gages
    cover water years 2011 on), it transmits gage height (`HG`) as its main variable, and it is an NWS
    forecast point (`HAS_HML`). For each of 20 states spread across the country, including the ice-affected
    north (MN, ND, WI, MI, ME, VT, MT, NY), we shuffle the candidates with a fixed seed and keep the first five
    that NOAA's NWPS service maps to a USGS gage with a minor flood stage. We add the gages the question names:
    the White River at Indianapolis (03353000, the settled Polymarket market) and the two Helene gages near
    Asheville (03451500 French Broad, 03451000 Swannanoa), whose IEM archive starts in December 2010.
    """)
    return


@app.cell
def _(CACHE, IEM_NETWORKS, NWPS, PER_STATE, SEED, httpx, pl, random, time):
    STATES = ["MN", "ND", "WI", "MI", "ME", "VT", "MT", "NY", "IA", "MO",
              "IN", "OH", "PA", "TN", "NC", "GA", "LA", "TX", "OK", "CA"]  # fmt: skip
    NAMED = {"INDI3": "IN", "AVLN7": "NC", "BLTN7": "NC"}
    gages_path = CACHE / "gages.csv"

    def nwps_gauge(client: httpx.Client, lid: str) -> dict | None:
        """USGS id and NWS flood stages for an NWS gauge id, or None if NWPS has no usable record."""
        time.sleep(0.3)
        resp = client.get(f"{NWPS}/gauges/{lid}", timeout=60)
        if resp.status_code != 200:
            return None
        g = resp.json()
        cats = (g.get("flood") or {}).get("categories") or {}
        stage = {k: (cats.get(k) or {}).get("stage", -9999) for k in ("action", "minor", "moderate", "major")}
        if not g.get("usgsId") or stage["minor"] <= 0:
            return None
        return {"nws_id": lid, "usgs_id": g["usgsId"], "name": g["name"], **stage}

    if gages_path.exists():
        gages = pl.read_csv(gages_path, schema_overrides={"usgs_id": pl.String})
    else:
        picked: list[dict] = []
        rng = random.Random(SEED)
        with httpx.Client() as nclient:
            for lid, st in NAMED.items():
                row = nwps_gauge(nclient, lid)
                assert row is not None, f"named gage {lid} missing from NWPS"
                picked.append({**row, "state": st, "named": True})
            for st in STATES:
                resp = nclient.get(f"{IEM_NETWORKS}/{st}_DCP.geojson", timeout=120)
                resp.raise_for_status()
                props = [f["properties"] for f in resp.json()["features"]]
                cands = sorted(
                    p["sid"] for p in props
                    if (p.get("archive_begin") or "9999") <= "2010-12-31"
                    and (p.get("attributes") or {}).get("PEDTS", "").startswith("HG")
                    and (p.get("attributes") or {}).get("HAS_HML") == "1"
                    and p["sid"] not in NAMED
                )  # fmt: skip
                rng.shuffle(cands)
                kept = 0
                for lid in cands[:60]:
                    if kept >= PER_STATE:
                        break
                    row = nwps_gauge(nclient, lid)
                    if row is None or any(r["usgs_id"] == row["usgs_id"] for r in picked):
                        continue
                    picked.append({**row, "state": st, "named": False})
                    kept += 1
        gages = pl.DataFrame(picked)
        gages.write_csv(gages_path)
    print(f"{gages.height} gages in {gages['state'].n_unique()} states")
    gages
    return (gages,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Find each year's flood windows

    Pulling a full year of 15-minute values from both sources takes about five minutes per gage-year from IEM,
    so we pull only the days that matter. For each gage we read USGS's approved daily means (gage height, or
    discharge where USGS publishes no daily stage), and for each water year take the three highest days at
    least five days apart. Around each of those days we pull a three-day window of 15-minute values from both
    USGS (approved and provisional, with qualifiers) and IEM (as transmitted). The annual peak on each side is
    the highest value across the same three windows, so both sides look at exactly the same hours.

    The catch: a transmitted spike on a day that isn't among the approved top three is missed. Section 6
    checks how often that happens with full-year pulls for a sample of gage-years.
    """)
    return


@app.cell
def _(CACHE, FIRST_WY, LAST_WY, dt, iem_hads, pl, threading, usgs_items):
    iem_lock = threading.Lock()

    def flood_days(daily: pl.DataFrame) -> list[dt.date]:
        """Top three daily values per water year, at least five days apart."""
        days: list[dt.date] = []
        for wy in range(FIRST_WY, LAST_WY + 1):
            year = daily.filter(pl.col("wy") == wy).sort("value", descending=True)
            chosen: list[dt.date] = []
            for d in year["time"].to_list()[:400]:
                if all(abs((d - c).days) >= 5 for c in chosen):
                    chosen.append(d)
                if len(chosen) == 3:
                    break
            days.extend(chosen)
        return days

    def pull_gage(client, usgs_id: str, nws_id: str) -> pl.DataFrame:
        """15-minute USGS and IEM values in each flood window for one gage, cached as parquet."""
        path = CACHE / f"windows_{usgs_id}.parquet"
        if path.exists():
            return pl.read_parquet(path)
        daily = usgs_items(client, "daily", {
            "monitoring_location_id": f"USGS-{usgs_id}", "parameter_code": "00060,00065",
            "time": f"{FIRST_WY - 1}-10-01/{LAST_WY}-10-01", "properties": "time,value,parameter_code",
        })  # fmt: skip
        frames: list[pl.DataFrame] = []
        if daily.height:
            daily = daily.with_columns(
                pl.col("time").str.to_date(), pl.col("value").cast(pl.Float64, strict=False)
            ).with_columns(wy=pl.col("time").dt.year() + (pl.col("time").dt.month() >= 10).cast(pl.Int32))
            stage = daily.filter(pl.col("parameter_code") == "00065")
            use = stage if stage.height > daily.height / 4 else daily.filter(pl.col("parameter_code") == "00060")
            for day in flood_days(use.drop_nulls("value")):
                start, end = f"{day - dt.timedelta(days=1)}T06:00:00Z", f"{day + dt.timedelta(days=2)}T06:00:00Z"
                usgs = usgs_items(client, "continuous", {
                    "monitoring_location_id": f"USGS-{usgs_id}", "parameter_code": "00060,00065",
                    "time": f"{start}/{end}", "properties": "time,value,parameter_code,approval_status,qualifier",
                })  # fmt: skip
                with iem_lock:
                    iem = iem_hads(client, nws_id, start[:16] + "Z", end[:16] + "Z")
                if usgs.height:
                    frames.append(
                        usgs.select(
                            pl.col("time").str.to_datetime(time_zone="UTC").dt.replace_time_zone(None).alias("utc"),
                            pl.when(pl.col("parameter_code") == "00065").then(pl.lit("usgs_gh"))
                            .otherwise(pl.lit("usgs_q")).alias("var"),
                            pl.col("value").cast(pl.Float64, strict=False),
                            pl.col("approval_status").alias("status"),
                            pl.col("qualifier").cast(pl.List(pl.String)).list.join(",").alias("qualifier"),
                        ).with_columns(window=pl.lit(day))
                    )  # fmt: skip
                if iem.height:
                    frames.append(
                        iem.with_columns(
                            status=pl.lit("Transmitted"), qualifier=pl.lit(None, pl.String), window=pl.lit(day)
                        )  # fmt: skip
                    )
        schema = {"utc": pl.Datetime("us"), "var": pl.String, "value": pl.Float64, "status": pl.String,
                  "qualifier": pl.String, "window": pl.Date}  # fmt: skip
        out = pl.concat([f.cast(schema) for f in frames]) if frames else pl.DataFrame(schema=schema)
        out.write_parquet(path)
        return out

    return (pull_gage,)


@app.cell
def _(STARTED, ThreadPoolExecutor, gages, httpx, pl, pull_gage, time):
    def pull_one(row: dict) -> pl.DataFrame:
        with httpx.Client() as c:
            df = pull_gage(c, row["usgs_id"], row["nws_id"])
        print(f"{row['usgs_id']} {row['nws_id']}: {df.height} rows, {time.time() - STARTED:.0f}s elapsed")
        return df.with_columns(usgs_id=pl.lit(row["usgs_id"]))

    with ThreadPoolExecutor(max_workers=4) as pool:
        windows = pl.concat(list(pool.map(pull_one, gages.iter_rows(named=True))))
    print(f"{windows.height:,} values across {windows['usgs_id'].n_unique()} gages")
    return (windows,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Compare peaks, gage-year by gage-year

    IEM stores each SHEF series under a code. Gage height is `HG…` and discharge is `QR…` (in thousands of
    cfs). Where a gage sends more than one `HG` series (primary and backup sensor) we take the one it reports
    most often. A gage-year counts as **approved** only if every USGS value in its windows is approved.

    For each gage-year we record the approved peak and its time, the transmitted peak and its time, and the
    window offset: the median transmitted-minus-approved difference at matching timestamps across the windows.
    A peak revision close to the window offset means USGS shifted the whole record (a datum or gage-height
    correction); a peak revision much larger than it means the peak itself was edited (a spike removed, a gap
    filled, ice).

    The HADS feed also carries garbage readings: a 1,213 ft stage at a gage that never tops 30 ft, from a
    garbled radio message. USGS's website doesn't show those, so before taking the transmitted peak we drop
    any reading more than 1 ft (and more than 10%) away from the median of its five-reading neighbourhood
    (25% and 500 cfs for discharge), and any reading more than 25% and 2 ft above the highest value USGS
    approved at that gage in any of our windows (garbage often arrives in runs, which the median misses). We
    count how often such a spike sat above the crest. We also check that the gage transmitted something within
    two hours of the approved peak, because a transmission gap at the crest makes the "transmitted peak"
    meaningless rather than revised.
    """)
    return


@app.cell
def _(pl, windows):
    iem = windows.filter(pl.col("status") == "Transmitted")
    main_hg = (
        iem.filter(pl.col("var").str.starts_with("HG"))
        .with_columns(series=pl.col("var").str.slice(0, 5))
        .group_by("usgs_id", "series").len()
        .sort("len", descending=True).unique("usgs_id", keep="first")
        .select("usgs_id", "series")
    )  # fmt: skip

    def flag_spikes(t: pl.DataFrame, usgs_var: str, floor: float, share: float) -> pl.DataFrame:
        """Mark garbage readings: far from their five-reading median, or far above anything USGS ever approved."""
        record = (
            windows.filter((pl.col("var") == usgs_var) & (pl.col("status") == "Approved"))
            .group_by("usgs_id").agg(pl.col("value").max().alias("record"))
        )  # fmt: skip
        med = pl.col("value").rolling_median(5, center=True, min_samples=1).over("usgs_id", "window")
        ceiling = pl.max_horizontal(pl.col("record") * (1 + share * 2.5), pl.col("record") + floor * 2)
        return (
            t.sort("usgs_id", "window", "utc")
            .join(record, on="usgs_id", how="left")
            .with_columns(
                spike=((pl.col("value") - med).abs() > pl.max_horizontal(pl.lit(floor), med.abs() * share))
                | (pl.col("value") > ceiling).fill_null(False)
            )
            .drop("record")
        )

    tx_gh = flag_spikes(
        iem.with_columns(series=pl.col("var").str.slice(0, 5))
        .join(main_hg, on=["usgs_id", "series"])
        .group_by("usgs_id", "window", "utc").agg(pl.col("value").median()),
        "usgs_gh", floor=1.0, share=0.1,
    )  # fmt: skip
    tx_q = flag_spikes(
        iem.filter(pl.col("var").str.starts_with("QR"))
        .group_by("usgs_id", "window", "utc").agg(pl.col("value").median() * 1000),
        "usgs_q", floor=500.0, share=0.25,
    )  # fmt: skip

    def usgs_side(var: str) -> pl.DataFrame:
        return windows.filter(pl.col("var") == var).unique(["usgs_id", "window", "utc"])

    def peaks(approved: pl.DataFrame, transmitted: pl.DataFrame) -> pl.DataFrame:
        """One row per gage-year: approved and transmitted peaks over the same windows."""
        wy = pl.col("window").dt.year() + (pl.col("window").dt.month() >= 10).cast(pl.Int32)
        a = approved.with_columns(wy=wy)
        t = transmitted.with_columns(wy=wy)
        a_peak = a.sort(["value", "utc"], descending=[True, False]).group_by("usgs_id", "wy").agg(
            pl.col("value").first().alias("approved"), pl.col("utc").first().alias("approved_time"),
            pl.col("qualifier").first().alias("qualifier"),
            (pl.col("status") == "Approved").all().alias("all_approved"),
        )  # fmt: skip
        t_peak = (
            t.filter(~pl.col("spike")).sort(["value", "utc"], descending=[True, False]).group_by("usgs_id", "wy")
        ).agg(
            pl.col("value").first().alias("transmitted"), pl.col("utc").first().alias("transmitted_time"),
        ).join(t.group_by("usgs_id", "wy").agg(pl.col("value").max().alias("transmitted_raw")),
               on=["usgs_id", "wy"])  # fmt: skip
        t = t.filter(~pl.col("spike"))
        offset = (
            a.join(t, on=["usgs_id", "wy", "window", "utc"], suffix="_t")
            .group_by("usgs_id", "wy")
            .agg((pl.col("value_t") - pl.col("value")).median().alias("window_offset"), pl.len().alias("matched"))
        )  # fmt: skip
        near = (
            a_peak.join(t.select("usgs_id", "wy", "utc"), on=["usgs_id", "wy"])
            .filter((pl.col("utc") - pl.col("approved_time")).abs() <= pl.duration(hours=2))
            .group_by("usgs_id", "wy").len("tx_near_peak")
        )  # fmt: skip
        at_tx_peak = (
            t_peak.join(a.select("usgs_id", "wy", "utc", "value"), on=["usgs_id", "wy"])
            .filter((pl.col("utc") - pl.col("transmitted_time")).abs() <= pl.duration(hours=1))
            .group_by("usgs_id", "wy").agg(pl.col("value").max().alias("approved_at_tx_peak"))
        )  # fmt: skip
        return (
            a_peak.join(t_peak, on=["usgs_id", "wy"], how="left")
            .join(offset, on=["usgs_id", "wy"], how="left")
            .join(near, on=["usgs_id", "wy"], how="left")
            .join(at_tx_peak, on=["usgs_id", "wy"], how="left")
            .with_columns(
                revision=pl.col("transmitted") - pl.col("approved"),
                hours_apart=(pl.col("transmitted_time") - pl.col("approved_time")).dt.total_minutes() / 60,
                tx_near_peak=pl.col("tx_near_peak").fill_null(0),
            )
            .sort("usgs_id", "wy")
        )

    gh_years = peaks(usgs_side("usgs_gh"), tx_gh)
    q_years = peaks(usgs_side("usgs_q"), tx_q)
    gh_years
    return gh_years, q_years


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Gage height: how big are the revisions?

    Before measuring we drop three kinds of gage-year and count them: years not yet fully approved, years
    with no transmission within two hours of the approved crest, and gages whose transmitted stage sits on a
    different datum from USGS's gage height across all years (median window offset over 0.3 ft, a NWS-versus-
    USGS reference difference, not a revision). The flood-category flip counts use the NWS action, minor,
    moderate and major stages for each gage; a whole-foot flip means the two peaks fall on different sides of
    an integer foot, the kind of band edge a crest market uses.
    """)
    return


@app.cell
def _(gages, gh_years, pl):
    datum_off = (
        gh_years.filter(pl.col("all_approved"))
        .group_by("usgs_id").agg(pl.col("window_offset").median().alias("gage_offset"))
        .filter(pl.col("gage_offset").abs() > 0.3)
    )  # fmt: skip
    cat_expr = lambda c: (  # noqa: E731
        (pl.col(c) >= pl.col("action")).cast(pl.Int8) + (pl.col(c) >= pl.col("minor")).cast(pl.Int8)
        + (pl.col(c) >= pl.col("moderate")).cast(pl.Int8) + (pl.col(c) >= pl.col("major")).cast(pl.Int8)
    )  # fmt: skip
    labelled = gh_years.join(gages.select("usgs_id", "nws_id", "name", "state", "action", "minor", "moderate",
                                          "major"), on="usgs_id").with_columns(  # fmt: skip
        cat_tx=cat_expr("transmitted"), cat_ap=cat_expr("approved"),
        abs_rev=pl.col("revision").abs(),
        pct_rev=pl.col("revision") / pl.col("approved") * 100,
        foot_flip=pl.col("transmitted").floor() != pl.col("approved").floor(),
        ice_months=pl.col("transmitted_time").dt.month().is_in([12, 1, 2, 3]),
        cause=pl.when(pl.col("revision").abs() <= 0.1).then(pl.lit("within 0.1 ft"))
        .when(pl.col("approved_at_tx_peak").is_null()).then(pl.lit("USGS has no value at the transmitted crest"))
        .when((pl.col("revision") - pl.col("window_offset")).abs() < 0.05).then(pl.lit("whole window shifted"))
        .otherwise(pl.lit("crest value changed")),
    )  # fmt: skip
    excluded = {
        "not yet approved": labelled.filter(~pl.col("all_approved")).height,
        "no transmission within 2 h of approved crest": labelled.filter(
            pl.col("all_approved") & (pl.col("tx_near_peak") == 0)
        ).height,
        "gage on a different datum (gage-years)": labelled.filter(
            pl.col("all_approved")
            & (pl.col("tx_near_peak") > 0)
            & pl.col("usgs_id").is_in(datum_off["usgs_id"].implode())
        ).height,
    }
    gh = labelled.filter(
        pl.col("all_approved") & (pl.col("tx_near_peak") > 0) & ~pl.col("usgs_id").is_in(datum_off["usgs_id"].implode())
    )
    gh_summary = {
        "gages": gh["usgs_id"].n_unique(),
        "gage_years": gh.height,
        "water_years": f"{gh['wy'].min()}-{gh['wy'].max()}",
        "median_abs_revision_ft": round(gh["abs_rev"].median(), 3),
        "p95_abs_revision_ft": round(gh["abs_rev"].quantile(0.95), 3),
        "max_abs_revision_ft": round(gh["abs_rev"].max(), 2),
        "median_signed_revision_ft": round(gh["revision"].median(), 3),
        "share_within_0.05_ft": round((gh["abs_rev"] <= 0.05).mean(), 3),
        "share_within_0.1_ft": round((gh["abs_rev"] <= 0.1).mean(), 3),
        "share_within_0.5_ft": round((gh["abs_rev"] <= 0.5).mean(), 3),
        "share_over_0.1_ft": round((gh["abs_rev"] > 0.1).mean(), 3),
        "transmitted_higher_share": round((gh["revision"] > 0.005).mean(), 3),
        "transmitted_lower_share": round((gh["revision"] < -0.005).mean(), 3),
        "median_abs_revision_pct": round(gh["pct_rev"].abs().median(), 2),
        "p95_abs_revision_pct": round(gh["pct_rev"].abs().quantile(0.95), 2),
        "flood_category_flips": int((gh["cat_tx"] != gh["cat_ap"]).sum()),
        "flood_category_flips_crest_in_flood": int(
            ((gh["cat_tx"] != gh["cat_ap"]) & ((gh["cat_tx"] >= 2) | (gh["cat_ap"] >= 2))).sum()
        ),
        "flood_category_flips_revision_under_0.5_ft": int(
            ((gh["cat_tx"] != gh["cat_ap"]) & (gh["abs_rev"] <= 0.5)).sum()
        ),
        "whole_foot_flips": int(gh["foot_flip"].sum()),
        "whole_foot_flips_revision_under_0.5_ft": int((gh["foot_flip"] & (gh["abs_rev"] <= 0.5)).sum()),
        "gage_years_with_spike_over_1ft_above_peak": int((gh["transmitted_raw"] - gh["transmitted"] > 1).sum()),
        "peak_timing_over_6h_apart": int((gh["hours_apart"].abs() > 6).sum()),
        "causes_over_0.1_ft": dict(
            gh.filter(pl.col("abs_rev") > 0.1).group_by("cause").len().sort("cause").iter_rows()
        ),
        "over_0.1_ft_in_ice_months": int(gh.filter((pl.col("abs_rev") > 0.1) & pl.col("ice_months")).height),
        "excluded": excluded,
        "datum_offset_gages": datum_off["usgs_id"].to_list(),
    }
    gh_summary
    return gh, gh_summary, labelled


@app.cell
def _(alt, gh, pl):
    clipped = gh.with_columns(rev_ft=pl.col("revision").clip(-1, 1))
    hist = (
        alt.Chart(clipped)
        .mark_bar()
        .encode(
            alt.X("rev_ft:Q", bin=alt.Bin(step=0.02), title="Transmitted minus approved annual peak (ft, clipped ±1)"),
            alt.Y("count():Q", title="Gage-years"),
        )
        .properties(width=560, height=240, title="Annual peak gage height revisions")
    )
    hist
    return (hist,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. The worst cases

    The fifteen largest gage-height revisions, with what the record says about them. Every gage-year over
    0.1 ft gets a cause:

    - **USGS has no value at the transmitted crest:** the gage sent a higher reading, and the approved record
      has nothing within an hour of it. USGS deleted those hours, typically for ice, a frozen or failed sensor
      or a fouled orifice line.
    - **whole window shifted:** the revision equals the median shift across the windows, a datum or
      gage-height correction applied to the whole record.
    - **crest value changed:** USGS kept the hour but published a different value.

    We also flag crests in the ice months (December to March).
    """)
    return


@app.cell
def _(gh, pl):
    worst = (
        gh.sort("abs_rev", descending=True).head(15)
        .select("usgs_id", "nws_id", "name", "wy", "approved", "transmitted", "revision", "window_offset",
                "approved_at_tx_peak", "approved_time", "transmitted_time", "ice_months", "cause")
    )  # fmt: skip
    worst
    return (worst,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Did the windows miss any transmitted peaks?

    For a seeded sample of approved gage-years we pull the whole water year from IEM and check whether the
    gage's highest transmitted stage (after the same garbage filter) fell inside our three windows. A
    transmitted maximum outside them is usually a spike or a bad value that USGS removed, which is a revision
    our window method doesn't count.
    """)
    return


@app.cell
def _(CACHE, SEED, gh, httpx, iem_hads, pl, random):
    check_path = CACHE / "fullyear_check.csv"
    if check_path.exists():
        full_check = pl.read_csv(check_path, schema_overrides={"usgs_id": pl.String})
    else:
        sample = random.Random(SEED).sample(list(gh.select("usgs_id", "nws_id", "wy", "transmitted").iter_rows()),
                                            min(25, gh.height))  # fmt: skip
        record = dict(gh.group_by("usgs_id").agg(pl.col("approved").max()).iter_rows())
        rows = []
        with httpx.Client() as fclient:
            for usgs_id, nws_id, wy, tx_window in sample:
                year = iem_hads(fclient, nws_id, f"{wy - 1}-10-01T00:00Z", f"{wy}-10-01T00:00Z")
                hg = year.filter(pl.col("var").str.starts_with("HG"))
                series = hg.group_by(pl.col("var").str.slice(0, 5)).len().sort("len", descending=True)
                top = hg.filter(pl.col("var").str.slice(0, 5) == series["var"][0]) if series.height else hg
                med = pl.col("value").rolling_median(5, center=True, min_samples=1)
                ceiling = max(record[usgs_id] * 1.25, record[usgs_id] + 2)
                clean = top.sort("utc").filter(
                    ((pl.col("value") - med).abs() <= pl.max_horizontal(pl.lit(1.0), med.abs() * 0.1))
                    & (pl.col("value") <= ceiling)
                )
                rows.append({"usgs_id": usgs_id, "nws_id": nws_id, "wy": wy, "window_max": tx_window,
                             "full_year_max_raw": top["value"].max(),
                             "full_year_max": clean["value"].max()})  # fmt: skip
        full_check = pl.DataFrame(rows)
        full_check.write_csv(check_path)
    full_check = full_check.with_columns(missed=(pl.col("full_year_max") - pl.col("window_max")) > 0.05)
    print(f"{(full_check['full_year_max_raw'] - full_check['full_year_max'] > 1).sum()} of {full_check.height} "
          "sampled gage-years had a transmission spike of more than 1 ft somewhere in the year")  # fmt: skip
    print(f"{full_check['missed'].sum()} of {full_check.height} sampled gage-years had a higher transmitted "
          "value outside the windows")  # fmt: skip
    full_check
    return (full_check,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Discharge, where IEM has it

    IEM has transmitted discharge (`QR`) at only some gages, mostly from 2022 on. Discharge is computed
    from stage through a rating curve, and USGS revises ratings and applies shifts after field measurements,
    so we expect larger revisions here than for stage.
    """)
    return


@app.cell
def _(pl, q_years):
    q = q_years.filter(pl.col("all_approved") & (pl.col("tx_near_peak") > 0)).with_columns(
        pct_rev=pl.col("revision") / pl.col("approved") * 100
    )
    q_summary = {
        "gages": q["usgs_id"].n_unique(),
        "gage_years": q.height,
        "water_years": f"{q['wy'].min()}-{q['wy'].max()}" if q.height else None,
        "median_abs_revision_pct": round(q["pct_rev"].abs().median(), 2) if q.height else None,
        "p95_abs_revision_pct": round(q["pct_rev"].abs().quantile(0.95), 2) if q.height else None,
        "share_over_5pct": round((q["pct_rev"].abs() > 5).mean(), 3) if q.height else None,
        "share_over_10pct": round((q["pct_rev"].abs() > 10).mean(), 3) if q.height else None,
        "max_abs_revision_pct": round(q["pct_rev"].abs().max(), 1) if q.height else None,
    }
    q_summary
    return q, q_summary


@app.cell
def _(q):
    q.sort(q["pct_rev"].abs(), descending=True).head(10)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. Not yet approved: the White River 2026 crest and the Helene year

    Water year 2026 (October 2025 to September 2026) is still provisional at most gages. For the gages the
    question names we show the transmitted peak against what USGS shows today, approved or not.
    """)
    return


@app.cell
def _(labelled, pl):
    named_rows = labelled.filter(pl.col("usgs_id").is_in(["03353000", "03451500", "03451000"])).select(
        "usgs_id", "name", "wy", "approved", "transmitted", "revision", "approved_time", "transmitted_time",
        "all_approved", "tx_near_peak",
    )  # fmt: skip
    named_rows
    return (named_rows,)


@app.cell
def _(
    OUT,
    STARTED,
    full_check,
    gh,
    gh_summary,
    hist,
    json,
    labelled,
    named_rows,
    q,
    q_summary,
    time,
    worst,
):
    labelled.write_csv(OUT / "gage_height_peaks.csv")
    q.write_csv(OUT / "discharge_peaks.csv")
    worst.write_csv(OUT / "worst_gage_height.csv")
    named_rows.write_csv(OUT / "named_gages.csv")
    hist.save(str(OUT / "revision_histogram.png"), scale_factor=2)
    summary = {
        "gage_height": gh_summary,
        "discharge": q_summary,
        "full_year_check": {
            "sampled": full_check.height,
            "missed": int(full_check["missed"].sum()),
            "spike_over_1ft_in_year": int((full_check["full_year_max_raw"] - full_check["full_year_max"] > 1).sum()),
        },
        "runtime_s": round(time.time() - STARTED),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(json.dumps(summary, indent=2, default=str))
    print(f"{gh.height} gage-years measured")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What this doesn't show

    - IEM is a proxy for the USGS website. It stores what the gage transmitted through HADS; edits USGS made
      before or after display don't appear in it.
    - Windows around the approved top three days can miss a transmitted spike elsewhere in the year; section 6
      measures how often.
    - The gage sample is NWS forecast points with long IEM archives, not a random sample of all USGS gages.
    - Discharge covers only the gages that transmit it to HADS, mostly 2022 onward.
    """)
    return


if __name__ == "__main__":
    app.run()

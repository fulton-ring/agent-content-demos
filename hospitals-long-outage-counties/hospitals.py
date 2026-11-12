import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import os
    import time
    import zipfile
    from pathlib import Path

    import geopandas as gpd
    import httpx
    import marimo as mo
    import matplotlib.pyplot as plt
    import polars as pl

    return Path, gpd, httpx, json, mo, os, pl, plt, time, zipfile


@app.cell
def _(mo):
    mo.md(r"""
    # Which US hospitals sat in the counties that stayed dark longest after major storms?

    **The question.** After the major storms of the past decade, which hospitals sat in counties
    where the grid stayed down for days? We expected a short list of hospitals that keep showing
    up: in counties where at least 10% of customers were out and restoration took more than
    three days, more than once.

    **What this measures, and what it doesn't.** County outages measure *exposure*: how long
    the grid around a hospital was down. They don't measure how long a hospital went without
    grid power. Utilities restore hospitals early as priority loads, and hospitals run backup
    generators. Heimdall Research says its tables are "not for any decision about a single
    address or property". So the headline here is counts and method. Names appear only in
    `outputs/`, for people checking their own facilities.

    **Data, all downloaded at run time:**

    - Hospitals: [HIFLD Next](https://hifld.publicenvirodata.org) `hospitals-3` v1.1.0
      (8,340 records, public domain).
    - Outages: Heimdall Research's [Storm Blackout and Restoration
      1.2](https://zenodo.org/records/23010005) (CC BY 4.0). It gives one row per storm and
      county, with restoration times computed from DOE's EAGLE-I county outage counts.
    - Counties: Census 2020 cartographic boundaries. Heimdall uses the old Connecticut counties,
      which the 2024 file replaces with planning regions.
    - EAGLE-I's own state-by-year coverage table ([figshare](https://doi.org/10.6084/m9.figshare.24237376)),
      used to test whether the result comes from gaps in coverage.
    """)
    return


@app.cell
def _(Path, httpx, os, time):
    DATA = Path(os.environ.get("DATA_DIR", Path(__file__).parent / "data"))
    OUT = Path(__file__).parent / "outputs"
    DATA.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(exist_ok=True)
    ZENODO = "https://zenodo.org/api/records/23010005/files/"
    HOSPITALS_URL = (
        "https://hifld.publicenvirodata.org/storage/hifld/hospitals-3/hospitals-3/v1.1.0/"
        "geoparquet/hospitals-3.parquet"
    )

    def download(url: str, name: str) -> Path:
        """Download url into DATA once, with up to four tries. Returns the cached path."""
        path = DATA / name
        if path.exists() and path.stat().st_size > 0:
            return path
        for attempt in range(4):
            try:
                with httpx.stream("GET", url, timeout=300, follow_redirects=True) as response:
                    response.raise_for_status()
                    part = path.with_suffix(path.suffix + ".part")
                    with open(part, "wb") as f:
                        f.writelines(response.iter_bytes(1 << 20))
                part.rename(path)
                return path
            except httpx.HTTPError:
                if attempt == 3:
                    raise
                time.sleep(2 ** (attempt + 1))
        raise AssertionError("unreachable")

    return DATA, HOSPITALS_URL, OUT, ZENODO, download


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. The storms

    Heimdall lists 672 FEMA-declared storms from 2012 to 2026. Only some of them have an outage
    run, because the public EAGLE-I county series starts on November 1, 2014 and its last
    published day is December 31, 2025. We keep declared counties whose utility records cover
    the storm window (`reason == "ok"`). Hurricane Eta has two rows, the NHC storm and FEMA's
    North Carolina declaration, which cover the same counties. We keep the NHC row so Eta
    counts once.
    """)
    return


@app.cell
def _(ZENODO, download, pl):
    storms = pl.read_parquet(download(ZENODO + "data__storms.parquet/content", "storms.parquet"))
    county_summary = pl.read_parquet(
        download(ZENODO + "data__county_summary.parquet/content", "county_summary.parquet")
    )
    outages = county_summary.filter(
        pl.col("declared") & (pl.col("reason") == "ok") & (pl.col("event_id") != "DR-4588")
    ).join(storms.select("event_id", "name", "kind", "landfall"), on="event_id")

    storm_counts = {
        "storms_in_heimdall": storms.height,
        "storms_with_outage_run": storms.filter(pl.col("outage_reason").is_null()).height,
        "storms_with_any_county_record": outages["event_id"].n_unique(),
        "county_storm_rows_with_records": outages.height,
    }
    dropped_by_reason = (
        storms.filter(pl.col("outage_reason").is_not_null())
        .group_by("outage_reason")
        .len()
        .sort("len", descending=True)
    )
    print(storm_counts)
    dropped_by_reason
    return outages, storm_counts, storms


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Which county-storms count as "long"

    Heimdall's restoration hours start at each county's outage **peak**:

    - `hours_to_90pct_restored`: hours until customers out stayed at or below 10% of the peak
      for 6 hours.
    - `peak_share_out`: peak customers out as a share of the county's customers.

    **Main test, as the issue sets it:** the county took more than 72 hours to reach 90%
    restored, and at least 10% of its customers were out at the peak. A county that never got
    to 90% within Heimdall's 45-day window (`not_restored_in_window`) counts as long. A county
    whose utility feed stopped reporting partway through (`reporting_drop`) has no restore time,
    so it doesn't count, unless its feed lasted long enough to show that it hadn't reached
    even 50% restored by hour 72, which means it hadn't reached 90% either.

    **Strict test, "at least 10% of customers still out three days later":** Heimdall has no
    hourly series, so we can't read the share out at hour 72. We can bound it, though. If a
    county had 20% or more out at the peak and still hadn't reached 50% restored at 72 hours,
    then more than half of its peak, which is at least 10% of all customers, was still out at
    hour 72. Every county-storm that passes the strict test passes the main one too.
    """)
    return


@app.cell
def _(outages, pl):
    _h90, _h50 = pl.col("hours_to_90pct_restored"), pl.col("hours_to_50pct_restored")
    _not_back_90 = pl.col("hours_to_90pct_reason") == "not_restored_in_window"
    _not_back_50 = pl.col("hours_to_50pct_reason") == "not_restored_in_window"
    county_storms = outages.with_columns(
        long=((_h90 > 72) | _not_back_90 | (_h50 > 72) | _not_back_50).fill_null(False)
        & (pl.col("peak_share_out") >= 0.10).fill_null(False),
        strict=((_h50 > 72) | _not_back_50).fill_null(False)
        & (pl.col("peak_share_out") >= 0.20).fill_null(False),
    )
    assert county_storms.filter(pl.col("strict") & ~pl.col("long")).height == 0
    long_county_storms = county_storms.filter("long")
    print(
        f"{long_county_storms.height:,} long county-storms of {county_storms.height:,} "
        f"({long_county_storms['geoid'].n_unique():,} counties, "
        f"{long_county_storms['event_id'].n_unique()} storms); "
        f"{county_storms['strict'].sum():,} pass the strict test"
    )
    return (county_storms,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Hospitals to counties

    Each hospital point goes into the Census 2020 county that contains it. HIFLD also has a
    `COUNTYFIPS` column, and we count how often the two agree. We keep hospitals marked `OPEN`.
    The layer has no opening or closing date, so we can't drop hospitals that didn't exist yet
    at older storms. Closed hospitals are counted separately, below.
    """)
    return


@app.cell
def _(DATA, HOSPITALS_URL, download, gpd, pl, zipfile):
    _zip = download(
        "https://www2.census.gov/geo/tiger/GENZ2020/shp/cb_2020_us_county_500k.zip",
        "cb_2020_us_county_500k.zip",
    )
    with zipfile.ZipFile(_zip) as _z:
        _z.extractall(DATA / "counties_2020")
    _counties = gpd.read_file(DATA / "counties_2020")[["GEOID", "geometry"]]
    _points = gpd.read_parquet(download(HOSPITALS_URL, "hospitals-3.parquet"))
    _joined = gpd.sjoin(
        _points, _counties.to_crs(_points.crs), how="left", predicate="within"
    ).drop_duplicates("source_ID")
    assert len(_joined) == len(_points), "a hospital fell in two counties"
    all_hospitals = pl.from_pandas(
        _joined[["source_ID", "NAME", "CITY", "STATE", "TYPE", "STATUS", "BEDS", "TRAUMA",
                 "COUNTYFIPS", "GEOID"]]
    ).rename({"GEOID": "geoid"})
    hospitals = all_hospitals.filter(pl.col("STATUS") == "OPEN")
    join_check = {
        "hospitals_in_layer": all_hospitals.height,
        "open": hospitals.height,
        "closed": all_hospitals.height - hospitals.height,
        "outside_any_county": all_hospitals["geoid"].null_count(),
        "county_differs_from_COUNTYFIPS": all_hospitals.filter(
            pl.col("geoid") != pl.col("COUNTYFIPS")
        ).height,
    }
    join_check
    return all_hospitals, hospitals, join_check


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Hospital-storm pairs

    A pair is one hospital in one long county-storm. Every hospital in a county shares that
    county's numbers, so the real unit is the county. Hospitals only weight counties by how many
    hospitals they hold.
    """)
    return


@app.cell
def _(county_storms, hospitals, pl):
    def pairs_for(flag: str) -> pl.DataFrame:
        return hospitals.join(county_storms.filter(flag), on="geoid")

    def headline(flag: str) -> dict[str, int]:
        _p = pairs_for(flag)
        _per = _p.group_by("source_ID").len()
        return {
            "hospital_storm_pairs": _p.height,
            "hospitals": _per.height,
            "hospitals_more_than_once": _per.filter(pl.col("len") > 1).height,
            "hospitals_three_or_more": _per.filter(pl.col("len") >= 3).height,
            "storms": _p["event_id"].n_unique(),
            "counties": _p["geoid"].n_unique(),
            "counties_more_than_once": _p.select("geoid", "event_id")
            .unique()
            .group_by("geoid")
            .len()
            .filter(pl.col("len") > 1)
            .height,
        }

    pairs = pairs_for("long")
    headlines = {"main": headline("long"), "strict": headline("strict")}
    pl.DataFrame([{"test": k} | v for k, v in headlines.items()])
    return headlines, pairs, pairs_for


@app.cell
def _(mo):
    mo.md(r"""
    **The ranking.** Hospitals are ranked first by the number of long storms, then by total
    hours to 90% restored across those storms. A county that never reached 90% in the window
    is counted at the window's length (usually 45 days), which is a floor.
    """)
    return


@app.cell
def _(OUT, pairs, pl):
    _hours = pl.coalesce(
        "hours_to_90pct_restored", pl.col("window_end_day").cast(pl.Float64) * 24
    )
    ranking = (
        pairs.with_columns(hours_to_90=_hours)
        .group_by("source_ID", "NAME", "CITY", "STATE", "geoid", "TYPE", "BEDS", "TRAUMA")
        .agg(
            long_storms=pl.len(),
            total_hours_to_90=pl.col("hours_to_90").sum().round(0),
            worst_peak_share_out=pl.col("peak_share_out").max().round(3),
            storms=pl.col("name").sort_by("landfall").str.join("; "),
        )
        .sort(["long_storms", "total_hours_to_90"], descending=True)
    )
    ranking.write_csv(OUT / "hospital_ranking.csv")
    _per_storm = ranking.group_by("long_storms").len().sort("long_storms")
    _per_storm
    return (ranking,)


@app.cell
def _(OUT, pairs, plt, ranking):
    _fig, (_a, _b) = plt.subplots(1, 2, figsize=(11, 3.8))
    _counts = ranking["long_storms"].value_counts().sort("long_storms")
    _a.bar(_counts["long_storms"], _counts["count"], color="#3b6ea5")
    _a.set_xlabel("long-outage storms in the hospital's county")
    _a.set_ylabel("hospitals")
    _a.set_title("How often hospitals repeat")
    _by_year = (
        pairs.with_columns(year=pairs["landfall"].dt.year())
        .group_by("year")
        .len()
        .sort("year")
    )
    _b.bar(_by_year["year"], _by_year["len"], color="#c0504d")
    _b.set_xlabel("storm year")
    _b.set_ylabel("hospital-storm pairs")
    _b.set_title("Pairs by year")
    _fig.tight_layout()
    _fig.savefig(OUT / "repeats_and_years.png", dpi=150)
    _fig
    return


@app.cell
def _(mo):
    mo.md(r"""
    **Which storms put the most hospitals in long-outage counties.** A few storms account for most
    of the pairs.
    """)
    return


@app.cell
def _(OUT, pairs, pl):
    storm_table = (
        pairs.group_by("event_id", "name", "landfall")
        .agg(
            hospitals=pl.len(),
            counties=pl.col("geoid").n_unique(),
            states=pl.col("STATE").unique().sort().str.join(" "),
            median_hours_to_90=pl.col("hours_to_90pct_restored").median().round(0),
        )
        .sort("hospitals", descending=True)
    )
    storm_table.write_csv(OUT / "storms_by_hospitals.csv")
    _top5_share = storm_table["hospitals"].head(5).sum() / storm_table["hospitals"].sum()
    print(f"Top 5 storms hold {_top5_share:.0%} of hospital-storm pairs")
    storm_table.head(12)
    return (storm_table,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. By beds and trauma level

    Beds come from HIFLD's `BEDS` field, where -999 means unknown. For trauma level we take the
    highest adult level in `TRAUMA`. Values like `TRH` or `CTH`, which are state designations
    that aren't numbered levels, go under "other designation". For each group the table gives
    the share of all open hospitals that had at least one long storm, and the share that had
    more than one.
    """)
    return


@app.cell
def _(OUT, hospitals, pl, ranking):
    _beds = pl.col("BEDS")
    _trauma = pl.col("TRAUMA")
    _groups = hospitals.join(
        ranking.select("source_ID", "long_storms"), on="source_ID", how="left"
    ).with_columns(
        long_storms=pl.col("long_storms").fill_null(0),
        beds=pl.when(_beds < 0).then(pl.lit("unknown"))
        .when(_beds < 26).then(pl.lit("1-25"))
        .when(_beds < 100).then(pl.lit("26-99"))
        .when(_beds < 300).then(pl.lit("100-299"))
        .otherwise(pl.lit("300+")),
        trauma=pl.when(_trauma.str.contains(r"LEVEL I\b|LEVEL I$")).then(pl.lit("Level I"))
        .when(_trauma.str.contains(r"LEVEL II\b")).then(pl.lit("Level II"))
        .when(_trauma.str.contains(r"LEVEL III\b")).then(pl.lit("Level III"))
        .when(_trauma.str.contains(r"LEVEL IV\b")).then(pl.lit("Level IV"))
        .when(_trauma == "NOT AVAILABLE").then(pl.lit("none listed"))
        .otherwise(pl.lit("other designation")),
    )

    def breakdown(column: str) -> pl.DataFrame:
        return (
            _groups.group_by(column)
            .agg(
                open_hospitals=pl.len(),
                any_long_storm=(pl.col("long_storms") >= 1).sum(),
                more_than_once=(pl.col("long_storms") >= 2).sum(),
            )
            .with_columns(
                share_any=(pl.col("any_long_storm") / pl.col("open_hospitals")).round(3),
                share_repeat=(pl.col("more_than_once") / pl.col("open_hospitals")).round(3),
            )
            .rename({column: "group"})
            .with_columns(by=pl.lit(column))
            .sort("open_hospitals", descending=True)
        )

    by_group = pl.concat([breakdown("beds"), breakdown("trauma")])
    by_group.write_csv(OUT / "by_beds_and_trauma.csv")
    by_group
    return (by_group,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Is the list driven by EAGLE-I coverage gaps?

    The issue says the idea is wrong if the repeat list comes from gaps in EAGLE-I's coverage.
    We check four ways.

    1. **Heimdall's `coverage_gap` flag** marks a gap of more than 6 hours in the utility series
       after the peak. EAGLE-I leaves out rows when nobody is out, so gaps are normal. We compare
       how often the flag is set on long rows and on all other rows.
    2. **EAGLE-I's own coverage table** gives, for each state and year from 2018 on, the share of
       customers whose utilities EAGLE-I tracks. We look at how many long pairs fall in
       state-years with under 80% coverage, or before 2018, when the coverage is unknown.
    3. **Rows that may be broken feeds.** A county counted as never restored could be a utility
       map stuck on a stale number. Heimdall also flags counties whose peak exceeded the customer
       estimate in another storm, which suggests the estimate is too low.
    4. **Recount with the doubtful rows removed.** We drop every row flagged in 2 and 3, recount
       the hospitals that repeat, and see how many are left.
    """)
    return


@app.cell
def _(county_storms, download, pairs, pairs_for, pl):
    _flag = county_storms.group_by("long").agg(
        rows=pl.len(), coverage_gap_share=pl.col("coverage_gap").mean().round(3)
    )
    print("1. coverage_gap flag on long vs. other county-storms")
    print(_flag)

    _cov = pl.read_csv(
        download("https://ndownloader.figshare.com/files/42547714", "eaglei_coverage_history.csv")
    ).select(
        year=pl.col("year").str.to_date("%m/%d/%y").dt.year(),
        STATE=pl.col("state"),
        coverage=pl.col("max_pct_covered"),
    )

    def with_quality(df: pl.DataFrame) -> pl.DataFrame:
        return (
            df.with_columns(year=pl.col("landfall").dt.year())
            .join(_cov, on=["year", "STATE"], how="left")
            .with_columns(
                coverage_unknown=pl.col("coverage").is_null(),
                coverage_under_80=(pl.col("coverage") < 0.8).fill_null(False),
                maybe_stuck=(pl.col("hours_to_90pct_reason") == "not_restored_in_window")
                .fill_null(False),
                estimate_low=pl.col("estimate_exceeded_in_other_storm").fill_null(False),
            )
        )

    _q = with_quality(pairs)
    _repeat_ids = (
        pairs.group_by("source_ID").len().filter(pl.col("len") > 1)["source_ID"].implode()
    )
    _flags = ["coverage_unknown", "coverage_under_80", "maybe_stuck", "estimate_low"]
    gap_shares = pl.concat(
        [
            _q.select([pl.col(f).mean().round(3) for f in _flags]).with_columns(
                pairs=pl.lit("all long pairs")
            ),
            _q.filter(pl.col("source_ID").is_in(_repeat_ids))
            .select([pl.col(f).mean().round(3) for f in _flags])
            .with_columns(pairs=pl.lit("pairs of hospitals that repeat")),
        ]
    )
    print("2-3. share of pairs with each doubt")
    print(gap_shares)

    _clean = _q.filter(~pl.any_horizontal(_flags))
    _per = _clean.group_by("source_ID").len()
    robust = {
        "pairs_kept": _clean.height,
        "hospitals_kept": _per.height,
        "hospitals_more_than_once_kept": _per.filter(pl.col("len") > 1).height,
        "storms_kept": _clean["event_id"].n_unique(),
        "strict_test_repeaters": pairs_for("strict")
        .group_by("source_ID")
        .len()
        .filter(pl.col("len") > 1)
        .height,
    }
    print("4. recount with doubtful rows removed")
    print(robust)
    return gap_shares, robust


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. An agent repeats the analysis

    A [Pydantic AI](https://ai.pydantic.dev) agent gets the question in plain words and the same
    sources. It has the HIFLD Next MCP server (its catalog and query tools) to find the hospital
    layer, the Zenodo record that holds Heimdall's files, and two tools of ours: `load_table`
    downloads a CSV or Parquet file into a local DuckDB, and `sql` runs a SELECT query there.
    We don't tell it the column names or the join. It has to return a typed answer.

    Calling the model costs money, so by default the notebook re-scores the saved answers in
    `outputs/agent/`. Set `AGENT_RUN=1` (with `OPENROUTER_API_KEY`) to call the model again.
    The model is `AGENT_MODEL`, by default Claude Haiku 5.5 on OpenRouter, and a run stops
    starting new attempts once spending passes `AGENT_BUDGET_USD` (default $3).
    """)
    return


@app.cell
def _(os):
    import asyncio

    import duckdb
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent, ModelRetry
    from pydantic_ai.mcp import MCPToolset
    from pydantic_ai.messages import ModelMessagesTypeAdapter
    from pydantic_ai.usage import UsageLimits

    AGENT_RUN = os.environ.get("AGENT_RUN") == "1"
    AGENT_MODEL = os.environ.get("AGENT_MODEL", "anthropic/claude-haiku-5.5")
    AGENT_REPEATS = int(os.environ.get("AGENT_REPEATS", "3"))
    AGENT_BUDGET_USD = float(os.environ.get("AGENT_BUDGET_USD", "3"))
    return (
        AGENT_BUDGET_USD,
        AGENT_MODEL,
        AGENT_REPEATS,
        AGENT_RUN,
        Agent,
        BaseModel,
        Field,
        MCPToolset,
        ModelMessagesTypeAdapter,
        ModelRetry,
        UsageLimits,
        asyncio,
        duckdb,
    )


@app.cell
def _(BaseModel, Field):
    class GroupCount(BaseModel):
        group: str = Field(description="A trauma level, for example 'LEVEL I' or 'none'.")
        hospitals: int = Field(description="Hospitals in this group with at least one long storm.")

    class AgentAnswer(BaseModel):
        hospitals: int = Field(
            description="Distinct hospitals in a county that had at least one qualifying storm."
        )
        hospital_storm_pairs: int = Field(description="Hospital-storm pairs that qualify.")
        storms: int = Field(description="Distinct storms with at least one qualifying county.")
        hospitals_more_than_once: int = Field(
            description="Hospitals whose county qualified in two or more storms."
        )
        top_hospital_ids: list[str] = Field(
            description="HIFLD source_ID of the 10 hospitals with the most qualifying storms."
        )
        by_trauma_level: list[GroupCount]
        method: str = Field(description="The definition and join you used, in a few sentences.")
        caveats: list[str] = Field(description="What limits the result.")

    return (AgentAnswer,)


@app.cell
def _(Agent, AgentAnswer, MCPToolset, ModelRetry, download, duckdb):
    QUESTION = (
        "Which US hospitals sat in counties that stayed without power longest after the major "
        "storms of the past decade? Use HIFLD Next's hospital layer (version 1.1.0, find it "
        "with the MCP tools) and Heimdall Research's Storm Blackout and Restoration tables, "
        "version 1.2, on Zenodo: record 23010005, files listed at "
        "https://zenodo.org/api/records/23010005 (a file named X downloads from "
        "https://zenodo.org/api/records/23010005/files/X/content; the data dictionary is "
        "docs__DATA_DICTIONARY.md). Count a storm against a county when at least 10% of the "
        "county's customers were out at the peak and it took more than 72 hours to get 90% of "
        "them back, including counties never restored within the data's window. Use only "
        "FEMA-declared counties with utility records. Keep open hospitals only. Report how many "
        "hospitals, hospital-storm pairs and storms qualify, how many hospitals qualify in more "
        "than one storm, the 10 hospitals with the most qualifying storms, and a count by "
        "trauma level."
    )
    INSTRUCTIONS = (
        "You are a data analyst. Use the HIFLD Next MCP tools to find datasets and their file "
        "URLs. Use load_table to download a CSV or Parquet file by URL into a local DuckDB "
        "table, and sql to query those tables. Read documentation files with load_text. Check "
        "column meanings before you rely on them. Report numbers only from query results."
    )
    MCP_TOOLS = {
        "list_collections", "get_collection", "search_datasets", "get_dataset",
        "get_dataset_file", "get_dataset_file_schema", "read_geoparquet_rows",
        "query_parquet", "inspect_query_source", "get_query_page",
    }

    def make_agent(model: str) -> tuple[Agent[duckdb.DuckDBPyConnection, AgentAnswer], MCPToolset]:
        mcp = MCPToolset("https://hifld.publicenvirodata.org/mcp", max_retries=3)
        agent = Agent(
            f"openrouter:{model}",
            deps_type=duckdb.DuckDBPyConnection,
            toolsets=[mcp.filtered(lambda _ctx, tool: tool.name in MCP_TOOLS)],
            output_type=AgentAnswer,
            instructions=INSTRUCTIONS,
            retries=3,
            model_settings={"openrouter_usage": {"include": True}},
        )

        @agent.tool
        def load_table(ctx, url: str, table: str) -> str:  # noqa: ANN001
            """Download a .csv or .parquet file from an https URL into DuckDB table `table`."""
            if not url.startswith("https://") or not table.isidentifier():
                raise ModelRetry("url must be https and table a plain identifier")
            name = "agent_" + url.split("://", 1)[1].replace("/", "_")[-120:]
            try:
                path = download(url, name)
            except Exception as exc:  # the model sees the error and can fix the URL
                raise ModelRetry(f"download failed: {exc}") from exc
            reader = "read_parquet" if "parquet" in url else "read_csv_auto"
            try:
                ctx.deps.execute(f"CREATE OR REPLACE TABLE {table} AS SELECT * FROM {reader}(?)",
                                 [str(path)])
            except duckdb.Error as exc:
                raise ModelRetry(f"could not read the file: {exc}") from exc
            cols = ctx.deps.execute(f"DESCRIBE {table}").fetchall()
            rows = ctx.deps.execute(f"SELECT count(*) FROM {table}").fetchone()
            return f"{table}: {rows[0] if rows else 0} rows; columns " + ", ".join(
                f"{c[0]} {c[1]}" for c in cols
            )

        @agent.tool_plain
        def load_text(url: str) -> str:
            """Download a text or markdown file and return its first 30,000 characters."""
            if not url.startswith("https://"):
                raise ModelRetry("url must be https")
            name = "agent_" + url.split("://", 1)[1].replace("/", "_")[-120:]
            try:
                return download(url, name).read_text(errors="replace")[:30_000]
            except Exception as exc:
                raise ModelRetry(f"download failed: {exc}") from exc

        @agent.tool
        def sql(ctx, query: str) -> str:  # noqa: ANN001
            """Run one read-only SELECT in DuckDB. Returns at most 60 rows as CSV."""
            if not query.lstrip().lower().startswith(("select", "with", "describe")):
                raise ModelRetry("only SELECT, WITH or DESCRIBE queries")
            try:
                frame = ctx.deps.execute(query).pl()
            except duckdb.Error as exc:
                raise ModelRetry(f"query failed: {exc}") from exc
            return f"{frame.height} rows\n" + frame.head(60).write_csv()

        return agent, mcp

    return QUESTION, make_agent


@app.cell
async def _(
    AGENT_BUDGET_USD,
    AGENT_MODEL,
    AGENT_REPEATS,
    AGENT_RUN,
    ModelMessagesTypeAdapter,
    OUT,
    QUESTION,
    UsageLimits,
    asyncio,
    duckdb,
    json,
    make_agent,
    time,
):
    AGENT_DIR = OUT / "agent"
    AGENT_DIR.mkdir(exist_ok=True)

    async def attempt(n: int) -> dict:
        agent, mcp = make_agent(AGENT_MODEL)
        start = time.monotonic()
        record: dict = {"attempt": n, "model": AGENT_MODEL}
        with duckdb.connect() as con:
            try:
                async with mcp:
                    result = await asyncio.wait_for(
                        agent.run(QUESTION, deps=con, usage_limits=UsageLimits(request_limit=60)),
                        timeout=900,
                    )
            except Exception as exc:  # a failed attempt is a measured outcome
                return record | {"error": f"{type(exc).__name__}: {exc}"[:500],
                                 "seconds": round(time.monotonic() - start), "cost_usd": None}
        (AGENT_DIR / f"transcript_{n}.json").write_bytes(
            ModelMessagesTypeAdapter.dump_json(result.all_messages(), indent=1)
        )
        usage = result.usage
        return record | {
            "answer": result.output.model_dump(),
            "seconds": round(time.monotonic() - start),
            "cost_usd": float(usage.cost or 0),
            "requests": usage.requests,
            "tool_calls": usage.tool_calls,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
        }

    if AGENT_RUN:
        _spent = 0.0
        for _n in range(1, AGENT_REPEATS + 1):
            if _spent >= AGENT_BUDGET_USD:
                print(f"budget reached after {_n - 1} attempts")
                break
            _rec = await attempt(_n)
            _spent += _rec["cost_usd"] or 0
            (AGENT_DIR / f"answer_{_n}.json").write_text(json.dumps(_rec, indent=1))
            print(f"attempt {_n}: {_rec['seconds']} s, ${_rec['cost_usd'] or 0:.3f}",
                  _rec.get("error", ""))
    agent_records = [
        json.loads(p.read_text()) for p in sorted(AGENT_DIR.glob("answer_*.json"))
    ]
    print(f"{len(agent_records)} saved agent answers")
    return (agent_records,)


@app.cell
def _(mo):
    mo.md(r"""
    **Scoring.** We compare each answer's counts with ours (step 4, main test), and its top 10
    with our hospitals that have the most long storms. Because ties are common, a top-10 ID
    counts as right if that hospital has as many long storms as our tenth-ranked hospital.
    """)
    return


@app.cell
def _(agent_records, headlines, pl, ranking):
    _ours = headlines["main"]
    _cutoff = ranking["long_storms"][min(9, ranking.height - 1)]
    _top_ok = set(ranking.filter(pl.col("long_storms") >= _cutoff)["source_ID"].to_list())
    _rows = []
    for _r in agent_records:
        _a = _r.get("answer")
        if _a is None:
            _rows.append({"attempt": _r["attempt"], "error": _r.get("error")})
            continue
        _rows.append(
            {
                "attempt": _r["attempt"],
                "hospitals": _a["hospitals"],
                "pairs": _a["hospital_storm_pairs"],
                "storms": _a["storms"],
                "repeat_hospitals": _a["hospitals_more_than_once"],
                "top10_right": sum(i in _top_ok for i in _a["top_hospital_ids"][:10]),
                "seconds": _r["seconds"],
                "cost_usd": round(_r["cost_usd"] or 0, 4),
                "error": None,
            }
        )
    _rows.append(
        {"attempt": 0, "hospitals": _ours["hospitals"], "pairs": _ours["hospital_storm_pairs"],
         "storms": _ours["storms"], "repeat_hospitals": _ours["hospitals_more_than_once"],
         "top10_right": 10, "error": "ours (attempt 0)"}
    )
    agent_scores = pl.DataFrame(_rows)
    agent_scores
    return (agent_scores,)


@app.cell
def _(agent_records, mo):
    _parts = []
    for _r in agent_records:
        if _r.get("answer"):
            _parts.append(f"**Attempt {_r['attempt']}, method:** {_r['answer']['method']}")
    mo.md("\n\n".join(_parts) or "No saved agent answers.")
    return


@app.cell
def _(
    OUT,
    agent_scores,
    by_group,
    gap_shares,
    headlines,
    join_check,
    json,
    robust,
    storm_counts,
    storm_table,
):
    summary = {
        "storms": storm_counts,
        "hospital_join": join_check,
        "headline": headlines,
        "top5_storms_share_of_pairs": round(
            storm_table["hospitals"].head(5).sum() / storm_table["hospitals"].sum(), 3
        ),
        "top_storms": storm_table.head(5).select("name", "landfall", "hospitals").to_dicts(),
        "coverage_doubt_shares": gap_shares.to_dicts(),
        "robust_recount": robust,
        "by_beds_and_trauma": by_group.to_dicts(),
        "agent": agent_scores.to_dicts(),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(json.dumps(summary["headline"], indent=1))
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What this doesn't show

    - **Hours a hospital was without grid power.** Hospitals are priority loads with
      generators. This counts the grid around them.
    - **Hospitals that didn't exist at the time of a storm.** The layer is a 2024 snapshot with
      no opening dates. Closed hospitals are excluded, but a hospital that opened in 2020 is
      still counted against a 2016 storm.
    - **Storms before November 2014 or after 2025.** EAGLE-I has no county records then. The
      decade covered is 2014 to 2025, not the 14 years of Heimdall's storm list.
    - **The exact share out at hour 72.** Heimdall gives restoration hours, not an hourly
      series. The strict test is a lower bound.
    - **Counties not declared by FEMA.** Heimdall's outage run reads declared counties only.
    """)
    return


if __name__ == "__main__":
    app.run()

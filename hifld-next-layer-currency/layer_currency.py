import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(r"""
    # How current is the infrastructure data the country plans with?

    [HIFLD Next](https://hifld.publicenvirodata.org) preserves the federal HIFLD Open layers that planners,
    utilities and emergency managers used to map hospitals, power plants, dams, schools and shelters. We want to
    know how old the data in those layers is, which categories are oldest, and whether the agencies behind them
    have published something newer since.

    This notebook reads, for every layer in the catalog:

    1. the source's last-updated date that HIFLD Next recorded for it;
    2. the record dates inside the data (`SOURCEDATE`, `VAL_DATE` and the like), read column by column from the
       GeoParquet files without downloading whole layers;
    3. for the layers that matter for hazard and climate risk, plus a seeded random sample of 40 others, the date
       of the source agency's current publication, read live from a URL we found from the layer's own metadata.

    It writes `outputs/layer_currency.csv` (one row per layer) and `outputs/summary.json`.
    """)
    return (mo,)


@app.cell
def _():
    import csv
    import datetime as dt
    import html
    import json
    import os
    import random
    import re
    import statistics
    import time
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import duckdb
    import pandas as pd
    import requests

    HERE = Path(__file__).parent
    OUT = Path(os.environ.get("OUTPUT_DIR", HERE / "outputs"))
    OUT.mkdir(parents=True, exist_ok=True)
    HIFLD = os.environ.get("HIFLD_BASE_URL", "https://hifld.publicenvirodata.org")
    AS_OF = dt.date.fromisoformat(os.environ.get("AS_OF", dt.date.today().isoformat()))
    SEED = 171
    SAMPLE_SIZE = 40
    MAX_PAGES = 100
    STARTED = time.time()
    return (
        AS_OF,
        HERE,
        HIFLD,
        MAX_PAGES,
        OUT,
        SAMPLE_SIZE,
        SEED,
        STARTED,
        ThreadPoolExecutor,
        csv,
        dt,
        duckdb,
        html,
        json,
        pd,
        random,
        re,
        requests,
        statistics,
        time,
    )


@app.cell
def _(requests, time):
    HEADERS = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36",
        "Accept": "text/html,application/json,text/csv,*/*",
    }
    MAX_TRIES = 3

    def get(url: str) -> requests.Response:
        """GET with a fixed number of retries; raises on the last failure."""
        for attempt in range(1, MAX_TRIES + 1):
            try:
                response = requests.get(url, headers=HEADERS, timeout=60)
                response.raise_for_status()
                return response
            except requests.RequestException:
                if attempt == MAX_TRIES:
                    raise
                time.sleep(2**attempt)
        raise AssertionError("unreachable")

    return (get,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## The catalog

    HIFLD Next's [STAC API](https://hifld.publicenvirodata.org/stac) lists one STAC Collection per file and
    version, for example `hifld/hospitals-3/hospitals-3/v1.1.0`. Each one carries the source agency, the
    source's `issued` and `modified` dates (from the old HIFLD inventory), the column schema and the GeoParquet
    file. We page through all of them and keep the newest version of each file. A *layer* here is one HIFLD
    Next dataset; most have one file, a few (census blocks, local roads, the flood map, NHD) have one per state
    or theme.
    """)
    return


@app.cell
def _(HIFLD, MAX_PAGES, get):
    _url = f"{HIFLD}/stac/collections?limit=100"
    _collections = []
    for _page in range(MAX_PAGES):
        _body = get(_url).json()
        _collections += _body["collections"]
        _next = [link["href"] for link in _body["links"] if link["rel"] == "next"]
        if not _next:
            break
        _url = _next[0]
    else:
        raise RuntimeError(f"catalog still paging after {MAX_PAGES} pages")

    def version_key(collection_id: str) -> tuple[int, ...]:
        return tuple(int(part) for part in collection_id.rsplit("/v", 1)[1].split("."))

    latest = {}
    for _c in _collections:
        _file = _c["id"].rsplit("/", 1)[0]
        if _file not in latest or version_key(_c["id"]) > version_key(latest[_file]["id"]):
            latest[_file] = _c
    print(f"{len(_collections)} collections, {len(latest)} files after keeping the newest version")
    return (latest,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    Categories come from the dataset listing (`/api/collections/hifld/datasets`), where each dataset has
    HIFLD's own category tags. We use the first tag as the layer's category. A few datasets store their tags as
    one string rather than a list; we read those as a single tag.
    """)
    return


@app.cell
def _(HIFLD, MAX_PAGES, get):
    categories = {}
    for _page in range(MAX_PAGES):
        _body = get(f"{HIFLD}/api/collections/hifld/datasets?limit=50&offset={50 * _page}&omit=description").json()
        for _d in _body["datasets"]:
            _tags = _d.get("hifld:tags", {}).get("categories") or ["Uncategorized"]
            categories[_d["id"].split("/")[1]] = _tags if isinstance(_tags, str) else _tags[0]
        if 50 * (_page + 1) >= _body["total"]:
            break
    print(f"{len(categories)} datasets in the listing")
    return (categories,)


@app.cell
def _(categories, latest, pd):
    _rows = []
    for _file, _c in latest.items():
        _parquet = [a for k, a in _c["assets"].items() if k.startswith("geoparquet")]
        _dates = _c.get("hifld:source_dates") or {}
        _rows.append(
            {
                "file": _file,
                "layer": _file.split("/")[1],
                "title": _c["title"],
                "agency": _c["hifld:agency"],
                "issued": _dates.get("issued"),
                "modified": _dates.get("modified"),
                "features": _c["hifld:feature_count"],
                "parquet_urls": [a["href"] for a in _parquet],
                "parquet_bytes": sum(a["file:size"] for a in _parquet),
                "columns": [col["name"] for col in _c["table:columns"] if not col.get("is_geometry")],
            }
        )
    files = pd.DataFrame(_rows)
    files["category"] = files["layer"].map(categories).fillna("Uncategorized")
    print(
        f"{files['layer'].nunique()} layers, {len(files)} files, "
        f"{files['parquet_bytes'].sum() / 1e9:.1f} GB of GeoParquet, "
        f"{(files['parquet_urls'].str.len() == 0).sum()} files with no GeoParquet, "
        f"{(files['parquet_urls'].str.len() > 1).sum()} split into parts"
    )
    files.groupby("category")["layer"].nunique().sort_values(ascending=False).head(15)
    return (files,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Which columns hold record dates

    The schemas use dozens of names for a date. We sort them into two kinds by name:

    - **Record-currency columns** say when a record was sourced, validated, loaded or updated: `SOURCEDATE`,
      `VAL_DATE`, `LOADDATE`, `UPDATE_DATE`, `DATA_UPDAT` (the dams layer's truncated "data updated"),
      `Source_Dat` in the USACE charts, `FDATE` in NHD, `CONTDATE` and `GEODATE` (contact and geocode dates in
      the TechniGraphics layers) and similar. These are what we use when a layer has them.
    - **Event columns** date the thing being mapped, such as an earthquake, a fire perimeter or a permit
      inspection. For a layer with no record-currency column, its newest event is the newest data it holds.

    We leave out dates that describe the facility, not the data (year built, opened, planned retirement, lease
    expiry), and names that only look like dates (`TIMEZONE`, `Source_Dataset`, `attr_ModifiedBySystem`).
    """)
    return


@app.cell
def _(files, re):
    RECORD = re.compile(
        r"source_?dat|src_?date|val_?date|load_?date|updat|updte|modif|date_?mod|edit_?date|date_?current"
        r"|last_?reported|last_?confirmed|dbrev|pub_?date|download_?date|featuredate|map_date|data_?year"
        r"|census_?year|datestamp|extrdate|run_?date|create_?date|createdon|contdate|geodate|^fdate$"
        r"|eff_date|base_date",
        re.I,
    )
    EVENT = re.compile(r"date|_dt$|^year$|time", re.I)
    NOT_DATA = re.compile(
        r"plan|expect|expir|retire|future|target|built|constr|open|estab|est$|compl|operat|spud|termin|closeout"
        r"|remedy|response|lease|activ|time_zone|timezone|unit|trips|cost|average|inspect|fracture|undwater"
        r"|spec_last|recovery|fed_reg|aprv|apprv|effect|vacate|ret_date|stat_date|close|pre_date|pal_date"
        r"|^edate$|effdate|mag_varn|year_of|yr_|year_rec|adt|signal|^date$|source_?data|sourcedata|modifiedby",
        re.I,
    )

    _jobs = []
    for _f in files.itertuples():
        if not _f.parquet_urls:
            continue
        _usable = [c for c in _f.columns if not NOT_DATA.search(c)]
        _record = [c for c in _usable if RECORD.search(c)]
        _event = [c for c in _usable if EVENT.search(c) and not RECORD.search(c)]
        _jobs += [(_f.file, tuple(_f.parquet_urls), c, "record") for c in _record]
        _jobs += [(_f.file, tuple(_f.parquet_urls), c, "event") for c in (_event if not _record else [])]
    date_jobs = _jobs
    print(
        f"{len(date_jobs)} date columns to read in {len({j[0] for j in date_jobs})} files "
        f"({sum(j[3] == 'record' for j in date_jobs)} record-currency, {sum(j[3] == 'event' for j in date_jobs)} event)"
    )
    return (date_jobs,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Reading the dates without downloading the layers

    [DuckDB](https://duckdb.org/docs/stable/data/parquet/overview) reads a Parquet file over HTTPS with range
    requests: the footer first, then only the column chunks a query names. So reading `SOURCEDATE` from the
    hospitals layer fetches that one column, not the geometry. We count the bytes from each file's own Parquet
    metadata (the compressed size of the columns read).

    Almost every date is stored as text, in a dozen formats: ISO with or without a time, `YYYY/MM/DD`,
    `YYYYMMDD`, `MMDDYYYY`, `M/D/YYYY`, `MM/YYYY`, a bare year, epoch milliseconds, and in one layer an Excel day
    number. One SQL macro tries each in turn. A bare year counts as 31 December of that year, so it can only make
    a layer look newer, never older. We drop dates before 1800 and after the run date (placeholders such as
    `9999-09-09`, and scheduled dates in the future). For the copies rescued from HIFLD Open (version `v1.0.0`)
    the cutoff is 26 August 2025, the day DHS discontinued HIFLD Open
    ([NAPSG](https://www.napsgfoundation.org/navigating-the-hifld-transition/)): a later date in those files is a
    scheduled date or an error, not a record. `future` counts the values dropped this way.
    """)
    return


@app.cell
def _(AS_OF, ThreadPoolExecutor, date_jobs, dt, duckdb, re, time):
    HIFLD_OPEN_END = dt.date(2025, 8, 26)

    def file_version(url: str) -> str:
        found = re.search(r"/(v\d+\.\d+\.\d+)/", url)
        return found.group(1) if found else ""

    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs;")
    con.sql(r"""
        CREATE MACRO parse_date(x, cutoff) AS (
            WITH s AS (SELECT trim(CAST(x AS VARCHAR)) AS v)
            SELECT COALESCE(
                TRY_CAST(replace(substr(v, 1, 10), '/', '-') AS DATE),
                CASE WHEN regexp_full_match(v, '\d{8}') THEN COALESCE(
                    TRY_CAST(try_strptime(v, '%Y%m%d') AS DATE), TRY_CAST(try_strptime(v, '%m%d%Y') AS DATE)) END,
                TRY_CAST(try_strptime(v, '%m/%d/%Y') AS DATE),
                TRY_CAST(try_strptime(v, '%m/%Y') AS DATE),
                TRY_CAST(try_strptime(v, '%Y-%m') AS DATE),
                CASE WHEN regexp_full_match(v, '\d{4}(\.0+)?')
                    THEN least(make_date(CAST(substr(v, 1, 4) AS INT), 12, 31), cutoff) END,
                CASE WHEN regexp_full_match(v, '\d{5}(\.0+)?') AND CAST(v AS DOUBLE) BETWEEN 20000 AND 60000
                    THEN DATE '1899-12-30' + CAST(CAST(v AS DOUBLE) AS INT) END,
                CASE WHEN regexp_full_match(v, '\d{11,13}(\.0+)?')
                    THEN CAST(to_timestamp(CAST(v AS DOUBLE) / 1000) AS DATE) END)
            FROM s)
    """)

    def read_dates(job: tuple[str, tuple[str, ...], str, str]) -> dict:
        file, parts, column, kind = job
        url = "[" + ", ".join(f"'{part}'" for part in parts) + "]"
        cursor = con.cursor()
        # A v1.0.0 file is the copy rescued from HIFLD Open, so no record in it can postdate the shutdown.
        cutoff = HIFLD_OPEN_END if file_version(parts[0]) == "v1.0.0" else AS_OF
        ok = f"d BETWEEN DATE '1800-01-01' AND DATE '{cutoff}'"
        try:
            stats = cursor.sql(f"""
                WITH t AS (
                    SELECT parse_date("{column}", DATE '{cutoff}') AS d
                    FROM read_parquet({url}, union_by_name = true))
                SELECT count(*), count(*) FILTER ({ok}), min(d) FILTER ({ok}),
                       quantile_disc(d, 0.1) FILTER ({ok}), quantile_disc(d, 0.5) FILTER ({ok}), max(d) FILTER ({ok}),
                       count(*) FILTER (d > DATE '{cutoff}')
                FROM t""").fetchall()[0]
            size = cursor.sql(
                f"SELECT sum(total_compressed_size) FROM parquet_metadata({url}) WHERE path_in_schema = '{column}'"
            ).fetchall()[0][0]
        except duckdb.Error as error:
            return {"file": file, "column": column, "kind": kind, "error": str(error)[:200]}
        keys = ["rows", "dated", "min", "p10", "median", "max", "future"]
        return {"file": file, "column": column, "kind": kind, **dict(zip(keys, stats, strict=True)), "bytes": size}

    _t = time.time()
    with ThreadPoolExecutor(16) as _pool:
        date_reads = list(_pool.map(read_dates, date_jobs))
    read_seconds = time.time() - _t
    _errors = [r for r in date_reads if r.get("error")]
    print(f"read {len(date_reads)} columns in {read_seconds:.0f} s, {len(_errors)} errors")
    assert len(_errors) < len(date_reads) / 10, _errors[:3]
    return date_reads, read_seconds


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## One row per layer

    For each layer we take:

    - **newest record date**: the newest date across its record-currency columns, or, if it has none, across its
      event columns;
    - **the spread**: the 10th percentile and median of the column with the most dated values (the most complete
      `SOURCEDATE` or `VAL_DATE`), so a layer whose newest record is recent but whose typical record is a decade
      old shows both;
    - **metadata date**: the newest `modified` (or, failing that, `issued`) date HIFLD Next recorded across the
      layer's files.

    The layer's **best date** is its newest record date when it has one, else its metadata date, and its age is
    measured from the run date. `how_dated` says which it was. A layer with neither is flagged with the reason.
    """)
    return


@app.cell
def _(AS_OF, date_reads, files, pd):
    reads = pd.DataFrame([r for r in date_reads if not r.get("error") and r["dated"]])
    reads = reads.merge(files[["file", "layer"]], on="file")
    _cols_tried = pd.DataFrame(date_reads).merge(files[["file", "layer"]], on="file").groupby("layer")["column"]

    _rows = []
    for _layer, _f in files.groupby("layer", sort=True):
        _r = reads[reads["layer"] == _layer]
        _kind = "record" if (_r["kind"] == "record").any() else "event" if len(_r) else None
        _r = _r[_r["kind"] == _kind]
        _main = _r.sort_values("dated", ascending=False).iloc[0] if len(_r) else None
        _meta = pd.to_datetime(_f["modified"].fillna(_f["issued"]), errors="coerce").max()
        _newest = _r["max"].max() if len(_r) else None
        _tried = list(_cols_tried.get_group(_layer)) if _layer in _cols_tried.groups else []
        if _newest is not None and _main is not None:
            _how, _best, _flag = f"{_kind} column {_main['column']}", pd.Timestamp(_newest), ""
        elif pd.notna(_meta):
            _how, _best = "metadata modified/issued date", _meta
            _flag = "date columns present but empty or unparseable" if _tried else "no date column in the data"
        else:
            _how, _best = "none", pd.NaT
            _flag = "no date column and no metadata date"
        _rows.append(
            {
                "layer": _layer,
                "title": _f["title"].iloc[0],
                "category": _f["category"].iloc[0],
                "agency": _f["agency"].dropna().iloc[0] if _f["agency"].notna().any() else "",
                "files": len(_f),
                "features": int(_f["features"].fillna(0).sum()),
                "metadata_date": _meta.date() if pd.notna(_meta) else None,
                "record_column": _main["column"] if _main is not None else "",
                "records_dated_share": round(_main["dated"] / _main["rows"], 3) if _main is not None else None,
                "record_min": _r["min"].min() if len(_r) else None,
                "record_p10": _main["p10"] if _main is not None else None,
                "record_median": _main["median"] if _main is not None else None,
                "record_max": _newest,
                "best_date": _best.date() if pd.notna(_best) else None,
                "how_dated": _how,
                "flag": _flag,
            }
        )
    layers = pd.DataFrame(_rows)
    layers["age_years"] = ((pd.Timestamp(AS_OF) - pd.to_datetime(layers["best_date"])).dt.days / 365.25).round(2)
    _shutdown = pd.Timestamp("2025-08-26")
    layers["age_at_shutdown_years"] = ((_shutdown - pd.to_datetime(layers["best_date"])).dt.days / 365.25).round(2)
    layers["how_dated"].str.split(" column").str[0].value_counts()
    return (layers,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## How old is the newest data in each layer?

    The share of layers whose best date is more than one, three and five years before the run date, overall
    and by category. The second table repeats it for the layers dated from their own records only, since a
    metadata `modified` date can move when an item is re-published without new data.

    Every rescued copy stopped at HIFLD Open's shutdown on 26 August 2025, so by now every layer is over a year
    old by construction. The `_at_shutdown` columns ask the sharper question: how old was the data already on
    the day HIFLD Open went dark?
    """)
    return


@app.cell
def _(layers, pd):
    def age_shares(frame: pd.DataFrame) -> pd.Series:
        dated = frame["age_years"].dropna()
        return pd.Series(
            {
                "layers": len(frame),
                "dated": len(dated),
                "over_1y": round((dated > 1).mean(), 3),
                "over_3y": round((dated > 3).mean(), 3),
                "over_5y": round((dated > 5).mean(), 3),
                "median_age_y": round(dated.median(), 1),
                "over_1y_at_shutdown": round((frame["age_at_shutdown_years"].dropna() > 1).mean(), 3),
                "over_3y_at_shutdown": round((frame["age_at_shutdown_years"].dropna() > 3).mean(), 3),
            }
        )

    overall = age_shares(layers)
    record_only = age_shares(layers[layers["how_dated"].str.startswith(("record", "event"))])
    by_category = (
        layers.groupby("category").apply(age_shares, include_groups=False).sort_values("layers", ascending=False)
    )
    print("All layers:", overall.to_dict())
    print("Layers dated from their own records:", record_only.to_dict())
    by_category
    return age_shares, by_category, overall, record_only


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Has the source published something newer?

    For the layers that matter for hazard and climate risk (hospitals, fire and EMS, shelters, schools, power
    plants, transmission, dams, the flood map, fire perimeters and the like, 33 in all) and a seeded random sample
    of 40 of the rest, we looked for the agency's current publication, starting only from the layer's own
    metadata: its agency, office, title and any URL in its description. Each find is a row in
    `source_checks.csv` with a URL and a regular expression for the date, the same approach as
    `rescued-data-currency/`. Here the notebook re-reads every URL and takes the newest date the pattern matches,
    so the dates are from this run.

    A source counts as **newer** when its date is more than 30 days after the layer's best date. A year-only
    source date counts as 1 January and a month as its first day, so the gap is never overstated. Rows with no
    URL (no current source found, the agency stopped publishing it, or the site blocks scripts) keep the status
    we recorded by hand, and say so in `how_checked`.
    """)
    return


@app.cell
def _(SAMPLE_SIZE, SEED, layers, random):
    CLIMATE_RISK = [
        "hospitals-3", "trauma-levels", "fire-and-emergency-medical-service-ems-stations",
        "local-emergency-operations-center-eoc", "state-emergency-operations-centers-eoc",
        "national-shelter-system-facilities", "nursing-homes", "dialysis-centers",
        "veterans-health-administration-medical-facilities", "child-care-centers", "public-schools",
        "private-schools", "colleges-and-universities", "local-law-enforcement-locations", "prison-boundaries-1",
        "mobile-home-parks", "power-plants-1", "generating-units-1", "transmission-lines-1",
        "electric-retail-service-territories", "natural-gas-interstate-and-intrastate-pipelines",
        "petroleum-refineries", "national-inventory-of-dams-nid-1", "icis-wastewater-treatment-plants",
        "epa-emergency-response-rmp-facilities", "epa-superfund-enterprise-management-system-sems-sites-1",
        "cellular-towers", "national-bridge-inventory-nbi", "nfhl", "wfigs-interagency-fire-perimeters",
        "us-landslide-regions", "quaternary-fault-lines", "uniform-hazard-ground-motion",
    ]  # fmt: skip
    _all = sorted(layers["layer"])
    assert set(CLIMATE_RISK) <= set(_all), set(CLIMATE_RISK) - set(_all)
    sample = random.Random(SEED).sample([x for x in _all if x not in CLIMATE_RISK], SAMPLE_SIZE)
    print(f"{len(CLIMATE_RISK)} climate-risk layers + {len(sample)} sampled with seed {SEED}")
    return CLIMATE_RISK, sample


@app.cell
def _(HERE, ThreadPoolExecutor, dt, get, html, pd, re):
    MONTHS = {m: i for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
         "november", "december"], start=1)}  # fmt: skip

    def match_to_date(groups: dict[str, str | None]) -> dt.date:
        """The earliest day the match can mean: a year is 1 January, a month its first day."""
        if groups.get("ms"):
            return dt.datetime.fromtimestamp(int(groups["ms"] or 0) / 1000, dt.UTC).date()
        month = groups.get("m") or "1"
        month_number = MONTHS.get(month.lower()) or int(month)
        return dt.date(int(groups["y"] or 0), month_number, int(groups.get("d") or 1))

    def read_source(url: str, pattern: str) -> dt.date:
        response = get(url)
        text = response.text
        if "html" in response.headers.get("Content-Type", ""):
            text += " " + html.unescape(re.sub(r"<[^>]+>", " ", text))
        dates = [match_to_date(m.groupdict()) for m in re.finditer(pattern, text)]
        if not dates:
            raise ValueError(f"no date matched; the response starts {text[:100]!r}")
        return max(dates)

    def check(row: dict) -> tuple[str, dt.date | None, str]:
        if not row["check_url"]:
            return row["layer"], None, f"by hand: {row['status']}"
        try:
            return row["layer"], read_source(row["check_url"], row["check_pattern"]), "script"
        except (ValueError, OSError) as error:
            return row["layer"], None, f"read failed ({type(error).__name__}); by hand: {row['status']}"

    source_checks = pd.read_csv(HERE / "source_checks.csv", dtype=str, keep_default_na=False)
    with ThreadPoolExecutor(8) as _pool:
        _results = list(_pool.map(check, source_checks.to_dict("records")))
    source_live = pd.DataFrame(_results, columns=["layer", "source_date_live", "how_checked"])
    print(source_live["how_checked"].str.split(" \\(").str[0].value_counts().to_dict())
    return source_checks, source_live


@app.cell
def _(CLIMATE_RISK, layers, pd, sample, source_checks, source_live):
    checked = layers[layers["layer"].isin(CLIMATE_RISK + sample)].merge(
        source_checks[["layer", "current_source", "check_url", "status", "date_meaning", "notes"]],
        on="layer",
        how="left",
    )
    checked = checked.merge(source_live, on="layer", how="left")
    assert checked["current_source"].notna().all(), checked.loc[checked["current_source"].isna(), "layer"].tolist()
    checked["group"] = checked["layer"].map(lambda x: "climate risk" if x in CLIMATE_RISK else "sample")
    _gap = (pd.to_datetime(checked["source_date_live"]) - pd.to_datetime(checked["best_date"])).dt.days / 365.25
    checked["gap_years"] = _gap.round(2)

    def verdict(row: pd.Series) -> str:
        if pd.notna(row["source_date_live"]):
            return "newer" if row["gap_years"] > 30 / 365.25 else "not newer"
        return {"newer": "newer (by hand)", "same": "not newer (by hand)"}.get(row["status"], row["status"])

    checked["source_verdict"] = checked.apply(verdict, axis=1)
    checked.groupby("group")["source_verdict"].value_counts().unstack(fill_value=0)
    return (checked,)


@app.cell
def _(checked):
    _found = checked[checked["source_verdict"].str.startswith(("newer", "not newer"))]
    _newer = _found["source_verdict"].str.startswith("newer")
    _gaps = checked.loc[checked["source_verdict"] == "newer", "gap_years"]
    source_stats = {
        "checked": len(checked),
        "current_source_dated": len(_found),
        "newer": int(_newer.sum()),
        "share_newer_of_dated": round(_newer.mean(), 3),
        "median_gap_years_where_newer": round(_gaps.median(), 2),
        "by_group": {
            g: {
                "checked": len(f),
                "dated": int(f["source_verdict"].str.startswith(("newer", "not newer")).sum()),
                "newer": int(f["source_verdict"].str.startswith("newer").sum()),
                "median_gap_years_where_newer": round(f.loc[f["source_verdict"] == "newer", "gap_years"].median(), 2),
            }
            for g, f in checked.groupby("group")
        },
        "no_current_source": checked.loc[
            ~checked["source_verdict"].str.startswith(("newer", "not newer")), "source_verdict"
        ]
        .value_counts()
        .to_dict(),
    }
    source_stats
    return (source_stats,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## The ten stalest climate-risk layers

    Sorted by the age of their newest data. The record median shows how old a typical record is.
    """)
    return


@app.cell
def _(checked):
    stalest = checked[checked["group"] == "climate risk"].sort_values("age_years", ascending=False).head(10)
    stalest[
        ["title", "best_date", "how_dated", "record_median", "age_years", "current_source", "source_date_live",
         "source_verdict"]
    ]  # fmt: skip
    return (stalest,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Layers with no usable record date

    Most of the catalog has no date column at all: census geography, the USACE inland chart layers that store
    their source date in a separate table, and many boundary layers. Those fall back to the metadata date.
    """)
    return


@app.cell
def _(layers):
    no_record_date = layers[~layers["how_dated"].str.startswith(("record", "event"))]
    print(no_record_date["flag"].value_counts().to_dict())
    no_record_date.groupby("category")["layer"].count().sort_values(ascending=False).head(10)
    return (no_record_date,)


@app.cell
def _(
    AS_OF,
    OUT,
    STARTED,
    by_category,
    checked,
    date_reads,
    files,
    json,
    layers,
    no_record_date,
    overall,
    read_seconds,
    record_only,
    source_stats,
    stalest,
    time,
):
    _out = layers.merge(
        checked[["layer", "group", "current_source", "check_url", "source_date_live", "gap_years", "source_verdict",
                 "how_checked"]], on="layer", how="left",
    )  # fmt: skip
    _out.to_csv(OUT / "layer_currency.csv", index=False)
    _bytes = sum(r.get("bytes") or 0 for r in date_reads)
    summary = {
        "as_of": AS_OF.isoformat(),
        "layers": int(layers["layer"].nunique()),
        "files": len(files),
        "geoparquet_gb_in_catalog": round(files["parquet_bytes"].sum() / 1e9, 1),
        "date_columns_read": len(date_reads),
        "date_column_mb_read": round(_bytes / 1e6, 1),
        "date_read_seconds": round(read_seconds, 1),
        "run_seconds": round(time.time() - STARTED, 1),
        "cost_usd": 0,
        "all_layers": overall.to_dict(),
        "layers_dated_from_records": record_only.to_dict(),
        "how_dated": layers["how_dated"].str.split(" column").str[0].value_counts().to_dict(),
        "no_record_date_reasons": no_record_date["flag"].value_counts().to_dict(),
        "by_category": by_category.reset_index().to_dict("records"),
        "source_check": source_stats,
        "stalest_climate_risk": stalest[["layer", "best_date", "age_years", "source_verdict"]]
        .astype(str)
        .to_dict("records"),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    print(
        json.dumps(
            {k: v for k, v in summary.items() if k not in ("by_category", "stalest_climate_risk")},
            indent=1,
            default=str,
        )
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## What this doesn't show

    - **The layers HIFLD Next doesn't have.** Electric substations and other layers HIFLD moved behind its
      secure tier before 2025 aren't in the catalog, so they aren't measured here.
    - **A record date is the date someone last touched the record**, not proof it's right. A `VAL_DATE` of 2024
      on a hospital means it was validated then, not that nothing has changed since.
    - **Metadata dates are weaker.** Most `modified` dates cluster in spring 2025, when HIFLD Open re-published
      its inventory before shutting down. For layers dated only that way, the age is a floor.
    - **Source checks rest on one URL each.** We found each current source from the layer's metadata and read
      one date from it. A source we couldn't find may still exist under another name.
    """)
    return


if __name__ == "__main__":
    app.run()

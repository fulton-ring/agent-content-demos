import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import asyncio
    import json
    import os
    import re
    import time
    from dataclasses import replace

    import duckdb
    import httpx
    import marimo as mo
    import polars as pl
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent, capture_run_messages
    from pydantic_ai.mcp import MCPToolset
    from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse
    from pydantic_ai.usage import UsageLimits

    return (
        Agent,
        BaseModel,
        Field,
        MCPToolset,
        ModelMessagesTypeAdapter,
        ModelResponse,
        UsageLimits,
        asyncio,
        capture_run_messages,
        duckdb,
        httpx,
        json,
        mo,
        os,
        pl,
        re,
        replace,
        time,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Do codes that differ between HIFLD Next layers lead an AI agent to wrong joins?

    [HIFLD Next](https://hifld.publicenvirodata.org) puts 500-plus layers from separate federal
    owners in one catalog with one MCP server. Many layers share field names such as `STATE`,
    `COUNTYFIPS` or `STATUS`. If the same name holds a different format or meaning in different
    layers, an agent that carries a code from one layer to another can get no match (safe) or a
    match to the wrong place (not safe). Issue: #194.

    This notebook does four things, top to bottom:

    1. **Inventory**: read every value of nine shared identifier fields in every layer and
       classify its format and meaning.
    2. **Questions and answer key**: 24 questions that need a join between two layers, or between
       a layer and FEMA's National Risk Index (NRI). The key comes from a spatial join of each
       facility's point to the Census county polygons, never from the codes.
    3. **Agent**: a Pydantic AI agent on the HIFLD Next MCP server answers each question, scored
       correct, no match or wrong match.
    4. **Metadata fix**: the same agent again, with code descriptions generated from the
       inventory added to the MCP tool descriptions it reads.
    """)
    return


@app.cell
def _(mo, os):
    BASE_URL = os.environ.get("HIFLD_BASE_URL", "https://hifld.publicenvirodata.org")
    MCP_URL = f"{BASE_URL}/mcp"
    NRI_URL = (
        "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
        "National_Risk_Index_Counties/FeatureServer/0/query"
    )
    MODEL = os.environ.get("AGENT_MODEL", "anthropic/claude-haiku-5.5")
    REPEATS = int(os.environ.get("AGENT_REPEATS", "2"))
    BUDGET_USD = float(os.environ.get("AGENT_BUDGET_USD", "4.0"))
    # Call the models only when asked; otherwise score the saved answers in outputs/.
    RUN_AGENT = os.environ.get("RUN_AGENT", "0") == "1"
    # The nine shared identifier fields we check, matched case-insensitively.
    FIELDS = {
        "STATE": "state",
        "COUNTY": "county",
        "COUNTYFIPS": "county code",
        "FIPS": "county code",
        "FIPS_CODE": "county code",
        "ZIP": "zip",
        "NAICS_CODE": "naics",
        "STATUS": "status",
        "TYPE": "type",
    }
    MAX_ROWS_READ = 200_000  # per layer and field; the big layers are read up to this many rows
    HERE = mo.notebook_dir()
    OUT = HERE / "outputs"
    OUT.mkdir(exist_ok=True)
    return (
        BASE_URL,
        BUDGET_USD,
        FIELDS,
        HERE,
        MAX_ROWS_READ,
        MCP_URL,
        MODEL,
        NRI_URL,
        OUT,
        REPEATS,
        RUN_AGENT,
    )


@app.cell
def _(duckdb, os):
    # DuckDB reads the public GeoParquet files over HTTPS. Behind a proxy it needs to be told.
    db = duckdb.connect()
    db.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
    _proxy = os.environ.get("HTTPS_PROXY", "").removeprefix("http://").rstrip("/")
    if _proxy:
        db.execute(f"SET http_proxy = '{_proxy}'")
    return (db,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. The catalog

    The portal's STAC API lists every layer (one GeoParquet file each) with its column schema.
    We keep the latest version of each file.
    """)
    return


@app.cell
def _(BASE_URL, httpx, pl):
    _url = f"{BASE_URL}/stac/collections?limit=100"
    _collections = []
    for _page in range(50):  # about 6 pages today; the bound stops a runaway cursor
        _resp = httpx.get(_url, timeout=120)
        _resp.raise_for_status()
        _body = _resp.json()
        _collections += _body["collections"]
        _next = [link for link in _body["links"] if link["rel"] == "next"]
        if not _next:
            break
        _url = _next[0]["href"]
    else:
        raise RuntimeError("STAC paging did not finish in 50 pages")

    _latest = {}
    for _c in _collections:
        _layer = "/".join(_c["id"].split("/")[:3])
        if _layer not in _latest or _c["id"] > _latest[_layer]["id"]:
            _latest[_layer] = _c
    layers = pl.DataFrame(
        [
            {
                "layer": _layer,
                "slug": _layer.split("/")[1]
                if _layer.split("/")[1] == _layer.split("/")[2]
                else "/".join(_layer.split("/")[1:]),
                "title": _c.get("title"),
                "rows": _c.get("hifld:feature_count"),
                "parquet": next(
                    (
                        a["href"]
                        for a in _c["assets"].values()
                        if a.get("type") == "application/vnd.apache.parquet"
                    ),
                    None,
                ),
                "columns": [col["name"] for col in _c.get("table:columns") or []],
                "column_types": [col.get("type") for col in _c.get("table:columns") or []],
            }
            for _layer, _c in _latest.items()
        ]
    )
    print(f"{len(_collections)} STAC collections, {layers.height} layers after keeping the latest")
    return (layers,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Inventory of shared identifier fields

    For each layer that has one of the nine fields, we read the column's values from the
    GeoParquet file (up to 200,000 rows) and count each distinct value. Reading real values, not
    the catalog's five example values, matters: several problems below sit in a minority of
    rows. The catalog sometimes lists a column twice in different case (`ID` and `id`) when the
    file has only one; we use the file's own column list.
    """)
    return


@app.cell
def _(FIELDS, MAX_ROWS_READ, db, layers, pl):
    from concurrent.futures import ThreadPoolExecutor

    def read_values(job: tuple[str, str, str, str]) -> dict:
        layer, listed, catalog_type, href = job
        con = db.cursor()
        file_cols = [
            r[0]
            for r in con.execute(
                f"DESCRIBE SELECT * FROM read_parquet('{href}') LIMIT 0"
            ).fetchall()
        ]
        column = next((c for c in file_cols if c.upper() == listed.upper()), None)
        if column is None:
            return {
                "layer": layer,
                "column": listed,
                "type": catalog_type,
                "error": "listed in the catalog schema but not in the file",
            }
        sql = (
            f"WITH s AS (SELECT CAST(\"{column}\" AS VARCHAR) v FROM read_parquet('{href}') "
            f"LIMIT {MAX_ROWS_READ}) SELECT v, count(*) n FROM s GROUP BY v ORDER BY n DESC"
        )
        error = None
        for _attempt in range(3):
            try:
                rows = con.execute(sql).fetchall()
                return {"layer": layer, "column": column, "type": catalog_type, "values": rows}
            except Exception as exc:  # recorded and reported below, not swallowed
                error = f"{type(exc).__name__}: {exc}"[:200]
        return {"layer": layer, "column": column, "type": catalog_type, "error": error}

    _jobs = []
    for _row in layers.filter(pl.col("parquet").is_not_null()).iter_rows(named=True):
        _seen = set()
        for _name, _type in zip(_row["columns"], _row["column_types"], strict=True):
            if _name.upper() in FIELDS and _name.upper() not in _seen:
                _seen.add(_name.upper())
                _jobs.append((_row["layer"], _name, _type or "", _row["parquet"]))
    with ThreadPoolExecutor(12) as _pool:
        raw_values = list(_pool.map(read_values, _jobs))
    _failed = [r for r in raw_values if "error" in r]
    print(f"{len(_jobs)} layer-field pairs read, {len(_failed)} failed")
    for _r in _failed:
        print("  failed:", _r["layer"], _r["column"], _r["error"])
    return (raw_values,)


@app.cell
def _(mo):
    mo.md(r"""
    **How a value is classified.** Each field family has a few regular expressions, one per
    format (for example a county code is a 5-digit FIPS like `48029`, a float like `6037.0`, a
    4-digit code that lost its leading zero, or letters plus digits like `ME011`). A layer's
    format is the class that holds at least 90% of its non-blank values, otherwise `mixed`.
    County codes also get a meaning check against the Census county list in HIFLD Next's own
    county layer: is the code a real county, the county and state parts reversed, or one of
    Connecticut's eight old counties that the Census replaced with nine planning regions in 2022?
    """)
    return


@app.cell
def _(db, layers, pl):
    _county_href = layers.filter(pl.col("slug") == "us-county-boundaries-1")["parquet"][0]
    db.execute(
        f"CREATE OR REPLACE TABLE counties AS SELECT GEOID, NAME, NAMELSAD, STATEFP, geometry "
        f"FROM read_parquet('{_county_href}')"
    )
    county_geoids = {r[0] for r in db.execute("SELECT GEOID FROM counties").fetchall()}
    # Connecticut's eight counties before the 2022 change to planning regions (09110-09190).
    CT_LEGACY = {f"090{n:02d}" for n in range(1, 16, 2)}
    print(f"{len(county_geoids)} county GEOIDs in HIFLD Next's county layer")
    return CT_LEGACY, county_geoids


@app.cell
def _(CT_LEGACY, FIELDS, county_geoids, pl, raw_values, re):
    STATE_NAMES = {
        "alabama",
        "alaska",
        "arizona",
        "arkansas",
        "california",
        "colorado",
        "connecticut",
        "delaware",
        "district of columbia",
        "florida",
        "georgia",
        "hawaii",
        "idaho",
        "illinois",
        "indiana",
        "iowa",
        "kansas",
        "kentucky",
        "louisiana",
        "maine",
        "maryland",
        "massachusetts",
        "michigan",
        "minnesota",
        "mississippi",
        "missouri",
        "montana",
        "nebraska",
        "nevada",
        "new hampshire",
        "new jersey",
        "new mexico",
        "new york",
        "north carolina",
        "north dakota",
        "ohio",
        "oklahoma",
        "oregon",
        "pennsylvania",
        "rhode island",
        "south carolina",
        "south dakota",
        "tennessee",
        "texas",
        "utah",
        "vermont",
        "virginia",
        "washington",
        "west virginia",
        "wisconsin",
        "wyoming",
        "puerto rico",
        "guam",
        "virgin islands",
        "american samoa",
        "northern mariana islands",
    }
    # (pattern, label) in order; the first match wins.
    PATTERNS = {
        "state": [
            (r"[A-Z]{2}", "postal code (TX)"),
            (r"[a-z]{2}", "lowercase postal code (tx)"),
            (r"\d{2}", "state FIPS number (48)"),
        ],
        "county": [
            (r"\d{3}", "3-digit county FIPS (029)"),
            (r"\d+", "other number"),
            (r"[A-Za-z][A-Za-z .'\-]*[A-Za-z.]", "county name (Bexar)"),
            (r"[A-Za-z][A-Za-z .'\-]*\s+", "county name + trailing spaces"),
        ],
        "county code": [
            (r"\d{5}", "5-digit county FIPS (48029)"),
            (r"\d{5}\s+", "5-digit FIPS + trailing space"),
            (r"\d{4,5}\.0", "float, leading zero lost (6037.0)"),
            (r"\d{4}", "4 digits, leading zero lost (6037)"),
            (r"\d{2}", "2-digit state FIPS (48)"),
            (r"[A-Z]{2}\d{3}", "state letters + county digits (ME011)"),
            (r"[A-Za-z][A-Za-z .'\-]+", "county name"),
        ],
        "zip": [
            (r"\d{5}", "5-digit ZIP"),
            (r"\d{5}-\d{4}", "ZIP+4"),
            (r"\d{5}\s+", "5-digit ZIP + trailing space"),
            (r"\d{3,4}", "leading zero lost (2110)"),
            (r"[A-Z]{2}", "state code"),
        ],
        "naics": [
            (r"\d{2}", "2-digit NAICS"),
            (r"\d{4}", "4-digit NAICS"),
            (r"\d{6}", "6-digit NAICS"),
            (r"\d{3}|\d{5}", "3 or 5-digit NAICS"),
        ],
    }
    BLANK = {"", "NOT AVAILABLE", "NONE", "NULL", "N/A", "NAN", "0"}

    def short_name(layer: str) -> str:
        _, dataset, file = layer.split("/")
        return dataset if dataset == file else f"{dataset}/{file}"

    def classify(family: str, value: str) -> str:
        if family == "state" and value.strip().lower() in STATE_NAMES:
            return "full state name (Texas)"
        for pattern, label in PATTERNS[family]:
            if re.fullmatch(pattern, value):
                return label
        return "other"

    def county_meaning(value: str) -> str:
        code = value.strip().removesuffix(".0").zfill(5)
        if code in CT_LEGACY:
            return "Connecticut legacy county"
        if code in county_geoids:
            return "valid county"
        if code[3:] + code[:3] in county_geoids:
            return "county and state reversed"
        return "not a county"

    _rows = []
    for _r in raw_values:
        if "error" in _r:
            continue
        _family = FIELDS[_r["column"].upper()]
        _vals = [
            (v, n) for v, n in _r["values"] if v is not None and v.strip().upper() not in BLANK
        ]
        _total = sum(n for _, n in _r["values"])
        _filled = sum(n for _, n in _vals)
        _row = {
            "layer": short_name(_r["layer"]),
            "field": _r["column"].upper(),
            "column": _r["column"],
            "family": _family,
            "catalog_type": _r["type"],
            "rows_read": _total,
            "filled": _filled,
            "examples": ", ".join(v.strip() for v, _ in _vals[:3]),
            "format": "all blank",
            "format_share": None,
            "meaning": None,
        }
        if _family in ("status", "type"):
            _row["format"] = "vocabulary"
            _row["examples"] = "; ".join(v.strip() for v, _ in _vals[:6])
        elif _filled:
            _counts: dict[str, int] = {}
            for _v, _n in _vals:
                _label = classify(_family, _v)
                _counts[_label] = _counts.get(_label, 0) + _n
            _top = sorted(_counts.items(), key=lambda kv: -kv[1])
            _row["format_share"] = _top[0][1] / _filled
            _row["format"] = (
                _top[0][0]
                if _row["format_share"] >= 0.9
                else "mixed: " + ", ".join(f"{k} {n / _filled:.0%}" for k, n in _top[:3])
            )
            if _family == "county code":
                _meanings: dict[str, int] = {}
                for _v, _n in _vals:
                    _m = county_meaning(_v)
                    _meanings[_m] = _meanings.get(_m, 0) + _n
                _row["meaning"] = ", ".join(
                    f"{k} {n / _filled:.1%}"
                    for k, n in sorted(_meanings.items(), key=lambda kv: -kv[1])
                )
        _rows.append(_row)
    inventory = pl.DataFrame(_rows)
    return (inventory,)


@app.cell
def _(mo):
    mo.md(r"""
    **Status codes.** `STATUS` is free vocabulary in each layer, so a format class says little.
    What matters for a join is meaning. We sort each layer's `STATUS` vocabulary with keyword
    rules into: operating status in words (`OPEN`, `Operating`), operating status as codes
    (`OP`, `A`, `1`), or something else entirely (ownership, volcano dating evidence, a
    regulatory stage).
    """)
    return


@app.cell
def _(inventory, pl):
    _WORDS = {
        "OPEN",
        "CLOSED",
        "ACTIVE",
        "INACTIVE",
        "OPERATING",
        "IN SERVICE",
        "REMOVED",
        "DISMANTLED",
        "NOT IN USE",
        "UNDER CONSTRUCTION",
        "PRODUCING WELL",
        "NON-ACTIVE WELL",
    }
    _CODES = {"OP", "SB", "OS", "OA", "RE", "A", "N", "G", "M", "D", "R", "C", "1", "2", "3"}
    _OTHER = {
        "PRIVATE": "ownership (Public/Private)",
        "PUBLIC": "ownership (Public/Private)",
        "HOLOCENE": "dating evidence (Holocene...)",
        "HISTORICAL": "dating evidence (Holocene...)",
        "FINAL": "regulatory stage (Final, Effective)",
        "EFFECTIVE": "regulatory stage (Final, Effective)",
        "PROPOSED": "regulatory stage (Final, Effective)",
        "COMPLETED": "regulatory stage (Final, Effective)",
        "EXISTENCE DOUBTFUL": "chart reliability",
    }

    def status_meaning(examples: str) -> str:
        vocab = {v.strip().upper() for v in examples.split(";") if v.strip()}
        if not vocab:
            return "all blank"
        for word, label in _OTHER.items():
            if word in vocab:
                return label
        if vocab & _WORDS:
            return "operating status, words"
        if vocab <= _CODES or vocab & {"OP", "A"}:
            return "operating status, codes"
        return "other"

    status = (
        inventory.filter(pl.col("field") == "STATUS")
        .with_columns(
            meaning=pl.col("examples").map_elements(status_meaning, return_dtype=pl.String)
        )
        .select("layer", "meaning", "examples", "filled")
        .sort("meaning", "layer")
    )
    status.group_by("meaning").agg(layers=pl.len()).sort("layers", descending=True)
    return (status,)


@app.cell
def _(OUT, inventory, pl, status):
    inventory_out = (
        inventory.join(
            status.select("layer", pl.col("meaning").alias("status_meaning")),
            on="layer",
            how="left",
        )
        .with_columns(
            meaning=pl.when(pl.col("field") == "STATUS")
            .then(pl.col("status_meaning"))
            .otherwise(pl.col("meaning"))
        )
        .drop("status_meaning")
    )
    inventory_out.write_csv(OUT / "inventory.csv")

    def county_code_meaning(meaning: str) -> str:
        # "valid county 96.8%, not a county 2.8%, ..." -> the main way the codes go wrong,
        # or "current county codes" when at least 99% are current Census counties.
        shares = dict(part.rsplit(" ", 1) for part in meaning.split(", "))
        if float(shares.get("valid county", "0%").rstrip("%")) >= 99:
            return "current county codes"
        return next(kind for kind in shares if kind != "valid county")

    def field_summary(frame: pl.DataFrame) -> pl.DataFrame:
        checked = frame.filter(pl.col("format") != "all blank")
        meaning_key = (
            pl.when(pl.col("family") == "county code")
            .then(pl.col("meaning").map_elements(county_code_meaning, return_dtype=pl.String))
            .when(pl.col("field") == "STATUS")
            .then(pl.col("meaning"))
        )
        return (
            checked.with_columns(
                fmt=pl.when(pl.col("format").str.starts_with("mixed"))
                .then(pl.lit("mixed"))
                .otherwise(pl.col("format")),
                mean=meaning_key,
            )
            .group_by("field")
            .agg(
                layers=pl.len(),
                formats=pl.col("fmt").n_unique(),
                meanings=pl.col("mean").drop_nulls().n_unique(),
                format_list=pl.col("fmt")
                .value_counts(sort=True)
                .map_elements(lambda s: f"{s['fmt']} ({s['count']})", return_dtype=pl.String)
                .str.join("; "),
            )
            .with_columns(differs=(pl.col("formats") > 1) | (pl.col("meanings") > 1))
            .sort("layers", descending=True)
        )

    summary_by_field = field_summary(inventory_out.filter(pl.col("family") != "type"))
    summary_by_field.write_csv(OUT / "field_summary.csv")
    summary_by_field
    return inventory_out, summary_by_field


@app.cell
def _(inventory_out, pl, summary_by_field):
    _checked = inventory_out.filter(pl.col("format") != "all blank")
    inventory_numbers = {
        "fields_checked": summary_by_field.height + 1,  # + TYPE, reported separately below
        "layer_field_pairs": _checked.height,
        "layers_checked": _checked["layer"].n_unique(),
        "fields_that_differ": int(summary_by_field["differs"].sum()) + 1,  # TYPE always differs
        "type_vocabularies": inventory_out.filter(pl.col("field") == "TYPE")["examples"].n_unique(),
    }
    print(inventory_numbers)
    return (inventory_numbers,)


@app.cell
def _(mo):
    mo.md(r"""
    `TYPE` is left out of the table above: every one of its layers uses its own vocabulary
    (power plant fuel, hospital kind, school level), so it differs by construction.

    **The county codes up close.** These are the layers whose county-code field is not a plain
    5-digit Census county code for nearly all rows:
    """)
    return


@app.cell
def _(inventory_out, pl):
    _typical = {
        "county code": "5-digit county FIPS (48029)",
        "county": "county name (Bexar)",
        "state": "postal code (TX)",
        "zip": "5-digit ZIP",
    }
    _valid = pl.col("meaning").str.extract(r"valid county ([\d.]+)%").cast(pl.Float64)
    county_problems = (
        inventory_out.filter(
            pl.col("family").is_in(list(_typical)) & (pl.col("format") != "all blank")
        )
        .with_columns(typical=pl.col("family").replace_strict(_typical))
        .filter(
            (pl.col("format") != pl.col("typical"))
            | (pl.col("format_share") < 0.99)
            | (pl.col("catalog_type").is_in(["integer", "float"]) & (pl.col("family") != "county"))
            | ((pl.col("family") == "county code") & (_valid.fill_null(0) < 99))
        )
        .select("layer", "column", "catalog_type", "format", "meaning", "examples")
        .sort("layer")
    )
    county_problems
    return (county_problems,)


@app.cell
def _(db, inventory_out, layers, pl):
    # Connecticut: which county geography does each layer's county code use?
    _rows = []
    for _r in inventory_out.filter(pl.col("family") == "county code").iter_rows(named=True):
        _href = layers.filter(pl.col("slug") == _r["layer"])["parquet"][0]
        _code = f"""lpad(regexp_replace(CAST("{_r["column"]}" AS VARCHAR), '\\.0$', ''), 5, '0')"""
        _codes = db.execute(
            f"SELECT DISTINCT {_code} FROM read_parquet('{_href}') WHERE starts_with({_code}, '09')"
        ).fetchall()
        _codes = {c[0] for c in _codes if c[0] and c[0][2:].isdigit()}
        if _codes:
            _legacy = sum(1 for c in _codes if int(c[2:]) < 100)
            _rows.append(
                {
                    "layer": _r["layer"],
                    "column": _r["column"],
                    "legacy_counties": _legacy,
                    "planning_regions": len(_codes) - _legacy,
                }
            )
    connecticut = (
        pl.DataFrame(_rows)
        .with_columns(
            uses=pl.when(pl.col("planning_regions") == 0)
            .then(pl.lit("legacy counties only"))
            .when(pl.col("legacy_counties") == 0)
            .then(pl.lit("planning regions only"))
            .otherwise(pl.lit("both"))
        )
        .sort("uses", "layer")
    )
    connecticut
    return (connecticut,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. The National Risk Index

    The usual join from an infrastructure layer to the NRI is the 5-character county code
    `STCOFIPS`. We fetch the county table from FEMA's public ArcGIS service (the bulk download
    on fema.gov returned *Access Denied* when we built this). NRI already uses Connecticut's
    planning regions.
    """)
    return


@app.cell
def _(NRI_URL, httpx, pl):
    _fields = (
        "STATE,STATEABBRV,STATEFIPS,COUNTY,COUNTYTYPE,COUNTYFIPS,STCOFIPS,RISK_SCORE,RISK_RATNG"
    )
    _rows = []
    for _page in range(10):  # 3,232 counties at up to 2,000 per page
        _resp = httpx.get(
            NRI_URL,
            params={
                "where": "1=1",
                "outFields": _fields,
                "returnGeometry": "false",
                "f": "json",
                "resultOffset": _page * 2000,
                "resultRecordCount": 2000,
                "orderByFields": "OBJECTID",
            },
            timeout=120,
        )
        _resp.raise_for_status()
        _feats = _resp.json()["features"]
        _rows += [f["attributes"] for f in _feats]
        if len(_feats) < 2000:
            break
    nri = pl.DataFrame(_rows)
    assert nri["STCOFIPS"].n_unique() == nri.height > 3000, "NRI county table looks incomplete"
    print(f"NRI: {nri.height} counties")
    return (nri,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Questions and the answer key

    [`questions.csv`](questions.csv) holds 24 questions in three families, written so each needs
    a join. We picked the facilities on purpose, to land on the problems the inventory found,
    plus three controls whose codes are clean (n09-n11):

    - **nri** (12): which NRI risk rating applies to the county a facility is in. Needs the
      facility's county, then an NRI row.
    - **count** (8): how many facilities of layer B are in the same county as facility A.
    - **status** (4): the same, counting only open or operating facilities, where "open" is
      spelled `OPEN`, `OP`, `A` or a number depending on the layer.

    The key: each facility's point is placed in a county polygon with a spatial join (each
    layer's own CRS transformed to the county layer's NAD83). For counts we count layer B's
    points inside that polygon. An answer within max(1, 5%) of that count is correct, which
    absorbs a few facilities geocoded across a county line. For comparison the key also shows
    what a plain code join gets (layer B's county code, padded to 5 digits, equal to the key
    county): where the codes are sound the two agree, and where they aren't, they don't.
    """)
    return


@app.cell
def _(HERE, db, layers, pl):
    import json as _json

    questions = pl.read_csv(HERE / "questions.csv")

    def point_sql(slug: str) -> tuple[str, str]:
        href = layers.filter(pl.col("slug") == slug)["parquet"][0]
        geo = db.execute(
            f"SELECT value FROM parquet_kv_metadata('{href}') WHERE key = 'geo'"
        ).fetchall()
        assert geo, f"{slug} has no GeoParquet metadata"
        geo = geo[0]
        meta = _json.loads(geo[0])
        crs = meta["columns"][meta["primary_column"]].get("crs") or {}
        code = crs.get("id", {}).get("code") if isinstance(crs, dict) else None
        geom = meta["primary_column"]
        if code in (4269, 4326):  # NAD83 and WGS84 differ by about a metre; treat as the same
            expr = f"ST_SetCRS(ST_Centroid({geom}), 'EPSG:4269')"
        else:
            expr = f"ST_Transform(ST_Centroid({geom}), 'EPSG:4269', always_xy := true)"
        return f"read_parquet('{href}')", expr

    def county_of(slug: str, where: str) -> tuple[str, int]:
        src, expr = point_sql(slug)
        hits = db.execute(
            f"SELECT c.GEOID FROM (SELECT {expr} AS pt FROM {src} WHERE {where}) f "
            f"JOIN counties c ON ST_Intersects(c.geometry, f.pt)"
        ).fetchall()
        geoids = {h[0] for h in hits}
        assert len(geoids) == 1, f"{slug} / {where}: expected one county, got {geoids}"
        return geoids.pop(), len(hits)

    def count_in_county(slug: str, geoid: str, where: str | None) -> int:
        src, expr = point_sql(slug)
        cond = f"WHERE {where}" if where else ""
        return db.execute(
            f"SELECT count(*) FROM (SELECT {expr} AS pt FROM {src} {cond}) f "
            f"JOIN counties c ON c.GEOID = '{geoid}' AND ST_Intersects(c.geometry, f.pt)"
        ).fetchall()[0][0]

    COUNTY_CODE_COLUMN = {
        "ncua-insured-credit-unions": "COUNTYFIPS",
        "hospitals-3": "COUNTYFIPS",
        "nursing-homes": "COUNTYFIPS",
        "mobile-home-parks": "COUNTYFIPS",
        "private-schools": "COUNTYFIPS",
        "public-schools": "COUNTYFIPS",
        "power-plants-1": "COUNTYFIPS",
        "colleges-and-universities": "COUNTYFIPS",
    }

    def count_by_code(slug: str, geoid: str, where: str | None) -> int | None:
        column = COUNTY_CODE_COLUMN.get(slug)
        if column is None:
            return None
        href = layers.filter(pl.col("slug") == slug)["parquet"][0]
        cond = f"AND {where}" if where else ""
        return db.execute(
            f"""SELECT count(*) FROM read_parquet('{href}') WHERE lpad(regexp_replace(
            CAST("{column}" AS VARCHAR), '\\.0$', ''), 5, '0') = '{geoid}' {cond}"""
        ).fetchall()[0][0]

    _rows = []
    for _q in questions.iter_rows(named=True):
        _geoid, _matched = county_of(_q["layer_a"], _q["where_a"])
        _row = {"qid": _q["qid"], "key_geoid": _geoid, "records_matched": _matched}
        if _q["layer_b"]:
            _row["key_count"] = count_in_county(_q["layer_b"], _geoid, _q["where_b"])
            _row["key_count_by_code"] = count_by_code(_q["layer_b"], _geoid, _q["where_b"])
        _rows.append(_row)
    key = (
        questions.join(pl.DataFrame(_rows), on="qid")
        .join(
            db.sql("SELECT GEOID, NAMELSAD FROM counties").pl(),
            left_on="key_geoid",
            right_on="GEOID",
            how="left",
        )
        .rename({"NAMELSAD": "key_county"})
    )
    return (key,)


@app.cell
def _(OUT, key, nri, pl):
    key_out = key.join(
        nri.select(pl.col("STCOFIPS").alias("key_geoid"), pl.col("RISK_RATNG").alias("key_rating")),
        on="key_geoid",
        how="left",
    )
    assert key_out.filter(pl.col("family") == "nri")["key_rating"].null_count() == 0
    key_out.write_csv(OUT / "answer_key.csv")
    key_out.select(
        "qid",
        "layer_a",
        "key_county",
        "key_geoid",
        "key_rating",
        "layer_b",
        "key_count",
        "key_count_by_code",
    )
    return (key_out,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Code descriptions for the tool metadata

    The fix the argument proposes is cheap: say what each code means where the agent reads it.
    We generate a short note from the inventory above, listing for each shared identifier field
    the layers whose format or meaning departs from the common one, and add it to the
    description of the MCP tool the agent uses to run SQL. The notes are
    written from the inventory, not from the questions; they cover every layer the inventory
    flagged. The full text is saved to `outputs/code_notes.md`.
    """)
    return


@app.cell
def _(OUT, connecticut, county_problems, pl, status):
    _lines = [
        "CODE NOTES for HIFLD Next identifier fields (generated from a scan of every layer).",
        "Most layers store: STATE as a 2-letter postal code; COUNTYFIPS/FIPS/FIPS_CODE as the "
        "5-character Census county code with leading zeros (FEMA NRI calls it STCOFIPS); "
        "COUNTY as a county name, which repeats across states and, in Virginia, Maryland, "
        "Missouri and Nevada, inside one state (Richmond city vs Richmond County); ZIP as a "
        "5-digit string. Exceptions by layer:",
    ]
    for _r in county_problems.iter_rows(named=True):
        _meaning = f"; meaning: {_r['meaning']}" if _r["meaning"] else ""
        _lines.append(
            f"- {_r['layer']}.{_r['column']} ({_r['catalog_type']}): {_r['format']}{_meaning}; "
            f"e.g. {_r['examples']}"
        )
    _both = connecticut.filter(pl.col("uses") != "planning regions only")["layer"].to_list()
    _lines.append(
        "- Connecticut: since 2022 Census and NRI use 9 planning regions (09110-09190). These "
        f"layers still carry the 8 old counties (09001-09015) for some or all CT rows: "
        f"{', '.join(_both)}. Old and new codes never match each other."
    )
    _codes = status.filter(pl.col("meaning") == "operating status, codes")
    _lines.append(
        "- STATUS meaning differs by layer. Operating status as codes in: "
        + "; ".join(f"{r['layer']} ({r['examples']})" for r in _codes.iter_rows(named=True))
        + ". public-schools STATUS is the NCES code: 1 open, 2 closed, 3 new, 4 added, "
        "5 changed agency, 6 inactive, 7 future, 8 reopened. colleges STATUS A = active. "
        "power plants STATUS OP = operating. Some layers' STATUS is not operating status at all: "
        + "; ".join(
            f"{r['layer']} ({r['meaning']})"
            for r in status.filter(~pl.col("meaning").str.starts_with("operating")).iter_rows(
                named=True
            )
            if r["meaning"] != "all blank"
        )
        + ".",
    )
    code_notes = "\n".join(_lines)
    (OUT / "code_notes.md").write_text(code_notes + "\n")
    print(f"{len(code_notes):,} characters, {len(_lines)} lines")
    return (code_notes,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. The agent

    A [Pydantic AI](https://ai.pydantic.dev) agent gets the HIFLD Next MCP server's catalog and
    query tools (the map-widget tools are dropped), plus one tool of ours, `query_nri`, which
    runs a read-only SQL query on the NRI county table. Its description lists the NRI columns
    with FEMA's own labels and is the same in both conditions. The answer is typed: the county
    the agent settled on, the NRI rating or the count, and how it joined (a code, a name, or a
    spatial query).

    - **baseline**: the server's tool descriptions as published.
    - **code notes**: the same, with the note from section 5 appended to the description of
      `query_parquet`, the tool that runs joins. (The model sees every tool description on every
      request, so one copy is enough.)
    """)
    return


@app.cell
def _(Agent, BaseModel, Field, MCPToolset, MCP_URL, db, nri, replace):
    from typing import Literal

    db.register("nri_frame", nri.to_arrow())
    db.execute("CREATE OR REPLACE TABLE nri AS SELECT * FROM nri_frame")

    class Answer(BaseModel):
        found: bool = Field(description="False if you could not complete the join.")
        county_fips: str | None = Field(
            description="5-character state+county FIPS code of the county you settled on."
        )
        county_name: str | None = Field(description="That county's name and state.")
        risk_rating: str | None = Field(description="NRI RISK_RATNG, for risk questions.")
        count: int | None = Field(description="The number asked for, for 'how many' questions.")
        join_method: Literal["county code", "county name", "spatial", "other"] = Field(
            description="How you linked the two datasets: by a county code, by county "
            "name, by a spatial query on geometry, or another way."
        )
        codes_used: str = Field(description="The fields and values you joined on.")
        answer: str = Field(description="One or two sentences answering the question.")

    QUERY_TOOLS = {
        "list_collections",
        "get_collection",
        "search_datasets",
        "get_dataset",
        "get_dataset_file",
        "get_dataset_file_schema",
        "read_geoparquet_rows",
        "query_parquet",
        "inspect_query_source",
        "get_query_page",
    }
    NOTE_TOOLS = {"query_parquet"}  # every tool description is sent on every request anyway
    INSTRUCTIONS = (
        "You answer questions that join HIFLD Next infrastructure layers with each other or "
        "with FEMA's National Risk Index. Use the HIFLD Next MCP tools to find records and "
        "query_nri for the risk index. Base every answer on tool results."
    )

    def query_nri(sql: str) -> list[dict] | str:
        """Run one read-only DuckDB SELECT on table `nri`: FEMA National Risk Index, one row
        per US county or county equivalent. Columns: STATE (State Name), STATEABBRV (State
        Name Abbreviation), STATEFIPS (State FIPS Code), COUNTY (County Name), COUNTYTYPE
        (County Type), COUNTYFIPS (County FIPS Code), STCOFIPS (State-County FIPS Code),
        RISK_SCORE (National Risk Index - Score - Composite), RISK_RATNG (National Risk Index
        - Rating - Composite). Returns at most 50 rows."""
        if not sql.lstrip().upper().startswith(("SELECT", "WITH")):
            return "Only SELECT queries are allowed."
        cursor = db.cursor()
        try:
            rows = cursor.execute(sql).fetchmany(50)
        except Exception as exc:  # the model sees SQL errors and can fix its query
            return f"Query failed: {exc}"[:500]
        names = [d[0] for d in cursor.description]
        return [dict(zip(names, r, strict=True)) for r in rows]

    def make_agent(model: str, notes: str | None) -> Agent[None, Answer]:
        def add_notes(_ctx: object, tools: list) -> list:
            return [
                replace(t, description=f"{t.description}\n\n{notes}") if t.name in NOTE_TOOLS else t
                for t in tools
            ]

        toolset = MCPToolset(MCP_URL, max_retries=3).filtered(
            lambda _ctx, tool: tool.name in QUERY_TOOLS
        )
        if notes:
            toolset = toolset.prepared(add_notes)
        return Agent(
            f"openrouter:{model}",
            toolsets=[toolset],
            tools=[query_nri],
            output_type=Answer,
            instructions=INSTRUCTIONS,
            model_settings={"openrouter_usage": {"include": True}},
        )

    return (make_agent,)


@app.cell
async def _(
    BUDGET_USD,
    MODEL,
    ModelMessagesTypeAdapter,
    ModelResponse,
    OUT,
    REPEATS,
    RUN_AGENT,
    UsageLimits,
    asyncio,
    capture_run_messages,
    code_notes,
    json,
    key_out,
    make_agent,
    pl,
    time,
):
    ANSWERS = OUT / "answers.jsonl"
    TRANSCRIPTS = OUT / "transcripts"

    async def ask(agent, condition: str, repeat: int, q: dict, gate, spend: dict) -> dict:
        row = {
            "condition": condition,
            "repeat": repeat,
            "qid": q["qid"],
            "model": MODEL,
            "run_date": time.strftime("%Y-%m-%d"),
            "error": None,
        }
        async with gate:
            if spend["usd"] >= BUDGET_USD:
                return row | {"error": "skipped: budget reached"}
            start = time.monotonic()
            with capture_run_messages() as messages:
                try:
                    result = await asyncio.wait_for(
                        agent.run(q["question"], usage_limits=UsageLimits(request_limit=30)),
                        timeout=420,
                    )
                except Exception as exc:  # a failed run is a measured outcome
                    cost = sum(
                        (m.provider_details or {}).get("cost", 0)
                        for m in messages
                        if isinstance(m, ModelResponse)
                    )
                    spend["usd"] += cost
                    (TRANSCRIPTS / f"{condition}-{repeat}-{q['qid']}.json").write_bytes(
                        ModelMessagesTypeAdapter.dump_json(messages, indent=1)
                    )
                    return row | {
                        "error": f"{type(exc).__name__}: {exc}"[:300],
                        "seconds": time.monotonic() - start,
                        "cost_usd": cost,
                    }
        usage = result.usage
        spend["usd"] += float(usage.cost or 0)
        (TRANSCRIPTS / f"{condition}-{repeat}-{q['qid']}.json").write_bytes(
            ModelMessagesTypeAdapter.dump_json(result.all_messages(), indent=1)
        )
        return (
            row
            | result.output.model_dump()
            | {
                "seconds": time.monotonic() - start,
                "cost_usd": float(usage.cost or 0),
                "input_tokens": usage.input_tokens,
                "output_tokens": usage.output_tokens,
                "tool_calls": usage.tool_calls,
            }
        )

    if RUN_AGENT:
        TRANSCRIPTS.mkdir(exist_ok=True)
        _spend = {"usd": 0.0}
        _runs = []
        for _condition, _notes in (("baseline", None), ("code notes", code_notes)):
            _agent = make_agent(MODEL, _notes)
            async with _agent:
                for _repeat in range(1, REPEATS + 1):
                    _gate = asyncio.Semaphore(6)
                    _runs += await asyncio.gather(
                        *(
                            ask(_agent, _condition, _repeat, _q, _gate, _spend)
                            for _q in key_out.iter_rows(named=True)
                        )
                    )
        ANSWERS.write_text("".join(json.dumps(r) + "\n" for r in _runs))
        print(f"ran {len(_runs)} agent queries, ${_spend['usd']:.2f}")
    assert ANSWERS.exists(), "no saved answers: run with RUN_AGENT=1 and OPENROUTER_API_KEY set"
    answers = pl.read_ndjson(ANSWERS, infer_schema_length=None)
    print(f"{answers.height} answers from {answers['run_date'].unique().to_list()}")
    return (answers,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. Scoring

    - **nri**: correct if the county code the agent reports (zero-padded) is the key county
      and its rating is that county's NRI rating; **no match** if it found nothing or reported
      no county; **wrong match** if it settled on another county, or the right county with a
      rating from another row.
    - **count / status**: correct if the count is within max(1, 5%) of the spatial count;
      **no match** if it found nothing or reported 0 where the key
      is above 0; **wrong match** for any other number.

    A run that errored or hit the request limit is scored as no match and counted separately.
    """)
    return


@app.cell
def _(OUT, answers, key_out, pl):
    def outcome(r: dict) -> str:
        if r["error"] or not r["found"]:
            return "no match"
        if r["family"] == "nri":
            fips = (r["county_fips"] or "").strip().removesuffix(".0").zfill(5)
            if not r["county_fips"]:
                return "no match"
            rating_ok = (r["risk_rating"] or "").strip().lower() == r["key_rating"].lower()
            return "correct" if fips == r["key_geoid"] and rating_ok else "wrong match"
        if r["count"] is None or (r["count"] == 0 and r["key_count"] > 0):
            return "no match"
        ok = abs(r["count"] - r["key_count"]) <= max(1, 0.05 * r["key_count"])
        return "correct" if ok else "wrong match"

    _cols = [
        c
        for c in [
            "found",
            "county_fips",
            "county_name",
            "risk_rating",
            "count",
            "join_method",
            "codes_used",
            "answer",
            "error",
        ]
        if c in answers.columns
    ]
    scored = answers.join(key_out, on="qid").with_columns(
        outcome=pl.struct(pl.all()).map_elements(outcome, return_dtype=pl.String)
    )
    scored.select(
        "condition",
        "repeat",
        "qid",
        "family",
        "outcome",
        "key_geoid",
        "key_rating",
        "key_count",
        "key_count_by_code",
        *_cols,
        "seconds",
        "cost_usd",
    ).write_csv(OUT / "scored.csv")
    return (scored,)


@app.cell
def _(OUT, pl, re, scored):
    # The agent's own join_method label is a claim. The transcript says what it ran: a spatial
    # join needs a spatial predicate in a query_parquet SQL string.
    def ran_spatial_sql(r: dict) -> bool:
        path = OUT / "transcripts" / f"{r['condition']}-{r['repeat']}-{r['qid']}.json"
        text = path.read_text() if path.exists() else ""
        return bool(re.search(r"ST_(Intersects|Contains|Within|DWithin)", text))

    scored_spatial = scored.with_columns(
        spatial_sql=pl.struct("condition", "repeat", "qid").map_elements(
            ran_spatial_sql, return_dtype=pl.Boolean
        )
    )
    return (scored_spatial,)


@app.cell
def _(pl, scored_spatial):
    def shares(frame: pl.DataFrame, by: list[str]) -> pl.DataFrame:
        return (
            frame.group_by(by)
            .agg(
                answers=pl.len(),
                correct=(pl.col("outcome") == "correct").mean(),
                no_match=(pl.col("outcome") == "no match").mean(),
                wrong_match=(pl.col("outcome") == "wrong match").mean(),
                said_spatial=(pl.col("join_method") == "spatial").sum(),
                ran_spatial_sql=pl.col("spatial_sql").sum(),
                errors=pl.col("error").is_not_null().sum(),
            )
            .sort(by)
        )

    by_condition = shares(scored_spatial, ["condition"])
    by_family = shares(scored_spatial, ["condition", "family"])
    by_condition
    return by_condition, by_family


@app.cell
def _(by_family):
    by_family
    return


@app.cell
def _(mo):
    mo.md(r"""
    **Every question, both conditions.** One letter per run: C correct, N no match, W wrong
    match.
    """)
    return


@app.cell
def _(pl, scored):
    per_question = (
        scored.sort("repeat")
        .with_columns(
            letter=pl.col("outcome").replace_strict(
                {"correct": "C", "no match": "N", "wrong match": "W"}
            )
        )
        .group_by("qid", "condition")
        .agg(pl.col("letter").str.join(""), pl.col("join_method").unique().sort().str.join("/"))
        .pivot(on="condition", index="qid", values=["letter", "join_method"])
        .sort("qid")
    )
    per_question
    return


@app.cell
def _(mo):
    mo.md(r"""
    **The wrong matches**, with what the agent said it joined on:
    """)
    return


@app.cell
def _(pl, scored):
    scored.filter(pl.col("outcome") == "wrong match").select(
        "condition",
        "repeat",
        "qid",
        "key_geoid",
        "key_rating",
        "key_count",
        "county_fips",
        "risk_rating",
        "count",
        "join_method",
        "codes_used",
    ).sort("qid", "condition")
    return


@app.cell
def _(MODEL, OUT, by_condition, inventory_numbers, json, pl, scored):
    _cost = (
        scored.group_by("condition")
        .agg(
            usd=pl.col("cost_usd").sum(),
            usd_per_answer=pl.col("cost_usd").mean(),
            median_s=pl.col("seconds").median(),
            tool_calls=pl.col("tool_calls").mean(),
        )
        .sort("condition")
    )
    summary = {
        "inventory": inventory_numbers,
        "model": MODEL,
        "run_dates": scored["run_date"].unique().sort().to_list(),
        "questions": scored["qid"].n_unique(),
        "by_condition": by_condition.to_dicts(),
        "cost": _cost.to_dicts(),
        "total_usd": float(scored["cost_usd"].sum()),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    _cost
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What this doesn't show

    - **The questions are aimed at the problems.** We picked facilities where the inventory
      found a trap, plus three controls. The wrong-match rate is the rate on these questions,
      not on questions people ask at random.
    - **One cheap model**, two runs per question per condition. A stronger model may notice
      more traps by itself.
    - **The NRI tool is ours.** HIFLD Next doesn't serve NRI; we gave the agent a SQL tool over
      FEMA's county table, with FEMA's column labels.
    - **The code notes go into tool descriptions on our side.** On the server they would belong
      in each column's schema entry, where an agent reads them only for the layer at hand.
    - **The inventory's classes are rules.** A format we didn't write a pattern for shows as
      `other`; the saved `outputs/inventory.csv` lists examples for every layer-field pair.
    """)
    return


if __name__ == "__main__":
    app.run()

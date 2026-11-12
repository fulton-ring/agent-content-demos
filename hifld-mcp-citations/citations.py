import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import asyncio
    import datetime as dt
    import gzip
    import json
    import math
    import os
    import re
    import time

    import duckdb
    import httpx
    import marimo as mo
    import polars as pl
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent
    from pydantic_ai.mcp import MCPToolset
    from pydantic_ai.messages import ModelResponse, ToolCallPart, ToolReturnPart
    from pydantic_ai.usage import UsageLimits

    return (
        Agent,
        BaseModel,
        Field,
        MCPToolset,
        ModelResponse,
        ToolCallPart,
        ToolReturnPart,
        UsageLimits,
        asyncio,
        dt,
        duckdb,
        gzip,
        httpx,
        json,
        math,
        mo,
        os,
        pl,
        re,
        time,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Can an answer an AI agent gets from HIFLD Next be cited and checked a year later?

    An agent connected to [HIFLD Next](https://hifld.publicenvirodata.org)'s MCP server can
    answer "how many hospitals are in Vermont?" in a few seconds. A researcher or a reporter
    who quotes that answer needs more than the number: which layer, which version of it, when
    it was read, who produced the data, under what terms, and a query that gives the same
    number again. HIFLD Next keeps every version of every layer, so the data to check against
    exists. The question is whether the answer carries enough to find it.

    We ask an agent 20 questions with known answers, record which of six citation fields show
    up in the raw tool responses and in the agent's final answer, then try to reproduce each
    answer from the final answer alone. We do it three ways: the server as shipped, the same
    server with a one-line instruction to cite, and a thin proxy that adds a citation block to
    every data tool response, plus the same line.
    """)
    return


@app.cell
def _(mo, os):
    BASE_URL = os.environ.get("HIFLD_BASE_URL", "https://hifld.publicenvirodata.org")
    MCP_URL = f"{BASE_URL}/mcp"
    FEATURES = f"{BASE_URL}/features/collections"
    MODEL = os.environ.get("AGENT_MODEL", "anthropic/claude-haiku-5.5")
    REPEATS = int(os.environ.get("AGENT_REPEATS", "2"))
    BUDGET_USD = float(os.environ.get("AGENT_BUDGET_USD", "4.0"))
    # Rerun the agent only when a key is set and AGENT_RUN isn't 0; otherwise rescore the
    # committed answers and tool responses.
    RUN_AGENT = bool(os.environ.get("OPENROUTER_API_KEY")) and os.environ.get("AGENT_RUN") != "0"
    OUT = mo.notebook_dir() / "outputs"
    CACHE = OUT / "cache"  # downloaded GeoParquet files for reproduction; not committed
    CACHE.mkdir(parents=True, exist_ok=True)
    RUNS_FILE = OUT / "runs.jsonl.gz"
    return (
        BASE_URL,
        BUDGET_USD,
        CACHE,
        FEATURES,
        MCP_URL,
        MODEL,
        OUT,
        REPEATS,
        RUNS_FILE,
        RUN_AGENT,
    )


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. Twenty questions with known answers

    Counts, attribute lookups, one sum and one nearest-facility question, across seven
    layers. Ten are about hospitals, because `hospitals-3` is the only layer in HIFLD Next
    with two versions today: v1.0.0, the archived HIFLD Open snapshot, and v1.1.0 (issued
    2026-04-06), which updated bed counts. The bed-count questions are the ones where an
    answer without a version can't be checked: the right number depends on which version the
    agent read.

    Each question names the layer, the filters that define the answer and the field to read.
    The key comes from HIFLD Next's own OGC features API, which serves every version as its
    own collection (`hifld~hospitals-3~hospitals-3~v1.0.0`, `…~v1.1.0`), so we compute the
    answer on every version of each layer.
    """)
    return


@app.cell
def _():
    ALL = " (every record, whatever its status)?"
    # kind: count (numberMatched), lookup (one record's field), sum (of a field over matches),
    # nearest (NAME of the closest feature to lat/lon).
    # fmt: off
    QUESTIONS = [
        ("h01", "hospitals-3", "count", {"STATE": "VT"}, None,
         "How many hospitals are there in Vermont" + ALL),
        ("h02", "hospitals-3", "count", {"STATE": "TX", "TYPE": "CRITICAL ACCESS"}, None,
         "How many critical access hospitals are in Texas" + ALL),
        ("h03", "hospitals-3", "lookup", {"source_ID": "0014563110", "OBJECTID": "11722"}, "BEDS",
         "How many beds does Barnes Jewish Hospital in St. Louis have?"),
        ("h04", "hospitals-3", "lookup", {"source_ID": "0002289169", "OBJECTID": "12096"}, "BEDS",
         "How many beds does Sunrise Hospital and Medical Center in Las Vegas have?"),
        ("h05", "hospitals-3", "lookup", {"source_ID": "0005514607", "OBJECTID": "12375"}, "BEDS",
         "How many beds does Strong Memorial Hospital in Rochester, New York have?"),
        ("h06", "hospitals-3", "sum", {"STATE": "VT"}, "BEDS",
         "What is the total number of hospital beds in Vermont, across every record?"),
        ("h07", "hospitals-3", "count", {"STATE": "CO", "HELIPAD": "Y"}, None,
         "How many hospitals in Colorado have a helipad" + ALL),
        ("h08", "hospitals-3", "lookup", {"source_ID": "0000720001", "OBJECTID": "9467"}, "TRAUMA",
         "What trauma level is Howard University Hospital in Washington, DC?"),
        ("h09", "hospitals-3", "nearest", {"lat": 44.4719, "lon": -73.1533}, "NAME",
         "Which hospital is closest to Burlington International Airport in Vermont "
         "(44.4719 N, 73.1533 W)?"),
        ("h10", "hospitals-3", "lookup", {"source_ID": "0196785344", "OBJECTID": "16236"}, "OWNER",
         "What type of owner runs St. Peter's Hospital in Albany, New York?"),
        ("p01", "power-plants-1", "count", {"STATE": "IA", "PRIM_FUEL": "WND"}, None,
         "How many wind power plants are in Iowa" + ALL),
        ("p02", "power-plants-1", "lookup", {"PLANT_CODE": "6008"}, "SUMMER_CAP",
         "What is the summer capacity, in megawatts, of the Palo Verde power plant in Arizona?"),
        ("p03", "power-plants-1", "count", {"STATE": "VT", "STATUS": "OP"}, None,
         "How many operating power plants are in Vermont?"),
        ("d01", "national-inventory-of-dams-nid-1", "lookup", {"NIDID": "NV10122"}, "DAM_HEIGHT",
         "How tall, in feet, is Hoover Dam on the Colorado River in Nevada?"),
        ("d02", "national-inventory-of-dams-nid-1", "count", {"STATE": "Rhode Island"}, None,
         "How many dams are listed in Rhode Island" + ALL),
        ("n01", "nursing-homes", "count", {"STATE": "ME", "COUNTY": "AROOSTOOK"}, None,
         "How many nursing homes are in Aroostook County, Maine" + ALL),
        ("c01", "colleges-and-universities", "lookup", {"IPEDSID": "231174"}, "TOT_ENROLL",
         "What is the total enrollment of the University of Vermont?"),
        ("c02", "colleges-and-universities", "count", {"STATE": "WY"}, None,
         "How many colleges and universities are in Wyoming" + ALL),
        ("j01", "prison-boundaries-1", "count", {"STATE": "VT", "TYPE": "STATE"}, None,
         "How many state prisons are in Vermont" + ALL),
        ("f01", "fire-and-emergency-medical-service-ems-stations", "count",
         {"STATE": "VT", "CITY": "Burlington"}, None,
         "How many fire and EMS stations are in Burlington, Vermont" + ALL),
    ]
    # fmt: on
    # What a reader would call each layer, to tell whether an answer names it.
    LAYER_NAMES = {
        "hospitals-3": "hospitals",
        "power-plants-1": "power plants",
        "national-inventory-of-dams-nid-1": "national inventory of dams",
        "nursing-homes": "nursing homes",
        "colleges-and-universities": "colleges and universities",
        "prison-boundaries-1": "prison boundaries",
        "fire-and-emergency-medical-service-ems-stations": "fire and emergency medical service",
    }
    assert len(QUESTIONS) == 20
    return LAYER_NAMES, QUESTIONS


@app.cell
def _(BASE_URL, FEATURES, LAYER_NAMES, QUESTIONS, httpx, math, pl, re):
    http = httpx.Client(timeout=120)
    _resp = http.get(FEATURES, params={"f": "json"})
    _resp.raise_for_status()
    versions = {
        slug: sorted(
            m.group(1)
            for c in _resp.json()["collections"]
            if (m := re.fullmatch(rf"hifld~{slug}~{slug}~(v[\d.]+)", c["id"]))
        )
        for slug in LAYER_NAMES
    }
    assert all(versions.values()), versions

    # Each layer version's STAC metadata: title, license, producers, the GeoParquet file.
    layer_meta = {}
    for _slug, _vs in versions.items():
        for _v in _vs:
            _r = http.get(
                f"{BASE_URL}/api/collections/hifld/datasets/{_slug}/files/{_slug}",
                params={"version": _v},
            )
            _r.raise_for_status()
            layer_meta[(_slug, _v)] = _r.json()

    def ogc_items(slug: str, version: str, params: dict) -> dict:
        resp = http.get(
            f"{FEATURES}/hifld~{slug}~{slug}~{version}/items",
            params={"f": "json", "limit": 10000} | params,
        )
        resp.raise_for_status()
        return resp.json()

    _rows = []
    for _qid, _slug, _kind, _filters, _field, _question in QUESTIONS:
        for _v in versions[_slug]:
            if _kind == "count":
                _value = ogc_items(_slug, _v, _filters | {"limit": 1})["numberMatched"]
            elif _kind == "nearest":
                _lat, _lon = _filters["lat"], _filters["lon"]
                _box = f"{_lon - 0.5},{_lat - 0.5},{_lon + 0.5},{_lat + 0.5}"
                _feats = ogc_items(_slug, _v, {"bbox": _box})["features"]

                def _km(f: dict, lat: float = _lat, lon: float = _lon) -> float:
                    x, y = f["geometry"]["coordinates"][:2]
                    a = (
                        math.sin(math.radians(y - lat) / 2) ** 2
                        + math.cos(math.radians(lat))
                        * math.cos(math.radians(y))
                        * math.sin(math.radians(x - lon) / 2) ** 2
                    )
                    return 12742 * math.asin(math.sqrt(a))

                _value = min(_feats, key=_km)["properties"]["NAME"]
            else:
                # The same hospital needs a different filter on each version: v1.0.0 has an `ID`
                # column; v1.1.0 renamed it `source_ID`, which its OGC API won't filter on (and
                # its published schema still says `ID`, which returns a 500). OBJECTID, new in
                # v1.1.0, works there.
                _f = dict(_filters)
                if "source_ID" in _f:
                    _f = {"ID": _f["source_ID"]} if _v == "v1.0.0" else {"OBJECTID": _f["OBJECTID"]}
                _feats = ogc_items(_slug, _v, _f)["features"]
                _vals = [f["properties"][_field] for f in _feats]
                assert _vals, (_qid, _v)
                if _kind == "lookup":
                    assert len(_vals) == 1, (_qid, _v, len(_vals))
                    _value = _vals[0]
                else:  # sum, skipping the -999 "not available" sentinel
                    _value = sum(x for x in _vals if x is not None and x >= 0)
            _rows.append({"qid": _qid, "layer": _slug, "version": _v, "value": str(_value)})
    key = pl.DataFrame(_rows)
    current = key.group_by("qid").agg(pl.all().sort_by("version").last())
    changed = (
        key.group_by("qid")
        .agg(pl.col("value").n_unique().alias("n"), pl.col("version"), pl.col("value"))
        .filter(pl.col("n") > 1)
        .sort("qid")
    )
    changed
    return changed, current, http, key, layer_meta, versions


@app.cell
def _(changed, current, mo, versions):
    _multi = [s for s, v in versions.items() if len(v) > 1]
    mo.md(f"""
    Layers with more than one version: **{", ".join(_multi)}**. Of the 20 answers,
    **{changed.height}** differ between versions (the table above): the bed counts and the
    Vermont bed total. An answer of the form "Barnes Jewish Hospital has 1,737 beds" is right
    on one version and wrong on the other. The current answer for every question:
    """)
    current.sort("qid")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. The agent, three ways

    A [Pydantic AI](https://ai.pydantic.dev) agent connects to the public MCP server and
    keeps its catalog and query tools (the map-widget tools render UI and don't help answer).
    It returns a typed answer: the text it would give the person asking, and the bare value
    so we can score it. The instructions say nothing about which layer holds what.

    1. **As shipped**: the server's tools and responses, unchanged.
    2. **Instruction only**: the same, plus one line asking for a citation a reader could
       check a year from now. This separates what a prompt can do from what the server must.
    3. **Proxy + instruction**: the same line, plus a thin proxy between the agent and the
       server. After each data tool call (`get_dataset_file`, `read_geoparquet_rows`,
       `query_parquet`, `inspect_query_source`) it adds a `citation` block built from metadata
       the server already publishes: layer title and slug, version, retrieval date, producer
       agency, license, the version's GeoParquet URL and checksum, a pinned OGC features URL,
       and for SQL, the same query rewritten to read the pinned GeoParquet file in DuckDB.
       It is Pydantic AI's `process_tool_call` hook, about 40 lines in the next cell; the
       server is untouched.

    The license field needs a judgment: v1.0.0 layers say `"license": "other"`, and HIFLD
    Next's rights notice says the archived HIFLD Open snapshot is public domain (Public Domain
    Mark 1.0). The proxy reports that, with the notice's URL. v1.1.0 of hospitals carries
    `CC-PDM-1.0` itself.
    """)
    return


@app.cell
def _(Agent, BASE_URL, BaseModel, FEATURES, Field, MCPToolset, MCP_URL, dt, http, re):
    class Answer(BaseModel):
        answer: str = Field(description="Your full answer, as you would write it to the person.")
        value: str = Field(
            description="Just the answer: a number without units or commas, or a facility name."
        )

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
    BASE_INSTRUCTIONS = (
        "You answer questions about US infrastructure using only the HIFLD Next MCP tools. "
        "Find the right dataset, query it, and answer as you would for a researcher."
    )
    CITE_LINE = (
        " End your answer with a citation a reader could use to check it a year from now: "
        "layer, version, retrieval date, source agency, license, and a query URL or SQL that "
        "reproduces the answer."
    )
    PDM_NOTICE = f"{BASE_URL}/storage/hifld/LICENSE.md"
    _meta_cache: dict[tuple[str, str, str], dict] = {}

    def file_meta(dataset: str, file: str, version: str) -> dict:
        if (dataset, file, version) not in _meta_cache and len(_meta_cache) < 64:
            resp = http.get(
                f"{BASE_URL}/api/collections/hifld/datasets/{dataset}/files/{file}",
                params={"version": version},
            )
            resp.raise_for_status()
            _meta_cache[(dataset, file, version)] = resp.json()
        return _meta_cache[(dataset, file, version)]

    def citation(source: dict, sql: str | None, rows: list) -> dict:
        ds, file, version = source["dataset_slug"], source["file_slug"], source["version"]
        meta = file_meta(ds, file, version)
        asset = meta["assets"].get(source["asset_key"], {})
        license_ = meta.get("license")
        if license_ in (None, "other"):
            license_ = f"Public Domain Mark 1.0 (archived HIFLD Open snapshot; {PDM_NOTICE})"
        agencies = [p["name"] for p in meta.get("providers", []) if "producer" in p["roles"]]
        pinned = f"{FEATURES}/hifld~{ds}~{file}~{version}/items"
        cite = {
            "layer": f"{meta.get('title')} (hifld/{ds}/{file})",
            "version": version,
            "retrieved": dt.date.today().isoformat(),
            "source_agency": agencies + [meta["hifld:agency"]] * bool(meta.get("hifld:agency")),
            "license": license_,
            "data_url": asset.get("href"),
            "data_checksum": asset.get("file:checksum"),
            "query_url": pinned,
        }
        id_col = meta.get("hifld:feature_id_column")
        ids = [r[id_col] for r in rows if isinstance(r, dict) and id_col and id_col in r]
        if ids:
            cite["record_urls"] = [f"{pinned}?{id_col}={i}" for i in ids[:5]]
        if sql and asset.get("href"):
            cite["reproduce_sql"] = re.sub(
                rf"\b(FROM|JOIN)\s+{re.escape(source['alias'])}\b",
                rf"\1 read_parquet('{asset['href']}') AS {source['alias']}",
                sql,
                flags=re.IGNORECASE,
            )
        return cite

    async def add_citations(ctx: object, call_tool: object, name: str, args: dict) -> object:
        result = await call_tool(name, args)  # ty: ignore[call-non-callable]
        if not isinstance(result, dict):
            return result
        sources = args.get("sources") or ([args["source"]] if args.get("source") else [])
        if name == "get_dataset_file":
            sources = result.get("query_sources") or []
        if not sources:
            return result
        rows = result.get("rows") or []
        return result | {"citation": [citation(s, args.get("sql"), rows) for s in sources]}

    ARMS = ("as shipped", "instruction only", "proxy + instruction")

    def make_agent(model: str, arm: str) -> Agent[None, Answer]:
        toolset = MCPToolset(
            MCP_URL,
            max_retries=3,
            process_tool_call=add_citations if arm == "proxy + instruction" else None,
        ).filtered(lambda _ctx, tool: tool.name in QUERY_TOOLS)
        return Agent(
            f"openrouter:{model}",
            toolsets=[toolset],
            output_type=Answer,
            instructions=BASE_INSTRUCTIONS + ("" if arm == "as shipped" else CITE_LINE),
            model_settings={"openrouter_usage": {"include": True}},
        )

    return ARMS, make_agent


@app.cell
def _(mo):
    mo.md(r"""
    Each arm runs every question `AGENT_REPEATS` times (default 2). We save every final
    answer and every raw tool response to `outputs/runs.jsonl.gz`, so the scoring below
    reruns without an API key. A budget guard stops starting runs past `AGENT_BUDGET_USD`.
    """)
    return


@app.cell
async def _(
    ARMS,
    BUDGET_USD,
    MODEL,
    ModelResponse,
    QUESTIONS,
    REPEATS,
    RUNS_FILE,
    RUN_AGENT,
    ToolCallPart,
    ToolReturnPart,
    UsageLimits,
    asyncio,
    dt,
    gzip,
    json,
    make_agent,
    time,
):
    def tool_log(messages: list) -> list[dict]:
        calls = {}
        log = []
        for m in messages:
            for p in m.parts:
                if isinstance(p, ToolCallPart):
                    calls[p.tool_call_id] = p.args_as_dict()
                elif isinstance(p, ToolReturnPart):
                    log.append(
                        {
                            "tool": p.tool_name,
                            "args": calls.get(p.tool_call_id, {}),
                            "content": json.dumps(p.content, default=str),
                        }
                    )
        return log

    async def ask(agent: object, arm: str, repeat: int, q: tuple, spend: dict) -> dict:
        row = {"arm": arm, "repeat": repeat, "qid": q[0], "date": dt.date.today().isoformat()}
        if spend["usd"] >= BUDGET_USD:
            return row | {"error": "skipped: budget reached"}
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                agent.run(q[5], usage_limits=UsageLimits(request_limit=25)),  # ty: ignore
                timeout=300,
            )
        except Exception as exc:  # a failed run is a measured outcome, not a crash
            return row | {
                "error": f"{type(exc).__name__}: {exc}"[:300],
                "seconds": time.monotonic() - start,
            }
        messages = result.all_messages()
        cost = sum(
            float((m.provider_details or {}).get("cost", 0) or 0)
            for m in messages
            if isinstance(m, ModelResponse)
        )
        spend["usd"] += cost
        return (
            row
            | result.output.model_dump()
            | {
                "seconds": time.monotonic() - start,
                "cost_usd": cost,
                "input_tokens": result.usage.input_tokens,
                "output_tokens": result.usage.output_tokens,
                "tool_calls": result.usage.tool_calls,
                "tools": tool_log(messages),
                "error": None,
            }
        )

    if RUN_AGENT:
        _spend = {"usd": 0.0}
        _runs = []
        _gate = asyncio.Semaphore(6)

        async def _gated(agent: object, arm: str, repeat: int, q: tuple) -> dict:
            async with _gate:
                return await ask(agent, arm, repeat, q, _spend)

        for _arm in ARMS:
            _agent = make_agent(MODEL, _arm)
            async with _agent:
                for _rep in range(1, REPEATS + 1):
                    _runs += await asyncio.gather(
                        *(_gated(_agent, _arm, _rep, q) for q in QUESTIONS)
                    )
        with gzip.open(RUNS_FILE, "wt") as _fh:
            for _r in _runs:
                _fh.write(json.dumps(_r) + "\n")
    with gzip.open(RUNS_FILE, "rt") as _fh:
        runs = [json.loads(line) for line in _fh]
    print(f"{len(runs)} runs ({'fresh' if RUN_AGENT else 'loaded from ' + RUNS_FILE.name})")
    return (runs,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Which citation fields does each answer carry?

    For each run we look for the six fields twice: in everything the tools returned, and in
    the agent's final answer text. The rules are mechanical, so a second scorer gets the same
    table:

    - **layer**: the layer's slug, or its name (for example "power plants")
    - **version**: a version string such as `v1.1.0` or "version 1.1.0"
    - **retrieval date**: the run's date (`2026-11-12`, "November 12, 2026" or "Nov 12, 2026")
    - **query URL**: a URL that runs a query (`/features/…/items`, `/api/queries`), or a SQL
      `SELECT` statement. A link to a whole file doesn't count.
    - **source agency**: a producer or agency named in the layer's STAC metadata, for any
      of its versions (Oak Ridge National Laboratory, US Army Corps of Engineers…)
    - **license**: "public domain", "CC-PDM", "PDM" or a license name from the metadata
    """)
    return


@app.cell
def _(LAYER_NAMES, QUESTIONS, dt, layer_meta, pl, re, runs):
    LAYER_OF = {q[0]: q[1] for q in QUESTIONS}
    AGENCIES = {
        slug: {
            name.lower()
            for (s, _v), m in layer_meta.items()
            if s == slug
            for name in [p["name"] for p in m.get("providers", []) if "producer" in p["roles"]]
            + [m.get("hifld:agency") or "", m.get("hifld:office") or ""]
            if name
        }
        for slug in LAYER_NAMES
    }
    FIELDS = ("layer", "version", "retrieval date", "query URL", "source agency", "license")

    def fields_in(text: str, qid: str, date: str) -> dict[str, bool]:
        low = text.lower()
        slug = LAYER_OF[qid]
        d = dt.date.fromisoformat(date)
        dates = [date, d.strftime("%B %-d, %Y").lower(), d.strftime("%b %-d, %Y").lower()]
        return {
            "layer": slug in low or LAYER_NAMES[slug] in low,
            "version": bool(re.search(r"\bv\d+\.\d+\.\d+|version\s*\d+\.\d+", low)),
            "retrieval date": any(x in low for x in dates),
            "query URL": bool(
                re.search(
                    r"https?://[^\s\"']+/(features/collections/[^\s\"']+/items"
                    r"|api/queries)",
                    low,
                )
                or re.search(r"\bselect\b[\s\S]+?\bfrom\b", low)
            ),
            "source agency": any(a in low for a in AGENCIES[slug]),
            "license": bool(re.search(r"public domain|cc-pdm|\bpdm\b|creative commons", low)),
        }

    _rows = []
    for _r in runs:
        if _r.get("error"):
            continue
        _tools_text = " ".join(t["content"] for t in _r["tools"])
        for _where, _text in (("tool responses", _tools_text), ("final answer", _r["answer"])):
            _rows.append(
                {"arm": _r["arm"], "repeat": _r["repeat"], "qid": _r["qid"], "where": _where}
                | fields_in(_text, _r["qid"], _r["date"])
            )
    presence = pl.DataFrame(_rows)
    field_table = (
        presence.group_by("arm", "where")
        .agg(
            pl.len().alias("answers"),
            *[pl.col(f).sum() for f in FIELDS],
            pl.all_horizontal(*FIELDS).sum().alias("all six"),
        )
        .sort("where", "arm", descending=[True, False])
    )
    field_table
    return FIELDS, LAYER_OF, field_table, presence


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Can the answer be reproduced from the final answer alone?

    We take only the agent's final answer text, as a reader of a report would, and try to
    get the same value again. The rubric is fixed and runs as code:

    - **Reproduced**: the answer contains a recipe pinned to a version (an OGC features URL
      on a `~vX.Y.Z` collection, or SQL reading a `/vX.Y.Z/` GeoParquet file), and running
      it returns the value the agent stated. URLs are fetched; SQL runs in DuckDB on a
      downloaded copy of the named file.
    - **Reproduced with effort**: no pinned recipe that works, but the answer names the layer
      and the stated value matches the key on some version of it. A reader can find the
      layer and write their own query, and for a multi-version layer try each version.
    - **Not reproducible**: neither. The reader can't tell where the number came from, or
      it matches no version of the layer it names.

    Reproducibility is not accuracy: a wrong number with a working pinned recipe is
    reproducible, and that's the point, because the error can be found. We report accuracy
    (the value matches the current version's key) separately.
    """)
    return


@app.cell
def _(CACHE, LAYER_NAMES, LAYER_OF, duckdb, http, key, pl, re, runs):
    URL_RE = re.compile(r"https?://[^\s<>()\[\]\"'`]+")

    def num(s: str) -> float | None:
        m = re.fullmatch(r"-?\d+(\.\d+)?", s.replace(",", "").strip())
        return float(m.group(0)) if m else None

    def same(a: str, b: str) -> bool:
        na, nb = num(a), num(b)
        if na is not None and nb is not None:
            return abs(na - nb) < 0.5
        a, b = a.lower().strip(), b.lower().strip()
        return bool(a) and bool(b) and (a in b or b in a)

    def found_in(value: str, cells: list[str]) -> bool:
        return any(same(value, str(c)) for c in cells)

    def run_ogc(url: str, kind: str) -> tuple[bool, list[str]]:
        pinned = bool(re.search(r"~v\d+\.\d+\.\d+/items", url))
        resp = http.get(url, params={"f": "json"} if "f=" not in url else None)
        if resp.status_code != 200:
            return pinned, []
        body = resp.json()
        if kind == "count":
            return pinned, [str(body.get("numberMatched"))]
        return pinned, [
            str(v) for f in body.get("features", [])[:20] for v in f["properties"].values()
        ]

    def local_copy(url: str) -> str:
        path = CACHE / re.sub(r"[^A-Za-z0-9.]+", "_", url.split("/storage/")[-1])
        if not path.exists():
            resp = http.get(url)
            resp.raise_for_status()
            path.write_bytes(resp.content)
        return str(path)

    def run_sql(text: str) -> list[tuple[bool, list[str], str]]:
        # Every SELECT in the answer, cut at the first sentence break, a prose aside such as
        # "(then filter…)", a code fence or a newline.
        found = []
        for m in re.finditer(
            r"\bselect\b[\s\S]+?(?=\.\s+[A-Z(]|;|\s+\([a-z]+\s|```|\n|$)", text, re.IGNORECASE
        ):
            sql = m.group(0).rstrip(" ;.")
            files = re.findall(r"https?://[^\s'\"]+\.parquet", sql)
            if not files:
                found.append((False, [], "SQL names no data file"))
                continue
            pinned = all(re.search(r"/v\d+\.\d+\.\d+/", f) for f in files)
            try:
                for f in files:
                    sql = sql.replace(f, local_copy(f))
                rows = duckdb.sql(sql).fetchall()[:200]
            except Exception as exc:  # a recipe that doesn't run is a scored outcome
                found.append((pinned, [], f"SQL failed: {type(exc).__name__}"))
                continue
            found.append((pinned, [str(c) for r in rows for c in r], "SQL ran"))
        return found

    def score(r: dict, kind: str) -> dict:
        text, value = r["answer"], r["value"]
        recipes = []
        for url in dict.fromkeys(URL_RE.findall(text)):
            url = url.rstrip(".,;:")
            if "/features/collections/" in url and "/items" in url:
                pinned, cells = run_ogc(url, kind)
                recipes.append((pinned, found_in(value, cells), url.split("/collections/")[-1]))
        for pinned, cells, note in run_sql(text):
            recipes.append((pinned, found_in(value, cells), note))
        slug = LAYER_OF[r["qid"]]
        names_layer = slug in text.lower() or LAYER_NAMES[slug] in text.lower()
        key_vals = key.filter(pl.col("qid") == r["qid"])
        matches = [
            v
            for v, kv in zip(key_vals["version"], key_vals["value"], strict=True)
            if same(value, kv)
        ]
        if any(p and ok for p, ok, _ in recipes):
            verdict = "reproduced"
        elif names_layer and matches:
            verdict = "with effort"
        else:
            verdict = "not reproducible"
        return {
            "verdict": verdict,
            "recipes": len(recipes),
            "recipe_ran_ok": sum(ok for _, ok, _ in recipes),
            "recipe_notes": "; ".join(n for _, _, n in recipes)[:200],
            "names_layer": names_layer,
            "matches_versions": ",".join(matches),
        }

    return same, score


@app.cell
def _(ARMS, QUESTIONS, current, pl, runs, same, score):
    _kind = {q[0]: q[2] for q in QUESTIONS}
    _cur = dict(zip(current["qid"], current["value"], strict=True))
    _rows = []
    for _r in runs:
        _base = {"arm": _r["arm"], "repeat": _r["repeat"], "qid": _r["qid"]}
        if _r.get("error"):
            _rows.append(
                _base
                | {
                    "verdict": "not reproducible",
                    "correct": False,
                    "value": None,
                    "recipe_notes": _r["error"][:200],
                }
            )
            continue
        _rows.append(
            _base
            | {
                "value": _r["value"],
                "key": _cur[_r["qid"]],
                "correct": same(_r["value"], _cur[_r["qid"]]),
            }
            | score(_r, _kind[_r["qid"]])
        )
    scored = pl.DataFrame(_rows, infer_schema_length=None)
    repro_table = (
        scored.group_by("arm")
        .agg(
            pl.len().alias("answers"),
            (pl.col("verdict") == "reproduced").sum().alias("reproduced"),
            (pl.col("verdict") == "with effort").sum().alias("with effort"),
            (pl.col("verdict") == "not reproducible").sum().alias("not reproducible"),
            pl.col("correct").sum().alias("correct (current version)"),
        )
        .sort(pl.col("arm").replace_strict({a: i for i, a in enumerate(ARMS)}))
    )
    repro_table
    return repro_table, scored


@app.cell
def _(mo):
    mo.md(r"""
    Every answer, with its verdict and what the reproducer found. `matches_versions` is
    which versions of the layer the stated value matches; `recipe_notes` lists the URLs it
    fetched or why SQL failed.
    """)
    return


@app.cell
def _(scored):
    scored.select(
        "arm",
        "repeat",
        "qid",
        "value",
        "key",
        "correct",
        "verdict",
        "matches_versions",
        "recipe_notes",
    ).sort("qid", "arm", "repeat")
    return


@app.cell
def _(ARMS, OUT, mo, runs):
    # One version-sensitive question, answered three ways (first repeat), as a reader sees it.
    _by_arm = {r["arm"]: r for r in runs if r["qid"] == "h04" and r["repeat"] == 1}
    _md = "\n\n".join(
        f"### {a}\n\n{_by_arm[a].get('answer') or _by_arm[a].get('error')}"
        for a in ARMS
        if a in _by_arm
    )
    (OUT / "example_h04.md").write_text(
        "# Sunrise Hospital bed count, answered three ways\n\n" + _md + "\n"
    )
    mo.md("**Example: Sunrise Hospital's bed count (h04), answered three ways**\n\n" + _md)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Cost and time
    """)
    return


@app.cell
def _(ARMS, FIELDS, OUT, field_table, json, pl, repro_table, runs, scored):
    _ok = pl.DataFrame([r for r in runs if not r.get("error")], infer_schema_length=None)
    cost_table = (
        _ok.group_by("arm")
        .agg(
            pl.len().alias("runs"),
            pl.col("cost_usd").sum().round(3).alias("total $"),
            pl.col("cost_usd").mean().round(4).alias("$/answer"),
            pl.col("input_tokens").mean().round(0).alias("input tokens"),
            pl.col("tool_calls").mean().round(1).alias("tool calls"),
            pl.col("seconds").median().round(1).alias("median s"),
            pl.col("seconds").quantile(0.9).round(1).alias("p90 s"),
        )
        .sort(pl.col("arm").replace_strict({a: i for i, a in enumerate(ARMS)}))
    )
    summary = {
        "runs": len(runs),
        "errors": sum(bool(r.get("error")) for r in runs),
        "fields": field_table.to_dicts(),
        "reproducibility": repro_table.to_dicts(),
        "cost": cost_table.to_dicts(),
        "field_names": list(FIELDS),
        "total_cost_usd": round(float(_ok["cost_usd"].sum()), 3),
        "wall_seconds_sum": round(float(_ok["seconds"].sum()), 1),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    scored.write_csv(OUT / "scored.csv")
    cost_table
    return (cost_table,)


@app.cell
def _(field_table, mo, pl, repro_table):
    def _cell(arm: str, where: str, col: str) -> int:
        row = field_table.filter((pl.col("arm") == arm) & (pl.col("where") == where))
        return int(row[col][0]) if row.height else 0

    def _rep(arm: str, col: str) -> int:
        row = repro_table.filter(pl.col("arm") == arm)
        return int(row[col][0]) if row.height else 0

    _n = _rep("as shipped", "answers")
    mo.md(f"""
    ## What it shows

    **As shipped**, the tool responses carried a version in
    {_cell("as shipped", "tool responses", "version")} of {_n} runs, but the agent's final
    answer did in {_cell("as shipped", "final answer", "version")}, a query URL or SQL in
    {_cell("as shipped", "final answer", "query URL")}, and all six fields in
    {_cell("as shipped", "final answer", "all six")}. Reproduced from the answer alone:
    **{_rep("as shipped", "reproduced")}** of {_n}, with effort
    {_rep("as shipped", "with effort")}, not reproducible
    {_rep("as shipped", "not reproducible")}.

    **Instruction only**: reproduced **{_rep("instruction only", "reproduced")}**, with
    effort {_rep("instruction only", "with effort")}, not reproducible
    {_rep("instruction only", "not reproducible")}; all six fields in
    {_cell("instruction only", "final answer", "all six")} final answers.

    **Proxy + instruction**: reproduced **{_rep("proxy + instruction", "reproduced")}**,
    with effort {_rep("proxy + instruction", "with effort")}, not reproducible
    {_rep("proxy + instruction", "not reproducible")}; all six fields in
    {_cell("proxy + instruction", "final answer", "all six")} final answers.
    """)
    return


if __name__ == "__main__":
    app.run()

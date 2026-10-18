import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import asyncio
    import csv
    import json
    import os
    import random
    import re
    import time
    from dataclasses import replace
    from pathlib import Path

    import httpx
    import marimo as mo
    import polars as pl
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent, capture_run_messages
    from pydantic_ai.mcp import MCPToolset
    from pydantic_ai.messages import ModelMessagesTypeAdapter
    from pydantic_ai.usage import UsageLimits

    return (
        Agent,
        BaseModel,
        Field,
        MCPToolset,
        ModelMessagesTypeAdapter,
        Path,
        UsageLimits,
        asyncio,
        capture_run_messages,
        csv,
        httpx,
        json,
        mo,
        os,
        pl,
        random,
        re,
        replace,
        time,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Can an AI agent using the HIFLD Next MCP server find the records we know are there?

    Before anyone trusts a search that comes back empty, it should be shown to find what is
    known to be there. This notebook builds a list of datasets and individual facilities that
    are in [HIFLD Next](https://hifld.publicenvirodata.org), asks for each one the way a person
    would, and counts what comes back through two paths:

    1. **Catalog search alone**: the portal's public search API. Is the right dataset ranked
       first, in the top 5, or anywhere?
    2. **An AI agent using the HIFLD Next MCP server**: does it name the right dataset and the
       right record, and does it cite IDs we can check mechanically against the key?
    """)
    return


@app.cell
def _(mo, os):
    # Endpoints come from https://hifld.publicenvirodata.org/api, which links the MCP server card.
    BASE_URL = os.environ.get("HIFLD_BASE_URL", "https://hifld.publicenvirodata.org")
    MCP_URL = f"{BASE_URL}/mcp"
    SEED = 54
    DATASET_SAMPLE = 40
    RECORDS_PER_LAYER = 7
    # Point-facility layers to sample records from, with the column that identifies a record.
    RECORD_LAYERS = {
        "power-plants-1": "PLANT_CODE",
        "hospitals-3": "source_ID",
        "national-inventory-of-dams-nid-1": "NIDID",
        "nursing-homes": "source_ID",
        "colleges-and-universities": "IPEDSID",
        "prison-boundaries-1": "FACILITYID",
    }
    # (model on OpenRouter, patch the source schemas on the client side). See section 3.
    AGENTS = [
        ("anthropic/claude-haiku-5.5", False),
        ("openai/gpt-6-luna", False),
        ("openai/gpt-6-luna", True),
    ]
    REPEATS = int(os.environ.get("AGENT_REPEATS", "2"))
    BUDGET_USD = float(os.environ.get("AGENT_BUDGET_USD", "3.0"))
    HERE = mo.notebook_dir()
    OUT = HERE / "outputs"
    OUT.mkdir(exist_ok=True)
    return (
        BASE_URL,
        AGENTS,
        BUDGET_USD,
        DATASET_SAMPLE,
        HERE,
        MCP_URL,
        OUT,
        RECORDS_PER_LAYER,
        RECORD_LAYERS,
        REPEATS,
        SEED,
    )


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. The test set

    The answer key comes from HIFLD Next itself. With a fixed seed we sample 40 of the
    catalog's datasets, then 7 records from each of six point-facility layers (power plants,
    hospitals, dams, nursing homes, colleges, prisons). For each item we wrote the question a
    person might ask; a little under half are paraphrased or colloquial on purpose ("CDL
    schools" for *Truck Driving Schools*, "Overlook Hospital" for *OVERLOOK MEDICAL CENTER*).

    The committed `key.csv` holds the questions and the IDs. This cell re-draws the sample and
    checks it still matches the key, then collects every ID-like value of each sampled record
    (`OBJECTID`, `STATE_ID` and so on), since an agent may cite any of them.
    """)
    return


@app.cell
def _(
    BASE_URL,
    DATASET_SAMPLE,
    RECORDS_PER_LAYER,
    RECORD_LAYERS,
    HERE,
    SEED,
    csv,
    httpx,
    pl,
    random,
    re,
):
    http = httpx.Client(timeout=120)
    datasets = []
    for _page in range(20):  # the catalog has ~330 datasets; 20 pages of 100 is a hard bound
        _resp = http.get(
            f"{BASE_URL}/api/collections/hifld/datasets",
            params={"limit": 100, "offset": 100 * _page, "omit": "description"},
        )
        _resp.raise_for_status()
        _body = _resp.json()
        datasets += _body["datasets"]
        if len(datasets) >= _body["total"]:
            break
    datasets.sort(key=lambda d: d["id"])
    catalog_size = len(datasets)

    rng = random.Random(SEED)
    sampled = [(d["id"], "", "") for d in rng.sample(datasets, DATASET_SAMPLE)]
    for _slug, _id_col in RECORD_LAYERS.items():
        _items_url = f"{BASE_URL}/features/collections/hifld~{_slug}~{_slug}/items"
        _resp = http.get(_items_url, params={"f": "json", "limit": 1})
        _resp.raise_for_status()
        _n = _resp.json()["numberMatched"]
        for _offset in sorted(rng.sample(range(_n), RECORDS_PER_LAYER)):
            _resp = http.get(_items_url, params={"f": "json", "limit": 1, "offset": _offset})
            _resp.raise_for_status()
            _props = _resp.json()["features"][0]["properties"]
            _ids = {
                str(v)
                for k, v in _props.items()
                if re.search(r"(^ID|ID$)", k.upper())
                and v is not None
                and str(v) not in ("", "NOT AVAILABLE")
                and not str(v).startswith("-")
            }
            sampled.append((f"hifld/{_slug}", str(_props[_id_col]), "|".join(sorted(_ids))))

    with open(HERE / "key.csv", newline="") as _fh:
        key_rows = list(csv.DictReader(_fh))
    _matches = sum(
        (k["dataset_id"], k["record_id"]) == (s[0], s[1])
        for k, s in zip(key_rows, sampled, strict=False)
    )
    assert _matches == len(key_rows) == len(sampled), (
        f"re-sample matches only {_matches}/{len(key_rows)} key rows; the catalog has changed"
    )
    key = pl.DataFrame(key_rows).with_columns(pl.Series("record_ids", [s[2] for s in sampled]))
    key
    return catalog_size, http, key


@app.cell
def _(catalog_size, key, mo):
    mo.md(f"""
    Re-sampled from a catalog of **{catalog_size} datasets** with seed 54: all
    **{key.height} items** match the committed key ({(key["kind"] == "dataset").sum()} datasets,
    {(key["kind"] == "record").sum()} records; {(key["phrasing"] != "exact").sum()} phrased as a
    paraphrase or colloquially).
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. Catalog search alone

    The search API ranks datasets by full-text match, and every word must match. We send each
    item's `search_terms`, the words a person would type into a search box (for a record item,
    the kind of facility, since the catalog indexes datasets, not records). We also send the
    whole question, as someone pasting a sentence would. We record the rank of the key dataset.
    """)
    return


@app.cell
def _(BASE_URL, OUT, http, key, pl):
    def rank_in_search(text: str, dataset_id: str) -> tuple[int | None, str]:
        resp = http.get(
            f"{BASE_URL}/api/collections/hifld/datasets",
            params={"search": text, "limit": 100, "omit": "description"},
        )
        resp.raise_for_status()
        ids = [d["id"] for d in resp.json()["datasets"]]
        top = ids[0] if ids else ""
        return (ids.index(dataset_id) + 1 if dataset_id in ids else None), top

    _rows = []
    for _item in key.iter_rows(named=True):
        _terms_rank, _terms_top = rank_in_search(_item["search_terms"], _item["dataset_id"])
        _question_rank, _ = rank_in_search(_item["question"], _item["dataset_id"])
        _rows.append(
            {
                "item_id": _item["item_id"],
                "terms_rank": _terms_rank,
                "terms_top": _terms_top,
                "question_rank": _question_rank,
            }
        )
    catalog = key.select("item_id", "kind", "phrasing", "dataset_id", "search_terms").join(
        pl.DataFrame(_rows, schema_overrides={"terms_rank": pl.Int64, "question_rank": pl.Int64}),
        on="item_id",
    )

    def recall(frame: pl.DataFrame, col: str) -> pl.DataFrame:
        return frame.group_by("kind").agg(
            n=pl.len(),
            **{
                f"{col}@1": (pl.col(col) == 1).mean(),
                f"{col}@5": (pl.col(col) <= 5).mean(),
                f"{col}_found": pl.col(col).is_not_null().mean(),
            },
        )

    catalog_recall = (
        recall(catalog, "terms_rank")
        .join(recall(catalog, "question_rank").drop("n"), on="kind")
        .sort("kind")
    )
    catalog.write_csv(OUT / "catalog_results.csv")
    catalog_recall
    return catalog, catalog_recall


@app.cell
def _(catalog, pl):
    # Misses by catalog search with the typed terms, by phrasing.
    catalog.group_by("phrasing").agg(
        n=pl.len(),
        at_1=(pl.col("terms_rank") == 1).mean(),
        found=pl.col("terms_rank").is_not_null().mean(),
    ).sort("phrasing")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. An agent on the MCP server

    A [Pydantic AI](https://ai.pydantic.dev) agent connects to the public MCP server at
    `/mcp`. We keep its ten catalog and query tools and drop the map-widget tools, which
    render UI and can't help find anything. The agent must return a typed answer: the dataset
    ID, the record ID, whether it found the item, a short answer and a source link. The
    instructions say what the IDs look like but give no hint about which layer holds what.
    Tool errors go back to the model, which may retry each tool up to three times.

    **One thing we found while building this.** The server's `query_parquet` and
    `read_geoparquet_rows` tools declare their `sources` argument as an object with no listed
    properties, while `inspect_query_source` spells out the same object field by field. The
    Anthropic model fills in the fields anyway; the OpenAI model sends `{}` every time, the
    server rejects it, and the agent can never read a row. So we run three agents: the two
    models as the server ships, and the OpenAI model once more with the typed `source` schema
    from `inspect_query_source` copied onto the other two tools on our side. The third agent
    is not the portal as shipped; it shows how much of the gap that one schema causes.

    Each agent runs every item twice, so the run-to-run variance is visible. A budget guard
    stops starting new items once this run's spend passes `AGENT_BUDGET_USD`.
    """)
    return


@app.cell
def _(Agent, BaseModel, Field, MCPToolset, MCP_URL, replace):
    class Answer(BaseModel):
        found: bool = Field(description="True only if you located the item in HIFLD Next data.")
        dataset_id: str | None = Field(
            description="Collection and dataset slug, for example 'hifld/railroads'."
        )
        record_id: str | None = Field(
            description=(
                "For a question about one facility or feature: the identifier stored in that "
                "record (an ID column such as a plant code or facility ID), copied exactly. "
                "Null for questions about a whole dataset."
            )
        )
        answer: str = Field(description="One or two sentences answering the question.")
        source_link: str | None = Field(description="A URL for the dataset or record.")

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
    INSTRUCTIONS = (
        "You answer questions about HIFLD Next, a public catalog of US infrastructure datasets, "
        "using only its MCP tools. Find the dataset that answers the question and, if the "
        "question is about one facility or feature, the record for it. Cite IDs copied from "
        "tool results; never guess an ID. If you can't find it, set found to false."
    )

    def type_sources(_ctx: object, tools: list) -> list:
        # Copy inspect_query_source's typed `source` object onto the tools that leave it untyped.
        typed = next(t for t in tools if t.name == "inspect_query_source")
        source = typed.parameters_json_schema["properties"]["source"]
        patched = []
        for tool in tools:
            schema = tool.parameters_json_schema
            props = dict(schema["properties"])
            if tool.name == "read_geoparquet_rows":
                props["source"] = source
            elif tool.name == "query_parquet":
                props["sources"] = {"type": "array", "items": source}
            patched.append(replace(tool, parameters_json_schema=schema | {"properties": props}))
        return patched

    def make_agent(model: str, patch: bool) -> Agent[None, Answer]:
        toolset = MCPToolset(MCP_URL, max_retries=3).filtered(
            lambda _ctx, tool: tool.name in QUERY_TOOLS
        )
        if patch:
            toolset = toolset.prepared(type_sources)
        return Agent(
            f"openrouter:{model}",
            toolsets=[toolset],
            output_type=Answer,
            instructions=INSTRUCTIONS,
            model_settings={"openrouter_usage": {"include": True}},
        )

    return (make_agent,)


@app.cell
async def _(
    AGENTS,
    BUDGET_USD,
    ModelMessagesTypeAdapter,
    OUT,
    REPEATS,
    UsageLimits,
    asyncio,
    capture_run_messages,
    key,
    make_agent,
    pl,
    time,
):
    spend = {"usd": 0.0}
    transcripts: dict[tuple[str, int, str], bytes] = {}

    async def ask(agent, label: str, repeat: int, item: dict, gate: asyncio.Semaphore) -> dict:
        row = {
            "model": label,
            "repeat": repeat,
            "item_id": item["item_id"],
            "error": None,
        }
        async with gate:
            if spend["usd"] >= BUDGET_USD:
                return row | {"error": "skipped: budget reached"}
            start = time.monotonic()
            with capture_run_messages() as messages:
                try:
                    result = await asyncio.wait_for(
                        agent.run(item["question"], usage_limits=UsageLimits(request_limit=25)),
                        timeout=300,
                    )
                except Exception as exc:  # a failed run is a measured outcome, not a crash
                    transcripts[(label, repeat, item["item_id"])] = (
                        ModelMessagesTypeAdapter.dump_json(messages, indent=1)
                    )
                    return row | {
                        "error": f"{type(exc).__name__}: {exc}"[:300],
                        "seconds": time.monotonic() - start,
                    }
            usage = result.usage
            cost = float(usage.cost or 0)
            spend["usd"] += cost
            transcripts[(label, repeat, item["item_id"])] = ModelMessagesTypeAdapter.dump_json(
                result.all_messages(), indent=1
            )
            return (
                row
                | result.output.model_dump()
                | {
                    "seconds": time.monotonic() - start,
                    "cost_usd": cost,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "requests": usage.requests,
                    "tool_calls": usage.tool_calls,
                }
            )

    _runs = []
    for _model, _patch in AGENTS:
        _agent = make_agent(_model, _patch)
        _label = _model + (" + typed sources" if _patch else "")
        async with _agent:
            for _repeat in range(1, REPEATS + 1):
                _gate = asyncio.Semaphore(10)
                _runs += await asyncio.gather(
                    *(
                        ask(_agent, _label, _repeat, _item, _gate)
                        for _item in key.iter_rows(named=True)
                    )
                )
    agent_raw = pl.DataFrame(_runs, infer_schema_length=None)
    agent_raw.write_csv(OUT / "agent_results.csv")
    print(f"agent runs: {agent_raw.height}, spend this run: ${spend['usd']:.4f}")
    return agent_raw, spend, transcripts


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Scoring against the key

    * **Dataset hit**: the cited `dataset_id` is the key dataset (with or without the
      `hifld/` prefix).
    * **Record hit**: the cited `record_id` equals one of the sampled record's ID values,
      ignoring case and leading zeros.
    * **Traces to a source record**: dataset hit *and* record hit, so the answer can be checked
      mechanically. For dataset questions, traceable means the dataset ID is right.

    Each miss gets one type, decided by rules rather than by reading:

    * *naming difference*: the agent missed and catalog search on the person's words doesn't
      return the key dataset at all;
    * *wrong layer ranked first*: catalog search returns the key dataset, but not first, and
      the agent cited another layer;
    * *chose another layer*: catalog search ranks the key dataset first, and the agent still
      cited another one;
    * *record in another layer*: a record question where the agent says it found the facility
      but in a different dataset (records split across layers);
    * *record not located*: right dataset, but the agent didn't find the record;
    * *wrong or missing record ID*: right dataset, the agent says it found the record, but its
      ID doesn't match;
    * *said not found* / *error*: no dataset cited, or the run failed.
    """)
    return


@app.cell
def _(OUT, agent_raw, catalog, key, pl, re):
    def norm_id(value: str | None) -> str:
        return re.sub(r"^0+", "", (value or "").strip().lower())

    def miss_type(row: dict) -> str | None:
        if row["error"]:
            return "error"
        if row["kind"] == "dataset" and row["dataset_hit"]:
            return None
        if row["kind"] == "record" and row["dataset_hit"] and row["record_hit"]:
            return None
        if row["dataset_hit"]:
            return "wrong or missing record ID" if row["found"] else "record not located"
        if not row["dataset_id"]:
            return "said not found"
        if row["kind"] == "record" and row["found"]:
            return "record in another layer"
        if row["terms_rank"] is None:
            return "naming difference"
        if row["terms_rank"] > 1:
            return "wrong layer ranked first"
        return "chose another layer"

    _joined = agent_raw.join(
        key.select(
            "item_id",
            "kind",
            "phrasing",
            pl.col("dataset_id").alias("key_dataset"),
            "record_ids",
            "name",
        ),
        on="item_id",
    ).join(catalog.select("item_id", "terms_rank"), on="item_id")
    _scored = []
    for _row in _joined.iter_rows(named=True):
        _cited = (_row["dataset_id"] or "").strip().lower()
        _row["dataset_hit"] = _cited in (
            _row["key_dataset"],
            _row["key_dataset"].split("/")[1],
        )
        _key_ids = {norm_id(i) for i in _row["record_ids"].split("|") if i}
        _row["record_hit"] = bool(_row["record_id"]) and norm_id(_row["record_id"]) in _key_ids
        _row["cited_both"] = bool(_row["dataset_id"]) and bool(_row["record_id"])
        _row["traces"] = _row["dataset_hit"] and (_row["kind"] == "dataset" or _row["record_hit"])
        _row["miss"] = miss_type(_row)
        _scored.append(_row)
    scored = pl.DataFrame(_scored, infer_schema_length=None)
    scored.write_csv(OUT / "agent_scored.csv")
    return (scored,)


@app.cell
def _(pl, scored):
    # Agent recall per model and repeat. record_hit only applies to record questions.
    agent_recall = (
        scored.group_by("model", "repeat", "kind")
        .agg(
            n=pl.len(),
            dataset_recall=pl.col("dataset_hit").mean(),
            record_recall=pl.when(pl.col("kind") == "record").then(pl.col("record_hit")).mean(),
            cited_both_ids=pl.col("cited_both").mean(),
            traces_to_source=pl.col("traces").mean(),
            errors=pl.col("error").is_not_null().sum(),
        )
        .sort("kind", "model", "repeat")
    )
    agent_recall
    return (agent_recall,)


@app.cell
def _(mo):
    mo.md(r"""
    ### Variance

    The same question can pass on one run and fail on the next. Below: for each model, how
    many items got the same verdict (trace or no trace) on both runs, and the overall share
    of items that traced on every run of every model.
    """)
    return


@app.cell
def _(pl, scored):
    _per_item = scored.group_by("model", "item_id").agg(
        runs=pl.len(), traced=pl.col("traces").sum()
    )
    variance = (
        _per_item.group_by("model")
        .agg(
            items=pl.len(),
            always=(pl.col("traced") == pl.col("runs")).sum(),
            never=(pl.col("traced") == 0).sum(),
            flipped=((pl.col("traced") > 0) & (pl.col("traced") < pl.col("runs"))).sum(),
        )
        .sort("model")
    )
    variance
    return (variance,)


@app.cell
def _(mo):
    mo.md(r"""
    ### Misses by type, and by how the question was phrased
    """)
    return


@app.cell
def _(pl, scored):
    miss_tally = (
        scored.filter(pl.col("miss").is_not_null())
        .group_by("miss", "kind")
        .agg(n=pl.len())
        .pivot(on="kind", index="miss", values="n")
        .fill_null(0)
        .sort("miss")
    )
    by_phrasing = (
        scored.group_by("kind", "phrasing")
        .agg(runs=pl.len(), traces_to_source=pl.col("traces").mean())
        .sort("kind", "phrasing")
    )
    miss_tally, by_phrasing
    return (miss_tally,)


@app.cell
def _(pl, scored):
    # Every miss, with what the agent cited. Names and IDs are public HIFLD values.
    scored.filter(pl.col("miss").is_not_null()).select(
        "item_id",
        "model",
        "repeat",
        "miss",
        "phrasing",
        "key_dataset",
        "name",
        "dataset_id",
        "record_id",
        "answer",
    ).sort("item_id", "model", "repeat")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Cost, tokens and time per query
    """)
    return


@app.cell
def _(pl, scored, spend):
    cost_table = (
        scored.filter(pl.col("error").is_null())
        .group_by("model")
        .agg(
            queries=pl.len(),
            total_usd=pl.col("cost_usd").sum(),
            usd_per_query=pl.col("cost_usd").mean(),
            input_tokens_per_query=pl.col("input_tokens").mean(),
            output_tokens_per_query=pl.col("output_tokens").mean(),
            tool_calls_per_query=pl.col("tool_calls").mean(),
            median_seconds=pl.col("seconds").median(),
            p90_seconds=pl.col("seconds").quantile(0.9),
        )
        .sort("model")
    )
    print(f"Total OpenRouter spend this run: ${spend['usd']:.4f}")
    cost_table
    return (cost_table,)


@app.cell
def _(
    OUT,
    agent_recall,
    catalog_recall,
    cost_table,
    json,
    miss_tally,
    pl,
    scored,
    spend,
    transcripts,
    variance,
):
    # Save a few full transcripts: per model, the first dataset hit, the first record hit and
    # the first two misses of repeat 1.
    _dir = OUT / "transcripts"
    _dir.mkdir(exist_ok=True)
    for _old in _dir.glob("*.json"):
        _old.unlink()
    for _model in scored["model"].unique().sort():
        _first = scored.filter((pl.col("model") == _model) & (pl.col("repeat") == 1))
        _picks = (
            _first.filter(pl.col("traces") & (pl.col("kind") == "dataset"))
            .head(1)["item_id"]
            .to_list()
            + _first.filter(pl.col("traces") & (pl.col("kind") == "record"))
            .head(1)["item_id"]
            .to_list()
            + _first.filter(pl.col("miss").is_not_null()).head(2)["item_id"].to_list()
        )
        for _item in _picks:
            _blob = transcripts.get((_model, 1, _item))
            if _blob:
                (_dir / f"{_model.replace('/', '_')}-{_item}.json").write_bytes(_blob)

    _summary = {
        "catalog_recall": catalog_recall.to_dicts(),
        "agent_recall": agent_recall.to_dicts(),
        "variance": variance.to_dicts(),
        "misses": miss_tally.to_dicts(),
        "cost": cost_table.to_dicts(),
        "total_spend_usd": spend["usd"],
    }
    (OUT / "summary.json").write_text(json.dumps(_summary, indent=1, default=str))
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What this test can't see

    * It measures recall only on items we chose. A miss we didn't think to ask about is
      invisible here, and 82 items is a small sample: one item is 2.5 points of dataset recall.
    * The dataset sample is uniform over the catalog, so it is heavy with USACE inland
      navigation-chart layers, which make up a large share of HIFLD Next. Record items come
      from six well-kept facility layers only.
    * The miss types are assigned by rules. They are a first sort, not a diagnosis; read the
      misses table and the saved transcripts for the actual reasons.
    * We built HIFLD Next, so a good score here can read as promotion. The misses table is the
      part to read.
    """)
    return


if __name__ == "__main__":
    app.run()

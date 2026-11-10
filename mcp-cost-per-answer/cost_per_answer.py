import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import asyncio
    import json
    import os
    import time
    from urllib.parse import urlparse

    import httpx
    import marimo as mo
    import polars as pl
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent, capture_run_messages
    from pydantic_ai.mcp import MCPToolset
    from pydantic_ai.messages import (
        ModelMessagesTypeAdapter,
        ModelRequest,
        ModelResponse,
        ToolReturnPart,
    )
    from pydantic_ai.usage import UsageLimits

    return (
        Agent,
        BaseModel,
        ClientSession,
        Field,
        MCPToolset,
        ModelMessagesTypeAdapter,
        ModelRequest,
        ModelResponse,
        ToolReturnPart,
        UsageLimits,
        asyncio,
        capture_run_messages,
        httpx,
        json,
        mo,
        os,
        pl,
        streamable_http_client,
        time,
        urlparse,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # What does one answer cost an AI agent through a public data MCP server?

    Public data publishers are putting [MCP](https://modelcontextprotocol.io) servers in front
    of their data so AI agents can query it. Each answer an agent gets costs its user tokens,
    tool calls, time and money. We expect that cost to differ by an order of magnitude between
    servers, and to depend less on the data than on how the tools are designed: how many calls
    it takes to get valid filter codes, how much each result returns, and whether results carry
    their own citation.

    We ask about 20 questions with known answers through each of three public servers, with the
    same client and model, and count what every answer costs and whether it is right:

    - [HIFLD Next](https://hifld.publicenvirodata.org) (`/mcp`): US infrastructure, 400+
      datasets, run by Public Environmental Data Partners. We built it.
    - [mcp.mospi.gov.in](https://github.com/nso-india/esankhyiki-mcp): Indian official
      statistics from India's Ministry of Statistics (MoSPI).
    - [Education Data Portal](https://educationdata.urban.org/mcp/edp): US schools, districts
      and colleges, from the Urban Institute.

    Then we make one design change to HIFLD Next, on our side of the wire, and rerun it.
    """)
    return


@app.cell
def _(mo, os):
    SERVERS = {
        "HIFLD Next": {
            "url": "https://hifld.publicenvirodata.org/mcp",
            "domains": ("hifld.publicenvirodata.org",),
            "key": "hifld",
        },
        "MoSPI": {
            "url": "https://mcp.mospi.gov.in/mcp",
            "domains": ("mospi.gov.in",),
            "key": "mospi",
        },
        "Urban EDP": {
            "url": "https://educationdata.urban.org/mcp/edp",
            "domains": ("educationdata.urban.org",),
            "key": "urban",
        },
    }
    MODEL = os.environ.get("AGENT_MODEL", "anthropic/claude-haiku-5.5")
    REPEATS = int(os.environ.get("AGENT_REPEATS", "2"))
    BUDGET_USD = float(os.environ.get("AGENT_BUDGET_USD", "4.0"))
    # RESCORE=1 scores the committed runs in outputs/runs_*.jsonl without calling any model.
    RESCORE = os.environ.get("RESCORE", "") == "1"
    HERE = mo.notebook_dir()
    OUT = HERE / "outputs"
    (OUT / "transcripts").mkdir(parents=True, exist_ok=True)
    return BUDGET_USD, HERE, MODEL, OUT, REPEATS, RESCORE, SERVERS


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. What each server sends before the first question

    An MCP client sends every tool's name, description and input schema to the model on
    **every** request, plus the server's instructions if it has any. That is a fixed cost per
    step, paid before any data comes back. Here is what each server ships, read straight from
    the servers.
    """)
    return


@app.cell
async def _(ClientSession, OUT, SERVERS, json, pl, streamable_http_client):
    _rows = []
    _shipped = {}
    for _name, _server in SERVERS.items():
        async with (
            streamable_http_client(_server["url"]) as (_read, _write),
            ClientSession(_read, _write) as _session,
        ):
            _init = await _session.initialize()
            _tools = (await _session.list_tools()).tools
        _defs = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in _tools
        ]
        _shipped[_name] = {"instructions": _init.instructions, "tools": _defs}
        _rows.append(
            {
                "server": _name,
                "tools": len(_tools),
                "tool_definition_chars": len(json.dumps(_defs)),
                "instruction_chars": len(_init.instructions or ""),
                "largest_tool": max(_defs, key=lambda d: len(json.dumps(d)))["name"],
            }
        )
    (OUT / "tool_definitions.json").write_text(json.dumps(_shipped, indent=1))
    shipped = pl.DataFrame(_rows)
    shipped
    return (shipped,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. The questions

    One set per server, written the way that server's users would ask, each with one answer we
    looked up ourselves from the publisher's own API (the `how_found` column has the exact call,
    so anyone can check the key). Numbers carry a tolerance for honest rounding; names carry the
    strings we accept. The questions differ by server because the data does; section 7 comes
    back to what that does to the comparison.
    """)
    return


@app.cell
def _(HERE, SERVERS, pl):
    questions = pl.concat(
        [
            pl.read_csv(HERE / "questions" / f"{s['key']}.csv", infer_schema_length=0).with_columns(
                server=pl.lit(name)
            )
            for name, s in SERVERS.items()
        ]
    )
    assert questions["qid"].n_unique() == questions.height, "question IDs must be unique"
    assert set(questions["kind"].unique()) <= {"number", "text"}
    questions.group_by("server").agg(questions=pl.len()).sort("server")
    return (questions,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. One client, one model

    A [Pydantic AI](https://ai.pydantic.dev) agent connects to each server as shipped: every
    tool it lists, and its instructions if it sends any (Urban's server does; the other two
    don't). The model is Claude Haiku 5.5 on OpenRouter, which reports the dollar cost of each
    request. The agent must return a typed answer: a sentence, the number if there is one, and
    the source a reader could use to check it. Our instructions say nothing about any server,
    so the only guidance it gets is what the server itself provides. A run stops at 25 model
    requests or 5 minutes.
    """)
    return


@app.cell
def _(Agent, BaseModel, Field, MCPToolset, MODEL):
    class Answer(BaseModel):
        found: bool = Field(description="True only if the tools returned data that answers it.")
        answer: str = Field(description="One or two sentences answering the question.")
        value: float | None = Field(
            description=(
                "The number that answers the question, as published, in the units the question "
                "implies (a rate of 3.2% is 3.2). Null if the answer is a name."
            )
        )
        source_url: str | None = Field(
            description=(
                "A URL a reader could open to check the figure: the dataset, record, or the "
                "API query the data came from, copied from tool results where possible."
            )
        )
        citation: str | None = Field(
            description="The source as a reader should cite it, using the publisher's citation "
            "if the tools give one."
        )

    INSTRUCTIONS = (
        "You answer questions about public data using only the tools of the connected data "
        "server. Look the answer up; never answer from memory. Report figures exactly as the "
        "data gives them and cite where they came from. If the tools can't answer it, set "
        "found to false."
    )

    def make_agent(toolset: MCPToolset) -> Agent[None, Answer]:
        return Agent(
            f"openrouter:{MODEL}",
            toolsets=[toolset],
            output_type=Answer,
            instructions=INSTRUCTIONS,
            model_settings={"openrouter_usage": {"include": True}},
        )

    return (make_agent,)


@app.cell
def _(
    ModelMessagesTypeAdapter,
    ModelRequest,
    ModelResponse,
    OUT,
    ToolReturnPart,
    UsageLimits,
    asyncio,
    capture_run_messages,
    time,
):
    def tool_result_chars(messages: list) -> int:
        # How much data the tools sent back to the model over the whole run.
        return sum(
            len(part.model_response_str())
            for m in messages
            if isinstance(m, ModelRequest)
            for part in m.parts
            if isinstance(part, ToolReturnPart)
        )

    async def ask(agent, variant: str, repeat: int, q: dict, gate, spend: dict, budget: float):
        row = {"variant": variant, "server": q["server"], "qid": q["qid"], "repeat": repeat}
        async with gate:
            if spend["usd"] >= budget:
                return row | {"error": "skipped: budget reached"}
            start = time.monotonic()
            with capture_run_messages() as messages:
                try:
                    result = await asyncio.wait_for(
                        agent.run(q["question"], usage_limits=UsageLimits(request_limit=25)),
                        timeout=300,
                    )
                except Exception as exc:  # a failed run is a measured outcome, not a crash
                    error = f"{type(exc).__name__}: {exc}"[:300]
                    result = None
            seconds = time.monotonic() - start
            final = result.all_messages() if result else messages
            path = OUT / "transcripts" / f"{variant}-{q['qid']}-{repeat}.json"
            path.write_bytes(ModelMessagesTypeAdapter.dump_json(final, indent=1))
            responses = [m for m in final if isinstance(m, ModelResponse)]
            # OpenRouter reports each response's cost, so a failed run is still priced.
            cost = sum((m.provider_details or {}).get("cost", 0) for m in responses)
            spend["usd"] += cost
            row |= {
                "seconds": round(seconds, 2),
                "cost_usd": cost,
                "input_tokens": sum(m.usage.input_tokens for m in responses),
                "output_tokens": sum(m.usage.output_tokens for m in responses),
                "requests": len(responses),
                "tool_calls": sum(len(m.tool_calls) for m in responses),
                "tool_result_chars": tool_result_chars(final),
                "transcript": path.name,
            }
            if result is None:
                return row | {"error": error}
            return row | result.output.model_dump() | {"error": None}

    return (ask,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Run every question through its server

    Four questions run at a time per server. Each run's full transcript is saved to
    `outputs/transcripts/` and its usage to `outputs/runs_*.jsonl`, so the scoring below can be
    rerun or changed without paying for model calls (`RESCORE=1 ./run.sh`).
    """)
    return


@app.cell
async def _(
    BUDGET_USD,
    MCPToolset,
    OUT,
    REPEATS,
    RESCORE,
    SERVERS,
    ask,
    asyncio,
    make_agent,
    pl,
    questions,
):
    spend = {"usd": 0.0}
    if RESCORE:
        runs = pl.read_ndjson(OUT / "runs_shipped.jsonl")
    else:
        _rows = []
        for _name, _server in SERVERS.items():
            _agent = make_agent(
                MCPToolset(_server["url"], max_retries=3, include_instructions=True)
            )
            _gate = asyncio.Semaphore(4)
            _qs = questions.filter(pl.col("server") == _name).iter_rows(named=True)
            _qs = list(_qs)
            async with _agent:
                for _repeat in range(1, REPEATS + 1):
                    _rows += await asyncio.gather(
                        *(
                            ask(_agent, "shipped", _repeat, _q, _gate, spend, BUDGET_USD)
                            for _q in _qs
                        )
                    )
        runs = pl.DataFrame(_rows, infer_schema_length=None)
        runs.write_ndjson(OUT / "runs_shipped.jsonl")
    print(f"{runs.height} runs, ${spend['usd']:.4f} spent in this section")
    return runs, spend


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Score every answer

    **Correct**: a number within the key's tolerance, or a name containing one of the strings
    the key accepts. **Checkable source**: the answer gives a URL on the publisher's own domain
    that opens (HTTP status below 400) and is more than the home page. A named dataset with no
    link doesn't count, because a reader can't click it; we report it separately as
    `has_citation`. Failed runs count as wrong and their cost counts.
    """)
    return


@app.cell
def _(
    ModelMessagesTypeAdapter,
    ModelRequest,
    OUT,
    SERVERS,
    ToolReturnPart,
    httpx,
    pl,
    questions,
    urlparse,
):
    def is_correct(row: dict) -> bool:
        if row["error"]:
            return False
        if row["kind"] == "number":
            if row["value"] is None:
                return False
            key, tol = float(row["answer_key"]), float(row["tolerance"] or 0)
            return abs(row["value"] - key) <= tol * abs(key) + 1e-9
        said = f"{row['answer']} {row['value']}".lower()
        return any(term.strip() and term.strip() in said for term in row["accept"].split("|"))

    def cited_url(row: dict) -> str:
        # Agents sometimes put a note after the link; the link is the first token.
        first = (row["source_url"] or "").split(" ")[0]
        return first if first.startswith("http") else ""

    def tool_text(transcript: str) -> str:
        messages = ModelMessagesTypeAdapter.validate_json(
            (OUT / "transcripts" / transcript).read_bytes()
        )
        return " ".join(
            part.model_response_str()
            for m in messages
            if isinstance(m, ModelRequest)
            for part in m.parts
            if isinstance(part, ToolReturnPart)
        )

    async def score(runs: pl.DataFrame) -> pl.DataFrame:
        rows = runs.join(
            questions.select(
                "server", "qid", "kind", "tolerance", "accept", pl.col("answer").alias("answer_key")
            ),
            on=["server", "qid"],
            how="left",
        ).with_columns(pl.col("accept").fill_null(""))
        urls = {cited_url(r) for r in rows.iter_rows(named=True)} - {""}
        status: dict[str, int] = {}
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as http:
            for url in sorted(urls):
                try:
                    async with http.stream("GET", url) as resp:
                        status[url] = resp.status_code
                except (httpx.HTTPError, httpx.InvalidURL):
                    status[url] = 0
        out = []
        for r in rows.iter_rows(named=True):
            url = cited_url(r)
            parsed = urlparse(url)
            on_domain = any(
                (parsed.hostname or "").endswith(d) for d in SERVERS[r["server"]]["domains"]
            )
            deep = parsed.path.strip("/") != "" or parsed.query != ""
            link = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
            out.append(
                {
                    "correct": is_correct(r),
                    "checkable": on_domain and deep and 0 < status.get(url, 0) < 400,
                    "url_from_tools": bool(url)
                    and r["requests"] > 0
                    and link in tool_text(r["transcript"]),
                }
            )
        print(f"checked {len(status)} cited URLs, {sum(0 < v < 400 for v in status.values())} open")
        return pl.concat([rows, pl.DataFrame(out)], how="horizontal").with_columns(
            has_citation=pl.col("citation").fill_null("").str.len_chars() > 0,
            total_tokens=pl.col("input_tokens") + pl.col("output_tokens"),
        )

    return (score,)


@app.cell
async def _(runs, score):
    scored = await score(runs)
    return (scored,)


@app.cell
def _(pl):
    def summarize(frame: pl.DataFrame, by: str) -> pl.DataFrame:
        # The numbers the card asks for, one row per group.
        return (
            frame.group_by(by)
            .agg(
                answers=pl.len(),
                correct=pl.col("correct").mean(),
                checkable_source=pl.col("checkable").mean(),
                link_from_tools=pl.col("url_from_tools").mean(),
                correct_and_checkable=(pl.col("correct") & pl.col("checkable")).mean(),
                errors=pl.col("error").is_not_null().sum(),
                median_tokens=pl.col("total_tokens").median(),
                p90_tokens=pl.col("total_tokens").quantile(0.9, "nearest"),
                median_tool_calls=pl.col("tool_calls").median(),
                p90_tool_calls=pl.col("tool_calls").quantile(0.9, "nearest"),
                median_seconds=pl.col("seconds").median(),
                p90_seconds=pl.col("seconds").quantile(0.9, "nearest"),
                usd_per_answer=pl.col("cost_usd").mean(),
                usd_per_correct=pl.col("cost_usd").sum() / pl.col("correct").sum(),
                usd_per_correct_checkable=pl.col("cost_usd").sum()
                / (pl.col("correct") & pl.col("checkable")).sum(),
                total_usd=pl.col("cost_usd").sum(),
            )
            .sort(by)
        )

    return (summarize,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. Cost per correct answer, by server
    """)
    return


@app.cell
def _(OUT, scored, summarize):
    scored.write_csv(OUT / "scored.csv")
    by_server = summarize(scored, "server")
    by_server
    return (by_server,)


@app.cell
def _(mo):
    mo.md(r"""
    ### Where the tokens go

    The first request of a run holds only the instructions, the tool definitions and the
    question, so its input tokens are the fixed price of one step on that server. Every later
    step resends that, plus everything the tools have returned so far. So two things drive
    tokens: the fixed price times the number of steps, and how much data the tools return.
    `fixed_share` is the fixed price times the steps, as a share of all input tokens.
    """)
    return


@app.cell
def _(OUT, ModelMessagesTypeAdapter, pl, scored):
    def first_request_tokens(name: str) -> int:
        messages = ModelMessagesTypeAdapter.validate_json((OUT / "transcripts" / name).read_bytes())
        return next(m.usage.input_tokens for m in messages if m.kind == "response")

    with_fixed = scored.filter(pl.col("requests") > 0).with_columns(
        first_request_tokens=pl.col("transcript").map_elements(first_request_tokens, pl.Int64)
    )
    drivers = (
        with_fixed.group_by("server")
        .agg(
            fixed_tokens_per_step=pl.col("first_request_tokens").median(),
            median_steps=pl.col("requests").median(),
            median_tool_result_chars=pl.col("tool_result_chars").median(),
            fixed_share=(pl.col("first_request_tokens") * pl.col("requests")).sum()
            / pl.col("input_tokens").sum(),
        )
        .sort("server")
    )
    drivers
    return drivers, first_request_tokens


@app.cell
def _(mo):
    mo.md(r"""
    ### Which tool calls return the most

    Characters each tool sent back to the model, summed over all runs on a server. A large
    result is paid for again on every later step of that run.
    """)
    return


@app.cell
def _(OUT, ModelMessagesTypeAdapter, ModelRequest, ToolReturnPart, pl, scored):
    _rows = []
    for _r in scored.filter(pl.col("requests") > 0).iter_rows(named=True):
        _msgs = ModelMessagesTypeAdapter.validate_json(
            (OUT / "transcripts" / _r["transcript"]).read_bytes()
        )
        for _m in _msgs:
            if isinstance(_m, ModelRequest):
                _rows += [
                    {
                        "server": _r["server"],
                        "tool": p.tool_name,
                        "chars": len(p.model_response_str()),
                    }
                    for p in _m.parts
                    if isinstance(p, ToolReturnPart)
                ]
    tool_returns = (
        pl.DataFrame(_rows)
        .group_by("server", "tool")
        .agg(
            calls=pl.len(), median_chars=pl.col("chars").median(), total_chars=pl.col("chars").sum()
        )
        .sort("server", "total_chars", descending=[False, True])
    )
    tool_returns
    return (tool_returns,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. One design change on HIFLD Next

    HIFLD Next's MCP server ships map-widget tools for clients that can show an
    [MCP Apps](https://modelcontextprotocol.io/docs/extensions/apps) map. Their definitions are
    long, and a client sends them to the model on every step whether or not it can draw a map.
    The change: list those tools only to clients that render MCP Apps UI. A client declares that
    when it connects, so the server can do this itself; here we do it on our side, by dropping
    every tool the server marks with a UI resource, and leave the production server alone.
    Everything else is the same: same questions, model and instructions.
    """)
    return


@app.cell
async def _(
    BUDGET_USD,
    MCPToolset,
    OUT,
    REPEATS,
    RESCORE,
    SERVERS,
    ask,
    asyncio,
    make_agent,
    pl,
    questions,
    spend,
):
    def renders_no_ui(_ctx: object, tool) -> bool:
        return "ui" not in ((tool.metadata or {}).get("meta") or {})

    if RESCORE:
        changed_runs = pl.read_ndjson(OUT / "runs_no_map_tools.jsonl")
    else:
        _toolset = MCPToolset(
            SERVERS["HIFLD Next"]["url"], max_retries=3, include_instructions=True
        ).filtered(renders_no_ui)
        _agent = make_agent(_toolset)
        _gate = asyncio.Semaphore(4)
        _qs = list(questions.filter(pl.col("server") == "HIFLD Next").iter_rows(named=True))
        _rows = []
        async with _agent:
            for _repeat in range(1, REPEATS + 1):
                _rows += await asyncio.gather(
                    *(
                        ask(_agent, "no-map-tools", _repeat, _q, _gate, spend, BUDGET_USD)
                        for _q in _qs
                    )
                )
        changed_runs = pl.DataFrame(_rows, infer_schema_length=None)
        changed_runs.write_ndjson(OUT / "runs_no_map_tools.jsonl")
    print(f"{changed_runs.height} runs, ${spend['usd']:.4f} spent so far")
    return (changed_runs,)


@app.cell
async def _(changed_runs, first_request_tokens, pl, score, scored, summarize):
    changed = await score(changed_runs)
    _both = pl.concat(
        [scored.filter(pl.col("server") == "HIFLD Next"), changed], how="diagonal_relaxed"
    )
    before_after = summarize(_both, "variant").join(
        _both.filter(pl.col("requests") > 0)
        .with_columns(first=pl.col("transcript").map_elements(first_request_tokens, pl.Int64))
        .group_by("variant")
        .agg(fixed_tokens_per_step=pl.col("first").median()),
        on="variant",
    )
    before_after
    return before_after, changed


@app.cell
def _(OUT, before_after, by_server, drivers, json, mo, shipped, spend):
    _cpc = dict(zip(by_server["server"], by_server["usd_per_correct"], strict=True))
    spread = max(_cpc.values()) / min(_cpc.values())
    _ba = {r["variant"]: r for r in before_after.iter_rows(named=True)}
    summary = {
        "by_server": by_server.to_dicts(),
        "drivers": drivers.to_dicts(),
        "shipped_tools": shipped.to_dicts(),
        "hifld_before_after": before_after.to_dicts(),
        "cost_per_correct_spread": spread,
        "model_spend_this_run_usd": spend["usd"],
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1, default=str))
    _saving = 1 - _ba["no-map-tools"]["usd_per_answer"] / _ba["shipped"]["usd_per_answer"]
    _changed_cpc = _cpc | {"HIFLD Next": _ba["no-map-tools"]["usd_per_correct"]}
    _link = dict(zip(by_server["server"], by_server["link_from_tools"], strict=True))
    _fixed = dict(zip(drivers["server"], drivers["fixed_share"], strict=True))
    mo.md(
        f"""
    ## 8. Does it hold?

    **On cost, it fails.** Cost per correct answer runs from
    **{min(_cpc.values()) * 100:.2f}¢** to **{max(_cpc.values()) * 100:.2f}¢**, a **{spread:.1f}x**
    spread, not an order of magnitude. All three servers answer for about a cent.

    **On what drives the cost, it holds.** The most expensive server is not the one with the
    most data or the biggest results. HIFLD Next costs most because of what it sends before any
    data: its tool definitions are {_fixed["HIFLD Next"]:.0%} of its input tokens. Dropping
    the map tools from its list cut its cost per answer by **{_saving:.0%}** (fixed
    tokens per step {_ba["shipped"]["fixed_tokens_per_step"]:,.0f} →
    {_ba["no-map-tools"]["fixed_tokens_per_step"]:,.0f}) with no loss of accuracy
    ({_ba["shipped"]["correct"]:.0%} → {_ba["no-map-tools"]["correct"]:.0%} correct), and the
    spread falls to {max(_changed_cpc.values()) / min(_changed_cpc.values()):.1f}x.

    **The difference that is large is the citation.** Urban's results carry a link in every
    result and {_link["Urban EDP"]:.0%} of its answers pass one on; HIFLD Next's carry file
    URLs and {_link["HIFLD Next"]:.0%} do. MoSPI's results carry no link, so
    {_link["MoSPI"]:.0%} of its answers cite one taken from a tool result. Its answers were
    right, but a reader has no link to check them by.
    """
    )
    return spread, summary


@app.cell
def _(mo):
    mo.md(r"""
    ## 9. What this doesn't show

    - **The questions were easy for this model.** Almost every answer was right, so cost per
      correct answer is nearly cost per answer. Harder questions (the judgment calls Urban's
      own study found agents get wrong) would separate the servers on accuracy, which this set
      can't.
    - **Questions differ by server**, because the data does. A MoSPI question needs a dataset,
      an indicator and filter codes; an HIFLD question often needs SQL over a file. We pinned
      every question to one answer, but not to equal difficulty.
    - **One client and one model.** Pydantic AI sends every listed tool on every step and the
      server's instructions verbatim. A client that defers tool definitions until needed would
      erase most of HIFLD Next's fixed cost, and another model may take more or fewer steps.
    - **Prices date.** Haiku 5.5 costs $0.10 per million input tokens on OpenRouter; tokens and
      steps are the numbers that will hold up.
    - **The link check is mechanical.** MoSPI's API host refuses modern TLS clients (it
      needs legacy renegotiation), so links an agent built to it fail our check even when they
      may open in some browsers. `link_from_tools` doesn't depend on that: it asks only whether
      the link came from a tool result.
    - **We built HIFLD Next**, so read its numbers knowing that. Its server costs most of the
      three as shipped.
    """)
    return


if __name__ == "__main__":
    app.run()

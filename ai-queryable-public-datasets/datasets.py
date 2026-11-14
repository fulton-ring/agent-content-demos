import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import asyncio
    import json
    import os
    import re
    import threading
    import time

    import duckdb
    import httpx
    import marimo as mo
    import polars as pl
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent, capture_run_messages
    from pydantic_ai.mcp import MCPToolset
    from pydantic_ai.messages import (
        ModelMessagesTypeAdapter,
        ModelRequest,
        ModelResponse,
        ToolCallPart,
        ToolReturnPart,
    )
    from pydantic_ai.usage import UsageLimits

    return (
        Agent,
        BaseModel,
        Field,
        MCPToolset,
        ModelMessagesTypeAdapter,
        ModelRequest,
        ModelResponse,
        ToolCallPart,
        ToolReturnPart,
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
        threading,
        time,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Which free public datasets can an AI agent or a notebook query in place today?

    Ask an AI assistant for "AI-ready" public data and you get a mix of machine-learning
    training sets, government portals and listicles that rarely say what format anything is in.
    We expect the honest answer to be a short list: a handful of datasets published as Parquet
    or GeoParquet over plain HTTP, or behind a stable open API, that an agent can query without
    a download-and-clean step.

    We froze a list of 12 well-known free datasets before testing (committed in
    `datasets.csv` before any agent ran) and gave each the same three tests:

    1. **DuckDB one-liner.** Can one SQL statement in DuckDB, with only its core extensions
       (httpfs, spatial, excel, json), answer a real question from the data where it is
       published, with no download step? Pass means it returns the known answer.
    2. **Schema and vintage documented where an agent can read them.** Is there a description
       of the columns, and a stated date or edition of the data, that a plain HTTP request can
       read as text (JSON, Markdown, CSV, HTML with the text in it, or a spreadsheet DuckDB can
       open)? A PDF, a page that only renders in a browser, or a page that refuses our request
       fails.
    3. **Agent.** Can an agent with one generic tool (DuckDB SQL, which can also fetch any URL
       as text) start from the dataset's home page and answer the same question correctly?

    The hypothesis is **wrong** if most datasets pass all three tests, or if almost none do.
    """)
    return


@app.cell
def _(mo, os):
    MODEL = os.environ.get("AGENT_MODEL", "anthropic/claude-haiku-5.5")
    REPEATS = int(os.environ.get("AGENT_REPEATS", "3"))
    BUDGET_USD = float(os.environ.get("AGENT_BUDGET_USD", "4.0"))
    # RESCORE=1 scores the committed agent runs in outputs/ without calling any model.
    RESCORE = os.environ.get("RESCORE", "") == "1"
    HERE = mo.notebook_dir()
    OUT = HERE / "outputs"
    (OUT / "transcripts").mkdir(parents=True, exist_ok=True)
    return BUDGET_USD, HERE, MODEL, OUT, REPEATS, RESCORE


@app.cell
def _(mo):
    mo.md(r"""
    ## The datasets

    Two are ours (HIFLD Next and the Future Risk Index files we preserved), four come from the
    proposal card, and six are what AI assistants named when we asked them the customer's
    question: ChatGPT named World Bank indicators and NYC taxi trips, Perplexity named COCO,
    and the 2026-11-01 answers named Hugging Face Parquet, Portolan NL on Source Cooperative
    and Google's Data Commons MCP server. For Hugging Face we took the most-downloaded mirror of
    US public data we found on the Hub (a USGS earthquake catalog).

    Each row has one question, its known answer, and `how_found`: how we got that answer by a
    different route from the one being tested, so anyone can check the key.
    """)
    return


@app.cell
def _(HERE, pl):
    datasets = pl.read_csv(HERE / "datasets.csv", infer_schema_length=0)
    assert datasets["id"].n_unique() == datasets.height, "dataset IDs must be unique"
    assert set(datasets["kind"].unique()) <= {"number", "text"}
    datasets.select("dataset", "picked_by", "format", "question", "answer")
    return (datasets,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Test 1: one DuckDB statement against the data where it lives

    Each statement runs in a fresh DuckDB connection. The time includes fetching whatever
    DuckDB needs over the network. A result counts as right under the same rule as the agent
    test below: the number within the row's tolerance, or the name contained in the result.

    Public S3 buckets (Overture) need anonymous access, so `run.sh` clears any AWS
    credentials in the environment first; DuckDB otherwise sends them and S3 refuses.
    """)
    return


@app.cell
def _(re):
    def is_right(kind: str, answer: str, tolerance: str, text: str) -> bool:
        # A number is right if any number in the text is within tolerance of the key;
        # a name is right if the text contains it.
        if kind == "text":
            return answer.lower() in text.lower()
        key = float(answer)
        allowed = abs(key) * float(tolerance or 0)
        numbers = re.findall(r"-?\d[\d,]*\.?\d*", text)
        return any(abs(float(n.replace(",", "")) - key) <= allowed for n in numbers)

    return (is_right,)


@app.cell
def _(duckdb, threading):
    def connect() -> duckdb.DuckDBPyConnection:
        con = duckdb.connect()
        con.execute("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
        con.execute("INSTALL excel; LOAD excel; SET s3_region = 'us-west-2';")
        return con

    def run_sql_text(con: duckdb.DuckDBPyConnection, sql: str, timeout_s: float) -> str:
        # DuckDB has no query timeout, so a timer interrupts it. Errors come back as text:
        # for the agent an error is information, and for test 1 it is the failure reason.
        timer = threading.Timer(timeout_s, con.interrupt)
        timer.start()
        try:
            rel = con.sql(sql)
            if rel is None:
                return "OK (no result set)"
            return str(rel.limit(50))
        except Exception as exc:  # noqa: BLE001
            return f"ERROR {type(exc).__name__}: {str(exc)[:600]}"
        finally:
            timer.cancel()

    return connect, run_sql_text


@app.cell
def _(OUT, connect, datasets, is_right, pl, run_sql_text, time):
    _rows = []
    for _d in datasets.iter_rows(named=True):
        _con = connect()
        _start = time.monotonic()
        _out = run_sql_text(_con, _d["one_liner"], timeout_s=600)
        _seconds = time.monotonic() - _start
        _con.close()
        _ok = not _out.startswith("ERROR") and is_right(
            _d["kind"], _d["answer"], _d["tolerance"], _out
        )
        _rows.append(
            {
                "id": _d["id"],
                "duckdb_pass": _ok,
                "duckdb_seconds": round(_seconds, 1),
                "duckdb_output": _out if _out.startswith("ERROR") else _out[-300:],
            }
        )
    one_liners = pl.DataFrame(_rows)
    one_liners.write_csv(OUT / "one_liners.csv")
    one_liners.select("id", "duckdb_pass", "duckdb_seconds")
    return (one_liners,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Test 2: is the schema and the vintage readable over plain HTTP?

    For each dataset we name where its column descriptions and its date or edition are
    published (`schema_url`, `vintage_url`) and a string that must appear there
    (`*_evidence`). The notebook fetches each with a plain HTTP GET, the way an agent's fetch
    tool would, and checks the status, the content type and the string. A blank URL means we
    found no such statement; `doc_note` says what we found instead.
    """)
    return


@app.cell
def _(OUT, datasets, httpx, pl):
    _readable = ("json", "text", "markdown", "html", "csv", "xml", "spreadsheet", "octet-stream")

    def _check(client: httpx.Client, url: str, evidence: str) -> str:
        if not url:
            return "no statement found"
        resp = client.get(url)
        ctype = resp.headers.get("content-type", "")
        if resp.status_code != 200:
            return f"HTTP {resp.status_code}"
        # No content type at all (NOAA's README) is fine if the text is there.
        if ctype and not any(t in ctype for t in _readable):
            return f"not text: {ctype.split(';')[0]}"
        if evidence and evidence not in resp.text:
            return f"'{evidence}' not in the {len(resp.text):,} characters returned"
        return "ok"

    _rows = []
    with httpx.Client(follow_redirects=True, timeout=60) as _client:
        for _d in datasets.iter_rows(named=True):
            _schema = _check(_client, _d["schema_url"], _d["schema_evidence"])
            _vintage = _check(_client, _d["vintage_url"], _d["vintage_evidence"])
            _rows.append(
                {
                    "id": _d["id"],
                    "schema": _schema,
                    "vintage": _vintage,
                    "docs_pass": _schema == "ok" and _vintage == "ok",
                }
            )
    docs = pl.DataFrame(_rows)
    docs.write_csv(OUT / "docs_check.csv")
    docs
    return (docs,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Test 3: one agent, one generic tool

    A [Pydantic AI](https://ai.pydantic.dev) agent gets the dataset's name, the page a person
    would hand it (the publisher's home page for the dataset) and the question. Its only tool
    runs DuckDB SQL with the same extensions as test 1, so it can query remote files by URL and
    read any web page or document with `read_text`. It must return a typed answer: the value,
    the SQL that produced it and the URL of the data.

    An answer counts as **right** only if it matches the key *and* the matching value appears
    in something the tool returned, so an answer recalled from the model's memory doesn't
    count. The model is Claude Haiku 5.5 on OpenRouter, which reports each request's dollar
    cost. Each question runs three times; a run stops at 30 model requests or 15 minutes, and
    a single query at 6 minutes.

    Data Commons is reached through its hosted MCP server instead, as the card asks. It needs
    a `DC_API_KEY`; without one we record what the server says.
    """)
    return


@app.cell
def _(Agent, BaseModel, Field, MODEL, connect, run_sql_text):
    class Answer(BaseModel):
        found: bool = Field(description="True only if the answer came from data you queried.")
        answer: str = Field(description="The answer in one short sentence, with the value.")
        value: str = Field(description="Just the number or name that answers the question.")
        sql: str = Field(description="The SQL statement whose result gave the answer.")
        data_url: str = Field(description="URL of the file or endpoint the answer came from.")
        blocker: str = Field(description="If not found, what stopped you; else empty.")

    INSTRUCTIONS = (
        "You answer questions about public datasets using one tool, run_sql, which runs DuckDB "
        "SQL. The httpfs, json, spatial and excel extensions are loaded, so you can query "
        "remote Parquet, CSV, JSON and XLSX files by URL (https://, s3://, hf://), and read any "
        "web page or document as text with: SELECT content FROM read_text('<url>'). "
        "Start from the page you are given, find the data, and query it. Look the answer up; "
        "never answer from memory. If you can't get the answer from the data, set found to "
        "false and say what blocked you."
    )

    def make_sql_agent() -> Agent:
        con = connect()
        agent = Agent(
            f"openrouter:{MODEL}",
            output_type=Answer,
            instructions=INSTRUCTIONS,
            model_settings={"openrouter_usage": {"include": True}},
        )

        @agent.tool_plain
        def run_sql(sql: str) -> str:
            """Run one DuckDB SQL statement and return up to 50 rows as text."""
            return run_sql_text(con, sql, timeout_s=360)[:8000]

        return agent

    return Answer, INSTRUCTIONS, make_sql_agent


@app.cell
def _(
    Agent,
    Answer,
    INSTRUCTIONS,
    MCPToolset,
    MODEL,
    ModelMessagesTypeAdapter,
    ModelResponse,
    OUT,
    UsageLimits,
    asyncio,
    capture_run_messages,
    make_sql_agent,
    os,
    time,
):
    def make_mcp_agent() -> Agent | None:
        key = os.environ.get("DC_API_KEY", "")
        if not key:
            return None
        server = MCPToolset("https://api.datacommons.org/mcp", headers={"X-API-Key": key})
        return Agent(
            f"openrouter:{MODEL}",
            toolsets=[server],
            output_type=Answer,
            instructions=INSTRUCTIONS.replace(
                "one tool, run_sql, which runs DuckDB SQL", "the Data Commons MCP tools"
            ),
            model_settings={"openrouter_usage": {"include": True}},
        )

    async def ask(d: dict, repeat: int, gate: asyncio.Semaphore, spend: dict, budget: float):
        row = {"id": d["id"], "repeat": repeat}
        async with gate:
            if spend["usd"] >= budget:
                return row | {"error": "skipped: budget reached"}
            agent = make_mcp_agent() if d["id"] == "data_commons_mcp" else make_sql_agent()
            if agent is None:
                return row | {"error": "no DC_API_KEY: Data Commons answers 401 without one"}
            prompt = (
                f"Dataset: {d['dataset']}\nStart here: {d['landing_url']}\n"
                f"Question: {d['question']}"
            )
            start = time.monotonic()
            error = None
            with capture_run_messages() as messages:
                try:
                    result = await asyncio.wait_for(
                        agent.run(prompt, usage_limits=UsageLimits(request_limit=30)),
                        timeout=900,
                    )
                except Exception as exc:  # noqa: BLE001  a failed run is a measured outcome
                    error = f"{type(exc).__name__}: {exc}"[:400]
                    result = None
            seconds = time.monotonic() - start
            final = result.all_messages() if result else messages
            path = OUT / "transcripts" / f"{d['id']}-{repeat}.json"
            path.write_bytes(ModelMessagesTypeAdapter.dump_json(final, indent=1))
            responses = [m for m in final if isinstance(m, ModelResponse)]
            # OpenRouter reports each response's cost, so a failed run is still priced.
            cost = sum((m.provider_details or {}).get("cost", 0) for m in responses)
            spend["usd"] += cost
            row |= {
                "seconds": round(seconds, 1),
                "cost_usd": cost,
                "requests": len(responses),
                "tool_calls": sum(len(m.tool_calls) for m in responses),
                "transcript": path.name,
                "error": error,
            }
            return row if result is None else row | result.output.model_dump()

    return (ask,)


@app.cell
async def _(
    BUDGET_USD,
    OUT,
    REPEATS,
    RESCORE,
    ask,
    asyncio,
    datasets,
    httpx,
    json,
):
    _runs_path = OUT / "agent_runs.jsonl"
    if not RESCORE:
        # Record what the Data Commons MCP server says to a client without a key.
        _probe = httpx.post(
            "https://api.datacommons.org/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={"Accept": "application/json, text/event-stream"},
        )
        (OUT / "data_commons_no_key.txt").write_text(f"HTTP {_probe.status_code}\n{_probe.text}")
        _gate = asyncio.Semaphore(4)
        _spend = {"usd": 0.0}
        _runs = await asyncio.gather(
            *[
                ask(_d, _r, _gate, _spend, BUDGET_USD)
                for _d in datasets.iter_rows(named=True)
                for _r in range(REPEATS)
            ]
        )
        _runs_path.write_text("".join(json.dumps(_x) + "\n" for _x in _runs))
    agent_runs = [json.loads(_line) for _line in _runs_path.read_text().splitlines()]
    print(f"{len(agent_runs)} agent runs ({'rescored from file' if RESCORE else 'new'})")
    return (agent_runs,)


@app.cell
def _(mo):
    mo.md(r"""
    ### Scoring the agent

    Read straight from the saved transcripts, so `RESCORE=1` gives the same numbers without a
    model call. A dataset passes the agent test if at least two of its three runs are right.
    """)
    return


@app.cell
def _(
    ModelMessagesTypeAdapter,
    ModelRequest,
    OUT,
    ToolReturnPart,
    agent_runs,
    datasets,
    is_right,
    pl,
):
    _key = {d["id"]: d for d in datasets.iter_rows(named=True)}

    def _tool_text(transcript: str | None) -> str:
        if not transcript:
            return ""
        messages = ModelMessagesTypeAdapter.validate_json(
            (OUT / "transcripts" / transcript).read_bytes()
        )
        return "\n".join(
            p.model_response_str()
            for m in messages
            if isinstance(m, ModelRequest)
            for p in m.parts
            if isinstance(p, ToolReturnPart)
        )

    _rows = []
    for _r in agent_runs:
        _d = _key[_r["id"]]
        _said = f"{_r.get('value') or ''} {_r.get('answer') or ''}"
        _matches = bool(_r.get("found")) and is_right(
            _d["kind"], _d["answer"], _d["tolerance"], _said
        )
        _grounded = _matches and is_right(
            _d["kind"], _d["answer"], _d["tolerance"], _tool_text(_r.get("transcript"))
        )
        _rows.append(
            {
                "id": _r["id"],
                "repeat": _r["repeat"],
                "right": _grounded,
                "matched_but_ungrounded": _matches and not _grounded,
                "seconds": _r.get("seconds"),
                "cost_usd": _r.get("cost_usd", 0.0),
                "tool_calls": _r.get("tool_calls", 0),
                "value": _r.get("value"),
                "blocker": _r.get("blocker") or _r.get("error") or "",
            }
        )
    scored = pl.DataFrame(_rows, infer_schema_length=None)
    agent_summary = scored.group_by("id").agg(
        agent_right=pl.col("right").sum(),
        agent_runs=pl.len(),
        agent_seconds=pl.col("seconds").median(),
        agent_cost_usd=pl.col("cost_usd").sum(),
        agent_values=pl.col("value").cast(pl.String).str.join(" | "),
    )
    scored.write_csv(OUT / "agent_scored.csv")
    scored.select("id", "repeat", "right", "value", "seconds", "cost_usd", "blocker")
    return agent_summary, scored


@app.cell
def _(mo):
    mo.md(r"""
    ## Results
    """)
    return


@app.cell
def _(OUT, agent_summary, datasets, docs, one_liners, pl):
    results = (
        datasets.select("id", "dataset", "picked_by", "format")
        .join(one_liners.select("id", "duckdb_pass", "duckdb_seconds"), on="id")
        .join(docs.select("id", "docs_pass"), on="id")
        .join(agent_summary, on="id", how="left")
        .with_columns(agent_pass=pl.col("agent_right").fill_null(0) >= 2)
        .with_columns(all_three=pl.col("duckdb_pass") & pl.col("docs_pass") & pl.col("agent_pass"))
    )
    results.write_csv(OUT / "results.csv")
    results.select(
        "dataset",
        "format",
        "duckdb_pass",
        "duckdb_seconds",
        "docs_pass",
        "agent_right",
        "agent_runs",
        "agent_seconds",
        "all_three",
    )
    return (results,)


@app.cell
def _(OUT, json, mo, results, scored):
    _assist = results.filter(results["picked_by"] == "assistant")
    _paid = scored.filter(scored["cost_usd"] > 0)
    summary = {
        "datasets": results.height,
        "duckdb_pass": int(results["duckdb_pass"].sum()),
        "docs_pass": int(results["docs_pass"].sum()),
        "agent_pass": int(results["agent_pass"].sum()),
        "all_three": int(results["all_three"].sum()),
        "assistant_named": _assist.height,
        "assistant_named_all_three": int(_assist["all_three"].sum()),
        "agent_runs_paid": _paid.height,
        "agent_runs_right": int(scored["right"].sum()),
        "agent_runs_matched_but_ungrounded": int(scored["matched_but_ungrounded"].sum()),
        "total_cost_usd": round(float(scored["cost_usd"].sum()), 4),
        "cost_per_question_usd": round(float(_paid["cost_usd"].mean() or 0), 4),
        "passed_all_three": results.filter(results["all_three"])["dataset"].to_list(),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=1))
    mo.md(f"""
    **{summary["all_three"]} of {summary["datasets"]}** datasets pass all three tests:
    {", ".join(summary["passed_all_three"])}.

    - DuckDB one-liner: {summary["duckdb_pass"]} of {summary["datasets"]} pass.
    - Schema and vintage readable over HTTP: {summary["docs_pass"]} of {summary["datasets"]}.
    - Agent right in at least two of three runs: {summary["agent_pass"]} of
      {summary["datasets"]}.
    - Of the {summary["assistant_named"]} datasets AI assistants recommended,
      **{summary["assistant_named_all_three"]}** pass all three.
    - Model cost: **${summary["total_cost_usd"]:.2f}** for {summary["agent_runs_paid"]} agent
      runs, **${summary["cost_per_question_usd"]:.3f}** per run on average.
      {summary["agent_runs_matched_but_ungrounded"]} runs gave the right value without it
      appearing in any tool result, and were scored wrong.
    """)
    return (summary,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Why each failure failed

    Every failed test, with the reason the test itself recorded: the DuckDB error, the
    documentation check's finding, or what the agent said blocked it (or the wrong value it
    gave).
    """)
    return


@app.cell
def _(docs, one_liners, pl, results, scored):
    _fails = []
    for _r in one_liners.filter(~pl.col("duckdb_pass")).iter_rows(named=True):
        _fails.append({"id": _r["id"], "test": "duckdb", "why": _r["duckdb_output"][:300]})
    for _r in docs.filter(~pl.col("docs_pass")).iter_rows(named=True):
        _fails.append(
            {
                "id": _r["id"],
                "test": "docs",
                "why": f"schema: {_r['schema']}; vintage: {_r['vintage']}",
            }
        )
    for _id in results.filter(~pl.col("agent_pass"))["id"]:
        _runs = scored.filter(pl.col("id") == _id)
        _why = " | ".join(
            f"run {r['repeat']}: {r['value'] or '-'}; {r['blocker'][:160]}"
            for r in _runs.iter_rows(named=True)
        )
        _fails.append({"id": _id, "test": "agent", "why": _why})
    failures = pl.DataFrame(_fails).sort("id", "test")
    failures
    return (failures,)


@app.cell
def _(OUT, failures):
    failures.write_csv(OUT / "failures.csv")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What this doesn't show

    - **One question per dataset.** A pass means the path works for a plain counting or
      ranking question, not that every question is answerable.
    - **One runner.** We ran from a cloud container. nyc.gov and fema.gov's web pages refuse
      it (HTTP 403 from their edge network), which may not happen from a laptop; the TLC and
      OpenFEMA data files themselves load fine. Our runner also can't reach github.com pages,
      so the Future Risk Index agent starts from the raw README instead.
    - **Free keys count as a failure here.** The Census API (since 2026) and Data Commons
      need a free key from a sign-up form. An agent can't get one by itself, which is the
      point of the test, but a person who registers once gets through. Set `CENSUS_API_KEY`
      or `DC_API_KEY` to see how far each gets with a key (the Census one-liner would need it
      appended to the URL).
    - **Our test, our judgment.** The schema and vintage URLs and evidence strings are our
      reading of each publisher's docs; `doc_note` in `datasets.csv` says what we found.
    - **One model.** A stronger model may get further from a poor landing page; a weaker one
      less far.
    - **We built HIFLD Next and preserved the Future Risk Index files**, so read their rows
      knowing that.
    """)
    return


if __name__ == "__main__":
    app.run()

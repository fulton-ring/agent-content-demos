import marimo

__generated_with = "0.17.0"
app = marimo.App(width="medium")


@app.cell
def _():
    import asyncio
    import json
    import os
    import shutil
    import subprocess
    import time
    from dataclasses import dataclass, field
    from decimal import Decimal
    from pathlib import Path
    from typing import Any

    import marimo as mo
    import pandas as pd
    from pydantic import BaseModel, Field
    from pydantic_ai import Agent, RunContext, capture_run_messages
    from pydantic_ai.mcp import MCPToolset
    from pydantic_ai.messages import ModelMessagesTypeAdapter, ModelResponse
    from pydantic_ai.toolsets import FunctionToolset
    from pydantic_ai.usage import UsageLimits

    return (
        Agent,
        Any,
        BaseModel,
        Decimal,
        Field,
        FunctionToolset,
        MCPToolset,
        ModelMessagesTypeAdapter,
        ModelResponse,
        Path,
        RunContext,
        UsageLimits,
        asyncio,
        capture_run_messages,
        dataclass,
        field,
        json,
        mo,
        os,
        pd,
        shutil,
        subprocess,
        time,
    )


@app.cell
def _(mo):
    mo.md(r"""
    # Part 2: the agent answers the ten questions, three times each, on two models

    The agent is [Pydantic AI](https://ai.pydantic.dev) through OpenRouter, run on Claude Haiku 5.5 and
    GPT-6 Luna (the two cheap models the earlier HIFLD Next MCP spike used), with two
    sets of tools:

    - **HIFLD Next**, the public MCP server `org.publicenvirodata.hifld/dataset-mcp`, connected
      as it is. We leave out its six map-widget tools, which draw maps for a chat app and can't
      answer anything here.
    - **QGIS 3.34, headless**: QGIS's own command-line runner, `qgis_process`, exposed as tools to
      list, explain and run any Processing algorithm, plus two read-only PyQGIS tools to describe a
      layer and read its attributes. The open-source QGIS MCP servers we looked at either need the
      QGIS desktop app running a plugin or target QGIS 4, and the sandbox wouldn't install the
      one headless server that targets QGIS 3, so we wrapped `qgis_process` ourselves (the
      fallback the issue allows). The tool set copies the shape those servers share.

    FEMA's NFHL county extracts for the four counties sit unzipped on disk, and the agent is told
    where. Everything else it has to find.

    Running this costs money, so it's off by default: `run.sh` scores the transcripts saved in
    `runs/`. Set `RUN_AGENT=1` to run the agent again: 60 runs, two models, about $2 and an hour.
    """)
    return


@app.cell
def _(Path, json, os):
    HERE = Path(__file__).parent
    CACHE = Path(os.environ.get("HQAE_CACHE", Path.home() / ".cache" / "hifld-qgis-agent-errors"))
    RUNS = HERE / "runs"
    RUN_AGENT = os.environ.get("RUN_AGENT") == "1"
    MODELS = os.environ.get("AGENT_MODELS", "anthropic/claude-haiku-5.5,openai/gpt-6-luna").split(",")
    REPEATS = int(os.environ.get("AGENT_REPEATS", "3"))
    BUDGET_USD = float(os.environ.get("AGENT_BUDGET_USD", "4.5"))
    QGIS_PYTHON = os.environ.get("QGIS_PYTHON", "/usr/bin/python3.12")
    MCP_URL = os.environ.get("HIFLD_MCP_URL", "https://hifld.publicenvirodata.org/mcp")
    QUESTIONS = json.loads((HERE / "questions.json").read_text())
    if os.environ.get("AGENT_QUESTIONS"):  # e.g. AGENT_QUESTIONS=Q1,Q5 for a trial run
        QUESTIONS = [q for q in QUESTIONS if q["id"] in os.environ["AGENT_QUESTIONS"].split(",")]
    NFHL = {
        "Harris County, TX": CACHE / "nfhl" / "48201C",
        "Orleans Parish, LA": CACHE / "nfhl" / "22071C",
        "Miami-Dade County, FL": CACHE / "nfhl" / "12086C",
        "Charleston County, SC": CACHE / "nfhl" / "45019C",
    }
    # Every tool result the model sees is cut to this many characters, so one huge result
    # (a full algorithm list, a dataset's whole metadata) can't blow the context or the budget.
    MAX_TOOL_CHARS = 12_000
    return (
        BUDGET_USD,
        CACHE,
        HERE,
        MAX_TOOL_CHARS,
        MCP_URL,
        MODELS,
        NFHL,
        QGIS_PYTHON,
        QUESTIONS,
        REPEATS,
        RUNS,
        RUN_AGENT,
    )


@app.cell
def _(Any, MAX_TOOL_CHARS, dataclass, field, json, time):
    @dataclass
    class RunLog:
        """What one run's tools did: every call, its arguments, how long it took and how big its result was."""

        workspace: str
        calls: list[dict[str, Any]] = field(default_factory=list)

        def record(self, server: str, name: str, args: Any, started: float, result: Any) -> str:
            text = result if isinstance(result, str) else json.dumps(result, default=str)
            self.calls.append(
                {
                    "server": server,
                    "tool": name,
                    "args": args,
                    "seconds": round(time.monotonic() - started, 2),
                    "result_chars": len(text),
                    "truncated": len(text) > MAX_TOOL_CHARS,
                }
            )
            if len(text) > MAX_TOOL_CHARS:
                return text[:MAX_TOOL_CHARS] + f"\n... [cut: {len(text):,} characters in all]"
            return text

    return (RunLog,)


@app.cell
def _(mo):
    mo.md(r"""
    ## The QGIS tools

    Five tools. `qgis_run_algorithm` is the one that does the work: it hands an algorithm ID and a
    parameter dictionary to `qgis_process run`, exactly as QGIS's command line takes them, and
    returns QGIS's JSON results. Each call is a fresh QGIS process, so layers live in files, not in
    a project.
    """)
    return


@app.cell
def _(Any, FunctionToolset, HERE, QGIS_PYTHON, RunContext, RunLog, json, os, subprocess, time):
    QGIS_ENV = {"QT_QPA_PLATFORM": "offscreen", "PATH": "/usr/bin:/bin", "HOME": "/tmp"}

    def run_qgis(args: list[str], stdin: str | None = None, timeout: int = 600) -> tuple[int, str, str]:
        try:
            proc = subprocess.run(
                args, input=stdin, capture_output=True, text=True, timeout=timeout, env=QGIS_ENV | proxy_env()
            )
        except subprocess.TimeoutExpired:
            return 124, "", f"timed out after {timeout} s"
        return proc.returncode, proc.stdout, proc.stderr

    def proxy_env() -> dict[str, str]:
        return {k: v for k, v in os.environ.items() if k.lower() in ("https_proxy", "http_proxy", "no_proxy")}

    qgis_tools = FunctionToolset[RunLog]()

    @qgis_tools.tool
    def qgis_list_algorithms(ctx: RunContext[RunLog], search: str) -> str:
        """List QGIS Processing algorithms whose ID or name contains `search` (case-insensitive), at most 60."""
        started = time.monotonic()
        code, out, err = run_qgis(["qgis_process", "--json", "list"])
        if code != 0:
            return ctx.deps.record(
                "qgis", "qgis_list_algorithms", {"search": search}, started, f"failed: {err[-1500:]}"
            )
        hits = [
            {"id": alg_id, "name": alg["name"]}
            for provider in json.loads(out)["providers"].values()
            for alg_id, alg in provider["algorithms"].items()
            if search.lower() in alg_id.lower() or search.lower() in alg["name"].lower()
        ]
        return ctx.deps.record(
            "qgis", "qgis_list_algorithms", {"search": search}, started, {"total": len(hits), "algorithms": hits[:60]}
        )

    @qgis_tools.tool
    def qgis_algorithm_help(ctx: RunContext[RunLog], algorithm_id: str) -> str:
        """Show a QGIS Processing algorithm's description, parameters and outputs (from `qgis_process help`)."""
        started = time.monotonic()
        code, out, err = run_qgis(["qgis_process", "help", algorithm_id])
        return ctx.deps.record(
            "qgis",
            "qgis_algorithm_help",
            {"algorithm_id": algorithm_id},
            started,
            out if code == 0 else f"failed: {err[-1500:]}",
        )

    @qgis_tools.tool
    def qgis_run_algorithm(ctx: RunContext[RunLog], algorithm_id: str, parameters: dict[str, Any]) -> str:
        """Run a QGIS Processing algorithm with `qgis_process run`.

        `parameters` maps the algorithm's parameter names to values: file paths for layers, numbers,
        enum indexes, and output file paths. Write outputs under your working directory. Returns
        QGIS's results JSON, or its error log.
        """
        started = time.monotonic()
        code, out, err = run_qgis(
            ["qgis_process", "--json", "run", algorithm_id, "-"],
            stdin=json.dumps({"inputs": parameters, "ellipsoid": "EPSG:7030"}),
        )
        args = {"algorithm_id": algorithm_id, "parameters": parameters}
        if code != 0:
            return ctx.deps.record(
                "qgis", "qgis_run_algorithm", args, started, f"failed (exit {code}):\n{err[-3000:]}\n{out[-2000:]}"
            )
        result = json.loads(out)
        return ctx.deps.record(
            "qgis",
            "qgis_run_algorithm",
            args,
            started,
            {"results": result.get("results"), "log": result.get("log", {}).get("msg", "")[-1500:]},
        )

    def pyqgis(request: dict[str, Any]) -> str:
        code, out, err = run_qgis([QGIS_PYTHON, str(HERE / "pyqgis_tool.py"), json.dumps(request)], timeout=300)
        return out if code == 0 else f"failed: {err[-1500:]}"

    @qgis_tools.tool
    def qgis_layer_info(ctx: RunContext[RunLog], path: str) -> str:
        """Describe a vector file with PyQGIS: CRS, geometry type, feature count, extent and fields."""
        started = time.monotonic()
        return ctx.deps.record(
            "qgis", "qgis_layer_info", {"path": path}, started, pyqgis({"command": "layer_info", "path": path})
        )

    @qgis_tools.tool
    def qgis_get_features(
        ctx: RunContext[RunLog], path: str, expression: str = "", fields: list[str] | None = None, limit: int = 20
    ) -> str:
        """Read attributes (no geometry) of features in a vector file that match a QGIS expression.

        Returns how many features match and up to `limit` of them (at most 50).
        """
        started = time.monotonic()
        request = {
            "command": "features",
            "path": path,
            "expression": expression,
            "fields": fields or [],
            "limit": limit,
        }
        return ctx.deps.record("qgis", "qgis_get_features", request, started, pyqgis(request))

    return (qgis_tools,)


@app.cell
def _(Any, MCPToolset, MCP_URL, RunLog, time):
    # The map widgets render maps in a chat app; they can't answer a question, so the agent doesn't get them.
    MAP_TOOLS = {
        "view_map",
        "view_query_map",
        "refresh_query_map",
        "prepare_map_layer",
        "refresh_map",
        "generate_mvt_tile_url",
    }

    async def log_mcp_call(ctx: Any, call_tool: Any, name: str, args: dict[str, Any]) -> Any:
        started = time.monotonic()
        try:
            result = await call_tool(name, args)
        except Exception as exc:  # the model sees the error, and so does the log
            ctx.deps.record("hifld", name, args, started, f"error: {exc}")
            raise
        return ctx.deps.record("hifld", name, args, started, result)

    def hifld_toolset() -> Any:
        return MCPToolset(MCP_URL, max_retries=3, process_tool_call=log_mcp_call).filtered(
            lambda _ctx, tool: tool.name not in MAP_TOOLS
        )

    return (hifld_toolset,)


@app.cell
def _(BaseModel, Field, NFHL):
    from typing import Literal

    class Answer(BaseModel):
        status: Literal["answered", "unavailable", "unsure"] = Field(
            description=(
                "answered: you computed the answer; unavailable: the data needed isn't available; "
                "unsure: you couldn't finish"
            )
        )
        count: int | None = Field(None, description="The answer, if it is a count")
        value: float | None = Field(
            None, description="The answer, if it is a number other than a count (a length, a total, a percentage)"
        )
        unit: str | None = Field(None, description="Unit of `value`, such as km, beds or %")
        names: list[str] = Field(
            default_factory=list, description="The answer, if it is a list of names, spelled as in the data"
        )
        datasets_used: list[str] = Field(default_factory=list, description="The datasets and files you used")
        method: str = Field(description="Two or three sentences on how you got the answer")

    _nfhl = "\n".join(f"- {name}: {path}" for name, path in NFHL.items())
    INSTRUCTIONS = f"""You answer questions about US infrastructure and flood hazard with two sets of tools:
    - HIFLD Next, a public catalog of infrastructure datasets that you can search, inspect, and query with SQL.
    - QGIS 3.34, headless: run any QGIS Processing algorithm on files, describe a layer, read its attributes.

    FEMA's National Flood Hazard Layer (NFHL) county extracts are on disk, unzipped, as FEMA publishes them:
    {_nfhl}

    QGIS works on local files. To use a HIFLD Next file in QGIS, download it into your working directory with
    the QGIS algorithm native:filedownloader, using a file URL from get_dataset_file. Your working directory is
    given with each question; write all outputs there.

    Answer with what you computed from the data, not an estimate. If the data needed to answer isn't available,
    or you can't finish, say so in `status`."""
    return Answer, INSTRUCTIONS


@app.cell
def _(Agent, Answer, INSTRUCTIONS, RunLog, hifld_toolset, qgis_tools):
    def make_agent(model: str) -> Agent[RunLog, Answer]:
        return Agent(
            f"openrouter:{model}",
            deps_type=RunLog,
            toolsets=[hifld_toolset(), qgis_tools],
            output_type=Answer,
            instructions=INSTRUCTIONS,
            model_settings={"openrouter_usage": {"include": True}, "max_tokens": 8000},
            retries=3,
        )

    return (make_agent,)


@app.cell
def _(mo):
    mo.md(r"""
    ## The runs

    Each run gets a fresh, empty working directory, a 15-minute wall clock, at most 40 model
    requests and at most $0.25. The whole batch stops starting runs at `AGENT_BUDGET_USD` (default
    $4.50, under the issue's $5). Three run at a time. Every run, finished or failed, is saved to
    `runs/<model>/<question>_<repeat>.json` with the full message history and the tool log.
    """)
    return


@app.cell
async def _(
    Any,
    BUDGET_USD,
    MODELS,
    CACHE,
    Decimal,
    ModelMessagesTypeAdapter,
    ModelResponse,
    QUESTIONS,
    REPEATS,
    RUNS,
    RUN_AGENT,
    RunLog,
    UsageLimits,
    asyncio,
    capture_run_messages,
    json,
    make_agent,
    shutil,
    time,
):
    spend = {"usd": 0.0}

    async def run_one(agent, model: str, q: dict, repeat: int, gate: asyncio.Semaphore) -> None:
        out_file = RUNS / model.split("/")[-1] / f"{q['id']}_{repeat}.json"
        async with gate:
            if spend["usd"] >= BUDGET_USD:
                print(f"{q['id']} #{repeat}: skipped, budget reached")
                return
            workspace = CACHE / "workspace" / model.split("/")[-1] / f"{q['id']}_{repeat}"
            shutil.rmtree(workspace, ignore_errors=True)
            workspace.mkdir(parents=True)
            log = RunLog(workspace=str(workspace))
            prompt = f"{q['question']}\n\nYour working directory: {workspace}"
            record: dict[str, Any] = {
                "question_id": q["id"],
                "repeat": repeat,
                "model": model,
                "prompt": prompt,
            }
            started = time.monotonic()
            with capture_run_messages() as messages:
                try:
                    result = await asyncio.wait_for(
                        agent.run(
                            prompt,
                            deps=log,
                            usage_limits=UsageLimits(request_limit=40, cost_limit=Decimal("0.25")),
                        ),
                        timeout=900,
                    )
                    record |= {"output": result.output.model_dump(), "error": None}
                except Exception as exc:  # a failed run is a result to score, not a crash
                    record |= {"output": None, "error": f"{type(exc).__name__}: {exc}"[:1000]}
            responses = [m for m in messages if isinstance(m, ModelResponse)]
            cost = sum(float((m.provider_details or {}).get("cost", 0) or 0) for m in responses)
            spend["usd"] += cost
            record |= {
                "seconds": round(time.monotonic() - started, 1),
                "cost_usd": cost,
                "requests": len(responses),
                "input_tokens": sum(m.usage.input_tokens for m in responses),
                "output_tokens": sum(m.usage.output_tokens for m in responses),
                "tool_log": log.calls,
                "messages": json.loads(ModelMessagesTypeAdapter.dump_json(messages)),
            }
            out_file.write_text(json.dumps(record, indent=1, default=str))
            shutil.rmtree(workspace, ignore_errors=True)
            status = record["output"]["status"] if record["output"] else record["error"][:80]
            print(
                f"{model} {q['id']} #{repeat}: {status}, {record['seconds']} s, ${cost:.4f} (total ${spend['usd']:.2f})"
            )

    if RUN_AGENT:
        _gate = asyncio.Semaphore(3)
        for _model in MODELS:
            (RUNS / _model.split("/")[-1]).mkdir(parents=True, exist_ok=True)
            _agent = make_agent(_model)
            async with _agent:
                await asyncio.gather(
                    *(run_one(_agent, _model, q, r, _gate) for r in range(1, REPEATS + 1) for q in QUESTIONS)
                )
        print(f"OpenRouter spend this batch: ${spend['usd']:.2f}")
    return


@app.cell
def _(RUNS, json, mo, pd):
    _rows = []
    for _f in sorted(RUNS.glob("*/Q*_*.json")):
        _r = json.loads(_f.read_text())
        _o = _r["output"] or {}
        _rows.append(
            {
                "model": _f.parent.name,
                "run": _f.stem,
                "status": _o.get("status", "error"),
                "count": _o.get("count"),
                "value": _o.get("value"),
                "names": "; ".join(_o.get("names") or []),
                "tool calls": len(_r["tool_log"]),
                "seconds": _r["seconds"],
                "cost $": round(_r["cost_usd"], 4),
            }
        )
    mo.vstack([mo.md(f"## Saved runs: {len(_rows)}"), mo.ui.table(pd.DataFrame(_rows), selection=None, page_size=30)])
    return


if __name__ == "__main__":
    app.run()

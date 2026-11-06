import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import re
    import urllib.request
    from pathlib import Path

    import marimo as mo
    import pandas as pd

    here = Path(__file__).parent
    return Path, here, json, mo, pd, re, urllib


@app.cell
def _(mo):
    mo.md(r"""
    # Can an AI agent run a public nf-core pipeline on its own?

    We gave an agent (Claude Sonnet 5.5 through Pydantic AI, see `nfwatch.py`) a written brief
    (`brief.md`, committed before the run) and asked it to do what a PhD student would:
    install Nextflow, run **nf-core/rnaseq 3.27.0** on its own test profile, then run it once
    per sample across six samples, retry failures and report. One of the six samples, the
    "collaborator's" sample, is a public test FASTQ that we cut off halfway on purpose, the way a
    download that stopped early looks. The agent was not told.

    A person (the supervising worker session) approved any change to parameters and stepped in
    when needed. Everything the agent and the person did is in `log/events.jsonl`. This notebook
    reads that log and the checksums of every output file, and scores the run.
    """)
    return


@app.cell
def _(here, json, pd):
    events = pd.DataFrame(
        [json.loads(line) for line in (here / "log" / "events.jsonl").read_text().splitlines()]
    )
    events["ts"] = pd.to_datetime(events["ts"])
    events.groupby("kind").size().rename("events").to_frame()
    return (events,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 1. What the agent set up

    Every shell command the agent ran, in order, and the ones the harness refused. The agent's
    shell is limited to common file, download and inspection programs inside its workspace, and
    it can't start a pipeline except through the `launch_run` tool.
    """)
    return


@app.cell
def _(events):
    shell_log = events[events["kind"].isin(["shell", "shell_refused"])][
        ["ts", "kind", "command", "exit", "reason"]
    ]
    shell_log
    return (shell_log,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 2. The runs

    One row per attempt: when it started, how it ended and how long it took.
    """)
    return


@app.cell
def _(events, pd):
    launched = events[events["kind"] == "run_launched"][["ts", "run", "attempt", "resume"]]
    finished = events[events["kind"] == "run_finished"][["run", "attempt", "status", "minutes"]]
    attempts = launched.merge(finished, on=["run", "attempt"], how="left")
    runs = attempts.groupby("run").agg(
        attempts=("attempt", "max"),
        final_status=("status", "last"),
        minutes_total=("minutes", "sum"),
    )
    totals = pd.Series(
        {
            "runs": len(runs),
            "attempts": len(attempts),
            "retries": len(attempts) - len(runs),
            "runs finished": int((runs["final_status"] == "succeeded").sum()),
            "pipeline minutes": round(attempts["minutes"].sum(), 1),
        }
    )
    attempts, runs, totals
    return attempts, runs, totals


@app.cell
def _(mo):
    mo.md(r"""
    ## 3. Do the validation outputs match the pipeline's own answer key?

    nf-core/rnaseq ships nf-test snapshots. `tests/default.nf.test.snap` at the 3.27.0 tag
    records, for `-profile test`: the number of tasks that succeed, every output path, and md5
    checksums of the 143 output files whose content is stable from run to run. We download it
    and compare it with the validation run's outputs (`results/validation/outputs.tsv`, written by
    `nfwatch.py manifest` from the run's output folder) and trace.
    """)
    return


@app.cell
def _(json, urllib):
    snap_url = "https://raw.githubusercontent.com/nf-core/rnaseq/3.27.0/tests/default.nf.test.snap"
    with urllib.request.urlopen(snap_url, timeout=60) as resp:
        assert resp.status == 200
        snapshot = json.loads(resp.read())["Params: default"]["content"]
    expected_tasks, _versions, expected_paths, expected_md5 = snapshot
    expected_md5 = dict(item.rsplit(":md5,", 1) for item in expected_md5)
    len(expected_paths), len(expected_md5), expected_tasks
    return expected_md5, expected_paths, expected_tasks


@app.cell
def _(expected_md5, expected_paths, expected_tasks, here, pd):
    val_dir = here / "results" / "validation"
    outputs = pd.read_csv(val_dir / "outputs.tsv", sep="\t", dtype=str).fillna("")
    trace = pd.concat(pd.read_csv(t, sep="\t") for t in sorted(val_dir.glob("trace_*.txt")))
    succeeded_tasks = int(trace["status"].isin(["COMPLETED", "CACHED"]).sum())

    stable = [p for p in expected_paths if not p.startswith("pipeline_info/")]
    got_paths = set(outputs["path"])
    missing_paths = sorted(set(stable) - got_paths)

    by_name = outputs.assign(name=outputs["path"].str.rsplit("/", n=1).str[-1])
    md5_rows = []
    for name, want in expected_md5.items():
        got = set(by_name.loc[by_name["name"] == name, "md5"])
        md5_rows.append({"file": name, "match": want in got, "found": bool(got)})
    md5_check = pd.DataFrame(md5_rows)
    answer_key = pd.Series(
        {
            "tasks succeeded (expected)": expected_tasks,
            "tasks succeeded (run)": succeeded_tasks,
            "expected output paths": len(stable),
            "expected paths missing": len(missing_paths),
            "stable files checked": len(md5_check),
            "md5 matches": int(md5_check["match"].sum()),
            "md5 mismatches": int((md5_check["found"] & ~md5_check["match"]).sum()),
            "files not found": int((~md5_check["found"]).sum()),
        }
    )
    answer_key
    return answer_key, md5_check, missing_paths


@app.cell
def _(md5_check, missing_paths):
    mismatched = md5_check[~md5_check["match"]]
    mismatched, missing_paths[:20]
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. Human interventions

    Everything a person did: answering an approval request, or stepping in by hand (logged with
    `nfwatch.py intervene`). Anything done to the environment before the agent started is not
    counted here and is listed in the README.
    """)
    return


@app.cell
def _(events):
    interventions = events[
        events["kind"].isin(["approval_requested", "approval_answered", "intervention"])
    ].dropna(axis=1, how="all")
    interventions
    return (interventions,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Time and cost

    Model cost is what OpenRouter reported per call, summed by Pydantic AI. Compute ran in the
    worker's own cloud container (4 vCPU, 15 GB memory, Docker) at no charge, so compute cost is
    zero.
    """)
    return


@app.cell
def _(events, pd):
    # Usage counters are cumulative within one agent session, so take each session's last value.
    session = (events["kind"] == "agent_started").cumsum().rename("session")
    usage_rows = events[events["kind"].isin(["model_turn", "report", "budget_stop"])]
    per_session = usage_rows.groupby(session).agg(
        model_calls=("kind", "size"),
        cost_usd=("cost_usd", "max"),
        input_tokens=("input_tokens", "max"),
        cache_read_tokens=("cache_read_tokens", "max"),
        output_tokens=("output_tokens", "max"),
    )
    model_cost = float(per_session["cost_usd"].sum())
    start = events.loc[events["kind"] == "agent_started", "ts"].min()
    end = events["ts"].max()
    cost = pd.Series(
        {
            "agent sessions": len(per_session),
            "model calls": int(per_session["model_calls"].sum()),
            "input tokens": int(per_session["input_tokens"].sum()),
            "of which cache reads": int(per_session["cache_read_tokens"].sum()),
            "output tokens": int(per_session["output_tokens"].sum()),
            "model cost (USD)": round(model_cost, 2),
            "compute cost (USD)": 0.0,
            "total cost (USD)": round(model_cost, 2),
            "wall clock, agent start to end (h)": round((end - start).total_seconds() / 3600, 2),
        }
    )
    per_session, cost
    return (cost,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. The agent's own report

    The typed `RunReport` the agent returned at the end (see `nfwatch.py`).
    """)
    return


@app.cell
def _(events, pd):
    final = events[events["kind"] == "report"]
    report = final["report"].iloc[-1] if len(final) else {}
    agent_runs = pd.DataFrame(report.get("runs", []))
    (
        report.get("setup_steps"),
        agent_runs,
        report.get("failures_caught"),
        report.get("needs_a_person"),
    )
    return


@app.cell
def _(answer_key, cost, here, interventions, json, totals):
    # The headline numbers the README quotes, printed when run as a script and saved to disk.
    score = {
        "runs": totals.to_dict(),
        "answer_key": answer_key.to_dict(),
        "interventions": int((interventions["kind"] == "intervention").sum()),
        "approvals_answered": int((interventions["kind"] == "approval_answered").sum()),
        "cost": cost.to_dict(),
    }
    (here / "results" / "score.json").write_text(json.dumps(score, indent=1, default=str))
    print(json.dumps(score, indent=1, default=str))
    return


if __name__ == "__main__":
    app.run()

import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import urllib.request
    from collections import Counter
    from pathlib import Path

    import marimo as mo
    import pandas as pd

    here = Path(__file__).parent
    return Counter, here, json, mo, pd, urllib


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
    checksums of the 143 output files whose content is stable from run to run (nf-test hashes a
    `.gz` file by its decompressed content). We download it and compare it with the validation
    run's last attempt: its trace, and `results/validation/outputs.tsv`, which
    `nfwatch.py manifest` wrote from the run's output folder.

    Files are listed in the snapshot by name only, and five samples share names such as
    `cmd_info.json`, so we compare the multiset of checksums for each file name.
    """)
    return


@app.cell
def _(json, urllib):
    snap_url = "https://raw.githubusercontent.com/nf-core/rnaseq/3.27.0/tests/default.nf.test.snap"
    with urllib.request.urlopen(snap_url, timeout=60) as resp:
        assert resp.status == 200
        snapshot = json.loads(resp.read())["Params: default"]["content"]
    expected_tasks, _versions, expected_paths, expected_files = snapshot
    expected_md5 = [item.rsplit(":md5,", 1) for item in expected_files]
    len(expected_paths), len(expected_md5), expected_tasks
    return expected_md5, expected_paths, expected_tasks


@app.cell
def _(Counter, expected_md5, expected_paths, expected_tasks, here, pd):
    val_dir = here / "results" / "validation"
    outputs = pd.read_csv(val_dir / "outputs.tsv", sep="\t", dtype=str).fillna("")
    last_trace = pd.read_csv(sorted(val_dir.glob("trace_*.txt"))[-1], sep="\t")
    task_status = last_trace["status"].value_counts().to_dict()

    stable = [p for p in expected_paths if not p.startswith("pipeline_info/")]
    missing_paths = sorted(set(stable) - set(outputs["path"]))

    names = outputs["path"].str.rsplit("/", n=1).str[-1]
    md5_rows = []
    for name, wanted in Counter(n for n, _ in expected_md5).items():
        want = Counter(m for n, m in expected_md5 if n == name)
        got = outputs[names == name]
        exact = sum((want & Counter(got["md5"])).values())
        threads2 = sum((want & Counter(got["md5_threads2"])).values())
        md5_rows.append({"file": name, "expected": wanted, "exact": exact, "threads2": threads2})
    md5_check = pd.DataFrame(md5_rows)
    answer_key = pd.Series(
        {
            "tasks succeeded (expected)": expected_tasks,
            "tasks succeeded, last attempt (run + cached)": task_status.get("COMPLETED", 0)
            + task_status.get("CACHED", 0),
            "expected output paths": len(stable),
            "expected paths missing": len(missing_paths),
            "stable files checked": int(md5_check["expected"].sum()),
            "md5 exact matches": int(md5_check["exact"].sum()),
            "md5 matches with thread count set to 2": int(md5_check["threads2"].sum()),
        }
    )
    answer_key
    return answer_key, md5_check, missing_paths


@app.cell
def _(mo):
    mo.md(r"""
    The files that don't match exactly are salmon's `cmd_info.json` and featureCounts'
    `*.featureCounts.tsv`. Both write the number of threads into the file (`"threads": 4`,
    `"-T" "4"`). This machine has 4 CPUs; nf-test's CI config gives each process 2. With that one
    number set back to 2 (`THREAD_RECORDS` in `nfwatch.py`), the checksums match.
    """)
    return


@app.cell
def _(md5_check, missing_paths):
    md5_check[md5_check["exact"] < md5_check["expected"]], missing_paths[:20]
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### Do the one-sample batch runs agree with the validation run?

    The answer key only covers the validation run. For the batch, we compare each one-sample
    run's files with the validation run's files at the same path, for the file names nf-test
    treats as stable. MultiQC's tables are left out: they pool every sample in a run, so a
    one-sample run's tables are supposed to differ.
    """)
    return


@app.cell
def _(expected_md5, here, pd):
    stable_names = {name for name, _ in expected_md5}

    def stable_files(run: str) -> pd.Series:
        table = pd.read_csv(here / "results" / run / "outputs.tsv", sep="\t", dtype=str)
        table = table.dropna(subset=["md5_threads2"])
        keep = table["path"].str.rsplit("/", n=1).str[-1].isin(stable_names) & ~table[
            "path"
        ].str.startswith("multiqc/")
        return table[keep].set_index("path")["md5_threads2"]

    validation_files = stable_files("validation")
    batch_rows = []
    for sample_dir in sorted((here / "results").glob("sample_*")):
        files = stable_files(sample_dir.name)
        shared = files.index.intersection(validation_files.index)
        same = int((files[shared] == validation_files[shared]).sum())
        batch_rows.append(
            {"run": sample_dir.name, "files compared": len(shared), "identical": same}
        )
    batch_check = pd.DataFrame(batch_rows)
    batch_check
    return (batch_check,)


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
def _(answer_key, batch_check, cost, here, interventions, json, totals):
    # The headline numbers the README quotes, printed when run as a script and saved to disk.
    score = {
        "runs": totals.to_dict(),
        "answer_key": answer_key.to_dict(),
        "batch_vs_validation": batch_check.to_dict(orient="records"),
        "interventions": int((interventions["kind"] == "intervention").sum()),
        "approvals_answered": int((interventions["kind"] == "approval_answered").sum()),
        "cost": cost.to_dict(),
    }
    (here / "results" / "score.json").write_text(json.dumps(score, indent=1, default=str))
    print(json.dumps(score, indent=1, default=str))
    return


if __name__ == "__main__":
    app.run()

import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import difflib

    import marimo as mo
    import matplotlib.pyplot as plt

    from fri_rebuild.agents import records

    log = records.table()
    return difflib, log, mo, plt, records


@app.cell
def _(mo):
    mo.md(r"""
    # What the agents did

    Every proposal from every agent harness is one line of `experiments.jsonl`, with the code it
    produced:

    - **swarm**: the Pydantic AI loop (`uv run fri-swarm <hazard>`), one record per proposal.
    - **swarm-guard-bug**: the first wildfire round, rejected by a bug in the answer-key guard.
    - **claude-code-subagent**: Claude Code subagents running the same loop by hand (wildfire,
      coastal flooding); they logged metrics per experiment and kept their final file.
    - **recipe-search**: the Claude Code agents that searched for FEMA's coastal recipe.

    Pick a harness and hazard, then select a row to read its code and, for the swarm, its diff
    against the pipeline it started from.
    """)
    return


@app.cell
def _(log):
    summary = (
        log.assign(kept=log["status"].isin(["keep", "keep(final)"]))
        .groupby(["harness", "hazard"])
        .agg(
            records=("id", "size"),
            kept=("kept", "sum"),
            with_code=("has_code", "sum"),
            model_cost_usd=("cost_usd", "sum"),
        )
        .round(2)
    )
    summary
    return


@app.cell
def _(log, mo):
    harness = mo.ui.dropdown(sorted(log["harness"].unique()), value="swarm", label="Harness")
    harness
    return (harness,)


@app.cell
def _(harness, log, mo):
    hazards = sorted(log.loc[log["harness"] == harness.value, "hazard"].unique())
    hazard = mo.ui.dropdown(hazards, value=hazards[0], label="Hazard")
    hazard
    return (hazard,)


@app.cell
def _(harness, hazard, log, mo):
    rows = log[(log["harness"] == harness.value) & (log["hazard"] == hazard.value)]
    rows = rows.dropna(axis=1, how="all").drop(columns=["harness", "hazard"])
    picked = mo.ui.table(rows, selection="single", page_size=15)
    picked
    return (picked,)


@app.cell
def _(harness, hazard, log, mo, plt):
    def progress():
        swarm = log[(log["harness"] == "swarm") & (log["hazard"] == hazard.value)]
        tested = swarm.dropna(subset=["metric_log_mae"])
        kept = tested[tested["status"].isin(["keep", "resume"])]
        fig, ax = plt.subplots(figsize=(8, 3.5))
        ax.scatter(tested["round"], tested["metric_log_mae"], s=14, color="#bbb", label="tried")
        ax.step(kept["round"], kept["metric_log_mae"], where="post", color="#c0392b", label="kept")
        ax.set_xlabel("round")
        ax.set_ylabel("training log error")
        ax.set_yscale("log")
        ax.legend(frameon=False)
        ax.set_title(f"{hazard.value}: every proposal and the kept pipeline")
        fig.tight_layout()
        return fig

    progress() if harness.value == "swarm" else mo.md("")
    return


@app.cell
def _(difflib, harness, hazard, mo, picked, records):
    def show():
        if picked.value is None or len(picked.value) == 0:
            return mo.md("_Select a row to see its code._")
        row = picked.value.iloc[0]
        run = row.get("run")
        run = None if isinstance(run, float) else run
        try:
            code = records.code(harness.value, hazard.value, str(row["id"]), run)
        except KeyError:
            return mo.md("_No code was kept for this record (rejected, or a metrics-only log)._")
        parent = row.get("parent")
        if harness.value == "swarm" and isinstance(parent, str) and parent != "-":
            try:
                before = records.code("swarm", hazard.value, parent)
            except KeyError:
                return mo.md(f"```python\n{code}\n```")
            diff = "".join(
                difflib.unified_diff(
                    before.splitlines(keepends=True),
                    code.splitlines(keepends=True),
                    fromfile=parent,
                    tofile=str(row["id"]),
                )
            )
            return mo.ui.tabs(
                {
                    f"Diff against {parent}": mo.md(f"```diff\n{diff}\n```"),
                    "Code": mo.md(f"```python\n{code}\n```"),
                }
            )
        return mo.md(f"```python\n{code}\n```")

    show()
    return


if __name__ == "__main__":
    app.run()

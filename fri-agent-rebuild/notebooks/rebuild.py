import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import pandas as pd

    from fri_rebuild import rebuild
    from fri_rebuild.paths import RESULTS_DIR
    from fri_rebuild.scoring import answer_key

    out = RESULTS_DIR / "rebuild"
    out.mkdir(parents=True, exist_ok=True)
    return answer_key, mo, out, pd, rebuild


@app.cell
def _(mo):
    mo.md(r"""
    # Rebuilding FEMA's Future Risk Index multipliers

    Runs each hazard's final pipeline (`hazards/<hazard>/pipeline.py`), scores its county
    multipliers against FEMA's published values on training and held-out states, and summarizes
    the agent loop's experiment record (`experiments.jsonl`; browse it in
    `notebooks/experiments.py`). The loop itself is not rerun here: it
    costs money and is not deterministic (`uv run fri-swarm <hazard>`).

    Writes `results/rebuild/`.
    """)
    return


@app.cell
def _(answer_key, out, pd, rebuild):
    key = answer_key.conus(answer_key.load())
    runs = {_hazard: rebuild.run_hazard(key, _hazard) for _hazard in rebuild.HAZARDS}
    county_hm = pd.concat([run[0] for run in runs.values()], axis=1).sort_index()
    county_hm.index.name = "fips"
    county_hm.to_csv(out / "county_hm.csv")
    return key, runs


@app.cell
def _(mo):
    mo.md(r"""
    ## Scores

    `log_mae` is the mean absolute ln(rebuilt / published); `same_bin` is the share of counties
    in the same rating bin; held-out states were never shown to the agents.
    """)
    return


@app.cell
def _(out, pd, runs):
    scores = pd.concat([run[1] for run in runs.values()])
    scores.to_csv(out / "scores.csv", index=False)
    scores.round(3)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Largest differences
    """)
    return


@app.cell
def _(out, pd, rebuild, runs):
    largest = rebuild.largest_differences(pd.concat([run[2] for run in runs.values()])).round(4)
    largest.to_csv(out / "largest_differences.csv")
    largest
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## The agent loop
    """)
    return


@app.cell
def _(out, pd, rebuild, runs):
    timings = pd.DataFrame(
        [{"hazard": hazard, "seconds": round(run[3])} for hazard, run in runs.items()]
    )
    summary = pd.DataFrame([rebuild.swarm_summary(h) for h in rebuild.HAZARDS]).merge(timings)
    summary.to_csv(out / "swarm_summary.csv", index=False)
    summary
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Every kept pipeline on held-out states

    Scored after the fact, next to the Claude Code subagent runs. Picking among them with these
    scores would contaminate the held-out set, so they are reported, not used.
    """)
    return


@app.cell
def _(key, out, pd, rebuild):
    kept = pd.concat(
        [
            *(rebuild.kept_pipeline_scores(key, h) for h in rebuild.HAZARDS),
            rebuild.claude_code_comparison(key),
        ]
    )
    kept.to_csv(out / "kept_pipelines_held_out.csv", index=False)
    kept
    return


if __name__ == "__main__":
    app.run()

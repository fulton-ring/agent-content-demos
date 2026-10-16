import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import pandas as pd

    from hurloss_rebuild.paths import results_dir

    results = results_dir()
    return mo, pd, results


@app.cell
def _(mo):
    mo.md(
        """
        # Rebuilding FEMA's hurricane multipliers from public data

        Reads the tables `uv run hurloss-run` wrote to `results/`. Run that first.
        """
    )
    return


@app.cell
def _(mo, pd, results):
    levels = pd.read_csv(results / "answer_key_levels.csv")
    mo.vstack([mo.md("## What FEMA published (answer key)"), levels])
    return


@app.cell
def _(mo, pd, results):
    ara = pd.read_csv(results / "ara_white_paper.csv")
    mo.vstack([mo.md("## ARA's own Figure 1 through FEMA's Eq. 11"), ara])
    return


@app.cell
def _(mo, pd, results):
    scores = pd.read_csv(results / "scores.csv")
    held_out = scores[scores["subset"] == "held_out"].drop(columns="subset")
    mo.vstack([mo.md("## Scores on held-out states"), held_out])
    return


@app.cell
def _(mo, pd, results):
    baseline = pd.concat(
        [
            pd.read_csv(results / "baseline_historical.csv"),
            pd.read_csv(results / "baseline_storm_present.csv"),
        ]
    )
    mo.vstack([mo.md("## Today's hazard against NRI v1.20"), baseline])
    return


@app.cell
def _(mo, results):
    mo.vstack(
        [
            mo.image(results / "map_published.png"),
            mo.image(results / "map_rebuilt_ratio.png"),
            mo.image(results / "scatter_held_out.png"),
        ]
    )
    return


@app.cell
def _(mo, pd, results):
    layer = results / "layer"
    summary = pd.read_csv(layer / "fri_comparison_summary.csv")
    tracts = pd.read_csv(layer / "tract_summary_FL.csv")
    mo.vstack(
        [
            mo.md("## Our layer against FEMA's (see METHOD.md)"),
            summary,
            pd.read_csv(layer / "storm_check.csv"),
            mo.image(layer / "map_fema_vs_ours.png"),
            mo.md("## Florida tracts"),
            tracts,
            mo.image(layer / "map_tracts_FL.png"),
        ]
    )
    return


if __name__ == "__main__":
    app.run()

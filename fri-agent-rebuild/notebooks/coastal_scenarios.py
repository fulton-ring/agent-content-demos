import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    from fri_rebuild.coastal import scenarios
    from fri_rebuild.paths import RESULTS_DIR

    out = RESULTS_DIR / "coastal_scenarios"
    out.mkdir(parents=True, exist_ok=True)
    return mo, out, scenarios


@app.cell
def _(mo):
    mo.md(r"""
    # What-if: the floodplain share of coastal flooding

    **Scenarios, not findings.** The recovered recipe's weights sum to less than 1 for most
    counties; our reading is that the remainder is the 1% and 0.2% annual-chance floodplain
    share of NRI v1.19's coastal EAL, which FEMA's multipliers give no factor. For counties the
    recipe fits within 1%, three variants show how much that omission could matter:
    the share kept at today's losses, or growing like the 1% or the 0.2% flood level.
    None is FEMA's number or a forecast; late-century values show the method's limits.

    Writes `results/coastal_scenarios/`.
    """)
    return


@app.cell
def _(out, scenarios):
    by_county = scenarios.county_scenarios()
    by_county.to_csv(out / "by_county.csv", index=False)
    summary = scenarios.summary(by_county)
    summary.to_csv(out / "summary.csv", index=False)
    summary.round(2)
    return


if __name__ == "__main__":
    app.run()

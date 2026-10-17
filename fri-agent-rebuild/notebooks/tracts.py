import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import pandas as pd

    from fri_rebuild import maps, tracts
    from fri_rebuild.paths import RESULTS_DIR

    args = mo.cli_args()
    hazard = str(args.get("hazard", "drought"))
    column = str(args.get("column", "DRGT_LATE_HIGHER_HM"))
    state_fips = str(args.get("state-fips", "06"))
    state = str(args.get("state", "CA"))
    out = RESULTS_DIR / "tracts"
    out.mkdir(parents=True, exist_ok=True)
    return column, hazard, maps, mo, out, pd, state, state_fips, tracts


@app.cell
def _(column, mo, state):
    mo.md(rf"""
    # Below the county: {column} by census tract, {state}

    FEMA publishes multipliers per county only. This reruns the hazard's final pipeline with
    2020 tract polygons in place of counties, multiplies each tract's multiplier by NRI v1.19's
    tract EAL, and checks that the tracts roll back up to the county values.

    Other hazards and states: `uv run python notebooks/tracts.py -- --hazard wildfire
    --column WFIR_LATE_HIGHER_HM --state-fips 41 --state OR`. Writes `results/tracts/`.
    """)
    return


@app.cell
def _(column, hazard, out, state, state_fips, tracts):
    table, counties = tracts.tract_table(hazard, column, state_fips)
    check = tracts.roll_up(table, counties, column)
    table.to_csv(out / f"{column}_{state}_tracts.csv")
    check.to_csv(out / f"{column}_{state}_rollup.csv")
    return check, table


@app.cell
def _(check, column, pd, table, tracts):
    pd.Series(tracts.checks(table, check, column)).round(4)
    return


@app.cell
def _(column, maps, out, state, state_fips, table):
    figure = maps.tract_map(
        table[column], state_fips, f"{column} by census tract, {state} (rebuilt)"
    )
    figure.savefig(out / f"{column}_{state}_tracts.png", dpi=130)
    figure
    return


if __name__ == "__main__":
    app.run()

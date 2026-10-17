import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo
    import pandas as pd

    from fri_rebuild import maps
    from fri_rebuild.coastal import buildings
    from fri_rebuild.paths import RESULTS_DIR

    args = mo.cli_args()
    fips = str(args.get("fips", "45019"))
    gauge = str(args.get("gauge", "8665530"))
    out = RESULTS_DIR / "charleston"
    out.mkdir(parents=True, exist_ok=True)
    return buildings, fips, gauge, maps, mo, out, pd


@app.cell
def _(mo):
    mo.md(r"""
    # Pilot: coastal multipliers by tract, built from buildings (Charleston County, SC)

    FEMA's coastal multiplier is one number per county. Here every building in the USACE
    National Structure Inventory gets its own change in expected annual damage from the gauge's
    return-level curve and the FRI's sea level rise; buildings sum to tracts, and the tract
    multiplier is applied to NRI's own tract EAL. A bathtub model at one gauge: a scenario,
    not FEMA's number or a forecast. See `fri_rebuild.coastal.buildings` for the method.

    Another county: `uv run python notebooks/charleston_pilot.py -- --fips <county> --gauge
    <station>` (results/charleston/ is then named by the county FIPS).
    """)
    return


@app.cell
def _(buildings, fips, gauge, out):
    damage = buildings.building_damage(fips, gauge)
    table = buildings.tract_multipliers(damage, fips)
    table.to_csv(out / f"tracts_{fips}.csv")
    summary = buildings.summary(table, damage, fips, gauge)
    summary.to_csv(out / f"summary_{fips}.csv", index=False)
    return damage, summary, table


@app.cell
def _(buildings, damage, mo, pd, table):
    mo.vstack(
        [
            mo.md("## Checks on the building model"),
            pd.Series(buildings.diagnostics(damage, table)).round(3),
        ]
    )
    return


@app.cell
def _(mo, summary):
    mo.vstack(
        [
            mo.md(
                "## County and tract multipliers by scenario\n\n"
                "Variants: `curve` (depth-damage at the first floor), `step` (any water at the "
                "first floor is a total loss), `ground` (foundation height ignored)."
            ),
            summary.set_index("scenario").T.round(3),
        ]
    )
    return


@app.cell
def _(fips, maps, out, table):
    figure = maps.tract_map(
        table["curve_MID_LOWER_hm"],
        fips[:2],
        "Coastal flooding multiplier by tract, mid-century lower (building-level pilot)",
        county=fips,
    )
    figure.savefig(out / f"tracts_{fips}_mid_lower.png", dpi=130)
    figure
    return


if __name__ == "__main__":
    app.run()

import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import importlib.util

    import geopandas as gpd
    import marimo as mo
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    from fri_rebuild import data, inputs

    args = mo.cli_args()
    hazard = str(args.get("hazard", "drought"))
    column = str(args.get("column", "DRGT_LATE_HIGHER_HM"))
    state_fips = str(args.get("state-fips", "06"))
    out = data.PROJECT_DIR / "results" / "tracts"
    out.mkdir(parents=True, exist_ok=True)
    return column, data, gpd, hazard, importlib, inputs, mo, np, out, pd, plt, state_fips


@app.cell
def _(column, mo):
    mo.md(rf"""
    # Below the county: {column} by census tract

    **The question.** FEMA published multipliers per county only. If a rebuilt pipeline matches
    FEMA's county values, can the same pipeline say how the change varies inside a county, and
    do its tract numbers add back up to the county?

    **The method.** Rerun the hazard's final pipeline (`hazards/<hazard>/pipeline.py`) with
    2020 census tract polygons in place of counties: each tract's multiplier is the
    area-weighted mean of the 25 km climate cells it overlaps. Tract projected annual loss (PAL)
    is NRI v1.19's tract EAL × tract HM, the same product FEMA formed per county.

    Defaults to drought in California, late century, higher warming. Another hazard or state:
    `uv run notebooks/tracts.py -- --hazard wildfire --column WFIR_LATE_HIGHER_HM
    --state-fips 41`. Writes `results/tracts/`.
    """)
    return


@app.cell
def _(column, data, hazard, importlib, inputs, out, pd, state_fips):
    _spec = importlib.util.spec_from_file_location(
        hazard, data.PROJECT_DIR / "hazards" / hazard / "pipeline.py"
    )
    pipeline = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(pipeline)
    county_hm = pipeline.hazard_multipliers()[column]
    _nri_hazard = {"EXHT": "HWAV", "DRGT": "DRGT", "WFIR": "WFIR"}[column[:4]]
    tracts = pipeline.hazard_multipliers(inputs.tract_weights(state_fips))[[column]].join(
        data.nri_tracts()[f"{_nri_hazard}_EALT"].rename("EAL")
    )
    tracts["county"] = tracts.index.str[:5]
    tracts.to_csv(out / f"{column}_{state_fips}_tracts.csv")
    pd.Series(
        {
            "tracts": len(tracts),
            "counties": tracts["county"].nunique(),
            "tracts with NRI EAL": tracts["EAL"].notna().sum(),
            "lowest tract HM": tracts[column].min(),
            "highest tract HM": tracts[column].max(),
            "median within-county highest / lowest": tracts.groupby("county")[column]
            .agg(lambda s: s.max() / s.min())
            .median(),
        }
    ).round(2)
    return county_hm, tracts


@app.cell
def _(mo):
    mo.md(r"""
    ## Does it roll back up?

    Summing tract PAL gives a county PAL, and so a county multiplier: tract HMs weighted by
    where the losses are (EAL), not by area. We compare it with the same pipeline's
    area-weighted county value and with FEMA's published value.
    """)
    return


@app.cell
def _(column, county_hm, data, np, out, pd, state_fips, tracts):
    _key = data.answer_key()
    _by_county = tracts.groupby("county")
    rollup = pd.DataFrame(
        {
            "tract_eal_sum": _by_county["EAL"].sum(),
            "nri_county_eal": _key[f"{column[:4]}_EALT"],
            "rolled_up_hm": (tracts["EAL"] * tracts[column]).groupby(tracts["county"]).sum()
            / _by_county["EAL"].sum().replace(0, np.nan),
            "county_pipeline_hm": county_hm,
            "published_hm": _key[column],
        }
    ).loc[_by_county.size().index]
    rollup.to_csv(out / f"{column}_{state_fips}_rollup.csv")
    _gap = rollup["rolled_up_hm"] / rollup["county_pipeline_hm"] - 1
    pd.Series(
        {
            "largest |tract EAL sum / county EAL - 1|": (
                rollup["tract_eal_sum"] / rollup["nri_county_eal"] - 1
            )
            .abs()
            .max(),
            "rolled-up vs county pipeline, median |difference|": _gap.abs().median(),
            "rolled-up vs county pipeline, largest |difference|": _gap.abs().max(),
            "county pipeline vs FEMA, correlation": rollup["county_pipeline_hm"].corr(
                rollup["published_hm"]
            ),
            "rolled-up vs FEMA, correlation": rollup["rolled_up_hm"].corr(rollup["published_hm"]),
        }
    ).round(4)
    return


@app.cell
def _(mo):
    mo.md(r"""
    For California drought: NRI's tract EAL adds up to its county EAL exactly, so the baselines
    agree. The EAL-weighted roll-up differs from the area-weighted county multiplier by a few
    percent in the median county (up to about a fifth in the worst), and correlates less well
    with FEMA's county values than the county pipeline does. That is expected: FEMA's county
    multiplier is area-weighted, so tract PAL adds up to a slightly different county number
    than FEMA's HM. The gap comes from where the losses sit inside the county.
    """)
    return


@app.cell
def _(column, data, gpd, out, plt, state_fips, tracts):
    _shapes = gpd.GeoDataFrame(data.tracts(state_fips).join(tracts[column])).to_crs(data.EQUAL_AREA)
    _fig, _ax = plt.subplots(figsize=(10, 8))
    _shapes.plot(
        column=column,
        ax=_ax,
        cmap="YlOrRd",
        legend=True,
        missing_kwds={"color": "#ddd"},
        legend_kwds={"label": "Hazard multiplier", "shrink": 0.6},
    )
    _counties = data.counties()
    _counties[_counties["STATEFP"] == state_fips].to_crs(data.EQUAL_AREA).boundary.plot(
        ax=_ax, color="#333", linewidth=0.4
    )
    _ax.set_axis_off()
    _ax.set_title(f"{column} by census tract, state {state_fips} (rebuilt)")
    _fig.tight_layout()
    _fig.savefig(out / f"{column}_{state_fips}_tracts.png", dpi=130)
    _fig
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What the downscaling assumes

    - **The climate signal is no finer than its grid**: 0.25°, about 25 km, for NEX. Small
      urban tracts inside one cell share its value; what varies between them is NRI's tract EAL.
    - Exposure, historic loss ratios and community risk factors stay at today's values, as in
      the FRI.
    - The tract multiplier uses the county method with no tract-level calibration. FEMA
      published no tract multipliers, so the tract values can be checked only by the roll-up,
      not against an answer key.
    - **ZIP code or property level is not supported by this data.** LOCA2 heat, rebuilt at
      1/16°, is the finest hazard here and could support a finer tract layer; we did not build
      one.
    """)
    return


if __name__ == "__main__":
    app.run()

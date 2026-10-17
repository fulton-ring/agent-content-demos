import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import functools

    import marimo as mo
    import pandas as pd

    from fri_rebuild.coastal import forensics, recipe, recipe_score
    from fri_rebuild.paths import RESULTS_DIR
    from fri_rebuild.scoring import answer_key

    out = RESULTS_DIR / "coastal_forensics"
    out.mkdir(parents=True, exist_ok=True)
    return answer_key, forensics, functools, mo, out, pd, recipe, recipe_score


@app.cell
def _(mo):
    mo.md(r"""
    # Reverse engineering FEMA's coastal flooding multipliers

    Unlike the rebuild, this reads FEMA's published values directly (the answer key is open) and
    asks what structure produced them. See `fri_rebuild.coastal.forensics` for each check.
    Writes `results/coastal_forensics/`.
    """)
    return


@app.cell
def _(answer_key, forensics, out):
    table = forensics.published()
    gauges = forensics.nearest_gauges(table)
    checks = {
        "zero_hm": forensics.zeros(table),
        "hm_below_one": forensics.below_one(table, gauges),
        "late_equality_by_state": forensics.late_equality(table),
        "footprint_v1_18_1": forensics.footprint(table),
        "baseline_drift_v1_20": forensics.baseline_drift(answer_key.load()),
        "gauge_rank_test": forensics.subspace_test(table, gauges),
        "recipe_fit": forensics.recipe_fit(table, gauges),
    }
    for _name, _frame in checks.items():
        _frame.to_csv(out / f"{_name}.csv")
    return (checks,)


@app.cell
def _(checks, mo, pd):
    _zero = checks["zero_hm"]
    _equal = checks["late_equality_by_state"]
    _footprint = checks["footprint_v1_18_1"]
    mo.vstack(
        [
            mo.md(
                f"""
    ## What the published values look like

    - HM = 0 in {len(_zero)} counties; FEMA's own PAL ratings treat
      {_zero["matches_hm_1"].sum()} of them as HM = 1.
    - 0 < HM < 1 in {len(checks["hm_below_one"])} counties, which the documented formula cannot
      produce.
    - Late century lower equals higher in {_equal["late_lower_equals_higher"].sum()} of
      {_equal["counties"].sum()} counties.

    **Footprint:** published HM = 0 against coastal flooding EAL in NRI v1.18.1.
    """
            ),
            pd.crosstab(_footprint["published_zero"], _footprint["coastal_in_v1_18_1"]),
            mo.md("**Do counties sharing a gauge lie in a 3-dimensional subspace?**"),
            checks["gauge_rank_test"].round(4),
        ]
    )
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## The recovered recipe

    `fri_rebuild.coastal.recipe`: NOAA's minor, moderate and major thresholds, frequencies read
    off the 2022 return-level curves, shifted by median sea level rise, capped at 10 a year.
    Each county's three weights are fitted (non-negative) to its four published values. Only the
    counties whose four values all differ test a recipe. The thresholds can come from CO-OPS or
    from NOAA's tide-range formula; the first-pass baseline used return periods instead.
    """)
    return


@app.cell
def _(forensics, functools, out, pd, recipe, recipe_score):
    candidates = {
        "return periods (baseline)": functools.partial(forensics.report_factors, cap=True),
        "NOAA thresholds, published": recipe.gauge_factors,
        "NOAA thresholds, formula": functools.partial(recipe.gauge_factors, source="formula"),
        "NOAA thresholds, formula where missing": functools.partial(
            recipe.gauge_factors, source="formula_missing"
        ),
    }
    results = {name: recipe_score.score(factors) for name, factors in candidates.items()}
    recipe_scores = pd.DataFrame({name: result[0] for name, result in results.items()}).T
    recipe_scores.to_csv(out / "recipe_scores.csv")
    weights = results["NOAA thresholds, published"][1]
    weights.to_csv(out / "recipe_weights.csv", index=False)
    recipe_scores.round(4)
    return (weights,)


@app.cell
def _(mo, weights):
    _four = weights[weights["four_distinct"]].sort_values("relative_residual", ascending=False)
    mo.vstack(
        [
            mo.md(
                "Counties with four distinct values, worst fit first. The weights sum to a "
                f"median of {weights['weight_sum'].median():.2f}, not 1."
            ),
            _four.round(4),
        ]
    )
    return


if __name__ == "__main__":
    app.run()

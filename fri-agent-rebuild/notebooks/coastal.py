import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import functools
    from collections.abc import Callable

    import geopandas as gpd
    import marimo as mo
    import numpy as np
    import pandas as pd
    from scipy.optimize import nnls

    from fri_rebuild import data, inputs, recipe, scoring

    out = data.PROJECT_DIR / "results" / "coastal"
    out.mkdir(parents=True, exist_ok=True)
    return Callable, data, functools, gpd, inputs, mo, nnls, np, out, pd, recipe, scoring


@app.cell
def _(mo):
    mo.md(r"""
    # Reverse engineering FEMA's coastal flooding multipliers

    **The question.** The blind rebuild of coastal flooding failed: held-out correlation stayed
    near 0.3 whatever the agents tried. Was the method undocumented, or were the inputs not
    public? Here we open the answer key on purpose and ask what structure produced FEMA's
    numbers. This says what FEMA did, not whether agents can find it.

    FEMA's documented formula (equation 4) is HM = Σ over three flood sub-types of
    (frequency factor at the county's nearest tide gauge × that sub-type's share of the
    county's coastal flood EAL). Writes `results/coastal/`.
    """)
    return


@app.cell
def _(data, gpd, inputs, recipe):
    published = data.answer_key()
    published = published[published[recipe.COLUMNS].notna().any(axis=1)]
    _gauges = inputs.coastal_tables()["extreme_water_levels"]
    _gauges = inputs.points(
        _gauges[["St", "Location", "Latitude", "Longitude"]], "Longitude", "Latitude"
    )
    _shapes = data.counties().loc[lambda c: c.index.isin(published.index)]
    nearest_gauge = (
        gpd.sjoin_nearest(
            _shapes[["geometry"]].to_crs(data.EQUAL_AREA), _gauges.to_crs(data.EQUAL_AREA)
        )
        .groupby(level=0)[["St", "Location"]]
        .first()
        .astype({"St": str})
    )
    coastal = published[published[recipe.COLUMNS[0]] > 0].join(nearest_gauge)
    return coastal, published


@app.cell
def _(mo):
    mo.md(r"""
    ## What the published values show

    **Zero means "no projection", and FEMA's own ratings treat it as 1.** If HM = 0, projected
    loss is 0 and the rating should be the lowest. We check which rating each zero county's
    projected loss actually got.
    """)
    return


@app.cell
def _(out, published, recipe, scoring):
    _zero = published[(published[recipe.COLUMNS[0]] == 0)]
    _thresholds = scoring.rating_thresholds(published, "CFLD")
    zeros = _zero[["STATEABBRV", "COUNTY", "CFLD_EALT", "CFLD_LATE_HIGHER_PALR"]].assign(
        rating_if_hm_1=scoring.rate(_zero["CFLD_EALT"], _thresholds),
        published_rating=_zero["CFLD_LATE_HIGHER_PALR"].map(scoring.rating_name),
    )
    zeros.to_csv(out / "zero_hm.csv")
    _below = published[
        (published[recipe.COLUMNS] > 0).all(axis=1) & (published[recipe.COLUMNS] < 1).any(axis=1)
    ]
    _below[["STATEABBRV", "COUNTY", *recipe.COLUMNS]].to_csv(out / "hm_below_one.csv")
    {
        "counties published at HM = 0": len(zeros),
        "... of which with coastal flood EAL today": int((zeros["CFLD_EALT"] > 0).sum()),
        "... whose published rating equals the HM = 1 rating": int(
            (zeros["rating_if_hm_1"] == zeros["published_rating"]).sum()
        ),
        "counties with 0 < HM < 1 in some scenario": len(_below),
    }
    return


@app.cell
def _(mo):
    mo.md(r"""
    So the HM column says these counties' future coastal losses are zero, and the ratings say
    they are unchanged. They are mostly Great Lakes counties, which have no sea-level gauges,
    plus inland Louisiana; East Baton Rouge has $1.2M of coastal flood loss a year today.

    **Some counties have 0 < HM < 1, which equation 4 cannot produce**: under rising seas floods
    can't get rarer, and shares that sum to 1 can't give less than 1 (Effingham, GA is 0.013 at
    mid-century; Williamsburg, SC 0.03). Ratings floor HM at 1, so this doesn't show in them.

    **Late century saturates on the Atlantic and Gulf coasts.** Count of counties whose two
    late-century scenarios (1.0 m and 2.0 m of sea level rise) are identical, by state:
    """)
    return


@app.cell
def _(coastal, np, out):
    _equal = np.isclose(coastal["CFLD_LATE_LOWER_HM"], coastal["CFLD_LATE_HIGHER_HM"], rtol=1e-9)
    late_equal = (
        coastal.assign(late_equal=_equal).groupby("STATEABBRV")["late_equal"].agg(["size", "sum"])
    )
    late_equal.sort_values("size", ascending=False).to_csv(out / "late_equality_by_state.csv")
    late_equal.sum().rename({"size": "counties", "sum": "late lower = late higher"})
    return


@app.cell
def _(mo):
    mo.md(r"""
    The exceptions are on the Pacific coast and in Puerto Rico and the Virgin Islands.

    **The structure checks out.** If HM = Σ (gauge factor × county weight) with three
    sub-types, the four scenario values of counties sharing a gauge must lie in a 3-dimensional
    subspace. We test it with the ratio of the fourth to the first singular value (0 = exactly
    rank 3) for each gauge with at least four such counties, against 2,000 random groups of the
    same size. Only counties whose four values all differ count; with equal late values any
    three weights fit.
    """)
    return


@app.cell
def _(coastal, np, out, pd, recipe):
    def rank_ratio(values: np.ndarray) -> float:
        scaled = values / np.linalg.norm(values, axis=1, keepdims=True)
        singular = np.linalg.svd(scaled, compute_uv=False)
        return float(singular[3] / singular[0])

    _distinct = coastal[~np.isclose(coastal["CFLD_LATE_LOWER_HM"], coastal["CFLD_LATE_HIGHER_HM"])]
    _pool, _rng = _distinct[recipe.COLUMNS].to_numpy(), np.random.default_rng(0)
    rank_test = pd.DataFrame(
        {
            "gauge": _gauge,
            "counties": len(_group),
            "rank_ratio": rank_ratio(_group[recipe.COLUMNS].to_numpy()),
            "random_groups_median": np.median(
                [
                    rank_ratio(_pool[_rng.choice(len(_pool), len(_group), replace=False)])
                    for _ in range(2000)
                ]
            ),
        }
        for _gauge, _group in _distinct.groupby("Location")
        if len(_group) >= 4
    )
    rank_test.to_csv(out / "gauge_rank_test.csv", index=False)
    rank_test.round(4)
    return


@app.cell
def _(mo):
    mo.md(r"""
    **The multipliers follow the previous NRI release's footprint.** FEMA applied them to NRI
    v1.19.0 (March 2023). We compare which counties got a non-zero HM with which had coastal
    flood EAL in v1.18.1 (November 2021). FEMA no longer serves v1.18.1; our copy is a third
    party's, but its coastal flood EAL matches FEMA's v1.18.1 tract layer on ArcGIS Online for
    every county. States and DC only (the copy has no territories).
    """)
    return


@app.cell
def _(data, out, pd, published, recipe):
    _url = (
        "https://media.githubusercontent.com/media/dynamicalsystemslaboratory/"
        "Data-centers-siting-across-U.S.-cities/main/Section%202%20and%204/Data/NRI_Table_Counties.csv"
    )
    _v1181 = pd.read_csv(
        data.download(_url, data.cache("forensics", "nri_v1_18_1.csv")), dtype={"STCOFIPS": str}
    )
    _v1181 = _v1181.set_index(_v1181["STCOFIPS"].str.zfill(5))["CFLD_EALT"]
    _states = published[~published["STATEABBRV"].isin(data.CONUS_EXCLUDED - {"AK", "HI"})]
    footprint = _states[["STATEABBRV", "COUNTY", "CFLD_EALT", recipe.COLUMNS[0]]].assign(
        published_zero=_states[recipe.COLUMNS[0]] == 0,
        coastal_in_v1_18_1=_v1181.reindex(_states.index).fillna(0) > 0,
    )
    footprint.to_csv(out / "footprint_v1_18_1.csv")
    pd.crosstab(footprint["published_zero"], footprint["coastal_in_v1_18_1"])
    return


@app.cell
def _(mo):
    mo.md(r"""
    Every county with a non-zero multiplier had coastal flood EAL in v1.18.1, and every county
    that gained coastal flood EAL only in v1.19.0 is published at 0; every Great Lakes county is
    among them. The 2023 release changed coastal flooding everywhere (building values revalued,
    per-county frequencies, new loss ratios), and the counties below 1 are mostly inland ones
    where the new method cut frequency and mapped area.

    ## The recipe, found by search

    Three Claude Code subagents searched for a recipe that reproduces FEMA's gauge factors from
    public NOAA data, scored by how well each county's three weights (non-negative) can fit its
    four published values. Two of them, starting from different angles, converged on the same
    recipe, now `fri_rebuild/recipe.py`. Their final recipes and search logs are in
    `experiments.jsonl` (harness `recipe-search`).

    - **Sub-types are NOAA's thresholds, not return periods**: the minor, moderate and major
      flood thresholds at each gauge (about 0.5, 0.8 and 1.2 m above high tide), not the 1-2,
      10-50 and 100-year floods FEMA's documentation names.
    - **Frequencies come from the 2022 report's return-level curves**, today and with the
      threshold lowered by the median sea level rise: 1.0 m by 2100 for the lower scenario, 2.0 m
      for the higher. They are capped at 10 a year, the curve's shortest return period, which is
      why the two late-century scenarios coincide where thresholds sink below the curve.
    - **The factor is new frequency over today's.**

    Below, the recipe against the first-pass baseline (FEMA's named return periods on the same
    curves), and with thresholds from NOAA's tide-range formula instead of CO-OPS's published
    ones. Only counties with four distinct values test a recipe.
    """)
    return


@app.cell
def _(Callable, coastal, inputs, nnls, np, pd, recipe):
    def score_recipe(
        gauge_factors: Callable[[str], np.ndarray | None],
    ) -> tuple[dict, pd.DataFrame]:
        """Fit each county's weights to its gauge's factors; summarize the fit."""
        rows = []
        for gauge, group in coastal.groupby("St"):
            factors = gauge_factors(gauge)
            if factors is None:
                continue
            recipe_equal = bool(np.allclose(factors[:, 2], factors[:, 3], rtol=1e-9))
            for fips, county in group.iterrows():
                values = county[recipe.COLUMNS].to_numpy(float)
                weights, residual = nnls(factors.T, values)
                data_equal = bool(np.isclose(values[2], values[3], rtol=1e-9))
                rows.append(
                    {
                        "fips": fips,
                        "state": county["STATEABBRV"],
                        "county": county["COUNTY"],
                        "gauge": county["Location"],
                        "four_distinct": not data_equal,
                        "late_pattern_agrees": data_equal == recipe_equal,
                        "relative_residual": residual / np.linalg.norm(values),
                        "weight_sum": weights.sum(),
                        "w_minor": weights[0],
                        "w_moderate": weights[1],
                        "w_major": weights[2],
                    }
                )
        detail = pd.DataFrame(rows)
        four = detail.loc[detail["four_distinct"], "relative_residual"]
        return {
            "four_distinct_median_error": four.median(),
            "four_distinct_within_0.1pct": int((four < 1e-3).sum()),
            "four_distinct_counties": len(four),
            "late_pattern_agrees": detail["late_pattern_agrees"].mean(),
            "counties_covered": len(detail),
        }, detail

    def return_period_factors(gauge: str) -> np.ndarray | None:
        """The first-pass baseline: FEMA's named return periods as sub-types."""
        row, levels, periods = recipe.curve(gauge)
        rise_table = inputs.coastal_tables()["sea_level_projections"]
        own = rise_table[rise_table["NOAA ID"] == float(gauge)].set_index("Scenario")
        if own.empty:
            return None
        rises = [own.loc[s, f"RSL{y} (cm)"] / 100 for s, y in recipe.RISES]
        factors = []
        for return_periods in ([1, 2], [10, 20, 30, 40, 50], [100]):
            today = [np.interp(np.log(rp), np.log(periods), levels) for rp in return_periods]
            current = np.mean([1 / rp for rp in return_periods])
            factors.append(
                [
                    np.mean([recipe.frequency(z - r, levels, periods) for z in today]) / current
                    for r in rises
                ]
            )
        return np.array(factors)

    return return_period_factors, score_recipe


@app.cell
def _(functools, out, pd, recipe, return_period_factors, score_recipe):
    _candidates = {
        "return periods (first pass)": return_period_factors,
        "NOAA thresholds, published": recipe.gauge_factors,
        "NOAA thresholds, formula": functools.partial(recipe.gauge_factors, source="formula"),
        "NOAA thresholds, formula where missing": functools.partial(
            recipe.gauge_factors, source="formula_missing"
        ),
    }
    _results = {name: score_recipe(factors) for name, factors in _candidates.items()}
    recipe_scores = pd.DataFrame({name: result[0] for name, result in _results.items()}).T
    recipe_scores.to_csv(out / "recipe_scores.csv")
    weights = _results["NOAA thresholds, published"][1]
    weights.to_csv(out / "recipe_weights.csv", index=False)
    recipe_scores.round(4)
    return recipe_scores, weights


@app.cell
def _(mo, recipe_scores, weights):
    _fit = weights[weights["relative_residual"] < 0.01]
    _best = recipe_scores.loc["NOAA thresholds, published"]
    mo.md(f"""
    The recipe reproduces {_best["four_distinct_within_0.1pct"]:.0f} of the
    {_best["four_distinct_counties"]:.0f} counties with four distinct values to within 0.1%,
    with a median error of {_best["four_distinct_median_error"]:.1%}; the first pass managed
    none. It gets right whether the two late values are equal for
    {_best["late_pattern_agrees"]:.0%} of counties. NOAA's current thresholds still equal its
    2018 tide-range formula (0.04 × range + 0.50 m, 0.03 × + 0.80 m, 0.04 × + 1.17 m), and the
    formula fits as well, so the threshold inputs have not drifted.

    **What still doesn't fit**: Pacific gauges (Tacoma, Astoria, parts of Oregon and
    California) are off by 2-40%, as if FEMA's cap or sea level inputs differed there, and some
    Atlantic gauges have identical mid-century values under both scenarios, which the recipe
    doesn't produce. A global 6 cm cut in the rise would bring the median error to about 0.2%,
    but there is no physical reason for it, so it is not in the recipe.

    **What the recipe says about the weights.** With the factors known, each county's three
    weights can be solved. For the {len(_fit)} counties fit within 1%, they sum to a median of
    {_fit["weight_sum"].median():.2f}, and {(_fit["weight_sum"] < 0.95).mean():.0%} sum to less
    than 0.95. NRI v1.19.0 has five coastal sub-types: NOAA's three high-tide-flooding zones and
    FEMA's 1% and 0.2% annual-chance floodplains. The FRI formula adjusts only the three
    high-tide ones. If the floodplain share of EAL was simply left out, rather than kept at a
    factor of 1, that explains the counties below 1, and the zeros: Great Lakes counties have
    floodplain EAL but no tidal flooding. This depends on our "today's frequency" matching
    FEMA's, so we treat the weight sums as strong evidence, not proof.

    One retraction during the analysis: an early subspace test seemed to match an uncapped
    return-period recipe to within 0.06°, but that recipe produces factors as large as 10^24,
    which made the angle meaningless.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What-if: the floodplain share (scenarios, not findings)

    For counties the recipe fits within 1%, we treat each county's weights' shortfall from 1 as
    its floodplain share and compute three variants: the share **kept** at today's losses
    (factor 1), or **growing** the way the 1% or the 0.2% annual-chance flood level does under
    the scenario's sea level rise (the 0.2% level extrapolated past the curve's 100-year end).
    NRI doesn't publish how the floodplain share splits between the two, so they bracket it.
    None is FEMA's number or a forecast.
    """)
    return


@app.cell
def _(coastal, nnls, np, out, pd, published, recipe, scoring):
    _rows = []
    for _gauge, _group in coastal.groupby("St"):
        _factors = recipe.gauge_factors(_gauge)
        _row, _levels, _periods = recipe.curve(_gauge)
        _rises, _log_rp = recipe.rises(_row), np.log(_periods)
        assert _periods[-1] == 100, "the curve should end at the 100-year level"
        _slope = (_levels[-1] - _levels[-6]) / (_log_rp[-1] - _log_rp[-6])
        _growth = {}
        for _name, _level in (
            ("floodplain_1pct", _levels[-1]),
            ("floodplain_0_2pct", _levels[-1] + _slope * (np.log(500) - _log_rp[-1])),
        ):
            _today = recipe.frequency(_level, _levels, _periods)
            _growth[_name] = [
                recipe.frequency(_level - r, _levels, _periods) / _today for r in _rises
            ]
        for _fips, _county in _group.iterrows():
            _published = _county[recipe.COLUMNS].to_numpy(float)
            _weights, _residual = nnls(_factors.T, _published)
            if _residual / np.linalg.norm(_published) >= 0.01:
                continue
            _rest = max(0.0, 1.0 - _weights.sum())
            for _i, _column in enumerate(recipe.COLUMNS):
                _rows.append(
                    {
                        "fips": _fips,
                        "scenario": _column[5:-3],
                        "eal": _county["CFLD_EALT"],
                        "published": _published[_i],
                        "floodplain_kept": _published[_i] + _rest,
                        "floodplain_1pct": _published[_i] + _rest * _growth["floodplain_1pct"][_i],
                        "floodplain_0_2pct": _published[_i]
                        + _rest * _growth["floodplain_0_2pct"][_i],
                    }
                )
    by_county = pd.DataFrame(_rows)
    by_county.to_csv(out / "scenarios_by_county.csv", index=False)
    _thresholds = scoring.rating_thresholds(published, "CFLD")
    _summary = []
    for _scenario, _part in by_county.groupby("scenario", sort=False):
        _base = scoring.rate(_part["eal"] * _part["published"].clip(lower=1), _thresholds)
        for _variant in ("published", "floodplain_kept", "floodplain_1pct", "floodplain_0_2pct"):
            _pal = _part["eal"] * _part[_variant].clip(lower=1)
            _summary.append(
                {
                    "scenario": _scenario,
                    "variant": _variant,
                    "counties": len(_part),
                    "projected_loss_usd_bn": _pal.sum() / 1e9,
                    "rating_changes": int((scoring.rate(_pal, _thresholds) != _base).sum()),
                }
            )
    scenarios = pd.DataFrame(_summary)
    scenarios.to_csv(out / "scenarios_summary.csv", index=False)
    scenarios.round(2)
    return


@app.cell
def _(mo):
    mo.md(r"""
    Keeping the floodplain share at today's losses changes little (2-5% mid-century, under
    1% late). Letting it grow with sea level raises mid-century projected losses by roughly a
    fifth to two thirds. **The late-century figures are not credible as estimates**: by 2100
    today's 100- and 500-year flood levels are reached up to 10 times a year, so their factors
    run into the thousands, and the frequency-ratio method then multiplies today's floodplain
    losses as if every one of those floods did the same damage. Like FEMA's own late-century
    coastal values, they say more about the method's limits than about future losses.

    ## How stale is the baseline?

    The thresholds and curves have not moved. The NRI baseline has: v1.20 (December 2025)
    against v1.19.0, the release FEMA applied its multipliers to.
    """)
    return


@app.cell
def _(data, np, out, pd, recipe):
    _target = data.cache("forensics", "nri_v1_20_counties.parquet")
    if not _target.exists():
        _url = (
            "https://services.arcgis.com/XG15cJAlne2vxtgt/arcgis/rest/services/"
            "National_Risk_Index_Counties/FeatureServer/0/query"
        )
        _rows = []
        for _offset in range(0, 10_000, 2000):  # about 3,200 counties
            _params = {
                "where": "1=1",
                "outFields": "STCOFIPS,CFLD_EALT",
                "returnGeometry": "false",
                "resultOffset": _offset,
                "resultRecordCount": 2000,
                "f": "json",
            }
            _response = data.http().get(_url, params=_params, timeout=120)
            _response.raise_for_status()
            _rows += [feature["attributes"] for feature in _response.json()["features"]]
        pd.DataFrame(_rows).to_parquet(_target)
    _v120 = pd.read_parquet(_target).set_index("STCOFIPS")["CFLD_EALT"].rename("CFLD_EALT_v1_20")
    drift = data.answer_key()[["STATEABBRV", "COUNTY", "CFLD_EALT", recipe.COLUMNS[0]]].join(
        _v120, how="outer"
    )
    drift = drift[(drift["CFLD_EALT"].fillna(0) > 0) | (drift["CFLD_EALT_v1_20"].fillna(0) > 0)]
    drift.to_csv(out / "baseline_drift_v1_20.csv")
    _both = drift[(drift["CFLD_EALT"] > 0) & (drift["CFLD_EALT_v1_20"] > 0)]
    _ratio = _both["CFLD_EALT_v1_20"] / _both["CFLD_EALT"]
    {
        "national coastal flood EAL, v1.19 ($bn/yr)": drift["CFLD_EALT"].sum() / 1e9,
        "national coastal flood EAL, v1.20 ($bn/yr)": drift["CFLD_EALT_v1_20"].sum() / 1e9,
        "counties in both": len(_both),
        "... changed more than 2x either way": float((np.abs(np.log(_ratio)) > np.log(2)).mean()),
        "... middle half of v1.20 / v1.19": (_ratio.quantile(0.25), _ratio.quantile(0.75)),
    }
    return


@app.cell
def _(mo):
    mo.md(r"""
    Part of the change is Connecticut moving from 8 counties to 9 planning regions. FEMA's
    multipliers were never refit even to v1.19.0 (they follow v1.18.1's footprint); applying
    them to v1.20 would widen the mismatch.

    ## What this shows, and doesn't

    - FEMA's coastal multipliers come from NOAA's flood thresholds read off the 2022 report's
      curves, not the return periods its documentation names, and appear to drop the floodplain
      share of EAL rather than keep it at 1. That is why a blind rebuild from the documentation
      could not get the ranking right.
    - The county weights (each sub-type's share of EAL) are not public, so even with the recipe
      a blind rebuild would still need them; we only fit them here because the answer key is
      open.
    """)
    return


if __name__ == "__main__":
    app.run()

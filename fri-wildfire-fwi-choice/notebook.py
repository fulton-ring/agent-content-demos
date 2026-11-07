import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    from concurrent.futures import ThreadPoolExecutor
    from pathlib import Path

    import marimo as mo
    import numpy as np
    import pandas as pd
    from fri_rebuild import data, inputs, scoring

    out = Path(__file__).resolve().parent / "results"
    out.mkdir(exist_ok=True)
    return ThreadPoolExecutor, data, inputs, mo, np, out, pd, scoring


@app.cell
def _(mo):
    mo.md(r"""
    # Which FWI ensemble and statistic match FEMA's wildfire multipliers?

    **The question.** FEMA's Future Risk Index wildfire multiplier is
    `HM = (FWI_future / FWI_historic) ^ gamma`, built from NASA's NEX-GDDP-CMIP6 Fire Weather
    Index. FEMA says only that it used "a MME which averages several distinct downscaled
    results". NASA publishes three ensemble members (MME25, MME50, MME75: the 25th, 50th and
    75th percentile across models) and several yearly statistics, including the annual mean
    and the 95th percentile (P95). Which ensemble member and statistic reproduce FEMA's
    published county multipliers best?

    **Why rerun it.** The [FRI rebuild](../fri-agent-rebuild/) tried these swaps, but each
    one on top of a different gamma regression, so it can't say what the ensemble or the
    statistic does on its own. Its best wildfire pipeline (Claude Code agent 3: MME50, annual
    mean, plain log-log regression) never tried P95. Here every choice of ensemble and
    statistic runs under the same two fixed regressions.

    **The two regressions** (both from the rebuild, copied unchanged):

    - **Simple** (agent 3): OLS of ln(NRI v1.19 wildfire EAL) on ln(historical county FWI),
      no fixed effects, no fuel controls. A county's HM is the area-weighted mean of the
      cell-level HMs.
    - **Swarm** (the rebuild's kept pipeline): weighted least squares of ln(wildfire EAL) on
      ln(FWI), LANDFIRE fuel-group shares and ln(burnable share), weighted by the square root
      of the burnable share. A county's HM is the ratio of county-mean FWI, raised to gamma.

    gamma is refitted for every ensemble and statistic, as FEMA's method requires.

    **The score.** FEMA's published `WFIR_<MID|LATE>_<LOWER|HIGHER>_HM` for the CONUS
    counties, from the datasheet saved before the tool came down. Same metrics and same
    train/held-out state split as the rebuild (`fri_rebuild.scoring`). Nothing is chosen with
    the scores, so all counties are reported too.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## The data

    Downloaded on first run into `~/.cache/fri-agent-rebuild` (shared with the rebuild; set
    `FRI_CACHE` to move it): FEMA's datasheet, Census 2020 counties, LANDFIRE fuel models at
    500 m, NASA's yearly FWI files for MME50 and MME75 (about 13 GB transferred, kept as the
    CONUS box), and one NEX-GDDP-CMIP6 file for the 0.25° grid. Already cached files are
    skipped. Any year the portal doesn't serve is skipped. The rebuild found 4-7 of the 30
    years missing in each period; on 7 November 2026 all 300 files were there.
    """)
    return


@app.cell
def _(ThreadPoolExecutor, data, np):
    fips = data.conus(data.answer_key()).index
    if not data.cache("nex", "grid.npz").exists():
        _keys = data.nex_newest_files("tas", "historical")
        data.nex_year("tas", "historical", 1990, _keys[1990], (False, False))
    _jobs = [
        (ensemble, scenario, year)
        for ensemble in ("MME50", "MME75")
        for scenario, years in data.HEAT_YEARS.items()
        for year in years
    ]
    with ThreadPoolExecutor(4) as _pool:
        _found = list(_pool.map(lambda job: data.fwi_year(*job), _jobs))
    _grid = np.load(data.cache("nex", "grid.npz"))
    data.area_weights(data.counties().loc[fips], _grid["lat"], _grid["lon"], "counties")
    data.fuel_shares(data.counties().loc[fips], "counties")
    print(f"{len(fips)} counties; FWI: {len(_jobs)} files, {_found.count(False)} missing")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 1: 30-year mean of each statistic, per grid cell

    For each ensemble member, statistic, scenario and period, average the yearly values over
    the years present. Periods are FEMA's: historical 1976-2005, mid 2036-2065, late
    2070-2099; LOWER is SSP2-4.5 and HIGHER is SSP5-8.5.
    """)
    return


@app.cell
def _(inputs, np):
    ensembles, statistics = ("MME50", "MME75"), ("FWI", "FWI_P95")
    runs = [("historical", "historical")] + [
        (ssp, period) for ssp in inputs.SSP.values() for period in ("MID", "LATE")
    ]
    cell_fwi = {
        (ensemble, statistic, scenario, period): np.nanmean(
            inputs.fwi(scenario, period, variable=statistic, ensemble=ensemble), axis=0
        )
        for ensemble in ensembles
        for statistic in statistics
        for scenario, period in runs
    }
    weights, counties = inputs.county_weights()
    return cell_fwi, counties, ensembles, statistics, weights


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 2: multipliers under each regression

    Area-weighted county means skip cells with no data (the same rule as the rebuild). For
    each of the 2 × 2 FWI choices, fit gamma on historical county FWI, then build the four
    scenario columns both ways described above.
    """)
    return


@app.cell
def _(cell_fwi, counties, ensembles, inputs, np, pd, statistics, weights):
    def county_mean(values: np.ndarray) -> np.ndarray:
        valid = np.isfinite(values)
        with np.errstate(invalid="ignore", divide="ignore"):
            return (weights @ np.where(valid, values, 0.0)) / (weights @ valid.astype(float))

    _baseline = inputs.baseline()
    _all_fuels = inputs.county_fuel_shares()
    _fuels = _all_fuels.drop(columns="nonburnable")
    _burnable = (1.0 - _all_fuels["nonburnable"]).clip(lower=1e-3)
    _eal = _baseline["WFIR_EALT"]

    multipliers, gammas = {}, []
    for _ensemble in ensembles:
        for _statistic in statistics:
            _hist_cell = cell_fwi[(_ensemble, _statistic, "historical", "historical")]
            _hist = pd.Series(county_mean(_hist_cell), index=counties)
            _usable = (_eal > 0) & (_hist > 0) & _fuels.notna().all(axis=1) & _burnable.notna()
            _y = np.log(_eal[_usable].to_numpy())
            _log_fwi = np.log(_hist[_usable].to_numpy())

            # Simple: ln EAL on ln FWI and a constant.
            _X = np.column_stack([_log_fwi, np.ones(len(_y))])
            _gamma_simple = float(np.linalg.lstsq(_X, _y, rcond=None)[0][0])

            # Swarm: add fuel shares and ln(burnable share), weight by sqrt(burnable share).
            _w = np.sqrt(_burnable[_usable].to_numpy())
            _X = np.column_stack(
                [_log_fwi, _fuels[_usable], np.log(_burnable[_usable]), np.ones(len(_y))]
            )
            _gamma_swarm = float(np.linalg.lstsq(_X * _w[:, None], _y * _w, rcond=None)[0][0])

            _simple, _swarm = {}, {}
            for _warming, _ssp in inputs.SSP.items():
                for _period in ("MID", "LATE"):
                    _future_cell = cell_fwi[(_ensemble, _statistic, _ssp, _period)]
                    _column = f"WFIR_{_period}_{_warming}_HM"
                    with np.errstate(invalid="ignore", divide="ignore"):
                        _simple[_column] = county_mean((_future_cell / _hist_cell) ** _gamma_simple)
                    _swarm[_column] = (county_mean(_future_cell) / _hist.to_numpy()) ** _gamma_swarm
            multipliers[("simple", _ensemble, _statistic)] = pd.DataFrame(_simple, index=counties)
            multipliers[("swarm", _ensemble, _statistic)] = pd.DataFrame(_swarm, index=counties)
            gammas += [
                {
                    "regression": "simple",
                    "ensemble": _ensemble,
                    "statistic": _statistic,
                    "gamma": _gamma_simple,
                    "counties_in_fit": int(_usable.sum()),
                },
                {
                    "regression": "swarm",
                    "ensemble": _ensemble,
                    "statistic": _statistic,
                    "gamma": _gamma_swarm,
                    "counties_in_fit": int(_usable.sum()),
                },
            ]
    gammas = pd.DataFrame(gammas)
    gammas.round(3)
    return (multipliers,)


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 3: score against FEMA

    Mean over the four scenario columns. **log error** is the mean absolute difference of
    ln(HM), so 0.03 is about 3% off on average; it measures level. **Same bin** is the share
    of counties whose projected loss lands in the same NRI rating bin as FEMA's. **Pearson**
    and **Spearman** measure whether counties are ordered the same way.
    """)
    return


@app.cell
def _(data, multipliers, out, pd, scoring):
    key = data.conus(data.answer_key())
    _key_all = key.copy()
    _rows = []
    for (_regression, _ensemble, _statistic), _hm in multipliers.items():
        _scores, _ = scoring.score(key, _hm, ("train", "held_out"))
        _all = pd.DataFrame(
            [scoring.score_column(_key_all, _hm[c], c)[0] for c in _hm.columns]
        ).assign(subset="all")
        _mean = (
            pd.concat([_scores, _all])
            .groupby("subset")[["log_mae", "same_bin", "pearson", "spearman"]]
            .mean()
        )
        for _subset in ("train", "held_out", "all"):
            _rows.append(
                {
                    "regression": _regression,
                    "ensemble": _ensemble,
                    "statistic": _statistic,
                    "subset": _subset,
                }
                | _mean.loc[_subset].to_dict()
            )
    scores = pd.DataFrame(_rows)
    scores.to_csv(out / "scores.csv", index=False)
    scores[scores["subset"] == "held_out"].drop(columns="subset").round(3)
    return key, scores


@app.cell
def _(mo):
    mo.md(r"""
    **Check against the rebuild.** Two cells of this grid are exactly the rebuild's pipelines:
    simple + MME50 + mean is Claude Code agent 3 (held-out log error 0.027 there), and swarm +
    MME75 + P95 is the kept swarm pipeline (0.072). They come out about 0.001-0.002 higher
    here. The likely reason is that this run averages all 30 years per period, where the
    rebuild had 23-26; we can't confirm it because the rebuild didn't record which years it
    lacked. The gap is small next to the differences between cells.
    """)
    return


@app.cell
def _(scores):
    _held = scores[scores["subset"] == "held_out"].set_index(
        ["regression", "ensemble", "statistic"]
    )
    _checks = {
        ("simple", "MME50", "FWI"): 0.026682,
        ("swarm", "MME75", "FWI_P95"): 0.071809,
    }
    for _cell, _published in _checks.items():
        print(f"{_cell}: {_held.loc[_cell, 'log_mae']:.4f} here, {_published:.4f} in the rebuild")
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 4: the effect of each switch on its own

    Change in held-out log error and Pearson from switching one choice, with the other choice
    and the regression held fixed. Negative log error change is better; positive Pearson
    change is better.
    """)
    return


@app.cell
def _(out, pd, scores):
    _held = scores[scores["subset"] == "held_out"].set_index(
        ["regression", "ensemble", "statistic"]
    )
    _rows = []
    for _regression in ("simple", "swarm"):
        for _fixed in ("FWI", "FWI_P95"):
            _a, _b = (
                _held.loc[(_regression, "MME50", _fixed)],
                _held.loc[(_regression, "MME75", _fixed)],
            )
            _rows.append(
                {
                    "regression": _regression,
                    "switch": "MME50 -> MME75",
                    "held fixed": _fixed,
                    "log_mae_change": _b["log_mae"] - _a["log_mae"],
                    "pearson_change": _b["pearson"] - _a["pearson"],
                }
            )
        for _fixed in ("MME50", "MME75"):
            _a, _b = (
                _held.loc[(_regression, _fixed, "FWI")],
                _held.loc[(_regression, _fixed, "FWI_P95")],
            )
            _rows.append(
                {
                    "regression": _regression,
                    "switch": "mean -> P95",
                    "held fixed": _fixed,
                    "log_mae_change": _b["log_mae"] - _a["log_mae"],
                    "pearson_change": _b["pearson"] - _a["pearson"],
                }
            )
    effects = pd.DataFrame(_rows)
    effects.to_csv(out / "switch_effects.csv", index=False)
    effects.round(3)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## Step 5: where the choices differ

    The rebuild found northern New England and northern New York at 1.4-1.7× FEMA's values
    under P95, and blamed low historical fire weather there. Median ratio of rebuilt to
    published HM, late century, higher warming, for those states and for the rest of CONUS.
    """)
    return


@app.cell
def _(key, multipliers, np, out, pd):
    _northeast = key["STATEABBRV"].isin(["ME", "NH", "VT", "NY"])
    _rows = []
    for (_regression, _ensemble, _statistic), _hm in multipliers.items():
        _ratio = _hm["WFIR_LATE_HIGHER_HM"].reindex(key.index) / key["WFIR_LATE_HIGHER_HM"]
        _rows.append(
            {
                "regression": _regression,
                "ensemble": _ensemble,
                "statistic": _statistic,
                "ME/NH/VT/NY median ratio": float(np.nanmedian(_ratio[_northeast])),
                "rest of CONUS median ratio": float(np.nanmedian(_ratio[~_northeast])),
            }
        )
    regional = pd.DataFrame(_rows)
    regional.to_csv(out / "northeast_late_higher.csv", index=False)
    regional.round(2)
    return


@app.cell
def _(mo, scores):
    _held = scores[scores["subset"] == "held_out"].sort_values("log_mae")
    _best = _held.iloc[0]
    mo.md(rf"""
    ## Result

    Best held-out match of the eight: **{_best["regression"]} regression, {_best["ensemble"]},
    {_best["statistic"]}**, log error {_best["log_mae"]:.3f}, same bin {_best["same_bin"]:.1%},
    Pearson {_best["pearson"]:.3f}. Full grid in `results/scores.csv` (train, held-out and all
    counties); one-switch effects in `results/switch_effects.csv`.

    ## What this doesn't show

    - **Not which ensemble FEMA used**, only which public file reproduces its numbers best
      under two regressions. A different regression could favour a different choice.
    - **One climate model's grid, NASA's ensemble files.** FEMA averaged census blocks
      weighted by block EAL, which is not published; county area weights stand in for that.
    - MME25 and the other statistics (P25-P75, day counts) are not in this grid; the rebuild's
      log covers them under other regressions.
    """)
    return


if __name__ == "__main__":
    app.run()

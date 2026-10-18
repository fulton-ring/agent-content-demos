import marimo

__generated_with = "0.25.1"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import sys
    import time
    import types

    import marimo as mo
    import pandas as pd

    from fri_rebuild import data, scoring

    out = data.PROJECT_DIR / "results" / "rebuild"
    out.mkdir(parents=True, exist_ok=True)
    return data, json, mo, out, pd, scoring, sys, time, types


@app.cell
def _(mo):
    mo.md(r"""
    # Rebuilding FEMA's Future Risk Index with a swarm of agents

    **The question.** FEMA's Future Risk Index (FRI, December 2024) multiplied each county's
    expected annual loss (EAL) from the National Risk Index by a *hazard multiplier* (HM) for
    four futures: mid and late century, lower and higher warming. FEMA took the tool down in
    February 2025. Can agents working from FEMA's published methodology and public climate data
    rebuild those county multipliers?

    The FRI covers five hazards. For each one we wrote a first pipeline by hand from FEMA's
    *Future Risk Technical Documentation*, then let an agent loop improve it. Hurricane was not
    attempted: FEMA's input, Applied Research Associates' climate-conditioned landfall rates, is
    not public, and no public stand-in (STORM or RAFT tracks, Knutson et al.'s basin-scale
    factors) matches it. Building from one of those would be a different method, not a rebuild.

    This notebook reruns each hazard's final pipeline, scores it, and summarizes what the agents
    did. Three more notebooks take it further: `tracts.py` (below the county), `coastal.py`
    (why coastal flooding failed) and `charleston.py` (coastal multipliers built from buildings).
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## The data

    Everything is public and downloaded at run time into `$FRI_CACHE`
    (`fri_rebuild/data.py`); nothing downloaded is committed.

    - **The answer key**: FEMA's own *NRI Future Risk Master Datasheet* (12/05/2024), saved
      before the takedown and published in
      [fulton-ring/nri-future-risk](https://github.com/fulton-ring/nri-future-risk). It has the
      county HMs, the projected-loss ratings and the NRI v1.19 EAL each HM was applied to.
    - **Climate**: NASA [NEX-GDDP-CMIP6](https://registry.opendata.aws/nex-gddp-cmip6/) daily
      temperature, humidity and precipitation (0.25°, model MPI-ESM1-2-HR, the one FEMA used)
      for drought and NEX heat; [LOCA2](https://cirrus.ucsd.edu/~pierce/LOCA2/) daily minimum
      temperature (1/16°, same model) for LOCA2 heat; NASA's
      [NEX-GDDP-CMIP6 Fire Weather Index](https://data.nas.nasa.gov/gddpimpact/FWI/)
      ensemble files for wildfire. The FWI portal is missing 4-7 of the 30 years in each
      period; those years are skipped.
    - **Fuels**: LANDFIRE LF2022 fuel models, resampled to 500 m.
    - **Coastal**: NOAA tide-gauge high-tide-flooding projections and counts, flood thresholds,
      and the 2022 Sea Level Rise Technical Report's return levels and sea level projections.
    - **Boundaries**: Census 2020 counties. Scope is the contiguous US (3,108 counties), as in
      FEMA's documentation for its climate inputs.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## How a rebuild is scored

    We put each rebuilt county's projected loss (EAL × HM) into FEMA's fixed NRI rating bins and
    ask whether it lands in the same bin as FEMA's. A bin's upper edge is the largest EAL
    published in that rating (FRI Section 3.2). We also report Pearson correlation and the mean
    absolute log error, `log_mae` = mean |ln(rebuilt / published)|: 0.1 means typically about
    10% off. A county a pipeline leaves blank counts as HM = 1, so leaving hard counties blank
    can't help, and counties FEMA published at HM = 0 are left out (only coastal flooding has
    any). The code is `fri_rebuild/scoring.py`, shared with the agent loop.

    **First check: the bins.** Applied to FEMA's own multipliers, the bins should reproduce
    FEMA's published projected-loss ratings exactly.
    """)
    return


@app.cell
def _(data, pd, scoring):
    key = data.conus(data.answer_key())
    _matches = {}
    for _column in [c for c in key if c.endswith("_HM")]:
        _hazard, _theirs = (
            _column[:4],
            key[_column.replace("_HM", "_PALR")].map(scoring.rating_name),
        )
        _loss = key[_column].clip(lower=1) * key[f"{_hazard}_EALT"]
        _ours = scoring.rate(_loss, scoring.rating_thresholds(key, _hazard))
        _rated = _theirs.notna() & key[_column].notna()
        _matches[_column] = (_ours == _theirs)[_rated].mean()
    pd.Series(_matches, name="share of PAL ratings reproduced").describe()[["count", "min"]]
    return (key,)


@app.cell
def _(mo):
    mo.md(r"""
    ## The split, and how the agents worked

    Every fourth state in FIPS order is held out: 12 states and 896 counties (AZ, CT, GA, IA,
    ME, MN, NE, NM, OH, RI, TX, WA). The agents saw scores for the 2,212 training counties only;
    held-out scores were computed after the loop ended.

    **The loop** (`fri_rebuild/swarm.py`, modelled on
    [karpathy/autoresearch](https://github.com/karpathy/autoresearch)). Each hazard has one
    file the agents may change, `hazards/<hazard>/pipeline.py`, and a human-written brief next
    to it, `program.md`: what FEMA's document says, what the data looks like, and numbered open
    questions. Each round, three agents (Pydantic AI, `anthropic/claude-sonnet-5.5` through
    OpenRouter, temperature 0.8) propose in parallel. Each gets the brief, the current best
    pipeline, its training scores with the worst states, the experiment log and notes on earlier
    hypotheses, and returns a complete new file. The harness rejects code that names the answer
    key, the scorer or the split, skips code identical to an earlier run, runs each candidate in
    a subprocess, and keeps the round's best if it beats the current best by more than 0.002.
    From the coastal run on, agents could call a read-only `describe_input` tool to look at
    input tables. Every proposal, with its code, is a line of `experiments.jsonl`.

    The loop is not rerun here: it costs money and gives different results each run
    (`uv run fri-swarm drought --rounds 8 --agents 3 --budget 3`, needs `OPENROUTER_API_KEY`).
    What this notebook reruns is each hazard's final, kept pipeline.
    """)
    return


@app.cell
def _(sys, time, types):
    def run_pipeline(code: str, name: str) -> tuple:
        """Run a pipeline's source code: its county multipliers and the seconds it took."""
        module = types.ModuleType(name)
        sys.modules[name] = module  # dataclasses look their module up by name
        exec(compile(code, name, "exec"), module.__dict__)  # noqa: S102 - our own record
        started = time.time()
        return module.hazard_multipliers(), time.time() - started

    return (run_pipeline,)


@app.cell
def _(data, key, out, pd, run_pipeline, scoring):
    hazards = {
        "extreme_heat_loca2": "Extreme heat, LOCA2",
        "drought": "Drought",
        "wildfire": "Wildfire",
        "extreme_heat": "Extreme heat, NEX",
        "coastal_flooding": "Coastal flooding",
    }
    rebuilt, scores, details, seconds = {}, [], [], {}
    for _hazard, _label in hazards.items():
        _code = (data.PROJECT_DIR / "hazards" / _hazard / "pipeline.py").read_text()
        rebuilt[_hazard], seconds[_label] = run_pipeline(_code, _hazard)
        _scores, _detail = scoring.score(key, rebuilt[_hazard], ("train", "held_out"))
        scores.append(_scores.assign(hazard=_label))
        details.append(_detail)
    scores = pd.concat(scores)
    pd.concat(rebuilt.values(), axis=1).sort_index().rename_axis("fips").to_csv(
        out / "county_hm.csv"
    )
    scores.to_csv(out / "scores.csv", index=False)
    pd.Series(seconds, name="pipeline seconds").round()
    return details, hazards, scores


@app.cell
def _(mo):
    mo.md(r"""
    ## Results

    Mean over the four scenarios (and, for heat, both thresholds), training and held-out states.
    Per-column numbers are in `results/rebuild/scores.csv`.
    """)
    return


@app.cell
def _(hazards, out, pd, scores):
    headline = (
        scores.groupby(["hazard", "subset"], sort=False)
        .agg(
            counties=("counties", "first"),
            same_bin=("same_bin", "mean"),
            pearson=("pearson", "mean"),
            log_mae=("log_mae", "mean"),
            median_ratio=("median_ratio", "mean"),
        )
        .reindex(pd.MultiIndex.from_product([list(hazards.values()), ["train", "held_out"]]))
    )
    headline.to_csv(out / "headline.csv")
    headline.round(3)
    return (headline,)


@app.cell
def _(headline, mo, scores):
    _held = headline.xs("held_out", level=1)
    _loca2, _drought = _held.loc["Extreme heat, LOCA2"], _held.loc["Drought"]
    _fire, _nex, _cfld = (
        _held.loc["Wildfire"],
        _held.loc["Extreme heat, NEX"],
        _held.loc["Coastal flooding"],
    )
    _n99 = scores[
        (scores["hazard"] == "Extreme heat, NEX")
        & (scores["subset"] == "held_out")
        & scores["column"].str.contains("N99")
    ]
    mo.md(f"""
    On the held-out states:

    - **LOCA2 heat and drought are rebuilt essentially exactly**: {_loca2["same_bin"]:.1%} and
      {_drought["same_bin"]:.1%} of counties in the same rating bin, typical error
      {_loca2["log_mae"]:.3f} and {_drought["log_mae"]:.3f}.
    - **Wildfire is close**: {_fire["same_bin"]:.1%} same bin, Pearson {_fire["pearson"]:.3f}.
    - **NEX heat is a partial match**: {_nex["same_bin"]:.1%} same bin. The 95th-percentile
      threshold is good; the 99th runs low, at a median {_n99["median_ratio"].min():.2f} to
      {_n99["median_ratio"].max():.2f} of FEMA's.
    - **Coastal flooding is not rebuilt**: Pearson {_cfld["pearson"]:.2f}. Levels are roughly
      right (median ratio {_cfld["median_ratio"]:.2f}), the ranking is not.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## The largest differences, and why

    The five largest misses per column and subset (all of them are in
    `results/rebuild/largest_differences.csv`).

    - **LOCA2 heat.** Almost every county is within a few percent. The exceptions are small
      Virginia independent cities (Alexandria, Falls Church, Manassas and others), which FEMA
      publishes at L99 = 1.0 and we put at 14-21. FEMA's raster-to-county step probably gave
      these few-square-mile cities no 6 km cell. Our county weights are not exact either: every
      grid is drawn as 0.25° boxes around its cell centres (`data.area_weights`), so LOCA2's
      1/16° cells are smoothed over about 25 km. That is how these numbers were made.
    - **Drought.** The largest misses are small or coastal counties (Richmond and Kings, NY;
      Jackson, MS), off by 12-21%. They overlap one or two 25 km cells, some mostly ocean.
    - **Wildfire.** Northern New England and northern New York come out 1.4-1.7× FEMA's. Fire
      weather there is low today, so a small increase is a large ratio, and the 95th-percentile
      statistic the agents chose amplifies it. FEMA weighted by census-block EAL, which is not
      published.
    - **NEX heat.** The 99th percentile in Oklahoma and northeast Texas comes out at about 0.4×
      FEMA's. LOCA2 heat follows the same method with the same climate model, but with a fixed
      temperature floor instead of a heat index, and matches FEMA almost exactly. That isolates
      the heat-index step: FEMA cites Lu and Romps (2022) for its 298 K threshold but gives no
      formula, and NEX has only daily means of temperature and humidity.
    - **Coastal flooding.** No approach got the ranking right. Fredericksburg, VA (inland) is
      published at 429 late century, San Diego at 254, Galveston at 33; every approach put them
      near 5-30. FEMA weights each flood severity by its share of county EAL and clips
      levee-protected areas, and neither is public. `coastal.py` works out what FEMA did.
    """)
    return


@app.cell
def _(details, out, pd):
    _all = pd.concat(details)
    largest = (
        _all.assign(abs_log_error=_all["log_error"].abs())
        .sort_values("abs_log_error", ascending=False)
        .groupby(["column", "subset"])
        .head(5)
        .sort_values(["column", "subset", "abs_log_error"], ascending=[True, False, False])
    )
    largest.to_csv(out / "largest_differences.csv")
    largest.round(3)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ## What the agents did

    The experiment record, per hazard: rounds, proposals, how many the harness kept, model
    cost (as logged per OpenRouter response) and the summed run time of the pipelines.
    """)
    return


@app.cell
def _(data, hazards, json, out, pd):
    record = pd.DataFrame(
        json.loads(line) for line in (data.PROJECT_DIR / "experiments.jsonl").open()
    )
    _swarm = record[record["harness"] == "swarm"]
    _agents = _swarm[(_swarm["round"] > 0) & (_swarm["status"] != "resume")]
    loop = (
        pd.DataFrame(
            {
                "rounds": _agents.groupby("hazard")["round"].max(),
                "proposals": _agents.groupby("hazard").size(),
                "ran": _agents.groupby("hazard")["metric_log_mae"].count(),
                "kept": _agents[_agents["status"] == "keep"].groupby("hazard").size(),
                "crashed": _agents[_agents["status"] == "crash"].groupby("hazard").size(),
                "baseline_train_log_mae": _swarm[_swarm["round"] == 0]
                .groupby("hazard")["metric_log_mae"]
                .first(),
                "best_train_log_mae": _swarm[_swarm["status"] == "keep"]
                .groupby("hazard")["metric_log_mae"]
                .min(),
                "pipeline_minutes": _swarm.groupby("hazard")["seconds"].sum() / 60,
                "model_cost_usd": _swarm.groupby("hazard")["cost_usd"].sum(),
            }
        )
        .reindex(list(hazards))
        .fillna({"crashed": 0})
    )
    loop.to_csv(out / "swarm_summary.csv")
    loop.round(3)
    return loop, record


@app.cell
def _(loop, mo, record):
    _bug = record[record["harness"] == "swarm-guard-bug"]
    mo.md(f"""
    In all, **{int(loop["proposals"].sum())} proposals for ${loop["model_cost_usd"].sum():.2f}** of
    model calls (the issue's budget was $25), plus {int((_bug["status"] == "rejected").sum())}
    lost to an early harness bug (${_bug["cost_usd"].sum():.2f}). Everything ran on one 4-core,
    16 GB machine. Coastal cost the most once agents could call `describe_input`: up to $0.61 a
    proposal against about $0.03 without it.

    - **Drought**: the decisive change, in round 4, was computing the Thornthwaite heat index per
      calendar year instead of from the whole series (training error 0.135 → 0.031). With
      3-month SPEI, a generalized-logistic fit, 1950-2010 calibration and the −1.6 threshold,
      that reproduces FEMA almost exactly. A kept 15-day floor on historical drought days did
      not overfit (held-out error stayed as low).
    - **Wildfire**: the human baseline used state fixed effects and got an elasticity below the
      "greater than 1" FEMA states; dropping spatial fixed effects did most of the work. The
      agents then moved to the 75th-percentile ensemble, the 95th-percentile FWI statistic, a
      log burnable-share control and burnable-share weights. Each helped on training states; on
      held-out states they lowered correlation while improving log error (table below).
    - **NEX heat**: one kept change, dividing by the historical number of days over the
      percentile without the heat-index condition, which reads FEMA's equation 9 more literally.
      Nothing after it helped, and a person's nudge after round 4 made all three agents try the
      same worse idea, then submit byte-identical code.
    - **LOCA2 heat**: the human baseline already matched FEMA, since it carried over what the
      NEX run taught. The agents kept one change, interpolating inside the 0.1 °C histogram
      bins, which removes a rounding artifact of our own data reduction.
    - **Coastal**: the biggest step was using the projections' own 2020 decade as today's
      frequency instead of observed counts. After that they tuned which decade counts as today
      and the weight of each flood severity; training error fell, held-out correlation never
      rose above the human baseline's.
    """)
    return


@app.cell
def _(mo):
    mo.md(r"""
    ### Every kept pipeline, and the Claude Code subagents, on held-out states

    Scored after the fact, so it is reported, not used to pick anything: choosing among them
    with held-out scores would contaminate the held-out set.

    We also ran wildfire and coastal flooding a second way: Claude Code subagents (Sonnet), each
    starting from the human baseline with the same rules and brief, steered to different open
    questions. Each ran 6-10 experiments in 2-3 minutes and 42-62k tokens, and unlike the
    Pydantic AI agents they could read the data and run code. **Nothing stopped them reading the
    answer key or held-out scores**: they had a shell in the project with the answer key in the
    cache. Their rules forbade it and their logs record only training scores, but that was an
    instruction, not a wall. Read their held-out numbers with that in mind.
    """)
    return


@app.cell
def _(key, out, pd, record, run_pipeline, scoring):
    _rows = []
    _kept = record[
        ((record["harness"] == "swarm") & (record["status"] == "keep") & record["code"].notna())
        | ((record["harness"] == "claude-code-subagent") & (record["status"] == "final"))
    ]
    for _, _entry in _kept.iterrows():
        _label = (
            f"{_entry['id']} {_entry['description']}"
            if _entry["harness"] == "swarm"
            else f"Claude Code subagent {_entry['run']}"
        )
        _hm, _ = run_pipeline(_entry["code"], f"{_entry['hazard']}_{_entry['id']}_{_entry['run']}")
        _scores, _ = scoring.score(key, _hm, ("train", "held_out"))
        _mean = _scores.groupby("subset")[["log_mae", "same_bin", "pearson"]].mean()
        _rows.append(
            {"hazard": _entry["hazard"], "pipeline": _label}
            | {
                f"{subset}_{metric}": _mean.loc[subset, metric]
                for subset in ("train", "held_out")
                for metric in ("log_mae", "same_bin", "pearson")
            }
        )
    kept = pd.DataFrame(_rows)
    kept.to_csv(out / "kept_pipelines_held_out.csv", index=False)
    kept.round(3)
    return


@app.cell
def _(mo):
    mo.md(r"""
    Wildfire Claude Code agent 3 found the simplest specification, a plain log-log regression
    of wildfire EAL on historical mean FWI with no fuel controls, and it beats everything else
    on both sets. It drops the fuel-type controls FEMA documents, and the agent flagged that
    itself. We did not swap it in: the final pipeline is the one the swarm's own rule chose.

    ## Every point where a person stepped in

    1. **Prime Agent** (the harness the issue asked for) could not be installed: its only route
       is a downloaded installer script, which the session sandbox blocked. We built the loop
       with Pydantic AI instead.
    2. **Modal was unreachable**: its gRPC client can't get through this environment's proxy.
       All data reduction ran locally.
    3. **The answer-key guard rejected valid code.** The first wildfire round lost all three
       proposals to banned patterns every pipeline needs. The person removed them and
       restarted; that run is kept in `experiments.jsonl` as harness `swarm-guard-bug`.
    4. **Kept code needed tidying**: an unused table and two type-check errors, fixed without
       changing results. The harness does not lint candidates.
    5. **NEX heat stalled, and the person's nudge backfired** (above).
    6. **Duplicate proposals**: a check was added that skips code identical to an earlier run.
    7. **Bookkeeping fixes** in the report: a resume row counted as a proposal, and the best
       score taken over discarded rows.
    8. **Coastal: a note pointing to the 187-gauge route** after ten rounds without a gain in
       correlation: FEMA's 187 gauges are exactly the 2022 report's extreme-water-level gauges.
    9. **Coastal: silent fallbacks.** The next attempts at that route guessed column names,
       crashed inside a `try/except` the agent had written, and silently fell back to the old
       method. The Pydantic AI agents could not see the data, only scores; the person added
       `describe_input` and a rule against fallbacks. The route then ran, but no better.
    10. **Data plumbing**: a dropped NEX download and a dropped LOCA2 read needed retries, and a
        container restart interrupted the LOCA2 reduction.
    11. **The LOCA2 bin width** (0.1 °C) was the person's choice; the agents fixed its rounding.
    12. **Held-out leak, coastal**: the note in 8 says the old method's held-out score.
    13. **Held-out leak, LOCA2**: its brief names Texas, a held-out state, among the states where
        NEX heat ran low. More broadly, the LOCA2 and coastal briefs were written after the
        person had seen earlier hazards' held-out scores. The drought, wildfire and NEX briefs
        were written before any held-out score existed.

    Neither leak is large: coastal still ended at held-out correlation 0.28, and the LOCA2
    baseline matched FEMA before the agents ran. But for those two hazards the held-out scores
    are not fully blind. The Pydantic AI agents never tried to reach the answer key once the
    guard was fixed, and every kept change is a method choice that can be read in its diff.

    ## What this doesn't show

    - **Hurricane** was not attempted, and **coastal flooding** was attempted and not rebuilt.
    - **NEX heat** is only partly rebuilt: we could not reproduce FEMA's heat-index filter.
    - **Alaska, Hawaii and the territories** were not rebuilt.
    - **Wildfire fit its training set**: the agents' later steps improved training error at some
      cost to held-out correlation. Coastal shows the same pattern more strongly.
    - **One climate model, one run**: the results describe how closely FEMA's numbers can be
      reproduced, not how uncertain they are.
    """)
    return


if __name__ == "__main__":
    app.run()

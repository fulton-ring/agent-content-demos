import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import json
    import logging
    import os
    import time
    from pathlib import Path

    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    log = logging.getLogger("aging")
    here = Path(mo.notebook_dir() or ".")
    results = Path(os.environ.get("AGING_RESULTS", here / "results"))
    results.mkdir(parents=True, exist_ok=True)
    started = time.time()
    return json, log, mo, np, pd, plt, results, started, time


@app.cell
def _(mo):
    mo.md(r"""
    # Ranking aging electrical equipment by exposure to load growth

    **Question.** Given one plant's equipment list (type, age, rating), its test records and
    its meter data, can a ranking pick out the ten assets most likely to fail in the next three
    years under the load they now carry, and say for each whether to replace it, extend its life
    or test it again? And how much better is that than ranking by age alone?

    **Data.** Real plant records are private. We looked for public data first: the public
    transformer datasets we found (dissolved-gas and health-index sets) have test readings but
    no loading and no recorded failures, so they can't be used to measure a failure ranking.
    So this notebook **builds a synthetic plant** from published parameters, simulates which
    assets fail, hides those failures from the ranking, and counts how many it catches. Every
    number below comes from that simulation, not from a real plant.
    """)
    return


@app.cell
def _(mo, pd):
    mo.md(r"""
    ## 1. Published parameters the plant is built from

    - **Failure rates** (failures per unit-year): liquid-filled transformers 0.0062 (IEEE 493,
      1979 survey), metal-clad breakers 0.0036 (IEEE 493-1980 Table 24, 58 failures in 16,280
      unit-years), large industrial motors 0.0708 (IEEE-IAS 1985 survey, 200 hp and up).
    - **Share of failures that are thermal/insulation ageing**, the part load drives: our
      assumption from the cause splits (motors: stator windings 26%, bearings 44%, IEEE-IAS).
    - **Ageing physics.** Transformers: IEEE C57.91 ageing acceleration factor
      $F_{AA} = e^{15000/383 - 15000/(\theta_H+273)}$, with a normal insulation life of
      180,000 hours (20.55 years) at a 110 °C hot spot, and the IEEE C57.91 / IEC 60076-7
      hot-spot model for an ONAN unit (top-oil rise 55 °C, hot-spot gradient 25 °C, loss ratio
      5, exponents 0.8). Motors and switchgear: insulation life halves for every 10 °C
      (EASA), with temperature rise proportional to load squared.
    - **Assumptions we chose** (and test where they matter): motor reference life 12.9 years
      at full load and 40 °C (Class F, 20,000 h at 155 °C, Class B rise), switchgear 30 years
      at rated current, Weibull shape 3 on consumed life, and the plant's mix, ages and loading.
    """)
    types = pd.DataFrame(
        [
            # n, rate, thermal share, normal life (yr), expected service life (yr), age mode,
            # max age, mean loading, max loading, share with a test, test noise, meter error
            ("transformer", 40, 0.0062, 0.6, 20.55, 40, 30, 55, 0.80, 1.3, 0.8, 0.30, 0.03),
            ("switchgear", 90, 0.0036, 0.4, 30.0, 40, 30, 55, 0.70, 1.1, 0.6, 0.40, 0.05),
            ("motor", 120, 0.0708, 0.3, 12.9, 25, 12, 40, 0.75, 1.15, 0.5, 0.35, 0.15),
        ],
        columns=[
            "kind",
            "n",
            "rate",
            "thermal_share",
            "normal_life",
            "service_life",
            "age_mode",
            "age_max",
            "load_mean",
            "load_max",
            "test_share",
            "test_noise",
            "meter_error",
        ],
    ).set_index("kind")
    monthly_ambient = [0, 2, 7, 13, 18, 23, 26, 25, 21, 14, 8, 2]  # outdoor °C, temperate US
    indoor_offset = 10  # motors and switchgear sit indoors, warmer than outside
    past_growth = 0.03  # plant load grew 3%/yr for the last five years
    bus_exposure = [0.25, 0.75, 1.0, 2.0]  # bus D carries the new production line
    beta = 3.0
    growth_cases = {"low": 0.01, "base": 0.04, "high": 0.08}
    types
    return (
        beta,
        bus_exposure,
        growth_cases,
        indoor_offset,
        monthly_ambient,
        past_growth,
        types,
    )


@app.cell
def _(indoor_offset, mo, monthly_ambient, np):
    mo.md(r"""
    ## 2. How load ages each kind of equipment

    One function turns a peak loading (per unit of rating) into how many "normal years" of
    insulation life the asset uses up per calendar year. It averages over twelve months of
    ambient temperature and a daily cycle of 8 hours at peak and 16 hours at 70% of peak, since
    ageing is steeply non-linear and the peak hours do most of the damage.
    """)

    def ageing_rate(kind: str, peak_load: np.ndarray) -> np.ndarray:
        """Normal-life years consumed per calendar year at this peak loading."""
        ambient = np.array(monthly_ambient, dtype=float)[None, :, None]
        load = np.asarray(peak_load, dtype=float)[:, None, None] * np.array([1.0, 0.7])
        if kind == "transformer":
            top_oil = 55 * ((load**2 * 5 + 1) / 6) ** 0.8
            hot_spot = ambient + top_oil + 25 * load**1.6
            factor = np.exp(15000 / 383 - 15000 / (hot_spot + 273))
        elif kind == "motor":
            factor = 2 ** ((ambient + indoor_offset + 90 * load**2 - 130) / 10)
        elif kind == "switchgear":
            factor = 2 ** ((ambient + indoor_offset + 65 * load**2 - 105) / 10)
        else:
            raise ValueError(kind)
        return (factor * np.array([8, 16]) / 24).sum(axis=2).mean(axis=1)

    _loads = np.array([0.6, 0.8, 1.0, 1.1, 1.2])
    {
        k: dict(zip(_loads, ageing_rate(k, _loads).round(3), strict=True))
        for k in ("transformer", "switchgear", "motor")
    }
    return (ageing_rate,)


@app.cell
def _(mo):
    mo.md(r"""
    The table above is the core of the argument: at 120% of rating a transformer ages about
    11 times faster than at 100%, a motor about 15 times and switchgear about 6 times. A few
    points of load growth on an already heavily loaded asset matter more than its age.

    ## 3. A synthetic plant

    250 assets: 40 transformers, 90 switchgear sections and 120 large motors, spread across
    four buses. Ages skew old (underinvestment). Each asset also carries things a reliability
    engineer can't see directly, and the ranking never gets: a hidden **quality factor** on how
    fast it ages (cooling, manufacturing, installation), a hidden **other-cause factor**
    (bearings, mechanical, external damage), and the true loading behind a meter reading that
    is off by 3% (transformers, metered directly) to 15% (motors, estimated from the motor
    control centre). What the engineer does see: type, age, bus, metered peak load, and for
    some assets a condition test (oil furan for transformers, thermography and contact
    resistance for switchgear, insulation and vibration tests for motors) taken 0 to 6 years
    ago, which reads the true consumed life with noise.
    """)
    return


@app.cell
def _(ageing_rate, beta, bus_exposure, np, past_growth, pd, types):
    def consumed_life(plant: pd.DataFrame, load_col: str, years_back: pd.Series) -> np.ndarray:
        """Normal lives used up to `years_back` years ago, from the loading history.

        Loading grew at the plant's past growth rate for five years and was flat before that.
        """
        used = np.zeros(len(plant))
        for kind, t in types.iterrows():
            rows = (plant["kind"] == kind).to_numpy()
            p = plant.loc[rows]
            back = np.asarray(years_back, dtype=float)[rows]
            growth = 1 + past_growth * p["exposure"].to_numpy()
            age = p["age"].to_numpy()
            for j in range(1, 6):
                rate = ageing_rate(str(kind), p[load_col].to_numpy() * growth**-j)
                used[rows] += rate * np.clip(age - (j - 1), 0, 1) * (j > back)
            flat_years = np.maximum(age - np.maximum(5, back), 0)
            used[rows] += rate * flat_years
            used[rows] /= t["normal_life"]
        return used

    def make_plants(n_plants: int, seed: int, eta: dict[str, float]) -> pd.DataFrame:
        """Generate n_plants synthetic plants with true and observed fields for every asset.

        `eta` is the characteristic consumed life (in normal lives) at which thermal failures
        happen, per kind. Any asset whose true consumed life already passed its own drawn
        failure point was replaced at some earlier date, so its age is redrawn (three passes).
        """
        rng = np.random.default_rng(seed)
        frames = []
        for kind, t in types.iterrows():
            n = int(t["n"]) * n_plants
            frames.append(
                pd.DataFrame(
                    {
                        "plant": np.repeat(np.arange(n_plants), int(t["n"])),
                        "kind": kind,
                        "age": rng.triangular(1, t["age_mode"], t["age_max"], n).round(),
                        "bus": rng.integers(0, len(bus_exposure), n),
                        "load_true": np.clip(
                            rng.normal(t["load_mean"], 0.17, n), 0.3, t["load_max"]
                        ),
                        "quality": rng.lognormal(-0.08, 0.4, n),
                        "other": rng.lognormal(-0.18, 0.6, n),
                        "meter_bias": rng.lognormal(0, t["meter_error"], n),
                        "tested": rng.random(n) < t["test_share"],
                        "test_age": rng.integers(0, 7, n),
                        "test_noise": rng.lognormal(0, t["test_noise"], n),
                        "vibration_noise": rng.lognormal(0, 0.5, n),
                        "fails_at": eta[str(kind)] * rng.weibull(beta, n),
                    }
                )
            )
        plant = pd.concat(frames, ignore_index=True)
        plant["exposure"] = np.array(bus_exposure)[plant["bus"]]
        for _ in range(3):
            used = plant["quality"] * consumed_life(
                plant, "load_true", pd.Series(np.zeros(len(plant)))
            )
            burned_out = (used > plant["fails_at"]).to_numpy()
            plant.loc[burned_out, "age"] = np.floor(rng.uniform(1, plant.loc[burned_out, "age"]))
        cap = plant["kind"].map(types["load_max"])
        plant["load_meter"] = np.clip(plant["load_true"] * plant["meter_bias"], 0.3, cap)
        plant["test_age"] = np.minimum(plant["test_age"], plant["age"])
        return plant

    return consumed_life, make_plants


@app.cell
def _(mo):
    mo.md(r"""
    ## 4. The ranking, and what each version is allowed to see

    Every version uses the same failure model: a Weibull curve on **consumed insulation life**
    (not calendar age), so the cumulative hazard over the next three years is
    $c\,(u_3^\beta - u_0^\beta)$ where $u$ grows by the ageing rate at each year's projected
    load, plus a constant other-cause hazard. What changes is the input:

    - **truth**: true loading, hidden quality and other-cause factors, actual load growth.
      This is what decides who fails; no ranking sees it.
    - **full ranking**: metered load, the assumed load growth on each bus, and test results
      where they exist. A test tells us how far along an asset really is, so it also gives
      that asset's own ageing speed relative to the nominal curve. A motor vibration test
      gives a noisy read on the other-cause factor.
    - **age + load**: metered load and growth, no tests.
    - **age only**: type and nameplate age; every asset assumed at its type's average load.

    Each version's scale $c$ is calibrated so its plant-wide failure rate matches the
    published IEEE rate, the way an engineer would fit a curve to survey data.
    """)
    return


@app.cell
def _(ageing_rate, beta, consumed_life, np, pd, types):
    def three_year_hazard(
        plant: pd.DataFrame,
        view: str,
        growth: float,
        shape: float = beta,
        scale: dict[str, float] | None = None,
    ) -> tuple[np.ndarray, np.ndarray]:
        """Return (thermal hazard term u3^b - u0^b before scaling, other-cause hazard)."""
        assert view in ("truth", "full", "age_load", "age_only"), view
        if view == "truth":
            load = plant["load_true"]
        elif view == "age_only":
            load = plant["kind"].map(types["load_mean"])
        else:
            load = plant["load_meter"]
        p = plant.assign(view_load=load.to_numpy())
        u_nominal = consumed_life(p, "view_load", pd.Series(np.zeros(len(p))))
        speed = np.ones(len(p))
        other = np.ones(len(p))
        if view == "truth":
            speed = p["quality"].to_numpy()
            other = p["other"].to_numpy()
        elif view == "full":
            at_test = consumed_life(p, "view_load", p["test_age"])
            true_at_test = p["quality"] * consumed_life(p, "load_true", p["test_age"])
            read = true_at_test * p["test_noise"]
            ratio = np.clip(read / np.maximum(at_test, 1e-3), 0.3, 3.0)
            speed = np.where(p["tested"], ratio, 1.0)
            motor_test = p["tested"] & (p["kind"] == "motor")
            other = np.where(motor_test, p["other"] * p["vibration_noise"], 1.0)
        u = speed * u_nominal
        u_start = u.copy()
        for year in range(1, 4):
            for kind, t in types.iterrows():
                rows = (p["kind"] == kind).to_numpy()
                yearly = p.loc[rows, "view_load"] * (1 + growth * p.loc[rows, "exposure"]) ** year
                u[rows] += (
                    speed[rows] * ageing_rate(str(kind), yearly.to_numpy()) / t["normal_life"]
                )
        thermal = u**shape - u_start**shape
        rate = p["kind"].map(types["rate"] * (1 - types["thermal_share"])).to_numpy()
        hazard_other = 3 * rate * other
        if scale is not None:
            thermal = thermal * p["kind"].map(scale).to_numpy()
        return thermal, hazard_other

    def calibrate(plant: pd.DataFrame, view: str, growth: float, shape: float = beta) -> dict:
        """Scale c per kind so the view's mean thermal hazard matches the published rate."""
        thermal, _ = three_year_hazard(plant, view, growth, shape)
        target = types["rate"] * types["thermal_share"] * 3
        mean = pd.Series(thermal).groupby(plant["kind"].to_numpy()).mean()
        return (target / mean).to_dict()

    def risk(
        plant: pd.DataFrame, view: str, growth: float, scale: dict, shape: float = beta
    ) -> np.ndarray:
        """Cumulative three-year hazard H; the chance of failing is 1 - exp(-H).

        Rankings sort on H rather than on the probability, which rounds to 1.0 at the top.
        """
        thermal, other = three_year_hazard(plant, view, growth, shape, scale)
        return thermal + other

    def rank_in_plant(plants: pd.DataFrame, score: np.ndarray) -> np.ndarray:
        """Rank 1 = highest score, within each plant; ties broken by order."""
        grouped = pd.Series(score).groupby(plants["plant"].to_numpy())
        return grouped.rank(ascending=False, method="first").to_numpy()

    return calibrate, rank_in_plant, risk, three_year_hazard


@app.cell
def _(mo):
    mo.md(r"""
    **Calibration.** The truth model's Weibull scale $\eta$ (consumed life at which thermal
    failures happen) is set so the surviving plant fails at the published IEEE rate. Because
    the plant is built by replacing assets that would already have burned out, which depends
    on $\eta$, we iterate a few times on 200 reference plants that are never scored. Then each
    ranking fits its own scale $c$ to the same published rates on its own inputs.
    """)
    return


@app.cell
def _(beta, calibrate, growth_cases, log, make_plants, time, types):
    _t = time.time()
    eta = dict.fromkeys(types.index, 1.0)
    for _round in range(8):
        reference = make_plants(200, seed=10_000, eta=eta)
        _c = calibrate(reference, "truth", growth_cases["base"])
        _new = {k: c ** (-1 / beta) for k, c in _c.items()}
        _shift = max(abs(_new[k] / eta[k] - 1) for k in eta)
        eta = _new
        log.info("eta round %d: %s (moved %.1f%%)", _round, eta, 100 * _shift)
        if _shift < 0.01:
            break
    reference = make_plants(200, seed=10_000, eta=eta)
    scales = {
        view: calibrate(reference, view, growth_cases["base"])
        for view in ("truth", "full", "age_load", "age_only")
    }
    log.info("calibrated on %d reference assets in %.1fs", len(reference), time.time() - _t)
    {"eta (normal lives)": eta, "scale c": scales}
    return eta, reference, scales


@app.cell
def _(mo):
    mo.md(r"""
    ## 5. Hold out the failures and count what each ranking catches

    1,000 fresh synthetic plants. In each, the truth model decides which assets fail in the
    next three years (load grows at the base 4% a year, scaled by each bus's exposure). The
    rankings never see those failures. For each plant we take each ranking's top ten and
    top 10% (25 assets) and count the failures inside them.
    """)
    return


@app.cell
def _(eta, growth_cases, make_plants, np, pd, rank_in_plant, risk, scales):
    def score_plants(
        plants: pd.DataFrame,
        failed: np.ndarray,
        assumed_growth: float,
        shape_scales: dict,
        shape: float,
    ) -> pd.DataFrame:
        """Share of held-out failures inside each ranking's top 10 and top 10%.

        `share` pools all plants; plant_p5 and plant_p95 bound what a single plant sees.
        """
        rows = []
        for view in ("full", "age_load", "age_only"):
            score = risk(plants, view, assumed_growth, shape_scales[view], shape)
            rank = rank_in_plant(plants, score)
            for label, k in (("top 10", 10), ("top 10%", 25)):
                inside = (rank <= k) & failed
                per_plant = pd.DataFrame({"plant": plants["plant"], "in": inside, "f": failed})
                sums = per_plant.groupby("plant")[["in", "f"]].sum()
                plant_share = (sums["in"] / sums["f"])[sums["f"] > 0]
                rows.append(
                    {
                        "ranking": view,
                        "cut": label,
                        "caught": int(sums["in"].sum()),
                        "failures": int(sums["f"].sum()),
                        "share": sums["in"].sum() / sums["f"].sum(),
                        "plant_p5": plant_share.quantile(0.05),
                        "plant_p95": plant_share.quantile(0.95),
                    }
                )
        return pd.DataFrame(rows)

    holdout = make_plants(1000, seed=1, eta=eta)
    _truth_h = risk(holdout, "truth", growth_cases["base"], scales["truth"])
    failed = np.random.default_rng(2).random(len(holdout)) < 1 - np.exp(-_truth_h)
    capture = score_plants(holdout, failed, growth_cases["base"], scales, 3.0)
    capture
    return capture, failed, holdout, score_plants


@app.cell
def _(capture, failed, holdout, mo, pd):
    _by_kind = pd.Series(failed).groupby(holdout["kind"].to_numpy()).sum()
    _f = capture.set_index(["ranking", "cut"])["share"]
    mo.md(f"""
    Across 1,000 plants, {int(failed.sum()):,} assets failed in three years
    ({failed.sum() / 1000:.1f} per plant: {_by_kind.to_dict()}). Picking ten at random would
    catch 4% of them (10 of 250). The full ranking's top ten caught
    **{_f["full", "top 10"]:.0%}**, age plus load **{_f["age_load", "top 10"]:.0%}**, and age
    alone **{_f["age_only", "top 10"]:.0%}**. Motors make up most failures because their
    published failure rate is more than ten times a transformer's, and about 70% of motor
    failures (bearings, mechanical) have nothing to do with load, which caps what any
    ranking here can catch.
    """)
    return


@app.cell
def _(failed, growth_cases, holdout, np, plt, rank_in_plant, results, risk, scales):
    _fig, _ax = plt.subplots(figsize=(7, 4))
    _ks = np.arange(1, 51)
    _labels = {"full": "full ranking", "age_load": "age + load", "age_only": "age only"}
    for _view, _label in _labels.items():
        _score = risk(holdout, _view, growth_cases["base"], scales[_view])
        _rank = rank_in_plant(holdout, _score)
        _share = [((_rank <= k) & failed).sum() / failed.sum() for k in _ks]
        _ax.plot(_ks, _share, label=_label)
    _ax.plot(_ks, _ks / 250, "k--", label="random")
    _ax.axvline(10, color="grey", lw=0.5)
    _ax.set_xlabel("assets flagged per plant (of 250)")
    _ax.set_ylabel("share of 3-year failures caught")
    _ax.set_title("Held-out failures caught, 1,000 synthetic plants")
    _ax.legend()
    _fig.tight_layout()
    _fig.savefig(results / "capture_curve.png", dpi=150)
    _fig
    return


@app.cell
def _(mo):
    mo.md(r"""
    **Within each type.** Motors fill most top-ten slots because their published failure rate
    is ten to twenty times higher, so the overall numbers mostly measure motors. A capital
    plan usually looks at each class separately, so here is the same test within type: rank
    each plant's transformers, switchgear and motors on their own and take the top 10% of each
    (4 transformers, 9 switchgear sections, 12 motors).
    """)
    return


@app.cell
def _(failed, growth_cases, holdout, pd, risk, scales, types):
    _rows = {}
    for _view in ("full", "age_load", "age_only"):
        _score = pd.Series(risk(holdout, _view, growth_cases["base"], scales[_view]))
        _group = [holdout["plant"].to_numpy(), holdout["kind"].to_numpy()]
        _rank = _score.groupby(_group).rank(ascending=False, method="first")
        _cut = holdout["kind"].map((types["n"] / 10).round())
        _inside = pd.Series((_rank <= _cut) & failed)
        _rows[_view] = (
            _inside.groupby(holdout["kind"].to_numpy()).sum()
            / pd.Series(failed).groupby(holdout["kind"].to_numpy()).sum()
        )
    _rows["failures"] = pd.Series(failed).groupby(holdout["kind"].to_numpy()).sum()
    by_kind = pd.DataFrame(_rows).round(3)
    by_kind
    return (by_kind,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 6. How much does the load-growth assumption move the list?

    Two questions. First, on the same plants, how many of the base-case top ten are still in
    the top ten if the engineer assumes low (1%/yr) or high (8%/yr) growth instead of 4%?
    Second, if growth actually comes in high but the engineer planned on base, how much does
    the catch rate drop?
    """)
    return


@app.cell
def _(
    growth_cases,
    holdout,
    np,
    pd,
    rank_in_plant,
    risk,
    scales,
    score_plants,
):
    def top_ten(plants: pd.DataFrame, growth: float) -> pd.Series:
        """Boolean mask of each plant's full-ranking top ten under this growth assumption."""
        score = risk(plants, "full", growth, scales["full"])
        rank = rank_in_plant(plants, score)
        return pd.Series(rank <= 10)

    _base = top_ten(holdout, growth_cases["base"])
    overlap = {}
    for _case in ("low", "high"):
        _other = top_ten(holdout, growth_cases[_case])
        _kept = (_base & _other).groupby(holdout["plant"].to_numpy()).sum()
        overlap[_case] = {"mean_kept": float(_kept.mean()), "min_kept": int(_kept.min())}

    _truth_high = risk(holdout, "truth", growth_cases["high"], scales["truth"])
    failed_high = np.random.default_rng(2).random(len(holdout)) < 1 - np.exp(-_truth_high)
    _planned_base = score_plants(holdout, failed_high, growth_cases["base"], scales, 3.0)
    _planned_high = score_plants(holdout, failed_high, growth_cases["high"], scales, 3.0)
    growth_miss = pd.DataFrame(
        {
            "planned base": _planned_base.set_index(["ranking", "cut"])["share"],
            "planned high": _planned_high.set_index(["ranking", "cut"])["share"],
        }
    ).round(3)
    overlap, growth_miss
    return failed_high, growth_miss, overlap


@app.cell
def _(mo):
    mo.md(r"""
    ## 7. What if the published curve is the wrong shape?

    The ranking assumes a Weibull shape of 3. Here the truth uses 2 (failures spread more
    evenly) or 5 (failures concentrate in the most worn assets) while the ranking keeps 3.
    """)
    return


@app.cell
def _(calibrate, risk, growth_cases, holdout, np, pd, reference, scales, score_plants):
    _rows = {}
    for _shape in (2.0, 5.0):
        _truth_scale = calibrate(reference, "truth", growth_cases["base"], _shape)
        _h = risk(holdout, "truth", growth_cases["base"], _truth_scale, _shape)
        _failed = np.random.default_rng(2).random(len(holdout)) < 1 - np.exp(-_h)
        _s = score_plants(holdout, _failed, growth_cases["base"], scales, 3.0)
        _rows[f"truth shape {_shape:g}"] = _s.set_index(["ranking", "cut"])["share"]
    shape_check = pd.DataFrame(_rows).round(3)
    shape_check
    return (shape_check,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 8. The one-page report for one plant

    Plant 0 of the hold-out set stands in for a real plant. For each of its ten highest-risk
    assets the call is:

    - **retest** if it has no condition test or the test is more than three years old, since
      its rank then rests on age and a meter reading alone;
    - **replace** if a recent test puts it past one normal insulation life;
    - **extend life** otherwise: the risk comes from load on an asset with life left, so
      relieve the load, add cooling, rewind or refurbish (for motors whose risk is mostly
      bearings or mechanical, an overhaul).
    """)
    return


@app.cell
def _(
    consumed_life,
    risk,
    growth_cases,
    holdout,
    np,
    pd,
    scales,
    three_year_hazard,
):
    plant0 = holdout[holdout["plant"] == 0].reset_index(drop=True)
    _prefix = {"transformer": "TX", "switchgear": "SWG", "motor": "M"}
    plant0["asset"] = [
        f"{_prefix[k]}-{'ABCD'[b]}{i:03d}"
        for i, (k, b) in enumerate(zip(plant0["kind"], plant0["bus"], strict=True))
    ]
    _g = growth_cases["base"]
    _h = risk(plant0, "full", _g, scales["full"])
    plant0["pof_3yr"] = 1 - np.exp(-_h)
    plant0["rank"] = pd.Series(_h).rank(ascending=False, method="first").astype(int)
    _h_age = risk(plant0, "age_only", _g, scales["age_only"])
    plant0["age_rank"] = pd.Series(_h_age).rank(ascending=False, method="first").astype(int)
    for _case, _rate in growth_cases.items():
        plant0[f"rank_{_case}"] = (
            pd.Series(risk(plant0, "full", _rate, scales["full"]))
            .rank(ascending=False, method="first")
            .astype(int)
        )
    plant0["load_in_3yr"] = plant0["load_meter"] * (1 + _g * plant0["exposure"]) ** 3
    _thermal, _other = three_year_hazard(plant0, "full", _g, scale=scales["full"])
    plant0["thermal_share"] = _thermal / (_thermal + _other)
    _p = plant0.assign(view_load=plant0["load_meter"])
    _nominal = consumed_life(_p, "view_load", pd.Series(np.zeros(len(_p))))
    _at_test = consumed_life(_p, "view_load", _p["test_age"])
    _read = plant0["quality"] * consumed_life(plant0, "load_true", plant0["test_age"])
    _read = _read * plant0["test_noise"]
    _speed = np.clip(_read / np.maximum(_at_test, 1e-3), 0.3, 3.0)
    plant0["life_used"] = np.where(plant0["tested"], _speed, 1.0) * _nominal
    plant0["recent_test"] = plant0["tested"] & (plant0["test_age"] <= 3)
    plant0["call"] = np.select(
        [~plant0["recent_test"], plant0["life_used"] >= 1.0],
        ["retest", "replace"],
        "extend life",
    )
    top = plant0.nsmallest(10, "rank")
    top[
        [
            "asset",
            "kind",
            "age",
            "load_meter",
            "load_in_3yr",
            "tested",
            "test_age",
            "life_used",
            "pof_3yr",
            "rank",
            "age_rank",
            "call",
        ]
    ].round(2)
    return plant0, top


@app.cell
def _(
    by_kind,
    capture,
    growth_cases,
    growth_miss,
    json,
    log,
    overlap,
    pd,
    plant0,
    results,
    shape_check,
    started,
    time,
    top,
    types,
):
    def why(row: pd.Series) -> str:
        """One line on what drives this asset's rank."""
        parts = [f"{row['age']:.0f} yrs old", f"at {row['load_meter']:.0%} of rating"]
        if row["load_in_3yr"] - row["load_meter"] > 0.05:
            parts.append(f"{row['load_in_3yr']:.0%} by year 3 (bus {'ABCD'[row['bus']]})")
        test = f"test {row['test_age']:.0f} yrs ago" if row["tested"] else "no test on file"
        parts.append(f"{row['life_used']:.2f} normal lives used ({test})")
        driver = "load/insulation" if row["thermal_share"] >= 0.5 else "bearing/mechanical"
        parts.append(f"risk mostly {driver}")
        return "; ".join(parts)

    _f = capture.set_index(["ranking", "cut"])
    _full10, _age10 = _f.loc[("full", "top 10")], _f.loc[("age_only", "top 10")]
    _full25, _age25 = _f.loc[("full", "top 10%")], _f.loc[("age_only", "top 10%")]
    _counts = plant0["kind"].value_counts().to_dict()
    _lines = [
        "# Plant 0: ten assets to bring to capital planning",
        "",
        f"Synthetic plant, {len(plant0)} assets ({_counts}). Ranked by probability of failing "
        f"in the next three years at today's metered load growing "
        f"{growth_cases['base']:.0%}/yr (bus D, the new line, twice that).",
        "",
        "| # | Asset | Type | 3-yr failure chance | Age-only rank | Why it ranks here | Call |",
        "|---|---|---|---|---|---|---|",
    ]
    for _, _r in top.iterrows():
        _lines.append(
            f"| {_r['rank']} | {_r['asset']} | {_r['kind']} | {_r['pof_3yr']:.0%} | "
            f"{_r['age_rank']} | {why(_r)} | **{_r['call']}** |"
        )
    _kept_low, _kept_high = overlap["low"]["mean_kept"], overlap["high"]["mean_kept"]
    _lines.append("")
    for _kind in ("transformer", "switchgear"):
        _r = plant0[plant0["kind"] == _kind].nsmallest(1, "rank").iloc[0]
        _lines.append(
            f"Highest-ranked {_kind}: {_r['asset']}, #{_r['rank']}, "
            f"{_r['pof_3yr']:.1%} in 3 yrs; {why(_r)}; **{_r['call']}**.  "
        )
    _lines += [
        "",
        "**How good is this list?** On 1,000 simulated plants like this one, the top ten "
        f"caught {_full10['share']:.0%} of the assets that failed within three years "
        f"(in a single plant, 90% of the time between {_full10['plant_p5']:.0%} and "
        f"{_full10['plant_p95']:.0%}); ranking by age alone "
        f"caught {_age10['share']:.0%}, ten at random 4%. The top 25 caught "
        f"{_full25['share']:.0%} (age alone {_age25['share']:.0%}). Most failures it misses are "
        "motor bearing and mechanical failures that load and insulation tests don't predict.",
        "",
        f"**If load grows differently.** At 1%/yr instead of 4%, {_kept_low:.1f} of these ten "
        f"stay in the top ten on average; at 8%/yr, {_kept_high:.1f}.",
        "",
        "**What it can't tell you.** Consequence of failure (a transformer outage costs more "
        "than a motor), spares and lead times, failures with no thermal cause, and anything "
        "about a real plant: every number here comes from a synthetic plant built from "
        "published IEEE failure rates and ageing curves.",
    ]
    report_text = "\n".join(_lines) + "\n"
    (results / "report.md").write_text(report_text)
    plant0.drop(
        columns=["quality", "other", "meter_bias", "test_noise", "vibration_noise", "load_true"]
    ).round(4).to_csv(results / "plant0_assets.csv", index=False)
    metrics = {
        "assets_per_plant_by_type": types["n"].to_dict(),
        "holdout_plants": 1000,
        "capture_base_growth": capture.round(4).to_dict(orient="records"),
        "top10pct_within_kind": by_kind.to_dict(orient="index"),
        "top10_kept_vs_base": overlap,
        "growth_miss": {f"{k[0]} {k[1]}": v for k, v in growth_miss.to_dict("index").items()},
        "shape_check": {f"{k[0]} {k[1]}": v for k, v in shape_check.to_dict("index").items()},
        "plant0_top10_by_call": top["call"].value_counts().to_dict(),
        "plant0_top10_by_kind": top["kind"].value_counts().to_dict(),
        "plant0_top10_rank_by_growth": top[["asset", "rank_low", "rank_base", "rank_high"]].to_dict(
            orient="records"
        ),
        "runtime_seconds": round(time.time() - started, 1),
    }
    (results / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))
    log.info("wrote report.md, metrics.json, plant0_assets.csv in %.1fs", time.time() - started)
    return (report_text,)


@app.cell
def _(mo):
    mo.md(r"""
    ## 9. What didn't work, and what this can't show

    - **The first version saturated.** Without load limits, a few simulated motors ran at
      150-190% of rating, their failure probability rounded to 1.0, and ties wrecked the
      ranks. Fixes: cap loading where protection would trip (motor service factor 1.15,
      breakers 1.1, transformers 1.3), replace assets that would already have burned out
      (the burn-in in `make_plants`), and rank on cumulative hazard instead of probability.
    - **Motors fill the overall top ten.** Their published rate is 0.0708 a year against
      0.0062 for a transformer, so a list ranked purely by chance of failure is a motor list.
      Within type, load is what finds the failing transformers and switchgear; age alone is
      no better than chance there. A real capital list also needs consequence of failure,
      which this does not model.
    - **Tests add little for transformers and switchgear here.** With a 30-40% noisy reading
      taken up to six years ago, the full ranking is no better than age + load for those
      types. For motors the vibration test is what lifts the full ranking, because most
      motor failures are bearings.
    - **The big caveat: it's circular by construction.** The truth and the rankings share the
      same ageing physics and failure curve; the rankings just see it through noisy meters,
      stale tests and missing hidden factors. Section 7 shows a wrong Weibull shape barely
      matters, but nothing here shows the ageing curves hold in a real plant. That needs a
      plant's own failure history.
    """)
    return


@app.cell
def _(mo, report_text):
    mo.md(report_text)
    return


if __name__ == "__main__":
    app.run()

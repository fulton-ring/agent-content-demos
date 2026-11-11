# Ranking aging electrical equipment by exposure to load growth

Can an equipment-risk ranking, fed one plant's equipment list, test records and meter data,
pick out the ten assets most likely to fail in the next three years under the load they now
carry, with a replace, extend-life or retest call for each? And how much better is that than
ranking by age? Issue [#192](https://github.com/fulton-ring/agent-content-demos/issues/192).

**Short answer, on a synthetic plant:** the ranking's top ten caught 15% of the failures held
out from it, against 8% for an age-only ranking and 4% for ten picked at random. Within
transformers and switchgear, load is what finds the failing units: their top 10% caught about
40% of failures, while age alone was no better than chance (10-14%). Every number here comes
from a simulated plant built from published IEEE parameters, not from a real plant.

## Run it

```bash
./run.sh          # uv run notebook.py, about 1-2 minutes, no network or API keys needed
```

To read it as a notebook: `uv run marimo edit notebook.py`. Output goes to `results/`
(override with `AGING_RESULTS`).

## Data

No public dataset fits. The public transformer datasets we found (dissolved-gas and
health-index sets, such as a GitHub health-index sample in cyberfantics/transformer-health-analysis
and the partial DGA data released with Mirowski & LeCun, 2012) have test readings but no loading and no recorded failures,
so they can't score a failure ranking. The notebook therefore **generates a synthetic plant**
from published parameters:

| Parameter | Value | Source |
|---|---|---|
| Transformer failure rate | 0.0062 per unit-year | IEEE 493, 1979 survey ([summary](https://reliamag.com/guides/electrical-equipment-failure-rate-benchmarks/)) |
| Switchgear (metal-clad breaker) rate | 0.0036 per unit-year | IEEE 493-1980 Table 24, 58 failures in 16,280 unit-years (same) |
| Large motor rate | 0.0708 per unit-year | IEEE-IAS 1985 survey, 200 hp+ ([summary](https://reliamag.com/guides/electric-motor-failure-statistics/)) |
| Transformer ageing | $F_{AA}=e^{15000/383-15000/(\theta_H+273)}$, 180,000 h normal life at 110 °C | IEEE C57.91; ONAN hot-spot model from IEEE C57.91 / IEC 60076-7 |
| Motor and switchgear ageing | insulation life halves per 10 °C | [EASA](https://easa.com/resources/trade_press/when-it-comes-to-motors-how-hot-is-hot) |

Our own assumptions, stated in the notebook: the plant mix (40 transformers, 90 switchgear
sections, 120 large motors on four buses), ages, loading, the share of each type's failures
that are thermal (60/40/30%), motor and switchgear reference lives, a Weibull shape of 3 on
consumed life, 3% a year past load growth, and test and meter noise.

## How it works

`notebook.py` reads top to bottom:

1. Turn peak loading into insulation life used per year, over a year of ambient temperature
   and a daily load cycle.
2. Build plants. Each asset has hidden factors the ranking never sees (how fast it really
   ages, bearing and mechanical risk, true load behind a 3-15% noisy meter). Assets that
   would already have burned out are replaced. Some have a condition test, 0-6 years old.
3. Rank by three-year failure hazard: a Weibull curve on consumed life, projected forward at
   each bus's assumed load growth, plus other-cause hazard. Three versions see different
   inputs: **full** (meter, growth, tests), **age + load** (no tests), **age only**.
4. Simulate 1,000 plants, let the hidden truth decide who fails, hold those failures out and
   count what each ranking's top ten and top 10% catch.
5. Change the growth assumption and the failure-curve shape and see what moves.
6. Write the one-page report for one plant.

## Results (from `results/metrics.json`)

Base case: 1,000 plants of 250 assets, 18,099 failures in three years (16,729 motors, 916
switchgear, 454 transformers), load growing 4% a year (bus D 8%).

| Ranking | Top 10 caught | Top 10% (25) caught | Single plant, top 10, 5th-95th pct |
|---|---|---|---|
| Full (meter + growth + tests) | 14.5% | 28.3% | 4% to 27% |
| Age + load, no tests | 9.9% | 21.5% | 0% to 22% |
| Age only | 8.0% | 19.8% | 0% to 19% |
| Random | 4.0% | 10.0% | |

Within type, top 10% of each type per plant:

| Type | Full | Age + load | Age only |
|---|---|---|---|
| Transformer | 40.3% | 40.5% | 14.3% |
| Switchgear | 40.9% | 40.2% | 10.3% |
| Motor | 17.2% | 11.7% | 10.2% |

**Load-growth assumption.** Re-ranking the same plants at 1% a year keeps 8.1 of the base
top ten on average; at 8% a year only 2.7 stay. If growth actually comes in at 8% and the
engineer planned for 4%, the full top ten catches 14.6% of failures; planning for 8% catches
25.9%. Age-only gets 8.4% and 11.2%.

**Failure-curve shape.** If the true Weibull shape is 2 or 5 while the ranking assumes 3, the
full top ten still catches 14.7% and 13.8%.

**Sample report:** [`results/report.md`](results/report.md), with chart
[`results/capture_curve.png`](results/capture_curve.png) and the plant's asset list (observed
fields only) in [`results/plant0_assets.csv`](results/plant0_assets.csv). In that plant all
ten are motors (5 retest, 5 extend life). The highest-ranked transformer is #101, at 117% of
rating with 1.38 normal lives used, and its call is replace.

## What didn't work

- The first version had no load limits. A few motors ran at 150-190% of rating, their
  failure probability rounded to 1.0 and ties broke the ranks. It now caps load where
  protection would trip, replaces assets that would already have burned out, and ranks on
  cumulative hazard.
- Ranked purely by chance of failure, the list is a motor list, because motors fail more
  than ten times as often. A capital plan needs consequence of failure, which isn't modelled.
- Condition tests add almost nothing for transformers and switchgear at the noise and
  staleness assumed. The motor vibration test is what lifts the full ranking overall.
- When growth comes in high but the plan assumed base, age + load did slightly better than
  the full ranking (16.8% vs 14.6%). We didn't chase why.

## What it doesn't show

- **That this works on a real plant.** The truth and the rankings share the same ageing
  physics and failure curve. The rankings only see it through noisy meters, stale tests and
  without the hidden factors. That shows the ranking pulls the signal out if the physics
  holds. It can't show the physics holds. That takes a plant's own failure history.
- Consequence, spares and lead times, which drive the actual replace-or-extend decision.
- Whether "extend life" (load relief, cooling, rewind) actually lowers the risk.
- The interview behind the card (Latitude Media, 2026-09-23) is context only. No numbers
  from it are used here.

## What we looked at first

Public transformer DGA and health-index datasets (no failures or loading), IEEE 493 rate
summaries, the IEEE C57.91 / IEC 60076-7 thermal model and the EASA 10 °C rule. No existing
open-source tool ranks plant equipment by load-driven ageing that we could reuse, so the
ranking is a few dozen lines of numpy in the notebook. No model calls, no paid services.

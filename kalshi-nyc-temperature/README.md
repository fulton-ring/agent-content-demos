# Can an AI weather model beat Kalshi on New York's daily high?

Kalshi runs a daily market on the highest temperature in New York City (series
`KXHIGHNY`, measured at Central Park). Each day has six brackets, such as "67° to 68°". This
spike backtests a year of it: does ECMWF's open AI weather model (AIFS), corrected with
Central Park's own sensor record, price those brackets better than the market? It also
scores NOAA's National Blend of Models (NBM) as the conventional baseline, and paper-trades
each model against Kalshi's quoted prices after fees.

Issue: [#89](https://github.com/fulton-ring/agent-content-demos/issues/89).
## Run it

```bash
./run.sh
```

This needs [uv](https://docs.astral.sh/uv/). It runs three [marimo](https://marimo.io)
notebooks as scripts and writes every table and figure to `results/`:

- `1_data.py` downloads the public data into `~/.cache/kalshi-nyc-temperature` (or set
  `KALSHI_NYC_CACHE`). **The first run takes two to three and a half hours**: about two for
  Kalshi's rate limit on anonymous candlestick reads, plus up to 1.5 for the AIFS downloads on a busy machine. Markets settled before Kalshi's archive cutoff
  (late August 2026) need one call per bracket, about 1,800 calls, and the limit allowed
  only a few a minute. Later runs use the cache and take about a minute.
- `2_backtest.py` builds the forecasts, scores them and paper-trades them (about 30 seconds).
- `3_favourite.py` tests whether the market underprices its favourite bracket (a few seconds;
  it needs only the Kalshi tables).

The default period is 2025-10-20 to 2026-10-19. Set `BACKTEST_START` and `BACKTEST_END`
(ISO dates) for a shorter run; the period since late August 2026 downloads fast. To read
the notebooks with their outputs, use `uv run marimo edit 2_backtest.py`.

## Data

All public, fetched at run time, nothing committed, no account or key.

| Source | Used for |
|---|---|
| [Kalshi Trade API](https://docs.kalshi.com), live and `/historical/` endpoints | brackets, settled values, hourly yes bid and ask |
| [ECMWF AIFS Single open data](https://www.ecmwf.int/en/forecasts/datasets/open-data) on AWS (`ecmwf-forecasts`, CC BY 4.0) | the AI model's 2 m temperature at Central Park |
| NOAA NBM station text (NBS) via the [Iowa Environmental Mesonet](https://mesonet.agron.iastate.edu) MOS archive | NOAA's max temperature and its standard deviation |
| NWS Daily Climate Report for Central Park (CLI), via IEM | the official daily high the correction learns from |
| ASOS 1-minute data for KNYC, via IEM | the high so far and the temperature at 2 pm |
| [Kalshi fee schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf) (July 2026) and the series' `fee_type` | taker fee `round up(0.07 × C × P × (1 − P))` |

## Method in one paragraph

At three times before the close (4 pm the day before, 8 am and 2 pm on the day, New York
time) we take the market's midpoint for each bracket and each model's forecast of the high,
using only what was published by then (AIFS runs land about 5.5 hours after they start).
Each model forecast becomes bracket probabilities through a normal error curve. "Corrected"
means the centre and spread come from the last 30 days of misses against the Central Park
record; "AIFS + 2 pm sensors" also shifts the forecast by how far the 2 pm reading is from
what AIFS said, and floors it near the high so far. Scores are the Brier score and log loss
against Kalshi's settled value. The paper-trading rule buys 10 contracts of a bracket (yes
at the ask or no at 1 − bid) when the model's edge beats the price and fee by 5 cents, and
holds to settlement.

## What it found

All numbers are from `results/` after a run of the full period: 365 days, 2,190 brackets.

**1. The market beat every model at every lead time.** Daily log loss (lower is better;
`results/scores.csv`, which also has Brier scores and 95% intervals):

| | 4 pm day before | 8 am on the day | 2 pm on the day |
|---|---|---|---|
| Kalshi market (bid-ask midpoint) | **1.25** | **0.97** | **0.53** |
| AIFS raw | 1.61 | 1.50 | 1.57 |
| AIFS corrected with Central Park's record | 1.36 | 1.26 | 1.35 |
| NBM, as issued | 1.65 | 1.58 | 1.61 |
| NBM corrected | 1.56 | 1.48 | 1.46 |
| AIFS + 2 pm sensors (258 days with a full morning record) | | | 1.05 |

The closest any model came was corrected AIFS the day before, 0.12 ± 0.09 worse than the
market. Brier scores rank the sources the same way (market 0.64, 0.53, 0.31; corrected
AIFS 0.70, 0.67, 0.69).

**2. The local correction is worth more than the model choice.** Raw AIFS runs about 2°F
cold at Central Park (mean error +2.1°F, mean absolute error 2.5°F the day before),
largely because it only writes temperature every 6 hours and the peak falls between. A
30-day correction against the Central Park record removes the bias and cuts the mean
absolute error to 1.7°F the day before and 1.6°F at 8 am. That beats NOAA's NBM (2.2°F),
and cuts AIFS's log loss by 0.22 to 0.25 at each lead (`results/errors.csv`). At 2 pm,
adding the Central Park 1-minute record (the high so far and how warm it is now) cuts
the error again, to 1.5°F, on the 258 days with a full morning record. On those days it
still scores 0.53 ± 0.13 worse than the market.

**3. Paper trading loses money after fees.** At a 5-cent edge threshold, corrected AIFS
made 2,543 trades with a 39% hit rate and lost $107 (10 contracts a trade, $289 of it fees,
maximum drawdown $356). The 95% interval on that P&L is ±$380, so it is indistinguishable
from zero. NBM lost $948. The slices that made money, such as corrected AIFS the day before
(+$145 on 955 trades, ±$237) or corrected AIFS at a 20-cent threshold (+$160, ±$239), are
within their intervals and are the kind of result you find by looking at enough slices. At 2 pm every model loses: by then the market knows the morning.

**4. The days that went wrong** (`results/bad_days.csv`, worst 10 for corrected AIFS at
8 am): in 9 of 10, AIFS ran cold, in 8 of them by 4 to 7°F. Three of those highs came at 11 pm or
midnight, which 6-hourly output and NOAA's 7 am to 7 pm window both miss. The market also scored badly (log loss above 2) on half of them.

**5. Sensor data is not settlement data.** The Central Park 1-minute record reads above
the official high on 32% of days, so the "high so far" can't be used as a hard floor; we
floor one degree below it. Kalshi also switched its settlement source from the NWS Daily
Climate Report to The Weather Company on 2026-08-14 (67 days of this period); where both
exist, they agreed on every day.

## Is the market underconfident on its favourite? (#101)

No, not reliably, and not tradably. `2_backtest.py`'s calibration plot suggested brackets
priced 60 to 80% won more often than that. `3_favourite.py` tests the day's favourite (the
highest midpoint) alone, one per day, with 95% intervals (`results/favourite_*.csv` and
`favourite_calibration.png`):

| Favourite at | Days | Avg price | Won | Gap (± 95%) | p | After half-spread and fee |
|---|---|---|---|---|---|---|
| 4 pm day before | 360 | 44.8% | 49.7% | +5.0 ± 5.0 pts | 0.05 | +2.2 ± 5.0 |
| 8 am | 364 | 56.0% | 61.0% | +5.0 ± 4.8 | 0.04 | +2.3 ± 4.8 |
| 2 pm | 365 | 76.8% | 78.4% | +1.6 ± 3.9 | 0.43 | −0.9 ± 3.9 |

- **The 60 to 80% band itself shows nothing.** Only 15 favourites the day before and 56 at
  8 am were priced there, and the gap is inside its interval at every snapshot. The
  whole-year gap comes mostly from favourites priced 40 to 60%.
- **It doesn't hold over time.** At 8 am the gap was +9.6 ± 6.7 pts in the first half,
  −3.7 ± 8.8 from 2026-04-20 to the settlement switch, and +7.3 ± 11.0 after it.
- **Out of sample it loses.** Of 63 rules (snapshot × price band on the ask) tried on
  2025-10-20 to 2026-04-19, the best was "buy 10 of the 8 am favourite whenever its ask is
  40% or more": +$132 ± $115 on 159 trades. On 2026-04-20 to 2026-10-19 the same rule lost
  **$51 ± $125** on 180 trades (57% hit rate, $30 in fees, $104 maximum drawdown):
  −$83 before the 2026-08-14 switch to The Weather Company and +$32 after, both inside
  their intervals (`results/favourite_pnl.png`).

A gap of a few points might exist, but a year is too short to tell it from noise, and the
half-spread plus the fee take about half of it.

## What didn't work

The first two come from a 59-day trial run (2026-08-22 to 2026-10-19) during development,
not from the published run.

- **Using the freshest AIFS run.** Switching each snapshot from the 00 UTC run to the latest
  one a trader could see (12 UTC the day before, 06 and 12 UTC on the day) didn't close the
  gap to the market; the published run uses the freshest run anyway, as a trader would.
- **A hard floor at the 1-minute high so far** made the 2 pm model worse than no sensors at
  all (log loss 1.69 against 1.11), because of point 5.
- **NBM's own spread** is too narrow for Central Park: as issued, it scores worse than raw
  AIFS at every lead.

## What it doesn't show

- **Past performance, one city, one market, one year.** The market and the models change;
  Kalshi switched the settlement source mid-period.
- **No slippage, depth or queue.** Every paper order fills in full at the quoted hourly
  close. Real orders of any size would move these thin books.
- **A simple model pipeline.** One deterministic AIFS run per snapshot, 6-hourly output and
  a normal error curve. The AIFS ensemble, hourly models (HRRR) and later runs are not used.
- **Not the NYS Mesonet.** Its Manhattan station would be the obvious second local sensor.
  The history is reachable through the API behind its website, but that host's robots.txt
  disallows automated access, and the Mesonet's data policy makes the data free only for
  personal use and bars redistribution; others license it. Airport ASOS isn't used either.

## What an article could argue from

- Open AI weather data is good enough to build on with no account: AIFS's archive on AWS,
  read 0.5 MB at a time, plus a free local sensor archive, gave a forecast of the Central
  Park high more accurate than NOAA's blended forecast.
- The value is in the local correction, not the model. The raw AI model was 2°F cold; one
  month of public observations fixed that.
- A liquid market is a hard benchmark. Kalshi's NYC market quotes a median spread of 1 cent
  and beat every public model and sensor combination we tried, at every lead time.
- Sensor data and the official record are different things: 1-minute readings ran above
  the official high on a third of days.
- The market's apparent underconfidence on its favourite bracket is not a reliable edge
  (see below).

## What we looked at first

Kalshi's API has an event-level candlestick endpoint (one call per day) but only for live
markets; its batch endpoint doesn't cover the archive. Open-Meteo's archived forecasts
(including AIFS) would have saved the GRIB step, but its free tier was over its daily
limit from this network, so we read ECMWF's open data directly with `eccodes`.

# S&P 500 volume-spike scanner: do any follow-up strategies make money?

A scanner flags S&P 500 stocks priced $1-$20 that jump on heavy volume. Six strategies then trade
the flagged stocks, and each is backtested over ten years of daily bars. The aim is to see
whether any of them, including "continuation" and "wait for support to break", has an edge.

## Run it

```bash
./run.sh        # about a minute the first time (data download), a few seconds after
```

This runs three [marimo](https://marimo.io) notebooks as scripts. Open one to read it with its
output: `uv run marimo edit 2_backtest.py`.

- `1_data.py`: downloads prices and splits for today's S&P 500 members and SPY (cached outside the repo).
- `2_backtest.py`: daily-bar scanner, six strategies, results, robustness checks. Writes `results/`.
- `3_intraday.py`: the same idea on hourly bars for the last 2 years, compared with SPY.
- `common.py`: the summary statistics both notebooks use.

## What the scanner and strategies are

Scanner (day 0, at the close): price between $1 and $20 **as traded that day**, up 5% or more,
volume at least 3x the prior 20-day average. 133 events from 2016-11 to 2026-11.

| | Strategy | Entry |
|---|---|---|
| A | Continuation | Long at day 1 open |
| B | Confirmed continuation | Long if day 1 trades above day 0's high |
| C | Fade | Short at day 1 open |
| D | Buy the pullback | Long if price gives back half of day 0's gain within 5 days |
| E | Support breaks | Days 1-3 stay in a tight box; short below the box low |
| F | Resistance breaks | Same box; long above the box high |

Exit: 8% stop or the close of the 5th trading day, whichever is first. Costs: 0.10% each way.
All parameters were fixed before looking at results. Other stops, holding periods and scanner
thresholds are reported in full, not just the best.

## Results (default exits)

| Strategy | Trades | Win rate | Mean per trade | Mean without top 3 trades | 95% interval for the mean |
|---|---|---|---|---|---|
| A continuation | 133 | 43% | +0.57% | -0.26% | -1.1% to +2.4% |
| B confirmed continuation | 68 | 40% | +0.48% | -1.21% | -1.9% to +3.2% |
| C fade (short) | 133 | 42% | -1.68% | -2.47% | -3.1% to -0.2% |
| D buy pullback | 69 | 51% | +1.66% | +0.34% | -1.1% to +4.6% |
| E support break (short) | 19 | 26% | -1.65% | -3.04% | -3.4% to +0.1% |
| F resistance break | 21 | 33% | -1.21% | -2.53% | -3.2% to +1.0% |
| Control: A's rules on random $1-$20 days | 19,983 | 50% | +0.40% | | +0.07% to +0.75% |

- Five of the six intervals include zero. Only the fade (C) is clearly negative.
- The scanner adds little to the control: A is +0.57% against +0.40% for random cheap stock-days.
- A's and D's averages come from a few big winners. The best A trade was Bloom Energy,
  +55%, in 2024, before it joined the index.
- **Membership look-ahead:** 64 of 133 events were in stocks that joined the S&P 500 later.
  Among stocks already in the index, A averaged -1.0% (69 trades) against +2.3% for the rest
  (64 trades). D went from +3.5% to +0.2%. See `results/by_membership.csv`.
- Results move a lot with the exit rule and scanner threshold (`results/sensitivity_*.csv`),
  and the first and second half of the period often disagree (`results/halves.csv`).

![returns](results/returns.png)

## Intraday test (hourly bars, last 2 years, vs SPY)

Yahoo's free intraday history is only 2 years of hourly bars (5-minute bars: 60 days), so this is
**not** a 5-year test. After the first hour (9:30-10:30) the scanner flags stocks whose
previous close was $1-$20, with first-hour volume at least 2x normal and a gain of at least 2%.
That gave 70 events. Every trade is closed by the end of the day. `results/intraday_*.csv`.

| Strategy | Trades | Win rate | Mean per trade | 95% interval | Account over 2 years |
|---|---|---|---|---|---|
| I1 continuation (long 10:30) | 70 | 39% | -0.21% | -0.7% to +0.3% | -9.9% |
| I2 opening-range breakout | 40 | 38% | -0.32% | -0.9% to +0.3% | -12.6% |
| I3 fade (short 10:30) | 70 | 23% | -0.50% | -0.8% to -0.2% | -26.9% |
| I4 support break (short) | 15 | 13% | -1.44% | -2.7% to -0.5% | -14.4% |
| I5 pullback | 15 | 53% | -0.11% | -1.0% to +0.9% | +0.7% |
| **SPY buy and hold** | | | | | **+20.5%** (worst drop -18.9%) |

"Account" splits the whole account equally across each day's trades and holds cash otherwise.
That is aggressive sizing, used only to make the totals comparable with owning SPY.

- None of the five beat SPY, and four lost money after 0.10% costs each way.
- With stricter scanners (3x volume, 3%+ gain) continuation turned slightly positive
  (+0.15% on 31 events), but that is too few events to read anything into
  (`results/intraday_sensitivity_scanner.csv`).
- **Yahoo's hourly data changes between downloads.** Two pulls on the same day gave 79 and 70
  events. About 0.1-0.3% of bars had different volume or price. With this few events, expect
  your numbers to differ slightly from the ones above.
- Hourly bars can't show the order of the high and low inside the hour, so stops are assumed
  to hit first. The 5-minute data (60 days) would hold only about 10 events at this scanner.

## Data

- Prices, volume, splits: Yahoo Finance via `yfinance` (free, unofficial, can change without notice).
- Members: [datasets/s-and-p-500-companies](https://github.com/datasets/s-and-p-500-companies) (current list, with "date added").
- Yahoo shows old prices divided by later splits. The notebook multiplies splits back in to get the price as traded, so the $1-$20 filter is right. 134 splits in the data.
- Hourly bars come from Yahoo too and are cached after the first run.
- Nothing is committed except small result files. Prices are downloaded on each fresh run.

## What it doesn't show

- **Survivorship and look-ahead.** Only today's members, so removed stocks are missing and
  recent additions were often added after rising. Long-side results are probably flattered.
- **Small samples.** 19 and 21 trades for the range-break strategies.
- **Daily bars only.** A real scanner works within the day. Free intraday history is about 60
  days, so intraday entries are untested.
- **Not modelled:** short borrow fees and squeezes, position sizing, overlapping trades, taxes.
  Where a bar could hit both the stop and a profit, the stop is assumed first.
- **Reading of "price between $1 and $20".** Taken as the stock's price, not the size of the move.
- Prices are not adjusted for dividends or spin-offs, and I could not verify Yahoo's history for
  every ticker. I spot-checked a handful (AMD, GE, Pure Storage) and they looked right.
- A backtesting library such as backtesting.py or vectorbt was not evaluated. The simulator here
  is about 40 lines of plain code so the entry and stop rules can be read in the notebook.

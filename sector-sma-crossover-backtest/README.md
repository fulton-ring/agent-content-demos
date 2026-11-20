# Sector ETF 10/50-day SMA crossover backtest

## What it shows

A one-year backtest (2025-11-20 to 2026-11-20, 252 trading days) of a simple rule on the 11 SPDR sector ETFs
(XLK, XLF, XLE, XLV, XLY, XLP, XLI, XLU, XLB, XLRE, XLC): hold an ETF while its 10-day simple moving
average is above its 50-day average, otherwise hold cash. Capital is split equally across the 11.

- The signal is read at the close and applied to the next day's return (no look-ahead).
- Cash earns 0%. Sharpe uses a 0% risk-free rate.
- Benchmarks: equal-weight buy-and-hold of the same 11 ETFs, and SPY.
- The 10/50 windows were fixed as requested, not tuned.

## Run it

```
./run.sh
```

Needs `uv` and internet. The notebook is `backtest.py` (marimo). It prints the tables and writes
`outputs/equity_curves.png`, `outputs/results.csv` and `outputs/per_etf.csv`.
Set `BACKTEST_END=YYYY-MM-DD` to move the window.

## Data

Daily dividend-adjusted closes from Yahoo Finance via the `yfinance` library, downloaded at run time
and not committed. Prices from 6 months before the window are loaded only to warm up the 50-day average.
The final day's price can still change after the close, and Yahoo adjusts past prices for dividends, so
re-running can shift the numbers (the same window moved the basket from 4.72% to 4.58% across three runs
on 2026-11-20, mostly from the last day's XLK price).

## Results (from the run in `outputs/`)

| Strategy | Return % | Ann. vol % | Sharpe | Max drawdown % | Time invested % |
|---|---|---|---|---|---|
| SMA 10/50 basket, no costs | 4.58 | 6.61 | 0.71 | -3.83 | 61.9 |
| SMA 10/50 basket, 5 bps/trade | 4.16 | 6.61 | 0.65 | -3.90 | 61.9 |
| SMA 10/50 basket, 10 bps/trade | 3.74 | 6.62 | 0.59 | -3.98 | 61.9 |
| Buy & hold, equal-weight basket | 12.64 | 10.15 | 1.22 | -6.26 | 100 |
| Buy & hold SPY | 7.20 | 14.00 | 0.57 | -9.80 | 100 |

89 position changes across the 11 ETFs (about 8 each), counting entries on day one for ETFs already
above their 50-day average.

Per ETF, the rule beat that ETF's own buy-and-hold in 1 of 11 cases (XLI, +5.9 points). Largest
shortfalls: XLB -17.7, XLE -21.8, XLP -16.8 points. See `outputs/per_etf.csv`.

## Position sizing variants (`position_sizing.py`)

Same signal, different sizes: thirds in, Fibonacci tranches (1,1,2,3,5) in, Fibonacci in and out,
a Fibonacci win/loss progression, trend-strength sizing and inverse-volatility sizing. Results for
the last 1 and 5 years are in `outputs/sizing_1_year.csv` and `outputs/sizing_5_years.csv`; the
notebook prints them with exposure, drawdown and turnover.

Return % (before costs) for the basket of 11 ETFs:

| Variant | 1 year | 5 years | Avg. exposure % (1y) |
|---|---|---|---|
| Baseline all-in/all-out | 4.58 | 9.66 | 62 |
| Thirds in | 5.67 | 9.41 | 60 |
| Fibonacci in | 5.51 | 8.34 | 58 |
| Fibonacci in and out | 6.00 | 9.99 | 60 |
| Fibonacci progression | 0.54 | 0.91 | 8 |
| Trend strength | 1.99 | 9.72 | 41 |
| Inverse volatility | 2.69 | 6.44 | 37 |
| Buy & hold basket | 12.64 | 55.80 | 100 |

Fibonacci progression starts every trade at 1/8 of full size, so it was invested about 8% of the
time. It is not comparable with the others on return. Sizing changes were small next to the gap to
buy-and-hold in both windows.

## What didn't work / failure cases

- The crossover trailed buy-and-hold on return in this window. It had lower volatility and a smaller
  drawdown, partly because it was in cash about 38% of the time.
- Sectors with strong trends but sharp dips (energy, materials, staples) lost the most, since the
  rule exits after a dip and re-enters late.
- Whipsaw: utilities and materials traded 11 times each.

## What it doesn't show

- One year is one market regime, so this says nothing about other periods.
- No tax, spread or slippage beyond the 5 and 10 bps cases. No intraday fills (close-to-close only).
- No comparison with other window lengths, and no out-of-sample test.
- The buy-and-hold basket is rebalanced daily, a simplification.

## What I looked at first

`yfinance` for data and `pandas` rolling means for the averages. Backtesting libraries such as
`vectorbt` or `backtrader` were not used, since a one-rule backtest is a few lines of pandas.

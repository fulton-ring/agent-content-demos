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
Yahoo adjusts past prices after dividends, so re-running later can shift the numbers by a few hundredths
of a percent (a re-run during this work moved the basket from 4.72% to 4.71%).

## Results (from the run in `outputs/`)

| Strategy | Return % | Ann. vol % | Sharpe | Max drawdown % | Time invested % |
|---|---|---|---|---|---|
| SMA 10/50 basket, no costs | 4.71 | 6.61 | 0.73 | -3.83 | 61.9 |
| SMA 10/50 basket, 5 bps/trade | 4.29 | 6.62 | 0.67 | -3.90 | 61.9 |
| SMA 10/50 basket, 10 bps/trade | 3.87 | 6.62 | 0.61 | -3.98 | 61.9 |
| Buy & hold, equal-weight basket | 12.86 | 10.14 | 1.24 | -6.26 | 100 |
| Buy & hold SPY | 7.43 | 13.97 | 0.58 | -9.61 | 100 |

89 position changes across the 11 ETFs (about 8 each), counting entries on day one for ETFs already
above their 50-day average.

Per ETF, the rule beat that ETF's own buy-and-hold in 1 of 11 cases (XLI, +5.6 points). Largest
shortfalls: XLB -17.7, XLE -21.8, XLP -16.8 points. See `outputs/per_etf.csv`.

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

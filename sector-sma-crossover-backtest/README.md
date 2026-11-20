# Sector ETF 10/50-day SMA crossover backtest

## What it shows

A one-year backtest (2025-11-19 to 2026-11-19, 252 trading days) of a simple rule on the 11 SPDR sector ETFs
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

Needs `uv` and internet. Notebooks (marimo, run as scripts): `backtest.py`, `position_sizing.py`,
`rotation_momentum.py`. Results go to `outputs/`. Set `BACKTEST_END=YYYY-MM-DD` to move the end date;
the default is the last completed day when this was written.

## Data

Daily dividend-adjusted closes from Yahoo Finance via `yfinance`, downloaded at run time, not
committed. Yahoo restates adjusted prices and an unfinished day keeps moving, so results can shift
slightly between runs (one run moved the basket from 4.72% to 4.58%). The end date is a completed day.

## Results (from the run in `outputs/`)

| Strategy | Return % | Ann. vol % | Sharpe | Max drawdown % | Time invested % |
|---|---|---|---|---|---|
| SMA 10/50 basket, no costs | 4.32 | 6.61 | 0.67 | -3.83 | 61.8 |
| SMA 10/50 basket, 5 bps/trade | 3.9 | 6.61 | 0.61 | -3.9 | 61.8 |
| SMA 10/50 basket, 10 bps/trade | 3.48 | 6.62 | 0.55 | -3.98 | 61.8 |
| Buy & hold, equal-weight basket | 12.97 | 10.14 | 1.25 | -6.26 | 100.0 |
| Buy & hold SPY | 9.62 | 13.88 | 0.73 | -8.88 | 100.0 |

89 position changes across the 11 ETFs (about 8 each), counting entries on day one for ETFs already
above their 50-day average.

Per ETF, the rule beat that ETF's own buy-and-hold in 1 of 11 cases (XLI). Largest
shortfalls: XLE -20.8, XLB -18.1, XLP -15.5 points. See `outputs/per_etf.csv`.

## Position sizing variants (`position_sizing.py`)

Same signal, different sizes: thirds in, Fibonacci tranches (1,1,2,3,5) in, Fibonacci in and out,
a Fibonacci win/loss progression, trend-strength sizing and inverse-volatility sizing.
Return % before costs for the 11-ETF basket (all variants are in `outputs/sizing_*.csv`):

| Variant | 1 year | 5 years | Avg. exposure % (1y) |
|---|---|---|---|
| Baseline | 4.32 | 9.01 | 62 |
| Fibonacci in | 5.25 | 7.7 | 58 |
| Fibonacci in and out | 5.75 | 9.34 | 59 |
| Trend strength | 1.78 | 9.06 | 41 |
| Buy & hold basket | 12.97 | 55.82 | 100 |

Fibonacci progression (not shown) starts each trade at 1/8 size, was invested about 8% of the time
and is not comparable on return. Sizing changes were small next to the gap to buy-and-hold.

## Momentum, rotation and market filters (`rotation_momentum.py`)

Asks whether momentum (trailing return) instead of price averages, rotating into the strongest ETFs,
or a market-wide filter can get ahead of big selloffs. Run on the 11 sectors and on 10 country ETFs
(SPY, EWC, EWU, EWG, EWJ, MCHI, INDA, EWZ, EWA, EWY, in US dollars). Windows (12-1 and 6-1 month
momentum, top 3, 200-day filter) were set once, not tuned. Cash earns 0%. All strategies and windows
are in `outputs/rotation_*.csv`.

**Sectors**

| Strategy | Return % since 2019-07 | Max drawdown % | Covid crash % | 2022 bear % |
|---|---|---|---|---|
| Buy & hold | 134.38 | -36.34 | -36.21 | -18.13 |
| SMA 10/50 | 43.49 | -13.02 | -7.7 | -11.31 |
| Top 3 rotation | 169.48 | -31.5 | -31.5 | -2.56 |
| SPY filter, 200-day | 99.35 | -16.72 | -16.12 | -6.06 |
| SPY filter, momentum | 107.92 | -36.34 | -36.21 | -6.64 |

**Countries**

| Strategy | Return % since 2019-07 | Max drawdown % | Covid crash % | 2022 bear % |
|---|---|---|---|---|
| Buy & hold | 85.48 | -38.78 | -36.89 | -22.12 |
| SMA 10/50 | 40.11 | -17.39 | -3.7 | -9.98 |
| Top 3 rotation | 81.08 | -40.81 | -40.11 | -19.28 |
| SPY filter, 200-day | 66.51 | -16.99 | -12.64 | -1.9 |
| SPY filter, momentum | 70.84 | -38.78 | -36.89 | -7.27 |

Only SMA 10/50 and the SPY 200-day filter cut max drawdown by more than half; the filter kept more
return. The SPY 12-1 momentum filter stayed invested through Covid, since the prior year's return was
still positive. Rotation depends on which few ETFs led. Two selloffs are a small sample.

**Rebalance frequency for top 3 rotation** (re-ranking at month-end, week-end or every day):

| Universe | Re-rank | Return % | Net of 5 bps % | Max drawdown % | 2022 bear % |
|---|---|---|---|---|---|
| Sectors | Monthly | 169.48 | 164.73 | -31.5 | -2.56 |
| Sectors | Weekly | 196.98 | 182.54 | -33.59 | 0.15 |
| Sectors | Daily | 234.81 | 202.48 | -32.27 | -1.58 |
| Countries | Monthly | 81.08 | 77.48 | -40.81 | -19.28 |
| Countries | Weekly | 114.47 | 106.09 | -36.71 | -16.64 |
| Countries | Daily | 102.9 | 83.96 | -38.68 | -19.36 |

Weekly and daily re-ranking beat monthly in both universes, before and after 5 bps. Daily lost the
most to costs (about 32 points in sectors, 19 in countries). Drawdowns changed little.

## By calendar year (`rotation_momentum.py`)

Return %. `*` marks a partial year (2019 from July, 2026 to Nov 19). Drawdown per year and the other
strategies are in `outputs/yearly_*.csv`.

**Sectors**

| Strategy | 2019* | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|---|
| Buy & hold | 7.1 | 10.8 | 29.9 | -10.5 | 17.0 | 16.6 | 13.5 | 9.8 |
| SMA 10/50 | 0.9 | 12.2 | 17.3 | -10.7 | 5.2 | 8.8 | 1.8 | 3.9 |
| Top 3 rotation | 7.2 | 16.1 | 21.0 | 9.2 | 13.5 | 18.6 | 12.3 | 8.4 |
| SPY filter, 200-day | 7.1 | 6.9 | 29.9 | -8.4 | 7.7 | 16.6 | 10.8 | 5.3 |

**Countries**

| Strategy | 2019* | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|---|
| Buy & hold | 5.8 | 11.6 | 6.0 | -12.1 | 17.1 | 3.3 | 33.4 | 4.5 |
| SMA 10/50 | 1.1 | 24.7 | 1.2 | -5.9 | 7.3 | -4.0 | 14.0 | -0.6 |
| Top 3 rotation | 6.0 | 12.7 | 10.0 | -13.0 | 3.5 | 2.9 | 24.0 | 19.9 |
| SPY filter, 200-day | 5.8 | 17.6 | 6.0 | -3.7 | 6.1 | 3.3 | 23.7 | -3.4 |

No strategy was best in every year.

## What didn't work / failure cases

- The crossover trailed buy-and-hold on return in the one-year window, with lower volatility and
  a smaller drawdown, partly from being in cash about 38% of the time.
- Strong-trend sectors with sharp dips (energy, materials, staples) lost the most, since the rule
  exits after a dip and re-enters late. Utilities and materials traded 11 times each.

## What it doesn't show

- The first backtest is one year, one market regime. Later sections add 5 and 7 years and two selloffs.
- No tax, spread or slippage beyond the 5 and 10 bps cases; close-to-close fills only; no out-of-sample test.
- Buy-and-hold baskets are rebalanced daily, a simplification.

## What I looked at first
`yfinance` for data and `pandas` for the averages. Backtesting libraries such as `vectorbt` or
`backtrader` were not used, since these rules are a few lines of pandas.

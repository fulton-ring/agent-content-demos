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

89 position changes across the 11 ETFs (about 8 each), including day-one entries.

Per ETF, the rule beat that ETF's own buy-and-hold in 1 of 11 cases (XLI). Largest
shortfalls: XLE -20.8, XLB -18.1, XLP -15.5 points. See `outputs/per_etf.csv`.

## Position sizing variants (`position_sizing.py`)

Same signal, different sizes: thirds in, Fibonacci tranches (1,1,2,3,5) in, Fibonacci in and out,
a Fibonacci win/loss progression, trend-strength sizing and inverse-volatility sizing.
Return % before costs for the 11-ETF basket (all variants are in `outputs/sizing_*.csv`):

| Variant | 1 year | 5 years | Avg. exposure % (1y) |
|---|---|---|---|
| Baseline | 4.32 | 9.01 | 62 |
| Fibonacci in and out | 5.75 | 9.34 | 59 |
| Buy & hold basket | 12.97 | 55.82 | 100 |

Fibonacci progression was invested about 8% of the time, so it is not comparable on return. Sizing
changes were small next to the gap to buy-and-hold. Other variants are in the CSVs.

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
| Momentum-weighted daily | 174.48 | -33.6 | -33.47 | -1.41 |
| SPY filter, 200-day | 99.35 | -16.72 | -16.12 | -6.06 |

**Countries**

| Strategy | Return % since 2019-07 | Max drawdown % | Covid crash % | 2022 bear % |
|---|---|---|---|---|
| Buy & hold | 85.48 | -38.78 | -36.89 | -22.12 |
| SMA 10/50 | 40.11 | -17.39 | -3.7 | -9.98 |
| Top 3 rotation | 81.08 | -40.81 | -40.11 | -19.28 |
| Momentum-weighted daily | 84.2 | -38.35 | -36.8 | -5.83 |
| SPY filter, 200-day | 66.51 | -16.99 | -12.64 | -1.9 |

Only SMA 10/50 and the SPY 200-day filter cut max drawdown by more than half; the filter kept more
return. Momentum-weighted daily weights each ETF by its positive 12-1 momentum (cash if none); its
largest position averaged 31% (sectors) and 36% (countries). Rotation depends on which few ETFs led.

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

Return % / max drawdown % within the year. `*` marks a partial year (2019 from July, 2026 to Nov 19).
Dual momentum is top 3 rotation that holds cash for a pick with negative momentum (sector exposure
94-100%, countries 56-100% by year). Other strategies and yearly exposure: `outputs/yearly_*.csv`.

**Sectors**

| Strategy | 2019* | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|---|
| Buy & hold | 7.1 / -5.1 | 10.8 / -36.3 | 29.9 / -4.7 | -10.5 / -19.2 | 17.0 / -10.3 | 16.6 / -6.4 | 13.5 / -15.0 | 9.8 / -6.3 |
| SMA 10/50 | 0.9 / -6.1 | 12.2 / -9.5 | 17.3 / -4.2 | -10.7 / -11.1 | 5.2 / -6.3 | 8.8 / -4.3 | 1.8 / -6.9 | 3.9 / -3.8 |
| Top 3 rotation | 7.2 / -4.1 | 16.1 / -31.5 | 21.0 / -7.8 | 9.2 / -15.3 | 13.5 / -10.7 | 18.6 / -8.9 | 12.3 / -15.2 | 8.4 / -9.9 |
| Dual momentum | 7.2 / -4.1 | 14.5 / -31.5 | 21.0 / -7.8 | 7.1 / -15.3 | 12.6 / -10.7 | 18.6 / -8.9 | 12.3 / -15.2 | 8.4 / -9.9 |
| Momentum-weighted daily | 7.9 / -4.2 | 15.4 / -33.6 | 23.4 / -5.5 | 7.5 / -19.3 | 15.9 / -13.5 | 16.3 / -7.2 | 15.8 / -15.0 | 6.5 / -8.6 |
| SPY filter, 200-day | 7.1 / -5.1 | 6.9 / -16.7 | 29.9 / -4.7 | -8.4 / -9.2 | 7.7 / -10.0 | 16.6 / -6.4 | 10.8 / -6.2 | 5.3 / -6.2 |

**Countries**

| Strategy | 2019* | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|---|
| Buy & hold | 5.8 / -8.3 | 11.6 / -38.8 | 6.0 / -9.4 | -12.1 / -24.0 | 17.1 / -11.9 | 3.3 / -8.7 | 33.4 / -12.8 | 4.5 / -11.2 |
| SMA 10/50 | 1.1 / -7.4 | 24.7 / -7.9 | 1.2 / -8.7 | -5.9 / -12.1 | 7.3 / -7.3 | -4.0 / -6.4 | 14.0 / -9.3 | -0.6 / -10.7 |
| Top 3 rotation | 6.0 / -10.4 | 12.7 / -40.8 | 10.0 / -10.3 | -13.0 / -22.5 | 3.5 / -16.8 | 2.9 / -7.4 | 24.0 / -16.7 | 19.9 / -17.7 |
| Dual momentum | 6.0 / -10.4 | 7.8 / -40.8 | 10.0 / -10.3 | -6.5 / -17.2 | -3.2 / -17.3 | 2.9 / -7.4 | 24.0 / -16.7 | 19.9 / -17.7 |
| Momentum-weighted daily | 5.4 / -13.3 | 1.6 / -38.3 | 8.6 / -8.5 | -7.5 / -17.4 | 10.8 / -12.8 | 6.4 / -7.0 | 33.7 / -16.4 | 8.7 / -24.2 |
| SPY filter, 200-day | 5.8 / -8.3 | 17.6 / -15.3 | 6.0 / -9.4 | -3.7 / -6.5 | 6.1 / -10.9 | 3.3 / -8.7 | 23.7 / -4.9 | -3.4 / -13.9 |

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

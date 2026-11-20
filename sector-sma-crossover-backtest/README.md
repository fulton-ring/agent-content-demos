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
`rotation_momentum.py`, `real_products.py`; shared rules in `strategies.py`. Results go to `outputs/`. Set `BACKTEST_END=YYYY-MM-DD` to move the end date;
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

Per ETF it beat that ETF's buy-and-hold in 1 of 11 cases (XLI); largest shortfalls:
XLE -20.8, XLB -18.1, XLP -15.5 points (`outputs/per_etf.csv`).

## Position sizing variants (`position_sizing.py`)

Same signal, different sizes: thirds in, Fibonacci tranches (1,1,2,3,5) in, Fibonacci in and out,
a Fibonacci win/loss progression, trend-strength sizing and inverse-volatility sizing.
Return % before costs, 1 year / 5 years: baseline 4.3 / 9.7, Fibonacci in and out 6.0 / 10.0, buy and
hold 12.6 / 55.8. Fibonacci progression was invested about 8% of the time, so it is not comparable.
Sizing changes were small next to the gap to buy-and-hold. All variants: `outputs/sizing_*.csv`.

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

Sectors, return % / max drawdown % (countries: `outputs/yearly_*`); `*` = partial year (2019 from July, 2026 to Nov 19). Dual momentum is top 3
that holds cash for a pick with negative momentum (invested 94-100% in sectors, 56-100% in countries).

**Sectors**

| Strategy | 2019* | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|---|
| Buy & hold | 7.1 / -5.1 | 10.8 / -36.3 | 29.9 / -4.7 | -10.5 / -19.2 | 17.0 / -10.3 | 16.6 / -6.4 | 13.5 / -15.0 | 9.8 / -6.3 |
| SMA 10/50 | 0.9 / -6.1 | 12.2 / -9.5 | 17.3 / -4.2 | -10.7 / -11.1 | 5.2 / -6.3 | 8.8 / -4.3 | 1.8 / -6.9 | 3.9 / -3.8 |
| Top 3 rotation | 7.2 / -4.1 | 16.1 / -31.5 | 21.0 / -7.8 | 9.2 / -15.3 | 13.5 / -10.7 | 18.6 / -8.9 | 12.3 / -15.2 | 8.4 / -9.9 |
| Dual momentum | 7.2 / -4.1 | 14.5 / -31.5 | 21.0 / -7.8 | 7.1 / -15.3 | 12.6 / -10.7 | 18.6 / -8.9 | 12.3 / -15.2 | 8.4 / -9.9 |
| Momentum-weighted daily | 7.9 / -4.2 | 15.4 / -33.6 | 23.4 / -5.5 | 7.5 / -19.3 | 15.9 / -13.5 | 16.3 / -7.2 | 15.8 / -15.0 | 6.5 / -8.6 |
| SPY filter, 200-day | 7.1 / -5.1 | 6.9 / -16.7 | 29.9 / -4.7 | -8.4 / -9.2 | 7.7 / -10.0 | 16.6 / -6.4 | 10.8 / -6.2 | 5.3 / -6.2 |

## Compared with existing funds (`real_products.py`)

Real funds (after fees) versus our rules (before fees; cash earns T-bill returns). Top 3 rotation is monthly; Top 3 daily re-ranks every day. XLSR is a sector
rotation fund, PTLC and TRND are Pacer Trendpilot 200-day trend funds, MTUM a momentum fund. Since 2019-07, %:

| Line | Return | Ann. vol | Max drawdown | Covid crash | 2022 bear |
|---|---|---|---|---|---|
| Ours: SMA 10/50 | 50.21 | 9.44 | -12.37 | -7.56 | -11.26 |
| Ours: Top 3 rotation | 164.86 | 19.74 | -31.52 | -31.52 | -2.69 |
| Ours: Top 3 daily | 202.63 | 19.79 | -32.39 | -32.27 | -2.43 |
| Ours: SPY 200-day filter | 100.93 | 11.33 | -16.87 | -16.2 | -5.96 |
| Ours: Equal-weight buy & hold | 134.38 | 18.43 | -36.34 | -36.21 | -18.13 |
| XLSR | 123.8 | 20.05 | -32.94 | -32.34 | -21.91 |
| PTLC | 92.36 | 14.19 | -26.63 | -22.79 | -9.22 |
| TRND | 51.78 | 11.34 | -17.88 | -16.38 | -15.85 |
| MTUM | 126.87 | 24.29 | -34.08 | -33.93 | -24.73 |
| SPY | 166.01 | 19.6 | -33.72 | -33.4 | -23.83 |

A 0.6% annual fee would take about 11 points off our top 3 rotation and 9 off our SPY filter over this
window. Yearly return and drawdown for every line: `outputs/products_yearly.csv`.

## What didn't work / failure cases

- The crossover trailed buy-and-hold on return in the one-year window, with lower volatility and a
  smaller drawdown, partly from being in cash 38% of the time.
- Strong-trend sectors with sharp dips (energy, materials, staples) lost the most; utilities and
  materials traded 11 times each.

## What it doesn't show

- The first backtest is one year, one market regime. Later sections add 5 and 7 years and two selloffs.
- No tax, spread or slippage beyond the 5 and 10 bps cases; close-to-close fills; no out-of-sample test;
  buy-and-hold baskets are rebalanced daily.

## What I looked at first
`yfinance` and `pandas`; backtesting libraries like `vectorbt` were skipped, as these rules are a few lines.

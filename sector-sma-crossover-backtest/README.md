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

Fibonacci progression starts each trade at 1/8 size, so it was invested about 8% of the time and
is not comparable on return. Sizing changes were small next to the gap to buy-and-hold.

## Momentum, rotation and market filters (`rotation_momentum.py`)

Asks whether momentum (trailing return) instead of price averages, rotating into the strongest ETFs,
or a market-wide filter can get ahead of big selloffs. Run on the 11 sectors and on 10 country ETFs
(SPY, EWC, EWU, EWG, EWJ, MCHI, INDA, EWZ, EWA, EWY, in US dollars). Rules are in the notebook; windows
(12-1 and 6-1 month momentum, top 3, 200-day filter) were set once, not tuned. Cash earns 0%.
All strategies and windows, including 6-1 momentum and dual momentum, are in `outputs/rotation_*.csv`.

**Sectors**

| Strategy | Return % since 2019-07 | Max drawdown % | Covid crash % | 2022 bear % |
|---|---|---|---|---|
| Buy & hold | 133.43 | -36.34 | -36.21 | -18.13 |
| SMA 10/50 | 43.76 | -13.02 | -7.7 | -11.31 |
| Momentum 12-1 | 72.12 | -31.39 | -31.3 | -10.21 |
| Top 3 rotation | 166.39 | -31.5 | -31.5 | -2.56 |
| SPY filter, 200-day | 99.35 | -16.72 | -16.12 | -6.06 |
| SPY filter, momentum | 107.08 | -36.34 | -36.21 | -6.64 |

**Countries**

| Strategy | Return % since 2019-07 | Max drawdown % | Covid crash % | 2022 bear % |
|---|---|---|---|---|
| Buy & hold | 82.59 | -38.78 | -36.89 | -22.12 |
| SMA 10/50 | 40.05 | -17.39 | -3.7 | -9.98 |
| Momentum 12-1 | 26.67 | -37.93 | -35.84 | -3.87 |
| Top 3 rotation | 75.03 | -40.81 | -40.11 | -19.28 |
| SPY filter, 200-day | 66.51 | -16.99 | -12.64 | -1.9 |
| SPY filter, momentum | 68.18 | -38.78 | -36.89 | -7.27 |

In both universes only two rules cut the max drawdown by more than half: SMA 10/50 and the SPY
200-day filter. The filter kept more of the buy-and-hold return (sectors 99 vs 44, countries 67 vs 40). The SPY 12-1 momentum filter stayed invested through the Covid crash,
since the prior year's return was still positive in February 2020. Rotation and dual momentum
results depend on which few ETFs led, and the country version did not beat buy-and-hold on drawdown.
Two selloffs are a small sample.

## By calendar year (`rotation_momentum.py`)

Return %. `*` marks a partial year (2019 from July, 2026 to Nov 20). Max drawdown per year and the other strategies are in `outputs/yearly_*.csv`.

**Sectors**

| Strategy | 2019* | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|---|
| Buy & hold | 7.1 | 10.8 | 29.9 | -10.5 | 17.0 | 16.6 | 13.5 | 9.2 |
| SMA 10/50 | 0.9 | 12.2 | 17.3 | -10.7 | 5.2 | 8.8 | 1.8 | 4.0 |
| Top 3 rotation | 7.2 | 16.1 | 21.0 | 9.2 | 13.5 | 18.6 | 12.3 | 6.9 |
| SPY filter, 200-day | 7.1 | 6.9 | 29.9 | -8.4 | 7.7 | 16.6 | 10.8 | 5.3 |
| SPY filter, momentum | 5.3 | 1.0 | 29.9 | -6.6 | 9.5 | 16.6 | 15.1 | 9.2 |

**Countries**

| Strategy | 2019* | 2020 | 2021 | 2022 | 2023 | 2024 | 2025 | 2026* |
|---|---|---|---|---|---|---|---|---|
| Buy & hold | 5.8 | 11.6 | 6.0 | -12.1 | 17.1 | 3.3 | 33.4 | 2.7 |
| SMA 10/50 | 1.1 | 24.7 | 1.2 | -5.9 | 7.3 | -4.0 | 14.0 | -0.7 |
| Top 3 rotation | 6.0 | 12.7 | 10.0 | -13.0 | 3.5 | 2.9 | 24.0 | 15.6 |
| SPY filter, 200-day | 5.8 | 17.6 | 6.0 | -3.7 | 6.1 | 3.3 | 23.7 | -3.4 |
| SPY filter, momentum | 4.5 | 6.2 | 6.0 | -7.3 | 8.8 | 3.3 | 33.4 | 2.7 |

No strategy was best in every year. In sectors, buy and hold led in 2023 and tied the SPY filters in 2021;
top-3 rotation led 2020 and 2022. In countries, the 10/50 SMA led 2020 and the 200-day filter led 2022.

## What didn't work / failure cases

- The crossover trailed buy-and-hold on return in this window. It had lower volatility and a smaller
  drawdown, partly because it was in cash about 38% of the time.
- Sectors with strong trends but sharp dips (energy, materials, staples) lost the most, since the
  rule exits after a dip and re-enters late.
- Whipsaw: utilities and materials traded 11 times each.

## What it doesn't show

- The first backtest is one year, one market regime. Later sections add 5 and 7 years and two selloffs.
- No tax, spread or slippage beyond the 5 and 10 bps cases; close-to-close fills only; no out-of-sample test.
- Buy-and-hold baskets are rebalanced daily, a simplification.

## What I looked at first
`yfinance` for data and `pandas` rolling means for the averages. Backtesting libraries such as
`vectorbt` or `backtrader` were not used, since a one-rule backtest is a few lines of pandas.

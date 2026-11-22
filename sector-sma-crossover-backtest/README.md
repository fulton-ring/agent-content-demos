# Sector ETF 10/50-day SMA crossover backtest and follow-ups

## What it shows

Started as a one-year backtest of a 10/50-day SMA crossover on the 11 sector ETFs (XLK, XLF, XLE, XLV,
XLY, XLP, XLI, XLU, XLB, XLRE, XLC). Each ETF is held while its 10-day average is above its 50-day
average, otherwise cash; capital is split equally. Follow-ups, one notebook each:

- `backtest.py`: the one-year SMA backtest (2025-11-19 to 2026-11-19).
- `position_sizing.py`: scaling in and out, Fibonacci tranches, trend-strength and volatility sizing.
- `rotation_momentum.py`: momentum, top 3 rotation, dual momentum, SPY filters, 10 country ETFs, years.
- `real_products.py`: our rules against XLSR, Pacer Trendpilot (PTLC, TRND), MTUM and SPY.
- `volatility_exit.py`: volatility gates, VIX 5/10-day exits, re-entry levels, market-direction filters.
- `vix_episodes.py`: what SPY did after the VIX crossed 25, and the VIX rules on SPY since 1993.
- `per_etf_volatility.py`: top 3 daily with per-ETF volatility. `broad_market.py`: simple broad-market rules.
- `strategies.py`, `gates.py`: position rules and the exit/re-entry gate shared by the notebooks.

Signals are read at the close and applied the next day. All thresholds were set once, not tuned.

## Run it

```
./run.sh
```

Needs `uv` and internet. Results go to `outputs/` (CSVs, one chart). Set `BACKTEST_END=YYYY-MM-DD`
to move the end date; the default is a completed day. Data: daily dividend-adjusted closes from Yahoo
Finance via `yfinance`, downloaded at run time, not committed. Yahoo restates prices, so results can
shift between runs (the volatility gate result moved by 2.6 points between two runs).

## Headline results, since 2019-07 (%)

Funds are after their fees. Our lines are before fees, with 5 bps cost per position change and cash
earning T-bill returns. Max drawdown is peak to trough on daily closes.

| Line | Return | Ann. vol | Max drawdown | Covid crash | 2022 bear |
|---|---|---|---|---|---|
| Equal-weight all sectors (no top 3) | 134.38 | 18.43 | -36.34 | -36.21 | -18.13 |
| Equal-weight + SPY volatility level gate | 146.7 | 12.65 | -13.66 | -8.37 | -5.36 |
| Top 3 daily | 202.63 | 19.79 | -32.39 | -32.27 | -2.43 |
| Top 3 daily + SPY volatility level gate | 165.99 | 14.92 | -17.97 | -7.8 | 5.77 |
| XLSR (fund) | 123.8 | 20.05 | -32.94 | -32.34 | -21.91 |
| SPY | 166.01 | 19.6 | -33.72 | -33.4 | -23.83 |

## What the other tests found

- Rotation: weekly and daily re-ranking beat monthly before and after 5 bps; daily lost about 32 points to
  costs in sectors, 19 in countries. Country rotation did not beat buy and hold on drawdown. Yearly: `outputs/yearly_*`.
- Dual momentum barely changed sectors and did not avoid Covid. XLSR trailed SPY and our top 3; top 3's 2% a year edge over
  the index is within luck over seven years. After any VIX close above 25 (48 episodes), SPY's median further 60-day drop was -6.1%.

## Volatility exit (`volatility_exit.py`)

Gates exit to cash when SPY 20-day volatility is above 25% (level), above 1.5 times its 120-day average (spike), or
per ETF (own spike). Since 2019-07 the level gate cut max drawdown and improved Covid and 2022; the spike gate lost
return over five years. Threshold sensitivity (return %, max drawdown %, Sharpe, % of days in cash):

| Top 3 daily, gate and threshold | Return | Max drawdown | Sharpe | Days in cash |
|---|---|---|---|---|
| SPY 20-day vol, exit above 25% | 165.99 | -17.97 | 0.96 | 10.94 |
| SPY vol, no gate | 202.63 | -32.39 | 0.86 | 0.0 |
| VIX 5-day, exit above 25 | 89.07 | -18.21 | 0.72 | 18.75 |

Results move with the threshold, and 29 days sat within half a point of the 25% line, so small data revisions can
flip exits. Gates act after prices fall: in Covid the level gate first exited on 2020-03-03, after SPY was down 8.6%.

## Exit when the 5- or 10-day average VIX close is above 25 (`vix_episodes.py`, `volatility_exit.py`)

SPY rule, 1993 to 2026, cash at 0% (no T-bill history), 5 bps per switch; hold while the average VIX close is at or
below 25. Return % / max drawdown %:

| Window | Buy and hold | 5-day avg | 10-day avg | 1-day |
|---|---|---|---|---|
| All years | 2805.88 / -55.19 | 538.22 / -51.92 | 625.74 / -44.42 | 554.31 / -50.91 |
| 2007-09 | -54.77 / -55.19 | -29.08 / -29.74 | -33.5 / -35.18 | -30.18 / -32.07 |
| Covid crash | -33.4 / -33.72 | -11.69 / -12.11 | -8.25 / -12.44 | -4.3 / -4.75 |
| 2022 bear | -23.83 / -24.5 | -23.33 / -23.77 | -22.82 / -23.26 | -18.41 / -20.72 |

About 18% of days in cash for all three; exits since 1993: 69 (5-day), 47 (10-day), 163 (1-day). The 5-day average crossed 25 in
37 episodes (median further 60-day drop -5.4%, 8% fell 20%+); the 10-day in 31 (-5.3%, 6%). On the sector strategies since
2019-07 both gates gave up half or more of the return; 2021, 2022 and 2025 were years they lost to no gate (`outputs/*yearly*.csv`).

### Separate re-entry level

Exit at a 5-day average VIX above 25, re-enter only at or below 25, 22, 20, 18 or 15 (grid fixed in advance). SPY
since 1993 (cash 0%): return 538.22%, 332.53%, 358.88%, 380.01%, 486.46%, max drawdown -51.92%, -52.88%, -41.57%, -40.08%, -22.97%. At 15 it sat in cash for all of 1998 to 2003 and 2021 to 2022, skipping two bear markets, not timing
rebounds. Top 3 daily since 2019-07 (no gate 202.6%): 89.07%, 64.04%, 40.1%, 61.97%, 32.6%; not monotonic.

## Taking market direction into account (`volatility_exit.py`, `vix_episodes.py`)

The exit needs both a 5-day average VIX above 25 and a falling market (SPY below its 50-day or 200-day average,
or down over 20 days); re-entry is either "back when either clears" or "back when VIX low". Of 37 episodes, 19 crossed
with SPY below its 200-day: median further 60-day drop -9.4% against -4.7% otherwise
(42.0% against 6.0% fell 10% or more). 33 of 37 were below the 50-day, too common to inform.
Top 3 daily since 2019-07, return / max drawdown: no gate 202.6% / -32.4%; VIX alone 89.1% / -18.2%;
+ SPY below 200-day (either clears) 128.6% / -17.0%.
SPY since 1993 (cash 0%): VIX alone 538.2% / -51.9%; with the 200-day filter 949.8% / -50.1% (either clears)
and 1051.0% / -47.0% (VIX low), against 2805.9% / -55.2% buy and hold (`outputs/volatility_direction*.csv`, `vix_direction_spy.csv`).

## Volatility per ETF inside Top 3 daily (`per_etf_volatility.py`)

Own spike = an ETF's 20-day volatility above 1.5 times its own 120-day average. Since 2019-07, %: return, max drawdown, Covid, 2022, exposure.

| Variant | Return | Max drawdown | Covid | 2022 | Exposure |
|---|---|---|---|---|---|
| Base | 202.6 | -32.4 | -32.3 | -2.4 | 100.0 |
| Own spike, to cash | 174.2 | -17.2 | -6.8 | -2.5 | 92.0 |
| Own spike, reallocate | 153.6 | -22.1 | -10.5 | -6.6 | 96.8 |
| Volatility-adjusted ranking | 199.1 | -30.2 | -30.2 | -4.4 | 100.0 |

Dropping a spiking ETF to cash kept the protection; refilling its slot with the next-best ETF gave much of it back (all sectors
fall together). Volatility-adjusted ranking and inverse-volatility weights barely changed the Covid drawdown.

## Simple broad-market strategies (`broad_market.py`)

Seven rules on liquid ETFs (SPY, EFA, AGG, TLT, GLD, VNQ, DBC, T-bills as cash; 5 bps costs; rules in the notebook). Sharpe is
against T-bills; since 2007-10 unless marked.

| Strategy | CAGR % | Sharpe | Max drawdown % | Sharpe since 2019-07 | 2007-09 % | 2022 bear % |
|---|---|---|---|---|---|---|
| SPY buy & hold | 10.33 | 0.53 | -55.19 | 0.64 | -54.77 | -23.83 |
| 60/40 SPY/AGG | 7.81 | 0.57 | -34.7 | 0.55 | -34.39 | -20.26 |
| SPY/TLT/GLD thirds | 8.23 | 0.7 | -22.74 | 0.55 | -6.63 | -22.06 |
| SPY 200-day | 8.47 | 0.64 | -21.02 | 0.68 | -11.89 | -12.5 |
| Faber 5-asset | 4.86 | 0.45 | -17.54 | 0.51 | -5.94 | -4.02 |
| Dual momentum | 7.88 | 0.48 | -33.72 | 0.4 | 7.17 | -19.51 |
| Vol-targeted SPY | 7.76 | 0.64 | -24.3 | 0.67 | -23.78 | -11.95 |

Nothing beat SPY on return. The 200-day and volatility-target rules lifted Sharpe by cutting drawdowns; the bond and gold mixes
benefited from bonds (strong to 2020, weak in 2022). Gains did not hold in every window (`outputs/broad_*.csv`, `broad_yearly.csv`).

## What didn't work / failure cases

- The crossover trailed buy and hold in the one-year window, with lower volatility and drawdown, partly
  from being in cash 38% of the time. Utilities and materials traded 11 times each.
- Momentum windows, spike gates, tight volatility thresholds and country rotation gave up return or
  were unstable.

## What it doesn't show

- Seven years, one crash and one bear market; no out-of-sample test, so gate and rotation results may not repeat.
- Fund holdings are not reproduced; fund fees are inside their returns, ours are not (a 0.6% yearly fee would take about
  9 to 11 points off our top lines). No taxes or spreads beyond 5 bps; close-to-close fills.

## What I looked at first

`yfinance` and `pandas`; backtesting libraries like `vectorbt` were skipped, as these rules are a few lines.

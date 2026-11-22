# Sector ETF 10/50-day SMA crossover backtest and follow-ups

## What it shows

Started as a one-year backtest of a 10/50-day SMA crossover on the 11 sector ETFs (XLK, XLF, XLE, XLV,
XLY, XLP, XLI, XLU, XLB, XLRE, XLC). Each ETF is held while its 10-day average is above its 50-day
average, otherwise cash; capital is split equally. Follow-ups, one notebook each:

- `backtest.py`: the one-year SMA backtest (2025-11-19 to 2026-11-19).
- `position_sizing.py`: scaling in and out, Fibonacci tranches, trend-strength and volatility sizing.
- `rotation_momentum.py`: momentum instead of price, top 3 rotation (monthly, weekly, daily),
  momentum-weighted baskets, dual momentum, SPY market filters, 10 country ETFs, calendar years.
- `real_products.py`: our rules against XLSR, Pacer Trendpilot (PTLC, TRND), MTUM and SPY.
- `volatility_exit.py`: exiting to cash when volatility is unstable, threshold sensitivity, years.
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
| Equal-weight + SPY volatility level gate | 144.09 | 12.66 | -13.66 | -8.37 | -6.36 |
| Equal-weight + exit on 5-day avg VIX > 25 | 59.98 | 11.12 | -21.06 | -11.22 | -17.04 |
| Top 3 daily | 202.63 | 19.79 | -32.39 | -32.27 | -2.43 |
| Top 3 daily + SPY volatility level gate | 162.87 | 14.93 | -17.97 | -7.8 | 4.53 |
| Top 3 daily + exit on 5-day avg VIX > 25 | 89.07 | 13.32 | -18.21 | -11.51 | -4.09 |
| XLSR (fund) | 123.8 | 20.05 | -32.94 | -32.34 | -21.91 |
| PTLC (fund) | 92.36 | 14.19 | -26.63 | -22.79 | -9.22 |
| SPY | 166.01 | 19.6 | -33.72 | -33.4 | -23.83 |

First backtest, one year to 2026-11-19, cash at 0%: SMA 10/50 basket 4.32%, equal-weight buy and
hold 12.97%, SPY 9.62%. It beat its own sector's buy and hold in 1 of 11 ETFs (XLI).

## What the other tests found

- Sizing (`outputs/sizing_*.csv`): scale-in and Fibonacci variants moved one-year return by about 1 point
  and showed no clear five-year gain. Volatility and trend-strength sizing mostly cut exposure.
- Rotation: weekly and daily re-ranking beat monthly before and after 5 bps. Daily lost about
  32 points to costs in sectors and 19 in countries (0% cash). On 10 country ETFs, rotation
  did not beat buy and hold on drawdown. Calendar-year tables: `outputs/yearly_*` and
  `outputs/products_yearly.csv`; no strategy was best in every year.
- Dual momentum (cash for a negative-momentum pick) barely changed sectors; it did not avoid the Covid crash.
- Funds: XLSR trailed SPY and our top 3. Top 3 rotation's 2% a year edge over the index is within luck over seven years.

## Volatility exit (`volatility_exit.py`)

Gates exit to cash when SPY 20-day volatility is above 25% (level), above 1.5 times its 120-day average (spike), or
per ETF (own spike). Since 2019-07 the level gate cut max drawdown and improved Covid and 2022; the spike gate lost
return over five years. Threshold sensitivity (return %, max drawdown %, Sharpe, % of days in cash):

| Top 3 daily, gate and threshold | Return | Max drawdown | Sharpe | Days in cash |
|---|---|---|---|---|
| SPY 20-day vol, exit above 25% | 162.87 | -17.97 | 0.95 | 10.88 |
| SPY vol, no gate | 202.63 | -32.39 | 0.86 | 0.0 |
| VIX 5-day, exit above 15 | 47.15 | -7.62 | 1.09 | 80.66 |
| VIX 5-day, exit above 25 | 89.07 | -18.21 | 0.72 | 18.75 |
| VIX 5-day, exit above 35 | 158.34 | -18.45 | 0.88 | 2.8 |

Results move a lot with the threshold, and 29 days sat within half a point of the 25% line, so small data
revisions can flip exits. Gates act after prices fall: in the Covid crash the level gate first exited on
2020-03-03 after SPY was down about 8.6%.

## How far did SPY fall after the VIX crossed 25? (`vix_episodes.py`)

48 episodes since 1993 (first close above 25 after 20 quiet days). Median further drop in the next 60 trading days:
-6.1%; 5% or more in 60% of episodes, 10% or more in 29%, 20% or more in 6% (2002, 2008, 2020).
SPY was higher after 60 days in 58%. Worst: 2008-09-09 (further -38.4%) and 2020-02-24 (-30.4%): `outputs/vix_episodes.csv`.

## Exit when the 5- or 10-day average VIX close is above 25 (`vix_episodes.py`, `volatility_exit.py`)

SPY rule, 1993 to 2026, cash at 0% (no T-bill history), 5 bps per switch; hold while the average VIX close is at or
below 25. Return % / max drawdown %:

| Window | Buy and hold | 5-day avg | 10-day avg | 1-day |
|---|---|---|---|---|
| All years | 2805.88 / -55.19 | 538.22 / -51.92 | 625.74 / -44.42 | 554.31 / -50.91 |
| 2007-09 | -54.77 / -55.19 | -29.08 / -29.74 | -33.5 / -35.18 | -30.18 / -32.07 |
| Covid crash | -33.4 / -33.72 | -11.69 / -12.11 | -8.25 / -12.44 | -4.3 / -4.75 |
| 2022 bear | -23.83 / -24.5 | -23.33 / -23.77 | -22.82 / -23.26 | -18.41 / -20.72 |
| Since 2019-07 | 166.01 / -33.72 | 75.0 / -28.06 | 68.88 / -27.64 | 80.63 / -23.03 |

Days in cash are about 18% for all three; exits since 1993: 69 (5-day), 47 (10-day), 163 (1-day). The 5-day average
crossed 25 in 37 episodes (median further 60-day drop -5.4%, 8% fell 20% or more); the 10-day in 31 (-5.3%, 6%).
In the sector strategies since 2019-07 both gates gave up about half or more of the return (table above), and
2021, 2022 and 2025 were years they lost to no gate. Years: `outputs/vix_rule_yearly.csv`, `outputs/volatility_yearly.csv`.

### Separate re-entry level

Exit at a 5-day average VIX above 25, re-enter only at or below 25, 22, 20, 18 or 15 (grid fixed in advance). SPY
since 1993 (cash 0%): return 538.22%, 332.53%, 358.88%, 380.01%, 486.46%, max drawdown
-51.92%, -52.88%, -41.57%, -40.08%, -22.97%. At 15 it sat in cash for all of 1998 to 2003 and 2021 to 2022, so its result
comes from skipping two bear markets, not timing rebounds. Top 3 daily since 2019-07 (no gate 202.6%): 89.07%, 64.04%,
40.1%, 61.97%, 32.6%; not monotonic (`outputs/vix_reentry_*.csv`, `outputs/volatility_reentry.csv`).

## Taking market direction into account (`volatility_exit.py`, `vix_episodes.py`)

The exit needs both a 5-day average VIX above 25 and a falling market (SPY below its 50-day or 200-day average,
or down over 20 days); re-entry is either "back when either clears" or "back when VIX low". Of 37 episodes, 19 crossed
with SPY below its 200-day: median further 60-day drop -9.4% against -4.7% otherwise
(42.0% against 6.0% fell 10% or more). 33 of 37 were below the 50-day, too common to inform.
Since 2019-07, %: return, max drawdown, Covid, 2022, % days in cash, exits.

| Sector line | Return | Max drawdown | Covid | 2022 | Cash | Exits |
|---|---|---|---|---|---|---|
| Top 3 daily, no gate | 202.6 | -32.4 | -32.3 | -2.4 | 0.0 | 0.0 |
| Top 3 daily, VIX 5-day alone | 89.1 | -18.2 | -11.5 | -4.1 | 18.8 | 17.0 |
| + SPY below 200-day, back when either clears | 128.6 | -17.0 | -15.5 | -0.1 | 11.5 | 12.0 |
| + SPY below 200-day, back when VIX low | 111.6 | -17.2 | -11.5 | -3.5 | 14.4 | 10.0 |
| Equal-weight, VIX 5-day alone | 60.0 | -21.1 | -11.2 | -17.0 | 18.8 | 17.0 |
| Equal-weight + SPY below 200-day, either clears | 86.7 | -19.8 | -16.2 | -16.7 | 11.5 | 12.0 |

SPY since 1993 (cash 0%): VIX alone 538.2% / -51.9%; with the 200-day filter 949.8% / -50.1% (either clears)
and 1051.0% / -47.0% (VIX low), against 2805.9% / -55.2% buy and hold. Everything is in `outputs/volatility_direction*.csv`
and `outputs/vix_direction_spy.csv`.

## What didn't work / failure cases

- The crossover trailed buy and hold in the one-year window, with lower volatility and drawdown, partly
  from being in cash 38% of the time. Utilities and materials traded 11 times each.
- Momentum windows, spike gates, tight volatility thresholds and country rotation gave up return or
  were unstable.

## What it doesn't show

- Seven years, one crash and one bear market. No out-of-sample test, so gate and rotation results
  may not repeat.
- Fund results are reported, not their holdings; fund fees are inside their returns, ours are not
  (a 0.6% yearly fee would take roughly 9 to 11 points off our top lines over this window).
- No taxes, spreads or slippage beyond 5 bps. Close-to-close fills.

## What I looked at first

`yfinance` and `pandas`; backtesting libraries like `vectorbt` were skipped, as these rules are a few lines.

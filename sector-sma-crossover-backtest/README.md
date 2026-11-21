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
| Sector buy and hold | 134.38 | 18.43 | -36.34 | -36.21 | -18.13 |
| SMA 10/50 (each sector) | 50.21 | 9.44 | -12.37 | -7.56 | -11.26 |
| Top 3 rotation, monthly | 164.86 | 19.74 | -31.52 | -31.52 | -2.69 |
| Top 3 rotation, daily | 202.63 | 19.79 | -32.39 | -32.27 | -2.43 |
| SPY 200-day filter | 100.93 | 11.33 | -16.87 | -16.2 | -5.96 |
| Top 3 daily + SPY volatility level gate | 162.87 | 14.93 | -17.97 | -7.8 | 4.53 |
| Top 3 daily + exit on 5-day avg VIX > 25 | 89.07 | 13.32 | -18.21 | -11.51 | -4.09 |
| Top 3 daily + exit on 10-day avg VIX > 25 | 84.21 | 13.53 | -18.39 | -7.8 | -4.38 |
| XLSR (fund) | 123.8 | 20.05 | -32.94 | -32.34 | -21.91 |
| PTLC (fund) | 92.36 | 14.19 | -26.63 | -22.79 | -9.22 |
| TRND (fund) | 51.78 | 11.34 | -17.88 | -16.38 | -15.85 |
| MTUM (fund) | 126.87 | 24.29 | -34.08 | -33.93 | -24.73 |
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
- Dual momentum (cash for a negative-momentum pick) barely changed sectors; it mattered in countries
  in 2022 (invested about 58%). It did not avoid the Covid crash, since 12-month momentum was positive.
- Funds: XLSR trailed SPY and our top 3; the Pacer funds had lower drawdowns than SPY.
- Versus the index: top 3 rotation had 0.88 correlation and 0.94 beta to the equal-weight sector basket
  and about 2% a year excess return, which is within what luck could produce over seven years.

## Volatility exit (`volatility_exit.py`)

Gates exit to cash when SPY 20-day volatility is above 25% (level), above 1.5 times its 120-day average
(spike), or per ETF (own spike). Since 2019-07 the level gate cut max drawdown in both bases and
improved the Covid and 2022 windows. The spike gate lost return over five years in all three bases.
Threshold sensitivity, since 2019-07 (return %, max drawdown %, Sharpe, % of days in cash):

| Top 3 daily, gate and threshold | Return | Max drawdown | Sharpe | Days in cash |
|---|---|---|---|---|
| SPY 20-day vol, exit above 25% | 162.87 | -17.97 | 0.95 | 10.88 |
| SPY vol, no gate | 202.63 | -32.39 | 0.86 | 0.0 |
| VIX 5-day, exit above 15 | 47.15 | -7.62 | 1.09 | 80.66 |
| VIX 5-day, exit above 20 | 41.39 | -18.4 | 0.5 | 38.85 |
| VIX 5-day, exit above 25 | 89.07 | -18.21 | 0.72 | 18.75 |
| VIX 5-day, exit above 30 | 116.19 | -23.29 | 0.77 | 7.92 |
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

Exit stays at a 5-day average VIX above 25; re-entry only at or below the level shown (grid fixed in advance).
SPY, 1993 to 2026, cash at 0% (buy and hold: 2805.88% return, -55.19% drawdown):

| Re-enter at | Return % | Max drawdown % | 2007-09 % | 2022 % | Days in cash % | Exits |
|---|---|---|---|---|---|---|
| 25 | 538.22 | -51.92 | -29.08 | -23.33 | 17.7 | 69 |
| 22 | 332.53 | -52.88 | -30.79 | -19.33 | 23.2 | 42 |
| 20 | 358.88 | -41.57 | -31.17 | -21.73 | 29.4 | 29 |
| 18 | 380.01 | -40.08 | -18.37 | -7.44 | 35.9 | 22 |
| 15 | 486.46 | -22.97 | 0.0 | 0.0 | 48.9 | 10 |

A lower re-entry level cuts crash exposure but keeps the portfolio out for years: at 15 it was in cash for all of
1998 to 2003 and 2021 to 2022, so its all-years result comes from skipping two bear markets, not timing rebounds.
Top 3 daily since 2019-07 (no gate 202.6%): re-entry at 25, 22, 20, 18, 15 gave 89.07%, 64.04%,
40.1%, 61.97%, 32.6%; not monotonic (`outputs/vix_reentry_*.csv`, `outputs/volatility_reentry.csv`).

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

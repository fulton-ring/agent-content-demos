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
- `strategies.py`: position rules shared by the notebooks.

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
| Top 3 monthly + volatility level gate | 150.53 | 14.93 | -15.64 | -7.29 | 7.23 |
| Sector buy and hold + volatility level gate | 144.09 | 12.66 | -13.66 | -8.37 | -6.36 |
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

| Top 3 monthly | Return | Max drawdown | Sharpe | Days in cash |
|---|---|---|---|---|
| Top 3 monthly, exit above 15% | 65.44 | -11.32 | 0.68 | 40.09 |
| Top 3 monthly, exit above 20% | 98.39 | -14.11 | 0.76 | 21.07 |
| Top 3 monthly, exit above 25% | 150.53 | -15.64 | 0.91 | 10.88 |
| Top 3 monthly, exit above 30% | 134.84 | -19.71 | 0.81 | 5.33 |
| Top 3 monthly, exit above 35% | 170.22 | -15.45 | 0.9 | 3.45 |
| Top 3 monthly, no gate | 164.86 | -31.52 | 0.77 | 0.0 |

Results move a lot with the threshold (exits above 15% or 20% gave up 40 to 60% of the return), and 29 days
sat within half a point of the 25% line, so small data revisions can flip exits. Gates act after prices
have already fallen: in the Covid crash the level gate first exited on 2020-03-03 after SPY was down
about 8.6%.

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

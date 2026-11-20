import marimo

app = marimo.App()


@app.cell
def _():
    import os
    from pathlib import Path

    import marimo as mo
    import numpy as np
    import pandas as pd
    import yfinance as yf

    return Path, mo, np, os, pd, yf


@app.cell
def _(mo):
    mo.md("""
    # Can momentum, rotation or a market filter get ahead of big selloffs?

    Two ETF universes, same strategies on each:

    - **Sectors:** the 11 Select Sector SPDRs from `backtest.py`.
    - **Countries:** US (SPY), Canada (EWC), UK (EWU), Germany (EWG), Japan (EWJ), China (MCHI),
      India (INDA), Brazil (EWZ), Australia (EWA), South Korea (EWY). Returns are in US dollars.

    Momentum here means the trailing return over a past window, skipping the most recent month
    (the usual "12-1" definition). The price-based rule is the 10/50 SMA crossover. Windows
    (12 and 6 months) were fixed in advance, not tuned.

    | Strategy | Rule |
    |---|---|
    | Buy & hold | equal weight, always invested |
    | SMA 10/50 | each ETF on while 10-day SMA > 50-day SMA |
    | Momentum 12-1 | each ETF on while its 12-1 month return > 0 |
    | Momentum 6-1 | each ETF on while its 6-1 month return > 0 |
    | Top 3 rotation | each month-end hold the 3 ETFs with the best 12-1 momentum, 1/3 each |
    | Dual momentum | same top 3, but an ETF is held only if its 12-1 momentum is also > 0, else cash |
    | SPY filter, 200-day | hold the equal-weight basket unless SPY is below its 200-day average, then cash |
    | SPY filter, momentum | hold the basket unless SPY's 12-1 return is < 0, then cash |

    Positions are decided at the close and earn the next day's return. Cash earns 0%.
    """)


@app.cell
def _(Path, os, pd, yf):
    end = pd.Timestamp(os.environ.get("BACKTEST_END", "2026-11-20"))
    universes = {
        "Sectors": [
            "XLK",
            "XLF",
            "XLE",
            "XLV",
            "XLY",
            "XLP",
            "XLI",
            "XLU",
            "XLB",
            "XLRE",
            "XLC",
        ],
        "Countries": [
            "SPY",
            "EWC",
            "EWU",
            "EWG",
            "EWJ",
            "MCHI",
            "INDA",
            "EWZ",
            "EWA",
            "EWY",
        ],
    }
    all_tickers = sorted({t for ts in universes.values() for t in ts} | {"SPY"})
    raw = yf.download(
        all_tickers,
        start="2017-01-03",
        end=end + pd.Timedelta(days=1),
        auto_adjust=True,
        progress=False,
    )
    prices = raw["Close"]
    assert prices.index[-1] >= end - pd.Timedelta(days=4), "data is stale"
    first_full = prices.dropna().index[0]
    study_start = first_full + pd.Timedelta(days=380)
    out_dir = Path(os.environ.get("OUT_DIR", "outputs"))
    out_dir.mkdir(exist_ok=True)
    print(
        f"All tickers present from {first_full.date()}; studies start {study_start.date()}"
    )
    return end, out_dir, prices, study_start, universes


@app.cell
def _(mo):
    mo.md("""
    ## Strategy positions

    `weights` returns the fraction of capital in each ETF, decided at each close and applied to the
    next day. The rotation rules only change on the last trading day of each month.
    """)


@app.cell
def _(pd, prices):
    month_ends = (
        prices.index.to_series().groupby(prices.index.to_period("M")).last().to_numpy()
    )
    spy = prices["SPY"]
    spy_above_200 = (spy > spy.rolling(200).mean()).astype(float)
    spy_mom_ok = (spy.shift(21) / spy.shift(252) - 1 > 0).astype(float)

    def weights(tickers: list[str]) -> dict[str, pd.DataFrame]:
        px = prices[tickers]
        n = len(tickers)
        mom12 = px.shift(21) / px.shift(252) - 1
        mom6 = px.shift(21) / px.shift(126) - 1
        top3 = (mom12.rank(axis=1, ascending=False) <= 3) & mom12.notna()
        rotation = (top3 / 3).loc[month_ends].reindex(px.index).ffill()
        dual = ((top3 & (mom12 > 0)) / 3).loc[month_ends].reindex(px.index).ffill()
        equal = pd.DataFrame(1.0 / n, index=px.index, columns=tickers)
        raw = {
            "Buy & hold": equal,
            "SMA 10/50": (px.rolling(10).mean() > px.rolling(50).mean()) / n,
            "Momentum 12-1": (mom12 > 0) / n,
            "Momentum 6-1": (mom6 > 0) / n,
            "Top 3 rotation": rotation,
            "Dual momentum": dual,
            "SPY filter, 200-day": equal.mul(spy_above_200, axis=0),
            "SPY filter, momentum": equal.mul(spy_mom_ok, axis=0),
        }
        return {k: v.astype(float).shift(1).fillna(0.0) for k, v in raw.items()}

    return (weights,)


@app.cell
def _(mo):
    mo.md("""
    ## Results

    Three windows ending on the same date, plus two selloffs measured on their own:
    the Covid crash (2020-02-19 to 2020-03-23) and the 2022 bear market (2022-01-03 to 2022-10-14).
    "Net" charges 5 bps per unit of position change.
    """)


@app.cell
def _(end, np, out_dir, pd, prices, study_start, universes, weights):
    def metrics(w: pd.DataFrame, ret: pd.DataFrame) -> dict[str, float]:
        gross = (w * ret).sum(axis=1)
        cost = w.diff().abs().fillna(w.abs()).sum(axis=1) * 5 / 10_000
        equity = (1 + gross).cumprod()
        return {
            "return_%": 100 * (equity.iloc[-1] - 1),
            "net_return_%": 100 * ((1 + gross - cost).cumprod().iloc[-1] - 1),
            "ann_vol_%": 100 * gross.std() * np.sqrt(252),
            "sharpe": gross.mean() / gross.std() * np.sqrt(252),
            "max_drawdown_%": 100 * (equity / equity.cummax() - 1).min(),
            "exposure_%": 100 * w.sum(axis=1).mean(),
        }

    windows = {
        "1 year": (end - pd.DateOffset(years=1), end),
        "5 years": (end - pd.DateOffset(years=5), end),
        f"since {study_start.date()}": (study_start, end),
        "Covid crash": (pd.Timestamp("2020-02-19"), pd.Timestamp("2020-03-23")),
        "2022 bear": (pd.Timestamp("2022-01-03"), pd.Timestamp("2022-10-14")),
    }
    daily = prices.pct_change()
    tables = {}
    for uni, tickers in universes.items():
        paths = weights(tickers)
        for label, (lo, hi) in windows.items():
            sel = (daily.index >= lo) & (daily.index <= hi)
            ret = daily.loc[sel, tickers]
            assert not ret.isna().any().any(), f"missing data in {uni} {label}"
            table = pd.DataFrame(
                {k: metrics(w[sel], ret) for k, w in paths.items()}
            ).T.round(2)
            tables[(uni, label)] = table
            name = f"rotation_{uni}_{label}".replace(" ", "_")
            table.to_csv(out_dir / f"{name}.csv")
            print(
                f"\n=== {uni}, {label}: {ret.index[0].date()} to {ret.index[-1].date()} ==="
            )
            print(table.to_string())


@app.cell
def _(mo):
    mo.md("""
    ## What this does not show

    - Covid 2020 and 2022 are two selloffs. Rules that happened to exit early in them may not
      exit early in the next one, which could look different (slow grind, sudden gap).
    - Country returns are in dollars, so currency moves are mixed in with local stock moves.
    - Three universes picks (11 sectors, 10 countries) are one choice each, not a survey.
    - Momentum windows, top-3 count and the 200-day filter were set once, not tuned.
    - Taxes and spreads beyond 5 bps are ignored. Cash earns 0%.
    """)


if __name__ == "__main__":
    app.run()

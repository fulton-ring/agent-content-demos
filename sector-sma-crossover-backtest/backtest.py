import marimo

app = marimo.App()


@app.cell
def _():
    import os
    from pathlib import Path

    import marimo as mo
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import yfinance as yf

    return Path, mo, np, os, pd, plt, yf


@app.cell
def _(mo):
    mo.md("""
    # Does a 10/50-day SMA crossover beat buy-and-hold on sector ETFs?

    **Rule:** for each of the 11 SPDR sector ETFs, hold it while the 10-day simple moving
    average is above the 50-day average; otherwise hold cash (0% return).
    Capital is split equally across the 11 ETFs. The signal is read at the close and
    traded at the *next* day's close-to-close return, so there is no look-ahead.

    **Window:** the last 365 days. Prices before that are loaded only so the 50-day
    average is already warm on day one.
    """)


@app.cell
def _(Path, os, pd, yf):
    end = pd.Timestamp(os.environ.get("BACKTEST_END", "2026-11-20"))
    start = end - pd.DateOffset(years=1)
    sectors = {
        "XLK": "Technology", "XLF": "Financials", "XLE": "Energy",
        "XLV": "Health Care", "XLY": "Consumer Discretionary",
        "XLP": "Consumer Staples", "XLI": "Industrials", "XLU": "Utilities",
        "XLB": "Materials", "XLRE": "Real Estate", "XLC": "Communication Services",
    }  # fmt: skip
    tickers = [*sectors, "SPY"]
    raw = yf.download(
        tickers,
        start=start - pd.DateOffset(months=6),
        end=end + pd.Timedelta(days=1),
        auto_adjust=True,
        progress=False,
    )
    prices = raw["Close"].dropna()
    assert set(tickers) <= set(prices.columns), "missing tickers"
    assert prices.index[-1] >= end - pd.Timedelta(days=4), "data is stale"
    out_dir = Path(os.environ.get("OUT_DIR", "outputs"))
    out_dir.mkdir(exist_ok=True)
    print(
        f"{len(prices)} trading days, {prices.index[0].date()} to {prices.index[-1].date()}"
    )
    return end, out_dir, prices, sectors, start


@app.cell
def _(mo):
    mo.md("""
    ## Signals and daily strategy returns

    `position` is 1 when SMA10 > SMA50 as of the *previous* close. A trade is any day
    the position changes. Prices are dividend-adjusted closes.
    """)


@app.cell
def _(prices, sectors, start):
    etfs = list(sectors)
    sma_fast = prices[etfs].rolling(10).mean()
    sma_slow = prices[etfs].rolling(50).mean()
    position = (sma_fast > sma_slow).astype(float).shift(1)
    daily = prices.pct_change()
    in_window = prices.index >= start
    window_pos = position[in_window].fillna(0.0)
    window_ret = daily[in_window]
    strat_ret = window_pos * window_ret[etfs]
    trades = window_pos.diff().abs()
    trades.iloc[0] = window_pos.iloc[0]
    print(f"Window starts {window_ret.index[0].date()}, {len(window_ret)} trading days")
    return etfs, sma_fast, sma_slow, strat_ret, trades, window_pos, window_ret


@app.cell
def _(mo):
    mo.md("""
    ## Results

    Basket = equal weight across the 11 ETFs, rebalanced daily. Costs are charged per
    unit of position change (basis points of the traded amount). Sharpe uses a 0% risk-free
    rate to keep it simple; max drawdown is peak-to-trough on daily closes.
    """)


@app.cell
def _(np, pd, strat_ret, trades, window_pos, window_ret, etfs):
    def summarize(r: pd.Series) -> dict[str, float]:
        equity = (1 + r).cumprod()
        return {
            "total_return_%": 100 * (equity.iloc[-1] - 1),
            "ann_vol_%": 100 * r.std() * np.sqrt(252),
            "sharpe": r.mean() / r.std() * np.sqrt(252),
            "max_drawdown_%": 100 * (equity / equity.cummax() - 1).min(),
        }

    rows = {}
    for bps in (0, 5, 10):
        cost = trades.mean(axis=1) * bps / 10_000
        rows[f"SMA 10/50 basket ({bps} bps/trade)"] = summarize(
            strat_ret.mean(axis=1) - cost
        )
    rows["Buy & hold basket (equal weight)"] = summarize(window_ret[etfs].mean(axis=1))
    rows["Buy & hold SPY"] = summarize(window_ret["SPY"])
    results = pd.DataFrame(rows).T.round(2)
    results["trades"] = [
        int(trades.sum().sum()), int(trades.sum().sum()), int(trades.sum().sum()), 0, 0,
    ]  # fmt: skip
    results["avg_time_in_market_%"] = [
        round(100 * window_pos.mean().mean(), 1), round(100 * window_pos.mean().mean(), 1),
        round(100 * window_pos.mean().mean(), 1), 100.0, 100.0,
    ]  # fmt: skip
    print(results.to_string())
    return results, summarize


@app.cell
def _(mo):
    mo.md("""
    ## Per ETF

    Same rule on each ETF alone, with no costs, next to that ETF's own buy-and-hold return.
    """)


@app.cell
def _(etfs, pd, sectors, strat_ret, summarize, trades, window_pos, window_ret):
    per_etf = pd.DataFrame(
        {
            "sector": pd.Series(sectors),
            "sma_return_%": {
                t: summarize(strat_ret[t])["total_return_%"] for t in etfs
            },
            "buy_hold_return_%": {
                t: summarize(window_ret[t])["total_return_%"] for t in etfs
            },
            "trades": trades.sum().astype(int),
            "time_in_market_%": 100 * window_pos.mean(),
        }
    ).round(1)
    per_etf["sma_minus_hold_%"] = (
        per_etf["sma_return_%"] - per_etf["buy_hold_return_%"]
    ).round(1)
    print(per_etf.to_string())
    return (per_etf,)


@app.cell
def _(end, out_dir, per_etf, plt, results, start, strat_ret, window_ret, etfs):
    fig, ax = plt.subplots(figsize=(9, 4.5))
    (1 + strat_ret.mean(axis=1)).cumprod().plot(ax=ax, label="SMA 10/50 basket (0 bps)")
    (1 + window_ret[etfs].mean(axis=1)).cumprod().plot(ax=ax, label="Buy & hold basket")
    (1 + window_ret["SPY"]).cumprod().plot(ax=ax, label="Buy & hold SPY", alpha=0.7)
    ax.set_title(f"Growth of $1, {start.date()} to {end.date()}")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_dir / "equity_curves.png", dpi=150)
    results.to_csv(out_dir / "results.csv")
    per_etf.to_csv(out_dir / "per_etf.csv")
    print(f"saved to {out_dir}/")


@app.cell
def _(mo):
    mo.md("""
    ## What this does not show

    - One year is one market regime. Crossover results vary a lot from year to year.
    - Fast/slow windows were fixed at 10/50 as asked, not tuned.
    - Cash earns 0%, taxes and bid/ask spreads beyond the bps shown are ignored.
    - Daily rebalancing of the buy-and-hold basket is a simplification.
    """)


if __name__ == "__main__":
    app.run()

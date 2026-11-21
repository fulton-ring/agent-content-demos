import marimo

app = marimo.App()


@app.cell
def _():
    import os
    from pathlib import Path

    import marimo as mo
    import pandas as pd
    import yfinance as yf

    return Path, mo, os, pd, yf


@app.cell
def _(mo):
    mo.md("""
    # How much further did the market fall after the VIX crossed 25?

    The volatility gates in `volatility_exit.py` used SPY's own 20-day realized volatility. This
    notebook uses the VIX itself. An **episode** starts on the first close above 25 after at least
    20 trading days at or below 25, so a VIX that bounces around 25 counts once.

    For each episode, from the close of the crossing day:

    - `already_down_%`: SPY's drop from its highest close in the prior 252 trading days.
    - `further_drop_%`: the lowest SPY close in the next 60 trading days, versus the crossing close.
    - `return_20d_%`, `return_60d_%`: SPY's return over the next 20 and 60 trading days.

    The next-day price is what a gate could actually trade at, so `further_drop_%` is measured from
    the crossing close, not the next open. Data starts when SPY does (1993).
    """)


@app.cell
def _(Path, os, pd, yf):
    end = pd.Timestamp(os.environ.get("BACKTEST_END", "2026-11-19"))
    raw = yf.download(
        ["SPY", "^VIX"],
        start="1993-01-29",
        end=end + pd.Timedelta(days=1),
        auto_adjust=True,
        progress=False,
    )
    prices = raw["Close"].dropna()
    assert prices.index[-1] >= end - pd.Timedelta(days=4), "data is stale"
    out_dir = Path(os.environ.get("OUT_DIR", "outputs"))
    out_dir.mkdir(exist_ok=True)
    print(f"{len(prices)} days, {prices.index[0].date()} to {prices.index[-1].date()}")
    return end, out_dir, prices


@app.cell
def _(out_dir, pd, prices):
    spy = prices["SPY"]
    vix = prices["^VIX"]
    above = vix > 25
    quiet_before = ~above.shift(1, fill_value=False).rolling(20).max().fillna(1).astype(
        bool
    )
    starts = prices.index[above & quiet_before]
    rows = {}
    for _day in starts:
        _i = prices.index.get_loc(_day)
        _close = spy.iloc[_i]
        _prior_high = spy.iloc[max(0, _i - 252) : _i + 1].max()
        _next60 = spy.iloc[_i + 1 : _i + 61]
        if len(_next60) < 60:
            continue
        rows[str(_day.date())] = {
            "vix": round(float(vix.iloc[_i]), 1),
            "already_down_%": round(100 * (_close / _prior_high - 1), 1),
            "further_drop_%": round(100 * (_next60.min() / _close - 1), 1),
            "return_20d_%": round(100 * (spy.iloc[_i + 20] / _close - 1), 1),
            "return_60d_%": round(100 * (spy.iloc[_i + 60] / _close - 1), 1),
        }
    episodes = pd.DataFrame(rows).T
    episodes.to_csv(out_dir / "vix_episodes.csv")
    print(episodes.to_string())
    return (episodes,)


@app.cell
def _(episodes, out_dir, pd):
    summary = pd.DataFrame(
        {
            "median": episodes.median(),
            "worst": episodes[
                ["already_down_%", "further_drop_%", "return_20d_%", "return_60d_%"]
            ].min(),
            "best": episodes[
                ["already_down_%", "further_drop_%", "return_20d_%", "return_60d_%"]
            ].max(),
        }
    ).round(1)
    summary.to_csv(out_dir / "vix_episodes_summary.csv")
    print(f"\n{len(episodes)} episodes with 60 days of data after the cross")
    print(summary.to_string())
    for _limit in (5, 10, 20):
        _share = (episodes["further_drop_%"] <= -_limit).mean()
        print(
            f"further drop of {_limit}% or more within 60 days: {100 * _share:.0f}% of episodes"
        )
    print(
        f"SPY higher after 60 days: {100 * (episodes['return_60d_%'] > 0).mean():.0f}% of episodes"
    )


@app.cell
def _(mo):
    mo.md("""
    ## What this does not show

    - Few episodes, and the big ones (2000-02, 2008, 2020) overlap with their own long falls.
    - Prices are SPY closes. It ignores what a gate would have done after the exit (when to
      re-enter), which is what decides the cost of exiting.
    - A crossing close is known only after the close, so the earliest trade is the next day.
    """)


if __name__ == "__main__":
    app.run()

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
    # Does scaling into and out of positions help the 10/50 SMA crossover?

    The entry/exit signal is unchanged from `backtest.py`: an ETF is "on" while its 10-day SMA is
    above its 50-day SMA. Only the **size** changes. Each variant below is applied to each of the
    11 sector ETFs, then averaged with equal weight. Cash earns 0%.

    | Variant | Size rule |
    |---|---|
    | Baseline | 100% on the day after a cross up, 0% after a cross down |
    | Thirds in | 1/3 per day for 3 days after a cross up, all out on cross down |
    | Fibonacci in | tranches 1,1,2,3,5 (cumulative 1/12, 2/12, 4/12, 7/12, 12/12), one per day, all out on cross down |
    | Fibonacci in and out | same build-up, but exit in reverse tranches 5,3,2,1,1 |
    | Fibonacci progression | each new trade's size steps up the sequence 1,1,2,3,5,8 (as a fraction of 8) after a winning trade and back two places after a losing one |
    | Trend strength | size = SMA10/SMA50 - 1, divided by 3% and capped at 100% |
    | Inverse volatility | 100% size scaled by 10% / 20-day realized annual vol, capped at 100% |

    The 3% cap and 10% vol target are arbitrary round numbers, not tuned.
    Every position is decided at the close and earns the *next* day's return.
    """)


@app.cell
def _(Path, os, pd, yf):
    end = pd.Timestamp(os.environ.get("BACKTEST_END", "2026-11-19"))
    etfs = [
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
    ]
    raw = yf.download(
        etfs,
        start=end - pd.DateOffset(years=5, months=6),
        end=end + pd.Timedelta(days=1),
        auto_adjust=True,
        progress=False,
    )
    prices = raw["Close"].dropna()
    assert set(etfs) <= set(prices.columns), "missing tickers"
    assert prices.index[-1] >= end - pd.Timedelta(days=4), "data is stale"
    out_dir = Path(os.environ.get("OUT_DIR", "outputs"))
    out_dir.mkdir(exist_ok=True)
    print(
        f"{len(prices)} trading days, {prices.index[0].date()} to {prices.index[-1].date()}"
    )
    return end, etfs, out_dir, prices


@app.cell
def _(etfs, prices):
    fast = prices[etfs].rolling(10).mean()
    slow = prices[etfs].rolling(50).mean()
    signal = (fast > slow).fillna(False)
    daily = prices[etfs].pct_change()
    vol20 = daily.rolling(20).std() * (252**0.5)
    return daily, fast, signal, slow, vol20


@app.cell
def _(mo):
    mo.md("""
    ## Position paths

    `ladder` walks a level up one rung per day while the signal is on, and either drops to zero or
    one rung per day when it turns off. `fib_progression` needs trade results, so it loops over days.
    Both return the target position held *during the next day*.
    """)


@app.cell
def _(daily, etfs, np, pd, signal):
    def ladder(cum_weights: list[float], gradual_exit: bool) -> pd.DataFrame:
        top = len(cum_weights) - 1
        out = pd.DataFrame(0.0, index=signal.index, columns=etfs)
        for t in etfs:
            level = 0
            for i, on in enumerate(signal[t].to_numpy()):
                if on:
                    level = min(level + 1, top)
                else:
                    level = max(level - 1, 0) if gradual_exit else 0
                out.iloc[i, out.columns.get_loc(t)] = cum_weights[level]
        return out.shift(1).fillna(0.0)

    fib = [1, 1, 2, 3, 5, 8]

    def fib_progression() -> pd.DataFrame:
        out = pd.DataFrame(0.0, index=signal.index, columns=etfs)
        nxt = daily.shift(-1).fillna(0.0)
        for t in etfs:
            on_arr, r_arr = signal[t].to_numpy(), nxt[t].to_numpy()
            level, size, growth = 0, 0.0, 1.0
            col = out.columns.get_loc(t)
            for i, on in enumerate(on_arr):
                if on:
                    if size == 0.0:
                        size, growth = fib[level] / fib[-1], 1.0
                    growth *= 1 + size * r_arr[i]
                    out.iloc[i, col] = size
                elif size > 0.0:
                    level = (
                        min(level + 1, len(fib) - 1)
                        if growth > 1
                        else max(level - 2, 0)
                    )
                    size = 0.0
        return out.shift(1).fillna(0.0)

    thirds = [0, 1 / 3, 2 / 3, 1]
    fib_cum = [0, 1 / 12, 2 / 12, 4 / 12, 7 / 12, 1]
    return fib_cum, fib_progression, ladder, thirds


@app.cell
def _(fast, fib_cum, fib_progression, ladder, np, signal, slow, thirds, vol20):
    base = signal.astype(float).shift(1).fillna(0.0)
    positions = {
        "Baseline": base,
        "Thirds in": ladder(thirds, gradual_exit=False),
        "Fibonacci in": ladder(fib_cum, gradual_exit=False),
        "Fibonacci in and out": ladder(fib_cum, gradual_exit=True),
        "Fibonacci progression": fib_progression(),
        "Trend strength": (((fast / slow - 1) / 0.03).clip(0, 1)).shift(1).fillna(0.0),
        "Inverse volatility": (signal * (0.10 / vol20).clip(upper=1.0))
        .shift(1)
        .fillna(0.0),
    }
    assert all(p.shape == base.shape for p in positions.values())
    assert all(np.isfinite(p.to_numpy()).all() for p in positions.values())
    return (positions,)


@app.cell
def _(mo):
    mo.md("""
    ## Results

    Two windows ending on the same date: the last year and the last five years. "Net 5 bps" charges
    5 basis points on every unit of position change, which matters more for ladders that trade on
    several days. Exposure is the average share of capital invested.
    """)


@app.cell
def _(daily, end, etfs, np, out_dir, pd, positions):
    def metrics(pos: pd.DataFrame, ret: pd.DataFrame) -> dict[str, float]:
        gross = (pos * ret).mean(axis=1)
        turnover = pos.diff().abs().fillna(pos.abs()).mean(axis=1)
        net = gross - turnover * 5 / 10_000
        equity = (1 + gross).cumprod()
        return {
            "return_%": 100 * (equity.iloc[-1] - 1),
            "net_5bps_return_%": 100 * ((1 + net).cumprod().iloc[-1] - 1),
            "ann_vol_%": 100 * gross.std() * np.sqrt(252),
            "sharpe": gross.mean() / gross.std() * np.sqrt(252),
            "max_drawdown_%": 100 * (equity / equity.cummax() - 1).min(),
            "exposure_%": 100 * pos.mean().mean(),
            "turnover_per_year": turnover.sum() * len(etfs) / (len(pos) / 252),
        }

    tables = {}
    for label, years in (("1 year", 1), ("5 years", 5)):
        window = daily.index >= end - pd.DateOffset(years=years)
        ret = daily[window]
        table = pd.DataFrame(
            {n: metrics(p[window], ret) for n, p in positions.items()}
        ).T
        buy_hold = metrics(pd.DataFrame(1.0, index=ret.index, columns=etfs), ret)
        table.loc["Buy & hold basket"] = buy_hold
        tables[label] = table.round(2)
        tables[label].to_csv(out_dir / f"sizing_{label.replace(' ', '_')}.csv")
        print(
            f"\n=== Last {label}: {ret.index[0].date()} to {ret.index[-1].date()} ==="
        )
        print(tables[label].to_string())


@app.cell
def _(mo):
    mo.md("""
    ## What this does not show

    - All variants share one signal. Differences come from sizing only, and they are small
      compared with the gap to buy-and-hold in `backtest.py`.
    - The 5-year window includes 2022, which is one bear market; it is not a full cycle.
    - Fibonacci progression depends on a handful of closed trades per ETF, so it is noisy.
    - Sizes (3% cap, 10% vol target, rung order) were picked once and not tuned.
    - No taxes or spreads beyond the 5 bps case.
    """)


if __name__ == "__main__":
    app.run()

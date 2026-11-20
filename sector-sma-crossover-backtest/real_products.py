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

    from strategies import build_weights

    return Path, build_weights, mo, np, os, pd, yf


@app.cell
def _(mo):
    mo.md("""
    # How do our rules compare with funds that already exist?

    Real funds, total return after their own fees (Yahoo adjusted closes):

    | Ticker | Fund | Idea |
    |---|---|---|
    | XLSR | SPDR SSGA US Sector Rotation | model-driven rotation among the sector ETFs |
    | PTLC | Pacer Trendpilot US Large Cap | S&P 500 with a 200-day average rule that moves to T-bills |
    | TRND | Pacer Trendpilot Fund of Funds | other Trendpilot funds combined |
    | MTUM | iShares MSCI USA Momentum Factor | momentum-ranked US stocks, for reference |
    | SPY | SPDR S&P 500 | the index |

    Our rules run on the 11 sector ETFs from `backtest.py` through `strategies.py`. Differences from
    the funds: our results are **before** any management fee, and uninvested cash earns the return
    of BIL (a 1-3 month T-bill ETF) here, because the Pacer funds hold T-bills. "After fee" charges
    0.60% a year, about what the Pacer funds list. Trading cost is 5 bps per unit of position change.
    """)


@app.cell
def _(Path, os, pd, yf):
    end = pd.Timestamp(os.environ.get("BACKTEST_END", "2026-11-19"))
    sectors = [
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
    funds = ["XLSR", "PTLC", "TRND", "MTUM", "SPY"]
    raw = yf.download(
        [*sectors, *funds, "BIL"],
        start="2017-01-03",
        end=end + pd.Timedelta(days=1),
        auto_adjust=True,
        progress=False,
    )
    prices = raw["Close"]
    assert prices.index[-1] >= end - pd.Timedelta(days=4), "data is stale"
    study_start = pd.Timestamp("2019-07-04")
    assert prices.loc[study_start:].notna().all().all(), "missing data in study window"
    out_dir = Path(os.environ.get("OUT_DIR", "outputs"))
    out_dir.mkdir(exist_ok=True)
    first = {f: prices[f].first_valid_index().date() for f in funds}
    print(f"fund data starts: {first}")
    return end, funds, out_dir, prices, sectors, study_start


@app.cell
def _(mo):
    mo.md("""
    ## Daily returns for each line in the comparison

    Our strategies: position weights from `build_weights`, cash earning BIL, minus trading cost.
    """)


@app.cell
def _(build_weights, funds, prices, sectors):
    daily = prices.pct_change()
    weights = build_weights(prices.drop(columns=["BIL"]), sectors)
    ours = {
        "Ours: SMA 10/50": "SMA 10/50",
        "Ours: Top 3 rotation": "Top 3 rotation",
        "Ours: Momentum-weighted daily": "Momentum-weighted daily",
        "Ours: SPY 200-day filter": "SPY filter, 200-day",
        "Ours: Equal-weight buy & hold": "Buy & hold",
    }
    series = {}
    for _label, _key in ours.items():
        _w = weights[_key]
        _invested = _w.sum(axis=1)
        _cost = _w.diff().abs().fillna(_w.abs()).sum(axis=1) * 5 / 10_000
        series[_label] = (
            (_w * daily[sectors]).sum(axis=1) + (1 - _invested) * daily["BIL"] - _cost
        )
    fee = 0.006 / 252
    _fee_labels = {
        f"{_k} (after 0.6% fee)": _v - fee
        for _k, _v in series.items()
        if "Top 3" in _k or "SMA" in _k or "200-day" in _k
    }
    for _label in funds:
        series[_label] = daily[_label]
    series.update(_fee_labels)
    print(f"{len(series)} lines compared")
    return daily, series


@app.cell
def _(mo):
    mo.md("""
    ## Results

    Windows end on the same date. Max drawdown is peak to trough on daily closes. Sharpe uses a 0%
    risk-free rate. The Covid crash and 2022 bear market are measured on their own.
    """)


@app.cell
def _(end, np, out_dir, pd, series, study_start):
    def metrics(r: pd.Series) -> dict[str, float]:
        equity = (1 + r).cumprod()
        return {
            "return_%": 100 * (equity.iloc[-1] - 1),
            "ann_vol_%": 100 * r.std() * np.sqrt(252),
            "sharpe": r.mean() / r.std() * np.sqrt(252),
            "max_drawdown_%": 100 * (equity / equity.cummax() - 1).min(),
        }

    windows = {
        "1 year": (end - pd.DateOffset(years=1), end),
        "5 years": (end - pd.DateOffset(years=5), end),
        f"since {study_start.date()}": (study_start, end),
        "Covid crash": (pd.Timestamp("2020-02-19"), pd.Timestamp("2020-03-23")),
        "2022 bear": (pd.Timestamp("2022-01-03"), pd.Timestamp("2022-10-14")),
    }
    frame = pd.DataFrame(series)
    for _label, (_lo, _hi) in windows.items():
        _part = frame[(frame.index >= _lo) & (frame.index <= _hi)]
        _table = pd.DataFrame({_k: metrics(_part[_k]) for _k in frame.columns}).T.round(
            2
        )
        _table.to_csv(out_dir / f"products_{_label.replace(' ', '_')}.csv")
        print(
            f"\n=== {_label}: {_part.index[0].date()} to {_part.index[-1].date()} ==="
        )
        print(_table.to_string())
    return (frame,)


@app.cell
def _(mo):
    mo.md("""
    ## By calendar year

    Return % / max drawdown % inside each year. `*` marks a partial year.
    """)


@app.cell
def _(end, frame, out_dir, pd, study_start):
    years = {}
    for _year in range(study_start.year, end.year + 1):
        _lo = max(study_start, pd.Timestamp(year=_year, month=1, day=1))
        _hi = min(end, pd.Timestamp(year=_year, month=12, day=31))
        _part = frame[(frame.index >= _lo) & (frame.index <= _hi)]
        _equity = (1 + _part).cumprod()
        _partial = _lo > pd.Timestamp(year=_year, month=1, day=7) or _hi < pd.Timestamp(
            year=_year, month=12, day=24
        )
        _label = f"{_year}*" if _partial else str(_year)
        _ret = 100 * (_equity.iloc[-1] - 1)
        _dd = 100 * (_equity / _equity.cummax() - 1).min()
        years[_label] = {k: f"{_ret[k]:.1f} / {_dd[k]:.1f}" for k in frame.columns}
    yearly = pd.DataFrame(years)
    yearly.to_csv(out_dir / "products_yearly.csv")
    print(yearly.to_string())


@app.cell
def _(mo):
    mo.md("""
    ## What this does not show

    - The funds' own models and holdings are not reproduced. This compares results only.
    - Fund fees are inside their returns. Ours are before fees, with one 0.6% adjustment shown.
    - XLSR and the Pacer funds hold their own trading costs and taxes in their returns; we only
      charge 5 bps per unit of position change.
    - Seven years includes one bear market and one crash. It is a small sample.
    - Yahoo's adjusted closes can be restated, so numbers can shift slightly between runs.
    """)


if __name__ == "__main__":
    app.run()

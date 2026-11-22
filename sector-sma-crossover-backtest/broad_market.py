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
    # Simple broad-market strategies, compared on Sharpe ratio

    Each rule is a few lines and uses liquid ETFs: SPY (US stocks), EFA (developed ex-US), AGG
    (US bonds), TLT (long Treasuries), GLD (gold), VNQ (real estate), DBC (commodities), with BIL
    (T-bills) as cash. Rules were fixed in advance, set once and not tuned. Signals are read at the
    close and applied the next day; 5 bps cost per unit of position change.

    | Strategy | Rule |
    |---|---|
    | SPY buy & hold | the benchmark |
    | 60/40 | 60% SPY, 40% AGG, held at those weights |
    | SPY/TLT/GLD | one third each, held at those weights |
    | SPY 200-day | SPY while above its 200-day average, otherwise T-bills (daily signal) |
    | Faber 5-asset | SPY, EFA, AGG, VNQ, DBC at 20% each; each held while above its 10-month (210-day) average at month-end, else T-bills |
    | Dual momentum | month-end: if SPY's 12-month return beats T-bills, hold the better of SPY and EFA by 12-month return, else AGG |
    | Vol-targeted SPY | SPY scaled to 10% annual volatility from its 20-day volatility (never above 100%), rest in T-bills |

    "Held at those weights" means rebalanced daily, a simplification that makes drift costless.
    """)


@app.cell
def _(Path, os, pd, yf):
    end = pd.Timestamp(os.environ.get("BACKTEST_END", "2026-11-19"))
    tickers = ["SPY", "EFA", "AGG", "TLT", "GLD", "VNQ", "DBC", "BIL"]
    raw = yf.download(
        tickers,
        start="2006-03-01",
        end=end + pd.Timedelta(days=1),
        auto_adjust=True,
        progress=False,
    )
    prices = raw["Close"].dropna(subset=[t for t in tickers if t != "BIL"])
    assert prices.index[-1] >= end - pd.Timedelta(days=4), "data is stale"
    study_start = pd.Timestamp("2007-10-09")
    assert prices.loc[study_start:].notna().all().all(), "missing data in study window"
    out_dir = Path(os.environ.get("OUT_DIR", "outputs"))
    out_dir.mkdir(exist_ok=True)
    print(f"{len(prices)} days, {prices.index[0].date()} to {prices.index[-1].date()}")
    return end, out_dir, prices, study_start, tickers


@app.cell
def _(mo):
    mo.md("""
    ## Positions

    Weights are decided at each close and shifted one day. The remaining weight is in BIL.
    """)


@app.cell
def _(pd, prices, tickers):
    px = prices[tickers]
    returns = px.pct_change()
    dates = pd.DatetimeIndex(px.index)
    month_ends = px.index.to_series().groupby(dates.to_period("M")).last().to_numpy()
    zeros = pd.DataFrame(0.0, index=px.index, columns=tickers)

    def monthly(frame: pd.DataFrame) -> pd.DataFrame:
        return frame.loc[month_ends].reindex(px.index).ffill()

    def with_cash(frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.copy()
        out["BIL"] = 1.0 - frame.drop(columns=["BIL"]).sum(axis=1)
        return out

    def fixed(mix: dict[str, float]) -> pd.DataFrame:
        frame = zeros.copy()
        for name, weight in mix.items():
            frame[name] = weight
        return with_cash(frame)

    spy_sma200 = px["SPY"] > px["SPY"].rolling(200).mean()
    trend = zeros.copy()
    trend["SPY"] = spy_sma200.astype(float)

    faber_assets = ["SPY", "EFA", "AGG", "VNQ", "DBC"]
    above_10m = px[faber_assets] > px[faber_assets].rolling(210).mean()
    faber = zeros.copy()
    faber[faber_assets] = monthly(above_10m.astype(float)) * 0.2

    ret12 = px.pct_change(252)
    risk_on = ret12["SPY"] > ret12["BIL"]
    pick_spy = ret12["SPY"] >= ret12["EFA"]
    dual = zeros.copy()
    dual["SPY"] = monthly((risk_on & pick_spy).astype(float).to_frame("SPY"))["SPY"]
    dual["EFA"] = monthly((risk_on & ~pick_spy).astype(float).to_frame("EFA"))["EFA"]
    dual["AGG"] = monthly((~risk_on).astype(float).to_frame("AGG"))["AGG"]

    vol20 = returns["SPY"].rolling(20).std() * (252**0.5)
    target = zeros.copy()
    target["SPY"] = (0.10 / vol20).clip(upper=1.0)

    raw_weights = {
        "SPY buy & hold": fixed({"SPY": 1.0}),
        "60/40 SPY/AGG": fixed({"SPY": 0.6, "AGG": 0.4}),
        "SPY/TLT/GLD thirds": fixed({"SPY": 1 / 3, "TLT": 1 / 3, "GLD": 1 / 3}),
        "SPY 200-day": with_cash(trend),
        "Faber 5-asset": with_cash(faber),
        "Dual momentum": with_cash(dual),
        "Vol-targeted SPY": with_cash(target),
    }
    weights = {k: v.shift(1).fillna(0.0) for k, v in raw_weights.items()}
    for _name, _w in weights.items():
        assert (_w.sum(axis=1).loc["2007-10-09":] - 1.0).abs().max() < 1e-9, (
            f"{_name} not fully allocated"
        )
    return returns, weights


@app.cell
def _(mo):
    mo.md("""
    ## Results

    Sharpe is shown two ways: against a 0% risk-free rate (as in the other notebooks) and against
    BIL, which is fairer for strategies that sit in T-bills. Windows end on the same date.
    """)


@app.cell
def _(end, np, out_dir, pd, returns, study_start, weights):
    lines = {}
    for _name, _w in weights.items():
        _risky = _w.drop(columns=["BIL"])
        _cost = _risky.diff().abs().fillna(_risky.abs()).sum(axis=1) * 5 / 10_000
        lines[_name] = (_w * returns).sum(axis=1) - _cost
    frame = pd.DataFrame(lines)
    cash = returns["BIL"].fillna(0.0)

    def stats(r: pd.Series, rf: pd.Series) -> dict[str, float]:
        equity = (1 + r).cumprod()
        years = len(r) / 252
        excess = r - rf.loc[r.index]
        return {
            "return_%": 100 * (equity.iloc[-1] - 1),
            "cagr_%": 100 * (equity.iloc[-1] ** (1 / years) - 1)
            if years >= 1
            else float("nan"),
            "ann_vol_%": 100 * r.std() * np.sqrt(252),
            "sharpe_0rf": r.mean() / r.std() * np.sqrt(252),
            "sharpe_vs_bil": excess.mean() / excess.std() * np.sqrt(252),
            "max_drawdown_%": 100 * (equity / equity.cummax() - 1).min(),
        }

    windows = {
        "since 2007-10": (study_start, end),
        "since 2019-07": (pd.Timestamp("2019-07-04"), end),
        "5 years": (end - pd.DateOffset(years=5), end),
        "1 year": (end - pd.DateOffset(years=1), end),
        "financial crisis 2007-2009": (study_start, pd.Timestamp("2009-03-09")),
        "Covid crash": (pd.Timestamp("2020-02-19"), pd.Timestamp("2020-03-23")),
        "2022 bear": (pd.Timestamp("2022-01-03"), pd.Timestamp("2022-10-14")),
    }
    for _wname, (_lo, _hi) in windows.items():
        _part = frame[(frame.index >= _lo) & (frame.index <= _hi)]
        _table = pd.DataFrame(
            {c: stats(_part[c], cash) for c in frame.columns}
        ).T.round(2)
        _table.to_csv(out_dir / f"broad_{_wname.replace(' ', '_')}.csv")
        print(
            f"\n=== {_wname}: {_part.index[0].date()} to {_part.index[-1].date()} ==="
        )
        print(_table.to_string())
    return cash, frame, stats


@app.cell
def _(frame, out_dir, pd, study_start):
    _data = frame[frame.index >= study_start]
    _years = {}
    for _year, _part in _data.groupby(_data.index.year):
        _equity = (1 + _part).cumprod()
        _ret = 100 * (_equity.iloc[-1] - 1)
        _dd = 100 * (_equity / _equity.cummax() - 1).min()
        _years[str(_year)] = {c: f"{_ret[c]:.1f} / {_dd[c]:.1f}" for c in _data.columns}
    _yearly = pd.DataFrame(_years).T
    _yearly.to_csv(out_dir / "broad_yearly.csv")
    print("\nReturn % / max drawdown % by calendar year")
    print(_yearly.to_string())


@app.cell
def _(mo):
    mo.md("""
    ## What this does not show

    - Eighteen years and a handful of market episodes. Several rules were tried, so a higher Sharpe
      here can be luck, and rules like these have shown weaker out-of-sample results in published tests.
    - Much of the edge in the diversified rules comes from bonds, which did well through 2020 and
      badly in 2022; a different rate environment would change the ranking.
    - Rules are fixed and untuned, but the choices (200 days, 10 months, 12 months, 10% target) are
      common conventions, not proven optimal.
    - Fixed-weight mixes are rebalanced daily and ETF expense ratios are inside the returns, not
      added separately. Taxes are ignored.
    """)


if __name__ == "__main__":
    app.run()

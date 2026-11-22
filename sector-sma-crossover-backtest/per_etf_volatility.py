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

    from strategies import build_weights, ranked_weights

    return Path, build_weights, mo, np, os, pd, ranked_weights, yf


@app.cell
def _(mo):
    mo.md("""
    # Top 3 sector daily with volatility tracked per ETF

    Base: each day, hold the 3 sector ETFs with the best 12-1 month momentum, 1/3 each. Variants
    (fixed in advance; 5 bps costs, BIL cash, positions decided at the close and applied the next day):

    | Variant | Rule |
    |---|---|
    | Base | no volatility rule |
    | Own spike, to cash | an ETF whose 20-day volatility is above 1.5 times its own 120-day average is dropped and its slot goes to cash |
    | Own spike, reallocate | the same ETFs are skipped when ranking, so the next-best stable ETF fills the slot |
    | Own spike + own trend, reallocate | skip an ETF only if it has the volatility spike **and** is below its own 200-day average |
    | Volatility-adjusted ranking | rank by 12-1 momentum divided by 1-year volatility instead of raw momentum |
    | Inverse-volatility weights | same top 3, weighted by 1 / 20-day volatility instead of equally |
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
    raw = yf.download(
        [*sectors, "SPY", "BIL"],
        start="2017-01-03",
        end=end + pd.Timedelta(days=1),
        auto_adjust=True,
        progress=False,
    )
    prices = raw["Close"].dropna()
    assert prices.index[-1] >= end - pd.Timedelta(days=4), "data is stale"
    study_start = pd.Timestamp("2019-07-04")
    out_dir = Path(os.environ.get("OUT_DIR", "outputs"))
    out_dir.mkdir(exist_ok=True)
    print(
        f"{len(prices)} trading days, {prices.index[0].date()} to {prices.index[-1].date()}"
    )
    return end, out_dir, prices, sectors, study_start


@app.cell
def _(mo):
    mo.md("""
    ## Positions

    Everything is built from the sector prices. `eligible` marks ETFs not flagged by the volatility
    rule that day. Weights are decided at each close and shifted one day.
    """)


@app.cell
def _(build_weights, np, pd, prices, ranked_weights, sectors):
    px = prices[sectors]
    daily_ret = prices.pct_change()
    returns = daily_ret[sectors]
    vol20 = returns.rolling(20).std() * np.sqrt(252)
    vol252 = returns.rolling(252).std() * np.sqrt(252)
    mom12 = px.shift(21) / px.shift(252) - 1
    spike = vol20 > 1.5 * vol20.rolling(120).mean()
    below_200 = px < px.rolling(200).mean()
    all_eligible = pd.DataFrame(True, index=px.index, columns=sectors)
    calm = ~spike | spike.isna()
    calm_or_uptrend = ~(spike & below_200)
    inverse_vol = 1.0 / vol20

    raw_weights = {
        "Base": ranked_weights(mom12, all_eligible),
        "Own spike, to cash": ranked_weights(mom12, all_eligible) * calm,
        "Own spike, reallocate": ranked_weights(mom12, calm),
        "Own spike + own trend, reallocate": ranked_weights(mom12, calm_or_uptrend),
        "Volatility-adjusted ranking": ranked_weights(mom12 / vol252, all_eligible),
        "Inverse-volatility weights": ranked_weights(
            mom12, all_eligible, weight_by=inverse_vol
        ),
    }
    weights = {k: v.shift(1).fillna(0.0) for k, v in raw_weights.items()}
    reference = build_weights(prices.drop(columns=["BIL"]), sectors)["Top 3 daily"]
    gap = (weights["Base"] - reference).abs().to_numpy().max()
    print(
        f"largest difference between Base and the shared Top 3 daily weights: {gap:.2e}"
    )
    assert gap < 1e-9, "Base should reproduce the shared Top 3 daily strategy"
    return daily_ret, weights


@app.cell
def _(mo):
    mo.md("""
    ## Results

    Same windows as the other notebooks. "Exposure" is the average share of capital invested,
    "positions" the average number of ETFs held, and "turnover" the sum of daily position changes
    per year (1.0 = replacing the whole portfolio once).
    """)


@app.cell
def _(daily_ret, end, np, out_dir, pd, sectors, study_start, weights):
    def run(w: pd.DataFrame) -> pd.Series:
        cost = w.diff().abs().fillna(w.abs()).sum(axis=1) * 5 / 10_000
        return (
            (w * daily_ret[sectors]).sum(axis=1)
            + (1 - w.sum(axis=1)) * daily_ret["BIL"]
            - cost
        )

    lines = pd.DataFrame({k: run(w) for k, w in weights.items()})
    windows = {
        "since 2019-07": (study_start, end),
        "5 years": (end - pd.DateOffset(years=5), end),
        "1 year": (end - pd.DateOffset(years=1), end),
        "Covid crash": (pd.Timestamp("2020-02-19"), pd.Timestamp("2020-03-23")),
        "2022 bear": (pd.Timestamp("2022-01-03"), pd.Timestamp("2022-10-14")),
    }
    table = {}
    for _wname, (_lo, _hi) in windows.items():
        _part = lines[(lines.index >= _lo) & (lines.index <= _hi)]
        _equity = (1 + _part).cumprod()
        for _col in lines.columns:
            table.setdefault(_col, {})[f"{_wname} return_%"] = 100 * (
                _equity[_col].iloc[-1] - 1
            )
            table[_col][f"{_wname} max_dd_%"] = (
                100 * (_equity[_col] / _equity[_col].cummax() - 1).min()
            )
    since = lines.index >= study_start
    for _col, _w in weights.items():
        _ws = _w[since]
        table[_col]["sharpe"] = (
            lines.loc[since, _col].mean() / lines.loc[since, _col].std() * np.sqrt(252)
        )
        table[_col]["exposure_%"] = 100 * _ws.sum(axis=1).mean()
        table[_col]["positions"] = (_ws > 0).sum(axis=1).mean()
        table[_col]["turnover_per_year"] = _ws.diff().abs().sum(axis=1).sum() / (
            len(_ws) / 252
        )
    results = pd.DataFrame(table).T.round(1)
    results.to_csv(out_dir / "per_etf_volatility.csv")
    print(results.to_string())
    return (lines,)


@app.cell
def _(lines, out_dir, pd, study_start):
    _frame = lines[lines.index >= study_start]
    _years = {}
    for _year, _part in _frame.groupby(_frame.index.year):
        _equity = (1 + _part).cumprod()
        _ret = 100 * (_equity.iloc[-1] - 1)
        _dd = 100 * (_equity / _equity.cummax() - 1).min()
        _years[str(_year)] = {
            c: f"{_ret[c]:.1f} / {_dd[c]:.1f}" for c in _frame.columns
        }
    _yearly = pd.DataFrame(_years)
    _yearly.to_csv(out_dir / "per_etf_volatility_yearly.csv")
    print("\nReturn % / max drawdown % by calendar year")
    print(_yearly.to_string())


@app.cell
def _(mo):
    mo.md("""
    ## What this does not show

    - One seven-year path with one crash and one bear market. Variants were fixed in advance but
      several were tried, so the best looking one is the most likely to be luck.
    - The 1.5 times and 120-day settings were not tuned, and neither were the 200-day and 252-day
      windows. Other values would give different results.
    - Daily re-ranking trades often. Costs are 5 bps per unit of position change; higher costs
      would hurt the high-turnover variants most.
    - Weights go to cash when an ETF is skipped without a replacement; BIL earns the T-bill rate.
    """)


if __name__ == "__main__":
    app.run()

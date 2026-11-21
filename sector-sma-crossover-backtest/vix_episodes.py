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

    from gates import hysteresis_gate

    return Path, hysteresis_gate, mo, np, os, pd, yf


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
    ## Rule: exit when the 5-day average VIX close is above 25

    SPY is held while the 5-day average of the VIX close is at or below 25, otherwise cash (0%
    return; no T-bill history is used so the test can go back to 1993). The reading at the close
    applies from the next day. "1-day" is the same rule on the single-day close, for comparison.
    Each switch costs 5 bps. Episodes below use the 5-day average crossing above 25 after 20 days
    at or below it, with the same measures as above.
    """)


@app.cell
def _(hysteresis_gate, pd, prices):
    vix5 = prices["^VIX"].rolling(5).mean()
    vix10 = prices["^VIX"].rolling(10).mean()
    gate5 = hysteresis_gate(vix5, 25, 25)
    gate10 = hysteresis_gate(vix10, 25, 25)
    gate1 = hysteresis_gate(prices["^VIX"], 25, 25)
    first_valid = vix5.first_valid_index()
    assert first_valid is not None
    start_day = pd.Timestamp(first_valid)
    spy_ret = prices["SPY"].pct_change()
    return gate1, gate10, gate5, spy_ret, start_day, vix10, vix5


@app.cell
def _(gate1, gate10, gate5, np, out_dir, pd, spy_ret, start_day):
    def run_rule(gate: pd.Series) -> pd.Series:
        pos = gate.fillna(1.0)
        cost = pos.diff().abs().fillna(0.0) * 5 / 10_000
        return spy_ret * pos - cost

    lines = pd.DataFrame(
        {
            "SPY buy & hold": spy_ret,
            "Exit on 5-day avg VIX > 25": run_rule(gate5),
            "Exit on 10-day avg VIX > 25": run_rule(gate10),
            "Exit on 1-day VIX > 25": run_rule(gate1),
        }
    ).loc[start_day:]
    lines = lines.iloc[1:]

    def stats(r: pd.Series) -> dict[str, float]:
        equity = (1 + r).cumprod()
        return {
            "return_%": 100 * (equity.iloc[-1] - 1),
            "ann_vol_%": 100 * r.std() * np.sqrt(252),
            "sharpe": r.mean() / r.std() * np.sqrt(252),
            "max_drawdown_%": 100 * (equity / equity.cummax() - 1).min(),
        }

    windows = {
        "all years": (lines.index[0], lines.index[-1]),
        "dot-com 2000-2002": (pd.Timestamp("2000-03-24"), pd.Timestamp("2002-10-09")),
        "financial crisis 2007-2009": (
            pd.Timestamp("2007-10-09"),
            pd.Timestamp("2009-03-09"),
        ),
        "Covid crash": (pd.Timestamp("2020-02-19"), pd.Timestamp("2020-03-23")),
        "2022 bear": (pd.Timestamp("2022-01-03"), pd.Timestamp("2022-10-14")),
        "since 2019-07": (pd.Timestamp("2019-07-04"), lines.index[-1]),
    }
    for _label, (_lo, _hi) in windows.items():
        _part = lines[(lines.index >= _lo) & (lines.index <= _hi)]
        _table = pd.DataFrame({c: stats(_part[c]) for c in lines.columns}).T.round(2)
        _table.to_csv(out_dir / f"vix_rule_{_label.replace(' ', '_')}.csv")
        print(
            f"\n=== {_label}: {_part.index[0].date()} to {_part.index[-1].date()} ==="
        )
        print(_table.to_string())
    invested = pd.DataFrame({"10-day": gate10, "5-day": gate5, "1-day": gate1}).loc[
        lines.index
    ]
    switches = {
        k: int(((invested[k].shift(1) == 1) & (invested[k] == 0)).sum())
        for k in invested.columns
    }
    print(
        f"\nDays in cash: 10-day {100 * (1 - invested['10-day'].mean()):.1f}%, "
        f"5-day {100 * (1 - invested['5-day'].mean()):.1f}%, "
        f"1-day {100 * (1 - invested['1-day'].mean()):.1f}%; exits: {switches}"
    )
    return (lines,)


@app.cell
def _(lines, out_dir, pd):
    years = {}
    for _year, _part in lines.groupby(lines.index.year):
        _equity = (1 + _part).cumprod()
        _ret = 100 * (_equity.iloc[-1] - 1)
        _dd = 100 * (_equity / _equity.cummax() - 1).min()
        years[str(_year)] = {c: f"{_ret[c]:.1f} / {_dd[c]:.1f}" for c in lines.columns}
    yearly_table = pd.DataFrame(years).T
    yearly_table.to_csv(out_dir / "vix_rule_yearly.csv")
    print("\nReturn % / max drawdown % by calendar year")
    print(yearly_table.to_string())


@app.cell
def _(out_dir, pd, prices, vix10, vix5):
    spy_px = prices["SPY"]
    for _window, _avg in ((5, vix5), (10, vix10)):
        _above = _avg > 25
        _quiet = ~_above.shift(1, fill_value=False).rolling(20).max().fillna(1).astype(
            bool
        )
        _rows = {}
        for _day in prices.index[_above & _quiet]:
            _i = prices.index.get_loc(_day)
            _close = spy_px.iloc[_i]
            _next60 = spy_px.iloc[_i + 1 : _i + 61]
            if len(_next60) < 60:
                continue
            _rows[str(_day.date())] = {
                f"avg{_window}_vix": round(float(_avg.iloc[_i]), 1),
                "already_down_%": round(
                    100 * (_close / spy_px.iloc[max(0, _i - 252) : _i + 1].max() - 1), 1
                ),
                "further_drop_%": round(100 * (_next60.min() / _close - 1), 1),
                "return_60d_%": round(100 * (spy_px.iloc[_i + 60] / _close - 1), 1),
            }
        _episodes = pd.DataFrame(_rows).T
        _episodes.to_csv(out_dir / f"vix_episodes_{_window}day.csv")
        print(
            f"\n{len(_episodes)} episodes with the {_window}-day average crossing above 25"
        )
        print(_episodes.describe().loc[["50%", "min", "max"]].round(1).to_string())
        for _limit in (5, 10, 20):
            _share = 100 * (_episodes["further_drop_%"] <= -_limit).mean()
            print(f"further drop of {_limit}% or more: {_share:.0f}%")


@app.cell
def _(mo):
    mo.md("""
    ## Separate re-entry level

    Same exit (5-day average VIX above 25), but the gate returns to SPY only when the 5-day average
    is at or below a lower level. The grid (25, 22, 20, 18, 15) was fixed before running. A lower
    level keeps the portfolio in cash longer, which avoids buying back into rebounds that fail but
    also misses fast recoveries. Cash earns 0%, 5 bps per switch.
    """)


@app.cell
def _(hysteresis_gate, np, out_dir, pd, spy_ret, start_day, vix5):
    reentry_levels = [25, 22, 20, 18, 15]
    reentry_lines = {"SPY buy & hold": spy_ret}
    reentry_gates = {}
    for _level in reentry_levels:
        _gate = hysteresis_gate(vix5, 25, _level)
        reentry_gates[_level] = _gate
        _cost = _gate.diff().abs().fillna(0.0) * 5 / 10_000
        reentry_lines[f"exit 25, re-enter {_level}"] = spy_ret * _gate - _cost
    reentry_frame = pd.DataFrame(reentry_lines).loc[start_day:].iloc[1:]

    def reentry_stats(r: pd.Series) -> dict[str, float]:
        equity = (1 + r).cumprod()
        return {
            "return_%": 100 * (equity.iloc[-1] - 1),
            "sharpe": r.mean() / r.std() * np.sqrt(252),
            "max_drawdown_%": 100 * (equity / equity.cummax() - 1).min(),
        }

    reentry_windows = {
        "all years": (reentry_frame.index[0], reentry_frame.index[-1]),
        "dot-com 2000-2002": (pd.Timestamp("2000-03-24"), pd.Timestamp("2002-10-09")),
        "financial crisis 2007-2009": (
            pd.Timestamp("2007-10-09"),
            pd.Timestamp("2009-03-09"),
        ),
        "Covid crash": (pd.Timestamp("2020-02-19"), pd.Timestamp("2020-03-23")),
        "2022 bear": (pd.Timestamp("2022-01-03"), pd.Timestamp("2022-10-14")),
        "since 2019-07": (pd.Timestamp("2019-07-04"), reentry_frame.index[-1]),
    }
    for _label, (_lo, _hi) in reentry_windows.items():
        _part = reentry_frame[
            (reentry_frame.index >= _lo) & (reentry_frame.index <= _hi)
        ]
        _table = pd.DataFrame(
            {c: reentry_stats(_part[c]) for c in reentry_frame.columns}
        ).T.round(2)
        _table.to_csv(out_dir / f"vix_reentry_{_label.replace(' ', '_')}.csv")
        print(
            f"\n=== {_label}: {_part.index[0].date()} to {_part.index[-1].date()} ==="
        )
        print(_table.to_string())
    _activity = {}
    for _level, _gate in reentry_gates.items():
        _g = _gate.loc[reentry_frame.index]
        _activity[f"re-enter {_level}"] = {
            "days_in_cash_%": round(100 * (1 - _g.mean()), 1),
            "exits": int(((_g.shift(1) == 1) & (_g == 0)).sum()),
        }
    print("\n=== Activity, all years ===")
    print(pd.DataFrame(_activity).T.to_string())
    return reentry_frame, reentry_gates


@app.cell
def _(out_dir, pd, reentry_frame):
    _years = {}
    for _year, _part in reentry_frame.groupby(reentry_frame.index.year):
        _equity = (1 + _part).cumprod()
        _ret = 100 * (_equity.iloc[-1] - 1)
        _dd = 100 * (_equity / _equity.cummax() - 1).min()
        _years[str(_year)] = {
            c: f"{_ret[c]:.1f} / {_dd[c]:.1f}" for c in reentry_frame.columns
        }
    _table = pd.DataFrame(_years).T
    _table.to_csv(out_dir / "vix_reentry_yearly.csv")
    print("\nReturn % / max drawdown % by calendar year")
    print(_table.to_string())


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

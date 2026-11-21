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
    from strategies import build_weights

    return Path, build_weights, hysteresis_gate, mo, np, os, pd, yf


@app.cell
def _(mo):
    mo.md("""
    # Does exiting when volatility is unstable help?

    Base strategies on the 11 sector ETFs (from `strategies.py`): equal-weight buy and hold, Top 3
    rotation (monthly) and Top 3 daily. Each gets a volatility gate that moves it to cash (BIL, a
    T-bill ETF) when volatility looks unstable. Gates are set once, not tuned:

    | Gate | Exit when | Re-enter when |
    |---|---|---|
    | Level | SPY 20-day realized volatility (annualized) is above 25% | it is at or below 25% |
    | Spike | SPY 20-day volatility is above 1.5 times its own 120-day average | it is at or below that |
    | VIX 5-day | the 5-day average of the VIX close is above 25 | it is at or below 25 |
    | Own spike | an ETF's own 20-day volatility is above 1.5 times its 120-day average (per ETF) | it is at or below that |

    Each gate is read at the close and applied from the next day. Trading cost is 5 bps per unit of
    position change. Results are compared with the same base strategy without the gate.
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
        [*sectors, "SPY", "BIL", "^VIX"],
        start="2017-01-03",
        end=end + pd.Timedelta(days=1),
        auto_adjust=True,
        progress=False,
    )
    prices = raw["Close"].dropna(subset=[*sectors, "SPY", "BIL"])
    assert prices.index[-1] >= end - pd.Timedelta(days=4), "data is stale"
    study_start = pd.Timestamp("2019-07-04")
    assert prices.loc[study_start:].notna().all().all(), "missing data in study window"
    out_dir = Path(os.environ.get("OUT_DIR", "outputs"))
    out_dir.mkdir(exist_ok=True)
    print(
        f"{len(prices)} trading days, {prices.index[0].date()} to {prices.index[-1].date()}"
    )
    return end, out_dir, prices, sectors, study_start


@app.cell
def _(mo):
    mo.md("""
    ## Gates

    A gate is 1 when invested and 0 when in cash. `shift(1)` makes today's volatility reading act
    from tomorrow.
    """)


@app.cell
def _(hysteresis_gate, prices, sectors):
    daily = prices.pct_change()
    ann = 252**0.5
    spy_vol = daily["SPY"].rolling(20).std() * ann
    gate_level = (spy_vol <= 0.25).astype(float).shift(1).fillna(1.0)
    gate_spike = (
        (spy_vol <= 1.5 * spy_vol.rolling(120).mean())
        .astype(float)
        .shift(1)
        .fillna(1.0)
    )
    gate_vix5 = hysteresis_gate(prices["^VIX"].rolling(5).mean(), 25, 25)
    gate_vix10 = hysteresis_gate(prices["^VIX"].rolling(10).mean(), 25, 25)
    own_vol = daily[sectors].rolling(20).std() * ann
    gate_own = (
        (own_vol <= 1.5 * own_vol.rolling(120).mean())
        .astype(float)
        .shift(1)
        .fillna(1.0)
    )
    return daily, gate_level, gate_own, gate_spike, gate_vix10, gate_vix5, spy_vol


@app.cell
def _(
    build_weights,
    daily,
    gate_level,
    gate_own,
    gate_spike,
    gate_vix10,
    gate_vix5,
    pd,
    prices,
    sectors,
):
    base = build_weights(prices.drop(columns=["BIL"]), sectors)
    bases = {
        "Buy & hold": base["Buy & hold"],
        "Top 3 rotation": base["Top 3 rotation"],
        "Top 3 daily": base["Top 3 daily"],
    }
    lines = {}
    for _name, _w in bases.items():
        gated = {
            "no gate": _w,
            "level gate": _w.mul(gate_level, axis=0),
            "spike gate": _w.mul(gate_spike, axis=0),
            "VIX 5-day gate": _w.mul(gate_vix5, axis=0),
            "VIX 10-day gate": _w.mul(gate_vix10, axis=0),
            "own spike gate": _w * gate_own,
        }
        for _gate, _gw in gated.items():
            _cost = _gw.diff().abs().fillna(_gw.abs()).sum(axis=1) * 5 / 10_000
            _cash = 1 - _gw.sum(axis=1)
            lines[f"{_name}, {_gate}"] = (
                (_gw * daily[sectors]).sum(axis=1) + _cash * daily["BIL"] - _cost
            )
    frame = pd.DataFrame(lines)
    return base, frame


@app.cell
def _(mo):
    mo.md("""
    ## Results

    Windows end on the same date. Sharpe uses a 0% risk-free rate. "Exits" counts the days a gate
    switched from invested to cash.
    """)


@app.cell
def _(
    end,
    frame,
    gate_level,
    gate_own,
    gate_spike,
    gate_vix10,
    gate_vix5,
    np,
    out_dir,
    pd,
    study_start,
):
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
    for _label, (_lo, _hi) in windows.items():
        _part = frame[(frame.index >= _lo) & (frame.index <= _hi)]
        _table = pd.DataFrame({k: metrics(_part[k]) for k in frame.columns}).T.round(2)
        _table.to_csv(out_dir / f"volatility_{_label.replace(' ', '_')}.csv")
        print(
            f"\n=== {_label}: {_part.index[0].date()} to {_part.index[-1].date()} ==="
        )
        print(_table.to_string())

    in_window = gate_level.index >= study_start
    market_gates = {
        "level": gate_level,
        "spike": gate_spike,
        "VIX 5-day": gate_vix5,
        "VIX 10-day": gate_vix10,
    }
    summary = {}
    for _gname, _gate in market_gates.items():
        _g = _gate[in_window]
        summary[f"{_gname} gate"] = {
            "exits": int(((_g.shift(1) == 1) & (_g == 0)).sum()),
            "days_in_cash_%": round(100 * (1 - _g.mean()), 1),
        }
    _own = gate_own[in_window]
    summary["own spike gate (avg per ETF)"] = {
        "exits": round(float(((_own.shift(1) == 1) & (_own == 0)).sum().mean()), 1),
        "days_in_cash_%": round(100 * float(1 - _own.mean().mean()), 1),
    }
    gate_summary = pd.DataFrame(summary).T
    gate_summary.to_csv(out_dir / "volatility_gate_summary.csv")
    print("\n=== Gate activity since study start ===")
    print(gate_summary.to_string())


@app.cell
def _(mo):
    mo.md("""
    ## When did the gates act in the Covid crash?

    SPY peaked on 2020-02-19. The table shows the first day each market gate moved to cash, and
    SPY's loss from the peak up to the day before that exit would take effect.
    """)


@app.cell
def _(daily, gate_level, gate_spike, gate_vix10, gate_vix5, pd):
    peak = pd.Timestamp("2020-02-19")
    trough = pd.Timestamp("2020-03-23")
    rows = {}
    for _gname, _gate in {
        "level": gate_level,
        "spike": gate_spike,
        "VIX 5-day": gate_vix5,
        "VIX 10-day": gate_vix10,
    }.items():
        _after = _gate[(_gate.index > peak) & (_gate.index <= trough)]
        _first = _after[_after == 0].index
        if len(_first) == 0:
            rows[_gname] = {
                "first_exit_day": "none",
                "spy_loss_before_exit_%": float("nan"),
            }
            continue
        _day = _first[0]
        _path = (
            1 + daily.loc[(daily.index > peak) & (daily.index < _day), "SPY"]
        ).prod() - 1
        rows[_gname] = {
            "first_exit_day": str(_day.date()),
            "spy_loss_before_exit_%": round(100 * _path, 1),
        }
    covid = pd.DataFrame(rows).T
    print(covid.to_string())
    spy_total = (
        1 + daily.loc[(daily.index > peak) & (daily.index <= trough), "SPY"]
    ).prod() - 1
    print(f"SPY loss peak to trough: {100 * spy_total:.1f}%")


@app.cell
def _(mo):
    mo.md("""
    ## How sensitive are the gates to their thresholds?

    The 25 level was picked once, for both the SPY volatility gate and the VIX 5-day gate. This shows what other round thresholds would have done, to see
    whether the result depends on that one choice. Since the study start, with 5 bps costs.
    """)


@app.cell
def _(base, daily, np, out_dir, pd, prices, sectors, spy_vol, study_start):
    _vix5 = prices["^VIX"].rolling(5).mean()
    _sources = {
        "SPY vol": (spy_vol, [0.15, 0.20, 0.25, 0.30, 0.35], 100),
        "VIX 5-day": (_vix5, [15, 20, 25, 30, 35], 1),
    }
    _rows = {}
    for _name in ("Buy & hold", "Top 3 rotation"):
        for _kind, (_series, _limits, _scale) in _sources.items():
            for _limit in [*_limits, None]:
                if _limit is None:
                    _gate = pd.Series(1.0, index=_series.index)
                else:
                    _gate = (_series <= _limit).astype(float).shift(1).fillna(1.0)
                _gw = base[_name].mul(_gate, axis=0)
                _cost = _gw.diff().abs().fillna(_gw.abs()).sum(axis=1) * 5 / 10_000
                _r = (
                    (_gw * daily[sectors]).sum(axis=1)
                    + (1 - _gw.sum(axis=1)) * daily["BIL"]
                    - _cost
                )
                _r = _r[_r.index >= study_start]
                _g = _gate[_gate.index >= study_start]
                _equity = (1 + _r).cumprod()
                _label = (
                    f"{_kind}, no gate"
                    if _limit is None
                    else f"{_kind}, exit above {int(_limit * _scale)}{'%' if _scale == 100 else ''}"
                )
                _rows[f"{_name}, {_label}"] = {
                    "return_%": 100 * (_equity.iloc[-1] - 1),
                    "max_drawdown_%": 100 * (_equity / _equity.cummax() - 1).min(),
                    "sharpe": _r.mean() / _r.std() * np.sqrt(252),
                    "days_in_cash_%": 100 * (1 - _g.mean()),
                    "exits": int(((_g.shift(1) == 1) & (_g == 0)).sum()),
                }
    _sensitivity = pd.DataFrame(_rows).T.round(2)
    _sensitivity.to_csv(out_dir / "volatility_threshold_sensitivity.csv")
    print(_sensitivity.to_string())


@app.cell
def _(mo):
    mo.md("""
    ## By calendar year

    Return % / max drawdown % inside each year, for the base strategies with and without the
    SPY level gate. `*` marks a partial year.
    """)


@app.cell
def _(end, frame, out_dir, pd, study_start):
    _pairs = [
        c
        for c in frame.columns
        if c.endswith(("no gate", "level gate", "VIX 5-day gate", "VIX 10-day gate"))
    ]
    _years = {}
    for _year in range(study_start.year, end.year + 1):
        _lo = max(study_start, pd.Timestamp(year=_year, month=1, day=1))
        _hi = min(end, pd.Timestamp(year=_year, month=12, day=31))
        _part = frame.loc[(frame.index >= _lo) & (frame.index <= _hi), _pairs]
        _equity = (1 + _part).cumprod()
        _partial = _lo > pd.Timestamp(year=_year, month=1, day=7) or _hi < pd.Timestamp(
            year=_year, month=12, day=24
        )
        _ret = 100 * (_equity.iloc[-1] - 1)
        _dd = 100 * (_equity / _equity.cummax() - 1).min()
        _years[f"{_year}*" if _partial else str(_year)] = {
            c: f"{_ret[c]:.1f} / {_dd[c]:.1f}" for c in _pairs
        }
    _yearly = pd.DataFrame(_years)
    _yearly.to_csv(out_dir / "volatility_yearly.csv")
    print(_yearly.to_string())


@app.cell
def _(mo):
    mo.md("""
    ## Separate re-entry level on the sector strategies

    Exit when the 5-day average VIX is above 25 (as above), re-enter only when it is at or below
    the level shown. The grid (25, 22, 20, 18, 15) was fixed before running. BIL cash, 5 bps costs.
    """)


@app.cell
def _(base, daily, hysteresis_gate, np, out_dir, pd, prices, sectors, study_start):
    _vix5 = prices["^VIX"].rolling(5).mean()
    _windows = {
        "since 2019-07": (study_start, prices.index[-1]),
        "Covid crash": (pd.Timestamp("2020-02-19"), pd.Timestamp("2020-03-23")),
        "2022 bear": (pd.Timestamp("2022-01-03"), pd.Timestamp("2022-10-14")),
    }
    _out = {}
    for _name in ("Buy & hold", "Top 3 rotation"):
        for _level in (None, 25, 22, 20, 18, 15):
            _gate = (
                pd.Series(1.0, index=_vix5.index)
                if _level is None
                else hysteresis_gate(_vix5, 25, _level)
            )
            _gw = base[_name].mul(_gate, axis=0)
            _cost = _gw.diff().abs().fillna(_gw.abs()).sum(axis=1) * 5 / 10_000
            _r = (
                (_gw * daily[sectors]).sum(axis=1)
                + (1 - _gw.sum(axis=1)) * daily["BIL"]
                - _cost
            )
            _label = f"{_name}, " + (
                "no gate" if _level is None else f"re-enter {_level}"
            )
            _row = {}
            for _wname, (_lo, _hi) in _windows.items():
                _part = _r[(_r.index >= _lo) & (_r.index <= _hi)]
                _equity = (1 + _part).cumprod()
                _row[f"{_wname} return_%"] = 100 * (_equity.iloc[-1] - 1)
                _row[f"{_wname} max_dd_%"] = (
                    100 * (_equity / _equity.cummax() - 1).min()
                )
            _g = _gate[_gate.index >= study_start]
            _row["days_in_cash_%"] = 100 * (1 - _g.mean())
            _row["exits"] = int(((_g.shift(1) == 1) & (_g == 0)).sum())
            _out[_label] = _row
    _reentry = pd.DataFrame(_out).T.round(2)
    _reentry.to_csv(out_dir / "volatility_reentry.csv")
    print(_reentry.to_string())


@app.cell
def _(mo):
    mo.md("""
    ## What this does not show

    - Thresholds (25%, 1.5 times, 20 and 120 days) were set once, not tuned. Other choices would
      give different results.
    - Two selloffs are a small sample, and volatility rises after prices fall, so gates tend to
      act late in a fast crash.
    - Gates are market-wide (SPY) or per ETF, not combined with the 200-day filter.
    - No taxes or spreads beyond the 5 bps cost. Yahoo adjusted prices can be restated.
    """)


if __name__ == "__main__":
    app.run()

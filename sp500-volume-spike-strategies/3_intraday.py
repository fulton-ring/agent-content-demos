import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # 3. Intraday version, on the data Yahoo gives for free

        Yahoo only serves **hourly bars for the last 2 years** and 5-minute bars for the last 60
        days, so this is a 2-year test, not 5, and the bars are coarse. Treat it as exploratory.

        **Scanner.** After the first hour of trading (9:30-10:30), flag a stock when
        (1) yesterday's close, as traded, was $1-$20,
        (2) the first hour's volume is at least 2x the average first-hour volume of the prior
        20 days, and (3) it is up at least 2% from yesterday's close.
        The first hour's high and low form the "opening range". Every trade is closed by the
        end of the day.

        | | Idea | Entry | Stop |
        |---|---|---|---|
        | I1 | Continuation | Long at 10:30 | Opening-range low |
        | I2 | Opening-range breakout | Long when price passes the range high | Range low |
        | I3 | Fade | Short at 10:30 | Range high |
        | I4 | Support break | Short when price falls below the range low | Range high |
        | I5 | Pullback | Long after a half retrace of the day's gain | Yesterday's close |

        Each is compared with SPY over the same 2 years.
        """
    )
    return (mo,)


@app.cell
def _():
    import os
    from pathlib import Path

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    import yfinance as yf

    from common import summarize

    CACHE = Path(
        os.environ.get("SPIKES_CACHE", Path.home() / ".cache" / "sp500-volume-spike-strategies")
    )
    RESULTS = Path(__file__).parent / "results"
    RESULTS.mkdir(exist_ok=True)
    NY = "America/New_York"
    BAND_LO, BAND_HI = 1.0, 20.0
    RVOL_MIN, RET_MIN, VOL_WINDOW = 2.0, 0.02, 20
    COST_BPS = 10.0
    return (
        BAND_HI,
        BAND_LO,
        CACHE,
        COST_BPS,
        NY,
        RESULTS,
        RET_MIN,
        RVOL_MIN,
        VOL_WINDOW,
        np,
        pd,
        plt,
        summarize,
        yf,
    )


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 1: Which stocks, and the hourly data

        The daily file from notebook 1 gives yesterday's close as traded (splits multiplied back
        in, as in notebook 2). Only stocks that were in the $1-$20 band at some point in the last
        two years need hourly bars, which keeps the download small. Whether a stock qualifies on
        a given day still depends only on the previous close.
        """
    )
    return


@app.cell
def _(BAND_HI, BAND_LO, CACHE, NY, pd, yf):
    _path = CACHE / "prices.parquet"
    if not _path.exists():
        raise FileNotFoundError(f"{_path} is missing. Run 1_data.py first.")
    daily = pd.read_parquet(_path).sort_values(["ticker", "date"]).reset_index(drop=True)
    _ratio = daily["split"].where(daily["split"] > 0, 1.0)
    _later = _ratio.groupby(daily["ticker"]).transform(
        lambda s: s[::-1].cumprod()[::-1].shift(-1, fill_value=1.0)
    )
    daily["traded"] = daily["close"] * _later
    daily["prev_traded"] = daily.groupby("ticker")["traded"].shift(1)
    daily["prev_close"] = daily.groupby("ticker")["close"].shift(1)

    _cutoff = daily["date"].max() - pd.Timedelta(days=730)
    _recent = daily[daily["date"] >= _cutoff]
    universe = sorted(
        set(_recent.loc[_recent["traded"].between(BAND_LO, BAND_HI), "ticker"]) - {"SPY"}
    )

    _hourly_path = CACHE / "hourly.parquet"
    if _hourly_path.exists():
        hourly = pd.read_parquet(_hourly_path)
    else:
        _raw = yf.download(
            [*universe, "SPY"], period="2y", interval="1h", auto_adjust=False, progress=False
        )
        assert not _raw.empty, "Yahoo returned no hourly data"
        _parts = []
        for _t in [*universe, "SPY"]:
            _one = _raw.xs(_t, axis=1, level="Ticker").dropna(subset=["Close"])
            _parts.append(
                pd.DataFrame(
                    {
                        "ticker": _t,
                        "ts": _one.index.tz_convert(NY),
                        "open": _one["Open"].to_numpy(),
                        "high": _one["High"].to_numpy(),
                        "low": _one["Low"].to_numpy(),
                        "close": _one["Close"].to_numpy(),
                        "volume": _one["Volume"].to_numpy(),
                    }
                )
            )
        hourly = pd.concat(_parts, ignore_index=True)
        hourly.to_parquet(_hourly_path, index=False)
    hourly["day"] = hourly["ts"].dt.tz_localize(None).dt.normalize()
    _first_day, _last_day = hourly["day"].min().date(), hourly["day"].max().date()
    f"{len(universe)} stocks; hourly bars {_first_day} to {_last_day}"
    return daily, hourly, universe


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 2: Find the events

        Per stock and day we take the first hourly bar and compare its volume with the average
        first-hour volume of the prior 20 days.
        """
    )
    return


@app.cell
def _(RET_MIN, RVOL_MIN, VOL_WINDOW, daily, hourly, pd):
    _first = hourly[hourly["ticker"] != "SPY"].sort_values(["ticker", "ts"])
    _first = _first.groupby(["ticker", "day"], as_index=False).first()
    _first = _first[_first["ts"].dt.strftime("%H:%M") == "09:30"].copy()
    _first["rvol"] = _first["volume"] / _first.groupby("ticker")["volume"].transform(
        lambda s: s.rolling(VOL_WINDOW).mean().shift(1)
    )
    _ref = daily.rename(columns={"date": "day"})[["ticker", "day", "prev_traded", "prev_close"]]
    candidates = _first.merge(_ref, on=["ticker", "day"], how="inner")
    candidates["gain"] = candidates["close"] / candidates["prev_close"] - 1

    def pick_events(rvol_min: float, gain_min: float) -> pd.DataFrame:
        """First-hour spikes in stocks that closed yesterday in the price band."""
        _ok = (
            candidates["prev_traded"].between(1, 20)
            & (candidates["rvol"] >= rvol_min)
            & (candidates["gain"] >= gain_min)
        )
        return candidates[_ok].sort_values("day").reset_index(drop=True)

    events = pick_events(RVOL_MIN, RET_MIN)
    _n_stocks, _n_days = events["ticker"].nunique(), events["day"].nunique()
    f"{len(events)} events across {_n_stocks} stocks on {_n_days} days"
    return events, pick_events


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 3: Entry and exit rules

        Bar 0 is the first hour, the signal. Trades can only start from bar 1 (10:30) onward.
        Stop and breakout entries fill at the trigger price, or at the bar's open if it gaps
        past. Inside one hourly bar we cannot tell the order of the high and low, so if a bar
        reaches both the stop and anything else, the stop is assumed first.
        """
    )
    return


@app.cell
def _(hourly, np, pd):
    _bars = hourly.sort_values(["ticker", "ts"])
    day_bars: dict[tuple[str, pd.Timestamp], pd.DataFrame] = {
        (str(_t), _d): _g.reset_index(drop=True)
        for (_t, _d), _g in _bars.groupby(["ticker", "day"])
    }
    _spy = _bars[_bars["ticker"] == "SPY"].set_index("ts")
    spy_open, spy_close = _spy["open"], _spy["close"]

    def find_entry(
        strategy: str, o: np.ndarray, h: np.ndarray, low: np.ndarray, c0: float, prev_close: float
    ) -> tuple[int, float, int, float] | None:
        """Return (entry bar, price, +1 long / -1 short, stop price), or None if no trade."""
        if len(o) < 2:
            return None
        rng_high, rng_low = float(h[0]), float(low[0])
        if strategy == "I1":
            return 1, float(o[1]), 1, rng_low
        if strategy == "I3":
            return 1, float(o[1]), -1, rng_high
        pullback = c0 - 0.5 * (c0 - prev_close)
        for i in range(1, len(o)):
            if strategy == "I2" and h[i] >= rng_high:
                return i, max(float(o[i]), rng_high), 1, rng_low
            if strategy == "I4" and low[i] <= rng_low:
                return i, min(float(o[i]), rng_low), -1, rng_high
            if strategy == "I5" and low[i] <= pullback:
                return i, min(float(o[i]), pullback), 1, float(prev_close)
        return None

    return day_bars, find_entry, spy_close, spy_open


@app.cell
def _(COST_BPS, day_bars, find_entry, np, pd, spy_close, spy_open):
    def run_trades(
        events: pd.DataFrame, strategies: tuple[str, ...], cost_bps: float
    ) -> pd.DataFrame:
        """Trade every strategy on every event day, closing at the last bar of the day."""
        rows = []
        for _e in events.itertuples():
            _b = day_bars[(_e.ticker, _e.day)]
            _o, _h, _l, _c = (_b[k].to_numpy() for k in ("open", "high", "low", "close"))
            for strategy in strategies:
                _entry = find_entry(strategy, _o, _h, _l, float(_c[0]), float(_e.prev_close))
                if _entry is None:
                    continue
                _i, _px, _side, _stop = _entry
                _j, _exit_px = len(_c) - 1, float(_c[-1])
                for _k in range(_i, len(_c)):
                    _gap = _k > _i and (_o[_k] - _stop) * _side <= 0
                    _hit = _l[_k] <= _stop if _side == 1 else _h[_k] >= _stop
                    if _gap or _hit:
                        _j, _exit_px = _k, float(_o[_k]) if _gap else _stop
                        break
                _ret = _side * (_exit_px / _px - 1) - 2 * cost_bps / 1e4
                _spy = spy_close.get(_b["ts"][_j], np.nan) / spy_open.get(_b["ts"][_i], np.nan) - 1
                rows.append((strategy, _e.ticker, _e.day, _side, _px, _exit_px, _ret, _spy))
        _cols = [
            "strategy",
            "ticker",
            "entry_date",
            "side",
            "entry_px",
            "exit_px",
            "ret",
            "spy_ret",
        ]
        _t = pd.DataFrame(rows, columns=_cols)
        _t["excess"] = _t["ret"] - _t["side"] * _t["spy_ret"]
        return _t

    STRATEGIES = ("I1", "I2", "I3", "I4", "I5")
    NAMES = {
        "I1": "I1 continuation",
        "I2": "I2 opening-range breakout",
        "I3": "I3 fade (short)",
        "I4": "I4 support break (short)",
        "I5": "I5 pullback",
    }
    return NAMES, STRATEGIES, run_trades


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 4: Results against SPY

        Costs: 0.10% each way, no borrow fees. `vs_SPY` per trade subtracts SPY's move over the
        same hours (for shorts, assuming a matching SPY long hedge).

        **Portfolio view.** To compare with owning SPY, each day's trades are given equal shares
        of the whole account and the account sits in cash on days with no trade. That is a
        deliberately aggressive way to size, chosen so that "total return" is comparable to
        buy-and-hold SPY. SPY here is bought at the first open and held to the last close.
        """
    )
    return


@app.cell
def _(COST_BPS, NAMES, STRATEGIES, events, hourly, np, pd, run_trades, summarize):
    trades = run_trades(events, STRATEGIES, COST_BPS)
    _spy = hourly[hourly["ticker"] == "SPY"].sort_values("ts")
    _spy_days = _spy.groupby("day").agg(open=("open", "first"), close=("close", "last"))
    _all_days = _spy_days.index

    def drawdown(equity: pd.Series) -> float:
        return float((equity / equity.cummax() - 1).min())

    _spy_equity = _spy_days["close"] / _spy_days["open"].iloc[0]
    _rows = []
    equity: dict[str, pd.Series] = {}
    for _s in STRATEGIES:
        _t = trades[trades["strategy"] == _s]
        _stats = summarize(_t)
        _daily = _t.groupby("entry_date")["ret"].mean().reindex(_all_days).fillna(0.0)
        _eq = (1 + _daily).cumprod()
        equity[NAMES[_s]] = _eq
        _rows.append(
            {
                "strategy": NAMES[_s],
                **_stats,
                "vs_SPY_per_trade": summarize(_t, "excess").get("mean"),
                "days_traded": int(_t["entry_date"].nunique()),
                "account_total_return": float(_eq.iloc[-1] - 1),
                "account_max_drawdown": drawdown(_eq),
            }
        )
    headline = pd.DataFrame(_rows).set_index("strategy")
    spy_total = float(_spy_equity.iloc[-1] - 1)
    spy_drawdown = drawdown(_spy_equity)
    equity["SPY buy and hold"] = _spy_equity
    summary = pd.concat(
        [
            headline,
            pd.DataFrame(
                {"account_total_return": [spy_total], "account_max_drawdown": [spy_drawdown]},
                index=pd.Index(["SPY buy and hold"], name="strategy"),
            ),
        ]
    )
    summary.round(4)
    return equity, spy_drawdown, spy_total, summary, trades


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 5: Does it hold up with other scanner settings and costs?
        """
    )
    return


@app.cell
def _(COST_BPS, NAMES, STRATEGIES, events, pd, pick_events, run_trades, summarize):
    _rows = []
    for _rvol, _gain in ((2.0, 0.02), (3.0, 0.03), (3.0, 0.05), (5.0, 0.03)):
        _ev = pick_events(_rvol, _gain)
        _t = run_trades(_ev, STRATEGIES, COST_BPS)
        _row = {"scanner": f"first-hour rvol>={_rvol:g}, gain>={_gain:.0%}", "events": len(_ev)}
        for _s in STRATEGIES:
            _row[NAMES[_s]] = summarize(_t[_t["strategy"] == _s]).get("mean")
        _rows.append(_row)
    scanner_grid = pd.DataFrame(_rows).set_index("scanner")

    _rows = []
    for _bps in (0.0, COST_BPS, 25.0):
        _t = run_trades(events, STRATEGIES, _bps)
        _rows.append(
            {"cost_bps_per_side": _bps}
            | {NAMES[_s]: summarize(_t[_t["strategy"] == _s]).get("mean") for _s in STRATEGIES}
        )
    cost_grid = pd.DataFrame(_rows).set_index("cost_bps_per_side")
    pd.concat({"scanner settings": scanner_grid.round(4)}).round(4)
    return cost_grid, scanner_grid


@app.cell
def _(NAMES, RESULTS, STRATEGIES, equity, plt, trades):
    _fig, (_ax1, _ax2) = plt.subplots(1, 2, figsize=(13, 4.8))
    for _name, _eq in equity.items():
        _ax1.plot(_eq.index, (_eq - 1) * 100, label=_name, lw=2.5 if "SPY" in _name else 1.3)
    _ax1.set_title("Account value change (%), equal share of account across each day's trades")
    _ax1.set_ylabel("percent since start")
    _ax1.legend(fontsize=7)
    _ax1.grid(alpha=0.3)
    _ax2.boxplot(
        [trades.loc[trades["strategy"] == _s, "ret"] * 100 for _s in STRATEGIES],
        tick_labels=[NAMES[_s].split(" ")[0] for _s in STRATEGIES],
        showfliers=False,
    )
    _ax2.axhline(0, color="k", lw=0.8)
    _ax2.set_title("Per-trade return (%), outliers hidden")
    _ax2.grid(alpha=0.3)
    _fig.tight_layout()
    _fig.savefig(RESULTS / "intraday_returns.png", dpi=130)
    _fig
    return


@app.cell
def _(
    RESULTS,
    cost_grid,
    events,
    scanner_grid,
    spy_drawdown,
    spy_total,
    summary,
    trades,
):
    events.drop(columns=["volume"]).to_csv(RESULTS / "intraday_events.csv", index=False)
    trades.to_csv(RESULTS / "intraday_trades.csv", index=False)
    summary.round(5).to_csv(RESULTS / "intraday_summary.csv")
    scanner_grid.round(5).to_csv(RESULTS / "intraday_sensitivity_scanner.csv")
    cost_grid.round(5).to_csv(RESULTS / "intraday_sensitivity_costs.csv")
    print(summary.round(4).to_string())
    print(f"\nSPY buy and hold: {spy_total:.2%}, max drawdown {spy_drawdown:.2%}\n")
    print(scanner_grid.round(4).to_string())
    print()
    print(cost_grid.round(4).to_string())
    return


if __name__ == "__main__":
    app.run()

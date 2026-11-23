import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # 2. The backtest: what happens after a cheap S&P 500 stock jumps on heavy volume?

        **Scanner.** At the close, flag any S&P 500 stock that
        (1) closed between $1 and $20 *as actually traded that day*,
        (2) rose at least 5% on the day, and
        (3) traded at least 3x its average volume of the prior 20 days.

        **Strategies**, all decided from daily bars with no look-ahead (day 0 is the flagged day):

        | | Idea | Entry |
        |---|---|---|
        | A | Continuation, naive | Long at day 1 open |
        | B | Continuation, confirmed | Long only if day 1 trades above day 0's high |
        | C | Fade | Short at day 1 open |
        | D | Buy the pullback | Long if price gives back half of day 0's gain within 5 days |
        | E | Support breaks | Days 1-3 hold a tight box under day 0's high; short below its low |
        | F | Resistance breaks | Same box; long above its high |

        Every trade exits on a fixed stop or after a fixed number of days, whichever comes first.
        Parameters are set before looking at results and every combination is reported,
        so there is nothing to cherry-pick.
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

    CACHE = Path(
        os.environ.get("SPIKES_CACHE", Path.home() / ".cache" / "sp500-volume-spike-strategies")
    )
    RESULTS = Path(__file__).parent / "results"
    RESULTS.mkdir(exist_ok=True)
    SEED = 7

    # Scanner, fixed in advance.
    BAND_LO, BAND_HI = 1.0, 20.0
    RVOL_MIN, RET_MIN = 3.0, 0.05
    VOL_WINDOW = 20
    COOLDOWN = 10  # trading days before the same ticker can be flagged again

    # Strategy rules, fixed in advance.
    PULLBACK_FRACTION, PULLBACK_WINDOW = 0.5, 5
    BOX_DAYS, BOX_MAX_RANGE, WATCH_DAYS = 3, 0.10, 10

    # Exits: default first, then the grid that is reported in full.
    DEFAULT_HOLD, DEFAULT_STOP, DEFAULT_COST_BPS = 5, 0.08, 10.0
    HOLDS = (3, 5, 10)
    STOPS = (0.05, 0.08, None)
    CONTROL_SAMPLE = 20_000
    BOOTSTRAPS = 2000
    return (
        BAND_HI,
        BAND_LO,
        BOOTSTRAPS,
        BOX_DAYS,
        BOX_MAX_RANGE,
        CACHE,
        CONTROL_SAMPLE,
        COOLDOWN,
        DEFAULT_COST_BPS,
        DEFAULT_HOLD,
        DEFAULT_STOP,
        HOLDS,
        PULLBACK_FRACTION,
        PULLBACK_WINDOW,
        RESULTS,
        RET_MIN,
        RVOL_MIN,
        SEED,
        STOPS,
        VOL_WINDOW,
        WATCH_DAYS,
        np,
        pd,
        plt,
    )


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 1: Rebuild the price as traded

        Yahoo divides old prices by every later split. A stock that is $200 today after a 10-for-1
        split shows as $20 ten years ago, but it traded at $200 then. Filtering on Yahoo's price
        would put such stocks in the $1-$20 band wrongly, so we multiply the splits back in.
        """
    )
    return


@app.cell
def _(CACHE, VOL_WINDOW, pd):
    _path = CACHE / "prices.parquet"
    if not _path.exists():
        raise FileNotFoundError(f"{_path} is missing. Run 1_data.py first.")
    prices = pd.read_parquet(_path)

    days_by_ticker: dict[str, pd.DataFrame] = {}
    for _ticker, _g in prices.groupby("ticker"):
        _g = _g.sort_values("date").dropna(subset=["open", "high", "low", "close"])
        _g = _g.reset_index(drop=True)
        _ratio = _g["split"].where(_g["split"] > 0, 1.0)
        # Product of splits that happen after each day (the split day's own price is post-split).
        _later = _ratio[::-1].cumprod()[::-1].shift(-1, fill_value=1.0)
        _g["traded_close"] = _g["close"] * _later
        _g["ret"] = _g["close"].pct_change()
        _g["rvol"] = _g["volume"] / _g["volume"].rolling(VOL_WINDOW).mean().shift(1)
        days_by_ticker[str(_ticker)] = _g

    spy = days_by_ticker.pop("SPY").set_index("date")
    n_splits_fixed = int(
        sum((d["traded_close"] != d["close"]).any() for d in days_by_ticker.values())
    )
    f"{len(days_by_ticker)} stocks; {n_splits_fixed} had their price changed by the split fix"
    return days_by_ticker, n_splits_fixed, spy


@app.cell
def _(BAND_HI, BAND_LO, COOLDOWN, RET_MIN, RVOL_MIN, days_by_ticker, pd):
    _frames = []
    for _ticker, _g in days_by_ticker.items():
        _f = _g.loc[
            _g["traded_close"].between(BAND_LO, BAND_HI), ["date", "traded_close", "ret", "rvol"]
        ]
        _f = _f.assign(ticker=_ticker, i=_f.index)
        _frames.append(_f.dropna())
    band_days = pd.concat(_frames, ignore_index=True)

    def pick_events(rvol_min: float, ret_min: float) -> pd.DataFrame:
        """Flagged days, keeping the first of any run closer than COOLDOWN trading days."""
        _hits = band_days[(band_days["rvol"] >= rvol_min) & (band_days["ret"] >= ret_min)]
        _hits = _hits.sort_values(["ticker", "i"])
        _keep = []
        _last: dict[str, int] = {}
        for _row in _hits.itertuples():
            if _row.i - _last.get(_row.ticker, -10_000) > COOLDOWN:
                _keep.append(_row.Index)
                _last[_row.ticker] = _row.i
        return _hits.loc[_keep].sort_values("date").reset_index(drop=True)

    events = pick_events(RVOL_MIN, RET_MIN)
    f"{len(band_days):,} stock-days in the $1-$20 band; {len(events)} scanner events"
    return band_days, events, pick_events


@app.cell
def _(events, mo):
    _by_year = events.groupby(events["date"].dt.year).size().rename("events")
    _top = events.groupby("ticker").size().sort_values(ascending=False).head(8).rename("events")
    mo.md(
        f"""
        ### The scanner's output

        {len(events)} events across {events["ticker"].nunique()} tickers. Events per year:
        {", ".join(f"{y}: {n}" for y, n in _by_year.items())}.
        The most frequent tickers: {", ".join(f"{t} ({n})" for t, n in _top.items())}.
        """
    )
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 2: Turn each strategy into entry and exit rules

        `find_entry` returns the bar, price and direction where a strategy would trade, using
        only bars up to that point. Stop-style entries (B, D, E, F) fill at the trigger price, or
        at the open if the price gaps past it. `simulate` then walks forward bar by bar.
        On a bar where both the stop and a profitable move are possible we assume the stop hit
        first, and a gap through the stop fills at the open.
        """
    )
    return


@app.cell
def _(
    BOX_DAYS,
    BOX_MAX_RANGE,
    PULLBACK_FRACTION,
    PULLBACK_WINDOW,
    WATCH_DAYS,
    days_by_ticker,
    np,
    pd,
    spy,
):
    bars: dict[str, tuple[np.ndarray, ...]] = {
        _t: tuple(_g[_c].to_numpy() for _c in ("open", "high", "low", "close"))
        for _t, _g in days_by_ticker.items()
    }
    dates: dict[str, pd.DatetimeIndex] = {
        _t: pd.DatetimeIndex(_g["date"]) for _t, _g in days_by_ticker.items()
    }
    spy_open, spy_close = spy["open"], spy["close"]

    def find_entry(
        strategy: str, o: np.ndarray, h: np.ndarray, low: np.ndarray, c: np.ndarray, i0: int
    ) -> tuple[int, float, int] | None:
        """Return (entry bar, entry price, +1 long / -1 short), or None if no trade."""
        n = len(c)
        i1 = i0 + 1
        if i1 >= n:
            return None
        if strategy == "A":
            return i1, float(o[i1]), 1
        if strategy == "C":
            return i1, float(o[i1]), -1
        if strategy == "B":
            trigger = float(h[i0])
            if o[i1] >= trigger:
                return i1, float(o[i1]), 1
            return (i1, trigger, 1) if h[i1] >= trigger else None
        if strategy == "D":
            level = float(c[i0] - PULLBACK_FRACTION * (c[i0] - c[i0 - 1]))
            for i in range(i1, min(i1 + PULLBACK_WINDOW, n)):
                if low[i] <= level:
                    return i, min(float(o[i]), level), 1
            return None
        box = slice(i1, i1 + BOX_DAYS)
        if i1 + BOX_DAYS >= n:
            return None
        box_high, box_low = float(h[box].max()), float(low[box].min())
        if box_high > h[i0] or (box_high - box_low) / c[i0] > BOX_MAX_RANGE:
            return None
        for i in range(i1 + BOX_DAYS, min(i1 + BOX_DAYS + WATCH_DAYS, n)):
            if strategy == "E" and low[i] <= box_low:
                return i, min(float(o[i]), box_low), -1
            if strategy == "F" and h[i] >= box_high:
                return i, max(float(o[i]), box_high), 1
        return None

    def simulate(
        o: np.ndarray,
        h: np.ndarray,
        low: np.ndarray,
        c: np.ndarray,
        entry_i: int,
        entry_px: float,
        side: int,
        hold: int,
        stop: float | None,
    ) -> tuple[int, float] | None:
        """Walk forward from the entry bar. Return (exit bar, exit price), None if data ends."""
        last = entry_i + hold - 1
        if last >= len(c):
            return None
        stop_px = None if stop is None else entry_px * (1 - side * stop)
        for i in range(entry_i, last + 1):
            if stop_px is None:
                continue
            if i > entry_i and (o[i] - stop_px) * side <= 0:
                return i, float(o[i])
            if (low[i] <= stop_px) if side == 1 else (h[i] >= stop_px):
                return i, stop_px
        return last, float(c[last])

    def run_trades(
        signals: pd.DataFrame,
        strategies: tuple[str, ...],
        hold: int,
        stop: float | None,
        cost_bps: float,
    ) -> pd.DataFrame:
        """Apply every strategy to every flagged day. Return one row per trade."""
        rows = []
        for _s in signals.itertuples():
            _o, _h, _l, _c = bars[_s.ticker]
            for strategy in strategies:
                _entry = find_entry(strategy, _o, _h, _l, _c, _s.i)
                if _entry is None:
                    continue
                _i, _px, _side = _entry
                _exit = simulate(_o, _h, _l, _c, _i, _px, _side, hold, stop)
                if _exit is None:
                    continue
                _j, _exit_px = _exit
                _d_in, _d_out = dates[_s.ticker][_i], dates[_s.ticker][_j]
                _ret = _side * (_exit_px / _px - 1) - 2 * cost_bps / 1e4
                _spy = spy_close.get(_d_out, np.nan) / spy_open.get(_d_in, np.nan) - 1
                rows.append(
                    (strategy, _s.ticker, _s.date, _d_in, _d_out, _side, _px, _exit_px, _ret, _spy)
                )
        _cols = [
            "strategy", "ticker", "event_date", "entry_date", "exit_date", "side",
            "entry_px", "exit_px", "ret", "spy_ret",
        ]  # fmt: skip
        _t = pd.DataFrame(rows, columns=_cols)
        _t["excess"] = _t["ret"] - _t["side"] * _t["spy_ret"]
        return _t

    return find_entry, run_trades, simulate


@app.cell
def _(BOOTSTRAPS, SEED, np, pd):
    def summarize(trades: pd.DataFrame, column: str = "ret") -> dict[str, float]:
        """Headline numbers. The 95% interval resamples whole months, because events cluster."""
        x = trades[column].to_numpy()
        n = len(x)
        if n < 5:
            return {"n": n}
        wins, losses = x[x > 0].sum(), -x[x < 0].sum()
        month = trades["entry_date"].dt.to_period("M").astype(str).to_numpy()
        _, inverse = np.unique(month, return_inverse=True)
        sums = np.bincount(inverse, weights=x)
        counts = np.bincount(inverse).astype(float)
        draws = np.random.default_rng(SEED).integers(0, len(sums), size=(BOOTSTRAPS, len(sums)))
        boot = sums[draws].sum(axis=1) / counts[draws].sum(axis=1)
        return {
            "n": n,
            "win_rate": float((x > 0).mean()),
            "mean": float(x.mean()),
            "median": float(np.median(x)),
            "profit_factor": float(wins / losses) if losses > 0 else float("inf"),
            "ci_low": float(np.percentile(boot, 2.5)),
            "ci_high": float(np.percentile(boot, 97.5)),
        }

    return (summarize,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 3: Headline results

        Default exits: stop 8% from entry, or sell at the close of the 5th trading day from entry.
        Costs: 10 basis points (0.10%) each way for slippage and commission. No borrow fees on
        shorts. `mean` is the average return per trade. `vs_SPY` subtracts what SPY did over the
        same window (for shorts, assumes a matching SPY long hedge).

        **Control.** To see whether the scanner adds anything, strategy A's rules are applied to
        random $1-$20 stock-days that did *not* trigger the scanner.
        """
    )
    return


@app.cell
def _(
    CONTROL_SAMPLE,
    DEFAULT_COST_BPS,
    DEFAULT_HOLD,
    DEFAULT_STOP,
    SEED,
    band_days,
    events,
    pd,
    run_trades,
    summarize,
):
    STRATEGIES = ("A", "B", "C", "D", "E", "F")
    NAMES = {
        "A": "A continuation (open)",
        "B": "B continuation (confirmed)",
        "C": "C fade (short)",
        "D": "D buy pullback",
        "E": "E range break down (short)",
        "F": "F range break up",
        "control": "control: A on non-events",
    }
    trades = run_trades(events, STRATEGIES, DEFAULT_HOLD, DEFAULT_STOP, DEFAULT_COST_BPS)

    _event_keys = set(zip(events["ticker"], events["date"], strict=True))
    _non_events = band_days[
        [
            (t, d) not in _event_keys
            for t, d in zip(band_days["ticker"], band_days["date"], strict=True)
        ]
    ]
    _sample = _non_events.sample(min(CONTROL_SAMPLE, len(_non_events)), random_state=SEED)
    control = run_trades(_sample, ("A",), DEFAULT_HOLD, DEFAULT_STOP, DEFAULT_COST_BPS)
    control["strategy"] = "control"

    _rows = []
    for _name, _t in [(s, trades[trades["strategy"] == s]) for s in STRATEGIES] + [
        ("control", control)
    ]:
        _r = summarize(_t)
        _ex = summarize(_t, "excess")
        _trim = _t["ret"].nsmallest(max(len(_t) - 3, 0)).mean()
        _rows.append(
            {"strategy": NAMES[_name], **_r, "mean_ex_top3": _trim, "vs_SPY": _ex.get("mean")}
        )
    headline = pd.DataFrame(_rows).set_index("strategy")
    headline.round(4)
    return NAMES, STRATEGIES, control, headline, trades


@app.cell
def _(
    DEFAULT_COST_BPS,
    DEFAULT_HOLD,
    DEFAULT_STOP,
    NAMES,
    STRATEGIES,
    events,
    run_trades,
    summarize,
    pd,
):
    _rows = []
    for _bps in (0.0, DEFAULT_COST_BPS, 25.0):
        _t = run_trades(events, STRATEGIES, DEFAULT_HOLD, DEFAULT_STOP, _bps)
        for _s in STRATEGIES:
            _rows.append(
                {
                    "cost_bps_per_side": _bps,
                    "strategy": NAMES[_s],
                    "mean": summarize(_t[_t["strategy"] == _s]).get("mean"),
                }
            )
    costs = pd.DataFrame(_rows).pivot(index="strategy", columns="cost_bps_per_side", values="mean")
    costs.round(4)
    return (costs,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 4: Do the results survive other exits, other scanner thresholds and other years?

        If a strategy only works for one stop, one holding period, one threshold, or one year, the
        headline number is probably luck. Every combination is shown, not just the best.
        """
    )
    return


@app.cell
def _(HOLDS, STOPS, DEFAULT_COST_BPS, NAMES, STRATEGIES, events, pd, run_trades, summarize):
    _rows = []
    for _hold in HOLDS:
        for _stop in STOPS:
            _t = run_trades(events, STRATEGIES, _hold, _stop, DEFAULT_COST_BPS)
            _label = f"hold {_hold}d, stop {'none' if _stop is None else f'{_stop:.0%}'}"
            for _s in STRATEGIES:
                _rows.append(
                    {
                        "exit": _label,
                        "strategy": NAMES[_s],
                        "mean": summarize(_t[_t["strategy"] == _s]).get("mean"),
                    }
                )
    exit_grid = pd.DataFrame(_rows).pivot(index="strategy", columns="exit", values="mean")
    exit_grid.round(4)
    return (exit_grid,)


@app.cell
def _(
    DEFAULT_COST_BPS,
    DEFAULT_HOLD,
    DEFAULT_STOP,
    NAMES,
    STRATEGIES,
    pd,
    pick_events,
    run_trades,
    summarize,
):
    _rows = []
    for _rvol in (2.0, 3.0, 5.0):
        for _ret in (0.03, 0.05, 0.08):
            _ev = pick_events(_rvol, _ret)
            _t = run_trades(_ev, STRATEGIES, DEFAULT_HOLD, DEFAULT_STOP, DEFAULT_COST_BPS)
            _row = {"scanner": f"rvol>={_rvol:g}, gain>={_ret:.0%}", "events": len(_ev)}
            for _s in STRATEGIES:
                _row[NAMES[_s]] = summarize(_t[_t["strategy"] == _s]).get("mean")
            _rows.append(_row)
    scanner_grid = pd.DataFrame(_rows).set_index("scanner")
    scanner_grid.round(4)
    return (scanner_grid,)


@app.cell
def _(NAMES, STRATEGIES, pd, trades):
    _t = trades.assign(year=trades["entry_date"].dt.year)
    by_year = _t.pivot_table(index="strategy", columns="year", values="ret", aggfunc="mean")
    by_year.index = [NAMES[s] for s in by_year.index]
    _n = _t.pivot_table(index="strategy", columns="year", values="ret", aggfunc="count")
    _n.index = [NAMES[s] for s in _n.index]
    by_year_n = _n.reindex([NAMES[s] for s in STRATEGIES])
    by_year = by_year.reindex([NAMES[s] for s in STRATEGIES])
    pd.concat({"mean return": by_year, "trades": by_year_n}, axis=1).round(3)
    return by_year, by_year_n


@app.cell
def _(NAMES, STRATEGIES, pd, summarize, trades):
    _cut = trades["entry_date"].sort_values().iloc[len(trades) // 2]
    _rows = []
    for _s in STRATEGIES:
        _t = trades[trades["strategy"] == _s]
        _first, _second = _t[_t["entry_date"] < _cut], _t[_t["entry_date"] >= _cut]
        _rows.append(
            {
                "strategy": NAMES[_s],
                "first_half_n": len(_first),
                "first_half_mean": summarize(_first).get("mean"),
                "second_half_n": len(_second),
                "second_half_mean": summarize(_second).get("mean"),
            }
        )
    halves = pd.DataFrame(_rows).set_index("strategy")
    halves.round(4)
    return (halves,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Step 5: Were these stocks in the index at the time?

        The member list is today's, and a stock is often added to the S&P 500 *because* it rose
        a lot. So a cheap stock that spiked years before joining is a future winner that nobody
        could have picked from the index at that time. The member list gives each stock's
        "date added", so we split the events into those before and after that date.
        (A stock that was removed and re-added shows its latest date, so this is approximate.)
        """
    )
    return


@app.cell
def _(CACHE, NAMES, STRATEGIES, events, pd, summarize, trades):
    _members = pd.read_csv(CACHE / "members.csv")
    _members["ticker"] = _members["Symbol"].str.replace(".", "-", regex=False)
    _added = pd.to_datetime(_members.set_index("ticker")["Date added"])
    _member_at_event = events["date"] >= events["ticker"].map(_added)
    member_flag = dict(
        zip(zip(events["ticker"], events["date"], strict=True), _member_at_event, strict=True)
    )
    _t = trades.assign(
        member=[member_flag[k] for k in zip(trades["ticker"], trades["event_date"], strict=True)]
    )
    _rows = []
    for _s in STRATEGIES:
        _row = {"strategy": NAMES[_s]}
        for _flag, _label in ((True, "member_then"), (False, "not_yet_member")):
            _r = summarize(_t[(_t["strategy"] == _s) & (_t["member"] == _flag)])
            _row[f"{_label}_n"] = _r["n"]
            _row[f"{_label}_mean"] = _r.get("mean")
        _rows.append(_row)
    by_membership = pd.DataFrame(_rows).set_index("strategy")
    n_not_member = int((~_member_at_event).sum())
    by_membership.round(4)
    return by_membership, n_not_member


@app.cell
def _(NAMES, RESULTS, STRATEGIES, control, plt, trades):
    _fig, (_ax1, _ax2) = plt.subplots(1, 2, figsize=(13, 4.8))
    for _s in STRATEGIES:
        _t = trades[trades["strategy"] == _s].sort_values("entry_date")
        _ax1.plot(_t["entry_date"], _t["ret"].cumsum() * 100, label=NAMES[_s])
    _ax1.set_title("Cumulative sum of per-trade returns (%), default exits")
    _ax1.set_ylabel("percentage points, 1 unit per trade")
    _ax1.legend(fontsize=7)
    _ax1.grid(alpha=0.3)
    _ax2.hist(
        [trades.loc[trades["strategy"] == "A", "ret"] * 100, control["ret"] * 100],
        bins=40, range=(-15, 25), density=True, label=["A after scanner", "control"],
    )  # fmt: skip
    _ax2.set_title("Trade return distribution, continuation (A) vs control (%)")
    _ax2.legend()
    _ax2.grid(alpha=0.3)
    _fig.tight_layout()
    _fig.savefig(RESULTS / "returns.png", dpi=130)
    _fig
    return


@app.cell
def _(
    NAMES,
    RESULTS,
    by_year,
    by_year_n,
    control,
    costs,
    events,
    exit_grid,
    halves,
    headline,
    scanner_grid,
    trades,
    by_membership,
):
    events.to_csv(RESULTS / "events.csv", index=False)
    pd_all = trades.assign(strategy=trades["strategy"].map(NAMES))
    pd_all.to_csv(RESULTS / "trades_default_exits.csv", index=False)
    control.sample(min(2000, len(control)), random_state=1).to_csv(
        RESULTS / "control_trades_sample.csv", index=False
    )
    headline.round(5).to_csv(RESULTS / "headline.csv")
    costs.round(5).to_csv(RESULTS / "sensitivity_costs.csv")
    exit_grid.round(5).to_csv(RESULTS / "sensitivity_exits.csv")
    scanner_grid.round(5).to_csv(RESULTS / "sensitivity_scanner.csv")
    by_year.round(5).to_csv(RESULTS / "by_year_mean.csv")
    by_year_n.to_csv(RESULTS / "by_year_trades.csv")
    halves.round(5).to_csv(RESULTS / "halves.csv")
    by_membership.round(5).to_csv(RESULTS / "by_membership.csv")
    print(headline.round(4).to_string())
    print()
    print(costs.round(4).to_string())
    print()
    print(exit_grid.round(4).to_string())
    print()
    print(scanner_grid.round(4).to_string())
    print()
    print(halves.round(4).to_string())
    print()
    print(by_membership.round(4).to_string())
    return


@app.cell
def _(headline, mo, n_not_member, events):
    _a, _ctl = headline.loc["A continuation (open)"], headline.loc["control: A on non-events"]
    _widest = headline["ci_high"].sub(headline["ci_low"]).drop("control: A on non-events")
    mo.md(
        f"""
        ## What this does and does not show

        - **Small samples.** {len(events)} events in ten years, and the two range-break
        strategies (E, F) traded only {int(headline.loc["E range break down (short)", "n"])} and
        {int(headline.loc["F range break up", "n"])} times. The 95% intervals on the mean return
        per trade are as wide as {_widest.max():.1%} across, so most rows cannot be told apart
        from zero.
        - **A few trades carry the averages.** Without each strategy's three best trades, A's mean
        is {_a["mean_ex_top3"]:.2%} and D's is
        {headline.loc["D buy pullback", "mean_ex_top3"]:.2%} (column `mean_ex_top3`).
        - **The scanner barely beats the control.** Continuation (A) averaged {_a["mean"]:.2%} per
        trade against {_ctl["mean"]:.2%} for random $1-$20 stock-days, with the same exits.
        - **Today's members, not the index as it was.** {n_not_member} of the {len(events)}
        events were in stocks that joined the S&P 500 later (step 5). Stocks that fell out of the
        index are missing entirely, so long-side results are probably flattered.
        - **Daily bars only.** A real scanner works inside the day. Free intraday history is
        limited to about 60 days, so entries near the open or on intraday breaks are not tested.
        - **Not modelled:** borrow fees and short squeezes, position sizing, several trades at
        once, taxes, and stocks that cannot be traded at the quoted price.
        """
    )
    return


if __name__ == "__main__":
    app.run()

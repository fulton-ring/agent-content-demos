import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # 2. The backtest: does the AI model price the NYC high better than Kalshi?

        `1_data.py` saved a year of Kalshi prices, ECMWF AIFS and NOAA NBM forecasts, and
        Central Park sensor data. Here we turn every source into a probability for each of the
        day's six brackets, at three times before the market closes, and score them against
        how the market settled. Then we paper-trade the model against the quoted prices,
        after Kalshi's fees.
        """
    )
    return (mo,)


@app.cell
def _():
    import datetime as dt
    import os
    from pathlib import Path

    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import numpy as np
    import pandas as pd
    from scipy.stats import norm

    CACHE = Path(
        os.environ.get("KALSHI_NYC_CACHE", Path.home() / ".cache" / "kalshi-nyc-temperature")
    )
    RESULTS = Path(__file__).parent / "results"
    RESULTS.mkdir(exist_ok=True)
    markets = pd.read_parquet(CACHE / "markets.parquet")
    prices = pd.read_parquet(CACHE / "prices.parquet")
    aifs = pd.read_parquet(CACHE / "aifs.parquet")
    nbm = pd.read_parquet(CACHE / "nbm.parquet")
    cli = pd.read_parquet(CACHE / "cli.parquet").set_index("date").cli_high
    obs = pd.read_parquet(CACHE / "obs.parquet").set_index("date")
    SNAPSHOTS = ["D-1 16:00", "D 08:00", "D 14:00"]
    return RESULTS, SNAPSHOTS, aifs, cli, dt, markets, nbm, norm, np, obs, pd, plt, prices


@app.cell
def _(mo):
    mo.md(
        """
        ## The answer key

        The answer is the bracket Kalshi paid out on. Kalshi also publishes the settled high
        (`expiration_value`), though the archive leaves it blank on some days. We check that
        the paid bracket contains the settled high where there is one, fill the blanks from
        the NWS Daily Climate Report when it falls in the paid bracket, and count how often
        the two sources disagree, since Kalshi switched from the NWS report to The Weather
        Company in August 2026.
        """
    )
    return


@app.cell
def _(cli, markets, np, obs, pd):
    def in_bracket(high: float, strike_type: str, floor: float, cap: float) -> bool:
        if strike_type == "greater":
            return high > floor
        if strike_type == "less":
            return high < cap
        return floor <= high <= cap

    markets["won"] = markets.result == "yes"
    _known = markets[markets.settled_high.notna()]
    _rule = [in_bracket(m.settled_high, m.strike_type, m.floor, m.cap) for m in _known.itertuples()]
    _agree = (_known.won == _rule).mean()
    assert _agree > 0.99, f"bracket rule disagrees with Kalshi on {1 - _agree:.1%} of brackets"
    _paid = markets[markets.won].set_index("date")
    assert _paid.index.is_unique, "more than one paid bracket on a day"
    days = _paid[["settled_high", "source"]].copy()
    days["cli_high"] = cli.reindex(days.index)
    _cli_in_paid = [
        in_bracket(c, m.strike_type, m.floor, m.cap)
        for c, m in zip(days.cli_high, _paid.itertuples(), strict=True)
    ]
    _fill = days.settled_high.isna() & np.array(_cli_in_paid)
    print(
        f"{days.settled_high.isna().sum()} days have no settled high; {_fill.sum()} filled from CLI"
    )
    days.loc[_fill, "settled_high"] = days.cli_high[_fill]
    _diff = (days.settled_high - days.cli_high)[~_fill]
    answer_key = pd.DataFrame(
        {
            "days": days.groupby("source").size(),
            "settled_high_differs_from_CLI": (_diff != 0).groupby(days.source[~_fill]).sum(),
        }
    )
    print(f"Kalshi's payouts match its settled value on {_agree:.2%} of brackets")
    print(f"Mean |settled - CLI| = {np.abs(_diff).mean():.2f} °F where both exist")
    _max_1min = obs.max_1min.round().reindex(days.index).dropna()
    _above = (_max_1min > days.settled_high.reindex(_max_1min.index)).mean()
    print(f"Central Park's 1-minute max reads above the settled high on {_above:.0%} of days")
    answer_key
    return days, in_bracket


@app.cell
def _(mo):
    mo.md(
        """
        ## The market's forecast

        At each snapshot the market's probability for a bracket is the midpoint of the yes bid
        and ask. The six midpoints rarely sum to exactly 1, so we scale them to.
        Brackets with no quote on one side (bid 0 or ask 1) still count, at their midpoint.
        """
    )
    return


@app.cell
def _(days, markets, prices):
    book = prices.merge(markets[["ticker", "strike_type", "floor", "cap", "won"]], on="ticker")
    book = book[book.date.isin(days.index)]
    book["mid"] = (book.yes_bid + book.yes_ask) / 2
    _ok = book.groupby(["date", "snapshot"]).mid.transform(lambda s: s.notna().all())
    book = book[_ok].copy()
    book["p_market"] = book.mid / book.groupby(["date", "snapshot"]).mid.transform("sum")
    _spread = (book.yes_ask - book.yes_bid).median()
    print(f"Median quoted spread: {_spread * 100:.0f} cents")
    book.groupby("snapshot").date.nunique().rename("days with a full book")
    return (book,)


@app.cell
def _(mo):
    mo.md(
        """
        ## The models' forecasts

        A forecast of the high becomes bracket probabilities by assuming the error is normal:
        a centre `mu` and a spread `sigma`, integrated over each whole degree.

        - **AIFS raw.** `mu` is the warmest 6-hourly temperature over the day from the latest
          AIFS run at the snapshot; `sigma` is the root-mean-square error of that number over
          the last 30 days. No shift.
        - **AIFS corrected.** Learns from the Central Park record. `mu` adds the average miss
          over the last 30 days (observed high minus AIFS), and `sigma` is the spread of those
          misses. Only days already reported by the snapshot are used: two days back for the
          4 pm D-1 snapshot, one day back on the day.
        - **NBM.** NOAA's max temperature and its own standard deviation, as issued.
        - **NBM corrected.** The same 30-day correction applied to the NBM.
        - **AIFS + 2 pm sensors** (2 pm snapshot only). By 2 pm we know two things from the
          Central Park 1-minute record: the high so far, which the final high can't go below,
          and how warm it is now compared with what AIFS said for this hour. We shift `mu` by
          that afternoon anomaly, correct it like the others, and floor the distribution
          one degree below the high so far, because the 1-minute record often reads a degree
          above the official high.
        """
    )
    return


@app.cell
def _(SNAPSHOTS, aifs, cli, days, dt, nbm, np, obs, pd):
    WINDOW = 30
    # One AIFS forecast of the high per snapshot: the warmest 6-hourly value from its run.
    hist = aifs.groupby(["date", "snapshot"]).t2m_f.max().unstack()
    hist["aifs_2pm"] = (
        aifs[(aifs.snapshot == "D 14:00") & (aifs.valid_hour == 18)].set_index("date").t2m_f
    )
    hist["cli_high"] = cli
    hist = hist.join(obs[["temp_2pm", "max_by_2pm", "minutes_by_2pm"]])

    def latest_nbm(day: dt.date, issued_before: pd.Timestamp) -> pd.Series | None:
        runs = nbm[(nbm.date == day) & (nbm.runtime <= issued_before)]
        return None if runs.empty else runs.loc[runs.runtime.idxmax()]

    def snapshot_utc(day: dt.date, snapshot: str) -> pd.Timestamp:
        offset = -1 if snapshot.startswith("D-1") else 0
        hour = int(snapshot.split()[1][:2])
        local = pd.Timestamp(day + dt.timedelta(days=offset)).replace(hour=hour)
        return local.tz_localize("America/New_York").tz_convert("UTC")

    _nbm_rows = []
    for _day in hist.index:
        for _snap in SNAPSHOTS:
            _run = latest_nbm(_day, snapshot_utc(_day, _snap) - pd.Timedelta(hours=1))
            if _run is not None:
                _nbm_rows.append((_day, _snap, _run.nbm_max, _run.nbm_sd))
    nbm_at = pd.DataFrame(_nbm_rows, columns=["date", "snapshot", "nbm_max", "nbm_sd"])

    def trailing(errors: pd.Series, day: dt.date, lag: int) -> pd.Series:
        """The last WINDOW errors known `lag` days before `day`."""
        known = errors[errors.index <= day - dt.timedelta(days=lag)].dropna()
        return known.iloc[-WINDOW:]

    _rows = []
    for _day in days.index:
        for _snap in SNAPSHOTS:
            _lag = 2 if _snap.startswith("D-1") else 1
            _f = hist[_snap]
            _err = trailing(hist.cli_high - _f, _day, _lag)
            _n = nbm_at[nbm_at.snapshot == _snap].set_index("date")
            _nerr = trailing(hist.cli_high - _n.nbm_max.reindex(hist.index), _day, _lag)
            if len(_err) < WINDOW or _day not in _f.index or _day not in _n.index:
                continue
            _row = {
                "date": _day,
                "snapshot": _snap,
                "aifs_raw_mu": _f[_day],
                "aifs_raw_sd": (_err**2).mean() ** 0.5,
                "aifs_corr_mu": _f[_day] + _err.mean(),
                "aifs_corr_sd": _err.std(),
                "nbm_mu": _n.nbm_max[_day],
                "nbm_sd": _n.nbm_sd[_day],
                "nbm_corr_mu": _n.nbm_max[_day] + _nerr.mean(),
                "nbm_corr_sd": _nerr.std() if len(_nerr) >= 10 else _n.nbm_sd[_day],
            }
            if _snap == "D 14:00":
                # Shift the AIFS high by how much warmer Central Park is at 2 pm than AIFS
                # said; the 30-day correction then removes the usual size of that gap.
                _pred = _f + (hist.temp_2pm - hist.aifs_2pm)
                _perr = trailing(hist.cli_high - _pred, _day, 1)
                _row["sensor_mu"] = _pred[_day] + _perr.mean()
                _row["sensor_sd"] = _perr.std()
                # The 1-minute record often reads a degree above the official high (see the
                # answer key), so the floor is one degree below it, and only on days where
                # at least 10 of the 14 hours before 2 pm were recorded.
                _complete = hist.minutes_by_2pm.get(_day, 0) >= 600
                _row["sensor_floor"] = hist.max_by_2pm.get(_day) - 1 if _complete else np.nan
            _rows.append(_row)
    forecasts = pd.DataFrame(_rows)
    forecasts.groupby("snapshot").size().rename("days with every model")
    return forecasts, hist


@app.cell
def _(mo):
    mo.md(
        """
        How far off is each forecast of the high, before any probabilities? Error is the
        settled high minus the forecast centre, so a positive mean means the forecast ran cold.
        """
    )
    return


@app.cell
def _(RESULTS, days, forecasts, pd):
    _f = forecasts.merge(days.settled_high, left_on="date", right_index=True)
    _rows = []
    for _snap, _g in _f.groupby("snapshot", sort=False):
        for _name, _col in [
            ("AIFS raw", "aifs_raw"),
            ("AIFS corrected", "aifs_corr"),
            ("NBM", "nbm"),
            ("AIFS + 2 pm sensors", "sensor"),
        ]:
            if f"{_col}_mu" not in _g or _g[f"{_col}_mu"].isna().all():
                continue
            _err = (_g.settled_high - _g[f"{_col}_mu"]).dropna()
            _rows.append(
                {
                    "snapshot": _snap,
                    "forecast": _name,
                    "days": len(_err),
                    "mean_error": _err.mean(),
                    "mean_abs_error": _err.abs().mean(),
                    "misses_over_3F": (_err.abs() > 3).mean(),
                }
            )
    errors = pd.DataFrame(_rows)
    errors.to_csv(RESULTS / "errors.csv", index=False)
    errors.round(2)
    return


@app.cell
def _(book, forecasts, in_bracket, norm, np, pd):
    SOURCES = {
        "Market": None,
        "AIFS raw": "aifs_raw",
        "AIFS corrected": "aifs_corr",
        "NBM": "nbm",
        "NBM corrected": "nbm_corr",
        "AIFS + 2 pm sensors": "sensor",
    }
    whole_degrees = np.arange(-20, 131)

    def degree_probs(mu: float, sd: float, floor: float = np.nan) -> np.ndarray:
        """P(high = k) for each whole degree k, with an optional known minimum."""
        sd = max(sd, 1.0)
        p = norm.cdf(whole_degrees + 0.5, mu, sd) - norm.cdf(whole_degrees - 0.5, mu, sd)
        if not np.isnan(floor):
            floor = round(floor)
            p = np.where(whole_degrees < floor, 0.0, p)
            p[whole_degrees == floor] += norm.cdf(floor - 0.5, mu, sd)
        return p / p.sum()

    _f = forecasts.set_index(["date", "snapshot"])
    scored = book.merge(forecasts[["date", "snapshot"]], on=["date", "snapshot"])
    for _name, _col in SOURCES.items():
        if _col is None:
            continue
        _probs = []
        for _r in scored.itertuples():
            _fc = _f.loc[(_r.date, _r.snapshot)]
            if f"{_col}_mu" not in _fc or pd.isna(_fc[f"{_col}_mu"]):
                _probs.append(np.nan)
                continue
            _p = degree_probs(
                _fc[f"{_col}_mu"], _fc[f"{_col}_sd"], _fc.get(f"{_col}_floor", np.nan)
            )
            _mask = [in_bracket(k, _r.strike_type, _r.floor, _r.cap) for k in whole_degrees]
            _probs.append(_p[_mask].sum())
        scored[f"p_{_name}"] = _probs
    scored = scored.rename(columns={"p_market": "p_Market"})
    scored[
        ["date", "snapshot", "ticker", "yes_bid", "yes_ask", "won"] + [f"p_{s}" for s in SOURCES]
    ].head(6)
    return SOURCES, scored


@app.cell
def _(mo):
    mo.md(
        """
        ## Scores

        For each day and snapshot, the **Brier score** sums the squared gap between each
        bracket's probability and what happened (1 for the winning bracket, 0 for the rest),
        and the **log loss** is minus the log of the probability given to the bracket that won
        (floored at 0.001). Lower is better for both. Every source is scored on the same days.
        The last column is the log-loss gap to the market with a 95% interval; a negative gap
        means the source beat the market.
        """
    )
    return


@app.cell
def _(RESULTS, SNAPSHOTS, SOURCES, np, pd, scored):
    _rows = []
    _daily = []
    for _snap in SNAPSHOTS:
        _s = scored[scored.snapshot == _snap]
        for _src in SOURCES:
            _p = _s[["date", "won", f"p_{_src}"]].dropna()
            if _p.empty:
                continue
            _brier = ((_p[f"p_{_src}"] - _p.won) ** 2).groupby(_p.date).sum()
            _ll = -np.log(_p[_p.won][f"p_{_src}"].clip(lower=1e-3)).groupby(_p[_p.won].date).sum()
            _daily.append(
                pd.DataFrame({"snapshot": _snap, "source": _src, "brier": _brier, "log_loss": _ll})
            )
    daily_scores = pd.concat(_daily).reset_index()
    for (_snap, _src), _g in daily_scores.groupby(["snapshot", "source"], sort=False):
        _m = daily_scores[(daily_scores.snapshot == _snap) & (daily_scores.source == "Market")]
        _gap = _g.set_index("date").log_loss - _m.set_index("date").log_loss
        _gap = _gap.dropna()
        _rows.append(
            {
                "snapshot": _snap,
                "source": _src,
                "days": len(_g),
                "brier": _g.brier.mean(),
                "log_loss": _g.log_loss.mean(),
                "log_loss_vs_market": _gap.mean(),
                "ci95": 1.96 * _gap.std() / max(len(_gap), 1) ** 0.5,
            }
        )
    scores = pd.DataFrame(_rows)
    scores.to_csv(RESULTS / "scores.csv", index=False)
    scores.round(3)
    return (daily_scores,)


@app.cell
def _(mo):
    mo.md(
        """
        ## Calibration

        Pooling every bracket, a calibrated source's 30% brackets win about 30% of the time.
        Points below the diagonal mean the source was overconfident in that range.
        """
    )
    return


@app.cell
def _(RESULTS, SNAPSHOTS, np, plt, scored):
    _fig, _axes = plt.subplots(1, 3, figsize=(13, 4.2), sharey=True)
    _bins = np.linspace(0, 1, 11)
    for _ax, _snap in zip(_axes, SNAPSHOTS, strict=True):
        _s = scored[scored.snapshot == _snap]
        _show = ["Market", "AIFS raw", "AIFS corrected", "NBM"] + (
            ["AIFS + 2 pm sensors"] if _snap == "D 14:00" else []
        )
        for _src in _show:
            _p = _s[[f"p_{_src}", "won"]].dropna()
            _bin = np.digitize(_p[f"p_{_src}"], _bins[1:-1])
            _g = _p.groupby(_bin).agg(
                p=(f"p_{_src}", "mean"), hit=("won", "mean"), n=("won", "size")
            )
            _g = _g[_g.n >= 5]
            _ax.plot(_g.p, _g.hit, marker="o", label=_src)
        _ax.plot([0, 1], [0, 1], color="grey", linestyle=":", linewidth=1)
        _ax.set_title(_snap)
        _ax.set_xlabel("forecast probability")
    _axes[0].set_ylabel("share that won")
    _axes[0].legend(fontsize=8)
    _axes[2].legend(fontsize=8)
    _fig.tight_layout()
    _fig.savefig(RESULTS / "calibration.png", dpi=120)
    _fig
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## Paper trading

        A simple rule: at each snapshot, for each bracket, buy 10 **yes** contracts at the ask
        if the model's probability beats the ask plus the fee by at least the threshold, or buy
        10 **no** contracts at 1 minus the bid if the model's "no" probability beats that plus
        the fee by the threshold. Hold to settlement. Kalshi's series data says `KXHIGHNY`
        uses the quadratic fee with multiplier 1: a taker pays 0.07 × contracts × price ×
        (1 − price), rounded up to the next cent, per order. We trade only against a real
        quote (bid above 0, ask below 1) and assume the whole order fills at the quoted price:
        no slippage and no queue.
        """
    )
    return


@app.cell
def _(np, pd, scored):
    CONTRACTS = 10

    def fee(price: float) -> float:
        return np.ceil(0.07 * CONTRACTS * price * (1 - price) * 100 - 1e-9) / 100

    def paper_trades(source: str, threshold: float) -> pd.DataFrame:
        s = scored.dropna(subset=[f"p_{source}"])
        s = s[(s.yes_bid > 0) & (s.yes_ask < 1)]
        p = s[f"p_{source}"]
        yes_edge = p - s.yes_ask - s.yes_ask.map(fee) / CONTRACTS
        no_price = 1 - s.yes_bid
        no_edge = (1 - p) - no_price - no_price.map(fee) / CONTRACTS
        buy_yes = s[yes_edge >= threshold].assign(side="yes", price=lambda d: d.yes_ask)
        buy_no = s[(no_edge >= threshold) & ~(yes_edge >= threshold)].assign(
            side="no", price=lambda d: 1 - d.yes_bid
        )
        t = pd.concat([buy_yes, buy_no])
        wins = np.where(t.side == "yes", t.won, ~t.won)
        t["pnl"] = CONTRACTS * (wins - t.price) - t.price.map(fee)
        return t.sort_values(["date", "snapshot"])

    def summary(t: pd.DataFrame) -> dict:
        cum = t.pnl.cumsum()
        return {
            "trades": len(t),
            "hit_rate": (t.pnl > 0).mean() if len(t) else np.nan,
            "staked": (CONTRACTS * t.price).sum(),
            "fees": t.price.map(fee).sum(),
            "pnl": t.pnl.sum(),
            # Rough: treats trades as independent, though trades on one day are not.
            "pnl_ci95": 1.96 * t.pnl.std() * len(t) ** 0.5 if len(t) > 1 else np.nan,
            "max_drawdown": (cum.cummax().clip(lower=0) - cum).max() if len(t) else 0.0,
        }

    return paper_trades, summary


@app.cell
def _(RESULTS, SNAPSHOTS, SOURCES, paper_trades, pd, summary):
    _rows = []
    for _src in [s for s in SOURCES if s != "Market"]:
        for _th in (0.02, 0.05, 0.10, 0.20):
            _t = paper_trades(_src, _th)
            _rows.append({"source": _src, "snapshot": "all", "threshold": _th, **summary(_t)})
            if _th == 0.05:
                for _snap in SNAPSHOTS:
                    _ts = _t[_t.snapshot == _snap]
                    if len(_ts):
                        _rows.append(
                            {"source": _src, "snapshot": _snap, "threshold": _th, **summary(_ts)}
                        )
    trading = pd.DataFrame(_rows)
    trading.to_csv(RESULTS / "trading.csv", index=False)
    trading.round(2)
    return


@app.cell
def _(RESULTS, SOURCES, paper_trades, plt):
    _fig, _ax = plt.subplots(figsize=(9, 4))
    for _src in [s for s in SOURCES if s != "Market"]:
        _t = paper_trades(_src, 0.05)
        if len(_t):
            _ax.plot(
                _t.date.to_numpy(), _t.pnl.cumsum().to_numpy(), label=f"{_src} ({len(_t)} trades)"
            )
    _ax.axhline(0, color="grey", linewidth=0.8)
    _ax.set_ylabel("cumulative P&L after fees ($, 10 contracts a trade)")
    _ax.set_title("Paper trading at a 5-cent edge threshold")
    _ax.legend(fontsize=8)
    _fig.autofmt_xdate()
    _fig.tight_layout()
    _fig.savefig(RESULTS / "pnl.png", dpi=120)
    _fig
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## The days that went wrong

        The ten days the corrected AIFS forecast scored worst at 8 am on the day, with what
        the market thought and what the Central Park sensor saw. `hour_of_max` is the hour
        (New York time) of the highest 1-minute reading; a high set before 9 am usually means
        a cold front came through and the afternoon was cooler than the night.
        """
    )
    return


@app.cell
def _(RESULTS, daily_scores, days, forecasts, hist, obs, scored):
    _ll = daily_scores[(daily_scores.snapshot == "D 08:00")].pivot(
        index="date", columns="source", values="log_loss"
    )
    _worst = _ll.sort_values("AIFS corrected", ascending=False).head(10)
    _f = forecasts[forecasts.snapshot == "D 08:00"].set_index("date")
    _s = scored[scored.snapshot == "D 08:00"]
    _fav = _s.loc[_s.groupby("date").p_Market.idxmax()].set_index("date")
    bad_days = _worst[["Market", "AIFS corrected", "NBM"]].rename(columns=lambda c: f"log_loss {c}")
    bad_days["settled_high"] = days.settled_high.reindex(bad_days.index)
    bad_days["aifs_corr_mu"] = _f.aifs_corr_mu.reindex(bad_days.index).round(1)
    bad_days["aifs_raw"] = hist["D 08:00"].reindex(bad_days.index).round(1)
    bad_days["nbm_mu"] = _f.nbm_mu.reindex(bad_days.index)
    bad_days["market_favourite"] = _fav.ticker.str.split("-").str[-1].reindex(bad_days.index)
    bad_days["hour_of_max"] = obs.hour_of_max.reindex(bad_days.index)
    bad_days.to_csv(RESULTS / "bad_days.csv")
    bad_days.round(2)
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## What this does and doesn't show

        It is one city, one market and one year, scored after the fact. The model side uses
        a single 00 UTC AIFS run per day and a normal error curve; a better pipeline would use
        later runs and the AIFS ensemble. The trading assumes every order fills at the quoted
        price, with no slippage, depth limit or queue. The README sums up the numbers.
        """
    )
    return


if __name__ == "__main__":
    app.run()

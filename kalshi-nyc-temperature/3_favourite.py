import marimo

__generated_with = "0.25.2"
app = marimo.App(width="medium")


@app.cell
def _():
    import marimo as mo

    mo.md(
        """
        # 3. Is the market underconfident on its favourite bracket?

        The calibration plot in `2_backtest.py` hinted that Kalshi's NYC high-temperature
        market underprices its favourite: brackets priced around 60 to 80% at 4 pm the day
        before and at 8 am seemed to win more often than that. That was seen by eye, on the
        whole year, pooling every bracket. Here we test it properly, three ways:

        1. **Calibration of the favourite alone**, by price bin, with 95% intervals.
        2. **A trading rule picked on the first half of the year and scored on the second**:
           buy the favourite at the ask when its price is in a fixed band, after Kalshi's fee.
        3. **Before and after the settlement-source switch** on 2026-08-14 (NWS Daily Climate
           Report to The Weather Company).

        It uses only the Kalshi tables `1_data.py` saved: each bracket's result and its yes
        bid and ask at the three snapshots.
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
    from scipy.stats import binomtest

    CACHE = Path(
        os.environ.get("KALSHI_NYC_CACHE", Path.home() / ".cache" / "kalshi-nyc-temperature")
    )
    RESULTS = Path(__file__).parent / "results"
    RESULTS.mkdir(exist_ok=True)
    markets = pd.read_parquet(CACHE / "markets.parquet")
    prices = pd.read_parquet(CACHE / "prices.parquet")
    SNAPSHOTS = ["D-1 16:00", "D 08:00", "D 14:00"]
    # The split for the out-of-sample test, and Kalshi's settlement-source switch.
    SECOND_HALF = pd.Timestamp("2026-04-20")
    SWITCH = pd.Timestamp("2026-08-14")
    return (
        RESULTS,
        SECOND_HALF,
        SNAPSHOTS,
        SWITCH,
        binomtest,
        markets,
        np,
        pd,
        plt,
        prices,
    )


@app.cell
def _(mo):
    mo.md(
        """
        ## Each day's favourite

        At each snapshot the favourite is the bracket with the highest bid-ask midpoint. We
        keep only days where all six brackets have a quote and exactly one bracket paid out,
        as in `2_backtest.py`. The midpoint is the market's price; the ask is what a buyer
        would actually pay, so we keep both.
        """
    )
    return


@app.cell
def _(markets, pd, prices):
    _book = prices.merge(markets[["ticker", "result"]], on="ticker")
    _book["won"] = _book.result == "yes"
    _book["mid"] = (_book.yes_bid + _book.yes_ask) / 2
    _book["date"] = pd.to_datetime(_book.date)
    _groups = _book.groupby(["date", "snapshot"])
    _full = _groups.mid.transform(lambda s: s.notna().all()) & (_groups.won.transform("sum") == 1)
    _book = _book[_full]
    fav = (
        _book.loc[_book.groupby(["date", "snapshot"]).mid.idxmax()]
        .reset_index(drop=True)
        .sort_values(["snapshot", "date"])
    )
    print(f"{fav.date.nunique()} days; favourites per snapshot:")
    fav.groupby("snapshot").agg(
        days=("date", "size"),
        mean_mid=("mid", "mean"),
        mean_ask=("yes_ask", "mean"),
        won=("won", "mean"),
    ).round(3)
    return (fav,)


@app.cell
def _(mo):
    mo.md(
        """
        ## 1. Calibration of the favourite

        If the market is calibrated, favourites priced at 70% win about 70% of the time. For
        each snapshot and price bin we count wins and give a Wilson 95% interval for the win
        rate. One favourite a day, so the days are independent draws. The last column of the
        summary is the **gap**: win rate minus average midpoint, with a 95% interval. A gap
        above zero means the market was underconfident.
        """
    )
    return


@app.cell
def _(RESULTS, SNAPSHOTS, binomtest, fav, np, pd):
    BINS = [0.0, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]
    _fav = fav.assign(bin=pd.cut(fav.mid, BINS, right=False))
    _rows = []
    for (_snap, _bin), _g in _fav.groupby(["snapshot", "bin"], observed=True):
        _ci = binomtest(int(_g.won.sum()), len(_g)).proportion_ci(method="wilson")
        _rows.append(
            {
                "snapshot": _snap,
                "price_bin": f"{_bin.left:.0%}-{min(_bin.right, 1):.0%}",
                "n": len(_g),
                "mean_mid": _g.mid.mean(),
                "win_rate": _g.won.mean(),
                "ci_low": _ci.low,
                "ci_high": _ci.high,
            }
        )
    calibration = pd.DataFrame(_rows)
    calibration.to_csv(RESULTS / "favourite_calibration.csv", index=False)

    def gap(g: pd.DataFrame) -> pd.Series:
        """Win rate minus average price, with a normal 95% interval over days."""
        diff = g.won - g.mid
        return pd.Series(
            {
                "n": len(g),
                "mean_mid": g.mid.mean(),
                "win_rate": g.won.mean(),
                "gap": diff.mean(),
                "gap_ci95": 1.96 * diff.std() / np.sqrt(len(g)),
            }
        )

    _overall = [gap(fav[fav.snapshot == s]).rename(s) for s in SNAPSHOTS]
    _band = [
        gap(fav[(fav.snapshot == s) & fav.mid.between(0.6, 0.8, inclusive="left")]).rename(
            f"{s}, priced 60-80%"
        )
        for s in SNAPSHOTS
    ]
    gaps = pd.DataFrame(_overall + _band)
    gaps.to_csv(RESULTS / "favourite_gaps.csv")
    calibration.round(3)
    return calibration, gap, gaps


@app.cell
def _(gaps):
    gaps.round(3)
    return


@app.cell
def _(RESULTS, SNAPSHOTS, calibration, plt):
    _fig, _axes = plt.subplots(1, 3, figsize=(13, 4.2), sharey=True)
    for _ax, _snap in zip(_axes, SNAPSHOTS, strict=True):
        _c = calibration[calibration.snapshot == _snap]
        _ax.errorbar(
            _c.mean_mid,
            _c.win_rate,
            yerr=[_c.win_rate - _c.ci_low, _c.ci_high - _c.win_rate],
            marker="o",
            capsize=3,
            linestyle="none",
        )
        for _x, _y, _n in zip(_c.mean_mid, _c.win_rate, _c.n, strict=True):
            _ax.annotate(f"{_n}", (_x, _y), textcoords="offset points", xytext=(6, -10), fontsize=7)
        _ax.plot([0, 1], [0, 1], color="grey", linestyle=":", linewidth=1)
        _ax.set_title(f"Favourite at {_snap}")
        _ax.set_xlabel("midpoint price")
        _ax.set_xlim(0.2, 1)
    _axes[0].set_ylim(0, 1.05)
    _axes[0].set_ylabel("share that won (95% Wilson interval; n per bin)")
    _fig.tight_layout()
    _fig.savefig(RESULTS / "favourite_calibration.png", dpi=120)
    _fig
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## 2. A trading rule, picked on the first half, scored on the second

        The rule: at one snapshot, if the favourite's **ask** is in a band [low, high), buy 10
        yes contracts at the ask and hold to settlement, paying Kalshi's taker fee
        (0.07 × contracts × price × (1 − price), rounded up to the cent, as in
        `2_backtest.py`). Only real quotes count (bid above 0, ask below 1).

        We try every band with edges on a 10-cent grid from 40% to 90%, at each of the three
        snapshots, on the first half of the year (2025-10-20 to 2026-04-19), and keep the one
        with the best P&L among those with at least 20 trades. Then we score that one rule,
        untouched, on the second half (2026-04-20 to 2026-10-19). Picking the best of 63
        rules in-sample is exactly how a noise result looks good, so only the second half
        counts.
        """
    )
    return


@app.cell
def _(np, pd):
    CONTRACTS = 10

    def fee(price: float) -> float:
        return np.ceil(0.07 * CONTRACTS * price * (1 - price) * 100 - 1e-9) / 100

    def trades(snapshot: str, low: float, high: float, days: pd.DataFrame) -> pd.DataFrame:
        t = days[(days.snapshot == snapshot) & (days.yes_bid > 0) & (days.yes_ask < 1)]
        t = t[(t.yes_ask >= low - 1e-9) & (t.yes_ask < high - 1e-9)].copy()
        t["fee"] = t.yes_ask.map(fee)
        t["pnl"] = CONTRACTS * (t.won - t.yes_ask) - t.fee
        return t

    def summary(t: pd.DataFrame) -> dict:
        cum = t.pnl.cumsum()
        return {
            "trades": len(t),
            "hit_rate": t.won.mean() if len(t) else np.nan,
            "mean_ask": t.yes_ask.mean() if len(t) else np.nan,
            "fees": t.fee.sum(),
            "pnl": t.pnl.sum(),
            # One trade a day, so trades are independent draws.
            "pnl_ci95": 1.96 * t.pnl.std() * len(t) ** 0.5 if len(t) > 1 else np.nan,
            "max_drawdown": (cum.cummax().clip(lower=0) - cum).max() if len(t) else 0.0,
        }

    return summary, trades


@app.cell
def _(RESULTS, SECOND_HALF, SNAPSHOTS, fav, pd, summary, trades):
    _first = fav[fav.date < SECOND_HALF]
    _edges = [0.4, 0.5, 0.6, 0.7, 0.8, 0.9]
    _rows = []
    for _snap in SNAPSHOTS:
        for _lo in _edges:
            for _hi in [e for e in _edges + [1.0] if e > _lo]:
                _rows.append(
                    {
                        "snapshot": _snap,
                        "low": _lo,
                        "high": _hi,
                        **summary(trades(_snap, _lo, _hi, _first)),
                    }
                )
    in_sample = pd.DataFrame(_rows)
    in_sample.to_csv(RESULTS / "favourite_rule_first_half.csv", index=False)
    chosen = in_sample[in_sample.trades >= 20].sort_values("pnl").iloc[-1]
    print(
        f"{len(in_sample)} rules tried; best in the first half: buy the favourite at "
        f"{chosen.snapshot} when its ask is in [{chosen.low:.0%}, {chosen.high:.0%}): "
        f"{chosen.trades:.0f} trades, P&L ${chosen.pnl:.2f} ± {chosen.pnl_ci95:.2f}"
    )
    in_sample.sort_values("pnl", ascending=False).head(10).round(2)
    return (chosen,)


@app.cell
def _(mo):
    mo.md(
        """
        Out of sample: the chosen rule on the second half, and, for comparison, the 60 to 80%
        band the calibration plot first suggested, at each snapshot. That band was spotted on
        the whole year, so it isn't a clean out-of-sample test, but if even it loses in the
        second half the effect isn't there to trade.
        """
    )
    return


@app.cell
def _(RESULTS, SECOND_HALF, SNAPSHOTS, chosen, fav, pd, summary, trades):
    _second = fav[fav.date >= SECOND_HALF]
    _rules = [("chosen in first half", chosen.snapshot, chosen.low, chosen.high)] + [
        ("eyeballed 60-80%", s, 0.6, 0.8) for s in SNAPSHOTS
    ]
    _rows = []
    for _label, _snap, _lo, _hi in _rules:
        _t = trades(_snap, _lo, _hi, _second)
        _rows.append({"rule": _label, "snapshot": _snap, "low": _lo, "high": _hi, **summary(_t)})
    out_of_sample = pd.DataFrame(_rows)
    out_of_sample.to_csv(RESULTS / "favourite_rule_second_half.csv", index=False)
    chosen_trades = trades(chosen.snapshot, chosen.low, chosen.high, _second)
    out_of_sample.round(2)
    return (chosen_trades,)


@app.cell
def _(RESULTS, chosen, chosen_trades, plt):
    _fig, _ax = plt.subplots(figsize=(9, 3.6))
    _ax.plot(chosen_trades.date.to_numpy(), chosen_trades.pnl.cumsum().to_numpy())
    _ax.axhline(0, color="grey", linewidth=0.8)
    _ax.set_ylabel("cumulative P&L after fees ($)")
    _ax.set_title(
        f"Second half: buy 10 of the favourite at {chosen.snapshot} when the ask is in "
        f"[{chosen.low:.0%}, {chosen.high:.0%})"
    )
    _fig.autofmt_xdate()
    _fig.tight_layout()
    _fig.savefig(RESULTS / "favourite_pnl.png", dpi=120)
    _fig
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## 3. Before and after the settlement-source switch

        On 2026-08-14 Kalshi moved settlement from the NWS Daily Climate Report to The
        Weather Company. `2_backtest.py` found the two agreed on every day both exist, but a
        change in source could still change how traders price the favourite. We split the
        calibration gap at the switch, and the chosen rule's second-half trades with it.
        """
    )
    return


@app.cell
def _(SNAPSHOTS, SWITCH, chosen_trades, fav, gap, pd, summary):
    _rows = []
    for _snap in SNAPSHOTS:
        for _label, _part in [("before", fav.date < SWITCH), ("after", fav.date >= SWITCH)]:
            _rows.append(gap(fav[(fav.snapshot == _snap) & _part]).rename(f"{_snap}, {_label}"))
    by_source = pd.DataFrame(_rows)
    _split = pd.DataFrame(
        {
            "before": summary(chosen_trades[chosen_trades.date < SWITCH]),
            "after": summary(chosen_trades[chosen_trades.date >= SWITCH]),
        }
    ).T
    print("Chosen rule's second-half trades, before and after the switch:")
    print(_split.round(2).to_string())
    by_source.round(3)
    return


@app.cell
def _(mo):
    mo.md(
        """
        ## What this does and doesn't show

        The tables above are the result; the README states the answer in a sentence. Limits:
        one year of one market; prices are hourly closes, and every order fills in full at
        the quoted ask with no slippage; the bins and bands are coarse because a year gives
        only about 180 favourites per half per snapshot, so an edge of a few cents is below
        what this sample can detect.
        """
    )
    return


if __name__ == "__main__":
    app.run()

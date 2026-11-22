"""Position rules shared by the notebooks: fraction of capital per ETF, decided at each close."""

import pandas as pd


def build_weights(prices: pd.DataFrame, tickers: list[str]) -> dict[str, pd.DataFrame]:
    """Return next-day position weights for each strategy over `tickers`.

    `prices` must also hold an `SPY` column, used by the market-filter strategies.
    Rotation rules change only on the last trading day of each month or week.
    """
    assert "SPY" in prices.columns, "SPY is needed for the market filters"
    dates = pd.DatetimeIndex(prices.index)
    month_ends = (
        prices.index.to_series().groupby(dates.to_period("M")).last().to_numpy()
    )
    week_ends = prices.index.to_series().groupby(dates.to_period("W")).last().to_numpy()
    spy = prices["SPY"]
    spy_above_200 = (spy > spy.rolling(200).mean()).astype(float)
    spy_mom_ok = (spy.shift(21) / spy.shift(252) - 1 > 0).astype(float)
    px = prices[tickers]
    n = len(tickers)
    mom12 = px.shift(21) / px.shift(252) - 1
    mom6 = px.shift(21) / px.shift(126) - 1
    top3 = (mom12.rank(axis=1, ascending=False) <= 3) & mom12.notna()
    top3_w = top3 / 3
    dual_w = (top3 & (mom12 > 0)) / 3
    rotation = top3_w.loc[month_ends].reindex(px.index).ffill()
    dual = dual_w.loc[month_ends].reindex(px.index).ffill()
    rotation_weekly = top3_w.loc[week_ends].reindex(px.index).ffill()
    dual_weekly = dual_w.loc[week_ends].reindex(px.index).ffill()
    positive = mom12.clip(lower=0)
    total = positive.sum(axis=1)
    mom_weighted = positive.div(total.where(total > 0), axis=0).fillna(0.0)
    mom6_positive = mom6.clip(lower=0)
    total6 = mom6_positive.sum(axis=1)
    mom6_weighted = mom6_positive.div(total6.where(total6 > 0), axis=0).fillna(0.0)
    mom_weighted_monthly = mom_weighted.loc[month_ends].reindex(px.index).ffill()
    equal = pd.DataFrame(1.0 / n, index=px.index, columns=tickers)
    raw = {
        "Buy & hold": equal,
        "SMA 10/50": (px.rolling(10).mean() > px.rolling(50).mean()) / n,
        "Momentum 12-1": (mom12 > 0) / n,
        "Momentum 6-1": (mom6 > 0) / n,
        "Top 3 rotation": rotation,
        "Dual momentum": dual,
        "Top 3 weekly": rotation_weekly,
        "Top 3 daily": top3_w,
        "Momentum-weighted daily": mom_weighted,
        "Momentum-weighted 6-1 daily": mom6_weighted,
        "Momentum-weighted monthly": mom_weighted_monthly,
        "Dual momentum weekly": dual_weekly,
        "Dual momentum daily": dual_w,
        "SPY filter, 200-day": equal.mul(spy_above_200, axis=0),
        "SPY filter, momentum": equal.mul(spy_mom_ok, axis=0),
    }
    return {k: v.astype(float).shift(1).fillna(0.0) for k, v in raw.items()}


def ranked_weights(
    score: pd.DataFrame,
    eligible: pd.DataFrame,
    top_n: int = 3,
    weight_by: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Weights decided at each close: the `top_n` best-scoring eligible ETFs.

    Equal weights of 1/top_n each (so fewer picks leave cash), or proportional to `weight_by`
    when given, summing to 1 across the picks. Apply with a one-day delay.
    """
    assert score.shape == eligible.shape, "score and eligible must align"
    masked = score.where(eligible)
    selected = (masked.rank(axis=1, ascending=False) <= top_n) & masked.notna()
    if weight_by is None:
        return selected.astype(float) / top_n
    raw = selected * weight_by
    return raw.div(raw.sum(axis=1), axis=0).fillna(0.0)

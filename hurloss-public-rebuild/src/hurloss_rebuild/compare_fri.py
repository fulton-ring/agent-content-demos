"""Our county multipliers next to FEMA's published Future Risk Index hurricane values.

Ratings use FEMA's fixed NRI bins (`scoring/ratings.py`), so a rating here means what FEMA's map
showed. FEMA's 0 ("no ARA point") is treated as 1, as FEMA's own ratings treat it.
"""

import pandas as pd

from hurloss_rebuild.conditioning import SCENARIOS
from hurloss_rebuild.scoring import ratings

RATING_RANK = {name: rank for rank, name in enumerate(ratings.RATINGS)}


def fema_hm(key: pd.DataFrame, scenario: str) -> pd.Series:
    published = key[f"HRCN_{scenario}_HM"]
    return published.where(published > 0, 1.0).clip(lower=1.0)


def by_county(ours: pd.DataFrame, key: pd.DataFrame, eal_now: pd.Series) -> pd.DataFrame:
    """Per county and scenario: FEMA's and our HM, projected loss and rating on both baselines."""
    rated = key[key["HRCN_EALR"].map(ratings.rating_name).notna() & (key["HRCN_EALT"] > 0)]
    bounds = ratings.thresholds(key)
    frames = []
    for scenario in SCENARIOS:
        name = scenario.name
        table = pd.DataFrame(index=rated.index)
        table["scenario"] = name
        table["state"] = rated["STATEABBRV"]
        table["county"] = rated["COUNTY"]
        table["eal_v1_19"] = rated["HRCN_EALT"]
        table["eal_v1_20"] = eal_now.reindex(rated.index)
        table["fema_hm"] = fema_hm(rated, name)
        for column in ("HM", "HM_LOW", "HM_HIGH"):
            table[f"our_{column.lower()}"] = (
                ours[f"{name}_{column}"].reindex(rated.index).fillna(1.0)
            )
        table["fema_pal"] = table["eal_v1_19"] * table["fema_hm"]
        table["our_pal_v1_19"] = table["eal_v1_19"] * table["our_hm"]
        table["our_pal_v1_20"] = table["eal_v1_20"] * table["our_hm"]
        table["fema_rating"] = ratings.rate(table["fema_pal"], bounds)
        table["our_rating_v1_19"] = ratings.rate(table["our_pal_v1_19"], bounds)
        table["our_rating_v1_20"] = ratings.rate(table["our_pal_v1_20"].fillna(0.0), bounds)
        table["rating_move"] = table["our_rating_v1_19"].map(RATING_RANK) - table[
            "fema_rating"
        ].map(RATING_RANK)
        table["fema_within_our_range"] = table["fema_hm"].between(
            table["our_hm_low"], table["our_hm_high"]
        )
        frames.append(table)
    return pd.concat(frames)


def summary(comparison: pd.DataFrame) -> pd.DataFrame:
    """Per scenario: levels, national projected loss, and how ratings move against FEMA's."""
    rows = []
    for scenario, part in comparison.groupby("scenario", sort=False):
        moves = part["rating_move"]
        rows.append(
            {
                "scenario": scenario,
                "counties": len(part),
                "fema_hm_median": part["fema_hm"].median(),
                "our_hm_median": part["our_hm"].median(),
                "our_hm_low_median": part["our_hm_low"].median(),
                "our_hm_high_median": part["our_hm_high"].median(),
                "fema_within_our_range": part["fema_within_our_range"].mean(),
                "eal_v1_19_total": part["eal_v1_19"].sum(),
                "fema_pal_total": part["fema_pal"].sum(),
                "our_pal_v1_19_total": part["our_pal_v1_19"].sum(),
                "our_pal_v1_20_total": part["our_pal_v1_20"].sum(),
                "rating_same": float((moves == 0).mean()),
                "rating_down_1": float((moves == -1).mean()),
                "rating_down_2_plus": float((moves <= -2).mean()),
                "rating_up": float((moves > 0).mean()),
            }
        )
    return pd.DataFrame(rows)


def storm_check(ours: pd.DataFrame, storm_ratio: pd.Series) -> pd.DataFrame:
    """2050 RCP/SSP 8.5: does STORM's GCM ensemble fall in our Knutson range, county by county?"""
    both = pd.DataFrame(
        {
            "storm_hm": storm_ratio.clip(lower=1.0),
            "our_hm": ours["MID_HIGHER_HM"],
            "low": ours["MID_HIGHER_HM_LOW"],
            "high": ours["MID_HIGHER_HM_HIGH"],
        }
    ).dropna()
    inside = both["storm_hm"].between(both["low"], both["high"])
    return pd.DataFrame(
        [
            {
                "counties": len(both),
                "storm_hm_median": both["storm_hm"].median(),
                "our_hm_median": both["our_hm"].median(),
                "storm_within_knutson_range": float(inside.mean()),
                "storm_above_range": float((both["storm_hm"] > both["high"]).mean()),
                "spearman": both["storm_hm"].corr(both["our_hm"], method="spearman"),
                "median_storm_over_ours": float((both["storm_hm"] / both["our_hm"]).median()),
            }
        ]
    )

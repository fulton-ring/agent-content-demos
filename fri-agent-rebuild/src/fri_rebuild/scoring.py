"""How a rebuilt county multiplier is compared with FEMA's: rating bins, the split, the metrics.

Shared by the rebuild notebook and the agent loop, which must score candidates the same way.
"""

import re

import numpy as np
import pandas as pd

SCENARIOS = ("MID_LOWER", "MID_HIGHER", "LATE_LOWER", "LATE_HIGHER")
RATINGS = ("Very Low", "Relatively Low", "Relatively Moderate", "Relatively High", "Very High")


def rating_name(label: object) -> str | None:
    """'Relatively Low (10.9K - 241K)' -> 'Relatively Low'; None for no rating."""
    name = re.sub(r"\s*\(.*\)$", "", label).strip() if isinstance(label, str) else None
    return name if name in RATINGS else None


def rating_thresholds(key: pd.DataFrame, hazard: str) -> np.ndarray:
    """Upper edge of each NRI rating: the largest EAL published in it (FRI Section 3.2)."""
    names = key[f"{hazard}_EALR"].map(rating_name)
    return np.array([key.loc[names == r, f"{hazard}_EALT"].max() for r in RATINGS[:-1]])


def rate(loss: pd.Series, thresholds: np.ndarray) -> pd.Series:
    """Sort projected annual losses into the fixed NRI rating bins."""
    index = np.minimum(np.searchsorted(thresholds, loss.to_numpy()), len(RATINGS) - 1)
    return pd.Series(np.array(RATINGS)[index], index=loss.index)


def split(fips: pd.Index) -> pd.Series:
    """'held_out' for every fourth state in FIPS order, starting with the second; else 'train'."""
    states = sorted(set(fips.str[:2]))
    held_out = set(states[1::4])
    return pd.Series(np.where(fips.str[:2].isin(held_out), "held_out", "train"), index=fips)


def score_column(key: pd.DataFrame, rebuilt: pd.Series, column: str) -> tuple[dict, pd.DataFrame]:
    """Metrics for one published column over the counties in `key`, and per-county detail."""
    hazard = column[:4]
    # A blank county counts as the floor value 1, so leaving hard counties blank can't help.
    both = pd.DataFrame(
        {"published": key[column], "rebuilt": rebuilt.reindex(key.index).astype(float).fillna(1)}
    ).dropna()
    both = both[both["published"] > 0]  # HM = 0 can't be scored in log terms
    eal, thresholds = key.loc[both.index, f"{hazard}_EALT"], rating_thresholds(key, hazard)
    rated = key.loc[both.index, f"{hazard}_EALR"].map(rating_name).notna()
    published_bin = rate(eal * both["published"], thresholds)[rated]
    rebuilt_bin = rate(eal * both["rebuilt"].clip(lower=1.0), thresholds)[rated]
    log_error = np.log(both["rebuilt"].clip(lower=1e-6)) - np.log(both["published"])
    metrics = {
        "column": column,
        "counties": len(both),
        "blank": int(rebuilt.reindex(both.index).isna().sum()),
        "same_bin": float((published_bin == rebuilt_bin).mean()),
        "pearson": float(both["published"].corr(both["rebuilt"])),
        "spearman": float(both["published"].corr(both["rebuilt"], method="spearman")),
        "log_mae": float(log_error.abs().mean()),
        "median_ratio": float(np.exp(log_error.median())),
    }
    detail = both.assign(
        log_error=log_error,
        state=key.loc[both.index, "STATEABBRV"],
        county=key.loc[both.index, "COUNTY"],
    )
    return metrics, detail


def score(
    key: pd.DataFrame, rebuilt: pd.DataFrame, subsets: tuple[str, ...] = ("train",)
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Metrics per published column and subset; `rebuilt` uses the published column names."""
    labels = split(key.index)
    rows, details = [], []
    for column in rebuilt.columns:
        for subset in subsets:
            metrics, detail = score_column(key[labels == subset], rebuilt[column], column)
            rows.append(metrics | {"subset": subset})
            details.append(detail.assign(column=column, subset=subset))
    return pd.DataFrame(rows), pd.concat(details)

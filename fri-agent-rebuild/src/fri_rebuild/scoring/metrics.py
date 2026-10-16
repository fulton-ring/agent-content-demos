"""Compare rebuilt county hazard multipliers with FEMA's published ones."""

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from fri_rebuild.scoring import answer_key, split


@dataclass(frozen=True)
class Score:
    column: str
    subset: str
    counties: int
    blank: int
    same_bin: float
    pearson: float
    spearman: float
    log_mae: float
    median_ratio: float


def hm_columns(table: pd.DataFrame, prefix: str) -> list[str]:
    """Published multiplier columns for one hazard variant, e.g. 'EXHT_N95' or 'DRGT'."""
    return [f"{prefix}_{scenario}_HM" for scenario in answer_key.SCENARIOS]


def score_column(
    key: pd.DataFrame, rebuilt: pd.Series, column: str, subset: str
) -> tuple[Score, pd.DataFrame]:
    hazard = column[:4]
    published = key[column]
    # A county the pipeline leaves blank counts as the floor value (1), so blanks can't help.
    filled = rebuilt.reindex(key.index).astype(float).fillna(1.0)
    both = pd.DataFrame({"published": published, "rebuilt": filled}).dropna()
    both = both[both["published"] > 0]
    thresholds = answer_key.rating_thresholds(key, hazard)
    eal = key.loc[both.index, f"{hazard}_EALT"]
    has_rating = key.loc[both.index, f"{hazard}_EALR"].map(answer_key.rating_name).notna()
    pub_bin = answer_key.rate(eal * both["published"], thresholds)[has_rating]
    our_bin = answer_key.rate(eal * both["rebuilt"].clip(lower=1.0), thresholds)[has_rating]
    log_error = np.log(both["rebuilt"].clip(lower=1e-6)) - np.log(both["published"])
    result = Score(
        column=column,
        subset=subset,
        counties=len(both),
        blank=int(rebuilt.reindex(both.index).isna().sum()),
        same_bin=float((pub_bin == our_bin).mean()) if len(pub_bin) else float("nan"),
        pearson=float(both["published"].corr(both["rebuilt"])),
        spearman=float(both["published"].corr(both["rebuilt"], method="spearman")),
        log_mae=float(log_error.abs().mean()),
        median_ratio=float(np.exp(log_error.median())),
    )
    detail = both.assign(
        log_error=log_error,
        published_bin=pub_bin,
        rebuilt_bin=our_bin,
        state=key.loc[both.index, "STATEABBRV"],
        county=key.loc[both.index, "COUNTY"],
    )
    return result, detail


def score(
    key: pd.DataFrame, rebuilt: pd.DataFrame, subsets: tuple[str, ...] = ("train",)
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Scores per published column and subset; `rebuilt` has the published column names."""
    labels = split.label(key)
    rows, details = [], []
    for column in rebuilt.columns:
        for subset in subsets:
            part = key[labels == subset]
            result, detail = score_column(part, rebuilt[column], column, subset)
            rows.append(asdict(result))
            details.append(detail.assign(column=column, subset=subset))
    return pd.DataFrame(rows), pd.concat(details)

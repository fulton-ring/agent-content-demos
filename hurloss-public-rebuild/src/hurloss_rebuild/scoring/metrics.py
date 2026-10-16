"""Compare rebuilt county hurricane multipliers with FEMA's published ones (#15's metrics)."""

from dataclasses import asdict, dataclass

import numpy as np
import pandas as pd

from hurloss_rebuild.scoring import ratings, split

SUBSETS = ("train", "held_out")
COVERED_SUFFIX = "_covered"


@dataclass(frozen=True)
class Score:
    method: str
    scenario: str
    subset: str
    counties: int
    blank: int
    same_bin: float
    pearson: float
    spearman: float
    log_mae: float
    median_ratio: float


def score_column(
    key: pd.DataFrame, rebuilt: pd.Series, published: pd.Series, labels: tuple[str, str, str]
) -> tuple[Score, pd.DataFrame]:
    """Score one rebuilt multiplier column on the counties of `key`.

    A county the rebuild leaves blank counts as HM = 1, so blanks can't help a score. Counties
    FEMA published as 0 (no ARA data) can't be scored in log terms and are left out.
    """
    method, scenario, subset = labels
    filled = rebuilt.reindex(key.index).astype(float).fillna(1.0)
    both = pd.DataFrame({"published": published.reindex(key.index), "rebuilt": filled}).dropna()
    both = both[both["published"] > 0]
    eal = key.loc[both.index, "HRCN_EALT"]
    rated = key.loc[both.index, "HRCN_EALR"].map(ratings.rating_name).notna()
    bounds = ratings.thresholds(key)
    published_bin = ratings.rate(eal * both["published"], bounds)[rated]
    rebuilt_bin = ratings.rate(eal * both["rebuilt"].clip(lower=1.0), bounds)[rated]
    log_error = np.log(both["rebuilt"].clip(lower=1e-6)) - np.log(both["published"])
    result = Score(
        method=method,
        scenario=scenario,
        subset=subset,
        counties=len(both),
        blank=int(rebuilt.reindex(both.index).isna().sum()),
        same_bin=float((published_bin == rebuilt_bin).mean()) if len(published_bin) else np.nan,
        pearson=float(both["published"].corr(both["rebuilt"])),
        spearman=float(both["published"].corr(both["rebuilt"], method="spearman")),
        log_mae=float(log_error.abs().mean()),
        median_ratio=float(np.exp(log_error.median())),
    )
    detail = both.assign(
        log_error=log_error,
        published_bin=published_bin,
        rebuilt_bin=rebuilt_bin,
        method=method,
        scenario=scenario,
        subset=subset,
    )
    return result, detail


def score(
    key: pd.DataFrame, rebuilt: pd.DataFrame, method: str
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Scores per scenario and subset; `rebuilt` has one column per FEMA scenario name.

    Each subset is scored twice: on every county FEMA published, and ("_covered") only on
    counties the rebuild gives a value, which separates coverage from the climate signal.
    """
    subset_of = split.label(key.index)
    rows, details = [], []
    for scenario in rebuilt.columns:
        published = key[f"HRCN_{scenario}_HM"]
        covered = rebuilt[scenario].reindex(key.index).notna()
        for subset in SUBSETS:
            for name, mask in ((subset, True), (subset + COVERED_SUFFIX, covered)):
                part = key[(subset_of == subset) & mask]
                result, detail = score_column(
                    part, rebuilt[scenario], published, (method, scenario, name)
                )
                rows.append(asdict(result))
                details.append(detail)
    return pd.DataFrame(rows), pd.concat(details)

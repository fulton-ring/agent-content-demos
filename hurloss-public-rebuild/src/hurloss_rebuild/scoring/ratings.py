"""FEMA's fixed NRI rating bins (FRI technical document, Sec. 3.2), as reproduced in #15."""

import re

import numpy as np
import pandas as pd

RATINGS = ("Very Low", "Relatively Low", "Relatively Moderate", "Relatively High", "Very High")


def rating_name(label: object) -> str | None:
    """'Relatively Low (625K - 7.36M)' -> 'Relatively Low'; None for no rating."""
    if not isinstance(label, str):
        return None
    name = re.sub(r"\s*\(.*\)$", "", label).strip()
    return name if name in RATINGS else None


def thresholds(key: pd.DataFrame) -> np.ndarray:
    """Upper bound of each hurricane EAL rating: the largest EAL observed in that rating."""
    names = key["HRCN_EALR"].map(rating_name)
    eal = key["HRCN_EALT"]
    bounds = np.array([eal[names == rating].max() for rating in RATINGS[:-1]])
    if not np.all(np.diff(bounds) > 0):
        raise ValueError(f"rating bounds are not increasing: {bounds}")
    return bounds


def rate(values: pd.Series, bounds: np.ndarray) -> pd.Series:
    """Sort projected annual losses into the fixed NRI bins."""
    index = np.searchsorted(bounds, values.to_numpy(), side="left")
    return pd.Series(np.array(RATINGS)[np.minimum(index, len(RATINGS) - 1)], index=values.index)

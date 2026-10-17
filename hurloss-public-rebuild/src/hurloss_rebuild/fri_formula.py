"""FEMA's Future Risk Index hurricane formula (technical document, Dec 2024, Sec. 7.2-7.3).

- Each ARA point has an annual frequency for Category 1 to 5 hurricane wind.
- Eq. 11: Intensity = F1*1 + F2*2 + F3*4 + F4*8 + F5*16.
- Sec. 7.2: a county's frequencies are the mean over points within 1 km of it.
- Eq. 12: HM = max(1, projected intensity / historical intensity).

This module is pure: arrays in, arrays out.
"""

import numpy as np
import pandas as pd
from scipy import sparse

# Saffir-Simpson lower bounds as 1-minute sustained wind at 10 m, m/s (64, 83, 96, 113, 137 kt).
CATEGORY_FLOOR_MS = np.array([32.92, 42.70, 49.39, 58.13, 70.48])
CATEGORY_WEIGHT = np.array([1.0, 2.0, 4.0, 8.0, 16.0])


def category_frequencies(
    wind: sparse.csr_matrix, frequency: np.ndarray, banded: bool = False
) -> np.ndarray:
    """Annual frequency of Cat 1-5 wind at each point (points x 5).

    `wind` is events x points (m/s) and `frequency` is each event's annual rate. With
    `banded=False` a column counts events reaching at least that category; with `banded=True`
    it counts events whose peak wind at the point falls in that category.
    """
    if wind.shape[0] != frequency.shape[0]:
        raise ValueError("wind rows and event frequencies differ in length")
    if np.any(frequency < 0):
        raise ValueError("negative event frequency")
    columns = []
    for floor in CATEGORY_FLOOR_MS:
        reached = (wind >= floor).astype(float)
        columns.append(np.asarray(reached.T @ frequency).ravel())
    exceeding = np.stack(columns, axis=1)
    if not banded:
        return exceeding
    above = np.concatenate([exceeding[:, 1:], np.zeros((exceeding.shape[0], 1))], axis=1)
    return exceeding - above


def intensity(frequencies: np.ndarray) -> np.ndarray:
    """Eq. 11, for each row of Cat 1-5 frequencies."""
    if frequencies.shape[-1] != len(CATEGORY_WEIGHT):
        raise ValueError("expected five category columns")
    return frequencies @ CATEGORY_WEIGHT


def county_mean(values: np.ndarray, point_county: pd.Series) -> pd.Series:
    """Mean of point values per county; `point_county` maps point index -> county FIPS.

    A point may appear under several counties (the 1 km buffer), so the mapping is a Series
    whose index is the point position and whose values are county FIPS codes.
    """
    picked = pd.Series(values[point_county.index.to_numpy()], index=point_county.to_numpy())
    return picked.groupby(level=0).mean()


def hazard_multiplier(projected: pd.Series, historical: pd.Series) -> pd.Series:
    """Eq. 12: max(1, projected / historical); blank where today's intensity is zero."""
    ratio = projected.reindex(historical.index) / historical.where(historical > 0)
    return ratio.clip(lower=1.0)

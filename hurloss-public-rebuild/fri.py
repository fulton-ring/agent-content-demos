"""FEMA's Future Risk Index hurricane formula, Knutson scaling and NRI rating bins.

These are the parts of `notebook.py` that would mislead if they broke, so they live here where
`tests/` can check them. Sources: FRI technical document (FEMA, Dec 2024), Sec. 3.2 and 7.1-7.3.
"""

import re
from dataclasses import dataclass, replace

import numpy as np
import pandas as pd
from climada.hazard.tc_clim_change import get_knutson_scaling_factor
from scipy import sparse

# Saffir-Simpson lower bounds as 1-minute sustained wind at 10 m, m/s (64, 83, 96, 113, 137 kt).
CATEGORY_FLOOR_MS = np.array([32.92, 42.70, 49.39, 58.13, 70.48])
CATEGORY_WEIGHT = np.array([1.0, 2.0, 4.0, 8.0, 16.0])
# FEMA's scenarios: lower and higher warming are RCP 4.5 and 8.5; mid and late are 2050 and 2100.
SCENARIOS = {
    "MID_LOWER": ("4.5", 2050),
    "MID_HIGHER": ("8.5", 2050),
    "LATE_LOWER": ("4.5", 2100),
    "LATE_HIGHER": ("8.5", 2100),
}
# Knutson et al. (2020) percentiles of model spread, paired across variables as CLIMADA pairs them.
PERCENTILES = ("5/10", "25", "50", "75", "90/95")
RATINGS = ("Very Low", "Relatively Low", "Relatively Moderate", "Relatively High", "Very High")


@dataclass(frozen=True)
class Events:
    """Peak wind per event and point, with each event's annual rate."""

    wind: sparse.csr_matrix  # events x points, m/s
    frequency: np.ndarray  # events per year
    category: np.ndarray  # Saffir-Simpson category of the track's lifetime peak
    basin: np.ndarray  # where each track starts; Knutson's changes differ by basin
    years: tuple[int, int]  # the climate the catalogue represents


def county_intensity(events: Events, point_county: pd.Series) -> pd.Series:
    """Eq. 11 per county: F1 + 2 F2 + 4 F3 + 8 F4 + 16 F5, from the mean over its points.

    F_k is the annual frequency of wind reaching at least Category k. `point_county` maps point
    position to county; a point can sit under several counties through FEMA's 1 km buffer.
    """
    if events.wind.shape[0] != events.frequency.shape[0]:
        raise ValueError("wind rows and event frequencies differ in length")
    if np.any(events.frequency < 0):
        raise ValueError("negative event frequency")
    reached = [(events.wind >= floor).astype(float) for floor in CATEGORY_FLOOR_MS]
    frequencies = np.stack([np.asarray(r.T @ events.frequency).ravel() for r in reached], axis=1)
    return county_mean(frequencies @ CATEGORY_WEIGHT, point_county)


def county_mean(values: np.ndarray, point_county: pd.Series) -> pd.Series:
    """Mean of point values per county (FRI Sec. 7.2); `point_county` maps point -> county."""
    picked = values[point_county.index.to_numpy()]
    return pd.Series(picked, index=point_county.to_numpy()).groupby(level=0).mean()


def ratio(projected: pd.Series, today: pd.Series) -> pd.Series:
    """Projected over today's intensity, blank where today's is zero. Eq. 12 floors this at 1."""
    return projected.reindex(today.index) / today.where(today > 0)


def knutson_percent(
    variable: str, scenario: str, basin: str, years: tuple[int, int], percentile: str = "50"
) -> float:
    """Knutson/Jewson % change in `variable` for one basin and scenario, against `years`."""
    if percentile not in PERCENTILES:
        raise ValueError(f"unknown Knutson percentile: {percentile}")
    rcp, year = SCENARIOS[scenario]
    table = get_knutson_scaling_factor(
        variable=variable, percentile=percentile, basin=basin, baseline=years, yearly_steps=5
    )
    return float(table.loc[year, rcp])


def frequency_only(events: Events, scenario: str, percentile: str = "50") -> Events:
    """Jewson's recommended use of Knutson: rescale event rates by peak category, winds unchanged.

    Cat 4-5 events take Knutson's Cat 4-5 frequency change; the rest take whatever keeps the
    all-storm change right (CLIMADA's `apply_climate_scenario_knu` arithmetic).
    """
    frequency = events.frequency.copy()
    strong = np.isin(events.category, [4, 5])
    for basin in np.unique(events.basin):
        rows = events.basin == basin
        all_change = knutson_percent("cat05", scenario, str(basin), events.years, percentile) / 100
        strong_change = (
            knutson_percent("cat45", scenario, str(basin), events.years, percentile) / 100
        )
        weak_total = frequency[rows & ~strong].sum()
        strong_total = frequency[rows & strong].sum()
        if weak_total <= 0:
            raise ValueError(f"no Cat 0-3 events in basin {basin}")
        weak_change = (all_change * (weak_total + strong_total) - strong_change * strong_total) / (
            weak_total
        )
        frequency[rows & strong] *= 1 + strong_change
        frequency[rows & ~strong] *= 1 + weak_change
    if np.any(frequency < 0):
        raise ValueError("climate scaling made a frequency negative")
    return replace(events, frequency=frequency)


def rating_name(label: object) -> str | None:
    """'Relatively Low (625K - 7.36M)' -> 'Relatively Low'; None for no rating."""
    if not isinstance(label, str):
        return None
    name = re.sub(r"\s*\(.*\)$", "", label).strip()
    return name if name in RATINGS else None


def rating_bounds(key: pd.DataFrame) -> np.ndarray:
    """Upper edge of each NRI hurricane EAL rating: the largest EAL FEMA put in that rating."""
    names = key["HRCN_EALR"].map(rating_name)
    bounds = np.array([key.loc[names == r, "HRCN_EALT"].max() for r in RATINGS[:-1]])
    if not np.all(np.diff(bounds) > 0):
        raise ValueError(f"rating bounds are not increasing: {bounds}")
    return bounds


def rate(values: pd.Series, bounds: np.ndarray) -> pd.Series:
    """Sort annual losses into FEMA's fixed NRI rating bins."""
    index = np.searchsorted(bounds, values.to_numpy(), side="left")
    return pd.Series(np.array(RATINGS)[np.minimum(index, len(RATINGS) - 1)], index=values.index)

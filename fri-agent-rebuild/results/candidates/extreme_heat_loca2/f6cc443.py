"""Extreme heat hazard multipliers from LOCA2 (MPI-ESM1-2-HR, 1/16 degree).

FRI Technical Documentation, Section 6: an extreme heat event-day is a day whose minimum
temperature exceeds the historical (1976-2005) 95th or 99th percentile and, for LOCA2 (which has
no humidity), exceeds 296.22 K. HM = max(1, projected event-days / historical days over the nth
percentile), computed per cell then averaged per county.
"""

import numpy as np
import pandas as pd

from fri_rebuild import inputs

FLOOR_C = 296.22 - 273.15
PERCENTILES = {"L95": 95, "L99": 99}


def percentile_bins(counts: np.ndarray, percentile: float) -> np.ndarray:
    """Index of the value bin holding each cell's percentile (missing-data row excluded)."""
    values = counts[:-1].astype(np.int64)
    cumulative = np.cumsum(values, axis=0)
    target = cumulative[-1] * percentile / 100
    return np.argmax(cumulative >= target, axis=0)


def days_above(counts: np.ndarray, edges: np.ndarray, first_bin: np.ndarray) -> np.ndarray:
    """Days per cell in value bins strictly above `first_bin`."""
    values = counts[:-1].astype(np.int64)
    above = np.arange(values.shape[0])[:, None] > first_bin[None, :]
    days = (values * above).sum(axis=0).astype(float)
    valid = counts[:-1].sum(axis=0) > 0
    return np.where(valid, days, np.nan)


def county_mean(values: np.ndarray) -> np.ndarray:
    weights, _ = inputs.loca2_county_weights()
    valid = np.isfinite(values)
    totals = weights @ np.where(valid, values, 0.0)
    covered = weights @ valid.astype(float)
    with np.errstate(invalid="ignore", divide="ignore"):
        return totals / covered


def hazard_multipliers() -> pd.DataFrame:
    """Columns EXHT_L95_<period>_<warming>_HM and EXHT_L99_..., indexed by county FIPS."""
    _, fips = inputs.loca2_county_weights()
    edges, history = inputs.loca2_histogram("historical", "historical")
    floor_bin = np.searchsorted(edges, FLOOR_C, side="right") - 1
    result = {}
    for name, percentile in PERCENTILES.items():
        threshold_bin = percentile_bins(history, percentile)
        past = days_above(history, edges, threshold_bin)
        event_bin = np.maximum(threshold_bin, floor_bin)
        for warming, ssp in inputs.SSP.items():
            for period in ("MID", "LATE"):
                _, counts = inputs.loca2_histogram(ssp, period)
                future = days_above(counts, edges, event_bin)
                with np.errstate(divide="ignore", invalid="ignore"):
                    cell_ratio = np.where(past > 0, future / past, np.nan)
                ratio = county_mean(cell_ratio)
                result[f"EXHT_{name}_{period}_{warming}_HM"] = np.maximum(1.0, ratio)
    return pd.DataFrame(result, index=fips)

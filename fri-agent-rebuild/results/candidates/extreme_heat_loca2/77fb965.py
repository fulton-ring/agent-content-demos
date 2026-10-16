"""Extreme heat hazard multipliers from LOCA2 (MPI-ESM1-2-HR, 1/16 degree).

FRI Technical Documentation, Section 6: an extreme heat event-day is a day whose minimum
temperature exceeds the historical (1976-2005) 95th or 99th percentile and, for LOCA2 (which has
no humidity), exceeds 296.22 K. HM = max(1, projected event-days / historical days over the nth
percentile), per county.

Percentile and floor positions are interpolated linearly inside their 0.1 C bins.
"""

import numpy as np
import pandas as pd

from fri_rebuild import inputs

FLOOR_C = 296.22 - 273.15
PERCENTILES = {"L95": 95, "L99": 99}


def percentile_position(counts: np.ndarray, percentile: float):
    """Bin index and fractional position within the bin of each cell's percentile."""
    values = counts[:-1].astype(np.int64)
    cumulative = np.cumsum(values, axis=0)
    target = cumulative[-1] * percentile / 100
    bins = np.argmax(cumulative >= target, axis=0)
    cols = np.arange(values.shape[1])
    in_bin = values[bins, cols]
    before = cumulative[bins, cols] - in_bin
    frac = np.where(in_bin > 0, (target - before) / np.maximum(in_bin, 1), 1.0)
    return bins, np.clip(frac, 0.0, 1.0)


def days_above(counts: np.ndarray, bins: np.ndarray, frac: np.ndarray) -> np.ndarray:
    """Days per cell above the position (bin + frac), partial bin counted proportionally."""
    values = counts[:-1].astype(np.int64)
    cols = np.arange(values.shape[1])
    above = np.arange(values.shape[0])[:, None] > bins[None, :]
    days = (values * above).sum(axis=0).astype(float)
    days = days + values[bins, cols] * (1.0 - frac)
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
    floor_bin = int(np.searchsorted(edges, FLOOR_C, side="right") - 1)
    if floor_bin + 1 < len(edges):
        width = edges[floor_bin + 1] - edges[floor_bin]
    else:
        width = 0.1
    floor_frac = float(np.clip((FLOOR_C - edges[floor_bin]) / width, 0.0, 1.0))
    result = {}
    for name, percentile in PERCENTILES.items():
        tb, tf = percentile_position(history, percentile)
        past = county_mean(days_above(history, tb, tf))
        use_pct = (tb + tf) >= (floor_bin + floor_frac)
        eb = np.where(use_pct, tb, floor_bin)
        ef = np.where(use_pct, tf, floor_frac)
        for warming, ssp in inputs.SSP.items():
            for period in ("MID", "LATE"):
                _, counts = inputs.loca2_histogram(ssp, period)
                future = county_mean(days_above(counts, eb, ef))
                with np.errstate(divide="ignore", invalid="ignore"):
                    ratio = np.where(past > 0, future / past, np.nan)
                result[f"EXHT_{name}_{period}_{warming}_HM"] = np.maximum(1.0, ratio)
    return pd.DataFrame(result, index=fips)

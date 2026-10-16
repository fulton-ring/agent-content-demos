"""Extreme heat hazard multipliers from LOCA2 (MPI-ESM1-2-HR, 1/16 degree).

FRI Technical Documentation, Section 6: an extreme heat event-day is a day whose minimum
temperature exceeds the historical (1976-2005) 95th or 99th percentile and, for LOCA2 (which has
no humidity), exceeds 296.22 K. HM = max(1, projected event-days / historical days over the nth
percentile), per county.

Percentiles and the floor are located with linear interpolation inside histogram bins.
"""

import numpy as np
import pandas as pd

from fri_rebuild import inputs

FLOOR_C = 296.22 - 273.15
PERCENTILES = {"L95": 95, "L99": 99}


def bin_bounds(edges: np.ndarray, nrows: int):
    """Lower and upper bound of each value row (open-ended rows have infinite bounds)."""
    edges = np.asarray(edges, dtype=float)
    if len(edges) == nrows - 1:
        lo = np.concatenate([[-np.inf], edges])
        hi = np.concatenate([edges, [np.inf]])
    elif len(edges) == nrows:
        lo = edges.copy()
        hi = np.concatenate([edges[1:], [np.inf]])
    else:
        raise ValueError(f"unexpected edges length {len(edges)} for {nrows} rows")
    return lo, hi


def percentile_value(values: np.ndarray, lo, hi, percentile: float) -> np.ndarray:
    """Per-cell percentile value, linearly interpolated within its bin."""
    cumulative = np.cumsum(values, axis=0)
    total = cumulative[-1]
    target = total * percentile / 100
    tbin = np.argmax(cumulative >= target[None, :], axis=0)
    idx = np.arange(values.shape[1])
    cnt = values[tbin, idx]
    before = cumulative[tbin, idx] - cnt
    with np.errstate(invalid="ignore", divide="ignore"):
        pos = np.where(cnt > 0, (target - before) / cnt, 1.0)
    pos = np.clip(pos, 0.0, 1.0)
    lo_f = np.where(np.isfinite(lo), lo, hi)
    width = np.where(np.isfinite(lo) & np.isfinite(hi), hi - lo, 0.0)
    return lo_f[tbin] + pos * width[tbin]


def days_above_value(values: np.ndarray, lo, hi, threshold: np.ndarray) -> np.ndarray:
    """Days per cell above a continuous threshold, fractional within the threshold's bin."""
    nrows, ncells = values.shape
    row = np.searchsorted(lo, threshold, side="right") - 1
    row = np.clip(row, 0, nrows - 1)
    idx = np.arange(ncells)
    width = np.where(np.isfinite(lo) & np.isfinite(hi), hi - lo, 0.0)
    w = width[row]
    with np.errstate(invalid="ignore", divide="ignore"):
        frac = np.where(w > 0, (hi[row] - threshold) / w, 0.0)
    frac = np.clip(frac, 0.0, 1.0)
    above = np.arange(nrows)[:, None] > row[None, :]
    days = (values * above).sum(axis=0) + values[row, idx] * frac
    valid = values.sum(axis=0) > 0
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
    hist_values = history[:-1].astype(float)
    lo, hi = bin_bounds(edges, hist_values.shape[0])
    result = {}
    for name, percentile in PERCENTILES.items():
        threshold = percentile_value(hist_values, lo, hi, percentile)
        past = county_mean(days_above_value(hist_values, lo, hi, threshold))
        event = np.maximum(threshold, FLOOR_C)
        for warming, ssp in inputs.SSP.items():
            for period in ("MID", "LATE"):
                _, counts = inputs.loca2_histogram(ssp, period)
                future = county_mean(days_above_value(counts[:-1].astype(float), lo, hi, event))
                with np.errstate(divide="ignore", invalid="ignore"):
                    ratio = np.where(past > 0, future / past, np.nan)
                result[f"EXHT_{name}_{period}_{warming}_HM"] = np.maximum(1.0, ratio)
    return pd.DataFrame(result, index=fips)
